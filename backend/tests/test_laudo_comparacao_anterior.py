"""Disposable SQLite and real protected-route checks for longitudinal echoes."""

import copy
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "synthetic-echo-comparison-secret-1234567890")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import laudos
from app.core import security
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.db.database import get_db
from app.models.laudo import Laudo
from app.models.paciente import Paciente
from app.models.papel import Papel, usuario_papel
from app.models.papel_permissao import PapelPermissao
from app.models.user import User
from app.services.laudo_comparacao_service import (
    LaudoComparacaoNaoEncontrada,
    LaudoComparacaoPacienteAusente,
    comparar_laudo_anterior,
)
from app.utils.echo_unit_provenance import ambiguous_echo_length_keys


def description(measurements: dict[str, str], *, qualitative: str = "") -> str:
    return "## Medidas Ecocardiograficas\n" + "".join(
        f"- {key}: {value}\n" for key, value in measurements.items()
    ) + f"\n## Avaliacao Qualitativa\n{qualitative}"


class LaudoComparacaoAnteriorTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        for table in (Paciente.__table__, Laudo.__table__):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=True)
        self.db = self.sessions()
        self.db.add_all([
            Paciente(id=1, nome="MESMO NOME", tutor_id=7, especie="Canina", peso_kg=18.0),
            Paciente(id=2, nome="MESMO NOME", tutor_id=7, especie="Canina", peso_kg=18.0),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_report(self, report_id: int, day: str | None, **kwargs) -> Laudo:
        values = {
            "id": report_id,
            "paciente_id": 1,
            "veterinario_id": 7,
            "tipo": "ecocardiograma",
            "titulo": "TESTE SINTETICO",
            "status": "Finalizado",
            "data_exame": datetime.fromisoformat(day) if day else None,
            "descricao": description({"DIVEd": "30", "VE_tecnica_relatorio": "modo_m"}),
        }
        values.update(kwargs)
        report = Laudo(**values)
        self.db.add(report)
        self.db.commit()
        return report

    def test_uses_exam_day_not_id_creation_update_or_finalization_and_only_same_patient(self):
        self.add_report(50, "2024-10-20", status="Rascunho")
        self.add_report(90, "2024-09-01", created_at=datetime(2025, 1, 1))
        self.add_report(5, "2024-10-01", veterinario_id=99, clinic_id=200,
                        created_at=datetime(2020, 1, 1), updated_at=datetime(2020, 1, 1),
                        finalizado_em=datetime(2020, 1, 1))
        self.add_report(6, "2024-10-19", paciente_id=2)
        self.add_report(7, "2024-10-19", status="Rascunho")
        self.add_report(8, "2024-10-19", status="Arquivado")
        self.add_report(9, "2024-10-19", tipo="eletrocardiograma")
        self.add_report(10, "2024-10-20")
        self.add_report(11, "2024-10-21")
        self.add_report(12, None, data_laudo=datetime(2024, 10, 19))

        result = comparar_laudo_anterior(self.db, 50)

        self.assertEqual(result.estado, "disponivel")
        self.assertEqual(result.anterior.id, 5)
        self.assertEqual(result.atual.data_exame, "2024-10-20")
        self.assertEqual([(option.id, option.data_exame) for option in result.opcoes],
                         [(5, "2024-10-01"), (90, "2024-09-01")])

    def test_duplicate_latest_day_requires_selection_and_all_eligible_options_work(self):
        self.add_report(1, "2024-10-20")
        self.add_report(2, "2024-10-01T08:00:00")
        self.add_report(3, "2024-10-01T14:00:00")
        self.add_report(4, "2024-09-01")

        automatic = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(automatic.estado, "data_anterior_ambigua")
        self.assertIsNone(automatic.anterior)
        self.assertEqual([option.id for option in automatic.opcoes], [3, 2, 4])
        for report_id in (2, 3, 4):
            with self.subTest(report_id=report_id):
                selected = comparar_laudo_anterior(self.db, 1, anterior_id=report_id)
                self.assertEqual(selected.estado, "disponivel")
                self.assertEqual(selected.anterior.id, report_id)

    def test_automatic_selection_keeps_completed_statuses_in_both_snapshots(self):
        for current_status in ("Finalizado", PORTAL_RELEASED_STATUS):
            for previous_status in ("Finalizado", PORTAL_RELEASED_STATUS):
                with self.subTest(current=current_status, previous=previous_status):
                    self.db.query(Laudo).delete()
                    self.db.commit()
                    self.add_report(1, "2024-10-20", status=current_status)
                    self.add_report(2, "2024-10-01", status=previous_status)
                    self.add_report(3, "2024-09-01", status="Finalizado")

                    result = comparar_laudo_anterior(self.db, 1)

                    self.assertEqual(result.estado, "disponivel")
                    self.assertEqual(result.anterior.id, 2)
                    self.assertEqual(result.atual.status, current_status)
                    self.assertEqual(result.anterior.status, previous_status)
                    self.assertEqual([option.id for option in result.opcoes], [2, 3])

    def test_manual_selection_accepts_both_completed_statuses_and_excludes_noncompleted(self):
        self.add_report(1, "2024-10-20", status="Rascunho")
        self.add_report(2, "2024-10-01", status=PORTAL_RELEASED_STATUS)
        self.add_report(3, "2024-09-01", status="Finalizado")
        excluded = ("Rascunho", "Arquivado", "FinalizadoXYZ", "Liberado no portalXYZ", "")
        for report_id, status in enumerate(excluded, start=4):
            self.add_report(report_id, "2024-10-19", status=status)

        for report_id, status in ((2, PORTAL_RELEASED_STATUS), (3, "Finalizado")):
            with self.subTest(report_id=report_id):
                result = comparar_laudo_anterior(self.db, 1, anterior_id=report_id)
                self.assertEqual(result.anterior.id, report_id)
                self.assertEqual(result.anterior.status, status)
                self.assertEqual(result.atual.status, "Rascunho")
                self.assertEqual([option.id for option in result.opcoes], [2, 3])
        for report_id in range(4, 4 + len(excluded)):
            with self.subTest(excluded_id=report_id):
                with self.assertRaises(LaudoComparacaoNaoEncontrada):
                    comparar_laudo_anterior(self.db, 1, anterior_id=report_id)

    def test_same_day_tie_across_completed_statuses_still_requires_selection(self):
        self.add_report(1, "2024-10-20")
        self.add_report(2, "2024-10-01T08:00:00", status="Finalizado")
        self.add_report(3, "2024-10-01T14:00:00", status=PORTAL_RELEASED_STATUS)

        result = comparar_laudo_anterior(self.db, 1)

        self.assertEqual(result.estado, "data_anterior_ambigua")
        self.assertIsNone(result.anterior)
        self.assertEqual([option.id for option in result.opcoes], [3, 2])
        for report_id in (2, 3):
            with self.subTest(report_id=report_id):
                self.assertEqual(comparar_laudo_anterior(self.db, 1, anterior_id=report_id).anterior.id,
                                 report_id)

    def test_portal_released_candidates_keep_patient_date_and_modality_guards(self):
        self.add_report(1, "2024-10-20")
        self.add_report(2, "2024-10-01", status=PORTAL_RELEASED_STATUS)
        self.add_report(3, "2024-10-19", status=PORTAL_RELEASED_STATUS, paciente_id=2)
        self.add_report(4, "2024-10-20", status=PORTAL_RELEASED_STATUS)
        self.add_report(5, "2024-10-21", status=PORTAL_RELEASED_STATUS)
        self.add_report(6, None, status=PORTAL_RELEASED_STATUS)
        self.add_report(7, "2024-10-19", status=PORTAL_RELEASED_STATUS, tipo="consulta")

        result = comparar_laudo_anterior(self.db, 1)

        self.assertEqual(result.anterior.id, 2)
        self.assertEqual([option.id for option in result.opcoes], [2])
        for report_id in range(3, 8):
            with self.subTest(report_id=report_id):
                with self.assertRaises(LaudoComparacaoNaoEncontrada):
                    comparar_laudo_anterior(self.db, 1, anterior_id=report_id)

    def test_ineligible_manual_selection_has_one_generic_exception(self):
        self.add_report(1, "2024-10-20")
        ineligible = [
            self.add_report(2, "2024-10-01", paciente_id=2),
            self.add_report(3, "2024-10-01", status="Rascunho"),
            self.add_report(4, "2024-10-01", status="Arquivado"),
            self.add_report(5, "2024-10-01", tipo="consulta"),
            self.add_report(6, "2024-10-20"),
            self.add_report(7, "2024-10-21"),
            self.add_report(8, None),
        ]
        for report_id in (1, 999, *(report.id for report in ineligible)):
            with self.subTest(report_id=report_id):
                with self.assertRaises(LaudoComparacaoNaoEncontrada):
                    comparar_laudo_anterior(self.db, 1, anterior_id=report_id)

    def test_missing_date_does_not_use_administrative_fallback(self):
        self.add_report(1, None, data_laudo=datetime(2024, 10, 20))
        self.add_report(2, "2024-10-01")
        result = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(result.estado, "data_atual_ausente")
        self.assertIsNone(result.atual.data_exame)
        self.assertIsNone(result.anterior)
        self.assertEqual(result.opcoes, [])
        with self.assertRaises(LaudoComparacaoNaoEncontrada):
            comparar_laudo_anterior(self.db, 1, anterior_id=2)

    def test_missing_current_and_orphan_patient_fail_without_matching_names(self):
        self.add_report(1, "2024-10-20", paciente_id=999)
        with self.assertRaises(LaudoComparacaoPacienteAusente):
            comparar_laudo_anterior(self.db, 1)
        with self.assertRaises(LaudoComparacaoNaoEncontrada):
            comparar_laudo_anterior(self.db, 999)

    def test_non_echo_and_no_prior_have_explicit_empty_states(self):
        self.add_report(1, "2024-10-20", tipo="consulta")
        unsupported = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(unsupported.estado, "tipo_nao_suportado")
        self.assertEqual(unsupported.atual.medidas, {})
        self.assertEqual(unsupported.opcoes, [])
        self.add_report(2, "2024-10-20")
        no_prior = comparar_laudo_anterior(self.db, 2)
        self.assertEqual(no_prior.estado, "sem_anterior")
        self.assertIsNone(no_prior.anterior)

    def test_echo_type_tolerates_case_and_surrounding_spaces_only(self):
        self.add_report(1, "2024-10-20", tipo=" ECOCARDIOGRAMA ")
        self.add_report(2, "2024-10-01", tipo="Ecocardiograma")
        self.add_report(3, "2024-10-19", tipo="ecocardiogramaXYZ")
        result = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(result.anterior.id, 2)
        self.assertEqual([option.id for option in result.opcoes], [2])

    def test_snapshot_only_contains_registered_whitelisted_fields_with_units_unchanged(self):
        measurements = {
            "DIVEd": "3,0", "SIVd": "0.4", "PLVEd": "0.5", "DIVES": "2.1",
            "SIVs": "0.6", "PLVES": "0.7", "DIVEd_2D": "31", "SIVd_2D": "4",
            "PLVEd_2D": "5", "DIVES_2D": "20", "SIVs_2D": "6", "PLVES_2D": "7",
            "VE_tecnica_relatorio": "2d", "VE_vista_2D": "eixo_curto",
            "AE_Ao": "1.4", "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial_sueco",
            "unidade_confirmada_DIVEd": "cm", "unidade_confirmada_SIVd": "cm",
            "unidade_confirmada_DIVEd_2D": "mm", "unidade_confirmada_Aorta": "mm",
            "DIVEd_normalizado": "99", "DIVEd_normalizado_2D": "98",
            "peso_kg": "18", "Aorta": "15", "Atrio_esquerdo": "21",
            "Onda_E": "1.08", "Onda_A": "0.95", "E_A": "1.14",
            "Diastolica_ondas": "fundidas", "E_E_linha": "6.95",
        }
        self.add_report(1, "2024-10-20", descricao=description(measurements),
                        anexos=json.dumps({"peso_kg": 99, "telefone": "REDACTED"}),
                        diagnostico="PRIVATE DIAGNOSIS", observacoes="PRIVATE NOTES")
        self.add_report(2, "2024-10-01", descricao=description(measurements))

        result = comparar_laudo_anterior(self.db, 1)
        expected = {key: value.replace(",", ".") for key, value in measurements.items()
                    if key in {"DIVEd", "SIVd", "PLVEd", "DIVES", "SIVs", "PLVES",
                               "DIVEd_2D", "SIVd_2D", "PLVEd_2D", "DIVES_2D", "SIVs_2D", "PLVES_2D",
                               "VE_tecnica_relatorio", "VE_vista_2D", "AE_Ao", "AE_Ao_metodo",
                               "unidade_confirmada_DIVEd", "unidade_confirmada_SIVd", "unidade_confirmada_DIVEd_2D",
                               "Aorta", "Atrio_esquerdo", "unidade_confirmada_Aorta"}}
        self.assertEqual(result.atual.medidas, expected)
        self.assertEqual(result.anterior.medidas, expected)
        self.assertEqual(result.anterior.medidas["DIVEd"], "3.0")
        serialized = result.model_dump_json()
        for leaked in ("PRIVATE", "REDACTED", "MESMO NOME", "peso", "normalizado"):
            self.assertNotIn(leaked, serialized)
        for key in ("Onda_E", "Onda_A", "E_A", "E_E_linha", "Diastolica_ondas"):
            self.assertNotIn(key, result.atual.medidas)
            self.assertNotIn(key, result.anterior.medidas)

    def test_does_not_fill_cleared_values_or_infer_technique_from_one_family(self):
        self.add_report(1, "2024-10-20", descricao=description({"DIVEd": "", "SIVd": "0"}))
        self.add_report(2, "2024-10-01", descricao=description(
            {"DIVEd_2D": "31", "DIVES_2D": ""},
            qualitative="- VE_tecnica_relatorio: 2d\n",
        ))
        result = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(result.atual.medidas, {"DIVEd": "", "SIVd": "0"})
        self.assertEqual(result.anterior.medidas, {"DIVEd_2D": "31", "DIVES_2D": ""})
        self.assertNotIn("VE_tecnica_relatorio", result.anterior.medidas)

    def test_preserves_unknown_or_cleared_explicit_units_including_last_duplicate(self):
        for suffix, raw_unit in enumerate(("cm.", "in", "", "CM."), start=1):
            with self.subTest(raw_unit=raw_unit):
                report = self.add_report(suffix, "2024-10-20", descricao=(
                    "## Medidas Ecocardiograficas\n"
                    "- DIVEd: 3\n- VE_tecnica_relatorio: modo_m\n"
                    "- unidade_confirmada_DIVEd: cm\n"
                    f"- unidade_confirmada_DIVEd: {raw_unit}\n"
                    "\n## Avaliacao Qualitativa\n"
                    "- unidade_confirmada_DIVEd: mm\n"
                ))
                result = comparar_laudo_anterior(self.db, report.id)
                self.assertEqual(result.atual.medidas["DIVEd"], "3")
                self.assertEqual(result.atual.medidas["unidade_confirmada_DIVEd"], raw_unit)
                self.assertEqual(result.atual.medidas["VE_tecnica_relatorio"], "modo_m")

    def test_last_canonical_clear_or_invalid_value_does_not_revive_previous_measurement_or_method(self):
        report = self.add_report(1, "2024-10-20", descricao=(
            "## Medidas Ecocardiograficas\n"
            "- DIVEd: 29\n- DIVEd: \n"
            "- DIVES: 20\n- DIVES: valor retirado\n"
            "- SIVd: 5\n- SIVd: 0x10\n"
            "- VE_tecnica_relatorio: modo_m\n- VE_tecnica_relatorio: \n"
            "- VE_vista_2D: eixo_curto\n- VE_vista_2D: desconhecida\n"
            "- AE_Ao: 1.4\n- AE_Ao: \n"
            "- AE_Ao_metodo: 2d_eixo_curto_diastole_inicial_sueco\n"
            "- AE_Ao_metodo: desconhecido\n"
            "\n## Avaliacao Qualitativa\n"
            "- DIVEd: 99\n- VE_tecnica_relatorio: modo_m\n"
        ))
        result = comparar_laudo_anterior(self.db, report.id)
        self.assertEqual(result.atual.medidas, {
            "DIVEd": "", "DIVES": "valor retirado", "SIVd": "0x10",
            "VE_tecnica_relatorio": "", "VE_vista_2D": "desconhecida",
            "AE_Ao": "", "AE_Ao_metodo": "desconhecido",
        })

    def test_last_valid_canonical_line_keeps_parser_normalization_with_crlf_and_alias_controls(self):
        report = self.add_report(1, "2024-10-20", descricao=(
            "## Medidas Ecocardiográficas\r\n"
            "- DIVEd: inválido\r\n- DIVEd: 3,0\r\n"
            "- LVIDd: 99\r\n"
            "- AE_Ao: 1,4\r\n- LA_Ao: 9\r\n"
            "- unidade_confirmada_DIVEd: cm.\r\n- unidade_confirmada_DIVEd: CM\r\n"
            "- unidade_confirmada_LVIDd: in\r\n"
            "- VE_tecnica_relatorio: inválido\r\n- VE_tecnica_relatorio: Modo-M\r\n"
            "- VE_vista_2D: desconhecida\r\n- VE_vista_2D: eixo_curto\r\n"
            "- AE_Ao_metodo: desconhecido\r\n"
            "- AE_Ao_metodo: 2d_eixo_curto_diastole_inicial_sueco\r\n"
            "\r\n## Avaliacao Qualitativa\r\n"
            "- DIVEd: 88\r\n- unidade_confirmada_DIVEd: mm\r\n"
        ))
        result = comparar_laudo_anterior(self.db, report.id)
        self.assertEqual(result.atual.medidas, {
            "DIVEd": "3.0", "AE_Ao": "1.4", "unidade_confirmada_DIVEd": "cm",
            "VE_tecnica_relatorio": "modo_m", "VE_vista_2D": "eixo_curto",
            "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial_sueco",
        })

    def test_does_not_capture_units_or_canonical_lines_outside_first_real_measurements_section(self):
        report = self.add_report(1, "2024-10-20", descricao=(
            "- DIVEd: 99\n- unidade_confirmada_DIVEd: cm.\n"
            "## Medidas Ecocardiograficas\n- DIVEd: 29\n"
            "## Avaliacao Qualitativa\n- unidade_confirmada_DIVEd: in\n"
            "- VE_tecnica_relatorio: modo_m\n- DIVEd: 88\n"
            "## Medidas Ecocardiograficas\n- DIVEd: 77\n"
        ))
        result = comparar_laudo_anterior(self.db, report.id)
        self.assertEqual(result.atual.medidas, {"DIVEd": "29"})

    def test_empty_first_section_never_falls_through_to_qualitative_or_second_measurement_section(self):
        later_sections = (
            "## Avaliacao Qualitativa\n- DIVEd: 99\n- VE_tecnica_relatorio: modo_m\n",
            "## Medidas Ecocardiograficas\n- DIVEd: 88\n- VE_tecnica_relatorio: modo_m\n",
            "## Avaliacao Qualitativa\n- LVIDd: 77\n- AE_Ao: 9\n"
            "- unidade_confirmada_DIVEd: cm\n"
            "## Medidas Ecocardiograficas\n- DIVEd: 66\n",
        )
        for report_id, later in enumerate(later_sections, start=1):
            for line_end in ("\n", "\r\n"):
                with self.subTest(later=later.splitlines()[0], line_end=repr(line_end)):
                    raw = ("## Medidas Ecocardiograficas\n\n" + later).replace("\n", line_end)
                    report = self.add_report(report_id * 10 + len(line_end), "2024-10-20", descricao=raw)
                    result = comparar_laudo_anterior(self.db, report.id)
                    self.assertEqual(result.atual.medidas, {})

    def test_inline_heading_mention_does_not_replace_the_first_real_measurements_section(self):
        report = self.add_report(1, "2024-10-20", descricao=(
            "Mencao em texto: ## Medidas Ecocardiograficas\n- DIVEd: 99\n"
            "## Medidas Ecocardiograficas\n- DIVEd: 29\n"
            "## Avaliacao Qualitativa\n- DIVEd: 88\n"
        ))
        result = comparar_laudo_anterior(self.db, report.id)
        self.assertEqual(result.atual.medidas, {"DIVEd": "29"})

    def test_unit_confirmation_is_never_guessed_or_converted_and_methods_remain_distinct(self):
        self.add_report(1, "2024-10-20", descricao=description({
            "DIVEd": "3", "SIVd": "0.4", "PLVEd": "0.5",
            "VE_tecnica_relatorio": "modo_m", "unidade_confirmada_DIVEd": "cm",
            "AE_Ao": "1.4", "AE_Ao_metodo": "outro",
        }))
        self.add_report(2, "2024-10-01", descricao=description({
            "DIVEd_2D": "30", "VE_tecnica_relatorio": "2d", "VE_vista_2D": "eixo_longo",
            "AE_Ao": "1.4", "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial_sueco",
        }))
        result = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(result.atual.medidas["DIVEd"], "3")
        self.assertEqual(result.atual.medidas["unidade_confirmada_DIVEd"], "cm")
        self.assertNotIn("unidade_confirmada_SIVd", result.atual.medidas)
        self.assertEqual(result.atual.medidas["VE_tecnica_relatorio"], "modo_m")
        self.assertEqual(result.anterior.medidas["VE_tecnica_relatorio"], "2d")
        self.assertEqual(result.anterior.medidas["VE_vista_2D"], "eixo_longo")

    def test_snapshot_keeps_full_registered_length_context_for_unit_ambiguity_guard(self):
        measurements = {
            "DIVEd": "2", "Aorta": "1", "Atrio_esquerdo": "1.4",
            "AE_diametro_max": "1.5", "AE_diametro_min": "1.2",
            "Ao_nivel_AP": "1", "AP": "0.9",
            "unidade_confirmada_AP": "cm", "VE_tecnica_relatorio": "modo_m",
        }
        self.add_report(1, "2024-10-20", descricao=description(measurements))
        result = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(result.atual.medidas, measurements)
        self.assertIn("DIVEd", ambiguous_echo_length_keys(result.atual.medidas))
        self.assertNotIn("AP", ambiguous_echo_length_keys(result.atual.medidas))

    def test_read_does_not_flush_write_modify_reports_or_mutate_projected_dicts(self):
        current = self.add_report(1, "2024-10-20")
        previous = self.add_report(2, "2024-10-01")
        original = (current.descricao, previous.descricao, current.updated_at, previous.updated_at)
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with patch.object(self.db, "commit", side_effect=AssertionError("read committed")), \
                    patch.object(self.db, "flush", side_effect=AssertionError("read flushed")), \
                    patch.object(laudos, "enqueue_laudo_pdf_job", side_effect=AssertionError("PDF")), \
                    patch.object(laudos, "registrar_auditoria", side_effect=AssertionError("audit")):
                first = comparar_laudo_anterior(self.db, 1)
                pristine = copy.deepcopy(first.model_dump())
                first.anterior.medidas["DIVEd"] = "999"
                second = comparar_laudo_anterior(self.db, 1)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(second.model_dump(), pristine)
        self.assertEqual(original, (current.descricao, previous.descricao, current.updated_at, previous.updated_at))
        self.assertFalse(self.db.new or self.db.dirty or self.db.deleted)
        self.assertTrue(statements)
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in statements))

    def test_no_autoflush_even_with_unrelated_pending_patient_edit(self):
        self.add_report(1, "2024-10-20")
        patient = self.db.get(Paciente, 1)
        patient.peso_kg = 99
        with patch.object(self.db, "flush", side_effect=AssertionError("read flushed pending change")):
            result = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(result.estado, "sem_anterior")
        self.assertIn(patient, self.db.dirty)
        self.assertEqual(patient.peso_kg, 99)

    def test_uses_shared_calendar_helper_for_timezone_and_legacy_midnight_dates(self):
        current = self.add_report(1, "2024-10-20")
        previous = self.add_report(2, "2024-10-19")
        # SQLite strips timezone offsets on round-trip. Retain the aware ORM
        # values for this pure helper boundary; DB identity/status selection is
        # exercised independently by the real SQLite tests above.
        current.data_exame = datetime(2024, 10, 20, 1, 30, tzinfo=timezone.utc)
        previous.data_exame = datetime(2024, 10, 18, 22, 0, tzinfo=timezone.utc)
        result = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(result.atual.data_exame, "2024-10-19")
        self.assertEqual(result.anterior.data_exame, "2024-10-18")
        current.data_exame = datetime(2024, 10, 20, 0, 0, tzinfo=timezone.utc)
        legacy = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(legacy.atual.data_exame, "2024-10-20")

    def test_future_current_date_requires_confirmation_even_with_historical_candidate(self):
        self.add_report(1, "2099-10-20")
        self.add_report(2, "2099-10-01")
        self.add_report(3, "2024-10-01")
        result = comparar_laudo_anterior(self.db, 1)
        self.assertEqual(result.estado, "data_atual_ausente")
        self.assertEqual(result.opcoes, [])
        self.assertIsNone(result.anterior)
        with self.assertRaises(LaudoComparacaoNaoEncontrada):
            comparar_laudo_anterior(self.db, 1, anterior_id=3)


class LaudoComparacaoAnteriorAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        for table in (Paciente.__table__, Laudo.__table__, Papel.__table__, User.__table__,
                      usuario_papel, PapelPermissao.__table__):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        with self.sessions() as db:
            doctor = Papel(id=1, nome="medico")
            admin = Papel(id=2, nome="admin")
            db.add_all([doctor, admin])
            db.add_all([
                User(id=1, email="reader@example.invalid", ativo=1, papeis=[doctor]),
                User(id=2, email="inactive@example.invalid", ativo=0, papeis=[doctor]),
                User(id=3, email="admin@example.invalid", ativo=1, papeis=[admin]),
            ])
            db.add(PapelPermissao(papel_id=1, modulo="laudos", visualizar=1, editar=0, excluir=0))
            db.add(Paciente(id=1, nome="TESTE PROTEGIDO", peso_kg=3))
            db.add(Paciente(id=2, nome="TESTE PROTEGIDO", peso_kg=3))
            db.add_all([
                Laudo(id=1, paciente_id=1, veterinario_id=1, tipo="ecocardiograma", titulo="PRIVATE TITLE",
                      status="Rascunho", data_exame=datetime(2024, 10, 20), descricao=description({"DIVEd": "30"})),
                Laudo(id=2, paciente_id=1, veterinario_id=1, tipo="ecocardiograma", titulo="PRIVATE TITLE",
                      status="Finalizado", data_exame=datetime(2024, 10, 1), descricao=description({"DIVEd": "29"})),
                Laudo(id=3, paciente_id=2, veterinario_id=1, tipo="ecocardiograma", titulo="PRIVATE TITLE",
                      status="Finalizado", data_exame=datetime(2024, 10, 1), descricao=description({"DIVEd": "29"})),
            ])
            db.commit()

        def isolated_db():
            with self.sessions() as db:
                yield db

        self.app = FastAPI()
        self.app.include_router(laudos.router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = isolated_db
        self.client = TestClient(self.app)
        self.decode = patch.object(security, "_decode_token_and_load_user", side_effect=self.load_user)
        self.decode.start()

    def tearDown(self):
        self.decode.stop()
        self.client.close()
        self.engine.dispose()

    @staticmethod
    def load_user(db, token):
        return db.get(User, {"reader": 1, "inactive": 2, "admin": 3}[token])

    def get_comparison(self, token=None, *, query="", current_id=1):
        return self.client.get(
            f"/api/v1/laudos/{current_id}/comparacao-anterior{query}",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )

    def test_route_keeps_real_auth_dependency_and_read_permission(self):
        route = next(route for route in self.app.routes
                     if getattr(route, "path", "") == "/api/v1/laudos/{laudo_id}/comparacao-anterior")
        self.assertTrue(any(dependency.call is security.get_current_user for dependency in route.dependant.dependencies))
        anonymous = self.get_comparison()
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(anonymous.headers["www-authenticate"], "Bearer")
        self.assertEqual(self.get_comparison("inactive").status_code, 403)
        self.assertEqual(self.get_comparison("reader").status_code, 200)

        with self.sessions() as db:
            db.query(PapelPermissao).filter(PapelPermissao.papel_id == 1).update({"visualizar": 0})
            db.commit()
        blocked = self.get_comparison("reader")
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("visualizar em laudos", blocked.json()["detail"])
        self.assertEqual(self.get_comparison("admin").status_code, 200)

    def test_http_schema_generic_404_and_no_pii(self):
        response = self.get_comparison("reader")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload), {"estado", "paciente_id", "atual", "anterior", "opcoes"})
        self.assertEqual(set(payload["atual"]), {"id", "paciente_id", "status", "data_exame", "medidas"})
        self.assertEqual(payload["atual"]["paciente_id"], payload["paciente_id"])
        self.assertEqual(payload["anterior"]["paciente_id"], payload["paciente_id"])
        self.assertEqual(payload["anterior"]["id"], 2)
        self.assertNotIn("PRIVATE", response.text)
        self.assertNotIn("TESTE PROTEGIDO", response.text)
        errors = [self.get_comparison("reader", query=f"?anterior_id={report_id}") for report_id in (1, 3, 999)]
        errors.append(self.get_comparison("reader", current_id=999))
        self.assertTrue(all(error.status_code == 404 for error in errors))
        self.assertTrue(all(error.json() == {"detail": "Comparação não encontrada"} for error in errors))
        manual = self.get_comparison("reader", query="?anterior_id=2")
        self.assertEqual(manual.status_code, 200)
        self.assertEqual(manual.json()["anterior"]["id"], 2)

    def test_missing_patient_is_generic_422_and_does_not_search_same_name(self):
        with self.sessions() as db:
            db.query(Laudo).filter(Laudo.id == 1).update({"paciente_id": 999})
            db.commit()
        response = self.get_comparison("reader")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "Paciente do laudo indisponível"})

    def test_route_returns_portal_released_previous_automatically_and_when_selected(self):
        with self.sessions() as db:
            db.query(Laudo).filter(Laudo.id.in_((1, 2))).update({"status": PORTAL_RELEASED_STATUS})
            db.commit()
        for query in ("", "?anterior_id=2"):
            with self.subTest(query=query):
                response = self.get_comparison("reader", query=query)
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["estado"], "disponivel")
                self.assertEqual(payload["anterior"]["id"], 2)
                self.assertEqual(payload["atual"]["status"], PORTAL_RELEASED_STATUS)
                self.assertEqual(payload["anterior"]["status"], PORTAL_RELEASED_STATUS)


if __name__ == "__main__":
    unittest.main()
