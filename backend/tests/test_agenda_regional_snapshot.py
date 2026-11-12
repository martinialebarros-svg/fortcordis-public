"""Writer snapshots must precede ORM mutation before regional route validation."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException, Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "regional-snapshot-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from tests import test_agenda_sugestao_janela_operacional as fixtures


class AgendaRegionalSnapshotTest(unittest.TestCase):
    _build_session = fixtures.AgendaSugestaoJanelaOperacionalTest._build_session
    _seed_config = fixtures.AgendaSugestaoJanelaOperacionalTest._seed_config

    def setUp(self):
        self.tmpdir, self.db, self.engine = self._build_session()
        self._seed_config(self.db, excecoes=[], regras_rota={
            "thresholds": {"max_neighbor_travel_min": 30, "max_insertion_detour_min": 100},
            "route_policy": {"regional_transition_enabled": True,
                "regional_transition_max_travel_min": 50, "regional_transition_margin_min": 15,
                "regional_transition_max_legs_per_day": 1},
        })
        self.clinics = []
        for number in range(1, 5):
            clinic = Clinica(nome=f"Synthetic snapshot {number}", latitude=-3.73 - number / 1000,
                longitude=-38.52, cidade="Fortaleza", estado="CE")
            self.db.add(clinic)
            self.clinics.append(clinic)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def appointment(self, clinic, hour, *, status="Agendado"):
        start = datetime.fromisoformat(f"2099-05-25T{hour}:00")
        item = Agendamento(clinica_id=clinic.id, clinica=clinic.nome, inicio=start,
            fim=start + timedelta(minutes=30), data="2099-05-25", hora=hour, status=status)
        self.db.add(item)
        self.db.commit()
        return item

    def routes(self, values):
        def resolve(_db, *, origem, destino, **_kwargs):
            if origem["entity_id"] == destino["entity_id"]:
                return 0, "mesmo_destino"
            return values[(origem["entity_id"], destino["entity_id"])], "manual"
        return resolve

    def test_new_two_leg_route_is_not_grandfathered_after_orm_mutation(self):
        first = self.appointment(self.clinics[0], "09:00")
        moved = self.appointment(self.clinics[1], "10:30")
        last = self.appointment(self.clinics[2], "13:00")
        baseline = agenda._capturar_baseline_regional_agendamento(self.db, moved.inicio)
        moved.clinica_id = self.clinics[3].id
        moved.inicio = datetime(2099, 5, 25, 11, 0)
        moved.fim = moved.inicio + timedelta(minutes=30)
        c1, c2, c3, c4 = (clinic.id for clinic in self.clinics)
        with patch.object(agenda, "_obter_duracao_deslocamento_operacional", side_effect=self.routes({
            (c1, c2): 20, (c2, c3): 20, (c1, c4): 40, (c4, c3): 40,
        })):
            with self.assertRaises(HTTPException) as raised:
                agenda._validar_deslocamento_agendamento(self.db, moved,
                    agendamento_id_excluir=moved.id, baseline_regional=baseline)
            bypass = agenda._validar_deslocamento_agendamento(self.db, moved,
                agendamento_id_excluir=moved.id, baseline_regional=baseline,
                confirmar_conflito_deslocamento=True)
            self.assertEqual(bypass, {"origem": "confirmacao_admin",
                "bloqueio": "TRANSICAO_REGIONAL_COTA_EXCEDIDA"})
        self.assertEqual(raised.exception.detail["motivo_regional"], "TRANSICAO_REGIONAL_COTA_EXCEDIDA")
        self.assertEqual(raised.exception.detail["transicao_regional"]["transicoes_longas_anteriores"], 0)
        self.assertEqual(baseline[1]["destino_operacional"]["entity_id"], c2)
        self.assertEqual(first.id, baseline[0]["id"])
        self.assertEqual(last.id, baseline[2]["id"])

    def test_legacy_two_leg_route_can_keep_same_count_on_move(self):
        self.appointment(self.clinics[0], "08:00")
        moved = self.appointment(self.clinics[1], "10:00")
        self.appointment(self.clinics[2], "12:00")
        baseline = agenda._capturar_baseline_regional_agendamento(self.db, moved.inicio)
        moved.inicio += timedelta(minutes=15)
        moved.fim += timedelta(minutes=15)
        c1, c2, c3, _c4 = (clinic.id for clinic in self.clinics)
        with patch.object(agenda, "_obter_duracao_deslocamento_operacional", side_effect=self.routes({
            (c1, c2): 40, (c2, c3): 40, (c1, c3): 50,
        })):
            self.assertIsNone(agenda._validar_deslocamento_agendamento(self.db, moved,
                agendamento_id_excluir=moved.id, baseline_regional=baseline))

    def test_unrelated_fixed_legacy_leg_and_gap_are_preserved(self):
        self.appointment(self.clinics[0], "08:00")
        self.appointment(self.clinics[1], "08:45")
        candidate = Agendamento(clinica_id=self.clinics[2].id, inicio=datetime(2099, 5, 25, 10),
            fim=datetime(2099, 5, 25, 10, 30), status="Agendado")
        c1, c2, c3, _c4 = (clinic.id for clinic in self.clinics)
        with patch.object(agenda, "_obter_duracao_deslocamento_operacional", side_effect=self.routes({
            (c1, c2): 60, (c2, c3): 10,
        })):
            self.assertIsNone(agenda._validar_deslocamento_agendamento(self.db, candidate))

    def test_disabled_snapshot_never_reads_appointments(self):
        with patch.object(agenda, "_obter_regras_rota_agenda", return_value={"route_policy": {}}), \
             patch.object(agenda, "_listar_agendamentos_ativos_do_dia") as read_day:
            self.assertIsNone(agenda._capturar_baseline_regional_agendamento(self.db, datetime(2099, 5, 25, 10)))
        read_day.assert_not_called()

    def test_put_passes_pre_mutation_snapshot_to_validator(self):
        self.appointment(self.clinics[0], "09:00")
        moved = self.appointment(self.clinics[1], "10:30")
        self.appointment(self.clinics[2], "13:00")
        old_id = self.clinics[1].id
        stop = HTTPException(409, "synthetic-stop-before-write")
        with patch.object(agenda, "_adquirir_lock_escrita_agenda"), \
             patch.object(agenda, "_expirar_reservas_vencidas"), \
             patch.object(agenda, "_validar_agendamento_no_funcionamento"), \
             patch.object(agenda, "_validar_slot_disponivel", return_value=[]), \
             patch.object(agenda, "_validar_deslocamento_agendamento", side_effect=stop) as validate:
            with self.assertRaises(HTTPException):
                agenda.atualizar_agendamento(moved.id,
                    agenda.AgendamentoUpdate(clinica_id=self.clinics[3].id,
                        inicio="2099-05-25T11:00:00", fim="2099-05-25T11:30:00"),
                    Request({"type": "http"}), self.db,
                    SimpleNamespace(id=1, nome="Synthetic staff", tem_papel=lambda role: role == "admin"))
        snapshot = validate.call_args.kwargs["baseline_regional"]
        original = next(item for item in snapshot if item["id"] == moved.id)
        self.assertEqual(original["destino_operacional"]["entity_id"], old_id)
        self.assertEqual(original["inicio"].strftime("%H:%M"), "10:30")


if __name__ == "__main__":
    unittest.main()
