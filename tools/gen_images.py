"""Яркие картинки для ленты, сгенерированные локально на FLUX.2 [klein] 4B
(лицензия Apache 2.0 — коммерческое использование разрешено).

Почему klein: в сравнении с FLUX.1 schnell и Z-Image-Turbo на одних и тех же запросах у него
самое осмысленное устройство сцены (лестницы ведут куда-то, реки откуда-то текут), сочные
цвета и мелкие детали по всему кадру — то, что нужно пазлу. И он самый быстрый.

Веса (~16 ГБ) лежат в кэше HF на диске E; модель открытая, вход на Hugging Face не нужен.
Пишет work/gen/<id>.jpg, work/gen/thumbs/<id>.jpg и work/gen_raw.json (дописывает: прерванный
запуск продолжается с того места, где остановился).

Запуск:
  tools/.venv/Scripts/python tools/gen_images.py --count 1000
  tools/.venv/Scripts/python tools/gen_images.py --test 30      пробная партия + лист-обзор"""
import json, os, random, sys, time

# веса моделей держим на диске E, а не в кэше на системном диске
os.environ.setdefault("HF_HUB_CACHE", "E:/Devolop/models/hf")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# Сертификаты — из хранилища Windows: антивирус с проверкой HTTPS (Kaspersky) подписывает
# соединения своим корнем, которому Windows доверяет, а встроенный список Python — нет.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import numpy as np
import torch
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "work")
OUT = os.path.join(WORK, "gen")
THUMBS = os.path.join(OUT, "thumbs")
MANIFEST = os.path.join(WORK, "gen_raw.json")
MODEL = "black-forest-labs/FLUX.2-klein-4B"
STEPS, GUIDANCE = 4, 1.0        # так рекомендует карточка модели
# Рисуем чуть больше и срезаем по CROP с каждого края: в «живописных» стилях модель любит
# ставить в угол выдуманную подпись художника — срез её убирает. После среза длинная
# сторона остаётся больше 1500 — столько нужно большим пазлам.
SIZES = [(1664, 1248), (1664, 1248), (1248, 1664), (1664, 1104)]
CROP = 0.04
THUMB = 500
SEED = 20261002
MAX_FLAT = 0.55                 # та же планка, что у фото в build_feed: больше — детали пазла пустые
RETRIES = 2

# Сюжеты. Надписей в кадре избегаем: вывески, корешки книг, названия лодок любая модель пишет
# абракадаброй. vary — какие вариации можно подставлять: "all" — сезон, погода и свет,
# "light" — только свет, None — сюжет как есть.
SCENES = [
    # природа
    ("a mountain valley with wildflower meadows, a winding river and grazing sheep", ["mountains", "landscape"], "all"),
    ("an alpine lake surrounded by pine forests and snowy peaks, a wooden boat at the shore", ["mountains", "water"], "all"),
    ("a waterfall cascading over mossy rocks into a turquoise pool in a lush forest", ["water", "forest"], "all"),
    ("rolling hills with patchwork fields, hedgerows and a small farmhouse", ["landscape"], "all"),
    ("a lavender field in rows leading to a stone farmhouse", ["flowers", "landscape"], "light"),
    ("a sunflower field with a red barn and a blue sky with fluffy clouds", ["flowers", "summer"], "light"),
    ("a field of tulips in rows of red, yellow and pink with a windmill", ["flowers", "spring"], "light"),
    ("a poppy meadow with wild daisies and cornflowers", ["flowers", "summer"], "light"),
    ("a forest path covered with fallen leaves among tall trees", ["forest"], "all"),
    ("a birch grove with tall white trunks and ferns", ["forest"], "all"),
    ("a misty pine forest with sunbeams through the trees", ["forest"], "light"),
    ("a rocky coastline with tide pools, starfish and crashing waves", ["sea"], "light"),
    ("a tropical beach with turquoise water, palm trees and colorful kayaks", ["sea", "summer"], "light"),
    ("a sandy cove with turquoise water surrounded by cliffs and green vegetation", ["sea"], "light"),
    ("a lighthouse on rocky cliffs above the sea", ["sea"], "all"),
    ("terraced rice fields on green hills with small houses", ["landscape"], "light"),
    ("a canyon with red and orange rock formations and a river at the bottom", ["landscape"], "light"),
    ("a mountain stream flowing between boulders and colorful wildflowers", ["water", "mountains"], "all"),
    ("an orchard with blossoming apple trees and a wooden fence", ["spring", "flowers"], None),
    ("a vineyard on rolling hills with a stone villa and cypress trees", ["landscape"], "all"),
    ("a lake with water lilies, reeds and a small wooden pier", ["water"], "all"),
    ("a garden pond with koi fish, water lilies and a stone lantern", ["water", "animals"], "light"),
    ("a pond with water lilies and an old stone arch bridge in a green park", ["water"], "all"),
    ("a river winding through a green valley with a stone bridge and a village", ["water", "landscape"], "all"),
    ("a fjord with steep green mountains, waterfalls and a red cabin by the water", ["mountains", "water"], "all"),
    ("a coral reef with tropical fish, sea turtles and anemones in clear water", ["sea", "animals"], None),
    ("a savanna with acacia trees, zebras and giraffes", ["animals", "landscape"], "light"),
    ("a bamboo forest with a stone path and lanterns", ["forest"], "light"),
    ("a meadow full of butterflies and wildflowers near the edge of a forest", ["flowers", "animals"], "light"),
    ("an autumn forest with a carpet of red and orange leaves and a small stream", ["forest", "autumn"], "light"),
    ("a snowy mountain village with wooden chalets and pine trees", ["winter", "mountains"], "light"),
    ("a frozen lake with ice skaters, surrounded by snowy trees", ["winter", "snow"], "light"),
    ("the northern lights over a snowy landscape with a small cabin", ["night", "winter", "sky"], None),
    ("a desert oasis with palm trees and a blue pool among golden dunes", ["landscape"], "light"),
    ("a volcanic landscape with green moss, black sand and a blue lake", ["landscape"], "light"),
    # животные и птицы
    ("a jungle river with colorful parrots on branches and huge tropical leaves", ["animals", "birds", "forest"], "light"),
    ("a red fox standing in a meadow full of wildflowers", ["animals"], "all"),
    ("a family of ducks swimming in a pond with water lilies", ["birds", "water"], "light"),
    ("a kingfisher perched on a branch above a river", ["birds", "water"], "light"),
    ("a peacock with its tail spread in a palace garden with fountains", ["birds"], "light"),
    ("flamingos wading in a shallow pink lagoon", ["birds", "water"], "light"),
    ("a deer in a forest clearing with ferns and mushrooms", ["animals", "forest"], "all"),
    ("a squirrel on a branch with acorns among leaves", ["animals"], "all"),
    ("horses grazing in a meadow with a wooden fence and mountains", ["animals", "landscape"], "all"),
    ("puffins on a grassy sea cliff with wildflowers", ["birds", "sea"], "light"),
    ("a hedgehog among autumn leaves, berries and mushrooms", ["animals", "autumn"], None),
    ("an owl family in a hollow tree surrounded by leaves and berries", ["birds"], "all"),
    ("butterflies on blooming flowers in a garden", ["animals", "flowers"], "light"),
    ("a red panda on a tree branch in a misty forest", ["animals"], "light"),
    ("goats on a rocky mountain slope with wildflowers", ["animals", "mountains"], "light"),
    ("a robin on a branch with red berries", ["birds"], "all"),
    ("a herd of elephants at a watering hole at the savanna", ["animals"], "light"),
    ("tropical fish and a clownfish among sea anemones", ["sea", "animals"], None),
    ("a cat sitting on a sunny windowsill among potted plants and flowers", ["animals", "cozy"], None),
    ("a golden retriever puppy in a meadow with dandelions", ["animals"], "light"),
    ("swans on a calm lake with willow trees", ["birds", "water"], "all"),
    # города и деревни без вывесок
    ("a hillside village of colorful houses with red roofs, stone stairways between the houses and flower boxes", ["city", "architecture"], "all"),
    ("a harbor with colorful wooden boats in front of painted houses", ["sea", "city"], "all"),
    ("a canal in an old european town with flower-covered bridges and colorful houses", ["city", "water"], "all"),
    ("a narrow cobblestone alley with ivy, flower pots and colorful shutters", ["street"], "all"),
    ("a white-washed greek village with blue domes above the sea", ["city", "sea"], "light"),
    ("a medieval castle on a hill above a river and forests", ["architecture"], "all"),
    ("an old stone bridge over a river in a historic town", ["architecture", "water"], "all"),
    ("a fishing village on stilts over a calm bay", ["sea", "city"], "light"),
    ("rows of colorful houses along a canal with boats", ["city", "water"], "all"),
    ("a japanese garden with a red wooden bridge, maples and a pond", ["water", "architecture"], "all"),
    ("a mountain monastery on a cliff with prayer flags", ["architecture", "mountains"], "light"),
    ("a cottage with a thatched roof and a garden full of flowers", ["architecture", "flowers"], "all"),
    ("a lighthouse and a small harbor town with colorful houses", ["sea", "city"], "light"),
    ("a palace garden with geometric hedges, fountains and flower beds", ["architecture", "flowers"], "light"),
    ("hot air balloons floating over a valley with rivers and fields", ["sky", "landscape"], "light"),
    # интерьеры и уют
    ("a cozy cabin interior with a fireplace, knitted blankets and a sleeping dog", ["cozy", "animals"], None),
    ("a greenhouse overflowing with exotic flowers, hanging plants and butterflies", ["flowers"], None),
    ("a cozy reading nook by a window with cushions, plants and a cup of tea", ["cozy"], None),
    ("a rustic kitchen with copper pots, herbs, bread and a basket of vegetables", ["cozy", "still_life"], None),
    ("a sunny conservatory with lemon trees, wicker chairs and tiles", ["cozy", "flowers"], None),
    ("a toy workshop full of wooden toys, trains and tools on shelves", ["cozy", "still_life"], None),
    ("a potter's studio with colorful ceramic bowls and vases on shelves", ["still_life"], None),
    ("a flower shop interior with buckets of colorful bouquets", ["flowers", "cozy"], None),
    ("a christmas living room with a decorated tree, presents and a fireplace", ["cozy", "winter"], None),
    ("an attic bedroom with a round window, quilts and plants", ["cozy"], None),
    # натюрморты и еда
    ("a summer feast on a wooden table with fruit, pies, jam jars and flowers", ["still_life", "summer"], None),
    ("a market stall piled with colorful fruit and vegetables", ["still_life", "street"], None),
    ("macarons, cupcakes and berries on a pastel table", ["still_life"], None),
    ("a basket of freshly picked berries on a garden table", ["still_life", "summer"], None),
    ("a bouquet of peonies and roses in a vase on a sunny table", ["flowers", "still_life"], None),
    ("colorful spices in bowls and sacks at a bazaar", ["still_life"], None),
    ("an autumn harvest of pumpkins, apples and corn on a wooden porch", ["still_life", "autumn"], None),
    ("a breakfast table with pancakes, berries, honey and flowers", ["still_life"], None),
    ("glass jars of colorful candies and sweets on shelves", ["still_life"], None),
    ("a garden with rows of vegetables, sunflowers and a scarecrow", ["summer"], "light"),
    ("a picnic on a meadow with a checkered blanket, fruit basket and lemonade", ["summer", "still_life"], None),
    ("seashells, starfish and corals arranged on sand", ["sea", "still_life"], None),
    # сказочное — для живописных стилей
    ("a floating island with waterfalls, tiny cottages and hot air balloons", ["sky"], None),
    ("an enchanted forest with glowing mushrooms, fireflies and a small cottage", ["forest", "night"], None),
    ("a treehouse village connected by rope bridges in a giant forest", ["forest"], None),
    ("a castle on a hill above a valley with a rainbow", ["architecture"], None),
    ("a colorful planet landscape with two moons, strange plants and crystal rocks", ["space"], None),
    ("a mermaid lagoon with a waterfall, coral and tropical fish", ["sea"], None),
]

# Вариации: что подставить к сюжету, какие теги добавить.
VARY_ALL = [
    ("", []), ("", []), ("at golden hour", ["sunset"]), ("in early morning mist", ["morning", "fog"]),
    ("in autumn", ["autumn"]), ("in winter with fresh snow", ["winter", "snow"]), ("in spring", ["spring"]),
    ("on a bright sunny day", ["sunny", "day"]), ("in summer", ["summer"]), ("at dusk with warm lights", ["evening"]),
]
VARY_LIGHT = [
    ("", []), ("", []), ("at golden hour", ["sunset"]), ("in soft morning light", ["morning"]),
    ("on a bright sunny day", ["sunny", "day"]),
]
# Для сюжетов без сезона (интерьеры, натюрморты, сказка) меняется ракурс и свет —
# иначе один и тот же запрос повторялся бы раз в круг.
VARY_VIEW = [
    ("", []), ("close-up view", []), ("wide view", []), ("seen from above", []),
    ("in warm evening light", ["evening"]), ("in soft daylight", ["day"]),
]

# Стиль: две трети — фотореализм, треть — сочная живопись (как пейзаж с овцами из пробы).
PHOTO_STYLES = [
    "professional nature photography, deep depth of field, everything in sharp focus, vivid natural colors",
    "golden hour travel photography, warm light, rich saturated colors, highly detailed",
    "photorealistic, shot on a full-frame camera, 35mm lens, crisp details, vibrant colors",
    "photorealistic miniature diorama, tilt-shift photography, vivid colors, lots of small details",
]
# Гуашь и акварель убраны: модель рисует их «на листе бумаги» — с белыми полями и подписью.
PAINT_STYLES = [
    "whimsical digital painting, bright cheerful palette, intricate details",
    "rich impasto oil painting, sunlit, saturated colors, fine details",
    "vivid acrylic painting, bold colors, fine details",
]
TAIL = ", highly detailed"
PAINT_TAIL = ", full-bleed artwork filling the entire frame edge to edge"


def plan(count):
    """Сюжеты по кругу; каждая третья картинка — живопись, остальные — фото. Вариация и стиль
    сдвигаются от круга к кругу, так что пары «сюжет + вариация + стиль» не повторяются."""
    rnd = random.Random(SEED)
    jobs = []
    for i in range(count):
        k = i % len(SCENES)
        scene, tags, vary = SCENES[k]
        lap = i // len(SCENES)
        # сдвиги считаем от номера круга, а не от i: шаг в len(SCENES) мог оказаться кратен
        # длине списка, и тогда у сюжета навсегда оставались одни и те же вариация и стиль
        paint = (k + lap) % 3 == 2
        styles = PAINT_STYLES if paint else PHOTO_STYLES
        style = styles[(k + lap) % len(styles)]
        pool = VARY_ALL if vary == "all" else VARY_LIGHT if vary == "light" else VARY_VIEW
        mod, mod_tags = pool[(k * 7 + lap) % len(pool)]
        text = scene + ((", " + mod if pool is VARY_VIEW else " " + mod) if mod else "")
        w, h = SIZES[rnd.randrange(len(SIZES))]
        jobs.append({"id": "gen_%04d" % i, "prompt": text + ", " + style + TAIL + (PAINT_TAIL if paint else ""),
                     "tags": sorted(set(tags + mod_tags)), "w": w, "h": h, "seed": rnd.randrange(2 ** 31),
                     "scene": scene, "look": "paint" if paint else "photo"})
    return jobs


def flatness(img):
    """Доля «ровных» участков — тот же счёт, что у фото в tag_items.color_features."""
    g = np.asarray(img.resize((128, 128)).convert("L"), dtype=np.float32) / 255.0
    grad = np.abs(np.diff(g, axis=0))[:, :-1] + np.abs(np.diff(g, axis=1))[:-1, :]
    return float((grad < 0.02).mean())


def paper_border(img):
    """Белые поля, как у рисунка на листе: у краёв почти белые малонасыщенные полосы.
    Пазлу они вредят (пустые детали по краю), а внутри полей модель ещё и ставит подпись."""
    a = np.asarray(img.resize((256, 256)).convert("HSV"), dtype=np.float32) / 255.0
    pale = (a[..., 2] > 0.88) & (a[..., 1] < 0.12)
    b = 8   # ~3% края
    sides = [pale[:b].mean(), pale[-b:].mean(), pale[:, :b].mean(), pale[:, -b:].mean()]
    return sum(1 for v in sides if v > 0.6) >= 2


def title_of(scene):
    t = scene.split(" with ")[0].split(",")[0]
    for a in ("a ", "an ", "the "):
        if t.startswith(a):
            t = t[len(a):]
    return t[:1].upper() + t[1:]


def load_pipe():
    from diffusers import Flux2KleinPipeline
    pipe = Flux2KleinPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()   # текстовый кодер и трансформер по очереди — запас по памяти
    return pipe


def contact_sheet(paths, dst, cols=6, cell=300):
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (240, 240, 240))
    for i, p in enumerate(paths):
        im = Image.open(p)
        im.thumbnail((cell - 6, cell - 6))
        sheet.paste(im, ((i % cols) * cell + (cell - im.width) // 2, (i // cols) * cell + (cell - im.height) // 2))
    sheet.save(dst, quality=88)


def main():
    test = "--test" in sys.argv
    flag = "--test" if test else "--count"
    count = int(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else 30
    os.makedirs(THUMBS, exist_ok=True)
    out = json.load(open(MANIFEST, encoding="utf-8")) if os.path.exists(MANIFEST) else {}
    all_jobs = plan(count)
    jobs = [j for j in all_jobs if j["id"] not in out]
    print("сюжетов %d, к генерации: %d из %d" % (len(SCENES), len(jobs), count), flush=True)
    if jobs:
        pipe = load_pipe()
        started = time.time()
        for n, j in enumerate(jobs):
            t0 = time.time()
            img, flat, tries = None, 1.0, 0
            for attempt in range(RETRIES + 1):
                tries = attempt + 1
                seed = j["seed"] + attempt * 7919
                img = pipe(prompt=j["prompt"], width=j["w"], height=j["h"], num_inference_steps=STEPS,
                           guidance_scale=GUIDANCE, generator=torch.Generator("cpu").manual_seed(seed)).images[0]
                dx, dy = int(img.width * CROP), int(img.height * CROP)
                img = img.crop((dx, dy, img.width - dx, img.height - dy))
                flat = flatness(img)
                border = paper_border(img)
                if flat <= MAX_FLAT and not border:
                    break
            if flat > MAX_FLAT or border:
                # так и не вышло без пустых участков или белых полей — запоминаем, чтобы не пробовать снова
                why = "border" if border else "flat"
                out[j["id"]] = {"rejected": why, "flat": round(flat, 3), "prompt": j["prompt"]}
                print("  %s  отсев (%s)" % (j["id"], "белые поля" if border else "ровных участков %.0f%%" % (flat * 100)), flush=True)
            else:
                img.save(os.path.join(OUT, j["id"] + ".jpg"), quality=86, optimize=True, progressive=True)
                th = img.copy()
                th.thumbnail((THUMB, THUMB))
                th.save(os.path.join(THUMBS, j["id"] + ".jpg"), quality=82, optimize=True)
                out[j["id"]] = {"section": "gen", "kind": "gen", "source": "flux2-klein",
                                "title": title_of(j["scene"]), "author": "",
                                "license": "AI-generated (FLUX.2 klein 4B, Apache-2.0)",
                                "w": img.width, "h": img.height, "look": j["look"], "flat": round(flat, 3),
                                "prompt": j["prompt"], "seed": seed, "meta": j["tags"], "src": j["id"]}
            left = (time.time() - started) / (n + 1) * (len(jobs) - n - 1)
            print("  %s  %.1f с%s  осталось ~%d мин  %s" % (j["id"], time.time() - t0,
                  "" if tries == 1 else " (попыток %d)" % tries, left / 60, j["scene"][:44]), flush=True)
            if n % 10 == 9:
                json.dump(out, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(out, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = [k for k, v in out.items() if not v.get("rejected")]
    print("готово: %d картинок, отсеяно %d" % (len(ok), len(out) - len(ok)), flush=True)
    if test:
        paths = [os.path.join(OUT, j["id"] + ".jpg") for j in all_jobs]
        contact_sheet([p for p in paths if os.path.exists(p)], os.path.join(OUT, "_test_sheet.jpg"))
        print("лист-обзор: work/gen/_test_sheet.jpg")


if __name__ == "__main__":
    main()
