import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.api.v1.endpoints import laudos, portal
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_partner import PortalPartnerProfile, PortalPartnerReleaseTarget
from app.models.tutor import Tutor

MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "20260923_90_portal_partner_downloaded_at.py"
SPEC = importlib.util.spec_from_file_location("migration_20260923_90", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class LaudosPortalDownloadIndicatorTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'downloads.db'}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Laudo.__table__,
            Exame.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerReleaseTarget.__table__,
        ):
            table.create(engine, checkfirst=True)
        return tmpdir, sessionmaker(bind=engine)(), engine

    def test_listagem_expoe_downloads_de_clinica_e_veterinario(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Monica", ativo=1)
            db.add(tutor)
            db.flush()
            paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
            partner = PortalPartnerProfile(
                tipo="veterinario", nome_exibicao="Dra. Ana", ativo=True
            )
            db.add_all([paciente, partner])
            db.flush()
            laudo = Laudo(
                paciente_id=paciente.id,
                veterinario_id=7,
                veterinario_parceiro_id=partner.id,
                tipo="ecocardiograma",
                titulo="Laudo Luna",
                status=PORTAL_RELEASED_STATUS,
            )
            db.add(laudo)
            db.flush()
            clinic_download = datetime(2026, 9, 23, 9, 10)
            partner_download = datetime(2026, 9, 23, 9, 20)
            exame = Exame(
                laudo_id=laudo.id,
                paciente_id=paciente.id,
                tipo_exame="Ecocardiograma",
                status=PORTAL_RELEASED_STATUS,
                visualizado_portal_em=clinic_download,
            )
            db.add(exame)
            db.flush()
            db.add(
                PortalPartnerReleaseTarget(
                    partner_id=partner.id,
                    exame_id=exame.id,
                    laudo_id=laudo.id,
                    downloaded_at=partner_download,
                )
            )
            db.commit()

            payload = laudos.listar_laudos(
                db=db, current_user=SimpleNamespace(id=7)
            )
            item = next(row for row in payload["items"] if row["id"] == laudo.id)
            self.assertEqual(item["portal_clinica_baixado_em"], clinic_download.isoformat())
            self.assertEqual(item["portal_veterinario_baixado_em"], partner_download.isoformat())
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_download_do_veterinario_e_idempotente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            target = PortalPartnerReleaseTarget(partner_id=19, exame_id=31, laudo_id=41)
            db.add(target)
            db.commit()

            portal._marcar_exame_visualizado_no_portal(db, 31, "parceiro", 19)
            db.refresh(target)
            first_download = target.downloaded_at
            self.assertIsNotNone(first_download)

            portal._marcar_exame_visualizado_no_portal(db, 31, "parceiro", 19)
            db.refresh(target)
            self.assertEqual(target.downloaded_at, first_download)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_migracao_adiciona_coluna_idempotentemente(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'migration.db'}")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("CREATE TABLE portal_partner_release_targets (id INTEGER PRIMARY KEY)")
                )
                MIGRATION.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")
            columns = {
                column["name"]
                for column in inspect(engine).get_columns("portal_partner_release_targets")
            }
            self.assertIn("downloaded_at", columns)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
