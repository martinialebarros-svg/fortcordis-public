"""Baixa e importa frases do repositório GitHub"""
import json
import re
import urllib.request
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
    """Baixa e importa frases do GitHub"""
    db = SessionLocal()
    
    try:
        # URL do arquivo no GitHub
        url = "https://raw.githubusercontent.com/martinialebarros-svg/fortcordis-app/main/data/frases_personalizadas.json"
        
        print("[INFO] Baixando frases do GitHub...")
        
        # Baixar arquivo
        with urllib.request.urlopen(url) as response:
            dados = json.loads(response.read().decode('utf-8'))
        
        print(f"[INFO] {len(dados)} frases encontradas no arquivo")
        
        count = 0
        for chave, frase_data in dados.items():
            patologia, grau = parse_chave(chave)
            
            # Verifica se já existe
            existing = db.query(FraseQualitativa).filter(
                FraseQualitativa.chave == chave
            ).first()
            
            if existing:
                print(f"[SKIP] {chave}")
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
        print(f"[INFO] Total de frases no banco: {db.query(FraseQualitativa).count()}")
        
    except Exception as e:
        print(f"[ERRO] {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    importar_frases()
