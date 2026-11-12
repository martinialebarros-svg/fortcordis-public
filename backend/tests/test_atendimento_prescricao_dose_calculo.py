import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-prescricao-dose-calculo-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AtendimentoClinico, PrescricaoClinica, PrescricaoItem, PrescricaoItemAjuste
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.schemas.atendimento import PrescricaoItemPayload, PrescricaoPayload


class AtendimentoPrescricaoDoseCalculoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-prescricao-dose-calculo.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            PrescricaoClinica.__table__,
            PrescricaoItem.__table__,
            PrescricaoItemAjuste.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=17, nome="Dra. Teste", email="teste@example.com")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _seed_atendimento(self) -> AtendimentoClinico:
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Rex", especie="Canina", tutor_id=None, ativo=1)
        clinica = Clinica(nome="Clinica Teste", ativo=True)
        self.db.add_all([tutor, paciente, clinica])
        self.db.flush()
        paciente.tutor_id = tutor.id

        registro = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=datetime(2026, 8, 3, 9, 0),
            status="Em atendimento",
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(registro)
        self.db.commit()
        return registro

    def test_salvar_e_reler_prescricao_preserva_campos_de_dose(self) -> None:
        registro = self._seed_atendimento()

        payload = PrescricaoPayload(
            itens=[
                PrescricaoItemPayload(
                    medicamento_nome="Enalapril",
                    dose="1 comprimido",
                    dose_mg_kg="0.5",
                    peso_referencia_kg="12.4",
                    unidade_dose_calculo="comprimido",
                    concentracao_personalizada="5mg/comprimido",
                )
            ]
        )
        atendimento._sync_prescricao(self.db, registro, payload, self.user)
        self.db.commit()

        item = self.db.query(PrescricaoItem).filter_by(prescricao_id=self.db.query(PrescricaoClinica).first().id).one()
        self.assertEqual(item.dose_mg_kg, "0.5")
        self.assertEqual(item.peso_referencia_kg, "12.4")
        self.assertEqual(item.unidade_dose_calculo, "comprimido")
        self.assertEqual(item.concentracao_personalizada, "5mg/comprimido")

        mapeado = atendimento._map_prescricao_item(item)
        self.assertEqual(mapeado["dose_mg_kg"], "0.5")
        self.assertEqual(mapeado["peso_referencia_kg"], "12.4")
        self.assertEqual(mapeado["unidade_dose_calculo"], "comprimido")
        self.assertEqual(mapeado["concentracao_personalizada"], "5mg/comprimido")

    def test_item_legado_sem_campos_de_dose_le_sem_erro(self) -> None:
        registro = self._seed_atendimento()
        prescricao = PrescricaoClinica(atendimento_id=registro.id)
        self.db.add(prescricao)
        self.db.flush()
        item_legado = PrescricaoItem(
            prescricao_id=prescricao.id,
            medicamento_nome="Furosemida",
            dose="1 comprimido",
            ordem=0,
        )
        self.db.add(item_legado)
        self.db.commit()

        mapeado = atendimento._map_prescricao_item(item_legado)
        self.assertEqual(mapeado["dose_mg_kg"], "")
        self.assertEqual(mapeado["peso_referencia_kg"], "")
        self.assertEqual(mapeado["unidade_dose_calculo"], "")
        self.assertEqual(mapeado["concentracao_personalizada"], "")

    def test_unidade_dose_calculo_invalida_e_rejeitada(self) -> None:
        with self.assertRaises(ValidationError):
            PrescricaoItemPayload(medicamento_nome="Enalapril", unidade_dose_calculo="litros")


if __name__ == "__main__":
    unittest.main()
