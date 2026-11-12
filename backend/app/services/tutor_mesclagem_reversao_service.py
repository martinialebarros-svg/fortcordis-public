"""Correcao humana e conservadora: alteracoes posteriores impedem desfazer cego."""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import DateTime, inspect, text

from app.models.tutor import Tutor
from app.models.tutor_mesclagem import TutorMesclagem
from app.models.tutor_mesclagem_reversao import TutorMesclagemReversao
from app.services.tutor_mesclagem_service import _bloquear_cadastros, _estado_cadastros, _json, _quote, _referencias


def _preparar(db, mesclagem_id):
    registro = db.get(TutorMesclagem, mesclagem_id)
    if not registro:
        raise HTTPException(404, "Mesclagem nao encontrada.")
    detalhes = json.loads(registro.detalhes_json)
    principal = db.query(Tutor).filter(Tutor.id == registro.principal_id).populate_existing().first()
    secundario = db.query(Tutor).filter(Tutor.id == registro.secundario_id).populate_existing().first()
    reversao = db.query(TutorMesclagemReversao).filter_by(mesclagem_id=registro.id).first()
    bloqueios = []
    if reversao:
        bloqueios.append("Esta mesclagem ja foi revertida. Consulte o historico.")
    if not detalhes.get("estado_reversivel_sha256"):
        bloqueios.append("Esta mesclagem antiga precisa de revisao tecnica para separar os vinculos com seguranca.")
    if not principal or not secundario or principal.mesclado_em_id or secundario.mesclado_em_id != registro.principal_id:
        bloqueios.append("Os cadastros participam de outra mesclagem ou foram alterados. E necessaria revisao tecnica.")
    estado = _estado_cadastros(db, principal, secundario) if principal and secundario else None
    hash_estado = hashlib.sha256(_json(estado).encode()).hexdigest()
    if detalhes.get("estado_reversivel_sha256") and detalhes["estado_reversivel_sha256"] != hash_estado:
        bloqueios.append("Houve alteracoes ou novos vinculos depois da mesclagem. Revise esses registros antes de separar as pessoas; a reversao automatica esta bloqueada.")
    token = hashlib.sha256(_json({"mesclagem_id": registro.id, "estado": hash_estado,
                                 "reversao_id": reversao.id if reversao else None}).encode()).hexdigest()
    previa = {"mesclagem_id": registro.id, "principal_id": registro.principal_id,
              "secundario_id": registro.secundario_id, "token_previa": token,
              "bloqueios": bloqueios, "avisos": ["Os dados cadastrais anteriores serao restaurados. Documentos emitidos e animais permanecem separados.",
                  "Contatos alternativos continuam com sua pessoa de origem. A identificacao ficara pendente para revisao; acessos revogados nao serao reativados."],
              "vinculos": {t: len(ids) for t, ids in detalhes.get("vinculos_movidos", {}).items()},
              "reversao": {"id": reversao.id, "usuario_nome": reversao.usuario_nome, "motivo": reversao.motivo,
                           "created_at": reversao.created_at.replace(tzinfo=reversao.created_at.tzinfo or timezone.utc).isoformat()} if reversao else None}
    return previa, registro, detalhes, principal, secundario


def obter_previa_reversao(db, mesclagem_id):
    return _preparar(db, mesclagem_id)[0]


def reverter_mesclagem(db, mesclagem_id, payload, user):
    from app.services.tutor_rotina_service import preparar_operacao, concluir_operacao, reabrir_identificacao
    if not payload.confirmar or len(payload.motivo.strip()) < 5:
        raise HTTPException(422, "Revise a previa, informe o motivo e confirme a correcao.")
    try:
        operacao, replay = preparar_operacao(db, usuario_id=user.id, tipo="reverter_mesclagem",
            chave=payload.chave_operacao, payload={"mesclagem_id": mesclagem_id,
                **payload.model_dump(exclude={"chave_operacao"})})
        if replay is not None:
            return replay
        registro = db.get(TutorMesclagem, mesclagem_id)
        if not registro:
            raise HTTPException(404, "Mesclagem nao encontrada.")
        _bloquear_cadastros(db, registro.principal_id)
        previa, registro, detalhes, principal, secundario = _preparar(db, mesclagem_id)
        if payload.token_previa != previa["token_previa"]:
            raise HTTPException(409, "Os dados mudaram. Gere uma nova previa da correcao.")
        if previa["bloqueios"]:
            raise HTTPException(409, previa["bloqueios"][0])
        tabelas = set(_referencias(db))
        for tabela, ids in detalhes["vinculos_movidos"].items():
            if tabela not in tabelas:
                raise HTTPException(409, "Um tipo de vinculo mudou. Solicite revisao tecnica.")
            # IDs vem somente do historico privado, nunca do pedido do cliente.
            for registro_id in ids:
                result = db.execute(text(f'UPDATE {_quote(db, tabela)} SET tutor_id=:s WHERE id=:id AND tutor_id=:p'),
                    {"s": secundario.id, "p": principal.id, "id": registro_id})
                if result.rowcount != 1:
                    raise HTTPException(409, "Um vinculo mudou durante a correcao. Nenhum dado foi separado.")
        for lado, tutor in (("principal", principal), ("secundario", secundario)):
            anteriores = detalhes["antes"][lado]
            for coluna in Tutor.__table__.columns:
                if coluna.name in {"id", "created_at", "updated_at"} or coluna.name not in anteriores:
                    continue
                valor = anteriores[coluna.name]
                if valor is not None and isinstance(coluna.type, DateTime):
                    valor = datetime.fromisoformat(valor)
                setattr(tutor, coluna.name, valor)
            tutor.updated_at = datetime.now(timezone.utc)
            reabrir_identificacao(db, tutor, user, "Correcao assistida de mesclagem: conferir a identidade no atendimento.")
        # A separacao tambem invalida desafios criados apos a consolidacao.
        if "portal_access_challenges" in inspect(db.connection()).get_table_names():
            db.execute(text("UPDATE portal_access_challenges SET status='revoked' WHERE actor_type='tutor' "
                            "AND actor_id IN (:p,:s) AND status='pending'"), {"p": principal.id, "s": secundario.id})
        reversao = TutorMesclagemReversao(mesclagem_id=registro.id, usuario_id=user.id, usuario_nome=user.nome,
            motivo=payload.motivo.strip(), detalhes_json=_json({"vinculos_restaurados": detalhes["vinculos_movidos"],
                "principal_id": principal.id, "secundario_id": secundario.id, "token_previa": payload.token_previa}))
        db.add(reversao)
        db.flush()
        resposta = {"id": reversao.id, "mesclagem_id": registro.id, "principal_id": principal.id,
                    "secundario_id": secundario.id, "message": "Correcao concluida com historico preservado."}
        concluir_operacao(operacao, resposta)
        db.commit()
        db.expire_all()
        return resposta
    except Exception as exc:
        db.rollback()
        if getattr(getattr(exc, "orig", None), "pgcode", None) in {"40P01", "55P03", "40001"}:
            raise HTTPException(409, "Cadastros em uso. Revise uma nova previa antes de tentar novamente.") from exc
        raise
