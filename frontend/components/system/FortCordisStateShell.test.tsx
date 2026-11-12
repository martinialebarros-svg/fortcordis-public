import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FortCordisStateShell from "./FortCordisStateShell";

describe("FortCordisStateShell", () => {
  it("renderiza eyebrow, titulo, descricao e icone", () => {
    render(
      <FortCordisStateShell eyebrow="Atencao" title="Sessao expirada" description="Faca login novamente." icon={<span data-testid="icone" />} />
    );

    expect(screen.getByText("Atencao")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sessao expirada" })).toBeInTheDocument();
    expect(screen.getByText("Faca login novamente.")).toBeInTheDocument();
    expect(screen.getByTestId("icone")).toBeInTheDocument();
  });

  it("nao renderiza a area de acoes quando nao ha children", () => {
    const { container } = render(
      <FortCordisStateShell eyebrow="Atencao" title="Erro" description="Algo falhou." icon={<span />} />
    );

    expect(container.querySelector(".fc-system-state-actions")).toBeNull();
  });

  it("renderiza children dentro da area de acoes quando fornecidos", () => {
    render(
      <FortCordisStateShell eyebrow="Atencao" title="Erro" description="Algo falhou." icon={<span />}>
        <button>Tentar novamente</button>
      </FortCordisStateShell>
    );

    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
  });

  it("aponta o link da marca para a home", () => {
    render(
      <FortCordisStateShell eyebrow="Atencao" title="Erro" description="Algo falhou." icon={<span />} />
    );

    expect(screen.getByRole("link", { name: /fort cordis/i })).toHaveAttribute("href", "/");
  });
});
