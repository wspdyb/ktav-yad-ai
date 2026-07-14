# -*- coding: utf-8 -*-
"""שערי הזנה בטוחה — לפי סעיף 6 בתרשים הבנייה.

כל דוגמה חדשה (תמונת שורה + תיוג) עוברת שלושה שערים לפני שהיא נכנסת לאימון:
  שער 1 — פורמט: תמונה תקינה בגודל סביר, טקסט לא ריק אחרי סינון מפת התווים.
  שער 2 — סתירה מול המודל: אם תמלול המודל רחוק קיצונית מהתיוג (CER גבוה מאוד)
           הדוגמה חשודה (תיוג שגוי / הצמדה שהחליקה שורה) ועוברת להסגר.
  שער 3 — עקביות פנימית: אותה תמונה בדיוק עם תיוג שונה => הסגר (סתירה);
           אותה תמונה עם אותו תיוג => דילוג שקט (כפילות).

דוגמה שנעצרת לא נזרקת: היא נשמרת ב"הסגר" (quarantine) של הכותב וממתינה
לאישור/דחייה ידניים בממשק. שער 4 (רגרסיה + rollback) ממומש ב-train.py.
"""
import os
import json
import hashlib

import numpy as np

from charset import clean
from paths import WRITERS_DIR

# ספי שער 2 — שמרניים בכוונה: עוצרים רק סתירות קיצוניות, לא כתב יד קשה
GATE2_MIN_LEN = 8      # טקסטים קצרים מזה לא נבדקים (CER לא יציב עליהם)
GATE2_CER = 0.65       # מעל זה — הדוגמה חשודה כסותרת

MAX_TEXT_LEN = 300
MIN_IMG_SIDE = 8
MAX_IMG_SIDE = 6000


def _levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _cer(pred, truth):
    if not truth:
        return 0.0 if not pred else 1.0
    return _levenshtein(pred, truth) / len(truth)


def img_hash(pil_img):
    """טביעת אצבע של הפיקסלים עצמם (לא של קובץ ה-PNG) — עמידה לקידוד חוזר."""
    a = np.asarray(pil_img.convert("L"), dtype=np.uint8)
    return hashlib.sha1(a.tobytes() + str(a.shape).encode()).hexdigest()


# ---------------------------------------------------------------- אינדקס כפילויות
def _hash_index_path(writer):
    return os.path.join(WRITERS_DIR, writer, ".hashes.json")


def load_hash_index(writer):
    """מדד hash->text של כל השורות הקיימות. נבנה פעם אחת ומתעדכן בכל שמירה."""
    p = _hash_index_path(writer)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    # בנייה ראשונית מהשורות הקיימות
    from PIL import Image
    idx = {}
    wdir = os.path.join(WRITERS_DIR, writer)
    labels = os.path.join(wdir, "labels.tsv")
    if os.path.exists(labels):
        with open(labels, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                fp = os.path.join(wdir, "lines", parts[0])
                if os.path.exists(fp):
                    try:
                        idx[img_hash(Image.open(fp))] = parts[1]
                    except Exception:
                        continue
    save_hash_index(writer, idx)
    return idx


def save_hash_index(writer, idx):
    os.makedirs(os.path.join(WRITERS_DIR, writer), exist_ok=True)
    with open(_hash_index_path(writer), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)


# ---------------------------------------------------------------- השערים
def gate1_format(pil_img, text):
    """שער 1. מחזיר (טקסט נקי, None) אם עבר, או (None, סיבה) אם נפסל."""
    if pil_img is None:
        return None, "תמונה פגומה"
    w, h = pil_img.size
    if w < MIN_IMG_SIDE or h < MIN_IMG_SIDE or w > MAX_IMG_SIDE or h > MAX_IMG_SIDE:
        return None, f"מידות תמונה חריגות ({w}x{h})"
    t = clean(text.strip().replace("\t", " "))
    if not t:
        return None, "טקסט ריק (או שכולו תווים שאינם במפת התווים)"
    if len(t) > MAX_TEXT_LEN:
        return None, f"טקסט ארוך מדי ({len(t)} תווים)"
    return t, None


def check_lines(writer, pil_text_pairs, predict_fn=None):
    """מריץ את שערים 1-3 על רשימת (תמונה, טקסט).

    predict_fn: פונקציה אופציונלית שמקבלת תמונת PIL ומחזירה תמלול —
    מפעילה את שער 2. בלעדיה נבדקים רק שערים 1 ו-3.

    מחזיר (accepted, quarantined, dups):
      accepted    — [(pil, text)] שורות שעברו הכול
      quarantined — [(pil, text, reason)] שורות חשודות להסגר
      dups        — מספר כפילויות מדויקות שדולגו בשקט
    """
    idx = load_hash_index(writer)
    accepted, quarantined, dups = [], [], 0
    batch_hashes = {}
    for pil, text in pil_text_pairs:
        # שער 1
        t, reason = gate1_format(pil, text)
        if reason:
            if pil is not None and text.strip():
                quarantined.append((pil, text.strip(), f"שער 1: {reason}"))
            continue
        # שער 3 — מול הקיים ומול שורות אחרות באותה שמירה
        h = img_hash(pil)
        prev = idx.get(h, batch_hashes.get(h))
        if prev is not None:
            if prev == t:
                dups += 1          # כפילות מדויקת — אין מה לשמור שוב
                continue
            quarantined.append((pil, t, "שער 3: אותה תמונה כבר קיימת עם תיוג שונה"
                                        f' ("{prev[:40]}")'))
            continue
        # שער 2 — סתירה קיצונית מול תמלול המודל
        if predict_fn is not None and len(t) >= GATE2_MIN_LEN:
            try:
                pred = predict_fn(pil)
            except Exception:
                pred = None
            if pred is not None:
                c = _cer(pred, t)
                if c > GATE2_CER:
                    quarantined.append(
                        (pil, t, f"שער 2: פער קיצוני מול המודל (CER {c*100:.0f}%) — "
                                 "ייתכן שהטקסט לא שייך לשורה הזו"))
                    continue
        batch_hashes[h] = t
        accepted.append((pil, t))
    # עדכון האינדקס עם מה שהתקבל
    if batch_hashes:
        idx.update(batch_hashes)
        save_hash_index(writer, idx)
    return accepted, quarantined, dups


# ---------------------------------------------------------------- הסגר
def _qdir(writer):
    return os.path.join(WRITERS_DIR, writer, "quarantine")


def _qtsv(writer):
    return os.path.join(_qdir(writer), "quarantine.tsv")


def quarantine_add(writer, items):
    """items: [(pil, text, reason)] — שומר להסגר של הכותב."""
    if not items:
        return 0
    import time
    qd = _qdir(writer)
    os.makedirs(qd, exist_ok=True)
    n_exist = len(quarantine_list(writer))
    with open(_qtsv(writer), "a", encoding="utf-8") as f:
        for k, (pil, text, reason) in enumerate(items):
            fname = f"q_{int(time.time())}_{n_exist + k:04d}.png"
            pil.save(os.path.join(qd, fname))
            f.write(f"{fname}\t{text}\t{reason}\n")
    return len(items)


def quarantine_list(writer):
    """[{file, text, reason}] — כל השורות שממתינות בהסגר."""
    out = []
    try:
        with open(_qtsv(writer), encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and \
                        os.path.exists(os.path.join(_qdir(writer), parts[0])):
                    out.append({"file": parts[0], "text": parts[1],
                                "reason": parts[2] if len(parts) > 2 else ""})
    except OSError:
        pass
    return out


def quarantine_resolve(writer, fname, approve, text=None):
    """מכריע על שורה בהסגר: אישור מעביר אותה לאימון, דחייה מוחקת אותה.
    מחזיר (ok, הודעה)."""
    from PIL import Image
    items = quarantine_list(writer)
    match = next((it for it in items if it["file"] == fname), None)
    if match is None:
        return False, "השורה לא נמצאה בהסגר"
    src = os.path.join(_qdir(writer), fname)
    ok_msg = "נדחתה ונמחקה"
    if approve:
        t, reason = gate1_format(Image.open(src), text if text is not None
                                 else match["text"])
        if reason:
            return False, f"אי אפשר לאשר: {reason}"
        wdir = os.path.join(WRITERS_DIR, writer)
        ldir = os.path.join(wdir, "lines")
        os.makedirs(ldir, exist_ok=True)
        new_name = "appr_" + fname
        img = Image.open(src).convert("L")
        img.save(os.path.join(ldir, new_name))
        with open(os.path.join(wdir, "labels.tsv"), "a", encoding="utf-8") as f:
            f.write(f"{new_name}\t{t}\n")
        idx = load_hash_index(writer)
        idx[img_hash(img)] = t
        save_hash_index(writer, idx)
        ok_msg = "אושרה ונוספה לאימון"
    # הסרה מההסגר (גם באישור וגם בדחייה)
    remaining = [it for it in items if it["file"] != fname]
    try:
        os.remove(src)
    except OSError:
        pass
    with open(_qtsv(writer), "w", encoding="utf-8") as f:
        for it in remaining:
            f.write(f"{it['file']}\t{it['text']}\t{it['reason']}\n")
    return True, ok_msg


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from PIL import Image
    # בדיקה עצמית קצרה על נתונים אמיתיים של הכותב "אישי"
    w = "אישי"
    wdir = os.path.join(WRITERS_DIR, w)
    with open(os.path.join(wdir, "labels.tsv"), encoding="utf-8") as f:
        rows = [l.rstrip("\n").split("\t") for l in f if "\t" in l][:3]
    pairs = []
    for fname, text in rows:
        pairs.append((Image.open(os.path.join(wdir, "lines", fname)), text))
    # 1) כפילות מדויקת -> dups
    acc, quar, dups = check_lines(w, pairs)
    print(f"existing lines resubmitted: accepted={len(acc)} quar={len(quar)} dups={dups}")
    assert dups == len(pairs) and not acc and not quar
    # 2) אותה תמונה עם טקסט אחר -> הסגר (שער 3)
    acc, quar, dups = check_lines(w, [(pairs[0][0], "טקסט אחר לגמרי")])
    print(f"conflicting label: accepted={len(acc)} quar={len(quar)} ({quar[0][2] if quar else ''})")
    assert len(quar) == 1
    # 3) טקסט ריק -> נפסל בשקט בשער 1 (בלי הסגר כי אין תוכן)
    acc, quar, dups = check_lines(w, [(pairs[0][0], "   ")])
    assert not acc and not quar
    print("gates self-test OK")
