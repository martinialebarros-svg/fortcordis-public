from datetime import datetime
import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, inspect, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.endpoints.paciente_mesclagem import router as mesclagem_router
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.atendimento_clinico import AlertaClinico, AtendimentoClinico
from app.models.laudo import Laudo
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.user import User
from app.services.tutor_identidade_service import exigir_tutor_utilizavel
from app.services import tutor_rotina_service as rotina_tutor
from app.utils.paciente_idade import alteracoes_idade, dados_idade_paciente
from app.utils.paciente_helpers import normalizar_sexo_paciente

router = APIRouter()
router.include_router(mesclagem_router)

LAUDO_STATUSES_CONCLUIDOS = (
    "arquivado",
    "concluido",
    "concluído",
    "finalizado",
    "liberado no portal",
)


def _gerar_nome_key(nome: Optional[str]) -> str:
    """Gera chave normalizada para compatibilidade com schema legado."""
    if not nome:
        return ""
    texto = unicodedata.normalize("NFKD", nome)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _legacy_now_dt() -> datetime:
    return datetime.utcnow()


def _to_iso(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _filtro_paciente_ativo():
    """Compatibilidade entre bancos legados com ativo como INTEGER/BOOLEAN/TEXT."""
    return func.lower(func.coalesce(cast(Paciente.ativo, String), "1")).in_(["1", "true", "t"])


def _is_ativo(valor) -> bool:
    if valor is None:
        return True
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return int(valor) != 0
    return str(valor).strip().lower() in {"1", "true", "t", "yes", "y"}


def _ensure_tutores_timestamp_columns(db: Session) -> None:
    """
    Compatibilidade com bases legadas (ex.: SQLite local) onde a tabela tutores
    não possui created_at/updated_at.
    """
    insp = inspect(db.connection())
    if "tutores" not in insp.get_table_names():
        return

    colunas = {col["name"] for col in insp.get_columns("tutores")}
    alteracoes: list[str] = []

    colunas_texto = {
        "created_at": 'ALTER TABLE "tutores" ADD COLUMN created_at DATETIME',
        "updated_at": 'ALTER TABLE "tutores" ADD COLUMN updated_at DATETIME',
        "place_id": 'ALTER TABLE "tutores" ADD COLUMN place_id TEXT',
        "endereco_normalizado": 'ALTER TABLE "tutores" ADD COLUMN endereco_normalizado TEXT',
    }
    colunas_float = {
        "latitude": 'ALTER TABLE "tutores" ADD COLUMN latitude FLOAT',
        "longitude": 'ALTER TABLE "tutores" ADD COLUMN longitude FLOAT',
    }

    for nome_coluna, sql in colunas_texto.items():
        if nome_coluna not in colunas:
            alteracoes.append(sql)
    for nome_coluna, sql in colunas_float.items():
        if nome_coluna not in colunas:
            alteracoes.append(sql)

    if not alteracoes:
        return

    for sql in alteracoes:
        db.execute(text(sql))
    db.commit()


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip()


def _paciente_tem_payload_tutor(paciente: BaseModel) -> bool:
    campos = (
        "tutor_id",
        "tutor",
        "tutor_email",
        "tutor_telefone",
        "tutor_whatsapp",
        "tutor_cpf",
        "tutor_cep",
        "tutor_endereco",
        "tutor_numero",
        "tutor_complemento",
        "tutor_bairro",
        "tutor_cidade",
        "tutor_estado",
        "tutor_identificacao_pendente",
        "tutor_origem_cadastro",
        "tutor_identificacao_observacoes",
    )
    campos_enviados = getattr(paciente, "model_fields_set", set())
    return any(campo in campos_enviados for campo in campos) or any(
        getattr(paciente, campo, None) not in (None, "") for campo in campos
    )


def _aplicar_dados_tutor(tutor: Tutor, paciente: BaseModel, *, db=None, current_user=None) -> None:
    identidade_antes = rotina_tutor.dados_identidade(tutor)
    campos_enviados = getattr(paciente, "model_fields_set", set())
    nome = _clean_optional_text(paciente.tutor)
    if "tutor" in campos_enviados and not nome:
        tutor.nome = ""
        tutor.nome_key = ""
    elif nome:
        tutor.nome = nome
        tutor.nome_key = _gerar_nome_key(nome)

    mapping = {
        "telefone": "tutor_telefone",
        "whatsapp": "tutor_whatsapp",
        "email": "tutor_email",
        "cpf": "tutor_cpf",
        "cep": "tutor_cep",
        "endereco": "tutor_endereco",
        "numero": "tutor_numero",
        "complemento": "tutor_complemento",
        "bairro": "tutor_bairro",
        "cidade": "tutor_cidade",
        "estado": "tutor_estado",
    }
    for attr, payload_attr in mapping.items():
        value = _clean_optional_text(getattr(paciente, payload_attr, None))
        if payload_attr in campos_enviados:
            setattr(tutor, attr, value or "")
        elif value:
            setattr(tutor, attr, value)

    if not _clean_optional_text(tutor.whatsapp) and _clean_optional_text(tutor.telefone):
        tutor.whatsapp = _clean_optional_text(tutor.telefone)

    for campo in ("origem_cadastro", "identificacao_observacoes"):
        valor = getattr(paciente, "tutor_" + campo, None)
        if valor is not None:
            setattr(tutor, campo, valor)
    if db is not None:
        rotina_tutor.registrar_edicao_identidade(db, tutor, identidade_antes, current_user)
        if getattr(paciente, "tutor_identificacao_pendente", None) is True and tutor.identificacao_pendente is False:
            rotina_tutor.reabrir_identificacao(db, tutor, current_user, "Revisao solicitada ao complementar o paciente.")
    elif identidade_antes != rotina_tutor.dados_identidade(tutor):
        tutor.identificacao_pendente = True
    tutor.ativo = 1
    tutor.updated_at = _legacy_now_dt()


def _serialize_tutor_fields(tutor: Tutor | None) -> dict[str, Optional[str] | Optional[int]]:
    return {
        "tutor_id": tutor.id if tutor else None,
        "tutor_identificacao_pendente": tutor.identificacao_pendente if tutor else None,
        "tutor_origem_cadastro": tutor.origem_cadastro if tutor else None,
        "tutor_identificacao_observacoes": tutor.identificacao_observacoes if tutor else None,
        "tutor": tutor.nome if tutor and tutor.nome else "",
        "tutor_email": tutor.email if tutor else None,
        "tutor_telefone": tutor.telefone if tutor else None,
        "tutor_whatsapp": tutor.whatsapp if tutor else None,
        "tutor_cpf": tutor.cpf if tutor else None,
        "tutor_cep": tutor.cep if tutor else None,
        "tutor_endereco": tutor.endereco if tutor else None,
        "tutor_numero": tutor.numero if tutor else None,
        "tutor_complemento": tutor.complemento if tutor else None,
        "tutor_bairro": tutor.bairro if tutor else None,
        "tutor_cidade": tutor.cidade if tutor else None,
        "tutor_estado": tutor.estado if tutor else None,
        "tutor_latitude": float(tutor.latitude) if tutor and tutor.latitude is not None else None,
        "tutor_longitude": float(tutor.longitude) if tutor and tutor.longitude is not None else None,
        "tutor_place_id": tutor.place_id if tutor else None,
        "tutor_endereco_normalizado": tutor.endereco_normalizado if tutor else None,
    }


def _obter_ou_criar_tutor(
    db: Session,
    paciente: BaseModel,
    *,
    tutor_id_padrao: Optional[int] = None,
    commit_changes: bool = True,
    current_user=None,
) -> Optional[int]:
    _ensure_tutores_timestamp_columns(db)

    tutor_id = int(getattr(paciente, "tutor_id", None) or tutor_id_padrao or 0)
    if tutor_id > 0:
        tutor = exigir_tutor_utilizavel(db, tutor_id)
        _aplicar_dados_tutor(tutor, paciente, db=db, current_user=current_user)
        if commit_changes:
            db.commit()
        else:
            db.flush()
        return tutor.id

    tutor_nome_raw = paciente.tutor
    if not tutor_nome_raw:
        return None

    tutor_nome = tutor_nome_raw.strip()
    if not tutor_nome:
        return None

    tutor_nome_key = _gerar_nome_key(tutor_nome)
    tutor = Tutor(
        nome=tutor_nome,
        nome_key=tutor_nome_key,
        identificacao_pendente=True,
        origem_cadastro=getattr(paciente, "tutor_origem_cadastro", None),
        identificacao_observacoes=getattr(paciente, "tutor_identificacao_observacoes", None),
        email=_clean_optional_text(paciente.tutor_email) or "",
        telefone=_clean_optional_text(paciente.tutor_telefone) or "",
        whatsapp=(
            _clean_optional_text(paciente.tutor_whatsapp)
            or _clean_optional_text(paciente.tutor_telefone)
            or ""
        ),
        cpf=_clean_optional_text(paciente.tutor_cpf) or "",
        cep=_clean_optional_text(paciente.tutor_cep) or "",
        endereco=_clean_optional_text(paciente.tutor_endereco) or "",
        numero=_clean_optional_text(paciente.tutor_numero) or "",
        complemento=_clean_optional_text(paciente.tutor_complemento) or "",
        bairro=_clean_optional_text(paciente.tutor_bairro) or "",
        cidade=_clean_optional_text(paciente.tutor_cidade) or "",
        estado=_clean_optional_text(paciente.tutor_estado) or "",
        ativo=1,
        created_at=_legacy_now_dt(),
    )
    db.add(tutor)

    try:
        if commit_changes:
            db.commit()
            db.refresh(tutor)
        else:
            db.flush()
        return tutor.id
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Nao foi possivel criar um tutor separado. Verifique a migracao de homonimos.")


def _buscar_paciente_por_chave(
    db: Session,
    *,
    nome_key: str,
    tutor_id: Optional[int],
    especie: str,
):
    query = db.query(Paciente).filter(Paciente.nome_key == nome_key, Paciente.mesclado_em_id.is_(None))

    if tutor_id is None:
        query = query.filter(Paciente.tutor_id.is_(None))
    else:
        query = query.filter(Paciente.tutor_id == tutor_id)

    query = query.filter(func.lower(func.coalesce(Paciente.especie, "")) == especie.lower())
    return query.order_by(Paciente.id.desc()).first()


def _contar_referencias_paciente(db: Session, paciente_id: int) -> dict[str, int]:
    """Conta registros em qualquer tabela que tenha coluna paciente_id."""
    bind = db.get_bind()
    insp = inspect(bind)
    referencias: dict[str, int] = {}

    for tabela in insp.get_table_names():
        if tabela == Paciente.__tablename__:
            continue

        colunas = {col["name"] for col in insp.get_columns(tabela)}
        if "paciente_id" not in colunas:
            continue

        total = db.execute(
            text(f'SELECT COUNT(*) FROM "{tabela}" WHERE paciente_id = :paciente_id'),
            {"paciente_id": paciente_id},
        ).scalar()

        total_int = int(total or 0)
        if total_int > 0:
            referencias[tabela] = total_int

    return referencias


# Schemas
class PacienteCreate(BaseModel):
    nome: str
    chave_operacao: Optional[str] = Field(default=None, min_length=8, max_length=128)
    tutor_id: Optional[int] = Field(default=None, gt=0)
    tutor_identificacao_pendente: Optional[bool] = None
    tutor_origem_cadastro: Optional[str] = None
    tutor_identificacao_observacoes: Optional[str] = None
    tutor: Optional[str] = None
    tutor_email: Optional[str] = None
    tutor_telefone: Optional[str] = None
    tutor_whatsapp: Optional[str] = None
    tutor_cpf: Optional[str] = None
    tutor_cep: Optional[str] = None
    tutor_endereco: Optional[str] = None
    tutor_numero: Optional[str] = None
    tutor_complemento: Optional[str] = None
    tutor_bairro: Optional[str] = None
    tutor_cidade: Optional[str] = None
    tutor_estado: Optional[str] = None
    especie: Optional[str] = None
    raca: Optional[str] = ""
    sexo: Optional[str] = None
    peso_kg: Optional[float] = None
    data_nascimento: Optional[str] = None
    idade: Optional[str] = None
    idade_informada: Optional[str] = None
    idade_referencia: Optional[str] = None
    idade_fonte: Optional[str] = None
    microchip: Optional[str] = ""
    observacoes: Optional[str] = ""


class PacienteUpdate(BaseModel):
    nome: Optional[str] = None
    tutor_id: Optional[int] = Field(default=None, gt=0)
    tutor_identificacao_pendente: Optional[bool] = None
    tutor_origem_cadastro: Optional[str] = None
    tutor_identificacao_observacoes: Optional[str] = None
    tutor: Optional[str] = None
    tutor_email: Optional[str] = None
    tutor_telefone: Optional[str] = None
    tutor_whatsapp: Optional[str] = None
    tutor_cpf: Optional[str] = None
    tutor_cep: Optional[str] = None
    tutor_endereco: Optional[str] = None
    tutor_numero: Optional[str] = None
    tutor_complemento: Optional[str] = None
    tutor_bairro: Optional[str] = None
    tutor_cidade: Optional[str] = None
    tutor_estado: Optional[str] = None
    especie: Optional[str] = None
    raca: Optional[str] = None
    sexo: Optional[str] = None
    peso_kg: Optional[float] = None
    data_nascimento: Optional[str] = None
    idade: Optional[str] = None
    idade_informada: Optional[str] = None
    idade_referencia: Optional[str] = None
    idade_fonte: Optional[str] = None
    microchip: Optional[str] = None
    observacoes: Optional[str] = None


class PacienteResponse(BaseModel):
    idade: str = ""
    data_nascimento: Optional[str] = None
    idade_informada: Optional[str] = None
    idade_referencia: Optional[str] = None
    idade_fonte: Optional[str] = None
    id: int
    nome: str
    tutor_id: Optional[int] = None
    tutor_identificacao_pendente: Optional[bool] = None
    tutor_origem_cadastro: Optional[str] = None
    tutor_identificacao_observacoes: Optional[str] = None
    tutor: str
    tutor_email: Optional[str] = None
    tutor_telefone: Optional[str] = None
    tutor_whatsapp: Optional[str] = None
    especie: Optional[str] = None
    raca: Optional[str] = None
    sexo: Optional[str] = None
    peso_kg: Optional[float] = None


@router.get("")
def listar_pacientes(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    tutor_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista pacientes ativos com nome do tutor."""
    query = (
        db.query(
            Paciente.id,
            Paciente.nome,
            Paciente.tutor_id,
            Paciente.especie,
            Paciente.raca,
            Tutor.nome.label("tutor_nome"),
            Tutor.email.label("tutor_email"),
            Tutor.telefone.label("tutor_telefone"),
            Tutor.whatsapp.label("tutor_whatsapp"),
        )
        .outerjoin(Tutor, Paciente.tutor_id == Tutor.id)
        .filter(_filtro_paciente_ativo())
    )

    # Mantém a métrica da carteira estável enquanto a busca retorna apenas
    # os resultados daquele termo.
    total_ativos = query.count()

    if tutor_id is not None:
        query = query.filter(Paciente.tutor_id == tutor_id)

    if search:
        termo = search.strip()
        termo_key = _gerar_nome_key(termo)
        filtros = [
            Paciente.nome.ilike(f"%{termo}%"),
            Tutor.nome.ilike(f"%{termo}%"),
            cast(Paciente.id, String).ilike(f"%{termo}%"),
            cast(Paciente.tutor_id, String).ilike(f"%{termo}%"),
        ]
        if termo_key:
            filtros.extend(
                [
                    func.coalesce(Paciente.nome_key, "").ilike(f"%{termo_key}%"),
                    func.coalesce(Tutor.nome_key, "").ilike(f"%{termo_key}%"),
                ]
            )
        query = query.filter(or_(*filtros))

    total = query.count()
    items = query.order_by(Paciente.nome.asc(), Paciente.id.asc()).offset(skip).limit(limit).all()

    pacientes = [
        {
            "id": p.id,
            "nome": p.nome,
            "tutor_id": p.tutor_id,
            "tutor": p.tutor_nome or "",
            "tutor_email": p.tutor_email or "",
            "tutor_telefone": p.tutor_telefone or "",
            "tutor_whatsapp": p.tutor_whatsapp or "",
            "especie": (p.especie or "").strip() or "",
            "raca": (p.raca or "").strip() or "",
        }
        for p in items
    ]

    return {"total": total, "total_ativos": total_ativos, "items": pacientes}


@router.post("", response_model=PacienteResponse, status_code=status.HTTP_201_CREATED)
def criar_paciente(
    paciente: PacienteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cria ou reativa um paciente; repeticao segura inclui o tutor criado inline."""
    nome = (paciente.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do paciente e obrigatorio")

    nome_key = _gerar_nome_key(nome)
    especie = (paciente.especie or "").strip()
    # Compatibilidade de schema e anterior a reserva idempotente: nunca efetuar
    # DDL/commit intermediario apos reservar uma operacao.
    _ensure_tutores_timestamp_columns(db)
    try:
        operacao, resposta_salva = rotina_tutor.preparar_operacao(
            db, usuario_id=current_user.id, tipo="criar_paciente", chave=paciente.chave_operacao,
            payload=paciente.model_dump(exclude={"chave_operacao"}),
        )
        if resposta_salva is not None:
            db.rollback()
            return resposta_salva
        tutor_id = _obter_ou_criar_tutor(db, paciente, commit_changes=False, current_user=current_user)
        tutor = db.query(Tutor).filter(Tutor.id == tutor_id).first() if tutor_id else None
        db_paciente = _buscar_paciente_por_chave(db, nome_key=nome_key, tutor_id=tutor_id, especie=especie)
        message = None
        if db_paciente and _is_ativo(db_paciente.ativo):
            message = "Paciente ja existe"
        else:
            if db_paciente:
                message = "Paciente reativado com sucesso"
            else:
                db_paciente = Paciente(created_at=_legacy_now_dt())
                db.add(db_paciente)
            db_paciente.nome = nome
            db_paciente.nome_key = nome_key
            db_paciente.tutor_id = tutor_id
            db_paciente.especie = especie
            db_paciente.raca = paciente.raca
            db_paciente.sexo = normalizar_sexo_paciente(paciente.sexo)
            db_paciente.peso_kg = paciente.peso_kg
            db_paciente.microchip = paciente.microchip
            db_paciente.observacoes = paciente.observacoes
            for key, value in alteracoes_idade(db_paciente, paciente.model_dump(exclude_unset=True)).items():
                setattr(db_paciente, key, value)
            db_paciente.ativo = 1
            db_paciente.updated_at = _legacy_now_dt()
        db.flush()
        resposta = {
            "id": db_paciente.id, "nome": db_paciente.nome,
            **_serialize_tutor_fields(tutor), "especie": db_paciente.especie,
            "raca": db_paciente.raca, "sexo": normalizar_sexo_paciente(db_paciente.sexo),
            "peso_kg": db_paciente.peso_kg,
            **dados_idade_paciente(db_paciente),
        }
        if message:
            resposta["message"] = message
        rotina_tutor.concluir_operacao(operacao, resposta)
        db.commit()
        return resposta
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar paciente: {str(exc)}") from exc


@router.get("/{paciente_id}")
def obter_paciente(
    paciente_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtem detalhes de um paciente."""
    paciente = (
        db.query(Paciente, Tutor)
        .outerjoin(Tutor, Paciente.tutor_id == Tutor.id)
        .filter(Paciente.id == paciente_id)
        .first()
    )

    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

    p, tutor = paciente

    return {
        "id": p.id,
        "nome": p.nome,
        "mesclado_em_id": p.mesclado_em_id,
        **_serialize_tutor_fields(tutor),
        "especie": p.especie,
        "raca": p.raca,
        "sexo": normalizar_sexo_paciente(p.sexo),
        "peso_kg": p.peso_kg,
        **dados_idade_paciente(p),
        "microchip": p.microchip,
        "observacoes": p.observacoes,
    }


@router.get("/{paciente_id}/resumo-clinico")
def obter_resumo_clinico_paciente(
    paciente_id: int,
    limite: int = Query(default=4, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna uma leitura curta do prontuario para a carteira do paciente."""
    _ = current_user
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

    atendimentos_query = db.query(AtendimentoClinico).filter(
        AtendimentoClinico.paciente_id == paciente_id
    )
    total_atendimentos = atendimentos_query.count()
    atendimentos_recentes = (
        atendimentos_query.order_by(
            AtendimentoClinico.data_atendimento.desc(),
            AtendimentoClinico.id.desc(),
        )
        .limit(limite)
        .all()
    )

    laudos_concluidos_query = db.query(Laudo).filter(
        Laudo.paciente_id == paciente_id,
        func.lower(func.trim(func.coalesce(Laudo.status, ""))).in_(LAUDO_STATUSES_CONCLUIDOS),
    )
    total_laudos_concluidos = laudos_concluidos_query.count()
    laudos_recentes = (
        laudos_concluidos_query.order_by(
            func.coalesce(Laudo.data_exame, Laudo.data_laudo, Laudo.created_at).desc(),
            Laudo.id.desc(),
        )
        .limit(limite)
        .all()
    )

    alertas_query = db.query(AlertaClinico).filter(
        AlertaClinico.paciente_id == paciente_id,
        AlertaClinico.ativo == 1,
    )
    total_alertas_ativos = alertas_query.count()
    alertas_ativos = (
        alertas_query.order_by(
            AlertaClinico.data_inicio.desc(),
            AlertaClinico.id.desc(),
        )
        .limit(limite)
        .all()
    )

    return {
        "paciente_id": paciente.id,
        "totais": {
            "atendimentos": total_atendimentos,
            "laudos_concluidos": total_laudos_concluidos,
            "alertas_ativos": total_alertas_ativos,
        },
        "atendimentos_recentes": [
            {
                "id": atendimento.id,
                "data_atendimento": _to_iso(atendimento.data_atendimento),
                "status": atendimento.status or "",
                "queixa_principal": atendimento.queixa_principal or "",
                "diagnostico_principal": atendimento.diagnostico_principal or "",
                "veterinario": atendimento.criado_por_nome or "",
            }
            for atendimento in atendimentos_recentes
        ],
        "laudos_recentes": [
            {
                "id": laudo.id,
                "tipo": laudo.tipo or "",
                "titulo": laudo.titulo or laudo.tipo or "Laudo",
                "status": laudo.status or "",
                "data_exame": _to_iso(laudo.data_exame),
                "data_laudo": _to_iso(laudo.data_laudo or laudo.created_at),
            }
            for laudo in laudos_recentes
        ],
        "alertas_ativos": [
            {
                "id": alerta.id,
                "titulo": alerta.titulo,
                "descricao": alerta.descricao or "",
                "gravidade": alerta.gravidade or "media",
            }
            for alerta in alertas_ativos
        ],
    }


@router.put("/{paciente_id}")
def atualizar_paciente(
    paciente_id: int,
    paciente: PacienteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza um paciente existente."""
    db_paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()

    if not db_paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

    if db_paciente.mesclado_em_id:
        raise HTTPException(409, f"Paciente mesclado. Edite o cadastro principal #{db_paciente.mesclado_em_id}.")

    campos_enviados = paciente.model_fields_set
    nome_atualizado: Optional[str] = None
    if "nome" in campos_enviados:
        nome_atualizado = (paciente.nome or "").strip()
        if not nome_atualizado:
            raise HTTPException(status_code=400, detail="Nome do paciente e obrigatorio")

    if _paciente_tem_payload_tutor(paciente):
        try:
            db_paciente.tutor_id = _obter_ou_criar_tutor(
                db,
                paciente,
                tutor_id_padrao=db_paciente.tutor_id,
                commit_changes=False,
                current_user=current_user,
            )
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Erro ao resolver tutor: {str(e)}")

    if nome_atualizado is not None:
        db_paciente.nome = nome_atualizado
        db_paciente.nome_key = _gerar_nome_key(nome_atualizado)
    if "especie" in campos_enviados:
        db_paciente.especie = paciente.especie
    if "raca" in campos_enviados:
        db_paciente.raca = paciente.raca
    if "sexo" in campos_enviados:
        db_paciente.sexo = normalizar_sexo_paciente(paciente.sexo)
    if "peso_kg" in campos_enviados:
        db_paciente.peso_kg = paciente.peso_kg
    if "microchip" in campos_enviados:
        db_paciente.microchip = paciente.microchip
    age_changes = alteracoes_idade(db_paciente, paciente.model_dump(exclude_unset=True))
    if "observacoes" in campos_enviados:
        db_paciente.observacoes = paciente.observacoes
    for key, value in age_changes.items():
        setattr(db_paciente, key, value)
    db_paciente.updated_at = _legacy_now_dt()

    db.commit()
    db.refresh(db_paciente)
    tutor = db.query(Tutor).filter(Tutor.id == db_paciente.tutor_id).first() if db_paciente.tutor_id else None

    return {
        "id": db_paciente.id,
        "nome": db_paciente.nome,
        **_serialize_tutor_fields(tutor),
        "especie": db_paciente.especie,
        "raca": db_paciente.raca,
        "sexo": normalizar_sexo_paciente(db_paciente.sexo),
        "peso_kg": db_paciente.peso_kg,
        **dados_idade_paciente(db_paciente),
        "microchip": db_paciente.microchip,
        "observacoes": db_paciente.observacoes,
        "message": "Paciente atualizado com sucesso",
    }


@router.get("/{paciente_id}/tutor")
def obter_tutor_paciente(
    paciente_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtem o tutor de um paciente."""
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()

    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

    if not paciente.tutor_id:
        raise HTTPException(status_code=404, detail="Paciente nao tem tutor cadastrado")

    tutor = db.query(Tutor).filter(Tutor.id == paciente.tutor_id).first()

    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor nao encontrado")

    return {
        "id": tutor.id,
        "nome": tutor.nome,
        "telefone": tutor.telefone,
        "whatsapp": tutor.whatsapp,
        "email": tutor.email,
        "cpf": tutor.cpf,
        "cep": tutor.cep,
        "endereco": tutor.endereco,
        "numero": tutor.numero,
        "complemento": tutor.complemento,
        "bairro": tutor.bairro,
        "cidade": tutor.cidade,
        "estado": tutor.estado,
    }


@router.delete("/{paciente_id}")
def deletar_paciente(
    paciente_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove paciente com protecao de integridade para historico."""
    db_paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()

    if not db_paciente:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

    if db_paciente.mesclado_em_id or db.query(Paciente.id).filter(Paciente.mesclado_em_id == paciente_id).first():
        raise HTTPException(409, "Preserve os cadastros vinculados a uma mesclagem no histórico.")

    referencias = _contar_referencias_paciente(db, paciente_id)
    if referencias:
        db_paciente.ativo = 0
        db_paciente.updated_at = _legacy_now_dt()
        db.commit()
        return {
            "message": "Paciente removido com sucesso (desativado por possuir historico vinculado)",
            "mode": "soft_delete",
            "references": referencias,
        }

    try:
        db.delete(db_paciente)
        db.commit()
        return {
            "message": "Paciente removido com sucesso",
            "mode": "hard_delete",
            "references": {},
        }
    except IntegrityError:
        db.rollback()
        db_paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
        if not db_paciente:
            raise HTTPException(status_code=404, detail="Paciente nao encontrado")

        db_paciente.ativo = 0
        db_paciente.updated_at = _legacy_now_dt()
        db.commit()
        return {
            "message": "Paciente removido com sucesso (desativado por integridade de dados)",
            "mode": "soft_delete",
            "references": _contar_referencias_paciente(db, paciente_id),
        }
