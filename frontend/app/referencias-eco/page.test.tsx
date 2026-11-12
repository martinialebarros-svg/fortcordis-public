import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReferenciasEcoPage from "./page";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), router: { push: vi.fn() } }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get, put: mocks.put } }));
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));
vi.mock("../layout-dashboard", () => ({ default: ({ children }: { children: React.ReactNode }) => children }));

beforeEach(() => {
  localStorage.setItem("token", "synthetic-test-token");
  mocks.get.mockReset();
  mocks.put.mockReset();
  mocks.put.mockResolvedValue({ data: {} });
  vi.spyOn(window, "alert").mockImplementation(() => {});
});

describe("gestão dos números originais do catálogo", () => {
  it("mostra política e edita limites originais sem reenviar substituições de FS/EF e metadados", async () => {
    mocks.get.mockResolvedValue({ data: { items: [{
      id: 1, especie: "Canina", peso_kg: 10,
      lvid_d_min: 21, lvid_d_max: 30, fs_min: 20.7, fs_max: 51.9,
      vmax_ao_min: null, vmax_ao_max: null,
      catalog_ranges: { lvid_d: { min: 20, max: 31 }, fs: { min: 25, max: 45 }, ef: { min: 50, max: 85 }, vmax_ao: { min: 0, max: 2.2 } },
      range_metadata: { vmax_ao: { status: "blocked", reason: "Intervalo individual sem fonte" }, fs: { status: "published", source: "Visser et al. 2019", candidate_min: 20.7, candidate_max: 51.9 } },
    }] } });
    render(<ReferenciasEcoPage />);
    const edit = await screen.findByLabelText("Editar referência de 10 kg");
    expect(screen.getByText("0 – 2.2")).toBeInTheDocument();
    expect(screen.getByText("25 – 45")).toBeInTheDocument();
    expect(screen.getByText("Comparação: 20.7 – 51.9")).toBeInTheDocument();
    expect(screen.getByText("Comparação suspensa")).toBeInTheDocument();
    fireEvent.click(edit);
    expect(screen.getByLabelText("LVIDd mínimo")).toHaveValue(20);
    expect(screen.getByLabelText("Vmax aórtica máximo")).toHaveValue(2.2);
    fireEvent.change(screen.getByLabelText("LVIDd mínimo"), { target: { value: "22" } });
    fireEvent.click(screen.getByLabelText("Salvar referência de 10 kg"));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledOnce());
    const payload = mocks.put.mock.calls[0][1];
    expect(payload).toMatchObject({ especie: "Canina", peso_kg: 10, lvid_d_min: 22, lvid_d_max: 31, vmax_ao_min: 0, vmax_ao_max: 2.2 });
    for (const key of ["fs_min", "fs_max", "ef_min", "ef_max", "range_metadata", "catalog_ranges", "fs_source", "id"]) expect(payload).not.toHaveProperty(key);
  });
});
