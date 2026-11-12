"""Read-only route envelope for one Agenda search, never a routing result.

The graph is a conservative superset: target <-> each operational destination
and existing chronological legs on the searched days. Cached directions count
zero; each missing direction includes Routes and its one legacy fallback.
No address, coordinate, entity ID or route duration leaves this planner.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
import math

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.services import logistica_service as routes

SEARCH_MODELS = {
    "agenda_search": "SugestaoHorarioPayload",
    "agenda_proximity": "SugestaoProximidadePayload",
    "agenda_offers": "AssistenteOfertaPayload",
    "agenda_validate_offer": "ValidarOfertaAssistentePayload",
}


def estimate_search(db, action, body):
    # Lazy import: Agenda already depends on the cost boundary.
    from app.api.v1.endpoints import agenda
    try:
        payload = getattr(agenda, SEARCH_MODELS[action]).model_validate(body)
    except ValidationError:
        raise HTTPException(422, "Dados inválidos para estimar esta busca da Agenda.") from None
    rules = agenda._obter_regras_rota_agenda(db)
    target = agenda._resolver_destino_operacional_payload(
        db, origem_atendimento=payload.origem_atendimento,
        clinica_id=payload.clinica_id, tutor_id=payload.tutor_id,
        contexto="estimar consultas da busca",
    )
    today = datetime.now(agenda.LOCAL_TZ).date()
    raw_date = getattr(payload, "data", None) or getattr(payload, "inicio", None)
    try:
        reference = date.fromisoformat(str(raw_date)[:10]) if raw_date else today
        if action == "agenda_validate_offer":
            local_start = agenda._to_local_naive(agenda._coerce_datetime(payload.inicio))
            if local_start is None:
                raise ValueError('invalid start')
            reference = local_start.date()
        contact = date.fromisoformat(getattr(payload, "data_contato", None) or today.isoformat())
    except ValueError:
        raise HTTPException(422, "Data inválida para estimar esta busca da Agenda.") from None
    starts, ends = [reference], [reference]
    preference = getattr(payload, "preferencia", None)
    if action in {"agenda_offers", "agenda_proximity"} and preference and preference.data_inicio:
        # An explicit period is authoritative, including when reference/contact
        # dates lie outside it. Do not union it with proximity/policy windows.
        starts = [date.fromisoformat(preference.data_inicio)]
        ends = [date.fromisoformat(preference.data_fim)]
    elif action in {"agenda_offers", "agenda_proximity"}:
        window = int(payload.janela_dias_proximidade or 7)
        starts += [reference - timedelta(days=window), contact]
        ends += [reference + timedelta(days=window), contact + timedelta(days=3)]
        policy = rules.get("offer_policy") or {}
        offsets = [2, 3, 4]
        for key in ("default_first_offer_days_ahead", "distant_low_frequency_first_offer_days_ahead"):
            offsets.extend(policy.get(key) or [])
        for override in (rules.get("clinic_overrides") or []):
            if isinstance(override, dict):
                offsets.extend(override.get("force_days_ahead") or [])
        ends.append(contact + timedelta(days=max(int(x) for x in offsets)))
        if action == "agenda_offers":
            ends.append(max(ends) + timedelta(days=agenda.ASSISTENTE_BUSCA_PROGRESSIVA_MAX_DIAS))
    start, end = min(starts), max(ends)
    items = agenda._listar_agendamentos_ativos_periodo(
        db, start.isoformat(), end.isoformat(),
        agendamento_id_excluir=payload.ignorar_agendamento_id,
    )
    # The regional baseline may include the item being edited.
    if payload.ignorar_agendamento_id:
        items += agenda._listar_agendamentos_ativos_periodo(db, start.isoformat(), end.isoformat())
    items = agenda._filtrar_agendamentos_por_janela_funcionamento(db, items)
    entities, days, pairs = {}, defaultdict(dict), set()
    target_entity = agenda._adaptar_destino_operacional_para_logistica(target)
    target_id = int(target_entity.id)
    entities[target_id] = target_entity
    for item in items:
        destination = item.get("destino_operacional") or {}
        if not destination.get("localizacao_confiavel"):
            continue
        entity = agenda._adaptar_destino_operacional_para_logistica(destination)
        if entity is None:
            continue
        entity_id = int(entity.id)
        entities[entity_id] = entity
        if entity_id != target_id:
            pairs.update(((target_id, entity_id), (entity_id, target_id)))
        if isinstance(item.get("inicio"), datetime):
            days[item["inicio"].date()][item["id"]] = (item["inicio"], entity_id)
    # Removing an edited item can expose another baseline neighbour. Include
    # the next-nearest leg too; repeated candidates never multiply the graph.
    for by_id in days.values():
        ordered = sorted(by_id.values())
        for index, (_, origin) in enumerate(ordered):
            for _, destination in ordered[index + 1:index + 3]:
                if origin != destination:
                    pairs.add((origin, destination))
    profile = routes.normalizar_perfil(payload.perfil_deslocamento)
    ids = list(entities)
    rows = db.query(ClinicaDeslocamento).filter(
        ClinicaDeslocamento.origem_clinica_id.in_(ids),
        ClinicaDeslocamento.destino_clinica_id.in_(ids),
        ClinicaDeslocamento.perfil == profile,
    ).all()
    matrix = {(row.origem_clinica_id, row.destino_clinica_id): row for row in rows}
    cached = sum(routes._cache_only_route_available(
        matrix.get((origin, destination)), origem=entities[origin], destino=entities[destination],
    ) for origin, destination in pairs)
    missing = len(pairs) - cached
    base = rules.get("base") or {}
    first_departure = int(bool(str(base.get("address") or "").strip()))
    try:
        lat, lng = float(base.get("lat")), float(base.get("lng"))
        coordinates = math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180 and not (abs(lat) < 1e-6 and abs(lng) < 1e-6)
    except (TypeError, ValueError):
        coordinates = False
    geocoding = int(first_departure and not coordinates)
    route_skus = ("routes_pro", "distance_matrix_pro") if routes._google_traffic_aware_enabled() else ("routes_essentials", "distance_matrix_essentials")
    return {
        "max_calls": 2 * (missing + first_departure) + geocoding,
        "services": list(route_skus) + (["geocoding"] if geocoding else []),
        "estimate_basis": "request_route_graph",
        "cached_directions": cached, "missing_directions": missing,
        "first_departure_routes": first_departure, "geocoding_units": geocoding,
        "max_attempts_per_direction": 2,
        "search_start": start.isoformat(), "search_end": end.isoformat(),
    }
