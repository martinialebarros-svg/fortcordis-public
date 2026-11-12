"""Script para criar tabelas de frases e adicionar dados iniciais"""
from app.db.database import engine, SessionLocal
from app.models.frase import FraseQualitativa, FraseQualitativaHistorico
from app.utils.frases_seed import seed_frases

print("Criando tabelas de frases...")
FraseQualitativa.__table__.create(engine, checkfirst=True)
FraseQualitativaHistorico.__table__.create(engine, checkfirst=True)
print("[OK] Tabelas criadas!")

print("\nAdicionando frases padrão...")
db = SessionLocal()
seed_frases(db)
db.close()
print("[OK] Seed completo!")
