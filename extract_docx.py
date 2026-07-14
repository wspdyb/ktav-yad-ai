# -*- coding: utf-8 -*-
"""חילוץ טקסט מקובץ docx (בלי תלויות): פסקאות מ-word/document.xml."""
import sys
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def extract_paragraphs(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter("{%s}p" % NS["w"]):
        texts = [t.text or "" for t in p.iter("{%s}t" % NS["w"])]
        paras.append("".join(texts))
    return paras


if __name__ == "__main__":
    src = sys.argv[1]
    out = sys.argv[2]
    anchor = sys.argv[3] if len(sys.argv) > 3 else None
    paras = extract_paragraphs(src)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(paras))
    print(f"paragraphs: {len(paras)}, chars: {sum(len(p) for p in paras)}")
    if anchor:
        norm = lambda s: re.sub(r'[\s"\'״׳]+', "", s)
        na = norm(anchor)
        for i, p in enumerate(paras):
            if na in norm(p):
                print(f"ANCHOR FOUND in paragraph {i}:")
                print(p[:300])
                break
        else:
            # חיפוש חלקי — אולי העוגן חוצה פסקאות
            first_words = anchor.split()[:3]
            for i, p in enumerate(paras):
                if all(w in p for w in first_words):
                    print(f"PARTIAL match in paragraph {i}: {p[:200]}")
