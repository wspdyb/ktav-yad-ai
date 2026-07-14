# -*- coding: utf-8 -*-
"""יוצר קורפוס מוקטן (corpus_lite.txt) לאריזת ה-EXE: דגימת stride על פני
כל הקורפוס המלא — גיוון מכל המקורות בנפח קטן. משמש לאימון הסינתטי
וליצירת תבניות אצל המשתמש; מודל השפה (postfix) עובד מהמטמונים, לא מכאן.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC = os.path.join(HERE, "data", "corpus_he.txt")
DST = os.path.join(HERE, "data", "corpus_lite.txt")
TARGET = 150_000

n = sum(1 for _ in open(SRC, encoding="utf-8"))
stride = max(1, n // TARGET)
kept = 0
with open(SRC, encoding="utf-8") as f, open(DST, "w", encoding="utf-8") as out:
    for i, line in enumerate(f):
        if i % stride == 0:
            out.write(line)
            kept += 1
mb = os.path.getsize(DST) / 1e6
print(f"corpus מלא: {n:,} שורות | corpus_lite: {kept:,} שורות ({mb:.0f}MB)")
