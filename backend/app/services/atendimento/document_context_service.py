from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.atendimento_clinico import AtendimentoClinico, DocumentoAtendimento, DocumentoAtendimentoTemplate
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.utils.paciente_idade import idade_do_paciente
from app.utils.paciente_helpers import normalizar_sexo_paciente


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _formatar_data_hora(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    parsed = _parse_datetime(str(value))
    if parsed:
        return parsed.strftime("%d/%m/%Y %H:%M")
    return str(value)


def _formatar_data_curta(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    parsed = _parse_datetime(str(value))
    if parsed:
        return parsed.strftime("%d/%m/%Y")
    return str(value)


def _resolver_peso_referencia(
    atendimento: Optional[AtendimentoClinico],
    paciente: Optional[Paciente],
) -> Optional[float]:
    if atendimento and atendimento.peso is not None:
        return float(atendimento.peso)
    if paciente and paciente.peso_kg is not None:
        return float(paciente.peso_kg)
    return None


def carregar_contexto_entidades_documento(
    db: Session,
    atendimento: AtendimentoClinico,
    *,
    preferir_tutor_paciente: bool = True,
) -> tuple[Optional[Paciente], Optional[Tutor], Optional[Clinica]]:
    paciente = db.query(Paciente).filter(Paciente.id == atendimento.paciente_id).first()

    tutor_id = None
    if preferir_tutor_paciente and paciente and paciente.tutor_id:
        tutor_id = paciente.tutor_id
    elif atendimento.tutor_id:
        tutor_id = atendimento.tutor_id

    tutor = db.query(Tutor).filter(Tutor.id == tutor_id).first() if tutor_id else None
    if not tutor and preferir_tutor_paciente and atendimento.tutor_id and atendimento.tutor_id != tutor_id:
        tutor = db.query(Tutor).filter(Tutor.id == atendimento.tutor_id).first()

    clinica = db.query(Clinica).filter(Clinica.id == atendimento.clinica_id).first() if atendimento.clinica_id else None
    return paciente, tutor, clinica


def montar_contexto_template_documento(
    atendimento: AtendimentoClinico,
    paciente: Optional[Paciente],
    tutor: Optional[Tutor],
    clinica: Optional[Clinica],
    branding: Dict[str, Any],
) -> Dict[str, str]:
    peso = _resolver_peso_referencia(atendimento, paciente)
    data_atendimento = atendimento.data_atendimento if isinstance(atendimento.data_atendimento, datetime) else None
    return {
        "atendimento_id": str(atendimento.id),
        "data_atendimento": _formatar_data_curta(data_atendimento or atendimento.data_atendimento),
        "data_atendimento_hora": _formatar_data_hora(data_atendimento or atendimento.data_atendimento),
        "data_emissao": datetime.now().strftime("%d/%m/%Y"),
        "paciente_nome": paciente.nome if paciente else "",
        "especie": paciente.especie if paciente else (atendimento.especie or ""),
        "raca": paciente.raca if paciente else "",
        "sexo": normalizar_sexo_paciente(paciente.sexo if paciente else ""),
        "idade": idade_do_paciente(paciente, data_referencia=atendimento.data_atendimento,
        ),
        "peso": f"{peso:.1f} kg" if peso is not None else "",
        "tutor_nome": tutor.nome if tutor else "",
        "clinica_nome": clinica.nome if clinica else "",
        "veterinario_nome": branding.get("nome_veterinario") or atendimento.criado_por_nome or "",
        "crmv": branding.get("crmv") or "",
        "queixa_principal": atendimento.queixa_principal or "",
        "anamnese": atendimento.anamnese or "",
        "exame_fisico": atendimento.exame_fisico or "",
        "dados_clinicos": atendimento.dados_clinicos or "",
        "diagnostico_principal": atendimento.diagnostico_principal or "",
        "diagnostico_secundario": atendimento.diagnostico_secundario or "",
        "diagnostico_diferencial": atendimento.diagnostico_diferencial or "",
        "plano_terapeutico": atendimento.plano_terapeutico or "",
        "retorno_recomendado": atendimento.retorno_recomendado or "",
        "motivo_retorno": atendimento.motivo_retorno or "",
        "observacoes": atendimento.observacoes or "",
    }


_VARIAVEL_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def renderizar_template_documento(template_text: str, contexto: Dict[str, str]) -> str:
    def substituir(match: re.Match[str]) -> str:
        chave = match.group(1).strip()
        if chave in contexto:
            return str(contexto[chave] or "")
        return match.group(0)

    return _VARIAVEL_TEMPLATE_PATTERN.sub(substituir, template_text or "")


def identificar_variaveis_vazias(template_text: str, contexto: Dict[str, str]) -> List[str]:
    """Chaves `{{chave}}` presentes no template que existem no contexto mas
    resolveriam para vazio (ex.: paciente sem peso/raca cadastrados) - usado
    para avisar o vet antes de gerar o PDF (achado #42 da auditoria UX)."""
    chaves = {match.group(1).strip() for match in _VARIAVEL_TEMPLATE_PATTERN.finditer(template_text or "")}
    return sorted(chave for chave in chaves if chave in contexto and not str(contexto[chave] or "").strip())


def renderizar_template_documento_para_atendimento(
    db: Session,
    atendimento: AtendimentoClinico,
    template: DocumentoAtendimentoTemplate,
    branding: Dict[str, Any],
    *,
    preferir_tutor_paciente: bool = True,
) -> tuple[str, str, Optional[Paciente], Optional[Tutor], Optional[Clinica]]:
    paciente, tutor, clinica = carregar_contexto_entidades_documento(
        db,
        atendimento,
        preferir_tutor_paciente=preferir_tutor_paciente,
    )
    contexto = montar_contexto_template_documento(atendimento, paciente, tutor, clinica, branding)
    titulo = renderizar_template_documento(template.titulo_padrao or "", contexto)
    corpo = renderizar_template_documento(template.corpo_template or "", contexto)
    return titulo, corpo, paciente, tutor, clinica


def _texto_documento_inalterado(value: str, rendered_value: str) -> bool:
    return (value or "").strip() == (rendered_value or "").strip()


def atualizar_documento_template_se_contexto_mudou(
    db: Session,
    atendimento: AtendimentoClinico,
    documento: DocumentoAtendimento,
    branding: Dict[str, Any],
) -> tuple[Optional[Paciente], Optional[Tutor], Optional[Clinica]]:
    paciente, tutor, clinica = carregar_contexto_entidades_documento(db, atendimento)
    if not documento.template_id or (documento.status or "").lower() == "emitido":
        return paciente, tutor, clinica

    template = db.query(DocumentoAtendimentoTemplate).filter(DocumentoAtendimentoTemplate.id == documento.template_id).first()
    if not template:
        return paciente, tutor, clinica

    titulo_atual, corpo_atual, paciente, tutor, clinica = renderizar_template_documento_para_atendimento(
        db,
        atendimento,
        template,
        branding,
        preferir_tutor_paciente=True,
    )
    titulo_original, corpo_original, *_ = renderizar_template_documento_para_atendimento(
        db,
        atendimento,
        template,
        branding,
        preferir_tutor_paciente=False,
    )

    if (
        _texto_documento_inalterado(documento.titulo, titulo_original)
        and _texto_documento_inalterado(documento.corpo, corpo_original)
        and (
            not _texto_documento_inalterado(documento.titulo, titulo_atual)
            or not _texto_documento_inalterado(documento.corpo, corpo_atual)
        )
    ):
        documento.titulo = titulo_atual.strip()
        documento.corpo = corpo_atual.strip()
        documento.updated_at = datetime.now()
        db.flush()

    return paciente, tutor, clinica
