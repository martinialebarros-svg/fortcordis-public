"""Read-only opportunities to complete one day using existing route evidence.

No provider requests, ledger calls, reservations or cache writes occur here.
The ordinary offer engine validates every candidate; the only replacement is
an in-memory directed travel resolver populated by one bounded matrix read.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.schemas.agenda_preferencia import AgendaPreferencia
from app.services.logistica_service import _cache_only_route_available


def buscar_oportunidades_dia(payload, db, current_user):
    from app.api.v1.endpoints import agenda

    if not any(agenda._usuario_tem_papel(current_user, role) for role in (
        "admin", "recepcao", "secretaria", "veterinario", "cardiologista",
    )):
        raise HTTPException(403, "Consulta de oportunidades disponivel somente para a equipe da agenda.")
    data_iso = agenda._extract_date_filter(payload.data)
    if not data_iso:
        raise HTTPException(422, "Data invalida. Use YYYY-MM-DD.")
    hoje = datetime.now(agenda.LOCAL_TZ).date()
    regras = agenda._obter_regras_rota_agenda(db)
    policy = regras["route_policy"]
    historico_inicio = hoje - timedelta(days=60)
    resposta = {
        "ok": True, "enabled": bool(policy.get("regional_transition_enabled")),
        "data": data_iso, "items": [], "sem_estimativa": 0,
        "total_clinicas_recorrentes": 0,
        "historico": {"inicio": historico_inicio.isoformat(),
                      "fim": (hoje - timedelta(days=1)).isoformat(), "dias": 60},
        "fonte_estimativa": "cache", "consultas_google": 0,
    }
    if not resposta["enabled"]:
        resposta["motivo"] = "A transicao regional esta desativada nas regras da agenda."
        return resposta
    if data_iso < hoje.isoformat():
        resposta["motivo"] = "Selecione hoje ou uma data futura."
        return resposta

    # The history describes completed local appointment days, never creation
    # dates, future bookings, cancelled appointments or domiciliary locations.
    inicio = datetime.combine(historico_inicio, time.min, agenda.LOCAL_TZ)
    fim = datetime.combine(hoje, time.min, agenda.LOCAL_TZ)
    volumes = defaultdict(int)
    dias = defaultdict(set)
    registros = db.query(Agendamento.clinica_id, Agendamento.inicio).filter(
        Agendamento.status == "Realizado", Agendamento.clinica_id.isnot(None),
        or_(Agendamento.origem_atendimento == "clinica_parceira", Agendamento.origem_atendimento.is_(None)),
        Agendamento.inicio >= inicio, Agendamento.inicio < fim,
    ).all()
    for clinica_id, instante in registros:
        local = agenda._to_local_naive(agenda._coerce_datetime(instante))
        if local is None or not historico_inicio <= local.date() < hoje:
            continue
        volumes[clinica_id] += 1
        dias[clinica_id].add(local.date())

    clinicas = db.query(Clinica).filter(Clinica.ativo.is_(True), Clinica.id.in_(list(dias))).all()
    clinicas_por_id = {c.id: c for c in clinicas}
    resposta["total_clinicas_recorrentes"] = len(clinicas)
    ativos = agenda._listar_agendamentos_ativos_do_dia(db, data_iso)
    ancoras = [item for item in ativos if agenda._status_conta_como_ancora(item.get("status"))]
    if not ancoras:
        resposta["motivo"] = "Ainda nao ha um atendimento de referencia neste dia para calcular as oportunidades."
        return resposta
    ids_ativos = {item["clinica_id"] for item in ativos if item.get("clinica_id")}
    extras = db.query(Clinica).filter(Clinica.id.in_(list(ids_ativos - set(clinicas_por_id)))).all()
    clinicas_por_id.update({c.id: c for c in extras})
    todos_ids = list(clinicas_por_id)
    matriz = db.query(ClinicaDeslocamento).filter(
        ClinicaDeslocamento.perfil == "comercial",
        or_(and_(ClinicaDeslocamento.origem_clinica_id.in_(list(ids_ativos)),
                 ClinicaDeslocamento.destino_clinica_id.in_(todos_ids)),
            and_(ClinicaDeslocamento.origem_clinica_id.in_(todos_ids),
                 ClinicaDeslocamento.destino_clinica_id.in_(list(ids_ativos)))),
    ).all()
    rotas = {}
    for row in matriz:
        origem = clinicas_por_id.get(row.origem_clinica_id)
        destino = clinicas_por_id.get(row.destino_clinica_id)
        if origem and destino and _cache_only_route_available(row, origem=origem, destino=destino) and row.duracao_min > 0:
            rotas[(origem.id, destino.id)] = row

    def resolver_viagem(_db, *, origem, destino, **_kwargs):
        if agenda._destinos_operacionais_mesma_referencia(origem, destino):
            return 0, "mesmo_destino"
        if not origem or not destino or origem.get("tipo") != "clinica_parceira" or destino.get("tipo") != "clinica_parceira":
            return None, "sem_estimativa"
        row = rotas.get((origem.get("entity_id"), destino.get("entity_id")))
        if row is None:
            return None, "sem_estimativa"
        return int(row.duracao_min), "manual" if row.manual_override else str(row.fonte)

    # No candidate is offered before the day's first anchor: this comparison
    # completes an existing day and cannot silently initiate a paid base lookup.
    primeiro_fim = min(item["fim"] for item in ancoras)
    if primeiro_fim.date().isoformat() != data_iso:
        resposta["motivo"] = "O atendimento de referencia termina fora desta data. Revise a agenda antes de consultar oportunidades."
        return resposta
    depois_primeiro = primeiro_fim.strftime("%H:%M")
    preferencia = AgendaPreferencia(data_inicio=data_iso, data_fim=data_iso, hora_inicio=depois_primeiro)
    contexto_dia = {
        "regras": regras, "agendamentos": ativos, "somente_cache": True,
        "janela": agenda._obter_janela_funcionamento_data(db, data_iso),
        "bloqueios": agenda._listar_bloqueios_ativos(db),
        "duracao_minutos": agenda._resolver_duracao_servico(db, servico_id=payload.servico_id, fallback_minutos=30),
        "destinos": {c.id: agenda._criar_destino_operacional_clinica(c) for c in clinicas},
    }

    def acrescimo(slot):
        custo = int(slot.get("tempo_deslocamento_total_min") or 0)
        anterior_id = int((slot.get("anterior") or {}).get("clinica_id") or 0)
        proximo_id = int((slot.get("proximo") or {}).get("clinica_id") or 0)
        if not anterior_id or not proximo_id or anterior_id == proximo_id:
            return custo
        direto = rotas.get((anterior_id, proximo_id))
        return max(0, custo - int(direto.duracao_min)) if direto is not None else None

    resultados = []
    for clinica in clinicas:
        if clinica.latitude is None or clinica.longitude is None:
            resposta["sem_estimativa"] += 1
            continue
        sugestao = agenda._sugerir_horarios_agenda(
            agenda.SugestaoHorarioPayload(data=data_iso, clinica_id=clinica.id,
                servico_id=payload.servico_id, intervalo_minutos=15, limite=50, preferencia=preferencia),
            db, current_user, resolver_viagem=resolver_viagem, contexto_dia=contexto_dia,
        )
        slots = sugestao.get("items", [])
        if not slots:
            if sugestao.get("teve_rota_sem_estimativa"):
                resposta["sem_estimativa"] += 1
            continue
        slots_com_custo = [(slot, acrescimo(slot)) for slot in slots]
        slots_com_custo = [(slot, custo) for slot, custo in slots_com_custo if custo is not None]
        if not slots_com_custo:
            resposta["sem_estimativa"] += 1
            continue
        slot, custo_adicional = min(slots_com_custo, key=lambda par: (
            par[1], par[0].get("preferencia_ancora_ordem", 1),
            par[0].get("espera_ancora_min") if par[0].get("espera_ancora_min") is not None else 999999,
            par[0].get("score", 0), par[0]["inicio"],
        ))
        # Useful compact slots and lower added-route costs remain primary.
        # Recurrence orders routes in the same ten-minute travel-cost band.
        custo = int(slot.get("tempo_deslocamento_total_min") or 0)
        envolvidos = [rotas.get((int((slot.get("anterior") or {}).get("clinica_id") or 0), clinica.id)),
                       rotas.get((clinica.id, int((slot.get("proximo") or {}).get("clinica_id") or 0)))]
        atualizacoes = [r.updated_at or r.created_at for r in envolvidos if r is not None and (r.updated_at or r.created_at)]
        resultados.append({
            "clinica_id": clinica.id, "clinica": clinica.nome, "cidade": clinica.cidade, "bairro": clinica.bairro,
            "dias_realizados_60d": len(dias[clinica.id]), "atendimentos_realizados_60d": volumes[clinica.id],
            "ultimo_atendimento": max(dias[clinica.id]).isoformat(),
            "inicio": slot["inicio"], "fim": slot["fim"], "tempo_deslocamento_total_min": custo,
            "acrescimo_deslocamento_min": custo_adicional,
            "transicao_regional": bool((slot.get("transicao_regional") or {}).get("usa_transicao_regional")),
            "estimativa_atualizada_em": min(atualizacoes).isoformat() if atualizacoes else None,
            "fonte_estimativa": "cache",
        })
    resultados.sort(key=lambda item: (item["acrescimo_deslocamento_min"] // 10,
        -item["dias_realizados_60d"], -item["atendimentos_realizados_60d"],
        item["acrescimo_deslocamento_min"], item["inicio"], item["clinica_id"]))
    # An explicit null requests every ranked clinic; omitted limits remain 20.
    resposta["items"] = resultados[:payload.limite]
    resposta["total_encontrados"] = len(resultados)
    if not resultados:
        resposta["motivo"] = "Nao encontramos oportunidades com as rotas salvas validas e as regras deste dia."
    return resposta
