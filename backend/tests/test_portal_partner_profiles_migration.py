import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

MIGRATION_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260729_57_portal_partner_profiles.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260729_57", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class PortalPartnerProfilesMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-partner-profiles-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_creates_partner_profiles_and_backfills_legacy_clinics(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE clinicas (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            nome TEXT NOT NULL,
                            email TEXT NULL,
                            telefone TEXT NULL,
                            cidade TEXT NULL,
                            estado TEXT NULL,
                            observacoes TEXT NULL,
                            ativo BOOLEAN NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE portal_clinic_accounts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            clinica_id INTEGER NOT NULL,
                            email_normalized TEXT NOT NULL,
                            status TEXT NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE portal_clinic_invites (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            clinica_id INTEGER NOT NULL,
                            contexto_json TEXT NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE laudos (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            clinic_id INTEGER NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE atendimentos_clinicos (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            clinica_id INTEGER NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE exames (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            laudo_id INTEGER NULL,
                            atendimento_id INTEGER NULL,
                            status TEXT NULL,
                            data_resultado DATETIME NULL
                        )
                        """
                    )
                )

                conn.execute(
                    text(
                        """
                        INSERT INTO clinicas (id, nome, email, telefone, cidade, estado, observacoes, ativo)
                        VALUES
                            (1, 'Animal Care', 'contato@animalcare.com', '85999990001', 'Fortaleza', 'CE', 'Clinica migrada', 1),
                            (2, 'Pet Movel', 'legacy@petmovel.com', '85999990002', 'Eusebio', 'CE', 'Sem conta ativa ainda', 0)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO portal_clinic_accounts (clinica_id, email_normalized, status)
                        VALUES
                            (1, 'portal@animalcare.com', 'active'),
                            (1, 'revogado@animalcare.com', 'revoked')
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO portal_clinic_invites (clinica_id, contexto_json)
                        VALUES
                            (1, '{"account_email":"convite@animalcare.com"}'),
                            (2, '{"account_email":"parceiro@petmovel.com"}')
                        """
                    )
                )
                conn.execute(text("INSERT INTO laudos (id, clinic_id) VALUES (101, 1)"))
                conn.execute(text("INSERT INTO atendimentos_clinicos (id, clinica_id) VALUES (201, 2)"))
                conn.execute(
                    text(
                        """
                        INSERT INTO exames (id, laudo_id, atendimento_id, status, data_resultado)
                        VALUES
                            (301, 101, NULL, 'Liberado no portal', '2026-07-28 10:30:00'),
                            (302, NULL, 201, 'Liberado no portal', '2026-07-28 11:45:00'),
                            (303, 101, NULL, 'Em laudo', '2026-07-28 12:00:00')
                        """
                    )
                )

                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            profile_indexes = {index["name"] for index in inspector.get_indexes("portal_partner_profiles")}
            target_indexes = {index["name"] for index in inspector.get_indexes("portal_partner_release_targets")}

            self.assertIn("portal_partner_profiles", tables)
            self.assertIn("portal_partner_release_targets", tables)
            self.assertIn("ix_portal_partner_profiles_tipo", profile_indexes)
            self.assertIn("ix_portal_partner_release_targets_partner_id", target_indexes)

            with engine.begin() as conn:
                partner_profiles = conn.execute(
                    text(
                        """
                        SELECT clinica_id, tipo, nome_exibicao, email_login, whatsapp, cidade_base, estado_base, ativo
                        FROM portal_partner_profiles
                        ORDER BY clinica_id
                        """
                    )
                ).mappings().all()
                release_targets = conn.execute(
                    text(
                        """
                        SELECT
                            pr.partner_id,
                            pp.clinica_id,
                            pr.exame_id,
                            pr.laudo_id,
                            pr.permitir_download,
                            pr.contexto_json
                        FROM portal_partner_release_targets pr
                        JOIN portal_partner_profiles pp ON pp.id = pr.partner_id
                        ORDER BY pr.exame_id
                        """
                    )
                ).mappings().all()

            self.assertEqual(len(partner_profiles), 2)
            self.assertEqual(
                [row["email_login"] for row in partner_profiles],
                ["portal@animalcare.com", "parceiro@petmovel.com"],
            )
            self.assertEqual(
                [row["tipo"] for row in partner_profiles],
                [MIGRATION.PORTAL_PARTNER_TYPE_CLINICA, MIGRATION.PORTAL_PARTNER_TYPE_CLINICA],
            )
            self.assertEqual(
                [row["whatsapp"] for row in partner_profiles],
                ["85999990001", "85999990002"],
            )
            self.assertEqual(
                [row["ativo"] for row in partner_profiles],
                [1, 0],
            )

            self.assertEqual(len(release_targets), 2)
            self.assertEqual(
                [(row["clinica_id"], row["exame_id"]) for row in release_targets],
                [(1, 301), (2, 302)],
            )
            self.assertEqual(
                [row["laudo_id"] for row in release_targets],
                [101, None],
            )
            self.assertEqual(
                [row["permitir_download"] for row in release_targets],
                [1, 1],
            )

            contexts = [json.loads(row["contexto_json"]) for row in release_targets]
            self.assertEqual(
                [context["migration_version"] for context in contexts],
                [MIGRATION.VERSION, MIGRATION.VERSION],
            )
            self.assertEqual(
                [context["legacy_clinica_id"] for context in contexts],
                [1, 2],
            )

        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
