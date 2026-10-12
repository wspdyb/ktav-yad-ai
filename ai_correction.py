"""Google AI Studio correction requests and locally encrypted API-key storage."""
import base64
import ctypes
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from ctypes import POINTER, Structure, byref, c_ubyte, c_void_p, c_wchar_p, cast, create_string_buffer, string_at
from ctypes import wintypes

from paths import DATA_DIR

# Default only for newly added keys and legacy key records without a saved model.
# AI requests use each key's saved model selection.
DEFAULT_MODEL = "gemini-2.5-flash"
BATCH_SIZE = 8
ALLOWED_BATCH_SIZES = (1, 2, 4, 8)
REQUEST_TIMEOUT = 90
CONNECTION_CHECK_TIMEOUT = 15
MODEL_LIST_PAGE_SIZE = 1000
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_lock = threading.RLock()
_next_key = 0


class AIStudioError(RuntimeError):
    pass


class _DataBlob(Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(c_ubyte))]


def _keys_path():
    return os.path.join(DATA_DIR, "ai_studio_keys.json")


def _crypt(data, protect):
    if os.name != "nt":
        raise AIStudioError("שמירת מפתחות API מוגנת זמינה כרגע ב-Windows בלבד")
    source = create_string_buffer(data)
    source_blob = _DataBlob(len(data), cast(source, POINTER(c_ubyte)))
    result_blob = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if protect:
        function = crypt32.CryptProtectData
        function.argtypes = [
            POINTER(_DataBlob), c_wchar_p, POINTER(_DataBlob), c_void_p,
            c_void_p, wintypes.DWORD, POINTER(_DataBlob)]
        args = (byref(source_blob), "KtavYadAI Google AI Studio key",
                None, None, None, 1, byref(result_blob))
    else:
        function = crypt32.CryptUnprotectData
        function.argtypes = [
            POINTER(_DataBlob), c_void_p, POINTER(_DataBlob), c_void_p,
            c_void_p, wintypes.DWORD, POINTER(_DataBlob)]
        args = (byref(source_blob), None, None, None, None, 1,
                byref(result_blob))
    function.restype = wintypes.BOOL
    if not function(*args):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return string_at(result_blob.pbData, result_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = [c_void_p]
        kernel32.LocalFree.restype = c_void_p
        kernel32.LocalFree(cast(result_blob.pbData, c_void_p))


def _read_keys():
    try:
        with open(_keys_path(), encoding="utf-8") as f:
            store = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise AIStudioError(f"לא ניתן לקרוא את קובץ מפתחות AI Studio: {exc}") from exc
    if not isinstance(store, dict) or not isinstance(store.get("keys"), list):
        raise AIStudioError("קובץ מפתחות AI Studio פגום; יש לבדוק את תיקיית data")
    for item in store["keys"]:
        if (not isinstance(item, dict)
                or not all(isinstance(item.get(field), str)
                           for field in ("id", "name", "encrypted"))
                or ("model" in item and not isinstance(item["model"], str))):
            raise AIStudioError("רשומת מפתח AI Studio פגומה; יש לבדוק את תיקיית data")
        item.setdefault("model", DEFAULT_MODEL)
    return store["keys"]


def _write_keys(keys):
    path = _keys_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump({"keys": keys}, f, ensure_ascii=False, indent=1)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def list_keys():
    with _lock:
        return [{"id": item["id"], "name": item["name"],
                 "model": item["model"]}
                for item in _read_keys()]


def add_key(name, api_key):
    name = (name or "").strip()
    api_key = (api_key or "").strip()
    if not name or len(name) > 60:
        raise AIStudioError("יש לתת למפתח שם באורך 1–60 תווים")
    if not api_key or len(api_key) > 1024:
        raise AIStudioError("מפתח API חסר או אינו תקין")
    with _lock:
        keys = _read_keys()
        if any(item["name"].casefold() == name.casefold() for item in keys):
            raise AIStudioError("כבר קיים מפתח בשם הזה")
        encrypted = base64.b64encode(_crypt(api_key.encode("utf-8"), True)).decode("ascii")
        keys.append({"id": uuid.uuid4().hex, "name": name,
                     "encrypted": encrypted, "model": DEFAULT_MODEL})
        _write_keys(keys)
        return [{"id": item["id"], "name": item["name"],
                 "model": item["model"]} for item in keys]


def remove_key(key_id):
    with _lock:
        keys = _read_keys()
        updated = [item for item in keys if item.get("id") != key_id]
        if len(updated) == len(keys):
            raise AIStudioError("מפתח ה-API לא נמצא")
        _write_keys(updated)
        return [{"id": item["id"], "name": item["name"],
                 "model": item["model"]} for item in updated]


def set_key_model(key_id, model):
    model = (model or "").strip()
    if not MODEL_NAME_RE.fullmatch(model):
        raise AIStudioError("שם מודל אינו תקין")
    with _lock:
        keys = _read_keys()
        item = next((key for key in keys if key["id"] == key_id), None)
        if item is None:
            raise AIStudioError("מפתח ה-API לא נמצא")
        item["model"] = model
        _write_keys(keys)
        return {"id": item["id"], "name": item["name"], "model": model}


def _decrypt_key(item):
    try:
        return _crypt(base64.b64decode(item["encrypted"]), False).decode("utf-8")
    except (ValueError, OSError) as exc:
        raise AIStudioError(
            f"לא ניתן לפענח את מפתח '{item['name']}'. "
            "המפתח מוגן לחשבון Windows שבו נשמר.") from exc


def _error_payload(exc):
    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
    except (ValueError, OSError):
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    message = error.get("message", "שגיאה לא מפורטת מהשירות")
    state = str(error.get("status", "")).upper()
    reasons = []
    for detail in error.get("details", []):
        if isinstance(detail, dict):
            reasons.extend(str(detail.get(field, ""))
                           for field in ("reason", "type"))
    reason = " ".join(reasons).upper()
    text = f"{state} {reason} {message}".upper()
    if exc.code == 429 or "RESOURCE_EXHAUSTED" in text or "QUOTA" in text:
        category = "quota"
    elif exc.code == 404:
        category = "model_unavailable"
    elif (exc.code in (400, 401, 403)
          and any(term in text for term in (
              "API_KEY_INVALID", "API KEY NOT VALID", "PERMISSION_DENIED",
              "API_KEY_SERVICE_BLOCKED", "SERVICE_DISABLED"))):
        category = "rejected"
    else:
        category = "service_error"
    return category, _translate_google_error(message, exc.code, text)


def _list_models(api_key):
    models = []
    page_token = None
    seen_tokens = set()
    while True:
        query = {"pageSize": MODEL_LIST_PAGE_SIZE}
        if page_token:
            query["pageToken"] = page_token
        url = ("https://generativelanguage.googleapis.com/v1beta/models?"
               + urllib.parse.urlencode(query))
        request = urllib.request.Request(
            url, headers={"x-goog-api-key": api_key}, method="GET")
        try:
            with urllib.request.urlopen(
                    request, timeout=CONNECTION_CHECK_TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            category, message = _error_payload(exc)
            if category == "quota":
                raise _RotateKey(f"מכסת השימוש במפתח הסתיימה ({message})") from exc
            if category == "rejected":
                raise _RotateKey(f"מפתח API נדחה על ידי Google ({message})") from exc
            raise AIStudioError(
                f"Google AI Studio לא הצליח להחזיר רשימת מודלים "
                f"({exc.code}): {message}") from exc
        except urllib.error.URLError as exc:
            raise AIStudioError(
                f"לא ניתן להתחבר ל-Google AI Studio: {exc.reason}") from exc
        except (OSError, TimeoutError, ValueError, UnicodeDecodeError) as exc:
            raise AIStudioError(
                f"תשובה לא תקינה בעת טעינת מודלים: {exc}") from exc
        if not isinstance(result, dict) or not isinstance(
                result.get("models", []), list):
            raise AIStudioError("Google החזיר רשימת מודלים בפורמט לא צפוי")
        for item in result.get("models", []):
            if not isinstance(item, dict):
                continue
            full_name = item.get("name")
            methods = item.get("supportedGenerationMethods", [])
            if (not isinstance(full_name, str)
                    or not full_name.startswith("models/")
                    or not isinstance(methods, list)
                    or "generateContent" not in methods):
                continue
            model_id = full_name[len("models/"):]
            if not MODEL_NAME_RE.fullmatch(model_id):
                continue
            models.append({
                "id": model_id,
                "display_name": item.get("displayName") or model_id,
                "description": item.get("description") or "",
                "input_token_limit": item.get("inputTokenLimit"),
                "output_token_limit": item.get("outputTokenLimit"),
            })
        next_token = result.get("nextPageToken")
        if not next_token:
            break
        if not isinstance(next_token, str) or next_token in seen_tokens:
            raise AIStudioError("Google החזיר עימוד מודלים לא תקין")
        seen_tokens.add(next_token)
        page_token = next_token
    return sorted(models, key=lambda item: item["id"].casefold())


def list_available_models(key_id):
    with _lock:
        item = next((key for key in _read_keys() if key["id"] == key_id), None)
    if item is None:
        raise AIStudioError("מפתח ה-API לא נמצא")
    return {
        "id": item["id"],
        "name": item["name"],
        "selected_model": item["model"],
        "models": _list_models(_decrypt_key(item)),
    }


def _probe_key(key_id, name, api_key, model):
    started = time.perf_counter()
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}",
        headers={"x-goog-api-key": api_key},
        method="GET")
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with urllib.request.urlopen(
                request, timeout=CONNECTION_CHECK_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        category, message = _error_payload(exc)
        status = category
        detail = message
    except urllib.error.URLError as exc:
        status = "unreachable"
        detail = f"לא ניתן להתחבר ל-Google: {exc.reason}"
    except (OSError, TimeoutError) as exc:
        status = "unreachable"
        detail = f"שגיאת תקשורת: {exc}"
    except (ValueError, UnicodeDecodeError):
        status = "service_error"
        detail = "Google החזיר תשובה שאינה JSON תקין."
    else:
        supported = (result.get("supportedGenerationMethods", [])
                     if isinstance(result, dict) else [])
        if (isinstance(result, dict)
                and result.get("name") == f"models/{model}"
                and isinstance(supported, list)
                and "generateContent" in supported):
            status = "connected"
            detail = f"המפתח מורשה למודל {model}; מכסת יצירת התוכן לא נבדקה."
        else:
            status = "service_error"
            detail = "Google החזיר פרטי מודל בפורמט לא צפוי."
    return {
        "id": key_id,
        "name": name,
        "model": model,
        "status": status,
        "detail": detail,
        "checked_at": checked_at,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def check_key(key_id):
    with _lock:
        item = next((key for key in _read_keys() if key["id"] == key_id), None)
    if item is None:
        raise AIStudioError("מפתח ה-API לא נמצא")
    return _probe_key(item["id"], item["name"], _decrypt_key(item),
                      item["model"])


def check_all_keys():
    with _lock:
        keys = list(_read_keys())
    return [_probe_key(item["id"], item["name"], _decrypt_key(item),
                       item["model"])
            for item in keys]


def _api_error_message(payload, status):
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    message = error.get("message", "שגיאה לא מפורטת מהשירות")
    reasons = []
    for detail in error.get("details", []):
        if isinstance(detail, dict):
            reasons.extend(str(detail.get(field, "")) for field in ("reason", "type"))
    reason = " ".join(reasons).upper()
    state = str(error.get("status", "")).upper()
    error_text = f"{state} {reason} {message}".upper()
    if (status == 429 or "RESOURCE_EXHAUSTED" in error_text
            or "QUOTA" in error_text or "RATE LIMIT" in error_text):
        raise _RotateKey(f"מכסת השימוש במפתח הסתיימה ({message})")
    if (status == 401 or "API_KEY_INVALID" in reason
            or "API_KEY_INVALID" in state or "API KEY NOT VALID" in error_text
            or "PERMISSION_DENIED" in error_text
            or "API_KEY_SERVICE_BLOCKED" in error_text
            or "SERVICE_DISABLED" in error_text):
        raise _RotateKey("מפתח API נדחה על ידי Google")
    if status == 404 or "MODEL" in error_text and (
            "NOT_FOUND" in error_text or "NOT SUPPORTED" in error_text):
        raise _RotateKey(
            "המודל שנבחר אינו זמין למפתח הזה; יש לרענן את רשימת המודלים")
    translated = _translate_google_error(message, status, error_text)
    raise AIStudioError(f"Google AI Studio: {translated}")


class _RotateKey(AIStudioError):
    pass


def _translate_google_error(message, status, error_text=""):
    normalized = f"{status} {error_text} {message}".casefold()
    if (status == 503 or "high demand" in normalized
            or "temporarily unavailable" in normalized
            or "service unavailable" in normalized):
        return (
            "שירות Google AI Studio עמוס כרגע (שגיאה 503). "
            "זו בדרך כלל תקלה זמנית, ולא בהכרח בעיה במפתח או בזמינות המודל. "
            "נסה שוב בעוד כמה דקות.")
    return message


def _request_gemini(api_key, lines, model=DEFAULT_MODEL):
    parts = [{
        "text": (
            "תקן תמלול OCR בעברית על פי התמונות המצורפות. לכל תמונה מצורפים "
            "מספר שורה והטקסט שזוהה כרגע. החזר את הטקסט המדויק שרואים בתמונה; "
            "אל תשלים תוכן חסר ואל תנחש מילים שאינן קריאות. שמור על סדר, "
            "מספרים, סימני פיסוק, מקפים, סוגריים, קווים תחתונים ושדות ריקים. "
            "אם התמלול הנוכחי נכון או שהתמונה אינה מאפשרת תיקון בטוח, החזר "
            "אותו ללא שינוי. החזר JSON בלבד במבנה "
            '{"corrections":[{"index":0,"text":"..."}]}.'
        )
    }]
    for index, item in enumerate(lines):
        parts.append({"text": f"שורה {index}; תמלול נוכחי: {item['text']}"})
        parts.append({"inline_data": {
            "mime_type": "image/png",
            "data": item["img"],
        }})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "corrections": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "index": {"type": "INTEGER"},
                                "text": {"type": "STRING"},
                            },
                            "required": ["index", "text"],
                        },
                    },
                },
                "required": ["corrections"],
            },
        },
    }
    request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent",
        data=request_data,
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": api_key},
        method="POST")
    try:
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8"))
        elapsed = time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
        except (ValueError, OSError):
            body = {}
        _api_error_message(body, exc.code)
    except urllib.error.URLError as exc:
        raise AIStudioError(f"לא ניתן להתחבר ל-Google AI Studio: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise AIStudioError("תשובת Google AI Studio אינה בפורמט הצפוי")
    try:
        text = "".join(part["text"] for part in result["candidates"][0]["content"]["parts"]
                       if "text" in part)
        decoded = json.loads(text)
        corrections = decoded["corrections"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AIStudioError("תשובת Google AI Studio אינה בפורמט הצפוי") from exc
    if not isinstance(corrections, list):
        raise AIStudioError("תשובת Google AI Studio אינה כוללת רשימת תיקונים")
    parsed = {}
    for item in corrections:
        if not isinstance(item, dict):
            raise AIStudioError("Google AI Studio החזיר תיקון לא תקין")
        index, text = item.get("index"), item.get("text")
        if (not isinstance(index, int) or isinstance(index, bool)
                or index < 0 or index >= len(lines)
                or not isinstance(text, str) or not text.strip()
                or index in parsed):
            raise AIStudioError("Google AI Studio החזיר תיקון לא תקין")
        parsed[index] = text.strip()
    usage = result.get("usageMetadata", {})
    if not isinstance(usage, dict):
        usage = {}
    return parsed, {
        "request_bytes": len(request_data),
        "prompt_tokens": usage.get("promptTokenCount"),
        "output_tokens": usage.get("candidatesTokenCount"),
        "thoughts_tokens": usage.get("thoughtsTokenCount"),
        "total_tokens": usage.get("totalTokenCount"),
        "elapsed_seconds": round(elapsed, 3),
    }


def _correct_batch(lines):
    global _next_key
    with _lock:
        keys = list(_read_keys())
        if not keys:
            raise AIStudioError("יש להוסיף מפתח Google AI Studio בהגדרות AI")
        start = _next_key % len(keys)
        _next_key = (start + 1) % len(keys)
    failures = []
    for offset in range(len(keys)):
        item = keys[(start + offset) % len(keys)]
        try:
            key = _decrypt_key(item)
            model = item["model"]
            corrections, usage = _request_gemini(key, lines, model)
            return item["name"], model, corrections, usage
        except _RotateKey as exc:
            failures.append(f"{item['name']}: {exc}")
    if failures and all("המודל שנבחר אינו זמין" in failure
                        for failure in failures):
        raise AIStudioError(
            "המודל שנבחר אינו זמין למפתחות שנבדקו. פתח את ניהול מפתחות "
            "AI, טען מחדש את רשימת המודלים עבור כל מפתח ובחר מודל זמין. "
            "פרטים: " + " | ".join(failures))
    raise AIStudioError(
        f"אף אחד מ-{len(failures)} מפתחות ה-API לא הצליח להשלים את הבקשה. "
        "הסיבות שדווחו: " + " | ".join(failures))


def correct_lines(lines, batch_size=BATCH_SIZE):
    if not isinstance(lines, list) or not lines:
        raise AIStudioError("אין שורות לשליחה לתיקון AI")
    if (not isinstance(batch_size, int) or isinstance(batch_size, bool)
            or batch_size not in ALLOWED_BATCH_SIZES):
        raise AIStudioError("גודל בקשה לא תקין; יש לבחור 1, 2, 4 או 8 שורות")
    corrections = []
    used_keys = []
    used_models = []
    batches = []
    warning = None
    started = time.perf_counter()
    for item in lines:
        if (not isinstance(item, dict)
                or not isinstance(item.get("text"), str)
                or not isinstance(item.get("img"), str)):
            raise AIStudioError("נתוני שורה חסרים או אינם תקינים")
        try:
            base64.b64decode(item["img"], validate=True)
        except (ValueError, TypeError) as exc:
            raise AIStudioError("תמונת שורה אינה תקינה") from exc
    for offset in range(0, len(lines), batch_size):
        batch = lines[offset:offset + batch_size]
        try:
            key_name, model, parsed, usage = _correct_batch(batch)
        except AIStudioError as exc:
            if not batches:
                raise
            warning = (
                f"עיבוד חלקי: הושלמו {offset} מתוך {len(lines)} שורות. "
                f"הבקשה הבאה נכשלה: {exc}")
            break
        if key_name not in used_keys:
            used_keys.append(key_name)
        if not any(used["key"] == key_name and used["model"] == model
                   for used in used_models):
            used_models.append({"key": key_name, "model": model})
        batches.append({
            "line_count": len(batch),
            "model": model,
            "image_bytes": sum(len(base64.b64decode(item["img"]))
                               for item in batch),
            **usage,
        })
        for local_index, corrected in parsed.items():
            original = batch[local_index]["text"]
            if corrected != original:
                corrections.append({"index": offset + local_index,
                                    "text": corrected})
    token_fields = ("request_bytes", "prompt_tokens", "output_tokens",
                    "thoughts_tokens", "total_tokens")
    totals = {
        field: (sum(batch[field] for batch in batches)
                if all(isinstance(batch.get(field), int) for batch in batches)
                else None)
        for field in token_fields
    }
    return {
        "corrections": corrections,
        "keys_used": used_keys,
        "models_used": used_models,
        "metrics": {
            "line_count": sum(batch["line_count"] for batch in batches),
            "requested_line_count": len(lines),
            "complete": warning is None,
            "batch_size": batch_size,
            "batch_count": len(batches),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "batches": batches,
            **totals,
        },
        "warning": warning,
    }
