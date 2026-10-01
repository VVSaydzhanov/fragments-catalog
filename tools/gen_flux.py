"""Яркие иллюстрации для ленты: генерация локально на FLUX.1 [schnell] (лицензия Apache 2.0 —
коммерческое использование разрешено).

Модель лежит на Hugging Face за «воротами» с автоодобрением: один раз войти на huggingface.co,
принять условия на странице black-forest-labs/FLUX.1-schnell и выполнить `hf auth login`
(токен сохраняется в кэше HF, в репозиторий не попадает).

Влезает в 16 ГБ видеопамяти: трансформер и T5 грузятся в 4 бита (bitsandbytes NF4).
Пишет work/flux/<id>.jpg (полный размер), work/flux/thumbs/<id>.jpg и work/flux_raw.json.

Запуск:
  tools/.venv/Scripts/python tools/gen_flux.py --test 40     пробная партия + лист-обзор
  tools/.venv/Scripts/python tools/gen_flux.py --count 600   основная партия"""
import json, os, random, sys, time

# веса модели (~34 ГБ) держим на диске E, а не в кэше на системном диске
os.environ.setdefault("HF_HUB_CACHE", "E:/Devolop/models/hf")
# Сертификаты — из хранилища Windows: антивирус с проверкой HTTPS (Kaspersky) подписывает
# соединения своим корнем, которому Windows доверяет, а встроенный список Python — нет.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import torch
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "work")
OUT = os.path.join(WORK, "flux")
THUMBS = os.path.join(OUT, "thumbs")
MODEL = "black-forest-labs/FLUX.1-schnell"
STEPS = 4                       # schnell рассчитан на 1–4 шага
SIZES = [(1536, 1152), (1152, 1536), (1536, 1024)]   # больше 1500 по длинной стороне — нужно большим пазлам
THUMB = 500
SEED = 20261001

# Сюжеты: подробные и пёстрые — у пазла должны быть мелкие различимые детали по всему кадру,
# без больших однотонных пятен (неба на полкадра, гладкого фона).
SCENES = [
    ("a hillside village of colorful houses with red roofs, winding stairs, flower boxes and laundry lines", ["city", "summer"]),
    ("a busy fairytale market square with striped awnings, fruit stalls, lanterns and cobblestones", ["city", "street"]),
    ("a cozy library with a cat sleeping among stacks of colorful books, plants and warm lamps", ["cozy", "animals"]),
    ("an underwater coral reef bursting with tropical fish, sea turtles and anemones", ["sea", "animals"]),
    ("a magical autumn forest with orange and red trees, mushrooms, a winding path and foxes", ["forest", "autumn"]),
    ("a floating island with waterfalls, tiny cottages, hot air balloons and a rainbow sky", ["sky"]),
    ("a harbor full of colorful fishing boats, seagulls and painted warehouses", ["sea", "city"]),
    ("a greenhouse overflowing with exotic flowers, butterflies and hanging plants", ["flowers"]),
    ("a winter village at night with glowing windows, a christmas tree, ice skaters and snow", ["winter", "night", "cozy"]),
    ("a candy shop window with jars of sweets, cakes, macarons and ribbons", ["still_life"]),
    ("a garden of giant sunflowers and poppies with bees, ladybugs and a small red shed", ["flowers", "summer"]),
    ("a jungle river with parrots, toucans, monkeys and huge tropical leaves", ["animals", "forest"]),
    ("a lighthouse on rocky cliffs at sunset with sailboats and crashing waves", ["sea", "sunset"]),
    ("a japanese street at night with paper lanterns, cherry blossoms and small shops", ["city", "night", "spring"]),
    ("a toy workshop full of wooden toys, trains, dolls, tools and shelves", ["cozy", "still_life"]),
    ("a mountain valley in spring with wildflower meadows, a river and grazing sheep", ["mountains", "spring"]),
    ("a steampunk airship port with brass machines, gears, balloons and flags", ["sky", "city"]),
    ("a spice bazaar with mountains of colorful spices, baskets, rugs and copper lamps", ["street", "still_life"]),
    ("a kitchen table with a summer feast of fruit, pies, jam jars and flowers", ["still_life", "summer"]),
    ("an enchanted pond with water lilies, frogs, dragonflies and a stone bridge", ["water", "animals"]),
    ("a rainy city street with colorful umbrellas, shop signs and reflections on wet cobblestones", ["street", "rain"]),
    ("a carnival at dusk with a carousel, a ferris wheel, string lights and balloons", ["night", "city"]),
    ("an owl family in a hollow tree surrounded by autumn leaves and berries", ["birds", "autumn"]),
    ("a tropical beach with turquoise water, palm trees, beach huts and colorful kayaks", ["sea", "summer"]),
    ("a stained glass window of birds and flowers in jewel colors", ["birds", "flowers"]),
    ("a bustling old railway station with steam trains, luggage and flower stalls", ["city"]),
    ("a field of tulips in rows of red, yellow and pink with a windmill", ["flowers", "spring"]),
    ("a cosmic scene of colorful planets, nebulae, comets and a tiny astronaut", ["space"]),
    ("a peacock in a palace garden with fountains, mosaics and roses", ["birds", "architecture"]),
    ("a cozy cabin interior in winter with a fireplace, knitted blankets, a dog and mugs of cocoa", ["cozy", "winter", "animals"]),
]
STYLES = [
    "detailed storybook illustration, vibrant colors",
    "rich gouache painting, saturated colors, fine details",
    "colorful watercolor illustration with ink outlines, highly detailed",
    "whimsical digital painting, bright cheerful palette, intricate details",
    "folk art style, bold patterns, vivid colors",
    "isometric miniature diorama, tilt-shift, vivid colors, lots of small details",
]
TAIL = ", no text, no letters, no watermark, sharp focus"


def load_pipe():
    from diffusers import BitsAndBytesConfig as DBnb, FluxPipeline, FluxTransformer2DModel
    from transformers import BitsAndBytesConfig as TBnb, T5EncoderModel
    nf4 = dict(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
    transformer = FluxTransformer2DModel.from_pretrained(
        MODEL, subfolder="transformer", quantization_config=DBnb(**nf4), torch_dtype=torch.bfloat16)
    t5 = T5EncoderModel.from_pretrained(
        MODEL, subfolder="text_encoder_2", quantization_config=TBnb(**nf4), torch_dtype=torch.bfloat16)
    pipe = FluxPipeline.from_pretrained(
        MODEL, transformer=transformer, text_encoder_2=t5, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()   # VAE и CLIP подгружаются на GPU по очереди — запас по памяти
    return pipe


def plan(count):
    """Сюжеты по кругу, стиль сдвигается от круга к кругу — одинаковых пар «сюжет + стиль» нет."""
    rnd = random.Random(SEED)
    jobs = []
    for i in range(count):
        scene, tags = SCENES[i % len(SCENES)]
        style = STYLES[(i // len(SCENES) + i) % len(STYLES)]
        w, h = SIZES[rnd.randrange(len(SIZES))]
        jobs.append({"id": "flux_%04d" % i, "prompt": scene + ", " + style + TAIL, "tags": tags,
                     "w": w, "h": h, "seed": rnd.randrange(2 ** 31), "scene": scene})
    return jobs


def title_of(scene):
    t = scene.split(" with ")[0].split(",")[0]
    for a in ("a ", "an "):
        if t.startswith(a):
            t = t[len(a):]
    return t[:1].upper() + t[1:]


def contact_sheet(paths, dst, cols=8, cell=240):
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (240, 240, 240))
    for i, p in enumerate(paths):
        im = Image.open(p)
        im.thumbnail((cell - 6, cell - 6))
        sheet.paste(im, ((i % cols) * cell + (cell - im.width) // 2, (i // cols) * cell + (cell - im.height) // 2))
    sheet.save(dst, quality=90)


def main():
    test = "--test" in sys.argv
    flag = "--test" if test else "--count"
    count = int(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else 40
    os.makedirs(THUMBS, exist_ok=True)
    manifest_path = os.path.join(WORK, "flux_raw.json")
    out = json.load(open(manifest_path, encoding="utf-8")) if os.path.exists(manifest_path) else {}
    all_jobs = plan(count)
    jobs = [j for j in all_jobs if not os.path.exists(os.path.join(OUT, j["id"] + ".jpg"))]
    print("к генерации: %d" % len(jobs), flush=True)
    if jobs:
        pipe = load_pipe()
        for n, j in enumerate(jobs):
            t0 = time.time()
            img = pipe(j["prompt"], width=j["w"], height=j["h"], num_inference_steps=STEPS, guidance_scale=0.0,
                       max_sequence_length=256, generator=torch.Generator("cpu").manual_seed(j["seed"])).images[0]
            img.save(os.path.join(OUT, j["id"] + ".jpg"), quality=88, optimize=True)
            th = img.copy()
            th.thumbnail((THUMB, THUMB))
            th.save(os.path.join(THUMBS, j["id"] + ".jpg"), quality=85, optimize=True)
            out[j["id"]] = {"section": "illustration", "kind": "illustration", "source": "flux",
                            "title": title_of(j["scene"]), "author": "",
                            "license": "Generated (FLUX.1 schnell, Apache-2.0)", "w": j["w"], "h": j["h"],
                            "prompt": j["prompt"], "seed": j["seed"], "meta": j["tags"], "src": j["id"]}
            print("  %s  %.1f с  %s" % (j["id"], time.time() - t0, j["scene"][:50]), flush=True)
            if n % 10 == 9:
                json.dump(out, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(out, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if test:
        paths = [os.path.join(OUT, j["id"] + ".jpg") for j in all_jobs]
        contact_sheet([p for p in paths if os.path.exists(p)], os.path.join(OUT, "_test_sheet.jpg"))
        print("лист-обзор: work/flux/_test_sheet.jpg")


if __name__ == "__main__":
    main()
