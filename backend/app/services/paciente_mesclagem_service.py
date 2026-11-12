"""Consolidation of one explicitly reviewed pair; preserve record and document IDs."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unicodedata

from fastapi import HTTPException
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.models.paciente import Paciente
from app.models.paciente_mesclagem import PacienteMesclagem
from app.models.tutor import Tutor
from app.services.paciente_mesclagem_vinculos import PRESERVAR, TRANSFERIR
from app.utils.referencia_eco_defaults import normalizar_especie_referencia

IDENTIDADE = ("especie", "sexo", "nascimento", "microchip")
CAMPOS_PREVIA = {
    "exames": ("tipo_exame", "status", "data_solicitacao", "data_resultado", "atendimento_id", "laudo_id"),
    "laudos": ("titulo", "tipo", "status", "data_exame", "data_laudo", "agendamento_id", "updated_at"),
    "atendimentos_clinicos": ("status", "data_atendimento", "agendamento_id", "updated_at"),
}
LIMITE_VINCULOS = 2500


def _normalizar(valor):
    return "".join(c for c in unicodedata.normalize("NFKD", str(valor or "").strip().casefold())
                   if not unicodedata.combining(c))


def _ativo(valor):
    return _normalizar(valor) in ("", "1", "true", "t")


def _chave(p, s):
    if p == s:
        raise HTTPException(422, "Selecione dois cadastros de paciente diferentes.")
    return f"{min(p, s)}:{max(p, s)}"


def _data(valor):
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=valor.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    return str(valor) if valor is not None else None


def _cadastro(paciente, tutor):
    campos = ("id", "nome", "tutor_id", *IDENTIDADE, "raca", "ativo", "mesclado_em_id")
    return {**{c: getattr(paciente, c) for c in campos},
            "tutor": tutor.nome if tutor else None, "atualizado_em": _data(paciente.updated_at)}


def _dupla(db, p, s, *, lock=False):
    _chave(p, s)
    q = db.query(Paciente).filter(Paciente.id.in_((p, s))).order_by(Paciente.id)
    if lock:
        q = q.with_for_update(nowait=True)
    rows = {r.id: r for r in q.populate_existing().all()}
    if len(rows) != 2:
        raise HTTPException(404, "Um dos pacientes não foi encontrado.")
    if any(r.mesclado_em_id or not _ativo(r.ativo) for r in rows.values()):
        raise HTTPException(409, "Selecione dois pacientes ativos que ainda não foram mesclados.")
    return rows[p], rows[s]


def _inventario(db):
    columns = inspect(db.connection()).get_multi_columns()
    return {table: {c["name"] for c in cols} for (_, table), cols in columns.items()}


def _referencias(tables):
    return {table: col for table, col in {**TRANSFERIR, **PRESERVAR}.items()
            if col in tables.get(table, set())}


def _desconhecidas(tables, refs):
    ignorar = {"pacientes", "pacientes_mesclagens", "schema_migrations"}
    return [(t, c) for t, cols in sorted(tables.items()) if t not in ignorar
            for c in ("paciente_id", "patient_id") if c in cols and refs.get(t) != c]


def _ler(db, table, col, campos, p, s):
    quote = db.get_bind().dialect.identifier_preparer.quote_identifier
    campos = ", ".join(map(quote, campos))
    sql = (f"SELECT {campos} FROM {quote(table)} WHERE {quote(col)} IN (:p,:s) "
           f"ORDER BY id LIMIT {LIMITE_VINCULOS + 1}")
    return [dict(row) for row in db.execute(text(sql), {"p": p, "s": s}).mappings()]


def _portal_em_uso(rows):
    # A sessão pode durar além do vencimento do desafio que a originou.
    margem = timedelta(minutes=max(1, settings.PORTAL_SESSION_TOKEN_EXPIRE_MINUTES))
    agora = datetime.now(timezone.utc)
    for row in rows:
        if row["status"] not in ("pending", "consumed"):
            continue
        try:
            expires = row["expires_at"]
            expires = expires if isinstance(expires, datetime) else datetime.fromisoformat(expires)
            expires = expires.replace(tzinfo=expires.tzinfo or timezone.utc)
        except (ValueError, TypeError):
            return True
        if expires + margem >= agora:
            return True
    return False


def _verificar_vinculos_cruzados(db, tables, p, s):
    # Uma referência histórica cruzada dentro da dupla converge. Um terceiro
    # paciente precisa ser esclarecido antes da mesclagem.
    relacoes = (
        ("exames", "atendimento_id", "atendimentos_clinicos"),
        ("exames", "laudo_id", "laudos"),
        ("atendimentos_clinicos", "agendamento_id", "agendamentos"),
        ("laudos", "agendamento_id", "agendamentos"),
        ("ordens_servico", "agendamento_id", "agendamentos"),
        ("ordens_servico", "laudo_id", "laudos"),
        ("ordens_servico", "atendimento_id", "atendimentos_clinicos"),
    )
    for origem, campo, destino in relacoes:
        if not {"paciente_id", campo} <= tables.get(origem, set()) or "paciente_id" not in tables.get(destino, set()):
            continue
        for lado, outro in (("a", "b"), ("b", "a")):
            if db.execute(text(f"""
                SELECT 1 FROM "{origem}" a JOIN "{destino}" b ON a."{campo}"=b.id
                WHERE {lado}.paciente_id IN (:p,:s) AND {outro}.paciente_id NOT IN (:p,:s)
                LIMIT 1
            """), {"p": p, "s": s}).first():
                return True
    return False


def _previa(db, principal, secundario, tables):
    p, s = principal.id, secundario.id
    tutores = {t.id: t for t in db.query(Tutor).filter(Tutor.id.in_(
        [t for t in {principal.tutor_id, secundario.tutor_id} if t is not None])).all()}
    fichas = [_cadastro(a, tutores.get(a.tutor_id)) for a in (principal, secundario)]
    bloqueios = []
    tutor = tutores.get(principal.tutor_id)
    if not tutor or principal.tutor_id != secundario.tutor_id or tutor.mesclado_em_id or not _ativo(tutor.ativo):
        bloqueios.append("Os dois cadastros precisam estar vinculados ao mesmo tutor ativo. Confira a identificação antes.")
    for c, label in zip(IDENTIDADE, ("espécie", "sexo", "nascimento", "microchip")):
        vals = [_normalizar(normalizar_especie_referencia(f[c]) if c == "especie" else f[c]) for f in fichas]
        if c == "microchip":
            vals = ["".join(v.split()) for v in vals]
        if all(vals) and vals[0] != vals[1]:
            bloqueios.append(f"Há divergência de {label}. Confira os dados de identificação antes de mesclar.")
    if db.query(Paciente.id).filter(Paciente.mesclado_em_id == s).first():
        bloqueios.append("O cadastro secundário já é o principal de outra mesclagem. Escolha-o como principal.")
    refs = _referencias(tables)
    agrupado, detalhes, contagens = {}, {}, {}
    for table, col in sorted(refs.items()):
        campos = set(CAMPOS_PREVIA.get(table, ())) & tables[table]
        if "tutor_id" in tables[table]:
            campos.add("tutor_id")
        if table == "portal_access_challenges":
            campos.update(("status", "expires_at"))
        rows = _ler(db, table, col, ("id", col, *sorted(campos)), p, s)
        agrupado[table] = rows
        if len(rows) > LIMITE_VINCULOS:
            bloqueios.append("O volume de vínculos excede o limite da revisão assistida. Solicite revisão técnica.")
        if table in TRANSFERIR:
            contagens[table] = {"principal": sum(r[col] == p for r in rows),
                                "secundario": sum(r[col] == s for r in rows)}
            if tutor and any(r.get("tutor_id") not in (None, tutor.id) for r in rows):
                bloqueios.append("Há vínculos registrados para outro tutor. A mesclagem requer revisão técnica.")
        if table in CAMPOS_PREVIA:
            detalhes[table] = [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in r.items()
                                if k not in {"tutor_id", "updated_at"}} for r in rows[:LIMITE_VINCULOS]]

    if any(_normalizar(r.get("status")) not in ("concluido", "cancelado")
           for r in agrupado.get("atendimentos_clinicos", ())):
        bloqueios.append("Há atendimento em aberto. Salve a revisão para depois e conclua a consulta antes de mesclar.")
    if _portal_em_uso(agrupado.get("portal_access_challenges", ())):
        bloqueios.append("Há um acesso recente do tutor ao portal. Aguarde sua expiração e gere uma nova prévia.")
    if any(r["patient_id"] == s for r in agrupado.get("ai_echo_sessions", ())):
        bloqueios.append("O secundário tem sessões vinculadas ao assistente de ecocardiografia. Mantenha-o como principal ou solicite revisão técnica.")
    if _verificar_vinculos_cruzados(db, tables, p, s):
        bloqueios.append("Há exames, laudos ou atendimentos relacionados a outro paciente. Confira os vínculos antes de mesclar.")
    for table, col in _desconhecidas(tables, refs):
        q = db.get_bind().dialect.identifier_preparer.quote_identifier
        if db.execute(text(f"SELECT 1 FROM {q(table)} WHERE {q(col)} IN (:p,:s) LIMIT 1"), {"p": p, "s": s}).first():
            bloqueios.append("Há vínculos que a revisão assistida não pode transferir. Solicite revisão técnica.")
            break
    bloqueios = list(dict.fromkeys(bloqueios))
    estado = [fichas, agrupado, bloqueios]
    token = hashlib.sha256(json.dumps(estado, sort_keys=True, default=_data).encode()).hexdigest()
    return {"principal": fichas[0], "secundario": fichas[1], "vinculos": contagens,
            "registros": detalhes, "bloqueios": bloqueios, "token_previa": token}, agrupado


def previa(db, p, s):
    principal, secundario = _dupla(db, p, s)
    return _previa(db, principal, secundario, _inventario(db))[0]


def _usuario(user):
    return str(getattr(user, "nome", None) or getattr(user, "username", None) or user.id)[:255]


def serializar(r, nomes=None):
    return {"id": r.id, "principal_id": r.principal_id, "secundario_id": r.secundario_id, "estado": r.estado,
            **({"principal_nome": nomes.get(r.principal_id), "secundario_nome": nomes.get(r.secundario_id)}
               if nomes is not None else {}),
            "criado_por": r.criado_por_nome, "criado_em": _data(r.criado_em), "motivo": r.motivo,
            "confirmado_por": r.confirmado_por_nome, "confirmado_em": _data(r.confirmado_em),
            "evidencia": r.evidencia}


def _registro(db, p, s):
    return db.query(PacienteMesclagem).filter_by(par_chave=_chave(p, s)).first()


def _novo(p, s, user):
    return PacienteMesclagem(par_chave=_chave(p, s), principal_id=p, secundario_id=s, estado="pendente",
                             criado_por_id=user.id, criado_por_nome=_usuario(user))


def _travar(db, tables):
    # Short, explicit write window. Read-only previews never lock application data.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        db.execute(text("SET LOCAL statement_timeout = '6s'"))
        refs = _referencias(tables)
        names = set(refs) | {"pacientes", "pacientes_mesclagens", "tutores"}
        names.update(t for t, _ in _desconhecidas(tables, refs))
        quote = db.get_bind().dialect.identifier_preparer.quote_identifier
        db.execute(text("LOCK TABLE " + ", ".join(quote(n) for n in sorted(names))
                        + " IN SHARE ROW EXCLUSIVE MODE NOWAIT"))
        guardadas = set(db.execute(text("""
            SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            WHERE c.relnamespace=to_regnamespace(current_schema())
              AND t.tgname='bloquear_codigo_mesclado' AND t.tgenabled IN ('O', 'A')
        """)).scalars())
        if not set(refs) <= guardadas:
            raise HTTPException(409, "A proteção dos vínculos ainda não está completa. Solicite revisão técnica.")
    elif db.get_bind().dialect.name == "sqlite":
        # The write lock is acquired before reading/revalidating the pair.
        db.execute(text("UPDATE pacientes_mesclagens SET estado=estado WHERE 1=0"))


def adiar(db, p, s, user):
    try:
        if db.get_bind().dialect.name == "sqlite":
            db.execute(text("UPDATE pacientes_mesclagens SET estado=estado WHERE 1=0"))
        _dupla(db, p, s, lock=True)
        r = _registro(db, p, s)
        if not r:
            r = _novo(p, s, user)
            db.add(r)
        db.flush()
        resp = serializar(r)
        db.commit()
        return resp
    except DBAPIError as exc:
        db.rollback()
        raise HTTPException(409, "O cadastro está em uso. Tente guardar a revisão novamente.") from exc
    except Exception:
        db.rollback()
        raise


def concluir(db, p, s, token, motivo, confirmado, user):
    motivo = motivo.strip()
    if not confirmado or len(motivo) < 5:
        raise HTTPException(422, "Confirme que é o mesmo animal e informe o motivo da mesclagem.")
    try:
        tables = _inventario(db)
        _travar(db, tables)
        r = _registro(db, p, s)
        if r and r.estado == "concluida":
            if (r.principal_id, r.secundario_id, r.motivo) != (p, s, motivo):
                raise HTTPException(409, "Essa dupla já foi mesclada.")
            resp = serializar(r)
            db.rollback()
            return resp
        principal, secundario = _dupla(db, p, s, lock=True)
        atual, agrupado = _previa(db, principal, secundario, tables)
        if atual["bloqueios"]:
            raise HTTPException(409, " ".join(atual["bloqueios"]))
        if token != atual["token_previa"]:
            raise HTTPException(409, "Os cadastros ou vínculos mudaram. Gere e confira uma nova prévia.")
        movidos = {}
        for table, col in TRANSFERIR.items():
            ids = [row["id"] for row in agrupado.get(table, ()) if row[col] == s]
            if not ids:
                continue
            # Only the foreign-reference value changes. No timestamps, results,
            # clinical text, totals, portal releases or generated files are rewritten.
            result = db.execute(text(f'UPDATE "{table}" SET "{col}"=:p WHERE "{col}"=:s'), {"p": p, "s": s})
            if result.rowcount != len(ids):
                raise HTTPException(409, "Os vínculos mudaram. Gere e confira uma nova prévia.")
            movidos[table] = ids
        secundario.ativo = 0
        secundario.mesclado_em_id = p
        if r is None:
            r = _novo(p, s, user)
            db.add(r)
        r.principal_id, r.secundario_id = p, s
        r.estado = "concluida"
        r.confirmado_por_id, r.confirmado_por_nome = user.id, _usuario(user)
        r.confirmado_em = datetime.now(timezone.utc)
        r.motivo = motivo
        r.evidencia = {"principal": atual["principal"], "secundario": atual["secundario"], "movidos": movidos}
        db.flush()
        db.query(PacienteMesclagem).filter(PacienteMesclagem.estado == "pendente",
            or_(PacienteMesclagem.principal_id == s, PacienteMesclagem.secundario_id == s)).update(
                {"estado": "indisponivel"}, synchronize_session=False)
        resp = serializar(r)
        db.commit()
        return resp
    except DBAPIError as exc:
        db.rollback()
        raise HTTPException(409, "Não foi possível mesclar com segurança. Confira os vínculos e gere uma nova prévia.") from exc
    except Exception:
        db.rollback()
        raise
