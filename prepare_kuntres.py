# -*- coding: utf-8 -*-
"""פילוח סריקות המחברת (דיו כחול על דף שורות) לשורות בודדות.

הטריק המרכזי: בערוץ האדום של התמונה, הדיו הכחול כהה מאוד ואילו קווי השורות
התכולים בהירים — כך קווי המחברת נעלמים כמעט לגמרי עוד לפני הבינאריזציה.

שימוש:  python prepare_kuntres.py <מספר עמוד> [--min-height 25]
פלט:    data/kuntres_lines/page_NNN/line_XX.png
"""
import os
import sys
import argparse
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCANS = os.path.join(HERE, "data", "raw_scans", "סריקות סיכומי סוגיות להקלדה")
OUT = os.path.join(HERE, "data", "kuntres_lines")

from segment import otsu_threshold, find_line_bands


def load_red_channel(path, max_side=2600):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > max_side:
        s = max_side / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.BILINEAR)
    r, g, b = img.split()
    return np.array(r, dtype=np.float32)


def _long_horizontal_runs(ink, min_run=80, max_gap=10):
    """מסכה של רצפים אופקיים ארוכים — קווי המחברת וקווי הדגשה (לא כתב יד)."""
    h, w = ink.shape
    rule = np.zeros_like(ink)
    row_frac = ink.mean(axis=1)
    for y in range(h):
        # רק שורות-פיקסלים צפופות חריג — חתימה של קו מחברת, לא של כתב יד
        if row_frac[y] < 0.15:
            continue
        row = ink[y]
        # זיהוי רצפים: מאפשרים חורים קטנים בתוך רצף (הקו שבור בערוץ האדום)
        padded = np.concatenate(([False], row, [False]))
        starts = np.where(~padded[:-1] & padded[1:])[0]
        ends = np.where(padded[:-1] & ~padded[1:])[0]
        merged = []
        for s, e in zip(starts, ends):
            if merged and s - merged[-1][1] <= max_gap:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        for s, e in merged:
            if e - s >= min_run:
                rule[y, s:e] = True
    # הרחבה אנכית קלה של הקווים שנמצאו (עובי הקו + אנטי-אליאסינג)
    grown = rule.copy()
    grown[1:] |= rule[:-1]
    grown[:-1] |= rule[1:]
    return grown


def clean_mask(arr):
    """מסכת דיו נקייה + מסכת קווים למחיקה: בלי קווי מחברת, קו שוליים ושולי סריקה."""
    t = otsu_threshold(arr)
    # מרווח ביטחון — קווי המחברת בהירים בערוץ האדום, הדיו כהה בהרבה
    ink = arr < min(t, 160)
    h, w = ink.shape
    # ביטול שולי הסריקה
    ink[:, :int(w * 0.03)] = False
    ink[:, -int(w * 0.03):] = False
    ink[:int(h * 0.015), :] = False
    ink[-int(h * 0.015):, :] = False
    rule = np.zeros_like(ink)
    # קו השוליים האנכי של המחברת + כל מה שמימין לו (הערות שוליים, בס"ד)
    col_frac = ink.mean(axis=0)
    vlines = np.where(col_frac > 0.3)[0]
    margin_lines = vlines[vlines > w * 0.6]
    if len(margin_lines):
        rule[:, max(0, margin_lines.max() - 6):] = True
    for x in vlines:
        x0, x1 = max(0, x - 6), min(w, x + 7)
        rule[:, x0:x1] = True
    # קווי מחברת אופקיים + קווי הדגשה מתחת למילים
    rule |= _long_horizontal_runs(ink & ~rule)
    return ink & ~rule, rule


def split_tall_bands(bands, ink):
    """מפצל רצועות גבוהות חריג (שורות שהתמזגו בגלל מילה שהוכנסה מעל שורה)
    בנקודת המינימום הפנימית של פרופיל הדיו."""
    if not bands:
        return bands
    heights = sorted(b - a for a, b in bands)
    med = heights[len(heights) // 2]
    out = []
    stack = list(bands)
    while stack:
        top, bottom = stack.pop(0)
        h = bottom - top
        if h < max(med * 1.7, 70):
            out.append((top, bottom))
            continue
        prof = ink[top:bottom].sum(axis=1).astype(np.float32)
        k = np.ones(7) / 7
        prof = np.convolve(prof, k, mode="same")
        lo, hi = int(h * 0.25), int(h * 0.75)
        if hi <= lo:
            out.append((top, bottom))
            continue
        cut = lo + int(np.argmin(prof[lo:hi]))
        # מפצלים רק אם באמת יש "עמק" — פחות מ-35% מהשיא
        if prof[cut] < prof.max() * 0.35:
            stack.insert(0, (top, top + cut))
            stack.insert(1, (top + cut, bottom))
        else:
            out.append((top, bottom))
    return sorted(out)


def segment_notebook_page(page_num, min_height=25, pad=10):
    path = os.path.join(SCANS, f"{page_num}.jpg")
    arr = load_red_channel(path)
    ink, rule = clean_mask(arr)
    arr = arr.copy()
    arr[rule] = 255  # מחיקת קווי המחברת מהתמונה עצמה
    bands = find_line_bands(ink, min_height=min_height, min_gap=10)
    bands = split_tall_bands(bands, ink)
    out_dir = os.path.join(OUT, f"page_{page_num:03d}")
    os.makedirs(out_dir, exist_ok=True)
    h, w = arr.shape
    crops = []
    for i, (top, bottom) in enumerate(bands):
        t0, b0 = max(0, top - pad), min(h, bottom + pad)
        band_ink = ink[t0:b0]
        cols = band_ink.sum(axis=0)
        xs = np.where(cols >= 2)[0]
        if len(xs) == 0:
            continue
        x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad)
        if x1 - x0 < 40:  # רסיסים
            continue
        crop = arr[t0:b0, x0:x1]
        # נרמול ניגודיות עדין
        crop = np.clip((crop - crop.min()) / max(1.0, crop.max() - crop.min()) * 255, 0, 255)
        p = os.path.join(out_dir, f"line_{len(crops):02d}.png")
        Image.fromarray(crop.astype(np.uint8)).save(p)
        crops.append((p, t0, b0, x0, x1))
    _save_map(page_num, arr, crops, out_dir)
    return crops


def _save_map(page_num, arr, crops, out_dir):
    """מפת עמוד: הסריקה עם מסגרות ממוספרות של כל חיתוך — לבקרה ויזואלית."""
    from PIL import ImageDraw, ImageFont
    img = Image.fromarray(arr.astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 54)
    except Exception:
        font = ImageFont.load_default()
    for i, (_, t0, b0, x0, x1) in enumerate(crops):
        d.rectangle([x0, t0, x1, b0], outline=(255, 0, 0), width=4)
        d.text((max(2, x0 - 70), (t0 + b0) // 2 - 27), str(i), fill=(200, 0, 0), font=font)
    img.save(os.path.join(out_dir, "_map.png"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("page", type=int)
    ap.add_argument("--min-height", type=int, default=25)
    args = ap.parse_args()
    crops = segment_notebook_page(args.page, args.min_height)
    print(f"page {args.page}: {len(crops)} lines")
    for p, t0, b0, x0, x1 in crops:
        print(f"  {os.path.basename(p)}  y={t0}-{b0}  x={x0}-{x1}")
