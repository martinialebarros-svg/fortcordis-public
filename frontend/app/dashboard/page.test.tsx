import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import api from "@/lib/axios";
import DashboardPage from "./page";

vi.mock("../layout-dashboard", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/axios", () => ({
  default: {
    get: vi.fn(),
  },
}));

const mockedGet = vi.mocked(api.get);

const response = (data: unknown) => Promise.resolve({ data });

describe("DashboardPage", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("token", "test-session");
    mockedGet.mockReset();
  });

  it("inicia as quatro leituras em paralelo e preserva as secoes que responderam", async () => {
    mockedGet.mockImplementation((url) => {
      if (String(url).startsWith("/agenda?")) {
        return response({ items: [] });
      }
      if (url === "/pacientes") {
        return Promise.reject(new Error("timeout"));
      }
      if (url === "/clinicas") {
        return response({ total: 164 });
      }
      return response({ total: 12 });
    });

    render(<DashboardPage />);

    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(4));
    expect(mockedGet.mock.calls.map(([url]) => url)).toEqual(
      expect.arrayContaining(["/pacientes", "/clinicas", "/servicos"])
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Pacientes");
    expect(screen.getAllByText("164").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("repete somente a secao que falhou", async () => {
    let pacientesShouldSucceed = false;
    mockedGet.mockImplementation((url) => {
      if (String(url).startsWith("/agenda?")) {
        return response({ items: [] });
      }
      if (url === "/pacientes") {
        return pacientesShouldSucceed ? response({ total: 1313 }) : Promise.reject(new Error("timeout"));
      }
      if (url === "/clinicas") {
        return response({ total: 164 });
      }
      return response({ total: 12 });
    });

    render(<DashboardPage />);
    await screen.findByRole("alert");
    mockedGet.mockClear();
    pacientesShouldSucceed = true;

    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));

    await waitFor(() => expect(mockedGet).toHaveBeenCalledWith("/pacientes", expect.anything()));
    expect(mockedGet).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
