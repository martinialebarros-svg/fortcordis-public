import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/dynamic", async () => {
  const { default: FortinhoOverlay } = await import("./FortinhoOverlay");
  return { default: () => FortinhoOverlay };
});

import { FortinhoProvider, useFortinho } from "./FortinhoProvider";

function Controles({ onResposta }: { onResposta: (resposta: boolean) => void }) {
  const fortinho = useFortinho();

  return (
    <>
      <button
        onClick={() =>
          fortinho.notify({
            title: "Dados da reserva atualizados",
            message: "Tutor e animal foram vinculados.",
            sticky: true,
          })
        }
      >
        Avisar
      </button>
      <button
        onClick={() => {
          void fortinho
            .confirm({
              title: "Confirmação recebida após o prazo",
              message: "O cliente confirmou?",
              confirmLabel: "Cliente confirmou; agendar",
              cancelLabel: "Cancelar",
            })
            .then(onResposta);
        }}
      >
        Pedir confirmação
      </button>
    </>
  );
}

describe("FortinhoProvider", () => {
  it("mostra confirmação após aviso persistente, resolve a resposta e retoma o aviso", async () => {
    const onResposta = vi.fn();
    render(
      <FortinhoProvider>
        <Controles onResposta={onResposta} />
      </FortinhoProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Avisar" }));
    const aviso = screen.getByText("Dados da reserva atualizados: Tutor e animal foram vinculados.");
    expect(aviso.closest(".fixed")).toHaveClass("z-[90]");
    expect(screen.getByRole("button", { name: "Entendi" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Pedir confirmação" }));
    const confirmacao = screen.getByText("Confirmação recebida após o prazo: O cliente confirmou?");
    expect(confirmacao.closest(".fixed")).toHaveClass("z-[110]");
    expect(screen.queryByRole("button", { name: "Entendi" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    await waitFor(() => expect(onResposta).toHaveBeenCalledExactlyOnceWith(false));
    expect(screen.getByText("Dados da reserva atualizados: Tutor e animal foram vinculados.").closest(".fixed")).toHaveClass("z-[90]");

    fireEvent.click(screen.getByRole("button", { name: "Pedir confirmação" }));
    fireEvent.click(screen.getByRole("button", { name: "Cliente confirmou; agendar" }));

    await waitFor(() => expect(onResposta).toHaveBeenNthCalledWith(2, true));
    expect(screen.getByText("Dados da reserva atualizados: Tutor e animal foram vinculados.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Entendi" }));
    expect(screen.queryByText("Dados da reserva atualizados: Tutor e animal foram vinculados.")).not.toBeInTheDocument();
  });

  it("reabre o Fortinho para confirmar e impede ocultá-lo antes da resposta", async () => {
    const onResposta = vi.fn();
    render(
      <FortinhoProvider>
        <Controles onResposta={onResposta} />
      </FortinhoProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Ocultar Fortinho" }));
    expect(screen.getByRole("button", { name: "Mostrar Fortinho" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Pedir confirmação" }));
    expect(screen.getByText("Confirmação recebida após o prazo: O cliente confirmou?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mostrar Fortinho" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ocultar Fortinho" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(onResposta).toHaveBeenCalledExactlyOnceWith(false));
    expect(screen.getByRole("button", { name: "Ocultar Fortinho" })).toBeInTheDocument();
  });
});
