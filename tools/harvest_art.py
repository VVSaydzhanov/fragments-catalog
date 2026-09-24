"""Картины для бесконечного каталога: Art Institute of Chicago API (только общественное достояние, CC0).
Живопись + цветные японские гравюры + акварели. Пишет work/art_raw.json.
Запуск: tools/.venv/Scripts/python tools/harvest_art.py"""
import json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "work")
os.makedirs(WORK, exist_ok=True)
UA = {"User-Agent": "FragmentsPuzzle/0.1 (catalog build; github.com/VVSaydzhanov/fragments-catalog)",
      "AIC-User-Agent": "FragmentsPuzzle (github.com/VVSaydzhanov/fragments-catalog)",
      "Content-Type": "application/json"}
FIELDS = ["id", "title", "artist_title", "date_display", "image_id", "thumbnail", "color",
          "subject_titles", "term_titles", "style_titles", "classification_titles", "place_of_origin",
          "artwork_type_title", "is_boosted"]
MIN_SIDE = 1600
# Крупные ответы API AIC в этой сети обрываются (~>20 КБ) — берём маленькие страницы.
PAGE = 10
MAX_PER_KIND = 2500

QUERIES = {
    "painting": [{"term": {"artwork_type_title.keyword": "Painting"}}],
    "print_jp": [{"term": {"artwork_type_title.keyword": "Print"}},
                 {"term": {"classification_titles.keyword": "woodblock print"}},
                 {"term": {"place_of_origin.keyword": "Japan"}}],
    "watercolor": [{"term": {"artwork_type_title.keyword": "Drawing and Watercolor"}},
                   {"match": {"classification_titles": "watercolor"}}],
}


def search(must, page):
    body = {"query": {"bool": {"must": [{"term": {"is_public_domain": True}}, {"exists": {"field": "image_id"}}] + must}},
            "fields": FIELDS, "limit": PAGE, "page": page}
    for a in range(5):
        try:
            req = urllib.request.Request("https://api.artic.edu/api/v1/artworks/search", headers=UA, data=json.dumps(body).encode())
            return json.load(urllib.request.urlopen(req, timeout=40))
        except Exception as e:  # noqa: BLE001 — сеть/лимиты: повторить
            print("  retry", e)
            time.sleep(10 * (a + 1))
    return {"data": [], "pagination": {"total_pages": 0}}


out = {}
for kind, must in QUERIES.items():
    page, pages, kept = 1, 1, 0
    while page <= pages and page * PAGE <= min(MAX_PER_KIND, 10000):
        d = search(must, page)
        pages = d["pagination"].get("total_pages", 0)
        for it in d["data"]:
            th = it.get("thumbnail") or {}
            w, h = th.get("width") or 0, th.get("height") or 0
            if not it.get("image_id") or max(w, h) < MIN_SIDE or not (0.5 <= w / max(h, 1) <= 2.0):
                continue
            iid = it["image_id"]
            out["aic_%d" % it["id"]] = {
                "section": "art", "kind": kind, "source": "aic",
                "title": it.get("title") or "", "author": it.get("artist_title") or "", "date": it.get("date_display") or "",
                "license": "CC0", "w": w, "h": h,
                "url": f"https://www.artic.edu/iiif/2/{iid}/full/!1686,1686/0/default.jpg",
                "thumb": f"https://www.artic.edu/iiif/2/{iid}/full/!400,400/0/default.jpg",
                "page": f"https://www.artic.edu/artworks/{it['id']}",
                "meta": [t.lower() for t in (it.get("subject_titles") or []) + (it.get("term_titles") or []) + (it.get("style_titles") or [])],
                "place": it.get("place_of_origin") or "", "boosted": bool(it.get("is_boosted")),
            }
            kept += 1
        page += 1
        time.sleep(0.9)  # лимит AIC ~60 запросов в минуту
        if page % 20 == 0:
            print(" ", kind, "page", page, "of", pages, "kept", kept, flush=True)
    print(kind, "kept", kept, flush=True)
json.dump(out, open(os.path.join(WORK, "art_raw.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("total art:", len(out))
