import { describe, expect, it, vi } from "vitest";
import { validateOrderSelection } from "./ordens-selection";

const order = { id: 1, status: "Pendente", valor_final: 10, destinatario_nome: "Sintetico" };
describe("validateOrderSelection", () => {
  it("accepts unchanged snapshots from more than one page", async () => {
    const orders = [order, { ...order, id: 101 }];
    const read = vi.fn(async (id: number) => orders.find((os) => os.id === id)!);
    await validateOrderSelection([1, 101], orders, "Pendente", read);
    expect(read).toHaveBeenCalledTimes(2);
  });
  it.each([{ status: "Pago" }, { valor_final: 11 }, { destinatario_nome: "Outro" }, { id: 2 }])("rejects changed record %j", async (change) => {
    await expect(validateOrderSelection([1], [order], "Pendente", async () => ({ ...order, ...change }))).rejects.toThrow(/mudou/);
  });
  it("fails closed on deletion or read failure", async () => {
    await expect(validateOrderSelection([1], [order], "Pendente", async () => { throw new Error("404"); })).rejects.toThrow("404");
  });
  it("does not silently discard missing or duplicate selections", async () => {
    const read = vi.fn();
    await expect(validateOrderSelection([2], [order], "Pendente", read)).rejects.toThrow();
    await expect(validateOrderSelection([1, 1], [order], "Pendente", read)).rejects.toThrow();
    expect(read).not.toHaveBeenCalled();
  });
  it("bounds concurrent reads to five", async () => {
    let active = 0, maximum = 0;
    const orders = Array.from({ length: 12 }, (_, id) => ({ ...order, id }));
    await validateOrderSelection(orders.map((os) => os.id), orders, "Pendente", async (id) => {
      active++; maximum = Math.max(maximum, active);
      await Promise.resolve(); active--;
      return orders[id];
    });
    expect(maximum).toBe(5);
  });
});
