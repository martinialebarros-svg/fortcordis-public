/**
 * Regras de alvo da receita no editor de prescricao.
 *
 * Um atendimento pode ter varias receitas: a do dia (sequencia 1), que viaja
 * no autosave do prontuario, e as complementares, emitidas em adendos depois
 * da alta, que tem endpoint proprio. Estas funcoes ficam fora da pagina por
 * serem a parte do fluxo que nao pode errar: apontar o editor para uma receita
 * e salvar em outra sobrescreveria um documento ja entregue ao tutor.
 */

export type ReceitaComSequencia = {
  id: number;
  sequencia: number;
  itens?: unknown[];
  [campo: string]: unknown;
};

/**
 * `true` quando o PUT do atendimento pode carregar `prescricao`.
 *
 * Com uma receita complementar aberta no editor, o campo sai do payload: o
 * backend so sincroniza a receita do dia por aquela rota.
 */
export const prescricaoEntraNoPayloadDoAtendimento = (
  form: { prescricao_alvo_id?: number | null } | null | undefined
): boolean => !form?.prescricao_alvo_id;

/**
 * Resolve qual receita alimenta o editor.
 *
 * Um alvo que sumiu do servidor volta para a receita do dia em vez de deixar
 * o formulario mostrando uma receita e salvando em outra.
 */
export const resolverPrescricaoDoForm = (
  detalhe: any,
  alvoId?: number | null
): { prescricao: any; alvoId: number | null } => {
  const lista: any[] = Array.isArray(detalhe?.prescricoes) ? detalhe.prescricoes : [];
  const alvo = alvoId ? lista.find((item) => Number(item?.id) === Number(alvoId)) : null;
  return {
    prescricao: alvo || detalhe?.prescricao || null,
    alvoId: alvo && Number(alvo.sequencia || 1) > 1 ? Number(alvo.id) : null,
  };
};

/**
 * Monta o snapshot que o autosave usa para decidir se ha algo a salvar.
 *
 * A receita entra sempre, inclusive quando sai do payload do atendimento por
 * haver uma complementar aberta no editor. Sao decisoes diferentes: o payload
 * diz o que vai para `PUT /atendimentos/{id}`; o snapshot diz se mudou
 * alguma coisa. Juntar as duas faz o autosave ficar cego a edicao da
 * complementar, que so seria gravada num salvamento manual.
 */
export const montarSnapshotDoAtendimento = (
  payloadAtendimento: Record<string, unknown>,
  form: { prescricao_alvo_id?: number | null } | null | undefined,
  prescricao: unknown
): string =>
  JSON.stringify({
    ...payloadAtendimento,
    _receita_alvo: form?.prescricao_alvo_id ?? null,
    _receita: prescricao,
  });
