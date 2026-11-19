import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AtendimentoReceitasBar from "./AtendimentoReceitasBar";

afterEach(() => {
  cleanup();
});

const receitaDoDia = {
  id: 10,
  sequencia: 1,
  emitida_em: "2026-09-01T15:00:00-03:00",
  orientacoes_gerais: "Repouso",
  retorno_dias: 7,
  itens: [],
};
const complementar = {
  id: 11,
  sequencia: 2,
  emitida_em: null,
  orientacoes_gerais: "",
  retorno_dias: null,
  itens: [],
};

type HarnessProps = {
  receitas?: any[];
  receitaAtiva?: any;
  podeCriarReceita?: boolean;
  controlesOcupados?: boolean;
  atendimentoConcluido?: boolean;
  selecionarReceita?: (id: number | null) => void;
  criarReceitaComplementar?: () => void;
};

function Harness(props: HarnessProps) {
  return (
    <AtendimentoReceitasBar
      atendimentoConcluido={props.atendimentoConcluido ?? true}
      criandoReceita={false}
      controlesOcupados={props.controlesOcupados ?? false}
      criarReceitaComplementar={props.criarReceitaComplementar ?? (() => {})}
      formatDate={(valor: string) => valor}
      receitaAtiva={props.receitaAtiva === undefined ? receitaDoDia : props.receitaAtiva}
      receitas={props.receitas ?? [receitaDoDia, complementar]}
      podeCriarReceita={props.podeCriarReceita ?? true}
      selecionarReceita={props.selecionarReceita ?? (() => {})}
    />
  );
}

describe("AtendimentoReceitasBar", () => {
  it("permite começar a receita com paciente selecionado, mesmo sem receitas anteriores", () => {
    const { container: semPaciente } = render(<Harness podeCriarReceita={false} />);
    expect(semPaciente.firstChild).toBeNull();
    cleanup();
    render(<Harness receitas={[]} receitaAtiva={null} atendimentoConcluido={false} />);
    expect(screen.getByRole("button", { name: "Nova receita" })).toBeTruthy();
  });

  it("distingue receita emitida de rascunho", () => {
    render(<Harness />);
    expect(screen.getByText("Emitida")).toBeTruthy();
    expect(screen.getByText("Rascunho")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Receita do dia/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Receita 2/i }).getAttribute("aria-pressed")).toBe("false");
  });

  it("avisa que a receita ativa ja foi emitida e pode estar com o tutor", () => {
    render(<Harness />);
    expect(screen.getByText(/ja pode estar com o tutor/i)).toBeTruthy();
  });

  it("manda null ao voltar para a receita do dia e o id ao abrir a complementar", () => {
    const selecionar = vi.fn();
    render(<Harness selecionarReceita={selecionar} receitaAtiva={complementar} />);

    fireEvent.click(screen.getByRole("button", { name: /Receita do dia/i }));
    expect(selecionar).toHaveBeenLastCalledWith(null);

    fireEvent.click(screen.getByRole("button", { name: /Receita 2/i }));
    expect(selecionar).toHaveBeenLastCalledWith(11);
  });

  it("identifica o alvo da emissão", () => {
    render(<Harness receitaAtiva={complementar} />);
    expect(screen.getByText(/PDF será gerado para a receita selecionada/i)).toBeTruthy();
  });

  it("permite edicao direta apos emissao com aviso de historico e novo PDF", () => {
    render(<Harness />);
    expect(screen.getByText(/Voce pode editar normalmente/i)).toBeTruthy();
    expect(screen.getByText(/Gere um novo PDF/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Confirmar e salvar/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Descartar alteracao/i })).toBeNull();
  });

  it("cria receita complementar pelo botao dedicado", () => {
    const criar = vi.fn();
    render(<Harness criarReceitaComplementar={criar} />);
    fireEvent.click(screen.getByRole("button", { name: /Nova receita/i }));
    expect(criar).toHaveBeenCalledTimes(1);
  });
});
