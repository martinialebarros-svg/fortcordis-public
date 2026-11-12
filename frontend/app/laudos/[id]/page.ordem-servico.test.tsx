import { render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VisualizarLaudoPage from "./page";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  router: { push: vi.fn(), replace: vi.fn() },
  buscarReferencia: vi.fn(),
}));
vi.mock("../../layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "90" }), useRouter: () => mocks.router }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get } }));
vi.mock("../hooks/useReferenciaEco", () => ({ useReferenciaEco: () => ({ buscarReferencia: mocks.buscarReferencia, loading: false }) }));

const laudo = {
  id: 90,
  tipo: "eletrocardiograma",
  titulo: "Eletrocardiograma",
  descricao: "",
  status: "Finalizado",
  data_laudo: "2026-10-05T12:00:00",
  paciente: { id: 7, nome: "Bidu", tutor: "Ana", especie: "Canina" },
  ordem_servico: { id: 17, numero_os: "OS-0017", valor_final: 120, status: "Pendente" },
};

describe("confirmação persistente da OS no laudo", () => {
  beforeEach(() => {
    mocks.get.mockReset().mockResolvedValue({ data: laudo });
    localStorage.setItem("token", "test-token");
  });
  afterEach(() => localStorage.clear());

  it("exibe a OS vinda do GET do laudo e aponta ao filtro financeiro correspondente", async () => {
    render(<VisualizarLaudoPage />);
    expect(await screen.findByRole("region", { name: "Ordem de serviço vinculada" })).toHaveTextContent("OS-0017");
    expect(screen.getByText(/Pendente no Financeiro/)).toHaveTextContent(/R\$\s*120,00/);
    expect(screen.getByRole("link", { name: "Ver no Financeiro" })).toHaveAttribute("href", "/financeiro?aba=ordens&os_id=17");
    expect(mocks.get).toHaveBeenCalledWith("/laudos/90");
  });

  it("não exibe confirmação quando a resposta não autoriza ou não possui OS", async () => {
    mocks.get.mockResolvedValue({ data: { ...laudo, ordem_servico: null } });
    render(<VisualizarLaudoPage />);
    await screen.findByRole("heading", { name: "Visualizar laudo" });
    expect(screen.queryByRole("region", { name: "Ordem de serviço vinculada" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ver no Financeiro" })).not.toBeInTheDocument();
  });
});
