import os
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-finalization-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda, atendimento
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tabela_preco import PrecoServico, PrecoServicoClinica
from app.models.tutor import Tutor
from app.schemas.atendimento import (
    AtendimentoCreatePayload,
    AtendimentoFinalizarPayload,
    AtendimentoUpdatePayload,
    TriagemPayload,
)


class AtendimentoTransactionalFinalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-finalization.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            PrecoServico.__table__,
            PrecoServicoClinica.__table__,
            Agendamento.__table__,
            AtendimentoClinico.__table__,
            OrdemServico.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=17, nome="Dra. Teste", email="teste@example.com")
        self.request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/atendimentos/1/finalizar",
                "headers": [],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _seed_linked(
        self,
        *,
        agenda_status: str = "Em atendimento",
        atendimento_status: str = "Em atendimento",
        paciente_agenda_diferente: bool = False,
    ):
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Paciente Teste", especie="Canina", tutor_id=None, ativo=1)
        outro_paciente = Paciente(nome="Outro Paciente", especie="Felina", tutor_id=None, ativo=1)
        clinica = Clinica(nome="Clinica Teste", tabela_preco_id=1)
        servico = Servico(
            nome="Consulta",
            preco=Decimal("150.00"),
            preco_fortaleza_comercial=Decimal("150.00"),
            preco_fortaleza_plantao=Decimal("220.00"),
        )
        self.db.add_all([tutor, paciente, outro_paciente, clinica, servico])
        self.db.flush()
        paciente.tutor_id = tutor.id
        outro_paciente.tutor_id = tutor.id
        agendamento = Agendamento(
            paciente_id=outro_paciente.id if paciente_agenda_diferente else paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            servico_id=servico.id,
            origem_atendimento="clinica_parceira",
            inicio=datetime(2026, 7, 29, 14, 30),
            status=agenda_status,
        )
        self.db.add(agendamento)
        self.db.flush()
        registro = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            agendamento_id=agendamento.id,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=agendamento.inicio,
            status=atendimento_status,
            queixa_principal="Retorno para reavaliacao.",
            exame_fisico="Paciente estavel ao exame.",
            diagnostico_principal="Evolucao favoravel.",
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(registro)
        self.db.commit()
        return registro, agendamento, paciente, clinica, servico

    def _finalizar(
        self,
        atendimento_id: int,
        tipo_horario: str = "comercial",
        *,
        confirmar_conclusao_pendencias: bool = False,
    ):
        with (
            patch.object(atendimento, "_emitir_efeitos_finalizacao"),
            patch.object(
                atendimento,
                "_montar_detalhe_atendimento",
                side_effect=lambda _db, item: {
                    "id": item.id,
                    "status": item.status,
                    "consulta_concluida": item.consulta_concluida,
                },
            ),
        ):
            return atendimento.finalizar_atendimento(
                atendimento_id,
                AtendimentoFinalizarPayload(
                    tipo_horario=tipo_horario,
                    confirmar_conclusao_pendencias=confirmar_conclusao_pendencias,
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )

    def test_finalizacao_vinculada_persiste_atendimento_agenda_e_os(self) -> None:
        registro, agendamento, *_ = self._seed_linked()

        with patch.object(self.db, "commit", wraps=self.db.commit) as commit_spy:
            resposta = self._finalizar(registro.id)

        self.assertEqual(commit_spy.call_count, 1)
        self.db.refresh(registro)
        self.db.refresh(agendamento)
        ordem = self.db.query(OrdemServico).filter_by(agendamento_id=agendamento.id).one()
        self.assertEqual(registro.status, "Concluido")
        self.assertEqual(registro.consulta_concluida, 1)
        self.assertEqual(agendamento.status, "Realizado")
        self.assertEqual(ordem.tipo_horario, "comercial")
        self.assertEqual(ordem.valor_final, Decimal("150.00"))
        self.assertEqual(resposta["ordem_servico"]["id"], ordem.id)
        self.assertFalse(resposta["ordem_servico"]["reutilizada"])

    def test_prontuario_incompleto_exige_confirmacao_nao_altera_agenda_nem_cria_os(self) -> None:
        registro, agendamento, *_ = self._seed_linked()
        registro.queixa_principal = ""
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            self._finalizar(registro.id)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["codigo"], "CONFIRMACAO_CONCLUSAO_PENDENCIAS")
        self.db.refresh(registro)
        self.db.refresh(agendamento)
        self.assertEqual(registro.status, "Em atendimento")
        self.assertEqual(agendamento.status, "Em atendimento")
        self.assertEqual(self.db.query(OrdemServico).count(), 0)

    def test_prontuario_incompleto_com_confirmacao_finaliza_e_audita(self) -> None:
        registro, agendamento, *_ = self._seed_linked()
        registro.queixa_principal = ""
        self.db.commit()

        with patch.object(atendimento, "_auditar_conclusao_com_pendencias") as auditoria_mock:
            self._finalizar(registro.id, confirmar_conclusao_pendencias=True)

        self.db.refresh(registro)
        self.assertEqual(registro.status, "Concluido")
        self.assertEqual(auditoria_mock.call_count, 1)
        self.assertIn("queixa principal", "; ".join(auditoria_mock.call_args.kwargs["pendencias"]))

    def test_falha_de_preco_faz_rollback_dos_tres_recursos(self) -> None:
        registro, agendamento, *_ = self._seed_linked()

        with patch.object(atendimento, "calcular_preco_servico", return_value=Decimal("0.00")):
            with self.assertRaises(HTTPException) as ctx:
                self._finalizar(registro.id)

        self.assertEqual(ctx.exception.status_code, 422)
        self.db.refresh(registro)
        self.db.refresh(agendamento)
        self.assertEqual(registro.status, "Em atendimento")
        self.assertEqual(agendamento.status, "Em atendimento")
        self.assertEqual(self.db.query(OrdemServico).count(), 0)

    def test_repeticao_reutiliza_a_mesma_os(self) -> None:
        registro, agendamento, *_ = self._seed_linked()

        primeira = self._finalizar(registro.id)
        ordem = self.db.query(OrdemServico).filter_by(agendamento_id=agendamento.id).one()
        ordem.valor_servico = Decimal("125.00")
        ordem.valor_final = Decimal("125.00")
        self.db.commit()
        segunda = self._finalizar(registro.id)

        self.assertEqual(self.db.query(OrdemServico).count(), 1)
        self.assertEqual(
            primeira["ordem_servico"]["id"],
            segunda["ordem_servico"]["id"],
        )
        self.assertTrue(segunda["ordem_servico"]["reutilizada"])
        self.db.refresh(ordem)
        self.assertEqual(ordem.valor_final, Decimal("125.00"))
        self.assertEqual(segunda["ordem_servico"]["valor_final"], 125.0)
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Realizado")

    def test_os_cancelada_nao_impede_nova_os_ativa(self) -> None:
        registro, agendamento, paciente, clinica, servico = self._seed_linked()
        cancelada = OrdemServico(
            numero_os="OS2026079999",
            agendamento_id=agendamento.id,
            paciente_id=paciente.id,
            clinica_id=clinica.id,
            servico_id=servico.id,
            valor_servico=Decimal("120.00"),
            valor_final=Decimal("120.00"),
            status="Cancelado",
        )
        self.db.add(cancelada)
        self.db.commit()

        resposta = self._finalizar(registro.id)

        self.assertFalse(resposta["ordem_servico"]["reutilizada"])
        self.assertEqual(self.db.query(OrdemServico).count(), 2)
        self.assertEqual(
            self.db.query(OrdemServico).filter(OrdemServico.status != "Cancelado").count(),
            1,
        )

    def test_agenda_terminal_preserva_atendimento_aberto(self) -> None:
        registro, agendamento, *_ = self._seed_linked(agenda_status="Cancelado")

        with self.assertRaises(HTTPException) as ctx:
            self._finalizar(registro.id)

        self.assertEqual(ctx.exception.status_code, 409)
        self.db.refresh(registro)
        self.db.refresh(agendamento)
        self.assertEqual(registro.status, "Em atendimento")
        self.assertEqual(agendamento.status, "Cancelado")
        self.assertEqual(self.db.query(OrdemServico).count(), 0)

    def test_paciente_incompativel_preserva_estado(self) -> None:
        registro, agendamento, *_ = self._seed_linked(paciente_agenda_diferente=True)

        with self.assertRaises(HTTPException) as ctx:
            self._finalizar(registro.id)

        self.assertEqual(ctx.exception.status_code, 409)
        self.db.refresh(registro)
        self.db.refresh(agendamento)
        self.assertEqual(registro.status, "Em atendimento")
        self.assertEqual(agendamento.status, "Em atendimento")

    def test_finalizacao_sem_agenda_conclui_apenas_atendimento(self) -> None:
        registro, _agendamento, *_ = self._seed_linked()
        registro.agendamento_id = None
        self.db.commit()

        resposta = self._finalizar(registro.id, "plantao")

        self.db.refresh(registro)
        self.assertEqual(registro.status, "Concluido")
        self.assertEqual(resposta["agenda"], None)
        self.assertEqual(resposta["ordem_servico"], None)

    def test_segunda_criacao_para_mesmo_agendamento_retorna_409(self) -> None:
        registro, agendamento, paciente, clinica, _servico = self._seed_linked()
        payload = AtendimentoCreatePayload(
            paciente_id=paciente.id,
            clinica_id=clinica.id,
            agendamento_id=agendamento.id,
            status="Em atendimento",
            triagem=TriagemPayload(),
        )

        with self.assertRaises(HTTPException) as ctx:
            atendimento.criar_atendimento(payload, db=self.db, current_user=self.user)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn(f"#{registro.id}", str(ctx.exception.detail))
        self.assertEqual(
            self.db.query(AtendimentoClinico).filter_by(agendamento_id=agendamento.id).count(),
            1,
        )

    def test_agenda_legada_bloqueia_realizado_quando_ha_atendimento(self) -> None:
        registro, agendamento, *_ = self._seed_linked()

        with (
            patch.object(agenda, "_adquirir_lock_escrita_agenda"),
            patch.object(agenda, "_expirar_reservas_vencidas"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                agenda.atualizar_status(
                    agendamento.id,
                    self.request,
                    "Realizado",
                    db=self.db,
                    current_user=self.user,
                )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn(f"Atendimento #{registro.id}", str(ctx.exception.detail))
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Em atendimento")

    def test_reabertura_isolada_do_atendimento_vinculado_e_bloqueada(self) -> None:
        registro, agendamento, *_ = self._seed_linked(
            agenda_status="Realizado",
            atendimento_status="Concluido",
        )

        with self.assertRaises(HTTPException) as ctx:
            atendimento.atualizar_atendimento(
                registro.id,
                AtendimentoUpdatePayload(status="Em atendimento"),
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.db.refresh(registro)
        self.db.refresh(agendamento)
        self.assertEqual(registro.status, "Concluido")
        self.assertEqual(agendamento.status, "Realizado")

    def test_agenda_legada_bloqueia_desfazer_realizado_com_atendimento(self) -> None:
        registro, agendamento, *_ = self._seed_linked(
            agenda_status="Realizado",
            atendimento_status="Concluido",
        )

        with (
            patch.object(agenda, "_adquirir_lock_escrita_agenda"),
            patch.object(agenda, "_expirar_reservas_vencidas"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                agenda.atualizar_status(
                    agendamento.id,
                    self.request,
                    "Em atendimento",
                    db=self.db,
                    current_user=self.user,
                )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn(f"Atendimento #{registro.id}", str(ctx.exception.detail))
        self.db.refresh(agendamento)
        self.assertEqual(agendamento.status, "Realizado")


if __name__ == "__main__":
    unittest.main()
