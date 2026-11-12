import type { AtendimentoForm, ExameSolicitacao, PrescricaoItem } from "@/app/atendimento/page";

/** Recupera texto ainda nao sincronizado sem reabrir um encontro concluido ou
 * reatribuir o prontuario a outro paciente/agendamento por um backup antigo. */
export const restorePersistedAtendimentoDraft = (
  persisted: AtendimentoForm,
  backup: Partial<AtendimentoForm>
): AtendimentoForm => {
  if (
    (backup.id != null && backup.id !== persisted.id) ||
    (backup.paciente_id && backup.paciente_id !== persisted.paciente_id)
  ) return persisted;

  return {
    ...persisted,
    ...backup,
    id: persisted.id,
    paciente_id: persisted.paciente_id,
    agendamento_id: persisted.agendamento_id,
    especie: persisted.especie,
    evolucoes: persisted.evolucoes,
    anexos: persisted.anexos,
    documentos: persisted.documentos,
    ...(persisted.status === "Concluido" ? {
      status: persisted.status,
      clinica_id: persisted.clinica_id,
      data_atendimento: persisted.data_atendimento,
      triagem_concluida: persisted.triagem_concluida,
      consulta_concluida: persisted.consulta_concluida,
    } : {}),
  };
};

export const buildExamMergeKey = (item: ExameSolicitacao) =>
  [
    item.catalogo_exame_id || "",
    (item.tipo_exame || "").trim().toLowerCase(),
    item.painel_exame_id || "",
    item.prioridade || "",
    item.status || "",
    (item.resultado || "").trim().toLowerCase(),
    item.data_resultado || "",
    Number(item.valor || 0),
    (item.observacoes || "").trim().toLowerCase(),
  ].join("|");

/**
 * Mantem a mesma chave React antes e depois do primeiro autosave. Todo exame
 * hidratado ou criado na tela recebe `_localId`; o `id` do banco e apenas o
 * fallback para dados legados sem identificador local.
 */
export const getExamStateKey = (
  item: Pick<ExameSolicitacao, "id" | "_localId">
): string => item._localId || (item.id != null ? String(item.id) : "sem-id");

/**
 * Limpar o nome de uma solicitacao manual ja persistida equivale a remove-la
 * somente quando o card nao carrega nenhum outro conteudo clinico ou vinculo.
 * Itens com catalogo, painel, resultado, observacao, preparo ou anexo continuam
 * dependendo do botao de exclusao e das protecoes do backend.
 */
export const isClearedPersistedExamEligibleForRemoval = (
  item: ExameSolicitacao
): boolean =>
  item.id != null &&
  !(item.tipo_exame || "").trim() &&
  !item.catalogo_exame_id &&
  !item.painel_exame_id &&
  !(item.observacoes || "").trim() &&
  !(item.resultado || "").trim() &&
  !(item.preparo || "").trim() &&
  (item.anexos_resultado || []).length === 0;

const isSameExamRequest = (left: ExameSolicitacao, right: ExameSolicitacao) => {
  const leftCatalogId = Number(left.catalogo_exame_id || 0);
  const rightCatalogId = Number(right.catalogo_exame_id || 0);
  if (leftCatalogId > 0 && rightCatalogId > 0) {
    return leftCatalogId === rightCatalogId;
  }
  return buildExamMergeKey(left) === buildExamMergeKey(right);
};

/**
 * Reconcilia a identidade de um exame criado pelo primeiro save com a mesma
 * linha local, mesmo que o usuario tenha continuado a digitar durante o
 * round-trip. Tambem conserva a intencao de exclusao quando a linha e removida
 * ou esvaziada nesse intervalo. Sem este ajuste, o texto antigo fica orfao no
 * banco e o texto novo e inserido como uma segunda solicitacao.
 */
export const reconcileExamsDuringSave = (
  currentExams: ExameSolicitacao[],
  sentExams: ExameSolicitacao[],
  persistedExams: ExameSolicitacao[],
  sentDestroyIds: ReadonlySet<number>
): ExameSolicitacao[] => {
  const next = currentExams.flatMap((item) => {
    if (item.id == null || !sentDestroyIds.has(item.id)) return [item];
    // A exclusao confirmada sai do estado mesmo quando `_destroy` foi derivado
    // do campo manual esvaziado no payload (e nao gravado no form). Se o
    // usuario voltou a digitar enquanto o DELETE logico estava em voo, conserva
    // o card como nova solicitacao sem reaproveitar o id que o servidor apagou.
    if (item._destroy || !(item.tipo_exame || "").trim()) return [];
    return [
      {
        ...item,
        id: undefined,
        _destroy: false,
        data_solicitacao: "",
      },
    ];
  });
  const idsAlreadySent = new Set(
    sentExams
      .map((item) => item.id)
      .filter((id): id is number => id != null)
  );
  // Registros que ja tinham id antes desta requisicao nao podem ser usados
  // para identificar um item novo com o mesmo nome (repeticoes manuais sao
  // validas). Restam no pool apenas os registros criados por este save.
  const persistedPool = persistedExams.filter(
    (item) => item.id == null || !idsAlreadySent.has(item.id)
  );

  sentExams.forEach((sentExam) => {
    if (sentExam.id != null || !sentExam._localId || !(sentExam.tipo_exame || "").trim()) return;

    const persistedIndex = persistedPool.findIndex((item) => isSameExamRequest(item, sentExam));
    if (persistedIndex < 0) return;

    const persistedExam = persistedPool.splice(persistedIndex, 1)[0];
    if (persistedExam.id == null || next.some((item) => item.id === persistedExam.id)) return;

    const currentIndex = next.findIndex((item) => item._localId === sentExam._localId);
    if (currentIndex >= 0) {
      const currentExam = next[currentIndex];
      next[currentIndex] = {
        ...currentExam,
        id: persistedExam.id,
        // Se o usuario apagou o texto enquanto o primeiro save estava em voo,
        // o proximo autosave deve excluir o registro parcial que acabou de ser
        // criado, em vez de deixa-lo invisivel e presente no PDF.
        _destroy: !(currentExam.tipo_exame || "").trim() || currentExam._destroy,
      };
      return;
    }

    const requestStillExists = next.some(
      (item) => !item._destroy && isSameExamRequest(item, sentExam)
    );
    if (requestStillExists) return;

    next.push({
      ...persistedExam,
      _destroy: true,
      _localId: sentExam._localId,
    });
  });

  return next;
};

const buildPrescriptionMergeKey = (item: PrescricaoItem) =>
  [
    item.medicamento_id || "",
    (item.medicamento_nome || "").trim().toLowerCase(),
    (item.apresentacao_selecionada || "").trim().toLowerCase(),
    (item.dose || "").trim().toLowerCase(),
    (item.frequencia || "").trim().toLowerCase(),
    (item.duracao || "").trim().toLowerCase(),
    (item.via || "").trim().toLowerCase(),
  ].join("|");

const mergeAutoSavedItems = <T extends { id?: number | null }>(
  currentItems: T[],
  persistedItems: T[],
  getMergeKey: (item: T) => string,
  applyPersisted: (currentItem: T, persistedItem: T) => T
) => {
  const pool = [...persistedItems];
  return currentItems.map((currentItem) => {
    if (currentItem.id) {
      const byIdIndex = pool.findIndex((persistedItem) => persistedItem.id === currentItem.id);
      if (byIdIndex >= 0) {
        return applyPersisted(currentItem, pool.splice(byIdIndex, 1)[0]);
      }
    }

    const mergeKey = getMergeKey(currentItem);
    if (!mergeKey) return currentItem;

    const bySignatureIndex = pool.findIndex((persistedItem) => getMergeKey(persistedItem) === mergeKey);
    if (bySignatureIndex >= 0) {
      return applyPersisted(currentItem, pool.splice(bySignatureIndex, 1)[0]);
    }

    return currentItem;
  });
};

export const mergeAutoSavedFormState = (current: AtendimentoForm, persisted: AtendimentoForm): AtendimentoForm => ({
  ...current,
  id: persisted.id || current.id,
  ...(persisted.status === "Concluido" ? {
    status: persisted.status,
    paciente_id: persisted.paciente_id,
    agendamento_id: persisted.agendamento_id,
    consulta_concluida: persisted.consulta_concluida,
  } : {}),
  exames: mergeAutoSavedItems(
    current.exames,
    persisted.exames,
    buildExamMergeKey,
    (currentItem, persistedItem) => ({
      ...currentItem,
      id: currentItem.id ?? persistedItem.id,
      laudo_id: currentItem.laudo_id ?? persistedItem.laudo_id ?? null,
      data_solicitacao: currentItem.data_solicitacao || persistedItem.data_solicitacao || "",
      data_resultado: currentItem.data_resultado || persistedItem.data_resultado || "",
      resultado: currentItem.resultado || persistedItem.resultado || "",
      valor_referencia: currentItem.valor_referencia || persistedItem.valor_referencia || "",
      unidade: currentItem.unidade || persistedItem.unidade || "",
      anexos_resultado: persistedItem.anexos_resultado || currentItem.anexos_resultado || [],
    })
  ),
  prescricao_itens: mergeAutoSavedItems(
    current.prescricao_itens,
    persisted.prescricao_itens,
    buildPrescriptionMergeKey,
    (currentItem, persistedItem) => ({
      ...currentItem,
      id: currentItem.id ?? persistedItem.id,
      medicamento_nome: currentItem.medicamento_nome || persistedItem.medicamento_nome,
      apresentacao_selecionada: currentItem.apresentacao_selecionada || persistedItem.apresentacao_selecionada || "",
      historico_ajustes: persistedItem.historico_ajustes || currentItem.historico_ajustes,
    })
  ),
});

/**
 * Merge da resposta do POST /finalizar. Difere do save comum em um ponto: o
 * `status` passa a ser do servidor, porque e esta chamada que move o
 * atendimento para "Concluido". Mantendo o valor local, todo autosave seguinte
 * reenviaria o status antigo e o backend recusaria com "nao pode ser reaberto
 * isoladamente", travando o prontuario ate recarregar a pagina.
 */
export const mergeAtendimentoFinalizado = (
  current: AtendimentoForm,
  persisted: AtendimentoForm
): AtendimentoForm => {
  const merged = mergeAutoSavedFormState(current, persisted);
  return { ...merged, status: persisted.status || merged.status };
};
