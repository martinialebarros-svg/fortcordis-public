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
  selecionado?: number | null;
  atendimentoConcluido?: boolean;
  selecionarReceita?: (id: number | null) => void;
  criarReceitaComplementar?: () => void;
};

function Harness(props: HarnessProps) {
  return (
    <AtendimentoReceitasBar
      atendimentoConcluido={props.atendimentoConcluido ?? true}
      criandoReceita={false}
      criarReceitaComplementar={props.criarReceitaComplementar ?? (() => {})}
      formatDate={(valor: string) => valor}
      receitaAtiva={props.receitaAtiva === undefined ? receitaDoDia : props.receitaAtiva}
      receitas={props.receitas ?? [receitaDoDia, complementar]}
      selecionado={props.selecionado === undefined ? 1 : props.selecionado}
      selecionarReceita={props.selecionarReceita ?? (() => {})}
    />
  );
}

describe("AtendimentoReceitasBar", () => {
  it("nao aparece sem atendimento salvo ou sem receita", () => {
    const { container: semAtendimento } = render(<Harness selecionado={null} />);
    expect(semAtendimento.firstChild).toBeNull();
    cleanup();
    const { container: semReceita } = render(<Harness receitas={[]} />);
    expect(semReceita.firstChild).toBeNull();
  });

  it("distingue receita emitida de rascunho", () => {
    render(<Harness />);
    expect(screen.getByText("Emitida")).toBeTruthy();
    expect(screen.getByText("Rascunho")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Receita do dia/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Complementar 2/i })).toBeTruthy();
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

    fireEvent.click(screen.getByRole("button", { name: /Complementar 2/i }));
    expect(selecionar).toHaveBeenLastCalledWith(11);
  });

  it("diz que a complementar nao altera a receita do dia", () => {
    render(<Harness receitaAtiva={complementar} />);
    expect(screen.getByText(/nao sao alterados por ela/i)).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: /Nova receita complementar/i }));
    expect(criar).toHaveBeenCalledTimes(1);
  });
});
