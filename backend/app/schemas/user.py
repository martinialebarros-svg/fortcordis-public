from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import List, Optional

class PapelResponse(BaseModel):
    id: int
    nome: str
    descricao: Optional[str]
    
    class Config:
        from_attributes = True

class UserResponse(BaseModel):
    id: int
    email: str
    nome: str
    ativo: int
    papeis: List[PapelResponse] = []
    
    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: EmailStr
    senha: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    nome: str
    email: str
    papeis: List[str] = []  # Lista de nomes de papéis
    provider: str = "legacy"
    expires_at: Optional[int] = None
