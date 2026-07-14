# -*- coding: utf-8 -*-
"""פילוח עמוד סרוק לשורות טקסט: יישור, בינאריזציה, וחיתוך לפי פרופיל דיו.

שימוש כקובץ עצמאי — קליטת עמוד תבנית מלא לתיקיית כותב:
  python segment.py --ingest scan.png --template page_001 --writer yaakov
"""
import os
import argparse
import numpy as np
from PIL import Image

from model import IMG_H

from paths import TEMPLATES_DIR, WRITERS_DIR  # noqa: F401

# ערך סף לסינון הנחיות התבנית המודפסות באפור בהיר
GRAY_PROMPT_THRESHOLD = 150


def load_gray(path, max_side=2600):
    img = Image.open(path).convert("L")
    w, h = img.size
    if max(w, h) > max_side:
        s = max_side / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.BILINEAR)
    return img


def otsu_threshold(arr):
    hist, _ = np.histogram(arr, bins=256, range=(0, 256))
    total = arr.size
    sum_all = np.dot(np.arange(256), hist)
    sum_b, w_b, best_t, best_var = 0.0, 0, 128, -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def deskew(img, max_angle=3.0, step=0.25):
    """מיישרת הטיה קלה של הסריקה לפי מקסימום שונות של פרופיל השורות."""
    small = img.resize((img.width // 3, img.height // 3), Image.BILINEAR)
    arr = np.array(small, dtype=np.float32)
    t = otsu_threshold(arr)
    best_angle, best_score = 0.0, -1.0
    angle = -max_angle
    while angle <= max_angle:
        rot = small.rotate(angle, resample=Image.BILINEAR, fillcolor=255)
        ink = (np.array(rot, dtype=np.float32) < t).sum(axis=1)
        score = float(np.var(ink))
        if score > best_score:
            best_score, best_angle = score, angle
        angle += step
    if abs(best_angle) >= step:
        img = img.rotate(best_angle, resample=Image.BILINEAR, fillcolor=255)
    return img


def find_line_bands(ink_mask, min_height=12, min_gap=4):
    """מזהה רצועות שורות לפי פרופיל דיו אופקי."""
    profile = ink_mask.sum(axis=1).astype(np.float32)
    if profile.max() <= 0:
        return []
    # החלקה
    k = 5
    kernel = np.ones(k) / k
    profile = np.convolve(profile, kernel, mode="same")
    thresh = max(2.0, profile.max() * 0.04)
    active = profile > thresh
    bands, start = [], None
    for y, a in enumerate(active):
        if a and start is None:
            start = y
        elif not a and start is not None:
            bands.append([start, y])
            start = None
    if start is not None:
        bands.append([start, len(active)])
    # מיזוג רצועות קרובות
    merged = []
    for b in bands:
        if merged and b[0] - merged[-1][1] < min_gap:
            merged[-1][1] = b[1]
        else:
            merged.append(b)
    return [(a, b) for a, b in merged if b - a >= min_height]


def _clean_linework(ink):
    """מנקה מהמסכה קווי שורות/הדגשה אופקיים ארוכים וקווי שוליים אנכיים —
    כדי שדפי מחברת לא ייצרו חיתוכי סרק. מחזירה (מסכה נקייה, מסכת הקווים)
    — מסכת הקווים משמשת גם למחיקת הקווים מהתמונה הנחתכת עצמה, כדי
    שהמודל לא "יקרא" קו הדגשה כאילו היה אותיות."""
    h, w = ink.shape
    # צילום מסך (תמונה קטנה) מול סריקה מנורמלת (2600): שומר-הטקסט למטה
    # פעיל רק בצילומי מסך — בסריקות הוא מנע ניקוי קווי מחברת (קו סרוק
    # רועש: כיסוי<0.9 ועובי>2.5) והכפיל את שגיאת התמלול (נמדד: עמ' 8
    # ‏5.1%→10.3%). בסריקות נשארת ההתנהגות המקורית בדיוק.
    small_page = max(h, w) < 2200
    orig = ink.copy()
    work = ink.copy()
    # קווים אנכיים מלאים (קו שוליים של מחברת)
    col_frac = work.mean(axis=0)
    for x in np.where(col_frac > 0.3)[0]:
        work[:, max(0, x - 6):min(w, x + 7)] = False
    # רצפים אופקיים ארוכים — ניקוי הדרגתי תוך כדי מעבר, בדיוק כבמקור:
    # שורת-פיקסלים שנוקתה כבר לא "מדביקה" את שכנותיה, אחרת שורות טקסט
    # שלמות נחצות באמצען (הבאג שגרם ל"ביטל"->"בילל")
    row_frac = work.mean(axis=1)
    for y in np.where(row_frac > 0.15)[0]:
        row = work[y]
        padded = np.concatenate(([False], row, [False]))
        starts = np.where(~padded[:-1] & padded[1:])[0]
        ends = np.where(padded[:-1] & ~padded[1:])[0]
        merged = []
        for s, e in zip(starts, ends):
            if merged and s - merged[-1][1] <= 10:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        for s, e in merged:
            if e - s >= 80:
                if small_page:
                    # שומר קו-אמיתי (צילומי מסך בלבד): קו מצויר רציף
                    # (כיסוי ~100% בשורת הטריגר), ואילו "קו" שגושר מאותיות
                    # טקסט קטן (14px) מלא רווחי אותיות (כיסוי <=85%) ופרוש
                    # אנכית. בלי השומר הניקוי כרסם שורות שלמות מהצילום.
                    cov = float(work[y, s:e].mean())
                    band = work[max(0, y - 4):min(h, y + 5), s:e]
                    col_rows = band.sum(axis=0)
                    inked = col_rows[col_rows > 0]
                    thick = float(inked.mean()) if len(inked) else 0.0
                    if cov < 0.9 and thick > 2.5:
                        continue    # טקסט מגושר — לא קו, לא מוחקים
                y0, y1 = max(0, y - 1), min(h, y + 2)
                work[y0:y1, s:e] = False
    # מסכת הקווים = בדיוק מה שנוקה (למחיקה מהתמונה אם יוחלט בעתיד)
    return work, orig & ~work


def split_tall_bands(bands, ink):
    """מפצל רצועות גבוהות חריג (שורות צפופות/הערות שהתמזגו) בעמק פרופיל הדיו."""
    if not bands:
        return bands
    heights = sorted(b - a for a, b in bands)
    med = heights[len(heights) // 2]
    out, stack = [], list(bands)
    while stack:
        top, bottom = stack.pop(0)
        h = bottom - top
        if h < max(med * 1.7, 70):
            out.append((top, bottom))
            continue
        prof = ink[top:bottom].sum(axis=1).astype(np.float32)
        prof = np.convolve(prof, np.ones(7) / 7, mode="same")
        lo, hi = int(h * 0.25), int(h * 0.75)
        if hi <= lo:
            out.append((top, bottom))
            continue
        cut = lo + int(np.argmin(prof[lo:hi]))
        if prof[cut] < prof.max() * 0.35:
            stack.insert(0, (top, top + cut))
            stack.insert(1, (top + cut, bottom))
        else:
            out.append((top, bottom))
    return sorted(out)


def _reattach_orphan_strips(bands):
    """מאחה "רצועות יתומות": פרופיל דיו חלש במותן האותיות מנתק לפעמים את
    רצועת הרגליים/הראשים מגוף השורה — הגוף נחתך (ויבואר -> וי בוא) והרצועה
    הופכת ל"שורה" של אות בודדת. רצועה נמוכה מאוד (<45% מהחציון) שצמודה
    לשכנתה (<35% מהחציון; רווח בין-שורות אמיתי גדול בהרבה) מוחזרת אליה.
    הערות/מספרי עמוד אמיתיים רחוקים מהשכנים ולא מושפעים."""
    if len(bands) < 2:
        return bands
    heights = sorted(b - a for a, b in bands)
    med = heights[len(heights) // 2]
    bands = list(bands)
    changed = True
    while changed:
        changed = False
        for i in range(len(bands)):
            a, b = bands[i]
            if b - a >= med * 0.45:
                continue
            gap_up = a - bands[i - 1][1] if i > 0 else 10 ** 9
            gap_dn = bands[i + 1][0] - b if i < len(bands) - 1 else 10 ** 9
            if min(gap_up, gap_dn) > med * 0.35:
                continue
            j = i - 1 if gap_up <= gap_dn else i + 1
            bands[j] = (min(bands[j][0], a), max(bands[j][1], b))
            del bands[i]
            changed = True
            break
    return bands


def split_crop_rows(pil_img, min_row=12, with_boxes=False):
    """מנסה לפצל חיתוך שמכיל שתי שורות דבוקות (שורה + שבר-שורה שמוזגו)
    לשתי תמונות נפרדות. משמש כ"חילוץ" בזמן תמלול: רק כשהביטחון של המודל
    על החיתוך המקורי נמוך מאוד. מחזירה [תמונה] אם אין פיצול בטוח,
    או [עליונה, תחתונה] אם נמצא עמק כמעט ריק בין שתי שורות.
    with_boxes=True: מחזירה [(תמונה, (x0,x1,y0,y1) בתוך החיתוך המקורי)].
    """
    def _wrap(items):
        return items if with_boxes else [im for im, _ in items]

    arr = np.array(pil_img.convert("L"), dtype=np.float32)
    h, w = arr.shape
    whole = [(pil_img, (0, w, 0, h))]
    if h < 56:
        return _wrap(whole)
    ink = arr < otsu_threshold(arr)
    prof = ink.sum(axis=1).astype(np.float32)
    prof = np.convolve(prof, np.ones(5) / 5, mode="same")
    lo, hi = int(h * 0.2), int(h * 0.8)
    if hi <= lo or prof.max() <= 0:
        return _wrap(whole)
    cut = lo + int(np.argmin(prof[lo:hi]))
    if prof[cut] > prof.max() * 0.18:   # אין הפרדה אמיתית — לא נוגעים
        return _wrap(whole)
    top = crop_line(arr, 0, cut, pad=2, with_box=True)
    bottom = crop_line(arr, cut, h, pad=2, with_box=True)
    out = [x for x in (top, bottom)
           if x is not None and x[0].height >= min_row
           and x[0].width >= x[0].height // 2]
    return _wrap(out if len(out) == 2 else whole)


def ink_span(pil_img, lo=0.03, hi=0.97):
    """טווח ה-X האפקטיבי של הדיו בתמונה לפי אחוזוני מסת הדיו — עמיד
    לפיקסלי רעש בודדים שמנפחים תיבה רגילה. מחזירה (שמאל, ימין, מרכז)
    או None אם אין דיו."""
    a = np.array(pil_img.convert("L"), dtype=np.float32)
    ink = a < otsu_threshold(a)
    cols = ink.sum(axis=0).astype(np.float64)
    total = cols.sum()
    if total <= 0:
        return None
    cum = np.cumsum(cols) / total
    x_left = int(np.searchsorted(cum, lo))
    x_right = int(np.searchsorted(cum, hi))
    x_center = int(np.searchsorted(cum, 0.5))
    return x_left, x_right, x_center


def crop_line(arr, top, bottom, pad=6, with_box=False):
    """חותכת שורה, מצמצמת רוחב לתוכן, ומחזירה תמונת PIL.
    with_box=True: מחזירה (תמונה, (x0,x1,y0,y1)) בפיקסלים של העמוד."""
    top = max(0, top - pad)
    bottom = min(arr.shape[0], bottom + pad)
    band = arr[top:bottom]
    t = otsu_threshold(band)
    cols = (band < t).sum(axis=0)
    xs = np.where(cols > 0)[0]
    if len(xs) == 0:
        return None
    x0, x1 = max(0, xs.min() - pad), min(band.shape[1], xs.max() + pad)
    img = Image.fromarray(band[:, x0:x1].astype(np.uint8))
    if with_box:
        return img, (int(x0), int(x1), int(top), int(bottom))
    return img


def _emphasis_spans(arr, rule, bands, w, h):
    """קווי-הדגשה שציירן הכותב מתחת למילים: קטעים במסכת הקווים שהם
    (א) קצרים מקו-מחברת מלא, (ב) דיו כהה (יד) או מחוץ לרשת הקווים,
    (ג) עם טקסט ממש מעליהם (מפריד-עמוד נכשל כאן). מחזירה
    {אינדקס_רצועה: [(x0,x1), ...]} בפיקסלים של העמוד. קריאה בלבד —
    לא נוגעת במסכות ולא במסלול הטקסט."""
    ink = arr < otsu_threshold(arr)
    out = {}
    for bi, (top, bottom) in enumerate(bands):
        cands = []      # (y, s, e) — קטעים כהים עם טקסט מעליהם
        y_hi = min(h, bottom + 10)
        for y in range(top + 6, y_hi):
            row = rule[y]
            if not row.any():
                continue
            padded = np.concatenate(([False], row, [False]))
            starts = np.where(~padded[:-1] & padded[1:])[0]
            ends = np.where(padded[:-1] & ~padded[1:])[0]
            for s, e in zip(starts, ends):
                if not (40 <= e - s <= w * 0.45):
                    continue
                stroke = arr[max(0, y - 1):y + 2, s:e]
                if float(np.percentile(stroke, 30)) >= 145:
                    continue
                above = ink[max(top, y - 45):max(top, y - 3), s:e]
                if above.size == 0 or float(above.mean()) < 0.06:
                    continue    # אין טקסט מעל — קו מפריד, לא הדגשה
                cands.append((y, int(s), int(e)))
        # איחוד דו-ממדי לקווים (קו גלי נתפס כקטעים בכמה שורות פיקסלים) —
        # איטרטיבי עד יציבות, אחרת שברי קו ארוך "הורגים" זה את זה
        # בבדיקת ההמשכיות שאחר כך
        cands.sort(key=lambda t: t[1])
        strokes = [[y, y, s, e] for y, s, e in cands]
        changed = True
        while changed:
            changed = False
            for i in range(len(strokes)):
                if strokes[i] is None:
                    continue
                for j in range(i + 1, len(strokes)):
                    if strokes[j] is None:
                        continue
                    a, b = strokes[i], strokes[j]
                    if b[0] <= a[1] + 6 and a[0] <= b[1] + 6 and \
                            b[2] <= a[3] + 120 and a[2] <= b[3] + 120:
                        a[0], a[1] = min(a[0], b[0]), max(a[1], b[1])
                        a[2], a[3] = min(a[2], b[2]), max(a[3], b[3])
                        strokes[j] = None
                        changed = True
        strokes = [s for s in strokes if s is not None]
        # ההכרעה: קו-מחברת מודפס ממשיך הרחק משני צידי הקטע; קו-הדגשה
        # של הכותב נעצר ליד המילה. בודקים המשכיות במסכת הקווים סביב
        # אותם גבהים — משופע-יישור עמיד (הרשת "בורחת" מסינון לפי שורות)
        spans = []
        for y0, y1, s, e in strokes:
            if e - s < 80:
                continue
            ry0, ry1 = max(0, y0 - 4), min(h, y1 + 5)
            left = rule[ry0:ry1, max(0, s - 110):max(1, s - 20)]
            right = rule[ry0:ry1, min(w - 1, e + 20):min(w, e + 110)]
            l_cont = float(left.any(axis=0).mean()) if left.size else 0.0
            r_cont = float(right.any(axis=0).mean()) if right.size else 0.0
            if l_cont > 0.55 and r_cont > 0.55:
                continue    # ממשיך לשני הכיוונים — קו מודפס, לא הדגשה
            spans.append((int(s), int(e)))
        if spans:
            out[bi] = sorted(spans)
    return out


def segment_page_ex(path, template_mode=False):
    """כמו segment_page אך מחזירה גם גיאומטריה לכל שורה:
    [(תמונה, meta)] כאשר meta = dict עם x0,x1,y0,y1 (בפיקסלים של העמוד
    המנורמל), page_w, page_h — הבסיס לייצוא שומר-פריסה ולסדר קריאה."""
    img = load_gray(path)
    # כתב בהיר על רקע כהה (צילום לוח/מסך כהה): הצינור מניח דיו כהה על רקע
    # בהיר, ולכן תמונה הפוכה מתהפכת אוטומטית. סריקה רגילה בהירה (ממוצע ~200+)
    # ולא מושפעת.
    if float(np.array(img, dtype=np.float32).mean()) < 118:
        img = Image.fromarray(255 - np.array(img, dtype=np.uint8))
    img = deskew(img)
    arr = np.array(img, dtype=np.float32)
    if template_mode:
        # בעמוד תבנית: ההנחיות מודפסות באפור בהיר — סף קשיח משאיר רק דיו כהה
        ink = arr < GRAY_PROMPT_THRESHOLD
    else:
        ink = arr < otsu_threshold(arr)
    # ניקוי שוליים (חורי תיוק, צל סורק)
    margin = int(arr.shape[1] * 0.02)
    ink[:, :margin] = False
    ink[:, -margin:] = False
    ink[:int(arr.shape[0] * 0.01), :] = False
    # הערה: הקווים מנוקים מהמסכה בלבד, לא מהתמונה — נבדק (eval12) שהלבנת
    # הקווים בתמונה עצמה מזיקה: המודל אומן על חיתוכים בלתי-מולבנים.
    ink, _rule = _clean_linework(ink)
    # צילום מסך (תמונה קטנה, טקסט 10-16px) מול סריקה (מנורמלת ל-2600):
    # בגובה-שורה מזערי 12 שורת מסך קטנה/אנגלית נופלת — סף מותאם לרזולוציה
    min_h = 12 if max(arr.shape) >= 2200 else 8
    bands = find_line_bands(ink, min_height=min_h)
    bands = split_tall_bands(bands, ink)
    bands = _reattach_orphan_strips(bands)
    h, w = arr.shape
    # קווי-הדגשה מתחת למילים (כתב מודגש) — קריאה בלבד, לא במסלול הטקסט
    try:
        emphasis = _emphasis_spans(arr, _rule, bands, w, h)
    except Exception:
        emphasis = {}
    out = []
    for bi, (top, bottom) in enumerate(bands):
        res = crop_line(arr, top, bottom, with_box=True)
        if res is None:
            continue
        line, (x0, x1, y0, y1) = res
        if line is None or line.width < line.height // 2:
            continue
        # סינון פסים דקים: אם כל הדיו (אחרי ניקוי קווים) מרוכז ברצועה
        # אנכית דקה מאוד — זה קו/מריחה ולא טקסט, ואין מה לתמלל
        band_ink = ink[y0:y1, x0:x1]
        rows_ink = band_ink.sum(axis=1)
        active = np.where(rows_ink >= 2)[0]
        if len(active) == 0 or active.max() - active.min() < 9 or \
                int(band_ink.sum()) < 30:
            continue
        meta = {"x0": int(x0), "x1": int(x1),
                "y0": int(y0), "y1": int(y1),
                "page_w": int(w), "page_h": int(h)}
        if bi in emphasis:
            # טווחי ההדגשה ביחס לחיתוך (אחרי קיצוץ הרוחב לתוכן)
            spans = [(max(0, s - int(x0)), min(int(x1) - int(x0), e - int(x0)))
                     for s, e in emphasis[bi]]
            spans = [(s, e) for s, e in spans if e - s >= 40]
            if spans:
                meta["em_spans"] = spans
        out.append((line, meta))
    return out


def segment_page(path, template_mode=False):
    """מחזירה רשימת תמונות שורה (PIL, גווני אפור) מעמוד סרוק, מלמעלה למטה."""
    return [im for im, _ in segment_page_ex(path, template_mode)]


def ingest_template(scan_path, template_name, writer):
    """קולט עמוד תבנית מלא: מפלח שורות ומצמיד לכל שורה את הטקסט הידוע מהתבנית."""
    labels_path = os.path.join(TEMPLATES_DIR, template_name + ".txt")
    if not os.path.exists(labels_path):
        raise SystemExit(f"לא נמצא קובץ תוויות לתבנית: {labels_path}")
    with open(labels_path, encoding="utf-8") as f:
        expected = [l.strip() for l in f if l.strip()]

    lines = segment_page(scan_path, template_mode=True)
    wdir = os.path.join(WRITERS_DIR, writer)
    ldir = os.path.join(wdir, "lines")
    os.makedirs(ldir, exist_ok=True)
    labels_file = os.path.join(wdir, "labels.tsv")

    if len(lines) != len(expected):
        review = os.path.join(wdir, "review", template_name)
        os.makedirs(review, exist_ok=True)
        for i, line in enumerate(lines):
            line.save(os.path.join(review, f"line_{i:02d}.png"))
        print(f"אזהרה: זוהו {len(lines)} שורות אך בתבנית יש {len(expected)} משפטים.")
        print(f"השורות נשמרו לבדיקה ידנית ב: {review}")
        print("אפשר לתייג אותן דרך הממשק הגרפי (app.py) או ידנית ב-labels.tsv")
        return 0

    existing = 0
    if os.path.exists(labels_file):
        with open(labels_file, encoding="utf-8") as f:
            existing = sum(1 for _ in f)
    with open(labels_file, "a", encoding="utf-8") as f:
        for i, (line, text) in enumerate(zip(lines, expected)):
            fname = f"{template_name}_{i:02d}.png"
            line.save(os.path.join(ldir, fname))
            f.write(f"{fname}\t{text}\n")
    total = existing + len(lines)
    print(f"נקלטו {len(lines)} שורות עבור '{writer}'. סה\"כ שורות מתויגות: {total}")
    return len(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", required=True, help="קובץ סריקה (PNG/JPG)")
    ap.add_argument("--template", required=True, help="שם תבנית, למשל page_001")
    ap.add_argument("--writer", required=True, help="שם הכותב")
    args = ap.parse_args()
    ingest_template(args.ingest, args.template, args.writer)
