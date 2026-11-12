"use client";

import { useEffect, useState, type FormEvent } from "react";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import { formatMapsBrl, MAPS_SKU_LABELS, type MapsOperationMode, type MapsPeriods } from "@/lib/google-maps-control";
import { MapsConsumption } from "./GoogleMapsActionGuard";
import GoogleMapsControlDemo from "./GoogleMapsControlDemo";

type Config = {
  operation_mode?: MapsOperationMode;
  agenda_budget_mode?: "enforce" | "monitor";
  clinic_geocode_manual_enabled?: boolean;
  enabled: boolean;
  limits: MapsPeriods;
  prices_usd?: Record<string, number> | null;
  fx_brl_per_usd_upper?: number | null;
  price_multiplier?: number | null;
  pricing_valid_until?: string | null;
  action_call_caps?: Record<string, number>;
  automatic_policies?: Record<string, { enabled: boolean; limits: MapsPeriods; skus: string[] }>;
  opening_usage?: MapsPeriods | null;
  opening_usage_as_of?: string | null;
  opening_usage_basis?: string | null;
};
type History = { id?: number; created_at: number | string; kind: string; reason?: string; message?: string; action: string; sku?: string; calls: number; estimated_brl?: number };
type Status = {
  agenda_cache_first?: boolean;
  agenda_confirmation_required?: boolean;
  agenda_budget_mode?: "enforce" | "monitor";
  alerts?: string[];
  operation_mode?: MapsOperationMode; message?: string;
  configured: boolean; enabled?: boolean; revision: number | null; config: Config | null;
  limits?: MapsPeriods; consumption?: MapsPeriods; remaining?: MapsPeriods; history?: History[];
  blocked?: boolean; reason?: string; billing_note?: string; consumed_since?: string | null;
  automatic_policies?: Record<string, { enabled: boolean; consumption: MapsPeriods; limits: MapsPeriods }>;
};
type Fields = Record<string, string>;
const periods = [["action", "Por ação"], ["day", "Por dia"], ["month", "Por mês"]] as const;
const skuLabels = MAPS_SKU_LABELS;
const inputClass = "mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-gray-900";
const dateLabel = (value: string | number) => {
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("pt-BR", { timeZone: "America/Fortaleza" });
};

function configToFields(config: Config | null): Fields {
  const fields: Fields = {};
  for (const [period] of periods) {
    fields[`${period}_calls`] = config?.limits?.[period]?.calls?.toString() ?? "";
    fields[`${period}_brl`] = config?.limits?.[period]?.estimated_brl?.toString() ?? "";
  }
  for (const sku of Object.keys(skuLabels)) fields[`price_${sku}`] = config?.prices_usd?.[sku]?.toString() ?? "";
  fields.fx = config?.fx_brl_per_usd_upper?.toString() ?? "";
  fields.multiplier = config?.price_multiplier?.toString() ?? "";
  fields.validUntil = config?.pricing_valid_until ?? "";
  fields.openingDate = config?.opening_usage_as_of ?? "";
  fields.openingBasis = config?.opening_usage_basis ?? "";
  for (const period of ["day", "month"] as const) {
    fields[`opening_${period}_calls`] = config?.opening_usage?.[period]?.calls?.toString() ?? "";
    fields[`opening_${period}_brl`] = config?.opening_usage?.[period]?.estimated_brl?.toString() ?? "";
  }
  for (const [period] of periods) {
    fields[`auto_${period}_calls`] = config?.automatic_policies?.whatsapp_agenda?.limits?.[period]?.calls?.toString() ?? "";
    fields[`auto_${period}_brl`] = config?.automatic_policies?.whatsapp_agenda?.limits?.[period]?.estimated_brl?.toString() ?? "";
  }
  return fields;
}

export default function GoogleMapsAdminPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [fields, setFields] = useState<Fields>({});
  const [enabled, setEnabled] = useState(false);
  const [operationMode, setOperationMode] = useState<MapsOperationMode>("paid_budget");
  const [agendaBudgetMode, setAgendaBudgetMode] = useState<"enforce" | "monitor">("monitor");
  const [automaticEnabled, setAutomaticEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = async () => {
    setLoading(true); setError("");
    try {
      const { data } = await api.get<Status>("/google-maps-control/status");
      setStatus(data); setFields(configToFields(data.config)); setEnabled(Boolean(data.config?.enabled));
      setOperationMode(data.config?.operation_mode ?? "paid_budget");
      setAgendaBudgetMode(data.config ? data.config.agenda_budget_mode ?? "enforce" : "monitor");
      setAutomaticEnabled(Boolean(data.config?.automatic_policies?.whatsapp_agenda?.enabled));
    } catch (error) {
      setError(extractApiErrorMessageSync(error, "Não foi possível consultar os controles do Google Maps."));
    } finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const changeOperationMode = (next: MapsOperationMode) => {
    setOperationMode(next);
    if (next === "paid_budget" && status?.config?.operation_mode === "cache_only") {
      // Opening a paid budget is a new administrative choice, never an
      // implicit conversion of cache-only zeros into an approved budget.
      setFields(configToFields(null));
      setEnabled(false);
      setAutomaticEnabled(false);
    }
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!status) return;
    setSaving(true); setError(""); setMessage("");
    try {
      if (operationMode === "cache_only") {
        await api.put("/google-maps-control/config", {
          operation_mode: "cache_only", enabled: true,
          limits: Object.fromEntries(periods.map(([period]) => [period, { calls: 0, estimated_brl: 0 }])),
          expected_revision: status.revision,
        });
        await load();
        setMessage("Modo R$ 0 — somente cache salvo. Novas chamadas ao Google ficam bloqueadas; o histórico de consumo é preservado.");
        return;
      }
      const requiredKeys = [...periods.flatMap(([period]) => [`${period}_calls`, `${period}_brl`]), ...Object.keys(skuLabels).map((sku) => `price_${sku}`), "fx", "multiplier"];
      if (automaticEnabled) requiredKeys.push(...periods.flatMap(([period]) => [`auto_${period}_calls`, `auto_${period}_brl`]));
      if (enabled && !status.config?.opening_usage) requiredKeys.push("opening_day_calls", "opening_day_brl", "opening_month_calls", "opening_month_brl");
      if (requiredKeys.some((key) => fields[key]?.trim() === "" || fields[key] == null || !Number.isFinite(Number(fields[key])))) {
        throw new Error("Preencha os limites escolhidos e os preços antes de salvar. Nenhum teto será presumido.");
      }
      if (!/(Z|[+-]\d{2}:\d{2})$/.test(fields.validUntil || "") || !Number.isFinite(new Date(fields.validUntil).getTime())) {
        throw new Error("Informe uma validade dos preços com data, hora e fuso, por exemplo no formato AAAA-MM-DDTHH:mm:ss-03:00.");
      }
      if (enabled && !status.config?.opening_usage && (!fields.openingDate || !fields.openingBasis)) throw new Error("Informe a data e a origem do consumo anterior à ativação.");
      const limits: MapsPeriods = {};
      for (const [period] of periods) limits[period] = { calls: Number(fields[`${period}_calls`]), estimated_brl: Number(fields[`${period}_brl`]) };
      const prices = Object.fromEntries(Object.keys(skuLabels).map((sku) => [sku, Number(fields[`price_${sku}`])]));
      const automaticPolicies = { ...status.config?.automatic_policies };
      if (automaticEnabled) {
        const automaticLimits: MapsPeriods = {};
        for (const [period] of periods) automaticLimits[period] = { calls: Number(fields[`auto_${period}_calls`]), estimated_brl: Number(fields[`auto_${period}_brl`]) };
        automaticPolicies.whatsapp_agenda = { enabled: true, limits: automaticLimits, skus: Object.keys(skuLabels).filter((sku) => sku !== "geocoding") };
      } else if (automaticPolicies.whatsapp_agenda) automaticPolicies.whatsapp_agenda = { ...automaticPolicies.whatsapp_agenda, enabled: false };
      await api.put("/google-maps-control/config", {
        operation_mode: "paid_budget", agenda_budget_mode: agendaBudgetMode, enabled, limits, prices_usd: prices, fx_brl_per_usd_upper: Number(fields.fx),
        price_multiplier: Number(fields.multiplier), pricing_valid_until: new Date(fields.validUntil).toISOString(),
        clinic_geocode_manual_enabled: status.config?.clinic_geocode_manual_enabled ?? false,
        action_call_caps: status.config?.action_call_caps ?? {},
        automatic_policies: automaticPolicies,
        ...(status.config?.opening_usage ? {
          opening_usage: status.config.opening_usage, opening_usage_as_of: status.config.opening_usage_as_of,
          opening_usage_basis: status.config.opening_usage_basis,
        } : enabled ? {
          opening_usage: { day: { calls: Number(fields.opening_day_calls), estimated_brl: Number(fields.opening_day_brl) }, month: { calls: Number(fields.opening_month_calls), estimated_brl: Number(fields.opening_month_brl) } },
          opening_usage_as_of: fields.openingDate, opening_usage_basis: fields.openingBasis,
        } : {}),
        expected_revision: status.revision,
      });
      await load();
      setMessage("Controles salvos. As próximas ações serão avaliadas com esta configuração no servidor.");
    } catch (error) {
      setError(extractApiErrorMessageSync(error, "Não foi possível salvar os controles. Revise os campos e atualize os dados."));
    } finally { setSaving(false); }
  };

  const field = (key: string, label: string, options: { min?: number; step?: string; placeholder?: string } = {}) => (
    <label className="block text-sm font-medium text-gray-700" key={key}>{label}
      <input required type="number" min={options.min ?? 0} step={options.step ?? "0.000001"} value={fields[key] ?? ""} placeholder={options.placeholder ?? "Escolha um valor"} onChange={(event) => setFields({ ...fields, [key]: event.target.value })} className={inputClass} />
    </label>
  );

  if (status?.operation_mode === "temporary_open") return <section className="fc-settings-card space-y-4" aria-labelledby="maps-admin-title">
    <h2 id="maps-admin-title" className="text-lg font-semibold">Custos do Google Maps</h2>
    <div role="alert" className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950">
      <h3 className="font-semibold">Liberação temporária ativa</h3>
      <p>As consultas Google estão liberadas, inclusive na Agenda e nas tarefas automáticas. O bloqueio financeiro e a confirmação de custo por ação estão temporariamente suspensos.</p>
      <p>Pode haver cobrança. Não há teto de gasto aplicado por este controle durante a liberação.</p>
    </div>
    <p className="text-sm text-gray-600">{status.billing_note || "Consumo e custo desta liberação não foram conciliados. O histórico anterior foi preservado."}</p>
    <p className="text-sm text-gray-600">A reativação dos controles exige encerrar a liberação operacional e revisar o consumo acumulado. Salvar um orçamento neste painel não encerra a liberação.</p>
    {error && <p role="alert" className="text-red-800">{error}</p>}
    <button type="button" disabled={loading} onClick={() => void load()} className="rounded-lg border px-3 py-2 text-sm">Atualizar situação</button>
  </section>;

  return <section className="fc-settings-card space-y-6" aria-labelledby="maps-admin-title">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 id="maps-admin-title" className="text-lg font-semibold">Custos do Google Maps</h2><p className="mt-1 text-sm text-gray-600">Limites aplicados no servidor antes de cada chamada. Valores em reais são estimativas conservadoras, não a fatura do Google.</p></div>
      <button type="button" disabled={loading || saving} onClick={() => void load()} className="rounded-lg border px-3 py-2 text-sm">Atualizar consumo</button>
    </div>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-800">{error}</p>}
    {message && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-emerald-800">{message}</p>}
    {loading ? <p role="status">Consultando limites…</p> : status && <>
      {status.agenda_cache_first && <>
        <div className="rounded-lg border border-teal-200 bg-teal-50 p-3 text-sm text-teal-950">
          <h3 className="font-semibold">Agenda: cache primeiro, confirmação somente para consulta nova</h3>
          <p className="mt-1">Agendamentos com rota válida e operações sem consulta paga seguem pela validação normal, mesmo se o orçamento estiver esgotado ou indisponível. Uma consulta externa exige confirmação limitada no servidor. No modo de alertas, a data de revisão de preços/câmbio também gera aviso sem suspender a Agenda; a última estimativa continua identificada como desatualizada. O orçamento da Agenda pode ser ultrapassado; lotes e extras continuam sujeitos ao teto rígido. Se ela for suspensa, o formulário é preservado.</p>
        </div>
        <GoogleMapsControlDemo />
      </>}
      <p className={`rounded-lg p-3 text-sm ${status.config?.enabled && !status.blocked ? "bg-emerald-50 text-emerald-900" : "bg-amber-50 text-amber-900"}`}>
        {status.config?.operation_mode === "cache_only" ? "Modo R$ 0 — somente cache. Novas chamadas ao Google estão bloqueadas, inclusive em tarefas automáticas." : status.config?.enabled && !status.blocked ? "Chamadas habilitadas sob limites e confirmação por ação." : status.reason === "pricing_expired" ? "Chamadas pagas suspensas: a validade dos preços/câmbio expirou. Revise a configuração." : "Chamadas pagas suspensas. Defina os limites e a política de preços antes de habilitar."}
      </p>
      {status.agenda_budget_mode === "monitor" && <div role="status" className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"><strong>Agenda liberada com alertas; lotes e extras sob teto rígido</strong><p>Não há teto financeiro diário ou mensal para a Agenda neste modo. {status.agenda_confirmation_required === false ? "Custos registrados internamente, sem popup na Agenda. Cada execução tem quantidade e custo máximos finitos no servidor; os alertas de custo ficam nesta área administrativa." : "Cada consulta nova exige confirmação com quantidade e custo máximos finitos."} O consumo da Agenda também reduz o saldo dos extras.</p>{status.alerts?.map((alert, index) => <p key={index}>{alert}</p>)}</div>}
      {status.config?.clinic_geocode_manual_enabled && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">Geocodificação manual de clínicas: uma chamada por execução, com registro interno, sem popup e respeitando os limites diário e mensal. Esta permissão não libera lotes nem automações.</p>}
      <MapsConsumption reference={status.agenda_budget_mode === "monitor"} consumption={status.consumption} remaining={status.remaining} limits={status.limits ?? status.config?.limits} />
      <p className="text-sm text-gray-600">O consumo inclui o saldo inicial informado e os envios registrados{status.consumed_since ? ` desde ${dateLabel(status.consumed_since)}` : " após a ativação"}. Não representa uma reconstrução da fatura ou do histórico completo da conta Google.</p>
      {status.billing_note && <p className="text-sm text-gray-600">{status.billing_note}</p>}
      <p className="text-sm text-gray-600">O consumo contabiliza o teto estimado dos envios registrados. Uma franquia pode estar sendo consumida por outros projetos da conta; ela não é deduzida do limite local. Descontos por volume e dados atrasados do Billing não liberam saldo automaticamente.</p>
      <form onSubmit={save} className="space-y-5">
        <fieldset disabled={saving || loading} className="space-y-4">
          <legend className="font-semibold">Limites escolhidos pela administração</legend>
          <label className="block text-sm font-medium text-gray-700">Modo de operação
            <select value={operationMode} onChange={(event) => changeOperationMode(event.target.value as MapsOperationMode)} className={inputClass}>
              <option value="cache_only">R$ 0 — somente cache</option>
              <option value="paid_budget">Chamadas Google com limites e confirmação</option>
            </select>
          </label>
          {operationMode === "cache_only" ? <div className="space-y-3 rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm text-teal-950">
            <h3 className="font-semibold">Zero novas chamadas e R$ 0 de custo adicional</h3>
            <p>Rotas já armazenadas e ainda válidas e ajustes manuais podem ser utilizados. Novas rotas, atualizações de rota e consultas de coordenadas ao Google ficam bloqueadas.</p>
            <p>Sem uma rota válida disponível, a operação é suspensa. As regras da agenda são preservadas; nenhuma distância, duração ou disponibilidade é presumida.</p>
            <div className="grid gap-3 sm:grid-cols-3">{periods.map(([key, label]) => <div key={key} className="rounded-lg border border-teal-200 bg-white p-3"><h4 className="font-semibold">{label}</h4><p>0 novas chamadas</p><p>R$ 0 de custo adicional</p></div>)}</div>
            <p>Este modo também bloqueia chamadas externas das tarefas automáticas. Não presume saldo de franquia gratuita, não exige preços ou câmbio e não reinicia o histórico de consumo.</p>
          </div> : <>
          <label className="block text-sm font-medium text-gray-700">Ao atingir o orçamento da Agenda
            <select value={agendaBudgetMode} onChange={(event) => setAgendaBudgetMode(event.target.value as "enforce" | "monitor")} className={inputClass}>
              <option value="monitor">Manter Agenda liberada com alertas; bloquear lotes e extras</option>
              <option value="enforce">Bloquear também novas consultas pagas da Agenda</option>
            </select>
          </label>
          <p className="text-sm text-gray-600">Nenhum valor financeiro é preenchido automaticamente. {agendaBudgetMode === "monitor" ? "Na Agenda, os valores em reais e os totais por dia/mês são referências de alerta. O máximo de chamadas por ação define o teto finito da confirmação. Lotes e tarefas extras respeitam todos os limites." : "O limite de chamadas e o limite em reais precisam ser respeitados ao mesmo tempo."}</p>
          <div className="grid gap-4 md:grid-cols-3">{periods.map(([key, label]) => <div key={key} className="space-y-3 rounded-xl border p-4"><h3 className="font-medium">{label}</h3>{field(`${key}_calls`, `Máximo de chamadas — ${label.toLowerCase()}`, { step: "1" })}{field(`${key}_brl`, `Máximo estimado em R$ — ${label.toLowerCase()}`)}</div>)}</div>
          <details className="rounded-xl border p-4" open={!status.config}>
            <summary className="cursor-pointer font-medium">Preços, câmbio e validade da estimativa</summary>
            <p className="my-3 text-sm text-gray-600">Use os preços máximos aplicáveis à conta. Inclua uma margem para câmbio e cobranças adicionais. Após a validade, novas chamadas ficam suspensas até revisão.</p>
            <div className="grid gap-4 md:grid-cols-2">{Object.entries(skuLabels).map(([sku, label]) => field(`price_${sku}`, `${label} — USD por unidade`, { min: 0.000001 }))}{field("fx", "Câmbio máximo — R$ por USD", { min: 0.000001 })}{field("multiplier", "Multiplicador conservador de preço", { min: 1 })}
              <label className="block text-sm font-medium text-gray-700">Data de revisão dos preços/câmbio (data ISO com fuso)
                <input required type="text" value={fields.validUntil ?? ""} placeholder="AAAA-MM-DDTHH:mm:ss-03:00" onChange={(event) => setFields({ ...fields, validUntil: event.target.value })} className={inputClass} />
              </label>
            </div>
          </details>
          <details className="rounded-xl border p-4 text-sm">
            <summary className="cursor-pointer font-semibold">Tarefas automáticas e limites próprios</summary>
            <p className="mt-2">Sem política explícita, tarefas automáticas ficam bloqueadas. A autorização abaixo abrange consultas de rota do assistente de agenda no WhatsApp, sem popup. Os limites próprios e globais continuam obrigatórios.</p>
            <label className="my-3 flex items-start gap-2 font-medium"><input type="checkbox" checked={automaticEnabled} onChange={(event) => setAutomaticEnabled(event.target.checked)} className="mt-1" /><span>Autorizar consultas automáticas de rota da agenda no WhatsApp.</span></label>
            {automaticEnabled && <div className="grid gap-4 md:grid-cols-3">{periods.map(([key, label]) => <div key={key} className="space-y-3 rounded-lg border p-3"><h4 className="font-medium">Automático — {label.toLowerCase()}</h4>{field(`auto_${key}_calls`, `Chamadas automáticas — ${label.toLowerCase()}`, { step: "1" })}{field(`auto_${key}_brl`, `Máximo automático em R$ — ${label.toLowerCase()}`)}</div>)}</div>}
            {Object.entries(status.automatic_policies ?? {}).map(([key, policy]) => <div key={key} className="mt-4"><h4 className="font-medium">{key === "whatsapp_agenda" ? "Agenda no WhatsApp" : key} — {policy.enabled ? "habilitada" : "suspensa"}</h4><MapsConsumption consumption={policy.consumption} limits={policy.limits} /></div>)}
          </details>
          <label className="flex items-start gap-2 text-sm font-medium"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} className="mt-1" /><span>Habilitar chamadas neste ambiente, com os limites acima e confirmação para cada ação manual.</span></label>
          <div className="rounded-xl border p-4 text-sm">
            <h3 className="font-semibold">Consumo anterior à ativação</h3>
            <p className="my-2">Para não criar saldo fictício, a primeira ativação exige o consumo já realizado no dia e no mês. Use telemetria verificada ou um teto conservador que cubra dados atrasados. Valores sintéticos são exclusivos de testes.</p>
            {status.config?.opening_usage ? <><MapsConsumption consumption={status.config.opening_usage} /><p className="mt-2">Registrado em {status.config.opening_usage_as_of}. Este saldo inicial é preservado após a ativação. A telemetria anterior pode estar incompleta; este valor não comprova o total da conta Google nem saldo de franquia gratuita.</p></> : enabled ? <div className="grid gap-4 md:grid-cols-2">
              {field("opening_day_calls", "Chamadas anteriores — dia", { step: "1" })}{field("opening_day_brl", "Custo anterior estimado em R$ — dia")}
              {field("opening_month_calls", "Chamadas anteriores — mês", { step: "1" })}{field("opening_month_brl", "Custo anterior estimado em R$ — mês")}
              <label className="block font-medium">Data do saldo inicial (Fortaleza)<input required type="date" value={fields.openingDate ?? ""} onChange={(event) => setFields({ ...fields, openingDate: event.target.value })} className={inputClass} /></label>
              <label className="block font-medium">Origem do saldo inicial<select required value={fields.openingBasis ?? ""} onChange={(event) => setFields({ ...fields, openingBasis: event.target.value })} className={inputClass}><option value="">Selecione a evidência</option><option value="verified_telemetry">Telemetria verificada</option><option value="conservative_upper_bound">Teto conservador documentado</option><option value="synthetic_stage">Valores sintéticos de teste/stage</option></select></label>
            </div> : <p>Será solicitado ao marcar a habilitação. Nenhum consumo anterior é presumido como zero.</p>}
          </div>
          </>}
          <button type="submit" className="rounded-lg bg-teal-700 px-4 py-2 font-semibold text-white disabled:opacity-50">{saving ? "Salvando…" : "Salvar controles"}</button>
        </fieldset>
      </form>
      <div><h3 className="mb-3 font-semibold">Histórico recente de consumo e bloqueios</h3>
        {(status.history ?? []).length ? <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-2">Horário</th><th className="p-2">Ação</th><th className="p-2">Resultado / motivo</th><th className="p-2">Chamadas</th><th className="p-2">Estimativa</th></tr></thead><tbody>{status.history?.map((item, index) => <tr className="border-b" key={item.id ?? index}><td className="p-2">{dateLabel(item.created_at)}</td><td className="p-2">{item.action}</td><td className="p-2">{item.kind === "internal_authorized" ? "Registro interno — execução limitada" : item.kind === "budget_alert" ? "Alerta — Agenda liberada" : item.kind === "blocked" ? "Bloqueada" : item.kind === "call" ? "Envio registrado" : item.kind === "configuration" ? "Configuração atualizada" : item.kind}{item.message ? ` — ${item.message}` : item.reason ? ` — ${item.reason}` : ""}</td><td className="p-2">{item.calls}</td><td className="p-2">{formatMapsBrl(item.estimated_brl)}</td></tr>)}</tbody></table></div> : <p className="text-sm text-gray-600">Nenhum registro disponível nesta janela.</p>}
        <p className="mt-3 text-xs text-gray-500">Histórico sem chaves, endereços, coordenadas ou conteúdo dos atendimentos. Horários em Fortaleza.</p>
      </div>
    </>}
  </section>;
}
