#!/usr/bin/env python3
"""One-shot authorized Maps cutover. No provider, appointment or auth writes."""
import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('/var/www/fortcordis-v2')
UNITS = ('fortcordis-backend', 'fortcordis-backend-worker')


def observed_baseline(route_month, route_day, emergency_month, emergency_day):
    # These sources overlap. Max is an observable floor, never a reconciled total
    # or an upper bound; extra actions stay zero regardless of remaining budget.
    month = max(route_month, emergency_month.get('routes_essentials', 0), 6487) + max(emergency_month.get('geocoding', 0), 23)
    day = max(route_day, emergency_day.get('routes_essentials', 0)) + emergency_day.get('geocoding', 0)
    return {'day': {'calls': day, 'estimated_brl': str(Decimal(day) * Decimal('0.036'))},
            'month': {'calls': max(month, day), 'estimated_brl': str(Decimal(max(month, day)) * Decimal('0.036'))}}


def upsert_env(path, changes):
    old = path.read_text()
    lines = old.splitlines()
    for key, value in changes.items():
        lines = [line for line in lines if not re.match(r'^\s*(?:export\s+)?' + re.escape(key) + r'\s*=', line)]
        lines.append(key + '=' + value)
    stat = path.stat()
    fd, name = tempfile.mkstemp(prefix='.maps-env-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write('\n'.join(lines) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        os.chmod(name, stat.st_mode & 0o777)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
    return hashlib.sha256(old.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args()
    assert re.fullmatch('[a-f0-9]{40}', args.expected_sha)
    assert ROOT.resolve() == ROOT and Path.cwd().resolve() == ROOT
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    assert sha == args.expected_sha
    assert subprocess.check_output(['git', 'rev-parse', 'origin/main'], text=True).strip() == sha
    credential = json.load(sys.stdin)['sudo_password']
    assert credential
    os.chdir(ROOT/'backend'); sys.path.insert(0, str(ROOT/'backend'))
    from app.core.config import Settings
    preview_settings = Settings(APP_ENV='production')
    assert len(preview_settings.SECRET_KEY) >= 32
    assert preview_settings.GOOGLE_MAPS_COST_EMERGENCY_RELEASE is True
    sys.path.insert(0, str(ROOT/'scripts'))
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    engine = create_engine(preview_settings.DATABASE_URL, poolclass=NullPool)
    evidence = ROOT/'backend/private/maps-activation-20261022'
    evidence.mkdir(parents=True, exist_ok=True); evidence.chmod(0o700)
    result = {'sha': sha, 'started_at': datetime.now(timezone.utc).isoformat(),
              'google_calls_from_activation': 0, 'business_records_modified': 0,
              'historical_baseline_complete': False, 'extra_actions_enabled': False}
    stopped = False

    def privileged(*command):
        proc = subprocess.run(['sudo', '-S', '-p', '', *command], input=credential+'\n',
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if proc.returncode: raise RuntimeError('Privileged command failed: '+command[0])

    def unit_state(unit):
        return subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','MainPID','-p','ExecMainStartTimestamp'], text=True).strip()

    def terminate(signum, frame):
        raise RuntimeError('Cutover interrupted')
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        # Confirm project before touching runtime. Never print DB URL or keys.
        with engine.connect() as conn:
            dbname = conn.execute(text('select current_database()')).scalar()
            assert 'stage' not in dbname.lower()
            assert hashlib.sha256(preview_settings.DATABASE_URL.encode()).hexdigest() == '2b9e80b81fff69d2a36ac7d695262d8deefb6b721210c0555e7afd795b9032d1'
            assert conn.execute(text('select count(*) from google_maps_cost_config')).scalar() == 0
            assert conn.execute(text("select count(*) from pg_namespace where nspname like 'maps_canary_%'")).scalar() == 0
        result['old_units'] = {unit: unit_state(unit) for unit in UNITS}
        stopped = True
        privileged('/bin/systemctl','stop',*UNITS)
        for unit in UNITS:
            state = unit_state(unit)
            assert 'ActiveState=inactive' in state and 'MainPID=0' in state
        # No older cost-capable service remains in this deployment directory.
        old_pids=[]
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit() or int(proc.name)==os.getpid(): continue
            try:
                if (proc/'cwd').resolve() == ROOT/'backend':
                    command=(proc/'cmdline').read_bytes().replace(b'\x00',b' ')
                    if b'uvicorn' in command or b'app.worker' in command:old_pids.append(proc.name)
            except (OSError,PermissionError):pass
        assert not old_pids
        now = datetime.now(ZoneInfo('America/Fortaleza'))
        month_start=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        day_start=now.replace(hour=0,minute=0,second=0,microsecond=0)
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            def count(start):
                return conn.execute(text("select count(*) from google_maps_usage_metricas where operation='compute_routes' and created_at >= :start"),{'start':start.astimezone(timezone.utc).replace(tzinfo=None)}).scalar()
            route_month,route_day=count(month_start),count(day_start)
            admin_ids=conn.execute(text("select id from usuarios where ativo=1 order by id")).scalars().all()
        # Resolve the real administrator through the existing role model.
        from app.db.database import SessionLocal
        from app.models.user import User
        with SessionLocal() as db:
            actor=next(user.id for user in db.query(User).filter(User.id.in_(admin_ids)).all() if user.tem_papel('admin'))
        def attempts(start):
            raw=subprocess.check_output(['journalctl','--no-pager','--output=json','--since',start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),'-u',UNITS[0],'-u',UNITS[1]],text=True)
            counts={}
            for line in raw.splitlines():
                message=json.loads(line).get('MESSAGE','')
                if 'google_maps_emergency_release_attempt' not in message:continue
                match=re.search(r'"sku":\s*"([a-z_]+)"',message)
                if match:counts[match.group(1)]=counts.get(match.group(1),0)+1
            assert not set(counts)-{'routes_essentials','geocoding'}, 'Unexpected SKU needs baseline review'
            return counts
        emergency_month,emergency_day=attempts(month_start),attempts(day_start)
        baseline=observed_baseline(route_month,route_day,emergency_month,emergency_day)
        result.update({'cutover_at':now.isoformat(),'telemetry':{'route_month':route_month,'route_day':route_day},
                       'emergency_month':emergency_month,'emergency_day':emergency_day,'opening_usage':baseline,
                       'baseline_note':'Observable historical floor; incomplete Billing reconciliation. Overlapping sources use max, never sum. Known Google snapshot 1-22 Oct: 6487 Routes and 23 Geocoding. No free credit inferred. All non-Agenda caps remain zero.'})
        upsert_env(ROOT/'backend/.env',{'APP_ENV':'production','GOOGLE_MAPS_AGENDA_CACHE_FIRST':'true','GOOGLE_MAPS_COST_EMERGENCY_RELEASE':'false'})
        # Import the service only AFTER env transition; never reuse cached settings.
        os.environ.update(APP_ENV='production',GOOGLE_MAPS_AGENDA_CACHE_FIRST='true',GOOGLE_MAPS_COST_EMERGENCY_RELEASE='false')
        from app.core.config import settings
        settings.APP_ENV='production';settings.GOOGLE_MAPS_AGENDA_CACHE_FIRST=True;settings.GOOGLE_MAPS_COST_EMERGENCY_RELEASE=False
        from app.services.google_maps_cost_control import CostConfiguration, update_configuration
        payload=json.loads((ROOT/'docs/specs/google-maps-enforced-budget/approved-monitor-config.json').read_text())
        assert payload['limits']['day']=={'calls':650,'estimated_brl':25}
        assert payload['limits']['month']=={'calls':13000,'estimated_brl':500}
        assert all(cap==0 for action,cap in payload['action_call_caps'].items() if not action.startswith('agenda_'))
        assert payload['automatic_policies']=={} and payload['agenda_budget_mode']=='monitor'
        payload.update(enabled=True,opening_usage=baseline,opening_usage_as_of=now.date().isoformat(),opening_usage_basis='verified_telemetry')
        config=CostConfiguration.model_validate(payload)
        assert config.pricing_valid_until > now
        status=update_configuration(actor,config,expected_revision=0)
        assert status['enabled'] and status['agenda_budget_mode']=='monitor' and status['revision']==1
        with engine.connect() as conn:
            row=conn.execute(text('select revision, config_json from google_maps_cost_config where id=1')).one()
            assert row.revision==1 and json.loads(row.config_json)==json.loads(config.model_dump_json(exclude_none=True))
        privileged('/bin/systemctl','start',*UNITS)
        result['new_units']={unit:unit_state(unit) for unit in UNITS}
        assert all('ActiveState=active' in state and 'MainPID=0' not in state for state in result['new_units'].values())
        result.update(revision=1,enabled=True,agenda_budget_mode='monitor',emergency_release=False,passed=True)
    except BaseException:
        if stopped:
            upsert_env(ROOT/'backend/.env',{'GOOGLE_MAPS_COST_EMERGENCY_RELEASE':'true'})
            privileged('/bin/systemctl','restart',*UNITS)
        result.update(passed=False,emergency_rollback=stopped)
        raise
    finally:
        engine.dispose()
        (evidence/'result.json').write_text(json.dumps(result,indent=2))
        (evidence/'result.json').chmod(0o600)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
