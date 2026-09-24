"""Фото для бесконечного каталога: «Избранные изображения» Wikimedia Commons по темам.
Лицензии только CC0 / PD / CC BY / CC BY-SA (без NC/ND и без «только GFDL»), автор сохраняется для подписи.
Пишет work/photo_raw.json. Запуск: tools/.venv/Scripts/python tools/harvest_photo.py"""
import html, json, os, re, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "work")
os.makedirs(WORK, exist_ok=True)
UA = {"User-Agent": "FragmentsPuzzle/0.1 (catalog build; github.com/VVSaydzhanov/fragments-catalog)"}
MIN_SIDE = 1600
PER_TOPIC = 700
DEPTH = 2

# корневые категории → теги-подсказки (дальше CLIP уточнит)
TOPICS = {
    "Category:Featured pictures of landscapes": ["landscape"],
    "Category:Featured pictures of mountains": ["landscape", "mountains"],
    "Category:Featured pictures of water": ["water"],
    "Category:Featured pictures of cities": ["city"],
    "Category:Featured pictures of streets": ["city", "street"],
    "Category:Featured pictures of architecture": ["architecture"],
    "Category:Featured pictures of bridges": ["architecture"],
    "Category:Featured pictures of mammals": ["animals"],
    "Category:Featured pictures of birds": ["birds"],
    "Category:Featured pictures of insects": ["animals"],
    "Category:Featured pictures of plants": ["flowers"],
    "Category:Featured pictures of natural phenomena": ["sky"],
    "Category:Featured pictures of astronomy": ["space"],
}
EXCLUDE_CAT = re.compile(r"people|portrait|humans|nude|sport|military|weapon|document|map|diagram|logo|coat of arms", re.I)
LIC_OK = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? \d(\.\d)?( [a-z]+)?)$", re.I)


def api(params):
    params = dict(params, format="json")
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    for a in range(8):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20 * (a + 1))
                continue
            raise
        except Exception:  # noqa: BLE001
            time.sleep(10 * (a + 1))
    return {}


def subcats(cat):
    out, cont = [], {}
    while True:
        r = api(dict({"action": "query", "list": "categorymembers", "cmtitle": cat, "cmtype": "subcat", "cmlimit": "500"}, **cont))
        out += [m["title"] for m in r.get("query", {}).get("categorymembers", [])]
        if "continue" not in r:
            return out
        cont = r["continue"]
        time.sleep(0.5)


def files_in(cat, limit):
    got, cont = [], {}
    while len(got) < limit:
        r = api(dict({"action": "query", "generator": "categorymembers", "gcmtitle": cat, "gcmtype": "file", "gcmlimit": "50",
                      "prop": "imageinfo", "iiprop": "size|mime|url|extmetadata", "iiurlwidth": "330",
                      "iiextmetadatafilter": "LicenseShortName|Artist|ObjectName"}, **cont))
        for p in r.get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            got.append((p["title"], ii))
        if "continue" not in r:
            break
        cont = r["continue"]
        time.sleep(0.6)
    return got


def clean(s):
    s = re.sub(r"<[^>]+>", "", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()


def nice_title(file_title, meta_name):
    t = clean(meta_name) if meta_name else ""
    if not t or len(t) > 80:
        t = re.sub(r"\.(jpe?g|png|tiff?)$", "", file_title[5:], flags=re.I)
        t = re.sub(r"[_]+", " ", t)
        t = re.sub(r"\b(IMG|DSC|DSCF|P\d+|\d{4}[-_]\d{2}[-_]\d{2}|\d{6,})\b.*$", "", t).strip(" -,._")
    return t[:80]


out = {}
for root, hint in TOPICS.items():
    cats, frontier = [root], [root]
    for _ in range(DEPTH):
        nxt = []
        for c in frontier:
            for s in subcats(c):
                if not EXCLUDE_CAT.search(s) and s not in cats:
                    cats.append(s)
                    nxt.append(s)
        frontier = nxt
    kept = 0
    for c in cats:
        if kept >= PER_TOPIC:
            break
        for title, ii in files_in(c, PER_TOPIC - kept):
            if title in out or ii.get("mime") != "image/jpeg":
                continue
            w, h = ii.get("width", 0), ii.get("height", 0)
            if max(w, h) < MIN_SIDE or not (0.5 <= w / max(h, 1) <= 2.0):
                continue
            em = ii.get("extmetadata", {})
            lic = clean(em.get("LicenseShortName", {}).get("value", ""))
            if not LIC_OK.match(lic):
                continue
            bucket = 1920 if w > h else 1280
            full = ii["url"] if max(w, h) <= bucket else re.sub(r"/330px-", f"/{bucket}px-", ii.get("thumburl", ""))
            out[title] = {
                "section": "photo", "kind": "photo", "source": "commons",
                "title": nice_title(title, em.get("ObjectName", {}).get("value", "")),
                "author": clean(em.get("Artist", {}).get("value", ""))[:80], "license": lic,
                "w": w, "h": h, "url": full.split("?")[0], "thumb": ii.get("thumburl", "").split("?")[0],
                "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                "meta": [c.lower().replace("category:", "")] + hint, "src": title,
            }
            kept += 1
    print(root, "cats", len(cats), "kept", kept, flush=True)
json.dump(out, open(os.path.join(WORK, "photo_raw.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("total photo:", len(out))
