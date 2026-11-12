"""Endpoints para gerenciamento de referências ecocardiográficas"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
import csv
import io
import math

from app.db.database import get_db
from app.models.referencia_eco import ReferenciaEco
from app.models.user import User
from app.core.security import get_current_user
from app.utils.referencia_eco_defaults import aplicar_defaults_publicados_caninos, normalizar_especie_referencia
from app.services.echo_reference_resolver import POLICY_VERSION, load_echo_reference

router = APIRouter()

# Mapeamento CSV -> modelo (igual ao importar_referencias.py)
_MAPEAMENTO_CSV_CANINOS = {
    "Peso (kg)": "peso_kg", "LVIDd_Min": "lvid_d_min", "LVIDd_Max": "lvid_d_max",
    "IVSd_Min": "ivs_d_min", "IVSd_Max": "ivs_d_max", "LVPWd_Min": "lvpw_d_min", "LVPWd_Max": "lvpw_d_max",
    "LVIDs_Min": "lvid_s_min", "LVIDs_Max": "lvid_s_max", "IVSs_Min": "ivs_s_min", "IVSs_Max": "ivs_s_max",
    "LVPWs_Min": "lvpw_s_min", "LVPWs_Max": "lvpw_s_max", "EDV_Min": "edv_min", "EDV_Max": "edv_max",
    "ESV_Min": "esv_min", "ESV_Max": "esv_max", "SV_Min": "sv_min", "SV_Max": "sv_max",
    "EF_Min": "ef_min", "EF_Max": "ef_max", "FS_Min": "fs_min", "FS_Max": "fs_max",
    "Ao_Min": "ao_min", "Ao_Max": "ao_max", "LA_Min": "la_min", "LA_Max": "la_max",
    "LA_Ao_Min": "la_ao_min", "LA_Ao_Max": "la_ao_max", "Vmax_Ao_Min": "vmax_ao_min", "Vmax_Ao_Max": "vmax_ao_max",
    "Vmax_Pulm_Min": "vmax_pulm_min", "Vmax_Pulm_Max": "vmax_pulm_max",
    "MV_E_Min": "mv_e_min", "MV_E_Max": "mv_e_max", "MV_A_Min": "mv_a_min", "MV_A_Max": "mv_a_max",
    "MV_E_A_Min": "mv_ea_min", "MV_E_A_Max": "mv_ea_max", "MV_DT_Min": "mv_dt_min", "MV_DT_Max": "mv_dt_max",
    "IVRT_Min": "ivrt_min", "IVRT_Max": "ivrt_max",
}
_MAPEAMENTO_CSV_FELINOS = {
    "Peso": "peso_kg", "IVSd_Min": "ivs_d_min", "IVSd_Max": "ivs_d_max", "LVIDd_Min": "lvid_d_min", "LVIDd_Max": "lvid_d_max",
    "LVPWd_Min": "lvpw_d_min", "LVPWd_Max": "lvpw_d_max", "IVSs_Min": "ivs_s_min", "IVSs_Max": "ivs_s_max",
    "LVIDs_Min": "lvid_s_min", "LVIDs_Max": "lvid_s_max", "LVPWs_Min": "lvpw_s_min", "LVPWs_Max": "lvpw_s_max",
    "FS_Min": "fs_min", "FS_Max": "fs_max", "EF_Min": "ef_min", "EF_Max": "ef_max",
    "LA_Min": "la_min", "LA_Max": "la_max", "Ao_Min": "ao_min", "Ao_Max": "ao_max",
    "LA_Ao_Min": "la_ao_min", "LA_Ao_Max": "la_ao_max",
}


def _normalizar_especie(especie: Optional[str]) -> Optional[str]:
    """Normaliza texto de especie para Canina/Felina."""
    return normalizar_especie_referencia(especie)


def _aplicar_filtro_especie(query, especie: Optional[str]):
    """Aplica filtro flexivel por especie (suporta legado canino/caninos/felino/felinos)."""
    especie_norm = _normalizar_especie(especie)
    if not especie_norm:
        return query

    if especie_norm == "Canina":
        return query.filter(ReferenciaEco.especie.ilike("canin%"))
    if especie_norm == "Felina":
        return query.filter(ReferenciaEco.especie.ilike("felin%"))

    return query.filter(func.lower(ReferenciaEco.especie) == especie_norm.lower())


def _referencia_to_dict(r: ReferenciaEco, peso_kg_override: Optional[float] = None,
                        medidas: Optional[dict] = None) -> dict:
    """Serializa um ReferenciaEco para dict (evita problemas de JSON com objetos SQLAlchemy)."""
    referencia = {
        "id": r.id,
        "especie": r.especie,
        "peso_kg": r.peso_kg,
        # VE - Modo M
        "lvid_d_min": r.lvid_d_min, "lvid_d_max": r.lvid_d_max,
        "lvid_s_min": r.lvid_s_min, "lvid_s_max": r.lvid_s_max,
        "ivs_d_min": r.ivs_d_min, "ivs_d_max": r.ivs_d_max,
        "ivs_s_min": r.ivs_s_min, "ivs_s_max": r.ivs_s_max,
        "lvpw_d_min": r.lvpw_d_min, "lvpw_d_max": r.lvpw_d_max,
        "lvpw_s_min": r.lvpw_s_min, "lvpw_s_max": r.lvpw_s_max,
        # Função
        "fs_min": r.fs_min, "fs_max": r.fs_max,
        "ef_min": r.ef_min, "ef_max": r.ef_max,
        "tapse_min": r.tapse_min, "tapse_max": r.tapse_max,
        "mapse_min": r.mapse_min, "mapse_max": r.mapse_max,
        # Vasos
        "ao_min": r.ao_min, "ao_max": r.ao_max,
        "la_min": r.la_min, "la_max": r.la_max,
        "la_ao_min": r.la_ao_min, "la_ao_max": r.la_ao_max,
        # Artéria Pulmonar
        "ap_min": r.ap_min, "ap_max": r.ap_max,
        "ap_ao_min": r.ap_ao_min, "ap_ao_max": r.ap_ao_max,
        # Fluxos
        "vmax_ao_min": r.vmax_ao_min, "vmax_ao_max": r.vmax_ao_max,
        "vmax_pulm_min": r.vmax_pulm_min, "vmax_pulm_max": r.vmax_pulm_max,
        # Mitral/Diastólica
        "mv_e_min": r.mv_e_min, "mv_e_max": r.mv_e_max,
        "mv_a_min": r.mv_a_min, "mv_a_max": r.mv_a_max,
        "mv_ea_min": r.mv_ea_min, "mv_ea_max": r.mv_ea_max,
        "mv_dt_min": r.mv_dt_min, "mv_dt_max": r.mv_dt_max,
        "ivrt_min": r.ivrt_min, "ivrt_max": r.ivrt_max,
        # Doppler Tecidual
        "tdi_e_min": r.tdi_e_min, "tdi_e_max": r.tdi_e_max,
        "tdi_a_min": r.tdi_a_min, "tdi_a_max": r.tdi_a_max,
        "e_e_linha_min": r.e_e_linha_min, "e_e_linha_max": r.e_e_linha_max,
        # Volumes
        "edv_min": r.edv_min, "edv_max": r.edv_max,
        "esv_min": r.esv_min, "esv_max": r.esv_max,
        "sv_min": r.sv_min, "sv_max": r.sv_max,
    }
    return aplicar_defaults_publicados_caninos(referencia, peso_kg=peso_kg_override, medidas=medidas)


def _importar_csv_from_content(content: str, especie: str, db: Session) -> int:
    """Validate the entire file before atomically replacing one species."""
    mapeamento = _MAPEAMENTO_CSV_CANINOS if especie == "Canina" else _MAPEAMENTO_CSV_FELINOS
    stream = io.StringIO(content)
    reader = csv.DictReader(stream, strict=True)
    # Normalizar nomes das colunas (strip BOM e espaços)
    if reader.fieldnames:
        reader.fieldnames = [c.strip().strip("\ufeff") for c in reader.fieldnames]
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("CSV sem cabeçalho válido ou com colunas duplicadas")
    weight_columns = ("Peso", "Peso (kg)", "peso", "Peso(kg)")
    if not any(column in reader.fieldnames for column in weight_columns):
        raise ValueError("CSV sem coluna de peso")
    validated_rows = []
    seen_weights = set()
    for line, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Linha {line}: número de colunas inválido")
        dados = {"especie": especie}
        for csv_col, db_col in mapeamento.items():
            valor = (row.get(csv_col) or "").strip()
            dados[db_col] = None
            if valor:
                try:
                    numeric = float(valor.replace(",", "."))
                except ValueError as error:
                    raise ValueError(f"Linha {line}: valor inválido em {csv_col}") from error
                if not math.isfinite(numeric):
                    raise ValueError(f"Linha {line}: valor não finito em {csv_col}")
                dados[db_col] = numeric
        # Fallback: caninos às vezes têm coluna "Peso" em vez de "Peso (kg)"
        if dados.get("peso_kg") is None and especie == "Canina":
            for alt in weight_columns:
                v = (row.get(alt) or "").strip()
                if v:
                    try:
                        dados["peso_kg"] = float(v.replace(",", "."))
                    except ValueError as error:
                        raise ValueError(f"Linha {line}: peso inválido") from error
                    break
        weight = dados.get("peso_kg")
        if weight is None or not math.isfinite(weight) or weight <= 0:
            raise ValueError(f"Linha {line}: peso deve ser positivo e finito")
        if weight in seen_weights:
            raise ValueError(f"Linha {line}: peso duplicado ({weight} kg)")
        seen_weights.add(weight)
        for column, minimum in dados.items():
            if column.endswith("_min") and minimum is not None:
                maximum = dados.get(column[:-4] + "_max")
                if maximum is not None and minimum > maximum:
                    raise ValueError(f"Linha {line}: mínimo maior que máximo em {column[:-4]}")
        validated_rows.append(dados)
    if not validated_rows:
        raise ValueError("CSV sem linhas de referência válidas")
    try:
        _aplicar_filtro_especie(db.query(ReferenciaEco), especie).delete(synchronize_session=False)
        db.add_all([ReferenciaEco(**dados) for dados in validated_rows])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(validated_rows)


class ReferenciaEcoCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    especie: str
    peso_kg: float = Field(gt=0)
    # VE - Modo M
    lvid_d_min: Optional[float] = None
    lvid_d_max: Optional[float] = None
    lvid_s_min: Optional[float] = None
    lvid_s_max: Optional[float] = None
    ivs_d_min: Optional[float] = None
    ivs_d_max: Optional[float] = None
    ivs_s_min: Optional[float] = None
    ivs_s_max: Optional[float] = None
    lvpw_d_min: Optional[float] = None
    lvpw_d_max: Optional[float] = None
    lvpw_s_min: Optional[float] = None
    lvpw_s_max: Optional[float] = None
    # Função
    fs_min: Optional[float] = None
    fs_max: Optional[float] = None
    ef_min: Optional[float] = None
    ef_max: Optional[float] = None
    tapse_min: Optional[float] = None
    tapse_max: Optional[float] = None
    mapse_min: Optional[float] = None
    mapse_max: Optional[float] = None
    # Vasos
    ao_min: Optional[float] = None
    ao_max: Optional[float] = None
    la_min: Optional[float] = None
    la_max: Optional[float] = None
    la_ao_min: Optional[float] = None
    la_ao_max: Optional[float] = None
    # Artéria Pulmonar
    ap_min: Optional[float] = None
    ap_max: Optional[float] = None
    ap_ao_min: Optional[float] = None
    ap_ao_max: Optional[float] = None
    # Fluxos
    vmax_ao_min: Optional[float] = None
    vmax_ao_max: Optional[float] = None
    vmax_pulm_min: Optional[float] = None
    vmax_pulm_max: Optional[float] = None
    # Mitral/Diastólica
    mv_e_min: Optional[float] = None
    mv_e_max: Optional[float] = None
    mv_a_min: Optional[float] = None
    mv_a_max: Optional[float] = None
    mv_ea_min: Optional[float] = None
    mv_ea_max: Optional[float] = None
    mv_dt_min: Optional[float] = None
    mv_dt_max: Optional[float] = None
    ivrt_min: Optional[float] = None
    ivrt_max: Optional[float] = None
    # Doppler Tecidual
    tdi_e_min: Optional[float] = None
    tdi_e_max: Optional[float] = None
    tdi_a_min: Optional[float] = None
    tdi_a_max: Optional[float] = None
    e_e_linha_min: Optional[float] = None
    e_e_linha_max: Optional[float] = None
    # Volumes
    edv_min: Optional[float] = None
    edv_max: Optional[float] = None
    esv_min: Optional[float] = None
    esv_max: Optional[float] = None
    sv_min: Optional[float] = None
    sv_max: Optional[float] = None

    @model_validator(mode="after")
    def validar_intervalos(self):
        for field in type(self).model_fields:
            if field.endswith("_min"):
                minimum = getattr(self, field)
                maximum = getattr(self, field[:-4] + "_max", None)
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise ValueError(f"Mínimo maior que máximo em {field[:-4]}")
        for field in ("especie", "peso_kg"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} não pode ser nulo")
        return self


class ReferenciaEcoUpdate(ReferenciaEcoCreate):
    especie: Optional[str] = None
    peso_kg: Optional[float] = Field(default=None, gt=0)


@router.get("", response_model=None)
@router.get("/", response_model=None)
def listar_referencias(
    especie: Optional[str] = None,
    peso: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista referências ecocardiográficas com filtros (aceita / e sem barra final)."""
    query = db.query(ReferenciaEco)
    
    if especie:
        query = _aplicar_filtro_especie(query, especie)
    if peso is not None:
        # Busca o peso mais próximo (dentro de uma faixa)
        query = query.filter(
            ReferenciaEco.peso_kg >= peso - 1,
            ReferenciaEco.peso_kg <= peso + 1
        )
    
    referencias = query.order_by(ReferenciaEco.especie, ReferenciaEco.peso_kg).all()
    return {"total": len(referencias), "policy_version": POLICY_VERSION,
            "items": [_referencia_to_dict(r) for r in referencias]}


@router.post("/importar")
def importar_referencias_csv(
    caninos: Optional[UploadFile] = File(None),
    felinos: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Importa referências a partir dos CSVs (caninos e/ou felinos). Substitui as existentes da espécie."""
    result = {"caninos": 0, "felinos": 0, "erros": []}
    if not caninos and not felinos:
        raise HTTPException(
            status_code=400,
            detail="Envie pelo menos um arquivo: caninos e/ou felinos",
        )
    if caninos:
        try:
            content = caninos.file.read().decode("utf-8-sig")
            result["caninos"] = _importar_csv_from_content(content, "Canina", db)
        except Exception as e:
            result["erros"].append(f"Caninos: {str(e)}")
    if felinos:
        try:
            content = felinos.file.read().decode("utf-8-sig")
            result["felinos"] = _importar_csv_from_content(content, "Felina", db)
        except Exception as e:
            result["erros"].append(f"Felinos: {str(e)}")
    return result


@router.get("/{referencia_id}")
def obter_referencia(
    referencia_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém uma referência específica"""
    ref = db.query(ReferenciaEco).filter(ReferenciaEco.id == referencia_id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    return _referencia_to_dict(ref)


@router.get("/buscar/{especie}/{peso_kg}")
def buscar_referencia_por_peso(
    especie: str,
    peso_kg: float,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    TAPSE_metodo: Optional[str] = None,
    AE_Ao_metodo: Optional[str] = None,
    idade: Optional[str] = None,
):
    """Resolve catálogo e fallback documentado de baixo peso, sem gravar linhas."""
    if not math.isfinite(peso_kg) or peso_kg <= 0:
        raise HTTPException(status_code=422, detail="Peso deve ser positivo e finito")
    ref = load_echo_reference(db, species=especie, weight_kg=peso_kg,
                              medidas={"TAPSE_metodo": TAPSE_metodo, "AE_Ao_metodo": AE_Ao_metodo}, idade=idade)
    
    if not ref:
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    return ref


@router.post("/", status_code=status.HTTP_201_CREATED)
def criar_referencia(
    referencia: ReferenciaEcoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova referência"""
    nova_ref = ReferenciaEco(**referencia.dict())
    db.add(nova_ref)
    db.commit()
    db.refresh(nova_ref)
    return _referencia_to_dict(nova_ref)


@router.put("/{referencia_id}")
def atualizar_referencia(
    referencia_id: int,
    referencia: ReferenciaEcoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza uma referência existente"""
    ref = db.query(ReferenciaEco).filter(ReferenciaEco.id == referencia_id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    
    changes = referencia.model_dump(exclude_unset=True)
    merged = {column.name: getattr(ref, column.name) for column in ReferenciaEco.__table__.columns
              if column.name != "id"}
    merged.update(changes)
    # A one-sided edit must also be valid against its persisted counterpart.
    try:
        ReferenciaEcoCreate.model_validate(merged)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Intervalo inválido para os valores cadastrados") from error
    for field, value in changes.items():
        setattr(ref, field, value)
    
    db.commit()
    db.refresh(ref)
    return _referencia_to_dict(ref)


@router.delete("/{referencia_id}")
def deletar_referencia(
    referencia_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove uma referência"""
    ref = db.query(ReferenciaEco).filter(ReferenciaEco.id == referencia_id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    
    db.delete(ref)
    db.commit()
    return {"message": "Referência removida com sucesso"}
