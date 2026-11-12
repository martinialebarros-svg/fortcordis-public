"""Integridade de exame e anexo no prontuario.

Cobre os defeitos em que o autosave apagava exame, anexo e arquivo fisico por
omissao no payload, e em que salvar o atendimento revogava a liberacao do exame
no portal da clinica parceira.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
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
os.environ.setdefault("SECRET_KEY", "atendimento-exame-integridade-test-secret-key-1234")

from app.api.v1.endpoints import atendimento
from app.models.auditoria_evento import AuditoriaEvento
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico, ExameAjuste
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.models.tutor import Tutor
from app.schemas.atendimento import AtendimentoUpdatePayload, ExameSolicitacaoPayload


class AtendimentoExameIntegridadeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-exame-integridade.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            AuditoriaEvento.__table__,
            AnexoAtendimento.__table__,
            Exame.__table__,
            ExameAjuste.__table__,
            PortalClinicExamLink.__table__,
            PortalClinicTrustedDevice.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=21, nome="Dra. Teste", email="teste@example.com")

        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Paciente Teste", especie="Canina", ativo=1)
        clinica = Clinica(nome="Clinica Parceira", tabela_preco_id=1)
        self.db.add_all([tutor, paciente, clinica])
        self.db.flush()
        paciente.tutor_id = tutor.id
        self.paciente = paciente
        self.clinica = clinica

        self.atendimento = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=datetime(2026, 7, 31, 10, 0),
            status="Em atendimento",
            queixa_principal="Tosse seca ha tres dias.",
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(self.atendimento)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------ helpers

    def _criar_exame(
        self,
        *,
        tipo_exame: str = "Hemograma",
        status: str = "Solicitado",
        resultado: str | None = None,
        laudo_id: int | None = None,
    ) -> Exame:
        exame = Exame(
            atendimento_id=self.atendimento.id,
            paciente_id=self.paciente.id,
            tipo_exame=tipo_exame,
            status=status,
            resultado=resultado,
            laudo_id=laudo_id,
            data_solicitacao=datetime(2026, 7, 31, 10, 5),
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(exame)
        self.db.commit()
        self.db.refresh(exame)
        return exame

    def _criar_anexo(self, exame: Exame) -> tuple[AnexoAtendimento, Path]:
        arquivo = Path(self.tmpdir.name) / f"resultado-{exame.id}.pdf"
        arquivo.write_bytes(b"%PDF-1.4 resultado do exame")
        anexo = AnexoAtendimento(
            atendimento_id=self.atendimento.id,
            exame_id=exame.id,
            tipo="documento",
            url=f"/api/v1/atendimentos/anexos/{exame.id}/arquivo",
            nome_original=f"resultado-{exame.id}.pdf",
            tamanho=arquivo.stat().st_size,
            mime_type="application/pdf",
            caminho_arquivo=str(arquivo),
            origem="upload",
        )
        self.db.add(anexo)
        self.db.commit()
        self.db.refresh(anexo)
        return anexo, arquivo

    def _payload_frontend(self, exame: Exame, **overrides) -> ExameSolicitacaoPayload:
        """Payload equivalente ao que o frontend envia para um exame existente."""
        base = {
            "id": exame.id,
            "tipo_exame": exame.tipo_exame,
            "prioridade": exame.prioridade or "Rotina",
            "status": exame.status,
            "resultado": exame.resultado or "",
            "laudo_id": exame.laudo_id,
        }
        base.update(overrides)
        return ExameSolicitacaoPayload(**base)

    def _atualizar(self, payload: AtendimentoUpdatePayload):
        with patch.object(
            atendimento,
            "_montar_detalhe_atendimento",
            side_effect=lambda _db, item: {"id": item.id, "status": item.status},
        ):
            return atendimento.atualizar_atendimento(
                self.atendimento.id,
                payload,
                db=self.db,
                current_user=self.user,
            )

    # --------------------------------------------------------- exclusao (D1)

    def test_put_que_omite_exame_existente_nao_apaga_exame_nem_anexo(self):
        """Cenario 1: limpar o tipo do exame nao pode apagar o exame nem o PDF."""
        exame = self._criar_exame()
        anexo, arquivo = self._criar_anexo(exame)

        # O frontend filtra exame sem `tipo_exame`, entao o item nao chega no payload.
        self._atualizar(AtendimentoUpdatePayload(exames=[]))

        self.assertIsNotNone(self.db.query(Exame).filter(Exame.id == exame.id).first())
        self.assertIsNotNone(
            self.db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo.id).first()
        )
        self.assertTrue(arquivo.exists())

    def test_exclusao_explicita_remove_exame(self):
        """Exame sem anexo e o unico caso que a exclusao explicita alcanca
        diretamente: com anexo, o guard de test_exclusao_explicita_bloqueada_
        quando_exame_tem_anexo bloqueia antes de chegar aqui (CA-004)."""
        exame = self._criar_exame()

        self._atualizar(
            AtendimentoUpdatePayload(exames=[ExameSolicitacaoPayload(id=exame.id, _destroy=True)])
        )

        self.assertIsNone(self.db.query(Exame).filter(Exame.id == exame.id).first())

    def test_excluir_anexos_por_exame_remove_registro_e_arquivo_fisico(self):
        """O mecanismo de remocao (`_excluir_anexos_por_exame`) e exercitado
        diretamente: pelo guard de CA-004, ele so roda dentro de _sync_exames
        quando o exame ja tem zero anexos, entao nao ha payload de API que
        force a limpeza de um arquivo real atraves do endpoint guardado."""
        exame = self._criar_exame()
        anexo, arquivo = self._criar_anexo(exame)

        atendimento._excluir_anexos_por_exame(self.db, exame.id)
        self.db.commit()

        self.assertIsNone(
            self.db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo.id).first()
        )
        self.assertFalse(arquivo.exists())

    def test_remover_anexo_individual_depois_excluir_exame_agora_vazio(self):
        """Fluxo real de dois passos: o guard exige remover o anexo primeiro
        (endpoint dedicado DELETE /anexos/{id}); so entao o exame, agora sem
        anexo, pode ser excluido pelo prontuario."""
        exame = self._criar_exame()
        anexo, arquivo = self._criar_anexo(exame)

        atendimento.excluir_anexo(anexo.id, db=self.db, current_user=self.user)
        self.assertFalse(arquivo.exists())

        self._atualizar(
            AtendimentoUpdatePayload(exames=[ExameSolicitacaoPayload(id=exame.id, _destroy=True)])
        )

        self.assertIsNone(self.db.query(Exame).filter(Exame.id == exame.id).first())

    def test_exclusao_com_dois_exames_resultado_misto_nao_apaga_o_permitido(self):
        """O exame que passaria no guard nao pode ser apagado quando outro item
        do MESMO payload e bloqueado: a excecao interrompe o loop antes do
        commit, e nada e persistido para nenhum dos dois."""
        exame_livre = self._criar_exame(tipo_exame="Hemograma")
        exame_bloqueado = self._criar_exame(tipo_exame="Ecocardiograma", laudo_id=55)

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(
                AtendimentoUpdatePayload(
                    exames=[
                        ExameSolicitacaoPayload(id=exame_livre.id, _destroy=True),
                        ExameSolicitacaoPayload(id=exame_bloqueado.id, _destroy=True),
                    ]
                )
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.db.rollback()
        self.assertIsNotNone(self.db.query(Exame).filter(Exame.id == exame_livre.id).first())
        self.assertIsNotNone(self.db.query(Exame).filter(Exame.id == exame_bloqueado.id).first())

    def test_exclusao_explicita_bloqueada_quando_exame_tem_laudo(self):
        """Cenario 2: exame com laudo vinculado nao pode ser apagado pelo prontuario."""
        exame = self._criar_exame(laudo_id=99)

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(
                AtendimentoUpdatePayload(
                    exames=[ExameSolicitacaoPayload(id=exame.id, _destroy=True)]
                )
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("laudo vinculado", str(ctx.exception.detail))
        self.db.rollback()
        self.assertIsNotNone(self.db.query(Exame).filter(Exame.id == exame.id).first())

    def test_exclusao_explicita_bloqueada_quando_exame_tem_anexo(self):
        exame = self._criar_exame()
        anexo, arquivo = self._criar_anexo(exame)

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(
                AtendimentoUpdatePayload(
                    exames=[ExameSolicitacaoPayload(id=exame.id, _destroy=True)]
                )
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Remova os arquivos", str(ctx.exception.detail))
        self.db.rollback()
        self.assertIsNotNone(self.db.query(Exame).filter(Exame.id == exame.id).first())
        self.assertIsNotNone(
            self.db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo.id).first()
        )
        self.assertTrue(arquivo.exists())

    def test_exclusao_explicita_bloqueada_quando_exame_esta_liberado_no_portal(self):
        exame = self._criar_exame(status=PORTAL_RELEASED_STATUS)

        with self.assertRaises(HTTPException) as ctx:
            self._atualizar(
                AtendimentoUpdatePayload(
                    exames=[ExameSolicitacaoPayload(id=exame.id, _destroy=True)]
                )
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("liberado no portal", str(ctx.exception.detail))
        self.db.rollback()
        self.assertIsNotNone(self.db.query(Exame).filter(Exame.id == exame.id).first())

    def test_exclusao_de_exame_inexistente_e_ignorada(self):
        """CB-001: repetir a exclusao e idempotente, nao gera erro."""
        self._atualizar(
            AtendimentoUpdatePayload(exames=[ExameSolicitacaoPayload(id=987654, _destroy=True)])
        )

        self.assertEqual(
            self.db.query(Exame).filter(Exame.atendimento_id == self.atendimento.id).count(),
            0,
        )

    def test_payload_marcado_para_exclusao_dispensa_tipo_exame(self):
        """CB-002: o schema aceita item sem `tipo_exame` quando ha `_destroy`."""
        payload = ExameSolicitacaoPayload(**{"id": 1, "_destroy": True})
        self.assertTrue(payload.destroy)

        with self.assertRaises(ValueError):
            ExameSolicitacaoPayload(**{"id": 1, "tipo_exame": ""})

    def test_autosave_atrasado_com_id_ja_excluido_nao_recria_exame(self):
        """Um PUT atrasado nao pode ressuscitar um item removido pelo usuario."""
        self._atualizar(
            AtendimentoUpdatePayload(
                exames=[ExameSolicitacaoPayload(id=987654, tipo_exame="Ultrassom abdominal")]
            )
        )

        self.assertEqual(
            self.db.query(Exame).filter(Exame.atendimento_id == self.atendimento.id).count(),
            0,
        )

    # ------------------------------------------------ status e portal (D2)

    def test_put_do_frontend_preserva_status_liberado_no_portal(self):
        """Cenario 3: o payload real do frontend nao pode revogar a liberacao."""
        exame = self._criar_exame(status=PORTAL_RELEASED_STATUS, resultado="Ritmo sinusal.")

        # O frontend recalculava o status e mandava "Concluido".
        self._atualizar(
            AtendimentoUpdatePayload(
                exames=[self._payload_frontend(exame, status="Concluido")]
            )
        )

        self.db.refresh(exame)
        self.assertEqual(exame.status, PORTAL_RELEASED_STATUS)

    def test_put_do_frontend_preserva_liberacao_mesmo_sem_resultado(self):
        exame = self._criar_exame(status=PORTAL_RELEASED_STATUS)
        self._criar_anexo(exame)

        self._atualizar(
            AtendimentoUpdatePayload(
                exames=[self._payload_frontend(exame, status="Solicitado", resultado="")]
            )
        )

        self.db.refresh(exame)
        self.assertEqual(exame.status, PORTAL_RELEASED_STATUS)

    def test_status_do_exame_e_derivado_no_servidor(self):
        exame = self._criar_exame(status="Solicitado")

        # Cliente mente dizendo "Concluido" sem resultado nem anexo.
        self._atualizar(
            AtendimentoUpdatePayload(
                exames=[self._payload_frontend(exame, status="Concluido", resultado="")]
            )
        )
        self.db.refresh(exame)
        self.assertEqual(exame.status, "Solicitado")

        # Com anexo em banco, o servidor deriva "Em andamento".
        self._criar_anexo(exame)
        self._atualizar(
            AtendimentoUpdatePayload(
                exames=[self._payload_frontend(exame, status="Solicitado", resultado="")]
            )
        )
        self.db.refresh(exame)
        self.assertEqual(exame.status, "Em andamento")

        # Com resultado preenchido, o servidor deriva "Concluido".
        self._atualizar(
            AtendimentoUpdatePayload(
                exames=[
                    self._payload_frontend(exame, status="Solicitado", resultado="Sem alteracoes.")
                ]
            )
        )
        self.db.refresh(exame)
        self.assertEqual(exame.status, "Concluido")

    def test_guarda_de_regressao_de_status_cobre_liberacao_no_portal(self):
        """Base do cenario 4; o endpoint de upload e testado em
        `test_atendimento_upload_endpoint.py`."""
        self.assertFalse(atendimento._status_exame_regressao_bloqueada("Solicitado"))
        self.assertFalse(atendimento._status_exame_regressao_bloqueada("Em andamento"))
        self.assertTrue(atendimento._status_exame_regressao_bloqueada("Concluido"))
        self.assertTrue(atendimento._status_exame_regressao_bloqueada(PORTAL_RELEASED_STATUS))

    def test_revogacao_explicita_devolve_exame_ao_status_derivado(self):
        exame = self._criar_exame(status=PORTAL_RELEASED_STATUS, resultado="Ritmo sinusal.")
        exame.observacoes = atendimento.PORTAL_EXAME_RELEASE_MESSAGE
        self.db.commit()

        with patch.object(atendimento, "_auditar_transicao_exame_portal") as auditoria_mock:
            resposta = atendimento.revogar_liberacao_exame_no_portal(
                exame.id,
                db=self.db,
                current_user=self.user,
            )

        self.db.refresh(exame)
        self.assertEqual(exame.status, "Concluido")
        self.assertEqual(resposta["status_anterior"], PORTAL_RELEASED_STATUS)
        self.assertEqual(exame.observacoes, "")
        self.assertEqual(auditoria_mock.call_count, 1)
        self.assertEqual(auditoria_mock.call_args.kwargs["acao"], "REVOGAR_EXAME_PORTAL")

        # Um novo save nao restaura a liberacao.
        self._atualizar(
            AtendimentoUpdatePayload(
                exames=[self._payload_frontend(exame, status=PORTAL_RELEASED_STATUS)]
            )
        )
        self.db.refresh(exame)
        self.assertEqual(exame.status, "Concluido")

    def test_revogar_exame_nao_liberado_retorna_conflito(self):
        exame = self._criar_exame(status="Concluido", resultado="Sem alteracoes.")

        with self.assertRaises(HTTPException) as ctx:
            atendimento.revogar_liberacao_exame_no_portal(
                exame.id,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.db.refresh(exame)
        self.assertEqual(exame.status, "Concluido")


if __name__ == "__main__":
    unittest.main()
