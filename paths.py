# -*- coding: utf-8 -*-
r"""ניהול נתיבים מרכזי — ההפרדה בין קבצי התוכנה לקבצי הנתונים.

בהרצה רגילה (פיתוח): הנתונים בתיקיית הפרויקט.
בהרצה כ-EXE ארוז: הנתונים בתיקייה קבועה ונפרדת —
    %LOCALAPPDATA%\KtavYadAI
כך שהאריזה לעולם לא "ננעלת": כל אימון, תיקון וייבוא נשמרים בתיקייה החיצונית,
שממשיכה לצבור נתונים בין גרסה לגרסה. בהפעלה הראשונה של ה-EXE מועתקים אליה
המודלים והנתונים ההתחלתיים שנארזו בפנים (זריעה חד-פעמית).
"""
import os
import sys
import shutil

FROZEN = getattr(sys, "frozen", False)

# בהרצה בלי חלון קונסולה (pythonw / EXE חלוני) אין stdout — נתעל לריק
# כדי שהדפסות לא יפילו את התוכנה
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

if FROZEN:
    # קבצי התוכנה הארוזים (לקריאה בלבד)
    BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    # תיקיית הנתונים החיצונית הקבועה
    BASE = os.path.join(os.environ.get("LOCALAPPDATA",
                                       os.path.expanduser("~")), "KtavYadAI")
else:
    BUNDLE = os.path.dirname(os.path.abspath(__file__))
    BASE = BUNDLE

DATA_DIR = os.path.join(BASE, "data")
MODELS_DIR = os.path.join(BASE, "models")
WRITERS_DIR = os.path.join(DATA_DIR, "writers")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")
CORPUS = os.path.join(DATA_DIR, "corpus_he.txt")
# קורפוס לאימון הסינתטי וליצירת תבניות: המוקטן (corpus_lite) אם קיים —
# בהפצה נשלח רק הוא (21MB), הקורפוס המלא (320MB) לא נארז. מודל השפה
# עובד מהמטמונים (.lm_*.pkl) ולא נוגע בקורפוס כלל.
SYNTH_CORPUS = os.path.join(DATA_DIR, "corpus_lite.txt")
if not os.path.exists(SYNTH_CORPUS) and os.path.exists(CORPUS):
    SYNTH_CORPUS = CORPUS
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")


def _seed_once():
    """בהפעלה ראשונה של EXE: מעתיק את המודלים והנתונים הארוזים לתיקייה החיצונית."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(WRITERS_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    if not FROZEN:
        return
    # קורפוס מוקטן (לאימון הסינתטי) + תצורה + מאגר התיקונים + שלושת מטמוני
    # מודל השפה. הקורפוס המלא לא נארז — מודל השפה עובד מהמטמונים בלבד.
    for name in ("corpus_lite.txt", "config.json", "fixes_general.tsv",
                 ".lm_counts.pkl", ".lm_bigrams.pkl", ".lm_trigrams.pkl"):
        src = os.path.join(BUNDLE, "data", name)
        dst = os.path.join(DATA_DIR, name)
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copy2(src, dst)
    # מודלים ארוזים — מועתקים אם חסרים בחוץ, או אם הגרסה הארוזה חדשה יותר
    # (כך פרסום גרסה חדשה של התוכנה מעדכן את המודלים אצל משתמשים קיימים)
    src_models = os.path.join(BUNDLE, "models")
    if os.path.isdir(src_models):
        for f in os.listdir(src_models):
            if not f.endswith(".pt"):
                continue
            src = os.path.join(src_models, f)
            dst = os.path.join(MODELS_DIR, f)
            if not os.path.exists(dst) or \
                    os.path.getmtime(src) > os.path.getmtime(dst) + 60:
                shutil.copy2(src, dst)
    # כותבים ארוזים (נתוני אימון התחלתיים) — זריעה רק לכותבים שלא קיימים
    src_writers = os.path.join(BUNDLE, "data", "writers")
    if os.path.isdir(src_writers):
        for name in os.listdir(src_writers):
            dst = os.path.join(WRITERS_DIR, name)
            if not os.path.exists(dst):
                shutil.copytree(os.path.join(src_writers, name), dst)


_seed_once()
