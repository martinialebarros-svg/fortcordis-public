"""Importa frases personalizadas do frases_personalizadas.json para o stage"""
import json
import re
import os

# Carregar .env
if os.path.exists('.env'):
    with open('.env', 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

from app.db.database import SessionLocal
from app.models.frase import FraseQualitativa

def parse_chave(chave: str):
    """Extrai patologia e grau da chave"""
    match = re.match(r"(.+)\s*\(([^)]+)\)", chave)
    if match:
        patologia = match.group(1).strip()
        grau = match.group(2).strip()
    else:
        patologia = chave.strip()
        grau = "Normal"
    return patologia, grau

def importar_frases():
    """Importa frases do arquivo JSON local"""
    db = SessionLocal()
    
    try:
        # Ler arquivo JSON
        with open("frases_personalizadas.json", "r", encoding="utf-8") as f:
            dados = json.load(f)
        
        print(f"[INFO] {len(dados)} frases encontradas no arquivo")
        
        count = 0
        skipped = 0
        for chave, frase_data in dados.items():
            patologia, grau = parse_chave(chave)
            
            # Verifica se já existe
            existing = db.query(FraseQualitativa).filter(
                FraseQualitativa.chave == chave
            ).first()
            
            if existing:
                # Atualiza frase existente
                existing.valvas = frase_data.get("valvas", "")
                existing.camaras = frase_data.get("camaras", "")
                existing.funcao = frase_data.get("funcao", "")
                existing.pericardio = frase_data.get("pericardio", "")
                existing.vasos = frase_data.get("vasos", "")
                existing.ad_vd = frase_data.get("ad_vd", "")
                existing.conclusao = frase_data.get("conclusao", "")
                existing.detalhado = frase_data.get("det", {})
                existing.layout = frase_data.get("layout", "enxuto")
                existing.ativo = 1
                skipped += 1
                print(f"[UPDATE] {chave}")
            else:
                # Cria nova frase
                frase = FraseQualitativa(
                    chave=chave,
                    patologia=patologia,
                    grau=grau,
                    valvas=frase_data.get("valvas", ""),
                    camaras=frase_data.get("camaras", ""),
                    funcao=frase_data.get("funcao", ""),
                    pericardio=frase_data.get("pericardio", ""),
                    vasos=frase_data.get("vasos", ""),
                    ad_vd=frase_data.get("ad_vd", ""),
                    conclusao=frase_data.get("conclusao", ""),
                    detalhado=frase_data.get("det", {}),
                    layout=frase_data.get("layout", "enxuto"),
                    ativo=1,
                )
                db.add(frase)
                count += 1
                print(f"[ADD] {chave}")
        
        db.commit()
        print(f"\n[OK] {count} frases novas importadas!")
        print(f"[OK] {skipped} frases atualizadas!")
        print(f"[INFO] Total de frases no banco: {db.query(FraseQualitativa).count()}")
        
    except FileNotFoundError:
        print("[ERRO] Arquivo frases_personalizadas.json nao encontrado!")
    except Exception as e:
        print(f"[ERRO] {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    importar_frases()
