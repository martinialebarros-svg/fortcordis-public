import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI
from openai.lib._parsing._responses import parse_response as sdk_parse_response

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.atendimento_assistente import AnaliseClinica
from app.services.atendimento_ia_response import StructuredResponseError, parse_structured_response

PRIVATE = "PRIVATE_PATIENT_AND_CREDENTIAL_SENTINEL"
VALID = {"campos": [], "fontes": [], "achados_exames": [], "sugestoes": [], "pendencias": [], "avisos": []}


def response_body(text=None, *, status="completed", reason=None):
    return {
        "id": "resp_synthetic", "object": "response", "created_at": 0,
        "model": "synthetic", "status": status,
        "incomplete_details": {"reason": reason} if reason else None,
        "output": [{"type": "message", "id": "msg_synthetic", "role": "assistant", "status": status,
                    "content": [{"type": "output_text", "text": json.dumps(VALID) if text is None else text,
                                 "annotations": []}]}],
        "parallel_tool_calls": False, "tool_choice": "none", "tools": [],
        "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens": 16000, "output_tokens_details": {"reasoning_tokens": 15990}, "total_tokens": 16100},
    }


class StructuredResponseTests(unittest.TestCase):
    def setUp(self):
        self.body = response_body()
        self.requests = []

        def respond(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json=self.body)

        self.client = OpenAI(api_key="synthetic-not-a-real-key", max_retries=0,
                             http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        self.addCleanup(self.client.close)

    def call(self):
        return parse_structured_response(
            self.client.responses, model="synthetic", text_format=AnaliseClinica,
            input=[{"role": "user", "content": PRIVATE}], instructions="synthetic",
            reasoning={"effort": "max"}, max_output_tokens=16000, store=False,
            safety_identifier="synthetic-actor",
        )

    def assert_rejected(self, reason):
        with self.assertLogs("app.services.atendimento_ia_response", level="WARNING") as logs:
            with self.assertRaises(StructuredResponseError) as captured:
                self.call()
        self.assertEqual(captured.exception.reason, reason)
        self.assertNotIn(PRIVATE, str(captured.exception))
        self.assertNotIn(PRIVATE, "\n".join(logs.output))
        self.assertEqual(len(self.requests), 1)
        return "\n".join(logs.output)

    def test_completed_valid_uses_real_sdk_and_preserves_request_and_schema(self):
        result = self.call()
        self.assertIsInstance(result.output_parsed, AnaliseClinica)
        self.assertEqual(result.output_parsed.model_dump(), VALID)
        request = self.requests[0]
        self.assertEqual(request["max_output_tokens"], 16000)
        self.assertEqual(request["reasoning"], {"effort": "max"})
        self.assertFalse(request["store"])
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertFalse(request["text"]["format"]["schema"]["additionalProperties"])
        self.assertEqual(request["text"]["format"]["name"], "AnaliseClinica")
        self.assertEqual(request["input"][0]["content"], PRIVATE)
        self.assertEqual(self.client.max_retries, 0)
        self.assertEqual(len(self.requests), 1)

    def test_truncated_incomplete_detected_before_sdk_json_parser(self):
        self.body = response_body('{"avisos":["' + PRIVATE, status="incomplete", reason="max_output_tokens")
        with patch("openai.resources.responses.responses.parse_response", wraps=sdk_parse_response) as parser:
            logs = self.assert_rejected("output_limit")
        parser.assert_not_called()
        self.assertIn("output_tokens=16000", logs)
        self.assertIn("reasoning_tokens=15990", logs)

    def test_incomplete_valid_json_is_still_rejected(self):
        self.body = response_body(status="incomplete", reason="max_output_tokens")
        self.assert_rejected("output_limit")

    def test_completed_invalid_json_remains_invalid_format(self):
        self.body = response_body('{"avisos":["' + PRIVATE)
        logs = self.assert_rejected("invalid_format")
        self.assertIn("json_invalid", logs)

    def test_completed_schema_invalid_redacts_values_and_unknown_field_names(self):
        invalid = copy.deepcopy(VALID)
        invalid[PRIVATE] = PRIVATE
        invalid["fontes"] = [{"arquivo": PRIVATE, "paciente_nome": PRIVATE}]
        self.body = response_body(json.dumps(invalid))
        logs = self.assert_rejected("invalid_format")
        self.assertIn("missing", logs)
        self.assertIn("fontes", logs)

    def test_unknown_property_name_itself_never_appears_in_diagnostics(self):
        invalid = {**VALID, PRIVATE: PRIVATE}
        self.body = response_body(json.dumps(invalid))
        logs = self.assert_rejected("invalid_format")
        self.assertIn("extra_forbidden", logs)
        self.assertIn("'?'", logs)

    def test_valid_json_over_schema_limits_is_rejected_without_truncation(self):
        excessive_items = {**VALID, "avisos": [PRIVATE] * 41}
        excessive_text = {**VALID, "campos": [{
            "campo": "anamnese", "texto": PRIVATE * 400,
            "fonte": "transcricao", "evidencia": PRIVATE,
        }]}
        for payload, expected_type in ((excessive_items, "too_long"), (excessive_text, "string_too_long")):
            with self.subTest(validation_type=expected_type):
                self.requests.clear()
                self.body = response_body(json.dumps(payload))
                logs = self.assert_rejected("invalid_format")
                self.assertIn(expected_type, logs)
                self.assertEqual(json.loads(self.body["output"][0]["content"][0]["text"]), payload)

    def test_refusal_detected_without_parsing_or_logging_its_text(self):
        self.body["output"][0]["content"] = [{"type": "refusal", "refusal": PRIVATE}]
        with patch("openai.resources.responses.responses.parse_response", wraps=sdk_parse_response) as parser:
            self.assert_rejected("refusal")
        parser.assert_not_called()

    def test_content_filter_is_incomplete_without_exposing_provider_details(self):
        self.body = response_body(PRIVATE, status="incomplete", reason="content_filter")
        self.assert_rejected("incomplete")

    def test_untrusted_metadata_strings_are_redacted(self):
        self.body = response_body(PRIVATE, status=PRIVATE, reason=PRIVATE)
        self.body["usage"]["output_tokens"] = PRIVATE
        self.body["usage"]["output_tokens_details"]["reasoning_tokens"] = PRIVATE
        logs = self.assert_rejected("incomplete")
        self.assertIn("status=unknown", logs)

    def test_incomplete_message_under_completed_response_is_rejected(self):
        self.body["output"][0]["status"] = "incomplete"
        self.assert_rejected("incomplete")

    def test_no_structured_output_is_rejected(self):
        self.body["output"] = []
        self.assert_rejected("invalid_response")

    def test_malformed_output_envelope_is_rejected_without_exposing_content(self):
        for output in (None, PRIVATE, [PRIVATE], [{"type": "message", "status": "completed", "content": PRIVATE}]):
            with self.subTest(output_type=type(output).__name__):
                self.requests.clear()
                self.body["output"] = output
                self.assert_rejected("invalid_response")

    def test_transport_error_propagates_without_retry(self):
        requests = []

        def fail(request):
            requests.append(request)
            raise httpx.ReadTimeout("synthetic-timeout", request=request)

        from openai import APITimeoutError
        with OpenAI(api_key="synthetic", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(fail))) as client:
            with self.assertRaises(APITimeoutError):
                parse_structured_response(client.responses, model="synthetic", input="synthetic", text_format=AnaliseClinica)
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
