# -*- coding: utf-8 -*-
"""תיקון מילוני אחרי תמלול + הצעות תיקון הקשריות.

שתי שכבות:
1. fix_text — תיקון אוטומטי שמרני: רק מועמד יחיד וחד-משמעי
   (השלמת גרשיים / מרחק עריכה 1 / פיצול רווח שנבלע / איחוי מילה שנחתכה).
2. suggest_line — "אינטליגנציה לשונית": כשיש כמה מועמדים, מודל שפה
   סטטיסטי (bigram שנבנה מהקורפוס הרבני) מדרג אותם לפי ההקשר במשפט.
   התוצאה אינה מוחלת אוטומטית — היא מוצגת למשתמש כהצעה ללחיצה (💡),
   כך שאין שום סיכון לרמת התמלול הבסיסית.
"""
import os
import re
import math
import pickle

from paths import CORPUS, WRITERS_DIR, DATA_DIR

_vocab = None          # כל המילים המוכרות
_counts = None         # תדירות מילה בקורפוס
_label_words = None    # מילים מהתיוגים של הכותבים (משקל גבוה בהצעות)
_bigrams = None        # זוגות מילים עוקבות (count>=3)
_PUNCT_RE = re.compile(r'^[\("\[]*|[\)\.",\]:;!?]*$')
_BIGRAM_CACHE = os.path.join(DATA_DIR, ".lm_bigrams.pkl")
_TRIGRAM_CACHE = os.path.join(DATA_DIR, ".lm_trigrams.pkl")
_COUNTS_CACHE = os.path.join(DATA_DIR, ".lm_counts.pkl")
_trigrams = None       # שלשות מילים עוקבות — ההקשר הדו-מילי של המנוע
_big = False           # קורפוס ענק? (נקבע לפי גודל האוצר שנטען)


def _iter_label_files():
    if os.path.isdir(WRITERS_DIR):
        for name in os.listdir(WRITERS_DIR):
            p = os.path.join(WRITERS_DIR, name, "labels.tsv")
            if os.path.exists(p):
                yield p


def _iter_texts():
    sources = [(CORPUS, False)] + [(p, True) for p in _iter_label_files()]
    for src, is_labels in sources:
        try:
            with open(src, encoding="utf-8") as f:
                for line in f:
                    yield line.split("\t")[-1], is_labels
        except OSError:
            pass


def _corpus_counts():
    """ספירות מילות הקורפוס — במטמון דיסק (.lm_counts.pkl). המטמון הוא
    המקור הסמכותי: בהפצה נשלח רק המטמון (הקורפוס המלא 320MB לא נארז),
    ולכן אם המטמון קיים משתמשים בו ישירות בלי לגעת בקורפוס. הקורפוס
    נדרש רק לבנייה ראשונית (פיתוח) כשאין מטמון."""
    from collections import Counter
    if os.path.exists(_COUNTS_CACHE):
        try:
            with open(_COUNTS_CACHE, "rb") as f:
                return pickle.load(f)
        except (OSError, pickle.PickleError):
            pass
    counts = Counter()
    try:
        with open(CORPUS, encoding="utf-8") as f:
            for line in f:
                for w in line.split():
                    w = _PUNCT_RE.sub("", w)
                    if len(w) >= 2:
                        counts[w] += 1
    except OSError:
        pass
    try:
        with open(_COUNTS_CACHE, "wb") as f:
            pickle.dump(counts, f)
    except OSError:
        pass
    return counts


def _load_lm():
    """בונה אוצר מילים + ספירות + ביגרמות + טריגרמות. שלושת המטמונים הם
    המקור הסמכותי (מנותקים מקובץ הקורפוס — ראו _corpus_counts); התיוגים
    של הכותבים (קטנים, משתנים) נספרים תמיד חי ומתמזגים פנימה."""
    global _vocab, _counts, _label_words, _bigrams, _trigrams, _big
    from collections import Counter
    counts = _corpus_counts().copy()
    label_words = set()
    for p in _iter_label_files():
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    for w in line.split("\t")[-1].split():
                        w = _PUNCT_RE.sub("", w)
                        if len(w) >= 2:
                            counts[w] += 1
                            label_words.add(w)
        except OSError:
            pass
    # מילת קורפוס נכנסת לאוצר רק אם מופיעה פעמיים+ (מופע בודד = לרוב שיבוש)
    _counts = counts
    _label_words = label_words
    _vocab = label_words | {w for w, c in counts.items() if c >= 2}
    # "קורפוס ענק" נקבע לפי גודל האוצר שנטען (לא לפי קובץ הקורפוס, שאולי
    # לא נארז) — קובע ספי-שכיחות ל-_strong ולסינון הביגרמות
    _big = len(counts) > 200_000
    # ביגרמות + טריגרמות — מהמטמון אם קיים (סמכותי), אחרת בנייה מהקורפוס
    _bigrams, _trigrams = {}, {}
    if os.path.exists(_BIGRAM_CACHE) and os.path.exists(_TRIGRAM_CACHE):
        try:
            with open(_BIGRAM_CACHE, "rb") as f:
                _bigrams = pickle.load(f)
            with open(_TRIGRAM_CACHE, "rb") as f:
                _trigrams = pickle.load(f)
            return
        except (OSError, pickle.PickleError):
            _bigrams, _trigrams = {}, {}
    from sys import intern
    bi, tri = Counter(), Counter()
    PRUNE_AT = 12_000_000     # גיזום יחידאים כשהמונה תופח — קורפוס ענק
    for text, _ in _iter_texts():
        ws = [intern(_PUNCT_RE.sub("", w)) for w in text.split()]
        ws = [w for w in ws if len(w) >= 2]
        for a, b in zip(ws, ws[1:]):
            bi[(a, b)] += 1
        for a, b, c in zip(ws, ws[1:], ws[2:]):
            tri[(a, b, c)] += 1
        if len(tri) > PRUNE_AT:
            tri = Counter({k: v for k, v in tri.items() if v >= 2})
        if len(bi) > PRUNE_AT:
            bi = Counter({k: v for k, v in bi.items() if v >= 2})
    # סף דינמי: בקורפוס ענק ביטוי דורש 3 מופעים, ותקרת 4M זוגות —
    # שליטה בזיכרון ובנפח ההפצה בלי לוותר על הרוחב הסטטיסטי
    _bigrams = {k: v for k, v in bi.items() if v >= (3 if _big else 2)}
    del bi
    if len(_bigrams) > 4_000_000:
        _bigrams = dict(sorted(_bigrams.items(),
                               key=lambda x: -x[1])[:4_000_000])
    # טריגרמות: סף 3 + תקרת 2.5M (זיכרון של מכונת קצה) — נשמרות השכיחות
    tri = {k: v for k, v in tri.items() if v >= 3}
    if len(tri) > 2_500_000:
        top = sorted(tri.items(), key=lambda x: -x[1])[:2_500_000]
        tri = dict(top)
    _trigrams = tri
    try:
        with open(_BIGRAM_CACHE, "wb") as f:
            pickle.dump(_bigrams, f)
        with open(_TRIGRAM_CACHE, "wb") as f:
            pickle.dump(_trigrams, f)
    except OSError:
        pass


def _ensure_lm():
    if _vocab is None:
        _load_lm()


def _edits1(word):
    """כל הווריאציות במרחק עריכה 1 (מחיקה/החלפה/החלפת סדר) — בלי הוספות,
    כדי לשמור על זהירות."""
    letters = "אבגדהוזחטיכךלמםנןסעפףצץקרשת"
    out = set()
    for i in range(len(word)):
        out.add(word[:i] + word[i + 1:])                      # מחיקה
        for c in letters:
            out.add(word[:i] + c + word[i + 1:])              # החלפה
        if i < len(word) - 1:
            out.add(word[:i] + word[i + 1] + word[i] + word[i + 2:])  # שיכול
    out.discard(word)
    return out


def _letter_insertions(word):
    """וריאציות עם אות אחת שנוספה — רק למנוע ההצעות (המשתמש מאשר),
    לא לתיקון האוטומטי: אות שהמודל 'בלע' (ונשעבדה -> ונשתעבדה)."""
    letters = "אבגדהוזחטיכךלמםנןסעפףצץקרשת"
    out = set()
    for i in range(len(word) + 1):
        for c in letters:
            out.add(word[:i] + c + word[i:])
    return out


def _quote_insertions(word):
    """וריאציות עם גרשיים/גרש שהוכנסו באמצע המילה — לתיקון ראשי תיבות
    שהמודל פספס בהם את סימן הגרשיים (בעח -> בע"ח)."""
    out = set()
    for i in range(1, len(word)):
        out.add(word[:i] + '"' + word[i:])
        out.add(word[:i] + "'" + word[i:])
    out.add(word + "'")  # גרש בסוף — קיצורים כמו לכאו', וכו', אפי'
    return out


# תחיליות נפוצות — מילה שהיא תחילית + מילה מוכרת נחשבת תקינה ולא תתוקן
_PREFIXES = ("ו", "ה", "ב", "ל", "כ", "מ", "ש", "ד", "וה", "וש", "וב", "ול",
             "וכ", "ומ", "וד", "שה", "כש", "מה", "שב", "דב", "לכש", "וכש", "ומה")


def _known(core):
    if core in _vocab:
        return True
    for p in _PREFIXES:
        if core.startswith(p):
            base = core[len(p):]
            # תחילית מתקבלת רק אם מילת הבסיס שכיחה באמת — אחרת מילה
            # נדירה/זיהום מהקורפוס "מכשירה" בטעות שגיאות תמלול (ד+במו)
            if base in _vocab and (base in _label_words or
                                   _counts.get(base, 0) >= 5):
                return True
    return False


def _strong_min():
    """סף שכיחות ל"מילה חזקה" — מדורג לגודל האוצר שנטען: בקורפוס ענק גם
    שברי-זבל (ונ, וכ) צוברים חמישה מופעים, והסף חייב לעלות איתו. מבוסס
    על _big (גודל האוצר), לא על קובץ הקורפוס שאולי לא נארז בהפצה."""
    return 20 if _big else 5


def _strong(w):
    """מילה "חזקה": מוכרת ישירות וגם שכיחה באמת (או מתיוגי הכותב) —
    התנאי לחלקי פיצול, כדי שזבל-קורפוס לא יכשיר פיצולים שגויים
    (ונשעבדה -> ונש עבדה / ונ שעבדה). שבר קצר (2 אותיות) שאינו מילת
    תיוג לעולם אינו חלק-פיצול תקין."""
    if w in _label_words:
        return w in _vocab
    return w in _vocab and len(w) >= 3 and _counts.get(w, 0) >= _strong_min()


def _split_candidates(core):
    """פירוקים של מילה לא-מוכרת לשתי מילים חזקות — לתיקון רווח שנבלע
    בתמלול (אםלדוג' -> אם לדוג'). כל חלק באורך 2 לפחות."""
    out = []
    for i in range(2, len(core) - 1):
        a, b = core[:i], core[i:]
        # לא חוצים ראשי תיבות באמצע הגרשיים
        if a[-1] in "\"'" or b[0] in "\"'":
            continue
        if _strong(a) and _strong(b):
            out.append(a + " " + b)
    return out


def fix_text(text, writer=None):
    """תיקון אוטומטי שמרני: רק מועמד יחיד. גרשיים -> מרחק 1 -> פיצול ->
    איחוי זוג (שתי מילים לא-מוכרות שחיבורן מילה מוכרת: וי בואר -> ויבואר).
    מילה שיש לה תיקון נלמד מהמשתמש לא מתוקנת כאן — כדי שהתיקון האוטומטי
    לא "יחטוף" אותה (יוכ->יו\"כ) לפני שמנוע ההצעות יציע את הנלמד (יוכל)."""
    _ensure_lm()
    if not _vocab:
        return text
    import fixes as _fixes_mod
    learned = _fixes_mod.load_merged(writer)
    out_words = []
    for token in text.split(" "):
        core = _PUNCT_RE.sub("", token)
        if len(core) < 2 or _known(core) or core in learned:
            out_words.append(token)
            continue
        has_quote = '"' in core or "'" in core
        if not has_quote:
            # קודם: החזרת גרשיים חסרים (ראשי תיבות) — הטעות הנפוצה ביותר
            q_candidates = {w for w in _quote_insertions(core) if w in _vocab}
            if len(q_candidates) == 1:
                out_words.append(token.replace(core, q_candidates.pop(), 1))
                continue
            if len(core) >= 3:
                candidates = {w for w in _edits1(core) if w in _vocab}
                if len(candidates) == 1:
                    out_words.append(token.replace(core, candidates.pop(), 1))
                    continue
        # רווח שנבלע: מילה ארוכה לא-מוכרת שמתפרקת באופן יחיד לשתי מוכרות
        if len(core) >= 6:
            splits = _split_candidates(core)
            if len(splits) == 1:
                out_words.append(token.replace(core, splits[0], 1))
                continue
        out_words.append(token)
    # איחוי: מילה שנחתכה לשניים — שני חלקים לא-מוכרים שחיבורם מוכר
    joined, i = [], 0
    while i < len(out_words):
        tok = out_words[i]
        core = _PUNCT_RE.sub("", tok)
        if i + 1 < len(out_words) and tok == core and len(core) >= 2:
            nxt = out_words[i + 1]
            ncore = _PUNCT_RE.sub("", nxt)
            if len(ncore) >= 2 and not _known(core) and not _known(ncore) \
                    and (core + ncore) in _vocab:
                joined.append(core + nxt)
                i += 2
                continue
        joined.append(tok)
        i += 1
    return " ".join(joined)


# ---------------------------------------------------------------- הצעות
def _ctx_score(prev, w, nxt, is_join=False):
    """ניקוד הקשרי למועמד: ההקשר (ביגרמות עם השכנים) הוא הסיגנל המרכזי;
    התדירות מוגבלת בתקרה כדי שמילה שכיחה לא "תדרוס" את ההקשר."""
    parts = w.split(" ")
    s = 0.0
    if prev:
        s += 1.5 * math.log1p(_bigrams.get((prev, parts[0]), 0))
    if nxt:
        s += 1.5 * math.log1p(_bigrams.get((parts[-1], nxt), 0))
    if len(parts) == 2:
        s += 1.0 * math.log1p(_bigrams.get((parts[0], parts[1]), 0))
    for p in parts:
        s += 0.15 * min(math.log1p(_counts.get(p, 0)), 6.0)
        if p in _label_words:
            s += 0.75
    if is_join:
        s += 0.5   # שני שברים שמתחברים למילה מוכרת = ראיה מבנית חזקה
    return s


def suggest_line_v1(text, min_score=1.2, writer=None):
    """הגרסה הישנה (ניקוד פר-מילה, חמדני) — נשמרת להשוואת A/B במדידות.
    הגרסה הפעילה היא suggest_line (ניקוד שרשרת לכל השורה)."""
    _ensure_lm()
    if not _vocab:
        return text, []
    import fixes as _fixes_mod
    learned = _fixes_mod.load_merged(writer)
    tokens = text.split(" ")
    cores = [_PUNCT_RE.sub("", t) for t in tokens]
    changes = []
    out = list(tokens)
    skip_next = False
    for i, (tok, core) in enumerate(zip(tokens, cores)):
        if skip_next:
            skip_next = False
            continue
        # תיקון שנלמד מהמשתמש גובר על הכול (גם על מילה "מוכרת")
        if core in learned:
            right, n = learned[core]
            if right != core:
                out[i] = tok.replace(core, right, 1)
                changes.append((core, right))
                continue
        if len(core) < 2:
            continue
        # מילה שמוכרת ישירות — מדולגת; מילה שמוכרת רק דרך תחילית (ד+במו)
        # עדיין מועמדת להצעה, אך רק אם מועמד גובר עליה בהקשר במרווח ברור
        direct = core in _vocab
        if direct and len(core) >= 3:
            continue
        prev = cores[i - 1] if i > 0 and len(cores[i - 1]) >= 2 else None
        nxt = cores[i + 1] if i + 1 < len(cores) and len(cores[i + 1]) >= 2 else None
        # מועמד איחוי: המילה הנוכחית + הבאה = מילה מוכרת (וי בואר -> ויבואר)
        join_cand, join_score = None, -1.0
        if i + 1 < len(tokens) and nxt and tok == core:
            joined = core + nxt
            j_core = _PUNCT_RE.sub("", joined)
            if j_core in _vocab and (not _known(core) or not _known(nxt)):
                nxt2 = cores[i + 2] if i + 2 < len(cores) and \
                    len(cores[i + 2]) >= 2 else None
                join_cand = joined
                join_score = _ctx_score(prev, j_core, nxt2, is_join=True)
        # מועמדי החלפה למילה בודדת (לא-מוכרת ישירות, באורך 3+)
        best, best_score = None, -1.0
        if len(core) >= 3 and not direct:
            cands = set()
            if '"' not in core and "'" not in core:
                cands |= {w for w in _quote_insertions(core) if w in _vocab}
                cands |= {w for w in _edits1(core) if w in _vocab}
                cands |= {w for w in _letter_insertions(core) if w in _vocab}
            if len(core) >= 6:
                cands |= set(_split_candidates(core))
            if cands and len(cands) <= 40:
                best = max(cands, key=lambda w: _ctx_score(prev, w, nxt))
                best_score = _ctx_score(prev, best, nxt)
                if _known(core):
                    # מוכרת-דרך-תחילית: המועמד חייב לגבור עליה בהקשר
                    if best_score < _ctx_score(prev, core, nxt) + 0.8:
                        best, best_score = None, -1.0
        if join_cand and join_score >= max(best_score, min_score):
            out[i] = core + tokens[i + 1]
            out[i + 1] = None
            changes.append((core + " " + cores[i + 1], _PUNCT_RE.sub("", join_cand)))
            skip_next = True
        elif best is not None and best_score >= min_score:
            out[i] = tok.replace(core, best, 1)
            changes.append((core, best))
    return " ".join(t for t in out if t is not None), changes


# ------------------------------------------------- הצעות v2: ניקוד שרשרת
def page_word_counts(texts):
    """ספירת מילות עמוד/מסמך — ההקשר הרב-שורתי של מנוע ההצעות."""
    from collections import Counter
    c = Counter()
    for t in texts:
        for w in t.split():
            w = _PUNCT_RE.sub("", w)
            if len(w) >= 2:
                c[w] += 1
    return c


def _chain_word_score(prev, w, page_words=None, is_join=False, orig=False,
                      prev2=None):
    """ניקוד מילה בשרשרת: טריגרמה (הקשר דו-מילי) + ביגרמה + תדירות (בתקרה)
    + בונוסים. בונוס העמוד ניתן רק למועמדים (orig=False) — מילה שגויה
    שהמודל חוזר עליה בעקביות לא תחזק את עצמה. ה"שכן הבא" מגיע באופן
    טבעי מהצעד הבא של השרשרת (ה-prev/prev2 שלו הם אנחנו)."""
    parts = w.split(" ")
    s = 1.5 * math.log1p(_bigrams.get((prev, parts[0]), 0)) if prev else 0.0
    if prev and prev2:
        s += 1.8 * math.log1p(_trigrams.get((prev2, prev, parts[0]), 0))
    if len(parts) == 2:
        s += 1.0 * math.log1p(_bigrams.get((parts[0], parts[1]), 0))
        if prev:
            s += 1.2 * math.log1p(_trigrams.get((prev, parts[0], parts[1]), 0))
    for p in parts:
        s += 0.15 * min(math.log1p(_counts.get(p, 0)), 6.0)
        if p in _label_words:
            s += 0.75
        if page_words is not None and not orig:
            s += 0.4 * min(page_words.get(p, 0), 3)
    if is_join:
        s += 0.5
    return s


def advance_tail(prev2, prev, text):
    """מקדם את זנב-ההקשר (שתי המילים האחרונות) אחרי שורה — לרצף חוצה-שורות."""
    ws = [c for c in (_PUNCT_RE.sub("", x) for x in text.split()) if len(c) >= 2]
    if not ws:
        return prev2, prev
    if len(ws) == 1:
        return prev, ws[-1]
    return ws[-2], ws[-1]


def _replacement_candidates(core, direct):
    """מועמדי החלפה לעמדה אחת — אותם שערים של הגרסה הישנה. מילה מוכרת
    (direct) מקבלת מועמדים רק מראשי-התיבות של תיוגי הכותב (דבק -> דב"ק):
    מילת קורפוס אמיתית עלולה להיות ר"ת אצל הכותב, וההקשר + המרווח יכריעו."""
    if len(core) < 3:
        return []
    if direct:
        if '"' not in core and "'" not in core:
            return [w for w in _quote_insertions(core) if w in _label_words]
        return []
    cands = set()
    if '"' not in core and "'" not in core:
        cands |= {w for w in _quote_insertions(core) if w in _vocab}
        cands |= {w for w in _edits1(core) if w in _vocab}
        cands |= {w for w in _letter_insertions(core) if w in _vocab}
    if len(core) >= 6:
        cands |= set(_split_candidates(core))
    # התפוצצות מועמדים = אין אות ברורה — עדיף לשתוק
    return list(cands) if len(cands) <= 40 else []


def _score_assignment(tokens, cores, choice, page_words, prev0=None,
                      prev20=None):
    """ניקוד שרשרת מלא של שורה תחת השמה נתונה (choice[i] = מילה/None=מקור,
    'JOIN' = מוזגה לתוך הקודמת). prev0/prev20 = הקשר פתיחה חוצה-שורות."""
    s, prev, prev2 = 0.0, prev0, prev20
    i = 0
    while i < len(tokens):
        if choice.get(i) == "JOIN":
            i += 1
            continue
        w = choice.get(i)
        if w is None:
            core = cores[i]
            if len(core) >= 2:
                s += _chain_word_score(prev, core, page_words, orig=True,
                                       prev2=prev2)
                prev2, prev = prev, core
        else:
            is_join = (i + 1 < len(tokens) and choice.get(i + 1) == "JOIN")
            s += _chain_word_score(prev, w, page_words, is_join=is_join,
                                   prev2=prev2)
            parts = w.split(" ")
            prev2 = parts[0] if len(parts) == 2 else prev
            prev = parts[-1]
        i += 1
    return s


def suggest_line(text, min_score=1.2, writer=None, page_words=None,
                 prev_tail=None, prev_tail2=None):
    """הצעת תיקון הקשרית לשורה שלמה — ניקוד שרשרת (beam קטן):
    תיקונים סמוכים מחזקים זה את זה (ה-prev המתוקן משפיע על הבא), ואוצר
    מילות העמוד (page_words, בלי מילות השורה עצמה) מחזק מועמדים חוזרים.
    שמרנות: כל תיקון בודד חייב לתרום לשרשרת לפחות min_score בהקשר הסופי,
    ומילה המוכרת-דרך-תחילית מקבלת מרווח הגנה של 0.8. מחזירה
    (טקסט מוצע, [(לפני, אחרי)]) — לא מוחל אוטומטית אלא מוצג לאישור."""
    _ensure_lm()
    if not _vocab:
        return text, []
    import fixes as _fixes_mod
    learned = _fixes_mod.load_merged(writer)
    tokens = text.split(" ")
    raw_cores = [_PUNCT_RE.sub("", t) for t in tokens]

    def _join_fragment(i, right):
        """ה"נכון" הנלמד הוא בעצם איחוי עם שכן (קא->סליקא ליד סלי) —
        לא מחילים כהחלפת מילה בודדת; ה-beam יאחה נכון דרך מסלול האיחוי."""
        prev_c = raw_cores[i - 1] if i > 0 else ""
        nxt_c = raw_cores[i + 1] if i + 1 < len(tokens) else ""
        return (prev_c and prev_c + raw_cores[i] == right) or \
               (nxt_c and raw_cores[i] + nxt_c == right)

    # שלב 0: תיקונים שנלמדו — החלפה ישירה רק כשהמילה השגויה אינה מילה
    # אמיתית; מילה נלמדת שהיא גם מילת אוצר (קא, נשם) נכנסת ל-beam
    # כמועמד מתוגבר, כדי שההקשר יכריע ולא נשבש שימוש תקין בה.
    pre_changes = []
    learned_cand = {}      # עמדה -> (נכון, בונוס)
    for i, tok in enumerate(list(tokens)):
        core = raw_cores[i]
        if core in learned:
            right, n = learned[core]
            if right == core or _join_fragment(i, right):
                continue
            if core not in _vocab:
                tokens[i] = tok.replace(core, right, 1)
                pre_changes.append((core, right))
            else:
                learned_cand[i] = (right, 1.2 + 0.2 * min(n, 4))
    cores = [_PUNCT_RE.sub("", t) for t in tokens]
    # מועמדים לכל עמדה (+ עונש מרווח למילה מוכרת/מוכרת-דרך-תחילית)
    options = []          # options[i] = [(מילה, עונש)]
    for i, (tok, core) in enumerate(zip(tokens, cores)):
        direct = core in _vocab and len(core) >= 3
        opts = []
        if len(core) >= 2:
            penalty = 0.8 if _known(core) else 0.0
            opts = [(w, penalty) for w in _replacement_candidates(core, direct)]
        if i in learned_cand:
            right, bonus = learned_cand[i]
            opts = [(w, p) for w, p in opts if w != right]
            opts.append((right, -bonus))   # עונש שלילי = בונוס נלמד
        options.append(opts)
    # מועמדי איחוי: עמדה i בולעת את i+1. באוצר ענק שברי מילה (וי, בואר)
    # נעשים "מוכרים" בעצמם — לכן איחוי מותר גם כששניהם מוכרים, אם המילה
    # המאוחה היא מתיוגי הכותב עצמו (ויבואר) — ראיה חזקה שזה פיצול-סורק
    joinable = set()
    for i in range(len(tokens) - 1):
        core, nxt = cores[i], cores[i + 1]
        if tokens[i] == core and len(core) >= 2 and len(nxt) >= 2 and \
                (core + nxt) in _vocab and \
                ((not _known(core) or not _known(nxt)) or
                 (core + nxt) in _label_words):
            joinable.add(i)
    if not any(options) and not joinable:
        return " ".join(tokens), pre_changes
    # beam על העמדות: מצב = (ניקוד, prev2, prev, השמה חלקית). זנב השורה
    # הקודמת (שתי מילים) = הקשר הפתיחה — רצף הטקסט נמשך מעבר לשבירת
    # השורות, ולכן טריגרמה חוצת-שורות היא הקשר אמיתי ("תיקון מורחב").
    prev0 = prev_tail if prev_tail and len(prev_tail) >= 2 else None
    prev20 = prev_tail2 if prev0 and prev_tail2 and len(prev_tail2) >= 2 else None
    BEAM = 6
    beams = [(0.0, prev20, prev0, {})]
    for i, tok in enumerate(tokens):
        core = cores[i]
        nxt_states = []
        for score, prev2, prev, choice in beams:
            if choice.get(i) == "JOIN":     # נבלעה על ידי איחוי קודם
                nxt_states.append((score, prev2, prev, choice))
                continue
            # 1. השארת המקור
            if len(core) >= 2:
                s = _chain_word_score(prev, core, page_words, orig=True,
                                      prev2=prev2)
                nxt_states.append((score + s, prev, core, choice))
            else:
                nxt_states.append((score, prev2, prev, choice))
            # 2. החלפה במועמד
            for w, penalty in options[i]:
                s = _chain_word_score(prev, w, page_words, prev2=prev2) - penalty
                nc = dict(choice)
                nc[i] = w
                parts = w.split(" ")
                np2 = parts[0] if len(parts) == 2 else prev
                nxt_states.append((score + s, np2, parts[-1], nc))
            # 3. איחוי עם הבאה
            if i in joinable:
                joined = core + cores[i + 1]
                s = _chain_word_score(prev, joined, page_words, is_join=True,
                                      prev2=prev2)
                nc = dict(choice)
                nc[i] = joined
                nc[i + 1] = "JOIN"
                nxt_states.append((score + s, prev, joined, nc))
        nxt_states.sort(key=lambda x: -x[0])
        beams = nxt_states[:BEAM]
    best_choice = beams[0][3]
    changed = [i for i, w in best_choice.items() if w != "JOIN"]
    if not changed:
        return " ".join(tokens), pre_changes
    # שמרנות: כל תיקון חייב לתרום min_score בהקשר הסופי — מסירים את
    # החלשים בזה אחר זה (ההקשר משתנה עם כל הסרה, לכן איטרטיבית)
    while changed:
        full = _score_assignment(tokens, cores, best_choice, page_words,
                                 prev0, prev20)
        weakest, weakest_gain = None, None
        for i in changed:
            reverted = dict(best_choice)
            del reverted[i]
            if i + 1 < len(tokens) and reverted.get(i + 1) == "JOIN":
                del reverted[i + 1]
            gain = full - _score_assignment(tokens, cores, reverted,
                                            page_words, prev0, prev20)
            if weakest_gain is None or gain < weakest_gain:
                weakest, weakest_gain = i, gain
        if weakest_gain >= min_score:
            break
        del best_choice[weakest]
        if weakest + 1 < len(tokens) and best_choice.get(weakest + 1) == "JOIN":
            del best_choice[weakest + 1]
        changed = [i for i, w in best_choice.items() if w != "JOIN"]
    if not changed:
        return " ".join(tokens), pre_changes
    # בניית הפלט + רשימת השינויים
    out, changes = [], list(pre_changes)
    i = 0
    while i < len(tokens):
        w = best_choice.get(i)
        if w == "JOIN":
            i += 1
            continue
        if w is None:
            out.append(tokens[i])
        elif best_choice.get(i + 1) == "JOIN":
            # tokens[i] הוא core נקי (תנאי האיחוי); הפיסוק של הבאה נשמר
            out.append(tokens[i + 1].replace(cores[i + 1], w, 1))
            changes.append((cores[i] + " " + cores[i + 1], w))
        else:
            out.append(tokens[i].replace(cores[i], w, 1))
            changes.append((cores[i], w))
        i += 1
    return " ".join(out), changes


def refresh_vocab():
    global _vocab, _counts, _label_words, _bigrams, _trigrams, _big
    _vocab = _counts = _label_words = _bigrams = _trigrams = None
    _big = False


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tests = ["ואל יגבה הניזק מעידית.",
             "וי בואר דכמו שמצינו בערב סרבנן קבעו את העדיבות",
             "אך אםלדוג' יבוא הבעח"]
    for t in tests:
        f = fix_text(t)
        s, ch = suggest_line(f)
        print("קלט :", t)
        print("אוטו:", f)
        print("הצעה:", s, ch if ch else "")
        print()
