# -*- coding: utf-8 -*-
"""בניית מטמוני מודל השפה (ספירות/ביגרמות/טריגרמות) מהקורפוס הנוכחי.
שימוש: python build_lm.py [--force]   (--force מוחק מטמונים קודם)"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import postfix

if "--force" in sys.argv:
    for p in (postfix._BIGRAM_CACHE, postfix._TRIGRAM_CACHE,
              postfix._COUNTS_CACHE):
        try:
            os.remove(p)
            print("נמחק:", os.path.basename(p))
        except OSError:
            pass

t0 = time.time()
postfix._ensure_lm()
mins = (time.time() - t0) / 60
print(f"LM נבנה תוך {mins:.1f} דקות")
print(f"אוצר: {len(postfix._vocab):,} | ביגרמות: {len(postfix._bigrams):,} | "
      f"טריגרמות: {len(postfix._trigrams):,}")
for p in (postfix._COUNTS_CACHE, postfix._BIGRAM_CACHE, postfix._TRIGRAM_CACHE):
    if os.path.exists(p):
        print(f"  {os.path.basename(p)}: {os.path.getsize(p)/1e6:.1f}MB")
