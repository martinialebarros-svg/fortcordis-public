"""Script para criar tabelas de imagens"""
from app.db.database import engine
from app.models.imagem_laudo import ImagemLaudo, ImagemTemporaria

print("Criando tabelas de imagens...")
ImagemLaudo.__table__.create(engine, checkfirst=True)
ImagemTemporaria.__table__.create(engine, checkfirst=True)
print("[OK] Tabelas criadas!")
