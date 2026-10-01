"""Фото с Pexels для бесконечного каталога: то, чего нет у музеев и Wikimedia, —
уют, коты и собаки, еда, праздники, живые улицы. Пишет work/pexels_raw.json.

Лицензия Pexels: бесплатно, в том числе коммерчески; картинки берём ссылкой на их CDN
(хранить у себя нельзя), в игре показываем имя автора и ссылку на Pexels.
Ключ (бесплатный, https://www.pexels.com/api/) — в переменной окружения PEXELS_API_KEY
или в файле work/pexels_key.txt (папка work в git не попадает).
Запуск: tools/.venv/Scripts/python tools/harvest_pexels.py [--pages 3] [--vivid]
  --vivid — вместо тематических запросов яркие: поиск с фильтром Pexels по цвету кадра."""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "work")
os.makedirs(WORK, exist_ok=True)
MIN_SIDE = 1600          # меньше — на большом пазле будет мыло
PER_PAGE = 80            # максимум, который отдаёт Pexels за запрос
FULL, THUMB = 1600, 500  # размеры, которые просим у их CDN

# запрос → подсказки-теги (дальше CLIP уточняет сам)
QUERIES = [
    ("cozy cafe interior", ["cozy"]), ("cozy living room fireplace", ["cozy"]),
    ("tea candles books", ["cozy", "still_life"]), ("bookshop interior", ["cozy"]),
    ("rain on window cozy", ["cozy", "rain"]),
    ("cat on windowsill", ["animals", "cozy"]), ("kitten", ["animals"]),
    ("golden retriever puppy", ["animals"]), ("dog autumn park", ["animals", "autumn"]),
    ("fox in snow", ["animals", "winter"]), ("horses in field", ["animals"]),
    ("squirrel autumn", ["animals", "autumn"]), ("red panda", ["animals"]),
    ("colorful parrot", ["birds"]), ("owl", ["birds"]), ("hummingbird flower", ["birds", "flowers"]),
    ("breakfast table flat lay", ["still_life"]), ("berry cake dessert", ["still_life"]),
    ("coffee latte art", ["still_life"]), ("fruit market stall", ["street", "still_life"]),
    ("picnic summer", ["summer", "still_life"]),
    ("colorful houses street", ["city", "street"]), ("venice canal", ["city", "water"]),
    ("paris street cafe", ["city", "street"]), ("tokyo street night", ["city", "night"]),
    ("amsterdam bicycles", ["city", "street"]), ("santorini greece", ["city", "sea"]),
    ("lavender field", ["flowers", "landscape"]), ("sunflower field", ["flowers", "summer"]),
    ("autumn forest path", ["forest", "autumn"]), ("waterfall rainforest", ["water", "forest"]),
    ("northern lights cabin", ["night", "winter"]), ("tropical beach palm", ["sea", "summer"]),
    ("mountain lake reflection", ["mountains", "water"]), ("cherry blossom", ["spring", "flowers"]),
    ("christmas decorations", ["cozy", "winter"]), ("christmas market night", ["city", "night", "winter"]),
    ("halloween pumpkins", ["autumn"]), ("spring flowers garden", ["spring", "flowers"]),
    ("hot air balloons", ["sky"]), ("lighthouse sea", ["sea"]), ("vintage car street", ["street"]),
    ("sailboat sunset", ["sea", "sunset"]), ("carousel lights", ["night", "city"]),
    ("bridge autumn river", ["architecture", "autumn"]),
]


# Яркие: запрос → цвет, который Pexels должен найти в кадре, → подсказки-теги.
# Фильтр по цвету отсекает блёклые снимки ещё на стороне Pexels — пёстрых в выдаче
# заметно больше, чем при одном слове «colorful» в запросе.
VIVID = [
    ("tulip field", "red", ["flowers", "spring"]), ("poppy field", "red", ["flowers", "summer"]),
    ("flowers bouquet", "pink", ["flowers"]), ("sunflowers", "yellow", ["flowers", "summer"]),
    ("lavender", "violet", ["flowers"]), ("cherry blossom", "pink", ["flowers", "spring"]),
    ("autumn leaves", "orange", ["autumn"]), ("autumn forest", "orange", ["forest", "autumn"]),
    ("tropical beach", "turquoise", ["sea", "summer"]), ("lagoon aerial", "turquoise", ["sea"]),
    ("coral reef fish", "blue", ["sea", "animals"]), ("colorful boats harbor", "blue", ["sea", "city"]),
    ("hot air balloons", "red", ["sky"]), ("sunset sky", "orange", ["sunset", "sky"]),
    ("neon street night", "violet", ["city", "night"]), ("neon signs", "pink", ["city", "night"]),
    ("paper lanterns", "red", ["night"]), ("festival lights", "yellow", ["night"]),
    ("colorful houses", "yellow", ["city", "street"]), ("colorful street art", "pink", ["city", "street"]),
    ("colorful umbrellas", "yellow", ["street"]), ("rainbow staircase", "pink", ["architecture"]),
    ("parrot", "green", ["birds"]), ("macaw", "blue", ["birds"]), ("peacock", "blue", ["birds"]),
    ("kingfisher", "turquoise", ["birds"]), ("butterfly flower", "orange", ["animals", "flowers"]),
    ("tree frog", "green", ["animals"]), ("goldfish", "orange", ["animals", "water"]),
    ("macarons", "pink", ["still_life"]), ("fruit bowl", "orange", ["still_life"]),
    ("berries", "red", ["still_life"]), ("lemons", "yellow", ["still_life"]),
    ("spice market", "orange", ["street", "still_life"]), ("candy sweets", "pink", ["still_life"]),
    ("colorful yarn", "violet", ["cozy", "still_life"]), ("crayons pencils", "yellow", ["still_life"]),
    ("christmas lights", "red", ["winter", "cozy"]), ("pumpkins", "orange", ["autumn"]),
    ("northern lights", "green", ["night", "sky"]), ("green rice terraces", "green", ["landscape"]),
    ("canyon desert", "orange", ["landscape"]), ("blue lake mountains", "blue", ["mountains", "water"]),
]


def key() -> str:
    k = os.environ.get("PEXELS_API_KEY", "").strip()
    if not k:
        path = os.path.join(WORK, "pexels_key.txt")
        if os.path.exists(path):
            k = open(path, encoding="utf-8").read().strip()
    if not k:
        sys.exit("нет ключа: положите его в work/pexels_key.txt или в PEXELS_API_KEY "
                 "(бесплатно на https://www.pexels.com/api/)")
    return k


def search(api_key: str, query: str, page: int, color: str = "") -> dict:
    params = {"query": query, "per_page": PER_PAGE, "page": page}
    if color:
        params["color"] = color
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": api_key, "User-Agent": "FragmentsPuzzle/0.1"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
                data["_left"] = int(r.headers.get("X-Ratelimit-Remaining", "1000"))
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:  # лимит на час выбран — ждём и пробуем ещё раз
                print("  лимит запросов, пауза 60 с", flush=True)
                time.sleep(60)
                continue
            print("  HTTP", e.code, query, flush=True)
            return {}
        except Exception:  # noqa: BLE001
            time.sleep(5 * (attempt + 1))
    return {}


def sized(original: str, w: int) -> str:
    """Свой размер у их CDN: картинка вписывается в квадрат w×w, пропорции сохраняются."""
    return original.split("?")[0] + "?auto=compress&cs=tinysrgb&fit=clip&w=%d&h=%d" % (w, w)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


TAIL_WORD = re.compile(r"\s+(and|with|in|on|of|a|an|the|for|at|to|by|from|near|over|under|its|their)$", re.I)


def short_title(alt: str, author: str) -> str:
    """Pexels отдаёт описание целым предложением — в карточке нужен короткий заголовок."""
    t = re.sub(r"\s+", " ", (alt or "").strip())
    t = re.sub(r"^(a|an|the) ", "", t, flags=re.I)
    cut = re.split(r"[,.;:]| showcasing | featuring | surrounded by | against | while ", t)[0].strip()
    if len(cut) >= 15:
        t = cut
    if len(t) > 60:
        t = t[:60].rsplit(" ", 1)[0]
    t = t.strip(" -—")
    while True:  # обрезали по длине — не оставляем висеть предлог или союз
        cut = TAIL_WORD.sub("", t)
        if cut == t:
            break
        t = cut
    return (t[:1].upper() + t[1:]) if t else author


def main() -> None:
    pages = int(sys.argv[sys.argv.index("--pages") + 1]) if "--pages" in sys.argv else 3
    api_key = key()
    path = os.path.join(WORK, "pexels_raw.json")
    out = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    started = len(out)
    vivid = "--vivid" in sys.argv
    plan = [(q, c, h) for q, c, h in VIVID] if vivid else [(q, "", h) for q, h in QUERIES]
    for query, color, hints in plan:
        kept = 0
        for page in range(1, pages + 1):
            data = search(api_key, query, page, color)
            photos = data.get("photos", [])
            if not photos:
                break
            for p in photos:
                w, h = int(p.get("width", 0)), int(p.get("height", 0))
                if min(w, h) < MIN_SIDE or not (0.5 <= w / max(h, 1) <= 2.0):
                    continue
                k = "pexels:%d" % int(p["id"])
                if k in out:
                    continue
                original = p.get("src", {}).get("original", "")
                if not original:
                    continue
                title = short_title(p.get("alt", ""), clean(p.get("photographer", "")))
                out[k] = {
                    "section": "photo", "kind": "photo", "source": "pexels",
                    "title": title, "author": clean(p.get("photographer", ""))[:80], "license": "Pexels",
                    "w": w, "h": h, "url": sized(original, FULL), "thumb": sized(original, THUMB),
                    "page": p.get("url", ""), "meta": query.split() + hints, "src": k,
                }
                if vivid:
                    out[k]["vivid"] = True
                kept += 1
            if data.get("_left", 1000) <= 2:
                print("часовой лимит почти выбран — останавливаемся", flush=True)
                json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
                return
            time.sleep(0.4)
        print("%-28s +%d" % (query + (" [" + color + "]" if color else ""), kept), flush=True)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print("pexels: всего %d (+%d за этот запуск)" % (len(out), len(out) - started))


if __name__ == "__main__":
    main()
