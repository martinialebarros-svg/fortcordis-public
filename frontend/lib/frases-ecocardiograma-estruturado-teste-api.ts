import api from "@/lib/axios";
import type { PayloadEcoEstruturadoTeste } from "@/lib/ecocardiograma-estruturado-teste";

export const FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT =
  "/frases-ecocardiograma-estruturado-teste";

export async function carregarBancoEcoEstruturadoTeste(): Promise<PayloadEcoEstruturadoTeste> {
  const response = await api.get(FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT);
  return response.data;
}

export async function aplicarPresetEcoEstruturadoTeste(presetId: number | string) {
  const response = await api.post(
    `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/presets/${presetId}/aplicar`
  );
  return response.data;
}

export async function salvarPresetEcoEstruturadoTeste(
  payload: Record<string, unknown>,
  presetId?: number
) {
  if (presetId) {
    const response = await api.put(
      `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/presets/${presetId}`,
      payload
    );
    return response.data;
  }

  const response = await api.post(`${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/presets`, payload);
  return response.data;
}

export async function excluirPresetEcoEstruturadoTeste(presetId: number) {
  const response = await api.delete(
    `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/presets/${presetId}`
  );
  return response.data;
}

export async function restaurarPresetEcoEstruturadoTeste(presetId: number) {
  const response = await api.post(
    `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/presets/${presetId}/restaurar`
  );
  return response.data;
}

export async function duplicarPresetEcoEstruturadoTeste(
  presetId: number,
  payload: Record<string, unknown>
) {
  const response = await api.post(
    `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/presets/${presetId}/duplicar`,
    payload
  );
  return response.data;
}

export async function criarFraseEcoEstruturadoTeste(payload: Record<string, unknown>) {
  const response = await api.post(`${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/frases`, payload);
  return response.data;
}

export async function atualizarFraseEcoEstruturadoTeste(
  fraseId: number,
  payload: Record<string, unknown>
) {
  const response = await api.put(
    `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/frases/${fraseId}`,
    payload
  );
  return response.data;
}

export async function excluirFraseEcoEstruturadoTeste(
  fraseId: number,
  payload: Record<string, unknown>
) {
  const response = await api.delete(
    `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/frases/${fraseId}`,
    { data: payload }
  );
  return response.data;
}

export async function restaurarFraseEcoEstruturadoTeste(
  fraseId: number,
  payload: Record<string, unknown>
) {
  const response = await api.post(
    `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/frases/${fraseId}/restaurar`,
    payload
  );
  return response.data;
}

export async function duplicarFraseEcoEstruturadoTeste(
  fraseId: number,
  payload: Record<string, unknown>
) {
  const response = await api.post(
    `${FRASES_ECO_ESTRUTURADO_TESTE_ENDPOINT}/frases/${fraseId}/duplicar`,
    payload
  );
  return response.data;
}
