import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_AGENDA_SEMANAL } from "@/lib/agenda-config";
import type { PedidoAgenda } from "@/lib/whatsapp-pedido-agenda";
import { renderAgendaWhatsAppTemplate } from "@/lib/agenda-whatsapp-templates";

const { apiGet, apiPost, apiPut } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: { get: (...args: unknown[]) => apiGet(...args), post: (...args: unknown[]) => apiPost(...args), put: (...args: unknown[]) => apiPut(...args) } }));
vi.mock("@/components/fortinho/FortinhoProvider", () => ({ useFortinho: () => ({ notify: vi.fn(), confirm: vi.fn(async () => true) }) }));
vi.mock("@/lib/stable-catalog-cache", () => ({ loadStableCatalog: ({ load }: { load: () => Promise<unknown> }) => load() }));
vi.mock("@/lib/credito-cliente", () => ({ consultarSaldoCreditoCliente: vi.fn(async () => 0) }));

import NovoAgendamentoModal from "./NovoAgendamentoModal";

const SERVICE = "Consulta cardiológica + Ecocardiograma + Eletrocardiograma";
const CLINIC = { id: 7, nome: "Clínica teste", telefone: "5585000000000", latitude: -3.73, longitude: -38.52 };
const PATIENT = { id: 21, nome: "Rex", tutor_id: 11, tutor: "Maria" };
const TUTOR = { id: 11, nome: "Maria" };
const REQUEST: PedidoAgenda = { pedido_id: 9, versao: 1, clinica_id: 7, resumo: "Solicitação de teste", paciente: PATIENT, tutor: TUTOR, servico_id: 3, avisos: [] };
const OFFER = { inicio: "2026-10-15 14:00", fim: "2026-10-15 14:40", score: 0, risco: 0, tempo_deslocamento_total_min: 0, anterior: null, proximo: null };

let serviceName: string;
let savedServiceName: string | undefined;

function mount(appointment?: Record<string, unknown>) {
  return render(<NovoAgendamentoModal isOpen isAdmin pedidoWhatsApp={appointment ? undefined : REQUEST} agendamento={appointment}
    onClose={vi.fn()} onSuccess={vi.fn()} defaultDate="2026-10-15" defaultTime="14:00"
    agendaSemanal={DEFAULT_AGENDA_SEMANAL} agendaFeriados={[]} agendaExcecoes={[]} />);
}

async function createAppointment() {
  mount();
  const offersButton = screen.getByRole("button", { name: "Gerar melhor oferta" });
  await waitFor(() => expect(offersButton).toBeEnabled());
  fireEvent.click(offersButton);
  fireEvent.click(await screen.findByRole("button", { name: "Cliente aceitou esta oferta" }));
  const saveButton = screen.getByRole("button", { name: "Salvar Agendamento" });
  await waitFor(() => expect(saveButton).toBeEnabled());
  fireEvent.click(saveButton);
  await screen.findByLabelText("Mensagem pronta");
}

describe("mensagem de agenda com serviço", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-14T13:00:00Z"));
    serviceName = SERVICE;
    savedServiceName = undefined;
    apiGet.mockReset(); apiPost.mockReset(); apiPut.mockReset();
    apiGet.mockImplementation(async (url: string) => {
      if (url === `/tutores/${TUTOR.id}/panorama`) return { data: { tutor: TUTOR, pets: [PATIENT], resumo: { total_pets: 1 } } };
      if (url === `/pacientes/${PATIENT.id}`) return { data: PATIENT };
      if (url.startsWith("/pacientes")) return { data: { items: [PATIENT] } };
      if (url.startsWith("/tutores")) return { data: { items: [TUTOR] } };
      if (url.startsWith("/clinicas")) return { data: { items: [CLINIC] } };
      if (url.startsWith("/servicos")) return { data: { items: [{ id: 3, nome: serviceName, duracao_minutos: 40 }] } };
      return { data: { items: [] } };
    });
    apiPost.mockImplementation(async (url: string) => {
      if (url === "/agenda/assistente/validar-oferta") return { data: { ok: true, valido: true } };
      if (url === "/agenda") return { data: { id: 901, servico_id: 3, servico: savedServiceName } };
      if (url === "/agenda/901/whatsapp/modelo") return { data: { ok: true } };
      return { data: { panorama_ofertas: { items: [OFFER] } } };
    });
    apiPut.mockResolvedValue({ data: { id: 901, servico_id: 3 } });
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

  it("seleciona a variante nova após salvar e preserva o serviço completo na prévia, cópia, link e envio oficial", async () => {
    serviceName = "  Consulta cardiológica   +\n Ecocardiograma\t+  Eletrocardiograma  ";
    const copy = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: copy } });
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    await createAppointment();
    expect(screen.getByLabelText("Modelo de mensagem")).toHaveValue("appointmentReminderService");
    expect(screen.getByRole("option", { name: "Lembrete de agendamento" })).toBeInTheDocument();
    const expected = renderAgendaWhatsAppTemplate("appointmentReminderService", ["Clínica teste", "Rex", "15/10/2026", "14:00", SERVICE]);
    expect(screen.getByLabelText("Mensagem pronta")).toHaveValue(expected);
    fireEvent.click(screen.getByRole("button", { name: "Copiar mensagem" }));
    await waitFor(() => expect(copy).toHaveBeenCalledWith(expected));
    fireEvent.click(screen.getByRole("button", { name: "Abrir WhatsApp" }));
    expect(new URL(String(open.mock.calls[0][0])).searchParams.get("text")).toBe(expected);
    fireEvent.click(screen.getByRole("button", { name: "Enviar pelo FortCordis" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/901/whatsapp/modelo", expect.objectContaining({ template_key: "appointmentReminderService" })));
  });

  it.each(["", "s".repeat(301)])("bloqueia a variante com serviço ausente ou longo e permite escolher o legado explicitamente", async (missingService) => {
    serviceName = missingService;
    await createAppointment();
    expect(screen.getByRole("alert")).toHaveTextContent("Confira o serviço salvo no agendamento");
    expect(screen.getByLabelText("Mensagem pronta")).toHaveValue("");
    for (const name of ["Copiar mensagem", "Abrir WhatsApp", "Enviar pelo FortCordis"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    fireEvent.change(screen.getByLabelText("Modelo de mensagem"), { target: { value: "appointmentReminder" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Mensagem pronta")).toHaveValue(renderAgendaWhatsAppTemplate("appointmentReminder", ["Clínica teste", "Rex", "15/10/2026", "14:00"]));
    expect(screen.getByRole("button", { name: "Enviar pelo FortCordis" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Enviar pelo FortCordis" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/901/whatsapp/modelo", expect.objectContaining({ template_key: "appointmentReminder" })));
  });

  it.each([SERVICE, "s".repeat(300)])("preserva o nome salvo retornado pelo agendamento até 300 caracteres quando o catálogo não fornece nome", async (savedName) => {
    serviceName = "";
    savedServiceName = savedName === SERVICE ? "  Consulta cardiológica   +\n Ecocardiograma\t+  Eletrocardiograma  " : savedName;
    await createAppointment();
    expect((screen.getByLabelText("Mensagem pronta") as HTMLTextAreaElement).value).toContain(`Serviço agendado: ${savedName}.`);
    expect(screen.getByRole("button", { name: "Enviar pelo FortCordis" })).toBeEnabled();
  });

  it("na edição usa o nome do mesmo serviço salvo quando o catálogo está incompleto", async () => {
    serviceName = "";
    mount({ id: 901, status: "Agendado", paciente_id: 21, tutor_id: 11, paciente: "Rex", tutor: "Maria", clinica_id: 7,
      servico_id: 3, servico: SERVICE, origem_atendimento: "clinica_parceira", inicio: "2026-10-15T14:00:00", fim: "2026-10-15T14:40:00" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Salvar Alterações" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Salvar Alterações" }));
    await screen.findByLabelText("Mensagem pronta");
    expect(screen.getByLabelText("Modelo de mensagem")).toHaveValue("appointmentChange");
    fireEvent.change(screen.getByLabelText("Modelo de mensagem"), { target: { value: "appointmentReminderService" } });
    expect((screen.getByLabelText("Mensagem pronta") as HTMLTextAreaElement).value).toContain(`Serviço agendado: ${SERVICE}`);
    expect(screen.getByRole("button", { name: "Enviar pelo FortCordis" })).toBeEnabled();
  });

  it("não reutiliza o nome anterior quando o serviço é alterado e o novo catálogo está incompleto", async () => {
    serviceName = "";
    mount({ id: 901, status: "Agendado", paciente_id: 21, tutor_id: 11, paciente: "Rex", tutor: "Maria", clinica_id: 7,
      servico_id: 4, servico: "Serviço anterior", origem_atendimento: "clinica_parceira", inicio: "2026-10-15T14:00:00", fim: "2026-10-15T14:40:00" });
    const serviceSelect = await waitFor(() => {
      const select = screen.getAllByRole("combobox").find((element) => element.querySelector('option[value="3"]'));
      if (!select) throw new Error("Catálogo de serviços ainda não carregou.");
      return select;
    });
    fireEvent.change(serviceSelect, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar Alterações" }));
    await screen.findByLabelText("Mensagem pronta");
    fireEvent.change(screen.getByLabelText("Modelo de mensagem"), { target: { value: "appointmentReminderService" } });
    expect(screen.getByLabelText("Mensagem pronta")).toHaveValue("");
    expect(screen.getByRole("alert")).toHaveTextContent("Confira o serviço salvo no agendamento");
    expect(screen.getByRole("button", { name: "Enviar pelo FortCordis" })).toBeDisabled();
  });

  it("preserva a reserva e usa o prazo como quinto parâmetro", async () => {
    mount({ id: 901, status: "Reservado", paciente_id: 21, tutor_id: 11, paciente: "Rex", tutor: "Maria", clinica_id: 7,
      servico_id: 3, servico: SERVICE, origem_atendimento: "clinica_parceira", inicio: "2026-10-15T14:00:00", fim: "2026-10-15T14:40:00" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Salvar Alterações" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Salvar Alterações" }));
    const preview = await screen.findByLabelText("Mensagem pronta");
    expect((preview as HTMLTextAreaElement).value).toContain("Confirme até");
    expect((preview as HTMLTextAreaElement).value).not.toContain("Serviço agendado:");
    expect(screen.queryByLabelText("Modelo de mensagem")).not.toBeInTheDocument();
  });
});
