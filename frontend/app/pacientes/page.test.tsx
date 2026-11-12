import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PacientesPage from "./page";

const mocks = vi.hoisted(() => {
  const push = vi.fn();
  return {
    get: vi.fn(),
    push,
    delete: vi.fn(),
    router: { push },
  };
});

vi.mock("../layout-dashboard", () => ({
  default: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => mocks.router,
}));

vi.mock("@/lib/axios", () => ({
  default: { get: mocks.get, delete: mocks.delete },
}));

describe("PacientesPage", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.push.mockReset();
    mocks.delete.mockReset();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    window.localStorage.setItem("token", "test-token");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("consulta o servidor ao buscar um paciente fora da primeira página", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/pacientes?limit=100&skip=0") {
        return Promise.resolve({
          data: {
            total: 1299,
            total_ativos: 1299,
            items: [{ id: 1, nome: "Bidu", tutor: "Ana", especie: "Canina" }],
          },
        });
      }
      if (url === "/pacientes?limit=100&skip=0&search=rex") {
        return Promise.resolve({
          data: {
            total: 1,
            total_ativos: 1299,
            items: [{ id: 1299, nome: "Rex", tutor: "Rafael", especie: "Canina" }],
          },
        });
      }
      return Promise.reject(new Error(`URL inesperada: ${url}`));
    });

    render(<PacientesPage />);

    expect(await screen.findByText("Bidu")).toBeInTheDocument();
    expect(screen.getAllByText("1299")).toHaveLength(2);

    fireEvent.change(screen.getByPlaceholderText("Buscar por nome, tutor ou ID..."), {
      target: { value: "rex" },
    });
    await waitFor(() => {
      expect(mocks.get).toHaveBeenCalledWith("/pacientes?limit=100&skip=0&search=rex");
    });

    expect(await screen.findByText("Rex")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("1299")).toBeInTheDocument();
  });

  it("solicita a próxima página sem carregar todos os pacientes", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/pacientes?limit=100&skip=0") {
        return Promise.resolve({
          data: {
            total: 101,
            total_ativos: 101,
            items: [{ id: 1, nome: "Primeira página", tutor: "Ana", especie: "Canina" }],
          },
        });
      }
      if (url === "/pacientes?limit=100&skip=100") {
        return Promise.resolve({
          data: {
            total: 101,
            total_ativos: 101,
            items: [{ id: 101, nome: "Última página", tutor: "Ana", especie: "Canina" }],
          },
        });
      }
      return Promise.reject(new Error(`URL inesperada: ${url}`));
    });

    render(<PacientesPage />);

    expect(await screen.findByText("Primeira página")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Próxima" }));

    await waitFor(() => {
      expect(screen.getByText("Última página")).toBeInTheDocument();
    });
    expect(mocks.get).toHaveBeenCalledWith("/pacientes?limit=100&skip=100");
    expect(screen.getByText("Página 2 de 2")).toBeInTheDocument();
  });

  it("permite tentar novamente após uma falha de carregamento", async () => {
    mocks.get.mockRejectedValueOnce(new Error("falha temporária"));
    mocks.get.mockResolvedValueOnce({
      data: {
        total: 1,
        total_ativos: 1,
        items: [{ id: 1, nome: "Rex", tutor: "Rafael", especie: "Canina" }],
      },
    });

    render(<PacientesPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar a carteira de pacientes.");
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));

    expect(await screen.findByText("Rex")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });
});
