"""Endpoints REST para o modulo fiscal."""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictInt, field_validator
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.fiscal import (
    CNPJConsultaResponse,
    FiscalFechamentoCreate,
    FiscalRotinaPreferenciaUpdate,
    FiscalRotinaPrepararRequest,
    FiscalAndamentoUpdate,
    NotaFiscalCreate,
    NotaFiscalListResponse,
    NotaFiscalResponse,
    NotaFiscalUpdate,
    RelatorioFiscalEmissaoListResponse,
    RelatorioFiscalEmissaoResponse,
)
from app.services import cnpj_consulta, fiscal_export_service, fiscal_fechamento_service, fiscal_rotina_service
from app.services.fiscal_service import (
    atualizar_nota_fiscal,
    buscar_clinicas_com_os,
    buscar_nota_fiscal,
    buscar_os_para_fiscal,
    buscar_os_por_ids_para_exportacao,
    criar_nota_fiscal,
    excluir_nota_fiscal,
    listar_clinicas_invalidas_para_exportacao,
    listar_emissoes_relatorios_fiscais,
    listar_notas_fiscais,
    marcar_exportada,
    registrar_emissao_relatorio_fiscal,
)


class ExportarLoteRequest(BaseModel):
    nota_ids: list[int]
    formato: str = Field(..., pattern="^(pdf|csv|xlsx)$")


class DadosTomadorExportacao(BaseModel):
    tipo_cliente: str = Field(default="PJ", pattern="^(PF|PJ)$")
    cliente_nome: Optional[str] = None
    cliente_documento: Optional[str] = None
    cliente_endereco: Optional[str] = None
    cliente_bairro: Optional[str] = None
    cliente_cidade: Optional[str] = None
    cliente_estado: Optional[str] = None
    cliente_cep: Optional[str] = None
    cliente_telefone: Optional[str] = None
    cliente_email: Optional[str] = None
    atividade_cnae: Optional[str] = None
    descricao_servico: Optional[str] = None
    natureza_operacao: Optional[str] = None
    aliquota_iss: Optional[float] = None
    data_referencia_nf: Optional[str] = None


class ExportarOSLoteRequest(BaseModel):
    os_ids: list[StrictInt] = Field(..., min_length=1, max_length=2000)
    formato: str = Field(..., pattern="^(pdf|csv|xlsx)$")
    dados_tomador: Optional[DadosTomadorExportacao] = None
    modo_multiclinica: bool = False
    tipo_emissao: Literal["fechamento_periodo", "por_servico"] = "fechamento_periodo"
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None

    @field_validator("os_ids")
    @classmethod
    def validar_os_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise ValueError("Selecione OS únicas com IDs positivos.")
        return values


router = APIRouter(dependencies=[Depends(get_current_user)])


def _resposta_pacote(fechamento):
    return StreamingResponse(
        iter([fechamento.pacote_bytes]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{fechamento.arquivo_nome}"',
            "X-Fechamento-Id": str(fechamento.id),
            "X-Content-SHA256": fechamento.checksum,
        },
    )


@router.get("/rotinas")
def listar_rotinas(db: Session = Depends(get_db)):
    return fiscal_rotina_service.listar_rotinas(db)


@router.put("/rotinas/clinicas/{clinica_id}")
def atualizar_rotina_clinica(
    clinica_id: int,
    body: FiscalRotinaPreferenciaUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return fiscal_rotina_service.atualizar_preferencia(db, clinica_id, **body.model_dump(), usuario_id=current_user.id, usuario_nome=current_user.nome)
    except fiscal_rotina_service.FiscalRotinaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/rotinas/previa")
def previa_rotina(
    competencia: str = Query(...),
    modo: Literal["semanal", "por_servico", "mensal"] = Query("semanal"),
    data_corte: Optional[str] = Query(None),
    clinica_id: Optional[int] = Query(None, gt=0),
    db: Session = Depends(get_db),
):
    try:
        return fiscal_rotina_service.previa_rotina(db, competencia, modo, data_corte, clinica_id)
    except fiscal_rotina_service.FiscalRotinaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/rotinas/preparar")
def preparar_rotina(
    body: FiscalRotinaPrepararRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        pacote = fiscal_rotina_service.preparar_rotina(db, **body.model_dump(), usuario_id=current_user.id, usuario_nome=current_user.nome)
        return _resposta_pacote(pacote)
    except fiscal_rotina_service.FiscalRotinaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/fechamentos/{fechamento_id}/andamentos")
def listar_andamentos(fechamento_id: int, db: Session = Depends(get_db)):
    try:
        return fiscal_rotina_service.listar_andamentos(db, fechamento_id)
    except fiscal_rotina_service.FiscalRotinaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/os/{os_id}/andamento")
def atualizar_andamento(
    os_id: int,
    body: FiscalAndamentoUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return fiscal_rotina_service.atualizar_andamento(db, os_id, **body.model_dump(), usuario_id=current_user.id, usuario_nome=current_user.nome)
    except fiscal_rotina_service.FiscalRotinaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/fechamentos/previa")
def previa_fechamento(competencia: str = Query(...), db: Session = Depends(get_db)):
    try:
        return fiscal_fechamento_service.previa_fechamento(db, competencia)
    except fiscal_fechamento_service.FiscalFechamentoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/fechamentos")
def preparar_fechamento(
    body: FiscalFechamentoCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        fechamento = fiscal_fechamento_service.preparar_fechamento(
            db, **body.model_dump(), usuario_id=current_user.id, usuario_nome=current_user.nome
        )
        return _resposta_pacote(fechamento)
    except fiscal_fechamento_service.FiscalFechamentoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/fechamentos")
def listar_fechamentos(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    competencia: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    try:
        return fiscal_fechamento_service.listar_fechamentos(db, skip=skip, limit=limit, competencia=competencia)
    except fiscal_fechamento_service.FiscalFechamentoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/fechamentos/{fechamento_id}/download")
def baixar_fechamento(fechamento_id: int, db: Session = Depends(get_db)):
    try:
        return _resposta_pacote(fiscal_fechamento_service.buscar_fechamento(db, fechamento_id))
    except fiscal_fechamento_service.FiscalFechamentoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/consulta-cnpj/{cnpj}", response_model=CNPJConsultaResponse)
def consultar_cnpj(cnpj: str):
    """
    Consulta dados de empresa pelo CNPJ usando a API Receita WS.
    Retorna razao social, endereco, telefone, email, CNAE, etc.
    """
    return cnpj_consulta.consultar_cnpj(cnpj)


@router.get("/clinicas-com-os")
def listar_clinicas_com_os(
    data_inicio: str = Query(...),
    data_fim: str = Query(...),
    somente_completas: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Lista clínicas ativas com OS no período e a situação de seu cadastro fiscal."""
    try:
        items = buscar_clinicas_com_os(
            db,
            data_inicio=data_inicio,
            data_fim=data_fim,
            somente_completas=somente_completas is True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"total": len(items), "items": items}


@router.get("/relatorios-emissoes", response_model=RelatorioFiscalEmissaoListResponse)
def listar_historico_relatorios(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    clinica_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Lista o histórico auditável de relatórios contábeis já exportados."""
    items, total = listar_emissoes_relatorios_fiscais(
        db,
        skip=skip,
        limit=limit,
        clinica_id=clinica_id,
    )
    return RelatorioFiscalEmissaoListResponse(
        total=total,
        items=[RelatorioFiscalEmissaoResponse(**item) for item in items],
    )


@router.get("/notas-fiscais", response_model=NotaFiscalListResponse)
def listar_notas(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    tipo_cliente: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Lista notas fiscais com filtros opcionais."""
    items, total = listar_notas_fiscais(
        db,
        skip=skip,
        limit=limit,
        status=status,
        tipo_cliente=tipo_cliente,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )
    return NotaFiscalListResponse(
        total=total,
        items=[NotaFiscalResponse.model_validate(n) for n in items],
    )


@router.post("/notas-fiscais", response_model=NotaFiscalResponse, status_code=201)
def criar_nota(
    data: NotaFiscalCreate,
    db: Session = Depends(get_db),
):
    """Cria uma nova nota fiscal. Dados sao pre-preenchidos a partir de OS vinculada."""
    try:
        nota = criar_nota_fiscal(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return NotaFiscalResponse.model_validate(nota)


@router.get("/notas-fiscais/{nota_id}", response_model=NotaFiscalResponse)
def buscar_nota(
    nota_id: int,
    db: Session = Depends(get_db),
):
    """Busca uma nota fiscal pelo ID."""
    nota = buscar_nota_fiscal(db, nota_id)
    if not nota:
        raise HTTPException(status_code=404, detail="Nota fiscal nao encontrada.")
    return NotaFiscalResponse.model_validate(nota)


@router.patch("/notas-fiscais/{nota_id}", response_model=NotaFiscalResponse)
def atualizar_nota(
    nota_id: int,
    data: NotaFiscalUpdate,
    db: Session = Depends(get_db),
):
    """Atualiza uma nota fiscal existente."""
    nota = atualizar_nota_fiscal(db, nota_id, data)
    if not nota:
        raise HTTPException(status_code=404, detail="Nota fiscal nao encontrada.")
    return NotaFiscalResponse.model_validate(nota)


@router.delete("/notas-fiscais/{nota_id}", status_code=204)
def excluir_nota(
    nota_id: int,
    db: Session = Depends(get_db),
):
    """Exclui (cancela) uma nota fiscal."""
    if not excluir_nota_fiscal(db, nota_id):
        raise HTTPException(status_code=404, detail="Nota fiscal nao encontrada.")


@router.get("/os-para-fiscal")
def listar_os_para_fiscal(
    search: Optional[str] = Query(None),
    clinica_id: Optional[int] = Query(None),
    clinica_ids: Optional[list[int]] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Lista OS disponiveis para exportacao fiscal.
    Permite filtrar por clinica e periodo, excluindo OS canceladas.
    """
    items, total = buscar_os_para_fiscal(
        db,
        search=search,
        clinica_id=clinica_id,
        clinica_ids=clinica_ids,
        data_inicio=data_inicio,
        data_fim=data_fim,
        skip=skip,
        limit=limit,
    )
    return {"total": total, "items": items}


@router.get("/notas-fiscais/{nota_id}/exportar/{formato}")
def exportar_nota(
    nota_id: int,
    formato: str,
    db: Session = Depends(get_db),
):
    """
    Exporta uma nota fiscal individual no formato especificado.
    Retorna arquivo para download.
    """
    nota = buscar_nota_fiscal(db, nota_id)
    if not nota:
        raise HTTPException(status_code=404, detail="Nota fiscal nao encontrada.")

    if formato == "pdf":
        content, filename = fiscal_export_service.exportar_pdf([nota], db)
        media_type = "application/pdf"
    elif formato == "csv":
        content, filename = fiscal_export_service.exportar_csv([nota], db)
        media_type = "text/csv; charset=utf-8"
    else:
        content, filename = fiscal_export_service.exportar_xlsx([nota], db)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    marcar_exportada(db, nota_id, formato)

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/notas-fiscais/exportar-lote")
def exportar_lote(
    body: ExportarLoteRequest,
    db: Session = Depends(get_db),
):
    """
    Exporta multiplas notas fiscais em lote no formato especificado.
    Retorna arquivo para download.
    """
    notas = [buscar_nota_fiscal(db, nid) for nid in body.nota_ids]
    notas = [n for n in notas if n is not None]

    if not notas:
        raise HTTPException(status_code=400, detail="Nenhuma nota fiscal encontrada.")

    if body.formato == "pdf":
        content, filename = fiscal_export_service.exportar_pdf(notas, db)
        media_type = "application/pdf"
    elif body.formato == "csv":
        content, filename = fiscal_export_service.exportar_csv(notas, db)
        media_type = "text/csv; charset=utf-8"
    else:
        content, filename = fiscal_export_service.exportar_xlsx(notas, db)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    for nota in notas:
        marcar_exportada(db, nota.id, body.formato)

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/os/exportar-lote")
def exportar_os_lote(
    body: Annotated[ExportarOSLoteRequest, Body(...)],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Exporta dados de OS para contabilidade sem gerar nota fiscal.
    Aceita exportacao em lote com multiplas OS selecionadas.
    """
    try:
        os_items = buscar_os_por_ids_para_exportacao(db, body.os_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not os_items:
        raise HTTPException(status_code=400, detail="Nenhuma OS valida encontrada para exportacao.")
    if len(os_items) != len(body.os_ids):
        raise HTTPException(status_code=422, detail="A seleção contém OS inexistentes ou canceladas. Nenhum arquivo foi exportado.")
    dados_tomador = body.dados_tomador.model_dump(exclude_none=True) if body.dados_tomador else None

    if body.modo_multiclinica:
        clinicas_invalidas = listar_clinicas_invalidas_para_exportacao(os_items)
        if clinicas_invalidas:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Existem clinicas com dados incompletos para exportacao.",
                    "clinicas": clinicas_invalidas,
                },
            )
        if dados_tomador:
            # No modo multiclinica os dados cadastrais do tomador vem de cada clinica.
            # Mantemos apenas campos fiscais globais que podem ser compartilhados.
            dados_tomador = {
                "atividade_cnae": dados_tomador.get("atividade_cnae"),
                "descricao_servico": dados_tomador.get("descricao_servico"),
                "natureza_operacao": dados_tomador.get("natureza_operacao"),
                "aliquota_iss": dados_tomador.get("aliquota_iss"),
                "data_referencia_nf": dados_tomador.get("data_referencia_nf"),
            }

    if body.formato == "pdf":
        content, filename = fiscal_export_service.exportar_os_pdf(os_items, db, dados_tomador=dados_tomador)
        media_type = "application/pdf"
    elif body.formato == "csv":
        content, filename = fiscal_export_service.exportar_os_csv(os_items, db, dados_tomador=dados_tomador)
        media_type = "text/csv; charset=utf-8"
    else:
        content, filename = fiscal_export_service.exportar_os_xlsx(os_items, db, dados_tomador=dados_tomador)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    registrar_emissao_relatorio_fiscal(
        db,
        os_items=os_items,
        formato=body.formato,
        modo_multiclinica=body.modo_multiclinica,
        tipo_emissao=body.tipo_emissao,
        data_inicio=body.data_inicio,
        data_fim=body.data_fim,
        descricao_servico=(dados_tomador or {}).get("descricao_servico"),
        arquivo_nome=filename,
        usuario_id=current_user.id,
        usuario_nome=current_user.nome,
    )

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
