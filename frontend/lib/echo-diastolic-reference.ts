import { canineDiastolicReferences } from "./echo-canine-diastolic-reference";
import { canonicalFelineDiastolicKey, felineDiastolicReferences } from "./echo-feline-diastolic-reference";
import { normalizeEchoSpecies } from "./echo-species";
export type { EchoDiastolicReference } from "./echo-diastolic-reference-types";
export { canonicalFelineDiastolicKey as canonicalEchoDiastolicKey };

/** One species-aware evidence resolver for comparison and report preview. */
export function echoDiastolicReferences(measurements: Record<string, string>, species: string) {
  if (normalizeEchoSpecies(species) === "Canina") return canineDiastolicReferences(measurements, species);
  return felineDiastolicReferences(measurements, species);
}
