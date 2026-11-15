"""Métricas de agenda com dados sintéticos; nenhuma dependência de produção."""
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.agendamento import Agendamento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.services.gestao_agenda import _interval, build_agenda_metrics


class GestaoAgendaTest(unittest.TestCase):
    day = date(2026, 10, 19)  # Segunda-feira.

    def setUp(self):
        self.engine = create_engine("sqlite://")
        for model in (Configuracao, Clinica, Agendamento, AgendaBloqueio, AuditoriaEvento):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.config = Configuracao(agenda_semanal=json.dumps({
            str(i): {"ativo": i <= 5, "inicio": "08:00", "fim": "14:00"} for i in range(1, 8)
        }))
        self.a = Clinica(nome="Parceira A sintética", regiao_operacional="Sul", cidade="Fortaleza", ativo=True)
        self.b = Clinica(nome="Parceira B sintética", cidade="Caucaia", ativo=False)
        self.db.add_all([self.config, self.a, self.b])
        self.db.commit()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)

    def appointment(self, hour="09:00", minutes=60, status="Agendado", clinic=None, day=None, **fields):
        day = day or self.day
        begin = datetime.fromisoformat(f"{day}T{hour}")
        row = Agendamento(
            inicio=begin, fim=begin + timedelta(minutes=minutes) if minutes is not None else None,
            data=str(day), hora=hour, status=status, clinica_id=self.a.id if clinic is None else clinic,
            **fields,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def block(self, identifier, begin, finish, active=True):
        self.db.add(AgendaBloqueio(
            id=identifier, inicio=datetime.fromisoformat(begin), fim=datetime.fromisoformat(finish),
            motivo="Ausência sintética, informação privada", ativo=active, criado_por_id=1,
        ))
        self.db.commit()

    def metrics(self, start=None, end=None, clinic=None, region=None):
        return build_agenda_metrics(self.db, start or self.day, end or self.day, clinic, region, date(2026, 10, 25))

    def audit(self, row, details, action="AGENDAMENTO_ATUALIZADO"):
        self.db.add(AuditoriaEvento(
            modulo="agenda", entidade="agendamento", entidade_id=str(row.id), acao=action,
            detalhes_json=json.dumps(details), descricao="Nome privado não deve sair",
        ))
        self.db.commit()

    def test_union_of_overlaps_and_blocks_preserves_single_capacity(self):
        self.block("one", "2026-10-19T10:00", "2026-10-19T11:00")
        self.block("two", "2026-10-19T10:30", "2026-10-19T11:30")
        self.block("inactive", "2026-10-19T08:00", "2026-10-19T14:00", active=False)
        self.appointment("08:00", 60)
        self.appointment("08:30", 60, status="Realizado", clinic=self.b.id)
        result = self.metrics()["ocupacao"]
        self.assertEqual(result["capacidade_minutos"], 270)
        self.assertEqual(result["dias"][0]["bloqueados_minutos"], 90)
        self.assertEqual(result["agendados_minutos"], 90)
        self.assertEqual(result["realizados_minutos"], 60)
        self.assertEqual(result["livres_minutos"], 180)
        self.assertEqual(result["taxa_agendada_pct"], 33.33)
        self.assertEqual(result["dias"][0]["janelas_livres"], [
            {"inicio": "09:30", "fim": "10:00"}, {"inicio": "11:30", "fim": "14:00"},
        ])

    def test_clinic_and_region_filter_do_not_invent_extra_free_capacity(self):
        self.appointment("08:00", 60)
        self.appointment("10:00", 60, clinic=self.b.id)
        result = self.metrics(clinic=self.a.id)["ocupacao"]
        self.assertEqual(result["capacidade_minutos"], 360)
        self.assertEqual(result["agendados_minutos"], 60)
        self.assertEqual(result["agendados_totais_minutos"], 120)
        self.assertEqual(result["livres_minutos"], 240)
        self.assertEqual(result["taxa_agendada_pct"], 16.67)
        regional = self.metrics(region="caucaia")["ocupacao"]
        self.assertEqual(regional["por_regiao"], [{"regiao": "Caucaia", "agendados_minutos": 60, "realizados_minutos": 0}])
        self.assertFalse(regional["registros"][0]["clinica_ativa"])
        self.assertEqual(self.metrics(clinic=self.a.id, region="Caucaia")["cancelamentos"]["total_agendamentos"], 0)

    def test_exception_overrides_holiday_and_weekly_closure(self):
        sunday = date(2026, 10, 25)
        self.config.agenda_feriados = json.dumps([str(sunday), str(self.day)])
        self.config.agenda_excecoes = json.dumps([{"data": str(sunday), "ativo": True, "inicio": "10:00", "fim": "12:00"}])
        self.db.commit()
        self.assertEqual(self.metrics(sunday, sunday)["ocupacao"]["capacidade_minutos"], 120)
        monday = self.metrics()["ocupacao"]
        self.assertEqual(monday["capacidade_minutos"], 0)
        self.assertEqual(monday["dias"][0]["motivo_fechado"], "Feriado cadastrado")
        self.assertIsNone(monday["taxa_agendada_pct"])

    def test_full_day_absence_and_multiday_block_are_clipped_to_journey(self):
        self.block("absence", "2026-10-19T12:00", "2026-10-20T10:00")
        result = self.metrics(end=date(2026, 10, 20))["ocupacao"]
        self.assertEqual(result["capacidade_minutos"], 480)
        self.assertEqual([row["capacidade_minutos"] for row in result["dias"]], [240, 240])
        self.config.agenda_excecoes = json.dumps([{"data": str(self.day), "ativo": False}])
        self.db.commit()
        self.assertEqual(self.metrics()["ocupacao"]["capacidade_minutos"], 0)

    def test_cancelled_expired_no_show_and_current_reservation_are_distinct(self):
        self.appointment(status="Cancelado")
        self.appointment(status="Faltou")
        self.appointment(status="Expirado")
        expired = self.appointment(status="Reservado", reserva_expira_em=datetime(2026, 10, 18, 23, 59))
        self.appointment(status="Reservado", reserva_expira_em=datetime(2099, 1, 1))
        self.appointment(status="Realizado")
        result = self.metrics()
        cancel = result["cancelamentos"]
        self.assertEqual(cancel["total_agendamentos"], 6)
        self.assertEqual(cancel["total_cancelados"], 1)
        self.assertEqual(cancel["taxa_pct"], 16.67)
        statuses = {row["status"]: row["quantidade"] for row in cancel["por_status"]}
        self.assertEqual(statuses, {"Cancelado": 1, "Faltou": 1, "Expirado": 2, "Reservado": 1, "Realizado": 1})
        self.db.expire_all()
        self.assertEqual(self.db.get(Agendamento, expired.id).status, "Reservado")
        self.assertEqual(result["ocupacao"]["agendados_minutos"], 60)

    def test_audit_events_do_not_duplicate_population_or_cancel_reactivated_records(self):
        row = self.appointment(status="Confirmado")
        details = {"antes": {"inicio": "2026-10-18T09:00", "status": "Cancelado"},
                   "depois": {"inicio": "2026-10-19T09:00", "status": "Confirmado"}}
        self.audit(row, details)
        self.audit(row, details)
        cancelled_again = self.appointment(status="Cancelado")
        self.audit(cancelled_again, {"status_anterior": "Cancelado", "status_novo": "Agendado"}, "AGENDAMENTO_STATUS_ALTERADO")
        reinstated = self.appointment(status="Reservado", reserva_expira_em=datetime(2099, 1, 1))
        self.audit(reinstated, {"status_anterior": "Expirado", "status_novo": "Reservado"}, "AGENDAMENTO_RESERVA_REABILITADA")
        result = self.metrics()["cancelamentos"]
        self.assertEqual(result["total_agendamentos"], 3)
        self.assertEqual(result["total_cancelados"], 1)
        self.assertEqual(result["reativados_identificados"], 1)
        self.assertEqual(result["reagendados_identificados"], 1)
        self.assertEqual(result["reservas_reabilitadas_identificadas"], 1)

    def test_missing_duration_has_no_silent_thirty_minute_fallback(self):
        self.appointment("08:00", 60)
        self.appointment("10:00", None)
        result = self.metrics()["ocupacao"]
        self.assertEqual(result["agendados_minutos"], 60)
        self.assertIsNone(result["registros"][1]["duracao_minutos"])
        self.assertIsNone(result["livres_minutos"])
        self.assertIsNone(result["taxa_agendada_pct"])
        self.assertTrue(result["parcial"])
        self.assertEqual(result["dias"][0]["janelas_livres"], [])

    def test_missing_duration_outside_clinic_filter_still_prevents_false_free_time(self):
        self.appointment("08:00", 60)
        self.appointment("10:00", None, clinic=self.b.id)
        result = self.metrics(clinic=self.a.id)["ocupacao"]
        self.assertIsNone(result["livres_minutos"])
        self.assertEqual(len(result["registros"]), 1)

    def test_unknown_status_is_not_classified_as_cancellation_or_availability(self):
        self.appointment(status="Estado legado desconhecido")
        result = self.metrics()
        self.assertEqual(result["cancelamentos"]["total_cancelados"], 0)
        self.assertEqual(result["cancelamentos"]["total_agendamentos"], 1)
        self.assertIsNone(result["ocupacao"]["livres_minutos"])
        self.assertTrue(result["ocupacao"]["parcial"])

    def test_no_denominator_and_outside_working_hours_are_explicit(self):
        self.appointment("07:30", 60)
        result = self.metrics()["ocupacao"]
        self.assertEqual(result["agendados_minutos"], 30)
        self.assertEqual(result["capacidade_minutos"], 360)
        self.assertIn("30.0 minuto(s)", " ".join(result["lacunas"]))
        sunday = date(2026, 10, 25)
        result = self.metrics(sunday, sunday)
        self.assertIsNone(result["ocupacao"]["taxa_agendada_pct"])
        self.assertIsNone(result["cancelamentos"]["taxa_pct"])

    def test_local_timezone_and_legacy_date_hour_match_agenda_without_fallback_duration(self):
        row = SimpleNamespace(inicio=datetime(2026, 10, 20, 1, 30, tzinfo=timezone.utc),
                              fim=datetime(2026, 10, 20, 2, tzinfo=timezone.utc), data=None, hora=None)
        self.assertEqual(_interval(row), (datetime(2026, 10, 19, 22, 30), datetime(2026, 10, 19, 23)))
        row.data, row.hora = "2026-10-19", "09:15"
        self.assertEqual(_interval(row), (datetime(2026, 10, 19, 9, 15), datetime(2026, 10, 19, 9, 45)))
        row.fim = None
        self.assertEqual(_interval(row), (datetime(2026, 10, 19, 9, 15), None))

    def test_denormalized_date_controls_period_instead_of_utc_column(self):
        row = self.appointment()
        row.inicio, row.fim = datetime(2026, 10, 20, 1), datetime(2026, 10, 20, 2)
        self.db.commit()
        self.assertEqual(self.metrics()["cancelamentos"]["total_agendamentos"], 1)
        self.assertEqual(self.metrics(date(2026, 10, 20), date(2026, 10, 20))["cancelamentos"]["total_agendamentos"], 0)

    def test_legacy_cross_midnight_interval_occupies_next_day_without_double_counting_population(self):
        row = self.appointment("13:00", 20 * 60)
        result = self.metrics(end=date(2026, 10, 20))
        self.assertEqual(result["ocupacao"]["agendados_minutos"], 120)
        self.assertEqual([day["agendados_minutos"] for day in result["ocupacao"]["dias"]], [60, 60])
        self.assertEqual(result["cancelamentos"]["total_agendamentos"], 1)
        next_day = self.metrics(date(2026, 10, 20), date(2026, 10, 20))
        self.assertEqual(next_day["ocupacao"]["agendados_minutos"], 60)
        self.assertEqual(next_day["ocupacao"]["livres_minutos"], 300)
        self.assertEqual(next_day["cancelamentos"]["total_agendamentos"], 0)
        self.assertEqual(next_day["ocupacao"]["registros"][0]["agendamento_id"], row.id)
        self.assertFalse(next_day["ocupacao"]["registros"][0]["incluido_populacao_cancelamentos"])

    def test_interval_started_before_query_buffer_still_reserves_its_overlap(self):
        self.appointment("13:00", 4 * 24 * 60, day=date(2026, 10, 16))
        result = self.metrics()
        self.assertEqual(result["ocupacao"]["agendados_minutos"], 360)
        self.assertEqual(result["ocupacao"]["livres_minutos"], 0)
        self.assertEqual(result["cancelamentos"]["total_agendamentos"], 0)

    def test_absent_clinic_and_unlinked_records_remain_visible(self):
        missing = self.appointment(clinic=999)
        unlinked = self.appointment()
        unlinked.clinica_id = None
        self.db.commit()
        result = self.metrics(region="Não informada")
        self.assertEqual(result["cancelamentos"]["total_agendamentos"], 2)
        records = {row["agendamento_id"]: row for row in result["ocupacao"]["registros"]}
        self.assertIn("cadastro ausente", records[missing.id]["clinica_nome"])
        self.assertEqual(records[unlinked.id]["clinica_nome"], "Não vinculada")

    def test_read_only_and_no_patient_tutor_or_free_text_exposure(self):
        row = self.appointment(paciente="PACIENTE PRIVADO", tutor="TUTOR PRIVADO", observacoes="DADO CLÍNICO PRIVADO")
        self.audit(row, {"antes": {"paciente": "PACIENTE PRIVADO"}, "motivo": "DADO CLÍNICO PRIVADO"})
        statements = []
        def record(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", record)
        try:
            result = self.metrics()
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        text = json.dumps(result, ensure_ascii=False)
        for private in ["PACIENTE PRIVADO", "TUTOR PRIVADO", "DADO CLÍNICO PRIVADO", "Nome privado"]:
            self.assertNotIn(private, text)
        self.assertEqual(result["cancelamentos"]["motivos"], [])
        self.assertFalse(any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER")) for statement in statements))
        self.assertFalse(self.db.new or self.db.dirty or self.db.deleted)

    def test_missing_optional_sources_are_partial_not_silently_empty(self):
        AgendaBloqueio.__table__.drop(self.engine)
        AuditoriaEvento.__table__.drop(self.engine)
        result = self.metrics()
        self.assertTrue(result["ocupacao"]["parcial"])
        self.assertIsNone(result["ocupacao"]["livres_minutos"])
        self.assertIn("Fonte de bloqueios indisponível", " ".join(result["ocupacao"]["lacunas"]))
        self.assertIn("Histórico de auditoria indisponível", " ".join(result["cancelamentos"]["lacunas"]))

    def test_default_journey_is_same_as_agenda_and_invalid_period_is_rejected(self):
        self.db.delete(self.config)
        self.db.commit()
        self.assertEqual(self.metrics()["ocupacao"]["capacidade_minutos"], 360)
        with self.assertRaises(ValueError):
            self.metrics(date(2026, 10, 20), date(2026, 10, 19))


if __name__ == "__main__":
    unittest.main()
