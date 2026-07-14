# -*- coding: utf-8 -*-
"""תמלול תמונות לטקסט.

שימוש:
  python infer.py image.png                    תמונה של שורה בודדת (מודל בסיס)
  python infer.py scan.png --page              עמוד שלם — פילוח אוטומטי לשורות
  python infer.py scan.png --page --writer יעקב   שימוש במודל המכוונן של כותב מסוים
  python infer.py folder --page --out out.txt  תיקייה שלמה, שמירה לקובץ
"""
import os
import sys
import argparse
import numpy as np
import torch

from charset import CHARSET, NUM_CLASSES, decode_ctc, to_logical
from model import load_checkpoint, IMG_H
from dataset import load_line_image, MAX_W
from segment import segment_page

from paths import MODELS_DIR as MODELS

# GPU אם קיים (מסלול A בתרשים) — אחרת CPU. אותו קוד לשני המסלולים.
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def pick_model(writer=None):
    candidates = []
    if writer:
        candidates.append(os.path.join(MODELS, f"writer_{writer}.pt"))
    candidates.append(os.path.join(MODELS, "base_synth.pt"))
    for c in candidates:
        if os.path.exists(c):
            model, ckpt = load_checkpoint(c, NUM_CLASSES, CHARSET)
            model.to(DEVICE)
            model.eval()
            return model, c
    raise SystemExit("לא נמצא אף מודל ב-models/. הרץ קודם: python train.py base")


@torch.no_grad()
def transcribe_array(model, arr):
    """arr: numpy HxW בטווח 0..1 -> מחרוזת בסדר לוגי."""
    x = torch.from_numpy(arr[None, None].astype(np.float32))
    dev = next(model.parameters()).device
    logits = model(x.to(dev))
    pred = logits.argmax(-1)[0].cpu().tolist()
    return to_logical(decode_ctc(pred))


@torch.no_grad()
def transcribe_with_conf(model, arr, collect=None):
    """תמלול + ציון ביטחון (0..1) — ממוצע ההסתברות של התו הנבחר בכל צעד.
    collect (dict, אופציונלי): מקבל את מסלול ה-CTC ורוחב הקלט — למיפוי
    מילים למיקומי X (זיהוי מילים מודגשות)."""
    x = torch.from_numpy(arr[None, None].astype(np.float32))
    logits = model(x.to(next(model.parameters()).device)).cpu()
    probs = logits.softmax(-1)[0]
    best = probs.max(-1)
    pred = best.indices.tolist()
    text = to_logical(decode_ctc(pred))
    conf = float(best.values.mean())
    if collect is not None:
        collect["pred"] = pred
        collect["arr_w"] = arr.shape[1]
    return text, conf


def visual_word_spans(pred, arr_w, orig_w):
    """מפענח את מסלול ה-CTC למילים חזותיות עם טווחי X (בפיקסלי החיתוך
    המקורי). מחזירה [(מילה_חזותית, x0, x1)] משמאל לימין."""
    from charset import idx_to_char
    chars, prev = [], 0
    for t, i in enumerate(pred):
        if i != 0 and i != prev:
            chars.append((idx_to_char.get(i, ""), t))
        prev = i
    scale = orig_w / max(1, arr_w)
    from model import DOWNSAMPLE_W
    words, cur, x0, x_last = [], "", 0.0, 0.0
    for ch, t in chars:
        x = (t * DOWNSAMPLE_W + DOWNSAMPLE_W / 2) * scale
        if ch == " ":
            if cur:
                words.append((cur, x0, x_last))
            cur = ""
        else:
            if not cur:
                x0 = x
            cur += ch
            x_last = x
    if cur:
        words.append((cur, x0, x_last))
    return words


def bold_word_indices(pred, arr_w, orig_w, em_spans, n_logical_words):
    """אינדקסי המילים (בסדר הלוגי) שמתחתן קו-הדגשה: חפיפה של ≥50% בין
    טווח ה-X של המילה החזותית לקו. הכתיבה RTL — מילה חזותית k = מילה
    לוגית n-1-k (קירוב שנכון לשורות עבריות; שורה שהמיפוי בה לא עקבי
    מוותרת על ההדגשה במקום לסמן מילה שגויה)."""
    vwords = visual_word_spans(pred, arr_w, orig_w)
    if not vwords or len(vwords) != n_logical_words:
        return []
    out = set()
    for k, (_wtxt, wx0, wx1) in enumerate(vwords):
        w_len = max(1.0, wx1 - wx0)
        for s, e in em_spans:
            inter = min(wx1, e) - max(wx0, s)
            if inter >= 0.5 * w_len:
                out.add(len(vwords) - 1 - k)
                break
    return sorted(out)


def insert_by_x(base_text, ins_text, ins_box, base_box):
    """משלב טקסט שנכתב מעל שורה ("משפך") בתוך טקסט השורה, לפי מיקום ה-X
    של הקטע העליון. הכתיבה מימין לשמאל: הקצה הימני של השורה = תו ראשון.
    ההצמדה נעשית לגבול המילה הקרוב ביותר. מחזירה את הטקסט המשולב."""
    bx0, bx1 = base_box[0], base_box[1]
    if bx1 <= bx0 or not base_text.strip():
        return None
    cx = (ins_box[0] + ins_box[1]) / 2.0
    ratio = (bx1 - cx) / float(bx1 - bx0)   # 0 = ימין (תחילת הטקסט)
    ratio = min(1.0, max(0.0, ratio))
    pos = int(round(ratio * len(base_text)))
    # הצמדה לרווח הקרוב ביותר (גבול מילה)
    spaces = [0] + [i + 1 for i, c in enumerate(base_text) if c == " "] \
        + [len(base_text)]
    snap = min(spaces, key=lambda s: abs(s - pos))
    left, right = base_text[:snap].rstrip(), base_text[snap:].lstrip()
    return (left + " " + ins_text.strip() + " " + right).strip()


def transcribe_rescued(model, im, med_h=None, collect=None):
    """תמלול חיתוך עם "חילוץ" מפני חיתוך כפול (שורה + שבר-שורה שמוזגו —
    מקור נפוץ לג'יבריש על כתב יד ברור). התנאים קשוחים בכוונה, כדי שלא
    לפגוע בשורות תקינות:
      טריגר: ביטחון נמוך, והחיתוך גבוה משמעותית מחציון השורות בעמוד.
      פיצול: רק אם נמצא עמק כמעט ריק בפרופיל הדיו (split_crop_rows).
      אימוץ: רק אם הביטחון של שני החצאים קופץ משמעותית מעל המקור.
    אם הקטע העליון צר משמעותית מהשורה — זו מילה שהוכנסה מעל השורה
    (סימון "משפך"), והיא משולבת לתוך השורה לפי מיקום ה-X במקום להיפלט
    כשורה נפרדת. מחזירה [(תמונה, טקסט, ביטחון)]."""
    from segment import split_crop_rows
    text, conf = transcribe_with_conf(model, pil_to_array(im), collect=collect)
    if conf >= 0.72 or (med_h and im.height < med_h * 1.35):
        return [(im, text, conf)]
    if collect is not None:
        collect.clear()   # חילוץ/פיצול משנה את מערכת הצירים — אין מיפוי הדגשות
    halves = split_crop_rows(im, with_boxes=True)
    if len(halves) < 2:
        return [(im, text, conf)]
    parts = []
    for h_img, box in halves:
        t2, c2 = transcribe_with_conf(model, pil_to_array(h_img))
        parts.append((h_img, t2, c2, box))
    if sum(p[2] for p in parts) / len(parts) <= conf + 0.12:
        return [(im, text, conf)]
    (t_img, t_txt, t_c, t_box), (b_img, b_txt, b_c, b_box) = parts
    # טווחי דיו אפקטיביים (עמידים לרעש) במערכת הצירים של החיתוך המקורי
    from segment import ink_span
    t_span, b_span = ink_span(t_img), ink_span(b_img)
    if t_txt.strip() and b_txt.strip() and t_span and b_span:
        t_l, t_r = t_box[0] + t_span[0], t_box[0] + t_span[1]
        b_l, b_r = b_box[0] + b_span[0], b_box[0] + b_span[1]
        t_cx = t_box[0] + t_span[2]
        if (t_r - t_l) < 0.55 * (b_r - b_l):
            merged = insert_by_x(b_txt, t_txt, (t_cx, t_cx), (b_l, b_r))
            if merged:
                return [(im, merged, min(t_c, b_c))]
    return [(p[0], p[1], p[2]) for p in parts]


# תקרת רוחב לאינפרנס — גבוהה מזו של האימון: שורת דפוס צפופה (גובה אות
# קטן יחסית לאורך) מתנפחת מאוד בנרמול לגובה 48, וקיצוץ ב-1600 היה חותך
# חצי שורה ומשבש עמודים מודפסים. 3200/4=800 צעדי LSTM — עדיין מהיר.
INFER_MAX_W = 3200


def pil_to_array(img):
    w, h = img.size
    new_w = max(16, int(w * IMG_H / h))
    img = img.resize((min(new_w, INFER_MAX_W), IMG_H))
    return np.array(img, dtype=np.float32) / 255.0


def transcribe_file(model, path, page_mode):
    if page_mode:
        lines = segment_page(path)
        return "\n".join(transcribe_array(model, pil_to_array(l)) for l in lines)
    return transcribe_array(model, load_line_image(path))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="קובץ תמונה או תיקייה")
    ap.add_argument("--page", action="store_true", help="פילוח עמוד שלם לשורות")
    ap.add_argument("--writer", default=None, help="שם כותב (ישתמש במודל המכוונן שלו)")
    ap.add_argument("--out", default=None, help="קובץ פלט טקסט")
    args = ap.parse_args()

    model, model_path = pick_model(args.writer)
    print(f"מודל: {os.path.basename(model_path)}", file=sys.stderr)

    if os.path.isdir(args.input):
        exts = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
        files = sorted(f for f in os.listdir(args.input) if f.lower().endswith(exts))
        results = []
        for f in files:
            text = transcribe_file(model, os.path.join(args.input, f), args.page)
            results.append(f"=== {f} ===\n{text}")
        output = "\n\n".join(results)
    else:
        output = transcribe_file(model, args.input, args.page)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"נשמר: {args.out}", file=sys.stderr)
    else:
        print(output)
