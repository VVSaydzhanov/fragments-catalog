"""Разметка каталога: превью → цвет/сложность (numpy) + теги настроения/сюжета (CLIP, локально на GPU)
+ отсев брака. Пишет work/tagged.json. Запуск: tools/.venv/Scripts/python tools/tag_items.py"""
import hashlib, io, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
import open_clip
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "work")
THUMBS = os.path.join(WORK, "thumbs")
os.makedirs(THUMBS, exist_ok=True)
# artic.edu стоит за Cloudflare и без их заголовка отдаёт 403
UA = {"User-Agent": "FragmentsPuzzle/0.1 (catalog build; github.com/VVSaydzhanov/fragments-catalog)",
      "AIC-User-Agent": "FragmentsPuzzle (github.com/VVSaydzhanov/fragments-catalog)"}

# --- словарь тегов: id → (группа, промпты CLIP, доля «сверху», которую допускаем) ---------------
CLIP_TAGS = {
    # время года
    "spring": ("season", ["a {} of spring with blossoming trees and fresh green leaves"], 0.10),
    "summer": ("season", ["a {} of a lush green summer day"], 0.14),
    "autumn": ("season", ["a {} of autumn with golden and red fall foliage"], 0.12),
    "winter": ("season", ["a {} of winter with snow and ice"], 0.12),
    # время суток
    "morning": ("time", ["a {} of an early morning with soft sunrise light"], 0.08),
    "day": ("time", ["a {} in bright daylight under a blue sky"], 0.18),
    "sunset": ("time", ["a {} of a sunset with an orange sky"], 0.08),
    "evening": ("time", ["a {} of a quiet evening at dusk, twilight"], 0.08),
    "night": ("time", ["a {} at night, dark night sky"], 0.08),
    # погода и настроение
    "sunny": ("mood", ["a sunny {} full of warm sunlight"], 0.14),
    "fog": ("mood", ["a misty foggy {}"], 0.06),
    "rain": ("mood", ["a rainy {} with wet streets and rain"], 0.05),
    "snow": ("mood", ["a {} with falling snow and snowy ground"], 0.10),
    "storm": ("mood", ["a stormy {} with dramatic clouds and rough waves"], 0.05),
    "cozy": ("mood", ["a cozy warm homely {}"], 0.08),
    "calm": ("mood", ["a calm peaceful serene {}"], 0.14),
    # сюжет
    "landscape": ("subject", ["a landscape {} of nature scenery"], 0.28),
    "sea": ("subject", ["a {} of the sea, ocean waves and the coast"], 0.12),
    "mountains": ("subject", ["a {} of mountains and peaks"], 0.12),
    "forest": ("subject", ["a {} of a forest with trees"], 0.12),
    "water": ("subject", ["a {} of a river or a lake"], 0.12),
    "city": ("subject", ["a {} of a city, a town view"], 0.14),
    "street": ("subject", ["a {} of a street with houses and people walking"], 0.08),
    "architecture": ("subject", ["a {} of a building, church, palace or bridge"], 0.14),
    "flowers": ("subject", ["a {} of flowers"], 0.10),
    "animals": ("subject", ["a {} of an animal"], 0.10),
    "birds": ("subject", ["a {} of a bird"], 0.07),
    "sky": ("subject", ["a {} of a dramatic sky with clouds"], 0.08),
    "still_life": ("subject", ["a still life {} of objects on a table"], 0.06),
    "space": ("subject", ["an astronomical {} of space, stars, nebula or planets"], 0.04),
}
# брак: если такой промпт побеждает свой «нормальный» — выкидываем
REJECT = {
    "art": [("a photograph of a framed painting hanging on a wall in a museum", "a {}"),
            ("a page of printed text or a book page", "a {}"),
            ("a faded blank sheet of old paper with a tiny sketch", "a colorful detailed {}"),
            ("a black and white sketch drawing", "a colorful {}")],
    "photo": [("a portrait photo of a person, a close-up of a face", "a {} of a place or nature"),
              ("a group of people posing for a photo", "a {} of a place or nature"),
              ("a diagram, map, chart or document", "a {}"),
              ("a microscope image or an x-ray scan", "a {}")],
}
WORD = {"art": "painting", "photo": "photo"}
# подсказки из метаданных (AIC subjects / категории Commons) — считаются надёжными
META_HINTS = {
    "winter": ["winter", "snow"], "autumn": ["autumn", "fall foliage"], "spring": ["spring"],
    "night": ["night", "nocturne", "moon"], "sea": ["sea", "seascape", "ocean", "marine", "coast", "beach", "boats"],
    "mountains": ["mountain", "alps"], "forest": ["forest", "woods", "trees"], "water": ["river", "lake"],
    "city": ["city", "cityscape", "urban", "town"], "street": ["street"], "architecture": ["architecture", "bridge", "church", "castle", "cathedral", "temple"],
    "flowers": ["flower", "floral", "botanical", "blossom"], "animals": ["animal", "horse", "dog", "cat", "cattle", "mammal", "insect"],
    "birds": ["bird"], "still_life": ["still life"], "space": ["astronomy", "nebula", "galaxy", "planet"], "landscape": ["landscape"],
}


def fetch(url, tries=3, timeout=15):
    """Музей за Cloudflare охотно отдаёт 403/таймауты при потоке запросов: не зависаем,
    пропускаем картинку — её подхватит следующий проход сборки каталога."""
    for a in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(5 * (a + 1))
                continue
            return None
        except Exception:  # noqa: BLE001
            time.sleep(2 * (a + 1))
    return None


def thumb_path(key):
    return os.path.join(THUMBS, hashlib.md5(key.encode()).hexdigest() + ".jpg")


def ensure_thumb(item):
    key, it = item
    p = thumb_path(key)
    if os.path.exists(p):
        return True
    data = fetch(it["thumb"])
    if not data:
        return False
    try:
        Image.open(io.BytesIO(data)).convert("RGB").save(p, quality=88)
        return True
    except Exception:  # noqa: BLE001
        return False


def color_features(img):
    """Тёплые/холодные, яркость, насыщенность, «пестрота» и детализация (для сложности пазла)."""
    a = np.asarray(img.resize((128, 128)).convert("RGB"), dtype=np.float32) / 255.0
    hsv = np.asarray(img.resize((128, 128)).convert("HSV"), dtype=np.float32) / 255.0
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    warm = ((h < 0.17) | (h > 0.92)) * s
    cold = ((h > 0.45) & (h < 0.75)) * s
    rg = a[..., 0] - a[..., 1]
    yb = 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    colorful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    g = np.asarray(img.resize((128, 128)).convert("L"), dtype=np.float32) / 255.0
    grad = np.abs(np.diff(g, axis=0))[:, :-1] + np.abs(np.diff(g, axis=1))[:-1, :]
    flat = float((grad < 0.02).mean())  # доля «ровных» участков: небо, вода, фон
    return {"warm": float(warm.mean()), "cold": float(cold.mean()), "sat": float(s.mean()), "bright": float(v.mean()),
            "colorful": colorful, "detail": float(grad.mean()), "flat": flat}


def main():
    art = json.load(open(os.path.join(WORK, "art_raw.json"), encoding="utf-8"))
    photo = json.load(open(os.path.join(WORK, "photo_raw.json"), encoding="utf-8"))
    # Pexels — необязательный источник: файла нет, пока не запускали harvest_pexels.py
    pex_path = os.path.join(WORK, "pexels_raw.json")
    pexels = json.load(open(pex_path, encoding="utf-8")) if os.path.exists(pex_path) else {}
    photo.update(pexels)
    items = dict(art)
    items.update(photo)
    print("items:", len(items), "art", len(art), "photo", len(photo), "(pexels", len(pexels), ")", flush=True)

    # 1) превью (--no-fetch: работаем только с уже скачанными)
    todo = [] if "--no-fetch" in sys.argv else [(k, v) for k, v in items.items() if not os.path.exists(thumb_path(k))]
    print("thumbs to fetch:", len(todo), flush=True)
    with ThreadPoolExecutor(4) as ex:
        for i, _ in enumerate(ex.map(ensure_thumb, todo)):
            if i % 250 == 0:
                print("  thumbs", i, flush=True)
    keys = [k for k in items if os.path.exists(thumb_path(k))]

    # 2) CLIP
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai", device=dev)
    tok = open_clip.get_tokenizer("ViT-L-14")
    model.eval()

    def enc_text(texts):
        # держим всё на CPU: признаки картинок тоже сложены на CPU
        with torch.no_grad():
            t = model.encode_text(tok(texts).to(dev))
            return torch.nn.functional.normalize(t.float(), dim=-1).cpu()

    feats = {}
    batch = 64
    for i in range(0, len(keys), batch):
        ks = keys[i:i + batch]
        imgs, ok = [], []
        for k in ks:
            try:
                im = Image.open(thumb_path(k)).convert("RGB")
                items[k]["color"] = color_features(im)
                imgs.append(preprocess(im))
                ok.append(k)
            except Exception:  # noqa: BLE001
                pass
        if not imgs:
            continue
        with torch.no_grad():
            f = model.encode_image(torch.stack(imgs).to(dev))
            f = torch.nn.functional.normalize(f.float(), dim=-1).cpu()
        for k, v in zip(ok, f):
            feats[k] = v
        if i % 1024 == 0:
            print("  clip", i, flush=True)
    keys = [k for k in keys if k in feats]

    # 3) брак
    rejected = set()
    for sec in ("art", "photo"):
        sk = [k for k in keys if items[k]["section"] == sec]
        if not sk:
            continue
        F = torch.stack([feats[k] for k in sk])
        for bad, good in REJECT[sec]:
            T = enc_text([bad, good.format(WORD[sec])])
            sim = F @ T.T
            for k, row in zip(sk, sim):
                if float(row[0] - row[1]) > 0.02:
                    rejected.add(k)
    print("rejected:", len(rejected), flush=True)
    keys = [k for k in keys if k not in rejected]

    # 4) теги CLIP: для каждой секции — относительный балл против нейтрального, берём верхнюю долю
    for k in keys:
        items[k]["tags"] = set()
    for sec in ("art", "photo"):
        sk = [k for k in keys if items[k]["section"] == sec]
        print("  секция", sec, len(sk), flush=True)
        if not sk:
            continue
        F = torch.stack([feats[k] for k in sk])
        neutral = enc_text(["a {}".format(WORD[sec])])
        base = (F @ neutral.T).squeeze(1)
        for tag, (group, prompts, share) in CLIP_TAGS.items():
            T = enc_text([p.format(WORD[sec]) for p in prompts]).mean(0, keepdim=True)
            T = torch.nn.functional.normalize(T, dim=-1)
            score = (F @ T.T).squeeze(1) - base
            thr = torch.quantile(score, 1.0 - share)
            for k, s in zip(sk, score):
                if float(s) >= float(thr) and float(s) > 0.0:
                    items[k]["tags"].add(tag)
        # в группах «время года» и «время суток» оставляем один, самый сильный тег
        for group in ("season", "time"):
            gt = [t for t, v in CLIP_TAGS.items() if v[0] == group]
            T = torch.nn.functional.normalize(torch.cat([enc_text([CLIP_TAGS[t][1][0].format(WORD[sec])]) for t in gt]), dim=-1)
            sims = F @ T.T
            for k, row in zip(sk, sims):
                have = [t for t in gt if t in items[k]["tags"]]
                if len(have) > 1:
                    best = gt[int(torch.argmax(row))]
                    for t in have:
                        if t != best:
                            items[k]["tags"].discard(t)

    # 5) подсказки из метаданных + тона + сложность
    for k in keys:
        it = items[k]
        meta = " | ".join(it.get("meta", []))
        for tag, words in META_HINTS.items():
            if any(w in meta for w in words):
                it["tags"].add(tag)
        c = it["color"]
        if c["warm"] > 0.16 and c["warm"] > c["cold"] * 1.5:
            it["tags"].add("warm")
        if c["cold"] > 0.14 and c["cold"] > c["warm"] * 1.5:
            it["tags"].add("cold")
        if c["colorful"] > 0.28 and c["sat"] > 0.35:
            it["tags"].add("bright")
        if c["sat"] < 0.25 and c["bright"] > 0.62:
            it["tags"].add("pastel")
        if c["bright"] < 0.33:
            it["tags"].add("dark")
        # сложность пазла: чем больше ровных участков и меньше деталей — тем труднее
        hard = c["flat"] * 1.2 - c["detail"] * 6.0 - c["colorful"] * 0.8
        it["difficulty"] = hard
    ds = sorted(items[k]["difficulty"] for k in keys)
    lo, hi = ds[len(ds) // 3], ds[2 * len(ds) // 3]
    for k in keys:
        d = items[k]["difficulty"]
        items[k]["tags"].add("easy" if d <= lo else ("hard" if d >= hi else "medium"))

    out = {}
    for k in keys:
        it = items[k]
        it["tags"] = sorted(it["tags"])
        it.pop("meta", None)
        out[k] = it
    json.dump(out, open(os.path.join(WORK, "tagged.json"), "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    cnt = Counter(t for it in out.values() for t in it["tags"])
    print("kept:", len(out), "art", sum(1 for v in out.values() if v["section"] == "art"),
          "photo", sum(1 for v in out.values() if v["section"] == "photo"))
    print(dict(cnt.most_common()))


if __name__ == "__main__":
    main()
