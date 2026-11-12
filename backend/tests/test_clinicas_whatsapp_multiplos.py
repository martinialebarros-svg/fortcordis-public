import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "clinicas-whatsapp-multiplos-test-secret-key-1234567890")

from app.api.v1.endpoints import clinicas
from app.models.clinica import Clinica


class ClinicasWhatsappMultiplosTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "clinicas-whatsapp-multiplos.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Clinica.__table__.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_criar_e_atualizar_clinica_persiste_lista_normalizada(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            criada = clinicas.criar_clinica(
                clinicas.ClinicaCreate(
                    nome="Animal Care",
                    telefone="(85) 3222-1111",
                    whatsapps=["(85) 98888-1111", "85 97777-2222", "(85) 98888-1111"],
                    cidade="Fortaleza",
                    estado="CE",
                ),
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(criada["whatsapps"], ["85988881111", "85977772222"])

            atualizada = clinicas.atualizar_clinica(
                criada["id"],
                clinicas.ClinicaUpdate(
                    nome="Animal Care",
                    whatsapps=["(85) 96666-3333"],
                ),
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(atualizada["whatsapps"], ["85966663333"])
            persistida = db.query(Clinica).filter(Clinica.id == criada["id"]).one()
            self.assertEqual(persistida.whatsapps, ["85966663333"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_atualizacao_focada_de_whatsapps_preserva_demais_dados(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            criada = clinicas.criar_clinica(
                clinicas.ClinicaCreate(
                    nome="Clinica Integrada",
                    telefone="(85) 3222-1111",
                    whatsapps=["(85) 98888-1111"],
                    email="contato@clinica.test",
                    endereco="Rua dos Animais",
                    cidade="Fortaleza",
                    estado="CE",
                ),
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            atualizada = clinicas.atualizar_whatsapps_clinica(
                criada["id"],
                clinicas.ClinicaWhatsappsUpdate(
                    whatsapps=["(85) 95555-4444", "(85) 94444-5555"],
                ),
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(
                atualizada["whatsapps"],
                ["85955554444", "85944445555"],
            )
            self.assertEqual(atualizada["nome"], "Clinica Integrada")
            self.assertEqual(atualizada["email"], "contato@clinica.test")
            self.assertEqual(atualizada["endereco"], "Rua dos Animais")
            self.assertEqual(atualizada["cidade"], "Fortaleza")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_serializacao_legada_usa_telefone_quando_lista_esta_vazia(self) -> None:
        clinica = Clinica(nome="Legada", telefone="(85) 98888-0000", whatsapps=[])
        payload = clinicas._serialize_clinica(clinica)
        self.assertEqual(payload["whatsapps"], ["85988880000"])

    def test_migracao_preenche_primeiro_whatsapp_com_telefone_existente(self) -> None:
        migration_path = BACKEND_DIR / "migrations" / "versions" / "20260719_50_clinicas_multiplos_whatsapps.py"
        spec = importlib.util.spec_from_file_location("migration_clinicas_whatsapps", migration_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_engine(f"sqlite:///{Path(tmpdir) / 'migration.db'}")
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "CREATE TABLE clinicas ("
                            "id INTEGER PRIMARY KEY, nome TEXT NOT NULL, telefone TEXT)"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO clinicas (id, nome, telefone) "
                            "VALUES (1, 'Animal Care', '(85) 98888-0000')"
                        )
                    )
                    module.upgrade(connection, "sqlite")
                    whatsapps = connection.execute(
                        text("SELECT whatsapps FROM clinicas WHERE id = 1")
                    ).scalar_one()

                self.assertEqual(json.loads(whatsapps), ["(85) 98888-0000"])
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
