"use client";

import { useEffect, useState } from "react";
import { ChevronDown, History, Loader2, RefreshCw } from "lucide-react";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import { formatDate } from "@/lib/atendimento-utils";

type Edicao = {
  id: number;
  created_at: string;
  usuario_nome: string | null;
  entidade: string;
  entidade_id: string;
  descricao: string | null;
  alteracoes: Record<string, { antes: unknown; depois: unknown }>;
};

type Historico = { items: Edicao[]; total: number };
type Props = { atendimentoId: number; documentoId?: number; refreshKey?: number | string };

const FIELD_LABELS: Record<string, string> = {
  titulo: "Titulo", corpo: "Texto do documento", status: "Status", versao: "Versao",
  triagem: "Triagem", peso: "Peso (kg)", temperatura: "Temperatura (°C)",
  frequencia_cardiaca: "Frequencia cardiaca", frequencia_respiratoria: "Frequencia respiratoria",
  pressao_arterial: "Pressao arterial", saturacao_oxigenio: "Saturacao de oxigenio",
  triagem_observacoes: "Observacoes da triagem", mucosas: "Mucosas", hidratacao: "Hidratacao",
  queixa_principal: "Queixa principal", anamnese: "Anamnese", exame_fisico: "Exame fisico",
  dados_clinicos: "Dados clinicos", diagnostico_principal: "Diagnostico principal",
  diagnostico_secundario: "Diagnostico secundario", diagnostico_diferencial: "Diagnostico diferencial",
  prognostico: "Prognostico", plano_terapeutico: "Plano terapeutico",
  retorno_recomendado: "Retorno recomendado", motivo_retorno: "Motivo do retorno", observacoes: "Observacoes",
  exames: "Exames", prescricao: "Prescricao", itens: "Itens", medicamento_nome: "Medicamento",
  dose: "Dose", frequencia: "Frequencia", duracao: "Duracao", via: "Via",
  orientacoes_gerais: "Orientacoes gerais", retorno_dias: "Retorno (dias)",
  apresentacao_selecionada: "Apresentacao", tipo_exame: "Exame", resultado: "Resultado",
  data_resultado: "Data do resultado", valor_referencia: "Valor de referencia", unidade: "Unidade",
  data_atendimento: "Data do atendimento", emitido_em: "Emissao", emitida_em: "Emissao",
  apresentacao: "Apresentacao", dose_calculada: "Dose calculada", dose_base: "Dose base",
  dose_base_unidade: "Unidade da dose base", dose_unidade: "Unidade da dose", quantidade: "Quantidade",
  peso_referencia: "Peso de referencia", unidade_calculada: "Unidade calculada",
  concentracao_mg_ml: "Concentracao (mg/mL)", concentracao_mg_comprimido: "Concentracao (mg/comprimido)",
};
const INTERNAL_FIELDS = new Set(["id", "atendimento_id", "prescricao_id", "medicamento_id", "catalogo_exame_id", "ordem", "created_at", "updated_at"]);

export function fieldLabel(campo: string): string {
  return FIELD_LABELS[campo] || campo.split(".").map((part) => FIELD_LABELS[part] || part.replaceAll("_", " ")).join(" / ");
}

export function HistoryValue({ value }: { value: unknown }) {
  if (value == null || value === "") return <span className="italic text-slate-400">Vazio</span>;
  if (typeof value === "boolean") return <>{value ? "Sim" : "Nao"}</>;
  if (Array.isArray(value)) {
    if (!value.length) return <span className="italic text-slate-400">Nenhum item</span>;
    return <ol className="space-y-2">{value.map((item, index) => <li key={index} className="border-b border-slate-200 pb-2 last:border-0"><HistoryValue value={item} /></li>)}</ol>;
  }
  if (typeof value === "object") {
    return <dl className="space-y-1">{Object.entries(value).filter(([campo]) => !INTERNAL_FIELDS.has(campo)).map(([campo, item]) => <div key={campo}><dt className="font-medium">{fieldLabel(campo)}</dt><dd><HistoryValue value={item} /></dd></div>)}</dl>;
  }
  return <>{String(value)}</>;
}

export default function AtendimentoHistoricoEdicoes({ atendimentoId, documentoId, refreshKey }: Props) {
  const [aberto, setAberto] = useState(false);
  const [pagina, setPagina] = useState(0);
  const [recarregar, setRecarregar] = useState(0);
  const [resultado, setResultado] = useState<{ scope: string; data: Historico } | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const scope = `${atendimentoId}:${documentoId || "todos"}`;
  const historico = resultado?.scope === scope ? resultado.data : null;
  const limite = 20;

  useEffect(() => {
    if (!aberto) return;
    let ativo = true;
    setCarregando(true);
    setErro("");
    api.get(`/atendimentos/${atendimentoId}/historico-edicoes`, {
      params: { skip: pagina * limite, limit: limite, ...(documentoId ? { documento_id: documentoId } : {}) },
    }).then((response) => {
      if (ativo) setResultado({ scope, data: response.data });
    }).catch((error: unknown) => {
      if (ativo) setErro(extractApiErrorMessageSync(error, "Nao foi possivel carregar o historico de edicoes."));
    }).finally(() => {
      if (ativo) setCarregando(false);
    });
    return () => { ativo = false; };
  }, [aberto, atendimentoId, documentoId, pagina, recarregar, refreshKey, scope]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4" aria-label={documentoId ? "Historico de edicoes do documento" : "Historico de edicoes do atendimento"}>
      <button type="button" onClick={() => setAberto(!aberto)} aria-expanded={aberto} className="flex w-full items-center gap-2 text-left text-sm font-semibold text-slate-800">
        <History className="h-4 w-4" />
        {documentoId ? "Historico de edicoes deste documento" : "Historico de edicoes"}
        <ChevronDown className={`ml-auto h-4 w-4 transition ${aberto ? "rotate-180" : ""}`} />
      </button>
      {aberto ? <div className="mt-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500">Alteracoes salvas, com autor, data e conteudo anterior.</p>
          <button type="button" disabled={carregando} onClick={() => setRecarregar((value) => value + 1)} className="inline-flex items-center gap-1 text-xs text-teal-700 disabled:opacity-50"><RefreshCw className="h-3.5 w-3.5" />Atualizar historico</button>
        </div>
        {carregando ? <p role="status" className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Carregando historico...</p> : null}
        {erro ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{erro} Use Atualizar historico para tentar novamente.</p> : null}
        {!carregando && !erro && historico?.items.length === 0 ? <p className="text-sm text-slate-500">Nenhuma edicao registrada neste historico.</p> : null}
        {!carregando && !erro ? historico?.items.map((edicao) => (
          <article key={edicao.id} className="rounded-xl border border-slate-200 p-3">
            <p className="text-sm font-semibold text-slate-800">{edicao.usuario_nome || "Autor nao informado"} <span className="font-normal text-slate-500">· {formatDate(edicao.created_at)}</span></p>
            <p className="mt-1 text-xs text-slate-500">{edicao.entidade === "documento_atendimento" ? `Documento #${edicao.entidade_id}` : edicao.entidade === "prescricao_clinica" ? `Receita #${edicao.entidade_id}` : "Atendimento"}{edicao.descricao ? ` · ${edicao.descricao}` : ""}</p>
            {Object.entries(edicao.alteracoes || {}).map(([campo, alteracao]) => <details key={campo} className="mt-3 rounded-lg bg-slate-50 p-3">
              <summary className="cursor-pointer text-sm font-medium text-slate-700">{fieldLabel(campo)}</summary>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div><p className="mb-1 text-xs font-semibold text-slate-500">Antes</p><div className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-sm text-slate-700"><HistoryValue value={alteracao.antes} /></div></div>
                <div><p className="mb-1 text-xs font-semibold text-teal-700">Depois</p><div className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-sm text-slate-800"><HistoryValue value={alteracao.depois} /></div></div>
              </div>
            </details>)}
            {Object.keys(edicao.alteracoes || {}).length === 0 ? <p className="mt-2 text-xs text-slate-500">Este registro anterior nao possui comparacao detalhada.</p> : null}
          </article>
        )) : null}
        {historico && historico.total > limite ? <div className="flex items-center justify-between gap-2 text-xs text-slate-600">
          <button type="button" disabled={carregando || pagina === 0} onClick={() => setPagina((value) => value - 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Edicoes mais recentes</button>
          <span>Pagina {pagina + 1} de {Math.ceil(historico.total / limite)}</span>
          <button type="button" disabled={carregando || (pagina + 1) * limite >= historico.total} onClick={() => setPagina((value) => value + 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Edicoes anteriores</button>
        </div> : null}
      </div> : null}
    </section>
  );
}
