# -*- coding: utf-8 -*-
"""סימולציה סופית: כל נקודות הקצה, כולל החדשות (כללי/תצורה/העלאה)."""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:8767"  # פורט נקי לבדיקה
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(detail) if detail else ""))


def post(path, obj, raw=False):
    req = urllib.request.Request(URL + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return r.read() if raw else json.loads(r.read())


def get(path, raw=False):
    with urllib.request.urlopen(URL + path, timeout=60) as r:
        return r.read() if raw else json.loads(r.read())


env = dict(os.environ)
proc = subprocess.Popen([sys.executable, "-c",
                         "import app; app.PORT=8767; app.main()"],
                        cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(45):
        time.sleep(1)
        try:
            get("/api/writers")
            break
        except OSError:
            continue

    # 1. תצורה
    cfg = get("/api/config")
    check("config get (upload_url baked)", "script.google.com" in cfg.get("upload_url", ""),
          cfg.get("upload_url", "")[:60])

    # 2. עדכון מודל כללי מקובץ (משתמשים בקובץ הכללי האמיתי)
    gp = os.path.join(HERE, "models", "general.pt")
    with open(gp, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    r = post("/api/import_general", {"file": b64})
    check("import_general", r.get("ok"), r.get("msg"))

    # 3. אימון בהיקפים — רק בדיקת תגובת API (אימון אמיתי רץ ברקע => busy)
    r = post("/api/train", {"writer": "אישי", "scope": "general"})
    check("train scope=general responds", "ok" in r, r.get("msg", "")[:60])

    # 4. סטטוס אימון דינמי
    st = get("/api/train_status")
    check("train_status", isinstance(st.get("running"), bool),
          f"running={st.get('running')} step={st.get('step')}")

    # 5. תמלול עמוד אמיתי + ודיקת שדות חדשים (conf/note/progress)
    scan = os.path.join(HERE, "data", "raw_scans",
                        "סריקות סיכומי סוגיות להקלדה", "5.jpg")
    with open(scan, "rb") as f:
        img64 = base64.b64encode(f.read()).decode()
    job = post("/api/transcribe", {"files": [{"name": "עמוד5.jpg", "data": img64}],
                                   "page": True, "writer": "אישי",
                                   "prefer": "auto", "fix": True})["job"]
    got, progress_moved = 0, False
    while True:
        time.sleep(1)
        s = post("/api/transcribe_status", {"job": job, "from": got})
        got += len(s["lines"])
        if 0 < s.get("progress", 0) < 1:
            progress_moved = True
        if s["done"] or s["error"]:
            break
    s_all = post("/api/transcribe_status", {"job": job, "from": 0})
    has_conf = all("conf" in l for l in s_all["lines"])
    has_note_field = all("note" in l for l in s_all["lines"])
    check("transcribe page5", s_all["error"] is None and got > 15, f"{got} lines")
    check("line-level progress moved", progress_moved)
    check("conf+note fields", has_conf and has_note_field)

    # 6. ייצוא Word מעוצב (כולל פסקת הערה)
    docx = post("/api/export_docx", {"paragraphs": ["כותרת בדיקה.",
                                                    "(הערה: הערת בדיקה)"]}, raw=True)
    import zipfile, io
    z = zipfile.ZipFile(io.BytesIO(docx))
    xml = z.read("word/document.xml").decode("utf-8")
    check("styled docx", b"PK" == docx[:2] and "David" in xml and "הערת בדיקה" in xml,
          f"{len(docx)}b")

    # 7. העלאה לדרייב — צנרת מלאה (ההצלחה בפועל תלויה באישור החד-פעמי שלך)
    r = post("/api/upload_pack", {"writer": "אישי"})
    check("upload_pack plumbing", "msg" in r, r.get("msg", "")[:70])

    # 8. מחיקת קובצי אימון — על כותב זמני בלבד (לא נוגע בנתונים אמיתיים)
    tmpw = "בדיקת_מחיקה_זמני"
    post("/api/writers", {"name": tmpw})
    wdir = os.path.join(HERE, "data", "writers", tmpw)
    with open(os.path.join(wdir, "labels.tsv"), "w", encoding="utf-8") as f:
        f.write("x.png\tבדיקה\n")
    running = get("/api/train_status").get("running")
    r = post("/api/delete_train_data", {"writer": tmpw})
    if running:
        check("delete_train_data blocked during training", not r.get("ok"),
              r.get("msg", ""))
    else:
        check("delete_train_data", r.get("ok") and
              not os.path.exists(os.path.join(wdir, "labels.tsv")),
              r.get("msg", ""))
    import shutil
    shutil.rmtree(wdir, ignore_errors=True)

finally:
    proc.terminate()

fails = [x for x in results if not x[1]]
print(f"\n=== {len(results) - len(fails)}/{len(results)} passed ===")
sys.exit(1 if fails else 0)
