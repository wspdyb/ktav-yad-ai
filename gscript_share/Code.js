/**
 * בוט שיתוף אוטומטי — כתב-יד AI.
 * כל מי ששולח מייל שבנושא שלו מופיעה המילה "מודל", מקבל אוטומטית:
 *   1. שיתוף (קורא) של תיקיית ההפצה בדרייב.
 *   2. מייל-מענה עם קישור להורדה.
 *
 * הגדרה חד-פעמית (המשתמש, לאחר שקלוד דחף את הקוד):
 *   פותחים את הסקריפט בעורך → מריצים את הפונקציה setupTrigger פעם אחת →
 *   מאשרים את ההרשאות (Gmail + Drive). מאותו רגע הבוט רץ אוטומטית כל 5 דקות.
 */

// מזהה תיקיית ההפצה בדרייב (מוזרק אוטומטית בעת הפריסה):
var FOLDER_ID = '__FOLDER_ID__';
var SUBJECT_KEYWORD = 'מודל';
var PROCESSED_LABEL = 'שיתוף-מודל-טופל';

function setupTrigger() {
  // מסיר טריגרים קודמים של אותה פונקציה, ומתקין אחד חדש כל 5 דקות
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'processModelRequests') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('processModelRequests')
    .timeBased().everyMinutes(5).create();
  // מריץ מיד פעם אחת כדי לטפל בבקשות שכבר בהמתנה ולאשר הרשאות
  processModelRequests();
  return 'הבוט הופעל — ירוץ כל 5 דקות.';
}

function getLabel_() {
  var lbl = GmailApp.getUserLabelByName(PROCESSED_LABEL);
  if (!lbl) { lbl = GmailApp.createLabel(PROCESSED_LABEL); }
  return lbl;
}

function processModelRequests() {
  var label = getLabel_();
  // מיילים נכנסים שבנושא יש "מודל", שעדיין לא טופלו
  var query = 'subject:(' + SUBJECT_KEYWORD + ') -label:' + PROCESSED_LABEL +
    ' newer_than:30d in:inbox';
  var threads = GmailApp.search(query, 0, 40);
  var folder = DriveApp.getFolderById(FOLDER_ID);
  var folderLink = 'https://drive.google.com/drive/folders/' + FOLDER_ID;

  for (var i = 0; i < threads.length; i++) {
    var thread = threads[i];
    var messages = thread.getMessages();
    var last = messages[messages.length - 1];
    var sender = last.getFrom(); // "שם <email@x.com>"
    var email = extractEmail_(sender);
    if (!email) { thread.addLabel(label); continue; }

    try {
      // שיתוף התיקייה עם השולח (קורא)
      folder.addViewer(email);
    } catch (e) {
      // כתובת לא-תקינה / כבר משותפת — ממשיכים לשלוח את הקישור בכל מקרה
    }

    var subject = 'הגישה שלך למודל כתב-יד AI ✓';
    var body =
      'שלום,\n\n' +
      'בהמשך לבקשתך — שיתפנו איתך את תיקיית ההפצה של תוכנת "כתב-יד AI".\n\n' +
      'קישור לתיקייה (כולל קובץ ההרצה, המדריך למשתמש והמסמכים):\n' +
      folderLink + '\n\n' +
      'בתיקייה יש:\n' +
      '  • KtavYadAI.zip — התוכנה (מחלצים ומריצים את KtavYadAI.exe)\n' +
      '  • USER_GUIDE — מדריך למשתמש\n' +
      '  • AI_HANDOFF / PROJECT_SUMMARY — מסמכים טכניים\n\n' +
      'התוכנה עובדת מקומית לגמרי — שום מידע לא יוצא מהמחשב.\n\n' +
      'בהצלחה!';
    GmailApp.sendEmail(email, subject, body);
    thread.addLabel(label);
    thread.markRead();
  }
}

function extractEmail_(from) {
  var m = from.match(/<([^>]+)>/);
  if (m) { return m[1].trim(); }
  var m2 = from.match(/[\w.+-]+@[\w.-]+\.\w+/);
  return m2 ? m2[0] : null;
}
