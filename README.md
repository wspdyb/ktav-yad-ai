# כתב-יד AI — Offline Hebrew Handwriting Recognition

מערכת מקומית (offline) להמרת **כתב יד עברי** — וגם טקסט מוקלד וצילומי מסך —
לטקסט במחשב. הכול רץ מקומית; שום דבר לא נשלח לאינטרנט.

An offline Hebrew handwriting-recognition (HTR) system: CRNN+CTC optical model,
synthetic pretraining from Hebrew fonts, per-writer fine-tuning with
regression-gated training, a statistical (bigram+trigram) language-model
post-corrector over a 2.5M-line rabbinic Hebrew corpus, a local browser GUI,
and a PyInstaller EXE for distribution. CPU-first (auto-detects CUDA).

## מסמכים / Docs

- **[USER_GUIDE.md](USER_GUIDE.md)** — מדריך למשתמש (עברית, לכולם).
- **[AI_HANDOFF.md](AI_HANDOFF.md)** — technical briefing for AI analysis / handoff (English).
- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** — יומן שינויים מלא ומפורט (עברית).

## הורדה / Download

התוכנה המוכנה להרצה (Windows EXE) מופצת כ-ZIP (‏243MB):
- **GitHub Releases** (בריפו הזה) — נכס `KtavYadAI.zip`.
- **Google Drive** — קישור בתיאור ה-Release ואצל בעל הפרויקט.

מחלצים את ה-ZIP ומריצים `KtavYadAI.exe`. בהפעלה הראשונה התוכנה מכינה את עצמה
(דקה) ונפתחת בדפדפן. עובד מקומית לגמרי.

## הרצה מהמקור / Run from source

```bash
# Python 3.14 venv: torch (CPU), numpy, pillow, pypdfium2, certifi, truststore, pyinstaller
python app.py                     # GUI → http://127.0.0.1:8765
python train.py chain <writer>    # fine-tune: personal then general
python measure_suggest.py 8 21 33 # postfix quality gate (run before any postfix change)
python test_v3.py ; python test_final.py ; python test_user_sim.py 15
```

## מבנה / Layout

מודל: `model.py` `charset.py` · סינתזה: `synth.py` · נתונים: `dataset.py` ·
פילוח: `segment.py` · אינפרנס: `infer.py` · תיקון-אחרי: `postfix.py` `fixes.py` ·
אימון: `train.py` · אפליקציה: `app.py` · נתיבים/אריזה: `paths.py` `main.py`
`build_exe.bat` · קורפוס: `build_corpus.py` `expand_corpus.py` · בוט שיתוף:
`gscript_share/`.

## תוצאות (CER — אחוז שגיאת תווים, נמוך = טוב)

| מודל | CER |
|---|---|
| אישי (כותב יחיד) | **3.49%** |
| כללי (כל הכותבים) | **3.67%** |
| מוקלד / צילום מסך | ‏0.46% סינתטי · ‏10.3% צילום מסך אמיתי |
| עמוד כתב-יד מלא (צינור מלא) | ‏~5–8% |

> נתוני האימון האישיים (כתב היד, הקונטרס) **אינם** בריפו — ראו `.gitignore`.
> ההפצה יוצאת עם פרופיל אישי **ריק**; המשתמש בונה את המודל שלו בעצמו.
