import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-relacionados-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.laudo import Laudo
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.tutor import Tutor


class AgendaRelacionadosVisiveisTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-relacionados.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Agendamento.__table__,
            Laudo.__table__,
            OrdemServico.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_data(self, db):
        tutor_visivel = Tutor(
            nome="Tutor visivel",
            endereco="Rua A",
            numero="10",
            cidade="Fortaleza",
            estado="CE",
            latitude=-3.7,
            longitude=-38.5,
            ativo=1,
        )
        tutor_fora = Tutor(nome="Tutor fora", endereco="Rua B", ativo=1)
        clinica_visivel = Clinica(nome="Clinica visivel", endereco="Av A", ativo=True)
        clinica_fora = Clinica(nome="Clinica fora", endereco="Av B", ativo=True)
        db.add_all([tutor_visivel, tutor_fora, clinica_visivel, clinica_fora])
        db.flush()

        paciente_visivel = Paciente(nome="Luna", tutor_id=tutor_visivel.id, ativo=1)
        paciente_fora = Paciente(nome="Thor", tutor_id=tutor_fora.id, ativo=1)
        db.add_all([paciente_visivel, paciente_fora])
        db.flush()

        agendamento_visivel = Agendamento(
            paciente_id=paciente_visivel.id,
            clinica_id=clinica_visivel.id,
            data="2026-08-30",
            hora="09:00",
            inicio=datetime(2026, 8, 30, 9, 0),
            status="Realizado",
        )
        agendamento_fora = Agendamento(
            paciente_id=paciente_fora.id,
            clinica_id=clinica_fora.id,
            data="2026-08-30",
            hora="10:00",
            inicio=datetime(2026, 8, 30, 10, 0),
            status="Realizado",
        )
        db.add_all([agendamento_visivel, agendamento_fora])
        db.flush()

        db.add_all(
            [
                Laudo(
                    paciente_id=paciente_visivel.id,
                    agendamento_id=agendamento_visivel.id,
                    veterinario_id=1,
                    tipo="ecocardiograma",
                    titulo="Laudo antigo",
                    status="Rascunho",
                ),
                Laudo(
                    paciente_id=paciente_visivel.id,
                    agendamento_id=agendamento_visivel.id,
                    veterinario_id=1,
                    tipo="ecocardiograma",
                    titulo="Laudo atual",
                    status="Finalizado",
                ),
                Laudo(
                    paciente_id=paciente_fora.id,
                    agendamento_id=agendamento_fora.id,
                    veterinario_id=1,
                    tipo="ecocardiograma",
                    titulo="Laudo fora",
                    status="Finalizado",
                ),
                OrdemServico(
                    numero_os="OS-VISIVEL-ANTIGA",
                    agendamento_id=agendamento_visivel.id,
                    paciente_id=paciente_visivel.id,
                    clinica_id=clinica_visivel.id,
                    servico_id=1,
                    status="Cancelado",
                    valor_final=100,
                ),
                OrdemServico(
                    numero_os="OS-VISIVEL-ATUAL",
                    agendamento_id=agendamento_visivel.id,
                    paciente_id=paciente_visivel.id,
                    clinica_id=clinica_visivel.id,
                    servico_id=1,
                    status="Pago",
                    valor_final=120,
                ),
                OrdemServico(
                    numero_os="OS-FORA",
                    agendamento_id=agendamento_fora.id,
                    paciente_id=paciente_fora.id,
                    clinica_id=clinica_fora.id,
                    servico_id=1,
                    status="Pago",
                    valor_final=200,
                ),
            ]
        )
        db.commit()
        return agendamento_visivel, agendamento_fora, tutor_visivel, clinica_visivel

    def test_parser_deduplica_e_valida_limite(self) -> None:
        self.assertEqual(agenda._parse_agendamento_ids_param("3, 2,3,1"), [3, 2, 1])

        with self.assertRaises(HTTPException) as invalid_context:
            agenda._parse_agendamento_ids_param("1,invalido")
        self.assertEqual(invalid_context.exception.status_code, 400)

        with self.assertRaises(HTTPException) as limit_context:
            agenda._parse_agendamento_ids_param(",".join(str(value) for value in range(1, 102)))
        self.assertEqual(limit_context.exception.status_code, 400)

    def test_retorna_somente_relacionados_do_lote_e_mais_recentes(self) -> None:
        tmpdir, db, engine = self._build_session()
        statements = []

        def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement.lower())

        try:
            visivel, fora, tutor, clinica = self._seed_data(db)
            visivel_id = visivel.id
            fora_id = fora.id
            tutor_id = tutor.id
            clinica_id = clinica.id
            event.listen(engine, "before_cursor_execute", _capture_sql)
            resultado = agenda.listar_relacionados_agenda(
                agendamento_ids=f"{visivel_id},999999",
                db=db,
                current_user=SimpleNamespace(id=1),
            )
            event.remove(engine, "before_cursor_execute", _capture_sql)

            self.assertEqual(resultado["agendamento_ids"], [visivel_id])
            self.assertEqual([item["titulo"] for item in resultado["laudos"]], ["Laudo atual"])
            self.assertEqual(
                [item["numero_os"] for item in resultado["ordens_servico"]],
                ["OS-VISIVEL-ATUAL"],
            )
            self.assertEqual([item["id"] for item in resultado["clinicas"]], [clinica_id])
            self.assertEqual([item["id"] for item in resultado["tutores"]], [tutor_id])
            self.assertNotIn(fora_id, resultado["agendamento_ids"])
            self.assertEqual(
                len(statements),
                5,
                msg="O endpoint deve manter cinco SELECTs por lote, sem consulta por agendamento.",
            )
        finally:
            if event.contains(engine, "before_cursor_execute", _capture_sql):
                event.remove(engine, "before_cursor_execute", _capture_sql)
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
