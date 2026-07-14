# -*- coding: utf-8 -*-
"""בדיקת עמוד-מסך: עמוד טקסט "מוקלד" בגופן מסך קטן (כמו צילום מסך),
מפולח ומתומלל בצינור המלא — מודד את תמיכת המודל בטקסט מוקלד/צילומי מסך.

שימוש:  python test_screenshot.py --make      (יצירת העמוד וה-GT — חד-פעמי)
        python test_screenshot.py [--model general|writer] [--font "Segoe UI"]
הנכסים נשמרים ב-data/test_assets/ (קבועים — לא ליצור מחדש בין השוואות!).
"""
import os
import random
import sys
import argparse

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "data", "test_assets")
PAGE = os.path.join(ASSETS, "screenshot_page.png")
GT = os.path.join(ASSETS, "screenshot_page_gt.txt")

sys.path.insert(0, HERE)
from charset import clean, to_visual  # noqa: E402


def make_page(font_name="Segoe UI", font_px=17, n_lines=18, seed=20260714):
    """עמוד דמוי-צילום-מסך: טקסט מוקלד קטן על רקע לבן, ללא שורות מחברת."""
    rng = random.Random(seed)
    with open(os.path.join(HERE, "data", "corpus_he.txt"), encoding="utf-8") as f:
        pool = [clean(l.strip()) for l in f if 4 <= len(l.split()) <= 10]
    lines = [pool[rng.randrange(len(pool))] for _ in range(n_lines)]
    W, H, margin, spacing = 900, 80 + n_lines * 34, 60, 34
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    font = None
    for f in os.listdir(fonts_dir):
        p = os.path.join(fonts_dir, f)
        if not f.lower().endswith((".ttf", ".ttc")):
            continue
        try:
            if ImageFont.truetype(p, font_px).getname()[0] == font_name:
                font = ImageFont.truetype(p, font_px)
                break
        except Exception:
            continue
    if font is None:
        raise RuntimeError(f"גופן {font_name} לא נמצא")
    y = 50
    for line in lines:
        vis = to_visual(line)
        w = draw.textlength(vis, font=font)
        draw.text((W - margin - w, y), vis, font=font, fill=20)
        y += spacing
    os.makedirs(ASSETS, exist_ok=True)
    img.save(PAGE)
    with open(GT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"נוצר: {PAGE} ({n_lines} שורות, {font_name} {font_px}px)")


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


def run(which):
    import torch
    from paths import MODELS_DIR
    from charset import CHARSET, NUM_CLASSES
    from model import load_checkpoint
    from segment import segment_page_ex
    from infer import transcribe_rescued
    import postfix
    name = {"writer": "writer_אישי.pt", "typed": "typed.pt"}.get(which, "general.pt")
    model, _ = load_checkpoint(os.path.join(MODELS_DIR, name), NUM_CLASSES, CHARSET)
    model.eval()
    torch.set_num_threads(2)
    gt_lines = [l.strip() for l in open(GT, encoding="utf-8") if l.strip()]
    items = segment_page_ex(PAGE)
    heights = sorted(im.height for im, _ in items)
    med_h = heights[len(heights) // 2] if heights else 1
    preds = []
    for im, meta in items:
        for _, t, _ in transcribe_rescued(model, im, med_h):
            t = postfix.fix_text(t).strip()
            if t:
                preds.append(t)
    gt_j, pr_j = " ".join(gt_lines), " ".join(preds)
    cer = lev(pr_j, gt_j) / max(1, len(gt_j)) * 100
    print(f"עמוד מסך ({which}): CER={cer:.2f}% "
          f"({len(preds)} שורות תחזית / {len(gt_lines)} GT)")
    return cer


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--model", default="general",
                    choices=["general", "writer", "typed"])
    ap.add_argument("--font", default="Segoe UI")
    args = ap.parse_args()
    if args.make:
        make_page(font_name=args.font)
    else:
        run(args.model)
