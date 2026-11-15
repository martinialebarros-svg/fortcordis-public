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

type Measurements = Record<string, string>;

/** Keep derived-ratio ownership atomic with measurements, outside the saved
 * clinical payload. Each mounted/replaced exam starts with its own state. */
export function useEchoMeasurements(options: { newReportSpecies?: string } = {}) {
  const species = options.newReportSpecies === undefined ? undefined : normalizeEchoSpecies(options.newReportSpecies);
  const previousSpecies = useRef(species);
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

  const setMeasurements = useCallback((action: SetStateAction<Measurements>) => {
    setState((previous) => {
      const next = updateEchoMeasurementState(previous,
        typeof action === "function" ? action(previous.measurements) : action);
      return { ...next, measurements: preserveNewReportProtocol(next.measurements, previous.measurements, species) };
    });
  }, [species]);
  const importMeasurements = useCallback((imported: Measurements) => {
    setState((previous) => {
      const next = importEchoMeasurementState({
        ...previous,
        measurements: clearReplacedOutflowProvenance(previous.measurements, imported),
      }, imported);
      return { ...next, measurements: preserveNewReportProtocol(next.measurements, previous.measurements, species) };
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
    setState({ measurements: { ...snapshot.measurements }, aeAoDerived: snapshot.aeAoDerived });
  }, []);

  return { measurements: state.measurements, setMeasurements, importMeasurements, replaceMeasurements, setProtocolMeasurement, exportState, restoreState };
}
