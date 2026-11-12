"""Excecao de conflito de rota concedida por admin precisa sobreviver a acao.

Cenario reportado: o admin concedeu a excecao ao criar o agendamento, a reserva
expirou e a tentativa posterior de reativar ("Agendar apos confirmacao tardia")
voltava a ser bloqueada pela validacao de deslocamento, porque a concessao era
transiente. Aqui a excecao e persistida no agendamento e vale enquanto horario,
destino e servico continuarem os mesmos.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
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
os.environ.setdefault("SECRET_KEY", "agenda-excecao-deslocamento-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor

INICIO_VIZINHO = datetime(2099, 5, 25, 10, 0, 0)
INICIO_ALVO = datetime(2099, 5, 25, 11, 0, 0)
# Acima de MAX_DESLOCAMENTO_TRECHO_VIZINHO_MIN (45): garante o bloqueio.
DESLOCAMENTO_CONFLITANTE_MIN = 75

ADMIN = SimpleNamespace(id=1, nome="Martiniano", tem_papel=lambda papel: papel == "admin")
SECRETARIA = SimpleNamespace(id=2, nome="Recepcao", tem_papel=lambda _papel: False)


def _agenda_semanal_aberta() -> dict[str, dict[str, object]]:
    return {
        str(dia): {"ativo": True, "inicio": "08:00", "fim": "18:00"}
        for dia in range(1, 8)
    }


class AgendaExcecaoDeslocamentoPersistenteTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-excecao-deslocamento.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            Clinica.__table__,
            Servico.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Agendamento.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed(self, db):
        db.add(
            Configuracao(
                agenda_semanal=json.dumps(_agenda_semanal_aberta()),
                agenda_feriados=json.dumps([]),
                agenda_excecoes=json.dumps([]),
            )
        )
        clinica_vizinha = Clinica(
            nome="Pet Xodo",
            ativo=True,
            latitude=-3.7319,
            longitude=-38.5267,
            cidade="Fortaleza",
            estado="CE",
        )
        clinica_alvo = Clinica(
            nome="Pet Sanus Caucaia",
            ativo=True,
            latitude=-3.7342,
            longitude=-38.6434,
            cidade="Caucaia",
            estado="CE",
        )
        servico = Servico(nome="Ecocardiograma", duracao_minutos=30, ativo=True)
        tutor = Tutor(nome="Ana Tutora", telefone="85999990000")
        db.add_all([clinica_vizinha, clinica_alvo, servico, tutor])
        db.commit()
        db.refresh(clinica_vizinha)
        db.refresh(clinica_alvo)
        db.refresh(servico)
        db.refresh(tutor)

        paciente = Paciente(nome="Bidu", tutor_id=tutor.id)
        db.add(paciente)
        db.commit()
        db.refresh(paciente)

        vizinho = Agendamento(
            clinica_id=clinica_vizinha.id,
            servico_id=servico.id,
            inicio=INICIO_VIZINHO,
            fim=INICIO_VIZINHO + timedelta(minutes=30),
            data=INICIO_VIZINHO.strftime("%Y-%m-%d"),
            hora=INICIO_VIZINHO.strftime("%H:%M"),
            status="Agendado",
            clinica=clinica_vizinha.nome,
        )
        db.add(vizinho)
        db.commit()
        return SimpleNamespace(
            clinica_vizinha=clinica_vizinha,
            clinica_alvo=clinica_alvo,
            servico=servico,
            tutor=tutor,
            paciente=paciente,
        )

    def _criar_alvo(self, db, ctx, *, status: str, inicio: datetime = INICIO_ALVO):
        agendamento = Agendamento(
            paciente_id=ctx.paciente.id,
            tutor_id=ctx.tutor.id,
            clinica_id=ctx.clinica_alvo.id,
            servico_id=ctx.servico.id,
            inicio=inicio,
            fim=inicio + timedelta(minutes=30),
            data=inicio.strftime("%Y-%m-%d"),
            hora=inicio.strftime("%H:%M"),
            status=status,
            clinica=ctx.clinica_alvo.nome,
            reserva_expira_em=(
                datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None) - timedelta(hours=2)
                if status == "Expirado"
                else None
            ),
        )
        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)
        return agendamento

    def _patch_rota(self):
        return patch.object(
            agenda,
            "_obter_duracao_deslocamento_operacional",
            return_value=(DESLOCAMENTO_CONFLITANTE_MIN, "mock"),
        )

    def _patch_efeitos_colaterais(self):
        return (
            patch.object(agenda, "registrar_auditoria", return_value=None),
            patch.object(agenda, "_notificar_agenda_update", return_value=None),
        )

    # ------------------------------------------------------------------
    # Validacao isolada
    # ------------------------------------------------------------------
    def test_bloqueia_sem_excecao_e_sinaliza_concessao_quando_admin_confirma(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Agendado")

            with self._patch_rota():
                with self.assertRaises(HTTPException) as erro:
                    agenda._validar_deslocamento_agendamento(
                        db, alvo, agendamento_id_excluir=alvo.id
                    )
                self.assertEqual(erro.exception.status_code, 409)
                self.assertEqual(erro.exception.detail.get("codigo"), "CONFLITO_DESLOCAMENTO")

                bypass = agenda._validar_deslocamento_agendamento(
                    db,
                    alvo,
                    agendamento_id_excluir=alvo.id,
                    confirmar_conflito_deslocamento=True,
                )
            self.assertEqual(bypass, {"origem": "confirmacao_admin", "bloqueio": "limite_trecho_anterior"})
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_excecao_persistida_libera_validacao_sem_nova_confirmacao(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Agendado")
            agenda._conceder_excecao_deslocamento(alvo, current_user=ADMIN, motivo="Rota longa aprovada")
            db.commit()

            with self._patch_rota():
                bypass = agenda._validar_deslocamento_agendamento(
                    db, alvo, agendamento_id_excluir=alvo.id
                )

            self.assertEqual(bypass.get("origem"), "excecao_persistida")
            self.assertEqual(alvo.excecao_deslocamento_motivo, "Rota longa aprovada")
            self.assertEqual(alvo.excecao_deslocamento_concedida_por_nome, "Martiniano")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_excecao_perde_validade_quando_horario_ou_destino_muda(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Agendado")
            agenda._conceder_excecao_deslocamento(alvo, current_user=ADMIN)
            db.commit()

            # Mesmo escopo: excecao continua valendo.
            self.assertTrue(agenda._excecao_deslocamento_ativa(alvo))

            alvo.inicio = INICIO_ALVO + timedelta(hours=1)
            alvo.fim = alvo.inicio + timedelta(minutes=30)
            self.assertFalse(agenda._excecao_deslocamento_ativa(alvo))

            with self._patch_rota():
                with self.assertRaises(HTTPException) as erro:
                    agenda._validar_deslocamento_agendamento(
                        db, alvo, agendamento_id_excluir=alvo.id
                    )
            self.assertEqual(erro.exception.status_code, 409)

            # Volta ao horario aprovado: a excecao original volta a valer.
            alvo.inicio = INICIO_ALVO
            alvo.fim = INICIO_ALVO + timedelta(minutes=30)
            self.assertTrue(agenda._excecao_deslocamento_ativa(alvo))

            # Trocar de clinica tambem invalida.
            alvo.clinica_id = ctx.clinica_vizinha.id
            self.assertFalse(agenda._excecao_deslocamento_ativa(alvo))
            self.assertTrue(agenda._descartar_excecao_deslocamento_obsoleta(alvo))
            self.assertIsNone(alvo.excecao_deslocamento_concedida_em)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_excecao_sobrevive_ao_preenchimento_de_paciente_e_tutor(self) -> None:
        """Reserva sem dados do pet recebe a excecao; os dados chegam depois."""
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Expirado")
            alvo.paciente_id = None
            alvo.tutor_id = None
            db.commit()
            agenda._conceder_excecao_deslocamento(alvo, current_user=ADMIN)
            db.commit()

            # A clinica envia os dados depois do prazo: a rota nao mudou, entao
            # a excecao continua valendo.
            alvo.paciente_id = ctx.paciente.id
            alvo.tutor_id = ctx.tutor.id
            self.assertTrue(agenda._excecao_deslocamento_ativa(alvo))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_excecao_domiciliar_invalida_quando_tutor_muda(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Agendado")
            alvo.clinica_id = None
            alvo.origem_atendimento = "domiciliar"
            db.commit()
            agenda._conceder_excecao_deslocamento(alvo, current_user=ADMIN)
            db.commit()

            self.assertTrue(agenda._excecao_deslocamento_ativa(alvo))
            # No domiciliar o endereco de destino vem do tutor: trocar o tutor
            # troca a rota aprovada.
            alvo.tutor_id = (ctx.tutor.id or 0) + 99
            self.assertFalse(agenda._excecao_deslocamento_ativa(alvo))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    # ------------------------------------------------------------------
    # PATCH /agenda/{id}/status - caminho do botao "Agendar apos confirmacao tardia"
    # ------------------------------------------------------------------
    def _reativar_expirado(self, db, agendamento_id, *, usuario, **kwargs):
        patch_auditoria, patch_push = self._patch_efeitos_colaterais()
        with self._patch_rota(), patch_auditoria, patch_push:
            return agenda.atualizar_status(
                agendamento_id=agendamento_id,
                request=SimpleNamespace(),
                status="Agendado",
                confirmar_slot_reserva_expirada=True,
                db=db,
                current_user=usuario,
                **kwargs,
            )

    def test_reativacao_de_expirado_e_bloqueada_sem_excecao(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Expirado")

            with self.assertRaises(HTTPException) as erro:
                self._reativar_expirado(db, alvo.id, usuario=ADMIN)

            self.assertEqual(erro.exception.status_code, 409)
            self.assertEqual(erro.exception.detail.get("codigo"), "CONFLITO_DESLOCAMENTO")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_nao_admin_nao_pode_confirmar_conflito_na_troca_de_status(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Expirado")

            with self.assertRaises(HTTPException) as erro:
                self._reativar_expirado(
                    db,
                    alvo.id,
                    usuario=SECRETARIA,
                    confirmar_conflito_deslocamento=True,
                )

            self.assertEqual(erro.exception.status_code, 403)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_admin_confirma_conflito_e_excecao_fica_persistida(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Expirado")

            resposta = self._reativar_expirado(
                db,
                alvo.id,
                usuario=ADMIN,
                confirmar_conflito_deslocamento=True,
                motivo_excecao_deslocamento="Cliente confirmou tarde; rota aprovada",
            )

            self.assertEqual(resposta["status"], "Agendado")
            db.refresh(alvo)
            self.assertTrue(resposta.get("excecao_deslocamento_ativa"))
            self.assertEqual(
                alvo.excecao_deslocamento_motivo,
                "Cliente confirmou tarde; rota aprovada",
            )
            self.assertEqual(alvo.excecao_deslocamento_concedida_por_id, ADMIN.id)
            self.assertIsNotNone(alvo.excecao_deslocamento_escopo)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_excecao_concedida_antes_libera_nova_reativacao_sem_confirmar(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Expirado")
            agenda._conceder_excecao_deslocamento(alvo, current_user=ADMIN, motivo="Rota aprovada na criacao")
            db.commit()

            resposta = self._reativar_expirado(db, alvo.id, usuario=SECRETARIA)

            self.assertEqual(resposta["status"], "Agendado")
            db.refresh(alvo)
            self.assertEqual(alvo.status, "Agendado")
            self.assertEqual(alvo.excecao_deslocamento_motivo, "Rota aprovada na criacao")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    # ------------------------------------------------------------------
    # POST /agenda/{id}/reabilitar-reserva
    # ------------------------------------------------------------------
    def test_reabilitar_reserva_respeita_excecao_ja_concedida(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Expirado")
            agenda._conceder_excecao_deslocamento(alvo, current_user=ADMIN)
            db.commit()

            payload = agenda.ReabilitarReservaPayload(prazo_confirmacao_horas=6)
            patch_auditoria, patch_push = self._patch_efeitos_colaterais()
            with self._patch_rota(), patch_auditoria, patch_push:
                resposta = agenda.reabilitar_reserva_expirada(
                    agendamento_id=alvo.id,
                    payload=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SECRETARIA,
                )

            self.assertEqual(resposta["status"], "Reservado")
            db.refresh(alvo)
            self.assertEqual(alvo.status, "Reservado")
            self.assertTrue(agenda._excecao_deslocamento_ativa(alvo))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reabilitar_reserva_sem_excecao_continua_bloqueada(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ctx = self._seed(db)
            alvo = self._criar_alvo(db, ctx, status="Expirado")

            payload = agenda.ReabilitarReservaPayload(prazo_confirmacao_horas=6)
            patch_auditoria, patch_push = self._patch_efeitos_colaterais()
            with self._patch_rota(), patch_auditoria, patch_push:
                with self.assertRaises(HTTPException) as erro:
                    agenda.reabilitar_reserva_expirada(
                        agendamento_id=alvo.id,
                        payload=payload,
                        request=SimpleNamespace(),
                        db=db,
                        current_user=SECRETARIA,
                    )

            self.assertEqual(erro.exception.status_code, 409)
            self.assertEqual(erro.exception.detail.get("codigo"), "CONFLITO_DESLOCAMENTO")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
