import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EcocardiogramaEstruturadoPersistido } from "@/lib/ecocardiograma-estruturado";

import EcocardiogramaEstruturadoEditor from "./EcocardiogramaEstruturadoEditor";

const apiMocks = vi.hoisted(() => ({
  aplicarPreset: vi.fn(),
  atualizarFrase: vi.fn(),
  carregarBanco: vi.fn(),
  criarFrase: vi.fn(),
  excluirPreset: vi.fn(),
  salvarPreset: vi.fn(),
}));

vi.mock("@/lib/frases-ecocardiograma-estruturado-teste-api", () => ({
  aplicarPresetEcoEstruturadoTeste: apiMocks.aplicarPreset,
  atualizarFraseEcoEstruturadoTeste: apiMocks.atualizarFrase,
  carregarBancoEcoEstruturadoTeste: apiMocks.carregarBanco,
  criarFraseEcoEstruturadoTeste: apiMocks.criarFrase,
  excluirPresetEcoEstruturadoTeste: apiMocks.excluirPreset,
  salvarPresetEcoEstruturadoTeste: apiMocks.salvarPreset,
}));

const textoModerado = "Ventrículo esquerdo com sobrecarga volumétrica moderada.";
const textoImportante = "Ventrículo esquerdo com sobrecarga volumétrica importante.";
const textoMitralNormal = "Valva mitral sem alterações morfológicas ou refluxo.";
const textoMitralLeve = "Valva mitral com espessamento e refluxo leves.";
const conclusaoDmvm = "Doença valvar mixomatosa com repercussão hemodinâmica.";
const conclusaoHp = "Alta probabilidade ecocardiográfica de hipertensão pulmonar.";

const payload = {
  version: "1",
  mode: "teste",
  last_updated: "2026-09-21T00:00:00Z",
  aspectos: [
    {
      key: "valva_mitral",
      label: "Valva mitral",
      categoria: "Valvas",
      descricao: "Morfologia e refluxo mitral",
      placeholder: "Descreva a valva mitral",
      legacy_field: "valvas",
      ordem: 5,
      frases: [
        {
          id: 1,
          titulo: "Mitral normal",
          texto: textoMitralNormal,
          tags: ["normal"],
          ativo: 1,
        },
        {
          id: 3,
          titulo: "Espessamento mitral leve com refluxo leve",
          texto: textoMitralLeve,
          tags: ["endocardiose", "leve", "B1"],
          ativo: 1,
        },
      ],
    },
    {
      key: "ventriculo_esquerdo",
      label: "Ventriculo esquerdo",
      categoria: "Camaras esquerdas",
      descricao: "Dimensoes do VE",
      placeholder: "Descreva o ventriculo esquerdo",
      legacy_field: "camaras",
      ordem: 10,
      frases: [
        {
          id: 65,
          titulo: "VE com sobrecarga volumétrica leve",
          texto: "Ventrículo esquerdo com sobrecarga volumétrica discreta.",
          tags: ["leve", "endocardiose", "cao"],
          ativo: 1,
        },
        {
          id: 66,
          titulo: "VE com sobrecarga volumétrica moderada",
          texto: textoModerado,
          tags: ["moderado", "endocardiose", "cao", "B2"],
          ativo: 1,
        },
        {
          id: 67,
          titulo: "VE com sobrecarga volumétrica importante",
          texto: textoImportante,
          tags: ["grave", "endocardiose", "cao", "C"],
          ativo: 1,
        },
      ],
    },
    {
      key: "conclusao",
      label: "Conclusao",
      categoria: "Conclusao",
      descricao: "Sintese",
      placeholder: "Escreva a conclusao",
      legacy_field: "conclusao",
      ordem: 20,
      frases: [
        {
          id: 170,
          titulo: "DMVM",
          texto: conclusaoDmvm,
          patologias: ["Doença valvar mixomatosa"],
          tags: ["dmvm"],
          ativo: 1,
        },
        {
          id: 181,
          titulo: "Hipertensao pulmonar importante",
          texto: conclusaoHp,
          patologias: ["Hipertensão pulmonar"],
          tags: ["hp", "grave"],
          ativo: 1,
        },
      ],
    },
  ],
  presets: [
    {
      id: 7,
      key: "dmvm_base",
      label: "DMVM base",
      selecoes: [
        { aspecto: "valva_mitral", frase_id: 1, frase_titulo: "Mitral normal" },
        { aspecto: "ventriculo_esquerdo", frase_id: 66, frase_titulo: "VE moderado" },
        { aspecto: "conclusao", frase_id: 170, frase_titulo: "DMVM" },
      ],
    },
  ],
};

const estadoInicial: EcocardiogramaEstruturadoPersistido = {
  versao: 1,
  modo: "teste",
  usar_no_laudo: true,
  preset_id: 7,
  preset_label: "DMVM base",
  preset_textos: {
    valva_mitral: textoMitralNormal,
    ventriculo_esquerdo: textoModerado,
    conclusao: conclusaoDmvm,
  },
  updated_at: "2026-09-21T00:00:00Z",
  textos: {
    valva_mitral: textoMitralNormal,
    ventriculo_esquerdo: textoModerado,
    conclusao: conclusaoDmvm,
  },
};

function EditorControlado({
  onChange,
}: {
  onChange: (estado: EcocardiogramaEstruturadoPersistido) => void;
}) {
  const [estado, setEstado] = useState(estadoInicial);
  return (
    <EcocardiogramaEstruturadoEditor
      value={estado}
      onChange={(proximo) => {
        onChange(proximo);
        setEstado(proximo);
      }}
    />
  );
}

describe("EcocardiogramaEstruturadoEditor - composicao de achados", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
    apiMocks.carregarBanco.mockResolvedValue(payload);
    window.localStorage.clear();
  });

  it.each(["Dog", "Cão", "Canino"])
    ("omite presets exclusivamente felinos no seletor clínico de %s", async (species) => {
      apiMocks.carregarBanco.mockResolvedValue({
        ...payload,
        presets: [
          { id: 71, key: "canino", label: "Preset exclusivamente canino", tags: ["cao"], selecoes: [] },
          { id: 72, key: "felino", label: "Preset exclusivamente felino", tags: ["gato"], selecoes: [] },
          { id: 73, key: "comum", label: "Preset comum às duas espécies", tags: ["cao", "gato"], selecoes: [] },
          { id: 74, key: "geral", label: "Preset sem restrição de espécie", tags: [], selecoes: [] },
        ],
      });
      const onChange = vi.fn();
      render(<EcocardiogramaEstruturadoEditor value={estadoInicial} onChange={onChange} especie={species} />);
      fireEvent.click(await screen.findByRole("button", { name: "Selecione um preset" }));
      expect(screen.queryByRole("button", { name: /Preset exclusivamente felino/i })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Preset exclusivamente canino/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Preset comum às duas espécies\s*cao \| gato/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Preset sem restrição de espécie/i })).toBeInTheDocument();
      expect(apiMocks.aplicarPreset).not.toHaveBeenCalled();
      expect(onChange).not.toHaveBeenCalled();
    });

  it("oferece padrão felino complementar e preserva os demais textos", async () => {
    const felinePreset = {
      id: 50,
      key: "felino_diastolica_relaxamento",
      label: "Função diastólica felina: relaxamento retardado",
      patologia: "Função diastólica felina",
      tags: ["gato", "diastolica", "complementar"],
      selecoes: [{ aspecto: "funcao_diastolica", frase_titulo: "Relaxamento retardado" }],
    };
    apiMocks.carregarBanco.mockResolvedValue({
      ...payload,
      presets: [payload.presets[0], felinePreset],
    });
    apiMocks.aplicarPreset.mockResolvedValue({
      preset: felinePreset,
      textos: { funcao_diastolica: "Relaxamento ventricular esquerdo retardado." },
      selecoes_resolvidas: [],
    });
    const onChange = vi.fn();
    render(<EcocardiogramaEstruturadoEditor value={estadoInicial} onChange={onChange} especie="Felina" />);
    fireEvent.click(await screen.findByRole("button", { name: "Selecione um preset" }));
    fireEvent.click(screen.getByRole("button", { name: /Função diastólica felina: relaxamento retardado/i }));
    expect(screen.queryByRole("button", { name: "Zerar e aplicar" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar sobre atual" }));
    await waitFor(() => {
      const next = onChange.mock.calls.at(-1)?.[0] as EcocardiogramaEstruturadoPersistido;
      expect(next.textos.funcao_diastolica).toBe("Relaxamento ventricular esquerdo retardado.");
      expect(next.textos.conclusao).toBe(conclusaoDmvm);
      expect(next.textos.ventriculo_esquerdo).toBe(textoModerado);
    });
  });

  it("substitui o grau do aspecto com escolha unica sem alterar a biblioteca", async () => {
    const onChange = vi.fn();
    render(<EditorControlado onChange={onChange} />);

    fireEvent.click(await screen.findByRole("button", { name: /Combinar achados/i }));
    const opcaoImportante = await screen.findByRole("radio", {
      name: /Importante/i,
    });
    fireEvent.click(opcaoImportante);

    await waitFor(() => {
      const ultimoEstado = onChange.mock.calls.at(-1)?.[0] as EcocardiogramaEstruturadoPersistido;
      expect(ultimoEstado.textos.ventriculo_esquerdo).toBe(textoImportante);
    });
    expect(screen.getByText("Alterado")).toBeInTheDocument();

    const campoVe = screen.getByPlaceholderText("Descreva o ventriculo esquerdo");
    fireEvent.change(campoVe, { target: { value: `${textoImportante} Revisado.` } });
    fireEvent.blur(campoVe);

    expect(apiMocks.atualizarFrase).not.toHaveBeenCalled();
  });

  it("combina varias conclusoes aprovadas somente apos aplicacao explicita", async () => {
    const onChange = vi.fn();
    render(<EditorControlado onChange={onChange} />);

    fireEvent.click(await screen.findByRole("button", { name: /Combinar achados/i }));
    fireEvent.click(await screen.findByRole("button", { name: "1 frase(s) selecionada(s)" }));
    fireEvent.change(screen.getByLabelText("Buscar conclusão"), {
      target: { value: "Hipertensao pulmonar" },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: /Hipertensao pulmonar importante/i }),
    );

    expect(screen.getAllByText(conclusaoHp, { exact: false })).not.toHaveLength(0);
    expect((screen.getByPlaceholderText("Escreva a conclusao") as HTMLTextAreaElement).value).toBe(
      conclusaoDmvm,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Aplicar seleção manual de 2 frase\(s\)/i }),
    );

    await waitFor(() => {
      const campo = screen.getByPlaceholderText("Escreva a conclusao") as HTMLTextAreaElement;
      expect(campo.value).toContain(`* ${conclusaoDmvm}`);
      expect(campo.value).toContain(`* ${conclusaoHp}`);
    });
  });

  it("gera e atualiza o rascunho pelos achados sem sobrescrever a conclusao antes da revisao", async () => {
    const onChange = vi.fn();
    render(<EditorControlado onChange={onChange} />);

    fireEvent.click(await screen.findByRole("button", { name: /Combinar achados/i }));

    const rascunho = await screen.findByRole("textbox", {
      name: /Rascunho automático da conclusão/i,
    });
    await waitFor(() => {
      expect((rascunho as HTMLTextAreaElement).value).toBe(conclusaoDmvm);
    });
    expect((screen.getByPlaceholderText("Escreva a conclusao") as HTMLTextAreaElement).value).toBe(
      conclusaoDmvm,
    );

    fireEvent.click(await screen.findByRole("radio", { name: /Importante/i }));

    await waitFor(() => {
      expect((rascunho as HTMLTextAreaElement).value).toContain(
        "Ventriculo esquerdo: VE com sobrecarga volumétrica importante.",
      );
      expect((rascunho as HTMLTextAreaElement).value).not.toContain("moderada");
    });
    expect((screen.getByPlaceholderText("Escreva a conclusao") as HTMLTextAreaElement).value).toBe(
      conclusaoDmvm,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Aplicar rascunho revisado na conclusão/i }),
    );

    await waitFor(() => {
      expect((screen.getByPlaceholderText("Escreva a conclusao") as HTMLTextAreaElement).value).toBe(
        `${conclusaoDmvm}\n* Ventriculo esquerdo: VE com sobrecarga volumétrica importante.`,
      );
    });
  });

  it("inclui automaticamente a mitral alterada e omite a frase normal do preset", async () => {
    const onChange = vi.fn();
    render(<EditorControlado onChange={onChange} />);

    fireEvent.click(await screen.findByRole("button", { name: /Combinar achados/i }));
    const rascunho = await screen.findByRole("textbox", {
      name: /Rascunho automático da conclusão/i,
    });
    await waitFor(() => {
      expect((rascunho as HTMLTextAreaElement).value).toBe(conclusaoDmvm);
      expect((rascunho as HTMLTextAreaElement).value).not.toContain("Mitral normal");
    });

    fireEvent.change(screen.getByLabelText("Escolher frase para Valva mitral"), {
      target: { value: "3" },
    });

    await waitFor(() => {
      expect((rascunho as HTMLTextAreaElement).value).toBe(
        `${conclusaoDmvm}\n* Valva mitral: Espessamento mitral leve com refluxo leve.`,
      );
    });
    expect((screen.getByPlaceholderText("Escreva a conclusao") as HTMLTextAreaElement).value).toBe(
      conclusaoDmvm,
    );
  });

  it("preserva a revisao manual e bloqueia aplicacao quando os achados mudam", async () => {
    const onChange = vi.fn();
    render(<EditorControlado onChange={onChange} />);

    fireEvent.click(await screen.findByRole("button", { name: /Combinar achados/i }));
    const rascunho = await screen.findByRole("textbox", {
      name: /Rascunho automático da conclusão/i,
    });
    await waitFor(() => expect((rascunho as HTMLTextAreaElement).value).not.toBe(""));

    fireEvent.change(rascunho, { target: { value: "Conclusão revisada pelo médico." } });
    fireEvent.click(await screen.findByRole("radio", { name: /Importante/i }));

    expect(await screen.findByText(/Os achados mudaram depois da sua edição/i)).toBeInTheDocument();
    expect((rascunho as HTMLTextAreaElement).value).toBe("Conclusão revisada pelo médico.");
    expect(
      screen.getByRole("button", { name: /Aplicar rascunho revisado na conclusão/i }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /Atualizar pelos achados/i }));

    await waitFor(() => {
      expect((rascunho as HTMLTextAreaElement).value).toContain(
        "VE com sobrecarga volumétrica importante",
      );
    });
    expect(
      screen.getByRole("button", { name: /Aplicar rascunho revisado na conclusão/i }),
    ).toBeEnabled();
  });
});

describe("EcocardiogramaEstruturadoEditor - atualizar frase", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
    apiMocks.carregarBanco.mockResolvedValue(payload);
    window.localStorage.clear();
  });

  async function abrirEditor() {
    const onChange = vi.fn();
    render(<EditorControlado onChange={onChange} />);
    const campo = await screen.findByPlaceholderText("Descreva o ventriculo esquerdo");
    const bloco = within(campo.parentElement!);
    return { campo, bloco, onChange };
  }

  it.each(["preset", "compositor"])(
    "atualiza somente a frase selecionada no modo %s, sem criar duplicata ou mudar o laudo",
    async (modo) => {
      apiMocks.carregarBanco.mockResolvedValue({
        ...payload,
        aspectos: payload.aspectos.map((aspecto) => ({
          ...aspecto,
          frases: aspecto.frases.map((frase) => frase.id === 66
            ? { ...frase, patologias: ["Categoria de teste"], ordem: 4 }
            : frase),
        })),
      });
      apiMocks.atualizarFrase.mockResolvedValue({ id: 66 });
      const { campo, bloco, onChange } = await abrirEditor();
      if (modo === "compositor") {
        fireEvent.click(screen.getByRole("button", { name: /Combinar achados/i }));
      }
      const botao = bloco.getByRole("button", { name: "Atualizar frase" });
      expect(botao).toBeDisabled();
      const texto = "Texto revisado pelo veterinário.";
      fireEvent.change(campo, { target: { value: texto } });
      expect(apiMocks.atualizarFrase).not.toHaveBeenCalled();
      expect(botao).toBeEnabled();
      expect(bloco.getByText(/Atualizar frase também altera/)).toBeInTheDocument();
      onChange.mockClear();

      fireEvent.click(botao);

      await screen.findByText(/Frase de Ventriculo esquerdo atualizada no banco/);
      expect(apiMocks.atualizarFrase).toHaveBeenCalledExactlyOnceWith(66, {
        aspecto: "ventriculo_esquerdo",
        titulo: "VE com sobrecarga volumétrica moderada",
        texto,
        tags: ["moderado", "endocardiose", "cao", "B2"],
        patologias: ["Categoria de teste"],
        ordem: 4,
      });
      expect(apiMocks.criarFrase).not.toHaveBeenCalled();
      expect(apiMocks.salvarPreset).not.toHaveBeenCalled();
      expect(onChange).not.toHaveBeenCalled();
      expect(campo).toHaveValue(texto);
      expect(screen.getByPlaceholderText("Descreva a valva mitral")).toHaveValue(textoMitralNormal);
      expect(screen.getByPlaceholderText("Escreva a conclusao")).toHaveValue(conclusaoDmvm);
      expect(botao).toBeDisabled();
      expect(bloco.getByRole("button", { name: "Salvar como nova frase" })).toBeEnabled();
      if (modo === "preset") {
        fireEvent.change(campo, { target: { value: "Outra edição local." } });
        fireEvent.click(bloco.getByRole("button", { name: "Usar frase" }));
        expect(campo).toHaveValue(texto);
      } else {
        expect(within(screen.getByPlaceholderText("Escreva a conclusao").parentElement!)
          .queryByRole("button", { name: "Atualizar frase" })).not.toBeInTheDocument();
      }
    }
  );

  it("mantém a frase original selecionada quando a edição coincide com outra frase", async () => {
    apiMocks.atualizarFrase.mockResolvedValue({ id: 66 });
    const { campo, bloco } = await abrirEditor();
    fireEvent.change(campo, { target: { value: textoImportante } });
    expect(bloco.getByRole("combobox")).toHaveValue("66");
    fireEvent.click(bloco.getByRole("button", { name: "Atualizar frase" }));
    await waitFor(() => expect(apiMocks.atualizarFrase).toHaveBeenCalledWith(
      66, expect.objectContaining({ texto: textoImportante })
    ));
    await screen.findByText(/Frase de Ventriculo esquerdo atualizada no banco/);
  });

  it("mantém a opção de criar uma frase nova com o texto editado", async () => {
    const novaFrase = { id: 900, titulo: "Frase de teste", texto: "Texto revisado", tags: [], ativo: 1 };
    apiMocks.criarFrase.mockResolvedValue(novaFrase);
    apiMocks.carregarBanco.mockResolvedValueOnce(payload).mockResolvedValue({
      ...payload,
      aspectos: payload.aspectos.map((aspecto) => aspecto.key === "ventriculo_esquerdo"
        ? { ...aspecto, frases: [...aspecto.frases, novaFrase] }
        : aspecto),
    });
    const prompt = vi.spyOn(window, "prompt").mockReturnValueOnce("Frase de teste").mockReturnValueOnce("");
    try {
      const { campo, bloco } = await abrirEditor();
      fireEvent.change(campo, { target: { value: "Texto revisado" } });
      fireEvent.click(bloco.getByRole("button", { name: "Salvar como nova frase" }));
      await screen.findByText('Frase "Frase de teste" salva no banco em Ventriculo esquerdo.');
      expect(apiMocks.criarFrase).toHaveBeenCalledExactlyOnceWith({
        aspecto: "ventriculo_esquerdo", titulo: "Frase de teste", texto: "Texto revisado", tags: [],
      });
      expect(apiMocks.atualizarFrase).not.toHaveBeenCalled();
      expect(campo).toHaveValue("Texto revisado");
      expect(bloco.getByRole("combobox")).toHaveValue("900");
    } finally {
      prompt.mockRestore();
    }
  });

  it("bloqueia atualização com texto vazio ou sem alterações", async () => {
    const { campo, bloco } = await abrirEditor();
    const botao = bloco.getByRole("button", { name: "Atualizar frase" });
    expect(botao).toBeDisabled();
    fireEvent.change(campo, { target: { value: "   " } });
    expect(botao).toBeDisabled();
    expect(apiMocks.atualizarFrase).not.toHaveBeenCalled();
  });

  it("não oferece atualização quando o aspecto não tem frase ativa selecionada", async () => {
    apiMocks.carregarBanco.mockResolvedValue({
      ...payload,
      aspectos: payload.aspectos.map((aspecto) => ({
        ...aspecto,
        frases: aspecto.frases.map((frase) => ({ ...frase, ativo: 0 })),
      })),
    });
    const { campo, bloco } = await abrirEditor();
    fireEvent.change(campo, { target: { value: "Texto manual" } });
    expect(bloco.getByRole("button", { name: "Atualizar frase" })).toBeDisabled();
    expect(apiMocks.atualizarFrase).not.toHaveBeenCalled();
  });

  it("preserva texto e seleção após falha e permite tentar novamente", async () => {
    apiMocks.atualizarFrase.mockRejectedValueOnce({ response: { data: { detail: "Falha simulada" } } })
      .mockResolvedValueOnce({ id: 66 });
    const { campo, bloco } = await abrirEditor();
    fireEvent.change(campo, { target: { value: "Texto revisado" } });
    const botao = bloco.getByRole("button", { name: "Atualizar frase" });
    fireEvent.click(botao);
    await screen.findByText("Falha simulada");
    expect(screen.queryByText(/Frase de Ventriculo esquerdo atualizada no banco/)).not.toBeInTheDocument();
    expect(campo).toHaveValue("Texto revisado");
    expect(bloco.getByRole("combobox")).toHaveValue("66");
    expect(botao).toBeEnabled();
    fireEvent.click(botao);
    await screen.findByText(/Frase de Ventriculo esquerdo atualizada no banco/);
    expect(apiMocks.atualizarFrase).toHaveBeenCalledTimes(2);
    expect(botao).toBeDisabled();
  });

  it("bloqueia salvamentos concorrentes e preserva a edição feita durante a requisição", async () => {
    let resolver!: () => void;
    apiMocks.atualizarFrase.mockImplementation(() => new Promise<void>((resolve) => { resolver = resolve; }));
    const { campo, bloco } = await abrirEditor();
    fireEvent.change(campo, { target: { value: "Texto enviado" } });
    fireEvent.click(bloco.getByRole("button", { name: "Atualizar frase" }));
    expect(bloco.getByRole("button", { name: "Atualizando..." })).toBeDisabled();
    expect(bloco.getByRole("button", { name: "Salvar como nova frase" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Propagar frases para banco" })).toBeDisabled();
    fireEvent.change(campo, { target: { value: "Edição posterior" } });
    await act(async () => resolver());
    expect(campo).toHaveValue("Edição posterior");
    expect(bloco.getByRole("button", { name: "Atualizar frase" })).toBeEnabled();
    expect(apiMocks.atualizarFrase).toHaveBeenCalledExactlyOnceWith(
      66, expect.objectContaining({ texto: "Texto enviado" })
    );
    fireEvent.click(bloco.getByRole("button", { name: "Usar frase" }));
    expect(campo).toHaveValue("Texto enviado");
  });
});
