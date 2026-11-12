from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.models.papel import usuario_papel

class User(Base):
    __tablename__ = "usuarios"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    nome = Column(String)
    senha_hash = Column(String)
    ativo = Column(Integer, default=1)
    ultimo_acesso = Column(DateTime(timezone=True))
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    criado_por = Column(Integer)
    tentativas_login = Column(Integer, default=0)
    bloqueado_ate = Column(DateTime(timezone=True))
    
    # Relacionamento com papéis
    papeis = relationship("Papel", secondary=usuario_papel, back_populates="usuarios")
    
    def tem_papel(self, papel_nome: str) -> bool:
        """Verifica se usuário tem um papel específico"""
        return any(p.nome.lower() == papel_nome.lower() for p in self.papeis)
    
    def tem_permissao(self, permissao: str) -> bool:
        """Verifica se usuário tem uma permissão específica (simplificado)"""
        # Aqui você pode implementar a lógica de permissões granulares
        # Por enquanto, vamos usar apenas papéis
        return True
