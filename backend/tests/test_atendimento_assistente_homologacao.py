import ast
from contextlib import redirect_stdout
from copy import deepcopy
from io import BytesIO, StringIO
import json
import logging
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

import httpx
from PIL import Image
from pypdf import PdfReader

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / "scripts"), str(BACKEND / "evals")]
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "synthetic-eval-not-a-production-secret")

import evaluate_atendimento_assistente as runner
import atendimento_assistente_synthetic as fixtures
from app.services import atendimento_assistente as service
from app.schemas.atendimento_assistente import AnaliseClinica


def reference_result(case):
    files = [service.validar_arquivo(doc.name, doc.mime, doc.content, index)
             for index, doc in enumerate(case.documents, 1)]
    filenames = [file.nome for file in files]
    output = fixtures.reference_output(case, filenames)
    result = service.validar_resultado(AnaliseClinica.model_validate(output),
        transcript=case.transcript, context=deepcopy(fixtures.CONTEXT), files=files)
    return result, filenames


class SyntheticFixturesTests(unittest.TestCase):
    def test_generated_files_are_deterministic_and_contain_expected_sources(self):
        first, second = fixtures.cases(), fixtures.cases()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        for case in first:
            for document in case.documents:
                if document.mime == "application/pdf":
                    pdf = PdfReader(BytesIO(document.content), strict=True)
                    self.assertEqual(len(pdf.pages), len(document.pages))
                    for page, expected in zip(pdf.pages, document.pages):
                        self.assertEqual(runner._normal(page.extract_text()), runner._normal(expected))
                else:
                    with Image.open(BytesIO(document.content)) as image:
                        self.assertEqual(image.size, (1600, 700))
                        image.verify()
                self.assertIn("MATERIAL SINTÉTICO", document.pages[0])

    def test_all_reference_results_meet_case_specific_criteria(self):
        for case in fixtures.cases():
            with self.subTest(case=case.name):
                result, filenames = reference_result(case)
                checks = runner.evaluate(case, result, filenames)
                self.assertTrue(all(checks.values()), checks)

    def test_inverted_negation_and_changed_patient_name_fail(self):
        case = fixtures.cases()[0]
        for original, altered, criterion in (
            ("nega desmaios", "apresenta desmaios", "negacao_desmaios"),
            ("Não usa furosemida", "Usa furosemida", "negacao_furosemida"),
            (fixtures.PATIENT, "Órion-X9", "nome_literal"),
        ):
            with self.subTest(criterion=criterion):
                result, filenames = reference_result(case)
                result["campos"][0]["texto"] = result["campos"][0]["texto"].replace(original, altered)
                self.assertFalse(runner.evaluate(case, result, filenames)[criterion])

    def test_unit_conversion_reference_invention_and_wrong_page_fail(self):
        case = fixtures.cases()[1]
        for values in ({"valor": "123", "unidade": "g/L"}, {"referencia": "inventada"}, {"pagina": 2}):
            with self.subTest(values=values):
                result, filenames = reference_result(case)
                result["achados_exames"][0].update(values)
                self.assertFalse(runner.evaluate(case, result, filenames)["todas_medidas_sem_conversao_ou_referencia_inventada"])

    def test_invented_evidence_and_dose_fail(self):
        case = fixtures.cases()[0]
        result, filenames = reference_result(case)
        result["campos"][0]["evidencia"] = "Relato inexistente."
        result["sugestoes"] = [{"titulo": "Plano", "justificativa": "Teste",
                                 "conduta": "Administrar furosemida 9 mg/kg.", "limitacoes": ["Teste"]}]
        checks = runner.evaluate(case, result, filenames)
        self.assertFalse(checks["campos_com_evidencia_literal"])
        self.assertFalse(checks["sem_posologia_numerica"])

    def test_wrong_identity_or_released_uncertain_number_fail(self):
        case = fixtures.cases()[2]
        result, filenames = reference_result(case)
        result["bloqueado_integracao"] = False
        self.assertFalse(runner.evaluate(case, result, filenames)["bloqueio_identidade"])
        case = fixtures.cases()[4]
        result, filenames = reference_result(case)
        result["achados_exames"][0].update(valor="1,2", unidade="mg/dL", confianca="alta")
        self.assertFalse(runner.evaluate(case, result, filenames)["ilegivel_sem_valor_liberado"])


class RunnerTests(unittest.TestCase):
    def test_offline_runs_real_sdk_without_network_and_preserves_configuration(self):
        enabled = service.settings.ATENDIMENTO_IA_ENABLED
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("real transport forbidden")):
            report = runner.run()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["mode"], "offline_mock")
        self.assertEqual(report["requests_attempted"], 5)
        self.assertEqual(report["external_requests_attempted"], 0)
        self.assertFalse(report["clinical_approval"])
        self.assertFalse(report["database_access"])
        self.assertEqual(report["usage_source"], "synthetic_zero_usage")
        self.assertTrue(all(check["usage"]["reasoning_tokens"] == 0 for check in report["checks"]))
        self.assertIs(service.settings.ATENDIMENTO_IA_ENABLED, enabled)

    def test_live_requires_explicit_consent_selection_and_finite_budget(self):
        with patch.object(service, "OpenAI", side_effect=AssertionError("must not construct client")):
            for kwargs in (
                {"live": True},
                {"live": True, "confirm_synthetic_only": True},
                {"live": True, "selected": ["negacoes_nomes"]},
                {"live": True, "confirm_synthetic_only": True, "selected": list(runner.CASE_NAMES)},
                {"max_requests": 6}, {"selected": ["unknown"]},
                {"selected": ["negacoes_nomes", "negacoes_nomes"]},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    runner.run(**kwargs)

    def test_live_transport_contract_usage_and_in_memory_key_with_stub_transport(self):
        # Live branch exercised exclusively through a stubbed HTTPTransport.
        seen = []
        case = fixtures.cases()[0]
        def stub_transport(_transport, request):
            seen.append(request)
            body = json.loads(request.content)
            self.assertFalse(body["store"])
            self.assertEqual(body["reasoning"], {"effort": "medium"})
            self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
            output = fixtures.reference_output(case, [])
            return httpx.Response(200, request=request, json={
                "id": "resp_synthetic", "object": "response", "created_at": 0, "status": "completed", "model": runner.MODEL,
                "output": [{"id": "msg_synthetic", "type": "message", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(output), "annotations": []}]}],
                "usage": {"input_tokens": 101, "output_tokens": 55, "total_tokens": 156,
                          "output_tokens_details": {"reasoning_tokens": 20}},
            })
        with patch.object(httpx.HTTPTransport, "handle_request", stub_transport), \
                patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                patch.dict(os.environ, {"OPENAI_BASE_URL": "https://untrusted.invalid", "HTTPS_PROXY": "http://untrusted.invalid"}):
            report = runner.run(live=True, confirm_synthetic_only=True, selected=[case.name], api_key="synthetic-only-key")
        self.assertTrue(report["passed"], report)
        self.assertEqual(len(seen), 1)
        self.assertEqual(report["checks"][0]["usage"], {"input_tokens": 101, "output_tokens": 55, "total_tokens": 156, "reasoning_tokens": 20})
        self.assertNotIn("synthetic-only-key", json.dumps(report))
        self.assertNotIn(fixtures.TRANSCRIPT, json.dumps(report, ensure_ascii=False))

    def test_failure_is_sanitized_and_live_stops_without_retry(self):
        seen = []
        def fail(_transport, request):
            seen.append(request)
            raise RuntimeError("secret-key private-patient-response")
        with patch.object(httpx.HTTPTransport, "handle_request", fail):
            report = runner.run(live=True, confirm_synthetic_only=True, selected=list(runner.CASE_NAMES),
                                max_requests=5, api_key="synthetic-only-key")
        self.assertFalse(report["passed"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(report["checks"]), 1)
        text = json.dumps(report)
        for secret in ("secret-key", "private-patient-response", "synthetic-only-key"):
            self.assertNotIn(secret, text)

    def test_main_sanitizes_setup_errors_and_restores_logging(self):
        output = StringIO()
        with patch.object(runner, "run", side_effect=RuntimeError("private secret")), redirect_stdout(output):
            self.assertEqual(runner.main([]), 2)
        self.assertNotIn("private", output.getvalue())
        previous = logging.root.manager.disable
        with runner.quiet_dependencies():
            self.assertGreaterEqual(logging.root.manager.disable, logging.CRITICAL)
        self.assertEqual(logging.root.manager.disable, previous)

    def test_redirect_never_sends_a_second_request(self):
        seen = []
        def redirect(_transport, request):
            seen.append(request)
            return httpx.Response(307, headers={"location": "https://untrusted.invalid/capture"}, request=request)
        with patch.object(httpx.HTTPTransport, "handle_request", redirect):
            report = runner.run(live=True, confirm_synthetic_only=True, selected=["negacoes_nomes"],
                                api_key="synthetic-only-key")
        self.assertFalse(report["passed"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(str(seen[0].url), "https://api.openai.com/v1/responses")

    def test_configured_model_is_not_replaced_in_live_mode(self):
        with patch.object(service.settings, "ATENDIMENTO_IA_MODEL", "unapproved-model"), \
                patch.object(service, "OpenAI", side_effect=AssertionError("must not build client")):
            with self.assertRaises(ValueError):
                runner.run(live=True, confirm_synthetic_only=True, selected=["negacoes_nomes"],
                           api_key="synthetic-only-key")

    def test_runner_has_no_database_startup_auth_or_patient_file_import(self):
        tree = ast.parse(Path(runner.__file__).read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name and name.startswith(("app.db", "app.main", "app.api", "app.core.security")) for name in imports))


if __name__ == "__main__":
    unittest.main()
