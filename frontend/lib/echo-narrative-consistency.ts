import { findEchoWaveNarrativeDiscrepancies, type EchoWaveNarrativeDiscrepancy } from "./echo-feline-narrative-consistency";
import { findEchoNumericNarrativeDiscrepancies, type EchoNumericNarrativeDiscrepancy } from "./echo-numeric-narrative-consistency";

export type EchoNarrativeDiscrepancy = EchoNumericNarrativeDiscrepancy | EchoWaveNarrativeDiscrepancy;

/** Avisos de revisão, sem alterar medidas ou interpretação clínica. */
export function findEchoNarrativeDiscrepancies(
  measurements: Record<string, string>,
  qualitative: object,
  conclusion: string,
  species?: string,
): EchoNarrativeDiscrepancy[] {
  return [
    ...findEchoNumericNarrativeDiscrepancies(measurements, qualitative, conclusion),
    ...findEchoWaveNarrativeDiscrepancies(measurements, qualitative, conclusion, species),
  ];
}
