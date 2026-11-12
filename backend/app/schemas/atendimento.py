"""Schemas Pydantic para o módulo de atendimento clínico."""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExameSolicitacaoPayload(BaseModel):
    """Exame solicitado no prontuario.

    `status` continua aceito por compatibilidade, mas e ignorado pelo backend:
    o status do exame e derivado no servidor para nao revogar liberacao no
    portal a cada save. Exclusao acontece somente com `_destroy`; exame
    existente omitido do payload e preservado.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[int] = None
    catalogo_exame_id: Optional[int] = None
    painel_exame_id: Optional[int] = None
    painel_exame_nome: Optional[str] = ""
    tipo_exame: str = Field(default="", max_length=120)
    categoria_exame: Optional[str] = ""
    preparo: Optional[str] = ""
    prioridade: str = Field(default="Rotina", max_length=50)
    status: str = Field(default="Solicitado", max_length=50)
    resultado: Optional[str] = ""
    valor_referencia: Optional[str] = ""
    unidade: Optional[str] = ""
    data_resultado: Optional[str] = None
    observacoes: Optional[str] = ""
    valor: Optional[float] = 0.0
    laudo_id: Optional[int] = None
    destroy: bool = Field(default=False, alias="_destroy")

    @model_validator(mode="after")
    def _exigir_tipo_exame_quando_nao_excluir(self) -> "ExameSolicitacaoPayload":
        if self.destroy:
            return self
        if len((self.tipo_exame or "").strip()) < 2:
            raise ValueError("Informe o tipo de exame com pelo menos 2 caracteres.")
        return self


class PrescricaoItemPayload(BaseModel):
    id: Optional[int] = None
    medicamento_id: Optional[int] = None
    medicamento_nome: Optional[str] = ""
    apresentacao_selecionada: Optional[str] = ""
    dose: Optional[str] = ""
    frequencia: Optional[str] = ""
    duracao: Optional[str] = ""
    via: Optional[str] = ""
    instrucoes: Optional[str] = ""
    ordem: Optional[int] = 0
    dose_mg_kg: Optional[str] = None
    peso_referencia_kg: Optional[str] = None
    unidade_dose_calculo: Optional[Literal["mg", "ml", "comprimido"]] = None
    concentracao_personalizada: Optional[str] = None


class PrescricaoPayload(BaseModel):
    orientacoes_gerais: Optional[str] = ""
    retorno_dias: Optional[int] = None
    itens: List[PrescricaoItemPayload] = Field(default_factory=list)


class PrescricaoSyncPayload(PrescricaoPayload):
    """Edicao de uma receita especifica do atendimento.

    `confirmar_edicao_receita_emitida` libera a alteracao de uma receita que
    ja virou PDF - o backend so exige a confirmacao quando o payload de fato
    muda o conteudo da receita emitida.
    """

    confirmar_edicao_receita_emitida: Optional[bool] = None


class PrescricaoComplementarPayload(BaseModel):
    """Criacao da proxima receita do atendimento.

    `copiar_de_prescricao_id` duplica os itens da receita indicada como
    registros novos; a receita de origem nao e alterada.
    """

    adendo_id: Optional[int] = None
    copiar_de_prescricao_id: Optional[int] = None


class TriagemPayload(BaseModel):
    peso: Optional[float] = None
    temperatura: Optional[float] = None
    frequencia_cardiaca: Optional[int] = None
    frequencia_respiratoria: Optional[int] = None
    pressao_arterial: Optional[str] = ""
    saturacao_oxigenio: Optional[int] = None
    escore_condicion_corpo: Optional[int] = None
    mucosas: Optional[str] = ""
    hidratacao: Optional[str] = ""
    triagem_observacoes: Optional[str] = ""


class DiagnosticoPayload(BaseModel):
    diagnostico_principal: Optional[str] = ""
    diagnostico_secundario: Optional[str] = ""
    diagnostico_diferencial: Optional[str] = ""
    prognostico: Optional[str] = ""


class EvolucaoPayload(BaseModel):
    descricao: str
    sinais_vitais: Optional[str] = ""


class AdendoPayload(BaseModel):
    """Adendo clinico: o que chega depois do encontro, no mesmo episodio.

    `pos_conclusao` nao entra aqui de proposito - e derivado no backend a
    partir do status do atendimento no momento da criacao.
    """

    tipo: Literal[
        "evolucao",
        "resultado_exame",
        "receita_complementar",
        "orientacao",
    ] = "evolucao"
    titulo: Optional[str] = Field(default="", max_length=255)
    descricao: str
    data_evolucao: Optional[str] = None
    sinais_vitais: Optional[str] = ""

    @model_validator(mode="after")
    def _exigir_descricao(self) -> "AdendoPayload":
        if len((self.descricao or "").strip()) < 2:
            raise ValueError("Descreva o adendo com pelo menos 2 caracteres.")
        return self


class AnexoPayload(BaseModel):
    tipo: str = Field(..., max_length=50)
    descricao: Optional[str] = ""
    url: str
    nome_original: Optional[str] = ""
    tamanho: Optional[int] = None
    mime_type: Optional[str] = ""
    exame_id: Optional[int] = None
    evolucao_id: Optional[int] = None


class DocumentoTemplatePayload(BaseModel):
    nome: str = Field(..., min_length=2, max_length=255)
    tipo: str = Field(default="documento", max_length=80)
    titulo_padrao: str = Field(..., min_length=2, max_length=255)
    corpo_template: str = Field(..., min_length=2)
    ativo: Optional[int] = 1
    ordem: Optional[int] = 0


class DocumentoAtendimentoCreatePayload(BaseModel):
    template_id: Optional[int] = None
    titulo: Optional[str] = Field(default="", max_length=255)
    corpo: Optional[str] = ""


class DocumentoAtendimentoUpdatePayload(BaseModel):
    versao: Optional[str] = Field(default=None, max_length=64)
    titulo: Optional[str] = Field(default=None, max_length=255)
    corpo: Optional[str] = None
    status: Optional[str] = Field(default=None, max_length=40)


class AlertaPayload(BaseModel):
    tipo: str = Field(..., max_length=50)
    titulo: str
    descricao: Optional[str] = ""
    gravidade: Optional[str] = "media"


class AtendimentoCreatePayload(BaseModel):
    paciente_id: int
    clinica_id: Optional[int] = None
    agendamento_id: Optional[int] = None
    data_atendimento: Optional[str] = None
    status: str = Field(default="Triagem", max_length=50)
    triagem: Optional[TriagemPayload] = None
    triagem_concluida: Optional[int] = 0
    consulta_concluida: Optional[int] = 0
    queixa_principal: Optional[str] = ""
    anamnese: Optional[str] = ""
    exame_fisico: Optional[str] = ""
    dados_clinicos: Optional[str] = ""
    diagnostico: Optional[Union[DiagnosticoPayload, str]] = None
    plano_terapeutico: Optional[str] = ""
    retorno_recomendado: Optional[str] = ""
    motivo_retorno: Optional[str] = ""
    observacoes: Optional[str] = ""
    exames: List[ExameSolicitacaoPayload] = Field(default_factory=list)
    prescricao: Optional[PrescricaoPayload] = None
    confirmar_conclusao_pendencias: Optional[bool] = None


class AtendimentoUpdatePayload(BaseModel):
    paciente_id: Optional[int] = None
    clinica_id: Optional[int] = None
    agendamento_id: Optional[int] = None
    data_atendimento: Optional[str] = None
    status: Optional[str] = Field(default=None, max_length=50)
    triagem: Optional[TriagemPayload] = None
    triagem_concluida: Optional[int] = None
    consulta_concluida: Optional[int] = None
    queixa_principal: Optional[str] = None
    anamnese: Optional[str] = None
    exame_fisico: Optional[str] = None
    dados_clinicos: Optional[str] = None
    diagnostico: Optional[Union[DiagnosticoPayload, str]] = None
    plano_terapeutico: Optional[str] = None
    retorno_recomendado: Optional[str] = None
    motivo_retorno: Optional[str] = None
    observacoes: Optional[str] = None
    exames: Optional[List[ExameSolicitacaoPayload]] = None
    prescricao: Optional[PrescricaoPayload] = None
    confirmar_desvinculo_agendamento: Optional[bool] = None
    confirmar_conclusao_pendencias: Optional[bool] = None
    confirmar_edicao_receita_emitida: Optional[bool] = None


class AtendimentoFinalizarPayload(BaseModel):
    tipo_horario: str = Field(default="comercial", max_length=20)
    confirmar_conclusao_pendencias: Optional[bool] = None


class MedicamentoPayload(BaseModel):
    nome: str = Field(..., min_length=2, max_length=255)
    principio_ativo: Optional[str] = ""
    concentracao: Optional[str] = ""
    forma_farmaceutica: Optional[str] = ""
    categoria: Optional[str] = ""
    classe_terapeutica: Optional[str] = ""
    especie_alvo: Optional[str] = ""
    dose_min_mg_kg: Optional[float] = None
    dose_max_mg_kg: Optional[float] = None
    dose_intervalo_horas: Optional[int] = None
    dose_unidade: Optional[str] = "mg/kg"
    via_padrao: Optional[str] = ""
    duracao_padrao: Optional[str] = ""
    concentracao_mg_ml: Optional[float] = None
    concentracao_mg_comprimido: Optional[float] = None
    indicacoes: Optional[str] = ""
    contraindicacoes: Optional[str] = ""
    interacoes: List[str] = Field(default_factory=list)
    observacao_seguranca: Optional[str] = ""
    parametrizacao_origem: Optional[str] = "manual"
    observacoes: Optional[str] = ""
    ativo: Optional[int] = 1


class ClinicalPhrasePayload(BaseModel):
    secao: str = Field(..., min_length=2, max_length=120)
    titulo: str = Field(..., min_length=2, max_length=255)
    texto: str = Field(..., min_length=2)
    ordem: Optional[int] = 0
    ativo: Optional[int] = 1


class CatalogoExameCustomPayload(BaseModel):
    nome: str = Field(..., min_length=2, max_length=120)
    categoria: str = Field(..., min_length=2, max_length=120)
    subcategoria: Optional[str] = Field(default="", max_length=120)
    especie_alvo: Optional[str] = Field(default="", max_length=120)
    prioridade_padrao: str = Field(default="Rotina", max_length=50)
    valor_padrao: float = Field(default=0, ge=0)
    preparo: Optional[str] = ""
    observacoes_padrao: Optional[str] = ""
    sinonimos: List[str] = Field(default_factory=list, max_length=30)


class PainelExameItemPayload(BaseModel):
    catalogo_exame_id: int = Field(..., ge=1)
    ordem: Optional[int] = 0


class PainelExamePayload(BaseModel):
    nome: str = Field(..., min_length=2, max_length=255)
    categoria: Optional[str] = ""
    especie_alvo: Optional[str] = ""
    observacoes: Optional[str] = ""
    ativo: Optional[int] = 1
    itens: List[PainelExameItemPayload] = Field(default_factory=list)


class PrescricaoPreviewPayload(BaseModel):
    """Payload para preview em tempo real da prescricao (sem salvar no banco)."""
    paciente_nome: str = ""
    paciente_especie: str = ""
    paciente_raca: str = ""
    paciente_peso: Optional[float] = None
    paciente_sexo: str = ""
    paciente_idade: str = ""
    tutor_nome: str = ""
    veterinario_nome: str = ""
    data_atendimento: str = ""
    orientacoes_gerais: str = ""
    retorno_dias: Optional[int] = None
    itens: List[PrescricaoItemPayload] = Field(default_factory=list)
