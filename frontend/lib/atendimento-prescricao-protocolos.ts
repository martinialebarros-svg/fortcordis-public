export type ProtocoloPrescricaoItem = {
  nomeFallback: string;
  keywords: string[];
  doseMgKg?: number;
  frequencia: string;
  duracao: string;
  via?: string;
  instrucoes?: string;
  unidadeCalculo?: "mg" | "ml" | "comprimido";
};

export type ProtocoloPrescricao = {
  key: string;
  label: string;
  descricao: string;
  gatilhos: string[];
  retornoDias?: string;
  orientacoesPadrao?: string;
  itens: ProtocoloPrescricaoItem[];
};

export const PROTOCOLOS_PRESCRICAO: ProtocoloPrescricao[] = [
  {
    key: "endocardiose_b1",
    label: "Endocardiose B1",
    descricao: "Monitorizacao sem terapia agressiva inicial.",
    gatilhos: ["b1", "endocardiose b1", "dmvm b1", "endocardiose mitral b1"],
    retornoDias: "120",
    orientacoesPadrao:
      "Manter acompanhamento clinico e ecocardiografico periodico. Registrar tosse, intolerancia ao exercicio e FR em repouso.",
    itens: [],
  },
  {
    key: "endocardiose_b2",
    label: "Endocardiose B2",
    descricao: "Suporte cardiaco precoce com remodelamento.",
    gatilhos: ["b2", "endocardiose b2", "dmvm b2", "remodelamento atrial"],
    retornoDias: "30",
    orientacoesPadrao:
      "Reavaliar com ECO e aferir FR em repouso diariamente. Ajustar terapia se houver progressao clinica.",
    itens: [
      {
        nomeFallback: "Pimobendan",
        keywords: ["pimobendan", "vetmedin"],
        doseMgKg: 0.25,
        frequencia: "a cada 12h",
        duracao: "uso continuo",
        via: "Oral",
        instrucoes: "Administrar em jejum quando possivel.",
      },
      {
        nomeFallback: "Benazepril",
        keywords: ["benazepril"],
        doseMgKg: 0.5,
        frequencia: "a cada 24h",
        duracao: "uso continuo",
        via: "Oral",
        instrucoes: "Monitorar creatinina e pressao arterial.",
      },
    ],
  },
  {
    key: "icc_compensada",
    label: "ICC compensada",
    descricao: "Controle de congestao e remodelamento.",
    gatilhos: ["icc", "insuficiencia cardiaca", "congestao", "edema pulmonar"],
    retornoDias: "7",
    orientacoesPadrao:
      "Monitorar FR em repouso, apetite e tolerancia ao exercicio. Retorno imediato se dispneia ou piora clinica.",
    itens: [
      {
        nomeFallback: "Furosemida",
        keywords: ["furosemida", "furosemide"],
        doseMgKg: 2,
        frequencia: "a cada 12h",
        duracao: "7 dias e reavaliar",
        via: "Oral",
        instrucoes: "Ajustar conforme congestao e funcao renal.",
      },
      {
        nomeFallback: "Pimobendan",
        keywords: ["pimobendan", "vetmedin"],
        doseMgKg: 0.25,
        frequencia: "a cada 12h",
        duracao: "uso continuo",
        via: "Oral",
      },
      {
        nomeFallback: "Espironolactona",
        keywords: ["espironolactona", "spironolactone"],
        doseMgKg: 2,
        frequencia: "a cada 24h",
        duracao: "uso continuo",
        via: "Oral",
      },
    ],
  },
  {
    key: "hipertensao_sistemica",
    label: "HAS sistemica",
    descricao: "Controle pressorico com revisao seriada.",
    gatilhos: ["hipertensao", "has", "pressao arterial elevada"],
    retornoDias: "14",
    orientacoesPadrao:
      "Aferir pressao arterial em ambiente calmo e registrar media de medidas sequenciais.",
    itens: [
      {
        nomeFallback: "Amlodipina",
        keywords: ["amlodipina", "amlodipine"],
        doseMgKg: 0.15,
        frequencia: "a cada 24h",
        duracao: "uso continuo",
        via: "Oral",
      },
      {
        nomeFallback: "Benazepril",
        keywords: ["benazepril"],
        doseMgKg: 0.5,
        frequencia: "a cada 24h",
        duracao: "uso continuo",
        via: "Oral",
      },
    ],
  },
];
