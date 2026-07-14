# -*- coding: utf-8 -*-
"""בניית קורפוס עברית רבנית מוויקיטקסט (רשות הציבור) + הטקסט המוקלד של הקונטרס.

הקורפוס משמש: (א) אימון-קדם סינתטי (synth.py מרנדר ממנו שורות),
(ב) אוצר המילים של התיקון המילוני (postfix.py) — מילה רבנית שנמצאת באוצר
לא "תתוקן" בטעות למילה אחרת. לכן העשרה זו מטפלת ישירות בתלונת
"שיבוש מילים ברורות".

המקורות נבחרו לפי הדומיין של הקונטרס (חושן משפט / נזיקין / למדנות):
קצות החושן, נתיבות המשפט, שולחן ערוך חו"מ, רמב"ם (ספרי נזיקין/משפטים).

שימוש:  python build_corpus.py            (מוריד עם מטמון ובונה מחדש)
        python build_corpus.py --offline  (רק מהמטמון והקבצים המקומיים)
"""
import os
import re
import sys
import ssl
import time
import argparse
import unicodedata
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "data", "corpus_he.txt")
KUNTRES = os.path.join(HERE, "data", "kuntres_full.txt")
CACHE = os.path.join(HERE, "data", "corpus_cache")

sys.path.insert(0, HERE)
from charset import clean  # noqa: E402


# ---------------------------------------------------------------- מקורות
def heb_num(n):
    """מספר -> אותיות עבריות (א, ב, ... טו, טז, ... קכ)."""
    ones = ["", "א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט"]
    tens = ["", "י", "כ", "ל", "מ", "נ", "ס", "ע", "פ", "צ"]
    hundreds = ["", "ק", "ר", "ש", "ת"]
    h, rem = divmod(n, 100)
    t, o = divmod(rem, 10)
    s = hundreds[h] + tens[t] + ones[o]
    return s.replace("יה", "טו").replace("יו", "טז")


def source_titles():
    titles = []
    for i in range(1, 61):
        titles.append(f"קצות החושן על חושן משפט {heb_num(i)}")
        titles.append(f"נתיבות המשפט/ביאורים/{heb_num(i)}")
    for i in range(1, 121):
        titles.append(f"שולחן ערוך חושן משפט {heb_num(i)}")
    rambam = [("נזקי ממון", 14), ("גזלה ואבדה", 18), ("חובל ומזיק", 8),
              ("מכירה", 30), ("זכיה ומתנה", 12), ("מלוה ולוה", 27),
              ("טוען ונטען", 16), ("שכנים", 14)]
    for book, chapters in rambam:
        for c in range(1, chapters + 1):
            titles.append(f'רמב"ם הלכות {book} {heb_num(c)}')
    return titles


# ---------------------------------------------------------------- אוצריא
# ספריית אוצריא (github.com/Sivan22/otzaria-library) — טקסטים תורניים
# ברשות הציבור. נבחרו חיבורים מדומיין הקונטרס (נזיקין / חושן משפט):
# גמרא, שו"ע חו"מ, סמ"ע, קצות החושן, נתיבות המשפט, שיטה מקובצת.
OTZARIA_REPO = "Sivan22/otzaria-library"
OTZARIA_SOURCES = [
    "אוצריא/תלמוד בבלי/סדר נזיקין/בבא קמא.txt",
    "אוצריא/תלמוד בבלי/סדר נזיקין/בבא מציעא.txt",
    "אוצריא/תלמוד בבלי/סדר נזיקין/בבא בתרא.txt",
    "אוצריא/תלמוד בבלי/סדר נזיקין/סנהדרין.txt",
    "אוצריא/תלמוד בבלי/סדר נזיקין/שבועות.txt",
    "אוצריא/תלמוד בבלי/סדר נזיקין/מכות.txt",
    "אוצריא/הלכה/שולחן ערוך/שולחן ערוך, חושן משפט.txt",
    # תיקיות — יורדים מהן קובצי txt רלוונטיים (לפי OTZARIA_DIR_FILTER)
    "אוצריא/הלכה/שולחן ערוך/מפרשים/קצות החושן",
    "אוצריא/הלכה/שולחן ערוך/מפרשים/נתיבות המשפט, ביאורים",
    "אוצריא/הלכה/שולחן ערוך/מפרשים/נתיבות המשפט, חידושים",
    "אוצריא/הלכה/שולחן ערוך/מפרשים/מאירת עיניים",
    "אוצריא/תלמוד בבלי/אחרונים/שיטה מקובצת",
    # ניסוח תלמודי קלאסי — ראשונים על סדר נזיקין
    "אוצריא/תלמוד בבלי/ראשונים/תוספות",
    "אוצריא/תלמוד בבלי/ראשונים/רשי",
    "אוצריא/תלמוד בבלי/ראשונים/רשבא",
    "אוצריא/תלמוד בבלי/ראשונים/ריטבא",
    "אוצריא/תלמוד בבלי/ראשונים/רמבן",
    "אוצריא/תלמוד בבלי/ראשונים/רן",
    # אחרונים ולמדנות בת-זמננו (סגנון קונטרסים)
    "אוצריא/תלמוד בבלי/אחרונים/פני יהושע",
    "אוצריא/תלמוד בבלי/אחרונים/נחלת דוד",
    "אוצריא/תלמוד בבלי/מחברי זמננו/רשימות שיעורים",
    # מחברי זמננו על נזיקין — ביאור חברותא והערותיו: עברית ישיבתית עכשווית.
    # (אילת השחר/דרכי החיים של ר' שטיינמן ור' אדלשטיין אינם קיימים באוצריא —
    # נבדק בעץ הקבצים המלא 07/2026; אלו התחליפים הקרובים בסגנון ובדומיין)
    "אוצריא/תלמוד בבלי/מחברי זמננו/ביאור חברותא/חברותא על בבא קמא.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/ביאור חברותא/חברותא על בבא מציעא.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/ביאור חברותא/חברותא על בבא בתרא.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/ביאור חברותא/חברותא על סנהדרין.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/ביאור חברותא/חברותא על שבועות.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/ביאור חברותא/חברותא על מכות.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/הערות על ביאור חברותא/הערות על חברותא על בבא קמא.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/הערות על ביאור חברותא/הערות על חברותא על בבא מציעא.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/הערות על ביאור חברותא/הערות על חברותא על בבא בתרא.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/הערות על ביאור חברותא/הערות על חברותא על סנהדרין.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/הערות על ביאור חברותא/הערות על חברותא על שבועות.txt",
    "אוצריא/תלמוד בבלי/מחברי זמננו/הערות על ביאור חברותא/הערות על חברותא על מכות.txt",
    # חומר כללי — הלכה נפוצה, אוצר מילים רחב מעבר לדומיין נזיקין
    "אוצריא/הלכה/שולחן ערוך/מפרשים/משנה ברורה/משנה ברורה.txt",
    "אוצריא/הלכה/שולחן ערוך/מפרשים/משנה ברורה/ביאור הלכה.txt",
]
OTZARIA_DIR_FILTER = ("חושן משפט", "בבא קמא", "בבא מציעא", "בבא בתרא",
                      "סנהדרין", "שבועות", "מכות", "נזיקין", "קידושין",
                      "כתובות", "גיטין", "נדרים")


def _gh_json(url, ctx):
    import json
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
        return json.loads(r.read())


def fetch_otzaria(ctx, offline=False, max_mb=90):
    """מוריד (עם מטמון) את קובצי אוצריא הנבחרים; מחזיר רשימת טקסטים."""
    texts, total = [], 0
    files = []
    for src in OTZARIA_SOURCES:
        if src.endswith(".txt"):
            files.append(src)
            continue
        try:
            listing = _gh_json(
                "https://api.github.com/repos/" + OTZARIA_REPO + "/contents/"
                + urllib.parse.quote(src), ctx)
            for it in listing:
                if it["type"] == "file" and it["name"].endswith(".txt") and \
                        any(k in it["name"] for k in OTZARIA_DIR_FILTER):
                    files.append(src + "/" + it["name"])
        except Exception as e:
            print(f"  דילוג על תיקייה {src}: {e}")
    for path in files:
        cache_f = os.path.join(CACHE, "otz_" +
                               re.sub(r'[\\/:"*?<>|, ]', "_", path[-80:]) + ".txt")
        if os.path.exists(cache_f):
            with open(cache_f, encoding="utf-8") as f:
                texts.append(f.read())
            continue
        if offline:
            continue
        if total > max_mb * 1e6:
            print(f"  הגעת לתקרת ההורדה ({max_mb}MB) — דילוג על השאר")
            break
        url = ("https://raw.githubusercontent.com/" + OTZARIA_REPO + "/main/"
               + urllib.parse.quote(path))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=180, context=ctx) as r:
                raw = r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  שגיאה בהורדת {path}: {e}")
            continue
        total += len(raw.encode("utf-8", "ignore"))
        os.makedirs(CACHE, exist_ok=True)
        with open(cache_f, "w", encoding="utf-8") as f:
            f.write(raw)
        texts.append(raw)
        print(f"  אוצריא: {os.path.basename(path)} ({len(raw)//1024}KB)")
        time.sleep(0.3)
    return texts


# ---------------------------------------------------------------- הורדה
def _ssl_ctx():
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            return ssl.create_default_context()


def fetch(title, ctx):
    cache_f = os.path.join(CACHE, re.sub(r'[\\/:"*?<>|]', "_", title) + ".txt")
    if os.path.exists(cache_f):
        with open(cache_f, encoding="utf-8") as f:
            return f.read()
    url = ("https://he.wikisource.org/wiki/"
           + urllib.parse.quote(title.replace(" ", "_")) + "?action=raw")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception:
        text = ""
    os.makedirs(CACHE, exist_ok=True)
    with open(cache_f, "w", encoding="utf-8") as f:
        f.write(text)
    time.sleep(0.3)  # נימוס כלפי השרת
    return text


# ---------------------------------------------------------------- ניקוי
_RE_KILL = [
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<ref[^>]*>.*?</ref>", re.S),
    re.compile(r"<[^>]+>"),
    re.compile(r"\{\{[^{}]*\}\}"),          # תבניות (גם אחרי הסרה מקוננת)
    re.compile(r"__[A-Zא-ת]+__"),
    re.compile(r"^[=;#:*].*$", re.M),       # כותרות/רשימות ויקי
    re.compile(r"\[\[קטגוריה:[^\]]*\]\]"),
]
_RE_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_RE_NIKUD = re.compile(r"[֑-ׇ]")
_RE_QUOTES = re.compile(r"'{2,}")


def strip_wiki(text):
    for _ in range(3):  # תבניות מקוננות
        text = _RE_KILL[3].sub(" ", text)
    for rx in _RE_KILL:
        text = rx.sub(" ", text)
    text = _RE_LINK.sub(r"\1", text)
    text = _RE_QUOTES.sub("", text)
    text = _RE_NIKUD.sub("", unicodedata.normalize("NFC", text))
    text = text.replace("־", "-").replace("‏", "").replace("‎", "")
    return text


def to_lines(text, min_words=3, max_words=18):
    """מפרק טקסט לשורות משפט באורך טבעי לשורת כתב יד."""
    out = []
    text = re.sub(r"\s+", " ", text)
    # פיצול לפי סוף משפט
    for sent in re.split(r"(?<=[.:;!?])\s+", text):
        sent = sent.strip()
        if not sent:
            continue
        words = sent.split()
        while words:
            chunk = words[:max_words]
            words = words[max_words:]
            if len(chunk) < min_words and out:
                # שארית קצרצרה — מצמידים לשורה הקודמת אם היא לא ארוכה מדי
                if len(out[-1].split()) + len(chunk) <= max_words + 4:
                    out[-1] = out[-1] + " " + " ".join(chunk)
                    continue
            line = clean(" ".join(chunk)).strip()
            heb = sum(1 for w in line.split() if re.search(r"[א-ת]", w))
            if heb >= min_words:
                out.append(line)
    return out


# ---------------------------------------------------------------- בנייה
def main(offline=False):
    lines, seen = [], set()

    def add(line):
        if line and line not in seen:
            seen.add(line)
            lines.append(line)

    # 1. הקורפוס הקיים (עברית מודרנית — נשמר, חשוב לגיוון)
    if os.path.exists(CORPUS):
        with open(CORPUS, encoding="utf-8") as f:
            for l in f:
                add(clean(l.strip()))
    n_base = len(lines)

    # 2. הטקסט המוקלד המלא של הקונטרס (הדומיין המדויק של הכותב)
    if os.path.exists(KUNTRES):
        with open(KUNTRES, encoding="utf-8") as f:
            for l in to_lines(strip_wiki(f.read())):
                add(l)
    n_kuntres = len(lines) - n_base

    # 3. ויקיטקסט
    n_pages = 0
    if True:
        ctx = _ssl_ctx()
        titles = source_titles()
        for i, t in enumerate(titles):
            if offline and not os.path.exists(
                    os.path.join(CACHE, re.sub(r'[\\/:"*?<>|]', "_", t) + ".txt")):
                continue
            raw = fetch(t, ctx)
            if raw and len(raw) > 200 and "#REDIRECT" not in raw and \
                    "#הפניה" not in raw:
                n_pages += 1
                for l in to_lines(strip_wiki(raw)):
                    add(l)
            if (i + 1) % 40 == 0:
                print(f"  {i + 1}/{len(titles)} דפים, {len(lines)} שורות עד כה",
                      flush=True)
    n_wiki = len(lines) - n_base - n_kuntres

    # 4. אוצריא (גמרא, שו"ע חו"מ ומפרשיו)
    for raw in fetch_otzaria(_ssl_ctx(), offline=offline):
        for l in to_lines(strip_wiki(raw)):
            add(l)
    n_otz = len(lines) - n_base - n_kuntres - n_wiki

    if os.path.exists(CORPUS):
        bak = CORPUS + ".bak"
        if not os.path.exists(bak):
            import shutil
            shutil.copy2(CORPUS, bak)
    with open(CORPUS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"קורפוס: {len(lines)} שורות "
          f"(בסיס {n_base} + קונטרס {n_kuntres} + ויקיטקסט {n_wiki} מ-{n_pages} דפים"
          f" + אוצריא {n_otz})")
    print(f"נשמר: {CORPUS}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    main(args.offline)
