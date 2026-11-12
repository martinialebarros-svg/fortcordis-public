"use client";

import type { ReactNode } from "react";
import { normalizeEchoSpecies } from "@/lib/echo-species";
import { canonicalEchoDiastolicKey } from "@/lib/echo-diastolic-reference";
import { FelineDiastolicProtocol } from "./FelineDiastolicProtocol";

type Props = { especie?: string; medidas: Record<string, string>; onMedidaChange: (key: string, value: string) => void };
const FLOW = new Set(["Onda_E", "Onda_A", "E_A", "TD", "TRIV", "E_TRIV", "E_E_linha"]);
const TISSUE = new Set(["e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"]);

/** Confirm acquisition once per exam; never infer it from measured values. */
export function EchoDiastolicProtocol(props: Props) {
  const { especie, medidas, onMedidaChange } = props;
  const species = normalizeEchoSpecies(especie);
  if (species === "Felina") return <FelineDiastolicProtocol {...props} />;
  if (species !== "Canina") return null;
  const present = Object.entries(medidas).filter(([, value]) => {
    const number = Number(String(value).replace(",", "."));
    return Number.isFinite(number) && number > 0;
  }).map(([key]) => canonicalEchoDiastolicKey(key));
  const hasFlow = present.some((key) => FLOW.has(key)) || Boolean(medidas.Diastolica_ondas || medidas.Diastolica_metodo);
  const hasTissue = present.some((key) => TISSUE.has(key)) || Boolean(medidas.TDI_ondas || medidas.TDI_metodo);
  if (!hasFlow && !hasTissue) return null;
  const select = (key: string, label: string, options: ReactNode) => <div className="min-w-0">
    <label htmlFor={`canine-${key}`} className="mb-1 block text-sm font-medium text-blue-900">{label}</label>
    <select id={`canine-${key}`} value={medidas[key] || ""} onChange={(event) => onMedidaChange(key, event.target.value)}
      className="w-full rounded border border-blue-200 bg-white p-2 text-sm text-gray-900">{options}</select>
  </div>;
  const waves = (key: string, label: string) => select(key, label, <>
    <option value="">Separação não confirmada</option>
    {medidas[key] === "nao_confirmadas" && <option value="nao_confirmadas">Separação a reconfirmar</option>}
    <option value="separadas">Separadas e mensuráveis</option>
    <option value="fundidas">Fundidas</option>
  </>);
  return <section aria-label="Protocolo diastólico canino" className="space-y-3 rounded-lg bg-blue-50 p-3 text-left">
    <p className="text-sm font-medium text-blue-900">Protocolo diastólico canino</p>
    {hasFlow && <>
      <div className="grid gap-3 sm:grid-cols-2">
        {select("Diastolica_metodo", "Aquisição transmitral e TRIV", <>
          <option value="">Protocolo não confirmado</option>
          <option value="canino_nao_sedado_pw_apical">PW apical 4 câmaras; não sedado; FC 55–171 bpm (E)</option>
          <option value="canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo">Mesmo PW; 2–6 anos, 4,2–37,4 kg; TRIV pelo fim do fluxo</option>
          <option value="outro">Outro protocolo ou população</option>
        </>)}
        {waves("Diastolica_ondas", "Ondas transmitrais E/A")}
      </div>
      <p className="text-xs text-blue-800">Ao selecionar o protocolo, confirme Doppler pulsado na vista apical esquerda de 4 câmaras, amostra nas pontas dos folhetos mitrais, paciente não sedado, sem fármacos cardioativos e FC durante a aquisição entre 55 e 171 bpm. Essa FC é o domínio observado na publicação de Chompoosan (2022), sem representar limite clínico de normalidade.</p>
      <p className="text-xs text-blue-800">A segunda opção confirma também a população de Pereira (2009): 2–6 anos e 4,2–37,4 kg, com TRIV na vista apical de 5 câmaras, do fim do fluxo aórtico ao início mitral. A, E/A, TD e TRIV são médias ± DP; só E recebe intervalo de referência de 95%.</p>
    </>}
    {hasTissue && <>
      <div className="grid gap-3 sm:grid-cols-2">
        {select("TDI_metodo", "Técnica e sítio do Doppler tecidual", <>
          <option value="">Técnica e sítio não confirmados</option>
          <option value="canino_pw_anel_septal_choi">PW; anel mitral septal; 1–9,6 anos, 1,3–14 kg (Choi)</option>
          <option value="canino_pw_basal_septal_wess">PW; segmento basal septal; 1–14 anos, 3–55 kg (Wess)</option>
          <option value="canino_pw_basal_lateral_wess">PW; segmento basal lateral; 1–14 anos, 3–55 kg (Wess)</option>
          <option value="outro">Outra técnica, sítio ou população</option>
        </>)}
        {waves("TDI_ondas", "Ondas teciduais e'/a'")}
      </div>
      <p className="text-xs text-blue-800">Confirme paciente não sedado e o sítio medido: Choi (2013), anel mitral septal; Wess (2010), vista apical de 4 câmaras e amostra de 5 mm no segmento basal septal ou lateral do VE. Segmento basal, anel mitral e Doppler colorido não são intercambiáveis. As populações e valores de cada estudo acompanham o comparador.</p>
    </>}
    <p className="text-xs text-blue-800">Fusão E/A e fusão e&apos;/a&apos; são confirmações independentes. Valores dependentes de ondas fundidas não serão apresentados como mensuráveis no PDF; o registro original é preservado. Um índice isolado não define função diastólica.</p>
  </section>;
}
