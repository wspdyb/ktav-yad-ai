# -*- coding: utf-8 -*-
"""הרחבה מסיבית של הקורפוס מאוצריא: כל הש"ס + מפרשיו, חברותא מלא,
שו"ע מלא + נושאי כלים, משנה תורה, טור, שו"ת ומוסר.

משתמש בעץ הקבצים המלא של הריפו (git trees API, במטמון) כדי לא לחרוג
ממגבלות ה-API, ומוריד עם מטמון קבצים (data/corpus_cache) — ריצה חוזרת
לא מורידה שוב. הפלט מתמזג ל-corpus_he.txt הקיים (דה-דופליקציה מלאה).

שימוש: python expand_corpus.py [--max-mb 400] [--dry]
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from charset import clean  # noqa: E402
from build_corpus import strip_wiki, to_lines, CORPUS, CACHE  # noqa: E402

TREE_CACHE = os.path.join(HERE, "data", "otzaria_tree.json")
REPO = "Sivan22/otzaria-library"

# תיקיות שלמות (כל קובצי ה-txt שתחתן) — דגש על אחרונים ובני-זמננו
PREFIXES = [
    "אוצריא/תלמוד בבלי/",              # כל הש"ס, רש"י, תוספות, ראשונים,
                                        # אחרונים, חברותא + הערות, מחברי זמננו
    "אוצריא/הלכה/שולחן ערוך/",          # כל ארבעת החלקים + כל נושאי הכלים
    "אוצריא/הלכה/משנה תורה/",
    "אוצריא/הלכה/טור/",
    "אוצריא/הלכה/מערכות ועניינים/",
    "אוצריא/הלכה/אחרונים/",             # ערוך השולחן, בן איש חי, חיי אדם...
    "אוצריא/הלכה/מחברי זמננו/",         # ילקוט יוסף ועוד
    "extraBooks/אוצריא/הלכה/מחברי זמננו/",      # פניני הלכה — עברית מודרנית
    "extraBooks/אוצריא/מחשבת ישראל/מחברי זמננו/",  # הרב קוק, הרב עמיאל...
    "אוצריא/שות/",                      # שאלות ותשובות
    "אוצריא/מוסר/",
    "אוצריא/משנה/",                     # משנה + מפרשיה
]
SKIP_RE = re.compile(r"links/|\.json$|הערות שוליים")


def _ssl_ctx():
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())


def tree_files():
    if not os.path.exists(TREE_CACHE):
        url = ("https://api.github.com/repos/" + REPO +
               "/git/trees/main?recursive=1")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300, context=_ssl_ctx()) as r:
            raw = r.read()
        os.makedirs(os.path.dirname(TREE_CACHE), exist_ok=True)
        with open(TREE_CACHE, "wb") as f:
            f.write(raw)
    tree = json.load(open(TREE_CACHE, encoding="utf-8"))
    out = []
    for it in tree["tree"]:
        p = it["path"]
        if it["type"] != "blob" or not p.endswith(".txt") or SKIP_RE.search(p):
            continue
        if any(p.startswith(pref) for pref in PREFIXES):
            out.append((p, it.get("size", 0)))
    return out


def main(max_mb=400, dry=False):
    files = tree_files()
    total_mb = sum(s for _, s in files) / 1e6
    print(f"{len(files)} קבצים נבחרו, {total_mb:.0f}MB גולמי")
    if dry:
        by_top = {}
        for p, s in files:
            top = "/".join(p.split("/")[:3])
            by_top[top] = by_top.get(top, 0) + s
        for t, s in sorted(by_top.items(), key=lambda x: -x[1])[:30]:
            print(f"  {s/1e6:7.1f}MB  {t}")
        return
    # סדר עדיפויות: בני-זמננו ואחרונים קודם (הנחיית המשתמש) — אם התקרה
    # נחתכת, נחתכים הכרכים הכבדים ביותר (ראשונים, מהדורות כפולות)
    PRIORITY = ["אוצריא/תלמוד בבלי/מחברי זמננו/",
                "extraBooks/אוצריא/הלכה/מחברי זמננו/",
                "extraBooks/אוצריא/מחשבת ישראל/מחברי זמננו/",
                "אוצריא/הלכה/מחברי זמננו/",
                "אוצריא/שות/מחברי זמננו/",
                "אוצריא/הלכה/אחרונים/",
                "אוצריא/תלמוד בבלי/אחרונים/",
                "אוצריא/שות/אחרונים/",
                "אוצריא/משנה/אחרונים/",
                "אוצריא/הלכה/שולחן ערוך/",
                "אוצריא/תלמוד בבלי/סדר ",
                "אוצריא/משנה/סדר ",
                "אוצריא/הלכה/משנה תורה/",
                "אוצריא/הלכה/טור/",
                "אוצריא/הלכה/מערכות ועניינים/",
                "אוצריא/שות/",
                "אוצריא/משנה/",
                "אוצריא/תלמוד בבלי/"]

    def prio(p):
        for k, pref in enumerate(PRIORITY):
            if p.startswith(pref):
                return k
        return len(PRIORITY)

    ctx = _ssl_ctx()
    os.makedirs(CACHE, exist_ok=True)
    texts, dl_bytes, cached_n = [], 0, 0
    t0 = time.time()
    ordered = sorted(files, key=lambda x: (prio(x[0]), x[0]))
    for i, (path, size) in enumerate(ordered):
        cache_f = os.path.join(
            CACHE, "otz_" + re.sub(r'[\\/:"*?<>|, ]', "_", path[-90:]) + ".txt")
        if os.path.exists(cache_f):
            with open(cache_f, encoding="utf-8") as f:
                texts.append(f.read())
            cached_n += 1
            continue
        if dl_bytes > max_mb * 1e6:
            continue
        url = ("https://raw.githubusercontent.com/" + REPO + "/main/"
               + urllib.parse.quote(path))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=240, context=ctx) as r:
                raw = r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  שגיאה: {path}: {e}", flush=True)
            continue
        dl_bytes += len(raw.encode("utf-8", "ignore"))
        with open(cache_f, "w", encoding="utf-8") as f:
            f.write(raw)
        texts.append(raw)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(files)} | הורדו {dl_bytes/1e6:.0f}MB | "
                  f"{time.time()-t0:.0f}s", flush=True)
        time.sleep(0.15)
    print(f"הורדה הושלמה: {dl_bytes/1e6:.0f}MB חדשים + {cached_n} מהמטמון")

    # מיזוג לקורפוס עם דה-דופליקציה מלאה מול הקיים
    lines, seen = [], set()
    if os.path.exists(CORPUS):
        with open(CORPUS, encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if l and l not in seen:
                    seen.add(l)
                    lines.append(l)
    n_base = len(lines)
    for raw in texts:
        for l in to_lines(strip_wiki(raw)):
            if l and l not in seen:
                seen.add(l)
                lines.append(l)
    with open(CORPUS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"קורפוס: {n_base:,} -> {len(lines):,} שורות "
          f"({os.path.getsize(CORPUS)/1e6:.0f}MB)")


def rebuild_capped(max_lines=2_500_000):
    """בנייה-מחדש דטרמיניסטית של קורפוס ההפצה מתוך המטמון, עם תקרת שורות
    ("שלא ייקח יותר מדי מקום") ועדיפות מובטחת: הבסיס הישן (קונטרס+ויקיטקסט
    +הבחירות המקוריות) ← ויקיפדיה (עברית כללית) ← בני-זמננו ← אחרונים ←
    שאר המקורות עד התקרה. העודף נשאר במטמון המקומי ולא נארז."""
    PRIORITY = ["wiki_he_random",
                "otz_חברותא", "otz_הערות_על_חברותא",
                "otz_פניני_הלכה", "otz_ילקוט", "otz_אב_בחכמה", "otz_וביום",
                "otz_שלח", "otz_תשובות_רפואיות",
                "otz_אורות", "otz_שמונה_קבצים", "otz_מדבר_שור", "otz_עולת",
                "otz_ערוך_השולחן", "otz_בן_איש_חי", "otz_חיי_אדם",
                "otz_חכמת_אדם", "otz_קיצור_שלחן", "otz_שולחן_ערוך_הרב",
                "otz_משנה_ברורה", "otz_ביאור_הלכה"]

    def prio(fname):
        for k, pref in enumerate(PRIORITY):
            if fname.startswith(pref):
                return k
        return len(PRIORITY)

    lines, seen = [], set()

    def add_text(raw, wiki=False):
        src = raw if not wiki else raw
        for l in to_lines(strip_wiki(src)):
            if l and l not in seen:
                seen.add(l)
                lines.append(l)
                if len(lines) >= max_lines:
                    return False
        return True

    # 1. הבסיס הקודם (270K: קונטרס, ויקיטקסט חו"מ, הבחירות המקוריות)
    base = os.path.join(HERE, "data", "corpus_he.v2.bak")
    if os.path.exists(base):
        with open(base, encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if l and l not in seen:
                    seen.add(l)
                    lines.append(l)
    print(f"בסיס: {len(lines):,} שורות")
    # 2. קובצי המטמון לפי עדיפות (בני-זמננו/אחרונים קודם), ואז השאר
    cache_files = sorted(os.listdir(CACHE), key=lambda f: (prio(f), f))
    for i, f in enumerate(cache_files):
        if not f.endswith(".txt"):
            continue
        try:
            with open(os.path.join(CACHE, f), encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            continue
        if not add_text(raw):
            print(f"התקרה הושגה אחרי {i+1}/{len(cache_files)} קבצים "
                  f"(נעצר ב-{f[:50]})")
            break
        if (i + 1) % 300 == 0:
            print(f"  {i+1}/{len(cache_files)} קבצים, {len(lines):,} שורות",
                  flush=True)
    with open(CORPUS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"קורפוס הפצה: {len(lines):,} שורות "
          f"({os.path.getsize(CORPUS)/1e6:.0f}MB)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mb", type=int, default=400)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--rebuild", action="store_true",
                    help="בנייה-מחדש קצובה מהמטמון (בלי הורדות)")
    ap.add_argument("--max-lines", type=int, default=2_500_000)
    args = ap.parse_args()
    if args.rebuild:
        rebuild_capped(args.max_lines)
    else:
        main(args.max_mb, args.dry)
