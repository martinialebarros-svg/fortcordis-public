import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from app.utils.paciente_idade import alteracoes_idade, idade_do_paciente, parse_idade
from app.utils.echo_low_weight_reference import low_weight_age_context


@pytest.fixture(autouse=True)
def today():
    with patch("app.utils.paciente_idade.hoje_operacional", return_value=date(2026, 11, 4)):
        yield


def patient(**values):
    return SimpleNamespace(nascimento=values.pop("nascimento", None), observacoes=values.pop("observacoes", None),
                           idade_fonte=values.pop("idade_fonte", None), idade_informada=values.pop("idade_informada", None),
                           idade_referencia=values.pop("idade_referencia", None), **values)


def test_edited_age_wins_without_erasing_birth_or_notes():
    row = patient(nascimento="2026-11-03", observacoes="Nota clínica\nIdade: 0m")
    changes = alteracoes_idade(row, {"idade": "12 anos"})
    assert "nascimento" not in changes
    assert changes["idade_referencia"] == date(2026, 11, 4)
    assert changes["observacoes"] == "Idade: 12 anos\nNota clínica"
    row.__dict__.update(changes)
    assert idade_do_paciente(row) == "12a (estimada)"
    assert low_weight_age_context(idade_do_paciente(row)) == "adult"


def test_age_progresses_and_uses_historical_reference():
    row = patient(idade_fonte="idade", idade_informada="8 meses", idade_referencia=date(2025, 1, 31))
    assert idade_do_paciente(row, data_referencia="2025-02-28") == "9m (estimada)"
    assert idade_do_paciente(row, data_referencia="2026-01-31") == "1a 8m (estimada)"
    assert idade_do_paciente(row, data_referencia="2024-04-01") == ""
    assert low_weight_age_context(idade_do_paciente(row, data_referencia="2025-02-28")) == "juvenile"


def test_days_and_weeks():
    row = patient(idade_fonte="idade", idade_informada="2 semanas", idade_referencia=date(2026, 11, 1))
    assert idade_do_paciente(row) == "17d (estimada)"
    assert idade_do_paciente(row, data_referencia="2026-10-01") == ""
    assert parse_idade("0,5 anos") == (6, 0)
    assert parse_idade("2a 3m") == (27, 0)


def test_exact_date_and_year_only():
    row = patient(nascimento="2025-11-04", idade_fonte="nascimento")
    assert idade_do_paciente(row) == "1a"
    assert idade_do_paciente(row, data_referencia="2026-11-03") == "11m"
    row.nascimento = "2025"
    assert idade_do_paciente(row) == "0–1 anos (estimada pelo ano)"
    assert low_weight_age_context(idade_do_paciente(row)) == "unknown"
    row.nascimento = "2026"
    assert low_weight_age_context(idade_do_paciente(row)) == "juvenile"
    row.nascimento = "2014"
    assert idade_do_paciente(row) == "11–12 anos (estimada pelo ano)"
    assert low_weight_age_context(idade_do_paciente(row)) == "adult"


def test_source_switch_keeps_both_inputs_and_anchor():
    row = patient(nascimento="2020-05-03", idade_fonte="idade", idade_informada="12 anos", idade_referencia=date(2026, 11, 3))
    changes = alteracoes_idade(row, {"data_nascimento": "2020-05-03", "idade_informada": "12 anos", "idade_referencia": "2026-11-03", "idade_fonte": "nascimento"})
    assert changes == {"idade_fonte": "nascimento"}
    row.__dict__.update(changes)
    assert idade_do_paciente(row) == "6a 6m"


def test_unrelated_save_never_reanchors():
    row = patient(idade_fonte="idade", idade_informada="12 anos", idade_referencia=date(2025, 11, 3))
    assert alteracoes_idade(row, {"nome": "Sintético"}) == {}
    assert alteracoes_idade(row, {"idade_informada": "12 anos", "idade_referencia": "2025-11-03", "idade_fonte": "idade", "data_nascimento": None}) == {}
    changes = alteracoes_idade(row, {"idade_informada": "12 anos", "idade_referencia": "2026-11-04", "idade_fonte": "idade"})
    assert changes == {"idade_referencia": date(2026, 11, 4)}


def test_legacy_kept_until_explicit_edit_and_clear():
    row = patient(observacoes="Nota\nIdade: 12 anos")
    assert idade_do_paciente(row) == "12 anos"
    assert alteracoes_idade(row, {"idade_informada": None, "idade_fonte": None, "data_nascimento": None}) == {}
    row.__dict__.update(alteracoes_idade(row, {"idade_informada": None, "idade_fonte": "idade"}))
    assert idade_do_paciente(row) == ""
    assert row.observacoes == "Nota"


@pytest.mark.parametrize("payload", [
    {"idade":"-1 ano"}, {"idade":"adulto"}, {"idade":"1 ano ou 5 meses"}, {"idade":"1a 2a"},
    {"data_nascimento":"2027"}, {"data_nascimento":"2026-11-05"}, {"data_nascimento":"2026-02-30"},
    {"idade":"1 ano", "idade_referencia":"2027-01-01"}, {"idade_fonte":"inventada"},
])
def test_invalid_inputs(payload):
    with pytest.raises(HTTPException) as exc:
        alteracoes_idade(patient(), payload)
    assert exc.value.status_code == 422


def test_migration_additive_idempotent_no_backfill():
    file = Path(__file__).parents[1] / "migrations/versions/20261104_106_paciente_idade_fonte.py"
    spec = importlib.util.spec_from_file_location("age_migration", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE pacientes (id INTEGER, nascimento TEXT, observacoes TEXT)"))
        connection.execute(text("INSERT INTO pacientes VALUES (1, '2026-11-03', 'Idade: 12 anos')"))
        module.upgrade(connection, "sqlite")
        module.upgrade(connection, "sqlite")
        assert len(inspect(connection).get_columns("pacientes")) == 6
        assert connection.execute(text("SELECT * FROM pacientes")).one() == (1, "2026-11-03", "Idade: 12 anos", None, None, None)


def test_reference_handles_utc_midnight_without_changing_civil_exam_dates():
    from datetime import datetime, timezone
    from app.utils.paciente_idade import referencia_documento
    instant = datetime(2026, 11, 5, 1, 15, tzinfo=timezone.utc)
    assert referencia_documento(None, date(2018, 8, 15)) == date(2018, 8, 15)
    assert referencia_documento(None, datetime(2018, 8, 15)) == date(2018, 8, 15)
    assert referencia_documento(None, instant) == date(2026, 11, 4)
    assert referencia_documento(None, instant.replace(tzinfo=None)) == date(2026, 11, 4)
    assert referencia_documento("2026-11-04T00:00:00Z") == date(2026, 11, 4)


def test_estimate_carries_declared_days_and_does_not_age_before_origin():
    row = patient(idade_fonte="idade", idade_informada="1 mês 29 dias", idade_referencia=date(2026, 10, 1))
    assert idade_do_paciente(row, data_referencia="2026-10-03") == "2m (estimada)"
    assert idade_do_paciente(row, data_referencia="2026-08-01") == ""


def test_clearing_last_source_does_not_revive_obsolete_legacy_age():
    row = patient(nascimento="2014", idade_fonte="nascimento", observacoes="Nota clínica\nIdade: 1a")
    row.__dict__.update(alteracoes_idade(row, {"data_nascimento": None}))
    assert idade_do_paciente(row) == ""
    assert row.observacoes == "Nota clínica"


def test_unrelated_full_save_preserves_legacy_birth_without_guessing_source():
    row = patient(nascimento="nascimento desconhecido", observacoes="Nota clínica")
    assert alteracoes_idade(row, {"data_nascimento": row.nascimento, "idade_informada": None, "idade_fonte": None}) == {}
    with pytest.raises(HTTPException):
        alteracoes_idade(row, {"data_nascimento": row.nascimento, "idade_fonte": "nascimento"})
