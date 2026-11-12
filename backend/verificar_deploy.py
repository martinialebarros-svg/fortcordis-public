#!/usr/bin/env python3
"""
Script de verificação pós-deploy
Execute na VPS após cada deploy para garantir que tudo está ok.
"""
import sys
from app.db.database import SessionLocal
from sqlalchemy import inspect, text

def verificar():
    print("🔍 VERIFICAÇÃO PÓS-DEPLOY\n")
    
    db = SessionLocal()
    inspector = inspect(db.bind)
    tabelas = inspector.get_table_names()
    
    checks = {
        "Tabelas criadas": len(tabelas) >= 10,
        "Frases qualitativas": False,
        "Tabelas de preço": False,
    }
    
    # Verificar frases
    try:
        from app.models.frase import FraseQualitativa
        count = db.query(FraseQualitativa).count()
        checks["Frases qualitativas"] = count > 0
        print(f"  Frases: {count} ✅" if count > 0 else f"  Frases: {count} ❌")
    except Exception as e:
        print(f"  Frases: ERRO - {e} ❌")
    
    # Verificar tabelas de preço
    try:
        from app.models.tabela_preco import TabelaPreco
        count = db.query(TabelaPreco).count()
        checks["Tabelas de preço"] = count > 0
        print(f"  Tabelas de preço: {count} ✅" if count > 0 else f"  Tabelas de preço: {count} ❌")
    except Exception as e:
        print(f"  Tabelas de preço: ERRO - {e} ❌")
    
    db.close()
    
    # Resumo
    print("\n" + "="*40)
    if all(checks.values()):
        print("✅ DEPLOY OK - Sistema pronto!")
        return 0
    else:
        print("❌ DEPLOY COM PROBLEMAS")
        print("\nExecute: python3 setup_database.py")
        return 1

if __name__ == "__main__":
    sys.exit(verificar())
