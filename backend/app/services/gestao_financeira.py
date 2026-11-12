"""Administrative read model; no financial or clinical record is mutated.

Competence uses non-cancelled OS and their service date. Cash uses actual active
receipts and dated obligations. Missing costs/times/bank balance remain unknown.
All manual totals refer to the exact filter context validated by the API.
"""
from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, load_only

from app.models.clinica import Clinica
from app.models.financeiro import (
    ContaPagar, ContaReceber, CreditoFinanceiro, OrdemServicoPagamento, Transacao,
)
from app.models.ordem_servico import OrdemServico

ZERO = Decimal("0")
CENT = Decimal("0.01")
TZ = ZoneInfo("America/Fortaleza")
DETAIL_LIMIT = 250
SETTLED = {"pago", "recebido"}
CANCELED = {"cancelado", "cancelada", "estornado", "estornada"}


def _d(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _money(value) -> float | None:
    return None if value is None else float(_d(value).quantize(CENT, rounding=ROUND_HALF_UP))


def _day(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        # Legacy naive datetimes are local wall clock; aware PostgreSQL timestamps
        # must use the same Fortaleza calendar days as Agenda and filters.
        return value.astimezone(TZ).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _status(value) -> str:
    return str(value or "").strip().lower()


def _region(clinic) -> str:
    return ((clinic.regiao_operacional or "").strip() or (clinic.cidade or "").strip() or "Não informada") if clinic else "Não informada"


def _periods(start: date, end: date, monthly: bool):
    cursor = start
    while cursor <= end:
        if monthly:
            last = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        else:
            last = cursor + timedelta(days=6 - cursor.weekday())
        last = min(last, end)
        yield cursor, last
        cursor = last + timedelta(days=1)


def _cash_buckets(entries: list[dict], start: date, end: date, initial, monthly: bool):
    balance = _d(initial) if initial is not None else None
    result = []
    for first, last in _periods(start, end, monthly):
        row = {"inicio": first.isoformat(), "fim": last.isoformat()}
        net = ZERO
        for direction, key in (("entrada", "entradas"), ("saida", "saidas")):
            for nature, suffix in (("confirmado", "confirmadas"), ("previsto", "previstas"), ("premissa", "premissas")):
                value = sum((_d(item["valor"]) for item in entries if first <= _day(item["data"]) <= last and item["tipo"] == direction and item["natureza"] == nature), ZERO)
                row[f"{key}_{suffix}"] = _money(value)
                net += value if direction == "entrada" else -value
        if balance is not None:
            balance += net
        row["saldo_final"] = _money(balance)
        result.append(row)
    return result


def build_financial_metrics(
    db: Session, start: date, end: date, clinic_id: int | None = None,
    region: str | None = None, assumptions: dict | None = None, today: date | None = None,
) -> dict:
    """Return exact-context metrics; bounded details, full totals, read-only SQL.

    Current statuses are authoritative, including reversals. Historical filters
    are not a reconstruction of what was known at that earlier instant.
    """
    if end < start:
        raise ValueError("O fim do período deve ser igual ou posterior ao início.")
    assumptions = assumptions or {}
    today = today or datetime.now(TZ).date()
    clinics = {c.id: c for c in db.query(Clinica).options(load_only(Clinica.id, Clinica.nome, Clinica.regiao_operacional, Clinica.cidade, Clinica.ativo)).all()}
    # A fixed number of reads avoids per-OS queries. The current portfolio is
    # required to reconcile old partial receipts and future/overdue obligations.
    orders = {o.id: o for o in db.query(OrdemServico).options(load_only(OrdemServico.id, OrdemServico.numero_os, OrdemServico.agendamento_id, OrdemServico.clinica_id, OrdemServico.valor_final, OrdemServico.data_atendimento, OrdemServico.status)).all()}
    transactions = {t.id: t for t in db.query(Transacao).options(load_only(Transacao.id, Transacao.tipo, Transacao.valor, Transacao.valor_final, Transacao.status, Transacao.forma_pagamento, Transacao.data_pagamento, Transacao.data_transacao, Transacao.data_vencimento, Transacao.observacoes, Transacao.clinica_id, Transacao.agendamento_id)).all()}
    payments = db.query(OrdemServicoPagamento).options(load_only(OrdemServicoPagamento.id, OrdemServicoPagamento.ordem_servico_id, OrdemServicoPagamento.transacao_id, OrdemServicoPagamento.forma_pagamento_codigo, OrdemServicoPagamento.valor_bruto, OrdemServicoPagamento.valor_taxa, OrdemServicoPagamento.valor_liquido, OrdemServicoPagamento.data_recebimento)).order_by(OrdemServicoPagamento.data_recebimento, OrdemServicoPagamento.id).all()
    credits = db.query(CreditoFinanceiro).options(load_only(CreditoFinanceiro.id, CreditoFinanceiro.valor, CreditoFinanceiro.ordem_servico_id, CreditoFinanceiro.data_movimento)).filter(
        CreditoFinanceiro.status == "Ativo", CreditoFinanceiro.origem == "consumo_credito_os",
    ).all()
    receivables = db.query(ContaReceber).options(load_only(ContaReceber.id, ContaReceber.clinica_id, ContaReceber.valor, ContaReceber.data_vencimento, ContaReceber.data_recebimento, ContaReceber.status, ContaReceber.agendamento_id)).all()
    payables = db.query(ContaPagar).options(load_only(ContaPagar.id, ContaPagar.clinica_id, ContaPagar.valor, ContaPagar.data_vencimento, ContaPagar.data_pagamento, ContaPagar.status)).all()

    def matches(cid):
        return (clinic_id is None or cid == clinic_id) and (not region or _region(clinics.get(cid)).casefold() == region.strip().casefold())

    def clinic_info(cid):
        clinic = clinics.get(cid)
        return {"clinica_id": cid, "clinica_nome": clinic.nome if clinic else (f"Clínica #{cid} não localizada" if cid is not None else "Sem clínica vinculada"), "regiao": _region(clinic)}

    active_orders = {oid: o for oid, o in orders.items() if _status(o.status) not in CANCELED}
    scoped_orders = {oid: o for oid, o in active_orders.items() if matches(o.clinica_id)}
    cohort = [o for o in scoped_orders.values() if _day(o.data_atendimento) is not None and start <= _day(o.data_atendimento) <= end]
    cohort.sort(key=lambda o: (_day(o.data_atendimento), o.id))
    cohort_ids = {o.id for o in cohort}
    payment_issues = []
    seen = set()
    candidate_payments = defaultdict(list)
    payment_transaction_ids = {p.transacao_id for p in payments if p.transacao_id is not None}
    for p in payments:
        tx = transactions.get(p.transacao_id)
        if not tx or tx.tipo != "entrada" or _status(tx.status) not in SETTLED:
            if p.ordem_servico_id in cohort_ids and (not tx or _status(tx.status) not in CANCELED):
                payment_issues.append("Há pagamentos sem transação recebida válida; não comprovam caixa nem prazo.")
            continue
        if _status(p.forma_pagamento_codigo) == "credito":
            if p.ordem_servico_id in cohort_ids:
                payment_issues.append("Crédito registrado como forma de pagamento foi excluído do dinheiro recebido.")
            continue
        key = (p.ordem_servico_id, p.transacao_id)
        if key in seen:
            if p.ordem_servico_id in cohort_ids:
                payment_issues.append("Há pagamentos repetidos para a mesma OS e transação; considerados uma única vez.")
            continue
        seen.add(key)
        if _d(p.valor_bruto) <= 0 or _day(p.data_recebimento) is None or _day(p.data_recebimento) > today:
            if p.ordem_servico_id in cohort_ids:
                payment_issues.append("Há pagamentos com valor ou data inconsistente; não compõem os indicadores.")
            continue
        candidate_payments[p.transacao_id].append(p)
    active_payments = defaultdict(list)
    for tx_id, group in candidate_payments.items():
        # A shared transaction can allocate different OS, but never more than its
        # gross amount. Do not invent an allocation for inconsistent records.
        if sum((_d(p.valor_bruto) for p in group), ZERO) > _d(transactions[tx_id].valor) + CENT:
            if any(p.ordem_servico_id in cohort_ids for p in group):
                payment_issues.append("Há rateio de pagamento maior que a transação de origem; excluído até conferência.")
            continue
        net_values_known = all(p.valor_liquido is not None for p in group)
        if net_values_known and transactions[tx_id].valor_final is not None and sum((_d(p.valor_liquido) for p in group), ZERO) > _d(transactions[tx_id].valor_final) + CENT:
            if any(p.ordem_servico_id in cohort_ids for p in group):
                payment_issues.append("Valor líquido alocado excede a transação de origem; recebimento inconsistente excluído até conferência.")
            continue
        for p in group:
            active_payments[p.ordem_servico_id].append(p)
    credit_by_os = defaultdict(lambda: ZERO)
    for credit in credits:
        if credit.valor is not None and credit.valor < 0 and _day(credit.data_movimento) and _day(credit.data_movimento) <= today:
            credit_by_os[credit.ordem_servico_id] += -_d(credit.valor)

    receivables_by_appointment = defaultdict(list)
    for account in receivables:
        if account.agendamento_id is not None and _status(account.status) not in CANCELED:
            receivables_by_appointment[account.agendamento_id].append(account)
    orders_by_appointment = defaultdict(list)
    for order in active_orders.values():
        if order.agendamento_id is not None:
            orders_by_appointment[order.agendamento_id].append(order)

    def associated_accounts(order):
        # An ambiguous legacy appointment cannot establish an installment split.
        if order.agendamento_id is None or len(orders_by_appointment[order.agendamento_id]) != 1:
            return []
        return receivables_by_appointment.get(order.agendamento_id, [])

    # Old transaction rows can be linked to an OS without a payment allocation.
    # They prove a cash movement but do not establish which installment/OS debt
    # remains. Never schedule the entire OS again from an unproven balance.
    unallocated_by_os = defaultdict(list)
    transaction_order = {}
    for tx in transactions.values():
        if tx.id in payment_transaction_ids or tx.tipo != "entrada" or _status(tx.status) not in SETTLED:
            continue
        if re.fullmatch(r"Gerado do (pagamento|recebimento) da conta #(\d+)", str(tx.observacoes or "").strip()):
            continue
        marker = re.search(r"(?:^|;)OS_ID=(\d+)(?:;|$)", str(tx.observacoes or ""))
        linked = [active_orders[int(marker.group(1))]] if marker and int(marker.group(1)) in active_orders else orders_by_appointment.get(tx.agendamento_id, [])
        if len(linked) == 1:
            unallocated_by_os[linked[0].id].append(tx)
            transaction_order[tx.id] = linked[0]

    order_state = {}
    for oid, order in scoped_orders.items():
        amount = _d(order.valor_final) if order.valor_final is not None and _d(order.valor_final) >= 0 else None
        paid = sum((_d(p.valor_bruto) for p in active_payments[oid]), ZERO)
        credit = min(credit_by_os[oid], amount) if amount is not None else credit_by_os[oid]
        legacy = _status(order.status) in SETTLED and (amount is None or paid + credit + CENT < amount)
        balance = None if legacy or amount is None or unallocated_by_os[oid] else max(amount - paid - credit, ZERO)
        order_state[oid] = {"amount": amount, "paid": paid, "credit": credit, "balance": balance, "legacy": legacy}

    # Contribution is competence, never the sum of cash receipts. Percentage
    # assumptions explicitly replace observed fee estimates, rather than add to
    # them. Fleet fixed costs are deliberately not classified as variable costs.
    invalid_values = [o for o in cohort if order_state[o.id]["amount"] is None]
    revenue = sum((order_state[o.id]["amount"] for o in cohort if order_state[o.id]["amount"] is not None), ZERO)
    contribution_gaps = []
    if invalid_values:
        contribution_gaps.append(f"{len(invalid_values)} OS têm valor ausente ou negativo; receita observada é parcial e contribuição não calculável.")
    costs = {}
    for name, assumption_key in (("tributos", "tributos_percentual"), ("repasses", "repasses_percentual")):
        rate = assumptions.get(assumption_key)
        costs[name] = revenue * _d(rate) / 100 if rate is not None else None
        if rate is None:
            contribution_gaps.append(f"Informe {name} aplicáveis ao período, inclusive 0 quando confirmado.")
    actual_fees = ZERO
    fees_complete = True
    for order in cohort:
        state = order_state[order.id]
        if state["amount"] is None:
            fees_complete = False
            continue
        remaining = max(state["amount"] - state["credit"], ZERO)
        for p in active_payments[order.id]:
            applied = min(_d(p.valor_bruto), remaining)
            if p.valor_taxa is None or _d(p.valor_taxa) < 0:
                fees_complete = False
            else:
                actual_fees += _d(p.valor_taxa) * applied / _d(p.valor_bruto)
            remaining -= applied
        if remaining > CENT or state["legacy"]:
            fees_complete = False
    estimated_fees = assumptions.get("taxas_percentual")
    costs["taxas"] = revenue * _d(estimated_fees) / 100 if estimated_fees is not None else actual_fees if fees_complete else None
    if costs["taxas"] is None:
        contribution_gaps.append("Taxas dos pagamentos ainda não recebidos ou legados desconhecidas; informe uma taxa estimada para toda a receita.")
    costs["custos_variaveis"] = _d(assumptions["custos_variaveis"]) if assumptions.get("custos_variaveis") is not None else None
    if costs["custos_variaveis"] is None:
        contribution_gaps.append("Informe custos variáveis totais atribuídos ao período; cada rota deve ser contada uma vez.")
    hours = []
    for key, label in (("horas_atendimento", "atendimentos"), ("horas_laudos", "laudos"), ("horas_deslocamento", "deslocamentos")):
        value = assumptions.get(key)
        hours.append(_d(value) if value is not None else None)
        if value is None:
            contribution_gaps.append(f"Tempo efetivo de {label} não registrado; informe o total estimado do período.")
    total_hours = sum(hours, ZERO) if all(h is not None for h in hours) else None
    contribution = revenue - sum(costs.values(), ZERO) if not invalid_values and all(v is not None for v in costs.values()) else None
    if total_hours == 0:
        contribution_gaps.append("O tempo total é zero; contribuição por hora não é calculável.")
    contribution_details = [{"os_id": o.id, "numero_os": o.numero_os, **clinic_info(o.clinica_id), "data_atendimento": _day(o.data_atendimento).isoformat(), "valor": _money(order_state[o.id]["amount"]), "status": o.status} for o in cohort]
    missing_service_dates = sum(1 for o in scoped_orders.values() if o.data_atendimento is None)
    if missing_service_dates:
        contribution_gaps.append(f"{missing_service_dates} OS sem data de atendimento não podem ser atribuídas a um período.")
    contribution_result = {
        "receita_competencia": _money(revenue), "receita_parcial": bool(invalid_values or missing_service_dates), **{key: _money(value) for key, value in costs.items()},
        "taxas_observadas": _money(actual_fees), "taxas_fonte": "premissa" if estimated_fees is not None else "pagamentos ativos" if fees_complete else "incompleta",
        "horas_totais": _money(total_hours), "valor": _money(contribution),
        "por_hora": _money(contribution / total_hours) if contribution is not None and total_hours is not None and total_hours > 0 else None,
        "estimado": any(assumptions.get(k) is not None for k in ("tributos_percentual", "repasses_percentual", "taxas_percentual", "custos_variaveis", "horas_atendimento", "horas_laudos", "horas_deslocamento")),
        "lacunas": contribution_gaps,
        "formula": "(Receita das OS não canceladas pela data de atendimento − tributos − taxas − repasses − custos variáveis) ÷ horas de atendimento, laudos e deslocamento. Contribuição antes de custos fixos e remuneração do proprietário.",
        "detalhes": contribution_details[:DETAIL_LIMIT], "total_registros": len(cohort), "detalhes_limitados": len(cohort) > DETAIL_LIMIT,
    }

    # The cohort is service date in the chosen period. Delay is amount-weighted
    # per actual installment; a partial receipt does not settle the whole OS.
    delay_value = ZERO
    delay_amount = ZERO
    total_paid = total_credit = open_balance = overdue = no_due = ZERO
    receipt_details = []
    receipt_gaps = list(payment_issues)
    legacy_count = 0
    for order in cohort:
        state = order_state[order.id]
        service_day = _day(order.data_atendimento)
        remaining_for_delay = max(state["amount"] - state["credit"], ZERO) if state["amount"] is not None else ZERO
        weighted = local_amount = ZERO
        for payment in active_payments[order.id]:
            applied = min(_d(payment.valor_bruto), remaining_for_delay)
            days = (_day(payment.data_recebimento) - service_day).days
            # Negative delay is a valid prepayment, explicitly retained.
            weighted += applied * days
            local_amount += applied
            remaining_for_delay -= applied
        delay_value += weighted
        delay_amount += local_amount
        total_paid += state["paid"]
        total_credit += state["credit"]
        balance = state["balance"]
        legacy_count += int(state["legacy"])
        dated = []
        if balance is not None:
            open_balance += balance
            to_allocate = balance
            pending_accounts = [a for a in associated_accounts(order) if _status(a.status) not in SETTLED]
            if len(pending_accounts) > 1 and state["paid"] + state["credit"] > 0:
                pending_accounts = []
                receipt_gaps.append("Pagamento parcial sem vínculo direto à parcela: vencimentos incertos; saldo mantido sem data até conferência.")
            for account in sorted(pending_accounts, key=lambda a: (_day(a.data_vencimento) or date.max, a.id)):
                if _status(account.status) in SETTLED or to_allocate <= 0:
                    continue
                allocated = min(max(_d(account.valor), ZERO), to_allocate)
                due = _day(account.data_vencimento)
                if due:
                    dated.append(due)
                    if due < today:
                        overdue += allocated
                    to_allocate -= allocated
            no_due += to_allocate
        receipt_details.append({
            "os_id": order.id, "numero_os": order.numero_os, **clinic_info(order.clinica_id),
            "valor": _money(state["amount"]), "recebido": _money(state["paid"]), "credito": _money(state["credit"]),
            "saldo_aberto": _money(balance), "data_atendimento": service_day.isoformat(),
            "prazo_medio_dias": _money(weighted / local_amount) if local_amount else None,
            "vencimento": min(dated).isoformat() if dated else None, "legacy": state["legacy"],
        })
    if invalid_values:
        receipt_gaps.append("OS com valor ausente ou negativo foram excluídas dos saldos calculáveis.")
    if any(unallocated_by_os[o.id] for o in cohort):
        receipt_gaps.append("Transação ligada à OS sem composição de pagamento: saldo e prazo incompletos; não foi presumida quitação.")
    if legacy_count:
        receipt_gaps.append(f"{legacy_count} OS pagas sem composição ativa suficiente: prazo e saldo não comprovados; não foram inventados recebimentos.")
    if no_due:
        receipt_gaps.append("Parte das OS em aberto não tem vencimento vinculado; não foi classificada como vencida.")
    receipt_result = {
        "prazo_medio_dias": _money(delay_value / delay_amount) if delay_amount else None,
        "valor_recebido_bruto": _money(total_paid), "valor_base_prazo": _money(delay_amount),
        "credito_utilizado": _money(total_credit), "saldo_aberto": _money(open_balance), "vencido": _money(overdue),
        "sem_vencimento": _money(no_due), "os_pagas_sem_comprovante": legacy_count,
        "saldo_parcial": any(order_state[o.id]["balance"] is None for o in cohort),
        "data_referencia": today.isoformat(), "lacunas": sorted(set(receipt_gaps)),
        "formula": "Σ(valor aplicado de cada pagamento ativo × dias entre atendimento e recebimento) ÷ Σ(valores aplicados). Coorte: OS pela data de atendimento no período; saldos e vencidos refletem o estado atual. Antecipações podem ter prazo negativo; crédito não é dinheiro. Sem data de faturamento própria.",
        "detalhes": receipt_details[:DETAIL_LIMIT], "total_registros": len(receipt_details), "detalhes_limitados": len(receipt_details) > DETAIL_LIMIT,
    }

    partner_values = defaultdict(lambda: ZERO)
    partner_counts = defaultdict(int)
    monthly_values = defaultdict(lambda: ZERO)
    month_totals = defaultdict(lambda: ZERO)
    for order in cohort:
        if order_state[order.id]["amount"] is None:
            continue
        partner_values[order.clinica_id] += _d(order.valor_final)
        partner_counts[order.clinica_id] += 1
        month = _day(order.data_atendimento).strftime("%Y-%m")
        monthly_values[(month, order.clinica_id)] += _d(order.valor_final)
        month_totals[month] += _d(order.valor_final)
    partners = []
    for cid, value in sorted(partner_values.items(), key=lambda pair: (-pair[1], pair[0] or 0)):
        clinic = clinics.get(cid)
        partners.append({**clinic_info(cid), "ativa": bool(clinic.ativo) if clinic else None, "receita": _money(value), "participacao_pct": _money(value / revenue * 100) if revenue > 0 and not invalid_values else None, "quantidade_os": partner_counts[cid]})
    linked_values = sorted((v for cid, v in partner_values.items() if cid is not None), reverse=True)
    concentration = {
        "base": "Competência: valor final de OS não canceladas pela data de atendimento; inclui clínicas inativas e valores sem vínculo.",
        "receita_total": _money(revenue), "parcial": bool(invalid_values or missing_service_dates),
        **{f"top{n}_pct": _money(sum(linked_values[:n], ZERO) / revenue * 100) if len(linked_values) >= n and revenue > 0 and not invalid_values else None for n in (1, 3, 5)},
        "clinicas": partners,
        "evolucao": [{"mes": month, "clinica_id": cid, "clinica_nome": clinic_info(cid)["clinica_nome"], "receita": _money(value), "participacao_pct": _money(value / month_totals[month] * 100) if month_totals[month] > 0 and not invalid_values else None} for (month, cid), value in sorted(monthly_values.items(), key=lambda pair: (pair[0][0], pair[0][1] or 0))],
        "lacunas": (["Receita parcial: há OS com valor ausente ou negativo; participações e Top N indisponíveis."] if invalid_values else []) + ([f"{missing_service_dates} OS sem data de atendimento fora da base de competência."] if missing_service_dates else []) + (["Valores sem clínica permanecem no denominador e são mostrados separadamente; Top N considera parceiros vinculados."] if None in partner_values else []),
    }

    entries = []
    cash_gaps = []
    unscheduled = ZERO

    def add_entry(source, item_id, cid, when, direction, value, nature, *, os_id=None, overdue_item=False):
        if value is None or _d(value) < 0:
            if matches(cid):
                cash_gaps.append("Movimento com valor líquido ausente ou inválido foi excluído; caixa parcial.")
            return
        if when is None or not matches(cid) or _d(value) == 0:
            return
        original = when
        # Past-due obligations enter the first projected day as backlog, with
        # their original due date retained; do not make overdue debt disappear.
        if nature == "previsto" and when < start:
            when = start
            overdue_item = original < today
        if start <= when <= end:
            entries.append({"fonte": source, "id": item_id, "os_id": os_id, "clinica_id": cid,
                            "data": when.isoformat(), "data_original": original.isoformat(), "tipo": direction,
                            "valor": _money(value), "natureza": nature, "vencido": overdue_item})

    # Explicit generated-account markers are strong links. Do not fuzzy-match
    # descriptions/amounts: unrelated financial records may look identical.
    account_transactions = defaultdict(list)
    for tx in transactions.values():
        marker = re.fullmatch(r"Gerado do (pagamento|recebimento) da conta #(\d+)", str(tx.observacoes or "").strip())
        if marker:
            kind = "pagar" if marker.group(1) == "pagamento" else "receber"
            key = (kind, int(marker.group(2)))
            account_transactions[key].append(tx)
    valid_payment_groups = {
        tx_id: [p for p in candidate_payments.get(tx_id, []) if p in active_payments[p.ordem_servico_id]]
        for tx_id in payment_transaction_ids
    }
    rejected_account_keys = set()
    rejected_mirror_ids = set()
    for account in receivables:
        key = ("receber", account.id)
        mirrors = account_transactions.get(key, [])
        paid_mirrors = [tx for tx in mirrors if _status(tx.status) in SETTLED and tx.tipo == "entrada"]
        if len(paid_mirrors) <= 1:
            continue
        # Repeated account settlement can create several transactions for one
        # obligation. Validate their OS allocations together before filters or
        # cash entries; choosing an arbitrary allocation would invent ownership.
        first = min(paid_mirrors, key=lambda tx: tx.id)
        group = [p for tx in paid_mirrors for p in valid_payment_groups.get(tx.id, [])]
        gross = sum((_d(p.valor_bruto) for p in group), ZERO)
        net = (sum((_d(p.valor_liquido) for p in group), ZERO)
               if all(p.valor_liquido is not None and _d(p.valor_liquido) >= 0 for p in group) else None)
        gross_limits = [value for value in (account.valor, first.valor) if value is not None and _d(value) >= 0]
        exceeds_gross = any(gross > _d(limit) + CENT for limit in gross_limits)
        exceeds_net = net is not None and first.valor_final is not None and net > _d(first.valor_final) + CENT
        if exceeds_gross or exceeds_net:
            rejected_account_keys.add(key)
            rejected_mirror_ids.update(tx.id for tx in mirrors)
            if matches(account.clinica_id) or any(p.ordem_servico_id in orders and matches(orders[p.ordem_servico_id].clinica_id) for p in group):
                cash_gaps.append("Composição OS entre espelhos da mesma conta excede a obrigação ou sua transação de origem; grupo excluído do caixa até conferência.")
    reconciled_transaction_ids = set(rejected_mirror_ids)
    allocated_transaction_net = {}
    for tx_id in payment_transaction_ids:
        if tx_id in rejected_mirror_ids:
            continue
        tx = transactions.get(tx_id)
        group = candidate_payments.get(tx_id, [])
        valid_group = valid_payment_groups[tx_id]
        if valid_group:
            # Allocated OS rows are authoritative for clinic filters and fees.
            # Reconcile the whole transaction before applying clinic/date
            # filters; a generated receivable may retain an unallocated part.
            allocated_transaction_net[tx_id] = (
                sum((_d(p.valor_liquido) for p in valid_group), ZERO)
                if all(p.valor_liquido is not None and _d(p.valor_liquido) >= 0
                       and p.ordem_servico_id in orders for p in valid_group)
                else None
            )
            for payment in valid_group:
                order = orders.get(payment.ordem_servico_id)
                if order is not None:
                    add_entry("pagamento_os", payment.id, order.clinica_id, _day(payment.data_recebimento), "entrada", payment.valor_liquido, "confirmado", os_id=order.id)
            reconciled_transaction_ids.add(tx_id)
        elif tx and _status(tx.status) in SETTLED:
            # Ambiguous payment ledger must not silently become an independent
            # receipt in another path; show the gap rather than double/count it.
            reconciled_transaction_ids.add(tx_id)
            if matches(tx.clinica_id) or any(p.ordem_servico_id in scoped_orders for p in group):
                cash_gaps.append("Recebimentos com vínculo de pagamento inconsistente foram excluídos até conferência.")

    # Planned OS balance is scheduled only when a real receivable supplies due
    # dates. Otherwise it remains explicitly unscheduled and outside projection.
    linked_receivable_ids = set()
    for oid, order in scoped_orders.items():
        state = order_state[oid]
        associated = associated_accounts(order)
        linked_receivable_ids.update(a.id for a in associated)
        balance = state["balance"]
        if balance is None:
            if state["legacy"]:
                cash_gaps.append("OS pagas sem composição ativa suficiente não viraram entradas futuras nem caixa confirmado.")
            if unallocated_by_os[oid]:
                cash_gaps.append("Transação ligada à OS sem composição de pagamento: pendência não projetada para evitar duplicidade.")
            if state["amount"] is None:
                cash_gaps.append("OS com valor ausente ou negativo não compõe entradas previstas.")
            continue
        remaining = balance
        pending_accounts = [a for a in associated if _status(a.status) not in SETTLED]
        if len(pending_accounts) > 1 and state["paid"] + state["credit"] > 0:
            pending_accounts = []
            cash_gaps.append("Pagamento parcial sem vínculo direto à parcela: saldo sem distribuição por vencimento até conferência.")
        for account in sorted(pending_accounts, key=lambda a: (_day(a.data_vencimento) or date.max, a.id)):
            if _status(account.status) in SETTLED or remaining <= 0:
                continue
            allocated = min(max(_d(account.valor), ZERO), remaining)
            due = _day(account.data_vencimento)
            if due:
                add_entry("saldo_os", order.id, order.clinica_id, due, "entrada", allocated, "previsto", os_id=order.id)
                remaining -= allocated
        unscheduled += remaining

    for kind, accounts, direction, settled_date in (("pagar", payables, "saida", "data_pagamento"), ("receber", receivables, "entrada", "data_recebimento")):
        for account in accounts:
            if _status(account.status) in CANCELED:
                continue
            if (kind, account.id) in rejected_account_keys:
                continue
            mirrors = account_transactions.get((kind, account.id), [])
            paid_mirrors = [tx for tx in mirrors if _status(tx.status) in SETTLED and tx.tipo == direction]
            if (kind == "receber" and account.id in linked_receivable_ids
                    and _status(account.status) not in SETTLED):
                # The OS balance owns pending obligations. A received account
                # is separate cash evidence unless its own transaction is
                # already represented by an OS payment allocation.
                reconciled_transaction_ids.update(tx.id for tx in mirrors)
                continue
            if paid_mirrors:
                # The account is one obligation; the first generated settled
                # transaction is its evidence, not N repeated endpoint clicks.
                first = min(paid_mirrors, key=lambda t: t.id)
                value = first.valor_final
                allocated_mirror_ids = {tx.id for tx in paid_mirrors if tx.id in payment_transaction_ids}
                if allocated_mirror_ids:
                    if any(tx_id not in allocated_transaction_net for tx_id in allocated_mirror_ids):
                        # Inconsistent allocations have already been excluded;
                        # the account must not reintroduce that transaction.
                        reconciled_transaction_ids.update(tx.id for tx in mirrors)
                        continue
                    # Repeated settlement calls produce exact mirrors of this
                    # one account. OS allocations can reference any mirror,
                    # not necessarily the oldest transaction chosen above.
                    net_values = [allocated_transaction_net[tx_id] for tx_id in allocated_mirror_ids]
                    allocated = sum(net_values, ZERO) if all(value is not None for value in net_values) else None
                    value = (max(_d(value) - allocated, ZERO)
                             if value is not None and allocated is not None else None)
                when = _day(first.data_pagamento or first.data_transacao)
                if when and when <= today:
                    add_entry(f"conta_{kind}", account.id, account.clinica_id, when, direction, value, "confirmado")
                reconciled_transaction_ids.update(tx.id for tx in mirrors)
                if len(paid_mirrors) > 1 and matches(account.clinica_id):
                    cash_gaps.append("Conta com várias transações automáticas de quitação: considerada uma obrigação; confira os registros duplicados.")
            elif _status(account.status) in SETTLED:
                if mirrors:
                    reconciled_transaction_ids.update(tx.id for tx in mirrors)
                    if matches(account.clinica_id):
                        cash_gaps.append("Conta quitada com transação cancelada ou não recebida: estorno prevalece; caixa não confirmado.")
                    continue
                when = _day(getattr(account, settled_date))
                if when and when <= today:
                    add_entry(f"conta_{kind}", account.id, account.clinica_id, when, direction, account.valor, "confirmado")
                elif matches(account.clinica_id):
                    cash_gaps.append("Há conta quitada sem data válida; não foi atribuída a um dia de caixa.")
            else:
                add_entry(f"conta_{kind}", account.id, account.clinica_id, _day(account.data_vencimento), direction, account.valor, "previsto")
                reconciled_transaction_ids.update(tx.id for tx in mirrors)

    for tx in transactions.values():
        if tx.id in reconciled_transaction_ids or _status(tx.status) in CANCELED or tx.tipo not in {"entrada", "saida"}:
            continue
        if _status(tx.forma_pagamento) == "credito":
            continue
        linked_order = transaction_order.get(tx.id)
        if linked_order and active_payments[linked_order.id]:
            if matches(linked_order.clinica_id):
                cash_gaps.append("Transação sem composição concorrente com pagamentos da mesma OS: excluída do caixa até conferência.")
            continue
        tx_clinic_id = linked_order.clinica_id if linked_order else tx.clinica_id
        if _status(tx.status) in SETTLED:
            when = _day(tx.data_pagamento or tx.data_transacao)
            if when and when <= today:
                add_entry("transacao", tx.id, tx_clinic_id, when, tx.tipo, tx.valor_final, "confirmado")
        else:
            due = _day(tx.data_vencimento)
            if due:
                add_entry("transacao", tx.id, tx_clinic_id, due, tx.tipo, tx.valor_final, "previsto")
            elif matches(tx.clinica_id):
                cash_gaps.append("Há transações pendentes sem vencimento; não foram distribuídas na projeção.")

    # Manually entered movements are scenario assumptions, not new financial
    # transactions. Monthly recurrence keeps the original day with month-end cap.
    for index, movement in enumerate(assumptions.get("movimentos") or []):
        first = _day(movement.get("data"))
        if first is None:
            continue
        occurrences = [first]
        if movement.get("recorrencia") == "mensal":
            occurrences = []
            month_start = date(max(first, start).year, max(first, start).month, 1)
            while month_start <= end:
                occurrence = date(month_start.year, month_start.month, min(first.day, calendar.monthrange(month_start.year, month_start.month)[1]))
                if occurrence >= first:
                    occurrences.append(occurrence)
                month_start = date(month_start.year + int(month_start.month == 12), month_start.month % 12 + 1, 1)
        for when in occurrences:
            # Assumptions already belong to this exact filter context. Region
            # filters must not reject an assumption due to absent clinic FK.
            if start <= when <= end and _d(movement.get("valor")) > 0:
                entries.append({"fonte": "premissa", "id": index + 1, "os_id": None, "clinica_id": clinic_id,
                                "data": when.isoformat(), "data_original": when.isoformat(), "tipo": movement["tipo"],
                                "valor": _money(movement["valor"]), "natureza": "premissa", "vencido": False,
                                "descricao": movement.get("descricao")})
    entries.sort(key=lambda row: (row["data"], row["fonte"], row["id"]))
    initial = assumptions.get("saldo_inicial")
    if initial is None:
        cash_gaps.append("Saldo inicial não informado; os fluxos são apresentados sem inventar saldo bancário.")
    if not assumptions.get("despesas_completas", False):
        cash_gaps.append("Despesas completas não foram confirmadas; confira custos recorrentes, tributos e outras saídas e inclua premissas quando necessário.")
    if unscheduled:
        cash_gaps.append("OS abertas sem vencimento não entram nas entradas previstas; informe previsão explícita de recebimento nas premissas sem duplicar contas já datadas.")
    if clinic_id is not None or region:
        cash_gaps.append("Recorte por clínica/região exclui valores sem vínculo; o saldo informado deve pertencer ao mesmo recorte, não ao banco inteiro.")
    if any(row["tipo"] == "entrada" and row["natureza"] == "previsto" for row in entries):
        cash_gaps.append("Entradas previstas estão em valor nominal; taxas futuras desconhecidas precisam de premissa explícita de saída.")
    weeks = _cash_buckets(entries, start, end, initial, False)
    months = _cash_buckets(entries, start, end, initial, True)
    cash_totals = {key: _money(sum((_d(row[key]) for row in weeks), ZERO)) for key in ("entradas_confirmadas", "entradas_previstas", "saidas_confirmadas", "saidas_previstas", "entradas_premissas", "saidas_premissas")}
    cash = {
        "saldo_inicial": _money(initial), "saldo_final": weeks[-1]["saldo_final"] if weeks else _money(initial),
        **cash_totals, "pendencias_sem_data": _money(unscheduled), "parcial": bool(cash_gaps),
        "semanas": weeks, "meses": months, "detalhes": entries[:DETAIL_LIMIT], "total_registros": len(entries),
        "detalhes_limitados": len(entries) > DETAIL_LIMIT, "lacunas": sorted(set(cash_gaps)),
        "formula": "Saldo informado na abertura do período + entradas confirmadas, previstas e premissas − saídas confirmadas, previstas e premissas. Previstas são valores nominais ainda não líquidos de taxas desconhecidas. Vencidas antes do período entram no primeiro dia como pendências; não são recebimentos garantidos.",
    }
    return {"contribuicao": contribution_result, "recebimento": receipt_result, "concentracao": concentration, "caixa": cash}
