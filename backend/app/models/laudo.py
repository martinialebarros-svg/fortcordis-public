from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Float, JSON, event
from sqlalchemy.sql import func
from datetime import datetime
from app.db.database import Base

class Laudo(Base):
    __tablename__ = "laudos"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Relacionamentos
    paciente_id = Column(Integer, nullable=False)
    agendamento_id = Column(Integer, nullable=True)
    veterinario_id = Column(Integer, nullable=False)  # Usuário que fez o laudo
    
    # Dados do laudo
    tipo = Column(String, nullable=False)  # exame, consulta, cirurgia, etc
    titulo = Column(String, nullable=False)
    descricao = Column(Text)
    diagnostico = Column(Text)
    observacoes = Column(Text)
    
    # Anexos (URLs separadas por vírgula ou JSON)
    anexos = Column(Text)  # URLs dos arquivos
    
    # Status
    status = Column(String, default='Rascunho')  # Rascunho, Finalizado, Arquivado

    # Momento da primeira finalizacao (status == "Finalizado"). Preenchido
    # automaticamente pelo evento SQLAlchemy abaixo, nao por cada endpoint -
    # nunca e sobrescrito depois, mesmo que o laudo seja reaberto/editado.
    # Usado para medir o prazo de 48h uteis (fila-pendentes-agenda), ja que
    # `updated_at` muda a cada edicao e nao serve pra isso.
    finalizado_em = Column(DateTime(timezone=True), nullable=True)

    # Datas
    data_laudo = Column(DateTime(timezone=True), default=func.now())
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Clínica
    clinic_id = Column(Integer, nullable=True)  # ID da clínica vinculada
    veterinario_parceiro_id = Column(Integer, nullable=True, index=True)  # Parceiro externo que encaminhou o caso

    # Resultado da ultima tentativa de aviso de liberacao pelo WhatsApp
    # (POST /laudos/{id}/portal/whatsapp) - sucesso/falha do envio, nao
    # confirmacao de entrega/leitura (essa vive so no whatsapp-stage-backend).
    whatsapp_liberacao_status = Column(String, nullable=True)  # "enviado" | "falhou"
    whatsapp_liberacao_em = Column(DateTime(timezone=True), nullable=True)
    whatsapp_liberacao_erro = Column(Text, nullable=True)

    # Mesmo aviso, mesma chamada, mas para o veterinario parceiro que
    # encaminhou o caso - destino independente do da clinica.
    whatsapp_parceiro_status = Column(String, nullable=True)  # "enviado" | "falhou"
    whatsapp_parceiro_em = Column(DateTime(timezone=True), nullable=True)
    whatsapp_parceiro_erro = Column(Text, nullable=True)

    # Ultimo resultado por destino do aviso, com as chaves que o seletor usa
    # ("clinica", "veterinario:<id>"). As colunas acima continuam sendo o
    # resumo; so este mapa responde "quem ja recebeu" quando o laudo tem mais
    # de um veterinario.
    whatsapp_envios = Column(JSON, nullable=True)

    # Dados adicionais
    data_exame = Column(DateTime(timezone=True))  # Data do exame
    medico_solicitante = Column(String)  # Médico solicitante
    
    # Auditoria
    criado_por_id = Column(Integer)
    criado_por_nome = Column(String)

class Exame(Base):
    __tablename__ = "exames"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Relacionamentos
    laudo_id = Column(Integer, nullable=True)
    atendimento_id = Column(Integer, nullable=True)
    paciente_id = Column(Integer, nullable=False)
    
    # Tipo de exame
    tipo_exame = Column(String, nullable=False)  # Sangue, Urina, Raio-X, Ultrassom, etc
    catalogo_exame_id = Column(Integer, nullable=True, index=True)
    painel_exame_id = Column(Integer, nullable=True, index=True)
    painel_exame_nome = Column(String)
    categoria_exame = Column(String)
    preparo = Column(Text)
    prioridade = Column(String, default='Rotina')  # Rotina, Urgente, Emergencial
    
    # Resultados
    resultado = Column(Text)
    valor_referencia = Column(Text)
    unidade = Column(String)
    
    # Status
    status = Column(String, default='Solicitado')  # Solicitado, Em andamento, Concluido
    
    # Datas
    data_solicitacao = Column(DateTime(timezone=True), default=func.now())
    data_resultado = Column(DateTime(timezone=True))
    
    # Valor
    valor = Column(Float, default=0)

    # Observações
    observacoes = Column(Text)
    # Backup do texto de `observacoes` de antes da liberacao no portal (que
    # sobrescreve o campo com uma mensagem fixa) - usado para restaurar ao
    # revogar a liberacao.
    observacoes_pre_portal = Column(Text)
    # Primeiro acesso da clinica parceira ao arquivo do exame liberado no
    # portal (nulo = ainda nao visualizado). Zerado ao liberar/revogar de
    # novo, para nao carregar uma visualizacao de um ciclo anterior.
    visualizado_portal_em = Column(DateTime(timezone=True), nullable=True)

    # Auditoria
    created_at = Column(DateTime(timezone=True), default=func.now())
    criado_por_id = Column(Integer)
    criado_por_nome = Column(String)


@event.listens_for(Laudo, "before_insert")
@event.listens_for(Laudo, "before_update")
def _preencher_finalizado_em(mapper, connection, target: "Laudo") -> None:
    """Marca o momento da primeira finalizacao, uma unica vez.

    Roda para qualquer insert/update de Laudo (upload de ECG ja nasce
    "Finalizado"; o fluxo normal transiciona de "Rascunho" via
    `atualizar_laudo`) - centralizado aqui em vez de em cada endpoint para
    nao depender de lembrar de setar isso em todo caminho de codigo,
    presente ou futuro.
    """
    if target.status == "Finalizado" and target.finalizado_em is None:
        target.finalizado_em = datetime.utcnow()
