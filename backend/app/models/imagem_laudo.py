"""Modelo para imagens de laudos"""
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, LargeBinary, Float
from sqlalchemy.sql import func
from app.db.database import Base


class ImagemLaudo(Base):
    """Imagens associadas a um laudo"""
    __tablename__ = "imagens_laudo"

    id = Column(Integer, primary_key=True, index=True)
    laudo_id = Column(Integer, ForeignKey("laudos.id"), nullable=True)
    
    # Metadados da imagem
    nome_arquivo = Column(String(255), nullable=False)
    tipo_mime = Column(String(100), default="image/jpeg")
    tamanho_bytes = Column(Integer)
    
    # Dados da imagem (pode ser binário ou path)
    conteudo = Column(LargeBinary, nullable=True)  # Para armazenamento no banco
    caminho_arquivo = Column(String(500), nullable=True)  # Para armazenamento em disco
    
    # Posicionamento e tamanho no PDF
    ordem = Column(Integer, default=0)
    pagina = Column(Integer, default=1)
    largura = Column(Float, default=0)  # em cm
    altura = Column(Float, default=0)   # em cm
    
    # Descrição/legenda
    descricao = Column(Text, default="")
    incluir_no_pdf = Column(Boolean, nullable=False, default=True, server_default="1")
    
    # Auditoria
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Controle
    ativo = Column(Integer, default=1)


class ImagemTemporaria(Base):
    """Imagens temporárias enquanto o laudo está sendo criado (antes de salvar)"""
    __tablename__ = "imagens_temporarias"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(255), index=True)  # ID da sessão do usuário
    
    nome_arquivo = Column(String(255), nullable=False)
    tipo_mime = Column(String(100), default="image/jpeg")
    tamanho_bytes = Column(Integer)
    conteudo = Column(LargeBinary, nullable=False)
    
    ordem = Column(Integer, default=0)
    descricao = Column(Text, default="")
    incluir_no_pdf = Column(Boolean, nullable=False, default=True, server_default="1")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Expira após X horas (job de limpeza)
    expira_em = Column(DateTime(timezone=True))
