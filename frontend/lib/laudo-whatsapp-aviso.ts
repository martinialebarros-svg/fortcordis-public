/**
 * Aviso de laudo disponivel pelo WhatsApp oficial.
 *
 * O mesmo clique avisa todos os destinos externos do laudo que ja estao
 * liberados no portal - a clinica parceira e o veterinario parceiro. Estas
 * funcoes decidem quem entra no aviso e como o resultado e descrito; as duas
 * telas de laudos (lista e visualizacao) compartilham a mesma regra.
 */
export const PORTAL_RELEASE_STATUS = "Liberado no portal";

export type DestinoAvisoWhatsApp = "clinica" | "veterinario_parceiro";

export interface DestinoVeterinarioLaudo {
  partner_id: number;
  nome?: string | null;
  origem?: string | null;
  liberado?: boolean;
}

export interface LaudoAvisoWhatsApp {
  status?: string;
  clinica?: string | null;
  clinic_id?: number | null;
  portal_clinica_liberado?: boolean;
  veterinario_parceiro_id?: number | null;
  veterinario_parceiro_nome?: string | null;
  portal_veterinario_liberado?: boolean;
  /**
   * Todos os veterinarios que recebem este laudo: o nomeado e os que entram
   * por vinculo de clinica com difusao ligada. E daqui que sai o nome de quem
   * vai ser avisado — o `veterinario_parceiro_id` sozinho nao ve os de vinculo.
   */
  portal_veterinarios_destinos?: DestinoVeterinarioLaudo[];
  /** Ultimo envio por destino; e daqui que o seletor sabe quem ja recebeu. */
  whatsapp_envios?: Record<string, EnvioDestinoWhatsApp> | null;
  whatsapp_liberacao_status?: "enviado" | "falhou" | null;
  whatsapp_liberacao_em?: string | null;
  whatsapp_liberacao_erro?: string | null;
  whatsapp_parceiro_status?: "enviado" | "falhou" | null;
  whatsapp_parceiro_em?: string | null;
  whatsapp_parceiro_erro?: string | null;
}

export interface ResumoDestinoAvisoWhatsApp {
  status?: "enviado" | "falhou" | "ignorado";
  motivo?: string | null;
  erro?: string | null;
}

/** Ultimo envio registrado para um destino, como o backend guarda em `whatsapp_envios`. */
export interface EnvioDestinoWhatsApp {
  status?: "enviado" | "falhou" | null;
  em?: string | null;
  erro?: string | null;
}

export interface DestinoSelecionavelWhatsApp {
  /** Chave que o backend entende: "clinica" ou "veterinario:<id>". */
  id: string;
  tipo: "clinica" | "veterinario";
  nome: string;
  ultimoEnvio: EnvioDestinoWhatsApp | null;
}

export interface ResumoVeterinarioAvisoWhatsApp extends ResumoDestinoAvisoWhatsApp {
  partner_id?: number;
  nome?: string | null;
  origem?: string | null;
}

export interface RespostaAvisoWhatsApp {
  message?: string;
  clinica?: ResumoDestinoAvisoWhatsApp;
  veterinario_parceiro?: ResumoDestinoAvisoWhatsApp;
  /** Um por veterinario destinatario; o `veterinario_parceiro` acima e so o nomeado. */
  veterinarios_parceiros?: ResumoVeterinarioAvisoWhatsApp[];
  whatsapp_envios?: Record<string, EnvioDestinoWhatsApp> | null;
  whatsapp_liberacao_status?: "enviado" | "falhou" | null;
  whatsapp_liberacao_em?: string | null;
  whatsapp_liberacao_erro?: string | null;
  whatsapp_parceiro_status?: "enviado" | "falhou" | null;
  whatsapp_parceiro_em?: string | null;
  whatsapp_parceiro_erro?: string | null;
}

export function getVeterinariosLiberados(laudo: LaudoAvisoWhatsApp): DestinoVeterinarioLaudo[] {
  const destinos = laudo.portal_veterinarios_destinos;
  if (Array.isArray(destinos)) {
    return destinos.filter((item) => item?.liberado);
  }
  // Contrato antigo, de antes da difusao por vinculo: so o nomeado.
  if (laudo.veterinario_parceiro_id && laudo.portal_veterinario_liberado) {
    return [{ partner_id: laudo.veterinario_parceiro_id, nome: laudo.veterinario_parceiro_nome }];
  }
  return [];
}

export function getDestinosAvisoWhatsApp(laudo: LaudoAvisoWhatsApp): DestinoAvisoWhatsApp[] {
  const destinos: DestinoAvisoWhatsApp[] = [];
  if (laudo.clinic_id && (laudo.portal_clinica_liberado || laudo.status === PORTAL_RELEASE_STATUS)) {
    destinos.push("clinica");
  }
  if (getVeterinariosLiberados(laudo).length > 0) {
    destinos.push("veterinario_parceiro");
  }
  return destinos;
}

export function podeAvisarWhatsApp(laudo: LaudoAvisoWhatsApp): boolean {
  return getDestinosAvisoWhatsApp(laudo).length > 0;
}

function nomeClinica(laudo: LaudoAvisoWhatsApp): string {
  return laudo.clinica?.trim() || "a clínica parceira";
}

function nomeParceiro(laudo: LaudoAvisoWhatsApp): string {
  const liberados = getVeterinariosLiberados(laudo);
  const nomes = liberados.map((item) => item.nome?.trim()).filter((nome): nome is string => Boolean(nome));

  if (nomes.length === 0) {
    return liberados.length > 1 ? "os veterinários parceiros" : "o veterinário parceiro";
  }
  if (nomes.length === 1) {
    return nomes[0];
  }
  // Nomear todo mundo: quem confirma o envio precisa saber quem vai receber.
  return `${nomes.slice(0, -1).join(", ")} e ${nomes[nomes.length - 1]}`;
}

export function getConfirmacaoAvisoWhatsApp(laudo: LaudoAvisoWhatsApp): string {
  const destinos = getDestinosAvisoWhatsApp(laudo);
  if (destinos.length === 2) {
    return `Enviar para ${nomeClinica(laudo)} e ${nomeParceiro(laudo)} o aviso de laudo disponível?`;
  }
  if (destinos.includes("veterinario_parceiro")) {
    return `Enviar para ${nomeParceiro(laudo)} o aviso de laudo disponível?`;
  }
  return `Enviar para ${nomeClinica(laudo)} o aviso de laudo disponível?`;
}

export function getTituloBotaoAvisoWhatsApp(laudo: LaudoAvisoWhatsApp): string {
  const destinos = getDestinosAvisoWhatsApp(laudo);
  const plural = getVeterinariosLiberados(laudo).length > 1;
  const rotuloVet = plural ? "veterinários parceiros" : "veterinário parceiro";
  if (destinos.length === 2) {
    return `Avisar clínica e ${rotuloVet} pelo WhatsApp oficial`;
  }
  if (destinos.includes("veterinario_parceiro")) {
    return `Avisar ${rotuloVet} pelo WhatsApp oficial`;
  }
  return "Avisar clínica pelo WhatsApp oficial";
}

export const DESTINO_AVISO_CLINICA = "clinica";

export function chaveDestinoVeterinario(partnerId: number): string {
  return `veterinario:${partnerId}`;
}

function envioRegistrado(
  laudo: LaudoAvisoWhatsApp,
  chave: string,
  legado: EnvioDestinoWhatsApp | null
): EnvioDestinoWhatsApp | null {
  const registrado = laudo.whatsapp_envios?.[chave];
  if (registrado?.status) {
    return registrado;
  }
  // Laudo avisado antes do seletor existir: o que ha e o resumo nas colunas
  // antigas. Serve para nao remarcar quem ja recebeu.
  return legado;
}

/**
 * Destinos que podem receber o aviso deste laudo, cada um com o resultado do
 * ultimo envio. A ordem e a da tela: clinica primeiro, veterinarios depois.
 */
export function getDestinosSelecionaveis(laudo: LaudoAvisoWhatsApp): DestinoSelecionavelWhatsApp[] {
  const destinos: DestinoSelecionavelWhatsApp[] = [];

  if (laudo.clinic_id && (laudo.portal_clinica_liberado || laudo.status === PORTAL_RELEASE_STATUS)) {
    destinos.push({
      id: DESTINO_AVISO_CLINICA,
      tipo: "clinica",
      nome: laudo.clinica?.trim() || "Clínica parceira",
      ultimoEnvio: envioRegistrado(
        laudo,
        DESTINO_AVISO_CLINICA,
        laudo.whatsapp_liberacao_status
          ? {
              status: laudo.whatsapp_liberacao_status,
              em: laudo.whatsapp_liberacao_em,
              erro: laudo.whatsapp_liberacao_erro,
            }
          : null
      ),
    });
  }

  for (const veterinario of getVeterinariosLiberados(laudo)) {
    const chave = chaveDestinoVeterinario(veterinario.partner_id);
    destinos.push({
      id: chave,
      tipo: "veterinario",
      nome: veterinario.nome?.trim() || "Veterinário parceiro",
      ultimoEnvio: envioRegistrado(
        laudo,
        chave,
        laudo.whatsapp_parceiro_status
          ? {
              status: laudo.whatsapp_parceiro_status,
              em: laudo.whatsapp_parceiro_em,
              erro: laudo.whatsapp_parceiro_erro,
            }
          : null
      ),
    });
  }

  return destinos;
}

/** Vem marcado quem ainda nao recebeu: nunca enviado, ou envio que falhou. */
export function getSelecaoInicialAviso(destinos: DestinoSelecionavelWhatsApp[]): string[] {
  return destinos.filter((destino) => destino.ultimoEnvio?.status !== "enviado").map((destino) => destino.id);
}

export function resumirRespostaAvisoWhatsApp(
  resposta: RespostaAvisoWhatsApp | null | undefined
): { texto: string; tom: "sucesso" | "alerta" } {
  const clinicaEnviada = resposta?.clinica?.status === "enviado";
  const veterinarios: ResumoVeterinarioAvisoWhatsApp[] = resposta?.veterinarios_parceiros?.length
    ? resposta.veterinarios_parceiros
    : resposta?.veterinario_parceiro
    ? [resposta.veterinario_parceiro]
    : [];
  const enviados = veterinarios.filter((item) => item.status === "enviado");
  const falharam = veterinarios.filter((item) => item.status === "falhou");

  // Destino escolhido que nao tem numero no cadastro: nao e erro de envio, mas
  // tambem nao pode passar como se tivesse sido avisado.
  const semNumero: string[] = [];
  if (resposta?.clinica?.motivo === "sem_whatsapp") {
    semNumero.push("a clínica");
  }
  for (const veterinario of veterinarios) {
    if (veterinario.motivo === "sem_whatsapp") {
      semNumero.push(veterinario.nome?.trim() || "o veterinário parceiro");
    }
  }
  const fraseSemNumero =
    semNumero.length > 0
      ? `${semNumero.join(", ")} ${semNumero.length > 1 ? "não têm" : "não tem"} WhatsApp cadastrado.`
      : "";
  // Vira frase propria quando entra depois de outra; por isso a maiuscula.
  const avisoSemNumero = fraseSemNumero
    ? ` ${fraseSemNumero.charAt(0).toUpperCase()}${fraseSemNumero.slice(1)}`
    : "";

  if (falharam.length > 0) {
    // O erro vem do provedor e nem sempre termina em ponto; sem isto ele emenda
    // na frase seguinte ("...template delivery a clínica não tem...").
    const erroBruto = falharam[0].erro?.trim() || "erro no envio pelo WhatsApp oficial";
    const erro = /[.!?]$/.test(erroBruto) ? erroBruto : `${erroBruto}.`;
    const alvo = rotuloVeterinarios(falharam);
    const inicio = clinicaEnviada
      ? `Aviso enviado para a clínica, mas o envio para ${alvo} falhou: `
      : `O envio para ${alvo} falhou: `;
    return { texto: `${inicio}${erro}${avisoSemNumero}`, tom: "alerta" };
  }

  const tom = avisoSemNumero ? "alerta" : "sucesso";

  if (clinicaEnviada && enviados.length > 0) {
    return {
      texto: `Aviso enviado para a clínica e para ${rotuloVeterinarios(
        enviados
      )} pelo WhatsApp oficial da Fort Cordis.${avisoSemNumero}`,
      tom,
    };
  }
  if (enviados.length > 0) {
    return {
      texto: `Aviso enviado para ${rotuloVeterinarios(
        enviados
      )} pelo WhatsApp oficial da Fort Cordis.${avisoSemNumero}`,
      tom,
    };
  }
  if (clinicaEnviada) {
    return {
      texto: `Aviso enviado para a clínica pelo WhatsApp oficial da Fort Cordis.${avisoSemNumero}`,
      tom,
    };
  }
  if (fraseSemNumero) {
    return {
      texto: `Ninguém foi avisado: ${fraseSemNumero}`,
      tom: "alerta",
    };
  }
  return {
    texto: "Aviso enviado pelo WhatsApp oficial da Fort Cordis.",
    tom: "sucesso",
  };
}

function rotuloVeterinarios(veterinarios: ResumoVeterinarioAvisoWhatsApp[]): string {
  const nomes = veterinarios
    .map((item) => item.nome?.trim())
    .filter((nome): nome is string => Boolean(nome));
  if (nomes.length === 1) {
    return nomes[0];
  }
  if (nomes.length > 1) {
    return `${nomes.slice(0, -1).join(", ")} e ${nomes[nomes.length - 1]}`;
  }
  return veterinarios.length > 1 ? "os veterinários parceiros" : "o veterinário parceiro";
}
