# -*- coding: utf-8 -*-
"""הצמדה חצי-אוטומטית של עמודים מפולחים לטקסט המוקלד (kuntres_full.txt).

לכל שורה מפולחת: תמלול במודל הקיים ← איתור הקטע התואם בטקסט המוקלד
(עוגני מילים + מרחק עריכה) ← שיוך גבולות מדויק ← שער איכות:
רק שורות שהתמלול שלהן קרוב מאוד לטקסט המשויך (CER < סף) נכנסות ל-TSV.

שימוש:  python align_pages.py 34 35 36 37 38 [--threshold 0.30]
פלט:    data/kuntres_align/page_0NN.tsv (רק שורות שעברו את השער)
        + דוח data/align_report.txt לבדיקה ידנית.
"""
import os
import re
import sys
import argparse

import torch
from PIL import Image

from paths import MODELS_DIR
from charset import CHARSET, NUM_CLASSES, clean
from model import load_checkpoint
from infer import pil_to_array, transcribe_with_conf

HERE = os.path.dirname(os.path.abspath(__file__))
LINES = os.path.join(HERE, "data", "kuntres_lines")
ALIGN = os.path.join(HERE, "data", "kuntres_align")
FULL = os.path.join(HERE, "data", "kuntres_full.txt")
REPORT = os.path.join(HERE, "data", "align_report.txt")


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


def cer(pred, truth):
    if not truth:
        return 1.0
    return levenshtein(pred, truth) / len(truth)


def _norm_word(w):
    """נרמול מילה להשוואת עוגנים — בלי גרשיים/פיסוק."""
    return re.sub(r'[^א-ת0-9]', "", w)


def load_doc_words():
    with open(FULL, encoding="utf-8") as f:
        text = " ".join(l.strip() for l in f if l.strip())
    words = text.split()
    index = {}
    for i, w in enumerate(words):
        index.setdefault(_norm_word(w), []).append(i)
    return words, index


def best_window(pred, words, index, hint=None, hint_radius=400):
    """מאתר את חלון המילים בטקסט שהכי קרוב לתמלול. עוגנים: זוגות מילים
    עוקבות מהתמלול שמופיעות צמוד גם בטקסט. hint: מיקום משוער (המשך רציף)."""
    pw = [w for w in pred.split() if _norm_word(w)]
    if len(pw) < 2:
        return None, None, 1.0
    n_target = len(pw)
    anchors = []
    for k in range(len(pw) - 1):
        a, b = _norm_word(pw[k]), _norm_word(pw[k + 1])
        if not a or not b:
            continue
        for i in index.get(a, []):
            if i + 1 < len(words) and _norm_word(words[i + 1]) == b:
                anchors.append(i - k)   # מיקום משוער של תחילת השורה
    if not anchors and hint is None:
        return None, None, 1.0
    starts = set()
    for s in anchors:
        if hint is None or abs(s - hint) <= hint_radius:
            starts.update((s - 1, s, s + 1))
    if not starts and hint is not None:
        starts = set(range(max(0, hint - 40), hint + 40))
    best = (None, None, 1.0)
    for s in starts:
        if s < 0 or s >= len(words):
            continue
        # מנסים כמה אורכי חלון סביב אורך התמלול
        for dl in (-2, -1, 0, 1, 2):
            ln = n_target + dl
            if ln < 1 or s + ln > len(words):
                continue
            cand = " ".join(words[s:s + ln])
            c = cer(pred, cand)
            if c < best[2]:
                best = (s, ln, c)
    return best


@torch.no_grad()
def align_page(page, model, words, index, threshold, report):
    pdir = os.path.join(LINES, f"page_{page:03d}")
    files = sorted(f for f in os.listdir(pdir)
                   if f.startswith("line_") and f.endswith(".png"))
    rows, hint = [], None
    accepted = 0
    report.append(f"\n===== עמוד {page} =====")
    for f in files:
        im = Image.open(os.path.join(pdir, f))
        pred, conf = transcribe_with_conf(model, pil_to_array(im))
        pred = pred.strip()
        if not pred:
            report.append(f"[דלג ] {f}: תמלול ריק")
            continue
        s, ln, c = best_window(pred, words, index, hint)
        if s is not None and c <= threshold:
            gt = clean(" ".join(words[s:s + ln]))
            rows.append((f, gt))
            accepted += 1
            hint = s + ln
            report.append(f"[אושר] {f} (CER {c*100:.0f}%)")
            report.append(f"   מודל: {pred}")
            report.append(f"   טקסט: {gt}")
        else:
            report.append(f"[דחה ] {f} (CER {c*100:.0f}% > {threshold*100:.0f}%)")
            report.append(f"   מודל: {pred}")
            if s is not None:
                report.append(f"   מועמד: {' '.join(words[s:s+ln])}")
    os.makedirs(ALIGN, exist_ok=True)
    out = os.path.join(ALIGN, f"page_{page:03d}.tsv")
    with open(out, "w", encoding="utf-8") as fo:
        for f, gt in rows:
            fo.write(f"{f}\t{gt}\n")
    print(f"page {page}: {accepted}/{len(files)} lines accepted -> {out}")
    return accepted, len(files)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="+", type=int)
    ap.add_argument("--threshold", type=float, default=0.30)
    args = ap.parse_args()
    torch.set_num_threads(max(1, os.cpu_count() - 2))
    model_path = os.path.join(MODELS_DIR, "writer_אישי.pt")
    model, _ = load_checkpoint(model_path, NUM_CLASSES, CHARSET)
    model.eval()
    words, index = load_doc_words()
    print(f"טקסט מוקלד: {len(words)} מילים")
    report = []
    tot_a = tot_f = 0
    for p in args.pages:
        a, n = align_page(p, model, words, index, args.threshold, report)
        tot_a += a
        tot_f += n
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print(f"\nסה\"כ: {tot_a}/{tot_f} שורות אושרו | דוח: {REPORT}")
