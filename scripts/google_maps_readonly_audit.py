#!/usr/bin/env python3
"""Aggregate-only Google Maps audit; no provider calls or database mutations.

Run from an authorized environment with its existing backend configuration.
Emits JSON to stdout. Never emits credential values, addresses or entity IDs.
"""
import os
import sys
from pathlib import Path
backend = Path(__file__).resolve().parents[1] / "backend"
os.chdir(backend)
sys.path.insert(0, str(backend))

import json,subprocess
from sqlalchemy import create_engine,text
from app.core.config import settings
result={'sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'safe_config':{k:getattr(settings,k,None) for k in ['GOOGLE_ROUTES_CACHE_MAX_AGE_DAYS','GOOGLE_MAPS_USAGE_METRICS_RETENTION_DAYS','LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ','LOGISTICA_FORCE_REFRESH_HEURISTICA_COM_API_KEY','LOGISTICA_GOOGLE_TRAFFIC_AWARE']},'google_key_configured':bool(settings.GOOGLE_MAPS_API_KEY)}
queries={
'metrics_coverage':"select count(*) total,min(created_at) oldest,max(created_at) newest from google_maps_usage_metricas",
'monthly_operations':"select date_trunc('month', created_at)::date as month,operation,provider,status,count(*) n from google_maps_usage_metricas group by 1,2,3,4 order by 1,2,3,4",
'daily_metrics':"select created_at::date as date_ref,count(*) n from google_maps_usage_metricas where operation='compute_routes' and created_at>='2026-07-01' and created_at<'2026-09-01' group by 1 order by 1",
'clinic_count':"select count(*) total, count(*) filter(where ativo) active from clinicas",
'per_pair_monthly_distribution':"with pairs as(select date_trunc('month',created_at)::date as month,origem_clinica_id,destino_clinica_id,count(*) n from google_maps_usage_metricas where operation='compute_routes' and created_at>='2026-07-01' and created_at<'2026-09-01' group by 1,2,3)select month,count(*) pairs,sum(n) calls,max(n) max_per_pair,percentile_cont(0.5)within group(order by n) median_per_pair,count(*)filter(where n>30) pairs_over30 from pairs group by 1 order by 1",
'repeated_pairs_in_hour':"with pairs as(select date_trunc('month',created_at)::date as month, date_trunc('hour',created_at) as hour,origem_clinica_id,destino_clinica_id,count(*) n from google_maps_usage_metricas where operation='compute_routes' and created_at>='2026-07-01' and created_at<'2026-09-01' group by 1,2,3,4)select month,sum(n) calls,sum(greatest(n-1,0)) extra_same_pair_same_hour,max(n) max_per_pair_hour from pairs group by 1 order by 1",
'calls_after_current_row_ttl':"select date_trunc('month',m.created_at)::date as month,count(*) metric_calls,count(*) filter(where d.id is not null) paired_current_cache,count(*) filter(where d.updated_at<m.created_at-interval '30 days') cache_already_stale_at_call,count(*) filter(where d.updated_at<m.created_at) current_cache_predates_call from google_maps_usage_metricas m left join clinica_deslocamentos d on d.origem_clinica_id=m.origem_clinica_id and d.destino_clinica_id=m.destino_clinica_id and d.perfil=m.perfil where m.operation='compute_routes' and m.status='ok' and m.created_at>='2026-07-01' and m.created_at<'2026-09-01' group by 1 order by 1",
'short_interval_calls':"with pairs as(select date_trunc('month',created_at)::date as month,origem_clinica_id,destino_clinica_id,created_at-lag(created_at)over(partition by origem_clinica_id,destino_clinica_id order by created_at) as delta from google_maps_usage_metricas where operation='compute_routes' and created_at>='2026-07-01' and created_at<'2026-09-01') select month,count(*)filter(where delta<interval '1 second') within_one_second,count(*)filter(where delta<interval '1 minute') within_one_minute from pairs group by 1 order by 1",
'audit_aggregate':"select date_trunc('month',created_at)::date as month,acao,count(*) n from auditoria_eventos where created_at>='2026-07-01' and created_at<'2026-09-01' and modulo='agenda' group by 1,2 order by 1,3 desc"
}
engine=create_engine(settings.DATABASE_URL)
if engine.dialect.name != "postgresql":
 raise RuntimeError("Read-only audit requires PostgreSQL transaction protection")
for name,query in queries.items():
 try:
  with engine.connect() as con:
   with con.begin():
    con.execute(text('SET TRANSACTION READ ONLY'))
    con.execute(text("SET LOCAL statement_timeout='12s'"))
    result[name]=[dict(r._mapping) for r in con.execute(text(query))]
 except Exception as e:result[name]={'error_class':type(e).__name__}
print(json.dumps(result,default=str))
