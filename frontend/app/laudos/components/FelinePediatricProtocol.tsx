"use client";

import { felinePediatricReference, FELINE_PEDIATRIC_PROTOCOL } from "@/lib/echo-feline-pediatric-reference";

interface Props {
  especie?: string;
  peso?: number;
  idade?: string | null;
  medidas: Record<string, string>;
  onMedidaChange: (key: string, value: string) => void;
}

export function FelinePediatricProtocol({ especie, peso, idade, medidas, onMedidaChange }: Props) {
  const reference = felinePediatricReference(especie, peso, idade, medidas);
  if (!reference) return null;
  return (
    <section className="space-y-3 rounded-lg border border-teal-200 bg-teal-50 p-3 text-left text-teal-950" aria-label="Referências pediátricas felinas">
      <p className="font-semibold">Referências para filhotes felinos · 6–16 semanas</p>
      <p className="text-sm">{reference.population}</p>
      <p className="text-sm">{reference.reason}</p>
      <p className="text-xs"><a href={`https://doi.org/${reference.doi}`} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">{reference.source}</a></p>
      <label htmlFor="protocolo-pediatrico-felino" className="block text-sm font-medium">Protocolo de aquisição pediátrico</label>
      <select id="protocolo-pediatrico-felino" value={medidas.Pediatria_protocolo || ""}
        onChange={(event) => onMedidaChange("Pediatria_protocolo", event.target.value)}
        className="w-full rounded border border-teal-300 bg-white p-2 text-sm text-gray-900">
        <option value="">Protocolo não confirmado</option>
        <option value={FELINE_PEDIATRIC_PROTOCOL}>Sem sedação; técnicas da publicação confirmadas para as medidas obtidas</option>
        <option value="outro">Sedação ou outro protocolo</option>
      </select>
      <p className="text-xs leading-relaxed">VE: modo M em eixo curto paraesternal direito, no nível das cordoalhas, ou 2D em eixo longo paraesternal direito, pela convenção leading edge da publicação. A técnica selecionada na aba Medidas deve corresponder à aquisição.</p>
      <p className="text-xs leading-relaxed">Doppler aórtico: contínuo (CW), janela apical esquerda. Doppler pulmonar: pulsado (PW), janela paraesternal direita, imediatamente após a valva pulmonar. Os intervalos não são intercambiáveis com outras técnicas.</p>
      {medidas.VE_tecnica_relatorio === "2d" && <>
        <label htmlFor="plano-pediatrico-2d" className="block text-sm font-medium">Vista 2D do ventrículo esquerdo</label>
        <select id="plano-pediatrico-2d" value={medidas.VE_vista_2D || ""}
          onChange={(event) => onMedidaChange("VE_vista_2D", event.target.value)}
          className="w-full rounded border border-teal-300 bg-white p-2 text-sm text-gray-900">
          <option value="">Vista não confirmada</option>
          <option value="eixo_longo">Eixo longo paraesternal direito</option>
          <option value="eixo_curto">Eixo curto (sem intervalo pediátrico 2D nesta fonte)</option>
        </select>
      </>}
    </section>
  );
}
