import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ClinicalFieldCard from "./ClinicalFieldCard";
import type { ClinicalFieldConfig } from "@/lib/atendimento-clinical-notes";

afterEach(() => {
  cleanup();
});

const config: ClinicalFieldConfig = {
  key: "exame_fisico",
  title: "Exame fisico",
  subtitle: "Achados de ausculta, perfusao e estabilidade.",
  placeholder: "Registre os achados relevantes do exame fisico.",
  rows: 7,
  tone: "sky",
  quickPhrases: [],
};

function noop() {}

describe("ClinicalFieldCard - salvar como frase rapida", () => {
  it("nao renderiza o botao quando onSaveAsPhrase nao e fornecido", () => {
    render(
      <ClinicalFieldCard
        config={config}
        value="Ausculta cardiaca com sopro em foco mitral."
        onChange={noop}
        onInsertPhrase={noop}
        onClear={noop}
      />
    );

    expect(screen.queryByText("Salvar como frase")).not.toBeInTheDocument();
  });

  it("desabilita o botao quando o campo esta vazio", () => {
    render(
      <ClinicalFieldCard
        config={config}
        value=""
        onChange={noop}
        onInsertPhrase={noop}
        onClear={noop}
        onSaveAsPhrase={() => true}
      />
    );

    expect(screen.getByText("Salvar como frase").closest("button")).toBeDisabled();
  });

  it("abre o formulario inline pre-preenchido com o texto atual do campo", () => {
    render(
      <ClinicalFieldCard
        config={config}
        value="Ausculta cardiaca com sopro em foco mitral."
        onChange={noop}
        onInsertPhrase={noop}
        onClear={noop}
        onSaveAsPhrase={() => true}
      />
    );

    fireEvent.click(screen.getByText("Salvar como frase"));

    expect(screen.getByPlaceholderText("Ex.: Sopro apical")).toHaveValue("");
    const textareasWithValue = screen.getAllByDisplayValue("Ausculta cardiaca com sopro em foco mitral.");
    expect(textareasWithValue).toHaveLength(2);
  });

  it("chama onSaveAsPhrase com titulo e texto e fecha o formulario quando a promessa resolve true", async () => {
    const onSaveAsPhrase = vi.fn().mockResolvedValue(true);
    render(
      <ClinicalFieldCard
        config={config}
        value="Ausculta cardiaca com sopro em foco mitral."
        onChange={noop}
        onInsertPhrase={noop}
        onClear={noop}
        onSaveAsPhrase={onSaveAsPhrase}
      />
    );

    fireEvent.click(screen.getByText("Salvar como frase"));
    fireEvent.change(screen.getByPlaceholderText("Ex.: Sopro apical"), {
      target: { value: "Sopro apical" },
    });

    fireEvent.click(screen.getByText("Salvar atalho"));

    expect(onSaveAsPhrase).toHaveBeenCalledWith("Sopro apical", "Ausculta cardiaca com sopro em foco mitral.");
    await screen.findByText("Salvar como frase");
    expect(screen.queryByText("Salvar atalho")).not.toBeInTheDocument();
  });

  it("mantem o formulario aberto quando onSaveAsPhrase resolve false", async () => {
    const onSaveAsPhrase = vi.fn().mockResolvedValue(false);
    render(
      <ClinicalFieldCard
        config={config}
        value="Ausculta cardiaca com sopro em foco mitral."
        onChange={noop}
        onInsertPhrase={noop}
        onClear={noop}
        onSaveAsPhrase={onSaveAsPhrase}
      />
    );

    fireEvent.click(screen.getByText("Salvar como frase"));
    fireEvent.change(screen.getByPlaceholderText("Ex.: Sopro apical"), {
      target: { value: "Sopro apical" },
    });
    fireEvent.click(screen.getByText("Salvar atalho"));

    await vi.waitFor(() => {
      expect(onSaveAsPhrase).toHaveBeenCalled();
    });
    expect(screen.getByText("Salvar atalho")).toBeInTheDocument();
  });

  it("nao permite salvar sem titulo preenchido", () => {
    render(
      <ClinicalFieldCard
        config={config}
        value="Ausculta cardiaca com sopro em foco mitral."
        onChange={noop}
        onInsertPhrase={noop}
        onClear={noop}
        onSaveAsPhrase={() => true}
      />
    );

    fireEvent.click(screen.getByText("Salvar como frase"));

    expect(screen.getByText("Salvar atalho").closest("button")).toBeDisabled();
  });
});
