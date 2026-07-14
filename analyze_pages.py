# -*- coding: utf-8 -*-
"""ניתוח סופי: תמלול N עמודים מזדמנים מתיקיית המקור של המשתמש (הורדות),
בצינור המלא של התוכנה (פילוח + חילוץ + fix + תיקון מורחב), עם:
- CER לכל שלב, טקסונומיית שגיאות ברמת מילה
- סטטיסטיקת ביטחון + מועמדים לחוק דיכוי-רעש (מניעת הזיות)
- אבחנה: שגיאת חוסר-אימון (בלבול אותיות) מול באג צנרת

שימוש: python analyze_pages.py [עמודים...] [--model writer|general]
ברירת מחדל: 3 17 24 29 36 (מחוץ לסט הכיול 5/8/12/21/33).
"""
import os
import re
import sys
import argparse

import torch

from paths import MODELS_DIR
from charset import CHARSET, NUM_CLASSES
from model import load_checkpoint
from segment import segment_page_ex
from infer import transcribe_rescued
import postfix

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = r"C:\Users\מנהל-\Downloads\לאימון מודל\סריקות לאימון מודל"
ALIGN = os.path.join(HERE, "data", "kuntres_align")
OUT = os.path.join(HERE, "data", "final_analysis.txt")


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


def word_align(a, b):
    n, m = len(a), len(b)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        D[i][0] = i
    for j in range(m + 1):
        D[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i - 1][j] + 1, D[i][j - 1] + 1,
                          D[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    pairs, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and D[i][j] == D[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            pairs.append((a[i - 1], b[j - 1])); i -= 1; j -= 1
        elif i > 0 and D[i][j] == D[i - 1][j] + 1:
            pairs.append((a[i - 1], None)); i -= 1
        else:
            pairs.append((None, b[j - 1])); j -= 1
    return pairs[::-1]


_STRIP = re.compile(r'[^א-ת0-9]')
_CONFUS = [set(x) for x in ("דר", "חת", "שס", "בכ", "םס", "וי", "ןו", "אמ",
                            "צע", "גנ", "הח", "טמ", "כפ", "זו", "ליו")]


def classify(p, g):
    sp, sg = _STRIP.sub("", p), _STRIP.sub("", g)
    if sp == sg:
        return "פיסוק/גרשיים"
    if len(sp) == len(sg):
        diffs = [(a, b) for a, b in zip(sp, sg) if a != b]
        if len(diffs) == 1:
            a, b = diffs[0]
            if any(a in s and b in s for s in _CONFUS):
                return "בלבול אותיות דומות (חוסר אימון)"
            return "אות בודדת אחרת"
    if sp and sg and (sp in sg or sg in sp):
        return "חיתוך/איחוי"
    return "אחר"


def main(pages, which):
    name = "writer_אישי.pt" if which == "writer" else "general.pt"
    model, _ = load_checkpoint(os.path.join(MODELS_DIR, name), NUM_CLASSES, CHARSET)
    model.eval()
    torch.set_num_threads(3)
    rep, cers = [], {"raw": [], "fix": [], "full": []}
    taxo, low_conf = {}, []
    for p in pages:
        gt_lines = []
        with open(os.path.join(ALIGN, f"page_{p:03d}.tsv"), encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[1].strip():
                    gt_lines.append(parts[1].strip())
        gt_j = " ".join(gt_lines)
        items = segment_page_ex(os.path.join(SRC, f"{p}.jpg"))
        heights = sorted(im.height for im, _ in items)
        med_h = heights[len(heights) // 2] if heights else 1
        raw, confs = [], []
        for im, meta in items:
            for _, t, c in transcribe_rescued(model, im, med_h):
                t = t.strip()
                if t:
                    raw.append(t)
                    confs.append(c)
                    heb = len([ch for ch in t if "א" <= ch <= "ת"])
                    if c < 0.62 or heb <= 1:
                        low_conf.append((p, round(c, 2), t[:40]))
        fixed = [postfix.fix_text(t) for t in raw]
        counts = postfix.page_word_counts(fixed)
        full, pt2, pt = [], None, None
        for t in fixed:
            ctx = counts - postfix.page_word_counts([t])
            s, _ch = postfix.suggest_line(t, page_words=ctx,
                                          prev_tail=pt, prev_tail2=pt2)
            full.append(s)
            pt2, pt = postfix.advance_tail(pt2, pt, t)
        c_raw = lev(" ".join(raw), gt_j) / len(gt_j) * 100
        c_fix = lev(" ".join(fixed), gt_j) / len(gt_j) * 100
        c_full = lev(" ".join(full), gt_j) / len(gt_j) * 100
        cers["raw"].append(c_raw)
        cers["fix"].append(c_fix)
        cers["full"].append(c_full)
        mean_c = sum(confs) / max(1, len(confs))
        print(f"עמוד {p}: raw={c_raw:.2f} fix={c_fix:.2f} מלא={c_full:.2f} | "
              f"{len(raw)} שורות | ביטחון ממוצע {mean_c:.2f}", flush=True)
        rep.append(f"===== עמוד {p} | raw={c_raw:.2f}% fix={c_fix:.2f}% "
                   f"מלא={c_full:.2f}% | ביטחון {mean_c:.2f} =====")
        for wp, wg in word_align(" ".join(full).split(), gt_j.split()):
            if wp == wg:
                continue
            if wp is None:
                rep.append(f"  חסרה: {wg}")
            elif wg is None:
                rep.append(f"  עודפת: {wp}")
            else:
                kind = classify(wp, wg)
                taxo[kind] = taxo.get(kind, 0) + 1
                rep.append(f"  {wp}  ->  {wg}   [{kind}]")
    avg = {k: sum(v) / len(v) for k, v in cers.items()}
    head = [f"ממוצע ({which}, {len(pages)} עמודים): raw={avg['raw']:.2f}% "
            f"fix={avg['fix']:.2f}% מלא={avg['full']:.2f}%",
            "טקסונומיה: " + ", ".join(f"{k}={v}" for k, v in
                                      sorted(taxo.items(), key=lambda x: -x[1])),
            f"שורות חשודות-רעש (conf<0.62 או עברית<=1): {len(low_conf)}"]
    for p, c, t in low_conf[:15]:
        head.append(f"   עמ' {p} [{c}] {t}")
    print("\n".join(head))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n\n" + "\n".join(rep))
    print(f"דוח מלא: {OUT}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", type=int, default=[3, 17, 24, 29, 36])
    ap.add_argument("--model", default="writer", choices=["writer", "general"])
    args = ap.parse_args()
    main(args.pages or [3, 17, 24, 29, 36], args.model)
