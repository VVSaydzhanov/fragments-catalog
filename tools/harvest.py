"""Сбор кандидатов с Wikimedia Commons: по категориям или поисковым запросам.
Фильтр: JPEG, общественное достояние/CC0, длинная сторона ≥1600, пропорции 0.6–1.7."""
import json, sys, time, urllib.parse, urllib.request, urllib.error
UA = {"User-Agent": "FragmentsPuzzle/0.1 (catalog curation; contact via github.com/VVSaydzhanov)"}

def api(params):
    params = dict(params, format="json")
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    for a in range(6):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(15 * (a + 1)); continue
            raise

def ok(ii, min_side=1600, min_ar=0.6):
    lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
    w, h = ii.get("width", 0), ii.get("height", 0)
    if ii.get("mime") != "image/jpeg" or not w: return None
    if "public domain" not in lic.lower() and lic.upper() != "CC0": return None
    if max(w, h) < min_side: return None
    if not (min_ar <= w / h <= 1.7): return None
    return lic

def from_generator(gen_params, limit, min_side=1600, min_ar=0.6):
    params = dict(gen_params, prop="imageinfo", iiprop="size|mime|extmetadata|url", iiurlwidth="330")
    r = api(params)
    pages = sorted(r.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        ii = p.get("imageinfo", [{}])[0]
        lic = ok(ii, min_side, min_ar)
        if lic:
            out.append({"title": p["title"], "w": ii["width"], "h": ii["height"], "lic": lic, "thumb": ii.get("thumburl", "")})
        if len(out) >= limit: break
    return out

spec = json.load(open(sys.argv[1], encoding="utf-8"))
result = {}
for col, cfg in spec.items():
    cands = []
    for cat in cfg.get("categories", []):
        cands += from_generator({"action": "query", "generator": "categorymembers", "gcmtitle": cat,
                                 "gcmtype": "file", "gcmlimit": "200"}, cfg.get("per_source", 40), cfg.get("min_side", 1600), cfg.get("min_ar", 0.6))
        time.sleep(1)
    for q in cfg.get("queries", []):
        got = from_generator({"action": "query", "generator": "search", "gsrsearch": q,
                              "gsrnamespace": "6", "gsrlimit": "10"}, 1, cfg.get("min_side", 1600), cfg.get("min_ar", 0.6))
        cands += got
        time.sleep(0.7)
    seen = set(); uniq = []
    for c in cands:
        if c["title"] not in seen:
            seen.add(c["title"]); uniq.append(c)
    result[col] = uniq
    print(col, len(uniq), flush=True)
json.dump(result, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
