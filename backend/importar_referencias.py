"""Script para importar referências ecocardiográficas dos CSVs"""
import csv
import io
import os
from pathlib import Path
from app.db.database import SessionLocal, engine, Base
from app.models.referencia_eco import ReferenciaEco

# Criar tabelas
Base.metadata.create_all(bind=engine)

# Caminhos: 1) variáveis de ambiente, 2) pasta data/ ao lado do backend, 3) fallback Desktop
_BASE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _BASE_DIR / "data"
_DEFAULT_CSV_CANINOS = os.environ.get(
    "REFERENCIAS_CSV_CANINOS",
    str(_DATA_DIR / "tabela_referencia_caninos.csv"),
)
_DEFAULT_CSV_FELINOS = os.environ.get(
    "REFERENCIAS_CSV_FELINOS",
    str(_DATA_DIR / "tabela_referencia_felinos.csv"),
)
_FALLBACK_CANINOS = r"C:\Users\marti\Desktop\FortCordis_Novo\tabela_referencia_caninos.csv"
_FALLBACK_FELINOS = r"C:\Users\marti\Desktop\FortCordis_Novo\tabela_referencia_felinos.csv"

# Mapeamento de colunas do CSV para campos do modelo (usado por importar_csv e pela API)
mapeamento_caninos = {
    'Peso (kg)': 'peso_kg',
    'LVIDd_Min': 'lvid_d_min',
    'LVIDd_Max': 'lvid_d_max',
    'IVSd_Min': 'ivs_d_min',
    'IVSd_Max': 'ivs_d_max',
    'LVPWd_Min': 'lvpw_d_min',
    'LVPWd_Max': 'lvpw_d_max',
    'LVIDs_Min': 'lvid_s_min',
    'LVIDs_Max': 'lvid_s_max',
    'IVSs_Min': 'ivs_s_min',
    'IVSs_Max': 'ivs_s_max',
    'LVPWs_Min': 'lvpw_s_min',
    'LVPWs_Max': 'lvpw_s_max',
    'EDV_Min': 'edv_min',
    'EDV_Max': 'edv_max',
    'ESV_Min': 'esv_min',
    'ESV_Max': 'esv_max',
    'SV_Min': 'sv_min',
    'SV_Max': 'sv_max',
    'EF_Min': 'ef_min',
    'EF_Max': 'ef_max',
    'FS_Min': 'fs_min',
    'FS_Max': 'fs_max',
    'Ao_Min': 'ao_min',
    'Ao_Max': 'ao_max',
    'LA_Min': 'la_min',
    'LA_Max': 'la_max',
    'LA_Ao_Min': 'la_ao_min',
    'LA_Ao_Max': 'la_ao_max',
    'Vmax_Ao_Min': 'vmax_ao_min',
    'Vmax_Ao_Max': 'vmax_ao_max',
    'Vmax_Pulm_Min': 'vmax_pulm_min',
    'Vmax_Pulm_Max': 'vmax_pulm_max',
    'MV_E_Min': 'mv_e_min',
    'MV_E_Max': 'mv_e_max',
    'MV_A_Min': 'mv_a_min',
    'MV_A_Max': 'mv_a_max',
    'MV_E_A_Min': 'mv_ea_min',
    'MV_E_A_Max': 'mv_ea_max',
    'MV_DT_Min': 'mv_dt_min',
    'MV_DT_Max': 'mv_dt_max',
    'IVRT_Min': 'ivrt_min',
    'IVRT_Max': 'ivrt_max',
}

mapeamento_felinos = {
    'Peso': 'peso_kg',
    'IVSd_Min': 'ivs_d_min',
    'IVSd_Max': 'ivs_d_max',
    'LVIDd_Min': 'lvid_d_min',
    'LVIDd_Max': 'lvid_d_max',
    'LVPWd_Min': 'lvpw_d_min',
    'LVPWd_Max': 'lvpw_d_max',
    'IVSs_Min': 'ivs_s_min',
    'IVSs_Max': 'ivs_s_max',
    'LVIDs_Min': 'lvid_s_min',
    'LVIDs_Max': 'lvid_s_max',
    'LVPWs_Min': 'lvpw_s_min',
    'LVPWs_Max': 'lvpw_s_max',
    'FS_Min': 'fs_min',
    'FS_Max': 'fs_max',
    'EF_Min': 'ef_min',
    'EF_Max': 'ef_max',
    'LA_Min': 'la_min',
    'LA_Max': 'la_max',
    'Ao_Min': 'ao_min',
    'Ao_Max': 'ao_max',
    'LA_Ao_Min': 'la_ao_min',
    'LA_Ao_Max': 'la_ao_max',
}


def importar_csv(caminho, especie):
    """Importa dados de um arquivo CSV"""
    db = SessionLocal()
    mapeamento = mapeamento_caninos if especie == 'Canina' else mapeamento_felinos
    count = 0
    with open(caminho, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dados = {'especie': especie}
            for csv_col, db_col in mapeamento.items():
                valor = row.get(csv_col, '').strip()
                if valor and valor.replace('.', '').replace('-', '').isdigit():
                    dados[db_col] = float(valor)
                else:
                    dados[db_col] = None
            ref = ReferenciaEco(**dados)
            db.add(ref)
            count += 1
    db.commit()
    db.close()
    print(f"Importadas {count} referências para {especie}")
    return count


def importar_csv_from_content(content: str, especie: str, db) -> int:
    """Importa referências a partir do conteúdo CSV (string). Remove as existentes da espécie."""
    mapeamento = mapeamento_caninos if especie == 'Canina' else mapeamento_felinos
    db.query(ReferenciaEco).filter(ReferenciaEco.especie == especie).delete()
    count = 0
    for row in csv.DictReader(io.StringIO(content)):
        dados = {'especie': especie}
        for csv_col, db_col in mapeamento.items():
            valor = row.get(csv_col, '').strip()
            if valor and valor.replace('.', '').replace('-', '').isdigit():
                dados[db_col] = float(valor)
            else:
                dados[db_col] = None
        ref = ReferenciaEco(**dados)
        db.add(ref)
        count += 1
    db.commit()
    return count


if __name__ == "__main__":
    csv_caninos = _DEFAULT_CSV_CANINOS if os.path.exists(_DEFAULT_CSV_CANINOS) else _FALLBACK_CANINOS
    csv_felinos = _DEFAULT_CSV_FELINOS if os.path.exists(_DEFAULT_CSV_FELINOS) else _FALLBACK_FELINOS

    if os.path.exists(csv_caninos):
        importar_csv(csv_caninos, 'Canina')
    else:
        print(f"Arquivo não encontrado: {csv_caninos}")

    if os.path.exists(csv_felinos):
        importar_csv(csv_felinos, 'Felina')
    else:
        print(f"Arquivo não encontrado: {csv_felinos}")

    print("Importação concluída!")
