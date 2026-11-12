"""Mesclagem administrativa: previa atual, escolhas explicitas e commit unico."""
import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.models.tutor import Tutor
from app.models.tutor_mesclagem import TutorMesclagem

ENDERECO = ("cep", "endereco", "numero", "complemento", "bairro", "cidade", "estado",
            "latitude", "longitude", "place_id", "endereco_normalizado")
CAMPOS = ("nome", "telefone", "whatsapp", "email", "cpf",
          "origem_cadastro", "identificacao_observacoes", "endereco")


def _json(value):
    def serializar(item):
        if isinstance(item, datetime):
            return item.replace(tzinfo=item.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
        return str(item)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=serializar)


def _snapshot(tutor):
    fields = {c.name: getattr(tutor, c.name) for c in Tutor.__table__.columns}
    return json.loads(_json(fields))


def _dados(tutor):
    return {campo: ({c: getattr(tutor, c) for c in ENDERECO} if campo == "endereco"
                    else getattr(tutor, campo)) for campo in CAMPOS}


def _preenchido(value):
    if isinstance(value, dict):
        return any(_preenchido(v) for v in value.values())
    return value is not None and value != ""


def _referencias(db):
    inspector = inspect(db.connection())
    return sorted(t for (_, t), columns in inspector.get_multi_columns().items()
                  if "tutor_id" in {c["name"] for c in columns})


def _quote(db, name):
    return db.bind.dialect.identifier_preparer.quote(name)


def _vinculos_snapshot(db, principal_id, secundario_id):
    vinculos = {}
    for tabela in _referencias(db):
        rows = db.execute(text(f'SELECT * FROM {_quote(db, tabela)} WHERE tutor_id IN (:p, :s)'),
                          {"p": principal_id, "s": secundario_id}).mappings().all()
        if rows and any("id" not in row for row in rows):
            raise HTTPException(409, f"Revisao tecnica necessaria para os vinculos de {tabela}.")
        vinculos[tabela] = sorted([dict(row) for row in rows], key=lambda r: r["id"])
    return vinculos


def _bloquear_cadastros(db, principal_id):
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("LOCK TABLE tutores IN EXCLUSIVE MODE"))
        tabelas = _referencias(db)
        if "portal_access_challenges" in inspect(db.connection()).get_table_names():
            tabelas.append("portal_access_challenges")
        if tabelas:
            db.execute(text("LOCK TABLE " + ", ".join(_quote(db, t) for t in sorted(tabelas)) + " IN SHARE ROW EXCLUSIVE MODE"))
    elif db.bind.dialect.name == "sqlite":
        db.execute(text("UPDATE tutores SET id=id WHERE id=:id"), {"id": principal_id})


def _estado_cadastros(db, principal, secundario):
    return json.loads(_json({"principal": _snapshot(principal), "secundario": _snapshot(secundario),
                            "vinculos": _vinculos_snapshot(db, principal.id, secundario.id)}))


def _preparar(db, principal_id, secundario_id):
    if principal_id == secundario_id:
        raise HTTPException(422, "Selecione dois cadastros diferentes.")
    tutores = db.query(Tutor).filter(Tutor.id.in_([principal_id, secundario_id])).populate_existing().all()
    by_id = {t.id: t for t in tutores}
    if len(by_id) != 2:
        raise HTTPException(404, "Tutor nao encontrado.")
    principal, secundario = by_id[principal_id], by_id[secundario_id]
    if any(t.mesclado_em_id or str(t.ativo).lower() in {"0", "false"} for t in tutores):
        raise HTTPException(409, "Use apenas cadastros ativos que ainda nao foram mesclados.")
    dados_principal, dados_secundario = _dados(principal), _dados(secundario)
    conflitos = [campo for campo in CAMPOS if _preenchido(dados_principal[campo])
                 and _preenchido(dados_secundario[campo]) and dados_principal[campo] != dados_secundario[campo]]
    cpfs = [re.sub(r"\D", "", t.cpf or "") for t in (principal, secundario)]
    bloqueios = ["Os CPFs informados sao diferentes. Esclareca a divergencia antes de mesclar."] if all(cpfs) and cpfs[0] != cpfs[1] else []
    vinculos = _vinculos_snapshot(db, principal_id, secundario_id)
    pets = vinculos.get("pacientes", [])
    nomes_p = {str(p.get("nome_key") or p.get("nome") or "").strip().lower()
               for p in pets if p["tutor_id"] == principal_id}
    repetidos = [p["nome"] for p in pets if p["tutor_id"] == secundario_id
                 and str(p.get("nome_key") or p.get("nome") or "").strip().lower() in nomes_p]
    avisos = ["Animais com o mesmo nome permanecerao separados: " + ", ".join(repetidos)] if repetidos else []
    avisos.append("A identificacao ficara pendente para conferencia do cadastro consolidado. Isso nao impede agendar ou atender.")
    fonte = {"principal": _snapshot(principal), "secundario": _snapshot(secundario), "vinculos": vinculos}
    token = hashlib.sha256(_json(fonte).encode()).hexdigest()
    previa = {
        "principal": {"id": principal_id, **dados_principal},
        "secundario": {"id": secundario_id, **dados_secundario},
        "conflitos": conflitos, "bloqueios": bloqueios, "avisos": avisos,
        "campos": list(CAMPOS), "token_previa": token,
        "vinculos": {t: {"principal": sum(r["tutor_id"] == principal_id for r in rows),
                         "secundario": sum(r["tutor_id"] == secundario_id for r in rows)}
                     for t, rows in vinculos.items() if rows},
        "pets": [{"id": p["id"], "nome": p["nome"], "tutor_id": p["tutor_id"]} for p in pets],
    }
    return previa, principal, secundario, fonte


def obter_previa(db, principal_id, secundario_id):
    return _preparar(db, principal_id, secundario_id)[0]


def mesclar(db, payload, user):
    if not payload.confirmar:
        raise HTTPException(422, "Confirme explicitamente a mesclagem apos revisar a previa.")
    if len(payload.motivo.strip()) < 5:
        raise HTTPException(422, "Informe o motivo da mesclagem (ao menos 5 caracteres).")
    try:
        from app.services.tutor_rotina_service import preparar_operacao, concluir_operacao, preservar_contatos_originais, registrar_edicao_identidade, reabrir_identificacao
        operacao, replay = preparar_operacao(db, usuario_id=user.id, tipo="mesclar",
            chave=getattr(payload, "chave_operacao", None), payload=payload.model_dump(exclude={"chave_operacao"}))
        if replay is not None:
            return replay
        _bloquear_cadastros(db, payload.principal_id)

        previa, principal, secundario, fonte = _preparar(db, payload.principal_id, payload.secundario_id)
        if payload.token_previa != previa["token_previa"]:
            raise HTTPException(409, "Os cadastros ou vinculos mudaram. Gere e revise uma nova previa.")
        if previa["bloqueios"]:
            raise HTTPException(409, previa["bloqueios"][0])
        if set(payload.escolhas) - set(CAMPOS) or any(v not in {"principal", "secundario"} for v in payload.escolhas.values()):
            raise HTTPException(422, "Escolha principal ou secundario para os campos apresentados.")
        if any(c not in payload.escolhas for c in previa["conflitos"]):
            raise HTTPException(422, "Resolva todos os campos conflitantes antes de mesclar.")

        # Contatos validos de ambos continuam acessiveis apos escolher o principal.
        preservar_contatos_originais(db, principal)
        preservar_contatos_originais(db, secundario)
        db.flush()
        fonte["vinculos"] = _vinculos_snapshot(db, principal.id, secundario.id)
        resultado = {}
        for campo in CAMPOS:
            lado = payload.escolhas.get(campo)
            a, b = previa["principal"][campo], previa["secundario"][campo]
            valor = (b if lado == "secundario" else a) if lado else (a if _preenchido(a) else b)
            resultado[campo] = valor
            if campo == "endereco":
                for c, v in valor.items():
                    setattr(principal, c, v)
            else:
                setattr(principal, campo, valor)
        # Uma escolha na comparacao nao substitui a confirmacao rastreavel.
        registrar_edicao_identidade(db, principal, fonte["principal"], user)
        reabrir_identificacao(db, principal, user, "Cadastro consolidado por mesclagem; conferir a identificacao no atendimento.")
        principal.identificacao_pendente = True
        resultado["identificacao_pendente"] = principal.identificacao_pendente
        from app.api.v1.endpoints.tutores import _gerar_nome_key
        principal.nome_key = _gerar_nome_key(principal.nome)
        principal.updated_at = datetime.now(timezone.utc)
        movidos = {}
        for tabela, rows in fonte["vinculos"].items():
            ids = [r["id"] for r in rows if r["tutor_id"] == secundario.id]
            if ids:
                db.execute(text(f'UPDATE {_quote(db, tabela)} SET tutor_id=:p WHERE tutor_id=:s'),
                           {"p": principal.id, "s": secundario.id})
                movidos[tabela] = ids
        secundario.ativo = 0
        secundario.mesclado_em_id = principal.id
        secundario.updated_at = datetime.now(timezone.utc)
        # Desafios pendentes pertencem ao contato e ao escopo anteriores. Nao
        # transferir OTPs ou ampliar sessoes de acesso ao portal.
        if "portal_access_challenges" in inspect(db.connection()).get_table_names():
            db.execute(text("UPDATE portal_access_challenges SET status='revoked' "
                            "WHERE actor_type='tutor' AND actor_id IN (:p, :s) AND status='pending'"),
                       {"p": principal.id, "s": secundario.id})
        db.flush()
        estado_reversivel_sha256 = hashlib.sha256(_json(_estado_cadastros(db, principal, secundario)).encode()).hexdigest()
        registro = TutorMesclagem(
            principal_id=principal.id, secundario_id=secundario.id, usuario_id=user.id,
            usuario_nome=user.nome, motivo=payload.motivo.strip(),
            detalhes_json=_json({"antes": {"principal": fonte["principal"], "secundario": fonte["secundario"]},
                                 "resultado": resultado, "escolhas": payload.escolhas,
                                 "vinculos_movidos": movidos, "avisos": previa["avisos"],
                                 "estado_reversivel_sha256": estado_reversivel_sha256}),
        )
        db.add(registro)
        db.flush()
        resposta = {"id": registro.id, "principal_id": payload.principal_id,
                    "secundario_id": payload.secundario_id, "message": "Tutores mesclados com historico preservado."}
        concluir_operacao(operacao, resposta)
        db.commit()
        # UPDATEs SQL tambem alteram objetos que ja estavam no identity map.
        db.expire_all()
        return resposta
    except Exception as exc:
        db.rollback()
        if getattr(getattr(exc, "orig", None), "pgcode", None) in {"40P01", "55P03", "40001"}:
            raise HTTPException(409, "Cadastros em uso por outra operacao. Gere uma nova previa e tente novamente.") from exc
        raise
