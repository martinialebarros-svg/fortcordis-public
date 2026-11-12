import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { concluirOperacaoTutor } from "@/lib/tutor-mesclagem";
import NovoPacientePage from "./page";

const mocks = vi.hoisted(() => {
  const push = vi.fn();
  return { get: vi.fn(), post: vi.fn(), router: { push } };
});
vi.mock("../../layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get, post: mocks.post } }));

const existente = { id: 184, nome: "Cristiane Souza", telefone: "85912345678", whatsapp: "85987654321",
  cpf: "12345678901", email: "cristiane@example.test", identificacao_pendente: false,
  origem_cadastro: "Clínica Alfa", identificacao_observacoes: "Conferido presencialmente", pets: [{ id: 5, nome: "Lua" }] };

async function selecionarExistente() {
  fireEvent.click(screen.getByRole("button", { name: "Selecionar tutor existente" }));
  fireEvent.change(screen.getByLabelText("Buscar por nome, ID, contato ou animal"), { target: { value: "Cristiane" } });
  fireEvent.click(await screen.findByRole("button", { name: "Selecionar Cristiane Souza #184" }));
  await screen.findByText(/Tutor selecionado: Cristiane Souza #184/);
}

describe("Novo paciente com seleção explícita de tutor", () => {
  beforeEach(() => {
    vi.stubGlobal("crypto", webcrypto);
    concluirOperacaoTutor("novo-paciente");
    mocks.get.mockReset(); mocks.post.mockReset(); mocks.router.push.mockReset();
    mocks.get.mockImplementation((url: string) => Promise.resolve(url === "/tutores/184"
      ? { data: existente } : { data: { items: [existente], total: 1 } }));
    mocks.post.mockResolvedValue({ data: { id: 20, tutor_id: 184 } });
    localStorage.setItem("token", "test-token");
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); });

  it("permite cadastro mínimo com primeiro nome e pet, sem busca ou confirmação", async () => {
    render(<NovoPacientePage />);
    fireEvent.change(screen.getByLabelText("Nome do tutor *"), { target: { value: "Cristiane" } });
    fireEvent.change(screen.getByPlaceholderText("Ex: Rex"), { target: { value: "Pingo" } });
    expect(screen.getByText("Dados adicionais do tutor (opcionais)").closest("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByRole("button", { name: "Salvar Paciente" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
    expect(mocks.post.mock.calls[0][0]).toBe("/pacientes");
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ nome: "Pingo", tutor: "Cristiane", tutor_id: null,
      tutor_identificacao_pendente: true, tutor_cpf: "", tutor_telefone: "", especie: null, sexo: null });
    expect(screen.getByLabelText("Espécie do paciente")).toHaveValue("");
    expect(screen.getByLabelText("Sexo do paciente")).toHaveValue("");
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("usa o ID escolhido sem reenviar ou limpar dados do tutor existente", async () => {
    render(<NovoPacientePage />);
    fireEvent.change(screen.getByPlaceholderText("Ex: Rex"), { target: { value: "Pingo" } });
    await selecionarExistente();
    expect(screen.getByLabelText("Nome do tutor *")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Salvar Paciente" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
    const payload = mocks.post.mock.calls[0][1];
    expect(payload).toMatchObject({ nome: "Pingo", tutor_id: 184 });
    expect(Object.keys(payload).filter((key) => key === "tutor" || key.startsWith("tutor_"))).toEqual(["tutor_id"]);
    expect(mocks.post.mock.calls.every(([url]) => url !== "/tutores")).toBe(true);
  });

  it("criar outra pessoa limpa o vínculo e dados de contato, preservando o pet", async () => {
    render(<NovoPacientePage />);
    fireEvent.change(screen.getByPlaceholderText("Ex: Rex"), { target: { value: "Pingo" } });
    await selecionarExistente();
    fireEvent.click(screen.getByRole("button", { name: "Criar outra pessoa" }));
    expect(screen.getByLabelText("Nome do tutor *")).toHaveValue("");
    expect(screen.getByLabelText("Nome do tutor *")).not.toBeDisabled();
    expect(screen.getByPlaceholderText("Ex: Rex")).toHaveValue("Pingo");
    expect(screen.getByPlaceholderText("email@tutor.com")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Nome do tutor *"), { target: { value: "Cristiane" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar Paciente" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ nome: "Pingo", tutor: "Cristiane", tutor_id: null,
      tutor_telefone: "", tutor_whatsapp: "", tutor_email: "", tutor_cpf: "", tutor_origem_cadastro: "",
      tutor_identificacao_pendente: true, tutor_identificacao_observacoes: "" });
  });

  it("cadastrar outro pet mantém o ID sem exigir dados complementares", async () => {
    render(<NovoPacientePage />);
    fireEvent.change(screen.getByLabelText("Nome do tutor *"), { target: { value: "Cristiane" } });
    fireEvent.change(screen.getByPlaceholderText("Ex: Rex"), { target: { value: "Pingo" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar e adicionar outro pet" }));
    await screen.findByText(/Paciente salvo. Cadastre o proximo pet/);
    fireEvent.change(screen.getByPlaceholderText("Ex: Rex"), { target: { value: "Lua" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar Paciente" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1]).toMatchObject({ nome: "Lua", tutor_id: 184 });
    expect(mocks.post.mock.calls[1][1]).not.toHaveProperty("tutor_identificacao_pendente");
    expect(mocks.post.mock.calls[1][1]).toMatchObject({ especie: null, sexo: null });
    expect(mocks.post.mock.calls[1][1].chave_operacao).not.toBe(mocks.post.mock.calls[0][1].chave_operacao);
  });

  it("repete a mesma operação após resposta perdida sem gerar outra chave", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.post.mockRejectedValueOnce(new Error("Resposta perdida depois do commit"))
      .mockResolvedValueOnce({ data: { id: 20, tutor_id: 184 } });
    render(<NovoPacientePage />);
    fireEvent.change(screen.getByLabelText("Nome do tutor *"), { target: { value: "Cristiane" } });
    fireEvent.change(screen.getByPlaceholderText("Ex: Rex"), { target: { value: "Pingo" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar Paciente" }));
    await screen.findByText(/Seus dados continuam preenchidos/);
    fireEvent.click(screen.getByRole("button", { name: "Salvar Paciente" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[0][1].chave_operacao).toEqual(expect.any(String));
    expect(mocks.post.mock.calls[1][1]).toEqual(mocks.post.mock.calls[0][1]);
  });

  it("gera nova intenção quando o usuário altera dados após uma falha", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.post.mockRejectedValueOnce(new Error("Falha"))
      .mockResolvedValueOnce({ data: { id: 20, tutor_id: 184 } });
    render(<NovoPacientePage />);
    fireEvent.change(screen.getByLabelText("Nome do tutor *"), { target: { value: "Cristiane" } });
    fireEvent.change(screen.getByPlaceholderText("Ex: Rex"), { target: { value: "Pingo" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar Paciente" }));
    await screen.findByText(/Seus dados continuam preenchidos/);
    fireEvent.change(screen.getByPlaceholderText("Ex: Rex"), { target: { value: "Pingo corrigido" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar Paciente" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1].nome).toBe("Pingo corrigido");
    expect(mocks.post.mock.calls[1][1].chave_operacao).not.toBe(mocks.post.mock.calls[0][1].chave_operacao);
  });
});
