import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-exame-laudo-id-propriedade-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.catalogo_exame import CatalogoExame, PainelExame
from app.models.laudo import Exame, Laudo
from app.schemas.atendimento import ExameSolicitacaoPayload


class AtendimentoExameLaudoIdPropriedadeTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "atendimento-exame-laudo-id.db"
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (
            AtendimentoClinico.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            Laudo.__table__,
            CatalogoExame.__table__,
            PainelExame.__table__,
        ):
            table.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return tmpdir, session_factory(), engine

    def _seed_atendimento(self, db, paciente_id):
        atendimento_item = AtendimentoClinico(
            paciente_id=paciente_id,
            tutor_id=44,
            clinica_id=8,
            veterinario_id=77,
            especie="Canina",
            data_atendimento=datetime(2026, 7, 5, 9, 30),
            status="Em atendimento",
            criado_por_id=77,
            criado_por_nome="Vet Teste",
        )
        db.add(atendimento_item)
        db.commit()
        return atendimento_item

    def test_laudo_id_de_outro_paciente_e_ignorado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            atendimento_paciente_a = self._seed_atendimento(db, paciente_id=100)
            laudo_paciente_b = Laudo(
                paciente_id=200,
                veterinario_id=1,
                tipo="exame",
                titulo="Laudo do paciente B",
                status="Liberado",
            )
            db.add(laudo_paciente_b)
            db.commit()

            payload = ExameSolicitacaoPayload(tipo_exame="Ecocardiograma", laudo_id=laudo_paciente_b.id)
            atendimento._sync_exames(
                db,
                atendimento_paciente_a,
                [payload],
                SimpleNamespace(id=1, nome="Dr Teste"),
            )
            db.commit()

            exame = db.query(Exame).filter(Exame.atendimento_id == atendimento_paciente_a.id).first()
            self.assertIsNotNone(exame)
            self.assertIsNone(exame.laudo_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_laudo_id_do_mesmo_paciente_e_aceito(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            atendimento_paciente_a = self._seed_atendimento(db, paciente_id=100)
            laudo_paciente_a = Laudo(
                paciente_id=100,
                veterinario_id=1,
                tipo="exame",
                titulo="Laudo do paciente A",
                status="Liberado",
            )
            db.add(laudo_paciente_a)
            db.commit()

            payload = ExameSolicitacaoPayload(tipo_exame="Ecocardiograma", laudo_id=laudo_paciente_a.id)
            atendimento._sync_exames(
                db,
                atendimento_paciente_a,
                [payload],
                SimpleNamespace(id=1, nome="Dr Teste"),
            )
            db.commit()

            exame = db.query(Exame).filter(Exame.atendimento_id == atendimento_paciente_a.id).first()
            self.assertEqual(exame.laudo_id, laudo_paciente_a.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_laudo_id_inexistente_e_ignorado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            atendimento_item = self._seed_atendimento(db, paciente_id=100)

            payload = ExameSolicitacaoPayload(tipo_exame="Ecocardiograma", laudo_id=999999)
            atendimento._sync_exames(
                db,
                atendimento_item,
                [payload],
                SimpleNamespace(id=1, nome="Dr Teste"),
            )
            db.commit()

            exame = db.query(Exame).filter(Exame.atendimento_id == atendimento_item.id).first()
            self.assertIsNone(exame.laudo_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reenviar_o_mesmo_laudo_id_ja_vinculado_preserva_o_vinculo(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            atendimento_item = self._seed_atendimento(db, paciente_id=100)
            laudo = Laudo(
                paciente_id=100,
                veterinario_id=1,
                tipo="exame",
                titulo="Laudo do paciente A",
                status="Liberado",
            )
            db.add(laudo)
            db.commit()

            payload_inicial = ExameSolicitacaoPayload(tipo_exame="Ecocardiograma", laudo_id=laudo.id)
            atendimento._sync_exames(
                db, atendimento_item, [payload_inicial], SimpleNamespace(id=1, nome="Dr Teste")
            )
            db.commit()
            exame = db.query(Exame).filter(Exame.atendimento_id == atendimento_item.id).first()

            # Round-trip: o frontend reenvia o mesmo laudo_id ja hidratado -
            # nao deve precisar consultar o Laudo de novo nem ser rejeitado.
            payload_round_trip = ExameSolicitacaoPayload(
                id=exame.id, tipo_exame="Ecocardiograma", laudo_id=laudo.id
            )
            atendimento._sync_exames(
                db, atendimento_item, [payload_round_trip], SimpleNamespace(id=1, nome="Dr Teste")
            )
            db.commit()

            db.refresh(exame)
            self.assertEqual(exame.laudo_id, laudo.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_payload_sem_laudo_id_nao_desvincula_laudo_ja_setado(self) -> None:
        """Achado #17 da auditoria: um payload com laudo_id vazio para um
        exame que ja tem laudo vinculado no banco e sempre um snapshot
        desatualizado do cliente - o atendimento nunca oferece um jeito de
        desvincular por aqui, so laudos.py cria esse vinculo. Sem esta
        protecao, o proximo autosave (com o form ainda sem o vinculo
        recem-criado por outra aba/sessao) apagaria a ligacao."""
        tmpdir, db, engine = self._build_session()
        try:
            atendimento_item = self._seed_atendimento(db, paciente_id=100)
            laudo = Laudo(
                paciente_id=100,
                veterinario_id=1,
                tipo="exame",
                titulo="Laudo do paciente A",
                status="Liberado",
            )
            db.add(laudo)
            db.commit()

            # Exame ja existe com laudo vinculado (simula vinculo feito por
            # laudos.py enquanto o atendimento estava aberto em outra aba).
            exame = Exame(
                atendimento_id=atendimento_item.id,
                paciente_id=100,
                tipo_exame="Ecocardiograma",
                laudo_id=laudo.id,
                criado_por_id=1,
                criado_por_nome="Dr Teste",
            )
            db.add(exame)
            db.commit()

            payload_desatualizado = ExameSolicitacaoPayload(
                id=exame.id, tipo_exame="Ecocardiograma", laudo_id=None
            )
            atendimento._sync_exames(
                db, atendimento_item, [payload_desatualizado], SimpleNamespace(id=1, nome="Dr Teste")
            )
            db.commit()

            db.refresh(exame)
            self.assertEqual(exame.laudo_id, laudo.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_payload_sem_laudo_id_em_exame_sem_vinculo_continua_sem_vinculo(self) -> None:
        """Caso de borda: exame que nunca teve laudo e continua sem laudo
        quando o payload nao envia nenhum - garante que a nova protecao nao
        vira um `if not payload.laudo_id: pass` incondicional."""
        tmpdir, db, engine = self._build_session()
        try:
            atendimento_item = self._seed_atendimento(db, paciente_id=100)
            exame = Exame(
                atendimento_id=atendimento_item.id,
                paciente_id=100,
                tipo_exame="Ecocardiograma",
                criado_por_id=1,
                criado_por_nome="Dr Teste",
            )
            db.add(exame)
            db.commit()

            payload = ExameSolicitacaoPayload(id=exame.id, tipo_exame="Ecocardiograma", laudo_id=None)
            atendimento._sync_exames(
                db, atendimento_item, [payload], SimpleNamespace(id=1, nome="Dr Teste")
            )
            db.commit()

            db.refresh(exame)
            self.assertIsNone(exame.laudo_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
