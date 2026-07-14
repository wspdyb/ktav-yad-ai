# -*- coding: utf-8 -*-
"""בונה דוח השוואה ויזואלי (HTML) בין שורות כתב היד לטקסט המוקלד — עמוד הדגמה."""
import os
import base64
import html as H

HERE = os.path.dirname(os.path.abspath(__file__))
LINES = os.path.join(HERE, "data", "kuntres_lines", "page_001")
OUT_HTML = os.path.join(HERE, "data", "kuntres_demo.html")
ALIGN_DIR = os.path.join(HERE, "data", "kuntres_align")

# ההצמדה של עמוד 1 (סריקה 1.jpg <-> קונטרס.docx פסקאות 676-681)
# label = הטקסט לאימון (נאמן לכתב היד), typed = מה שמופיע בקובץ המוקלד (אם שונה)
ALIGN = [
    ("line_00.png", None, None, 'כותרת העמוד: בס"ד, "סיכומי סוגיות" והערות למקלידה — לא חלק מהטקסט, לא ייכנס לאימון'),
    ("line_01.png", 'ויש לדחות זאת דאי אפשר לומר "אי אפשי בתקנ"ח"', None, "תחילת ההתאמה — בדיוק במילים שציינת"),
    ("line_02.png", 'כאשר אחרים יפסידו מזה (-במקרה כאן יפסידו הבע"ח וכתובת', 'כאשר אחרים יפסידו מזה (-במקרה כאן יפסידו מזה הבע"ח וכתובת', 'במוקלד מופיע "מזה" פעם שנייה שלא נראה בכתב היד'),
    ("line_03.png", "אישה).", "אשה).", 'בכתב היד "אישה" בכתיב מלא, במוקלד "אשה"'),
    ("line_04.png", 'הרא"ש מוסיף דאם הניזק ראשון בגבייה ומעוניין לקבל את העידית', 'הראש מוסיף דאם הניזק ראשון בגבייה ומעוניין לקבל את העידית', 'המילה "בגבייה" הוכנסה בכתב היד מעל השורה עם סימן ^ ושולבה במקומה; "דאם" — אושר על ידך'),
    ("line_05.png", "במקרה שהובא, הוא יוכל לפייס את הלוקח ראשון", None, 'המילה השנייה קשה לקריאה — אימצתי את המוקלד "שהובא"'),
    ("line_06.png", "ואז יגבה הניזק מעידית.", None, None),
    ("line_07.png", 'והנתיה"מ מבאר את דבריו שכוונתו היא שיפייס הניזק', 'והנתיה"מ מבאר דבריו שכוונתו היא שיפייס הניזק', 'בכתב היד יש "את" שהושמט במוקלד; המילה הקטנה בתחתית ("העידית") שייכת לשורה הבאה'),
    ("line_08.png", 'את לוקח העידית ע"מ שיאמר "אי אפשי בתקנת הנחתי לך', None, '"העידית" הוכנסה מעל השורה עם סימן ^ ושולבה במקומה'),
    ("line_09.png", 'מקום וכו\'" וממילא יוכל הניזק שהוא ראשון לגבייה', None, None),
    ("line_10.png", 'לגבות מן העידית [שברגע שאומר הלוקח "אי אפשי" עומד', 'לגבות מן העידית [שברגע שיאמר הלוקח "אי אפשי" עומד', '"[שברגע" — אושר על ידך; בכתב היד "שאומר" ובמוקלד "שיאמר"'),
    ("line_11.png", 'לרשות הגובה לגבייה הן הקרקע שנאמר עליה "אי אפשי"', None, None),
    ("line_12.png", "והן האחרונה בקנין].", "והן האחרונה בקניין].", "כתיב: קנין/קניין"),
    ("line_13.png", 'אומנם כ"ז הוא רק כשגובה כדיניה, אך אם לדוג\'', None, 'קריאה לא ודאית של "כ"ז" — אימצתי את המוקלד'),
    ("line_14.png", 'הבע"ח (האמצעי לגבייה) יפייס את בעל העידית שיאמר "אי', None, None),
    ("line_15.png", 'אפשי" (לאחר שהניזק גבה מהזיבורית שהיא האחרונה) עדיין', 'אפשי" (לאחר שהניזק גבה מהזיבורית שהיא אחרונה) עדיין', 'בכתב היד "האחרונה" עם ה"א הידיעה'),
    ("line_16.png", 'לא יוכל הבע"ח לגבות מהעידית כיון שכעת עומד לגבייתו', None, None),
    ("line_17.png", 'הן העידית והן הבינונית (שהיא עומדת לגבייה עבורו בסדר הגבייה)', None, '"לגבייה עבורו" הוכנס מעל השורה ושולב במקומו'),
    ("line_18.png", 'וכיון שדינו של הבע"ח הוא בבינונית, ייאלץ לגבות', 'וכיון שדינו של הבע"ח הוא בבינונית, יאלץ לגבות', 'בכתב היד "ייאלץ" בשני יו"דים — אושר על ידך'),
    ("line_19.png", "מבינונית.", "מהבינונית.", 'בכתב היד "מבינונית", במוקלד "מהבינונית"'),
    ("line_20.png", 'בחזו"א מבאר את פיוס הניזק ללוקח באופן אחר,', 'החזו"א מבאר את פיוס הניזק ללוקח באופן אחר,', 'האות הראשונה נראית ב\' (בחזו"א) ובמוקלד ה\' (החזו"א)'),
    ("line_21.png", 'לפי דבריו גם הבע"ח וכתובת אישה יוכלו לעשות כן,', 'ולפי דבריו גם הבע"ח וכתובת אישה יוכלו לעשות כן,', 'במוקלד "ולפי" עם ו\' החיבור'),
    ("line_22.png", None, None, 'מספר העמוד "100" — לא ייכנס לאימון'),
]


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


rows = []
n_match, n_diff, n_skip = 0, 0, 0
for fname, label, typed, note in ALIGN:
    img = b64(os.path.join(LINES, fname))
    if label is None:
        n_skip += 1
        status, color, badge = "מדולג", "#9aa0a6", "לא לאימון"
        body = f'<div class="note">{H.escape(note)}</div>'
    elif typed:
        n_diff += 1
        status, color, badge = "הבדל", "#b26a00", "הבדל מהמוקלד"
        body = (f'<div class="lbl">תווית לאימון (נאמן לכתב היד): <b>{H.escape(label)}</b></div>'
                f'<div class="typ">בקובץ המוקלד: {H.escape(typed)}</div>'
                + (f'<div class="note">💡 {H.escape(note)}</div>' if note else ""))
    else:
        n_match += 1
        status, color, badge = "תואם", "#1a7a4a", "תואם"
        body = (f'<div class="lbl">תווית לאימון: <b>{H.escape(label)}</b></div>'
                + (f'<div class="note">💡 {H.escape(note)}</div>' if note else ""))
    rows.append(f'''<div class="row">
<div class="imgwrap"><img src="data:image/png;base64,{img}"></div>
<div class="badge" style="background:{color}">{badge}</div>
{body}
</div>''')

html_doc = f'''<!DOCTYPE html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<title>דוח השוואה — עמוד 1</title><style>
body{{font-family:Segoe UI,Arial;background:#f0f2f5;margin:0;color:#1a1a2e}}
header{{background:#16213e;color:#fff;padding:18px 28px}}
main{{max-width:1150px;margin:18px auto;padding:0 14px}}
.row{{background:#fff;border-radius:10px;padding:14px 18px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,.08);position:relative}}
.imgwrap{{background:#fff;overflow-x:auto}} .imgwrap img{{max-width:100%;display:block}}
.badge{{position:absolute;top:10px;left:12px;color:#fff;border-radius:12px;padding:2px 12px;font-size:13px}}
.lbl{{font-size:18px;margin-top:8px}} .typ{{font-size:16px;color:#8a4b00;margin-top:4px}}
.note{{font-size:14px;color:#555;margin-top:4px}}
.sum{{background:#fff;border-radius:10px;padding:16px 20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.08);font-size:16px}}
</style></head><body>
<header><h2>דוח השוואה: כתב יד ↔ טקסט מוקלד — סריקה 1.jpg מול קונטרס.docx</h2>
<div>ההתאמה מתחילה במילים: "ויש לדחות זאת דאי אפשר לומר..." (עמוד 42 במוקלד)</div></header>
<main>
<div class="sum">✅ {n_match} שורות תואמות במלואן &nbsp;|&nbsp; ⚠️ {n_diff} שורות עם הבדל קטן בין כתב היד למוקלד (מוצג בשתי גרסאות) &nbsp;|&nbsp; ⏭️ {n_skip} קטעים מדולגים (כותרת ומספר עמוד)<br>
כלל העבודה: תווית האימון נאמנה למה שכתוב <b>ביד</b> בפועל, לא לגרסה הערוכה של ההקלדה. מילים שהוכנסו מעל השורה בסימן ^ שולבו במקומן הנכון.</div>
{"".join(rows)}
</main></body></html>'''

with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write(html_doc)

os.makedirs(ALIGN_DIR, exist_ok=True)
with open(os.path.join(ALIGN_DIR, "page_001.tsv"), "w", encoding="utf-8") as f:
    for fname, label, typed, note in ALIGN:
        if label:
            f.write(f"{fname}\t{label}\n")

print(f"match={n_match} diff={n_diff} skip={n_skip}")
print(f"report: {OUT_HTML}")
