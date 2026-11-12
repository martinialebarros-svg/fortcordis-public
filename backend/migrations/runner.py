"""Simple versioned migration runner.

This project does not yet have an Alembic environment committed. To avoid
schema drift in stage/production, migrations are tracked in
`schema_migrations` and executed in filename order from `migrations/versions`.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import util
from pathlib import Path
from typing import Callable, List, Set

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.db.database import engine
from migrations.exceptions import MigrationDeferred

VERSIONS_DIR = Path(__file__).parent / "versions"

# Preenchido por run_migrations(); lido por get_deferred_migrations().
_LAST_DEFERRED: List[tuple[str, str]] = []


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    upgrade: Callable[[Connection, str], None]
    source: Path


def _load_migration(module_path: Path) -> Migration:
    module_name = f"migrations.versions.{module_path.stem}"
    spec = util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nao foi possivel carregar migracao: {module_path}")

    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migration_module = module

    version = getattr(migration_module, "VERSION", None)
    description = getattr(migration_module, "DESCRIPTION", "")
    upgrade = getattr(migration_module, "upgrade", None)

    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"Migracao sem VERSION valido: {module_path.name}")
    if not callable(upgrade):
        raise RuntimeError(f"Migracao sem upgrade(connection, dialect): {module_path.name}")

    return Migration(
        version=version.strip(),
        description=str(description).strip(),
        upgrade=upgrade,
        source=module_path,
    )


def _discover_migrations() -> List[Migration]:
    if not VERSIONS_DIR.exists():
        return []

    migrations: List[Migration] = []
    seen_versions: Set[str] = set()
    for file_path in sorted(VERSIONS_DIR.glob("*.py")):
        if file_path.name == "__init__.py":
            continue
        migration = _load_migration(file_path)
        if migration.version in seen_versions:
            raise RuntimeError(f"Versao de migracao duplicada: {migration.version}")
        seen_versions.add(migration.version)
        migrations.append(migration)
    return migrations


def list_migrations() -> List[Migration]:
    return _discover_migrations()


def _ensure_schema_migrations_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                description TEXT,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )


def _get_applied_versions() -> Set[str]:
    with engine.connect() as connection:
        _ensure_schema_migrations_table(connection)
        rows = connection.execute(text("SELECT version FROM schema_migrations")).fetchall()
        return {str(row[0]) for row in rows}


def get_migration_status() -> dict:
    migrations = _discover_migrations()
    ordered_versions = [migration.version for migration in migrations]
    descriptions = {migration.version: migration.description for migration in migrations}

    applied_versions: Set[str] = set()
    tracking_table_exists = False
    with engine.connect() as connection:
        inspector = inspect(connection)
        tracking_table_exists = "schema_migrations" in inspector.get_table_names()
        if tracking_table_exists:
            rows = connection.execute(text("SELECT version FROM schema_migrations")).fetchall()
            applied_versions = {str(row[0]) for row in rows}

    ordered_applied = [version for version in ordered_versions if version in applied_versions]
    pending_versions = [version for version in ordered_versions if version not in applied_versions]
    unknown_applied_versions = sorted(applied_versions.difference(ordered_versions))

    return {
        "tracking_table_exists": tracking_table_exists,
        "discovered_count": len(ordered_versions),
        "applied_count": len(ordered_applied),
        "current_version": ordered_applied[-1] if ordered_applied else None,
        "latest_version": ordered_versions[-1] if ordered_versions else None,
        "pending_versions": pending_versions,
        "pending_count": len(pending_versions),
        "unknown_applied_versions": unknown_applied_versions,
        "descriptions": descriptions,
    }


def run_migrations() -> int:
    """Run pending migrations in order. Returns number of applied migrations.

    Uma migracao que levanta `MigrationDeferred` sinaliza pendencia de dados, nao
    erro: ela e adiada (nao registrada em `schema_migrations`, portanto tentada
    de novo no proximo deploy) e as migracoes seguintes continuam sendo
    aplicadas. Qualquer outra excecao continua interrompendo a esteira, porque ai
    o estado do schema e desconhecido e seguir seria pior.
    """
    migrations = _discover_migrations()
    if not migrations:
        print("[Migrations] Nenhuma migracao encontrada.")
        return 0

    with engine.begin() as connection:
        _ensure_schema_migrations_table(connection)

    applied_versions = _get_applied_versions()
    applied_count = 0
    deferred: List[tuple[str, str]] = []
    _LAST_DEFERRED.clear()

    for migration in migrations:
        if migration.version in applied_versions:
            continue

        try:
            with engine.begin() as connection:
                dialect_name = connection.dialect.name
                print(f"[Migrations] Aplicando {migration.version} ({migration.source.name})...")
                migration.upgrade(connection, dialect_name)
                connection.execute(
                    text(
                        """
                        INSERT INTO schema_migrations (version, description)
                        VALUES (:version, :description)
                        """
                    ),
                    {"version": migration.version, "description": migration.description},
                )
        except MigrationDeferred as exc:
            # Pendencia de conciliacao de dados. A transacao ja foi revertida por
            # engine.begin(), entao nada parcial ficou aplicado.
            deferred.append((migration.version, str(exc)))
            print(f"[Migrations] ADIADA {migration.version}: {exc}")
            continue

        applied_count += 1
        applied_versions.add(migration.version)
        print(f"[Migrations] OK {migration.version}")

    if applied_count == 0:
        print("[Migrations] Nenhuma migracao pendente.")
    else:
        print(f"[Migrations] {applied_count} migracao(oes) aplicada(s).")

    _LAST_DEFERRED.extend(deferred)
    if deferred:
        print(
            f"[Migrations] {len(deferred)} migracao(oes) adiada(s) por pendencia de dados. "
            "Sera(ao) tentada(s) novamente no proximo deploy apos a conciliacao:"
        )
        for version, motivo in deferred:
            print(f"[Migrations]   - {version}: {motivo}")

    return applied_count


def get_deferred_migrations() -> List[tuple[str, str]]:
    """Migracoes adiadas por pendencia de dados na ultima execucao do runner.

    Deliberadamente NAO sonda o banco reexecutando migracoes pendentes: aplicar
    DDL especulativo para depois reverter e arriscado em producao (migracao com
    efeito nao transacional, ordem entre migracoes dependentes). Reflete o que
    `run_migrations()` de fato adiou nesta execucao do processo.
    """
    return list(_LAST_DEFERRED)
