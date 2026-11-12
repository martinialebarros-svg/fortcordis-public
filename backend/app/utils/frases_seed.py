"""Dados iniciais para frases qualitativas"""

FRASES_PADRAO = [
    {
        "chave": "Normal (Normal)",
        "patologia": "Normal",
        "grau": "Normal",
        "valvas": "Valvas cardíacas com morfologia e funcionamento normais. Ausência de lesões valvares significativas.",
        "camaras": "Cavidades cardíacas com dimensões e paredes dentro dos limites da normalidade.",
        "funcao": "Função sistólica global preservada. Fração de encurtamento e fração de ejeção dentro da normalidade.",
        "pericardio": "Pericárdio sem alterações. Ausência de derrame pericárdico.",
        "vasos": "Grandes vasos com calibre e fluxo normais.",
        "ad_vd": "Átrio direito e ventrículo direito com dimensões normais.",
        "conclusao": "Ecocardiograma dentro dos limites da normalidade para a espécie.",
        "layout": "detalhado",
    },
    {
        "chave": "Endocardiose Mitral (Leve)",
        "patologia": "Endocardiose Mitral",
        "grau": "Leve",
        "valvas": "Valva mitral com espessamento leve dos folhetos, predominantemente na porção nodular. Coaptação preservada. Refluxo mitral leve ao Doppler.",
        "camaras": "Átrio esquerdo e ventrículo esquerdo com dimensões dentro da normalidade.",
        "funcao": "Função sistólica global preservada. Fração de encurtamento e fração de ejeção normais.",
        "pericardio": "Pericárdio sem alterações.",
        "vasos": "Grandes vasos normais.",
        "ad_vd": "Câmaras direitas normais.",
        "conclusao": "Endocardiose mitral leve (Estágio B1 - ACVIM). Refluxo mitral leve sem repercussão hemodinâmica significativa. Recomendado acompanhamento cardiológico periódico.",
        "layout": "detalhado",
    },
    {
        "chave": "Endocardiose Mitral (Moderada)",
        "patologia": "Endocardiose Mitral",
        "grau": "Moderada",
        "valvas": "Valva mitral com espessamento moderado dos folhetos e prolapsed leve. Coaptação parcialmente comprometida. Refluxo mitral moderado ao Doppler.",
        "camaras": "Leve aumento do átrio esquerdo. Ventrículo esquerdo com dimensão diastólica preservada.",
        "funcao": "Função sistólica global preservada. Fração de encurtamento e fração de ejeção dentro da normalidade.",
        "pericardio": "Pericárdio sem alterações.",
        "vasos": "Grandes vasos normais.",
        "ad_vd": "Câmaras direitas normais.",
        "conclusao": "Endocardiose mitral moderada (Estágio B2 - ACVIM). Refluxo mitral moderado com leve remodelamento atrial esquerdo. Recomendado controle clínico e ecocardiográfico periódico.",
        "layout": "detalhado",
    },
    {
        "chave": "Endocardiose Mitral (Importante)",
        "patologia": "Endocardiose Mitral",
        "grau": "Importante",
        "valvas": "Valva mitral com espessamento importante dos folhetos e prolapsed evidente. Coaptação severamente comprometida. Refluxo mitral importante/intenso ao Doppler.",
        "camaras": "Aumento moderado a importante do átrio esquerdo. Ventrículo esquerdo com dimensão diastólica aumentada.",
        "funcao": "Função sistólica global aparentemente preservada, porém com aumento da tensão parietal.",
        "pericardio": "Pericárdio sem alterações ou com mínimo derrame.",
        "vasos": "Grandes vasos normais.",
        "ad_vd": "Câmaras direitas com dimensões normais ou levemente aumentadas.",
        "conclusao": "Endocardiose mitral importante (Estágio C - ACVIM). Refluxo mitral importante com remodelamento cardíaco significativo. Recomendado tratamento medicamentoso e acompanhamento cardiológico rigoroso.",
        "layout": "detalhado",
    },
    {
        "chave": "Cardiomiopatia Dilatada (Leve)",
        "patologia": "Cardiomiopatia Dilatada",
        "grau": "Leve",
        "valvas": "Valvas com morfologia preservada. Refluxos valvares funcionais leves secundários à dilatação.",
        "camaras": "Leve aumento das dimensões do ventrículo esquerdo. Relação AE/Ao dentro da normalidade ou levemente aumentada.",
        "funcao": "Função sistólica global levemente reduzida. Fração de encurtamento e fração de ejeção levemente abaixo do normal.",
        "pericardio": "Pericárdio sem alterações.",
        "vasos": "Grandes vasos normais.",
        "ad_vd": "Câmaras direitas normais.",
        "conclusao": "Cardiomiopatia dilatada em fase inicial. Disfunção sistórica leve. Recomendado acompanhamento e avaliação para tratamento.",
        "layout": "detalhado",
    },
    {
        "chave": "Cardiomiopatia Dilatada (Moderada)",
        "patologia": "Cardiomiopatia Dilatada",
        "grau": "Moderada",
        "valvas": "Valvas com refluxos funcionais moderados secundários à dilatação das cavidades.",
        "camaras": "Aumento moderado das dimensões do ventrículo esquerdo e átrio esquerdo.",
        "funcao": "Função sistólica global moderadamente reduzida. Fração de encurtamento e fração de ejeção reduzidas.",
        "pericardio": "Pericárdio sem alterações.",
        "vasos": "Grandes vasos normais.",
        "ad_vd": "Câmaras direitas normais ou levemente aumentadas.",
        "conclusao": "Cardiomiopatia dilatada com disfunção sistórica moderada. Recomendado tratamento medicamentoso e acompanhamento cardiológico.",
        "layout": "detalhado",
    },
    {
        "chave": "Cardiomiopatia Dilatada (Grave)",
        "patologia": "Cardiomiopatia Dilatada",
        "grau": "Grave",
        "valvas": "Valvas com refluxos funcionais importantes secundários à dilatação severa das cavidades.",
        "camaras": "Aumento importante das dimensões do ventrículo esquerdo e átrio esquerdo. Remodelamento cardíaco severo.",
        "funcao": "Função sistólica global severamente reduzida. Fração de encurtamento e fração de ejeção significativamente diminuídas.",
        "pericardio": "Pericárdio sem alterações ou com derrame pericárdico.",
        "vasos": "Grandes vasos normais.",
        "ad_vd": "Câmaras direitas aumentadas (sinal de overload de volume).",
        "conclusao": "Cardiomiopatia dilatada grave com insuficiência cardíaca congestiva. Recomendado tratamento medicamentoso agressivo e acompanhamento cardiológico intensivo.",
        "layout": "detalhado",
    },
]


def seed_frases(db):
    """Adiciona frases padrão ao banco de dados se não existirem"""
    from app.models.frase import FraseQualitativa
    
    count = 0
    for frase_data in FRASES_PADRAO:
        # Verifica se já existe
        existing = db.query(FraseQualitativa).filter(
            FraseQualitativa.chave == frase_data["chave"]
        ).first()
        
        if not existing:
            frase = FraseQualitativa(**frase_data)
            db.add(frase)
            count += 1
    
    if count > 0:
        db.commit()
        print(f"[Seed] {count} frases qualitativas adicionadas.")
    else:
        print("[Seed] Frases qualitativas já existem.")
