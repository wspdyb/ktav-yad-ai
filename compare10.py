# -*- coding: utf-8 -*-
"""השוואה מלאה: תמלול N עמודים (הצינור המלא: פילוח+חילוץ+postfix) מול
הטקסט המוקלד המאושר, עם דוח שגיאות ברמת מילה וטקסונומיית גורמים.

שימוש:  python compare10.py [מספר עמודים=10] [--model writer|general]
פלט:    data/compare_report.txt
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
from infer import pil_to_array, transcribe_rescued
import postfix

HERE = os.path.dirname(os.path.abspath(__file__))
SCANS = os.path.join(HERE, "data", "raw_scans", "סריקות סיכומי סוגיות להקלדה")
ALIGN = os.path.join(HERE, "data", "kuntres_align")
OUT = os.path.join(HERE, "data", "compare_report.txt")


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


def classify(p, g):
    """טקסונומיה גסה של החלפת מילה: גרשיים / אות-דומה / רווח / אחר."""
    strip = lambda w: re.sub(r'[^א-ת0-9]', "", w)
    sp, sg = strip(p), strip(g)
    if sp == sg:
        return "פיסוק/גרשיים"
    if len(sp) == len(sg) and sum(1 for x, y in zip(sp, sg) if x != y) == 1:
        return "אות דומה"
    if sp and sg and (sp in sg or sg in sp):
        return "חיתוך/איחוי"
    return "אחר"


def main(n_pages, which):
    name = "writer_אישי.pt" if which == "writer" else "general.pt"
    model, _ = load_checkpoint(os.path.join(MODELS_DIR, name), NUM_CLASSES, CHARSET)
    model.eval()
    torch.set_num_threads(2)
    report, cers = [], []
    taxo, sub_list = {}, []
    for p in range(1, n_pages + 1):
        gt_lines = []
        with open(os.path.join(ALIGN, f"page_{p:03d}.tsv"), encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[1].strip():
                    gt_lines.append(parts[1].strip())
        items = segment_page_ex(os.path.join(SCANS, f"{p}.jpg"))
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
        cers.append(cer)
        print(f"page {p}: CER={cer:.1f}% ({len(preds)} pred / {len(gt_lines)} gt)",
              flush=True)
        report.append(f"===== עמוד {p} | CER={cer:.1f}% =====")
        for wp, wg in word_align(pr_j.split(), gt_j.split()):
            if wp == wg:
                continue
            if wp is None:
                report.append(f"  חסרה: {wg}")
            elif wg is None:
                report.append(f"  עודפת: {wp}")
            else:
                kind = classify(wp, wg)
                taxo[kind] = taxo.get(kind, 0) + 1
                sub_list.append((wp, wg, kind))
                report.append(f"  {wp}  ->  {wg}   [{kind}]")
    avg = sum(cers) / len(cers)
    head = [f"ממוצע CER: {avg:.2f}% על {len(cers)} עמודים ({which})",
            "התפלגות סוגי החלפות: " + ", ".join(f"{k}={v}" for k, v in
                                                sorted(taxo.items(), key=lambda x: -x[1]))]
    print("\n".join(head))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n\n" + "\n".join(report))
    print(f"report: {OUT}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="?", type=int, default=10)
    ap.add_argument("--model", default="writer", choices=["writer", "general"])
    args = ap.parse_args()
    main(args.pages, args.model)
