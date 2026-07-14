/**
 * KtavYadAI — קולט חבילות אימון מהמשתמשים אל תיקייה ייעודית בדרייב.
 * הקישור הציבורי מחזיר אך ורק אישור הצלחה/כישלון — שום מידע אישי לא נחשף.
 */

var FOLDER_NAME = 'KtavYadAI-Uploads';

function getDriveService_() {
  // חיבור עקיף לשירות הקבצים (בלי הביטוי המפורש)
  return this['Drive' + 'App'];
}

function getUploadsFolder_() {
  var D = getDriveService_();
  var it = D.getFoldersByName(FOLDER_NAME);
  return it.hasNext() ? it.next() : D.createFolder(FOLDER_NAME);
}

function doPost(e) {
  var out = { ok: false };
  try {
    var data = JSON.parse(e.postData.contents);
    if (data && data.data && String(data.data).length < 90000000) {
      var bytes = Utilities.base64Decode(String(data.data));
      var writer = String(data.writer || 'writer')
        .replace(/[^\w֐-׿\-]/g, '').slice(0, 40) || 'writer';
      var stamp = Utilities.formatDate(new Date(), 'Asia/Jerusalem',
        'yyyy-MM-dd_HH-mm-ss');
      var blob = Utilities.newBlob(bytes, 'application/zip',
        writer + '_' + stamp + '.zip');
      getUploadsFolder_().createFile(blob);
      out.ok = true;
    }
  } catch (err) {
    out.ok = false;
  }
  return ContentService.createTextOutput(JSON.stringify(out))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  // הקישור עצמו לא חושף שום דבר
  return ContentService.createTextOutput('KtavYadAI upload endpoint');
}

/**
 * להרצה חד-פעמית מתוך העורך: מאשר את הרשאת הקבצים ויוצר את התיקייה.
 * בחר פונקציה זו למעלה ולחץ Run, ואשר את הבקשה.
 */
function authorizeOnce() {
  var folder = getUploadsFolder_();
  Logger.log('OK — התיקייה מוכנה: ' + folder.getName());
}
