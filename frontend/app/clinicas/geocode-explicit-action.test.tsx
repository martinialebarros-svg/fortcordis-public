import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NovaClinicaPage from "./novo/page";
import EditarClinicaPage from "./[id]/page";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), router: { push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router, useParams: () => ({ id: "1" }) }));
vi.mock("../layout-dashboard", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get, post: mocks.post } }));
vi.mock("@/lib/stable-catalog-cache", () => ({ loadStableCatalog: async () => [] }));
vi.mock("./components/ManualPinModal", () => ({ default: () => null }));
vi.mock("./components/ClinicaPortalAccessCard", () => ({ default: () => null }));

describe("geocoding exige ação explícita na clínica", () => {
  beforeEach(() => {
    localStorage.setItem("token", "test");
    mocks.get.mockReset(); mocks.post.mockReset();
    mocks.get.mockImplementation(async (path: string) => ({ data: path === "/clinicas/1" ? {
      id: 1, nome: "Clínica sintética", endereco: "", numero: "", cidade: "", estado: "CE", whatsapps: [],
    } : [] }));
    mocks.post.mockResolvedValue({ data: { item: { latitude: -3, longitude: -38 } } });
  });

  it.each([["nova", NovaClinicaPage], ["edição", EditarClinicaPage]] as const)("não geocodifica ao sair de campos (%s)", async (_name, Page) => {
    render(<Page />);
    const address = await screen.findByPlaceholderText("Rua / Avenida");
    const number = screen.getByPlaceholderText("123");
    fireEvent.change(address, { target: { value: "Rua Sintética" } });
    fireEvent.change(number, { target: { value: "99" } });
    fireEvent.change(screen.getByPlaceholderText("Cidade"), { target: { value: "Fortaleza" } });
    fireEvent.blur(number);
    fireEvent.blur(address);
    expect(mocks.post).not.toHaveBeenCalledWith("/clinicas/geocode-endereco", expect.anything());
    expect(screen.getByText(/Use Geocodificar endereco/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Geocodificar/i }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/clinicas/geocode-endereco", expect.objectContaining({ endereco: "Rua Sintética", numero: "99" })));
  });
  it("consulta de CEP não exige coordenadas do geocodificador", async () => {
    mocks.get.mockResolvedValue({ data: { item: { cep: "60000000", endereco: "Rua Sintética", cidade: "Fortaleza", estado: "CE" } } });
    render(<NovaClinicaPage />);
    const cep = await screen.findByPlaceholderText("00000-000");
    fireEvent.change(cep, { target: { value: "60000-000" } });
    fireEvent.blur(cep);
    expect(await screen.findByText(/CEP preenchido pelo ViaCEP/)).toBeVisible();
    expect(mocks.post).not.toHaveBeenCalledWith("/clinicas/geocode-endereco", expect.anything());
  });

  it.each([null, undefined, "", 0])("coordenadas ausentes não aparecem como confirmadas (%s)", async (value) => {
    mocks.get.mockImplementation(async (path: string) => ({ data: path === "/clinicas/1" ? {
      id: 1, nome: "Clínica sintética", latitude: value, longitude: value, whatsapps: [],
    } : [] }));
    render(<EditarClinicaPage />);
    await screen.findByDisplayValue("Clínica sintética");
    expect(screen.queryByText(/Lat\/Lng:/)).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("resposta sem coordenadas não confirma zero nem sobrescreve endereço", async () => {
    mocks.post.mockResolvedValue({ data: { item: { latitude: null, longitude: null } } });
    render(<NovaClinicaPage />);
    fireEvent.change(await screen.findByPlaceholderText("Rua / Avenida"), { target: { value: "Rua Sintética" } });
    fireEvent.change(screen.getByPlaceholderText("123"), { target: { value: "99" } });
    fireEvent.change(screen.getByPlaceholderText("Cidade"), { target: { value: "Fortaleza" } });
    fireEvent.click(screen.getByRole("button", { name: /Geocodificar/i }));
    expect(await screen.findByText(/não retornou coordenadas válidas/)).toBeVisible();
    expect(screen.getByDisplayValue("Rua Sintética")).toBeVisible();
    expect(screen.queryByText(/Lat\/Lng:/)).toBeNull();
  });

});
