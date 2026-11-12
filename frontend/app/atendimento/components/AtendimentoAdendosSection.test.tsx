import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AtendimentoAdendosSection from "./AtendimentoAdendosSection";

afterEach(() => {
  cleanup();
});

function noop() {}

const ADENDO_TIPO_OPCOES = [
  { value: "resultado_exame", label: "Resultado de exame", ajuda: "O tutor enviou o exame solicitado na consulta." },
  { value: "receita_complementar", label: "Receita complementar", ajuda: "Ajuste de tratamento depois da alta." },
  { value: "orientacao", label: "Orientacao ao tutor", ajuda: "Contato, retorno por telefone ou WhatsApp." },
  { value: "evolucao", label: "Evolucao clinica", ajuda: "Acompanhamento do quadro." },
];

const adendoComExame = {
  id: 7,
  atendimento_id: 1,
  tipo: "resultado_exame",
  titulo: "Resultado de exame recebido",
  descricao: "Tutor enviou o ecocardiograma pelo WhatsApp.",
  data_evolucao: "2026-09-08T10:00:00",
  pos_conclusao: 1,
  responsavel_nome: "Dra. Teste",
  anexos: [],
  prescricao_id: null,
};

type HarnessProps = {
  adendos?: any[];
  atendimentoConcluido?: boolean;
  selecionado?: number | null;
  examesAguardandoArquivo?: any[];
  criarAdendo?: () => Promise<unknown>;
  criarReceitaComplementar?: (adendoId?: number | null) => void;
  anexarArquivoNoAdendo?: (adendo: any, arquivos: File[]) => Promise<void>;
};

function Harness(props: HarnessProps) {
  const [adendoForm, setAdendoForm] = useState({ tipo: "resultado_exame", titulo: "", descricao: "" });
  const [adendoFormAberto, setAdendoFormAberto] = useState(false);
  const [exameDoAdendo, setExameDoAdendo] = useState<Record<number, string>>({});

  return (
    <AtendimentoAdendosSection
      ADENDO_TIPO_OPCOES={ADENDO_TIPO_OPCOES}
      ATENDIMENTO_ATTACHMENT_ACCEPT=".jpeg,.jpg,.pdf,.png,.webp"
      abrirAnexo={noop}
      adendoForm={adendoForm}
      adendoFormAberto={adendoFormAberto}
      adendos={props.adendos ?? []}
      anexarArquivoNoAdendo={props.anexarArquivoNoAdendo ?? (async () => {})}
      atendimentoConcluido={props.atendimentoConcluido ?? true}
      cancelarUploadAnexo={noop}
      criandoAdendo={false}
      criandoReceita={false}
      criarAdendo={props.criarAdendo ?? (async () => null)}
      criarReceitaComplementar={props.criarReceitaComplementar ?? (() => {})}
      exameDoAdendo={exameDoAdendo}
      examesAguardandoArquivo={props.examesAguardandoArquivo ?? []}
      formatDate={(valor: string) => valor}
      selecionado={props.selecionado === undefined ? 1 : props.selecionado}
      setAdendoForm={setAdendoForm}
      setAdendoFormAberto={setAdendoFormAberto}
      setExameDoAdendo={setExameDoAdendo}
      uploadProgressByKey={{}}
      uploadingAttachmentKey={null}
    />
  );
}

describe("AtendimentoAdendosSection", () => {
  it("explica a continuidade quando o atendimento ja esta concluido", () => {
    render(<Harness atendimentoConcluido />);
    expect(screen.getByText(/ja foi concluido/i)).toBeTruthy();
    expect(screen.getByText(/Nenhum adendo neste atendimento/i)).toBeTruthy();
  });

  it("exige atendimento salvo antes de registrar adendo", () => {
    render(<Harness selecionado={null} />);
    expect(screen.getByText(/Salve o atendimento para poder registrar adendos/i)).toBeTruthy();
    const botao = screen.getByRole("button", { name: /Registrar adendo/i }) as HTMLButtonElement;
    expect(botao.disabled).toBe(true);
  });

  it("so habilita o envio do adendo com descricao preenchida", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Registrar adendo/i }));

    const enviar = screen.getAllByRole("button", { name: /Registrar adendo/i }).at(-1) as HTMLButtonElement;
    expect(enviar.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/Descreva o que chegou/i), {
      target: { value: "Ecocardiograma recebido." },
    });
    expect((screen.getAllByRole("button", { name: /Registrar adendo/i }).at(-1) as HTMLButtonElement).disabled).toBe(
      false
    );
  });

  it("marca o adendo criado depois da conclusao", () => {
    render(<Harness adendos={[adendoComExame]} />);
    expect(screen.getByText("Resultado de exame recebido")).toBeTruthy();
    expect(screen.getByText(/Apos a conclusao/i)).toBeTruthy();
    expect(screen.getByText(/Tutor enviou o ecocardiograma/i)).toBeTruthy();
  });

  it("anexa arquivo ao adendo vinculando o exame escolhido", async () => {
    const anexar = vi.fn<(adendo: any, arquivos: File[]) => Promise<void>>(async () => {});
    render(
      <Harness
        adendos={[adendoComExame]}
        examesAguardandoArquivo={[{ id: 42, tipo_exame: "Ecocardiograma" }]}
        anexarArquivoNoAdendo={anexar}
      />
    );

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "42" } });
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("42");

    const arquivo = new File(["conteudo"], "eco.pdf", { type: "application/pdf" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [arquivo] } });

    await waitFor(() => expect(anexar).toHaveBeenCalledTimes(1));
    expect(anexar.mock.calls[0][0].id).toBe(7);
    expect(anexar.mock.calls[0][1][0].name).toBe("eco.pdf");
  });

  it("emite receita a partir de um adendo de receita complementar", () => {
    const criar = vi.fn();
    render(
      <Harness
        adendos={[{ ...adendoComExame, tipo: "receita_complementar", titulo: "Receita complementar" }]}
        criarReceitaComplementar={criar}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Emitir receita deste adendo/i }));
    expect(criar).toHaveBeenCalledWith(7);
  });

  it("mostra que o adendo ja tem receita vinculada", () => {
    render(
      <Harness
        adendos={[{ ...adendoComExame, tipo: "receita_complementar", prescricao_id: 99 }]}
      />
    );
    expect(screen.getByText(/Receita vinculada/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Emitir receita deste adendo/i })).toBeNull();
  });

  it("nao oferece vinculo de exame quando nao ha exame aguardando arquivo", () => {
    render(<Harness adendos={[adendoComExame]} examesAguardandoArquivo={[]} />);
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
