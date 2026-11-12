"""Guards do vinculo Atendimento/Agenda no `PUT /atendimentos/{id}`.

Cobre o defeito em que `{"agendamento_id": null}` zerava a referencia usada
pelos bloqueios da finalizacao transacional, permitindo concluir um prontuario
sem gerar OS e sem realizar a Agenda, e desvincular o prontuario como efeito
colateral do autosave.
"""
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

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-vinculo-guard-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.agendamento import Agendamento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.schemas.atendimento import AtendimentoUpdatePayload


class AtendimentoVinculoAgendamentoGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-vinculo-guard.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            Agendamento.__table__,
            AtendimentoClinico.__table__,
            AuditoriaEvento.__table__,
            OrdemServico.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=31, nome="Dra. Teste", email="teste@example.com")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _seed(
        self,
        *,
        agenda_status: str = "Em atendimento",
        atendimento_status: str = "Em atendimento",
        vincular: bool = True,
    ):
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Paciente Teste", especie="Canina", ativo=1)
        clinica = Clinica(nome="Clinica Teste", tabela_preco_id=1)
        servico = Servico(nome="Consulta", preco=Decimal("150.00"))
        self.db.add_all([tutor, paciente, clinica, servico])
        self.db.flush()
        paciente.tutor_id = tutor.id
        agendamento = Agendamento(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            servico_id=servico.id,
            origem_atendimento="clinica_parceira",
            inicio=datetime(2026, 7, 31, 14, 30),
            status=agenda_status,
        )
        self.db.add(agendamento)
        self.db.flush()
        registro = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            agendamento_id=agendamento.id if vincular else None,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=agendamento.inicio,
            status=atendimento_status,
            queixa_principal="Retorno para reavaliacao.",
            anamnese="Sem intercorrencias no periodo.",
            exame_fisico="Paciente estavel ao exame.",
            dados_clinicos="Parametros dentro da normalidade.",
            diagnostico_principal="Evolucao favoravel.",
            plano_terapeutico="Manter conduta atual.",
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(registro)
        self.db.commit()
        return registro, agendamento

    def _criar_agendamento_extra(self, registro: AtendimentoClinico, *, status: str = "Confirmado") -> Agendamento:
        """Segundo agendamento do mesmo paciente/clinica, ainda sem atendimento vinculado."""
        outro = Agendamento(
            paciente_id=registro.paciente_id,
            tutor_id=registro.tutor_id,
            clinica_id=registro.clinica_id,
            servico_id=self.db.query(Agendamento).filter(Agendamento.id == registro.agendamento_id).first().servico_id,
            origem_atendimento="clinica_parceira",
            inicio=datetime(2026, 8, 3, 9, 0),
            status=status,
        )
        self.db.add(outro)
        self.db.commit()
        self.db.refresh(outro)
        return outro

    def _atualizar(self, atendimento_id: int, payload: AtendimentoUpdatePayload):
        with (
            patch.object(atendimento, "_auditar_desvinculo_agendamento"),
            patch.object(
                atendimento,
                "_montar_detalhe_atendimento",
                side_effect=lambda _db, item: {
                    "id": item.id,
                    "status": item.status,
                    "agendamento_id": item.agendamento_id,
                },
            ),
        ):
            return atendimento.atualizar_atendimento(
                atendimento_id,
                payload,
                db=self.db,
                current_user=self.user,
            )

    # ---------------------------------------------------- evasao dos guards

    def test_concluir_com_agendamento_nulo_retorna_conflito_e_nao_altera_nada(self):
        """Cenario 5: `{"agendamento_id": null, "status": "Concluido"}` era a
        rota que concluia o prontuario sem OS e sem realizar a Agenda."""
        registro, agendamento = self._seed()

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(
                registro.id,
                AtendimentoUpdatePayload(agendamento_id=None, status="Concluido"),
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Finalizar atendimento", str(ctx.exception.detail))
        self.db.rollback()
        self.db.refresh(registro)
        self.db.refresh(agendamento)
        self.assertEqual(registro.status, "Em atendimento")
        self.assertEqual(registro.agendamento_id, agendamento.id)
        self.assertEqual(agendamento.status, "Em atendimento")
        self.assertEqual(self.db.query(OrdemServico).count(), 0)

    def test_reabrir_concluido_com_agendamento_nulo_retorna_conflito(self):
        """Cenario 6: o mesmo caminho reabria um prontuario concluido."""
        registro, agendamento = self._seed(
            agenda_status="Realizado",
            atendimento_status="Concluido",
        )

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(
                registro.id,
                AtendimentoUpdatePayload(agendamento_id=None, status="Em atendimento"),
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.db.rollback()
        self.db.refresh(registro)
        self.db.refresh(agendamento)
        self.assertEqual(registro.status, "Concluido")
        self.assertEqual(registro.agendamento_id, agendamento.id)
        self.assertEqual(agendamento.status, "Realizado")

    def test_desvincular_concluido_e_bloqueado_mesmo_com_confirmacao(self):
        registro, agendamento = self._seed(
            agenda_status="Realizado",
            atendimento_status="Concluido",
        )

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(
                registro.id,
                AtendimentoUpdatePayload(
                    agendamento_id=None,
                    confirmar_desvinculo_agendamento=True,
                ),
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("concluido", str(ctx.exception.detail))
        self.db.rollback()
        self.db.refresh(registro)
        self.assertEqual(registro.agendamento_id, agendamento.id)

    def test_reatribuir_agendamento_de_concluido_para_outro_valor_e_bloqueado(self):
        """Reatribuir (nao so desvincular) o agendamento de um prontuario
        concluido tambem precisa ser bloqueado: sem isso, o agendamento antigo
        fica orfao (Agenda Realizado + OS sem atendimento correspondente) e o
        novo agendamento herda um prontuario Concluido sem passar pela
        finalizacao transacional, sem qualquer auditoria."""
        registro, agendamento_antigo = self._seed(
            agenda_status="Realizado",
            atendimento_status="Concluido",
        )
        agendamento_novo = self._criar_agendamento_extra(registro)

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(
                registro.id,
                AtendimentoUpdatePayload(agendamento_id=agendamento_novo.id),
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("concluido", str(ctx.exception.detail))
        self.db.rollback()
        self.db.refresh(registro)
        self.assertEqual(registro.agendamento_id, agendamento_antigo.id)

    # -------------------------------------------------- desvinculo explicito

    def test_desvincular_sem_confirmacao_retorna_conflito_confirmavel(self):
        registro, agendamento = self._seed()

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(registro.id, AtendimentoUpdatePayload(agendamento_id=None))

        self.assertEqual(ctx.exception.status_code, 409)
        detalhe = ctx.exception.detail
        self.assertEqual(detalhe["codigo"], "CONFIRMACAO_DESVINCULO_AGENDAMENTO")
        self.assertTrue(detalhe["confirmavel"])
        self.assertEqual(detalhe["agendamento_id"], agendamento.id)
        self.db.rollback()
        self.db.refresh(registro)
        self.assertEqual(registro.agendamento_id, agendamento.id)

    def test_desvincular_com_confirmacao_e_auditado(self):
        registro, agendamento = self._seed()

        with patch.object(atendimento, "_auditar_desvinculo_agendamento") as auditoria_mock:
            with patch.object(
                atendimento,
                "_montar_detalhe_atendimento",
                side_effect=lambda _db, item: {"id": item.id},
            ):
                atendimento.atualizar_atendimento(
                    registro.id,
                    AtendimentoUpdatePayload(
                        agendamento_id=None,
                        confirmar_desvinculo_agendamento=True,
                    ),
                    db=self.db,
                    current_user=self.user,
                )

        self.db.refresh(registro)
        self.assertIsNone(registro.agendamento_id)
        self.assertEqual(auditoria_mock.call_count, 1)
        self.assertEqual(
            auditoria_mock.call_args.kwargs["agendamento_id"],
            agendamento.id,
        )

    # ------------------------------------------------------ nao regressao

    def test_autosave_sem_agendamento_no_payload_preserva_o_vinculo(self):
        """O frontend passou a omitir `agendamento_id` quando o campo esta vazio."""
        registro, agendamento = self._seed()

        self._atualizar(
            registro.id,
            AtendimentoUpdatePayload(queixa_principal="Tosse produtiva ha uma semana."),
        )

        self.db.refresh(registro)
        self.assertEqual(registro.agendamento_id, agendamento.id)
        self.assertEqual(registro.queixa_principal, "Tosse produtiva ha uma semana.")

    def test_trocar_agendamento_de_um_valor_para_outro_nao_exige_confirmacao(self):
        """CB-006: trocar de um agendamento vinculado para outro (atendimento
        ainda aberto) continua permitido sem `confirmar_desvinculo_agendamento`,
        e ainda valida duplicidade via `_carregar_e_validar_agendamento_atendimento`."""
        registro, agendamento_antigo = self._seed()
        agendamento_novo = self._criar_agendamento_extra(registro)

        self._atualizar(registro.id, AtendimentoUpdatePayload(agendamento_id=agendamento_novo.id))

        self.db.refresh(registro)
        self.assertEqual(registro.agendamento_id, agendamento_novo.id)

    def test_atendimento_sem_vinculo_continua_podendo_concluir_por_put(self):
        """CB-007: sem Agenda envolvida, a conclusao direta segue permitida."""
        registro, _ = self._seed(vincular=False)

        self._atualizar(registro.id, AtendimentoUpdatePayload(status="Concluido"))

        self.db.refresh(registro)
        self.assertEqual(registro.status, "Concluido")
        self.assertIsNone(registro.agendamento_id)

    def test_desvincular_atendimento_sem_vinculo_nao_exige_confirmacao(self):
        registro, _ = self._seed(vincular=False)

        self._atualizar(registro.id, AtendimentoUpdatePayload(agendamento_id=None))

        self.db.refresh(registro)
        self.assertIsNone(registro.agendamento_id)


if __name__ == "__main__":
    unittest.main()
