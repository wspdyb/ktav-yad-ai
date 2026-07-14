# -*- coding: utf-8 -*-
"""מדידת מנוע ההצעות: v1 (פר-מילה) מול v2 (שרשרת) מול v2+הקשר-עמוד,
על עמודי GT אמיתיים, כולל ספירת תיקונים מיטיבים/מזיקים ובטיחות fix_text.

שימוש:  python measure_suggest.py [עמודים...] [--model writer|general]
ברירת מחדל: העמודים 8, 21, 33 (עמודי ה-baseline) + 5, 12.
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
SCANS = os.path.join(HERE, "data", "raw_scans", "סריקות סיכומי סוגיות להקלדה")
ALIGN = os.path.join(HERE, "data", "kuntres_align")

_STRIP = re.compile(r'[^א-ת0-9"\']')


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


def page_cer(lines, gt_lines):
    gt_j, pr_j = " ".join(gt_lines), " ".join(l for l in lines if l)
    return lev(pr_j, gt_j) / max(1, len(gt_j)) * 100


def classify_changes(changes, gt_words):
    """סיווג גס: מיטיב = 'אחרי' נמצא במילות ה-GT של העמוד ו'לפני' לא;
    מזיק = ההפך; אחרת לא-ידוע. בנוסף ה-CER הכולל מכריע את הנטו."""
    good, harm, unk = [], [], []
    for b, a in changes:
        bs = {_STRIP.sub("", w) for w in b.split()} - {""}
        as_ = {_STRIP.sub("", w) for w in a.split()} - {""}
        b_in = bs <= gt_words
        a_in = as_ <= gt_words
        if a_in and not b_in:
            good.append((b, a))
        elif b_in and not a_in:
            harm.append((b, a))
        else:
            unk.append((b, a))
    return good, harm, unk


def main(pages, which):
    name = "writer_אישי.pt" if which == "writer" else "general.pt"
    model, _ = load_checkpoint(os.path.join(MODELS_DIR, name), NUM_CLASSES, CHARSET)
    model.eval()
    torch.set_num_threads(3)
    totals = {k: [] for k in ("raw", "fix", "v1", "v2", "v2pg", "v2xl")}
    all_harm = {"fix": [], "v1": [], "v2": [], "v2pg": [], "v2xl": []}
    n_good = {"fix": 0, "v1": 0, "v2": 0, "v2pg": 0, "v2xl": 0}
    for p in pages:
        gt_lines = []
        with open(os.path.join(ALIGN, f"page_{p:03d}.tsv"), encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[1].strip():
                    gt_lines.append(parts[1].strip())
        gt_words = {_STRIP.sub("", w) for l in gt_lines for w in l.split()} - {""}
        items = segment_page_ex(os.path.join(SCANS, f"{p}.jpg"))
        heights = sorted(im.height for im, _ in items)
        med_h = heights[len(heights) // 2] if heights else 1
        raw = []
        for im, meta in items:
            for _, t, _ in transcribe_rescued(model, im, med_h):
                t = t.strip()
                if t:
                    raw.append(t)
        fixed, fix_ch = [], []
        for t in raw:
            ft = postfix.fix_text(t)
            fixed.append(ft)
            if ft != t:
                # זוגות מילים ששונו (לספירת בטיחות): יישור נאיבי לפי מיקום
                tw, fw = t.split(), ft.split()
                if len(tw) == len(fw):
                    fix_ch += [(a, b) for a, b in zip(tw, fw) if a != b]
                else:
                    fix_ch.append((t, ft))
        variants = {}
        # v1 — הגרסה הישנה, פר-מילה
        v1_lines, v1_ch = [], []
        for t in fixed:
            s, ch = postfix.suggest_line_v1(t)
            v1_lines.append(s)
            v1_ch += ch
        variants["v1"] = (v1_lines, v1_ch)
        # v2 — שרשרת, בלי הקשר עמוד
        v2_lines, v2_ch = [], []
        for t in fixed:
            s, ch = postfix.suggest_line(t)
            v2_lines.append(s)
            v2_ch += ch
        variants["v2"] = (v2_lines, v2_ch)
        # v2 + הקשר עמוד (כמו בתוכנה: אוצר העבודה בלי מילות השורה עצמה)
        counts = postfix.page_word_counts(fixed)
        v2p_lines, v2p_ch = [], []
        for t in fixed:
            ctx = counts - postfix.page_word_counts([t])
            s, ch = postfix.suggest_line(t, page_words=ctx)
            v2p_lines.append(s)
            v2p_ch += ch
        variants["v2pg"] = (v2p_lines, v2p_ch)
        # v2 + הקשר עמוד + רצף חוצה-שורות ("תיקון מורחב" המלא)
        v2x_lines, v2x_ch, prev_tail = [], [], None
        for t in fixed:
            ctx = counts - postfix.page_word_counts([t])
            s, ch = postfix.suggest_line(t, page_words=ctx, prev_tail=prev_tail)
            v2x_lines.append(s)
            v2x_ch += ch
            tail = [c for c in (re.sub(r'^[\("\[]*|[\)\.",\]:;!?]*$', "", x)
                                for x in t.split()) if len(c) >= 2]
            prev_tail = tail[-1] if tail else prev_tail
        variants["v2xl"] = (v2x_lines, v2x_ch)

        cers = {"raw": page_cer(raw, gt_lines), "fix": page_cer(fixed, gt_lines)}
        for k, (lines, _) in variants.items():
            cers[k] = page_cer(lines, gt_lines)
        for k in totals:
            totals[k].append(cers[k])
        g, h, u = classify_changes(fix_ch, gt_words)
        n_good["fix"] += len(g)
        all_harm["fix"] += [(p, b, a) for b, a in h]
        line = (f"עמוד {p}: raw={cers['raw']:.2f} fix={cers['fix']:.2f} "
                f"v1={cers['v1']:.2f} v2={cers['v2']:.2f} v2+page={cers['v2pg']:.2f}")
        for k, (_, ch) in variants.items():
            g, h, u = classify_changes(ch, gt_words)
            n_good[k] += len(g)
            all_harm[k] += [(p, b, a) for b, a in h]
            line += f" | {k}: {len(g)}+/{len(h)}-/{len(u)}?"
        print(line, flush=True)
    print("\n===== ממוצעים =====")
    for k in ("raw", "fix", "v1", "v2", "v2pg", "v2xl"):
        print(f"{k:5s}: CER ממוצע {sum(totals[k]) / len(totals[k]):.2f}% | "
              f"מיטיבים {n_good.get(k, '—')} | מזיקים {len(all_harm.get(k, []))}")
    for k, lst in all_harm.items():
        if lst:
            print(f"\nתיקונים מזיקים ({k}):")
            for p, b, a in lst:
                print(f"  עמוד {p}: {b} -> {a}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", type=int, default=[8, 21, 33, 5, 12])
    ap.add_argument("--model", default="writer", choices=["writer", "general"])
    args = ap.parse_args()
    main(args.pages or [8, 21, 33, 5, 12], args.model)
