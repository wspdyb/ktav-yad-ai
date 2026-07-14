# -*- coding: utf-8 -*-
"""מודל התיקונים הלומד — זוגות (שגוי -> נכון) שנלמדים מהשימוש בפועל.

כשהמשתמש שומר תיקונים "למודל התיקונים", ההבדלים בין התמלול המקורי לטקסט
הסופי שלו מפורקים לזוגות מילים, שנצברים עם מונה:
  data/writers/<כותב>/fixes.tsv   — התיקונים האישיים של הכותב
  data/fixes_general.tsv          — מאגר התיקונים הכללי (משותף/מיובא)

מנוע ההצעות (postfix.suggest_line) נותן לזוגות האלה משקל גבוה — טעות
שהמשתמש תיקן בעבר תזוהה ותוצע מיד. פורמט הקובץ: שגוי<TAB>נכון<TAB>מונה.
ייבוא קובץ תיקונים ממשתמש אחר מתמזג תמיד למאגר הכללי (לא לאישי).
"""
import json
import os
import re

from paths import DATA_DIR, WRITERS_DIR

GENERAL_FIXES = os.path.join(DATA_DIR, "fixes_general.tsv")
SEEN_PATH = os.path.join(DATA_DIR, ".fixes_seen.json")
_PUNCT_RE = re.compile(r'^[\("\[]*|[\)\.",\]:;!?]*$')
_cache = {}


def _path(writer=None):
    if writer:
        return os.path.join(WRITERS_DIR, writer, "fixes.tsv")
    return GENERAL_FIXES


def _load_file(path):
    """טוען קובץ תיקונים: {(שגוי, נכון): מונה}. מותרות כמה שורות לאותה
    מילה שגויה עם תיקונים שונים — ההכרעה ביניהם נעשית לפי הרוב בטעינה."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[0] and parts[1]:
                    try:
                        n = int(parts[2]) if len(parts) > 2 else 1
                    except ValueError:
                        n = 1
                    key = (parts[0], parts[1])
                    out[key] = out.get(key, 0) + max(1, n)
    except OSError:
        pass
    return out


def _save_file(path, fixes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for (wrong, right), n in sorted(fixes.items(), key=lambda x: -x[1]):
            f.write(f"{wrong}\t{right}\t{n}\n")


def _majority(pair_counts):
    """הכרעת רוב: לכל מילה שגויה — התיקון שנצבר לו המונה הגבוה ביותר.
    כך טעות חד-פעמית של המשתמש (פעם אחת ב', פעמיים א') לא משבשת: הרוב קובע.
    שוויון מוכרע דטרמיניסטית (אלפביתי) כדי שההתנהגות תהיה יציבה."""
    best = {}
    for (wrong, right), n in pair_counts.items():
        cur = best.get(wrong)
        if cur is None or n > cur[1] or (n == cur[1] and right < cur[0]):
            best[wrong] = (right, n)
    return best


def load_merged(writer=None):
    """מילון שגוי->(נכון, מונה) אחרי הכרעת רוב על כלל הזוגות (כללי+אישי;
    המונים מצטברים — עריכה אישית חוזרת מטה את הרוב). עם מטמון."""
    key = (writer, _mtimes(writer))
    if key in _cache:
        return _cache[key]
    pair_counts = dict(_load_file(GENERAL_FIXES))
    if writer:
        for k, n in _load_file(_path(writer)).items():
            pair_counts[k] = pair_counts.get(k, 0) + n
    merged = _majority(pair_counts)
    _cache.clear()
    _cache[key] = merged
    return merged


def _mtimes(writer):
    def m(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0
    return (m(GENERAL_FIXES), m(_path(writer)) if writer else 0)


def _lev_align(a, b):
    """יישור מילים (מסלול levenshtein) — זוגות (מילה_מקור, מילה_סופית)."""
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


def harvest_pairs(orig, final):
    """מפיק זוגות (שגוי, נכון) מהשוואת תמלול מקורי לטקסט סופי של המשתמש.
    רק החלפות מילה-במילה סבירות (לא מחיקות/הוספות, לא שינוי קיצוני).
    תיקוני איחוי/פיצול (סלי קא -> סליקא) מדולגים: מודל של מילה בודדת לא
    יכול לייצג אותם, ושמירת החצי (קא -> סליקא) מרעילה מילה תקינה."""
    out = []
    aligned = _lev_align(orig.split(), final.split())
    for k, (wp, wf) in enumerate(aligned):
        if not wp or not wf or wp == wf:
            continue
        a, b = _PUNCT_RE.sub("", wp), _PUNCT_RE.sub("", wf)
        if a == b or len(a) < 2 or len(b) < 2 or len(a) > 25 or len(b) > 25:
            continue
        # שבר איחוי: מילת מקור שכנה שנמחקה משלימה את "הנכון" (סלי+קא=סליקא)
        neigh_del = [_PUNCT_RE.sub("", p) for p, f2 in
                     (aligned[max(0, k - 1):k] + aligned[k + 1:k + 2]) if p and not f2]
        if any(d + a == b or a + d == b for d in neigh_del):
            continue
        # שבר פיצול: מילה סופית שכנה שנוספה משלימה את "השגוי" (אםלדוג=אם+לדוג)
        neigh_add = [_PUNCT_RE.sub("", f2) for p, f2 in
                     (aligned[max(0, k - 1):k] + aligned[k + 1:k + 2]) if f2 and not p]
        if any(b + d == a or d + b == a for d in neigh_add):
            continue
        # רק תיקונים "קרובים" — מילה שהוחלפה כליל היא עריכת תוכן, לא תיקון תמלול
        import difflib
        if difflib.SequenceMatcher(None, a, b).ratio() < 0.45:
            continue
        out.append((a, b))
    return out


def add_pairs(pairs, writer=None, scope="both"):
    """צובר זוגות למאגר לפי היקף: personal / general / both. כל זוג
    (שגוי, נכון) סופר בנפרד — ההכרעה בין תיקונים מתחרים היא לפי הרוב
    בזמן הטעינה, כך שטעות בודדת לעולם לא דורסת תיקון מבוסס."""
    if not pairs:
        return 0
    targets = []
    if scope in ("personal", "both") and writer:
        targets.append(_path(writer))
    if scope in ("general", "both"):
        targets.append(GENERAL_FIXES)
    for path in targets:
        fixes = _load_file(path)
        for wrong, right in pairs:
            fixes[(wrong, right)] = fixes.get((wrong, right), 0) + 1
        _save_file(path, fixes)
    _cache.clear()
    return len(pairs)


def import_tsv(text):
    """מיזוג קובץ תיקונים מיובא אל המאגר הכללי (לעולם לא לאישי)."""
    fixes = _load_file(GENERAL_FIXES)
    added = 0
    for line in text.splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
            wrong, right = parts[0].strip(), parts[1].strip()
            try:
                n = int(parts[2]) if len(parts) > 2 else 1
            except ValueError:
                n = 1
            fixes[(wrong, right)] = fixes.get((wrong, right), 0) + max(1, n)
            added += 1
    _save_file(GENERAL_FIXES, fixes)
    _cache.clear()
    return added


def clear(writer=None, scope="both"):
    """מחיקה מלאה של מאגר התיקונים (לבדיקות/תחזוקה — לא בממשק).
    בממשק משתמשים ב-mark_seen: ניקוי תצוגה בלבד."""
    removed = 0
    targets = []
    if scope in ("personal", "both") and writer:
        targets.append(_path(writer))
    if scope in ("general", "both"):
        targets.append(GENERAL_FIXES)
    for path in targets:
        removed += len(_load_file(path))
        try:
            os.remove(path)
        except OSError:
            pass
    _cache.clear()
    return removed


def _seen():
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def mark_seen(writer=None):
    """ניקוי הרשימה בתצוגה בלבד: צילום מצב המונים הנוכחי — הטבלה תציג
    מעתה רק תיקונים שנוספו/התחזקו אחרי הניקוי. **הלמידה עצמה לא נמחקת**
    וכל התיקונים ממשיכים לפעול בהצעות."""
    snap = _seen()
    pair_counts = dict(_load_file(GENERAL_FIXES))
    if writer:
        for k, n in _load_file(_path(writer)).items():
            pair_counts[k] = pair_counts.get(k, 0) + n
    for (w, r), n in pair_counts.items():
        key = w + "\t" + r
        snap[key] = max(snap.get(key, 0), n)
    try:
        with open(SEEN_PATH, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
    except OSError:
        pass
    return len(pair_counts)


def remove(wrong, writer=None):
    """מחיקה נקודתית של תיקון שגוי מהמודל (כל הווריאנטים של המילה),
    מהאישי ומהכללי יחד. מחזיר כמה רשומות הוסרו."""
    removed = 0
    for path in ([_path(writer)] if writer else []) + [GENERAL_FIXES]:
        fixes = _load_file(path)
        drop = [k for k in fixes if k[0] == wrong]
        for k in drop:
            del fixes[k]
            removed += 1
        if drop:
            _save_file(path, fixes)
    _cache.clear()
    return removed


def override(wrong, right, writer=None):
    """עריכת תיקון: המשתמש קובע ידנית את הצורה הנכונה — הזוג החדש מקבל
    מונה שגובר על הרוב הקיים (בכל הקבצים הרלוונטיים), כאילו תוקן שוב ושוב."""
    for path in ([_path(writer)] if writer else []) + [GENERAL_FIXES]:
        fixes = _load_file(path)
        cur_max = max([n for (w, _r), n in fixes.items() if w == wrong] or [0])
        fixes[(wrong, right)] = cur_max + 1
        _save_file(path, fixes)
    _cache.clear()
    return True


def stats(writer=None):
    """סטטיסטיקה לתצוגה: מונים כוללים + טבלת התיקונים שנוספו/התחזקו מאז
    ניקוי-התצוגה האחרון (mark_seen). הלמידה המלאה תמיד פעילה ברקע."""
    per = _majority(_load_file(_path(writer))) if writer else {}
    gen = _majority(_load_file(GENERAL_FIXES))
    merged = load_merged(writer)
    seen = _seen()
    pair_counts = dict(_load_file(GENERAL_FIXES))
    if writer:
        for k, n in _load_file(_path(writer)).items():
            pair_counts[k] = pair_counts.get(k, 0) + n
    top_all = sorted(merged.items(), key=lambda x: -x[1][1])
    visible = [(w, r, n) for w, (r, n) in top_all
               if pair_counts.get((w, r), 0) > seen.get(w + "\t" + r, 0)]
    return {"personal": len(per), "general": len(gen), "active": len(merged),
            "top": [{"wrong": w, "right": r, "count": n}
                    for w, r, n in visible[:20]]}


def export_tsv(writer=None):
    """תוכן קובץ התיקונים של הכותב (או הכללי) לייצוא — כל הזוגות, כולל
    מיעוט (המקבל יכריע רוב מול הנתונים שלו)."""
    fixes = _load_file(_path(writer))
    return "".join(f"{w}\t{r}\t{n}\n" for (w, r), n in
                   sorted(fixes.items(), key=lambda x: -x[1]))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # בדיקה עצמית על קבצים זמניים
    pairs = harvest_pairs("וי בואר דבמו שמצינו בערב סרבנן קבעו",
                          "ויבואר דכמו שמצינו בערב שרבנן קבעו")
    print("harvest:", pairs)
    assert ("דבמו", "דכמו") in pairs and ("סרבנן", "שרבנן") in pairs
    # מילה שהוחלפה כליל — לא תיקון תמלול
    assert not harvest_pairs("שלום עולם", "שלום חברים")
    print("fixes self-test OK")
