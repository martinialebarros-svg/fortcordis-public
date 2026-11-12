"""Complementos sob demanda: nunca bloqueiam o cadastro com apenas um nome."""
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import case, func, inspect, or_

from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.tutor_rotina import (
    TutorContato, TutorDuplicidadeDescarte, TutorIdentificacaoEvento,
    TutorOperacao, TutorOrigem,
)

IDENTIDADE = ("nome", "cpf", "telefone", "whatsapp", "email")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def tabela_disponivel(db, model):
    """Somente leitura, inclusive em fixtures legadas com schema reduzido."""
    return inspect(db.connection()).has_table(model.__tablename__)


def _texto(value):
    return " ".join(str(value or "").strip().split()).casefold()


def _nome(value):
    return "".join(c for c in unicodedata.normalize("NFKD", _texto(value)) if not unicodedata.combining(c))


def normalizar_contato(tipo, valor):
    if tipo == "email":
        return str(valor or "").strip().casefold()
    digits = re.sub(r"\D", "", str(valor or ""))
    return digits[2:] if digits.startswith("55") and len(digits) in (12, 13) else digits


def digitos_sql(column):
    result = func.coalesce(column, "")
    for char in (" ", "+", "(", ")", "-", ".", "/", "\t", "\n"):
        result = func.replace(result, char, "")
    return result


def telefone_sql(column):
    value = digitos_sql(column)
    return case((func.length(value).in_([12, 13]) & (func.substr(value, 1, 2) == "55"), func.substr(value, 3)), else_=value)


def dados_identidade(tutor):
    return {campo: getattr(tutor, campo, None) for campo in IDENTIDADE}


def _identidade_normalizada(dados):
    return {"nome": _nome(dados.get("nome")), "cpf": re.sub(r"\D", "", dados.get("cpf") or ""),
            "telefone": normalizar_contato("telefone", dados.get("telefone")),
            "whatsapp": normalizar_contato("whatsapp", dados.get("whatsapp")),
            "email": normalizar_contato("email", dados.get("email"))}


def versao_identificacao(tutor):
    return _hash({"id": tutor.id, **dados_identidade(tutor),
                  "pendente": bool(tutor.identificacao_pendente),
                  "origem": tutor.origem_cadastro, "observacoes": tutor.identificacao_observacoes})


def _evento(db, tutor, acao, user, *, metodo=None, evidencia=None, motivo=None, antes=None):
    if not tabela_disponivel(db, TutorIdentificacaoEvento):
        return None
    event = TutorIdentificacaoEvento(
        cadastro_id=tutor.id, acao=acao, usuario_id=getattr(user, "id", None),
        usuario_nome=getattr(user, "nome", None), metodo=metodo, evidencia=evidencia, motivo=motivo,
        detalhes_json=_json({"antes": antes, "depois": dados_identidade(tutor),
                            "versao": versao_identificacao(tutor)}),
    )
    db.add(event)
    return event


def registrar_edicao_identidade(db, tutor, antes, user=None):
    """Mantem a confirmacao somente enquanto os dados conferidos forem iguais."""
    if _identidade_normalizada(antes) == _identidade_normalizada(dados_identidade(tutor)):
        return
    if tutor.identificacao_pendente is False:
        tutor.identificacao_pendente = True
        _evento(db, tutor, "invalidar", user, motivo="Dados de identificacao alterados; conferir no atendimento.", antes=antes)


def confirmar_identificacao(db, tutor, user, *, metodo, evidencia, versao):
    if not tabela_disponivel(db, TutorIdentificacaoEvento):
        raise HTTPException(503, "Historico de identificacao indisponivel. Tente novamente apos a atualizacao.")
    if versao != versao_identificacao(tutor):
        raise HTTPException(409, "O cadastro mudou. Atualize os dados antes de confirmar a identificacao.")
    if len(metodo.strip()) < 3 or len(evidencia.strip()) < 5:
        raise HTTPException(422, "Informe como a identificacao foi conferida e a evidencia da confirmacao.")
    antes = dados_identidade(tutor)
    tutor.identificacao_pendente = False
    tutor.updated_at = datetime.now(timezone.utc)
    _evento(db, tutor, "confirmar", user, metodo=metodo.strip(), evidencia=evidencia.strip(), antes=antes)


def reabrir_identificacao(db, tutor, user, motivo):
    if len(motivo.strip()) < 5:
        raise HTTPException(422, "Informe o motivo da revisao da identificacao.")
    if tutor.identificacao_pendente is not False:
        return
    antes = dados_identidade(tutor)
    tutor.identificacao_pendente = True
    tutor.updated_at = datetime.now(timezone.utc)
    _evento(db, tutor, "reabrir", user, motivo=motivo.strip(), antes=antes)


def _iso(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None


def _serializar_evento(row):
    return {"id": row.id, "cadastro_id": row.cadastro_id, "acao": row.acao,
            "usuario_id": row.usuario_id, "usuario_nome": row.usuario_nome,
            "created_at": _iso(row.created_at), "metodo": row.metodo,
            "evidencia": row.evidencia, "motivo": row.motivo,
            "detalhes": json.loads(row.detalhes_json)}


def resumo_confirmacao(db, tutor):
    if tutor.identificacao_pendente or not tabela_disponivel(db, TutorIdentificacaoEvento):
        return None
    row = db.query(TutorIdentificacaoEvento).filter(TutorIdentificacaoEvento.cadastro_id == tutor.id).order_by(TutorIdentificacaoEvento.id.desc()).first()
    if not row or row.acao != "confirmar":
        return None
    return _serializar_evento(row)


def historico_identificacao(db, tutor_id):
    if not tabela_disponivel(db, TutorIdentificacaoEvento):
        return []
    # Manter o ID original em cada evento, inclusive apos uma cadeia de mesclagens.
    ids = {tutor_id}
    from app.models.tutor_mesclagem import TutorMesclagem
    if tabela_disponivel(db, TutorMesclagem):
        from app.models.tutor_mesclagem_reversao import TutorMesclagemReversao
        reversoes = db.query(TutorMesclagemReversao.mesclagem_id) if tabela_disponivel(db, TutorMesclagemReversao) else None
        while True:
            query = db.query(TutorMesclagem).filter(TutorMesclagem.principal_id.in_(ids))
            if reversoes is not None:
                query = query.filter(~TutorMesclagem.id.in_(reversoes))
            rows = query.all()
            expanded = ids | {r.secundario_id for r in rows}
            if expanded == ids:
                break
            ids = expanded
    return [_serializar_evento(row) for row in db.query(TutorIdentificacaoEvento)
            .filter(TutorIdentificacaoEvento.cadastro_id.in_(ids)).order_by(TutorIdentificacaoEvento.id.desc()).all()]


def preparar_operacao(db, *, usuario_id, tipo, chave, payload):
    """Reserva e replay na MESMA transacao da escrita; nunca faz commit.

    Consumidor deve chamar antes de locks de tutores, gravar a resposta por
    concluir_operacao e efetuar um unico commit. Reserva sem resposta nao pode
    existir apos um commit normal. A restricao unica serializa retries concorrentes.
    """
    if not chave:
        return None, None
    if not 8 <= len(chave) <= 128:
        raise HTTPException(422, "Chave de operacao deve ter de 8 a 128 caracteres.")
    if not tabela_disponivel(db, TutorOperacao):
        raise HTTPException(503, "Registro de operacoes indisponivel. Tente novamente apos a atualizacao.")
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise HTTPException(503, "Banco sem suporte a repeticao segura desta operacao.")
    fingerprint = _hash(payload)
    data = {"usuario_id": usuario_id, "tipo": tipo, "chave": chave, "hash_payload": fingerprint}
    db.execute(insert(TutorOperacao).values(**data).on_conflict_do_nothing(index_elements=["usuario_id", "tipo", "chave"]))
    row = db.query(TutorOperacao).filter_by(usuario_id=usuario_id, tipo=tipo, chave=chave).populate_existing().with_for_update().one()
    if row.hash_payload != fingerprint:
        raise HTTPException(409, "Esta chave de operacao ja foi usada com dados diferentes.")
    return row, json.loads(row.resposta_json) if row.resposta_json is not None else None


def concluir_operacao(registro, resposta):
    if registro is not None:
        registro.resposta_json = _json(resposta)


def listar_contatos(db, tutor):
    items = []
    seen = set()
    for tipo in ("telefone", "whatsapp", "email"):
        valor = str(getattr(tutor, tipo, None) or "").strip()
        if valor:
            seen.add((tipo, normalizar_contato(tipo, valor)))
            items.append({"id": None, "tipo": tipo, "valor": valor, "rotulo": "Principal", "principal": True})
    if tabela_disponivel(db, TutorContato):
        for row in db.query(TutorContato).filter(TutorContato.tutor_id == tutor.id).order_by(TutorContato.id).all():
            key = (row.tipo, row.valor_normalizado)
            if key not in seen:
                seen.add(key)
                items.append({"id": row.id, "tipo": row.tipo, "valor": row.valor, "rotulo": row.rotulo, "principal": False})
    return items


def adicionar_contato(db, tutor, *, tipo, valor, rotulo=None, user=None, validar=True):
    if tipo not in {"telefone", "whatsapp", "email"}:
        raise HTTPException(422, "Tipo de contato invalido.")
    normalized = normalizar_contato(tipo, valor)
    if validar and (not normalized or (tipo == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized))
                    or (tipo != "email" and not 8 <= len(normalized) <= 15)):
        raise HTTPException(422, "Informe um contato valido.")
    existing = db.query(TutorContato).filter_by(tutor_id=tutor.id, tipo=tipo, valor_normalizado=normalized).first()
    if existing:
        return existing, False
    row = TutorContato(tutor_id=tutor.id, tipo=tipo, valor=str(valor).strip(), valor_normalizado=normalized,
                       rotulo=rotulo, usuario_id=getattr(user, "id", None))
    db.add(row)
    db.flush()
    return row, True


def listar_origens(db, tutor):
    items = []
    seen = set()
    if tutor.origem_cadastro:
        seen.add((_texto(tutor.origem_cadastro), None))
        items.append({"id": None, "descricao": tutor.origem_cadastro, "clinica_id": None})
    if tabela_disponivel(db, TutorOrigem):
        for row in db.query(TutorOrigem).filter_by(tutor_id=tutor.id).order_by(TutorOrigem.id).all():
            key = (_texto(row.descricao), row.clinica_id)
            if key not in seen:
                seen.add(key)
                items.append({"id": row.id, "descricao": row.descricao, "clinica_id": row.clinica_id})
    return items


def adicionar_origem(db, tutor, *, descricao, clinica_id=None, user=None):
    descricao = descricao.strip()
    if not descricao:
        raise HTTPException(422, "Informe a origem do cadastro.")
    for row in db.query(TutorOrigem).filter_by(tutor_id=tutor.id).all():
        if _texto(row.descricao) == _texto(descricao) and row.clinica_id == clinica_id:
            return row, False
    row = TutorOrigem(tutor_id=tutor.id, descricao=descricao, clinica_id=clinica_id, usuario_id=getattr(user, "id", None))
    db.add(row)
    db.flush()
    return row, True


def preservar_contatos_originais(db, tutor):
    """Usado pela mesclagem; preserva legados sem conceder permissao de envio."""
    criados = {"tutores_contatos": [], "tutores_origens": []}
    if tabela_disponivel(db, TutorContato):
        for tipo in ("telefone", "whatsapp", "email"):
            valor = getattr(tutor, tipo, None)
            if valor:
                row, created = adicionar_contato(db, tutor, tipo=tipo, valor=valor, rotulo="Cadastro original", validar=False)
                if created:
                    criados["tutores_contatos"].append(row.id)
    if tutor.origem_cadastro and tabela_disponivel(db, TutorOrigem):
        row, created = adicionar_origem(db, tutor, descricao=tutor.origem_cadastro)
        if created:
            criados["tutores_origens"].append(row.id)
    return criados


def _contatos_comparaveis(db, tutor):
    return {(item["tipo"], normalizar_contato(item["tipo"], item["valor"])) for item in listar_contatos(db, tutor)
            if (item["tipo"] == "email" and "@" in item["valor"])
            or (item["tipo"] != "email" and len(normalizar_contato(item["tipo"], item["valor"])) >= 8)}


def _assinatura_par(db, a, b):
    return _hash([{ "id": t.id, "dados": _identidade_normalizada(dados_identidade(t)),
                   "contatos": sorted(_contatos_comparaveis(db, t))} for t in sorted((a, b), key=lambda t: t.id)])


def sugerir_duplicidades(db, tutor):
    contatos = _contatos_comparaveis(db, tutor)
    phones = {v for tipo, v in contatos if tipo != "email"}
    emails = {v for tipo, v in contatos if tipo == "email"}
    cpf = re.sub(r"\D", "", tutor.cpf or "")
    # Nomes iguais e CPFs de preenchimento (000...,111...) nunca sao evidencia suficiente.
    cpf_valido_para_busca = len(cpf) == 11 and len(set(cpf)) > 1
    filters = []
    if cpf_valido_para_busca:
        filters.append(digitos_sql(Tutor.cpf) == cpf)
    if phones:
        filters.extend([telefone_sql(Tutor.telefone).in_(phones), telefone_sql(Tutor.whatsapp).in_(phones)])
    if emails:
        filters.append(func.lower(func.trim(Tutor.email)).in_(emails))
    if tabela_disponivel(db, TutorContato) and contatos:
        alternativas = []
        if phones:
            alternativas.append(TutorContato.tipo.in_(["telefone", "whatsapp"]) & TutorContato.valor_normalizado.in_(phones))
        if emails:
            alternativas.append((TutorContato.tipo == "email") & TutorContato.valor_normalizado.in_(emails))
        filters.append(Tutor.id.in_(db.query(TutorContato.tutor_id).filter(or_(*alternativas))))
    if not filters:
        return []
    candidates = db.query(Tutor).filter(Tutor.id != tutor.id, Tutor.mesclado_em_id.is_(None),
                                      or_(Tutor.ativo == 1, Tutor.ativo.is_(None)), or_(*filters)).order_by(Tutor.nome, Tutor.id).limit(100).all()
    discarded = []
    if tabela_disponivel(db, TutorDuplicidadeDescarte):
        discarded = db.query(TutorDuplicidadeDescarte).filter(or_(TutorDuplicidadeDescarte.cadastro_id == tutor.id,
                                                                 TutorDuplicidadeDescarte.outro_cadastro_id == tutor.id)).all()
    items = []
    for candidate in candidates:
        signature = _assinatura_par(db, tutor, candidate)
        if any(row.assinatura_par == signature for row in discarded):
            continue
        outras = _contatos_comparaveis(db, candidate)
        motivos = []
        if cpf_valido_para_busca and re.sub(r"\D", "", candidate.cpf or "") == cpf:
            motivos.append("Mesmo CPF informado")
        if phones & {v for tipo, v in outras if tipo != "email"}:
            motivos.append("Telefone ou WhatsApp em comum; pode ser contato compartilhado")
        if emails & {v for tipo, v in outras if tipo == "email"}:
            motivos.append("E-mail em comum; pode ser contato compartilhado")
        if motivos:
            pets = db.query(Paciente.id, Paciente.nome).filter(Paciente.tutor_id == candidate.id).order_by(Paciente.id).all()
            items.append({"id": candidate.id, "nome": candidate.nome, "identificacao_pendente": candidate.identificacao_pendente,
                          "telefone": candidate.telefone, "whatsapp": candidate.whatsapp, "email": candidate.email,
                          "origem_cadastro": candidate.origem_cadastro, "motivos": motivos,
                          "pets": [{"id": p.id, "nome": p.nome} for p in pets]})
    return items


def descartar_duplicidade(db, tutor, outro, user, motivo):
    if tutor.id == outro.id or len(motivo.strip()) < 5:
        raise HTTPException(422, "Selecione outra pessoa e informe o motivo do descarte.")
    db.add(TutorDuplicidadeDescarte(cadastro_id=min(tutor.id, outro.id), outro_cadastro_id=max(tutor.id, outro.id),
                                   assinatura_par=_assinatura_par(db, tutor, outro), motivo=motivo.strip(),
                                   usuario_id=user.id, usuario_nome=user.nome))
