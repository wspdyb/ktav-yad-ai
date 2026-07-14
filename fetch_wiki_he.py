# -*- coding: utf-8 -*-
"""טקסט כללי מהרשת: ערכים אקראיים מוויקיפדיה העברית (תקצירי plain-text
בקבצות של 20) — עברית מודרנית כללית לגיוון הקורפוס ומודל השפה.
נשמר למטמון data/corpus_cache/wiki_he_random.txt (מצטבר בין ריצות).

שימוש: python fetch_wiki_he.py [מספר_בקשות=60]   (60 בקשות ≈ 1200 ערכים)
"""
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "corpus_cache", "wiki_he_random.txt")

API = ("https://he.wikipedia.org/w/api.php?action=query&format=json"
       "&generator=random&grnnamespace=0&grnlimit=20"
       "&prop=extracts&explaintext=1&exlimit=20")


def _ssl_ctx():
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())


def main(n_req=60):
    ctx = _ssl_ctx()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    got = 0
    with open(OUT, "a", encoding="utf-8") as out:
        for i in range(n_req):
            req = urllib.request.Request(API, headers={"User-Agent":
                                                       "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                    data = json.loads(r.read())
            except Exception as e:
                print(f"  שגיאה ({e}) — עוצר; נשמר מה שנאסף")
                break
            for page in data.get("query", {}).get("pages", {}).values():
                ext = (page.get("extract") or "").strip()
                if len(ext) > 200:
                    out.write(ext + "\n")
                    got += 1
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{n_req} בקשות, {got} ערכים", flush=True)
            time.sleep(0.4)
    size = os.path.getsize(OUT) / 1e6 if os.path.exists(OUT) else 0
    print(f"ויקיפדיה: {got} ערכים חדשים, קובץ מצטבר {size:.1f}MB")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
