import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-history-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import (
    AlertaClinico,
    AnexoAtendimento,
    AtendimentoClinico,
    EvolucaoClinica,
    PrescricaoClinica,
    PrescricaoItem,
)
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente


class AtendimentoPatientPrescriptionHistoryTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "atendimento-history.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Paciente.__table__,
            AtendimentoClinico.__table__,
            AlertaClinico.__table__,
            EvolucaoClinica.__table__,
            AnexoAtendimento.__table__,
            Exame.__table__,
            Laudo.__table__,
            PrescricaoClinica.__table__,
            PrescricaoItem.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_historico_retorna_series_de_temperatura_fc_fr(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            paciente = Paciente(nome="Bidu", especie="Canina", ativo=1)
            db.add(paciente)
            db.flush()
            antigo = AtendimentoClinico(
                paciente_id=paciente.id,
                veterinario_id=7,
                data_atendimento=datetime(2026, 5, 1, 9, 0),
                status="Concluido",
                criado_por_nome="Dra. Ana",
                temperatura=38.2,
                frequencia_cardiaca=110,
                frequencia_respiratoria=24,
            )
            # Atendimento sem sinais vitais registrados - nao deve aparecer em
            # nenhuma das series (mesma regra que "pesos" ja aplica ao peso).
            sem_vitais = AtendimentoClinico(
                paciente_id=paciente.id,
                veterinario_id=7,
                data_atendimento=datetime(2026, 6, 1, 9, 0),
                status="Concluido",
                criado_por_nome="Dra. Ana",
            )
            recente = AtendimentoClinico(
                paciente_id=paciente.id,
                veterinario_id=7,
                data_atendimento=datetime(2026, 7, 15, 9, 0),
                status="Concluido",
                criado_por_nome="Dra. Ana",
                temperatura=39.1,
                frequencia_cardiaca=130,
                frequencia_respiratoria=32,
            )
            db.add_all([antigo, sem_vitais, recente])
            db.commit()

            resultado = atendimento.historico_paciente(
                paciente.id,
                limite=10,
                db=db,
                current_user=SimpleNamespace(id=7),
            )

            self.assertEqual(
                [item["temperatura"] for item in resultado["temperaturas"]],
                [39.1, 38.2],
            )
            self.assertEqual(
                [item["frequencia_cardiaca"] for item in resultado["frequencias_cardiacas"]],
                [130, 110],
            )
            self.assertEqual(
                [item["frequencia_respiratoria"] for item in resultado["frequencias_respiratorias"]],
                [32, 24],
            )
            self.assertEqual(
                {item["atendimento_id"] for item in resultado["temperaturas"]},
                {antigo.id, recente.id},
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_historico_retorna_receitas_separadas_por_atendimento_sem_n_plus_one(self) -> None:
        tmpdir, db, engine = self._build_session()
        statements = []

        def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", _capture_sql)
        try:
            paciente = Paciente(nome="Luna", especie="Canina", ativo=1)
            db.add(paciente)
            db.flush()
            primeiro = AtendimentoClinico(
                paciente_id=paciente.id,
                veterinario_id=7,
                data_atendimento=datetime(2026, 7, 10, 9, 0),
                status="Concluido",
                criado_por_nome="Dra. Ana",
            )
            segundo = AtendimentoClinico(
                paciente_id=paciente.id,
                veterinario_id=7,
                data_atendimento=datetime(2026, 7, 15, 9, 0),
                status="Em atendimento",
                criado_por_nome="Dra. Ana",
            )
            db.add_all([primeiro, segundo])
            db.flush()

            receita_antiga = PrescricaoClinica(
                atendimento_id=primeiro.id,
                orientacoes_gerais="Manter repouso.",
                retorno_dias=7,
            )
            receita_nova = PrescricaoClinica(
                atendimento_id=segundo.id,
                orientacoes_gerais="Monitorar frequencia respiratoria.",
                retorno_dias=14,
            )
            db.add_all([receita_antiga, receita_nova])
            db.flush()
            db.add_all(
                [
                    PrescricaoItem(
                        prescricao_id=receita_antiga.id,
                        medicamento_nome="Pimobendan",
                        dose="0,25 mg/kg",
                        frequencia="A cada 12 horas",
                        via="Oral",
                        ordem=0,
                    ),
                    PrescricaoItem(
                        prescricao_id=receita_nova.id,
                        medicamento_nome="Furosemida",
                        dose="2 mg/kg",
                        frequencia="A cada 12 horas",
                        via="Oral",
                        ordem=0,
                    ),
                ]
            )
            db.commit()

            statements.clear()
            resultado = atendimento.historico_paciente(
                paciente.id,
                limite=10,
                db=db,
                current_user=SimpleNamespace(id=7),
            )

            self.assertEqual([item["id"] for item in resultado["atendimentos"]], [segundo.id, primeiro.id])
            self.assertEqual(resultado["atendimentos"][0]["prescricao"]["itens"][0]["medicamento_nome"], "Furosemida")
            self.assertEqual(resultado["atendimentos"][1]["prescricao"]["itens"][0]["medicamento_nome"], "Pimobendan")
            self.assertEqual(resultado["atendimentos"][1]["prescricao"]["retorno_dias"], 7)

            prescription_selects = [
                sql
                for sql in statements
                if sql.lstrip().startswith("select")
                and ("prescricoes_clinicas" in sql or "prescricoes_itens" in sql)
            ]
            self.assertEqual(len(prescription_selects), 2)
        finally:
            event.remove(engine, "before_cursor_execute", _capture_sql)
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
