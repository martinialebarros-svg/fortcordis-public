import { describe, expect, it, vi } from "vitest";
import { loadCompleteBillingGroup, type BillingGroup } from "./cobrancas-loading";

const group: BillingGroup = { chave: "clinica:1", nome_destinatario: "Sintetica", tipo_destinatario: "clinica", quantidade_total: 101, quantidade_os: 101, total_pendente: 1010 };
const page = (skip: number) => ({ total: 101, items: Array.from({ length: skip === 0 ? 100 : 1 }, (_, i) => ({ id: skip + i + 1, status: "Pendente", valor_final: 10 })), resumo: { pendentes: 101, valor_pendente: 1010 } });
describe("complete billing recipient loading", () => {
  it("reads all batches before returning a complete recipient", async () => {
    const read = vi.fn(async (skip: number) => page(skip));
    expect(await loadCompleteBillingGroup(group, read, new AbortController().signal)).toHaveLength(101);
    expect(read.mock.calls.map(([skip]) => skip)).toEqual([0, 100]);
  });
  it("rejects a failed later batch instead of returning partial rows", async () => {
    await expect(loadCompleteBillingGroup(group, async (skip) => { if (skip) throw new Error("offline"); return page(skip); }, new AbortController().signal)).rejects.toThrow("offline");
  });
  it("rejects changes to totals", async () => {
    await expect(loadCompleteBillingGroup(group, async (skip) => ({ ...page(skip), total: 102 }), new AbortController().signal)).rejects.toThrow("mudaram");
  });
  it("rejects duplicate ids across pages", async () => {
    await expect(loadCompleteBillingGroup(group, async (skip) => ({ ...page(skip), items: skip ? page(0).items.slice(0, 1) : page(0).items }), new AbortController().signal)).rejects.toThrow("inconsistente");
  });
  it("rejects changed row values despite unchanged summaries", async () => {
    await expect(loadCompleteBillingGroup(group, async (skip) => ({ ...page(skip), items: page(skip).items.map((item) => ({ ...item, valor_final: 20 })) }), new AbortController().signal)).rejects.toThrow("valores");
  });
  it("suppresses completion after cancellation", async () => {
    const controller = new AbortController();
    await expect(loadCompleteBillingGroup(group, async (skip) => { controller.abort(); return page(skip); }, controller.signal)).rejects.toThrow("cancelado");
  });
  it("requires narrower filters for oversized recipients without reading", async () => {
    const read = vi.fn();
    await expect(loadCompleteBillingGroup({ ...group, quantidade_total: 10001 }, read, new AbortController().signal)).rejects.toThrow("Restrinja");
    expect(read).not.toHaveBeenCalled();
  });
});
