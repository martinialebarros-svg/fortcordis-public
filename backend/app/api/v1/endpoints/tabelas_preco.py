"""Endpoints para gerenciamento de tabelas de preço"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from decimal import Decimal

from app.db.database import get_db
from app.models.tabela_preco import TabelaPreco, PrecoServico
from app.models.servico import Servico
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter()


class TabelaPrecoCreate(BaseModel):
    nome: str
    descricao: Optional[str] = ""


class TabelaPrecoResponse(BaseModel):
    id: int
    nome: str
    descricao: Optional[str] = None


class PrecoServicoCreate(BaseModel):
    servico_id: int
    preco_comercial: float
    preco_plantao: float
    observacoes: Optional[str] = ""


class PrecoServicoResponse(BaseModel):
    id: int
    servico_id: int
    servico_nome: str
    preco_comercial: float
    preco_plantao: float
    observacoes: Optional[str] = None


@router.get("/tabelas", response_model=List[TabelaPrecoResponse])
def listar_tabelas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todas as tabelas de preço"""
    tabelas = db.query(TabelaPreco).filter(TabelaPreco.ativo == 1).all()
    return tabelas


@router.post("/tabelas", response_model=TabelaPrecoResponse, status_code=status.HTTP_201_CREATED)
def criar_tabela(
    tabela: TabelaPrecoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova tabela de preço"""
    db_tabela = TabelaPreco(
        nome=tabela.nome,
        descricao=tabela.descricao,
        ativo=1
    )
    db.add(db_tabela)
    db.commit()
    db.refresh(db_tabela)
    return db_tabela


@router.get("/{tabela_id}/precos", response_model=List[PrecoServicoResponse])
def listar_precos_tabela(
    tabela_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todos os preços de uma tabela"""
    precos = db.query(
        PrecoServico,
        Servico.nome.label('servico_nome')
    ).join(
        Servico, PrecoServico.servico_id == Servico.id
    ).filter(
        PrecoServico.tabela_preco_id == tabela_id
    ).all()
    
    return [{
        "id": p.PrecoServico.id,
        "servico_id": p.PrecoServico.servico_id,
        "servico_nome": p.servico_nome,
        "preco_comercial": float(p.PrecoServico.preco_comercial) if p.PrecoServico.preco_comercial else 0,
        "preco_plantao": float(p.PrecoServico.preco_plantao) if p.PrecoServico.preco_plantao else 0,
        "observacoes": p.PrecoServico.observacoes
    } for p in precos]


@router.post("/{tabela_id}/precos", response_model=PrecoServicoResponse)
def adicionar_preco_servico(
    tabela_id: int,
    preco: PrecoServicoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Adiciona ou atualiza o preço de um serviço na tabela"""
    # Verificar se já existe preço para este serviço
    existing = db.query(PrecoServico).filter(
        PrecoServico.tabela_preco_id == tabela_id,
        PrecoServico.servico_id == preco.servico_id
    ).first()
    
    if existing:
        # Atualizar
        existing.preco_comercial = Decimal(str(preco.preco_comercial))
        existing.preco_plantao = Decimal(str(preco.preco_plantao))
        existing.observacoes = preco.observacoes
        db.commit()
        db.refresh(existing)
        db_preco = existing
    else:
        # Criar novo
        db_preco = PrecoServico(
            tabela_preco_id=tabela_id,
            servico_id=preco.servico_id,
            preco_comercial=Decimal(str(preco.preco_comercial)),
            preco_plantao=Decimal(str(preco.preco_plantao)),
            observacoes=preco.observacoes
        )
        db.add(db_preco)
        db.commit()
        db.refresh(db_preco)
    
    # Buscar nome do serviço
    servico = db.query(Servico).filter(Servico.id == preco.servico_id).first()
    
    return {
        "id": db_preco.id,
        "servico_id": db_preco.servico_id,
        "servico_nome": servico.nome if servico else "",
        "preco_comercial": float(db_preco.preco_comercial) if db_preco.preco_comercial else 0,
        "preco_plantao": float(db_preco.preco_plantao) if db_preco.preco_plantao else 0,
        "observacoes": db_preco.observacoes
    }


@router.get("/clinica/{clinica_id}/preco")
def obter_preco_para_clinica(
    clinica_id: int,
    servico_id: int,
    tipo_horario: str,  # 'comercial' ou 'plantao'
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém o preço de um serviço para uma clínica específica"""
    from app.models.clinica import Clinica
    
    # Buscar clínica
    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica não encontrada")
    
    # Buscar preço na tabela da clínica
    preco = db.query(PrecoServico).filter(
        PrecoServico.tabela_preco_id == clinica.tabela_preco_id,
        PrecoServico.servico_id == servico_id
    ).first()
    
    if not preco:
        return {
            "preco": 0,
            "tipo_horario": tipo_horario,
            "mensagem": "Preço não configurado para este serviço"
        }
    
    if tipo_horario == 'plantao':
        valor = float(preco.preco_plantao) if preco.preco_plantao else 0
    else:
        valor = float(preco.preco_comercial) if preco.preco_comercial else 0
    
    return {
        "preco": valor,
        "tipo_horario": tipo_horario,
        "tabela": clinica.tabela_preco_id
    }


# Seed data - criar tabelas padrão se não existirem
@router.post("/seed")
def seed_tabelas_preco(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria as tabelas de preço padrão"""
    tabelas_padrao = [
        {"nome": "Clínicas Fortaleza", "descricao": "Tabela para clínicas na cidade de Fortaleza"},
        {"nome": "Região Metropolitana", "descricao": "Tabela para clínicas na região metropolitana de Fortaleza"},
        {"nome": "Atendimento Domiciliar", "descricao": "Tabela para atendimentos domiciliares"},
    ]
    
    criadas = 0
    for tabela_data in tabelas_padrao:
        existing = db.query(TabelaPreco).filter(TabelaPreco.nome == tabela_data["nome"]).first()
        if not existing:
            tabela = TabelaPreco(**tabela_data, ativo=1)
            db.add(tabela)
            criadas += 1
    
    db.commit()
    return {"message": f"{criadas} tabelas criadas com sucesso"}
