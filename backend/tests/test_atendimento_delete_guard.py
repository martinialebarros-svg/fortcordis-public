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
os.environ.setdefault("SECRET_KEY", "atendimento-delete-guard-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.api.v1.endpoints import ordens_servico as ordens_servico_module
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import (
    AnexoAtendimento,
    AtendimentoClinico,
    DocumentoAtendimento,
    EvolucaoClinica,
    PrescricaoClinica,
    PrescricaoItem,
    PrescricaoItemAjuste,
)
from app.models.clinica import Clinica
from app.models.financeiro import CreditoFinanceiro, OrdemServicoPagamento, Transacao
from app.models.laudo import Exame
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tabela_preco import PrecoServico, PrecoServicoClinica
from app.models.tutor import Tutor


class AtendimentoDeleteGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-delete-guard.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
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
            OrdemServicoPagamento.__table__,
            Transacao.__table__,
            CreditoFinanceiro.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            PrescricaoClinica.__table__,
            PrescricaoItem.__table__,
            PrescricaoItemAjuste.__table__,
            EvolucaoClinica.__table__,
            DocumentoAtendimento.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=17, nome="Dra. Teste", email="teste@example.com")
        self.request = Request(
            {
                "type": "http",
                "method": "DELETE",
                "path": "/api/v1/atendimentos/1",
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

    def _seed_vinculado(self, *, atendimento_status: str = "Concluido", agenda_status: str = "Realizado"):
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Paciente Teste", especie="Canina", tutor_id=None, ativo=1)
        clinica = Clinica(nome="Clinica Teste", tabela_preco_id=1)
        servico = Servico(
            nome="Consulta",
            preco=Decimal("150.00"),
            preco_fortaleza_comercial=Decimal("150.00"),
            preco_fortaleza_plantao=Decimal("220.00"),
        )
        self.db.add_all([tutor, paciente, clinica, servico])
        self.db.flush()
        paciente.tutor_id = tutor.id

        agendamento = Agendamento(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            servico_id=servico.id,
            origem_atendimento="clinica_parceira",
            inicio=datetime(2026, 7, 29, 14, 30),
            status=agenda_status,
        )
        self.db.add(agendamento)
        self.db.flush()

        ordem_servico = OrdemServico(
            numero_os="OS-0001",
            agendamento_id=agendamento.id,
            paciente_id=paciente.id,
            clinica_id=clinica.id,
            servico_id=servico.id,
            data_atendimento=agendamento.inicio,
            tipo_horario="comercial",
            valor_servico=Decimal("150.00"),
            desconto=Decimal("0.00"),
            valor_final=Decimal("150.00"),
            status="Pendente",
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(ordem_servico)

        registro = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            agendamento_id=agendamento.id,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=agendamento.inicio,
            status=atendimento_status,
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(registro)
        self.db.commit()
        return registro, agendamento, ordem_servico

    def _seed_avulso(self, *, atendimento_status: str = "Concluido"):
        tutor = Tutor(nome="Tutora Avulsa", ativo=1)
        paciente = Paciente(nome="Paciente Avulso", especie="Felina", tutor_id=None, ativo=1)
        clinica = Clinica(nome="Clinica Teste", tabela_preco_id=1)
        self.db.add_all([tutor, paciente, clinica])
        self.db.flush()
        paciente.tutor_id = tutor.id

        registro = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            agendamento_id=None,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=datetime(2026, 7, 29, 14, 30),
            status=atendimento_status,
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(registro)
        self.db.commit()
        return registro

    def test_delete_concluido_sem_confirmacao_retorna_409_e_nao_apaga(self) -> None:
        registro, agendamento, ordem_servico = self._seed_vinculado()

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            with self.assertRaises(HTTPException) as ctx:
                atendimento.excluir_atendimento(
                    registro.id,
                    self.request,
                    confirmar_exclusao=False,
                    db=self.db,
                    current_user=self.user,
                )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["codigo"], "CONFIRMACAO_EXCLUSAO_ATENDIMENTO_CONCLUIDO")
        self.assertTrue(ctx.exception.detail["confirmavel"])
        auditoria_mock.assert_not_called()

        self.assertIsNotNone(
            self.db.query(AtendimentoClinico).filter_by(id=registro.id).first()
        )
        self.db.refresh(agendamento)
        self.db.refresh(ordem_servico)
        self.assertEqual(agendamento.status, "Realizado")
        self.assertEqual(ordem_servico.status, "Pendente")

    def test_delete_concluido_com_confirmacao_reverte_agenda_cancela_os_e_audita(self) -> None:
        registro, agendamento, ordem_servico = self._seed_vinculado()
        registro_id, agendamento_id, ordem_servico_id = registro.id, agendamento.id, ordem_servico.id

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            resposta = atendimento.excluir_atendimento(
                registro_id,
                self.request,
                confirmar_exclusao=True,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["id"], registro_id)
        self.assertIsNone(self.db.query(AtendimentoClinico).filter_by(id=registro_id).first())

        agendamento_pos = self.db.query(Agendamento).filter_by(id=agendamento_id).one()
        ordem_pos = self.db.query(OrdemServico).filter_by(id=ordem_servico_id).one()
        self.assertEqual(agendamento_pos.status, "Confirmado")
        self.assertEqual(ordem_pos.status, "Cancelado")

        acoes_registradas = [chamada.kwargs["acao"] for chamada in auditoria_mock.call_args_list]
        self.assertIn("ATENDIMENTO_EXCLUIDO", acoes_registradas)
        self.assertIn("AGENDAMENTO_REVERTIDO_POR_EXCLUSAO_ATENDIMENTO", acoes_registradas)

    def test_delete_atendimento_avulso_com_confirmacao_nao_tenta_reverter_nada(self) -> None:
        registro = self._seed_avulso()
        registro_id = registro.id

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            resposta = atendimento.excluir_atendimento(
                registro_id,
                self.request,
                confirmar_exclusao=True,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["id"], registro_id)
        self.assertIsNone(self.db.query(AtendimentoClinico).filter_by(id=registro_id).first())
        acoes_registradas = [chamada.kwargs["acao"] for chamada in auditoria_mock.call_args_list]
        self.assertEqual(acoes_registradas, ["ATENDIMENTO_EXCLUIDO"])

    def test_delete_nao_concluido_nao_exige_confirmacao(self) -> None:
        registro = self._seed_avulso(atendimento_status="Em atendimento")
        registro_id = registro.id

        with patch.object(atendimento, "registrar_auditoria"):
            resposta = atendimento.excluir_atendimento(
                registro_id,
                self.request,
                confirmar_exclusao=False,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["id"], registro_id)
        self.assertIsNone(self.db.query(AtendimentoClinico).filter_by(id=registro_id).first())

    def test_delete_limpa_evolucao_e_ajustes_orfaos(self) -> None:
        registro = self._seed_avulso(atendimento_status="Em atendimento")
        registro_id = registro.id
        self.db.add(
            EvolucaoClinica(
                atendimento_id=registro_id,
                descricao="Evolucao registrada durante o atendimento.",
                responsavel_id=self.user.id,
                responsavel_nome=self.user.nome,
            )
        )
        self.db.add(
            PrescricaoItemAjuste(
                prescricao_item_id=1,
                atendimento_id=registro_id,
                campo="dose",
                valor_anterior="10mg",
                valor_novo="20mg",
                responsavel_id=self.user.id,
                responsavel_nome=self.user.nome,
            )
        )
        self.db.commit()

        with patch.object(atendimento, "registrar_auditoria"):
            atendimento.excluir_atendimento(
                registro_id,
                self.request,
                confirmar_exclusao=False,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(
            self.db.query(EvolucaoClinica).filter_by(atendimento_id=registro_id).count(), 0
        )
        self.assertEqual(
            self.db.query(PrescricaoItemAjuste).filter_by(atendimento_id=registro_id).count(), 0
        )

    def test_delete_nao_concluido_com_exame_liberado_portal_exige_confirmacao(self) -> None:
        # Um exame pode estar liberado no portal parceiro mesmo com o atendimento
        # ainda "Em atendimento" - excluir o atendimento inteiro nao pode ser um
        # atalho para apagar esse PDF sem a mesma confirmacao que excluir_anexo
        # ja exige para o mesmo cenario.
        registro = self._seed_avulso(atendimento_status="Em atendimento")
        registro_id = registro.id
        exame = Exame(
            atendimento_id=registro_id,
            paciente_id=registro.paciente_id,
            tipo_exame="Ecocardiograma",
            status="Liberado no portal",
        )
        self.db.add(exame)
        self.db.commit()

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            with self.assertRaises(HTTPException) as ctx:
                atendimento.excluir_atendimento(
                    registro_id,
                    self.request,
                    confirmar_exclusao=False,
                    db=self.db,
                    current_user=self.user,
                )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["codigo"], "CONFIRMACAO_EXCLUSAO_ATENDIMENTO_CONCLUIDO")
        self.assertTrue(ctx.exception.detail["confirmavel"])
        auditoria_mock.assert_not_called()
        self.assertIsNotNone(self.db.query(AtendimentoClinico).filter_by(id=registro_id).first())
        self.assertIsNotNone(self.db.query(Exame).filter_by(id=exame.id).first())

        with patch.object(atendimento, "registrar_auditoria"):
            resposta = atendimento.excluir_atendimento(
                registro_id,
                self.request,
                confirmar_exclusao=True,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["id"], registro_id)
        self.assertIsNone(self.db.query(AtendimentoClinico).filter_by(id=registro_id).first())
        self.assertIsNone(self.db.query(Exame).filter_by(id=exame.id).first())

    def test_delete_concluido_com_os_paga_desfaz_recebimento_antes_de_cancelar(self) -> None:
        registro, agendamento, ordem_servico = self._seed_vinculado()
        ordem_servico.status = "Pago"
        self.db.commit()

        transacao = Transacao(
            tipo="entrada",
            categoria="Servico",
            valor=150.0,
            valor_final=150.0,
            status="Pago",
            data_pagamento=datetime(2026, 7, 29, 15, 0),
            descricao=f"Recebimento da OS {ordem_servico.numero_os}",
            observacoes=f"OS_ID={ordem_servico.id};TIPO=RECEBIMENTO_OS",
        )
        self.db.add(transacao)
        self.db.commit()
        transacao_id = transacao.id

        with patch.object(atendimento, "registrar_auditoria"), patch.object(
            ordens_servico_module, "registrar_auditoria"
        ):
            resposta = atendimento.excluir_atendimento(
                registro.id,
                self.request,
                confirmar_exclusao=True,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["id"], registro.id)
        self.db.refresh(ordem_servico)
        self.assertEqual(ordem_servico.status, "Cancelado")

        transacao_atualizada = self.db.query(Transacao).filter_by(id=transacao_id).first()
        self.assertEqual(transacao_atualizada.status, "Cancelado")
        self.assertIsNone(transacao_atualizada.data_pagamento)

    def test_delete_recarrega_os_recebida_em_outra_sessao_antes_de_cancelar(self) -> None:
        registro, _, ordem = self._seed_vinculado()
        registro_id, ordem_id = registro.id, ordem.id
        self.assertEqual(ordem.status, "Pendente")
        with sessionmaker(bind=self.engine)() as concorrente:
            concorrente.get(OrdemServico, ordem_id).status = "Pago"
            concorrente.add(Transacao(
                tipo="entrada", categoria="Servico", valor=150, valor_final=150,
                status="Recebido", observacoes=f"OS_ID={ordem_id};TIPO=RECEBIMENTO_OS",
            ))
            concorrente.commit()
        # O objeto carregado na sessao da exclusao ainda esta desatualizado.
        self.assertEqual(ordem.status, "Pendente")
        with patch.object(atendimento, "registrar_auditoria"), patch.object(ordens_servico_module, "registrar_auditoria"):
            atendimento.excluir_atendimento(
                registro_id, self.request, confirmar_exclusao=True, db=self.db, current_user=self.user,
            )
        self.assertEqual(self.db.get(OrdemServico, ordem_id).status, "Cancelado")
        self.assertEqual(self.db.query(Transacao).one().status, "Cancelado")

    def test_delete_nao_cancela_os_recebida_novamente_apos_desfazer(self) -> None:
        registro, _, ordem = self._seed_vinculado()
        registro_id, ordem_id = registro.id, ordem.id
        ordem.status = "Pago"
        self.db.add(Transacao(
            tipo="entrada", categoria="Servico", valor=150, valor_final=150,
            status="Recebido", observacoes=f"OS_ID={ordem_id};TIPO=RECEBIMENTO_OS",
        ))
        self.db.commit()
        desfazer_original = atendimento.desfazer_recebimento_ordem

        def desfazer_e_receber_novamente(**kwargs):
            result = desfazer_original(**kwargs)
            with sessionmaker(bind=self.engine)() as concorrente:
                concorrente.get(OrdemServico, ordem_id).status = "Pago"
                concorrente.add(Transacao(
                    tipo="entrada", categoria="Servico", valor=150, valor_final=150,
                    status="Recebido", observacoes=f"OS_ID={ordem_id};TIPO=RECEBIMENTO_OS;ITEM=2",
                ))
                concorrente.commit()
            return result

        with (
            patch.object(atendimento, "registrar_auditoria"),
            patch.object(ordens_servico_module, "registrar_auditoria"),
            patch.object(atendimento, "desfazer_recebimento_ordem", side_effect=desfazer_e_receber_novamente),
        ):
            with self.assertRaises(HTTPException) as raised:
                atendimento.excluir_atendimento(
                    registro_id, self.request, confirmar_exclusao=True, db=self.db, current_user=self.user,
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.db.rollback()
        self.assertIsNotNone(self.db.get(AtendimentoClinico, registro_id))
        self.assertEqual(self.db.get(OrdemServico, ordem_id).status, "Pago")
        self.assertEqual(self.db.query(Transacao).filter_by(status="Recebido").count(), 1)
        self.assertEqual(self.db.query(Transacao).filter_by(status="Cancelado").count(), 1)


if __name__ == "__main__":
    unittest.main()
