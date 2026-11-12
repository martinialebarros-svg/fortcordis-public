import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TutorExistenteSelector from "./TutorExistenteSelector";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get } }));
const pessoa = (id: number, pet: string) => ({ id, nome: "Cristiane", telefone: `8590000000${id}`,
  origem_cadastro: `Clínica ${id}`, identificacao_pendente: true, pets: [{ id: id * 10, nome: pet }] });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("TutorExistenteSelector", () => {
  beforeEach(() => mocks.get.mockReset());

  it("não consulta nem seleciona nada sem busca deliberada", () => {
    const onSelect = vi.fn();
    render(<TutorExistenteSelector onSelect={onSelect} onCancel={vi.fn()} />);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("apresenta homônimos com contexto e só carrega o ID escolhido", async () => {
    const onSelect = vi.fn();
    mocks.get.mockResolvedValueOnce({ data: { items: [pessoa(1, "Lua"), pessoa(2, "Pingo")] } });
    render(<TutorExistenteSelector onSelect={onSelect} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Cristiane" } });
    expect(await screen.findByText("Animais: Lua #10")).toBeInTheDocument();
    expect(screen.getByText("Animais: Pingo #20")).toBeInTheDocument();
    expect(screen.getByText("Clínica 2")).toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
    const detail = { ...pessoa(2, "Pingo"), email: "cadastro@example.test" };
    mocks.get.mockResolvedValueOnce({ data: detail });
    fireEvent.click(screen.getByRole("button", { name: "Selecionar Cristiane #2" }));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(detail));
    expect(mocks.get).toHaveBeenLastCalledWith("/tutores/2");
  });

  it("descarta uma busca antiga que termina depois da busca atual", async () => {
    const old = deferred<{ data: { items: ReturnType<typeof pessoa>[] } }>();
    mocks.get.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ data: { items: [pessoa(2, "Pingo")] } });
    render(<TutorExistenteSelector onSelect={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "primeira" } });
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "segunda" } });
    expect(await screen.findByText("Animais: Pingo #20")).toBeInTheDocument();
    await act(async () => old.resolve({ data: { items: [pessoa(1, "Lua")] } }));
    expect(screen.queryByText("Animais: Lua #10")).not.toBeInTheDocument();
    expect(screen.getByText("Animais: Pingo #20")).toBeInTheDocument();
  });

  it("não aplica seleção atrasada depois que a pessoa muda a busca", async () => {
    const detail = deferred<{ data: ReturnType<typeof pessoa> }>();
    const onSelect = vi.fn();
    mocks.get.mockResolvedValueOnce({ data: { items: [pessoa(1, "Lua")] } }).mockReturnValueOnce(detail.promise)
      .mockResolvedValueOnce({ data: { items: [] } });
    render(<TutorExistenteSelector onSelect={onSelect} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Cristiane" } });
    fireEvent.click(await screen.findByRole("button", { name: "Selecionar Cristiane #1" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Outra" } });
    await act(async () => detail.resolve({ data: pessoa(1, "Lua") }));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("não seleciona cadastro que foi mesclado após a busca", async () => {
    const onSelect = vi.fn();
    mocks.get.mockResolvedValueOnce({ data: { items: [pessoa(1, "Lua")] } })
      .mockResolvedValueOnce({ data: { ...pessoa(1, "Lua"), mesclado_em_id: 2 } });
    render(<TutorExistenteSelector onSelect={onSelect} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Cristiane" } });
    fireEvent.click(await screen.findByRole("button", { name: "Selecionar Cristiane #1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cadastro não está mais disponível");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("cancelar invalida a seleção em andamento", async () => {
    const detail = deferred<{ data: ReturnType<typeof pessoa> }>();
    const onSelect = vi.fn();
    const onCancel = vi.fn();
    mocks.get.mockResolvedValueOnce({ data: { items: [pessoa(1, "Lua")] } }).mockReturnValueOnce(detail.promise);
    render(<TutorExistenteSelector onSelect={onSelect} onCancel={onCancel} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Cristiane" } });
    fireEvent.click(await screen.findByRole("button", { name: "Selecionar Cristiane #1" }));
    fireEvent.click(screen.getByRole("button", { name: "Fechar busca" }));
    await act(async () => detail.resolve({ data: pessoa(1, "Lua") }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
