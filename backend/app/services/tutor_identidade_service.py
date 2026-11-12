from fastapi import HTTPException

from app.models.tutor import Tutor


def exigir_tutor_utilizavel(db, tutor_id: int) -> Tutor:
    """Um ID escolhido explicitamente e obrigatorio para reutilizar pessoas."""
    tutor = db.query(Tutor).filter(Tutor.id == tutor_id).populate_existing().with_for_update().first()
    if tutor is None:
        raise HTTPException(404, "Tutor informado nao encontrado.")
    if tutor.mesclado_em_id:
        principal_id = tutor.mesclado_em_id
        visitados = {tutor.id}
        while principal_id not in visitados:
            visitados.add(principal_id)
            principal = db.get(Tutor, principal_id)
            if not principal or not principal.mesclado_em_id:
                break
            principal_id = principal.mesclado_em_id
        raise HTTPException(409, detail={
            "codigo": "TUTOR_MESCLADO",
            "mensagem": "Este cadastro foi mesclado. Atualize a selecao antes de salvar.",
            "tutor_principal_id": principal_id,
        })
    if str(tutor.ativo).lower() in {"0", "false"}:
        raise HTTPException(409, "Tutor inativo. Reative explicitamente pelo ID antes de usar.")
    return tutor
