"""Servicos de negocio para o modulo fiscal."""
from __future__ import annotations

import logging
import json
from datetime import datetime, time
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, literal, text
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.clinica import Clinica
from app.models.fiscal import FiscalFechamentoOS, NotaFiscal, RelatorioFiscalEmissao
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.schemas.fiscal import NotaFiscalCreate, NotaFiscalUpdate

logger = logging.getLogger(__name__)
_MAX_NUMERO_GENERATION_ATTEMPTS = 5
FISCAL_TIMEZONE = ZoneInfo("America/Fortaleza")

_CAMPOS_FISCAIS_CLINICA_OBRIGATORIOS = (
    (("razao_social", "nome", "clinica_razao_social", "clinica_nome"), "razao/nome"),
    (("cnpj", "clinica_cnpj"), "cnpj"),
    (("endereco", "clinica_endereco"), "logradouro"),
    (("bairro", "clinica_bairro"), "bairro"),
    (("cidade", "clinica_cidade"), "cidade"),
    (("estado", "clinica_estado"), "estado"),
    (("cep", "clinica_cep"), "cep"),
    (("telefone", "clinica_telefone"), "telefone"),
)


def _now_str() -> str:
    return datetime.now(FISCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def campos_fiscais_pendentes_da_clinica(item: Mapping[str, Any]) -> list[str]:
    """Retorna os campos cadastrais mínimos exigidos para exportar um tomador PJ."""
    faltando: list[str] = []
    for keys, label in _CAMPOS_FISCAIS_CLINICA_OBRIGATORIOS:
        if not any(str(item.get(key) or "").strip() for key in keys):
            faltando.append(label)
    return faltando


def detalhes_fiscais_da_clinica(item: Mapping[str, Any]) -> dict:
    faltando = campos_fiscais_pendentes_da_clinica(item)
    return {
        "dados_fiscais_completos": not faltando,
        "campos_fiscais_pendentes": faltando,
    }


def _calcular_valores(valor_servico: float, valor_desconto: float, aliquota_iss: float) -> tuple[float, float]:
    """Calcula valor final e valor ISS."""
    valor_final = max(0, valor_servico - valor_desconto)
    valor_iss = round(valor_final * (aliquota_iss / 100), 2)
    return valor_final, valor_iss


def _gerar_numero(db: Session) -> str:
    """Gera proximo numero sequencial de NF no formato NFO-YYYY-NNNNN."""
    try:
        return _gerar_numero_por_sequencia(db)
    except (ProgrammingError, OperationalError) as exc:
        # Compatibilidade para ambientes sem migracao FOR-23 aplicada.
        db.rollback()
        if _is_missing_sequence_table_error(exc):
            return _gerar_numero_legado(db)
        raise


def _gerar_numero_por_sequencia(db: Session) -> str:
    ano = datetime.now().year
    now = _now_str()
    row = db.execute(
        text(
            """
            INSERT INTO fiscal_numero_sequencias (ano, ultimo_numero, updated_at)
            VALUES (:ano, 1, :updated_at)
            ON CONFLICT (ano) DO UPDATE
            SET
                ultimo_numero = ultimo_numero + 1,
                updated_at = :updated_at
            RETURNING ultimo_numero
            """
        ),
        {"ano": ano, "updated_at": now},
    ).fetchone()
    if not row or row[0] is None:
        raise RuntimeError("Falha ao obter proximo numero fiscal da sequencia.")
    return f"NFO-{ano}-{int(row[0]):05d}"


def _gerar_numero_legado(db: Session) -> str:
    ano = datetime.now().year
    result = db.execute(
        text(
            "SELECT numero FROM notas_fiscais "
            "WHERE numero LIKE :prefix ORDER BY id DESC LIMIT 1"
        ),
        {"prefix": f"NFO-{ano}-%"},
    ).fetchone()

    if result and result[0]:
        try:
            ultimo = int(result[0].split("-")[-1])
            proximo = ultimo + 1
        except (ValueError, IndexError):
            proximo = 1
    else:
        proximo = 1

    return f"NFO-{ano}-{proximo:05d}"


def _is_missing_sequence_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "fiscal_numero_sequencias" in message and (
        "does not exist" in message
        or "undefinedtable" in message
        or "no such table" in message
    )


def _is_unique_numero_violation(exc: Exception) -> bool:
    message = str(exc).lower()
    return "uq_notas_fiscais_numero" in message or "notas_fiscais.numero" in message


def criar_nota_fiscal(db: Session, data: NotaFiscalCreate) -> NotaFiscal:
    """Cria uma nova nota fiscal a partir dos dados fornecidos."""
    valor_final, valor_iss = _calcular_valores(
        data.valor_servico, data.valor_desconto, data.aliquota_iss
    )
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_NUMERO_GENERATION_ATTEMPTS + 1):
        numero = _gerar_numero(db)
        nota = NotaFiscal(
            numero=numero,
            serie="1",
            os_id=data.os_id,
            tipo_cliente=data.tipo_cliente,
            cliente_nome=data.cliente_nome,
            cliente_documento=data.cliente_documento,
            cliente_endereco=data.cliente_endereco or "",
            cliente_bairro=data.cliente_bairro or "",
            cliente_cidade=data.cliente_cidade or "",
            cliente_estado=data.cliente_estado or "",
            cliente_cep=data.cliente_cep or "",
            cliente_telefone=data.cliente_telefone or "",
            cliente_email=data.cliente_email or "",
            valor_servico=data.valor_servico,
            valor_desconto=data.valor_desconto,
            valor_final=valor_final,
            aliquota_iss=data.aliquota_iss,
            valor_iss=valor_iss,
            atividade_cnae=data.atividade_cnae or "",
            descricao_servico=data.descricao_servico or "",
            observacoes=data.observacoes or "",
            natureza_operacao=data.natureza_operacao,
            status="rascunho",
            created_at=_now_str(),
        )
        db.add(nota)
        try:
            db.flush()
            db.commit()
            db.refresh(nota)
            logger.info("[Fiscal] Nota fiscal criada: %s", nota.numero)
            return nota
        except IntegrityError as exc:
            db.rollback()
            if _is_unique_numero_violation(exc):
                last_exc = exc
                logger.warning(
                    "[Fiscal] Colisao de numero fiscal (%s). Tentativa %s/%s.",
                    numero,
                    attempt,
                    _MAX_NUMERO_GENERATION_ATTEMPTS,
                )
                continue
            raise

    raise ValueError(
        "Nao foi possivel gerar numero fiscal unico apos multiplas tentativas."
    ) from last_exc


def atualizar_nota_fiscal(
    db: Session, nota_id: int, data: NotaFiscalUpdate
) -> Optional[NotaFiscal]:
    """Atualiza uma nota fiscal existente."""
    nota = db.query(NotaFiscal).filter(NotaFiscal.id == nota_id).first()
    if not nota:
        return None

    update = data.model_dump(exclude_unset=True)

    # Se valores mudaram, recalcula.
    if "valor_servico" in update or "valor_desconto" in update or "aliquota_iss" in update:
        vs = update.get("valor_servico", float(nota.valor_servico or 0))
        vd = update.get("valor_desconto", float(nota.valor_desconto or 0))
        ai = update.get("aliquota_iss", nota.aliquota_iss or 5.0)
        vf, vi = _calcular_valores(vs, vd, ai)
        update["valor_final"] = vf
        update["valor_iss"] = vi

    for key, value in update.items():
        setattr(nota, key, value)

    nota.updated_at = _now_str()
    db.commit()
    db.refresh(nota)
    logger.info("[Fiscal] Nota fiscal atualizada: %s", nota.numero)
    return nota


def excluir_nota_fiscal(db: Session, nota_id: int) -> bool:
    """Exclui uma nota fiscal (soft-delete via status)."""
    nota = db.query(NotaFiscal).filter(NotaFiscal.id == nota_id).first()
    if not nota:
        return False
    nota.status = "cancelado"
    nota.updated_at = _now_str()
    db.commit()
    logger.info("[Fiscal] Nota fiscal cancelada: %s", nota.numero)
    return True


def buscar_nota_fiscal(db: Session, nota_id: int) -> Optional[NotaFiscal]:
    """Busca uma nota fiscal pelo ID."""
    return db.query(NotaFiscal).filter(NotaFiscal.id == nota_id).first()


def listar_notas_fiscais(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    tipo_cliente: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
) -> tuple[list[NotaFiscal], int]:
    """Lista notas fiscais com filtros."""
    query = db.query(NotaFiscal)

    if status:
        query = query.filter(NotaFiscal.status == status)
    if tipo_cliente:
        query = query.filter(NotaFiscal.tipo_cliente == tipo_cliente)
    if data_inicio:
        query = query.filter(NotaFiscal.created_at >= data_inicio)
    if data_fim:
        query = query.filter(NotaFiscal.created_at <= data_fim)

    total = query.count()
    items = query.order_by(NotaFiscal.created_at.desc()).offset(skip).limit(limit).all()
    return items, total


def marcar_exportada(
    db: Session, nota_id: int, formato: str
) -> Optional[NotaFiscal]:
    """Marca nota fiscal como exportada e registra o formato."""
    nota = db.query(NotaFiscal).filter(NotaFiscal.id == nota_id).first()
    if not nota:
        return None
    nota.status = "exportado"
    nota.formato_exportado = formato
    nota.updated_at = _now_str()
    db.commit()
    db.refresh(nota)
    return nota


def buscar_clinicas_com_os(
    db: Session,
    data_inicio: str,
    data_fim: str,
    somente_completas: bool = False,
) -> list[dict]:
    """Lista clinicas ativas que tiveram OS por data de atendimento no periodo."""
    dt_inicio = _parse_date_start(data_inicio)
    dt_fim = _parse_date_end(data_fim)
    if not dt_inicio or not dt_fim:
        raise ValueError("Periodo invalido.")
    if dt_inicio > dt_fim:
        raise ValueError("data_inicio nao pode ser maior que data_fim.")

    rows = (
        db.query(
            Clinica.id,
            Clinica.nome,
            Clinica.razao_social,
            Clinica.cnpj,
            Clinica.telefone,
            Clinica.email,
            Clinica.atividade_cnae,
            Clinica.endereco,
            Clinica.numero,
            Clinica.complemento,
            Clinica.bairro,
            Clinica.cidade,
            Clinica.estado,
            Clinica.cep,
            func.count(OrdemServico.id).label("qtd_os"),
            func.coalesce(func.sum(OrdemServico.valor_final), 0).label("valor_total"),
        )
        .join(OrdemServico, OrdemServico.clinica_id == Clinica.id)
        .filter(Clinica.ativo == True)
        .filter(OrdemServico.data_atendimento >= dt_inicio)
        .filter(OrdemServico.data_atendimento <= dt_fim)
        .filter(func.lower(func.trim(func.coalesce(OrdemServico.status, ""))) != "cancelado")
        .group_by(
            Clinica.id,
            Clinica.nome,
            Clinica.razao_social,
            Clinica.cnpj,
            Clinica.telefone,
            Clinica.email,
            Clinica.atividade_cnae,
            Clinica.endereco,
            Clinica.numero,
            Clinica.complemento,
            Clinica.bairro,
            Clinica.cidade,
            Clinica.estado,
            Clinica.cep,
        )
        .order_by(Clinica.nome.asc())
        .all()
    )

    items = [
        {
            "id": row.id,
            "nome": row.nome,
            "razao_social": row.razao_social,
            "cnpj": row.cnpj,
            "telefone": row.telefone,
            "email": row.email,
            "atividade_cnae": row.atividade_cnae,
            "endereco": row.endereco,
            "numero": row.numero,
            "complemento": row.complemento,
            "bairro": row.bairro,
            "cidade": row.cidade,
            "estado": row.estado,
            "cep": row.cep,
            "qtd_os": int(row.qtd_os or 0),
            "valor_total": float(row.valor_total or 0),
        }
        for row in rows
    ]
    for item in items:
        item.update(detalhes_fiscais_da_clinica(item))
    if somente_completas:
        items = [item for item in items if item["dados_fiscais_completos"]]
    return items


def listar_clinicas_invalidas_para_exportacao(os_items: list[dict]) -> list[dict]:
    """Agrupa as OS por clínica e aplica a mesma regra da lista de elegibilidade."""
    clinica_por_id: dict[str, dict] = {}
    for item in os_items:
        clinica_id = str(item.get("clinica_id") or item.get("clinica_nome") or "sem-clinica")
        clinica_por_id.setdefault(clinica_id, item)

    invalidas: list[dict] = []
    for row in clinica_por_id.values():
        faltando = campos_fiscais_pendentes_da_clinica(row)
        if faltando:
            invalidas.append(
                {
                    "clinica_id": row.get("clinica_id"),
                    "clinica_nome": row.get("clinica_nome") or "Clinica sem nome",
                    "faltando": faltando,
                }
            )
    return invalidas


def registrar_emissao_relatorio_fiscal(
    db: Session,
    *,
    os_items: list[dict],
    formato: str,
    modo_multiclinica: bool,
    tipo_emissao: str,
    data_inicio: Optional[str],
    data_fim: Optional[str],
    descricao_servico: Optional[str],
    arquivo_nome: str,
    usuario_id: Optional[int],
    usuario_nome: Optional[str],
) -> RelatorioFiscalEmissao:
    """Registra a emissão depois de gerar o arquivo para manter a trilha auditável."""
    clinicas: dict[str, dict] = {}
    for item in os_items:
        clinica_id = item.get("clinica_id")
        key = str(clinica_id if clinica_id is not None else "sem-clinica")
        atual = clinicas.setdefault(
            key,
            {
                "clinica_id": clinica_id,
                "nome": item.get("clinica_nome") or "Atendimento sem clinica",
                "quantidade_os": 0,
                "valor_total": 0.0,
            },
        )
        atual["quantidade_os"] += 1
        atual["valor_total"] = round(atual["valor_total"] + float(item.get("valor_final") or 0), 2)

    emissao = RelatorioFiscalEmissao(
        formato=formato,
        modo="multiclinica" if modo_multiclinica else "uma_clinica",
        tipo_emissao=tipo_emissao,
        data_inicio=data_inicio or None,
        data_fim=data_fim or None,
        quantidade_os=len(os_items),
        valor_total=round(sum(float(item.get("valor_final") or 0) for item in os_items), 2),
        clinicas_json=json.dumps(list(clinicas.values()), ensure_ascii=False),
        os_ids_json=json.dumps([item["os_id"] for item in os_items if item.get("os_id") is not None]),
        descricao_servico=(descricao_servico or "").strip() or None,
        arquivo_nome=arquivo_nome,
        usuario_id=usuario_id,
        usuario_nome=(usuario_nome or "").strip() or None,
        emitido_em=_now_str(),
    )
    db.add(emissao)
    db.commit()
    db.refresh(emissao)
    return emissao


def listar_emissoes_relatorios_fiscais(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 20,
    clinica_id: Optional[int] = None,
) -> tuple[list[dict], int]:
    query = db.query(RelatorioFiscalEmissao)
    if clinica_id is not None:
        # A coluna e JSON textual por compatibilidade SQLite/PostgreSQL; a busca é feita
        # após desserializar para evitar depender de funções JSON específicas do banco.
        rows = query.order_by(RelatorioFiscalEmissao.emitido_em.desc(), RelatorioFiscalEmissao.id.desc()).all()
        items = [_serializar_emissao_relatorio_fiscal(row) for row in rows]
        items = [
            item
            for item in items
            if any(clinica.get("clinica_id") == clinica_id for clinica in item["clinicas"])
        ]
        return items[skip : skip + limit], len(items)

    total = query.count()
    rows = (
        query.order_by(RelatorioFiscalEmissao.emitido_em.desc(), RelatorioFiscalEmissao.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_serializar_emissao_relatorio_fiscal(row) for row in rows], total


def _serializar_emissao_relatorio_fiscal(emissao: RelatorioFiscalEmissao) -> dict:
    try:
        clinicas = json.loads(emissao.clinicas_json or "[]")
    except (TypeError, json.JSONDecodeError):
        clinicas = []
    return {
        "id": emissao.id,
        "formato": emissao.formato,
        "modo": emissao.modo,
        "tipo_emissao": emissao.tipo_emissao,
        "data_inicio": emissao.data_inicio,
        "data_fim": emissao.data_fim,
        "quantidade_os": int(emissao.quantidade_os or 0),
        "valor_total": float(emissao.valor_total or 0),
        "clinicas": clinicas if isinstance(clinicas, list) else [],
        "descricao_servico": emissao.descricao_servico,
        "arquivo_nome": emissao.arquivo_nome,
        "usuario_nome": emissao.usuario_nome,
        "emitido_em": emissao.emitido_em,
    }


def buscar_os_para_fiscal(
    db: Session,
    search: Optional[str] = None,
    clinica_id: Optional[int] = None,
    clinica_ids: Optional[list[int]] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """Busca OS para exportacao fiscal com filtros opcionais."""
    query = _build_os_query(db)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Tutor.nome.ilike(search_term))
            | (Paciente.nome.ilike(search_term))
            | (Clinica.nome.ilike(search_term))
            | (Servico.nome.ilike(search_term))
            | (OrdemServico.numero_os.ilike(search_term))
        )

    if clinica_id is not None:
        query = query.filter(OrdemServico.clinica_id == clinica_id)
    if clinica_ids:
        query = query.filter(OrdemServico.clinica_id.in_(clinica_ids))
    dt_inicio = _parse_date_start(data_inicio)
    dt_fim = _parse_date_end(data_fim)
    if dt_inicio:
        query = query.filter(OrdemServico.data_atendimento >= dt_inicio)
    if dt_fim:
        query = query.filter(OrdemServico.data_atendimento <= dt_fim)

    total = query.count()
    rows = (
        query.order_by(OrdemServico.data_atendimento.desc(), OrdemServico.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_serialize_os_row(r) for r in rows], total


def buscar_os_por_ids_para_exportacao(db: Session, os_ids: list[int]) -> list[dict]:
    """Retorna OS especificas para exportacao contabil, preservando ordem de entrada."""
    if not os_ids:
        return []
    if any(type(os_id) is not int or os_id <= 0 for os_id in os_ids) or len(set(os_ids)) != len(os_ids):
        raise ValueError("Selecione OS únicas com IDs positivos.")
    db.query(OrdemServico.id).filter(OrdemServico.id.in_(os_ids)).order_by(OrdemServico.id.asc()).with_for_update().all()
    claims = db.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.os_id.in_(os_ids)).all()
    if claims:
        pacotes = ", ".join(str(value) for value in sorted({row.fechamento_id for row in claims}))
        raise ValueError(f"Há OS já incluídas nos pacotes {pacotes}. Baixe a segunda via do fechamento original.")

    rows = (
        _build_os_query(db)
        .filter(OrdemServico.id.in_(os_ids))
        .order_by(OrdemServico.data_atendimento.desc(), OrdemServico.id.desc())
        .all()
    )
    serialized = [_serialize_os_row(r) for r in rows]
    by_id = {item["os_id"]: item for item in serialized}
    return [by_id[oid] for oid in os_ids if oid in by_id]


def _build_os_query(db: Session):
    tutor_cpf_col = _optional_model_column(Tutor, "cpf", "").label("tutor_cpf")
    return (
        db.query(
            OrdemServico.id.label("os_id"),
            OrdemServico.numero_os,
            OrdemServico.data_atendimento,
            OrdemServico.valor_servico,
            OrdemServico.desconto,
            OrdemServico.valor_final,
            OrdemServico.status.label("status_os"),
            OrdemServico.clinica_id,
            OrdemServico.origem_atendimento,
            Paciente.nome.label("paciente_nome"),
            Tutor.nome.label("tutor_nome"),
            tutor_cpf_col,
            Clinica.nome.label("clinica_nome"),
            Clinica.razao_social.label("clinica_razao_social"),
            Clinica.cnpj.label("clinica_cnpj"),
            Clinica.atividade_cnae.label("clinica_atividade_cnae"),
            Clinica.endereco.label("clinica_endereco"),
            Clinica.numero.label("clinica_numero"),
            Clinica.bairro.label("clinica_bairro"),
            Clinica.cidade.label("clinica_cidade"),
            Clinica.estado.label("clinica_estado"),
            Clinica.cep.label("clinica_cep"),
            Clinica.telefone.label("clinica_telefone"),
            Clinica.email.label("clinica_email"),
            Servico.nome.label("servico_nome"),
        )
        .outerjoin(Paciente, Paciente.id == OrdemServico.paciente_id)
        .outerjoin(Tutor, Tutor.id == Paciente.tutor_id)
        .outerjoin(Clinica, Clinica.id == OrdemServico.clinica_id)
        .outerjoin(Servico, Servico.id == OrdemServico.servico_id)
        .filter(func.lower(func.trim(func.coalesce(OrdemServico.status, ""))) != "cancelado")
    )


def _serialize_os_row(row) -> dict:
    tipo_cliente = "PJ" if row.clinica_id else "PF"
    clinica_nome_exibicao = row.clinica_nome
    if not clinica_nome_exibicao and str(getattr(row, "origem_atendimento", None) or "").strip().lower() == "domiciliar":
        clinica_nome_exibicao = "Atendimento domiciliar"
    cliente_nome = row.clinica_razao_social or row.clinica_nome or row.tutor_nome or row.paciente_nome or ""
    cliente_documento = row.clinica_cnpj or row.tutor_cpf or ""

    return {
        "os_id": row.os_id,
        "numero_os": row.numero_os,
        "data_atendimento": row.data_atendimento.isoformat() if row.data_atendimento else None,
        "valor_servico": float(row.valor_servico or 0),
        "valor_desconto": float(row.desconto or 0),
        "valor_final": float(row.valor_final or 0),
        "status_os": row.status_os,
        "tipo_cliente": tipo_cliente,
        "cliente_nome": cliente_nome,
        "cliente_documento": cliente_documento,
        "paciente_nome": row.paciente_nome or "",
        "tutor_nome": row.tutor_nome or "",
        "servico_nome": row.servico_nome or "",
        "clinica_id": row.clinica_id,
        "clinica_nome": clinica_nome_exibicao,
        "clinica_razao_social": row.clinica_razao_social,
        "clinica_cnpj": row.clinica_cnpj,
        "clinica_atividade_cnae": row.clinica_atividade_cnae,
        "clinica_endereco": row.clinica_endereco,
        "clinica_numero": row.clinica_numero,
        "clinica_bairro": row.clinica_bairro,
        "clinica_cidade": row.clinica_cidade,
        "clinica_estado": row.clinica_estado,
        "clinica_cep": row.clinica_cep,
        "clinica_telefone": row.clinica_telefone,
        "clinica_email": row.clinica_email,
        "origem_atendimento": row.origem_atendimento,
    }


def _optional_model_column(model, column_name: str, default_value: str):
    column = getattr(model, column_name, None)
    if column is None:
        return literal(default_value)
    return column


def _parse_date_start(value: Optional[str]) -> Optional[datetime]:
    date_obj = _parse_date(value)
    if not date_obj:
        return None
    return datetime.combine(date_obj, time.min)


def _parse_date_end(value: Optional[str]) -> Optional[datetime]:
    date_obj = _parse_date(value)
    if not date_obj:
        return None
    return datetime.combine(date_obj, time.max)


def _parse_date(value: Optional[str]):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None
