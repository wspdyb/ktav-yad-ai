# -*- coding: utf-8 -*-
"""הערכה עצמית: תמלול 12 עמודים מלאים והשוואה לאמת-הקרקע (ה-TSV המאושרים)."""
import os
import sys
import torch

from paths import MODELS_DIR
from charset import CHARSET, NUM_CLASSES, decode_ctc, to_logical
from model import load_checkpoint
from segment import segment_page
from infer import pil_to_array, transcribe_rescued
import postfix

HERE = os.path.dirname(os.path.abspath(__file__))
SCANS = os.path.join(HERE, "data", "raw_scans", "סריקות סיכומי סוגיות להקלדה")
ALIGN = os.path.join(HERE, "data", "kuntres_align")
OUT = os.path.join(HERE, "data", "eval12_report.txt")


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
def transcribe(model, arr):
    x = torch.from_numpy(arr[None, None].astype("float32"))
    pred = model(x).argmax(-1)[0].tolist()
    return to_logical(decode_ctc(pred))


def main(pages, use_fix=True):
    model_path = os.path.join(MODELS_DIR, "writer_אישי.pt")
    model, ck = load_checkpoint(model_path, NUM_CLASSES, CHARSET)
    model.eval()
    torch.set_num_threads(max(1, os.cpu_count() - 2))
    report = []
    cers = []
    for p in pages:
        gt_lines = []
        tsv = os.path.join(ALIGN, f"page_{p:03d}.tsv")
        with open(tsv, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[1].strip():
                    gt_lines.append(parts[1].strip())
        imgs = segment_page(os.path.join(SCANS, f"{p}.jpg"))
        heights = sorted(im.height for im in imgs)
        med_h = heights[len(heights) // 2] if heights else 1
        preds = []
        for im in imgs:
            for _, t, _ in transcribe_rescued(model, im, med_h):
                if use_fix:
                    t = postfix.fix_text(t)
                if t.strip():
                    preds.append(t.strip())
        gt_j = " ".join(gt_lines)
        pr_j = " ".join(preds)
        cer = levenshtein(pr_j, gt_j) / max(1, len(gt_j)) * 100
        cers.append(cer)
        print(f"page {p}: {len(imgs)} crops, {len(preds)} pred lines, "
              f"{len(gt_lines)} gt lines, CER={cer:.1f}%")
        report.append(f"\n===== עמוד {p} | CER={cer:.1f}% | "
                      f"{len(preds)} שורות מודל מול {len(gt_lines)} אמת =====")
        for i in range(max(len(preds), len(gt_lines))):
            report.append(f"[מודל] {preds[i] if i < len(preds) else '—'}")
            report.append(f"[אמת ] {gt_lines[i] if i < len(gt_lines) else '—'}")
            report.append("")
    avg = sum(cers) / len(cers)
    print(f"\nAVERAGE CER over {len(pages)} pages: {avg:.2f}%")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"ממוצע CER: {avg:.2f}% על {len(pages)} עמודים\n")
        f.write("\n".join(report))
    print(f"report: {OUT}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    main(list(range(1, n + 1)))
