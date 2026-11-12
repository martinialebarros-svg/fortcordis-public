"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { usePathname } from "next/navigation";
import { formatMapsBrl, MAPS_SKU_LABELS, mapsConfirmationStore, type MapsPeriods } from "@/lib/google-maps-control";

export function MapsConsumption({ consumption, remaining, limits, reference = false }: {
  consumption?: MapsPeriods; remaining?: MapsPeriods; limits?: MapsPeriods; reference?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Consumo e saldo dos limites Google Maps</caption>
        <thead><tr className="border-b"><th className="py-2 pr-3">Período</th><th className="p-2">Consumo</th><th className="p-2">{reference ? "Referência / teto dos extras" : "Limite"}</th><th className="p-2">Saldo</th></tr></thead>
        <tbody>{(["day", "month"] as const).map((period) => (
          <tr key={period} className="border-b align-top">
            <th className="py-2 pr-3 font-medium">{period === "day" ? "Dia" : "Mês"}</th>
            <td className="p-2">{consumption?.[period]?.calls ?? "—"} chamadas<br />{formatMapsBrl(consumption?.[period]?.estimated_brl)}</td>
            <td className="p-2">{limits?.[period]?.calls ?? "Não definido"} chamadas<br />{formatMapsBrl(limits?.[period]?.estimated_brl)}</td>
            <td className="p-2">{remaining?.[period]?.calls ?? "—"} chamadas<br />{formatMapsBrl(remaining?.[period]?.estimated_brl)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export default function GoogleMapsActionGuard() {
  const state = useSyncExternalStore(mapsConfirmationStore.subscribe, mapsConfirmationStore.getSnapshot, mapsConfirmationStore.getSnapshot);
  const current = state.queue[0];
  const pathname = usePathname();
  const lastPath = useRef(pathname);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (lastPath.current !== pathname) {
      mapsConfirmationStore.cancelAll();
      lastPath.current = pathname;
    }
  }, [pathname]);

  useEffect(() => {
    if (!current) return;
    const priorFocus = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        mapsConfirmationStore.respond(current.id, false);
      }
      if (event.key === "Tab") {
        const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>("button");
        if (!buttons?.length) return;
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => { document.removeEventListener("keydown", onKey, true); priorFocus?.focus(); };
  }, [current]);

  if (typeof document === "undefined") return null;
  return createPortal(<>
    {state.notice && <div role="alert" className={`fixed inset-x-4 top-4 mx-auto flex max-w-3xl items-start gap-4 rounded-xl border p-4 text-sm shadow-xl ${state.noticeKind === "warning" ? "border-amber-300 bg-amber-50 text-amber-950" : "border-red-300 bg-red-50 text-red-950"}`} style={{ zIndex: 2147483646 }}>
      <div className="flex-1"><strong>{state.noticeKind === "warning" ? "Alerta de custo — Agenda liberada" : "Esta consulta ao Google Maps precisa de atenção"}</strong><p className="mt-1">{state.notice}</p><p className="mt-1">{state.noticeKind === "warning" ? "Este alerta não suspende a ação confirmada. As regras de agendamento e o teto desta confirmação continuam valendo." : "Os dados preenchidos permanecem no formulário. Rotas já válidas e ações sem consulta paga continuam disponíveis. Nenhuma rota ou disponibilidade será presumida."}</p></div>
      <button type="button" className="rounded border border-red-300 px-2 py-1" onClick={mapsConfirmationStore.dismissNotice}>Fechar aviso</button>
    </div>}
    {current && <div className="fixed inset-0 flex items-center justify-center bg-slate-950/60 p-4" style={{ zIndex: 2147483647 }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="maps-confirm-title" aria-describedby="maps-confirm-description" className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white p-6 text-gray-900 shadow-2xl">
        <div className="min-h-0 overflow-y-auto pr-1">
        <h2 id="maps-confirm-title" className="text-xl font-semibold">Confirmar consulta ao Google Maps</h2>
        <p id="maps-confirm-description" className="mt-2 text-sm text-gray-600">Esta ação pode gerar cobrança adicional. A confirmação vale apenas para a execução abaixo e continua sujeita aos limites do servidor.</p>
        <dl className="my-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="font-semibold">Ação</dt><dd>{current.quote.action}</dd>
          <dt className="font-semibold">Serviço</dt><dd>{current.quote.service}{current.quote.services?.length ? ` — ${current.quote.services.map((sku) => MAPS_SKU_LABELS[sku] || sku).join(", ")}` : ""}</dd>
          <dt className="font-semibold">Máximo</dt><dd>{current.quote.max_calls} chamadas/unidades cobradas</dd>
          <dt className="font-semibold">Custo adicional estimado</dt><dd>{formatMapsBrl(current.quote.estimated_cost_min_brl)} a {formatMapsBrl(current.quote.estimated_cost_max_brl)}</dd>
          <dt className="font-semibold">{current.quote.budget_policy === "agenda_monitor" ? "Teto desta confirmação" : "Limite por ação"}</dt><dd>{current.quote.budget_policy === "agenda_monitor" ? current.quote.max_calls : current.quote.limits?.action?.calls ?? "Não definido"} chamadas · {formatMapsBrl(current.quote.budget_policy === "agenda_monitor" ? current.quote.estimated_cost_max_brl : current.quote.limits?.action?.estimated_brl)}</dd>
        </dl>
        {current.quote.route_estimate && <div className="mb-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-800">
          <strong>Estimativa desta busca, após consultar a matriz</strong>
          <p>Período considerado: {current.quote.route_estimate.search_start.split("-").reverse().join("/")} a {current.quote.route_estimate.search_end.split("-").reverse().join("/")}.</p>
          <p>{current.quote.route_estimate.cached_directions} trecho(s) com rota válida em cache, sem nova cobrança. Até {current.quote.route_estimate.missing_directions} trecho(s) sem rota válida podem precisar de consulta.</p>
          {current.quote.route_estimate.first_departure_routes > 0 && <p>Inclui até {current.quote.route_estimate.first_departure_routes} rota adicional para validar a primeira saída.</p>}
          {current.quote.route_estimate.geocoding_units > 0 && <p>Inclui até {current.quote.route_estimate.geocoding_units} consulta de coordenadas da base operacional.</p>}
          <p>O máximo inclui até {current.quote.route_estimate.max_attempts_per_direction} tentativas por trecho: consulta de rota e alternativa em caso de falha. Os mesmos trechos são reutilizados entre horários e dias; o consumo pode ser menor.</p>
        </div>}
        {current.quote.budget_policy === "agenda_monitor" && <div className={`mb-3 rounded-lg border p-3 text-sm ${current.quote.alerts?.length ? "border-amber-300 bg-amber-50 text-amber-950" : "border-slate-200 bg-slate-50 text-slate-800"}`}><strong>{current.quote.alerts?.length ? "Agenda liberada com alertas" : "Agenda liberada"}</strong><p>As referências diárias e mensais não bloqueiam esta ação da Agenda. A confirmação vale apenas para a quantidade e o custo máximo apresentados nesta execução. Lotes e tarefas extras mantêm seus próprios bloqueios.</p>{current.quote.alerts?.map((alert, index) => <p className="mt-1" key={index}>{alert}</p>)}</div>}
        {current.quote.pricing_review_due && <p className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">Estimativa desatualizada — revisão pendente{current.quote.pricing_reference_valid_until ? ` desde ${new Date(current.quote.pricing_reference_valid_until).toLocaleDateString("pt-BR", { timeZone: "America/Fortaleza" })}` : ""}. A Agenda continua liberada com confirmação limitada por ação.</p>}
        <MapsConsumption reference={current.quote.budget_policy === "agenda_monitor"} consumption={current.quote.consumption} remaining={current.quote.remaining} limits={current.quote.limits} />
        <div className="my-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
          <p>A estimativa não é a cobrança efetiva. Franquia compartilhada, faixas de preço, câmbio e atraso do faturamento podem alterar o valor.</p>
          {current.quote.uncertainty?.map((item, index) => <p key={index} className="mt-1">{item}</p>)}
        </div>
        {state.queue.length > 1 && <p className="mb-3 text-sm text-gray-600">Há {state.queue.length - 1} outra(s) ação(ões) aguardando confirmação separada.</p>}
        </div>
        <div className="mt-4 flex shrink-0 flex-wrap justify-end gap-3 border-t border-gray-200 pt-4">
          <button ref={cancelRef} type="button" onClick={() => mapsConfirmationStore.respond(current.id, false)} className="rounded-lg border border-gray-300 px-4 py-2 font-medium">Cancelar</button>
          <button type="button" onClick={() => mapsConfirmationStore.respond(current.id, true)} className="rounded-lg bg-teal-700 px-4 py-2 font-semibold text-white">Confirmar esta ação</button>
        </div>
      </div>
    </div>}
  </>, document.body);
}
