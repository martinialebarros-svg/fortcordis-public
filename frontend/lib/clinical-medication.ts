export type MedicationRecord = {
  id: number;
  nome: string;
  principio_ativo?: string;
  concentracao?: string;
  dose_min_mg_kg?: number | null;
  dose_max_mg_kg?: number | null;
  dose_intervalo_horas?: number | null;
  via_padrao?: string;
  duracao_padrao?: string;
  concentracao_mg_ml?: number | null;
  concentracao_mg_comprimido?: number | null;
  classe_terapeutica?: string;
  interacoes?: string[];
  observacao_seguranca?: string;
  parametrizado?: boolean;
};

export type PrescriptionDraftItem = {
  medicamento_id?: number | null;
  medicamento_nome: string;
  apresentacao_selecionada?: string;
};

export type MedicationPresentationOption = {
  key: string;
  label: string;
  kind: "solid" | "liquid" | "other";
  unitLabel: string;
  strengthMg: number | null;
  strengthMgMl: number | null;
  splitIncrement: number;
  splitDescription: string;
};

export type PresentationSuggestion = {
  presentationLabel: string;
  doseAplicada: string;
  resumo: string;
  detalhe: string;
  requerManipulacao: boolean;
};

export type PrescriptionSupportItem = {
  index: number;
  alertas: string[];
  doseSugerida: string;
  detalhe: string;
  apresentacoes: MedicationPresentationOption[];
  sugestaoApresentacao: PresentationSuggestion | null;
};

export type PrescriptionSupport = {
  itens: PrescriptionSupportItem[];
  alertasGerais: string[];
};

type PresentationEvaluation = {
  option: MedicationPresentationOption;
  viable: boolean;
  deliveredMg: number;
  units: number | null;
  volumeMl: number | null;
  practicalFraction: boolean;
  splitPenalty: number;
  distanceFromMid: number;
};

const normalizeToken = (value?: string | null) =>
  (value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

const parseDecimal = (value?: string | null) => {
  if (!value) return null;
  const normalized = value.replace(/\s+/g, "").replace(",", ".");
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatNumber = (value: number, maxDigits = 2) =>
  new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: value % 1 === 0 ? 0 : Math.min(1, maxDigits),
    maximumFractionDigits: maxDigits,
  }).format(value);

const pluralizeUnit = (unitLabel: string, units: number) => {
  const rounded = Math.round(units * 1000) / 1000;
  if (Math.abs(rounded - 1) < 0.001) return unitLabel;
  if (unitLabel.endsWith("s")) return unitLabel;
  if (unitLabel.endsWith("ula")) return `${unitLabel}s`;
  return `${unitLabel}s`;
};

const formatDoseRangeMg = (doseMinMg: number, doseMaxMg: number) => {
  if (Math.abs(doseMinMg - doseMaxMg) < 0.001) {
    return `${formatNumber(doseMaxMg)} mg por dose`;
  }
  return `${formatNumber(doseMinMg)} a ${formatNumber(doseMaxMg)} mg por dose`;
};

const extractStrengthMgMl = (label: string) => {
  const match = label.match(/(\d+(?:[.,]\d+)?)\s*mg\s*\/\s*(\d+(?:[.,]\d+)?)?\s*m?l/i);
  if (!match) return null;
  const mg = parseDecimal(match[1]);
  const ml = parseDecimal(match[2] || "1");
  if (!mg || !ml) return null;
  return mg / ml;
};

const extractStrengthMg = (label: string) => {
  const match = label.match(/(\d+(?:[.,]\d+)?)\s*mg(?!\s*\/)/i);
  return match ? parseDecimal(match[1]) : null;
};

const derivePresentationMeta = (label: string): MedicationPresentationOption => {
  const normalized = normalizeToken(label);
  const strengthMgMl = extractStrengthMgMl(label);
  const isCapsule = normalized.includes("capsula") || normalized.includes("capsulas");
  const isTablet =
    normalized.includes("comprimido")
    || normalized.includes("comprimidos")
    || normalized.includes("tablete")
    || normalized.includes("dragea");
  const isLiquid =
    normalized.includes("ml")
    || normalized.includes("solucao")
    || normalized.includes("suspensao")
    || normalized.includes("xarope")
    || normalized.includes("gota")
    || normalized.includes("injetavel");

  if (strengthMgMl) {
    return {
      key: label,
      label,
      kind: "liquid",
      unitLabel: "mL",
      strengthMg: null,
      strengthMgMl,
      splitIncrement: 0,
      splitDescription: "dose mensuravel em mL",
    };
  }

  if (isTablet || isCapsule) {
    const allowsQuarter =
      normalized.includes("bissulcado")
      || normalized.includes("bissulcados")
      || normalized.includes("quadrissulcado")
      || normalized.includes("quadrissulcados");
    const splitIncrement = isCapsule ? 1 : allowsQuarter ? 0.25 : 0.5;
    return {
      key: label,
      label,
      kind: "solid",
      unitLabel: isCapsule ? "capsula" : "comprimido",
      strengthMg: extractStrengthMg(label),
      strengthMgMl: null,
      splitIncrement,
      splitDescription:
        splitIncrement === 1
          ? "unidade inteira"
          : splitIncrement === 0.25
            ? "fracionamento minimo de 1/4"
            : "fracionamento minimo de 1/2",
    };
  }

  return {
    key: label,
    label,
    kind: isLiquid ? "liquid" : "other",
    unitLabel: isLiquid ? "mL" : "unidade",
    strengthMg: extractStrengthMg(label),
    strengthMgMl: isLiquid ? (extractStrengthMgMl(label) ?? null) : null,
    splitIncrement: isLiquid ? 0 : 1,
    splitDescription: isLiquid ? "dose mensuravel em mL" : "unidade inteira",
  };
};

export const parseMedicationPresentations = (medicamento: MedicationRecord): MedicationPresentationOption[] => {
  const rawLines = (medicamento.concentracao || "")
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (rawLines.length === 0) {
    if (medicamento.concentracao_mg_comprimido) {
      rawLines.push(`${medicamento.nome} ${formatNumber(medicamento.concentracao_mg_comprimido)} mg, comprimido`);
    } else if (medicamento.concentracao_mg_ml) {
      rawLines.push(`${medicamento.nome} ${formatNumber(medicamento.concentracao_mg_ml)} mg/mL`);
    }
  }

  const seen = new Set<string>();
  return rawLines
    .map(derivePresentationMeta)
    .filter((item) => {
      const key = normalizeToken(item.label);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
};

const formatDose = (pesoKg: number, medicamento: MedicationRecord) => {
  const doseMin = medicamento.dose_min_mg_kg ?? null;
  const doseMax = medicamento.dose_max_mg_kg ?? null;
  const intervalo = medicamento.dose_intervalo_horas ?? null;

  if (doseMin === null && doseMax === null) return "";

  const doseBase = doseMax ?? doseMin ?? 0;
  const doseTotal = pesoKg * doseBase;

  let summary = "";
  if (doseMin !== null && doseMax !== null) {
    summary = `${doseMin.toFixed(2)} a ${doseMax.toFixed(2)} mg/kg (${(pesoKg * doseMin).toFixed(2)} a ${(pesoKg * doseMax).toFixed(2)} mg por dose)`;
  } else {
    summary = `${doseBase.toFixed(2)} mg/kg (${doseTotal.toFixed(2)} mg por dose)`;
  }

  if (intervalo) summary += ` a cada ${intervalo}h`;
  return summary;
};

const buildDoseTargets = (pesoKg: number, medicamento: MedicationRecord) => {
  const doseBaseMin = medicamento.dose_min_mg_kg ?? medicamento.dose_max_mg_kg ?? null;
  const doseBaseMax = medicamento.dose_max_mg_kg ?? medicamento.dose_min_mg_kg ?? null;
  if (doseBaseMin === null || doseBaseMax === null) return null;

  const doseMinMg = pesoKg * doseBaseMin;
  const doseMaxMg = pesoKg * doseBaseMax;
  const orderedMin = Math.min(doseMinMg, doseMaxMg);
  const orderedMax = Math.max(doseMinMg, doseMaxMg);

  return {
    doseMinMg: orderedMin,
    doseMaxMg: orderedMax,
    doseMidMg: (orderedMin + orderedMax) / 2,
  };
};

const evaluateSolidPresentation = (
  option: MedicationPresentationOption,
  doseMinMg: number,
  doseMaxMg: number,
  doseMidMg: number
): PresentationEvaluation | null => {
  if (!option.strengthMg) return null;

  const increment = option.splitIncrement > 0 ? option.splitIncrement : 1;
  const maxUnits = Math.max(2, Math.ceil(doseMaxMg / option.strengthMg) + 2);
  let best: PresentationEvaluation | null = null;

  for (let units = increment; units <= maxUnits; units += increment) {
    const deliveredMg = units * option.strengthMg;
    const viable = deliveredMg >= doseMinMg - 0.001 && deliveredMg <= doseMaxMg + 0.001;
    const practicalFraction = units >= 0.5;
    const splitPenalty = Math.abs(units - Math.round(units)) < 0.001
      ? 0
      : increment <= 0.25
        ? 400
        : 200;
    const distanceFromMid = Math.abs(deliveredMg - doseMidMg);

    const evaluation: PresentationEvaluation = {
      option,
      viable,
      deliveredMg,
      units,
      volumeMl: null,
      practicalFraction,
      splitPenalty,
      distanceFromMid,
    };

    if (!best || evaluation.distanceFromMid < best.distanceFromMid) {
      best = evaluation;
    }
  }

  return best;
};

const evaluateLiquidPresentation = (
  option: MedicationPresentationOption,
  doseMinMg: number,
  doseMaxMg: number,
  doseMidMg: number
): PresentationEvaluation | null => {
  if (!option.strengthMgMl) return null;

  const volumeMid = doseMidMg / option.strengthMgMl;
  const practical = volumeMid >= 0.05 && volumeMid <= 5;

  return {
    option,
    viable: practical,
    deliveredMg: doseMidMg,
    units: null,
    volumeMl: volumeMid,
    practicalFraction: practical,
    splitPenalty: 0,
    distanceFromMid: Math.abs(volumeMid - 0.5),
  };
};

const formatCommercialDose = (evaluation: PresentationEvaluation) => {
  if (evaluation.units !== null) {
    return `${formatNumber(evaluation.units)} ${pluralizeUnit(evaluation.option.unitLabel, evaluation.units)} por dose`;
  }
  if (evaluation.volumeMl !== null) {
    return `${formatNumber(evaluation.volumeMl)} mL por dose`;
  }
  return "";
};

export const suggestMedicationPresentation = (
  pesoKg: number | null | undefined,
  medicamento: MedicationRecord,
  selectedPresentationLabel?: string
): PresentationSuggestion | null => {
  if (!pesoKg) return null;

  const targets = buildDoseTargets(pesoKg, medicamento);
  if (!targets) return null;

  const presentations = parseMedicationPresentations(medicamento);
  if (!presentations.length) return null;

  const selected =
    selectedPresentationLabel
      ? presentations.find((option) => normalizeToken(option.label) === normalizeToken(selectedPresentationLabel)) || null
      : null;

  const evaluations = presentations
    .map((option) => {
      if (option.kind === "solid") {
        return evaluateSolidPresentation(option, targets.doseMinMg, targets.doseMaxMg, targets.doseMidMg);
      }
      if (option.kind === "liquid") {
        return evaluateLiquidPresentation(option, targets.doseMinMg, targets.doseMaxMg, targets.doseMidMg);
      }
      return null;
    })
    .filter((item): item is PresentationEvaluation => Boolean(item));

  if (!evaluations.length) return null;

  const viableEvaluations = evaluations
    .filter((evaluation) => evaluation.viable)
    .sort((left, right) => {
      if (left.splitPenalty !== right.splitPenalty) return left.splitPenalty - right.splitPenalty;
      if ((left.units ?? 0) !== (right.units ?? 0)) return (left.units ?? 0) - (right.units ?? 0);
      return left.distanceFromMid - right.distanceFromMid;
    });
  const selectedEvaluation =
    selected ? evaluations.find((evaluation) => evaluation.option.key === selected.key) || null : null;

  let chosen = selectedEvaluation?.viable ? selectedEvaluation : viableEvaluations[0] || null;
  if (chosen) {
    const doseAplicada = formatCommercialDose(chosen);
    const prefix =
      selectedEvaluation && chosen.option.key !== selectedEvaluation.option.key
        ? `A apresentacao selecionada nao ficou adequada para ${formatNumber(pesoKg)} kg. `
        : "";

    return {
      presentationLabel: chosen.option.label,
      doseAplicada,
      resumo: `${doseAplicada} com ${chosen.option.label}`,
      detalhe:
        `${prefix}Entrega ${formatNumber(chosen.deliveredMg)} mg para um alvo de ${formatDoseRangeMg(targets.doseMinMg, targets.doseMaxMg)}.`,
      requerManipulacao: false,
    };
  }

  const fallback = evaluations.sort((left, right) => {
    if (left.distanceFromMid !== right.distanceFromMid) return left.distanceFromMid - right.distanceFromMid;
    if (left.splitPenalty !== right.splitPenalty) return left.splitPenalty - right.splitPenalty;
    return (left.units ?? 0) - (right.units ?? 0);
  })[0];

  if (!fallback) return null;

  const aproximacao = formatCommercialDose(fallback);
  return {
    presentationLabel: fallback.option.label,
    doseAplicada: "",
    resumo: "Nenhuma apresentacao comercial ficou adequada para este peso.",
    detalhe:
      `${aproximacao ? `A melhor aproximacao comercial seria ${aproximacao} com ${fallback.option.label}, ` : ""}` +
      `entregando ${formatNumber(fallback.deliveredMg)} mg para um alvo de ${formatDoseRangeMg(targets.doseMinMg, targets.doseMaxMg)} (${fallback.option.splitDescription}). Considere formula manipulada.`,
    requerManipulacao: true,
  };
};

export const buildPrescriptionSupport = (
  pesoKg: number | null | undefined,
  medicamentos: MedicationRecord[],
  itens: PrescriptionDraftItem[]
): PrescriptionSupport => {
  const map = new Map(medicamentos.map((med) => [med.id, med]));
  const generalAlerts = new Set<string>();

  const supportItems = itens.map((item, index) => {
    const medicamento = item.medicamento_id ? map.get(item.medicamento_id) : undefined;
    const alertas: string[] = [];
    const doseSugerida = medicamento && pesoKg ? formatDose(pesoKg, medicamento) : "";
    const detalhe: string[] = [];
    const apresentacoes = medicamento ? parseMedicationPresentations(medicamento) : [];
    const sugestaoApresentacao =
      medicamento && pesoKg
        ? suggestMedicationPresentation(pesoKg, medicamento, item.apresentacao_selecionada)
        : null;

    if (medicamento) {
      if (!pesoKg && (medicamento.dose_min_mg_kg != null || medicamento.dose_max_mg_kg != null)) {
        alertas.push("Informe o peso para calcular a dose.");
      }
      if (!medicamento.parametrizado) {
        alertas.push("Medicamento sem parametrizacao clinica completa.");
      }
      if (medicamento.observacao_seguranca) {
        alertas.push(medicamento.observacao_seguranca);
      }
      if (medicamento.via_padrao) {
        detalhe.push(`Via: ${medicamento.via_padrao}`);
      }
      if (medicamento.duracao_padrao) {
        detalhe.push(`Duracao: ${medicamento.duracao_padrao}`);
      }
      if (apresentacoes.length) {
        detalhe.push(`${apresentacoes.length} apresentacao(oes) comercial(is) disponivel(is)`);
      }
      if (sugestaoApresentacao?.requerManipulacao) {
        alertas.push("Peso/dose abaixo da menor apresentacao comercial pratica. Considere formula manipulada.");
      }
    }

    return {
      index,
      alertas,
      doseSugerida,
      detalhe: detalhe.join(" | "),
      apresentacoes,
      sugestaoApresentacao,
    };
  });

  for (let i = 0; i < itens.length; i += 1) {
    const current = itens[i];
    const medicamento = current.medicamento_id ? map.get(current.medicamento_id) : undefined;
    if (!medicamento?.interacoes?.length) continue;

    const targets = new Set(medicamento.interacoes.map((target) => normalizeToken(target)).filter(Boolean));
    for (let j = i + 1; j < itens.length; j += 1) {
      const other = itens[j];
      const otherMedication = other.medicamento_id ? map.get(other.medicamento_id) : undefined;
      if (!otherMedication) continue;

      const candidates = [
        normalizeToken(otherMedication.nome),
        normalizeToken(otherMedication.principio_ativo),
        normalizeToken(other.medicamento_nome),
      ].filter(Boolean);

      if (!candidates.some((candidate) => targets.has(candidate))) continue;

      generalAlerts.add(
        `Interacao potencial entre ${current.medicamento_nome || medicamento.nome} e ${other.medicamento_nome || otherMedication.nome}.`
      );
    }
  }

  return {
    itens: supportItems,
    alertasGerais: Array.from(generalAlerts),
  };
};
