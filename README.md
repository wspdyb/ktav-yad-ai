# כתב-יד AI — Offline Hebrew Handwriting Recognition

מערכת מקומית (offline) להמרת **כתב יד עברי** — וגם טקסט מוקלד וצילומי מסך —
לטקסט במחשב. העיבוד והתמלול מקומיים. לחלופין, המשתמש יכול לבקש במפורש הצעות
תיקון מ-Google AI Studio; רק אז תמונות השורות וטקסט ה-OCR נשלחים ל-Google.

An offline Hebrew handwriting-recognition (HTR) system: CRNN+CTC optical model,
synthetic pretraining from Hebrew fonts, per-writer fine-tuning with
regression-gated training, a statistical (bigram+trigram) language-model
post-corrector over a 2.5M-line rabbinic Hebrew corpus, a local desktop GUI,
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
ונפתחת בדפדפן ברירת המחדל במחשב. התיקיות `data`
ו-`models` נוצרות לצד ה-EXE ושומרות את האימונים והמודלים, כך שאפשר להעביר אותן
יחד עם ה-EXE למחשב אחר.

גרסה **1.0.1** · יוצר: [ARI212121](https://github.com/ARI212121).

## הרצה מהמקור / Run from source

```bash
# Python 3.13/3.14 virtual environment
python -m venv venv
venv\Scripts\pip install -r requirements.txt
python app.py                     # Opens a standalone Edge/Chrome app window
python train.py chain <writer>    # fine-tune: personal then general
python measure_suggest.py 8 21 33 # postfix quality gate (run before any postfix change)
python test_v3.py ; python test_final.py ; python test_user_sim.py 15
```

## בניית EXE נייד / Build portable EXE

On Windows with Python 3.13 or 3.14 installed, run `build_exe.bat`. It creates
the project `venv` if needed and installs/verifies packages automatically.
The final multi-resolution application icon is included as `icon.ico` and used
directly by the build. The script asks how to open the interface; its default is a standalone
Microsoft Edge or Google Chrome app window (`--app` mode), matching the original
desktop behavior without bundling browser packages. Edge or Chrome must be
installed on the computer. Choose the optional Qt WebEngine mode only when a
fully embedded window is preferred; that option installs and bundles the
additional `pywebview[qt]` packages. The embedded window remembers its last
size. In either mode the EXE includes its application icon and version metadata
(1.0.1, creator ARI212121). On first launch it creates
adjacent `release/data` and `release/models` folders; keep those folders with
the EXE when moving the app or preserving training. Startup timings and any
startup errors are recorded in `data/startup.log`; the post-build diagnostic also
records total EXE launch time, including one-file extraction before Python
starts. Every build runs a startup
diagnostic (including PyTorch, the general model, the local server, and icon);
the build is reported as failed if that check does not pass.

Optional AI correction uses Google AI Studio only after an explicit button
click. Choose a number of lines or pages; page selection sends only the
segmented line crops, never the full-page image. Requests are split into
configurable batches of 1, 2, 4, or 8 lines. Add one or more named API keys in the
training tab; Windows DPAPI encrypts them for the current Windows account. If a
key reaches its quota, the app tries the next configured key. Suggested text
is shown as an editable draft and is never saved to training data until the user
applies/reviews it and presses the save button. Each run displays elapsed time
and token usage reported by Google per batch; remaining quota is not returned
by the correction API. Repeating a run to compare batch sizes resends the images
and consumes quota again.

The key manager can explicitly check one key or refresh all connection checks.
This lightweight GET validates access to the configured model without sending
images or generating content; it does not verify remaining generation quota.
Keys belonging to the same Google Cloud project share that project's quota.
For each key, use “טען מודלים” to explicitly fetch its available
`generateContent` models and choose one. The selection is saved per key and is
used for connection checks and when that key is selected during failover; model
discovery is not performed automatically at startup.

## מבנה / Layout

מודל: `model.py` `charset.py` · סינתזה: `synth.py` · נתונים: `dataset.py` ·
פילוח: `segment.py` · אינפרנס: `infer.py` · תיקון-אחרי: `postfix.py` `fixes.py` ·
אימון: `train.py` · אפליקציה: `app.py` · נתיבים/אריזה: `paths.py` `main.py`
`build_exe.bat` · builds one portable EXE that opens a standalone Edge/Chrome
app window by default, with optional embedded Qt WebEngine. Its runtime data is stored beside
it in `data/` and `models/`. If the preferred
local port is busy, the app automatically uses an available port. · קורפוס:
`build_corpus.py` `expand_corpus.py` · בוט שיתוף:
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
