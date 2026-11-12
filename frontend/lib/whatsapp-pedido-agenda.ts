import type { PreferenciaAgenda } from "@/lib/agenda-preferencias";

export interface PedidoAgenda {
  pedido_id: number;
  versao: number;
  clinica_id: number;
  resumo: string;
  dados_coletados?: { paciente?: string | null; tutor?: string | null; preferencia_agenda?: PreferenciaAgenda | null };
  paciente: { id: number; nome: string; tutor_id: number; tutor: string } | null;
  tutor: { id: number; nome: string } | null;
  servico_id: number | null;
  avisos: string[];
}

export function camposPedidoAgenda(pedido: PedidoAgenda) {
  return {
    clinica_id: String(pedido.clinica_id),
    paciente_id: pedido.paciente ? String(pedido.paciente.id) : "",
    tutor_id: pedido.tutor ? String(pedido.tutor.id) : "",
    servico_id: pedido.servico_id ? String(pedido.servico_id) : "",
    hora: "", // preferencia em texto nao define disponibilidade
    observacoes: `Pedido WhatsApp #${pedido.pedido_id}\n${pedido.resumo}`,
  };
}

export function divergenciasPedido(pedido: PedidoAgenda, paciente: string, tutor: string): string[] {
  const normalize = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase().replace(/\s+/g, " ");
  return ([['paciente', paciente], ['tutor', tutor]] as const).flatMap(([campo, escolhido]) => {
    const informado = pedido.dados_coletados?.[campo];
    return informado && escolhido && normalize(informado) !== normalize(escolhido)
      ? [`${campo === 'paciente' ? 'Pet' : 'Tutor'}: informado “${informado}”; selecionado “${escolhido}”.`] : [];
  });
}
