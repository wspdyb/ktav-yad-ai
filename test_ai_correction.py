import base64
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import ai_correction


class AICorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.keys_file = os.path.join(self.temp.name, "keys.json")
        self.crypt_patch = patch(
            "ai_correction._crypt",
            side_effect=lambda data, protect: b"enc:" + data if protect
            else data[4:])
        self.path_patch = patch("ai_correction._keys_path",
                                return_value=self.keys_file)
        self.crypt_patch.start()
        self.path_patch.start()
        ai_correction._next_key = 0

    def tearDown(self):
        self.path_patch.stop()
        self.crypt_patch.stop()
        self.temp.cleanup()

    def test_api_keys_are_stored_encrypted_and_listed_without_secrets(self):
        keys = ai_correction.add_key("work", "secret-api-key")
        with open(self.keys_file, encoding="utf-8") as f:
            stored = json.load(f)["keys"][0]
        self.assertNotIn("secret-api-key", json.dumps(stored))
        self.assertEqual(keys, [{
            "id": stored["id"], "name": "work",
            "model": ai_correction.DEFAULT_MODEL,
        }])
        self.assertEqual(ai_correction.list_keys(), keys)
        self.assertEqual(ai_correction.remove_key(keys[0]["id"]), [])

    def test_duplicate_names_are_rejected(self):
        ai_correction.add_key("work", "first")
        with self.assertRaises(ai_correction.AIStudioError):
            ai_correction.add_key("WORK", "second")

    def test_model_selection_is_saved_without_exposing_the_key(self):
        keys = ai_correction.add_key("work", "secret")
        selected = ai_correction.set_key_model(
            keys[0]["id"], "gemini-2.5-flash-lite")
        self.assertEqual(selected["model"], "gemini-2.5-flash-lite")
        self.assertEqual(ai_correction.list_keys()[0]["model"],
                         "gemini-2.5-flash-lite")
        with open(self.keys_file, encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertNotIn("secret", json.dumps(persisted))
        with self.assertRaises(ai_correction.AIStudioError):
            ai_correction.set_key_model(keys[0]["id"], "../not-a-model")

    def test_model_list_returns_only_generate_content_models_and_paginates(self):
        ai_correction.add_key("work", "secret")

        class Response:
            def __init__(self, result):
                self.result = result

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.result).encode("utf-8")

        responses = [
            {
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "displayName": "Gemini Flash",
                        "description": "fast model",
                        "supportedGenerationMethods": ["generateContent"],
                        "inputTokenLimit": 100000,
                        "outputTokenLimit": 8000,
                    },
                    {
                        "name": "models/text-embedding",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ],
                "nextPageToken": "next page",
            },
            {
                "models": [{
                    "name": "models/gemini-2.5-flash-lite",
                    "supportedGenerationMethods": ["generateContent"],
                }],
            },
        ]
        captured = []

        def open_request(request, timeout):
            captured.append((request, timeout))
            return Response(responses.pop(0))

        key_id = ai_correction.list_keys()[0]["id"]
        with patch("ai_correction.urllib.request.urlopen",
                   side_effect=open_request):
            result = ai_correction.list_available_models(key_id)
        self.assertEqual(
            [model["id"] for model in result["models"]],
            ["gemini-2.5-flash", "gemini-2.5-flash-lite"])
        self.assertEqual(result["selected_model"], "gemini-2.5-flash")
        self.assertEqual(len(captured), 2)
        self.assertIn("pageToken=next+page", captured[1][0].full_url)
        self.assertEqual(captured[0][1],
                         ai_correction.CONNECTION_CHECK_TIMEOUT)

    def test_quota_exhaustion_rotates_to_the_next_key(self):
        ai_correction.add_key("first", "key-one")
        ai_correction.add_key("second", "key-two")
        second = next(key for key in ai_correction.list_keys()
                      if key["name"] == "second")
        ai_correction.set_key_model(second["id"], "gemini-2.5-flash-lite")
        calls = []

        def request(key, lines, model):
            calls.append((key, model))
            if key == "key-one":
                raise ai_correction._RotateKey("quota exhausted")
            return {0: "תמלול מתוקן"}, {
                "request_bytes": 256,
                "prompt_tokens": 120, "output_tokens": 4,
                "thoughts_tokens": 0, "total_tokens": 124,
                "elapsed_seconds": 0.2,
            }

        with patch("ai_correction._request_gemini", side_effect=request):
            result = ai_correction.correct_lines([{
                "img": base64.b64encode(b"png").decode("ascii"),
                "text": "תמלול מקורי",
            }])
        self.assertEqual(calls, [
            ("key-one", "gemini-2.5-flash"),
            ("key-two", "gemini-2.5-flash-lite"),
        ])
        self.assertEqual(result["keys_used"], ["second"])
        self.assertEqual(result["models_used"], [{
            "key": "second", "model": "gemini-2.5-flash-lite",
        }])
        self.assertEqual(result["corrections"],
                         [{"index": 0, "text": "תמלול מתוקן"}])

    def test_unavailable_models_report_refresh_action_instead_of_quota_failure(self):
        ai_correction.add_key("work", "key-one")

        with patch("ai_correction._request_gemini", side_effect=(
                ai_correction._RotateKey(
                    "המודל שנבחר אינו זמין למפתח הזה; יש לרענן את רשימת המודלים"))):
            with self.assertRaises(ai_correction.AIStudioError) as context:
                ai_correction.correct_lines([{
                    "img": base64.b64encode(b"png").decode("ascii"),
                    "text": "תמלול מקורי",
                }])

        message = str(context.exception)
        self.assertIn("טען מחדש את רשימת המודלים", message)
        self.assertIn("work", message)
        self.assertNotIn("מכסתם הסתיימה", message)

    def test_identical_response_is_not_a_suggestion(self):
        ai_correction.add_key("only", "secret")
        with patch("ai_correction._request_gemini", return_value=(
                {0: "same"}, {
                    "request_bytes": 128,
                    "prompt_tokens": 10, "output_tokens": 1,
                    "thoughts_tokens": 0, "total_tokens": 11,
                    "elapsed_seconds": 0.1,
                })):
            result = ai_correction.correct_lines([{
                "img": base64.b64encode(b"png").decode("ascii"),
                "text": "same",
            }])
        self.assertEqual(result["corrections"], [])

    def test_selected_lines_are_split_and_usage_is_aggregated(self):
        ai_correction.add_key("only", "secret")
        calls = []

        def request(key, lines, model):
            calls.append(len(lines))
            return {
                index: f"תיקון {len(calls)}-{index}"
                for index in range(len(lines))
            }, {
                "request_bytes": len(lines) * 100,
                "prompt_tokens": len(lines) * 10,
                "output_tokens": len(lines),
                "thoughts_tokens": 0,
                "total_tokens": len(lines) * 11,
                "elapsed_seconds": 0.25,
            }

        rows = [{
            "img": base64.b64encode(b"png").decode("ascii"),
            "text": f"מקור {index}",
        } for index in range(10)]
        with patch("ai_correction._request_gemini", side_effect=request):
            result = ai_correction.correct_lines(rows, batch_size=4)
        self.assertEqual(calls, [4, 4, 2])
        self.assertEqual(result["metrics"]["batch_count"], 3)
        self.assertEqual(result["metrics"]["prompt_tokens"], 100)
        self.assertEqual(result["metrics"]["total_tokens"], 110)
        self.assertEqual([item["index"] for item in result["corrections"]],
                         list(range(10)))

    def test_only_supported_batch_sizes_are_accepted(self):
        with self.assertRaises(ai_correction.AIStudioError):
            ai_correction.correct_lines([{
                "img": base64.b64encode(b"png").decode("ascii"),
                "text": "מקור",
            }], batch_size=3)

    def test_two_line_batch_size_is_supported(self):
        ai_correction.add_key("only", "secret")
        calls = []

        def request(key, lines, model):
            calls.append(len(lines))
            return {}, {
                "request_bytes": 100,
                "prompt_tokens": 20,
                "output_tokens": 0,
                "thoughts_tokens": 0,
                "total_tokens": 20,
                "elapsed_seconds": 0.1,
            }

        rows = [{
            "img": base64.b64encode(b"png").decode("ascii"),
            "text": f"מקור {index}",
        } for index in range(5)]
        with patch("ai_correction._request_gemini", side_effect=request):
            result = ai_correction.correct_lines(rows, batch_size=2)
        self.assertEqual(calls, [2, 2, 1])
        self.assertEqual(result["metrics"]["batch_count"], 3)
        self.assertTrue(result["metrics"]["complete"])

    def test_later_batch_failure_returns_completed_suggestions_and_warning(self):
        ai_correction.add_key("only", "secret")
        calls = []

        def request(key, lines, model):
            calls.append(len(lines))
            if len(calls) == 2:
                raise ai_correction.AIStudioError("מכסה הסתיימה")
            return {
                index: f"תיקון {index}" for index in range(len(lines))
            }, {
                "request_bytes": 400, "prompt_tokens": 100,
                "output_tokens": 10, "thoughts_tokens": 0,
                "total_tokens": 110, "elapsed_seconds": 0.2,
            }

        rows = [{
            "img": base64.b64encode(b"png").decode("ascii"),
            "text": f"מקור {index}",
        } for index in range(6)]
        with patch("ai_correction._request_gemini", side_effect=request):
            result = ai_correction.correct_lines(rows, batch_size=4)
        self.assertEqual(calls, [4, 2])
        self.assertFalse(result["metrics"]["complete"])
        self.assertEqual(result["metrics"]["line_count"], 4)
        self.assertEqual(result["metrics"]["requested_line_count"], 6)
        self.assertIn("עיבוד חלקי", result["warning"])
        self.assertEqual([item["index"] for item in result["corrections"]],
                         [0, 1, 2, 3])

    def test_quota_http_errors_trigger_key_rotation(self):
        with self.assertRaises(ai_correction._RotateKey):
            ai_correction._api_error_message(
                {"error": {"status": "RESOURCE_EXHAUSTED",
                           "message": "quota exceeded"}}, 429)

    def test_api_key_connection_check_does_not_generate_content(self):
        key = ai_correction.add_key("work", "secret-key")[0]
        ai_correction.set_key_model(key["id"], "gemini-2.5-flash-lite")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({
                    "name": "models/gemini-2.5-flash-lite",
                    "supportedGenerationMethods": ["generateContent"],
                }).encode("utf-8")

        captured = []

        def open_request(request, timeout):
            captured.append((request, timeout))
            return Response()

        with patch("ai_correction.urllib.request.urlopen",
                   side_effect=open_request):
            result = ai_correction.check_all_keys()[0]
        request, timeout = captured[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.endswith(
            "/models/gemini-2.5-flash-lite"))
        self.assertNotIn("secret-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "secret-key")
        self.assertEqual(timeout, ai_correction.CONNECTION_CHECK_TIMEOUT)
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["model"], "gemini-2.5-flash-lite")
        self.assertIn("מכסת יצירת התוכן לא נבדקה", result["detail"])

    def test_connection_check_reports_invalid_key_without_exposing_it(self):
        ai_correction.add_key("bad-key", "secret-key")
        error_body = json.dumps({"error": {
            "status": "PERMISSION_DENIED",
            "message": "API key not valid",
        }}).encode("utf-8")
        error = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash", 403, "Forbidden", {}, io.BytesIO(error_body))
        with patch("ai_correction.urllib.request.urlopen", side_effect=error):
            result = ai_correction.check_key(
                ai_correction.list_keys()[0]["id"])
        self.assertEqual(result["status"], "rejected")
        self.assertNotIn("secret-key", result["detail"])

    def test_connection_check_reports_network_failure(self):
        ai_correction.add_key("offline", "secret-key")
        with patch("ai_correction.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("offline")):
            result = ai_correction.check_all_keys()[0]
        self.assertEqual(result["status"], "unreachable")
        self.assertIn("לא ניתן להתחבר", result["detail"])

    def test_connection_check_reports_quota_status_if_service_returns_it(self):
        ai_correction.add_key("limited", "secret-key")
        error_body = json.dumps({"error": {
            "status": "RESOURCE_EXHAUSTED",
            "message": "quota exceeded",
        }}).encode("utf-8")
        error = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash", 429, "Too Many Requests", {},
            io.BytesIO(error_body))
        with patch("ai_correction.urllib.request.urlopen", side_effect=error):
            result = ai_correction.check_all_keys()[0]
        self.assertEqual(result["status"], "quota")

    def test_gemini_request_contains_image_and_ocr_without_key_in_url(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                result = {"candidates": [{"content": {"parts": [{
                    "text": '{"corrections":[{"index":0,"text":"מתוקן"}]}'
                }]}}], "usageMetadata": {
                    "promptTokenCount": 14,
                    "candidatesTokenCount": 2,
                    "thoughtsTokenCount": 0,
                    "totalTokenCount": 16,
                }}
                return json.dumps(result).encode("utf-8")

        captured = []

        def open_request(request, timeout):
            captured.append((request, timeout))
            return Response()

        image = base64.b64encode(b"image-data").decode("ascii")
        with patch("ai_correction.urllib.request.urlopen", side_effect=open_request):
            parsed, usage = ai_correction._request_gemini(
                "secret-key", [{"img": image, "text": "מקור"}],
                model="gemini-2.5-flash-lite")
        request, timeout = captured[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url.rsplit("/", 1)[-1],
                         "gemini-2.5-flash-lite:generateContent")
        self.assertNotIn("secret-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "secret-key")
        self.assertEqual(timeout, ai_correction.REQUEST_TIMEOUT)
        self.assertEqual(payload["contents"][0]["parts"][2]["inline_data"]["data"],
                         image)
        self.assertIn("מקור", payload["contents"][0]["parts"][1]["text"])
        self.assertEqual(parsed, {0: "מתוקן"})
        self.assertEqual(usage["prompt_tokens"], 14)
        self.assertEqual(usage["total_tokens"], 16)
        self.assertEqual(usage["request_bytes"], len(request.data))


if __name__ == "__main__":
    unittest.main()
