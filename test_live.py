# -*- coding: utf-8 -*-
"""בדיקת קצה-לקצה של התמלול החי + מדידת זמן. מריץ שרת, שולח עמוד, מודד."""
import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(HERE, "data", "raw_scans", "סריקות סיכומי סוגיות להקלדה", "1.jpg")
URL = "http://127.0.0.1:8765"


def post(path, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(URL + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


proc = subprocess.Popen([sys.executable, os.path.join(HERE, "app.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(40):
        time.sleep(1)
        try:
            urllib.request.urlopen(URL + "/api/writers", timeout=3)
            break
        except OSError:
            continue
    with open(SCAN, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    t0 = time.time()
    job = post("/api/transcribe", {"img": img_b64, "page": True, "writer": "אישי"})["job"]
    first_line_t = None
    count = 0
    while True:
        time.sleep(0.7)
        s = post("/api/transcribe_status", {"job": job, "from": count})
        if s["count"] and first_line_t is None:
            first_line_t = time.time() - t0
        count = s["count"]
        if s["done"] or s["error"]:
            total_t = time.time() - t0
            print(f"DONE: {count} lines in {total_t:.1f}s "
                  f"(first line after {first_line_t:.1f}s), model={s['model']}, err={s['error']}")
            break
    s = post("/api/transcribe_status", {"job": job, "from": 0})
    out = os.path.join(os.environ.get("TEMP", "."), "live_result.txt")
    with open(out, "w", encoding="utf-8") as f:
        for l in s["lines"]:
            f.write(l["text"] + "\n")
    print("saved:", out)
finally:
    proc.terminate()
