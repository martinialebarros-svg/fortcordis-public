"""Endpoints para gerenciamento de imagens de laudos"""
import uuid
import os
from datetime import datetime, timedelta
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.models.imagem_laudo import ImagemLaudo, ImagemTemporaria
from app.core.security import get_current_user
from app.core.config import settings

router = APIRouter()


def _lock_laudo_for_image_write(db, laudo_id):
    """Share the existing-editor lock before changing official image metadata."""
    from app.models.laudo import Laudo
    db.query(Laudo.id).filter(Laudo.id == laudo_id).with_for_update().first()

# Tamanho máximo do arquivo (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

# Extensões permitidas
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}


class ImagemConfiguracaoItem(BaseModel):
    id: int
    ordem: int = Field(ge=0)
    incluir_no_pdf: bool = True
    descricao: Optional[str] = None


class ImagensConfiguracaoPayload(BaseModel):
    imagens: list[ImagemConfiguracaoItem]


def allowed_file(filename: str) -> bool:
    """Verifica se a extensão do arquivo é permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {ext.lstrip('.') for ext in ALLOWED_EXTENSIONS}


def get_file_extension(filename: str) -> str:
    """Retorna a extensão do arquivo em lowercase"""
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''


@router.post("/upload-temp", response_model=dict)
async def upload_imagem_temporaria(
    arquivo: UploadFile = File(...),
    descricao: str = Form(""),
    ordem: int = Form(0),
    incluir_no_pdf: bool = Form(True),
    session_id: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Upload de imagem temporária (antes de salvar o laudo).
    Retorna um ID para associar posteriormente ao laudo.
    """
    # Validações
    if not allowed_file(arquivo.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de arquivo não permitido. Use: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Ler conteúdo
    conteudo = await arquivo.read()
    
    if len(conteudo) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE / 1024 / 1024}MB"
        )
    
    # Usar session_id fornecido ou criar um novo
    session_id_usado = session_id if session_id else str(uuid.uuid4())
    
    imagem_temp = ImagemTemporaria(
        session_id=session_id_usado,
        nome_arquivo=arquivo.filename,
        tipo_mime=arquivo.content_type or f"image/{get_file_extension(arquivo.filename)}",
        tamanho_bytes=len(conteudo),
        conteudo=conteudo,
        ordem=ordem,
        descricao=descricao,
        incluir_no_pdf=incluir_no_pdf,
        expira_em=datetime.utcnow() + timedelta(hours=24)
    )
    
    db.add(imagem_temp)
    db.commit()
    db.refresh(imagem_temp)
    
    return {
        "success": True,
        "imagem_id": imagem_temp.id,
        "session_id": session_id_usado,
        "nome": imagem_temp.nome_arquivo,
        "tamanho": imagem_temp.tamanho_bytes,
        "url_preview": f"/imagens/temp/{imagem_temp.id}"
    }


@router.get("/temp/{imagem_id}")
def get_imagem_temporaria(
    imagem_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna uma imagem temporária para preview"""
    imagem = db.query(ImagemTemporaria).filter(
        ImagemTemporaria.id == imagem_id,
        ImagemTemporaria.expira_em > datetime.utcnow()
    ).first()
    
    if not imagem:
        raise HTTPException(status_code=404, detail="Imagem não encontrada ou expirada")
    
    from fastapi.responses import Response
    return Response(
        content=imagem.conteudo,
        media_type=imagem.tipo_mime,
        headers={
            "Content-Disposition": f"inline; filename={imagem.nome_arquivo}"
        }
    )


@router.delete("/temp/{imagem_id}")
def delete_imagem_temporaria(
    imagem_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove uma imagem temporária"""
    imagem = db.query(ImagemTemporaria).filter(ImagemTemporaria.id == imagem_id).first()
    
    if not imagem:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    
    db.delete(imagem)
    db.commit()
    
    return {"message": "Imagem removida com sucesso"}


@router.get("/temp/session/{session_id}", response_model=dict)
def listar_imagens_temporarias(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todas as imagens temporárias de uma sessão"""
    imagens = db.query(ImagemTemporaria).filter(
        ImagemTemporaria.session_id == session_id,
        ImagemTemporaria.expira_em > datetime.utcnow()
    ).order_by(ImagemTemporaria.ordem).all()
    
    return {
        "items": [
            {
                "id": img.id,
                "nome": img.nome_arquivo,
                "descricao": img.descricao,
                "ordem": img.ordem,
                "tamanho": img.tamanho_bytes,
                "incluir_no_pdf": bool(img.incluir_no_pdf),
                "url_preview": f"/imagens/temp/{img.id}"
            }
            for img in imagens
        ],
        "total": len(imagens)
    }


@router.post("/associar/{laudo_id}")
def associar_imagens_ao_laudo(
    laudo_id: int,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Associa imagens temporárias a um laudo salvo"""
    _lock_laudo_for_image_write(db, laudo_id)
    # Limpar imagens temporárias expiradas primeiro
    imagens_expiradas = db.query(ImagemTemporaria).filter(
        ImagemTemporaria.expira_em <= datetime.utcnow()
    ).all()
    for img_exp in imagens_expiradas:
        db.delete(img_exp)
    
    # Buscar imagens temporárias do session_id atual
    imagens_temp = db.query(ImagemTemporaria).filter(
        ImagemTemporaria.session_id == session_id,
        ImagemTemporaria.expira_em > datetime.utcnow()
    ).order_by(ImagemTemporaria.ordem).with_for_update().all()
    
    if not imagens_temp:
        db.commit()  # Commit da limpeza
        return {"message": "Nenhuma imagem para associar"}
    
    # Buscar a maior ordem existente no laudo
    ultima_ordem = db.query(ImagemLaudo).filter(
        ImagemLaudo.laudo_id == laudo_id,
        ImagemLaudo.ativo == 1
    ).count()
    
    count = 0
    for img_temp in imagens_temp:
        imagem_laudo = ImagemLaudo(
            laudo_id=laudo_id,
            nome_arquivo=img_temp.nome_arquivo,
            tipo_mime=img_temp.tipo_mime,
            tamanho_bytes=img_temp.tamanho_bytes,
            conteudo=img_temp.conteudo,
            ordem=ultima_ordem + count,  # Continuar ordem após imagens existentes
            descricao=img_temp.descricao,
            incluir_no_pdf=img_temp.incluir_no_pdf,
            ativo=1
        )
        db.add(imagem_laudo)
        count += 1
        
        # Remove a temporária
        db.delete(img_temp)
    
    db.commit()
    
    return {
        "message": f"{count} imagens associadas ao laudo {laudo_id}",
        "laudo_id": laudo_id
    }


@router.get("/laudo/{laudo_id}", response_model=dict)
def listar_imagens_do_laudo(
    laudo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todas as imagens de um laudo"""
    imagens = db.query(ImagemLaudo).filter(
        ImagemLaudo.laudo_id == laudo_id,
        ImagemLaudo.ativo == 1
    ).order_by(ImagemLaudo.ordem).all()
    
    return {
        "items": [
            {
                "id": img.id,
                "nome": img.nome_arquivo,
                "descricao": img.descricao,
                "ordem": img.ordem,
                "pagina": img.pagina,
                "tamanho": img.tamanho_bytes,
                "incluir_no_pdf": bool(img.incluir_no_pdf),
                "url": f"/imagens/{img.id}"
            }
            for img in imagens
        ],
        "total": len(imagens)
    }


@router.put("/temp/session/{session_id}/configuracao")
def atualizar_configuracao_imagens_temporarias(
    session_id: str,
    payload: ImagensConfiguracaoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza ordem, inclusao e legenda opcional das imagens temporarias."""
    del current_user
    ids = [item.id for item in payload.imagens]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="IDs de imagem duplicados")
    imagens = (
        db.query(ImagemTemporaria)
        .filter(
            ImagemTemporaria.session_id == session_id,
            ImagemTemporaria.id.in_(ids),
            ImagemTemporaria.expira_em > datetime.utcnow(),
        )
        .all()
        if ids
        else []
    )
    if len(imagens) != len(ids):
        raise HTTPException(status_code=404, detail="Imagem temporária não encontrada nesta sessão")
    por_id = {imagem.id: imagem for imagem in imagens}
    for item in payload.imagens:
        por_id[item.id].ordem = item.ordem
        por_id[item.id].incluir_no_pdf = item.incluir_no_pdf
        if item.descricao is not None:
            por_id[item.id].descricao = item.descricao.strip()
    db.commit()
    return {"message": "Configuração das imagens temporárias atualizada"}


@router.put("/laudo/{laudo_id}/configuracao")
def atualizar_configuracao_imagens_laudo(
    laudo_id: int,
    payload: ImagensConfiguracaoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza atomicamente ordem, inclusao e legenda opcional das imagens."""
    del current_user
    _lock_laudo_for_image_write(db, laudo_id)
    ids = [item.id for item in payload.imagens]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="IDs de imagem duplicados")
    imagens = (
        db.query(ImagemLaudo).populate_existing()
        .filter(
            ImagemLaudo.laudo_id == laudo_id,
            ImagemLaudo.ativo == 1,
            ImagemLaudo.id.in_(ids),
        )
        .all()
        if ids
        else []
    )
    if len(imagens) != len(ids):
        raise HTTPException(status_code=404, detail="Imagem não encontrada neste laudo")
    por_id = {imagem.id: imagem for imagem in imagens}
    for item in payload.imagens:
        por_id[item.id].ordem = item.ordem
        por_id[item.id].incluir_no_pdf = item.incluir_no_pdf
        if item.descricao is not None:
            por_id[item.id].descricao = item.descricao.strip()
    db.commit()
    return {"message": "Configuração das imagens do laudo atualizada"}


@router.get("/{imagem_id}")
def get_imagem(
    imagem_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna uma imagem do laudo"""
    imagem = db.query(ImagemLaudo).filter(
        ImagemLaudo.id == imagem_id,
        ImagemLaudo.ativo == 1
    ).first()
    
    if not imagem:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    
    from fastapi.responses import Response
    return Response(
        content=imagem.conteudo,
        media_type=imagem.tipo_mime,
        headers={
            "Content-Disposition": f"inline; filename={imagem.nome_arquivo}"
        }
    )


@router.delete("/{imagem_id}")
def delete_imagem(
    imagem_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove uma imagem do laudo (soft delete)"""
    imagem = db.query(ImagemLaudo).filter(ImagemLaudo.id == imagem_id).first()
    
    if not imagem:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")

    _lock_laudo_for_image_write(db, imagem.laudo_id)
    db.refresh(imagem)
    
    imagem.ativo = 0
    db.commit()
    
    return {"message": "Imagem removida com sucesso"}


@router.put("/{imagem_id}/ordem")
def atualizar_ordem_imagem(
    imagem_id: int,
    ordem: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza a ordem de uma imagem"""
    imagem = db.query(ImagemLaudo).filter(ImagemLaudo.id == imagem_id).first()
    
    if not imagem:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")

    _lock_laudo_for_image_write(db, imagem.laudo_id)
    db.refresh(imagem)
    
    imagem.ordem = ordem
    db.commit()
    
    return {"message": "Ordem atualizada com sucesso"}
