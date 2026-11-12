"use client";

import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";
import {
  createEchoMeasurementState,
  importEchoMeasurementState,
  updateEchoMeasurementState,
  type EchoMeasurementState,
} from "@/lib/echo-ae-ao-derivation";
import { clearReplacedOutflowProvenance } from "@/lib/echo-outflow-editor";
import { newEchoReportProtocol, NEW_REPORT_PROTOCOL_KEYS, preserveNewReportProtocol } from "@/lib/echo-new-report-defaults";
import { normalizeEchoSpecies } from "@/lib/echo-species";
import {
  HP_CONTEXT_KEYS,
  HP_NUMERIC_KEYS,
  hasValidPulmonaryReview,
  invalidatePulmonaryReview,
  makePulmonaryReviewStamp,
} from "@/lib/echo-pulmonary-probability";

type Measurements = Record<string, string>;

/** Keep derived-ratio ownership atomic with measurements, outside the saved
 * clinical payload. Each mounted/replaced exam starts with its own state. */
export function useEchoMeasurements(options: { newReportSpecies?: string; species?: string } = {}) {
  const species = options.newReportSpecies === undefined ? undefined : normalizeEchoSpecies(options.newReportSpecies);
  const reviewSpecies = normalizeEchoSpecies(options.species ?? options.newReportSpecies);
  const previousSpecies = useRef(species);
  const previousReviewSpecies = useRef(reviewSpecies);
  const [state, setState] = useState(() => createEchoMeasurementState(newEchoReportProtocol(species)));

  useEffect(() => {
    if (previousSpecies.current === species) return;
    previousSpecies.current = species;
    setState((previous) => {
      const measurements = { ...previous.measurements };
      const observedWaves = Object.fromEntries(["Diastolica_ondas", "TDI_ondas"]
        .filter((key) => ["fundidas", "nao_confirmadas"].includes(measurements[key]))
        .map((key) => [key, measurements[key]]));
      for (const key of NEW_REPORT_PROTOCOL_KEYS) delete measurements[key];
      return { ...previous, measurements: { ...measurements, ...newEchoReportProtocol(species), ...observedWaves } };
    });
  }, [species]);

  useEffect(() => {
    if (previousReviewSpecies.current === reviewSpecies) return;
    previousReviewSpecies.current = reviewSpecies;
    setState((previous) => {
      // A freshly loaded official record may already carry a valid review for
      // its own species. A species edit must not reuse the old species review.
      if (!previous.measurements.HP_revisao || hasValidPulmonaryReview(previous.measurements, reviewSpecies)) return previous;
      return { ...previous, measurements: invalidatePulmonaryReview(previous.measurements) };
    });
  }, [reviewSpecies]);

  const setMeasurements = useCallback((action: SetStateAction<Measurements>) => {
    setState((previous) => {
      const next = updateEchoMeasurementState(previous,
        typeof action === "function" ? action(previous.measurements) : action);
      let measurements = preserveNewReportProtocol(next.measurements, previous.measurements, species);
      if (previous.measurements.HP_revisao
        && makePulmonaryReviewStamp(previous.measurements, reviewSpecies) !== makePulmonaryReviewStamp(measurements, reviewSpecies)) {
        measurements = invalidatePulmonaryReview(measurements);
      }
      return { ...next, measurements };
    });
  }, [species, reviewSpecies]);
  const importMeasurements = useCallback((imported: Measurements) => {
    // Imports can supply explicitly labelled clinical measurements, never the
    // veterinarian's review, anatomical choices, or acquisition confirmations.
    const clinicalKeys = new Set<string>(HP_NUMERIC_KEYS);
    const safeImported = Object.fromEntries(Object.entries(imported)
      .filter(([key]) => !key.startsWith("HP_") || clinicalKeys.has(key)));
    setState((previous) => {
      const next = importEchoMeasurementState({
        ...previous,
        measurements: clearReplacedOutflowProvenance(previous.measurements, safeImported),
      }, safeImported);
      let measurements = preserveNewReportProtocol(next.measurements, previous.measurements, species);
      if (previous.measurements.HP_revisao && HP_CONTEXT_KEYS.some((key) => Object.hasOwn(safeImported, key))) {
        // A new acquisition must be reviewed even when its number is identical.
        measurements = invalidatePulmonaryReview(measurements);
      }
      return { ...next, measurements };
    });
  }, [species]);
  const setProtocolMeasurement = useCallback((key: string, value: string) => {
    if (!NEW_REPORT_PROTOCOL_KEYS.includes(key)) return;
    setState((previous) => ({ ...previous, measurements: { ...previous.measurements, [key]: value } }));
  }, []);
  const replaceMeasurements = useCallback((measurements: Measurements) => {
    setState(createEchoMeasurementState(measurements));
  }, []);
  const exportState = useCallback((): EchoMeasurementState => ({
    measurements: { ...state.measurements }, aeAoDerived: state.aeAoDerived,
  }), [state]);
  const restoreState = useCallback((snapshot: EchoMeasurementState, restoredSpecies?: string) => {
    // Recovery is not a new acquisition/import. Preserve the original ownership,
    // including an independently imported ratio, and do not reseed protocols.
    previousSpecies.current = restoredSpecies === undefined ? undefined : normalizeEchoSpecies(restoredSpecies);
    previousReviewSpecies.current = normalizeEchoSpecies(restoredSpecies);
    setState({ measurements: { ...snapshot.measurements }, aeAoDerived: snapshot.aeAoDerived });
  }, []);

  return { measurements: state.measurements, setMeasurements, importMeasurements, replaceMeasurements, setProtocolMeasurement, exportState, restoreState };
}
