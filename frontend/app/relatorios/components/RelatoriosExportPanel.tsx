import { Download } from "lucide-react";

import { DOMINIOS_RELATORIO, SECOES_EXPORT_OPCOES } from "../constants";
import { DominioRelatorio, SecaoExport } from "../types";

interface RelatoriosExportPanelProps {
  dominioAtivo: DominioRelatorio;
  modoExportacao: "contexto" | "personalizado";
  setModoExportacao: (mode: "contexto" | "personalizado") => void;
  secoesContexto: SecaoExport[];
  secoesPersonalizadas: SecaoExport[];
  alternarSecaoPersonalizada: (secao: SecaoExport) => void;
  setSecoesPersonalizadas: (secoes: SecaoExport[]) => void;
  baixandoCsv: boolean;
  baixandoPdf: boolean;
  onExportCsv: () => void;
  onExportPdf: () => void;
}

export default function RelatoriosExportPanel({
  dominioAtivo,
  modoExportacao,
  setModoExportacao,
  secoesContexto,
  secoesPersonalizadas,
  alternarSecaoPersonalizada,
  setSecoesPersonalizadas,
  baixandoCsv,
  baixandoPdf,
  onExportCsv,
  onExportPdf,
}: RelatoriosExportPanelProps) {
  const dominioAtual = DOMINIOS_RELATORIO.find((item) => item.id === dominioAtivo);
  const secoesAtuais = modoExportacao === "contexto" ? secoesContexto : secoesPersonalizadas;

  return (
    <div className="fc-reports-export">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-gray-900">Exportação por contexto</p>
          <p className="text-xs text-gray-600">
            Aba ativa: <span className="font-medium">{dominioAtual?.label || "Relatorio"}</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onExportCsv}
            disabled={baixandoCsv || secoesAtuais.length === 0}
            className="inline-flex items-center gap-2 px-3 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            <Download className="w-4 h-4" />
            {baixandoCsv ? "Baixando CSV..." : "Exportar CSV"}
          </button>
          <button
            type="button"
            onClick={onExportPdf}
            disabled={baixandoPdf || secoesAtuais.length === 0}
            className="inline-flex items-center gap-2 px-3 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            <Download className="w-4 h-4" />
            {baixandoPdf ? "Baixando PDF..." : "Exportar PDF"}
          </button>
        </div>
      </div>

      <div className="fc-reports-export-modes">
        <button
          type="button"
          onClick={() => setModoExportacao("contexto")}
          className={`fc-reports-export-mode ${modoExportacao === "contexto" ? "fc-reports-export-mode-active" : ""}`}
        >
          <p className="text-sm font-medium text-gray-900">Modo contexto</p>
          <p className="text-xs text-gray-600">Exporta automaticamente as seções da aba atual.</p>
        </button>
        <button
          type="button"
          onClick={() => setModoExportacao("personalizado")}
          className={`fc-reports-export-mode ${modoExportacao === "personalizado" ? "fc-reports-export-mode-active" : ""}`}
        >
          <p className="text-sm font-medium text-gray-900">Modo personalizado</p>
          <p className="text-xs text-gray-600">Escolha manualmente as seções para exportar.</p>
        </button>
      </div>

      <div className="fc-reports-export-sections">
        <div className="flex flex-wrap gap-2">
          {SECOES_EXPORT_OPCOES.map((secao) => {
            const ativo =
              modoExportacao === "contexto"
                ? secoesContexto.includes(secao.id)
                : secoesPersonalizadas.includes(secao.id);
            return (
              <button
                key={secao.id}
                type="button"
                onClick={() => {
                  if (modoExportacao === "personalizado") {
                    alternarSecaoPersonalizada(secao.id);
                  }
                }}
                disabled={modoExportacao !== "personalizado"}
                className={`px-2.5 py-1.5 text-xs rounded-full border transition-colors ${
                  ativo
                    ? "bg-blue-100 border-blue-300 text-blue-700"
                    : "bg-white border-gray-300 text-gray-600 hover:bg-gray-100"
                } ${modoExportacao !== "personalizado" ? "opacity-80 cursor-not-allowed" : ""}`}
              >
                {secao.label}
              </button>
            );
          })}
        </div>

        {modoExportacao === "personalizado" ? (
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setSecoesPersonalizadas(SECOES_EXPORT_OPCOES.map((item) => item.id))}
              className="text-xs px-2 py-1 border rounded-md text-gray-700 hover:bg-white"
            >
              Selecionar todas
            </button>
            <button
              type="button"
              onClick={() => setSecoesPersonalizadas([])}
              className="text-xs px-2 py-1 border rounded-md text-gray-700 hover:bg-white"
            >
              Limpar seleção
            </button>
          </div>
        ) : null}

        <p className="text-[11px] text-gray-500 mt-2">
          Exemplo: na aba <strong>Financeiro</strong>, o modo contexto exporta so indicadores financeiros.
        </p>
      </div>
    </div>
  );
}
