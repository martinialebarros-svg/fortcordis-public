"use client";

import { useCallback, useMemo, useState } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, FileSearch, Loader2, Upload, X } from "lucide-react";

import { importarEstudoEco } from "@/lib/eco-study-import";
import { DadosExameImportados } from "@/lib/xml-import";

interface EcoStudyImportUploaderProps {
  onDadosImportados: (dados: DadosExameImportados) => void;
}

const ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".pdf"];
const MAX_FILE_SIZE = 30 * 1024 * 1024;

function hasAllowedExtension(filename: string): boolean {
  const normalized = (filename || "").toLowerCase();
  return ALLOWED_EXTENSIONS.some((extension) => normalized.endsWith(extension));
}

function confidenceLabel(value: number): string {
  if (value >= 0.95) return "Alta";
  if (value >= 0.8) return "Media";
  return "Revisar";
}

export default function EcoStudyImportUploader({
  onDadosImportados,
}: EcoStudyImportUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<DadosExameImportados | null>(null);
  const [filename, setFilename] = useState("");
  const [applied, setApplied] = useState(false);
  const [selectedLvTechnique, setSelectedLvTechnique] = useState<
    "" | "modo_m" | "2d"
  >("");

  const extracted = result?.medidas_extraidas || [];
  const suggestions = useMemo(
    () => extracted.filter((item) => item.status === "sugerida"),
    [extracted]
  );
  const conflicts = useMemo(
    () => extracted.filter((item) => item.status === "conflito"),
    [extracted]
  );
  const patientFields = [result?.paciente?.idade, result?.paciente?.peso].filter(Boolean).length;
  const detectedLvTechniques = result?.meta_importacao_estudo?.tecnicas_ve_detectadas || [];
  const requiresLvTechniqueChoice =
    detectedLvTechniques.includes("modo_m") && detectedLvTechniques.includes("2d");
  const automaticLvTechnique =
    detectedLvTechniques.length === 1 &&
    (detectedLvTechniques[0] === "modo_m" || detectedLvTechniques[0] === "2d")
      ? detectedLvTechniques[0]
      : "";
  const lvTechniqueForApplication = requiresLvTechniqueChoice
    ? selectedLvTechnique
    : automaticLvTechnique;

  const processFile = async (file: File) => {
    if (!hasAllowedExtension(file.name)) {
      setError("Envie uma imagem JPG, PNG, WEBP, BMP, TIFF ou um PDF.");
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      setError("O estudo excede o limite de 30 MB.");
      return;
    }

    setFilename(file.name);
    setError("");
    setResult(null);
    setApplied(false);
    setSelectedLvTechnique("");
    setIsLoading(true);
    try {
      setResult(await importarEstudoEco(file));
    } catch (err: any) {
      setError(err?.message || "Nao foi possivel processar o estudo.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleDrop = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void processFile(file);
  }, []);

  const reset = () => {
    setFilename("");
    setError("");
    setResult(null);
    setApplied(false);
    setSelectedLvTechnique("");
  };

  const applySuggestions = () => {
    if (!result || !Object.keys(result.medidas || {}).length) return;
    onDadosImportados({
      ...result,
      medidas: {
        ...result.medidas,
        ...(lvTechniqueForApplication
          ? { VE_tecnica_relatorio: lvTechniqueForApplication }
          : {}),
      },
    });
    setApplied(true);
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setIsDragging(false);
        }}
        onDrop={handleDrop}
        className={`rounded-lg border-2 border-dashed p-5 text-center transition-colors ${
          isDragging ? "border-teal-500 bg-teal-50" : "border-slate-300 hover:border-teal-400"
        } ${error ? "border-red-300 bg-red-50" : ""}`}
      >
        <input
          id="eco-study-import"
          type="file"
          className="hidden"
          accept=".jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff,.pdf"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void processFile(file);
            event.target.value = "";
          }}
        />
        <label htmlFor="eco-study-import" className="block cursor-pointer">
          {isLoading ? (
            <>
              <Loader2 className="mx-auto mb-2 h-9 w-9 animate-spin text-teal-600" />
              <p className="text-sm font-medium text-slate-700">Extraindo medidas e evidencias...</p>
              <p className="mt-1 text-xs text-slate-500">PDFs rasterizados podem levar alguns segundos.</p>
            </>
          ) : (
            <>
              <Upload className="mx-auto mb-2 h-9 w-9 text-slate-400" />
              <p className="text-sm font-medium text-slate-700">Arraste a imagem ou PDF do estudo</p>
              <p className="mt-1 text-xs text-slate-500">Ate 30 MB. Nenhuma medida sera aplicada sem revisao.</p>
            </>
          )}
        </label>
      </div>

      {filename && (
        <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span className="truncate">{filename}</span>
          <button type="button" onClick={reset} className="rounded p-1 hover:bg-slate-200" aria-label="Limpar estudo">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-3">
          <div className="flex items-start gap-2">
            <FileSearch className="mt-0.5 h-4 w-4 shrink-0 text-teal-600" />
            <div>
              <p className="text-sm font-semibold text-slate-800">
                {patientFields > 0
                  ? `${patientFields} dado(s) do paciente e ${suggestions.length} medida(s) pronto(s) para aplicar`
                  : `${suggestions.length} medida(s) pronta(s) para aplicar`}
              </p>
              <p className="text-xs text-slate-500">
                {result.meta_importacao_estudo?.paginas || 1} pagina(s) analisada(s)
              </p>
            </div>
          </div>

          {conflicts.length > 0 && (
            <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{result.meta_importacao_estudo?.conflitos || 1} campo(s) com valores conflitantes nao serao aplicados.</span>
            </div>
          )}

          {requiresLvTechniqueChoice && (
            <div className="rounded-md border border-teal-200 bg-teal-50 p-3 text-xs text-teal-950">
              <label className="font-semibold" htmlFor="eco-lv-technique">
                O estudo contém medidas do VE em Modo M e em Modo 2D. Qual técnica deve constar no laudo?
              </label>
              <select
                id="eco-lv-technique"
                value={selectedLvTechnique}
                onChange={(event) =>
                  setSelectedLvTechnique(
                    event.target.value as "" | "modo_m" | "2d"
                  )
                }
                className="mt-2 w-full rounded-md border border-teal-300 bg-white px-2 py-2 text-sm"
              >
                <option value="">Escolha antes de aplicar</option>
                <option value="modo_m">Modo M</option>
                <option value="2d">Modo 2D</option>
              </select>
              <p className="mt-2 text-teal-800">
                As duas séries permanecerão disponíveis no formulário; somente a técnica escolhida será exibida no PDF.
              </p>
            </div>
          )}

          <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
            {extracted.map((item, index) => (
              <div
                key={`${item.campo}-${item.pagina}-${index}`}
                className={`rounded-md border p-2 text-xs ${
                  item.status === "conflito"
                    ? "border-amber-200 bg-amber-50"
                    : item.status === "duplicada"
                      ? "border-slate-200 bg-slate-50 opacity-70"
                      : "border-emerald-200 bg-emerald-50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <strong className="text-slate-800">{item.rotulo}</strong>
                  <span className="font-semibold text-slate-900">{item.valor} {item.unidade}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-slate-500">
                  <span>Pagina {item.pagina}</span>
                  <span>Confianca {confidenceLabel(item.confianca)}</span>
                  <span>{item.status === "conflito" ? "Conflito" : item.origem}</span>
                </div>
                <p className="mt-1 truncate text-slate-500" title={item.texto_origem}>{item.texto_origem}</p>
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={applySuggestions}
            disabled={
              applied ||
              suggestions.length === 0 ||
              (requiresLvTechniqueChoice && !selectedLvTechnique)
            }
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-teal-600 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {applied ? <CheckCircle2 className="h-4 w-4" /> : null}
            {applied
              ? "Sugestoes aplicadas"
              : requiresLvTechniqueChoice && !selectedLvTechnique
                ? "Escolha a técnica do VE"
                : patientFields > 0
                ? `Aplicar dados e ${suggestions.length} medida(s)`
                : `Aplicar ${suggestions.length} medida(s)`}
          </button>
        </div>
      )}
    </div>
  );
}
