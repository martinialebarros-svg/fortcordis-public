// Only update the suggested payment while it still matches the previous amount due.
// Edited amounts and split payments always require an explicit adjustment.
export function ajustarPagamentoSugerido<T extends { valor: string }>(
  pagamentos: T[], valorAnterior: number, valorNovo: number, creditoUtilizado = 0
): T[] {
  const centavos = (valor: number) => Math.round(valor * 100);
  if (pagamentos.length !== 1 ||
      centavos(Number(pagamentos[0].valor.replace(",", "."))) !== centavos(Math.max(0, valorAnterior - creditoUtilizado))) {
    return pagamentos;
  }
  return [{ ...pagamentos[0], valor: Math.max(0, valorNovo - creditoUtilizado).toFixed(2) }];
}
