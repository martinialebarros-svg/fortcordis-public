import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import UploadEletrocardiogramaPage from "./page";

const mocks = vi.hoisted(() => {
  const push = vi.fn();
  return {
    get: vi.fn(),
    post: vi.fn(),
    push,
    router: { push },
    listarTodasClinicas: vi.fn(),
  };
});

vi.mock("../../../layout-dashboard", () => ({
  default: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => mocks.router,
}));

vi.mock("@/lib/axios", () => ({
  default: { get: mocks.get, post: mocks.post },
}));

vi.mock("@/lib/clinicas", () => ({
  listarTodasClinicas: mocks.listarTodasClinicas,
}));

function campoDataRealizacao() {
  return screen.getByLabelText("Data de realizacao") as HTMLInputElement;
}

describe("UploadEletrocardiogramaPage", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.push.mockReset();
    mocks.listarTodasClinicas.mockReset();
    mocks.listarTodasClinicas.mockResolvedValue([]);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    window.localStorage.setItem("token", "test-token");
    window.history.replaceState({}, "", "/laudos/eletrocardiograma/upload");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("usa a data agendada como default quando o upload vem de um agendamento", async () => {
    window.history.replaceState({}, "", "/laudos/eletrocardiograma/upload?agendamento_id=42");
    mocks.get.mockImplementation((url: string) => {
      if (url === "/portal/parceiros/veterinarios/opcoes") {
        return Promise.resolve({ data: { items: [] } });
      }
      if (url === "/agenda/42") {
        return Promise.resolve({
          data: {
            id: 42,
            paciente_id: 7,
            clinica_id: 3,
            paciente: "Bidu",
            tutor: "Ana",
            data: "2026-09-04",
            inicio: "2026-09-04 09:30:00",
          },
        });
      }
      if (url === "/pacientes/7") {
        return Promise.resolve({ data: { id: 7, nome: "Bidu", tutor: "Ana" } });
      }
      return Promise.reject(new Error(`URL inesperada: ${url}`));
    });

    render(<UploadEletrocardiogramaPage />);

    await waitFor(() => expect(campoDataRealizacao().value).toBe("2026-09-04"));
  });

  it("cai para a data do dia quando o upload nao tem agendamento", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-10T15:00:00Z"));
    mocks.get.mockImplementation((url: string) => {
      if (url === "/portal/parceiros/veterinarios/opcoes") {
        return Promise.resolve({ data: { items: [] } });
      }
      return Promise.reject(new Error(`URL inesperada: ${url}`));
    });

    render(<UploadEletrocardiogramaPage />);

    await vi.waitFor(() => expect(campoDataRealizacao().value).toBe("2026-09-10"));
  });

  it("cai para a data do dia quando o agendamento nao carrega", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-10T15:00:00Z"));
    window.history.replaceState({}, "", "/laudos/eletrocardiograma/upload?agendamento_id=42");
    mocks.get.mockImplementation((url: string) => {
      if (url === "/portal/parceiros/veterinarios/opcoes") {
        return Promise.resolve({ data: { items: [] } });
      }
      return Promise.reject(new Error(`URL inesperada: ${url}`));
    });

    render(<UploadEletrocardiogramaPage />);

    await vi.waitFor(() => expect(campoDataRealizacao().value).toBe("2026-09-10"));
  });
});

const PREVIEW_URL = "/laudos/eletrocardiograma/ordem-servico/preview";
const UPLOAD_URL = "/laudos/eletrocardiograma/upload-pdf";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function mockGetPadrao(url: string) {
  if (url === "/portal/parceiros/veterinarios/opcoes") return Promise.resolve({ data: { items: [{ id: 5, nome_exibicao: "Dra. Ana" }] } });
  if (url === "/pacientes/7") return Promise.resolve({ data: { id: 7, nome: "Bidu", tutor: "Ana" } });
  if (url === "/servicos") return Promise.resolve({ data: { items: [{ id: 11, nome: "Laudo de eletrocardiograma" }] } });
  if (url === PREVIEW_URL) return Promise.resolve({ data: { valor_servico: 120, valor_final: 120 } });
  return Promise.reject(new Error(`URL inesperada: ${url}`));
}

async function prepararUpload(query = "paciente_id=7&clinic_id=3") {
  window.history.replaceState({}, "", `/laudos/eletrocardiograma/upload?${query}`);
  render(<UploadEletrocardiogramaPage />);
  await waitFor(() => expect(screen.getByRole("button", { name: /Salvar laudo/ })).toBeEnabled());
  fireEvent.change(document.getElementById("pdf-eletro")!, { target: { files: [new File(["%PDF-1.4"], "eletro.pdf", { type: "application/pdf" })] } });
}

function submeter() {
  fireEvent.submit(screen.getByRole("button", { name: /Salvar laudo/ }).closest("form")!);
}

async function ativarOrdem() {
  fireEvent.click(screen.getByRole("checkbox", { name: "Gerar ordem de serviço para a clínica" }));
  await waitFor(() => expect(screen.getByLabelText("Serviço da ordem")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Serviço da ordem"), { target: { value: "11" } });
}

describe("upload de eletro com ordem de serviço opcional", () => {
  beforeEach(() => {
    mocks.get.mockReset().mockImplementation(mockGetPadrao);
    mocks.post.mockReset().mockResolvedValue({ data: { id: 90 } });
    mocks.push.mockReset();
    mocks.listarTodasClinicas.mockReset().mockResolvedValue([{ id: 3, nome: "Clínica A" }, { id: 4, nome: "Clínica B" }]);
    window.localStorage.setItem("token", "test-token");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("mantém upload comum sem OS e não carrega serviços até optar pela geração", async () => {
    await prepararUpload();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(mocks.get.mock.calls.some(([url]) => url === "/servicos" || url === PREVIEW_URL)).toBe(false);
    submeter();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/laudos/90"));
    const payload = mocks.post.mock.calls[0][1] as FormData;
    expect(payload.has("gerar_ordem_servico")).toBe(false);
    expect(payload.has("idempotency_key")).toBe(false);
    expect(payload.get("clinic_id")).toBe("3");
  });

  it.each(["agendamento_id=42", "atendimento_id=18"])("oculta OS quando o upload está ligado a %s", async (contexto) => {
    mocks.get.mockImplementation((url: string) => url === "/agenda/42"
      ? Promise.resolve({ data: { id: 42, paciente_id: 7, clinica_id: 3 } })
      : mockGetPadrao(url));
    await prepararUpload(`paciente_id=7&clinic_id=3&${contexto}`);
    expect(screen.queryByRole("checkbox", { name: "Gerar ordem de serviço para a clínica" })).not.toBeInTheDocument();
    expect(mocks.get.mock.calls.some(([url]) => url === "/servicos")).toBe(false);
  });

  it("exige clínica mesmo com veterinário e valida antes de criar cadastros rápidos", async () => {
    await prepararUpload("veterinario_parceiro_id=5");
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar tutor e pet" }));
    fireEvent.click(screen.getByRole("checkbox"));
    submeter();
    expect(await screen.findByText("Selecione a clínica parceira para gerar a ordem de serviço.")).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.get.mock.calls.some(([url]) => url === PREVIEW_URL)).toBe(false);
  });

  it("exige seleção explícita de serviço e usa o preço autoritativo", async () => {
    await prepararUpload();
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(screen.getByLabelText("Serviço da ordem")).toBeEnabled());
    expect(screen.getByLabelText("Serviço da ordem")).toHaveValue("");
    submeter();
    expect(await screen.findByText("Selecione o serviço para gerar a ordem de serviço.")).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Serviço da ordem"), { target: { value: "11" } });
    await screen.findByText(/Valor da ordem de serviço: R\$\s*120,00/);
    expect(mocks.get).toHaveBeenCalledWith(PREVIEW_URL, { params: { clinic_id: 3, servico_id: 11, tipo_horario: "comercial" } });
    submeter();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/laudos/90"));
    const payload = mocks.post.mock.calls[0][1] as FormData;
    expect(payload.get("gerar_ordem_servico")).toBe("true");
    expect(payload.get("servico_id")).toBe("11");
    expect(payload.get("tipo_horario")).toBe("comercial");
    expect(payload.get("idempotency_key")).toMatch(/^[\da-f-]{36}$/);
    expect(payload.has("valor_final")).toBe(false);
  });

  it("descarta resposta obsoleta e bloqueia envio até atualizar clínica e horário", async () => {
    const primeira = deferred<{ data: { valor_servico: number; valor_final: number } }>();
    const segunda = deferred<{ data: { valor_servico: number; valor_final: number } }>();
    const terceira = deferred<{ data: { valor_servico: number; valor_final: number } }>();
    let previews = 0;
    mocks.get.mockImplementation((url: string) => url === PREVIEW_URL
      ? [primeira, segunda, terceira][previews++].promise
      : mockGetPadrao(url));
    await prepararUpload();
    await ativarOrdem();
    expect(screen.getByRole("button", { name: /Salvar laudo/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Clinica parceira"), { target: { value: "4" } });
    await act(async () => { segunda.resolve({ data: { valor_servico: 140, valor_final: 140 } }); });
    expect(await screen.findByText(/Valor da ordem de serviço: R\$\s*140,00/)).toBeInTheDocument();
    await act(async () => { primeira.resolve({ data: { valor_servico: 120, valor_final: 120 } }); });
    expect(screen.queryByText(/Valor da ordem de serviço: R\$\s*120,00/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Horário do serviço"), { target: { value: "plantao" } });
    expect(screen.queryByText(/Valor da ordem de serviço: R\$\s*140,00/)).not.toBeInTheDocument();
    submeter();
    expect(mocks.post).not.toHaveBeenCalled();
    await act(async () => { terceira.resolve({ data: { valor_servico: 200, valor_final: 200 } }); });
    await screen.findByText(/Valor da ordem de serviço: R\$\s*200,00/);
    submeter();
    await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
    const payload = mocks.post.mock.calls[0][1] as FormData;
    expect(payload.get("clinic_id")).toBe("4");
    expect(payload.get("tipo_horario")).toBe("plantao");
  });

  it("permite consultar novamente após falha e só então enviar", async () => {
    let previews = 0;
    mocks.get.mockImplementation((url: string) => url === PREVIEW_URL && previews++ === 0
      ? Promise.reject({ response: { data: { detail: "Preço indisponível para esta clínica." } } })
      : mockGetPadrao(url));
    await prepararUpload();
    await ativarOrdem();
    expect(await screen.findByRole("alert")).toHaveTextContent("Preço indisponível para esta clínica.");
    expect(screen.getByRole("button", { name: /Salvar laudo/ })).toBeDisabled();
    submeter();
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Consultar valor novamente" }));
    await screen.findByText(/Valor da ordem de serviço: R\$\s*120,00/);
    expect(screen.getByRole("button", { name: /Salvar laudo/ })).toBeEnabled();
  });

  it("preserva chave em retry, bloqueia submissão dupla e muda chave com alteração do conteúdo", async () => {
    const primeiroUpload = deferred<unknown>();
    mocks.post.mockImplementationOnce(() => primeiroUpload.promise)
      .mockRejectedValueOnce({ response: { data: { detail: "Falha temporária." } } })
      .mockResolvedValueOnce({ data: { id: 90 } });
    await prepararUpload();
    await ativarOrdem();
    await screen.findByText(/Valor da ordem de serviço: R\$\s*120,00/);
    const form = screen.getByRole("button", { name: /Salvar laudo/ }).closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(mocks.post).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("Clinica parceira")).toBeDisabled();
    await act(async () => { primeiroUpload.reject({ response: { data: { detail: "Falha temporária." } } }); });
    submeter();
    await screen.findByText("Falha temporária.");
    expect(mocks.post).toHaveBeenCalledTimes(2);
    const chave1 = (mocks.post.mock.calls[0][1] as FormData).get("idempotency_key");
    expect((mocks.post.mock.calls[1][1] as FormData).get("idempotency_key")).toBe(chave1);
    fireEvent.change(screen.getByLabelText("Observacoes internas"), { target: { value: "Exame remoto." } });
    submeter();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/laudos/90"));
    expect((mocks.post.mock.calls[2][1] as FormData).get("idempotency_key")).not.toBe(chave1);
  });

  it("reaproveita cadastros rápidos concluídos quando o upload precisa ser repetido", async () => {
    let uploads = 0;
    mocks.get.mockImplementation((url: string) => url === "/pacientes/8"
      ? Promise.resolve({ data: { id: 8, nome: "Luna", tutor: "Rita" } })
      : mockGetPadrao(url));
    mocks.post.mockImplementation((url: string) => {
      if (url === "/pacientes") return Promise.resolve({ data: { id: 8, nome: "Luna", tutor: "Rita" } });
      if (url === "/portal/parceiros/veterinarios/cadastro-rapido") return Promise.resolve({ data: { id: 9, nome_exibicao: "Dra. Maria" } });
      if (url === UPLOAD_URL && uploads++ === 0) return Promise.reject({ response: { data: { detail: "Tente novamente." } } });
      return Promise.resolve({ data: { id: 90 } });
    });
    await prepararUpload("clinic_id=3");
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar tutor e pet" }));
    fireEvent.change(screen.getByLabelText("Nome do tutor"), { target: { value: "Rita" } });
    fireEvent.change(screen.getByLabelText("Nome do pet"), { target: { value: "Luna" } });
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar veterinario parceiro" }));
    fireEvent.change(screen.getByLabelText("Nome exibido"), { target: { value: "Dra. Maria" } });
    fireEvent.change(screen.getByLabelText("Email de login"), { target: { value: "maria@example.test" } });
    await ativarOrdem();
    await screen.findByText(/Valor da ordem de serviço: R\$\s*120,00/);
    submeter();
    await screen.findByText("Tente novamente.");
    await waitFor(() => expect(screen.getByRole("button", { name: /Salvar laudo/ })).toBeEnabled());
    submeter();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/laudos/90"));
    expect(mocks.post.mock.calls.filter(([url]) => url === "/pacientes")).toHaveLength(1);
    expect(mocks.post.mock.calls.filter(([url]) => url === "/portal/parceiros/veterinarios/cadastro-rapido")).toHaveLength(1);
    const chamadasUpload = mocks.post.mock.calls.filter(([url]) => url === UPLOAD_URL);
    expect(chamadasUpload).toHaveLength(2);
    expect(chamadasUpload[0][1].get("idempotency_key")).toBe(chamadasUpload[1][1].get("idempotency_key"));
    expect(chamadasUpload[1][1].get("paciente_id")).toBe("8");
  });

  it("desmarcar a opção após falha de preço permite salvar sem OS", async () => {
    mocks.get.mockImplementation((url: string) => url === PREVIEW_URL
      ? Promise.reject({ response: { data: { detail: "Sem permissão para gerar OS." } } })
      : mockGetPadrao(url));
    await prepararUpload();
    await ativarOrdem();
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.queryByLabelText("Serviço da ordem")).not.toBeInTheDocument();
    submeter();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/laudos/90"));
    expect((mocks.post.mock.calls[0][1] as FormData).has("gerar_ordem_servico")).toBe(false);
  });

  it("recupera falha do catálogo e conserva seleção explícita após tentar novamente", async () => {
    let catalogos = 0;
    mocks.get.mockImplementation((url: string) => url === "/servicos" && catalogos++ === 0
      ? Promise.reject({ response: { data: { detail: "Catálogo indisponível." } } })
      : mockGetPadrao(url));
    await prepararUpload();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Catálogo indisponível.");
    expect(screen.getByLabelText("Serviço da ordem")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Tentar carregar serviços novamente" }));
    await waitFor(() => expect(screen.getByLabelText("Serviço da ordem")).toBeEnabled());
    expect(screen.getByLabelText("Serviço da ordem")).toHaveValue("");
    expect(mocks.get.mock.calls.some(([url]) => url === PREVIEW_URL)).toBe(false);
  });
});
