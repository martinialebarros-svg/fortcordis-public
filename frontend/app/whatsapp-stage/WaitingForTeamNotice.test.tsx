import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import WaitingForTeamNotice from "./WaitingForTeamNotice";
afterEach(cleanup);
const base = { needsReply: true, waitingLabel: "Aguardando há 2 h", windowOpen: true };
describe("Pendência com atendimento humano ou pausa", () => {
  it("mostra responsável mesmo sem pausa temporária e explica o bloqueio por atribuição", () => {
    render(<WaitingForTeamNotice {...base} ownerId="1" ownerName="Equipe teste" paused={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Responsável: Equipe teste");
    expect(screen.getByRole("status")).toHaveTextContent("Remover apenas a pausa não libera");
  });
  it("mostra motivo e prazo em Fortaleza para conversa sem responsável", () => {
    render(<WaitingForTeamNotice {...base} paused pausedUntil="2026-09-23T15:00:00Z" handoffReason="pedido_humano" />);
    expect(screen.getByRole("status")).toHaveTextContent("sem responsável");
    expect(screen.getByRole("status")).toHaveTextContent("12:00 (Fortaleza)");
    expect(screen.getByRole("status")).toHaveTextContent("cliente pediu atendimento humano");
  });
  it("remove o aviso após resposta e não trata motivo histórico como pausa ativa", () => {
    const { rerender } = render(<WaitingForTeamNotice {...base} paused />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    rerender(<WaitingForTeamNotice {...base} needsReply={false} paused />);
    expect(screen.queryByRole("status")).toBeNull();
    rerender(<WaitingForTeamNotice {...base} paused={false} handoffReason="emergencia" />);
    expect(screen.queryByRole("status")).toBeNull();
  });
  it("orienta usar modelos quando janela fechada e não exibe data inválida", () => {
    render(<WaitingForTeamNotice {...base} paused pausedUntil="invalid" windowOpen={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("janela de resposta livre está fechada");
    expect(screen.getByRole("status")).not.toHaveTextContent("invalid");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
