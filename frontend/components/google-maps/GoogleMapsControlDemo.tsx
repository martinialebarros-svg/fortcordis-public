"use client";

import { useState } from "react";
import { requestMapsConfirmation, type MapsQuote } from "@/lib/google-maps-control";

const example: MapsQuote = {
  operation_mode: "paid_budget", budget_policy: "agenda_monitor", financial_limit_enforced: false, required: true, blocked: false,
  action: "SIMULAÇÃO — agendar com uma nova consulta de rota", service: "Google Maps Platform",
  services: ["routes_essentials", "distance_matrix_essentials"], max_calls: 4, estimated_cost_min_brl: 0, estimated_cost_max_brl: 0.144,
  route_estimate: { estimate_basis: "request_route_graph", cached_directions: 12, missing_directions: 1, first_departure_routes: 1, geocoding_units: 0, max_attempts_per_direction: 2, search_start: "2099-05-25", search_end: "2099-05-25" },
  limits: { action: { calls: 4, estimated_brl: 0.144 }, day: { calls: 650, estimated_brl: 25 }, month: { calls: 13000, estimated_brl: 500 } },
  consumption: { day: { calls: 2, estimated_brl: 0.072 }, month: { calls: 8, estimated_brl: 0.288 } },
  remaining: { day: { calls: 648, estimated_brl: 24.928 }, month: { calls: 12992, estimated_brl: 499.712 } },
  uncertainty: ["SIMULAÇÃO: consumo, rotas e preços fictícios, apenas para demonstração. A estimativa reserva todas as tentativas sem descontar franquia; não é a fatura Google. Confirmar aqui não envia consultas nem cria agendamento."],
};

export default function GoogleMapsControlDemo() {
  const [result, setResult] = useState("");
  const [waiting, setWaiting] = useState(false);
  const simulate = async (mode: "normal" | "potential" | "exceeded" = "normal") => {
    setWaiting(true);
    try {
      const confirmed = await requestMapsConfirmation(mode === "potential" ? { ...example, consumption: { day: { calls: 649, estimated_brl: 24.95 }, month: { calls: 12999, estimated_brl: 499.95 } }, remaining: { day: { calls: 1, estimated_brl: 0.05 }, month: { calls: 1, estimated_brl: 0.05 } }, alerts: ["Esta ação pode ultrapassar a referência diária. O consumo atual ainda está abaixo dela; a Agenda continua liberada mediante confirmação.", "Esta ação pode ultrapassar a referência mensal. O consumo atual ainda está abaixo dela; a Agenda continua liberada mediante confirmação."] } : mode === "exceeded" ? { ...example, consumption: { day: { calls: 700, estimated_brl: 26 }, month: { calls: 14000, estimated_brl: 510 } }, remaining: { day: { calls: 0, estimated_brl: 0 }, month: { calls: 0, estimated_brl: 0 } }, alerts: ["Referência atingida: a Agenda continua liberada; lotes e extras ficam bloqueados."] } : example);
      setResult(confirmed
        ? "Simulação confirmada: uma única execução poderia consultar até 4 unidades, inclusive acima da referência diária/mensal. Lotes e extras ficam sujeitos ao teto rígido. Nesta demonstração: 0 consultas e 0 agendamentos."
        : "Simulação cancelada: 0 consultas pagas; os dados do formulário continuam preenchidos.");
    } finally { setWaiting(false); }
  };
  return <section aria-labelledby="maps-demo-title" className="space-y-3 rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm text-teal-950">
    <h3 id="maps-demo-title" className="font-semibold">Experimentar o controle sem gerar custo</h3>
    <p>Demonstração com consumo, rotas e preços fictícios. Os botões abaixo não consultam Google, não salvam orçamento e não criam agendamentos.</p>
    <div className="overflow-x-auto rounded-lg bg-white p-3">
      <table className="w-full text-left"><caption className="mb-2 text-left font-semibold">Exemplo das referências — sem alterar a configuração</caption>
        <thead><tr><th className="p-2">Controle</th><th className="p-2">Referência do exemplo</th><th className="p-2">Ao atingir</th></tr></thead>
        <tbody>
          <tr><td className="p-2">Referência diária compartilhada</td><td className="p-2">650 chamadas ou R$ 25 estimados</td><td className="p-2">Agenda alerta e continua; extras bloqueiam</td></tr>
          <tr><td className="p-2">Referência mensal compartilhada</td><td className="p-2">13.000 chamadas ou R$ 500 estimados</td><td className="p-2">Agenda alerta e continua; extras bloqueiam</td></tr>
          <tr><td className="p-2">Recalcular matriz e tarefas automáticas</td><td className="p-2">0 novas chamadas no exemplo</td><td className="p-2">Exigem liberação própria posterior</td></tr>
        </tbody>
      </table>
    </div>
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={waiting} onClick={() => setResult("Simulação de geocodificação manual: sem popup de custo; até 1 chamada, com registro interno exclusivo desta execução e validade de 10 minutos. Limites diário e mensal respeitados; lotes e automações continuam bloqueados. Nenhuma coordenada é inventada ou marcada como confirmada. Nesta demonstração: 0 consultas e 0 cadastros alterados.")} className="rounded-lg border border-teal-300 bg-white px-3 py-2">Geocodificação manual — registro interno</button>
      <button type="button" disabled={waiting} onClick={() => setResult("Rota válida no cache: o agendamento passa pela validação normal, sem popup, token ou nova consulta paga.")} className="rounded-lg border border-teal-300 bg-white px-3 py-2">Rota já armazenada</button>
      <button type="button" disabled={waiting} onClick={() => void simulate()} className="rounded-lg border border-teal-300 bg-white px-3 py-2">Nova consulta de rota</button>
      <button type="button" disabled={waiting} onClick={() => void simulate("potential")} className="rounded-lg border border-teal-300 bg-white px-3 py-2">Esta ação pode ultrapassar a referência</button>
      <button type="button" disabled={waiting} onClick={() => void simulate("exceeded")} className="rounded-lg border border-teal-300 bg-white px-3 py-2">Referência atingida — Agenda liberada</button>
      <button type="button" disabled={waiting} onClick={() => setResult("Simulação de lote bloqueado: a proposta inicial não autoriza recalcular a matriz nem tarefas automáticas pagas. A Agenda continua liberada. Nesta demonstração: 0 consultas e 0 agendamentos.")} className="rounded-lg border border-teal-300 bg-white px-3 py-2">Lote bloqueado — Agenda liberada</button>
    </div>
    {result && <p role="status" className="rounded-lg bg-white p-3">{result}</p>}
    <p>Política escolhida: Agenda liberada com alertas de custo; teto rígido somente para lotes e extras. Esta demonstração não altera a política aplicada em nenhum ambiente.</p>
  </section>;
}
