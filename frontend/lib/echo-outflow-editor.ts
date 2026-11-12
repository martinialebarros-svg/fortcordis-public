import { deriveOutflowGradients, ECHO_OUTFLOW_KEYS, isOutflowMetadataKey } from "./echo-outflow";

type Measurements = Record<string, string>;

/** Keep source labels and numerical precision from explicit acquisitions. */
export function mapImportedEchoMeasurements(medidasOriginais: Record<string, number | string>): Record<string, string> {
  const mapeamento: Record<string, string> = {
    // Campos em inglês (XML cru) -> nomes em português
    "LVIDd": "DIVEd",
    "LVIDs": "DIVES",
    "IVSd": "SIVd",
    "IVSs": "SIVs",
    "LVPWd": "PLVEd",
    "LVPWs": "PLVES",
    "EDV": "VDF",
    "ESV": "VSF",
    "EF": "FE_Teicholz",
    "FS": "DeltaD_FS",
    "LA": "Atrio_esquerdo",
    "Ao": "Aorta",
    "LA_Ao": "AE_Ao",
    "MV_E": "Onda_E",
    "MV_A": "Onda_A",
    "MV_E_A": "E_A",
    "MV_E_TRIV": "E_TRIV",
    "MV_DT": "TD",
    "IVRT": "TRIV",
    "TDI_e": "e_doppler",
    "TDI_a": "a_doppler",
    "TDI e": "e_doppler",
    "TDI a": "a_doppler",
    "Aprime": "a_doppler",
    "Aprime_Velocity": "a_doppler",
    "a_prime": "a_doppler",
    "EEp": "E_E_linha",
    "PA": "AP",
    "PA_Ao": "AP_Ao",
    "PA/Ao": "AP_Ao",
    "Ao_AP": "Ao_nivel_AP",
    "Vmax_Ao": "Vmax_aorta",
    "Grad_Ao": "Grad_aorta",
    "Vmax_Pulm": "Vmax_pulmonar",
    "Grad_Pulm": "Grad_pulmonar",
    "MR_Vmax": "IM_Vmax",
    "TR_Vmax": "IT_Vmax",
    "AR_Vmax": "IA_Vmax",
    "PR_Vmax": "IP_Vmax",
    "DIVdN": "DIVEd_normalizado",
    // Campos já em português (XML já processado pelo backend) -> mesmos nomes
    "DIVEd": "DIVEd",
    "DIVES": "DIVES",
    "SIVd": "SIVd",
    "SIVs": "SIVs",
    "PLVEd": "PLVEd",
    "PLVES": "PLVES",
    "VDF": "VDF",
    "VSF": "VSF",
    "FE_Teicholz": "FE_Teicholz",
    "DeltaD_FS": "DeltaD_FS",
    "Atrio_esquerdo": "Atrio_esquerdo",
    "Aorta": "Aorta",
    "AE_Ao": "AE_Ao",
    "Onda_E": "Onda_E",
    "Onda_A": "Onda_A",
    "E_A": "E_A",
    "E_TRIV": "E_TRIV",
    "E/TRIV": "E_TRIV",
    "TD": "TD",
    "TRIV": "TRIV",
    "e_doppler": "e_doppler",
    "a_doppler": "a_doppler",
    "E_E_linha": "E_E_linha",
    "Vmax_aorta": "Vmax_aorta",
    "Grad_aorta": "Grad_aorta",
    "Vmax_pulmonar": "Vmax_pulmonar",
    "Grad_pulmonar": "Grad_pulmonar",
    "IM_Vmax": "IM_Vmax",
    "IT_Vmax": "IT_Vmax",
    "IA_Vmax": "IA_Vmax",
    "IP_Vmax": "IP_Vmax",
    "DIVEd_normalizado": "DIVEd_normalizado",
    "TAPSE": "TAPSE",
    "MAPSE": "MAPSE",
    "Ao_nivel_AP": "Ao_nivel_AP",
    "AP": "AP",
    "AP_Ao": "AP_Ao",
    "MR_dp_dt": "MR_dp_dt",
    "doppler_tecidual_relacao": "doppler_tecidual_relacao",
  };

  const medidasFormatadas: Record<string, string> = {};
  
  Object.entries(medidasOriginais).forEach(([key, value]) => {
    if (value === null || value === undefined || String(value).trim() === "") return;
    const metadataSuffix = ["_rotulo_origem", "_origem"].find((suffix) => key.endsWith(suffix));
    const baseKey = metadataSuffix ? key.slice(0, -metadataSuffix.length) : key;
    const novoNome = `${mapeamento[baseKey] || baseKey}${metadataSuffix || ""}`;
    if (isOutflowMetadataKey(novoNome) && metadataSuffix === "_origem"
        && !["importado", "informado", "calculado"].includes(String(value))) return;
    if (
      novoNome === "VE_tecnica_relatorio" ||
      novoNome === "Remodelamento_AD" ||
      ECHO_OUTFLOW_KEYS.has(novoNome) ||
      isOutflowMetadataKey(novoNome) ||
      Number.isFinite(Number(String(value).replace(",", ".")))
    ) {
      medidasFormatadas[novoNome] = value.toString();
    }
  });
  
  return medidasFormatadas;
}

/** A deliberate operator correction owns only the edited value. An independent
 * imported or historical gradient survives a velocity correction. */
export function updateEchoOutflowMeasurement(measurements: Measurements, key: string, value: string): Measurements {
  if (!ECHO_OUTFLOW_KEYS.has(key) || measurements[key] === value) return measurements;
  const next = { ...measurements, [key]: value };
  delete next[`${key}_rotulo_origem`];
  if (value.trim()) next[`${key}_origem`] = "informado";
  else delete next[`${key}_origem`];
  return { ...next, ...deriveOutflowGradients(next) };
}

/** A new imported acquisition cannot inherit the previous acquisition's source
 * attribution when the new file does not provide that attribution. */
export function clearReplacedOutflowProvenance(measurements: Measurements, imported: Measurements): Measurements {
  const next = { ...measurements };
  for (const key of ECHO_OUTFLOW_KEYS) {
    if (!Object.hasOwn(imported, key)) continue;
    for (const suffix of ["_origem", "_rotulo_origem"]) {
      if (!Object.hasOwn(imported, `${key}${suffix}`)) delete next[`${key}${suffix}`];
    }
  }
  return next;
}
