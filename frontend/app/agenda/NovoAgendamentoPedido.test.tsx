import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import NovoAgendamentoModal from "./NovoAgendamentoModal";
import api from "@/lib/axios";
import { DEFAULT_AGENDA_SEMANAL } from "@/lib/agenda-config";
vi.mock("@/components/fortinho/FortinhoProvider", () => ({ useFortinho: () => ({ confirm: vi.fn(), notify: vi.fn() }) }));
vi.mock("@/lib/credito-cliente", () => ({ consultarSaldoCreditoCliente: async () => 0 }));
vi.mock("@/lib/stable-catalog-cache", () => ({ loadStableCatalog: ({ load }: { load: () => unknown }) => load() }));
vi.mock("@/lib/axios", () => ({ default: { get: vi.fn(async (url: string) => {
  if (url.startsWith("/clinicas?")) return { data: { items: [{id:9,nome:"Vet World",latitude:-3.7,longitude:-38.5,telefone:"5585000000000"}] } };
  if (url.startsWith("/servicos?")) return { data: {items:[{id:3,nome:"Ecocardiograma",duracao_minutos:30}]} };
  return { data: { items: [] } };
}), post: vi.fn() } }));
describe("Novo agendamento vindo do bot", () => {
  it("exige conferência da divergência e invalida o aceite ao reabrir", async () => {
    const props = {isOpen:true, onClose:() => {}, onSuccess:() => {}, agendaSemanal:DEFAULT_AGENDA_SEMANAL, agendaFeriados:[], agendaExcecoes:[], defaultDate:"2026-09-20", pedidoWhatsApp:{pedido_id:12,versao:3,clinica_id:9,resumo:"Pet Galhofa, tutor Ricardo",dados_coletados:{paciente:"Galhofa",tutor:"Ricardo"},paciente:{id:5001,nome:"Rex",tutor_id:5002,tutor:"Maria"},tutor:{id:5002,nome:"Maria"},servico_id:3,avisos:[]}};
    const {container, rerender} = render(<NovoAgendamentoModal {...props} />);
    const aceite = await screen.findByRole("checkbox", {name:/Conferi a divergência/});
    expect(await screen.findByText(/informado “Galhofa”; selecionado “Rex”/)).toBeInTheDocument();
    fireEvent.submit(container.querySelector("form")!);
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(aceite);
    expect(aceite).toBeChecked();
    rerender(<NovoAgendamentoModal {...props} isOpen={false} />);
    rerender(<NovoAgendamentoModal {...props} />);
    await waitFor(() => expect(screen.getByRole("checkbox", {name:/Conferi a divergência/})).not.toBeChecked());
  });
  it("preserva dados fora da pagina do catalogo e exige escolha do horario", async () => {
    const { container } = render(<NovoAgendamentoModal isOpen onClose={() => {}} onSuccess={() => {}} agendaSemanal={DEFAULT_AGENDA_SEMANAL} agendaFeriados={[]} agendaExcecoes={[]} defaultDate="2026-09-20" pedidoWhatsApp={{pedido_id:12,versao:3,clinica_id:9,resumo:"Preferência: manhã",paciente:{id:5001,nome:"Rex",tutor_id:5002,tutor:"Maria"},tutor:{id:5002,nome:"Maria"},servico_id:3,avisos:[]}} />);
    expect(await screen.findByText("Agendar pedido #12")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText(/Rex/).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/Maria/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button",{name:"Domiciliar"})).toBeDisabled();
    expect(container.querySelector<HTMLInputElement>('input[type="time"]')?.value).toBe("");
  });
});
