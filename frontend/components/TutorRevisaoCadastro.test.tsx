import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TutorRevisaoCadastro from "./TutorRevisaoCadastro";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: mocks }));
const tutor = { id: 1, nome: "Cristiane", telefone: "85911111111", identificacao_pendente: true, versao: "v".repeat(64) };
function abrirResumo(texto: string) {
  const details = screen.getByText(texto).closest("details")!;
  details.open = true; fireEvent(details, new Event("toggle"));
}
async function abrir() {
  abrirResumo("Revisar cadastro do tutor #1 (opcional)");
  await screen.findByRole("region", { name: "Complementar dados do tutor" });
}

describe("Revisão opcional do tutor durante o atendimento", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.get.mockImplementation((path: string) => Promise.resolve({ data: path === "/tutores/1" ? tutor : { items: [] } }));
    mocks.post.mockResolvedValue({ data: {} }); mocks.put.mockResolvedValue({ data: tutor });
  });

  it("permanece recolhida sem carregar dados ou pesquisar duplicidades durante o agendamento", async () => {
    render(<TutorRevisaoCadastro tutorId={1} />);
    expect(mocks.get).not.toHaveBeenCalled();
    await abrir();
    expect(mocks.get).toHaveBeenCalledTimes(4);
    expect(mocks.get.mock.calls.some(([path]) => path.includes("duplicidades"))).toBe(false);
    expect(screen.getByText("A identificação pode continuar pendente.", { exact: false })).toBeInTheDocument();
  });

  it("complementa nome e contato sem confirmar identidade implicitamente", async () => {
    const onUpdated = vi.fn();
    render(<TutorRevisaoCadastro tutorId={1} onUpdated={onUpdated} />); await abrir();
    fireEvent.change(screen.getByLabelText("Nome do tutor"), { target: { value: "Cristiane Silva" } });
    fireEvent.change(screen.getByLabelText("Telefone do tutor"), { target: { value: "(85) 99999-1234" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar dados do tutor" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/tutores/1", expect.objectContaining({ nome: "Cristiane Silva", telefone: "85999991234" })));
    expect(mocks.put.mock.calls[0][1]).not.toHaveProperty("identificacao_pendente");
    expect(mocks.post).not.toHaveBeenCalled();
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
  });

  it("descarta conclusão antiga se trocar de tutor enquanto salva", async () => {
    let concluir!: (value: unknown) => void;
    mocks.put.mockImplementationOnce(() => new Promise((resolve) => { concluir = resolve; }));
    mocks.get.mockImplementation((path: string) => Promise.resolve({ data: path === "/tutores/1" ? tutor
      : path === "/tutores/2" ? { ...tutor, id: 2, nome: "Outra Cristiane" } : { items: [] } }));
    const onUpdated = vi.fn();
    const view = render(<TutorRevisaoCadastro tutorId={1} onUpdated={onUpdated} />);
    await abrir();
    fireEvent.change(screen.getByLabelText("Nome do tutor"), { target: { value: "Cristiane primeira" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar dados do tutor" }));
    view.rerender(<TutorRevisaoCadastro tutorId={2} onUpdated={onUpdated} />);
    abrirResumo("Revisar cadastro do tutor #2 (opcional)");
    await waitFor(() => expect(screen.getByLabelText("Nome do tutor")).toHaveValue("Outra Cristiane"));
    const requests = mocks.get.mock.calls.length;
    await act(async () => concluir({ data: { ...tutor, nome: "Cristiane primeira" } }));
    expect(mocks.get).toHaveBeenCalledTimes(requests);
    expect(screen.getByLabelText("Nome do tutor")).toHaveValue("Outra Cristiane");
    expect(onUpdated).not.toHaveBeenCalled();
  });

  it("aguarda atualização assíncrona do atendimento e informa falha de resumo sem repetir a gravação", async () => {
    const onUpdated = vi.fn().mockRejectedValue(new Error("Resumo indisponível"));
    render(<TutorRevisaoCadastro tutorId={1} onUpdated={onUpdated} />); await abrir();
    fireEvent.click(screen.getByRole("button", { name: "Salvar dados do tutor" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Os dados foram salvos, mas não foi possível atualizar o resumo do atendimento");
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("confirma identidade somente com método, evidência e a versão revisada", async () => {
    render(<TutorRevisaoCadastro tutorId={1} />); await abrir();
    abrirResumo("Confirmar identidade e consultar histórico");
    expect(screen.getByRole("button", { name: "Confirmar identidade" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Como a identidade foi confirmada?"), { target: { value: "atendimento_presencial" } });
    expect(screen.getByRole("button", { name: "Confirmar identidade" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Evidência da confirmação"), { target: { value: "Tutor confirmou nome e seus dois animais." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar identidade" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/tutores/1/identificacao/confirmar", {
      metodo: "atendimento_presencial", evidencia: "Tutor confirmou nome e seus dois animais.", versao: tutor.versao,
    }));
  });

  it("pede salvar alterações locais antes de confirmar a versão do cadastro", async () => {
    render(<TutorRevisaoCadastro tutorId={1} />); await abrir();
    fireEvent.change(screen.getByLabelText("Nome do tutor"), { target: { value: "Cristiane Silva" } });
    abrirResumo("Confirmar identidade e consultar histórico");
    fireEvent.change(screen.getByLabelText("Como a identidade foi confirmada?"), { target: { value: "atendimento_presencial" } });
    fireEvent.change(screen.getByLabelText("Evidência da confirmação"), { target: { value: "Tutor confirmou nome e seus animais." } });
    expect(screen.getByRole("button", { name: "Confirmar identidade" })).toBeDisabled();
    expect(screen.getByText("Salve os dados do tutor acima antes de confirmar a identidade.")).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("só consulta candidatos quando solicitado e registra pessoas distintas com motivo", async () => {
    mocks.get.mockImplementation((path: string) => Promise.resolve({ data: path === "/tutores/1" ? tutor : path.endsWith("/duplicidades") ? {
      items: [{ id: 2, nome: "Cristiane", motivos: ["Mesmo telefone"], pets: [{ id: 20, nome: "Pingo" }] }],
    } : { items: [] } }));
    render(<TutorRevisaoCadastro tutorId={1} />); await abrir();
    expect(mocks.get).not.toHaveBeenCalledWith("/tutores/1/duplicidades");
    fireEvent.click(screen.getByRole("button", { name: "Procurar possíveis duplicidades" }));
    expect(await screen.findByText("Por que apareceu: Mesmo telefone")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Registrar que são pessoas diferentes" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Por que são pessoas diferentes?"), { target: { value: "Telefone compartilhado da clínica." } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar que são pessoas diferentes" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/tutores/1/duplicidades/2/descartar", { motivo: "Telefone compartilhado da clínica." }));
    expect(await screen.findByText(/Pessoas distintas registradas/)).toBeInTheDocument();
  });

  it("permite registrar outro contato sem substituir o contato principal", async () => {
    render(<TutorRevisaoCadastro tutorId={1} />); await abrir();
    abrirResumo("Outros contatos e clínicas de origem");
    fireEvent.change(screen.getByLabelText("Contato adicional"), { target: { value: "85988887777" } });
    fireEvent.change(screen.getByLabelText("De quem é este contato?"), { target: { value: "Clínica informante" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar contato" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/tutores/1/contatos", { tipo: "telefone", valor: "85988887777", rotulo: "Clínica informante" }));
    expect(mocks.put).not.toHaveBeenCalled();
  });
});
