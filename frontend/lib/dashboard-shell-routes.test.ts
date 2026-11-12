import { describe, expect, it } from "vitest";
import { usesDashboardShell } from "./dashboard-shell-routes";

describe("dashboard shell routes", () => {
  it("keeps the authenticated shell mounted for supported modules and descendants", () => {
    expect(usesDashboardShell("/dashboard")).toBe(true);
    expect(usesDashboardShell("/agenda/fullcalendar")).toBe(true);
    expect(usesDashboardShell("/atendimento")).toBe(true);
    expect(usesDashboardShell("/laudos/42/editar")).toBe(true);
    expect(usesDashboardShell("/financeiro/frota")).toBe(true);
    expect(usesDashboardShell("/gestao")).toBe(true);
    expect(usesDashboardShell("/tutores")).toBe(true);
  });

  it("does not mount the authenticated shell for public or similarly named routes", () => {
    expect(usesDashboardShell("/")).toBe(false);
    expect(usesDashboardShell("/portal/clinica")).toBe(false);
    expect(usesDashboardShell("/agendado")).toBe(false);
    expect(usesDashboardShell(null)).toBe(false);
  });
});
