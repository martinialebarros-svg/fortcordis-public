export interface EstadoSalvamentoEcocardiograma {
  analiseQualitativaAplicada: boolean;
  imagensCarregadas: boolean;
}

export function criarMensagemAlertaSalvamentoEcocardiograma({
  analiseQualitativaAplicada,
  imagensCarregadas,
}: EstadoSalvamentoEcocardiograma): string | null {
  const pendencias: string[] = [];

  if (!analiseQualitativaAplicada) {
    pendencias.push("a análise qualitativa ainda não foi aplicada ao laudo");
  }
  if (!imagensCarregadas) {
    pendencias.push("nenhuma imagem do exame foi carregada");
  }

  if (pendencias.length === 0) {
    return null;
  }

  const listaPendencias =
    pendencias.length === 1
      ? pendencias[0]
      : `${pendencias[0]} e ${pendencias[1]}`;

  return [
    "Atenção antes de salvar o ecocardiograma:",
    "",
    `${listaPendencias}.`,
    "",
    "Deseja salvar mesmo assim?",
  ].join("\n");
}
