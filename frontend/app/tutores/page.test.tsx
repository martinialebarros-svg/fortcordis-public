import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import TutoresPage from "./page";
import { concluirOperacaoTutor } from "@/lib/tutor-mesclagem";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("../layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("@/lib/axios", () => ({ default: mocks }));
const items = [
  { id: 1, nome: "Cristiane", identificacao_pendente: false, telefone: "85911111111", origem_cadastro: "Clínica Alfa", pets: [{ id: 10, nome: "Mel" }] },
  { id: 2, nome: "Cristiane", identificacao_pendente: true, telefone: "85922222222", origem_cadastro: "Clínica Beta", pets: [{ id: 20, nome: "Pingo" }] },
];
const previa = {
  principal: { id: 1, nome: "Cristiane", telefone: "85911111111", endereco: { endereco: "Rua A" } },
  secundario: { id: 2, nome: "Cristiane", telefone: "85922222222", endereco: { endereco: "Rua B" } },
  campos: ["nome", "telefone", "endereco"], conflitos: ["telefone", "endereco"], bloqueios: [], avisos: [],
  token_previa: "a".repeat(64), vinculos: { pacientes: { principal: 1, secundario: 1 } },
  pets: [{ id: 10, nome: "Mel", tutor_id: 1 }, { id: 20, nome: "Pingo", tutor_id: 2 }],
};

async function comparar() {
  await screen.findByRole("button", { name: "Manter #1 como principal" });
  fireEvent.click(screen.getByRole("button", { name: "Manter #1 como principal" }));
  fireEvent.click(screen.getByRole("button", { name: "Mesclar #2 no principal" }));
  fireEvent.click(screen.getByRole("button", { name: "Comparar cadastros" }));
  await screen.findByRole("region", { name: "Prévia da mesclagem" });
}
function confirmarRevisao() {
  fireEvent.click(screen.getByRole("radio", { name: "Telefone: usar secundario" }));
  fireEvent.click(screen.getByRole("radio", { name: "Endereço completo e localização: usar principal" }));
  fireEvent.change(screen.getByLabelText("Motivo e evidência de que é a mesma pessoa"), { target: { value: "Identidade confirmada com a clínica" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /Revisei os dados/ }));
}

describe("Tutores e mesclagem assistida", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("crypto", webcrypto);
    sessionStorage.clear(); concluirOperacaoTutor("novo-tutores"); concluirOperacaoTutor("mesclagem-tutores");
    window.history.replaceState({}, "", "/tutores");
    localStorage.setItem("user", JSON.stringify({ id: 7, email: "admin@example.com", papeis: ["admin"] }));
    mocks.get.mockResolvedValue({ data: { items, total: 2 } });
    mocks.post.mockImplementation((path: string) => Promise.resolve({ data: path.endsWith("/previa") ? previa : { id: 3 } }));
  });
  afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });

  it("distingue homônimos pelo código, animais, origem e situação da identificação", async () => {
    render(<TutoresPage />);
    expect(await screen.findByText("Identificação pendente")).toBeInTheDocument();
    expect(screen.getByText("Identificação confirmada pela equipe")).toBeInTheDocument();
    expect(screen.getByText("Animais: Pingo #20")).toBeInTheDocument();
    expect(screen.getByText(/85911111111 · Clínica Alfa/)).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("cria outro cadastro com identificação pendente e origem, sem reutilizar um homônimo", async () => {
    render(<TutoresPage />);
    fireEvent.click(screen.getByRole("button", { name: "Novo tutor" }));
    expect(screen.queryByRole("checkbox", { name: "Identificação pendente" })).not.toBeInTheDocument();
    expect(screen.getByText("Pode continuar com o primeiro nome. Os demais dados podem ser completados no atendimento.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nome"), { target: { value: "Cristiane" } });
    fireEvent.change(screen.getByLabelText("Origem do cadastro / clínica informante"), { target: { value: "Clínica Gama" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar cadastro" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/tutores", expect.objectContaining({ nome: "Cristiane", identificacao_pendente: true, origem_cadastro: "Clínica Gama" })));
  });

  it("só mescla após resolver conflitos, informar motivo e confirmar a revisão", async () => {
    render(<TutoresPage />); await comparar();
    expect(screen.getByRole("button", { name: "Confirmar mesclagem" })).toBeDisabled();
    confirmarRevisao();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar mesclagem" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/tutores/mesclagens", {
      principal_id: 1, secundario_id: 2, token_previa: previa.token_previa,
      escolhas: { telefone: "secundario", endereco: "principal" },
      motivo: "Identidade confirmada com a clínica", confirmar: true, chave_operacao: expect.any(String),
    }));
    expect(await screen.findByText(/Mesclagem concluída/)).toBeInTheDocument();
  });

  it("bloqueia a confirmação quando há CPFs divergentes", async () => {
    mocks.post.mockResolvedValue({ data: { ...previa, bloqueios: ["Os CPFs informados são diferentes."] } });
    render(<TutoresPage />); await comparar(); confirmarRevisao();
    expect(screen.getByRole("alert")).toHaveTextContent("CPFs");
    expect(screen.getByRole("button", { name: "Confirmar mesclagem" })).toBeDisabled();
  });

  it("descarta prévia obsoleta e exige nova comparação após conflito do servidor", async () => {
    mocks.post.mockImplementation((path: string) => path.endsWith("/previa") ? Promise.resolve({ data: previa })
      : Promise.reject({ response: { status: 409, data: { detail: "Os cadastros mudaram. Gere uma nova prévia." } } }));
    render(<TutoresPage />); await comparar(); confirmarRevisao();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar mesclagem" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("nova prévia");
    expect(screen.queryByRole("region", { name: "Prévia da mesclagem" })).not.toBeInTheDocument();
  });

  it("não oferece mesclagem nem histórico para usuário sem papel administrador", async () => {
    localStorage.setItem("user", JSON.stringify({ email: "recepcao@example.com", papeis: ["secretaria"] }));
    render(<TutoresPage />);
    await screen.findByText("Animais: Pingo #20");
    expect(screen.queryByRole("button", { name: "Comparar cadastros" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Histórico #1" })).not.toBeInTheDocument();
  });

  it("permite criar com somente o primeiro nome e mantém a mesma chave após resposta de rede desconhecida", async () => {
    mocks.post.mockRejectedValueOnce(new Error("Network Error")).mockResolvedValueOnce({ data: { id: 3 } });
    render(<TutoresPage />);
    fireEvent.click(screen.getByRole("button", { name: "Novo tutor" }));
    fireEvent.change(screen.getByLabelText("Nome"), { target: { value: "Cristiane" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar cadastro" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Salvar cadastro" }));
    await screen.findByText("Cadastro salvo.");
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(mocks.post.mock.calls[0][1].chave_operacao).toEqual(mocks.post.mock.calls[1][1].chave_operacao);
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ nome: "Cristiane", identificacao_pendente: true });
  });

  it("preserva prévia e chave de mesclagem quando a resposta da primeira tentativa é desconhecida", async () => {
    let falhou = false;
    mocks.post.mockImplementation((path: string) => {
      if (path.endsWith("/previa")) return Promise.resolve({ data: previa });
      if (!falhou) { falhou = true; return Promise.reject(new Error("Network Error")); }
      return Promise.resolve({ data: { id: 1 } });
    });
    render(<TutoresPage />); await comparar(); confirmarRevisao();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar mesclagem" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("region", { name: "Prévia da mesclagem" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar mesclagem" }));
    await screen.findByText(/Mesclagem concluída/);
    const chamadas = mocks.post.mock.calls.filter(([path]) => path === "/tutores/mesclagens");
    expect(chamadas).toHaveLength(2);
    expect(chamadas[0][1].chave_operacao).toEqual(chamadas[1][1].chave_operacao);
  });

  it("filtra pendências e origem, priorizando os próximos atendimentos", async () => {
    render(<TutoresPage />);
    fireEvent.change(screen.getByLabelText("Situação da identificação"), { target: { value: "true" } });
    fireEvent.change(screen.getByLabelText("Clínica ou origem"), { target: { value: "Clínica Alfa" } });
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(expect.stringContaining("pendentes=true")));
    const busca = mocks.get.mock.calls.at(-1)?.[0];
    expect(busca).toContain("origem=Cl%C3%ADnica+Alfa"); expect(busca).toContain("ordenar=proximo_atendimento");
    expect(mocks.get.mock.calls.some(([path]) => path.includes("duplicidades"))).toBe(false);
  });

  it("abre o cadastro explícito por tutor_id sem procurar homônimos", async () => {
    window.history.replaceState({}, "", "/tutores?tutor_id=2");
    mocks.get.mockImplementation((path: string) => Promise.resolve({ data: path === "/tutores/2" ? items[1] : { items, total: 2 } }));
    render(<TutoresPage />);
    expect(await screen.findByRole("heading", { name: "Editar tutor #2" })).toBeInTheDocument();
    expect(screen.getByLabelText("Nome")).toHaveValue("Cristiane");
    expect(mocks.get).toHaveBeenCalledWith("/tutores/2");
  });

  it("mostra impedimento e bloqueia reversão quando houve alteração posterior", async () => {
    mocks.get.mockImplementation((path: string) => Promise.resolve({ data: path.endsWith("/mesclagens") ? { items: [{
      id: 12, principal_id: 1, secundario_id: 2, usuario_nome: "Admin", created_at: "2026-10-27T10:00:00Z", motivo: "Revisão confirmada",
      detalhes: { antes: { principal: {}, secundario: {} }, resultado: {}, vinculos_movidos: { pacientes: [20] } },
    }] } : { items, total: 2 } }));
    mocks.post.mockResolvedValue({ data: { principal_id: 1, secundario_id: 2, token_previa: "r".repeat(64), vinculos: { pacientes: 1 },
      bloqueios: ["Houve alterações posteriores. A reversão exige revisão técnica."], avisos: [] } });
    render(<TutoresPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Histórico #1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revisar reversão da mesclagem #12" }));
    expect(await screen.findByRole("region", { name: "Prévia da reversão" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("alterações posteriores");
    expect(screen.getByRole("button", { name: "Confirmar reversão" })).toBeDisabled();
  });

  it("exige motivo e confirmação antes de enviar reversão e reaproveita a chave após falha de rede", async () => {
    mocks.get.mockImplementation((path: string) => Promise.resolve({ data: path.endsWith("/mesclagens") ? { items: [{
      id: 13, principal_id: 1, secundario_id: 2, usuario_nome: "Admin", created_at: "2026-10-27T10:00:00Z", motivo: "Revisão confirmada",
      detalhes: { antes: { principal: {}, secundario: {} }, resultado: {}, vinculos_movidos: { pacientes: [20] } },
    }] } : { items, total: 2 } }));
    let falhou = false;
    mocks.post.mockImplementation((path: string) => {
      if (path.endsWith("/previa")) return Promise.resolve({ data: { principal_id: 1, secundario_id: 2,
        token_previa: "r".repeat(64), vinculos: { pacientes: 1 }, bloqueios: [], avisos: [] } });
      if (!falhou) { falhou = true; return Promise.reject(new Error("Network Error")); }
      return Promise.resolve({ data: {} });
    });
    render(<TutoresPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Histórico #1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revisar reversão da mesclagem #13" }));
    expect(await screen.findByRole("button", { name: "Confirmar reversão" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Motivo da reversão"), { target: { value: "Mesclagem revisada: são pessoas diferentes." } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Revisei a separação/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar reversão" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar reversão" }));
    await screen.findByText(/Mesclagem revertida/);
    const chamadas = mocks.post.mock.calls.filter(([path]) => path.endsWith("/reversao"));
    expect(chamadas).toHaveLength(2); expect(chamadas[0][1].chave_operacao).toEqual(chamadas[1][1].chave_operacao);
    expect(chamadas[1][1]).toMatchObject({ confirmar: true, token_previa: "r".repeat(64), motivo: "Mesclagem revisada: são pessoas diferentes." });
  });
});
