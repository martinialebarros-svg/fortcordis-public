import { useState, type ComponentProps } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ImageUploader from "./ImageUploader";

const mocks = vi.hoisted(() => ({
  put: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/lib/axios", () => ({ default: mocks }));

const initialImages = [
  {
    id: "local-a",
    nome: "a.jpg",
    descricao: "",
    ordem: 0,
    dataUrl: "data:image/jpeg;base64,a",
    tamanho: 100,
    tempId: 10,
    uploaded: true,
    incluirNoPdf: true,
  },
  {
    id: "local-b",
    nome: "b.jpg",
    descricao: "",
    ordem: 1,
    dataUrl: "data:image/jpeg;base64,b",
    tamanho: 200,
    tempId: 11,
    uploaded: true,
    incluirNoPdf: true,
  },
];

describe("ImageUploader", () => {
  beforeEach(() => {
    mocks.put.mockReset();
    mocks.post.mockReset();
    mocks.delete.mockReset();
    mocks.put.mockResolvedValue({ data: {} });
    mocks.post.mockResolvedValue({ data: { success: true, imagem_id: 31 } });
  });

  it("persiste seleção para o PDF e reordenação por arrastar", async () => {
    render(
      <ImageUploader
        sessionId="sessao-1"
        imagensIniciais={initialImages}
      />
    );

    const checkboxes = screen.getAllByRole("checkbox", { name: "Incluir no PDF" });
    fireEvent.click(checkboxes[0]);

    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith(
      "/imagens/temp/session/sessao-1/configuracao",
      {
        imagens: [
          { id: 10, ordem: 0, incluir_no_pdf: false, descricao: "" },
          { id: 11, ordem: 1, incluir_no_pdf: true, descricao: "" },
        ],
      },
    ));

    const firstCard = screen.getByLabelText("Ampliar a.jpg").closest('[draggable="true"]');
    const secondCard = screen.getByLabelText("Ampliar b.jpg").closest('[draggable="true"]');
    expect(firstCard).not.toBeNull();
    expect(secondCard).not.toBeNull();
    const dataTransfer = { effectAllowed: "move", dropEffect: "move" };
    fireEvent.dragStart(firstCard!, { dataTransfer });
    fireEvent.dragOver(secondCard!, { dataTransfer });
    fireEvent.drop(secondCard!, { dataTransfer });

    await waitFor(() => expect(mocks.put).toHaveBeenLastCalledWith(
      "/imagens/temp/session/sessao-1/configuracao",
      {
        imagens: [
          { id: 11, ordem: 0, incluir_no_pdf: true, descricao: "" },
          { id: 10, ordem: 1, incluir_no_pdf: false, descricao: "" },
        ],
      },
    ));
  });

  it("usa a sessão pronta no primeiro upload e habilita os controles antes de salvar o laudo", async () => {
    const onImagensChange = vi.fn();
    const { container, rerender } = render(
      <ImageUploader
        sessionId=""
        imagensIniciais={[]}
        onImagensChange={onImagensChange}
      />
    );

    const inputInicial = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(inputInicial.disabled).toBe(true);

    rerender(
      <ImageUploader
        sessionId="sessao-primeiro-laudo"
        imagensIniciais={[]}
        onImagensChange={onImagensChange}
      />
    );

    const arquivo = new File(["imagem"], "primeiro.jpg", { type: "image/jpeg" });
    const inputPronto = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(inputPronto, { target: { files: [arquivo] } });

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const formData = mocks.post.mock.calls[0][1] as FormData;
    expect(formData.get("session_id")).toBe("sessao-primeiro-laudo");

    const checkbox = await screen.findByRole("checkbox", { name: "Incluir no PDF" });
    await waitFor(() => expect(checkbox).toBeEnabled());
    fireEvent.click(checkbox);

    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith(
      "/imagens/temp/session/sessao-primeiro-laudo/configuracao",
      {
        imagens: [{ id: 31, ordem: 0, incluir_no_pdf: false, descricao: "" }],
      },
    ));

    const controles = screen.getByTitle("Mover para baixo").parentElement;
    expect(controles).toHaveClass("bottom-2", "right-2");
    expect(controles).not.toHaveClass("inset-0");

    fireEvent.click(screen.getByRole("button", { name: "Ampliar primeiro.jpg" }));
    expect(screen.getByRole("dialog", { name: "Visualização ampliada de primeiro.jpg" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aumentar zoom" })).toBeEnabled();
  });

  it("envia todo o lote mesmo quando limpar o input esvazia seu FileList vivo", async () => {
    const onImagensChange = vi.fn();
    const onUploadStateChange = vi.fn();
    const { container } = render(
      <ImageUploader sessionId="sessao-lote" imagensIniciais={[]} onImagensChange={onImagensChange} onUploadStateChange={onUploadStateChange} />
    );
    mocks.post
      .mockResolvedValueOnce({ data: { success: true, imagem_id: 31 } })
      .mockResolvedValueOnce({ data: { success: true, imagem_id: 32 } });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    let selecionados = [
      new File(["imagem 1"], "qa-echo-1.png", { type: "image/png" }),
      new File(["imagem 2"], "qa-echo-2.png", { type: "image/png" }),
    ];
    // Browsers invalidate this live collection synchronously when value is cleared.
    // A plain files: [file1, file2] fixture would conceal that behavior in jsdom.
    const liveFiles = {
      get length() { return selecionados.length; },
      get 0() { return selecionados[0]; },
      get 1() { return selecionados[1]; },
      item(index: number) { return selecionados[index] ?? null; },
      [Symbol.iterator]() { return selecionados[Symbol.iterator](); },
    };
    let selectionValue = "C:\\fakepath\\qa-echo-1.png";
    Object.defineProperties(input, {
      files: { configurable: true, get: () => liveFiles },
      value: {
        configurable: true,
        get: () => selectionValue,
        set: (value: string) => {
          selectionValue = value;
          if (value === "") selecionados = [];
        },
      },
    });

    fireEvent.change(input);

    expect(input.value).toBe("");
    expect(liveFiles).toHaveLength(0);
    expect(onUploadStateChange).toHaveBeenCalledWith(true);
    await waitFor(() => expect(input).toBeEnabled());
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(onUploadStateChange.mock.calls.map(([active]) => active)).toEqual([true, false]);
    expect(mocks.post.mock.calls.map(([, formData]) => (formData.get("arquivo") as File).name))
      .toEqual(["qa-echo-1.png", "qa-echo-2.png"]);
    expect(mocks.post.mock.calls.map(([, formData]) => formData.get("ordem"))).toEqual(["0", "1"]);
    expect(screen.getByText("Imagens (2)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ampliar qa-echo-2.png" })).toBeInTheDocument();
    expect(onImagensChange.mock.lastCall?.[0]).toMatchObject([
      { nome: "qa-echo-1.png", uploaded: true, tempId: 31, ordem: 0 },
      { nome: "qa-echo-2.png", uploaded: true, tempId: 32, ordem: 1 },
    ]);
  });

  it("salva uma legenda opcional sem exigir campo adicional no upload", async () => {
    const onImagensChange = vi.fn();
    render(<ImageUploader sessionId="sessao-1" imagensIniciais={initialImages} onImagensChange={onImagensChange} />);

    const input = screen.getByRole("textbox", { name: "Legenda da imagem 1" });
    fireEvent.change(input, { target: { value: "Doppler da insuficiência tricúspide" } });
    fireEvent.blur(input);

    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith(
      "/imagens/temp/session/sessao-1/configuracao",
      {
        imagens: [
          { id: 10, ordem: 0, incluir_no_pdf: true, descricao: "Doppler da insuficiência tricúspide" },
          { id: 11, ordem: 1, incluir_no_pdf: true, descricao: "" },
        ],
      },
    ));
    expect(onImagensChange).toHaveBeenCalled();
  });

  it("preserva a legenda digitada enquanto outro upload termina", async () => {
    const concluirUploads: Array<(resultado: { data: { success: boolean; imagem_id: number } }) => void> = [];
    mocks.post.mockImplementation(() => new Promise((resolve) => concluirUploads.push(resolve)));
    const onImagensChange = vi.fn();
    const Parent = () => {
      const [imagens, setImagens] = useState<NonNullable<ComponentProps<typeof ImageUploader>["imagensIniciais"]>>([]);
      return (
        <ImageUploader
          sessionId="sessao-1"
          imagensIniciais={imagens}
          onImagensChange={(atualizadas) => {
            onImagensChange(atualizadas);
            setImagens(atualizadas);
          }}
        />
      );
    };
    const { container } = render(<Parent />);

    const inputArquivo = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(inputArquivo, {
      target: {
        files: [
          new File(["imagem a"], "a.jpg", { type: "image/jpeg" }),
          new File(["imagem b"], "b.jpg", { type: "image/jpeg" }),
        ],
      },
    });

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    concluirUploads[0]({ data: { success: true, imagem_id: 31 } });
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));

    const legenda = screen.getByRole("textbox", { name: "Legenda da imagem 1" });
    fireEvent.change(legenda, { target: { value: "Doppler da IT" } });
    concluirUploads[1]({ data: { success: true, imagem_id: 32 } });

    await waitFor(() => expect(screen.getAllByRole("checkbox", { name: "Incluir no PDF" })[1]).toBeEnabled());
    expect(legenda).toHaveValue("Doppler da IT");
    expect(onImagensChange.mock.lastCall?.[0][0]).toMatchObject({
      descricao: "Doppler da IT",
      tempId: 31,
    });

    fireEvent.blur(legenda);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith(
      "/imagens/temp/session/sessao-1/configuracao",
      {
        imagens: [
          { id: 31, ordem: 0, incluir_no_pdf: true, descricao: "Doppler da IT" },
          { id: 32, ordem: 1, incluir_no_pdf: true, descricao: "" },
        ],
      },
    ));
  });
});
