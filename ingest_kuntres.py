# -*- coding: utf-8 -*-
"""קליטת כל השורות המוצמדות מהקונטרס למאגר האימון של הכותב.
בונה מחדש את המאגר מאפס בכל הרצה (אידמפוטנטי)."""
import os
import glob
import shutil

from charset import clean

HERE = os.path.dirname(os.path.abspath(__file__))
ALIGN = os.path.join(HERE, "data", "kuntres_align")
LINES = os.path.join(HERE, "data", "kuntres_lines")
WRITER = "אישי"
OUT = os.path.join(HERE, "data", "writers", WRITER)


def main():
    ldir = os.path.join(OUT, "lines")
    if os.path.isdir(ldir):
        shutil.rmtree(ldir)
    os.makedirs(ldir, exist_ok=True)
    rows = []
    skipped = 0
    for tsv in sorted(glob.glob(os.path.join(ALIGN, "page_*.tsv"))):
        page = os.path.splitext(os.path.basename(tsv))[0]  # page_NNN
        with open(tsv, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2 or not parts[1].strip():
                    continue
                src = os.path.join(LINES, page, parts[0])
                if not os.path.exists(src):
                    skipped += 1
                    continue
                text = clean(parts[1].strip())
                if not text:
                    skipped += 1
                    continue
                dst_name = f"{page}_{parts[0]}"
                shutil.copy2(src, os.path.join(ldir, dst_name))
                rows.append((dst_name, text))
    with open(os.path.join(OUT, "labels.tsv"), "w", encoding="utf-8") as f:
        for name, text in rows:
            f.write(f"{name}\t{text}\n")
    print(f"writer '{WRITER}': {len(rows)} lines ingested, {skipped} skipped")


if __name__ == "__main__":
    main()
