from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Sequence, Set

from sqlalchemy import bindparam, inspect, text
from sqlalchemy.engine import Connection

from app.db.database import engine


@dataclass
class ResetPlan:
    targets: Dict[str, Set[int]]
    prefix: str
    cutoff_text: str | None
    cutoff_enabled: bool

    def total_rows(self) -> int:
        return sum(len(ids) for ids in self.targets.values())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset stage test data identified by prefix (default: TST-)."
    )
    parser.add_argument("--prefix", default="TST-", help="Prefix marker for test records.")
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=0,
        help="Only match prefixed rows created before now - N days when created_at exists.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions. Without this flag, script runs in dry-run mode.",
    )
    return parser.parse_args()


def _load_table_columns(conn: Connection) -> Dict[str, Set[str]]:
    inspector = inspect(conn)
    table_columns: Dict[str, Set[str]] = {}
    for table in inspector.get_table_names():
        table_columns[table] = {col["name"] for col in inspector.get_columns(table)}
    return table_columns


def _existing_prefix_columns(
    table_columns: Dict[str, Set[str]],
    table: str,
    candidate_columns: Sequence[str],
) -> List[str]:
    existing = table_columns.get(table, set())
    return [column for column in candidate_columns if column in existing]


def _select_ids_by_prefix(
    conn: Connection,
    table_columns: Dict[str, Set[str]],
    table: str,
    candidate_columns: Sequence[str],
    prefix_like: str,
    cutoff_text: str | None,
) -> Set[int]:
    if table not in table_columns or "id" not in table_columns[table]:
        return set()

    prefix_columns = _existing_prefix_columns(table_columns, table, candidate_columns)
    if not prefix_columns:
        return set()

    where_parts = [
        f"LOWER(COALESCE({column}, '')) LIKE :prefix_like"
        for column in prefix_columns
    ]
    params = {"prefix_like": prefix_like}
    where_sql = "(" + " OR ".join(where_parts) + ")"

    if cutoff_text and "created_at" in table_columns[table]:
        where_sql = f"{where_sql} AND CAST(created_at AS TEXT) <= :cutoff_text"
        params["cutoff_text"] = cutoff_text

    rows = conn.execute(text(f"SELECT id FROM {table} WHERE {where_sql}"), params).fetchall()
    return {int(row[0]) for row in rows}


def _select_ids_by_fk(
    conn: Connection,
    table_columns: Dict[str, Set[str]],
    table: str,
    fk_column: str,
    fk_ids: Iterable[int],
) -> Set[int]:
    fk_ids_list = sorted({int(item) for item in fk_ids if item is not None})
    if not fk_ids_list:
        return set()
    if table not in table_columns or "id" not in table_columns[table]:
        return set()
    if fk_column not in table_columns[table]:
        return set()

    stmt = text(f"SELECT id FROM {table} WHERE {fk_column} IN :fk_ids").bindparams(
        bindparam("fk_ids", expanding=True)
    )
    rows = conn.execute(stmt, {"fk_ids": fk_ids_list}).fetchall()
    return {int(row[0]) for row in rows}


def _select_fk_values(
    conn: Connection,
    table_columns: Dict[str, Set[str]],
    table: str,
    fk_column: str,
    row_ids: Iterable[int],
) -> Set[int]:
    row_ids_list = sorted({int(item) for item in row_ids if item is not None})
    if not row_ids_list:
        return set()
    if table not in table_columns or fk_column not in table_columns[table]:
        return set()

    stmt = text(
        f"SELECT DISTINCT {fk_column} FROM {table} "
        f"WHERE {fk_column} IS NOT NULL AND id IN :row_ids"
    ).bindparams(bindparam("row_ids", expanding=True))
    rows = conn.execute(stmt, {"row_ids": row_ids_list}).fetchall()
    return {int(row[0]) for row in rows if row[0] is not None}


def _merge_targets(targets: Dict[str, Set[int]], table: str, ids: Iterable[int]) -> None:
    ids_set = {int(item) for item in ids if item is not None}
    if not ids_set:
        return
    targets.setdefault(table, set()).update(ids_set)


def _build_plan(conn: Connection, prefix: str, older_than_days: int) -> ResetPlan:
    table_columns = _load_table_columns(conn)

    if not prefix.strip():
        raise ValueError("Prefix cannot be empty.")

    prefix_like = f"{prefix.strip().lower()}%"
    cutoff_text: str | None = None
    if older_than_days > 0:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        cutoff_text = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")

    targets: Dict[str, Set[int]] = {}

    pacientes_ids = _select_ids_by_prefix(
        conn,
        table_columns,
        "pacientes",
        ("nome", "nome_key", "microchip", "observacoes"),
        prefix_like,
        cutoff_text,
    )
    _merge_targets(targets, "pacientes", pacientes_ids)

    tutores_ids = _select_ids_by_prefix(
        conn,
        table_columns,
        "tutores",
        ("nome", "nome_key", "telefone", "whatsapp", "email"),
        prefix_like,
        cutoff_text,
    )
    tutores_from_pacientes = _select_fk_values(
        conn, table_columns, "pacientes", "tutor_id", pacientes_ids
    )
    _merge_targets(targets, "tutores", tutores_from_pacientes)
    _merge_targets(targets, "tutores", tutores_ids)

    clinicas_ids = _select_ids_by_prefix(
        conn,
        table_columns,
        "clinicas",
        ("nome", "cnpj", "telefone", "email", "endereco", "cidade", "bairro", "cep"),
        prefix_like,
        cutoff_text,
    )
    _merge_targets(targets, "clinicas", clinicas_ids)

    servicos_ids = _select_ids_by_prefix(
        conn,
        table_columns,
        "servicos",
        ("nome", "descricao", "categoria"),
        prefix_like,
        cutoff_text,
    )
    _merge_targets(targets, "servicos", servicos_ids)

    agendamentos_ids = set()
    agendamentos_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "agendamentos",
        ("paciente", "tutor", "telefone", "servico", "clinica", "observacoes", "criado_por_nome"),
        prefix_like,
        cutoff_text,
    )
    agendamentos_ids |= _select_ids_by_fk(
        conn, table_columns, "agendamentos", "paciente_id", pacientes_ids
    )
    agendamentos_ids |= _select_ids_by_fk(
        conn, table_columns, "agendamentos", "clinica_id", clinicas_ids
    )
    agendamentos_ids |= _select_ids_by_fk(
        conn, table_columns, "agendamentos", "servico_id", servicos_ids
    )
    _merge_targets(targets, "agendamentos", agendamentos_ids)

    laudos_ids = set()
    laudos_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "laudos",
        ("titulo", "descricao", "diagnostico", "observacoes", "criado_por_nome", "medico_solicitante"),
        prefix_like,
        cutoff_text,
    )
    laudos_ids |= _select_ids_by_fk(conn, table_columns, "laudos", "paciente_id", pacientes_ids)
    laudos_ids |= _select_ids_by_fk(conn, table_columns, "laudos", "agendamento_id", agendamentos_ids)
    _merge_targets(targets, "laudos", laudos_ids)

    atendimentos_ids = set()
    atendimentos_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "atendimentos_clinicos",
        (
            "queixa_principal",
            "anamnese",
            "exame_fisico",
            "dados_clinicos",
            "diagnostico_principal",
            "diagnostico_secundario",
            "diagnostico_diferencial",
            "plano_terapeutico",
            "motivo_retorno",
            "observacoes",
            "criado_por_nome",
        ),
        prefix_like,
        cutoff_text,
    )
    atendimentos_ids |= _select_ids_by_fk(
        conn, table_columns, "atendimentos_clinicos", "paciente_id", pacientes_ids
    )
    atendimentos_ids |= _select_ids_by_fk(
        conn, table_columns, "atendimentos_clinicos", "tutor_id", targets.get("tutores", set())
    )
    atendimentos_ids |= _select_ids_by_fk(
        conn, table_columns, "atendimentos_clinicos", "clinica_id", clinicas_ids
    )
    atendimentos_ids |= _select_ids_by_fk(
        conn, table_columns, "atendimentos_clinicos", "agendamento_id", agendamentos_ids
    )
    _merge_targets(targets, "atendimentos_clinicos", atendimentos_ids)

    exames_ids = set()
    exames_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "exames",
        ("tipo_exame", "painel_exame_nome", "categoria_exame", "resultado", "observacoes", "criado_por_nome"),
        prefix_like,
        cutoff_text,
    )
    exames_ids |= _select_ids_by_fk(conn, table_columns, "exames", "paciente_id", pacientes_ids)
    exames_ids |= _select_ids_by_fk(conn, table_columns, "exames", "laudo_id", laudos_ids)
    exames_ids |= _select_ids_by_fk(conn, table_columns, "exames", "atendimento_id", atendimentos_ids)
    _merge_targets(targets, "exames", exames_ids)

    ordens_ids = set()
    ordens_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "ordens_servico",
        ("numero_os", "status", "observacoes", "criado_por_nome"),
        prefix_like,
        cutoff_text,
    )
    ordens_ids |= _select_ids_by_fk(conn, table_columns, "ordens_servico", "paciente_id", pacientes_ids)
    ordens_ids |= _select_ids_by_fk(conn, table_columns, "ordens_servico", "agendamento_id", agendamentos_ids)
    ordens_ids |= _select_ids_by_fk(conn, table_columns, "ordens_servico", "clinica_id", clinicas_ids)
    ordens_ids |= _select_ids_by_fk(conn, table_columns, "ordens_servico", "servico_id", servicos_ids)
    _merge_targets(targets, "ordens_servico", ordens_ids)

    transacoes_ids = set()
    transacoes_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "transacoes",
        ("paciente_nome", "descricao", "observacoes", "criado_por_nome"),
        prefix_like,
        cutoff_text,
    )
    transacoes_ids |= _select_ids_by_fk(conn, table_columns, "transacoes", "paciente_id", pacientes_ids)
    transacoes_ids |= _select_ids_by_fk(conn, table_columns, "transacoes", "agendamento_id", agendamentos_ids)
    transacoes_ids |= _select_ids_by_fk(conn, table_columns, "transacoes", "clinica_id", clinicas_ids)
    _merge_targets(targets, "transacoes", transacoes_ids)

    contas_receber_ids = set()
    contas_receber_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "contas_receber",
        ("descricao", "cliente", "categoria", "observacoes"),
        prefix_like,
        cutoff_text,
    )
    contas_receber_ids |= _select_ids_by_fk(
        conn, table_columns, "contas_receber", "paciente_id", pacientes_ids
    )
    contas_receber_ids |= _select_ids_by_fk(
        conn, table_columns, "contas_receber", "agendamento_id", agendamentos_ids
    )
    contas_receber_ids |= _select_ids_by_fk(
        conn, table_columns, "contas_receber", "clinica_id", clinicas_ids
    )
    _merge_targets(targets, "contas_receber", contas_receber_ids)

    contas_pagar_ids = set()
    contas_pagar_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "contas_pagar",
        ("descricao", "fornecedor", "categoria", "observacoes"),
        prefix_like,
        cutoff_text,
    )
    contas_pagar_ids |= _select_ids_by_fk(
        conn, table_columns, "contas_pagar", "clinica_id", clinicas_ids
    )
    _merge_targets(targets, "contas_pagar", contas_pagar_ids)

    imagens_laudo_ids = set()
    imagens_laudo_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "imagens_laudo",
        ("nome_arquivo", "descricao", "caminho_arquivo"),
        prefix_like,
        cutoff_text,
    )
    imagens_laudo_ids |= _select_ids_by_fk(conn, table_columns, "imagens_laudo", "laudo_id", laudos_ids)
    _merge_targets(targets, "imagens_laudo", imagens_laudo_ids)

    alertas_ids = set()
    alertas_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "alertas_clinicos",
        ("titulo", "descricao", "tipo", "gravidade"),
        prefix_like,
        cutoff_text,
    )
    alertas_ids |= _select_ids_by_fk(
        conn, table_columns, "alertas_clinicos", "paciente_id", pacientes_ids
    )
    _merge_targets(targets, "alertas_clinicos", alertas_ids)

    anexos_ids = set()
    anexos_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "anexos_atendimentos",
        ("tipo", "descricao", "url", "nome_original", "caminho_arquivo"),
        prefix_like,
        cutoff_text,
    )
    anexos_ids |= _select_ids_by_fk(
        conn, table_columns, "anexos_atendimentos", "atendimento_id", atendimentos_ids
    )
    anexos_ids |= _select_ids_by_fk(
        conn, table_columns, "anexos_atendimentos", "exame_id", exames_ids
    )
    _merge_targets(targets, "anexos_atendimentos", anexos_ids)

    evolucoes_ids = set()
    evolucoes_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "evolucoes_clinicas",
        ("descricao", "sinais_vitais", "responsavel_nome"),
        prefix_like,
        cutoff_text,
    )
    evolucoes_ids |= _select_ids_by_fk(
        conn, table_columns, "evolucoes_clinicas", "atendimento_id", atendimentos_ids
    )
    _merge_targets(targets, "evolucoes_clinicas", evolucoes_ids)

    prescricoes_ids = set()
    prescricoes_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "prescricoes_clinicas",
        ("orientacoes_gerais",),
        prefix_like,
        cutoff_text,
    )
    prescricoes_ids |= _select_ids_by_fk(
        conn, table_columns, "prescricoes_clinicas", "atendimento_id", atendimentos_ids
    )
    _merge_targets(targets, "prescricoes_clinicas", prescricoes_ids)

    prescricao_itens_ids = set()
    prescricao_itens_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "prescricoes_itens",
        ("medicamento_nome", "apresentacao_selecionada", "dose", "frequencia", "duracao", "via", "instrucoes"),
        prefix_like,
        cutoff_text,
    )
    prescricao_itens_ids |= _select_ids_by_fk(
        conn, table_columns, "prescricoes_itens", "prescricao_id", prescricoes_ids
    )
    _merge_targets(targets, "prescricoes_itens", prescricao_itens_ids)

    prescricao_ajustes_ids = set()
    prescricao_ajustes_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "prescricao_item_ajustes",
        ("campo", "valor_anterior", "valor_novo", "motivo", "responsavel_nome"),
        prefix_like,
        cutoff_text,
    )
    prescricao_ajustes_ids |= _select_ids_by_fk(
        conn,
        table_columns,
        "prescricao_item_ajustes",
        "prescricao_item_id",
        prescricao_itens_ids,
    )
    prescricao_ajustes_ids |= _select_ids_by_fk(
        conn, table_columns, "prescricao_item_ajustes", "atendimento_id", atendimentos_ids
    )
    _merge_targets(targets, "prescricao_item_ajustes", prescricao_ajustes_ids)

    clinica_deslocamentos_ids = set()
    clinica_deslocamentos_ids |= _select_ids_by_fk(
        conn,
        table_columns,
        "clinica_deslocamentos",
        "origem_clinica_id",
        clinicas_ids,
    )
    clinica_deslocamentos_ids |= _select_ids_by_fk(
        conn,
        table_columns,
        "clinica_deslocamentos",
        "destino_clinica_id",
        clinicas_ids,
    )
    _merge_targets(targets, "clinica_deslocamentos", clinica_deslocamentos_ids)

    precos_servicos_clinica_ids = set()
    precos_servicos_clinica_ids |= _select_ids_by_fk(
        conn, table_columns, "precos_servicos_clinica", "clinica_id", clinicas_ids
    )
    precos_servicos_clinica_ids |= _select_ids_by_fk(
        conn, table_columns, "precos_servicos_clinica", "servico_id", servicos_ids
    )
    _merge_targets(targets, "precos_servicos_clinica", precos_servicos_clinica_ids)

    precos_servicos_ids = _select_ids_by_fk(
        conn, table_columns, "precos_servicos", "servico_id", servicos_ids
    )
    _merge_targets(targets, "precos_servicos", precos_servicos_ids)

    veiculos_ids = _select_ids_by_prefix(
        conn,
        table_columns,
        "veiculos_frota",
        ("nome", "placa", "tipo_combustivel", "criado_por_nome"),
        prefix_like,
        cutoff_text,
    )
    _merge_targets(targets, "veiculos_frota", veiculos_ids)

    telemetria_ids = _select_ids_by_fk(
        conn, table_columns, "telemetria_frota_mensal", "veiculo_id", veiculos_ids
    )
    _merge_targets(targets, "telemetria_frota_mensal", telemetria_ids)

    custos_frota_ids = set()
    custos_frota_ids |= _select_ids_by_prefix(
        conn,
        table_columns,
        "custos_frota",
        ("categoria", "forma_rateio", "veiculo", "descricao", "observacoes", "criado_por_nome"),
        prefix_like,
        cutoff_text,
    )
    custos_frota_ids |= _select_ids_by_fk(
        conn, table_columns, "custos_frota", "clinica_id", clinicas_ids
    )
    custos_frota_ids |= _select_ids_by_fk(
        conn, table_columns, "custos_frota", "veiculo_id", veiculos_ids
    )
    _merge_targets(targets, "custos_frota", custos_frota_ids)

    return ResetPlan(
        targets=targets,
        prefix=prefix,
        cutoff_text=cutoff_text,
        cutoff_enabled=bool(cutoff_text),
    )


def _delete_ids(conn: Connection, table: str, ids: Iterable[int]) -> int:
    ids_list = sorted({int(item) for item in ids if item is not None})
    if not ids_list:
        return 0

    stmt = text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    result = conn.execute(stmt, {"ids": ids_list})
    return int(result.rowcount or 0)


def _print_plan(plan: ResetPlan) -> None:
    mode = "prefix + created_at cutoff" if plan.cutoff_enabled else "prefix only"
    print("[reset-stage] Selection mode:", mode)
    if plan.cutoff_text:
        print("[reset-stage] Cutoff:", plan.cutoff_text, "(UTC, textual compare)")
    print("[reset-stage] Prefix:", plan.prefix)

    if plan.total_rows() == 0:
        print("[reset-stage] No matching rows found.")
        return

    print("[reset-stage] Rows marked for deletion:")
    for table in sorted(plan.targets):
        count = len(plan.targets[table])
        if count:
            print(f"  - {table}: {count}")
    print(f"[reset-stage] Total rows marked: {plan.total_rows()}")


def _apply_plan(conn: Connection, plan: ResetPlan) -> Dict[str, int]:
    deletion_order = [
        "prescricao_item_ajustes",
        "prescricoes_itens",
        "prescricoes_clinicas",
        "anexos_atendimentos",
        "evolucoes_clinicas",
        "alertas_clinicos",
        "imagens_laudo",
        "exames",
        "laudos",
        "ordens_servico",
        "agendamentos",
        "transacoes",
        "contas_receber",
        "contas_pagar",
        "atendimentos_clinicos",
        "clinica_deslocamentos",
        "custos_frota",
        "telemetria_frota_mensal",
        "veiculos_frota",
        "precos_servicos_clinica",
        "precos_servicos",
        "pacientes",
        "tutores",
        "clinicas",
        "servicos",
    ]

    deleted_counts: Dict[str, int] = {}
    for table in deletion_order:
        ids = plan.targets.get(table, set())
        if not ids:
            continue
        deleted_counts[table] = _delete_ids(conn, table, ids)
    return deleted_counts


def main() -> int:
    args = _parse_args()
    if args.older_than_days < 0:
        raise ValueError("--older-than-days must be >= 0")

    with engine.begin() as conn:
        plan = _build_plan(conn, prefix=args.prefix, older_than_days=args.older_than_days)
        _print_plan(plan)

        if not args.apply:
            print("[reset-stage] Dry-run complete. Re-run with --apply to execute.")
            return 0

        if plan.total_rows() == 0:
            print("[reset-stage] Nothing to delete.")
            return 0

        deleted = _apply_plan(conn, plan)
        print("[reset-stage] Applied deletions:")
        for table in sorted(deleted):
            print(f"  - {table}: {deleted[table]}")
        print("[reset-stage] Total rows deleted:", sum(deleted.values()))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
