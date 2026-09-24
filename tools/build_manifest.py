"""Собирает сетевой манифест: для каждой отобранной картины — прямые ссылки на Wikimedia
(полная — стандартный размер 1280/1920, превью — 330) и повторная проверка лицензии."""
import json, time, urllib.parse, urllib.request, urllib.error

UA = {"User-Agent": "FragmentsPuzzle/0.1 (catalog build)"}


def api(params):
    params = dict(params, format="json")
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    for a in range(6):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(15 * (a + 1))
                continue
            raise


sel = json.load(open("tools/selected.json", encoding="utf-8"))
T = json.load(open("tools/titles.json", encoding="utf-8"))
out = {"version": 1, "updated": "2026-09-24", "collections": []}
for col, items in sel.items():
    t = T[col]
    assert len(t["items"]) == len(items), (col, len(items))
    c = {"id": col, "title": t["title"], "added": "2026-09-24", "items": []}
    for (key, ru, en), it in zip(t["items"], items):
        w, h = it["w"], it["h"]
        bucket = 1920 if w > h else 1280
        r = api({"action": "query", "prop": "imageinfo", "iiprop": "url|extmetadata",
                 "iiurlwidth": str(bucket), "titles": it["title"]})
        ii = next(iter(r["query"]["pages"].values()))["imageinfo"][0]
        lic = ii["extmetadata"].get("LicenseShortName", {}).get("value", "")
        assert "public domain" in lic.lower() or lic.upper() == "CC0", (it["title"], lic)
        full = ii["url"] if w <= bucket else ii["thumburl"]
        c["items"].append({"key": col + "_" + key, "title": [ru, en], "url": full, "thumb": it["thumb"],
                           "w": w, "h": h, "src": it["title"], "license": lic})
        time.sleep(0.6)
    out["collections"].append(c)
    print(col, "ok", flush=True)
json.dump(out, open("catalog.json", "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
