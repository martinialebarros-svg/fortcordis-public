from __future__ import annotations

import csv
from io import BytesIO, StringIO
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.financeiro import ConfigRateioFrota, CustoFrota, CreditoFinanceiro, Transacao
from app.models.ordem_servico import OrdemServico
from app.models.servico import Servico
from app.models.user import User
from app.services.relatorios_helpers import (
    TOP_LIMIT,
    SECOES_EXPORT_ORDENADAS,
    coerce_datetime as _coerce_datetime,
    carregar_agendamentos_periodo_enxuto as _carregar_agendamentos_periodo_enxuto,
    estimar_distancia_duracao_local as _estimar_distancia_duracao_local,
    formatar_moeda_brl as _formatar_moeda_brl,
    formatar_numero as _formatar_numero,
    normalizar_pesos_rateio as _normalizar_pesos_rateio,
    normalizar_secoes_export as _normalizar_secoes_export,
    parse_iso_date as _parse_iso_date,
    selecionar_clinica_base as _selecionar_clinica_base,
    sum_transacoes as _sum_transacoes,
    to_float as _to_float,
)
from app.services.logistica_service import (
    normalizar_perfil,
)

router = APIRouter()

@router.get("/controle")
def relatorio_controle_gerencial(
    data_inicio: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    data_fim: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    data_referencia: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    perfil_deslocamento: str = Query(default="comercial"),
    clinica_base_id: Optional[int] = Query(default=None, ge=1),
    clinica_id: Optional[int] = Query(default=None, ge=1),
    servico_id: Optional[int] = Query(default=None, ge=1),
    profissional_id: Optional[int] = Query(default=None, ge=1),
    regiao: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    hoje = date.today()
    inicio = _parse_iso_date(data_inicio, "data_inicio") if data_inicio else hoje.replace(day=1)
    fim = _parse_iso_date(data_fim, "data_fim") if data_fim else hoje

    if inicio > fim:
        raise HTTPException(status_code=422, detail="data_inicio nao pode ser maior que data_fim.")
    if (fim - inicio).days > 400:
        raise HTTPException(status_code=422, detail="Periodo muito grande. Limite de 400 dias.")

    referencia = _parse_iso_date(data_referencia, "data_referencia") if data_referencia else hoje
    if referencia < inicio or referencia > fim:
        referencia = fim

    perfil = normalizar_perfil(perfil_deslocamento)

    clinicas = db.query(Clinica).order_by(Clinica.nome.asc()).all()
    clinica_map: dict[int, Clinica] = {int(c.id): c for c in clinicas if c.id is not None}
    clinicas_ativas = [c for c in clinicas if bool(c.ativo)]

    regiao_ids: Optional[set[int]] = None
    regiao_norm = str(regiao or "").strip().lower()
    if regiao_norm:
        regiao_ids = set()
        for c in clinicas:
            texto = " | ".join(
                [
                    str(c.regiao_operacional or ""),
                    str(c.bairro or ""),
                    str(c.cidade or ""),
                    str(c.estado or ""),
                ]
            ).lower()
            if regiao_norm in texto:
                regiao_ids.add(int(c.id))

    query_agendamentos = db.query(Agendamento).filter(
        func.date(Agendamento.inicio) >= inicio.isoformat(),
        func.date(Agendamento.inicio) <= fim.isoformat(),
    )
    if clinica_id:
        query_agendamentos = query_agendamentos.filter(Agendamento.clinica_id == clinica_id)
    if servico_id:
        query_agendamentos = query_agendamentos.filter(Agendamento.servico_id == servico_id)
    if profissional_id:
        query_agendamentos = query_agendamentos.filter(Agendamento.criado_por_id == profissional_id)
    if regiao_ids is not None:
        if regiao_ids:
            query_agendamentos = query_agendamentos.filter(Agendamento.clinica_id.in_(regiao_ids))
        else:
            query_agendamentos = query_agendamentos.filter(Agendamento.id == -1)

    agendamentos_periodo = _carregar_agendamentos_periodo_enxuto(query_agendamentos)

    clinica_ids_financeiro: Optional[list[int]] = None
    if clinica_id:
        clinica_ids_financeiro = [int(clinica_id)]
    elif regiao_ids is not None:
        clinica_ids_financeiro = sorted(int(cid) for cid in regiao_ids)

    base_id, base_nome, criterio_base = _selecionar_clinica_base(
        clinica_base_id=clinica_base_id,
        clinica_map=clinica_map,
        agendamentos_periodo=agendamentos_periodo,
        clinicas_ativas=clinicas_ativas,
    )

    agendamentos_com_rota = [
        ag
        for ag in agendamentos_periodo
        if str(ag.status or "").strip() != "Cancelado"
        and ag.clinica_id
        and _coerce_datetime(ag.inicio) is not None
    ]
    clinica_ids_rota = {int(ag.clinica_id) for ag in agendamentos_com_rota if ag.clinica_id}
    if base_id:
        clinica_ids_rota.add(int(base_id))

    matrix_rows = []
    if clinica_ids_rota:
        matrix_rows = (
            db.query(ClinicaDeslocamento)
            .filter(
                ClinicaDeslocamento.perfil == perfil,
                ClinicaDeslocamento.origem_clinica_id.in_(clinica_ids_rota),
                ClinicaDeslocamento.destino_clinica_id.in_(clinica_ids_rota),
            )
            .all()
        )

    matrix_map: dict[tuple[int, int], ClinicaDeslocamento] = {}
    for row in matrix_rows:
        key = (int(row.origem_clinica_id), int(row.destino_clinica_id))
        matrix_map[key] = row

    agenda_por_dia: dict[str, list[Agendamento]] = defaultdict(list)
    for ag in agendamentos_com_rota:
        inicio_local = _coerce_datetime(ag.inicio)
        if inicio_local is None:
            continue
        agenda_por_dia[inicio_local.date().isoformat()].append(ag)

    resumo_dia: list[dict] = []
    km_por_mes_map: dict[str, dict] = {}
    total_transicoes_jornada = 0
    transicoes_com_risco = 0
    transicoes_criticas: list[dict] = []
    for dia_iso in sorted(agenda_por_dia.keys()):
        itens = sorted(
            agenda_por_dia[dia_iso],
            key=lambda a: _coerce_datetime(a.inicio) or datetime.min,
        )
        total_km = 0.0
        total_duracao_min = 0
        trechos = 0
        trechos_estimados = 0

        for idx in range(len(itens) - 1):
            origem_id = int(itens[idx].clinica_id or 0)
            destino_id = int(itens[idx + 1].clinica_id or 0)
            if origem_id <= 0 or destino_id <= 0:
                continue

            if origem_id == destino_id:
                distancia_km = 0.0
                duracao_min = 0
                fonte = "mesma_clinica"
                matriz_encontrada = True
            else:
                item_matriz = matrix_map.get((origem_id, destino_id))
                if item_matriz:
                    distancia_km = _to_float(item_matriz.distancia_km)
                    duracao_min = int(item_matriz.duracao_min or 0)
                    fonte = str(item_matriz.fonte or "matriz")
                    matriz_encontrada = True
                else:
                    origem_clinica = clinica_map.get(origem_id)
                    destino_clinica = clinica_map.get(destino_id)
                    distancia_km, duracao_min, fonte = _estimar_distancia_duracao_local(
                        origem_clinica,
                        destino_clinica,
                        perfil=perfil,
                    )
                    matriz_encontrada = False

            total_km += max(0.0, distancia_km)
            total_duracao_min += max(0, int(duracao_min))
            trechos += 1
            if not matriz_encontrada and fonte != "mesma_clinica":
                trechos_estimados += 1

            fim_origem = _coerce_datetime(itens[idx].fim)
            if fim_origem is None:
                inicio_origem = _coerce_datetime(itens[idx].inicio)
                if inicio_origem is not None:
                    fim_origem = inicio_origem + timedelta(minutes=30)

            inicio_destino = _coerce_datetime(itens[idx + 1].inicio)
            if fim_origem is not None and inicio_destino is not None:
                folga_min = int((inicio_destino - fim_origem).total_seconds() // 60)
                total_transicoes_jornada += 1

                limite_risco = int(duracao_min or 0) + 5
                if folga_min < limite_risco:
                    transicoes_com_risco += 1
                    clinica_origem = clinica_map.get(origem_id)
                    clinica_destino = clinica_map.get(destino_id)
                    transicoes_criticas.append(
                        {
                            "data": dia_iso,
                            "origem_clinica_id": origem_id,
                            "origem_nome": str(clinica_origem.nome) if clinica_origem and clinica_origem.nome else f"Clinica #{origem_id}",
                            "destino_clinica_id": destino_id,
                            "destino_nome": str(clinica_destino.nome) if clinica_destino and clinica_destino.nome else f"Clinica #{destino_id}",
                            "folga_min": folga_min,
                            "deslocamento_estimado_min": int(duracao_min or 0),
                            "deficit_min": int(max(0, limite_risco - folga_min)),
                        }
                    )

        resumo_item = {
            "data": dia_iso,
            "agendamentos": len(itens),
            "trechos": trechos,
            "trechos_estimados": trechos_estimados,
            "km_total": round(total_km, 2),
            "duracao_total_min": total_duracao_min,
        }
        resumo_dia.append(resumo_item)

        mes_key = dia_iso[:7]
        if mes_key not in km_por_mes_map:
            km_por_mes_map[mes_key] = {
                "mes": mes_key,
                "km_total": 0.0,
                "duracao_total_min": 0,
                "trechos": 0,
                "dias_com_rota": 0,
                "agendamentos": 0,
            }

        km_por_mes_map[mes_key]["km_total"] += total_km
        km_por_mes_map[mes_key]["duracao_total_min"] += total_duracao_min
        km_por_mes_map[mes_key]["trechos"] += trechos
        km_por_mes_map[mes_key]["agendamentos"] += len(itens)
        if trechos > 0 or total_km > 0:
            km_por_mes_map[mes_key]["dias_com_rota"] += 1

    km_por_mes = [
        {
            "mes": item["mes"],
            "km_total": round(item["km_total"], 2),
            "duracao_total_min": int(item["duracao_total_min"]),
            "trechos": int(item["trechos"]),
            "dias_com_rota": int(item["dias_com_rota"]),
            "agendamentos": int(item["agendamentos"]),
        }
        for item in sorted(km_por_mes_map.values(), key=lambda x: x["mes"])
    ]

    resumo_por_data = {item["data"]: item for item in resumo_dia}
    referencia_dia_iso = referencia.isoformat()
    km_projetado_dia = resumo_por_data.get(
        referencia_dia_iso,
        {
            "data": referencia_dia_iso,
            "agendamentos": 0,
            "trechos": 0,
            "trechos_estimados": 0,
            "km_total": 0.0,
            "duracao_total_min": 0,
        },
    )

    rotas_mais_longas_rows = (
        db.query(ClinicaDeslocamento)
        .filter(
            ClinicaDeslocamento.perfil == perfil,
            ClinicaDeslocamento.origem_clinica_id != ClinicaDeslocamento.destino_clinica_id,
        )
        .order_by(ClinicaDeslocamento.distancia_km.desc())
        .limit(TOP_LIMIT)
        .all()
    )

    rotas_mais_longas = []
    for item in rotas_mais_longas_rows:
        origem = clinica_map.get(int(item.origem_clinica_id))
        destino = clinica_map.get(int(item.destino_clinica_id))
        rotas_mais_longas.append(
            {
                "origem_clinica_id": int(item.origem_clinica_id),
                "origem_nome": str(origem.nome) if origem and origem.nome else f"Clinica #{item.origem_clinica_id}",
                "destino_clinica_id": int(item.destino_clinica_id),
                "destino_nome": str(destino.nome) if destino and destino.nome else f"Clinica #{item.destino_clinica_id}",
                "distancia_km": round(_to_float(item.distancia_km), 2),
                "duracao_min": int(item.duracao_min or 0),
                "fonte": str(item.fonte or "matriz"),
            }
        )

    base_matriz_map: dict[int, ClinicaDeslocamento] = {}
    if base_id:
        base_rows = (
            db.query(ClinicaDeslocamento)
            .filter(
                ClinicaDeslocamento.perfil == perfil,
                ClinicaDeslocamento.origem_clinica_id == int(base_id),
            )
            .all()
        )
        base_matriz_map = {int(row.destino_clinica_id): row for row in base_rows}

    clinicas_distantes_base = []
    if base_id and base_id in clinica_map:
        base_clinica = clinica_map[base_id]
        for clinica in clinicas_ativas:
            cid = int(clinica.id or 0)
            if cid <= 0 or cid == int(base_id):
                continue

            row = base_matriz_map.get(cid)
            if row:
                distancia_km = _to_float(row.distancia_km)
                duracao_min = int(row.duracao_min or 0)
                fonte = str(row.fonte or "matriz")
            else:
                distancia_km, duracao_min, fonte = _estimar_distancia_duracao_local(
                    base_clinica,
                    clinica,
                    perfil=perfil,
                )

            clinicas_distantes_base.append(
                {
                    "clinica_id": cid,
                    "clinica_nome": str(clinica.nome or f"Clinica #{cid}"),
                    "distancia_km": round(max(0.0, distancia_km), 2),
                    "duracao_min": max(0, int(duracao_min)),
                    "fonte": fonte,
                }
            )

    clinicas_distantes_base = sorted(
        clinicas_distantes_base,
        key=lambda x: x["distancia_km"],
        reverse=True,
    )[:TOP_LIMIT]

    servico_ids = {int(ag.servico_id) for ag in agendamentos_periodo if ag.servico_id}
    servico_map: dict[int, str] = {}
    if servico_ids:
        servicos = db.query(Servico).filter(Servico.id.in_(servico_ids)).all()
        servico_map = {int(s.id): str(s.nome or f"Servico #{s.id}") for s in servicos if s.id is not None}

    clinicas_stats: dict[int, dict] = defaultdict(lambda: {"agendamentos": 0, "realizados": 0, "cancelados": 0, "faltou": 0})
    servicos_stats: dict[int, dict] = defaultdict(lambda: {"agendamentos": 0, "realizados": 0})

    total_agendamentos = len(agendamentos_periodo)
    total_cancelados = 0
    total_realizados = 0
    total_faltas = 0

    for ag in agendamentos_periodo:
        status_ag = str(ag.status or "").strip()
        if status_ag == "Cancelado":
            total_cancelados += 1
        elif status_ag == "Realizado":
            total_realizados += 1
        elif status_ag == "Faltou":
            total_faltas += 1

        if ag.clinica_id:
            cid = int(ag.clinica_id)
            clinicas_stats[cid]["agendamentos"] += 1
            if status_ag == "Realizado":
                clinicas_stats[cid]["realizados"] += 1
            if status_ag == "Cancelado":
                clinicas_stats[cid]["cancelados"] += 1
            if status_ag == "Faltou":
                clinicas_stats[cid]["faltou"] += 1

        if ag.servico_id:
            sid = int(ag.servico_id)
            servicos_stats[sid]["agendamentos"] += 1
            if status_ag == "Realizado":
                servicos_stats[sid]["realizados"] += 1

    clinicas_mais_agendam = []
    for cid, stats in clinicas_stats.items():
        clinica = clinica_map.get(cid)
        ag_count = int(stats["agendamentos"])
        realizados = int(stats["realizados"])
        taxa = round((realizados / ag_count) * 100, 2) if ag_count > 0 else 0.0
        clinicas_mais_agendam.append(
            {
                "clinica_id": cid,
                "clinica_nome": str(clinica.nome) if clinica and clinica.nome else f"Clinica #{cid}",
                "agendamentos": ag_count,
                "realizados": realizados,
                "cancelados": int(stats["cancelados"]),
                "faltou": int(stats["faltou"]),
                "taxa_realizacao_percent": taxa,
            }
        )
    clinicas_mais_agendam = sorted(
        clinicas_mais_agendam,
        key=lambda x: (x["agendamentos"], x["realizados"]),
        reverse=True,
    )[:TOP_LIMIT]

    servicos_mais_solicitados = []
    for sid, stats in servicos_stats.items():
        ag_count = int(stats["agendamentos"])
        realizados = int(stats["realizados"])
        taxa = round((realizados / ag_count) * 100, 2) if ag_count > 0 else 0.0
        servicos_mais_solicitados.append(
            {
                "servico_id": sid,
                "servico_nome": servico_map.get(sid, f"Servico #{sid}"),
                "agendamentos": ag_count,
                "realizados": realizados,
                "taxa_realizacao_percent": taxa,
            }
        )
    servicos_mais_solicitados = sorted(
        servicos_mais_solicitados,
        key=lambda x: (x["agendamentos"], x["realizados"]),
        reverse=True,
    )[:TOP_LIMIT]

    # Relatorios avancados solicitados
    horas_padrao = list(range(8, 18))
    agenda_ativa = [
        ag for ag in agendamentos_periodo if str(ag.status or "").strip() != "Cancelado"
    ]

    ociosidade_por_hora_count = {hora: 0 for hora in horas_padrao}
    dias_com_agenda = set()
    for ag in agenda_ativa:
        inicio_dt = _coerce_datetime(ag.inicio)
        if inicio_dt is None:
            continue
        dias_com_agenda.add(inicio_dt.date().isoformat())
        if inicio_dt.hour in ociosidade_por_hora_count:
            ociosidade_por_hora_count[inicio_dt.hour] += 1

    total_dias_agenda = max(1, len(dias_com_agenda))
    ociosidade_janela_horario = []
    for hora in horas_padrao:
        ags = int(ociosidade_por_hora_count.get(hora, 0))
        media_dia = round(ags / total_dias_agenda, 2)
        indice_ociosidade = round(max(0.0, 1.0 - min(1.0, media_dia / 1.0)) * 100, 2)
        ociosidade_janela_horario.append(
            {
                "hora_inicio": f"{hora:02d}:00",
                "hora_fim": f"{hora + 1:02d}:00",
                "agendamentos_total": ags,
                "media_agendamentos_dia": media_dia,
                "indice_ociosidade_percent": indice_ociosidade,
            }
        )
    ociosidade_janela_horario = sorted(
        ociosidade_janela_horario,
        key=lambda x: (x["media_agendamentos_dia"], -x["indice_ociosidade_percent"]),
    )

    lead_times_dias: list[int] = []
    lead_time_por_clinica: dict[int, list[int]] = defaultdict(list)
    for ag in agendamentos_periodo:
        inicio_dt = _coerce_datetime(ag.inicio)
        created_dt = _coerce_datetime(ag.created_at)
        if inicio_dt is None or created_dt is None:
            continue
        lead = int((inicio_dt.date() - created_dt.date()).days)
        if lead < 0:
            continue
        lead_times_dias.append(lead)
        if ag.clinica_id:
            lead_time_por_clinica[int(ag.clinica_id)].append(lead)

    antecedencia_media_dias = round(sum(lead_times_dias) / len(lead_times_dias), 2) if lead_times_dias else None
    antecedencia_mediana_dias = None
    if lead_times_dias:
        ordenado = sorted(lead_times_dias)
        meio = len(ordenado) // 2
        if len(ordenado) % 2 == 0:
            antecedencia_mediana_dias = round((ordenado[meio - 1] + ordenado[meio]) / 2, 2)
        else:
            antecedencia_mediana_dias = float(ordenado[meio])

    antecedencia_por_clinica = []
    for cid, leads in lead_time_por_clinica.items():
        clinica = clinica_map.get(cid)
        media = round(sum(leads) / len(leads), 2) if leads else 0.0
        antecedencia_por_clinica.append(
            {
                "clinica_id": cid,
                "clinica_nome": str(clinica.nome) if clinica and clinica.nome else f"Clinica #{cid}",
                "media_dias": media,
                "amostras": len(leads),
            }
        )
    antecedencia_por_clinica = sorted(
        antecedencia_por_clinica,
        key=lambda x: (x["media_dias"], x["amostras"]),
        reverse=True,
    )[:TOP_LIMIT]

    pontualidade = {
        "total_transicoes": int(total_transicoes_jornada),
        "transicoes_com_risco": int(transicoes_com_risco),
        "taxa_risco_percent": round((transicoes_com_risco / total_transicoes_jornada) * 100, 2)
        if total_transicoes_jornada > 0
        else 0.0,
        "transicoes_criticas": sorted(
            transicoes_criticas,
            key=lambda x: (x["deficit_min"], -x["folga_min"]),
            reverse=True,
        )[:TOP_LIMIT],
    }

    mix_servicos_map: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for ag in agenda_ativa:
        if not ag.clinica_id or not ag.servico_id:
            continue
        mix_servicos_map[int(ag.clinica_id)][int(ag.servico_id)] += 1

    mix_servicos_por_clinica = []
    for cid, mapa_servicos in mix_servicos_map.items():
        total = sum(mapa_servicos.values())
        if total <= 0:
            continue
        servico_top_id = max(mapa_servicos, key=mapa_servicos.get)
        top_count = mapa_servicos[servico_top_id]
        clinica = clinica_map.get(cid)
        mix_servicos_por_clinica.append(
            {
                "clinica_id": cid,
                "clinica_nome": str(clinica.nome) if clinica and clinica.nome else f"Clinica #{cid}",
                "total_agendamentos": int(total),
                "servico_principal_id": servico_top_id,
                "servico_principal_nome": servico_map.get(servico_top_id, f"Servico #{servico_top_id}"),
                "servico_principal_quantidade": int(top_count),
                "servico_principal_participacao_percent": round((top_count / total) * 100, 2),
                "servicos_distintos": int(len(mapa_servicos)),
            }
        )
    mix_servicos_por_clinica = sorted(
        mix_servicos_por_clinica,
        key=lambda x: (x["total_agendamentos"], x["servico_principal_participacao_percent"]),
        reverse=True,
    )[:TOP_LIMIT]

    def _aplicar_filtros_os(query):
        if clinica_id:
            query = query.filter(OrdemServico.clinica_id == clinica_id)
        elif regiao_ids is not None:
            if regiao_ids:
                query = query.filter(OrdemServico.clinica_id.in_(regiao_ids))
            else:
                query = query.filter(OrdemServico.id == -1)
        if servico_id:
            query = query.filter(OrdemServico.servico_id == servico_id)
        if profissional_id:
            query = query.filter(OrdemServico.criado_por_id == profissional_id)
        return query

    data_limite_recebimento = referencia + timedelta(days=30)
    previsao_rows = (
        _aplicar_filtros_os(
            db.query(
                OrdemServico.clinica_id,
                func.sum(OrdemServico.valor_final).label("total"),
                func.count(OrdemServico.id).label("quantidade"),
            ).filter(
                OrdemServico.status == "Pendente",
                OrdemServico.clinica_id.isnot(None),
                func.date(OrdemServico.data_atendimento) >= referencia.isoformat(),
                func.date(OrdemServico.data_atendimento) <= data_limite_recebimento.isoformat(),
            )
        )
        .group_by(OrdemServico.clinica_id)
        .order_by(func.sum(OrdemServico.valor_final).desc())
        .all()
    )

    previsao_recebimentos_30d_itens = []
    total_previsao_30d = 0.0
    for row in previsao_rows:
        cid = int(row.clinica_id)
        clinica = clinica_map.get(cid)
        valor = round(_to_float(row.total), 2)
        total_previsao_30d += valor
        previsao_recebimentos_30d_itens.append(
            {
                "clinica_id": cid,
                "clinica_nome": str(clinica.nome) if clinica and clinica.nome else f"Clinica #{cid}",
                "valor_previsto": valor,
                "ordens_pendentes": int(row.quantidade or 0),
            }
        )
    previsao_recebimentos_30d_itens = previsao_recebimentos_30d_itens[:TOP_LIMIT]

    pendencias_recebimento_rows = (
        _aplicar_filtros_os(
            db.query(
                OrdemServico.clinica_id,
                func.sum(OrdemServico.valor_final).label("total"),
                func.count(OrdemServico.id).label("quantidade"),
            ).filter(
                OrdemServico.status == "Pendente",
                OrdemServico.clinica_id.isnot(None),
                func.date(OrdemServico.data_atendimento) <= referencia.isoformat(),
            )
        )
        .group_by(OrdemServico.clinica_id)
        .order_by(func.sum(OrdemServico.valor_final).desc())
        .all()
    )

    pendencias_recebimento_itens = []
    total_pendencias_recebimento = 0.0
    for row in pendencias_recebimento_rows:
        cid = int(row.clinica_id)
        clinica = clinica_map.get(cid)
        valor = round(_to_float(row.total), 2)
        total_pendencias_recebimento += valor
        pendencias_recebimento_itens.append(
            {
                "clinica_id": cid,
                "clinica_nome": str(clinica.nome) if clinica and clinica.nome else f"Clinica #{cid}",
                "valor_pendente": valor,
                "ordens_pendentes": int(row.quantidade or 0),
            }
        )

    entradas_periodo = _sum_transacoes(
        db,
        tipo="entrada",
        status_list=["Recebido", "Pago"],
        data_inicio=inicio,
        data_fim=fim,
        clinica_ids_filter=clinica_ids_financeiro,
    )
    saidas_periodo = _sum_transacoes(
        db,
        tipo="saida",
        status_list=["Pago"],
        data_inicio=inicio,
        data_fim=fim,
        clinica_ids_filter=clinica_ids_financeiro,
    )

    inicio_mes_ref = referencia.replace(day=1)
    entradas_mes = _sum_transacoes(
        db,
        tipo="entrada",
        status_list=["Recebido", "Pago"],
        data_inicio=inicio_mes_ref,
        data_fim=referencia,
        clinica_ids_filter=clinica_ids_financeiro,
    )
    saidas_mes = _sum_transacoes(
        db,
        tipo="saida",
        status_list=["Pago"],
        data_inicio=inicio_mes_ref,
        data_fim=referencia,
        clinica_ids_filter=clinica_ids_financeiro,
    )

    filtros_taxa_periodo = [
        Transacao.tipo == "entrada",
        Transacao.status.in_(["Recebido", "Pago"]),
        func.date(Transacao.data_transacao) >= inicio.isoformat(),
        func.date(Transacao.data_transacao) <= fim.isoformat(),
    ]
    filtros_taxa_mes = [
        Transacao.tipo == "entrada",
        Transacao.status.in_(["Recebido", "Pago"]),
        func.date(Transacao.data_transacao) >= inicio_mes_ref.isoformat(),
        func.date(Transacao.data_transacao) <= referencia.isoformat(),
    ]
    if clinica_ids_financeiro is not None:
        if clinica_ids_financeiro:
            filtros_taxa_periodo.append(Transacao.clinica_id.in_(clinica_ids_financeiro))
            filtros_taxa_mes.append(Transacao.clinica_id.in_(clinica_ids_financeiro))
        else:
            filtros_taxa_periodo.append(Transacao.id == -1)
            filtros_taxa_mes.append(Transacao.id == -1)

    taxas_pagamento_periodo = (
        db.query(func.sum(Transacao.valor_taxa))
        .filter(*filtros_taxa_periodo)
        .scalar()
        or 0
    )
    taxas_pagamento_mes = (
        db.query(func.sum(Transacao.valor_taxa))
        .filter(*filtros_taxa_mes)
        .scalar()
        or 0
    )

    filtros_credito_periodo = [
        CreditoFinanceiro.origem == "excedente_pagamento_os",
        CreditoFinanceiro.status == "Ativo",
        func.date(CreditoFinanceiro.data_movimento) >= inicio.isoformat(),
        func.date(CreditoFinanceiro.data_movimento) <= fim.isoformat(),
    ]
    filtros_credito_mes = [
        CreditoFinanceiro.origem == "excedente_pagamento_os",
        CreditoFinanceiro.status == "Ativo",
        func.date(CreditoFinanceiro.data_movimento) >= inicio_mes_ref.isoformat(),
        func.date(CreditoFinanceiro.data_movimento) <= referencia.isoformat(),
    ]
    if clinica_ids_financeiro is not None:
        if clinica_ids_financeiro:
            filtros_credito_periodo.append(
                or_(
                    CreditoFinanceiro.clinica_id.in_(clinica_ids_financeiro),
                    and_(
                        CreditoFinanceiro.clinica_id.is_(None),
                        CreditoFinanceiro.paciente_id.isnot(None),
                    ),
                )
            )
            filtros_credito_mes.append(
                or_(
                    CreditoFinanceiro.clinica_id.in_(clinica_ids_financeiro),
                    and_(
                        CreditoFinanceiro.clinica_id.is_(None),
                        CreditoFinanceiro.paciente_id.isnot(None),
                    ),
                )
            )
        else:
            filtros_credito_periodo.append(CreditoFinanceiro.id == -1)
            filtros_credito_mes.append(CreditoFinanceiro.id == -1)

    creditos_gerados_periodo = (
        db.query(func.sum(CreditoFinanceiro.valor))
        .filter(*filtros_credito_periodo)
        .scalar()
        or 0
    )
    creditos_gerados_mes = (
        db.query(func.sum(CreditoFinanceiro.valor))
        .filter(*filtros_credito_mes)
        .scalar()
        or 0
    )

    valor_servicos_periodo = _aplicar_filtros_os(
        db.query(func.sum(OrdemServico.valor_final)).filter(
            OrdemServico.status != "Cancelado",
            func.date(OrdemServico.data_atendimento) >= inicio.isoformat(),
            func.date(OrdemServico.data_atendimento) <= fim.isoformat(),
        )
    ).scalar()
    qtd_servicos_periodo = _aplicar_filtros_os(
        db.query(func.count(OrdemServico.id)).filter(
            OrdemServico.status != "Cancelado",
            func.date(OrdemServico.data_atendimento) >= inicio.isoformat(),
            func.date(OrdemServico.data_atendimento) <= fim.isoformat(),
        )
    ).scalar()

    valor_servicos_mes = _aplicar_filtros_os(
        db.query(func.sum(OrdemServico.valor_final)).filter(
            OrdemServico.status != "Cancelado",
            func.date(OrdemServico.data_atendimento) >= inicio_mes_ref.isoformat(),
            func.date(OrdemServico.data_atendimento) <= referencia.isoformat(),
        )
    ).scalar()
    qtd_servicos_mes = _aplicar_filtros_os(
        db.query(func.count(OrdemServico.id)).filter(
            OrdemServico.status != "Cancelado",
            func.date(OrdemServico.data_atendimento) >= inicio_mes_ref.isoformat(),
            func.date(OrdemServico.data_atendimento) <= referencia.isoformat(),
        )
    ).scalar()

    valor_servicos_mes_float = round(_to_float(valor_servicos_mes), 2)
    qtd_servicos_mes_int = int(qtd_servicos_mes or 0)
    ticket_medio_mes = round(valor_servicos_mes_float / qtd_servicos_mes_int, 2) if qtd_servicos_mes_int > 0 else 0.0

    faturamento_clinica_rows = (
        _aplicar_filtros_os(
            db.query(
                OrdemServico.clinica_id,
                func.sum(OrdemServico.valor_final).label("total"),
                func.count(OrdemServico.id).label("quantidade"),
            ).filter(
                OrdemServico.status != "Cancelado",
                func.date(OrdemServico.data_atendimento) >= inicio.isoformat(),
                func.date(OrdemServico.data_atendimento) <= fim.isoformat(),
                OrdemServico.clinica_id.isnot(None),
            )
        )
        .group_by(OrdemServico.clinica_id)
        .order_by(func.sum(OrdemServico.valor_final).desc())
        .limit(TOP_LIMIT)
        .all()
    )

    faturamento_clinica_rows_full = (
        _aplicar_filtros_os(
            db.query(
                OrdemServico.clinica_id,
                func.sum(OrdemServico.valor_final).label("total"),
                func.count(OrdemServico.id).label("quantidade"),
            ).filter(
                OrdemServico.status != "Cancelado",
                func.date(OrdemServico.data_atendimento) >= inicio.isoformat(),
                func.date(OrdemServico.data_atendimento) <= fim.isoformat(),
                OrdemServico.clinica_id.isnot(None),
            )
        )
        .group_by(OrdemServico.clinica_id)
        .all()
    )

    faturamento_clinica_map: dict[int, dict] = {}
    for row in faturamento_clinica_rows_full:
        cid = int(row.clinica_id)
        faturamento_clinica_map[cid] = {
            "valor_total": round(_to_float(row.total), 2),
            "servicos": int(row.quantidade or 0),
        }

    clinicas_maior_faturamento = []
    for row in faturamento_clinica_rows:
        cid = int(row.clinica_id)
        clinica = clinica_map.get(cid)
        clinicas_maior_faturamento.append(
            {
                "clinica_id": cid,
                "clinica_nome": str(clinica.nome) if clinica and clinica.nome else f"Clinica #{cid}",
                "valor_total": round(_to_float(row.total), 2),
                "servicos": int(row.quantidade or 0),
            }
        )

    distancia_base_map: dict[int, dict] = {
        int(item["clinica_id"]): {
            "distancia_km": float(item["distancia_km"]),
            "duracao_min": int(item["duracao_min"]),
            "fonte": str(item["fonte"]),
        }
        for item in clinicas_distantes_base
    }

    base_operacao_clinica: dict[int, dict[str, float]] = {}
    total_km_rateio = 0.0
    total_atendimentos_rateio = 0
    for cid, stats in clinicas_stats.items():
        agendamentos = int(stats["agendamentos"])
        realizados = int(stats["realizados"])
        cancelados = int(stats["cancelados"])
        viagens_uteis = max(0, agendamentos - cancelados)

        distancia_info = distancia_base_map.get(cid)
        if distancia_info is None and base_id and base_id in clinica_map and cid in clinica_map and cid != base_id:
            distancia_km, duracao_min, fonte = _estimar_distancia_duracao_local(
                clinica_map[base_id],
                clinica_map[cid],
                perfil=perfil,
            )
            distancia_info = {
                "distancia_km": float(distancia_km),
                "duracao_min": int(duracao_min),
                "fonte": fonte,
            }
            distancia_base_map[cid] = distancia_info

        distancia_km_base = float(distancia_info["distancia_km"]) if distancia_info else 0.0
        km_estimado_operacao = round(distancia_km_base * 2 * viagens_uteis, 2)
        base_atendimento = max(realizados, viagens_uteis, 0)
        base_operacao_clinica[cid] = {
            "km_estimado_operacao": km_estimado_operacao,
            "base_atendimento": float(base_atendimento),
        }
        total_km_rateio += km_estimado_operacao
        total_atendimentos_rateio += base_atendimento

    despesas_clinica_query = db.query(
        Transacao.clinica_id,
        func.sum(Transacao.valor_final).label("total"),
        func.count(Transacao.id).label("quantidade"),
    ).filter(
        Transacao.tipo == "saida",
        Transacao.status == "Pago",
        func.date(Transacao.data_transacao) >= inicio.isoformat(),
        func.date(Transacao.data_transacao) <= fim.isoformat(),
        Transacao.clinica_id.isnot(None),
    )
    if clinica_id:
        despesas_clinica_query = despesas_clinica_query.filter(Transacao.clinica_id == clinica_id)
    elif regiao_ids is not None:
        if regiao_ids:
            despesas_clinica_query = despesas_clinica_query.filter(Transacao.clinica_id.in_(regiao_ids))
        else:
            despesas_clinica_query = despesas_clinica_query.filter(Transacao.id == -1)

    despesas_clinica_rows = despesas_clinica_query.group_by(Transacao.clinica_id).all()
    despesa_clinica_map: dict[int, float] = {
        int(row.clinica_id): round(_to_float(row.total), 2)
        for row in despesas_clinica_rows
        if row.clinica_id is not None
    }

    config_rateio_frota = db.query(ConfigRateioFrota).order_by(ConfigRateioFrota.id.asc()).first()
    peso_km_rateio = 0.7
    peso_atendimento_rateio = 0.3
    config_rateio_fonte = "padrao"
    if config_rateio_frota:
        peso_km_rateio, peso_atendimento_rateio = _normalizar_pesos_rateio(
            config_rateio_frota.peso_km,
            config_rateio_frota.peso_atendimento,
        )
        config_rateio_fonte = "configurado"

    custos_frota_query = db.query(CustoFrota).filter(
        func.date(CustoFrota.data_referencia) >= inicio.isoformat(),
        func.date(CustoFrota.data_referencia) <= fim.isoformat(),
    )
    if clinica_id:
        custos_frota_query = custos_frota_query.filter(
            or_(CustoFrota.clinica_id == clinica_id, CustoFrota.clinica_id.is_(None))
        )
    elif regiao_ids is not None:
        if regiao_ids:
            custos_frota_query = custos_frota_query.filter(
                or_(CustoFrota.clinica_id.is_(None), CustoFrota.clinica_id.in_(regiao_ids))
            )
        else:
            custos_frota_query = custos_frota_query.filter(CustoFrota.clinica_id.is_(None))
    custos_frota_rows = custos_frota_query.all()

    despesa_frota_alocada_map: dict[int, float] = defaultdict(float)
    custos_frota_total = 0.0
    custos_frota_diretos = 0.0
    custos_frota_por_km = 0.0
    custos_frota_por_atendimento = 0.0
    custos_frota_hibrido = 0.0
    custos_frota_fixo = 0.0
    custos_frota_nao_alocados = 0.0

    for row in custos_frota_rows:
        valor_item = round(_to_float(row.valor), 2)
        if valor_item <= 0:
            continue
        custos_frota_total += valor_item
        row_clinica_id = int(row.clinica_id) if row.clinica_id else None

        if row_clinica_id is not None and row_clinica_id in base_operacao_clinica:
            despesa_frota_alocada_map[row_clinica_id] += valor_item
            custos_frota_diretos += valor_item
            continue

        forma_rateio = str(row.forma_rateio or "por_km").strip().lower()
        alocado = False

        if forma_rateio == "por_km":
            if total_km_rateio > 0:
                for cid, base_info in base_operacao_clinica.items():
                    km_item = _to_float(base_info.get("km_estimado_operacao"))
                    if km_item <= 0:
                        continue
                    despesa_frota_alocada_map[cid] += round((km_item / total_km_rateio) * valor_item, 6)
                alocado = True
                custos_frota_por_km += valor_item
        elif forma_rateio == "por_atendimento":
            if total_atendimentos_rateio > 0:
                for cid, base_info in base_operacao_clinica.items():
                    atendimento_item = _to_float(base_info.get("base_atendimento"))
                    if atendimento_item <= 0:
                        continue
                    despesa_frota_alocada_map[cid] += round((atendimento_item / total_atendimentos_rateio) * valor_item, 6)
                alocado = True
                custos_frota_por_atendimento += valor_item
        elif forma_rateio == "hibrido":
            if total_km_rateio > 0 and total_atendimentos_rateio > 0:
                for cid, base_info in base_operacao_clinica.items():
                    km_item = _to_float(base_info.get("km_estimado_operacao"))
                    atendimento_item = _to_float(base_info.get("base_atendimento"))
                    if km_item <= 0 and atendimento_item <= 0:
                        continue
                    fator_km = (km_item / total_km_rateio) if km_item > 0 else 0.0
                    fator_atendimento = (
                        (atendimento_item / total_atendimentos_rateio) if atendimento_item > 0 else 0.0
                    )
                    fator_hibrido = (fator_km * peso_km_rateio) + (fator_atendimento * peso_atendimento_rateio)
                    if fator_hibrido <= 0:
                        continue
                    despesa_frota_alocada_map[cid] += round(fator_hibrido * valor_item, 6)
                alocado = True
            elif total_km_rateio > 0:
                for cid, base_info in base_operacao_clinica.items():
                    km_item = _to_float(base_info.get("km_estimado_operacao"))
                    if km_item <= 0:
                        continue
                    despesa_frota_alocada_map[cid] += round((km_item / total_km_rateio) * valor_item, 6)
                alocado = True
            elif total_atendimentos_rateio > 0:
                for cid, base_info in base_operacao_clinica.items():
                    atendimento_item = _to_float(base_info.get("base_atendimento"))
                    if atendimento_item <= 0:
                        continue
                    despesa_frota_alocada_map[cid] += round((atendimento_item / total_atendimentos_rateio) * valor_item, 6)
                alocado = True
            if alocado:
                custos_frota_hibrido += valor_item
        else:
            if total_atendimentos_rateio > 0:
                for cid, base_info in base_operacao_clinica.items():
                    atendimento_item = _to_float(base_info.get("base_atendimento"))
                    if atendimento_item <= 0:
                        continue
                    despesa_frota_alocada_map[cid] += round((atendimento_item / total_atendimentos_rateio) * valor_item, 6)
                alocado = True
            elif len(base_operacao_clinica) > 0:
                share = valor_item / len(base_operacao_clinica)
                for cid in base_operacao_clinica.keys():
                    despesa_frota_alocada_map[cid] += round(share, 6)
                alocado = True
            if alocado:
                custos_frota_fixo += valor_item

        if not alocado:
            custos_frota_nao_alocados += valor_item

    despesa_total_clinica_map: dict[int, float] = {}
    for cid in set(despesa_clinica_map.keys()) | set(despesa_frota_alocada_map.keys()) | set(
        base_operacao_clinica.keys()
    ):
        despesa_total_clinica_map[int(cid)] = round(
            _to_float(despesa_clinica_map.get(cid, 0.0))
            + _to_float(despesa_frota_alocada_map.get(cid, 0.0)),
            2,
        )

    avaliar_rateio_global = clinica_id is None and regiao_ids is None
    despesas_sem_clinica_total = 0.0
    if avaliar_rateio_global:
        despesas_sem_clinica_total = round(
            _to_float(
                db.query(func.sum(Transacao.valor_final))
                .filter(
                    Transacao.tipo == "saida",
                    Transacao.status == "Pago",
                    func.date(Transacao.data_transacao) >= inicio.isoformat(),
                    func.date(Transacao.data_transacao) <= fim.isoformat(),
                    Transacao.clinica_id.is_(None),
                )
                .scalar()
            ),
            2,
        )

    clinicas_com_receita_ids = {
        int(cid)
        for cid, item in faturamento_clinica_map.items()
        if _to_float(item.get("valor_total")) > 0
    }
    clinicas_sem_despesa_ids = sorted(
        int(cid)
        for cid in clinicas_com_receita_ids
        if _to_float(despesa_total_clinica_map.get(int(cid), 0.0)) <= 0
    )

    dados_necessarios_rentabilidade_real = [
        "Receita de servicos por clinica no periodo (OS realizadas).",
        "Despesas por clinica no periodo (transacoes de saida com clinica_id e/ou custos de frota vinculados).",
        "Custos de frota com regra de rateio (por_km, por_atendimento, hibrido ou fixo_mensal).",
        "Regra de rateio para despesas sem clinica vinculada (aluguel, salario, custos administrativos).",
    ]
    pendencias_rentabilidade_real: list[str] = []
    if servico_id or profissional_id:
        pendencias_rentabilidade_real.append(
            "Filtro por servico/profissional ativo: faltam custos segregados por servico/profissional para calculo real."
        )
    if not clinicas_com_receita_ids:
        pendencias_rentabilidade_real.append(
            "Nao ha faturamento por clinica no periodo/filtros para calcular margem real."
        )
    if clinicas_sem_despesa_ids:
        nomes_sem_despesa = []
        for cid in clinicas_sem_despesa_ids[:5]:
            clinica = clinica_map.get(cid)
            nomes_sem_despesa.append(
                str(clinica.nome) if clinica and clinica.nome else f"Clinica #{cid}"
            )
        sufixo = "..." if len(clinicas_sem_despesa_ids) > 5 else ""
        pendencias_rentabilidade_real.append(
            "Clinicas com receita e sem custo/despesa alocado no periodo: "
            + ", ".join(nomes_sem_despesa)
            + sufixo
            + "."
        )
    if custos_frota_total <= 0:
        pendencias_rentabilidade_real.append(
            "Nao ha custos de frota registrados no periodo. Registre combustivel/manutencao/seguro para melhorar a rentabilidade real."
        )
    if custos_frota_nao_alocados > 0:
        pendencias_rentabilidade_real.append(
            "Existem custos de frota sem base de rateio suficiente no periodo "
            f"({_formatar_moeda_brl(custos_frota_nao_alocados)})."
        )
    if avaliar_rateio_global and despesas_sem_clinica_total > 0:
        pendencias_rentabilidade_real.append(
            "Existem despesas pagas sem clinica vinculada no periodo "
            f"({_formatar_moeda_brl(despesas_sem_clinica_total)}). "
            "Defina criterio de rateio para consolidar rentabilidade real."
        )

    cobertura_real = {
        "clinicas_com_receita": int(len(clinicas_com_receita_ids)),
        "clinicas_com_despesa_vinculada": int(
            len([cid for cid in clinicas_com_receita_ids if _to_float(despesa_total_clinica_map.get(cid, 0.0)) > 0])
        ),
        "clinicas_sem_despesa_vinculada": int(len(clinicas_sem_despesa_ids)),
        "despesas_sem_clinica": round(despesas_sem_clinica_total, 2),
        "custos_frota_total": round(custos_frota_total, 2),
        "custos_frota_nao_alocados": round(custos_frota_nao_alocados, 2),
    }
    if cobertura_real["clinicas_com_receita"] > 0:
        cobertura_real["cobertura_percent"] = round(
            (
                cobertura_real["clinicas_com_despesa_vinculada"]
                / cobertura_real["clinicas_com_receita"]
            )
            * 100,
            2,
        )
    else:
        cobertura_real["cobertura_percent"] = 0.0

    metodologia_rentabilidade = (
        "real" if len(pendencias_rentabilidade_real) == 0 else "proxy_operacional"
    )
    mensagem_metodologia = (
        "Rentabilidade calculada em modo real (receita - despesas/custos alocados por clinica)."
        if metodologia_rentabilidade == "real"
        else "Rentabilidade em proxy operacional por falta de dados suficientes para calculo real."
    )
    resumo_custos_frota = {
        "total_periodo": round(custos_frota_total, 2),
        "alocado_por_km": round(custos_frota_por_km, 2),
        "alocado_por_atendimento": round(custos_frota_por_atendimento, 2),
        "alocado_hibrido": round(custos_frota_hibrido, 2),
        "alocado_fixo": round(custos_frota_fixo, 2),
        "diretos_por_clinica": round(custos_frota_diretos, 2),
        "nao_alocados": round(custos_frota_nao_alocados, 2),
        "total_itens": int(len(custos_frota_rows)),
        "config_rateio_hibrido": {
            "peso_km": peso_km_rateio,
            "peso_atendimento": peso_atendimento_rateio,
            "fonte": config_rateio_fonte,
        },
    }

    ranking_rentabilidade_proxy = []
    ranking_rentabilidade_real = []
    for cid, stats in clinicas_stats.items():
        clinica = clinica_map.get(cid)
        agendamentos = int(stats["agendamentos"])
        realizados = int(stats["realizados"])
        cancelados = int(stats["cancelados"])
        faltou = int(stats["faltou"])

        taxa_cancelamento_clinica = round((cancelados / agendamentos) * 100, 2) if agendamentos > 0 else 0.0
        taxa_realizacao_clinica = round((realizados / agendamentos) * 100, 2) if agendamentos > 0 else 0.0
        taxa_falta_clinica = round((faltou / agendamentos) * 100, 2) if agendamentos > 0 else 0.0

        distancia_info = distancia_base_map.get(cid)
        if distancia_info is None and base_id and base_id in clinica_map and cid in clinica_map and cid != base_id:
            distancia_km, duracao_min, fonte = _estimar_distancia_duracao_local(
                clinica_map[base_id],
                clinica_map[cid],
                perfil=perfil,
            )
            distancia_info = {
                "distancia_km": float(distancia_km),
                "duracao_min": int(duracao_min),
                "fonte": fonte,
            }
            distancia_base_map[cid] = distancia_info

        distancia_km_base = float(distancia_info["distancia_km"]) if distancia_info else 0.0
        duracao_min_base = int(distancia_info["duracao_min"]) if distancia_info else 0
        distancia_fonte = str(distancia_info["fonte"]) if distancia_info else "indefinido"

        faturamento = faturamento_clinica_map.get(cid, {"valor_total": 0.0, "servicos": 0})
        valor_total = float(faturamento["valor_total"])
        servicos_total = int(faturamento["servicos"])

        viagens_uteis = max(0, agendamentos - cancelados)
        km_estimado_operacao = round(distancia_km_base * 2 * viagens_uteis, 2)

        retorno_por_km_proxy = (
            round(valor_total / km_estimado_operacao, 2)
            if km_estimado_operacao > 0
            else None
        )
        despesa_transacoes = round(_to_float(despesa_clinica_map.get(cid, 0.0)), 2)
        despesa_frota = round(_to_float(despesa_frota_alocada_map.get(cid, 0.0)), 2)
        despesa_total = round(_to_float(despesa_total_clinica_map.get(cid, 0.0)), 2)
        lucro_liquido = round(valor_total - despesa_total, 2)
        margem_percent = (
            round((lucro_liquido / valor_total) * 100, 2)
            if valor_total > 0
            else 0.0
        )
        retorno_por_km_real = (
            round(lucro_liquido / km_estimado_operacao, 2)
            if km_estimado_operacao > 0
            else None
        )

        fator_execucao = (realizados / agendamentos) if agendamentos > 0 else 0.0
        fator_cancelamento = (1.0 - (cancelados / agendamentos)) if agendamentos > 0 else 0.0
        indice_rentabilidade_proxy = (
            round((retorno_por_km_proxy or 0.0) * max(0.0, fator_execucao) * max(0.0, fator_cancelamento), 2)
            if retorno_por_km_proxy is not None
            else 0.0
        )
        indice_rentabilidade_real = (
            round((retorno_por_km_real or 0.0) * max(0.0, fator_execucao) * max(0.0, fator_cancelamento), 2)
            if retorno_por_km_real is not None
            else 0.0
        )

        base_item = {
            "clinica_id": cid,
            "clinica_nome": str(clinica.nome) if clinica and clinica.nome else f"Clinica #{cid}",
            "agendamentos": agendamentos,
            "realizados": realizados,
            "cancelados": cancelados,
            "faltou": faltou,
            "taxa_realizacao_percent": taxa_realizacao_clinica,
            "taxa_cancelamento_percent": taxa_cancelamento_clinica,
            "taxa_falta_percent": taxa_falta_clinica,
            "valor_total_servicos": round(valor_total, 2),
            "quantidade_servicos": servicos_total,
            "distancia_km_base": round(distancia_km_base, 2),
            "duracao_min_base": duracao_min_base,
            "distancia_fonte": distancia_fonte,
            "km_estimado_operacao": km_estimado_operacao,
            "despesa_transacoes": despesa_transacoes,
            "despesa_frota": despesa_frota,
            "despesa_total": despesa_total,
            "lucro_liquido": lucro_liquido,
            "margem_percent": margem_percent,
        }

        ranking_rentabilidade_proxy.append(
            {
                **base_item,
                "retorno_por_km": retorno_por_km_proxy,
                "indice_rentabilidade": indice_rentabilidade_proxy,
                "metodologia": "proxy_operacional",
            }
        )
        ranking_rentabilidade_real.append(
            {
                **base_item,
                "retorno_por_km": retorno_por_km_real,
                "indice_rentabilidade": indice_rentabilidade_real,
                "metodologia": "real",
            }
        )

    ranking_rentabilidade_proxy = sorted(
        ranking_rentabilidade_proxy,
        key=lambda x: (x["indice_rentabilidade"], x["valor_total_servicos"], x["agendamentos"]),
        reverse=True,
    )[:TOP_LIMIT]
    ranking_rentabilidade_real = sorted(
        ranking_rentabilidade_real,
        key=lambda x: (x["indice_rentabilidade"], x["valor_total_servicos"], x["agendamentos"]),
        reverse=True,
    )[:TOP_LIMIT]
    ranking_rentabilidade = (
        ranking_rentabilidade_real
        if metodologia_rentabilidade == "real"
        else ranking_rentabilidade_proxy
    )

    km_mes_referencia = 0.0
    mes_ref_key = referencia.strftime("%Y-%m")
    for item in km_por_mes:
        if item["mes"] == mes_ref_key:
            km_mes_referencia = float(item["km_total"])
            break

    taxa_cancelamento = round((total_cancelados / total_agendamentos) * 100, 2) if total_agendamentos > 0 else 0.0
    taxa_realizacao = round((total_realizados / total_agendamentos) * 100, 2) if total_agendamentos > 0 else 0.0
    taxa_falta = round((total_faltas / total_agendamentos) * 100, 2) if total_agendamentos > 0 else 0.0
    retorno_por_km_mes = round(valor_servicos_mes_float / km_mes_referencia, 2) if km_mes_referencia > 0 else None

    alertas_operacionais = []
    severidade_peso = {"alto": 3, "medio": 2, "baixo": 1}

    if total_agendamentos > 0 and clinicas_mais_agendam:
        principal = clinicas_mais_agendam[0]
        concentracao = round((principal["agendamentos"] / total_agendamentos) * 100, 2)
        if concentracao >= 45:
            alertas_operacionais.append(
                {
                    "codigo": "concentracao_demanda",
                    "severidade": "medio",
                    "titulo": "Concentracao alta de demanda em uma clinica",
                    "descricao": (
                        f"{principal['clinica_nome']} concentra {concentracao}% dos agendamentos do periodo. "
                        "Isso aumenta risco operacional em caso de mudanca de parceria."
                    ),
                    "recomendacao": "Diversificar agenda com segunda e terceira clinica em volume.",
                    "clinica_id": principal["clinica_id"],
                }
            )

    for item in ranking_rentabilidade:
        if item["agendamentos"] >= 5 and item["taxa_cancelamento_percent"] >= 25:
            alertas_operacionais.append(
                {
                    "codigo": f"cancelamento_alto_{item['clinica_id']}",
                    "severidade": "alto",
                    "titulo": "Taxa de cancelamento elevada",
                    "descricao": (
                        f"{item['clinica_nome']} com {item['taxa_cancelamento_percent']}% de cancelamento "
                        f"em {item['agendamentos']} agendamentos."
                    ),
                    "recomendacao": "Rever politica de confirmacao e janela de agendamento desta clinica.",
                    "clinica_id": item["clinica_id"],
                }
            )

        if item["agendamentos"] >= 5 and item["taxa_falta_percent"] >= 18:
            alertas_operacionais.append(
                {
                    "codigo": f"falta_alta_{item['clinica_id']}",
                    "severidade": "medio",
                    "titulo": "Indice de faltas acima do ideal",
                    "descricao": (
                        f"{item['clinica_nome']} com {item['taxa_falta_percent']}% de faltas no periodo."
                    ),
                    "recomendacao": "Aplicar confirmacao ativa no dia anterior e no dia da agenda.",
                    "clinica_id": item["clinica_id"],
                }
            )

        retorno_km = item["retorno_por_km"]
        if item["distancia_km_base"] >= 35 and (retorno_km is None or retorno_km < 8):
            alertas_operacionais.append(
                {
                    "codigo": f"distancia_baixo_retorno_{item['clinica_id']}",
                    "severidade": "medio",
                    "titulo": "Distancia alta com retorno baixo por km",
                    "descricao": (
                        f"{item['clinica_nome']} esta a {item['distancia_km_base']} km da base e "
                        f"retorno por km em torno de {_formatar_moeda_brl(retorno_km or 0)}."
                    ),
                    "recomendacao": "Avaliar reajuste de tabela, agrupamento de atendimentos ou reducao de frequencia.",
                    "clinica_id": item["clinica_id"],
                }
            )

    if km_projetado_dia.get("trechos", 0) > 0:
        percentual_estimado = round(
            (km_projetado_dia.get("trechos_estimados", 0) / max(1, km_projetado_dia.get("trechos", 0))) * 100, 2
        )
        if percentual_estimado >= 30:
            alertas_operacionais.append(
                {
                    "codigo": "matriz_desatualizada",
                    "severidade": "baixo",
                    "titulo": "Matriz de deslocamento com muitos trechos estimados",
                    "descricao": (
                        f"{percentual_estimado}% dos trechos do dia de referencia usam estimativa heuristica."
                    ),
                    "recomendacao": "Recalibrar a matriz de deslocamento para aumentar precisao do planejamento.",
                    "clinica_id": None,
                }
            )

    alertas_operacionais = sorted(
        alertas_operacionais,
        key=lambda x: severidade_peso.get(str(x.get("severidade")), 0),
        reverse=True,
    )[:12]

    sugestoes_relatorios = [
        {
            "codigo": "janela_horario_ocioso",
            "titulo": "Ociosidade por Janela de Horario",
            "descricao": "Mostra horarios com baixa ocupacao para abrir encaixes ou reduzir deslocamentos improdutivos.",
        },
        {
            "codigo": "lead_time_agendamento",
            "titulo": "Antecedencia de Agendamento",
            "descricao": "Mede quantos dias antes cada clinica costuma agendar, ajudando previsao de demanda.",
        },
        {
            "codigo": "rentabilidade_por_clinica",
            "titulo": "Rentabilidade por Clinica",
            "descricao": "Cruza faturamento, taxa de cancelamento e distancia para priorizar parcerias de maior retorno.",
        },
        {
            "codigo": "pontualidade_operacional",
            "titulo": "Pontualidade e Atrasos",
            "descricao": "Identifica dias e rotas com maior risco de atraso para ajustar grade e margens.",
        },
        {
            "codigo": "mix_servicos_por_clinica",
            "titulo": "Mix de Servicos por Clinica",
            "descricao": "Evidencia quais clinicas concentram servicos de maior ticket e onde expandir oferta.",
        },
        {
            "codigo": "previsao_recebimentos_30d",
            "titulo": "Previsao de Recebimento 30 dias",
            "descricao": "Projeta entradas com base em OS pendentes para planejar fluxo de caixa com antecedencia.",
        },
    ]

    return {
        "periodo": {
            "data_inicio": inicio.isoformat(),
            "data_fim": fim.isoformat(),
            "data_referencia": referencia.isoformat(),
            "dias": int((fim - inicio).days + 1),
        },
        "parametros": {
            "perfil_deslocamento": perfil,
            "clinica_base_id_solicitada": clinica_base_id,
            "clinica_id": clinica_id,
            "servico_id": servico_id,
            "profissional_id": profissional_id,
            "regiao": regiao,
        },
        "base_operacional": {
            "clinica_id": base_id,
            "clinica_nome": base_nome,
            "criterio": criterio_base,
        },
        "logistica": {
            "km_projetado_dia": km_projetado_dia,
            "km_por_mes": km_por_mes,
            "rotas_mais_longas": rotas_mais_longas,
            "clinicas_mais_distantes_base": clinicas_distantes_base,
        },
        "producao": {
            "clinicas_mais_agendam": clinicas_mais_agendam,
            "servicos_mais_solicitados": servicos_mais_solicitados,
            "total_agendamentos": total_agendamentos,
            "realizados": total_realizados,
            "cancelados": total_cancelados,
            "faltas": total_faltas,
            "taxa_realizacao_percent": taxa_realizacao,
            "taxa_cancelamento_percent": taxa_cancelamento,
            "taxa_falta_percent": taxa_falta,
        },
        "financeiro": {
            "periodo": {
                "entradas_recebidas": round(entradas_periodo, 2),
                "saidas_pagas": round(saidas_periodo, 2),
                "saldo": round(entradas_periodo - saidas_periodo, 2),
                "taxas_pagamento": round(_to_float(taxas_pagamento_periodo), 2),
                "creditos_gerados": round(_to_float(creditos_gerados_periodo), 2),
                "valor_total_servicos": round(_to_float(valor_servicos_periodo), 2),
                "quantidade_servicos": int(qtd_servicos_periodo or 0),
            },
            "mes_referencia": {
                "mes": mes_ref_key,
                "ate_data_referencia": referencia.isoformat(),
                "entradas_recebidas": round(entradas_mes, 2),
                "saidas_pagas": round(saidas_mes, 2),
                "saldo": round(entradas_mes - saidas_mes, 2),
                "taxas_pagamento": round(_to_float(taxas_pagamento_mes), 2),
                "creditos_gerados": round(_to_float(creditos_gerados_mes), 2),
                "valor_total_servicos_realizados": valor_servicos_mes_float,
                "quantidade_servicos_realizados": qtd_servicos_mes_int,
                "ticket_medio_servico": ticket_medio_mes,
                "km_estimado_mes": round(km_mes_referencia, 2),
                "retorno_por_km": retorno_por_km_mes,
            },
            "clinicas_maior_faturamento": clinicas_maior_faturamento,
        },
        "indicadores_extras": {
            "retorno_por_km_mes_referencia": retorno_por_km_mes,
            "taxa_realizacao_percent": taxa_realizacao,
            "taxa_cancelamento_percent": taxa_cancelamento,
            "taxa_falta_percent": taxa_falta,
        },
        "rentabilidade": {
            "metodologia": metodologia_rentabilidade,
            "mensagem_metodologia": mensagem_metodologia,
            "dados_necessarios_para_real": dados_necessarios_rentabilidade_real,
            "pendencias_para_real": pendencias_rentabilidade_real,
            "cobertura_real": cobertura_real,
            "custos_frota": resumo_custos_frota,
            "ranking_clinicas": ranking_rentabilidade,
        },
        "alertas_operacionais": alertas_operacionais,
        "insights_avancados": {
            "ociosidade_janela_horario": ociosidade_janela_horario,
            "antecedencia_agendamento": {
                "media_dias": antecedencia_media_dias,
                "mediana_dias": antecedencia_mediana_dias,
                "amostras": len(lead_times_dias),
                "por_clinica": antecedencia_por_clinica,
            },
            "pontualidade_atrasos": pontualidade,
            "mix_servicos_por_clinica": mix_servicos_por_clinica,
            "previsao_recebimentos_30d": {
                "data_referencia": referencia.isoformat(),
                "data_limite": data_limite_recebimento.isoformat(),
                "valor_total_previsto": round(total_previsao_30d, 2),
                "itens": previsao_recebimentos_30d_itens,
            },
            "pendencias_recebimento": {
                "data_corte": referencia.isoformat(),
                "valor_total_pendente": round(total_pendencias_recebimento, 2),
                "itens": pendencias_recebimento_itens,
            },
        },
        "sugestoes_relatorios": sugestoes_relatorios,
    }


def _gerar_csv_relatorio_controle(payload: dict, secoes: list[str]) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";")

    periodo = payload.get("periodo", {})
    base = payload.get("base_operacional", {})
    logistica = payload.get("logistica", {})
    producao = payload.get("producao", {})
    financeiro = payload.get("financeiro", {})
    financeiro_periodo = (financeiro.get("periodo") or {}) if isinstance(financeiro, dict) else {}
    financeiro_mes = (financeiro.get("mes_referencia") or {}) if isinstance(financeiro, dict) else {}
    rentabilidade = payload.get("rentabilidade", {})
    insights = payload.get("insights_avancados", {})

    writer.writerow(["Relatorio Controle FortCordis"])
    writer.writerow(["Data inicio", periodo.get("data_inicio", "")])
    writer.writerow(["Data fim", periodo.get("data_fim", "")])
    writer.writerow(["Data referencia", periodo.get("data_referencia", "")])
    writer.writerow(["Clinica base", base.get("clinica_nome", "")])
    writer.writerow(["Secoes exportadas", ", ".join(secoes)])
    writer.writerow([])

    if "resumo" in secoes:
        writer.writerow(["Resumo operacional"])
        writer.writerow(["Indicador", "Valor"])
        km_dia = (logistica.get("km_projetado_dia") or {}) if isinstance(logistica, dict) else {}
        writer.writerow(["KM projetado dia", _formatar_numero(km_dia.get("km_total", 0))])
        writer.writerow(["Taxa realizacao %", _formatar_numero(producao.get("taxa_realizacao_percent", 0))])
        writer.writerow(["Taxa cancelamento %", _formatar_numero(producao.get("taxa_cancelamento_percent", 0))])
        writer.writerow(["Taxa falta %", _formatar_numero(producao.get("taxa_falta_percent", 0))])
        writer.writerow(["Valor servicos mes", _formatar_moeda_brl(financeiro_mes.get("valor_total_servicos_realizados", 0))])
        writer.writerow(["Retorno por km mes", _formatar_moeda_brl(financeiro_mes.get("retorno_por_km", 0))])
        writer.writerow([])

    if "logistica" in secoes:
        writer.writerow(["Logistica - KM por mes"])
        writer.writerow(["Mes", "KM total", "Duracao min", "Trechos", "Dias com rota"])
        for item in logistica.get("km_por_mes", []):
            writer.writerow(
                [
                    item.get("mes", ""),
                    _formatar_numero(item.get("km_total", 0)),
                    int(item.get("duracao_total_min", 0)),
                    int(item.get("trechos", 0)),
                    int(item.get("dias_com_rota", 0)),
                ]
            )
        writer.writerow([])

        writer.writerow(["Logistica - Rotas mais longas"])
        writer.writerow(["Origem", "Destino", "Distancia km", "Duracao min"])
        for item in logistica.get("rotas_mais_longas", []):
            writer.writerow(
                [
                    item.get("origem_nome", ""),
                    item.get("destino_nome", ""),
                    _formatar_numero(item.get("distancia_km", 0)),
                    int(item.get("duracao_min", 0)),
                ]
            )
        writer.writerow([])

    if "producao" in secoes:
        writer.writerow(["Producao - Clinicas que mais agendam"])
        writer.writerow(["Clinica", "Agendamentos", "Realizados", "Cancelados", "Taxa realizacao %"])
        for item in producao.get("clinicas_mais_agendam", []):
            writer.writerow(
                [
                    item.get("clinica_nome", ""),
                    int(item.get("agendamentos", 0)),
                    int(item.get("realizados", 0)),
                    int(item.get("cancelados", 0)),
                    _formatar_numero(item.get("taxa_realizacao_percent", 0)),
                ]
            )
        writer.writerow([])

        writer.writerow(["Producao - Servicos mais solicitados"])
        writer.writerow(["Servico", "Agendamentos", "Realizados", "Taxa realizacao %"])
        for item in producao.get("servicos_mais_solicitados", []):
            writer.writerow(
                [
                    item.get("servico_nome", ""),
                    int(item.get("agendamentos", 0)),
                    int(item.get("realizados", 0)),
                    _formatar_numero(item.get("taxa_realizacao_percent", 0)),
                ]
            )
        writer.writerow([])

    if "financeiro" in secoes:
        writer.writerow(["Financeiro - Resumo"])
        writer.writerow(["Indicador", "Valor"])
        writer.writerow(["Entradas recebidas periodo", _formatar_moeda_brl(financeiro_periodo.get("entradas_recebidas", 0))])
        writer.writerow(["Saidas pagas periodo", _formatar_moeda_brl(financeiro_periodo.get("saidas_pagas", 0))])
        writer.writerow(["Saldo periodo", _formatar_moeda_brl(financeiro_periodo.get("saldo", 0))])
        writer.writerow(["Taxas de pagamento periodo", _formatar_moeda_brl(financeiro_periodo.get("taxas_pagamento", 0))])
        writer.writerow(["Creditos gerados periodo", _formatar_moeda_brl(financeiro_periodo.get("creditos_gerados", 0))])
        writer.writerow(["Valor total servicos periodo", _formatar_moeda_brl(financeiro_periodo.get("valor_total_servicos", 0))])
        writer.writerow(["Valor total servicos mes", _formatar_moeda_brl(financeiro_mes.get("valor_total_servicos_realizados", 0))])
        writer.writerow(["Taxas de pagamento mes", _formatar_moeda_brl(financeiro_mes.get("taxas_pagamento", 0))])
        writer.writerow(["Creditos gerados mes", _formatar_moeda_brl(financeiro_mes.get("creditos_gerados", 0))])
        writer.writerow([])

        writer.writerow(["Financeiro - Clinicas maior faturamento"])
        writer.writerow(["Clinica", "Servicos", "Valor total"])
        for item in financeiro.get("clinicas_maior_faturamento", []):
            writer.writerow(
                [
                    item.get("clinica_nome", ""),
                    int(item.get("servicos", 0)),
                    _formatar_moeda_brl(item.get("valor_total", 0)),
                ]
            )
        writer.writerow([])

    if "rentabilidade" in secoes:
        writer.writerow(["Metodologia rentabilidade", str(rentabilidade.get("metodologia", ""))])
        writer.writerow(["Descricao metodologia", str(rentabilidade.get("mensagem_metodologia", ""))])
        custos_frota = rentabilidade.get("custos_frota", {})
        if isinstance(custos_frota, dict):
            writer.writerow(["Custos frota periodo", _formatar_moeda_brl(custos_frota.get("total_periodo", 0))])
            writer.writerow(["Custos frota nao alocados", _formatar_moeda_brl(custos_frota.get("nao_alocados", 0))])
        pendencias = rentabilidade.get("pendencias_para_real", [])
        if pendencias:
            writer.writerow(["Pendencias para calculo real"])
            for item in pendencias:
                writer.writerow([str(item)])
        writer.writerow([])

        writer.writerow(["Ranking de rentabilidade por clinica"])
        writer.writerow(
            [
                "Clinica",
                "Indice rentabilidade",
                "Retorno por km",
                "Despesa total",
                "Lucro liquido",
                "Margem %",
                "Valor total servicos",
                "Agendamentos",
                "Taxa realizacao %",
                "Taxa cancelamento %",
                "Distancia base km",
            ]
        )
        for item in rentabilidade.get("ranking_clinicas", []):
            writer.writerow(
                [
                    item.get("clinica_nome", ""),
                    _formatar_numero(item.get("indice_rentabilidade", 0)),
                    _formatar_moeda_brl(item.get("retorno_por_km", 0)),
                    _formatar_moeda_brl(item.get("despesa_total", 0)),
                    _formatar_moeda_brl(item.get("lucro_liquido", 0)),
                    _formatar_numero(item.get("margem_percent", 0)),
                    _formatar_moeda_brl(item.get("valor_total_servicos", 0)),
                    int(item.get("agendamentos", 0)),
                    _formatar_numero(item.get("taxa_realizacao_percent", 0)),
                    _formatar_numero(item.get("taxa_cancelamento_percent", 0)),
                    _formatar_numero(item.get("distancia_km_base", 0)),
                ]
            )
        writer.writerow([])

    if "alertas" in secoes:
        writer.writerow(["Alertas operacionais"])
        writer.writerow(["Severidade", "Titulo", "Descricao", "Recomendacao"])
        for alerta in payload.get("alertas_operacionais", []):
            writer.writerow(
                [
                    str(alerta.get("severidade", "")),
                    str(alerta.get("titulo", "")),
                    str(alerta.get("descricao", "")),
                    str(alerta.get("recomendacao", "")),
                ]
            )
        writer.writerow([])

    if "insights" in secoes:
        ociosidade = insights.get("ociosidade_janela_horario", [])
        writer.writerow(["Insights - Ociosidade por janela"])
        writer.writerow(["Inicio", "Fim", "Agendamentos", "Media dia", "Indice ociosidade %"])
        for item in ociosidade:
            writer.writerow(
                [
                    item.get("hora_inicio", ""),
                    item.get("hora_fim", ""),
                    int(item.get("agendamentos_total", 0)),
                    _formatar_numero(item.get("media_agendamentos_dia", 0)),
                    _formatar_numero(item.get("indice_ociosidade_percent", 0)),
                ]
            )
        writer.writerow([])

        antecedencia = insights.get("antecedencia_agendamento", {})
        writer.writerow(["Insights - Antecedencia de agendamento"])
        writer.writerow(["Indicador", "Valor"])
        writer.writerow(["Media dias", _formatar_numero(antecedencia.get("media_dias", 0)) if antecedencia.get("media_dias") is not None else "N/D"])
        writer.writerow(["Mediana dias", _formatar_numero(antecedencia.get("mediana_dias", 0)) if antecedencia.get("mediana_dias") is not None else "N/D"])
        writer.writerow(["Amostras", int(antecedencia.get("amostras", 0))])
        writer.writerow([])

        pontualidade = insights.get("pontualidade_atrasos", {})
        writer.writerow(["Insights - Pontualidade e atrasos"])
        writer.writerow(["Indicador", "Valor"])
        writer.writerow(["Transicoes", int(pontualidade.get("total_transicoes", 0))])
        writer.writerow(["Transicoes com risco", int(pontualidade.get("transicoes_com_risco", 0))])
        writer.writerow(["Taxa de risco %", _formatar_numero(pontualidade.get("taxa_risco_percent", 0))])
        writer.writerow([])

        previsao = insights.get("previsao_recebimentos_30d", {})
        writer.writerow(["Insights - Previsao de recebimentos 30 dias"])
        writer.writerow(["Data referencia", previsao.get("data_referencia", "")])
        writer.writerow(["Data limite", previsao.get("data_limite", "")])
        writer.writerow(["Valor total previsto", _formatar_moeda_brl(previsao.get("valor_total_previsto", 0))])
        writer.writerow([])

    if "sugestoes" in secoes:
        writer.writerow(["Sugestoes de novos relatorios"])
        writer.writerow(["Codigo", "Titulo", "Descricao"])
        for item in payload.get("sugestoes_relatorios", []):
            writer.writerow([item.get("codigo", ""), item.get("titulo", ""), item.get("descricao", "")])

    conteudo = "\ufeff" + buffer.getvalue()
    return conteudo.encode("utf-8")


def _gerar_pdf_relatorio_controle(payload: dict, secoes: list[str]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Relatorio Controle FortCordis",
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "RelatorioControleTitulo",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=14,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )
    style_section = ParagraphStyle(
        "RelatorioControleSecao",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=2,
        spaceBefore=8,
    )
    style_body = ParagraphStyle(
        "RelatorioControleTexto",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#111827"),
    )

    periodo = payload.get("periodo", {})
    base = payload.get("base_operacional", {})
    logistica = payload.get("logistica", {})
    producao = payload.get("producao", {})
    financeiro = payload.get("financeiro", {})
    financeiro_periodo = (financeiro.get("periodo") or {}) if isinstance(financeiro, dict) else {}
    financeiro_mes = (financeiro.get("mes_referencia") or {}) if isinstance(financeiro, dict) else {}
    rentabilidade = payload.get("rentabilidade", {})
    insights = payload.get("insights_avancados", {})

    story: list = []
    story.append(Paragraph("Relatorio Controle FortCordis", style_title))
    story.append(
        Paragraph(
            (
                f"Periodo: {periodo.get('data_inicio', '-')} ate {periodo.get('data_fim', '-')}<br/>"
                f"Referencia: {periodo.get('data_referencia', '-')}<br/>"
                f"Clinica base: {base.get('clinica_nome', '-')}<br/>"
                f"Secoes: {', '.join(secoes)}"
            ),
            style_body,
        )
    )
    story.append(Spacer(1, 3 * mm))

    if "resumo" in secoes:
        story.append(Paragraph("Resumo", style_section))
        km_dia = (logistica.get("km_projetado_dia") or {}) if isinstance(logistica, dict) else {}
        resumo_rows = [
            ["Indicador", "Valor"],
            ["KM projetado do dia", _formatar_numero(km_dia.get("km_total", 0)) + " km"],
            ["Taxa realizacao", _formatar_numero(producao.get("taxa_realizacao_percent", 0)) + "%"],
            ["Taxa cancelamento", _formatar_numero(producao.get("taxa_cancelamento_percent", 0)) + "%"],
            ["Taxa falta", _formatar_numero(producao.get("taxa_falta_percent", 0)) + "%"],
            ["Valor servicos no mes", _formatar_moeda_brl(financeiro_mes.get("valor_total_servicos_realizados", 0))],
            ["Retorno por km no mes", _formatar_moeda_brl(financeiro_mes.get("retorno_por_km", 0))],
            ["Taxas de pagamento no mes", _formatar_moeda_brl(financeiro_mes.get("taxas_pagamento", 0))],
            ["Creditos gerados no mes", _formatar_moeda_brl(financeiro_mes.get("creditos_gerados", 0))],
        ]
        tabela_resumo = Table(resumo_rows, colWidths=[90 * mm, 80 * mm], repeatRows=1)
        tabela_resumo.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
                    ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(tabela_resumo)

    if "financeiro" in secoes:
        story.append(Paragraph("Financeiro", style_section))
        tabela_financeiro = Table(
            [
                ["Indicador", "Valor"],
                ["Entradas recebidas (periodo)", _formatar_moeda_brl(financeiro_periodo.get("entradas_recebidas", 0))],
                ["Saidas pagas (periodo)", _formatar_moeda_brl(financeiro_periodo.get("saidas_pagas", 0))],
                ["Saldo (periodo)", _formatar_moeda_brl(financeiro_periodo.get("saldo", 0))],
                ["Taxas de pagamento (periodo)", _formatar_moeda_brl(financeiro_periodo.get("taxas_pagamento", 0))],
                ["Creditos gerados (periodo)", _formatar_moeda_brl(financeiro_periodo.get("creditos_gerados", 0))],
                ["Valor servicos (periodo)", _formatar_moeda_brl(financeiro_periodo.get("valor_total_servicos", 0))],
                ["Valor servicos (mes)", _formatar_moeda_brl(financeiro_mes.get("valor_total_servicos_realizados", 0))],
                ["Taxas de pagamento (mes)", _formatar_moeda_brl(financeiro_mes.get("taxas_pagamento", 0))],
                ["Creditos gerados (mes)", _formatar_moeda_brl(financeiro_mes.get("creditos_gerados", 0))],
            ],
            colWidths=[95 * mm, 75 * mm],
            repeatRows=1,
        )
        tabela_financeiro.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCFCE7")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                    ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(tabela_financeiro)

    if "logistica" in secoes:
        story.append(Paragraph("Logistica - Rotas mais longas", style_section))
        rotas_rows = [["Origem", "Destino", "KM", "Min"]]
        for item in logistica.get("rotas_mais_longas", [])[:10]:
            rotas_rows.append(
                [
                    str(item.get("origem_nome", "-"))[:30],
                    str(item.get("destino_nome", "-"))[:30],
                    _formatar_numero(item.get("distancia_km", 0)),
                    str(int(item.get("duracao_min", 0))),
                ]
            )
        if len(rotas_rows) == 1:
            rotas_rows.append(["Sem dados", "-", "-", "-"])
        tabela_rotas = Table(rotas_rows, colWidths=[62 * mm, 62 * mm, 20 * mm, 16 * mm], repeatRows=1)
        tabela_rotas.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DBEAFE")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.1),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                    ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(tabela_rotas)

    if "producao" in secoes:
        story.append(Paragraph("Producao - Clinicas que mais agendam", style_section))
        prod_rows = [["Clinica", "Ags", "Real.", "Canc.", "Taxa %"]]
        for item in producao.get("clinicas_mais_agendam", [])[:10]:
            prod_rows.append(
                [
                    str(item.get("clinica_nome", "-"))[:42],
                    str(int(item.get("agendamentos", 0))),
                    str(int(item.get("realizados", 0))),
                    str(int(item.get("cancelados", 0))),
                    _formatar_numero(item.get("taxa_realizacao_percent", 0)),
                ]
            )
        if len(prod_rows) == 1:
            prod_rows.append(["Sem dados", "-", "-", "-", "-"])
        tabela_prod = Table(prod_rows, colWidths=[82 * mm, 15 * mm, 15 * mm, 15 * mm, 25 * mm], repeatRows=1)
        tabela_prod.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FDE68A")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.1),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(tabela_prod)

    if "rentabilidade" in secoes:
        story.append(Paragraph("Ranking de rentabilidade por clinica", style_section))
        metodologia = str(rentabilidade.get("metodologia", "")).strip()
        mensagem_metodologia = str(rentabilidade.get("mensagem_metodologia", "")).strip()
        if metodologia or mensagem_metodologia:
            story.append(
                Paragraph(
                    (
                        f"Metodologia: <b>{metodologia or '-'}</b><br/>"
                        f"{mensagem_metodologia or ''}"
                    ),
                    style_body,
                )
            )
        custos_frota = rentabilidade.get("custos_frota", {})
        if isinstance(custos_frota, dict):
            story.append(
                Paragraph(
                    (
                        f"Custos de frota (periodo): {_formatar_moeda_brl(custos_frota.get('total_periodo', 0))}<br/>"
                        f"Custos de frota nao alocados: {_formatar_moeda_brl(custos_frota.get('nao_alocados', 0))}"
                    ),
                    style_body,
                )
            )
        pendencias = rentabilidade.get("pendencias_para_real", [])
        if isinstance(pendencias, list) and pendencias:
            story.append(Paragraph("Pendencias para calculo real:", style_body))
            for item in pendencias[:6]:
                story.append(Paragraph(f"- {str(item)}", style_body))
            story.append(Spacer(1, 1.2 * mm))

        ranking_rows = [["Clinica", "Indice", "R$/km", "Valor servicos", "Ags"]]
        for item in rentabilidade.get("ranking_clinicas", [])[:10]:
            ranking_rows.append(
                [
                    str(item.get("clinica_nome", "-"))[:38],
                    _formatar_numero(item.get("indice_rentabilidade", 0)),
                    _formatar_moeda_brl(item.get("retorno_por_km", 0)),
                    _formatar_moeda_brl(item.get("valor_total_servicos", 0)),
                    str(int(item.get("agendamentos", 0))),
                ]
            )
        if len(ranking_rows) == 1:
            ranking_rows.append(["Sem dados", "-", "-", "-", "-"])
        tabela_ranking = Table(ranking_rows, colWidths=[62 * mm, 25 * mm, 28 * mm, 35 * mm, 18 * mm], repeatRows=1)
        tabela_ranking.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DBEAFE")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(tabela_ranking)

    if "alertas" in secoes:
        story.append(Paragraph("Alertas operacionais", style_section))
        alertas = payload.get("alertas_operacionais", [])
        if not alertas:
            story.append(Paragraph("Sem alertas para os criterios atuais.", style_body))
        else:
            for alerta in alertas[:8]:
                story.append(
                    Paragraph(
                        (
                            f"<b>[{str(alerta.get('severidade', '')).upper()}] {str(alerta.get('titulo', 'Alerta'))}</b><br/>"
                            f"{str(alerta.get('descricao', '')).strip()}<br/>"
                            f"<i>Acao sugerida:</i> {str(alerta.get('recomendacao', '')).strip()}"
                        ),
                        style_body,
                    )
                )
                story.append(Spacer(1, 1.5 * mm))

    if "insights" in secoes:
        story.append(Paragraph("Insights avancados", style_section))
        antecedencia = insights.get("antecedencia_agendamento", {})
        pontualidade = insights.get("pontualidade_atrasos", {})
        previsao = insights.get("previsao_recebimentos_30d", {})
        story.append(
            Paragraph(
                (
                    f"Antecedencia media: {(_formatar_numero(antecedencia.get('media_dias', 0)) if antecedencia.get('media_dias') is not None else 'N/D')} dias<br/>"
                    f"Pontualidade - taxa de risco: {_formatar_numero(pontualidade.get('taxa_risco_percent', 0))}%<br/>"
                    f"Previsao de recebimentos 30d: {_formatar_moeda_brl(previsao.get('valor_total_previsto', 0))}"
                ),
                style_body,
            )
        )

    if "sugestoes" in secoes:
        story.append(Paragraph("Sugestoes de novos relatorios", style_section))
        for item in payload.get("sugestoes_relatorios", [])[:10]:
            story.append(
                Paragraph(
                    f"<b>{str(item.get('titulo', ''))}</b><br/>{str(item.get('descricao', ''))}",
                    style_body,
                )
            )
            story.append(Spacer(1, 1.2 * mm))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


@router.get("/controle/export/csv")
def exportar_relatorio_controle_csv(
    data_inicio: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    data_fim: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    data_referencia: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    perfil_deslocamento: str = Query(default="comercial"),
    clinica_base_id: Optional[int] = Query(default=None, ge=1),
    clinica_id: Optional[int] = Query(default=None, ge=1),
    servico_id: Optional[int] = Query(default=None, ge=1),
    profissional_id: Optional[int] = Query(default=None, ge=1),
    regiao: Optional[str] = Query(default=None),
    secoes: Optional[str] = Query(
        default=None,
        description=(
            "Lista separada por virgula. Ex.: financeiro,logistica "
            f"Valores: {', '.join(SECOES_EXPORT_ORDENADAS)}"
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = relatorio_controle_gerencial(
        data_inicio=data_inicio,
        data_fim=data_fim,
        data_referencia=data_referencia,
        perfil_deslocamento=perfil_deslocamento,
        clinica_base_id=clinica_base_id,
        clinica_id=clinica_id,
        servico_id=servico_id,
        profissional_id=profissional_id,
        regiao=regiao,
        db=db,
        current_user=current_user,
    )
    secoes_normalizadas = _normalizar_secoes_export(secoes)

    csv_bytes = _gerar_csv_relatorio_controle(payload, secoes=secoes_normalizadas)
    inicio = str(payload.get("periodo", {}).get("data_inicio", "inicio"))
    fim = str(payload.get("periodo", {}).get("data_fim", "fim"))
    sufixo = "-".join(secoes_normalizadas)
    filename = f"relatorio_controle_{sufixo}_{inicio}_{fim}.csv"
    return StreamingResponse(
        BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/controle/export/pdf")
def exportar_relatorio_controle_pdf(
    data_inicio: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    data_fim: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    data_referencia: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    perfil_deslocamento: str = Query(default="comercial"),
    clinica_base_id: Optional[int] = Query(default=None, ge=1),
    clinica_id: Optional[int] = Query(default=None, ge=1),
    servico_id: Optional[int] = Query(default=None, ge=1),
    profissional_id: Optional[int] = Query(default=None, ge=1),
    regiao: Optional[str] = Query(default=None),
    secoes: Optional[str] = Query(
        default=None,
        description=(
            "Lista separada por virgula. Ex.: financeiro,logistica "
            f"Valores: {', '.join(SECOES_EXPORT_ORDENADAS)}"
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = relatorio_controle_gerencial(
        data_inicio=data_inicio,
        data_fim=data_fim,
        data_referencia=data_referencia,
        perfil_deslocamento=perfil_deslocamento,
        clinica_base_id=clinica_base_id,
        clinica_id=clinica_id,
        servico_id=servico_id,
        profissional_id=profissional_id,
        regiao=regiao,
        db=db,
        current_user=current_user,
    )
    secoes_normalizadas = _normalizar_secoes_export(secoes)

    pdf_bytes = _gerar_pdf_relatorio_controle(payload, secoes=secoes_normalizadas)
    inicio = str(payload.get("periodo", {}).get("data_inicio", "inicio"))
    fim = str(payload.get("periodo", {}).get("data_fim", "fim"))
    sufixo = "-".join(secoes_normalizadas)
    filename = f"relatorio_controle_{sufixo}_{inicio}_{fim}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
