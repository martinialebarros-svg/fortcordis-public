"""Script para criar tabelas de laudos e financeiro"""
import os
os.environ['DATABASE_URL'] = 'sqlite:///./fortcordis.db'
os.environ['SECRET_KEY'] = 'test-secret-key'

from app.db.database import engine, Base
from app.models import laudo, financeiro

print("Criando tabelas...")
Base.metadata.create_all(bind=engine)
print("Tabelas criadas com sucesso!")
print("- laudos")
print("- exames")
print("- transacoes")
print("- contas_pagar")
print("- contas_receber")
