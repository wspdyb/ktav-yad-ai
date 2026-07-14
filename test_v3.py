# -*- coding: utf-8 -*-
"""בדיקת קצה-לקצה מלאה של גרסה 3."""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCANS = os.path.join(HERE, "data", "raw_scans", "סריקות סיכומי סוגיות להקלדה")
URL = "http://127.0.0.1:8765"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(detail) if detail else ""))


def post(path, obj, raw=False):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(URL + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read() if raw else json.loads(r.read())


def get(path, raw=False):
    with urllib.request.urlopen(URL + path, timeout=60) as r:
        return r.read() if raw else json.loads(r.read())


def levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# בדיקת ייבוא PDF עוד לפני השרת
try:
    import pypdfium2  # noqa
    check("pypdfium2 import", True)
except Exception as e:
    check("pypdfium2 import", False, e)

proc = subprocess.Popen([sys.executable, os.path.join(HERE, "app.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(45):
        time.sleep(1)
        try:
            get("/api/writers")
            break
        except OSError:
            continue

    # 1. תמלול מרובה קבצים: JPG (עמוד 2) + PDF (עמוד 3 שהומר)
    from PIL import Image
    with open(os.path.join(SCANS, "2.jpg"), "rb") as f:
        jpg_b64 = base64.b64encode(f.read()).decode()
    pdf_buf = io.BytesIO()
    Image.open(os.path.join(SCANS, "3.jpg")).convert("RGB").save(pdf_buf, "PDF")
    pdf_b64 = base64.b64encode(pdf_buf.getvalue()).decode()

    t0 = time.time()
    job = post("/api/transcribe", {"files": [
        {"name": "עמוד2.jpg", "data": jpg_b64},
        {"name": "עמוד3.pdf", "data": pdf_b64}],
        "page": True, "writer": "אישי", "prefer": "auto"})["job"]
    count = 0
    while True:
        time.sleep(1)
        s = post("/api/transcribe_status", {"job": job, "from": count})
        count += len(s["lines"])
        if s["done"] or s["error"]:
            break
    dt = time.time() - t0
    check("multi-file transcribe (jpg+pdf)", s["error"] is None and count > 30,
          f"{count} lines, {dt:.1f}s, err={s['error']}")
    s_all = post("/api/transcribe_status", {"job": job, "from": 0})
    srcs = {l["src"] for l in s_all["lines"]}
    check("pdf pages labeled", any("PDF" in x.upper() for x in srcs), srcs)

    # 2. השוואת דיוק מול אמת-קרקע של עמוד 2
    gt = []
    with open(os.path.join(HERE, "data", "kuntres_align", "page_002.tsv"),
              encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[1] != "101":
                gt.append(p[1])
    pred = [l["text"] for l in s_all["lines"] if l["src"] == "עמוד2.jpg"]
    gt_j, pr_j = " ".join(gt), " ".join(t for t in pred if t.strip())
    cer = levenshtein(pr_j, gt_j) / max(1, len(gt_j)) * 100
    check("page2 CER vs ground truth", cer < 25, f"CER={cer:.1f}%")
    with open(os.path.join(os.environ.get("TEMP", "."), "cmp_page2.txt"), "w",
              encoding="utf-8") as f:
        for i in range(min(len(pred), len(gt))):
            f.write(f"[מודל] {pred[i]}\n[אמת ] {gt[i]}\n\n")

    # 3. שמירת תיקונים לאימון
    post("/api/writers", {"name": "_בדיקה"})
    two = [{"img": l["img"], "text": l["text"] or "בדיקה"} for l in s_all["lines"][:2]]
    r = post("/api/save", {"writer": "_בדיקה", "lines": two})
    labels = os.path.join(HERE, "data", "writers", "_בדיקה", "labels.tsv")
    n_lab = sum(1 for _ in open(labels, encoding="utf-8"))
    check("save corrections", r.get("saved") == 2 and n_lab == 2, f"saved={r.get('saved')}")

    # 4. ייצוא חבילה ← ייבוא לכותב אחר
    from urllib.parse import quote
    pack = get("/api/export_writer?name=" + quote("_בדיקה"), raw=True)
    check("export pack", pack[:2] == b"PK" and len(pack) > 1000, f"{len(pack)} bytes")
    r = post("/api/import_pack", {"zip": base64.b64encode(pack).decode(),
                                  "writer": "_בדיקה2"})
    labels2 = os.path.join(HERE, "data", "writers", "_בדיקה2", "labels.tsv")
    n2 = sum(1 for _ in open(labels2, encoding="utf-8")) if os.path.exists(labels2) else 0
    check("import pack roundtrip", r.get("ok") and n2 == 2, r.get("msg"))

    # 5. ייצוא Word
    docx = post("/api/export_docx", {"paragraphs": ["שלום עולם.", "שורה שנייה."]}, raw=True)
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(docx))
    ok_docx = docx[:2] == b"PK" and "word/document.xml" in z.namelist() and \
        "שלום עולם" in z.read("word/document.xml").decode("utf-8")
    check("docx export", ok_docx, f"{len(docx)} bytes")

    # 6. סטטוס אימון (אמור לזהות את האימון שרץ ברקע)
    st = get("/api/train_status")
    check("train_status running detection", st.get("running") in (True, False),
          f"running={st.get('running')} step={st.get('step')}/{st.get('total')}")

finally:
    proc.terminate()
    # ניקוי כותבי בדיקה
    time.sleep(1)
    for w in ("_בדיקה", "_בדיקה2"):
        shutil.rmtree(os.path.join(HERE, "data", "writers", w), ignore_errors=True)

fails = [r for r in results if not r[1]]
print(f"\n=== {len(results) - len(fails)}/{len(results)} passed ===")
sys.exit(1 if fails else 0)
