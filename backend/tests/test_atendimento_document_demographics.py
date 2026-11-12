import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-document-demographics-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AtendimentoClinico, PrescricaoClinica, PrescricaoItem
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.services.atendimento.document_context_service import carregar_contexto_entidades_documento


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


class AtendimentoDocumentDemographicsTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "atendimento-document-demographics.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_contexto_documental_prefere_tutor_atual_do_paciente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor_antigo = Tutor(nome="Tutor Antigo", ativo=1)
            tutor_atual = Tutor(nome="Tutor Atualizado", ativo=1)
            clinica = Clinica(nome="Clinica Teste")
            db.add_all([tutor_antigo, tutor_atual, clinica])
            db.flush()
            paciente = Paciente(
                nome="Luna",
                tutor_id=tutor_atual.id,
                especie="Canina",
                raca="SRD",
                sexo="Fêmea",
                ativo=1,
            )
            db.add(paciente)
            db.flush()
            atendimento_item = AtendimentoClinico(
                paciente_id=paciente.id,
                tutor_id=tutor_antigo.id,
                clinica_id=clinica.id,
                veterinario_id=1,
                data_atendimento=datetime(2026, 7, 30, 8, 0),
                status="Em atendimento",
            )
            db.add(atendimento_item)
            db.commit()

            paciente_contexto, tutor_contexto, clinica_contexto = carregar_contexto_entidades_documento(
                db,
                atendimento_item,
            )

            self.assertEqual(paciente_contexto.id, paciente.id)
            self.assertEqual(tutor_contexto.id, tutor_atual.id)
            self.assertEqual(tutor_contexto.nome, "Tutor Atualizado")
            self.assertEqual(clinica_contexto.id, clinica.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reimpressao_receita_usa_sexo_e_tutor_atualizados(self) -> None:
        paciente = Paciente(
            id=10,
            nome="Faísca",
            especie="Canina",
            raca="SRD",
            sexo="Fêmea",
            peso_kg=8.4,
            nascimento="2026-07-29", idade_fonte="idade", idade_informada="12 anos",
            idade_referencia=date(2025, 7, 30),
        )
        tutor = Tutor(id=20, nome="João Felipe Corrigido")
        atendimento_item = AtendimentoClinico(
            id=30,
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            veterinario_id=1,
            data_atendimento=datetime(2026, 7, 30, 8, 0),
            status="Em atendimento",
            criado_por_nome="Dra. Teste",
        )
        prescricao = PrescricaoClinica(orientacoes_gerais="Administrar conforme orientacao.")
        item = PrescricaoItem(
            medicamento_nome="Medicamento teste",
            dose="1 comprimido",
            frequencia="A cada 12 horas",
            duracao="5 dias",
            via="Oral",
            ordem=0,
        )

        pdf = atendimento._gerar_pdf_prescricao_bytes(
            atendimento_item,
            paciente,
            tutor,
            None,
            prescricao,
            [item],
            nome_veterinario="Dra. Teste",
        )
        texto = _pdf_text(pdf)

        self.assertIn("13a (estimada)", texto)
        self.assertIn("Faísca", texto)
        self.assertIn("Fêmea", texto)
        self.assertIn("João Felipe Corrigido", texto)

    def test_reimpressao_solicitacao_usa_sexo_e_tutor_atualizados(self) -> None:
        paciente = Paciente(
            id=11,
            nome="Mel",
            especie="Felina",
            raca="SRD",
            sexo="Fêmea",
            peso_kg=4.1,
            nascimento="2025", idade_fonte="nascimento",
        )
        tutor = Tutor(id=21, nome="Tutora Atualizada")
        atendimento_item = AtendimentoClinico(
            id=31,
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            veterinario_id=1,
            data_atendimento=datetime(2026, 7, 30, 9, 0),
            status="Em atendimento",
            criado_por_nome="Dra. Teste",
        )
        exame = Exame(
            tipo_exame="Hemograma completo",
            status="Solicitado",
            data_solicitacao=datetime(2026, 7, 30, 9, 5),
        )

        pdf = atendimento._gerar_pdf_exames_bytes(
            atendimento_item,
            paciente,
            tutor,
            None,
            [exame],
            nome_veterinario="Dra. Teste",
        )
        texto = _pdf_text(pdf)

        self.assertIn("0–1 anos (estimada pelo ano)", texto)
        self.assertIn("Mel", texto)
        self.assertIn("Fêmea", texto)
        self.assertIn("Tutora Atualizada", texto)

    def test_download_pdf_impede_cache_de_reimpressao(self) -> None:
        headers = atendimento._headers_download_pdf("receita_atendimento_30.pdf")

        self.assertIn("no-store", headers["Cache-Control"])
        self.assertIn("no-cache", headers["Cache-Control"])
        self.assertEqual(headers["Pragma"], "no-cache")
        self.assertEqual(headers["Expires"], "0")


if __name__ == "__main__":
    unittest.main()
