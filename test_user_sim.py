# -*- coding: utf-8 -*-
"""סימולציית משתמש אמיתית מקצה-לקצה, דרך ה-API של התוכנה (לא קיצורי דרך):
1. תמלול עמוד אמיתי בממשק.
2. "תיקון" השורות לפי ה-GT (בדיוק מה שמשתמש אמיתי עושה) ושמירה דרך השערים.
3. שמירת התיקונים למודל התיקונים (קציר זוגות) + בדיקת הכרעת-רוב.
4. תיקון מורחב (suggest_page) על העמוד המלא — כולל מדידת זמן.
5. אימות שקובצי המודלים לא השתנו משום פעולת ממשק.
(צעד האימון עצמו נמדד בנפרד — train.py עם שער הרגרסיה.)

שימוש: python test_user_sim.py [עמוד=15]
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:8768"
PAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 15
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(detail) if detail else ""))


def post(path, obj):
    req = urllib.request.Request(URL + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def get(path):
    with urllib.request.urlopen(URL + path, timeout=60) as r:
        return json.loads(r.read())


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def lev(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


proc = subprocess.Popen([sys.executable, "-c",
                         "import app; app.PORT=8768; app.main()"],
                        cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        time.sleep(1)
        try:
            get("/api/writers")
            break
        except OSError:
            continue

    models = {f: md5(os.path.join(HERE, "models", f))
              for f in os.listdir(os.path.join(HERE, "models"))
              if f.endswith(".pt")}

    # 1. תמלול עמוד אמיתי
    scan = os.path.join(HERE, "data", "raw_scans",
                        "סריקות סיכומי סוגיות להקלדה", f"{PAGE}.jpg")
    with open(scan, "rb") as f:
        img64 = base64.b64encode(f.read()).decode()
    job = post("/api/transcribe", {"files": [{"name": f"עמוד{PAGE}.jpg",
                                              "data": img64}],
                                   "page": True, "writer": "אישי",
                                   "prefer": "auto", "fix": True})["job"]
    lines = []
    while True:
        time.sleep(1)
        s = post("/api/transcribe_status", {"job": job, "from": len(lines)})
        lines += s["lines"]
        if s["done"] or s["error"]:
            break
    check("תמלול עמוד בממשק", s["error"] is None and len(lines) > 15,
          f"{len(lines)} שורות")
    got_late_suggs = isinstance(s.get("suggs"), dict)
    check("עדכוני 💡 של המעבר השני הגיעו", got_late_suggs,
          f"{len(s.get('suggs') or {})} עדכונים")

    # 2. "תיקון" לפי GT ושמירה דרך השערים
    gt_lines = []
    with open(os.path.join(HERE, "data", "kuntres_align", f"page_{PAGE:03d}.tsv"),
              encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[1].strip():
                gt_lines.append(parts[1].strip())
    # יישור כמו משתמש אמיתי: לכל שורת תמלול — שורת ה-GT הדומה ביותר
    # (המשתמש מתקן את הטקסט של השורה עצמה, לא מדביק טקסט זר)
    def best_gt(pred):
        best, bd = None, 10 ** 9
        for g in gt_lines:
            d = lev(pred, g)
            if d < bd:
                best, bd = g, d
        return (best, bd / max(1, len(best))) if best else (None, 1.0)

    matched = []
    for l in lines:
        g, ratio = best_gt(l["text"])
        if g and ratio < 0.35:      # התאמה אמיתית בלבד
            matched.append((l, g))
    k = min(len(matched), 8)
    # נשמר לכותב זמני — לא מזהמים את נתוני המשתמש האמיתיים ("אישי")
    TMPW = "בדיקת_סימולציה_זמני"
    post("/api/writers", {"name": TMPW})
    to_save = [{"img": l["img"], "text": g} for l, g in matched[:k]]
    r = post("/api/save", {"writer": TMPW, "lines": to_save})
    # שער-הבטיחות עובד אם כל השורות התקבלו — כנשמרות או ככפילות (בהרצה חוזרת)
    check("שמירת תיקונים דרך השערים",
          r["saved"] + r["quarantined"] + r["dups"] == k and r["quarantined"] == 0,
          f"נשמרו {r['saved']} · הסגר {r['quarantined']} · כפולים {r['dups']}")

    # 3. מודל התיקונים: קציר מהעריכות + הכרעת רוב (היקף אישי לכותב הזמני)
    fx_items = [{"orig": l["text"], "final": g} for l, g in matched[:k]]
    r = post("/api/save_fixes", {"writer": TMPW, "scope": "personal",
                                 "lines": fx_items})
    check("למידת תיקונים מהעריכות", r.get("ok"), r.get("msg"))
    st = get("/api/fixes_stats?writer=" + urllib.parse.quote("אישי"))
    check("סטטיסטיקת תיקונים", st["general"] >= 14,
          f"אישי={st['personal']} כללי={st['general']}")

    # 4. תיקון מורחב על העמוד המלא + זמן
    t0 = time.time()
    r = post("/api/suggest_page", {"writer": "אישי",
                                   "lines": [{"text": l["text"],
                                              "src": l.get("src", "")}
                                             for l in lines]})
    dt = time.time() - t0
    check("תיקון מורחב לעמוד מלא", isinstance(r.get("suggs"), dict),
          f"{len(r['suggs'])} הצעות תוך {dt:.2f} שניות")
    check("תיקון מורחב מהיר (לא מאט את התוכנה)", dt < 5.0, f"{dt:.2f}s")
    # ההצעות משפרות CER מול GT?
    gt_j = " ".join(gt_lines)
    base_texts = [l["text"] for l in lines]
    sugg_texts = [r["suggs"].get(str(i), r["suggs"].get(i, t))
                  for i, t in enumerate(base_texts)]
    cer_b = lev(" ".join(base_texts), gt_j) / len(gt_j) * 100
    cer_s = lev(" ".join(sugg_texts), gt_j) / len(gt_j) * 100
    check("התיקון המורחב לא מזיק (CER)", cer_s <= cer_b + 0.01,
          f"{cer_b:.2f}% -> {cer_s:.2f}%")

    # 5. שום פעולת ממשק לא נגעה בקובצי המודלים
    after = {f: md5(os.path.join(HERE, "models", f))
             for f in models}
    check("קובצי המודלים לא השתנו", after == models)

finally:
    proc.terminate()

fails = [x for x in results if not x[1]]
print(f"\n=== {len(results) - len(fails)}/{len(results)} passed ===")
sys.exit(1 if fails else 0)
