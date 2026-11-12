import { describe, expect, it } from "vitest";
import {
  ATENDIMENTO_LIBRARY_PAGE_SIZE,
  ATENDIMENTO_PATIENT_SEARCH_LIMIT,
  buildClinicalPhraseLibraryPath,
  buildMedicationLibraryPath,
  buildPatientSearchPath,
  mergeRecordsById,
} from "./atendimento-library-loading";

describe("atendimento library loading", () => {
  it("limits patient search results instead of loading the full catalogue", () => {
    expect(buildPatientSearchPath("  Lua  ")).toBe(`/pacientes?search=Lua&limit=${ATENDIMENTO_PATIENT_SEARCH_LIMIT}`);
  });

  it("uses bounded pages for medications and clinical phrases", () => {
    expect(buildMedicationLibraryPath({ search: "pimobendan", skip: 100 })).toBe(
      `/atendimentos/medicamentos/banco?search=pimobendan&skip=100&limit=${ATENDIMENTO_LIBRARY_PAGE_SIZE}`
    );
    expect(buildClinicalPhraseLibraryPath({ secao: "anamnese", includeInactive: true })).toBe(
      `/atendimentos/frases-clinicas?secao=anamnese&include_inactive=1&skip=0&limit=${ATENDIMENTO_LIBRARY_PAGE_SIZE}`
    );
  });

  it("merges later pages without duplicating records already used by the editor", () => {
    expect(mergeRecordsById([{ id: 1, value: "old" }], [{ id: 1, value: "updated" }, { id: 2, value: "new" }])).toEqual([
      { id: 1, value: "updated" },
      { id: 2, value: "new" },
    ]);
  });
});
