# -*- coding: utf-8 -*-
"""יוצר עמודי איסוף כתב יד להדפסה.

כל עמוד מכיל 8 משפטים מודפסים באפור בהיר, ומתחת לכל אחד אזור כתיבה עם קו הנחיה.
הכותב מעתיק כל משפט בכתב ידו על הקו שמתחתיו. ההדפסה באפור מאפשרת למערכת
לסנן את הדפוס בסריקה ולהשאיר רק את כתב היד — כך התיוג אוטומטי לחלוטין.

שימוש:  python make_template.py [מספר עמודים, ברירת מחדל 10]
פלט:    data/templates/page_NNN.png (להדפסה) + page_NNN.txt (התוויות)
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

from paths import TEMPLATES_DIR as TEMPLATES, SYNTH_CORPUS as CORPUS

# A4 ב-200dpi
W, H = 1654, 2339
MARGIN = 110
LINES_PER_PAGE = 8
GRAY = 175        # גוון ההדפסה — בהיר מספיק כדי להימחק בסף 150 של segment.py
LIGHT_GRAY = 200


def find_font(names, size):
    import glob
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for path in glob.glob(os.path.join(fonts_dir, "*.tt[fc]")):
        try:
            f = ImageFont.truetype(path, size)
            if f.getname()[0] in names:
                return f
        except Exception:
            continue
    return ImageFont.load_default()


def rtl(text):
    """PIL מצייר משמאל לימין — הופכים לסדר חזותי עבור תצוגה בלבד."""
    from charset import to_visual
    return to_visual(text)


def render_page(name, batch, title_num):
    """מציירת עמוד תבנית אחד ושומרת PNG + קובץ תוויות."""
    os.makedirs(TEMPLATES, exist_ok=True)
    font_title = find_font({"David", "FrankRuehl", "Arial"}, 36)
    font_prompt = find_font({"David", "FrankRuehl", "Arial"}, 34)
    font_small = find_font({"David", "Arial"}, 24)
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)

    title = rtl(f"איסוף כתב יד — {title_num} — שם הכותב: ____________")
    tw = d.textlength(title, font=font_title)
    d.text((W - MARGIN - tw, 60), title, font=font_title, fill=GRAY)
    note = rtl("יש להעתיק כל משפט בכתב יד ברור על הקו שמתחתיו, בעט כחול או שחור")
    nw = d.textlength(note, font=font_small)
    d.text((W - MARGIN - nw, 115), note, font=font_small, fill=GRAY)

    zone_h = (H - 260 - 80) // LINES_PER_PAGE
    for i, sentence in enumerate(batch):
        top = 260 + i * zone_h
        prompt = rtl(sentence)
        pw = d.textlength(prompt, font=font_prompt)
        d.text((W - MARGIN - pw, top), prompt, font=font_prompt, fill=GRAY)
        line_y = top + zone_h - 55
        d.line((MARGIN, line_y, W - MARGIN, line_y), fill=LIGHT_GRAY, width=2)
        num_txt = rtl(f"{i+1}.")
        d.text((W - MARGIN + 40, top + zone_h // 2 - 15), num_txt,
               font=font_small, fill=LIGHT_GRAY)

    img.save(os.path.join(TEMPLATES, name + ".png"))
    with open(os.path.join(TEMPLATES, name + ".txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(batch) + "\n")
    return name


def make_custom_pages(sentences, prefix="custom"):
    """יוצרת עמודי תבנית מתוכן חופשי שהמשתמש הקליד. מחזירה שמות עמודים."""
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return []
    os.makedirs(TEMPLATES, exist_ok=True)
    existing = [f for f in os.listdir(TEMPLATES)
                if f.startswith(prefix + "_") and f.endswith(".png")]
    start = len(existing) + 1
    made = []
    for p in range(0, len(sentences), LINES_PER_PAGE):
        batch = sentences[p:p + LINES_PER_PAGE]
        num = start + p // LINES_PER_PAGE
        name = f"{prefix}_{num:03d}"
        render_page(name, batch, f"עמוד אישי {num}")
        made.append(name)
    return made


def make_pages(n_pages):
    os.makedirs(TEMPLATES, exist_ok=True)
    with open(CORPUS, encoding="utf-8") as f:
        sentences = [l.strip() for l in f if l.strip()]

    used_path = os.path.join(TEMPLATES, "used.txt")
    used = set()
    if os.path.exists(used_path):
        with open(used_path, encoding="utf-8") as f:
            used = {l.rstrip("\n") for l in f}
    available = [s for s in sentences if s not in used]

    existing = [f for f in os.listdir(TEMPLATES) if f.startswith("page_") and f.endswith(".png")]
    start_num = len(existing) + 1

    made = []
    for p in range(n_pages):
        batch = available[p * LINES_PER_PAGE:(p + 1) * LINES_PER_PAGE]
        if len(batch) < LINES_PER_PAGE:
            print(f"נגמרו משפטים פנויים בקורפוס אחרי {p} עמודים — הוסף שורות ל-data/corpus_he.txt")
            break
        num = start_num + p
        name = f"page_{num:03d}"
        render_page(name, batch, f"עמוד {num}")
        with open(used_path, "a", encoding="utf-8") as f:
            f.write("\n".join(batch) + "\n")
        made.append(name)
        print(f"נוצר: {name}.png ({LINES_PER_PAGE} משפטים)")

    if made:
        print(f"\nסה\"כ {len(made)} עמודים ב: {TEMPLATES}")
        print("הדפס אותם, מלא בכתב יד, סרוק ב-300dpi גווני אפור, ואז:")
        print(f'  python segment.py --ingest "סריקה.png" --template {made[0]} --writer <שם>')
    return made


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    make_pages(n)
