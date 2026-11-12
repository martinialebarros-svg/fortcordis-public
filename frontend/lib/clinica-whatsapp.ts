import { formatarTelefoneVisual } from "@/lib/atendimento-cadastro";

const somenteDigitos = (valor?: string | null): string =>
  String(valor || "").replace(/\D/g, "").replace(/^0+/, "");

export const formatarWhatsAppVisual = (valor?: string | null): string => {
  const digitos = somenteDigitos(valor);
  const nacional = digitos.startsWith("55") && (digitos.length === 12 || digitos.length === 13)
    ? digitos.slice(2)
    : digitos;
  return formatarTelefoneVisual(nacional);
};

export const normalizarWhatsappsParaApi = (valores?: Array<string | null> | null): string[] => {
  const resultado: string[] = [];
  for (const valor of valores || []) {
    const digitos = somenteDigitos(valor);
    if (digitos && !resultado.includes(digitos)) {
      resultado.push(digitos);
    }
  }
  return resultado.slice(0, 10);
};

export const prepararWhatsappsFormulario = (
  valores?: Array<string | null> | null,
  telefoneLegado?: string | null,
): string[] => {
  const disponiveis = normalizarWhatsappsParaApi(valores);
  if (disponiveis.length === 0) {
    const legado = somenteDigitos(telefoneLegado);
    if (legado) disponiveis.push(legado);
  }
  const formatados = disponiveis.map(formatarWhatsAppVisual).filter(Boolean);
  return formatados.length > 0 ? formatados : [""];
};

export const obterWhatsappsClinica = (
  valores?: Array<string | null> | null,
  telefoneLegado?: string | null,
): string[] => {
  const disponiveis = normalizarWhatsappsParaApi(valores);
  if (disponiveis.length === 0) {
    const legado = somenteDigitos(telefoneLegado);
    if (legado) disponiveis.push(legado);
  }
  return disponiveis;
};
