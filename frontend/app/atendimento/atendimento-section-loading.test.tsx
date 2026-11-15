import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React, { Suspense } from "react";
import { act, render, screen } from "@testing-library/react";
import dynamic, { type DynamicOptions } from "next/dist/shared/lib/app-dynamic";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import AtendimentoSectionLoading from "./components/AtendimentoSectionLoading";

// Usa as declarações reais da página e o carregador do App Router. Somente
// a chegada do módulo é controlada para reproduzir uma primeira abertura lenta.
const source = ts.createSourceFile(
  "page.tsx",
  readFileSync(resolve(process.cwd(), "app/atendimento/page.tsx"), "utf8"),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX
);

function declaration(name: string) {
  for (const statement of source.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    const match = statement.declarationList.declarations.find((item) => item.name.getText(source) === name);
    if (match?.initializer) return match.initializer.getText(source);
  }
  throw new Error(`Área não encontrada: ${name}`);
}

describe("carregamento independente das áreas do atendimento", () => {
  it.each([
    "AtendimentoExamesSection",
    "AtendimentoDocumentosSection",
    "AtendimentoPrescricaoWorkspace",
  ])("mantém cabeçalho e navegação visíveis enquanto %s carrega", async (name) => {
    let complete!: (value: { default: React.ComponentType }) => void;
    const moduleReady = new Promise<{ default: React.ComponentType }>((resolve) => { complete = resolve; });
    const controlledDynamic = (_loader: unknown, options: DynamicOptions = {}) => dynamic(() => moduleReady, options);
    const Section = new Function("dynamic", "AtendimentoSectionLoading", `return ${declaration(name)};`)(
      controlledDynamic, AtendimentoSectionLoading
    ) as React.ComponentType;

    render(
      <Suspense fallback={<p>Carregando a página inteira</p>}>
        <h1>Atendimento em revisão</h1>
        <button type="button">Consulta</button>
        <Section />
      </Suspense>
    );

    expect(screen.getByRole("heading", { name: "Atendimento em revisão" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Consulta" })).toBeVisible();
    expect(screen.queryByText("Carregando a página inteira")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Carregando esta área");

    await act(async () => { complete({ default: () => <p>Área pronta</p> }); });
    expect(screen.getByText("Área pronta")).toBeVisible();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
