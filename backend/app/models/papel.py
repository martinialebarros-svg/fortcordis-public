from sqlalchemy import Column, Integer, String, DateTime, Table, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.database import Base

# Tabela de associação usuario_papel
usuario_papel = Table(
    'usuario_papel',
    Base.metadata,
    Column('usuario_id', Integer, ForeignKey('usuarios.id'), primary_key=True),
    Column('papel_id', Integer, ForeignKey('papeis.id'), primary_key=True),
    Column('atribuido_em', DateTime(timezone=True), server_default=func.now()),
    Column('atribuido_por', Integer, nullable=True)
)

class Papel(Base):
    __tablename__ = "papeis"
    
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True)  # admin, medico, secretaria, parceiro
    descricao = Column(String)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relacionamento
    usuarios = relationship("User", secondary=usuario_papel, back_populates="papeis")
