/** Exact aliases shared with backend normalizar_especie_referencia.
 * Classification does not rewrite the species stored in the patient record. */
const FELINE_ALIASES = new Set(["felina", "felino", "felinos", "feline", "gato", "gatos", "cat", "cats"]);
const CANINE_ALIASES = new Set([
  "canina", "canino", "caninos", "canine", "cao", "caes", "cachorro", "cachorros", "dog", "dogs",
]);

export function normalizeEchoSpecies(species: string | null | undefined): string {
  const original = String(species ?? "").trim();
  // Match the backend's NFKD + ASCII normalization without prefix inference.
  const normalized = Array.from(original.normalize("NFKD"))
    .filter((character) => character.charCodeAt(0) <= 0x7f)
    .join("")
    .toLowerCase();
  if (FELINE_ALIASES.has(normalized)) return "Felina";
  if (CANINE_ALIASES.has(normalized)) return "Canina";
  return original;
}

export function isFelineEchoSpecies(species: string | null | undefined): boolean {
  return normalizeEchoSpecies(species) === "Felina";
}
