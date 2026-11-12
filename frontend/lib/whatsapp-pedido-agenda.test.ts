import { describe, expect, it } from "vitest";
import { divergenciasPedido, camposPedidoAgenda, type PedidoAgenda } from "./whatsapp-pedido-agenda";
const pedido: PedidoAgenda = { pedido_id: 12, versao: 3, clinica_id: 9, resumo: "Preferência: amanhã às 10h", paciente: {id:1,nome:"Rex",tutor_id:2,tutor:"Maria"}, tutor:{id:2,nome:"Maria"},servico_id:3,avisos:[] };
describe("pedido para agenda", () => {
  it("preserva ids identificados e deixa horario para escolha humana", () => {
    const fields=camposPedidoAgenda(pedido);
    expect(fields).toMatchObject({paciente_id:"1",tutor_id:"2",clinica_id:"9",servico_id:"3",hora:""});
    expect(fields.observacoes).toContain("amanhã às 10h");
    expect(fields).not.toHaveProperty("data");
  });
  it("não inventa identificadores para dados ambíguos", () => {
    expect(camposPedidoAgenda({...pedido,paciente:null,tutor:null,servico_id:null})).toMatchObject({paciente_id:"",tutor_id:"",servico_id:""});
  });
});

it("destaca troca de identidade e tolera apenas formatação equivalente", () => {
  const original = {...pedido, dados_coletados: {paciente: "Galhofa", tutor: "Ricardo"}};
  expect(divergenciasPedido(original, "Pet teste", "Tutor teste")).toHaveLength(2);
  expect(divergenciasPedido(original, " GALHOFA ", "Ricárdo")).toEqual([]);
  expect(divergenciasPedido(original, "", "")).toEqual([]);
});
