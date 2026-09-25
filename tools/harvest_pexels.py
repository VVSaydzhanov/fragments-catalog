"""Фото с Pexels для бесконечного каталога: то, чего нет у музеев и Wikimedia, —
уют, коты и собаки, еда, праздники, живые улицы. Пишет work/pexels_raw.json.

Лицензия Pexels: бесплатно, в том числе коммерчески; картинки берём ссылкой на их CDN
(хранить у себя нельзя), в игре показываем имя автора и ссылку на Pexels.
Ключ (бесплатный, https://www.pexels.com/api/) — в переменной окружения PEXELS_API_KEY
или в файле work/pexels_key.txt (папка work в git не попадает).
Запуск: tools/.venv/Scripts/python tools/harvest_pexels.py [--pages 3]"""
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


def search(api_key: str, query: str, page: int) -> dict:
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": PER_PAGE, "page": page})
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


def main() -> None:
    pages = int(sys.argv[sys.argv.index("--pages") + 1]) if "--pages" in sys.argv else 3
    api_key = key()
    path = os.path.join(WORK, "pexels_raw.json")
    out = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    started = len(out)
    for query, hints in QUERIES:
        kept = 0
        for page in range(1, pages + 1):
            data = search(api_key, query, page)
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
                title = clean(p.get("alt", ""))[:80] or clean(p.get("photographer", ""))[:80]
                out[k] = {
                    "section": "photo", "kind": "photo", "source": "pexels",
                    "title": title, "author": clean(p.get("photographer", ""))[:80], "license": "Pexels",
                    "w": w, "h": h, "url": sized(original, FULL), "thumb": sized(original, THUMB),
                    "page": p.get("url", ""), "meta": query.split() + hints, "src": k,
                }
                kept += 1
            if data.get("_left", 1000) <= 2:
                print("часовой лимит почти выбран — останавливаемся", flush=True)
                json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
                return
            time.sleep(0.4)
        print("%-28s +%d" % (query, kept), flush=True)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print("pexels: всего %d (+%d за этот запуск)" % (len(out), len(out) - started))


if __name__ == "__main__":
    main()
