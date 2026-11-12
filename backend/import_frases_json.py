"""Importa frases do arquivo frases_personalizadas.json do sistema antigo"""
import json
import re
from app.db.database import SessionLocal
from app.models.frase import FraseQualitativa

def parse_chave(chave: str):
    """Extrai patologia e grau da chave como 'Endocardiose Mitral (Leve)'"""
    match = re.match(r"(.+)\s*\(([^)]+)\)", chave)
    if match:
        patologia = match.group(1).strip()
        grau = match.group(2).strip()
    else:
        patologia = chave.strip()
        grau = "Normal"
    return patologia, grau

def importar_frases():
    """Importa frases do arquivo JSON"""
    db = SessionLocal()
    
    try:
        # Ler arquivo JSON
        with open("../fortcordis-app/data/frases_personalizadas.json", "r", encoding="utf-8") as f:
            dados = json.load(f)
        
        count = 0
        for chave, frase_data in dados.items():
            patologia, grau = parse_chave(chave)
            
            # Verifica se já existe
            existing = db.query(FraseQualitativa).filter(
                FraseQualitativa.chave == chave
            ).first()
            
            if existing:
                print(f"[SKIP] Frase ja existe: {chave}")
                continue
            
            # Monta a frase
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
        print(f"\n[OK] {count} frases importadas com sucesso!")
        
    except FileNotFoundError:
        print("[ERRO] Arquivo frases_personalizadas.json nao encontrado!")
        print("Certifique-se de que o arquivo esta em: ../fortcordis-app/data/frases_personalizadas.json")
    except Exception as e:
        print(f"[ERRO] {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    importar_frases()
