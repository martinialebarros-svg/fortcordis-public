"""Consultas de schema da agenda reutilizam a conexao da transacao atual."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "agenda-connection-pool-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AtendimentoClinico


class AgendaConnectionPoolTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            poolclass=QueuePool,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.05,
        )
        self.addCleanup(self.engine.dispose)

    def test_bloqueios_sem_tabela_reutilizam_conexao_e_cache_da_sessao(self):
        with Session(self.engine) as db:
            db.execute(text("SELECT 1"))
            with patch.object(agenda, "inspect", wraps=agenda.inspect) as schema_inspect:
                self.assertEqual(agenda._listar_bloqueios_ativos(db), [])
                self.assertEqual(agenda._listar_bloqueios_ativos(db), [])
            self.assertEqual(schema_inspect.call_count, 1)
            self.assertEqual(self.engine.pool.checkedout(), 1)

    def test_bloqueios_ativos_preservam_transacao_sem_conexao_extra(self):
        AgendaBloqueio.__table__.create(self.engine)
        inicio = datetime(2099, 5, 25, 9, 0)
        with Session(self.engine) as db:
            for identificador, ativo in (("ativo", True), ("inativo", False)):
                db.add(AgendaBloqueio(
                    id=identificador,
                    inicio=inicio,
                    fim=inicio + timedelta(hours=1),
                    motivo="Bloqueio sintetico",
                    ativo=ativo,
                    criado_por_id=1,
                ))
            db.flush()

            bloqueios = agenda._listar_bloqueios_ativos(db)

            self.assertEqual([item.id for item in bloqueios], ["ativo"])
            self.assertEqual(self.engine.pool.checkedout(), 1)
            db.rollback()
            self.assertEqual(db.query(AgendaBloqueio).count(), 0)

    def test_transicoes_vinculadas_preservam_bloqueio_clinico_com_pool_ocupado(self):
        Agendamento.__table__.create(self.engine)
        AtendimentoClinico.__table__.create(self.engine)
        usuario = SimpleNamespace(id=1, nome="Teste", tem_papel=lambda _: False)
        for anterior, novo in (("Confirmado", "Realizado"), ("Realizado", "Em atendimento")):
            with self.subTest(anterior=anterior, novo=novo), Session(self.engine) as db:
                agendamento = Agendamento(inicio=datetime(2099, 5, 25, 9, 0), status=anterior)
                db.add(agendamento)
                db.flush()
                db.add(AtendimentoClinico(
                    agendamento_id=agendamento.id,
                    paciente_id=1,
                    veterinario_id=1,
                ))
                db.flush()

                with self.assertRaises(HTTPException) as erro:
                    agenda.atualizar_status(
                        agendamento.id,
                        request=None,
                        status=novo,
                        db=db,
                        current_user=usuario,
                    )

                self.assertEqual(erro.exception.status_code, 409)
                self.assertIn("possui o Atendimento", erro.exception.detail)
                self.assertEqual(agendamento.status, anterior)
                self.assertEqual(self.engine.pool.checkedout(), 1)
                db.rollback()
                self.assertEqual(db.query(Agendamento).count(), 0)
                self.assertEqual(db.query(AtendimentoClinico).count(), 0)


if __name__ == "__main__":
    unittest.main()
