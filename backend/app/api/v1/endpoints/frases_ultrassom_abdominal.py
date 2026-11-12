from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.services import frases_ultrassom_abdominal_service as service


router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("")
def listar_frases(
    orgao: Optional[str] = None,
    sexo: Optional[str] = None,
    busca: Optional[str] = None,
    ativo: Optional[int] = 1,
    skip: int = 0,
    limit: int = 200,
) -> Any:
    return service.listar_frases(
        orgao=orgao,
        sexo=sexo,
        busca=busca,
        ativo=ativo,
        skip=skip,
        limit=limit,
    )


@router.get("/{frase_id}")
def obter_frase(frase_id: int) -> Any:
    frase = service.obter_frase(frase_id)
    if not frase:
        raise HTTPException(status_code=404, detail="Frase nao encontrada.")
    return frase


@router.post("", status_code=status.HTTP_201_CREATED)
def criar_frase(payload: dict) -> Any:
    try:
        return service.criar_frase(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{frase_id}")
def atualizar_frase(frase_id: int, payload: dict) -> Any:
    try:
        frase = service.atualizar_frase(frase_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not frase:
        raise HTTPException(status_code=404, detail="Frase nao encontrada.")
    return frase


@router.delete("/{frase_id}")
def deletar_frase(frase_id: int) -> Any:
    if not service.deletar_frase(frase_id):
        raise HTTPException(status_code=404, detail="Frase nao encontrada.")
    return {"message": "Frase removida com sucesso."}


@router.post("/{frase_id}/restaurar")
def restaurar_frase(frase_id: int) -> Any:
    if not service.restaurar_frase(frase_id):
        raise HTTPException(status_code=404, detail="Frase nao encontrada.")
    return {"message": "Frase restaurada com sucesso."}

