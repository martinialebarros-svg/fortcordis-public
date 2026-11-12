from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime

from app.db.database import get_db
from app.models.servico import Servico
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter()


# Schemas
class ServicoPrecos(BaseModel):
    """Schema para os preços por região"""
    fortaleza_comercial: float = Field(default=0, ge=0, description="Preço Fortaleza - Horário Comercial")
    fortaleza_plantao: float = Field(default=0, ge=0, description="Preço Fortaleza - Plantão")
    rm_comercial: float = Field(default=0, ge=0, description="Preço Região Metropolitana - Horário Comercial")
    rm_plantao: float = Field(default=0, ge=0, description="Preço Região Metropolitana - Plantão")
    domiciliar_comercial: float = Field(default=0, ge=0, description="Preço Domiciliar - Horário Comercial")
    domiciliar_plantao: float = Field(default=0, ge=0, description="Preço Domiciliar - Plantão")


class ServicoCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=255)
    descricao: Optional[str] = ""
    duracao_minutos: Optional[int] = Field(default=30, ge=5)
    precos: ServicoPrecos = Field(default_factory=ServicoPrecos)


class ServicoUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2, max_length=255)
    descricao: Optional[str] = None
    duracao_minutos: Optional[int] = Field(default=None, ge=5)
    precos: Optional[ServicoPrecos] = None


class ServicoResponse(BaseModel):
    id: int
    nome: str
    descricao: Optional[str] = None
    duracao_minutos: Optional[int] = None
    precos: ServicoPrecos
    ativo: bool = True


@router.get("")
def listar_servicos(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista servicos"""
    query = db.query(Servico).filter(Servico.ativo == True)
    
    total = query.count()
    items = query.order_by(Servico.nome).offset(skip).limit(limit).all()
    
    servicos = []
    for s in items:
        servico_dict = {
            "id": s.id,
            "nome": s.nome,
            "descricao": s.descricao,
            "duracao_minutos": s.duracao_minutos,
            "ativo": s.ativo,
            "precos": {
                "fortaleza_comercial": float(s.preco_fortaleza_comercial) if s.preco_fortaleza_comercial else 0.0,
                "fortaleza_plantao": float(s.preco_fortaleza_plantao) if s.preco_fortaleza_plantao else 0.0,
                "rm_comercial": float(s.preco_rm_comercial) if s.preco_rm_comercial else 0.0,
                "rm_plantao": float(s.preco_rm_plantao) if s.preco_rm_plantao else 0.0,
                "domiciliar_comercial": float(s.preco_domiciliar_comercial) if s.preco_domiciliar_comercial else 0.0,
                "domiciliar_plantao": float(s.preco_domiciliar_plantao) if s.preco_domiciliar_plantao else 0.0,
            }
        }
        servicos.append(servico_dict)
    
    return {"total": total, "items": servicos}


@router.post("", status_code=status.HTTP_201_CREATED)
def criar_servico(
    servico: ServicoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria um novo servico com preços por região"""
    try:
        precos = servico.precos
        now = datetime.now()
        
        db_servico = Servico(
            nome=servico.nome,
            descricao=servico.descricao,
            duracao_minutos=servico.duracao_minutos,
            ativo=True,
            # Preços Fortaleza
            preco_fortaleza_comercial=Decimal(str(precos.fortaleza_comercial)) if precos.fortaleza_comercial else Decimal("0.00"),
            preco_fortaleza_plantao=Decimal(str(precos.fortaleza_plantao)) if precos.fortaleza_plantao else Decimal("0.00"),
            # Preços RM
            preco_rm_comercial=Decimal(str(precos.rm_comercial)) if precos.rm_comercial else Decimal("0.00"),
            preco_rm_plantao=Decimal(str(precos.rm_plantao)) if precos.rm_plantao else Decimal("0.00"),
            # Preços Domiciliar
            preco_domiciliar_comercial=Decimal(str(precos.domiciliar_comercial)) if precos.domiciliar_comercial else Decimal("0.00"),
            preco_domiciliar_plantao=Decimal(str(precos.domiciliar_plantao)) if precos.domiciliar_plantao else Decimal("0.00"),
            created_at=now,
            updated_at=now,
        )
        
        db.add(db_servico)
        db.commit()
        db.refresh(db_servico)
        
        return {
            "id": db_servico.id,
            "nome": db_servico.nome,
            "descricao": db_servico.descricao,
            "duracao_minutos": db_servico.duracao_minutos,
            "ativo": db_servico.ativo,
            "precos": {
                "fortaleza_comercial": float(db_servico.preco_fortaleza_comercial) if db_servico.preco_fortaleza_comercial else 0.0,
                "fortaleza_plantao": float(db_servico.preco_fortaleza_plantao) if db_servico.preco_fortaleza_plantao else 0.0,
                "rm_comercial": float(db_servico.preco_rm_comercial) if db_servico.preco_rm_comercial else 0.0,
                "rm_plantao": float(db_servico.preco_rm_plantao) if db_servico.preco_rm_plantao else 0.0,
                "domiciliar_comercial": float(db_servico.preco_domiciliar_comercial) if db_servico.preco_domiciliar_comercial else 0.0,
                "domiciliar_plantao": float(db_servico.preco_domiciliar_plantao) if db_servico.preco_domiciliar_plantao else 0.0,
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar servico: {str(e)}")


@router.get("/{servico_id}")
def obter_servico(
    servico_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtem detalhes de um servico"""
    servico = db.query(Servico).filter(
        Servico.id == servico_id,
        Servico.ativo == True
    ).first()
    
    if not servico:
        raise HTTPException(status_code=404, detail="Servico nao encontrado")
    
    return {
        "id": servico.id,
        "nome": servico.nome,
        "descricao": servico.descricao,
        "duracao_minutos": servico.duracao_minutos,
        "ativo": servico.ativo,
        "precos": {
            "fortaleza_comercial": float(servico.preco_fortaleza_comercial) if servico.preco_fortaleza_comercial else 0.0,
            "fortaleza_plantao": float(servico.preco_fortaleza_plantao) if servico.preco_fortaleza_plantao else 0.0,
            "rm_comercial": float(servico.preco_rm_comercial) if servico.preco_rm_comercial else 0.0,
            "rm_plantao": float(servico.preco_rm_plantao) if servico.preco_rm_plantao else 0.0,
            "domiciliar_comercial": float(servico.preco_domiciliar_comercial) if servico.preco_domiciliar_comercial else 0.0,
            "domiciliar_plantao": float(servico.preco_domiciliar_plantao) if servico.preco_domiciliar_plantao else 0.0,
        }
    }


@router.put("/{servico_id}")
def atualizar_servico(
    servico_id: int,
    servico: ServicoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza um servico existente"""
    db_servico = db.query(Servico).filter(Servico.id == servico_id).first()
    
    if not db_servico:
        raise HTTPException(status_code=404, detail="Servico nao encontrado")
    
    try:
        if servico.nome is not None:
            db_servico.nome = servico.nome
        if servico.descricao is not None:
            db_servico.descricao = servico.descricao
        if servico.duracao_minutos is not None:
            db_servico.duracao_minutos = servico.duracao_minutos
        
        # Atualizar preços se fornecidos
        if servico.precos:
            precos = servico.precos
            if precos.fortaleza_comercial is not None:
                db_servico.preco_fortaleza_comercial = Decimal(str(precos.fortaleza_comercial))
            if precos.fortaleza_plantao is not None:
                db_servico.preco_fortaleza_plantao = Decimal(str(precos.fortaleza_plantao))
            if precos.rm_comercial is not None:
                db_servico.preco_rm_comercial = Decimal(str(precos.rm_comercial))
            if precos.rm_plantao is not None:
                db_servico.preco_rm_plantao = Decimal(str(precos.rm_plantao))
            if precos.domiciliar_comercial is not None:
                db_servico.preco_domiciliar_comercial = Decimal(str(precos.domiciliar_comercial))
            if precos.domiciliar_plantao is not None:
                db_servico.preco_domiciliar_plantao = Decimal(str(precos.domiciliar_plantao))

        db_servico.updated_at = datetime.now()

        db.commit()
        db.refresh(db_servico)
        
        return {
            "id": db_servico.id,
            "nome": db_servico.nome,
            "descricao": db_servico.descricao,
            "duracao_minutos": db_servico.duracao_minutos,
            "ativo": db_servico.ativo,
            "precos": {
                "fortaleza_comercial": float(db_servico.preco_fortaleza_comercial) if db_servico.preco_fortaleza_comercial else 0.0,
                "fortaleza_plantao": float(db_servico.preco_fortaleza_plantao) if db_servico.preco_fortaleza_plantao else 0.0,
                "rm_comercial": float(db_servico.preco_rm_comercial) if db_servico.preco_rm_comercial else 0.0,
                "rm_plantao": float(db_servico.preco_rm_plantao) if db_servico.preco_rm_plantao else 0.0,
                "domiciliar_comercial": float(db_servico.preco_domiciliar_comercial) if db_servico.preco_domiciliar_comercial else 0.0,
                "domiciliar_plantao": float(db_servico.preco_domiciliar_plantao) if db_servico.preco_domiciliar_plantao else 0.0,
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar servico: {str(e)}")


@router.delete("/{servico_id}")
def deletar_servico(
    servico_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove um servico (soft delete)"""
    db_servico = db.query(Servico).filter(Servico.id == servico_id).first()
    
    if not db_servico:
        raise HTTPException(status_code=404, detail="Servico nao encontrado")
    
    try:
        db_servico.ativo = False
        db.commit()
        
        return {"message": "Servico removido com sucesso"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao excluir servico: {str(e)}")


@router.get("/{servico_id}/preco")
def obter_preco_servico(
    servico_id: int,
    regiao: str,  # fortaleza, rm, domiciliar
    tipo_horario: str,  # comercial, plantao
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtem o preço específico de um serviço baseado na região e tipo de horário"""
    servico = db.query(Servico).filter(
        Servico.id == servico_id,
        Servico.ativo == True
    ).first()
    
    if not servico:
        raise HTTPException(status_code=404, detail="Servico nao encontrado")
    
    # Mapear região e tipo_horario para o campo correto
    campo_map = {
        ("fortaleza", "comercial"): "preco_fortaleza_comercial",
        ("fortaleza", "plantao"): "preco_fortaleza_plantao",
        ("rm", "comercial"): "preco_rm_comercial",
        ("rm", "plantao"): "preco_rm_plantao",
        ("domiciliar", "comercial"): "preco_domiciliar_comercial",
        ("domiciliar", "plantao"): "preco_domiciliar_plantao",
    }
    
    regiao_lower = regiao.lower()
    tipo_lower = tipo_horario.lower()
    
    campo = campo_map.get((regiao_lower, tipo_lower))
    if not campo:
        raise HTTPException(status_code=400, detail="Regiao ou tipo de horario invalido")
    
    preco = getattr(servico, campo, Decimal("0.00"))
    
    return {
        "servico_id": servico_id,
        "servico_nome": servico.nome,
        "regiao": regiao,
        "tipo_horario": tipo_horario,
        "preco": float(preco) if preco else 0.0
    }
