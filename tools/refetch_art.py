"""Докачка превью картин AIC: музей за Cloudflare и при потоке запросов начинает отвечать 403,
поэтому качаем в один поток с паузой и длинными перерывами после отказов.
Запуск: python tools/refetch_art.py [сколько_минут]"""
import hashlib, io, json, os, sys, time, urllib.error, urllib.request
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "work")
THUMBS = os.path.join(WORK, "thumbs")
UA = {"User-Agent": "FragmentsPuzzle/0.1 (catalog build; github.com/VVSaydzhanov/fragments-catalog)",
      "AIC-User-Agent": "FragmentsPuzzle (github.com/VVSaydzhanov/fragments-catalog)"}
LIMIT_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0

art = json.load(open(os.path.join(WORK, "art_raw.json"), encoding="utf-8"))
tp = lambda k: os.path.join(THUMBS, hashlib.md5(k.encode()).hexdigest() + ".jpg")
todo = [k for k in art if not os.path.exists(tp(k))]
print("докачиваем:", len(todo), flush=True)

t0 = time.time()
ok = fail = 0
cooldown = 0.6
for i, k in enumerate(todo):
    if (time.time() - t0) / 60.0 > LIMIT_MIN:
        print("время вышло", flush=True)
        break
    try:
        data = urllib.request.urlopen(urllib.request.Request(art[k]["thumb"], headers=UA), timeout=25).read()
        Image.open(io.BytesIO(data)).convert("RGB").save(tp(k), quality=88)
        ok += 1
        cooldown = max(0.5, cooldown * 0.9)
    except urllib.error.HTTPError as e:
        fail += 1
        # 403 от Cloudflare: притормаживаем сильнее, чтобы не углубить блокировку
        cooldown = min(30.0, cooldown * 2.0 + 1.0)
        time.sleep(cooldown)
    except Exception:  # noqa: BLE001
        fail += 1
        time.sleep(3.0)
    time.sleep(cooldown)
    if i % 50 == 0:
        print(f"  {i}/{len(todo)}  скачано {ok}, отказов {fail}, пауза {cooldown:.1f}s", flush=True)
print("итого скачано", ok, "отказов", fail, flush=True)
