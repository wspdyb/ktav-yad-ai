# -*- coding: utf-8 -*-
"""ביקורת מסד הנתונים: המודל מתומלל מול כל שורות האימון של כותב.

שורת אימון שהמודל (שאומן עליה!) קורא רחוק מאוד מהתיוג שלה — חשודה כתיוג
שגוי/מוסט (שיבוש במסד). הפלט: data/audit_<כותב>.txt ממוין מהחשוד ביותר.

שימוש:  python audit_data.py [שם כותב] [--threshold 0.30]
"""
import os
import sys
import argparse

import torch

from paths import MODELS_DIR, DATA_DIR
from charset import CHARSET, NUM_CLASSES, decode_ctc, to_logical
from model import load_checkpoint
from dataset import RealLines, load_line_image, make_batch


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


@torch.no_grad()
def audit(writer, threshold=0.30, batch_size=16):
    for cand in (f"writer_{writer}.pt", "general.pt", "base_synth.pt"):
        p = os.path.join(MODELS_DIR, cand)
        if os.path.exists(p):
            model, _ = load_checkpoint(p, NUM_CLASSES, CHARSET)
            break
    else:
        raise SystemExit("אין מודל")
    model.eval()
    torch.set_num_threads(max(1, os.cpu_count() - 2))
    items = RealLines(writer).items
    if not items:
        raise SystemExit(f"אין שורות לכותב '{writer}'")
    rows = []
    for i in range(0, len(items), batch_size):
        chunk = items[i:i + batch_size]
        batch = make_batch([(load_line_image(p), t) for p, t in chunk])
        if batch is None:
            continue
        imgs, _, _, _, _ = batch
        preds = model(imgs).argmax(-1)
        for k, (path, text) in enumerate(chunk):
            pred = to_logical(decode_ctc(preds[k].tolist()))
            c = levenshtein(pred, text) / max(1, len(text))
            rows.append((c, os.path.basename(path), text, pred))
        done = min(i + batch_size, len(items))
        print(f"\r{done}/{len(items)}", end="", flush=True)
    print()
    rows.sort(reverse=True)
    sus = [r for r in rows if r[0] > threshold]
    avg = sum(r[0] for r in rows) / len(rows)
    out = os.path.join(DATA_DIR, f"audit_{writer}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"ביקורת נתונים לכותב '{writer}' — {len(rows)} שורות\n")
        f.write(f"CER ממוצע על נתוני האימון: {avg*100:.2f}%\n")
        f.write(f"שורות חשודות (CER > {threshold*100:.0f}%): {len(sus)}\n\n")
        for c, fname, text, pred in rows:
            mark = " *** חשוד ***" if c > threshold else ""
            f.write(f"[{c*100:5.1f}%]{mark} {fname}\n  תיוג: {text}\n  מודל: {pred}\n\n")
    print(f"ממוצע: {avg*100:.2f}% | חשודות: {len(sus)} | דוח: {out}")
    return rows, sus


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("writer", nargs="?", default="אישי")
    ap.add_argument("--threshold", type=float, default=0.30)
    args = ap.parse_args()
    audit(args.writer, args.threshold)
