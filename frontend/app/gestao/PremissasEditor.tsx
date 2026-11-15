import { Plus, Trash2 } from "lucide-react";
import { formatCalendarDate } from "@/lib/calendar-date";
import type { ContextoGestao, PremissasGestao, PremissasSalvas } from "./types";

const numero = (value: string): number | null => value.trim() === "" ? null : Number(value);
const campos: Array<{ key: keyof Pick<PremissasGestao, "tributos_percentual" | "taxas_percentual" | "repasses_percentual" | "custos_variaveis" | "horas_atendimento" | "horas_laudos" | "horas_deslocamento" | "saldo_inicial">; label: string; hint: string; max?: number; negative?: boolean }> = [
  { key: "tributos_percentual", label: "Tributos (%)", hint: "Percentual sobre a receita por competência.", max: 100 },
  { key: "taxas_percentual", label: "Taxas (%)", hint: "Taxas variáveis aplicáveis aos serviços.", max: 100 },
  { key: "repasses_percentual", label: "Repasses (%)", hint: "Percentual repassado a parceiros.", max: 100 },
  { key: "custos_variaveis", label: "Outros custos variáveis (R$)", hint: "Total do recorte, sem repetir tributos, taxas e repasses." },
  { key: "horas_atendimento", label: "Horas de atendimento", hint: "Total atribuído aos serviços deste recorte." },
  { key: "horas_laudos", label: "Horas de laudos", hint: "Tempo adicional, sem repetir horas de atendimento." },
  { key: "horas_deslocamento", label: "Horas de deslocamento", hint: "Total alocado ao recorte; cada rota deve ser contada uma vez." },
  { key: "saldo_inicial", label: "Saldo inicial informado (R$)", hint: "Saldo na abertura do primeiro dia do período. Pode ser negativo.", negative: true },
];

export default function PremissasEditor({ value, onChange, contexto, salvas, disabled, saving, canSave, onSimulate, onSave, onRestore }: {
  value: PremissasGestao; onChange: (value: PremissasGestao) => void; contexto: ContextoGestao; salvas: PremissasSalvas | null;
  disabled: boolean; saving: boolean; canSave: boolean; onSimulate: () => void; onSave: () => void; onRestore: () => void;
}) {
  return <details className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <summary className="cursor-pointer text-base font-semibold text-slate-900">Premissas e cenário-base</summary>
    <div className="mt-4 space-y-5">
      <p className="text-sm text-slate-600">Informe apenas valores conhecidos ou estimados conscientemente. Campo vazio significa informação desconhecida; zero só é usado quando você o informa. Estes totais valem exclusivamente para {formatCalendarDate(contexto.data_inicio)} a {formatCalendarDate(contexto.data_fim)} e os filtros atuais.</p>
      <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-950">Custos, horas e saldo são premissas administrativas. Não são comprovantes nem saldo bancário integrado. Ao alocar uma rota compartilhada, não repita seu custo e seu tempo em mais de um recorte. A comparação anterior não recebe estes totais.</p>
      <fieldset disabled={disabled || saving} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <legend className="sr-only">Custos, horas e saldo do recorte</legend>
        {campos.map((campo) => <label key={campo.key} className="text-sm font-medium text-slate-800">
          {campo.label}
          <input aria-label={campo.label} type="number" inputMode="decimal" step="0.01" min={campo.negative ? undefined : 0} max={campo.max} value={value[campo.key] ?? ""} onChange={(event) => onChange({ ...value, [campo.key]: numero(event.target.value) })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" placeholder="Não informado" />
          <span className="mt-1 block text-xs font-normal text-slate-500">{campo.hint}</span>
        </label>)}
      </fieldset>
      <fieldset disabled={disabled || saving} className="space-y-3">
        <legend className="font-semibold text-slate-900">Entradas e saídas adicionais</legend>
        <p className="text-sm text-slate-600">Use apenas movimentos ainda não contemplados nos registros. A recorrência mensal repete a premissa a partir da data informada; confira as linhas da projeção antes de usar o resultado.</p>
        {value.movimentos.map((movimento, index) => <div key={index} className="grid gap-3 rounded-xl border border-slate-200 p-3 md:grid-cols-6">
          <label className="text-xs font-medium">Data {index + 1}<input aria-label={`Data do movimento ${index + 1}`} type="date" value={movimento.data} onChange={(event) => onChange({ ...value, movimentos: value.movimentos.map((item, i) => i === index ? { ...item, data: event.target.value } : item) })} className="mt-1 w-full rounded-lg border px-2 py-2" /></label>
          <label className="text-xs font-medium">Tipo<select aria-label={`Tipo do movimento ${index + 1}`} value={movimento.tipo} onChange={(event) => onChange({ ...value, movimentos: value.movimentos.map((item, i) => i === index ? { ...item, tipo: event.target.value as "entrada" | "saida" } : item) })} className="mt-1 w-full rounded-lg border px-2 py-2"><option value="saida">Saída</option><option value="entrada">Entrada</option></select></label>
          <label className="text-xs font-medium">Valor (R$)<input aria-label={`Valor do movimento ${index + 1}`} type="number" step="0.01" min="0.01" value={movimento.valor ?? ""} onChange={(event) => onChange({ ...value, movimentos: value.movimentos.map((item, i) => i === index ? { ...item, valor: numero(event.target.value) } : item) })} className="mt-1 w-full rounded-lg border px-2 py-2" /></label>
          <label className="text-xs font-medium">Recorrência<select aria-label={`Recorrência do movimento ${index + 1}`} value={movimento.recorrencia} onChange={(event) => onChange({ ...value, movimentos: value.movimentos.map((item, i) => i === index ? { ...item, recorrencia: event.target.value as "unica" | "mensal" } : item) })} className="mt-1 w-full rounded-lg border px-2 py-2"><option value="unica">Única</option><option value="mensal">Mensal</option></select></label>
          <label className="text-xs font-medium">Descrição<input aria-label={`Descrição do movimento ${index + 1}`} maxLength={160} value={movimento.descricao} onChange={(event) => onChange({ ...value, movimentos: value.movimentos.map((item, i) => i === index ? { ...item, descricao: event.target.value } : item) })} className="mt-1 w-full rounded-lg border px-2 py-2" /></label>
          <button type="button" onClick={() => onChange({ ...value, movimentos: value.movimentos.filter((_, i) => i !== index) })} className="self-end rounded-lg border px-3 py-2 text-sm text-red-700"><Trash2 className="mr-1 inline h-4 w-4" />Remover {index + 1}</button>
        </div>)}
        <button type="button" onClick={() => onChange({ ...value, movimentos: [...value.movimentos, { data: contexto.data_inicio, tipo: "saida", valor: null, recorrencia: "unica", descricao: "" }] })} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium"><Plus className="mr-1 inline h-4 w-4" />Adicionar movimento</button>
        <label className="flex items-start gap-2 text-sm text-slate-800"><input type="checkbox" checked={value.despesas_completas} onChange={(event) => onChange({ ...value, despesas_completas: event.target.checked })} className="mt-1" /><span>Revisei e considero completas as saídas deste recorte, incluindo despesas recorrentes e pendências.</span></label>
      </fieldset>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={disabled || saving} onClick={onSimulate} className="rounded-lg bg-teal-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Simular sem salvar</button>
        <button type="button" disabled={disabled || saving || !canSave} onClick={onSave} className="rounded-lg border border-teal-800 px-4 py-2 text-sm font-semibold text-teal-900 disabled:opacity-50">{saving ? "Salvando..." : "Salvar premissas deste recorte"}</button>
        <button type="button" disabled={disabled || saving} onClick={onRestore} className="text-sm text-slate-600 underline disabled:opacity-50">Recarregar premissas salvas</button>
      </div>
      <p className="text-xs text-slate-500">{salvas?.revision ? `Revisão salva: ${salvas.revision}. ${salvas.updated_at ? `Atualizada em ${formatCalendarDate(salvas.updated_at)}.` : ""}` : "Nenhuma premissa salva."} Há um cenário-base salvo por vez: salvar este recorte substitui o cenário anterior. Agenda, OS e pagamentos permanecem preservados.</p>
    </div>
  </details>;
}
