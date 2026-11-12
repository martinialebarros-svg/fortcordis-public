"use client";

import { useState, useEffect, useMemo } from "react";
import { CheckCircle, AlertCircle, AlertTriangle, ArrowUp, ArrowDown, Minus } from "lucide-react";
import { isFelineEchoSpecies, normalizeEchoSpecies } from "@/lib/echo-species";
import { compararMedidasDiastolicas, useReferenciaEco } from "../hooks/useReferenciaEco";
import { ComparacaoMedida, ReferenciaEco } from "../types/referencia-eco";
import { deriveLeftVentricularFunctionForReference } from "@/lib/echo-derived-measurements";
import { canineAeAoClinicalReference, prepareEchoReportMeasurements } from "@/lib/echo-report-presentation";
import type { Echo2DView } from "@/lib/echo-2d-reference";
import { EchoDiastolicProtocol } from "./EchoDiastolicProtocol";
import { resolveEchoReferenceForMeasurements } from "@/lib/echo-reference-policy";
import { makeLowWeightReference } from "@/lib/echo-low-weight-reference";

interface ReferenciaComparisonProps {
  especie?: "Canina" | "Felina" | string;
  peso?: number;
  idade?: string | null;
  medidas: Record<string, string>;
  onMedidaChange: (key: string, value: string) => void;
}

const CATEGORIAS = {
  estrutural: { label: "Medidas Estruturais", icon: "📏" },
  funcao: { label: "Função", icon: "💓" },
  vasos: { label: "Vasos", icon: "🩸" },
  doppler: { label: "Doppler", icon: "〰️" },
};

const formatarPeso = (valor: number) => new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(valor);
const positive = (value: unknown) => Number(String(value ?? "").replace(",", ".")) > 0;

export function ReferenciaComparison({ especie, peso, idade, medidas, onMedidaChange }: ReferenciaComparisonProps) {
  const { buscarReferencia, compararMedidas, loading } = useReferenciaEco();
  const [referencia, setReferencia] = useState<ReferenciaEco | null>(null);
  const plano2D: Echo2DView | "" = medidas.VE_vista_2D === "eixo_curto" || medidas.VE_vista_2D === "eixo_longo"
    ? medidas.VE_vista_2D
    : "";
  const { measurements: medidasSeguras, ambiguousKeys: unidadesAmbiguas } = useMemo(
    () => {
      const { measurements, ambiguousKeys } = prepareEchoReportMeasurements(medidas, peso, especie, idade);
      for (const key of ambiguousKeys) delete measurements[key];
      return { measurements, ambiguousKeys };
    },
    [medidas, peso, especie, idade]
  );
  const medidasDerivadasParaReferencia = useMemo(
    () => deriveLeftVentricularFunctionForReference(medidasSeguras),
    [medidasSeguras]
  );
  const medidasParaReferencia = useMemo(
    () => ({ ...medidasSeguras, ...medidasDerivadasParaReferencia }),
    [medidasSeguras, medidasDerivadasParaReferencia]
  );
  const referenciasDiastolicas = useMemo(
    () => compararMedidasDiastolicas(medidasParaReferencia, especie ?? ""),
    [medidasParaReferencia, especie],
  );
  // This clinical limit is independent of the weight-based catalog, but its
  // acquisition must still be confirmed for the current examination.
  const aeAoCanino = Number(String(medidasSeguras.AE_Ao ?? medidasSeguras.LA_Ao ?? "").replace(",", "."));
  const limiteAeAoCanino = canineAeAoClinicalReference(medidasSeguras, especie ?? "", unidadesAmbiguas);
  const comparacoes = useMemo(() => {
    const catalogo = referencia ? compararMedidas(medidasParaReferencia, referencia, plano2D, peso) : {};
    const linhas: Record<string, ComparacaoMedida> = { ...catalogo, ...referenciasDiastolicas };
    if (limiteAeAoCanino) {
      delete linhas.LA_Ao;
      linhas.AE_Ao = {
        nome: "AE/Ao",
        valor_medido: medidasSeguras.AE_Ao,
        referencia_tipo: "clinical_limit",
        referencia_texto: limiteAeAoCanino,
        referencia_min: null,
        referencia_max: null,
        fonte: "Rishniw (2023)",
        doi: "10.1016/j.jvc.2023.04.003",
        status: "nao_avaliado",
        categoria: "vasos",
        interpretacao: "Interpretar com os demais achados; este limite não determina diagnóstico ou estágio isoladamente.",
      };
    }
    return linhas;
  }, [referencia, compararMedidas, medidasParaReferencia, plano2D, peso, referenciasDiastolicas, limiteAeAoCanino, medidasSeguras.AE_Ao]);
  const origemAeAoAmbigua = ["AE_Ao", "Aorta", "Atrio_esquerdo"].some((key) => unidadesAmbiguas.has(key));
  const metodoAeAoCanino = normalizeEchoSpecies(especie) === "Canina" && !origemAeAoAmbigua && Number.isFinite(aeAoCanino) && aeAoCanino > 0 ? (
    <div className="p-3 bg-blue-50 rounded-lg space-y-2 text-left">
      <label htmlFor="metodo-ae-ao-canino" className="block text-sm font-medium text-blue-900">Método de obtenção de AE/Ao</label>
      <select id="metodo-ae-ao-canino" value={medidas.AE_Ao_metodo || ""}
        onChange={(event) => onMedidaChange("AE_Ao_metodo", event.target.value)}
        className="w-full sm:w-auto rounded border border-blue-200 bg-white p-2 text-sm text-gray-900">
        <option value="">Método não confirmado</option>
        <option value="2d_eixo_curto_diastole_inicial">Cão; 2D, eixo curto paraesternal direito, início da diástole</option>
        <option value="2d_eixo_curto_diastole_inicial_sueco">Método sueco (Hansson et al., 2002); 2D, eixo curto, início da diástole</option>
        <option value="outro">Outra vista ou fase</option>
      </select>
      <p className="text-xs text-blue-800">Confirme a medida na base do coração, na primeira imagem após o fechamento da valva aórtica, com bordas internas e exclusão das veias pulmonares.</p>
      {medidas.AE_Ao_metodo === "2d_eixo_curto_diastole_inicial_sueco" && (
        <p className="text-xs text-blue-800">Método sueco: meça a aorta do ponto médio da parede interna da cúspide coronariana direita até a comissura entre as cúspides não coronariana e coronariana esquerda. Prolongue esse eixo pelo átrio esquerdo até sua parede interna oposta, excluindo as veias pulmonares.
          {limiteAeAoCanino && " O PDF citará Hansson et al. (2002) como fonte da técnica."}</p>
      )}
      {limiteAeAoCanino && (
        <p className="text-xs text-blue-800">O PDF apresentará AE/Ao &lt; 1,60 como limite clínico orientativo (Rishniw, 2023). Interprete com os demais achados; não é um intervalo por peso nem determina diagnóstico ou estágio isoladamente.</p>
      )}
    </div>
  ) : null;

  useEffect(() => {
    const pesoValido = typeof peso === "number" && Number.isFinite(peso) && peso > 0;
    let ativo = true;

    async function carregarReferencia() {
      if (especie && pesoValido) {
        setReferencia(null);
        const ref = await buscarReferencia(especie, peso, idade);
        if (ativo) setReferencia(resolveEchoReferenceForMeasurements(
          ref || makeLowWeightReference(especie, peso, 0, {}, idade), {}, peso, idade,
        ));
        return;
      }

      setReferencia(null);
    }

    void carregarReferencia();
    return () => {
      ativo = false;
    };
  }, [especie, peso, idade, buscarReferencia]);

  if (loading && !limiteAeAoCanino && Object.keys(referenciasDiastolicas).length === 0) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-teal-600"></div>
      </div>
    );
  }

  if (!referencia && Object.keys(comparacoes).length === 0) {
    return (
      <div className="space-y-4 py-8 text-center text-gray-500">
        <AlertCircle className="w-12 h-12 mx-auto mb-3 text-gray-400" />
        <p className="text-lg font-medium mb-1">Nenhuma referência encontrada</p>
        <p className="text-sm">
          {!especie || !(typeof peso === "number" && Number.isFinite(peso) && peso > 0)
            ? "Preencha os dados do paciente (espécie e peso) para visualizar as referências."
            : `Não há referência cadastrada para ${especie} com ${peso}kg.`}
        </p>
        {metodoAeAoCanino}
        <EchoDiastolicProtocol especie={especie} medidas={medidas} onMedidaChange={onMedidaChange} />
      </div>
    );
  }

  // Agrupar comparações por categoria
  const porCategoria: Record<string, Array<{key: string} & ComparacaoMedida>> = {};
  const temMedidas2D = Object.keys(medidasParaReferencia).some((key) => key.endsWith("_2D"));
  const calculatedMetadata = Object.values(referencia?.range_metadata || {}).find((meta) => meta.model_weight_kg != null);
  Object.entries(comparacoes).forEach(([key, comp]) => {
    const categoria = comp.categoria || "outros";
    if (!porCategoria[categoria]) {
      porCategoria[categoria] = [];
    }
    porCategoria[categoria].push({ key, ...comp });
  });

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "normal":
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case "aumentado":
        return <ArrowUp className="w-4 h-4 text-red-500" />;
      case "diminuido":
        return <ArrowDown className="w-4 h-4 text-blue-500" />;
      default:
        return <Minus className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusClass = (status: string) => {
    switch (status) {
      case "normal":
        return "bg-green-50 border-green-200";
      case "aumentado":
        return "bg-red-50 border-red-200";
      case "diminuido":
        return "bg-blue-50 border-blue-200";
      case "nao_avaliado":
        return "bg-white border-gray-200";
      default:
        return "bg-white border-gray-200";
    }
  };

  const getStatusTextClass = (status: string) => {
    switch (status) {
      case "normal":
        return "text-green-700";
      case "aumentado":
        return "text-red-700";
      case "diminuido":
        return "text-blue-700";
      default:
        return "text-gray-500";
    }
  };

  return (
    <div className="space-y-6">
      {referencia ? <div className="flex items-center gap-2 p-3 bg-teal-50 rounded-lg">
        <span className="text-lg">📊</span>
        <div>
          <p className="font-medium text-teal-900">
            {referencia.reference_origin === "computed"
              ? `Referência calculada: ${referencia.especie || especie}, peso de ${formatarPeso(referencia.patient_weight_kg ?? referencia.peso_kg)} kg`
              : `Referência selecionada: ${referencia.especie || especie}, cadastro de ${formatarPeso(referencia.peso_kg)} kg`}
          </p>
          {calculatedMetadata && <p className="mt-1 text-xs text-teal-800">{calculatedMetadata.reason}</p>}
          <p className="text-sm text-teal-700">
            Peso do paciente: {typeof peso === "number" ? formatarPeso(peso) : "—"} kg. Faixas aplicáveis dependem do método, peso e fonte identificada.
          </p>
          {Object.keys(medidasDerivadasParaReferencia).length > 0 && (
            <p className="text-xs text-teal-700 mt-1">
              FE e/ou encurtamento foram calculados a partir das medidas do VE apenas para esta comparação.
            </p>
          )}
        </div>
      </div> : <p className="rounded-lg bg-teal-50 p-3 text-sm text-teal-900">Referências: estudos publicados independentes do cadastro por peso.</p>}

      <EchoDiastolicProtocol especie={especie} medidas={medidas} onMedidaChange={onMedidaChange} />

      {temMedidas2D && /^canin/i.test(referencia?.especie ?? "") && (
        <div className="p-3 bg-blue-50 rounded-lg space-y-2">
          <label htmlFor="plano-referencia-2d" className="block text-sm font-medium text-blue-900">
            Confirme cão adulto e vista 2D do ventrículo esquerdo
          </label>
          <select
            id="plano-referencia-2d"
            value={plano2D}
            onChange={(event) => onMedidaChange("VE_vista_2D", event.target.value)}
            className="w-full sm:w-auto rounded border border-blue-200 bg-white p-2 text-sm text-gray-900"
          >
            <option value="">Vista não confirmada</option>
            <option value="eixo_curto">Cão adulto; eixo curto direito, músculos papilares</option>
            <option value="eixo_longo">Cão adulto; eixo longo direito, quatro câmaras</option>
          </select>
          <p className="text-xs text-blue-800">
            Confirme que DIVEd e DIVEs 2D foram medidos na mesma vista. Só esses diâmetros e o encurtamento
            compatível com esse par serão comparados com faixas 2D específicas de Visser et al. (2019), para cães adultos
            entre 2,6 e 67,8 kg. Septo e parede não têm faixa 2D por peso nas fontes adotadas; volumes e FE por
            Teichholz não são comparados aos intervalos obtidos por Simpson.
          </p>
        </div>
      )}

      {positive(medidas.TAPSE) && /^canin/i.test(referencia?.especie ?? "") && (
        <div className="p-3 bg-blue-50 rounded-lg space-y-2">
          <label htmlFor="metodo-tapse" className="block text-sm font-medium text-blue-900">Método de obtenção do TAPSE</label>
          <select id="metodo-tapse" value={medidas.TAPSE_metodo || ""}
            onChange={(event) => onMedidaChange("TAPSE_metodo", event.target.value)}
            className="w-full sm:w-auto rounded border border-blue-200 bg-white p-2 text-sm text-gray-900">
            <option value="">Método não confirmado</option>
            <option value="modo_m_apical">Cão adulto; modo M, vista apical esquerda, quatro câmaras</option>
            <option value="2d">2D</option>
          </select>
          <p className="text-xs text-blue-800">A faixa de Visser et al. (2015) exige TAPSE em modo M na vista apical e peso entre 3 e 45 kg.</p>
        </div>
      )}

      {metodoAeAoCanino}

      {positive(medidas.AE_Ao ?? medidas.LA_Ao) && isFelineEchoSpecies(referencia?.especie) && (
        <div className="p-3 bg-blue-50 rounded-lg space-y-2">
          <label htmlFor="metodo-ae-ao" className="block text-sm font-medium text-blue-900">Método de obtenção de AE/Ao</label>
          <select id="metodo-ae-ao" value={medidas.AE_Ao_metodo || ""}
            onChange={(event) => onMedidaChange("AE_Ao_metodo", event.target.value)}
            className="w-full sm:w-auto rounded border border-blue-200 bg-white p-2 text-sm text-gray-900">
            <option value="">Método não confirmado</option>
            <option value="2d_eixo_curto_diastole_inicial">Gato adulto; 2D, eixo curto paraesternal direito, início da diástole</option>
            <option value="outro">Outra vista ou fase</option>
          </select>
          <p className="text-xs text-blue-800">Confirme a primeira imagem após o fechamento da valva aórtica. Häggström et al. (2016) estudaram gatos adultos de raça pura; o intervalo de predição por peso exige a vista e a fase confirmadas.</p>
        </div>
      )}

      {Object.keys(porCategoria).length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          <AlertTriangle className="w-12 h-12 mx-auto mb-3 text-yellow-400" />
          <p>Nenhuma medida preenchida para comparação.</p>
          <p className="text-sm mt-1">Vá para a aba &quot;Medidas&quot; e preencha os valores.</p>
        </div>
      ) : (
        Object.entries(porCategoria).map(([categoria, items]) => (
          <div key={categoria}>
            <h4 className="font-medium text-gray-900 mb-3 flex items-center gap-2">
              <span>{CATEGORIAS[categoria as keyof typeof CATEGORIAS]?.icon || "📋"}</span>
              {CATEGORIAS[categoria as keyof typeof CATEGORIAS]?.label || categoria}
            </h4>
            <div className="space-y-2">
              {items.map((item) => (
                (() => {
                  const semReferenciaDefinida =
                    item.status === "nao_avaliado" ||
                    item.referencia_min === null ||
                    item.referencia_max === null ||
                    (item.referencia_min === 0 && item.referencia_max === 0);
                  const faixaRef = item.referencia_texto ?? (semReferenciaDefinida
                    ? "-"
                    : `${item.referencia_min} - ${item.referencia_max}`);

                  return (
                <div
                  key={item.key}
                  className={`flex flex-col gap-3 p-3 rounded-lg border sm:flex-row sm:items-start sm:justify-between ${getStatusClass(
                    item.status
                  )}`}
                >
                  <div className="flex min-w-0 items-start gap-3">
                    {getStatusIcon(item.status)}
                    <div>
                      <p className="font-medium text-sm">{item.nome}</p>
                      <p className="text-xs text-gray-500">
                        {item.referencia_tipo === "clinical_limit" ? "Limite clínico orientativo"
                          : item.metadados?.status === "estimated" ? "Estimativa calculada"
                          : item.metadados?.status === "published" && ["allometric", "interpolated"].includes(item.metadados.calculation || "") ? "Limites calculados"
                          : item.referencia_texto ? (item.referencia_tipo === "reference_interval" ? "Intervalo de referência publicado" : item.estatistica === "mean_sd" ? "Média ± DP publicada" : "Comparação diastólica") : item.key.endsWith("_2D")
                          ? (semReferenciaDefinida ? "Faixa 2D" : "Faixa 2D publicada")
                          : item.metadados?.status === "published" ? "Faixa publicada" : "Faixa cadastrada"}: {faixaRef}
                      </p>
                      {item.fonte && <p className="text-xs text-gray-500">{item.doi ? <a href={`https://doi.org/${item.doi}`} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">{item.fonte}</a> : item.fonte}</p>}
                      {item.metadados?.model_weight_kg != null && <details className="mt-1 text-xs text-gray-600">
                        <summary className="cursor-pointer">População adulta e cálculo</summary>
                        <p>{item.metadados.population}</p>
                        <p>{item.metadados.formula}</p>
                        <p>{item.metadados.reason}</p>
                      </details>}
                      {item.nota_referencia && ["descriptive", "reference_interval"].includes(item.referencia_tipo ?? "") && (
                        <details className="mt-1 text-xs text-gray-600">
                          <summary className="cursor-pointer">Técnica e população do estudo</summary>
                          <p className="mt-1 max-w-xl leading-relaxed">{item.nota_referencia}</p>
                        </details>
                      )}
                      {item.metadados?.clinical_threshold && ["AE_Ao", "LA_Ao"].includes(item.key) && (
                        <p className="text-xs text-gray-500">Limiar clínico geral: AE/Ao &lt; 1,5, independente do intervalo estatístico por peso. Interpretar com os demais achados.</p>
                      )}
                    </div>
                  </div>
                  <div className="min-w-0 sm:max-w-sm sm:shrink-0 sm:text-right">
                    <p className="font-bold text-lg">{item.valor_medido || "-"}</p>
                    <p className={`text-xs ${getStatusTextClass(item.status)}`}>
                      {item.interpretacao}
                    </p>
                  </div>
                </div>
                  );
                })()
              ))}
            </div>
          </div>
        ))
      )}

      <div className="flex gap-4 text-sm mt-4 p-3 bg-gray-50 rounded-lg">
        <div className="flex items-center gap-1">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <span>Dentro da faixa</span>
        </div>
        <div className="flex items-center gap-1">
          <ArrowUp className="w-4 h-4 text-red-500" />
          <span>Acima da faixa</span>
        </div>
        <div className="flex items-center gap-1">
          <ArrowDown className="w-4 h-4 text-blue-500" />
          <span>Abaixo da faixa</span>
        </div>
      </div>
    </div>
  );
}
