"""Modelo para tabelas de referência ecocardiográfica"""
from sqlalchemy import Column, Integer, Float, String
from app.db.database import Base


class ReferenciaEco(Base):
    """Tabela de referência ecocardiográfica por espécie e peso"""
    __tablename__ = "referencias_eco"
    
    id = Column(Integer, primary_key=True, index=True)
    especie = Column(String, nullable=False)  # 'Canina' ou 'Felina'
    peso_kg = Column(Float, nullable=False)   # Peso em kg
    
    # Medidas em mm (exceto onde indicado)
    # Câmaras
    lvid_d_min = Column(Float)  # LVIDd - Diâmetro do VE em diástole
    lvid_d_max = Column(Float)
    lvid_s_min = Column(Float)  # LVIDs - Diâmetro do VE em sístole
    lvid_s_max = Column(Float)
    
    # Paredes
    ivs_d_min = Column(Float)   # IVSd - Septo interventricular em diástole
    ivs_d_max = Column(Float)
    ivs_s_min = Column(Float)   # IVSs - Septo interventricular em sístole
    ivs_s_max = Column(Float)
    
    lvpw_d_min = Column(Float)  # LVPWd - Parede posterior do VE em diástole
    lvpw_d_max = Column(Float)
    lvpw_s_min = Column(Float)  # LVPWs - Parede posterior do VE em sístole
    lvpw_s_max = Column(Float)
    
    # Função (%)
    fs_min = Column(Float)      # Fração de encurtamento
    fs_max = Column(Float)
    ef_min = Column(Float)      # Fração de ejeção
    ef_max = Column(Float)
    
    # TAPSE e MAPSE (mm) - atualizada para mm em 2026-02-19
    tapse_min = Column(Float)   # Excursão sistólica plano anular tricúspide
    tapse_max = Column(Float)
    mapse_min = Column(Float)   # Excursão sistólica plano anular mitral
    mapse_max = Column(Float)
    
    # Grandes vasos (mm)
    ao_min = Column(Float)      # Aorta
    ao_max = Column(Float)
    la_min = Column(Float)      # Átrio esquerdo
    la_max = Column(Float)
    
    # Razões
    la_ao_min = Column(Float)   # Razão LA/Ao
    la_ao_max = Column(Float)
    
    # Artéria Pulmonar
    ap_min = Column(Float)      # Artéria pulmonar
    ap_max = Column(Float)
    ap_ao_min = Column(Float)   # Razão AP/Ao
    ap_ao_max = Column(Float)
    
    # Fluxos Doppler (m/s)
    vmax_ao_min = Column(Float)     # Vmax da aorta
    vmax_ao_max = Column(Float)
    vmax_pulm_min = Column(Float)   # Vmax da artéria pulmonar
    vmax_pulm_max = Column(Float)
    
    # Mitral (m/s)
    mv_e_min = Column(Float)        # Onda E da mitral
    mv_e_max = Column(Float)
    mv_a_min = Column(Float)        # Onda A da mitral
    mv_a_max = Column(Float)
    mv_ea_min = Column(Float)       # Razão E/A
    mv_ea_max = Column(Float)
    
    # Doppler Tecidual
    tdi_e_min = Column(Float)       # e' (cm/s)
    tdi_e_max = Column(Float)
    tdi_a_min = Column(Float)       # a' (cm/s)
    tdi_a_max = Column(Float)
    e_e_linha_min = Column(Float)   # E/E'
    e_e_linha_max = Column(Float)
    
    # Volumes (ml) - usado principalmente em caninos
    edv_min = Column(Float)         # Volume diastólico final
    edv_max = Column(Float)
    esv_min = Column(Float)         # Volume sistólico final
    esv_max = Column(Float)
    sv_min = Column(Float)          # Volume sistólico
    sv_max = Column(Float)
    
    # Outros tempos e medidas
    mv_dt_min = Column(Float)       # Deceleração da onda E (ms)
    mv_dt_max = Column(Float)
    ivrt_min = Column(Float)        # Tempo de relaxamento isovolumétrico (ms)
    ivrt_max = Column(Float)
