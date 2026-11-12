export interface EchoRangeMetadata {
  status: "published" | "requires_method" | "blocked" | "unavailable" | "catalog" | "estimated";
  reason?: string;
  source?: string;
  doi?: string;
  statistic?: string;
  population?: string;
  min_weight_kg?: number | null;
  max_weight_kg?: number | null;
  candidate_min?: number | null;
  candidate_max?: number | null;
  candidate_weight_kg?: number | null;
  model_weight_kg?: number;
  estimate_min?: number;
  estimate_max?: number;
  estimate_context?: "age_unconfirmed" | "weight_extrapolation";
  calculation?: "allometric" | "interpolated" | "tabulated" | "extrapolated";
  formula?: string;
  exponent?: number;
  required_measurement_key?: string;
  required_measurement_value?: string;
  required_method?: string;
  clinical_threshold?: { operator?: string; value?: number; source?: string; description?: string } | number | string;
}

export interface ReferenciaEco {
  id: number;
  especie: "Canina" | "Felina";
  peso_kg: number;
  policy_version?: string;
  patient_weight_kg?: number;
  patient_age?: string | null;
  reference_origin?: "computed";
  catalog_weight_min?: number | null;
  catalog_weight_max?: number | null;
  catalog_ranges?: Record<string, { min?: number | null; max?: number | null }>;
  range_metadata?: Record<string, EchoRangeMetadata>;
  
  // Medidas estruturais (VE - Modo M)
  lvid_d_min?: number | null;
  lvid_d_max?: number | null;
  lvid_s_min?: number | null;
  lvid_s_max?: number | null;
  ivs_d_min?: number | null;
  ivs_d_max?: number | null;
  ivs_s_min?: number | null;
  ivs_s_max?: number | null;
  lvpw_d_min?: number | null;
  lvpw_d_max?: number | null;
  lvpw_s_min?: number | null;
  lvpw_s_max?: number | null;
  
  // Função
  fs_min?: number;
  fs_max?: number;
  fs_source?: string;
  ef_reference_note?: string;
  ef_min?: number;
  ef_max?: number;
  tapse_min?: number;
  tapse_max?: number;
  mapse_min?: number;
  mapse_max?: number;
  
  // Vasos (Aorta e Átrio Esquerdo)
  ao_min?: number;
  ao_max?: number;
  la_min?: number;
  la_max?: number;
  la_ao_min?: number;
  la_ao_max?: number;
  
  // Artéria Pulmonar
  ap_min?: number;
  ap_max?: number;
  ap_ao_min?: number;
  ap_ao_max?: number;
  
  // Doppler (Diastólica)
  vmax_ao_min?: number;
  vmax_ao_max?: number;
  vmax_pulm_min?: number;
  vmax_pulm_max?: number;
  mv_e_min?: number;
  mv_e_max?: number;
  mv_a_min?: number;
  mv_a_max?: number;
  mv_ea_min?: number;
  mv_ea_max?: number;
  mv_dt_min?: number;
  mv_dt_max?: number;
  ivrt_min?: number;
  ivrt_max?: number;
  tdi_e_min?: number;
  tdi_e_max?: number;
  tdi_a_min?: number;
  tdi_a_max?: number;
  e_e_linha_min?: number;
  e_e_linha_max?: number;
  
  // Volumes
  edv_min?: number;
  edv_max?: number;
  esv_min?: number;
  esv_max?: number;
  sv_min?: number;
  sv_max?: number;
}

export interface ComparacaoMedida {
  nome: string;
  valor_medido: string;
  referencia_texto?: string;
  nota_referencia?: string;
  referencia_tipo?: "reference_interval" | "descriptive" | "uninterpretable" | "unconfirmed" | "clinical_limit";
  estatistica?: string;
  doi?: string;
  fonte?: string;
  metadados?: EchoRangeMetadata;
  referencia_min: number | null;
  referencia_max: number | null;
  status: "normal" | "aumentado" | "diminuido" | "nao_avaliado";
  interpretacao: string;
  categoria: string;
}

export interface ReferenciaFormData {
  especie: "Canina" | "Felina";
  peso_kg: number;
  
  // Medidas estruturais (VE - Modo M)
  lvid_d_min?: number;
  lvid_d_max?: number;
  lvid_s_min?: number;
  lvid_s_max?: number;
  ivs_d_min?: number;
  ivs_d_max?: number;
  ivs_s_min?: number;
  ivs_s_max?: number;
  lvpw_d_min?: number;
  lvpw_d_max?: number;
  lvpw_s_min?: number;
  lvpw_s_max?: number;
  
  // Função
  fs_min?: number;
  fs_max?: number;
  ef_min?: number;
  ef_max?: number;
  tapse_min?: number;
  tapse_max?: number;
  mapse_min?: number;
  mapse_max?: number;
  
  // Vasos (Aorta e Átrio Esquerdo)
  ao_min?: number;
  ao_max?: number;
  la_min?: number;
  la_max?: number;
  la_ao_min?: number;
  la_ao_max?: number;
  
  // Artéria Pulmonar
  ap_min?: number;
  ap_max?: number;
  ap_ao_min?: number;
  ap_ao_max?: number;
  
  // Doppler (Diastólica)
  vmax_ao_min?: number;
  vmax_ao_max?: number;
  vmax_pulm_min?: number;
  vmax_pulm_max?: number;
  mv_e_min?: number;
  mv_e_max?: number;
  mv_a_min?: number;
  mv_a_max?: number;
  mv_ea_min?: number;
  mv_ea_max?: number;
  mv_dt_min?: number;
  mv_dt_max?: number;
  ivrt_min?: number;
  ivrt_max?: number;
  tdi_e_min?: number;
  tdi_e_max?: number;
  tdi_a_min?: number;
  tdi_a_max?: number;
  e_e_linha_min?: number;
  e_e_linha_max?: number;
  
  // Volumes
  edv_min?: number;
  edv_max?: number;
  esv_min?: number;
  esv_max?: number;
  sv_min?: number;
  sv_max?: number;
}
