"""Выкладывает сгенерированные картинки (work/gen, см. gen_images.py) в папку gen/ репозитория —
GitHub Pages раздаёт их по адресам, которые tag_items.py пишет в ленту.

Формат — WebP: приложение его читает, а весит он меньше JPEG. Полный размер — для самого пазла,
превью — для ленты. Уже выложенные файлы не трогаем; отсеянные при генерации пропускаем.

Отбор вручную: удали неудачную картинку из work/gen — при следующем запуске она помечается
в work/gen_raw.json как убранная, её файлы уходят из gen/, а из ленты она пропадёт после
tag_items.py и build_feed.py.
Запуск: tools/.venv/Scripts/python tools/publish_gen.py"""
import json, os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
WORK = os.path.join(ROOT, "work")
DST = os.path.join(ROOT, "gen")
FULL_Q, THUMB_Q = 82, 80


def main():
    os.makedirs(os.path.join(DST, "thumbs"), exist_ok=True)
    raw_path = os.path.join(WORK, "gen_raw.json")
    raw = json.load(open(raw_path, encoding="utf-8"))
    removed = 0
    for k, v in list(raw.items()):
        if not v.get("rejected") and not os.path.exists(os.path.join(WORK, "gen", k + ".jpg")):
            raw[k] = {"rejected": "removed_by_user", "prompt": v.get("prompt", "")}
            removed += 1
        if raw[k].get("rejected"):
            for p in (os.path.join(DST, k + ".webp"), os.path.join(DST, "thumbs", k + ".webp"),
                      os.path.join(WORK, "gen", "thumbs", k + ".jpg")):
                if os.path.exists(p):
                    os.remove(p)
    if removed:
        json.dump(raw, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("убрано вручную: %d" % removed)
    made = skipped = 0
    total = 0
    for k, v in sorted(raw.items()):
        if v.get("rejected"):
            continue
        for src, dst, q in [(os.path.join(WORK, "gen", k + ".jpg"), os.path.join(DST, k + ".webp"), FULL_Q),
                            (os.path.join(WORK, "gen", "thumbs", k + ".jpg"), os.path.join(DST, "thumbs", k + ".webp"), THUMB_Q)]:
            if not os.path.exists(src):
                continue
            if os.path.exists(dst):
                skipped += 1
            else:
                Image.open(src).convert("RGB").save(dst, "WEBP", quality=q, method=6)
                made += 1
            total += os.path.getsize(dst)
    ok = sum(1 for v in raw.values() if not v.get("rejected"))
    print("картинок %d; выложено %d файлов, уже были %d, всего в gen/ %.0f МБ" % (ok, made, skipped, total / 2 ** 20))


if __name__ == "__main__":
    main()
