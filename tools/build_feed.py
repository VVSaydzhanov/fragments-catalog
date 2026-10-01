"""Собирает бесконечную ленту из work/tagged.json в feed/ (статика для GitHub Pages):
  feed/index.json          — теги (RU/EN, группы, количество), подборки, число страниц
  feed/items/<n>.json      — страницы по SHARD картинок (порядок: на девять фото одна картина)
  feed/tags/<tag>.json     — отсортированные номера картинок с тегом (+ sec_art / sec_photo)
Ключи стабильные (хеш источника) — начатые партии в игре переживают пересборку.
Запуск: python tools/build_feed.py"""
import datetime, hashlib, json, os, random, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
WORK = os.path.join(ROOT, "work")
FEED = os.path.join(ROOT, "feed")
SHARD = 200
MIN_PRESET = 12
# доля «ровных» участков: у снимка с размытым фоном на весь кадр детали пазла получаются пустые.
# Фотографий в запасе на порядок больше, чем нужно ленте, так что самые «гладкие» просто не берём.
MAX_FLAT = 0.55
# В общей ленте на PHOTOS_PER_ART снимков одна картина: фото собирают охотнее, а картины
# остаются приправой. Раньше шло строго через одну — и в две колонки картины вставали
# слева, а фото справа.
PHOTOS_PER_ART = 9

TAGS = [
    ("season", "spring", "Весна", "Spring"), ("season", "summer", "Лето", "Summer"),
    ("season", "autumn", "Осень", "Autumn"), ("season", "winter", "Зима", "Winter"),
    ("time", "morning", "Утро", "Morning"), ("time", "day", "День", "Day"), ("time", "sunset", "Закат", "Sunset"),
    ("time", "evening", "Вечер", "Evening"), ("time", "night", "Ночь", "Night"),
    ("mood", "sunny", "Солнечно", "Sunny"), ("mood", "fog", "Туман", "Fog"), ("mood", "rain", "Дождь", "Rain"),
    ("mood", "snow", "Снег", "Snow"), ("mood", "storm", "Шторм", "Storm"), ("mood", "cozy", "Уютно", "Cozy"),
    ("mood", "calm", "Спокойно", "Calm"),
    ("subject", "landscape", "Пейзаж", "Landscape"), ("subject", "city", "Город", "City"),
    ("subject", "street", "Улицы", "Streets"), ("subject", "architecture", "Архитектура", "Architecture"),
    ("subject", "sea", "Море", "Sea"), ("subject", "mountains", "Горы", "Mountains"), ("subject", "forest", "Лес", "Forest"),
    ("subject", "water", "Реки и озёра", "Rivers & lakes"), ("subject", "flowers", "Цветы", "Flowers"),
    ("subject", "animals", "Животные", "Animals"), ("subject", "birds", "Птицы", "Birds"), ("subject", "sky", "Небо", "Sky"),
    ("subject", "still_life", "Натюрморт", "Still life"), ("subject", "space", "Космос", "Space"),
    ("tone", "warm", "Тёплые тона", "Warm tones"), ("tone", "cold", "Холодные тона", "Cool tones"),
    ("tone", "bright", "Яркие", "Vivid"), ("tone", "pastel", "Пастель", "Pastel"), ("tone", "dark", "Тёмные", "Dark"),
    ("difficulty", "easy", "Лёгкие", "Easy"), ("difficulty", "medium", "Средние", "Medium"), ("difficulty", "hard", "Сложные", "Hard"),
]
GROUPS = {"season": ["Время года", "Season"], "time": ["Время суток", "Time of day"], "mood": ["Погода и настроение", "Weather & mood"],
          "subject": ["Сюжет", "Subject"], "tone": ["Тона", "Tones"], "difficulty": ["Сложность пазла", "Puzzle difficulty"]}
PRESETS = [
    ("winter_evening", "Зимний вечер", "Winter evening", ["winter", "evening"]),
    ("warm_autumn", "Тёплый осенний день", "Warm autumn day", ["autumn", "sunny"]),
    ("sea_breeze", "Морской бриз", "Sea breeze", ["sea", "sunny"]),
    ("night_city", "Ночной город", "City at night", ["city", "night"]),
    ("rainy_streets", "Дождливые улицы", "Rainy streets", ["street", "rain"]),
    ("spring_flowers", "Весенние цветы", "Spring flowers", ["spring", "flowers"]),
    ("misty", "Туманное утро", "Misty morning", ["fog"]),
    ("cozy", "Уютно", "Cozy", ["cozy"]),
    ("mountains_snow", "Снежные горы", "Snowy mountains", ["mountains", "winter"]),
    ("easy", "Лёгкие пазлы", "Easy puzzles", ["easy"]),
]


def stable_key(src_key):
    return "f_" + hashlib.md5(src_key.encode()).hexdigest()[:10]


def big_thumb(url):
    """Превью под плотные экраны. У музея размер задаётся прямо в адресе, а Wikimedia отдаёт
    только заранее сгенерированные размеры — её ссылки обновляет refresh_photo_thumbs.py."""
    return url.replace("/full/!400,400/", "/full/!512,512/")


def _vivid_first(keys, items, rnd):
    """Перемешивание с перевесом в сторону ярких: чем пёстрее снимок, тем вероятнее он ближе
    к началу ленты. Не сортировка — иначе наверху собрались бы одинаковые закаты.
    Вес — место по пёстрости (0..1), а не сама величина: её масштаб у разных источников разный."""
    ranked = sorted(keys, key=lambda k: items[k]["color"]["colorful"])
    pct = {k: i / max(len(ranked) - 1, 1) for i, k in enumerate(ranked)}
    # взвешенная выборка без возвращения (Эфраимидис — Спиракис): ключ u^(1/w)
    return sorted(keys, key=lambda k: -(rnd.random() ** (1.0 / (0.3 + pct[k]))))


def _mix(photo, art):
    """Десятки: девять фото и одна картина. Место картины внутри десятка гуляет (3, 0, 7, 4…),
    и его чётность меняется от десятка к десятку — в сетке на две колонки картины встают
    то слева, то справа. Кончились фото — дальше идут оставшиеся картины, и наоборот."""
    order, pi, ai, block = [], 0, 0, 0
    size = PHOTOS_PER_ART + 1
    while pi < len(photo) or ai < len(art):
        slot = (block * 7 + 3) % size
        for k in range(size):
            if k == slot and ai < len(art):
                order.append(art[ai])
                ai += 1
            elif pi < len(photo):
                order.append(photo[pi])
                pi += 1
            elif ai < len(art):
                order.append(art[ai])
                ai += 1
        block += 1
    return order


def main():
    items = json.load(open(os.path.join(WORK, "tagged.json"), encoding="utf-8"))
    rnd = random.Random(20260924)
    art = [k for k, v in items.items() if v["section"] == "art"]
    photo = [k for k, v in items.items() if v["section"] == "photo" and v["color"]["flat"] <= MAX_FLAT]
    rnd.shuffle(art)
    photo = _vivid_first(photo, items, rnd)
    order = _mix(photo, art)

    if os.path.isdir(FEED):
        shutil.rmtree(FEED)
    os.makedirs(os.path.join(FEED, "items"))
    os.makedirs(os.path.join(FEED, "tags"))
    tag_ids = {t[1]: [] for t in TAGS}
    tag_ids["sec_art"], tag_ids["sec_photo"] = [], []
    shard = []
    for i, k in enumerate(order):
        v = items[k]
        rec = {"k": stable_key(k), "s": "a" if v["section"] == "art" else "p", "t": v["title"], "a": v.get("author", ""),
               "l": v["license"], "u": v["url"], "th": big_thumb(v["thumb"]), "w": v["w"], "h": v["h"], "p": v["page"], "g": v["tags"]}
        if v.get("date"):
            rec["d"] = v["date"]
        shard.append(rec)
        tag_ids["sec_art" if rec["s"] == "a" else "sec_photo"].append(i)
        for t in v["tags"]:
            if t in tag_ids:
                tag_ids[t].append(i)
        if len(shard) == SHARD:
            json.dump(shard, open(os.path.join(FEED, "items", "%d.json" % (i // SHARD)), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            shard = []
    if shard:
        json.dump(shard, open(os.path.join(FEED, "items", "%d.json" % ((len(order) - 1) // SHARD)), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    for t, ids in tag_ids.items():
        json.dump(ids, open(os.path.join(FEED, "tags", t + ".json"), "w"), separators=(",", ":"))

    presets = []
    for pid, ru, en, tags in PRESETS:
        s = set(tag_ids[tags[0]])
        for t in tags[1:]:
            s &= set(tag_ids[t])
        if len(s) >= MIN_PRESET:
            presets.append({"id": pid, "title": [ru, en], "tags": tags, "count": len(s)})
    index = {
        # время в метке: за день лента может пересобираться не раз, и клиент должен это заметить
        "version": 1, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "count": len(order), "shard": SHARD,
        "art": len(art), "photo": len(photo),
        "groups": [{"id": g, "title": t} for g, t in GROUPS.items()],
        "tags": [{"id": tid, "group": g, "title": [ru, en], "count": len(tag_ids[tid])} for g, tid, ru, en in TAGS if tag_ids[tid]],
        "presets": presets,
    }
    json.dump(index, open(os.path.join(FEED, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("feed:", len(order), "items (art", len(art), "/ photo", len(photo), "),", len(presets), "presets")
    for p in presets:
        print("  ", p["title"][0], p["count"])


if __name__ == "__main__":
    main()
