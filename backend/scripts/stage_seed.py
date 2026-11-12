from __future__ import annotations

from sqlalchemy import inspect, text

from app.db.database import SessionLocal, engine
from app.services import clinical_phrase_service, exam_catalog_service


SUMMARY_TABLES = [
    "usuarios",
    "clinicas",
    "servicos",
    "tutores",
    "pacientes",
    "agendamentos",
    "laudos",
    "exames",
    "atendimentos_clinicos",
    "ordens_servico",
    "transacoes",
    "contas_receber",
    "contas_pagar",
    "catalogo_exames",
    "painel_exames",
    "frases_qualitativas",
    "frases_atendimento_clinico",
]


def _seed_dynamic_content() -> None:
    db = SessionLocal()
    try:
        exam_report = exam_catalog_service.ensure_exam_catalog_seeded(db)
        clinical_report = clinical_phrase_service.ensure_clinical_phrases_seeded(db)

        print("[stage-seed] exam_catalog:", exam_report)
        print("[stage-seed] clinical_phrases:", clinical_report)
    finally:
        db.close()


def _print_summary() -> None:
    with engine.connect() as conn:
        inspector = inspect(conn)
        existing_tables = set(inspector.get_table_names())
        print("[stage-seed] Summary counts:")
        for table_name in SUMMARY_TABLES:
            if table_name not in existing_tables:
                print(f"  - {table_name}: table missing")
                continue
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
            print(f"  - {table_name}: {count}")


def main() -> None:
    _seed_dynamic_content()
    _print_summary()


if __name__ == "__main__":
    main()
