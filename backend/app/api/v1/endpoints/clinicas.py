from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field, validator
from decimal import Decimal
from datetime import datetime

from app.db.database import get_db
from app.models.clinica import Clinica
from app.schemas.clinica_fiscal import EnderecoFiscal
from app.models.cep_bairro_override import CepBairroOverride
from app.models.servico import Servico
from app.models.tabela_preco import PrecoServicoClinica
from app.core.security import get_current_user
from app.core.config import settings
from app.models.user import User
from app.services.precos_service import calcular_preco_servico
from app.services.geocoding_service import (
    GeocodingError,
    buscar_cep_viacep,
    geocodificar_endereco_google,
    montar_endereco_completo,
    normalizar_cep,
)

router = APIRouter()


def _normalizar_whatsapps(valores) -> List[str]:
    if valores is None:
        return []
    if isinstance(valores, str):
        valores = [valores]
    if not isinstance(valores, (list, tuple)):
        raise ValueError("WhatsApps devem ser informados em uma lista.")

    normalizados: List[str] = []
    for valor in valores:
        digitos = "".join(char for char in str(valor or "") if char.isdigit()).lstrip("0")
        if not digitos:
            continue
        if len(digitos) > 15:
            raise ValueError("Numero de WhatsApp invalido.")
        if digitos not in normalizados:
            normalizados.append(digitos)
        if len(normalizados) > 10:
            raise ValueError("Informe no maximo 10 numeros de WhatsApp por clinica.")
    return normalizados


# Schemas
class ClinicaBase(BaseModel):
    nome: str = Field(..., min_length=2, max_length=255)
    razao_social: Optional[str] = ""
    cnpj: Optional[str] = ""
    telefone: Optional[str] = ""
    whatsapps: List[str] = Field(default_factory=list)
    email: Optional[str] = ""
    atividade_cnae: Optional[str] = ""
    endereco: Optional[str] = ""
    numero: Optional[str] = ""
    complemento: Optional[str] = ""
    bairro: Optional[str] = ""
    cidade: Optional[str] = ""
    estado: Optional[str] = ""
    cep: Optional[str] = ""
    regiao_operacional: Optional[str] = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    place_id: Optional[str] = ""
    endereco_normalizado: Optional[str] = ""
    bairro_manual: bool = False
    observacoes: Optional[str] = ""

    @validator("whatsapps", pre=True)
    def validar_whatsapps(cls, valor):
        return _normalizar_whatsapps(valor)


class ClinicaCreate(ClinicaBase):
    tabela_preco_id: Optional[int] = 1
    preco_personalizado_km: Optional[float] = 0
    preco_personalizado_base: Optional[float] = 0
    observacoes_preco: Optional[str] = ""


class ClinicaUpdate(ClinicaBase):
    whatsapps: Optional[List[str]] = None
    tabela_preco_id: Optional[int] = None
    preco_personalizado_km: Optional[float] = None
    preco_personalizado_base: Optional[float] = None
    observacoes_preco: Optional[str] = None


class ClinicaWhatsappsUpdate(BaseModel):
    whatsapps: List[str] = Field(default_factory=list)

    @validator("whatsapps", pre=True)
    def validar_whatsapps(cls, valor):
        return _normalizar_whatsapps(valor)


class ClinicaResponse(BaseModel):
    id: int
    nome: str
    razao_social: Optional[str] = None
    cnpj: Optional[str] = None
    telefone: Optional[str] = None
    whatsapps: List[str] = Field(default_factory=list)
    email: Optional[str] = None
    atividade_cnae: Optional[str] = None
    endereco: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    cep: Optional[str] = None
    regiao_operacional: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    place_id: Optional[str] = None
    endereco_normalizado: Optional[str] = None
    observacoes: Optional[str] = None
    tabela_preco_id: int = 1
    preco_personalizado_km: float = 0
    preco_personalizado_base: float = 0
    observacoes_preco: Optional[str] = None
    ativo: bool = True
    endereco_fiscal: Optional[dict] = None


class PrecoServicoClinicaPayload(BaseModel):
    servico_id: int
    preco_comercial: Optional[float] = Field(default=None, ge=0)
    preco_plantao: Optional[float] = Field(default=None, ge=0)


class PrecosServicosClinicaUpdate(BaseModel):
    items: List[PrecoServicoClinicaPayload] = Field(default_factory=list)


class GeocodeEnderecoPayload(BaseModel):
    endereco: Optional[str] = ""
    numero: Optional[str] = ""
    complemento: Optional[str] = ""
    bairro: Optional[str] = ""
    cidade: Optional[str] = ""
    estado: Optional[str] = ""
    cep: Optional[str] = ""


# Dicionário de cidades da Região Metropolitana de Fortaleza
# Se a cidade não estiver nesta lista e não for Fortaleza, é considerada cidade distante
CIDADES_RM_FORTALEZA = [
    "caucaia", "maracanau", "pacatuba", "eusebio", "aquiraz",
    "horizonte", "itaitinga", "guaiuba", "maranguape", "pacajus",
    "sao goncalo do amarante", "chorozinho", "paracuru", "paraipaba",
    "sao luis do curu", "tra ri", "tururu", "uruoca", "varjota"
]


def determinar_tabela_preco(cidade: str) -> int:
    """
    Determina a tabela de preço baseada na cidade.
    
    Retorna:
    1 = Fortaleza
    2 = Região Metropolitana
    3 = Domiciliar (para cidades fora da RM)
    """
    if not cidade:
        return 1  # Default: Fortaleza
    
    cidade_lower = cidade.lower().strip()
    
    if cidade_lower == "fortaleza":
        return 1
    elif cidade_lower in CIDADES_RM_FORTALEZA:
        return 2
    else:
        return 3  # Domiciliar para cidades distantes


def classificar_regiao_operacional(cidade: Optional[str], estado: Optional[str]) -> str:
    cidade_norm = str(cidade or "").strip().lower()
    estado_norm = str(estado or "").strip().lower()
    if not cidade_norm:
        return "indefinida"
    if cidade_norm == "fortaleza" and (not estado_norm or estado_norm == "ce"):
        return "fortaleza"
    if cidade_norm in CIDADES_RM_FORTALEZA and (not estado_norm or estado_norm == "ce"):
        return "regiao_metropolitana"
    return "domiciliar"


def _upsert_bairro_aprendizado(
    db: Session,
    *,
    cep: Optional[str],
    bairro: Optional[str],
    cidade: Optional[str],
    estado: Optional[str],
) -> None:
    cep_norm = normalizar_cep(cep)
    bairro_limpo = str(bairro or "").strip()
    if len(cep_norm) != 8 or not bairro_limpo:
        return

    row = db.query(CepBairroOverride).filter(CepBairroOverride.cep == cep_norm).first()
    if not row:
        row = CepBairroOverride(
            cep=cep_norm,
            bairro=bairro_limpo,
            cidade=str(cidade or "").strip() or None,
            estado=str(estado or "").strip().upper() or None,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        return

    row.bairro = bairro_limpo
    row.cidade = str(cidade or "").strip() or None
    row.estado = str(estado or "").strip().upper() or None
    row.updated_at = datetime.utcnow()


def _buscar_bairro_aprendizado(db: Session, cep: Optional[str]) -> Optional[CepBairroOverride]:
    cep_norm = normalizar_cep(cep)
    if len(cep_norm) != 8:
        return None
    return db.query(CepBairroOverride).filter(CepBairroOverride.cep == cep_norm).first()


def _serialize_clinica(clinica: Clinica) -> dict:
    whatsapps = _normalizar_whatsapps(getattr(clinica, "whatsapps", None))
    if not whatsapps and clinica.telefone:
        whatsapps = _normalizar_whatsapps([clinica.telefone])
    return {
        "id": clinica.id,
        "nome": clinica.nome,
        "razao_social": clinica.razao_social,
        "cnpj": clinica.cnpj,
        "telefone": clinica.telefone,
        "whatsapps": whatsapps,
        "email": clinica.email,
        "atividade_cnae": clinica.atividade_cnae,
        "endereco": clinica.endereco,
        "numero": clinica.numero,
        "complemento": clinica.complemento,
        "bairro": clinica.bairro,
        "cidade": clinica.cidade,
        "estado": clinica.estado,
        "cep": clinica.cep,
        "endereco_fiscal": clinica.endereco_fiscal,
        "regiao_operacional": clinica.regiao_operacional,
        "latitude": float(clinica.latitude) if clinica.latitude is not None else None,
        "longitude": float(clinica.longitude) if clinica.longitude is not None else None,
        "place_id": clinica.place_id,
        "endereco_normalizado": clinica.endereco_normalizado,
        "observacoes": clinica.observacoes,
        "tabela_preco_id": clinica.tabela_preco_id or 1,
        "preco_personalizado_km": float(clinica.preco_personalizado_km) if clinica.preco_personalizado_km else 0,
        "preco_personalizado_base": float(clinica.preco_personalizado_base) if clinica.preco_personalizado_base else 0,
        "observacoes_preco": clinica.observacoes_preco,
        "ativo": clinica.ativo,
    }


@router.get("")
def listar_clinicas(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista clinicas com informações completas"""
    query = db.query(Clinica).filter(Clinica.ativo == True)
    
    total = query.count()
    items = query.order_by(Clinica.nome).offset(skip).limit(limit).all()
    
    clinicas = [_serialize_clinica(c) for c in items]
    return {"total": total, "items": clinicas}


@router.get("/cep/{cep}")
def consultar_cep(
    cep: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Consulta CEP no ViaCEP e aplica bairro aprendido (se existir)."""
    try:
        dados = buscar_cep_viacep(cep)
    except GeocodingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    bairro_origem = "viacep"
    aprendizado = _buscar_bairro_aprendizado(db, dados.get("cep"))
    if aprendizado:
        bairro_aprendido = str(aprendizado.bairro or "").strip()
        if bairro_aprendido:
            dados["bairro"] = bairro_aprendido
            if not dados.get("cidade"):
                dados["cidade"] = str(aprendizado.cidade or "").strip()
            if not dados.get("estado"):
                dados["estado"] = str(aprendizado.estado or "").strip().upper()
            bairro_origem = "aprendizado"

    return {
        "ok": True,
        "item": {
            "cep": dados.get("cep"),
            "logradouro": dados.get("logradouro"),
            "complemento": dados.get("complemento"),
            "bairro": dados.get("bairro"),
            "cidade": dados.get("cidade"),
            "estado": dados.get("estado"),
            "ibge": dados.get("ibge"),
            "bairro_origem": bairro_origem,
        },
    }


@router.post("/geocode-endereco")
def geocode_endereco(
    payload: GeocodeEnderecoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Geocodifica endereco completo no Google e retorna dados normalizados."""
    endereco_completo = montar_endereco_completo(
        endereco=payload.endereco,
        numero=payload.numero,
        complemento=payload.complemento,
        bairro=payload.bairro,
        cidade=payload.cidade,
        estado=payload.estado,
        cep=payload.cep,
    )
    if not str(endereco_completo or "").strip():
        raise HTTPException(status_code=422, detail="Endereco incompleto para geocoding.")

    try:
        geo = geocodificar_endereco_google(endereco_completo, settings.GOOGLE_MAPS_API_KEY)
    except GeocodingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    cep_final = geo.cep or normalizar_cep(payload.cep)
    bairro_final = geo.bairro or str(payload.bairro or "").strip()
    cidade_final = geo.cidade or str(payload.cidade or "").strip()
    estado_final = (geo.estado or str(payload.estado or "")).strip().upper()
    regiao = classificar_regiao_operacional(cidade_final, estado_final)

    aprendizado = _buscar_bairro_aprendizado(db, cep_final)
    bairro_origem = "google"
    if aprendizado:
        bairro_aprendido = str(aprendizado.bairro or "").strip()
        if bairro_aprendido:
            bairro_final = bairro_aprendido
            bairro_origem = "aprendizado"

    return {
        "ok": True,
        "item": {
            "latitude": geo.latitude,
            "longitude": geo.longitude,
            "endereco_normalizado": geo.endereco_normalizado,
            "place_id": geo.place_id,
            "bairro": bairro_final,
            "cidade": cidade_final,
            "estado": estado_final,
            "cep": cep_final,
            "regiao_operacional": regiao,
            "bairro_origem": bairro_origem,
        },
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def criar_clinica(
    clinica: ClinicaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova clinica com suporte a precos personalizados"""
    existing = db.query(Clinica).filter(
        Clinica.nome.ilike(clinica.nome),
        Clinica.ativo == True
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ja existe uma clinica com o nome '{clinica.nome}'"
        )

    try:
        regiao_operacional = classificar_regiao_operacional(clinica.cidade, clinica.estado)

        tabela_id = clinica.tabela_preco_id
        if tabela_id == 1 and clinica.cidade:
            tabela_id = determinar_tabela_preco(clinica.cidade)

        db_clinica = Clinica(
            nome=clinica.nome,
            razao_social=clinica.razao_social,
            cnpj=clinica.cnpj,
            telefone=clinica.telefone,
            whatsapps=clinica.whatsapps,
            email=clinica.email,
            atividade_cnae=clinica.atividade_cnae,
            endereco=clinica.endereco,
            numero=clinica.numero,
            complemento=clinica.complemento,
            bairro=clinica.bairro,
            cidade=clinica.cidade,
            estado=clinica.estado,
            cep=normalizar_cep(clinica.cep),
            regiao_operacional=regiao_operacional,
            latitude=clinica.latitude,
            longitude=clinica.longitude,
            place_id=clinica.place_id,
            endereco_normalizado=clinica.endereco_normalizado,
            geocode_at=datetime.utcnow() if clinica.latitude is not None and clinica.longitude is not None else None,
            observacoes=clinica.observacoes,
            tabela_preco_id=tabela_id,
            preco_personalizado_km=Decimal(str(clinica.preco_personalizado_km)) if clinica.preco_personalizado_km else Decimal("0.00"),
            preco_personalizado_base=Decimal(str(clinica.preco_personalizado_base)) if clinica.preco_personalizado_base else Decimal("0.00"),
            observacoes_preco=clinica.observacoes_preco,
            ativo=True
        )

        db.add(db_clinica)
        if clinica.bairro_manual:
            _upsert_bairro_aprendizado(
                db,
                cep=clinica.cep,
                bairro=clinica.bairro,
                cidade=clinica.cidade,
                estado=clinica.estado,
            )
        db.commit()
        db.refresh(db_clinica)

        return _serialize_clinica(db_clinica)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar clinica: {str(e)}")


@router.get("/{clinica_id}")
def obter_clinica(
    clinica_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtem detalhes completos de uma clinica"""
    clinica = db.query(Clinica).filter(
        Clinica.id == clinica_id,
        Clinica.ativo == True
    ).first()
    
    if not clinica:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada")
    
    return _serialize_clinica(clinica)


@router.get("/{clinica_id}/precos-servicos")
def listar_precos_servicos_clinica(
    clinica_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista precos base e precos negociados por servico para uma clinica."""
    clinica = db.query(Clinica).filter(
        Clinica.id == clinica_id,
        Clinica.ativo == True
    ).first()
    if not clinica:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada")

    # Para configuracao de precos negociados, exibimos todos os servicos cadastrados.
    # Isso evita "lista vazia" quando servicos estao temporariamente inativos.
    servicos = db.query(Servico).order_by(Servico.nome).all()
    custom_rows = []
    inspector = inspect(db.bind)
    if "precos_servicos_clinica" in inspector.get_table_names():
        custom_rows = db.query(PrecoServicoClinica).filter(
            PrecoServicoClinica.clinica_id == clinica_id,
            PrecoServicoClinica.ativo == 1
        ).all()
    custom_map = {row.servico_id: row for row in custom_rows}

    items = []
    for servico in servicos:
        preco_base_comercial = calcular_preco_servico(
            db=db,
            clinica_id=clinica_id,
            servico_id=servico.id,
            tipo_horario="comercial",
            usar_preco_clinica=False,
        )
        preco_base_plantao = calcular_preco_servico(
            db=db,
            clinica_id=clinica_id,
            servico_id=servico.id,
            tipo_horario="plantao",
            usar_preco_clinica=False,
        )
        custom = custom_map.get(servico.id)
        items.append(
            {
                "servico_id": servico.id,
                "servico_nome": servico.nome,
                "servico_ativo": bool(servico.ativo),
                "preco_base_comercial": float(preco_base_comercial),
                "preco_base_plantao": float(preco_base_plantao),
                "preco_negociado_comercial": float(custom.preco_comercial) if custom and custom.preco_comercial is not None else None,
                "preco_negociado_plantao": float(custom.preco_plantao) if custom and custom.preco_plantao is not None else None,
            }
        )

    return {"clinica_id": clinica_id, "items": items}


@router.put("/{clinica_id}/precos-servicos")
def salvar_precos_servicos_clinica(
    clinica_id: int,
    payload: PrecosServicosClinicaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Salva precos negociados por servico para uma clinica."""
    clinica = db.query(Clinica).filter(
        Clinica.id == clinica_id,
        Clinica.ativo == True
    ).first()
    if not clinica:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada")

    inspector = inspect(db.bind)
    if "precos_servicos_clinica" not in inspector.get_table_names():
        raise HTTPException(
            status_code=500,
            detail="Tabela de precos negociados indisponivel. Execute as migracoes pendentes."
        )

    servicos_validos = {row[0] for row in db.query(Servico.id).all()}
    existentes = db.query(PrecoServicoClinica).filter(
        PrecoServicoClinica.clinica_id == clinica_id
    ).all()
    existentes_map = {row.servico_id: row for row in existentes}

    atualizados = 0
    try:
        for item in payload.items:
            if item.servico_id not in servicos_validos:
                raise HTTPException(
                    status_code=400,
                    detail=f"Servico invalido para preco negociado: {item.servico_id}"
                )

            if item.preco_comercial is None and item.preco_plantao is None:
                row_to_disable = existentes_map.get(item.servico_id)
                if row_to_disable and row_to_disable.ativo == 1:
                    row_to_disable.ativo = 0
                    atualizados += 1
                continue

            row = existentes_map.get(item.servico_id)
            if not row:
                row = PrecoServicoClinica(
                    clinica_id=clinica_id,
                    servico_id=item.servico_id,
                    ativo=1,
                )
                db.add(row)
                existentes_map[item.servico_id] = row

            row.preco_comercial = Decimal(str(item.preco_comercial)) if item.preco_comercial is not None else None
            row.preco_plantao = Decimal(str(item.preco_plantao)) if item.preco_plantao is not None else None
            row.ativo = 1
            atualizados += 1

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao salvar precos negociados: {str(e)}")

    return {
        "message": "Precos negociados atualizados com sucesso",
        "atualizados": atualizados
    }


@router.put("/{clinica_id}/whatsapps")
def atualizar_whatsapps_clinica(
    clinica_id: int,
    payload: ClinicaWhatsappsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza somente os WhatsApps da clinica sem alterar os demais dados cadastrais."""
    db_clinica = db.query(Clinica).filter(
        Clinica.id == clinica_id,
        Clinica.ativo == True,
    ).first()

    if not db_clinica:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada")

    try:
        db_clinica.whatsapps = payload.whatsapps
        db.commit()
        db.refresh(db_clinica)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao atualizar WhatsApps da clinica: {str(exc)}",
        ) from exc

    return _serialize_clinica(db_clinica)


@router.put("/{clinica_id}/endereco-fiscal")
def atualizar_endereco_fiscal(
    clinica_id: int,
    payload: EnderecoFiscal,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Salva somente o endereço contábil, sem consultar CEP/Maps ou alterar preços."""
    import re
    from datetime import timezone
    from app.services.fiscal_fechamento_service import _documento_valido

    clinica = db.query(Clinica).filter(Clinica.id == clinica_id, Clinica.ativo == True).with_for_update().first()
    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica não encontrada")
    cnpj_atual = re.sub(r"[.\s/\-]", "", str(clinica.cnpj or "").upper())
    if payload.cnpj != cnpj_atual or not _documento_valido(payload.cnpj, "PJ"):
        raise HTTPException(status_code=422, detail="O endereço fiscal deve corresponder ao CNPJ válido salvo na clínica.")
    try:
        clinica.endereco_fiscal = {
            **payload.model_dump(),
            "conferido_em": datetime.now(timezone.utc).isoformat(),
            "conferido_por": current_user.id,
        }
        db.commit()
        db.refresh(clinica)
        return _serialize_clinica(clinica)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Não foi possível salvar o endereço fiscal.") from exc


@router.put("/{clinica_id}")
def atualizar_clinica(
    clinica_id: int,
    clinica: ClinicaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza uma clinica existente"""
    db_clinica = db.query(Clinica).filter(
        Clinica.id == clinica_id,
        Clinica.ativo == True
    ).first()

    if not db_clinica:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada")

    try:
        if clinica.nome is not None:
            db_clinica.nome = clinica.nome
        if clinica.razao_social is not None:
            db_clinica.razao_social = clinica.razao_social
        if clinica.cnpj is not None:
            db_clinica.cnpj = clinica.cnpj
        if clinica.telefone is not None:
            db_clinica.telefone = clinica.telefone
        if clinica.whatsapps is not None:
            db_clinica.whatsapps = clinica.whatsapps
        if clinica.email is not None:
            db_clinica.email = clinica.email
        if clinica.atividade_cnae is not None:
            db_clinica.atividade_cnae = clinica.atividade_cnae
        if clinica.endereco is not None:
            db_clinica.endereco = clinica.endereco
        if clinica.numero is not None:
            db_clinica.numero = clinica.numero
        if clinica.complemento is not None:
            db_clinica.complemento = clinica.complemento
        if clinica.bairro is not None:
            db_clinica.bairro = clinica.bairro
        if clinica.cidade is not None:
            db_clinica.cidade = clinica.cidade
        if clinica.estado is not None:
            db_clinica.estado = clinica.estado
        if clinica.cep is not None:
            db_clinica.cep = normalizar_cep(clinica.cep)
        if clinica.latitude is not None:
            db_clinica.latitude = clinica.latitude
        if clinica.longitude is not None:
            db_clinica.longitude = clinica.longitude
        if clinica.place_id is not None:
            db_clinica.place_id = clinica.place_id
        if clinica.endereco_normalizado is not None:
            db_clinica.endereco_normalizado = clinica.endereco_normalizado
        if clinica.latitude is not None and clinica.longitude is not None:
            db_clinica.geocode_at = datetime.utcnow()
        if clinica.observacoes is not None:
            db_clinica.observacoes = clinica.observacoes

        db_clinica.regiao_operacional = classificar_regiao_operacional(
            db_clinica.cidade,
            db_clinica.estado,
        )

        if clinica.tabela_preco_id is not None:
            db_clinica.tabela_preco_id = clinica.tabela_preco_id
        elif clinica.cidade is not None and (db_clinica.tabela_preco_id or 1) == 1:
            db_clinica.tabela_preco_id = determinar_tabela_preco(db_clinica.cidade)

        if clinica.preco_personalizado_km is not None:
            db_clinica.preco_personalizado_km = Decimal(str(clinica.preco_personalizado_km))
        if clinica.preco_personalizado_base is not None:
            db_clinica.preco_personalizado_base = Decimal(str(clinica.preco_personalizado_base))
        if clinica.observacoes_preco is not None:
            db_clinica.observacoes_preco = clinica.observacoes_preco

        if clinica.bairro_manual:
            _upsert_bairro_aprendizado(
                db,
                cep=db_clinica.cep,
                bairro=db_clinica.bairro,
                cidade=db_clinica.cidade,
                estado=db_clinica.estado,
            )

        db.commit()
        db.refresh(db_clinica)

        payload = _serialize_clinica(db_clinica)
        payload["message"] = "Clinica atualizada com sucesso"
        return payload
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar clinica: {str(e)}")


@router.delete("/{clinica_id}")
def deletar_clinica(
    clinica_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove uma clinica (soft delete)"""
    db_clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    
    if not db_clinica:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada")
    
    try:
        db_clinica.ativo = False
        db.commit()
        
        return {"message": "Clinica removida com sucesso"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao excluir clinica: {str(e)}")


@router.get("/tabelas-preco/opcoes")
def listar_opcoes_tabela_preco(
    current_user: User = Depends(get_current_user)
):
    """Retorna as opções de tabela de preço disponíveis"""
    return {
        "items": [
            {"id": 1, "nome": "Fortaleza", "descricao": "Clínicas na capital"},
            {"id": 2, "nome": "Região Metropolitana", "descricao": "Cidades próximas a Fortaleza"},
            {"id": 3, "nome": "Domiciliar", "descricao": "Atendimento domiciliar padrão"},
            {"id": 4, "nome": "Personalizado", "descricao": "Preço negociado para cidade distante"}
        ]
    }


@router.post("/sugerir-tabela-preco")
def sugerir_tabela_preco(
    cidade: str,
    estado: str = "",
    current_user: User = Depends(get_current_user)
):
    """Sugere a tabela de preco baseada na cidade informada"""
    tabela_id = determinar_tabela_preco(cidade)
    regiao = classificar_regiao_operacional(cidade, estado)

    tabelas = {
        1: {"id": 1, "nome": "Fortaleza", "descricao": "Capital"},
        2: {"id": 2, "nome": "Regiao Metropolitana", "descricao": "Cidades proximas"},
        3: {"id": 3, "nome": "Domiciliar", "descricao": "Cidade distante"},
    }

    return {
        "cidade": cidade,
        "estado": estado,
        "regiao_operacional": regiao,
        "tabela_sugerida": tabelas.get(tabela_id),
        "cidade_reconhecida": cidade.lower().strip() in ["fortaleza"] + CIDADES_RM_FORTALEZA,
    }
