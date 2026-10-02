"""Детский режим: помечает в work/tagged.json картинки, которые детям не показываем, —
обнажённая натура и эротика, кровь и смерть, оружие, алкоголь, курение, жуть.

Обнажённую натуру ловят два сигнала: концепты фильтра Stable Diffusion
(CompVis/stable-diffusion-safety-checker, откалиброванные пороги, то же пространство CLIP ViT-L/14)
и сравнение с описаниями «обнажённого» против обычных сюжетов. Фильтр SD путает с телом лепестки
и животных — его срабатывание засчитываем, только если на картинке есть человек.
Остальные причины — запас: насколько картинка ближе к «взрослому» описанию, чем к лучшему обычному.
Пороги подобраны по листам проверки (--review): берём только верх, где попадания верные.

Пометка пишется полем "adult": "<причина>" и в ленте становится списком feed/tags/adult.json,
по которому приложение в детском режиме (он включён по умолчанию) прячет картинки.
Признаки картинок кэшируются в work/clip_feats.npz, концепты SD — в work/safety_concepts.pt.
  python tools/mark_adult.py            — разметить и записать tagged.json
  python tools/mark_adult.py --review   — листы помеченного и «чуть-чуть не дотянувших» (work/adult_review_*.jpg)
Лишняя спрятанная картинка лучше пропущенной: пороги сдвинуты в сторону осторожности."""
import json, os, sys

import numpy as np
import torch
import open_clip
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tag_items import thumb_path, WORK  # noqa: E402

FEATS = os.path.join(WORK, "clip_feats.npz")
# причина → описания. Несколько формулировок на причину: картины и фото CLIP видит по-разному
ADULT = {
    "nudity": ["a painting of a nude woman", "a painting of a naked man", "a photo of a naked person",
               "bare breasts", "an erotic picture", "a person in lingerie", "a sexy pose in underwear",
               "nude bathers", "a nude figure lying on a bed"],
    "gore": ["blood and a wounded body", "a dead body", "a corpse", "a severed head",
             "a bloody battle with killing", "an execution", "a crucified body"],
    "weapon": ["a person holding a gun", "a rifle", "a pistol", "soldiers with weapons"],
    "alcohol": ["bottles of alcohol", "people drinking beer", "glasses of wine and liquor", "a bar with alcohol"],
    "smoking": ["a person smoking a cigarette", "smoking a pipe", "cigars and smoke"],
    "horror": ["a scary skull", "a frightening monster", "a demon from hell", "a horror scene"],
}
NEUTRAL = [
    "a landscape", "a portrait of a person", "a portrait of a woman in a dress", "a portrait of a man in a suit",
    "people walking on a street", "a family", "children playing", "flowers", "a still life with fruit",
    "animals", "a dog", "a cat", "birds", "the sea", "mountains", "a city", "a building", "a church",
    "food on a table", "a garden", "a river", "a forest", "a beach with people", "a boat", "a horse",
    "a religious painting of saints", "an angel", "a mythological scene", "a dancer in a dress",
    "a kitchen", "a market", "a cup of coffee", "a glass of juice", "a sculpture", "an abstract pattern",
]
# запас «взрослое минус лучшее обычное», выше которого прячем
MARGIN = {"nudity": 0.030, "gore": 0.035, "weapon": 0.025, "alcohol": 0.038, "smoking": 0.025, "horror": 0.030}
PERSON = ["a photo of a person", "a painting of a person", "a human body", "people"]
NO_PERSON = ["a flower", "an animal", "a bird", "a landscape without people", "an object", "food",
             "a building", "outer space", "a pattern", "fruit"]
SD_CONCEPTS = os.path.join(WORK, "safety_concepts.pt")
SD_STRONG = 0.03   # такой балл SD засчитываем и без человека на картинке
# в старой живописи обнажённой натуры много, а фото с Pexels и так прошли их модерацию —
# для картин пороги строже: лучше спрятать лишний музейный портрет, чем пропустить «Венеру»
ART_SD = -0.01
ART_NUDITY = 0.015


def model_and_feats(keys):
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai", device=dev)
    model.eval()
    tok = open_clip.get_tokenizer("ViT-L-14")
    cache = {}
    if os.path.exists(FEATS):
        z = np.load(FEATS, allow_pickle=True)
        cache = dict(zip(z["keys"].tolist(), z["feats"]))
    todo = [k for k in keys if k not in cache and os.path.exists(thumb_path(k))]
    print("признаки: в кэше %d, считать %d" % (len(cache), len(todo)), flush=True)
    for i in range(0, len(todo), 64):
        ks, imgs = [], []
        for k in todo[i:i + 64]:
            try:
                imgs.append(preprocess(Image.open(thumb_path(k)).convert("RGB")))
                ks.append(k)
            except Exception:  # noqa: BLE001
                pass
        if not imgs:
            continue
        with torch.no_grad():
            f = model.encode_image(torch.stack(imgs).to(dev))
            f = torch.nn.functional.normalize(f.float(), dim=-1).cpu().numpy()
        for k, v in zip(ks, f):
            cache[k] = v
        if i % 2048 == 0:
            print("  clip", i, flush=True)
    if todo:
        np.savez(FEATS, keys=np.array(list(cache.keys()), dtype=object), feats=np.stack(list(cache.values())))

    def enc(texts):
        with torch.no_grad():
            t = model.encode_text(tok(texts).to(dev))
            return torch.nn.functional.normalize(t.float(), dim=-1).cpu().numpy()
    return cache, enc


def sd_scores(F):
    """Балл фильтра Stable Diffusion: >0 — сработал (как в самом фильтре, с поправкой «особых» концептов)."""
    if not os.path.exists(SD_CONCEPTS):
        import truststore
        truststore.inject_into_ssl()
        from huggingface_hub import hf_hub_download
        sd = torch.load(hf_hub_download("CompVis/stable-diffusion-safety-checker", "pytorch_model.bin"),
                        map_location="cpu", weights_only=True)
        torch.save({k: v for k, v in sd.items() if "concept" in k or "special" in k}, SD_CONCEPTS)
    c = torch.load(SD_CONCEPTS)
    ce = torch.nn.functional.normalize(c["concept_embeds"].float(), dim=-1).numpy()
    se = torch.nn.functional.normalize(c["special_care_embeds"].float(), dim=-1).numpy()
    special = (F @ se.T - c["special_care_embeds_weights"].numpy() > 0).any(1)
    return (F @ ce.T - c["concept_embeds_weights"].numpy() + np.where(special, 0.01, 0.0)[:, None]).max(1)


def flag(keys, cache, enc, sections):
    """keys → причина или "" и баллы для листов проверки."""
    F = np.stack([cache[k] for k in keys])
    neutral = (F @ enc(NEUTRAL).T).max(1)
    margin = {r: (F @ enc(p).T).max(1) - neutral for r, p in ADULT.items()}
    person = (F @ enc(PERSON).T).max(1) - (F @ enc(NO_PERSON).T).max(1)
    sd = sd_scores(F)
    reasons = []
    for n in range(len(keys)):
        art = sections[n] == "art"
        hits = [(margin[r][n] / MARGIN[r], r) for r in ADULT if margin[r][n] >= MARGIN[r]]
        if art and margin["nudity"][n] >= ART_NUDITY:
            hits.append((1.0, "nudity"))
        # в живописи цветов и зверей мало, а тёмную картину проверка «есть ли человек» не узнаёт
        sd_hit = sd[n] > 0.0 if art else (sd[n] > 0.0 and person[n] > -0.02)
        if sd[n] > SD_STRONG or sd_hit or (art and sd[n] > ART_SD and person[n] > 0.0):
            hits.append((max(1.0, sd[n] / SD_STRONG), "nudity"))
        reasons.append(max(hits)[1] if hits else "")
    return reasons, margin, sd, person


def review(keys, reasons, margin, sd):
    """Листы: что спрятано по каждой причине и что чуть-чуть не дотянуло до порога."""
    def sheet(name, idx, label):
        if not idx:
            return
        cols, cw = 10, 150
        rows = (len(idx) + cols - 1) // cols
        img = Image.new("RGB", (cols * cw, rows * (cw + 16)), (255, 255, 255))
        d = ImageDraw.Draw(img)
        for n, i in enumerate(idx):
            try:
                im = Image.open(thumb_path(keys[i])).convert("RGB")
            except Exception:  # noqa: BLE001
                continue
            im.thumbnail((cw - 4, cw - 4))
            x, y = (n % cols) * cw, (n // cols) * (cw + 16)
            img.paste(im, (x + 2, y + 16))
            d.text((x + 3, y + 2), label(i), fill=(200, 0, 0) if reasons[i] else (0, 0, 200))
        img.save(os.path.join(WORK, "adult_review_%s.jpg" % name), quality=82)
    rnd = np.random.default_rng(1)
    for r in ADULT:
        idx = [i for i, x in enumerate(reasons) if x == r]
        sample = sorted(rnd.choice(idx, size=min(60, len(idx)), replace=False).tolist()) if idx else []
        sheet(r, sample, lambda i, r=r: "%s %.3f sd%.2f" % (r[:4], margin[r][i], sd[i]))
        print("%-8s спрятано %d" % (r, len(idx)))
    miss = [i for i in np.argsort(-margin["nudity"]) if not reasons[i]][:40]
    miss += [i for i in np.argsort(-sd) if not reasons[i]][:30]
    sheet("near_miss", miss, lambda i: "n%.3f sd%.2f" % (margin["nudity"][i], sd[i]))


def main():
    path = os.path.join(WORK, "tagged.json")
    items = json.load(open(path, encoding="utf-8"))
    keys = list(items)
    cache, enc = model_and_feats(keys)
    keys = [k for k in keys if k in cache]
    reasons, margin, sd, person = flag(keys, cache, enc, [items[k]["section"] for k in keys])
    if "--review" in sys.argv:
        review(keys, reasons, margin, sd)
        return
    for k in items:
        items[k].pop("adult", None)
    for k, r in zip(keys, reasons):
        if r:
            items[k]["adult"] = r
    json.dump(items, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    marked = Counter(v["adult"] for v in items.values() if "adult" in v)
    print("помечено %d из %d:" % (sum(marked.values()), len(items)), dict(marked))


if __name__ == "__main__":
    main()
