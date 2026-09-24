"""Обновляет ссылки на превью фото: Wikimedia отдаёт только те размеры, что уже сгенерированы,
поэтому нужный размер надо попросить у API — тогда сервер создаст превью и вернёт рабочий адрес.
Запуск: python tools/refresh_photo_thumbs.py [ширина]"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "work")
UA = {"User-Agent": "FragmentsPuzzle/0.1 (catalog build; github.com/VVSaydzhanov/fragments-catalog)"}
WIDTH = sys.argv[1] if len(sys.argv) > 1 else "500"
BATCH = 20  # длинные имена файлов: при 50 адрес запроса не влезает


def api(titles):
    q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo",
                                "iiprop": "url", "iiurlwidth": WIDTH, "titles": "|".join(titles)})
    for a in range(6):
        try:
            # POST: имена файлов длинные, в адресную строку не помещаются
            return json.load(urllib.request.urlopen(urllib.request.Request(
                "https://commons.wikimedia.org/w/api.php", headers=UA, data=q.encode()), timeout=60))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(15 * (a + 1))
                continue
            raise
        except Exception:  # noqa: BLE001
            time.sleep(5 * (a + 1))
    return {}


photo = json.load(open(os.path.join(WORK, "photo_raw.json"), encoding="utf-8"))
keys = list(photo)
updated = 0
for i in range(0, len(keys), BATCH):
    chunk = keys[i:i + BATCH]
    r = api(chunk)
    for p in r.get("query", {}).get("pages", {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        if p["title"] in photo and ii.get("thumburl"):
            photo[p["title"]]["thumb"] = ii["thumburl"].split("?")[0]
            updated += 1
    time.sleep(0.6)
    if i % 500 == 0:
        print(f"  {i}/{len(keys)}, обновлено {updated}", flush=True)
json.dump(photo, open(os.path.join(WORK, "photo_raw.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("обновлено ссылок:", updated, "из", len(keys))
