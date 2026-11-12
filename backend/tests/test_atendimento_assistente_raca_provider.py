"""Synthetic evidence for deferred breed review; no provider or patient data."""
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "breed-review-synthetic-only")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import atendimento_assistente as direct
from app.services import atendimento_assistente_lote_provider as provider
from app.services.atendimento_assistente_identidade import (
    AVISO_RACA_PENDENTE, impedimento_revisao_raca, revisao_raca_aplicavel,
)
from app.schemas.atendimento_assistente import AnaliseClinica
from tests.test_atendimento_assistente import CONTEXT, FILE, TRANSCRIPT, raw_output
from tests.test_atendimento_assistente_lote_provider import cached_exam, synthesis


REVIEW = {"decisao": "mesmo_paciente_raca_pendente", "usuario_id": 8,
          "registrado_em": "2026-11-09T20:00:00Z"}


class BreedReviewValidationTests(unittest.TestCase):
    def test_opaque_divergence_is_not_reclassified_without_explicit_review(self):
        raw = raw_output(True)
        raw["fontes"][0].update(identidade="divergente", motivo="Raça no laudo diferente; motivo original.")
        original = copy.deepcopy(raw)
        result = direct.validar_resultado(AnaliseClinica.model_validate(raw), transcript=TRANSCRIPT,
                                          context=CONTEXT, files=[FILE])
        self.assertTrue(result["bloqueado_integracao"])
        self.assertEqual(result["sugestoes"], [])
        self.assertEqual(result["fontes"][0]["motivo"], raw["fontes"][0]["motivo"])
        self.assertNotIn("revisao_raca", result["fontes"][0])
        self.assertEqual(raw, original)

    def test_vet_review_preserves_original_identity_and_requires_clinical_review(self):
        raw = raw_output(True)
        raw["fontes"][0].update(identidade="divergente", motivo="Raça pendente de conferência.")
        result = direct.validar_resultado(AnaliseClinica.model_validate(raw), transcript=TRANSCRIPT,
            context=CONTEXT, files=[FILE], revisoes_raca={FILE.nome: REVIEW})
        self.assertFalse(result["bloqueado_integracao"])
        self.assertTrue(result["revisao_obrigatoria"])
        self.assertTrue(result["raca_pendente_revisao"])
        self.assertEqual(result["fontes"][0]["identidade"], "divergente")
        self.assertEqual(result["fontes"][0]["revisao_raca"], REVIEW)
        self.assertIn(AVISO_RACA_PENDENTE, result["pendencias"])
        self.assertEqual(result["achados_exames"][0]["valor"], raw["achados_exames"][0]["valor"])

    def test_missing_or_different_name_species_cannot_use_breed_review(self):
        for field, value in [("paciente_nome", None), ("paciente_nome", "Outro paciente"),
                             ("especie", None), ("especie", "Felina")]:
            with self.subTest(field=field, value=value):
                raw = raw_output(True)
                source = raw["fontes"][0]
                source.update(identidade="divergente", motivo="Divergência a conferir.")
                source[field] = value
                self.assertIsNotNone(impedimento_revisao_raca(source, CONTEXT))
                self.assertFalse(revisao_raca_aplicavel(source, CONTEXT, REVIEW))
                result = direct.validar_resultado(AnaliseClinica.model_validate(raw), transcript=TRANSCRIPT,
                    context=CONTEXT, files=[FILE], revisoes_raca={FILE.nome: REVIEW})
                self.assertTrue(result["bloqueado_integracao"])
                self.assertNotIn("revisao_raca", result["fontes"][0])
                self.assertEqual(result["sugestoes"], [])

    def test_uncertain_findings_remain_without_numeric_values_after_confirmation(self):
        raw = raw_output(True)
        raw["fontes"][0]["identidade"] = "nao_confirmada"
        raw["achados_exames"][0]["confianca"] = "baixa"
        result = direct.validar_resultado(AnaliseClinica.model_validate(raw), transcript=TRANSCRIPT,
            context=CONTEXT, files=[FILE], revisoes_raca={FILE.nome: REVIEW})
        self.assertFalse(result["bloqueado_integracao"])
        for field in ("valor", "unidade", "referencia"):
            self.assertIsNone(result["achados_exames"][0][field])

    def test_long_original_reason_is_preserved_and_can_be_validated_again(self):
        raw = raw_output(True)
        raw["fontes"][0].update(paciente_nome="Outro paciente", motivo="x" * 2000)
        result = direct.validar_resultado(AnaliseClinica.model_validate(raw), transcript="",
                                          context=CONTEXT, files=[FILE])
        self.assertEqual(result["fontes"][0]["motivo"], "x" * 2000)
        AnaliseClinica.model_validate({key: result[key] for key in AnaliseClinica.model_fields})


class DeferredBreedSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.provider = Mock()
        self.provider.client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=synthesis())
        self.patches = [patch.object(provider, "require_enabled"),
                       patch.object(provider, "OpenAIAtendimentoProvider", return_value=self.provider),
                       patch.object(provider, "parse_structured_response",
                                    side_effect=lambda responses, **kwargs: responses.parse(**kwargs))]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_synthesis_only_uses_pending_breed_copy_and_preserves_cached_documents(self):
        exams = [cached_exam(1), cached_exam(2)]
        for exam in exams:
            exam["analise"]["fontes"][0].update(identidade="divergente", motivo="Raça no exame diverge do cadastro.")
        context = copy.deepcopy(CONTEXT)
        context["paciente"]["raca"] = "Raça cadastral não confirmada"
        originals = copy.deepcopy((exams, context))
        reviews = {exam["arquivo"]["nome"]: REVIEW for exam in exams}
        result = provider.sintetizar_lote(transcript=TRANSCRIPT, context=context,
                                          exames=exams, user_id=8, revisoes_raca=reviews)
        self.provider.analisar.assert_not_called()
        self.provider.client.responses.parse.assert_called_once()
        args = self.provider.client.responses.parse.call_args.kwargs
        sent = json.loads(args["input"][0]["content"][0]["text"])
        self.assertIsNone(sent["contexto_salvo"]["paciente"]["raca"])
        self.assertEqual(sent["contexto_salvo"]["paciente"]["raca_estado"], "pendente_revisao_veterinaria")
        self.assertEqual(len(sent["revisoes_veterinarias"]), 2)
        self.assertTrue(all(s["identidade"] == "divergente" for s in sent["exames"]["fontes"]))
        self.assertIn("não baseie conduta", args["instructions"])
        self.assertEqual((exams, context), originals)
        self.assertFalse(result["bloqueado_integracao"])
        self.assertTrue(result["raca_pendente_revisao"])
        self.assertIn(AVISO_RACA_PENDENTE, result["pendencias"])
        self.assertEqual(len(result["achados_exames"]), 2)

    def test_partial_confirmation_still_blocks_synthesis(self):
        exams = [cached_exam(1), cached_exam(2)]
        for exam in exams:
            exam["analise"]["fontes"][0]["identidade"] = "divergente"
        result = provider.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT,
            exames=exams, user_id=8, revisoes_raca={exams[0]["arquivo"]["nome"]: REVIEW})
        self.provider.client.responses.parse.assert_not_called()
        self.assertTrue(result["bloqueado_integracao"])
        self.assertIn("revisao_raca", result["fontes"][0])
        self.assertNotIn("revisao_raca", result["fontes"][1])

    def test_no_review_keeps_original_context_and_breed_unchanged(self):
        context = copy.deepcopy(CONTEXT)
        context["paciente"]["raca"] = "Raça cadastrada"
        provider.sintetizar_lote(transcript=TRANSCRIPT, context=context, exames=[cached_exam()], user_id=8)
        args = self.provider.client.responses.parse.call_args.kwargs
        sent = json.loads(args["input"][0]["content"][0]["text"])
        self.assertEqual(sent["contexto_salvo"], context)
        self.assertNotIn("revisoes_veterinarias", sent)


if __name__ == "__main__":
    unittest.main()
