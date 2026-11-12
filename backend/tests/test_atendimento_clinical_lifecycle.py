import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
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
os.environ.setdefault("SECRET_KEY", "atendimento-clinical-lifecycle-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.agendamento import Agendamento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico, PrescricaoClinica, PrescricaoItem
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.schemas.atendimento import (
    AtendimentoCreatePayload,
    AtendimentoUpdatePayload,
    DiagnosticoPayload,
    TriagemPayload,
)


class AtendimentoClinicalLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-clinical-lifecycle.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Agendamento.__table__,
            AtendimentoClinico.__table__,
            AuditoriaEvento.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            PrescricaoClinica.__table__,
            PrescricaoItem.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=17, nome="Dra. Teste")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _seed_contexto(self):
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Paciente Teste", especie="Canina", tutor_id=None, ativo=1)
        clinica = Clinica(nome="Clinica Teste")
        self.db.add_all([tutor, paciente, clinica])
        self.db.flush()
        paciente.tutor_id = tutor.id
        self.db.commit()
        return paciente, tutor, clinica

    def _seed_atendimento(self, *, status="Em atendimento", **campos):
        paciente, tutor, clinica = self._seed_contexto()
        item = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=datetime(2026, 7, 29, 14, 30),
            status=status,
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
            **campos,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def test_criacao_vazia_como_concluida_exige_confirmacao_antes_de_gravar(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            atendimento.criar_atendimento(
                AtendimentoCreatePayload(
                    paciente_id=1,
                    status="Concluido",
                    triagem=TriagemPayload(),
                ),
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        detalhe = ctx.exception.detail
        self.assertEqual(detalhe["codigo"], "CONFIRMACAO_CONCLUSAO_PENDENCIAS")
        self.assertTrue(detalhe["confirmavel"])
        self.assertIn("queixa principal", "; ".join(detalhe["pendencias"]))
        self.assertEqual(self.db.query(AtendimentoClinico).count(), 0)

    def test_criacao_vazia_como_concluida_com_confirmacao_e_gravada_e_auditada(self) -> None:
        paciente, _tutor, _clinica = self._seed_contexto()

        with (
            patch.object(atendimento, "_auditar_conclusao_com_pendencias") as auditoria_mock,
            patch.object(
                atendimento,
                "_montar_detalhe_atendimento",
                side_effect=lambda _db, registro: {
                    "id": registro.id,
                    "status": registro.status,
                },
            ),
        ):
            resposta = atendimento.criar_atendimento(
                AtendimentoCreatePayload(
                    paciente_id=paciente.id,
                    status="Concluido",
                    triagem=TriagemPayload(),
                    confirmar_conclusao_pendencias=True,
                ),
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["status"], "Concluido")
        self.assertEqual(self.db.query(AtendimentoClinico).count(), 1)
        self.assertEqual(auditoria_mock.call_count, 1)
        self.assertIn("queixa principal", "; ".join(auditoria_mock.call_args.kwargs["pendencias"]))

    def test_primeira_transicao_vazia_para_concluido_exige_confirmacao_e_preserva_estado(self) -> None:
        item = self._seed_atendimento()

        with self.assertRaises(HTTPException) as ctx:
            atendimento.atualizar_atendimento(
                item.id,
                AtendimentoUpdatePayload(status="Concluido"),
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["codigo"], "CONFIRMACAO_CONCLUSAO_PENDENCIAS")
        self.db.refresh(item)
        self.assertEqual(item.status, "Em atendimento")
        self.assertEqual(item.consulta_concluida or 0, 0)

    def test_primeira_transicao_vazia_com_confirmacao_conclui_e_audita(self) -> None:
        item = self._seed_atendimento()

        with (
            patch.object(atendimento, "_auditar_conclusao_com_pendencias") as auditoria_mock,
            patch.object(
                atendimento,
                "_montar_detalhe_atendimento",
                side_effect=lambda _db, registro: {"id": registro.id, "status": registro.status},
            ),
        ):
            atendimento.atualizar_atendimento(
                item.id,
                AtendimentoUpdatePayload(status="Concluido", confirmar_conclusao_pendencias=True),
                db=self.db,
                current_user=self.user,
            )

        self.db.refresh(item)
        self.assertEqual(item.status, "Concluido")
        self.assertEqual(auditoria_mock.call_count, 1)

    def test_conclusao_valida_normaliza_status_e_marca_consulta(self) -> None:
        item = self._seed_atendimento()
        payload = AtendimentoUpdatePayload(
            status="Concluído",
            consulta_concluida=0,
            queixa_principal="Retorno para reavaliacao.",
            exame_fisico="Paciente estavel ao exame.",
            diagnostico=DiagnosticoPayload(
                diagnostico_principal="Evolucao clinica favoravel.",
            ),
        )

        with patch.object(
            atendimento,
            "_montar_detalhe_atendimento",
            side_effect=lambda _db, registro: {
                "id": registro.id,
                "status": registro.status,
                "consulta_concluida": registro.consulta_concluida,
            },
        ):
            resposta = atendimento.atualizar_atendimento(
                item.id,
                payload,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["status"], "Concluido")
        self.assertEqual(resposta["consulta_concluida"], 1)
        self.db.refresh(item)
        self.assertEqual(item.status, "Concluido")
        self.assertEqual(item.consulta_concluida, 1)

    def test_registro_legado_ja_concluido_continua_editavel(self) -> None:
        item = self._seed_atendimento(status="Concluido")

        with patch.object(
            atendimento,
            "_montar_detalhe_atendimento",
            side_effect=lambda _db, registro: {
                "id": registro.id,
                "status": registro.status,
                "observacoes": registro.observacoes,
            },
        ):
            resposta = atendimento.atualizar_atendimento(
                item.id,
                AtendimentoUpdatePayload(
                    status="Concluido",
                    observacoes="Correcao revisada do registro legado.",
                ),
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["status"], "Concluido")
        self.assertEqual(resposta["observacoes"], "Correcao revisada do registro legado.")

    def test_criacao_respeita_flags_explicitas_e_nao_conclui_triagem_vazia(self) -> None:
        paciente, *_ = self._seed_contexto()
        payload = AtendimentoCreatePayload(
            paciente_id=paciente.id,
            status="Em atendimento",
            triagem=TriagemPayload(),
            triagem_concluida=0,
            consulta_concluida=0,
            data_atendimento="2026-07-29T14:30:00-03:00",
        )

        with (
            patch.object(atendimento, "_sync_exames"),
            patch.object(atendimento, "_sync_prescricao"),
            patch.object(
                atendimento,
                "_montar_detalhe_atendimento",
                side_effect=lambda _db, registro: {
                    "id": registro.id,
                    "status": registro.status,
                    "triagem_concluida": registro.triagem_concluida,
                    "consulta_concluida": registro.consulta_concluida,
                    "data_atendimento": atendimento._to_operational_iso(registro.data_atendimento),
                },
            ),
        ):
            resposta = atendimento.criar_atendimento(
                payload,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["triagem_concluida"], 0)
        self.assertEqual(resposta["consulta_concluida"], 0)
        self.assertEqual(resposta["data_atendimento"], "2026-07-29T14:30:00-03:00")

    def test_status_desconhecido_e_rejeitado(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            atendimento._normalizar_status_atendimento("Arquivado")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_serializacao_operacional_nao_desloca_horario(self) -> None:
        naive_local = datetime(2026, 7, 29, 14, 30)
        aware_utc = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)

        self.assertEqual(
            atendimento._to_operational_iso(naive_local),
            "2026-07-29T14:30:00-03:00",
        )
        self.assertEqual(
            atendimento._to_operational_iso(aware_utc),
            "2026-07-29T14:30:00-03:00",
        )

    def test_contexto_da_agenda_devolve_inicio_operacional(self) -> None:
        paciente, tutor, clinica = self._seed_contexto()
        agendamento = Agendamento(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            inicio=datetime(2026, 7, 30, 9, 15),
            status="Confirmado",
        )
        self.db.add(agendamento)
        self.db.commit()
        self.db.refresh(agendamento)

        contexto = atendimento.obter_contexto_agendamento(
            agendamento.id,
            db=self.db,
            current_user=self.user,
        )

        self.assertEqual(contexto["inicio"], "2026-07-30T09:15:00-03:00")
        self.assertEqual(contexto["paciente_id"], paciente.id)
        self.assertEqual(contexto["clinica_id"], clinica.id)


if __name__ == "__main__":
    unittest.main()
