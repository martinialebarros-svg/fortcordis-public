import { describe, expect, it } from "vitest";

import {
  getConfirmacaoAvisoWhatsApp,
  getDestinosAvisoWhatsApp,
  getDestinosSelecionaveis,
  getSelecaoInicialAviso,
  getTituloBotaoAvisoWhatsApp,
  podeAvisarWhatsApp,
  resumirRespostaAvisoWhatsApp,
} from "./laudo-whatsapp-aviso";

const laudoClinicaELiberadoParaParceiro = {
  status: "Liberado no portal",
  clinica: "Gram Pet",
  clinic_id: 8,
  portal_clinica_liberado: true,
  veterinario_parceiro_id: 4,
  veterinario_parceiro_nome: "Dra Isadora Bastos",
  portal_veterinario_liberado: true,
};

describe("destinos do aviso por WhatsApp", () => {
  it("inclui clinica e parceiro quando os dois estao liberados no portal", () => {
    expect(getDestinosAvisoWhatsApp(laudoClinicaELiberadoParaParceiro)).toEqual([
      "clinica",
      "veterinario_parceiro",
    ]);
  });

  it("deixa o parceiro de fora enquanto ele nao tem liberacao no portal", () => {
    expect(
      getDestinosAvisoWhatsApp({
        ...laudoClinicaELiberadoParaParceiro,
        portal_veterinario_liberado: false,
      })
    ).toEqual(["clinica"]);
  });

  it("aceita laudo so com parceiro, sem clinica vinculada", () => {
    const laudo = {
      status: "Liberado no portal",
      clinic_id: null,
      veterinario_parceiro_id: 4,
      veterinario_parceiro_nome: "Dra Isadora Bastos",
      portal_veterinario_liberado: true,
    };
    expect(getDestinosAvisoWhatsApp(laudo)).toEqual(["veterinario_parceiro"]);
    expect(podeAvisarWhatsApp(laudo)).toBe(true);
  });

  it("nao oferece o aviso quando nenhum destino esta liberado", () => {
    expect(
      podeAvisarWhatsApp({
        status: "Rascunho",
        clinic_id: 8,
        portal_clinica_liberado: false,
        veterinario_parceiro_id: 4,
        portal_veterinario_liberado: false,
      })
    ).toBe(false);
  });
});

describe("textos de confirmacao e titulo", () => {
  it("nomeia os dois destinatarios na confirmacao", () => {
    expect(getConfirmacaoAvisoWhatsApp(laudoClinicaELiberadoParaParceiro)).toBe(
      "Enviar para Gram Pet e Dra Isadora Bastos o aviso de laudo disponível?"
    );
    expect(getTituloBotaoAvisoWhatsApp(laudoClinicaELiberadoParaParceiro)).toBe(
      "Avisar clínica e veterinário parceiro pelo WhatsApp oficial"
    );
  });

  it("nomeia so a clinica quando o parceiro nao entra no envio", () => {
    const laudo = { ...laudoClinicaELiberadoParaParceiro, portal_veterinario_liberado: false };
    expect(getConfirmacaoAvisoWhatsApp(laudo)).toBe(
      "Enviar para Gram Pet o aviso de laudo disponível?"
    );
    expect(getTituloBotaoAvisoWhatsApp(laudo)).toBe("Avisar clínica pelo WhatsApp oficial");
  });

  it("nomeia so o parceiro em laudo sem clinica", () => {
    const laudo = {
      status: "Liberado no portal",
      clinic_id: null,
      veterinario_parceiro_id: 4,
      veterinario_parceiro_nome: "Dra Isadora Bastos",
      portal_veterinario_liberado: true,
    };
    expect(getConfirmacaoAvisoWhatsApp(laudo)).toBe(
      "Enviar para Dra Isadora Bastos o aviso de laudo disponível?"
    );
    expect(getTituloBotaoAvisoWhatsApp(laudo)).toBe(
      "Avisar veterinário parceiro pelo WhatsApp oficial"
    );
  });
});

describe("resumo da resposta do envio", () => {
  it("confirma os dois envios", () => {
    expect(
      resumirRespostaAvisoWhatsApp({
        clinica: { status: "enviado" },
        veterinario_parceiro: { status: "enviado" },
      })
    ).toEqual({
      texto:
        "Aviso enviado para a clínica e para o veterinário parceiro pelo WhatsApp oficial da Fort Cordis.",
      tom: "sucesso",
    });
  });

  it("trata falha so do parceiro como alerta, com o erro do provedor", () => {
    const resumo = resumirRespostaAvisoWhatsApp({
      clinica: { status: "enviado" },
      veterinario_parceiro: { status: "falhou", erro: "Numero invalido no provedor." },
    });
    expect(resumo.tom).toBe("alerta");
    expect(resumo.texto).toContain("Numero invalido no provedor.");
    expect(resumo.texto).toContain("clínica");
  });

  it("nao inventa envio para a clinica quando so o parceiro foi avisado", () => {
    expect(
      resumirRespostaAvisoWhatsApp({
        clinica: { status: "ignorado", motivo: "sem_vinculo" },
        veterinario_parceiro: { status: "enviado" },
      })
    ).toEqual({
      texto: "Aviso enviado para o veterinário parceiro pelo WhatsApp oficial da Fort Cordis.",
      tom: "sucesso",
    });
  });

  it("cai no texto generico quando a resposta nao detalha os destinos", () => {
    expect(resumirRespostaAvisoWhatsApp(undefined)).toEqual({
      texto: "Aviso enviado pelo WhatsApp oficial da Fort Cordis.",
      tom: "sucesso",
    });
  });
});

describe("difusao por vinculo de clinica", () => {
  const laudoComDifusao = {
    status: "Liberado no portal",
    clinica: "Animal Care",
    clinic_id: 8,
    portal_clinica_liberado: true,
    // Ninguem foi nomeado no laudo: a Dra. Carla entrou pelo vinculo da clinica.
    veterinario_parceiro_id: null,
    veterinario_parceiro_nome: "",
    portal_veterinario_liberado: true,
    portal_veterinarios_destinos: [
      { partner_id: 50, nome: "Dra. Carla Soares", origem: "vinculo_clinica", liberado: true },
    ],
  };

  it("inclui o veterinario que entrou so por vinculo, sem estar nomeado no laudo", () => {
    expect(getDestinosAvisoWhatsApp(laudoComDifusao)).toEqual(["clinica", "veterinario_parceiro"]);
    expect(podeAvisarWhatsApp(laudoComDifusao)).toBe(true);
  });

  it("o dialogo nomeia quem vai receber, e nao so a clinica", () => {
    expect(getConfirmacaoAvisoWhatsApp(laudoComDifusao)).toBe(
      "Enviar para Animal Care e Dra. Carla Soares o aviso de laudo disponível?",
    );
  });

  it("o botao avisa que o veterinario tambem recebe", () => {
    expect(getTituloBotaoAvisoWhatsApp(laudoComDifusao)).toBe(
      "Avisar clínica e veterinário parceiro pelo WhatsApp oficial",
    );
  });

  it("com mais de um veterinario, o dialogo nomeia todos e o botao vai para o plural", () => {
    const laudo = {
      ...laudoComDifusao,
      veterinario_parceiro_id: 4,
      veterinario_parceiro_nome: "Dra Isadora Bastos",
      portal_veterinarios_destinos: [
        { partner_id: 4, nome: "Dra Isadora Bastos", origem: "nomeado", liberado: true },
        { partner_id: 50, nome: "Dra. Carla Soares", origem: "vinculo_clinica", liberado: true },
      ],
    };

    expect(getConfirmacaoAvisoWhatsApp(laudo)).toBe(
      "Enviar para Animal Care e Dra Isadora Bastos e Dra. Carla Soares o aviso de laudo disponível?",
    );
    expect(getTituloBotaoAvisoWhatsApp(laudo)).toBe(
      "Avisar clínica e veterinários parceiros pelo WhatsApp oficial",
    );
  });

  it("veterinario ainda nao liberado no portal fica de fora do aviso", () => {
    const laudo = {
      ...laudoComDifusao,
      portal_veterinario_liberado: false,
      portal_veterinarios_destinos: [
        { partner_id: 50, nome: "Dra. Carla Soares", origem: "vinculo_clinica", liberado: false },
      ],
    };

    expect(getDestinosAvisoWhatsApp(laudo)).toEqual(["clinica"]);
    expect(getConfirmacaoAvisoWhatsApp(laudo)).toBe(
      "Enviar para Animal Care o aviso de laudo disponível?",
    );
  });

  it("laudo do contrato antigo, sem a lista, segue valendo pelo nomeado", () => {
    const laudo = {
      status: "Liberado no portal",
      clinica: "Animal Care",
      clinic_id: 8,
      portal_clinica_liberado: true,
      veterinario_parceiro_id: 4,
      veterinario_parceiro_nome: "Dra Isadora Bastos",
      portal_veterinario_liberado: true,
    };

    expect(getDestinosAvisoWhatsApp(laudo)).toEqual(["clinica", "veterinario_parceiro"]);
    expect(getConfirmacaoAvisoWhatsApp(laudo)).toBe(
      "Enviar para Animal Care e Dra Isadora Bastos o aviso de laudo disponível?",
    );
  });
});

describe("seletor de destino", () => {
  const laudoComDoisVeterinarios = {
    status: "Liberado no portal",
    clinica: "Clinica Veterinária São Jose",
    clinic_id: 39,
    portal_clinica_liberado: true,
    veterinario_parceiro_id: 4,
    veterinario_parceiro_nome: "Dra Isadora Bastos",
    portal_veterinario_liberado: true,
    portal_veterinarios_destinos: [
      { partner_id: 4, nome: "Dra Isadora Bastos", origem: "nomeado", liberado: true },
      { partner_id: 144, nome: "Dra Camila Rebouças", origem: "vinculo_clinica", liberado: true },
    ],
  };

  it("lista clinica e veterinarios liberados, com a chave que o backend entende", () => {
    const destinos = getDestinosSelecionaveis(laudoComDoisVeterinarios);
    expect(destinos.map((item) => item.id)).toEqual(["clinica", "veterinario:4", "veterinario:144"]);
    expect(destinos.map((item) => item.nome)).toEqual([
      "Clinica Veterinária São Jose",
      "Dra Isadora Bastos",
      "Dra Camila Rebouças",
    ]);
  });

  it("deixa de fora o veterinario que ainda nao esta liberado no portal", () => {
    const destinos = getDestinosSelecionaveis({
      ...laudoComDoisVeterinarios,
      portal_veterinarios_destinos: [
        { partner_id: 4, nome: "Dra Isadora Bastos", origem: "nomeado", liberado: true },
        { partner_id: 144, nome: "Dra Camila Rebouças", origem: "vinculo_clinica", liberado: false },
      ],
    });
    expect(destinos.map((item) => item.id)).toEqual(["clinica", "veterinario:4"]);
  });

  it("marca so quem ainda nao recebeu", () => {
    const destinos = getDestinosSelecionaveis({
      ...laudoComDoisVeterinarios,
      whatsapp_envios: {
        clinica: { status: "enviado" as const, em: "2026-09-17T02:07:46", erro: null },
        "veterinario:4": { status: "falhou" as const, em: "2026-09-17T02:07:46", erro: "Numero invalido." },
      },
    });

    expect(getSelecaoInicialAviso(destinos)).toEqual(["veterinario:4", "veterinario:144"]);
    expect(destinos[0].ultimoEnvio?.status).toBe("enviado");
    expect(destinos[1].ultimoEnvio?.erro).toBe("Numero invalido.");
    expect(destinos[2].ultimoEnvio).toBeNull();
  });

  it("laudo com um destino so abre com ele marcado", () => {
    const destinos = getDestinosSelecionaveis({
      status: "Liberado no portal",
      clinica: "Gram Pet",
      clinic_id: 8,
      portal_clinica_liberado: true,
    });
    expect(getSelecaoInicialAviso(destinos)).toEqual(["clinica"]);
  });

  it("laudo anterior ao seletor usa as colunas de resumo para saber quem ja recebeu", () => {
    const destinos = getDestinosSelecionaveis({
      ...laudoComDoisVeterinarios,
      portal_veterinarios_destinos: [
        { partner_id: 4, nome: "Dra Isadora Bastos", origem: "nomeado", liberado: true },
      ],
      whatsapp_liberacao_status: "enviado",
      whatsapp_liberacao_em: "2026-09-16T16:16:34",
      whatsapp_parceiro_status: "enviado",
      whatsapp_parceiro_em: "2026-09-16T16:16:34",
    });

    expect(getSelecaoInicialAviso(destinos)).toEqual([]);
  });

  it("fecha a frase do erro do provedor antes de emendar o proximo aviso", () => {
    const resumo = resumirRespostaAvisoWhatsApp({
      clinica: { status: "ignorado", motivo: "sem_whatsapp" },
      veterinarios_parceiros: [
        {
          partner_id: 49,
          nome: "Martiniano",
          status: "falhou",
          erro: "WhatsApp provider rejected or did not complete the template delivery",
        },
      ],
    });

    expect(resumo.texto).toContain("template delivery. A clínica não tem WhatsApp cadastrado.");
  });

  it("o resumo avisa quando um destino escolhido nao tem WhatsApp cadastrado", () => {
    const resumo = resumirRespostaAvisoWhatsApp({
      clinica: { status: "ignorado", motivo: "sem_whatsapp" },
      veterinarios_parceiros: [
        { partner_id: 144, nome: "Dra Camila Rebouças", status: "enviado" },
      ],
    });

    expect(resumo.tom).toBe("alerta");
    expect(resumo.texto).toContain("Dra Camila Rebouças");
    expect(resumo.texto).toContain("A clínica não tem WhatsApp cadastrado.");
  });

  it("quando ninguem tem numero, o resumo nao finge que avisou", () => {
    const resumo = resumirRespostaAvisoWhatsApp({
      clinica: { status: "ignorado", motivo: "sem_whatsapp" },
      veterinarios_parceiros: [
        { partner_id: 144, nome: "Dra Camila Rebouças", status: "ignorado", motivo: "sem_whatsapp" },
      ],
    });

    expect(resumo.tom).toBe("alerta");
    expect(resumo.texto).toContain("Ninguém foi avisado");
    expect(resumo.texto).toContain("Dra Camila Rebouças");
  });

  it("o resumo nomeia o veterinario que recebeu quando a resposta detalha a lista", () => {
    expect(
      resumirRespostaAvisoWhatsApp({
        clinica: { status: "ignorado", motivo: "nao_selecionado" },
        veterinarios_parceiros: [
          { partner_id: 4, nome: "Dra Isadora Bastos", status: "ignorado", motivo: "nao_selecionado" },
          { partner_id: 144, nome: "Dra Camila Rebouças", status: "enviado" },
        ],
      })
    ).toEqual({
      texto: "Aviso enviado para Dra Camila Rebouças pelo WhatsApp oficial da Fort Cordis.",
      tom: "sucesso",
    });
  });
});
