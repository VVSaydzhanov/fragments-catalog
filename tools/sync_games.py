"""«Ещё наши игры»: games.json — только то, что уже вышло в магазине.

Какие приложения опубликованы, спрашиваем у RuStore Public API (appStatus == PUBLISHED). Подписи,
цвет и порядок — из tools/games_meta.json (там все наши приложения, вышедшие и нет); вышедшее, но
не описанное там, берётся с названием и описанием из RuStore. Пишет games.json и, с --push,
коммитит и пушит его — игры подхватят новый список при следующем запуске (LumenGames.refresh).

  python tools/sync_games.py [--push]
Токен RuStore — E:/Devolop/Medicine/rustore/.jwe_token (обновить: cd E:/Devolop/Medicine && python rustore/get_token.py).
"""
import json, os, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(ROOT, "tools", "games_meta.json")
OUT = os.path.join(ROOT, "games.json")
TOKEN = "E:/Devolop/Medicine/rustore/.jwe_token"
API = "https://public-api.rustore.ru/public/v1/application?pageSize=50"
PREFIX = "com.lumen."


def published() -> dict:
    """package → карточка приложения RuStore, только опубликованные."""
    tok = open(TOKEN, encoding="utf-8").read().strip()
    out, cont = {}, None
    while True:
        url = API + ("&continuationToken=" + cont if cont else "")
        req = urllib.request.Request(url, headers={"Public-Token": tok, "accept": "application/json"})
        body = json.loads(urllib.request.urlopen(req, timeout=30).read())["body"]
        for a in body["content"]:
            if a.get("appStatus") == "PUBLISHED" and a["packageName"].startswith(PREFIX):
                out[a["packageName"]] = a
        cont = body.get("continuationToken")
        if not cont:
            return out


def main() -> None:
    meta = json.load(open(META, encoding="utf-8"))["games"]
    live = published()
    games = []
    for g in meta:
        if g["package"] in live:
            games.append(dict(g, stores=["rustore"]))
    known = {g["package"] for g in meta}
    for pkg, a in live.items():
        if pkg not in known:
            games.append({"id": pkg[len(PREFIX):], "package": pkg, "name": [a["appName"], a["appName"]],
                          "sub": [a.get("shortDescription", ""), a.get("shortDescription", "")],
                          "color": "6BA8E8", "stores": ["rustore"]})
    lines = ",\n".join("    " + json.dumps(g, ensure_ascii=False) for g in games)
    text = '{\n  "version": 1,\n  "games": [\n' + lines + "\n  ]\n}\n"
    old = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
    print("вышли:", ", ".join(g["id"] for g in games) or "—")
    if text == old:
        print("games.json не изменился")
        return
    open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    print("games.json обновлён")
    if "--push" in sys.argv:
        subprocess.run(["git", "-C", ROOT, "add", "games.json"], check=True)
        subprocess.run(["git", "-C", ROOT, "commit", "-m", "Список игр: только вышедшие в RuStore (" +
                        ", ".join(g["id"] for g in games) + ")"], check=True)
        subprocess.run(["git", "-C", ROOT, "push"], check=True)


if __name__ == "__main__":
    main()
