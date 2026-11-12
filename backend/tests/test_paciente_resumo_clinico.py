import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "paciente-resumo-clinico-test-secret-key-1234567890")

from app.api.v1.endpoints import pacientes
from app.models.atendimento_clinico import AlertaClinico, AtendimentoClinico
from app.models.laudo import Laudo
from app.models.paciente import Paciente


class PacienteResumoClinicoTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "paciente-resumo-clinico.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Paciente.__table__,
            AtendimentoClinico.__table__,
            AlertaClinico.__table__,
            Laudo.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_resumo_retorna_totais_e_registros_recentes_concluidos(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            paciente = Paciente(nome="Snoopy", especie="Canina", ativo=1)
            db.add(paciente)
            db.flush()

            atendimentos = [
                AtendimentoClinico(
                    paciente_id=paciente.id,
                    veterinario_id=7,
                    data_atendimento=datetime(2026, 7, dia, 9, 0),
                    status="Concluido",
                    diagnostico_principal=f"Diagnostico {dia}",
                    criado_por_nome="Dra. Ana",
                )
                for dia in (10, 20, 25)
            ]
            db.add_all(atendimentos)
            db.add_all(
                [
                    Laudo(
                        paciente_id=paciente.id,
                        veterinario_id=7,
                        tipo="ecocardiograma",
                        titulo="Eco final",
                        status="Finalizado",
                        data_laudo=datetime(2026, 7, 21, 10, 0),
                    ),
                    Laudo(
                        paciente_id=paciente.id,
                        veterinario_id=7,
                        tipo="eletrocardiograma",
                        titulo="ECG liberado",
                        status="Liberado no portal",
                        data_laudo=datetime(2026, 7, 26, 10, 0),
                    ),
                    Laudo(
                        paciente_id=paciente.id,
                        veterinario_id=7,
                        tipo="ecocardiograma",
                        titulo="Eco em preparo",
                        status="Rascunho",
                        data_laudo=datetime(2026, 7, 27, 10, 0),
                    ),
                ]
            )
            db.add_all(
                [
                    AlertaClinico(
                        paciente_id=paciente.id,
                        tipo="risco",
                        titulo="Alergia medicamentosa",
                        gravidade="alta",
                        ativo=1,
                        data_inicio=datetime(2026, 7, 10, 8, 0),
                    ),
                    AlertaClinico(
                        paciente_id=paciente.id,
                        tipo="risco",
                        titulo="Risco cardiaco",
                        gravidade="alta",
                        ativo=1,
                        data_inicio=datetime(2026, 7, 20, 8, 0),
                    ),
                    AlertaClinico(
                        paciente_id=paciente.id,
                        tipo="doenca_cronica",
                        titulo="Doenca cronica",
                        gravidade="media",
                        ativo=1,
                        data_inicio=datetime(2026, 7, 25, 8, 0),
                    ),
                    AlertaClinico(
                        paciente_id=paciente.id,
                        tipo="risco",
                        titulo="Alerta encerrado",
                        gravidade="baixa",
                        ativo=0,
                        data_inicio=datetime(2026, 7, 27, 8, 0),
                    ),
                ]
            )
            db.commit()

            resultado = pacientes.obter_resumo_clinico_paciente(
                paciente.id,
                limite=2,
                db=db,
                current_user=SimpleNamespace(id=7),
            )

            self.assertEqual(
                resultado["totais"],
                {
                    "atendimentos": 3,
                    "laudos_concluidos": 2,
                    "alertas_ativos": 3,
                },
            )
            self.assertEqual(
                [item["diagnostico_principal"] for item in resultado["atendimentos_recentes"]],
                ["Diagnostico 25", "Diagnostico 20"],
            )
            self.assertEqual(
                [item["titulo"] for item in resultado["laudos_recentes"]],
                ["ECG liberado", "Eco final"],
            )
            self.assertEqual(
                [item["titulo"] for item in resultado["alertas_ativos"]],
                ["Doenca cronica", "Risco cardiaco"],
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_resumo_rejeita_paciente_inexistente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            with self.assertRaises(HTTPException) as raised:
                pacientes.obter_resumo_clinico_paciente(
                    999,
                    limite=4,
                    db=db,
                    current_user=SimpleNamespace(id=7),
                )
            self.assertEqual(raised.exception.status_code, 404)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
