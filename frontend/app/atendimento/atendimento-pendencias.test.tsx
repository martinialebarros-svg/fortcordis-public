import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useCallback, useRef, useState, type RefObject } from "react";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";
import {
  CLINICAL_FIELD_CONFIGS,
  buildClinicalQuickSummary,
  type ClinicalFieldKey,
  type ClinicalFieldValues,
  type ClinicalPendingField,
} from "@/lib/atendimento-clinical-notes";
import AtendimentoClinicalRadarAside from "./components/AtendimentoClinicalRadarAside";
import AtendimentoConsultaEditorSection from "./components/AtendimentoConsultaEditorSection";

type Etapa = { key: string; titulo: string; campos: ClinicalFieldKey[] };
type ContextoFoco = {
  useCallback: typeof useCallback;
  clinicalTextareaRefs: RefObject<Partial<Record<ClinicalFieldKey, HTMLTextAreaElement | null>>>;
  prognosticoRef: RefObject<HTMLSelectElement | null>;
  focoPendenciaRef: RefObject<{ campo: ClinicalPendingField; contexto: number } | null>;
  atendimentoContextoAplicadoRef: RefObject<number>;
  isConsultaWorkspace: boolean;
  setWorkspacePainel: (area: "consulta") => void;
  setConsultaEditorEtapa: (etapa: string) => void;
  setConsultaCampoAtivo: (campo: ClinicalFieldKey) => void;
};

// Exercita a navegação real da página com os componentes reais. O restante da
// tela e a chegada do editor são controlados para simular a carga assíncrona.
const pageSource = ts.createSourceFile(
  "page.tsx",
  readFileSync(resolve(process.cwd(), "app/atendimento/page.tsx"), "utf8"),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);
const hooksPagina = [
  "CONSULTA_EDITOR_ETAPAS", "focarControleConsulta", "focarCampoConsulta", "irParaPendenciaClinica",
];
const declarations = new Map<string, string>();
function readDeclarations(node: ts.Node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && hooksPagina.includes(node.name.text)) {
    declarations.set(node.name.text, node.getText(pageSource));
  }
  ts.forEachChild(node, readDeclarations);
}
readDeclarations(pageSource);
const bindFocus = new Function("contexto", ts.transpileModule(`
  const { useCallback, clinicalTextareaRefs, prognosticoRef, focoPendenciaRef, atendimentoContextoAplicadoRef,
    isConsultaWorkspace, setWorkspacePainel, setConsultaEditorEtapa, setConsultaCampoAtivo } = contexto;
  ${hooksPagina.map((name) => `const ${declarations.get(name)};`).join("\n")}
  return { etapas: CONSULTA_EDITOR_ETAPAS, focarCampoConsulta, irParaPendenciaClinica };
`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText) as (ctx: ContextoFoco) => {
  etapas: Etapa[];
  focarCampoConsulta: (campo: ClinicalFieldKey | undefined, verTodos: boolean) => void;
  irParaPendenciaClinica: (campo: ClinicalPendingField) => void;
};

const notas = {
  queixa_principal: "Queixa fictícia",
  anamnese: "Anamnese fictícia",
  exame_fisico: "Exame fictício",
};
function Tela({
  documentos = false,
  editorPronto = true,
  consolidado = false,
  values = notas as Partial<ClinicalFieldValues>,
  onChange,
}: {
  documentos?: boolean;
  editorPronto?: boolean;
  consolidado?: boolean;
  values?: Partial<ClinicalFieldValues>;
  onChange: () => void;
}) {
  const [area, setWorkspacePainel] = useState<"consulta" | "documentos">(documentos ? "documentos" : "consulta");
  const [etapa, setConsultaEditorEtapa] = useState("anamnese");
  const [campo, setConsultaCampoAtivo] = useState<ClinicalFieldKey>("queixa_principal");
  const [verTodos, setConsultaVerTodosCampos] = useState(consolidado);
  const isConsultaWorkspace = area === "consulta";
  const clinicalTextareaRefs = useRef<Partial<Record<ClinicalFieldKey, HTMLTextAreaElement | null>>>({});
  const prognosticoRef = useRef<HTMLSelectElement>(null);
  const focoPendenciaRef = useRef<{ campo: ClinicalPendingField; contexto: number } | null>(null);
  const atendimentoContextoAplicadoRef = useRef(1);
  const { etapas, focarCampoConsulta, irParaPendenciaClinica } = bindFocus({
    useCallback, clinicalTextareaRefs, prognosticoRef, focoPendenciaRef, atendimentoContextoAplicadoRef,
    isConsultaWorkspace, setWorkspacePainel, setConsultaEditorEtapa, setConsultaCampoAtivo,
  });
  const clinicalSummary = buildClinicalQuickSummary(values, "");
  const form = {
    ...notas, plano_terapeutico: "", retorno_recomendado: "", consulta_concluida: 0,
    diagnostico: { prognostico: "" }, exames: [], prescricao_itens: [],
  };
  const grupos = etapas.map((item) => ({
    ...item,
    configs: CLINICAL_FIELD_CONFIGS.filter(({ key }) => item.campos.includes(key)),
    total: item.campos.length, preenchidos: 0, percentual: 0,
  }));
  const camposDaEtapa = grupos.find(({ key }) => key === etapa)!.configs;
  return (
    <>
      <span role="status">{area}</span>
      <aside aria-label="Radar">
        <AtendimentoClinicalRadarAside alertasAtivos={[]} form={form} clinicalSummary={clinicalSummary} irParaPendenciaClinica={irParaPendenciaClinica} />
      </aside>
      {isConsultaWorkspace && editorPronto ? (
        <AtendimentoConsultaEditorSection
          clinicalSummary={clinicalSummary}
          consultaCampoAtivoConfig={camposDaEtapa.find(({ key }) => key === campo) ?? camposDaEtapa[0]}
          consultaCampoAtivoIndex={camposDaEtapa.findIndex(({ key }) => key === campo)}
          consultaEditorCamposVisiveis={camposDaEtapa}
          consultaEditorEtapa={etapa}
          consultaEditorEtapas={grupos}
          consultaEditorGruposConsolidados={grupos}
          consultaVerTodosCampos={verTodos}
          focarCampoConsulta={focarCampoConsulta}
          form={form}
          getClinicalFieldValue={(key: ClinicalFieldKey) => values[key] || ""}
          irParaPendenciaClinica={irParaPendenciaClinica}
          PROGNOSTICO={["Bom"]}
          prognosticoRef={prognosticoRef}
          registerClinicalTextarea={(key: ClinicalFieldKey) => (node: HTMLTextAreaElement | null) => {
            clinicalTextareaRefs.current[key] = node;
          }}
          setClinicalFieldValue={onChange}
          setConsultaCampoAtivo={setConsultaCampoAtivo}
          setConsultaEditorEtapa={setConsultaEditorEtapa}
          setConsultaVerTodosCampos={setConsultaVerTodosCampos}
          setField={onChange}
        />
      ) : null}
    </>
  );
}

describe("atalhos para pendências do atendimento", () => {
  it("sai de Documentos pelo radar e foca diagnóstico quando o editor carrega", () => {
    const onChange = vi.fn();
    const { rerender } = render(<Tela documentos editorPronto={false} onChange={onChange} />);
    const radar = within(screen.getByRole("complementary", { name: "Radar" }));
    fireEvent.click(radar.getByRole("button", { name: "Definir o diagnostico principal." }));
    expect(screen.getByRole("status")).toHaveTextContent("consulta");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    rerender(<Tela documentos onChange={onChange} />);
    expect(screen.getByRole("textbox", { name: "Diagnostico principal" })).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("mantém a revisão consolidada ao saltar para o retorno", () => {
    const onChange = vi.fn();
    render(<Tela consolidado onChange={onChange} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Orientar o retorno." })[0]);
    expect(screen.getByRole("textbox", { name: "Retorno recomendado" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Ver um por vez" })).toBeVisible();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("permite focar o prognóstico mesmo com as outras pendências em aberto", () => {
    const onChange = vi.fn();
    render(<Tela values={{}} onChange={onChange} />);
    const select = screen.getByRole("combobox", { name: "Prognostico" });
    const scroll = vi.fn();
    select.scrollIntoView = scroll;
    fireEvent.click(screen.getByRole("button", { name: "Selecionar o prognostico." }));
    expect(select).toHaveFocus();
    expect(select).toHaveValue("");
    expect(scroll).toHaveBeenCalledWith({ block: "center" });
    expect(onChange).not.toHaveBeenCalled();
  });
});
