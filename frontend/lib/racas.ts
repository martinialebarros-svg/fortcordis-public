const RACAS_POR_ESPECIE: Record<string, string[]> = {
  Canina: [
    "SRD",
    "Akita",
    "American Pitbull",
    "Australian Shepherd",
    "Beagle",
    "Bernese Mountain Dog",
    "Bichon Frise",
    "Border Collie",
    "Boston Terrier",
    "Boxer",
    "Bull Terrier",
    "Cairn Terrier",
    "Cane Corso",
    "Cavalier King Charles Spaniel",
    "Chihuahua",
    "Chow Chow",
    "Cocker Spaniel",
    "Dachshund",
    "Doberman",
    "Dogue Alemao",
    "Fox Terrier",
    "Galgo",
    "Golden Retriever",
    "Great Dane",
    "Husky Siberiano",
    "Jack Russell Terrier",
    "Labrador Retriever",
    "Lhasa Apso",
    "Maltes",
    "Mastiff",
    "Newfoundland",
    "Pastor Alemao",
    "Pastor Belga",
    "Pinscher",
    "Poodle",
    "Pug",
    "Rottweiler",
    "Saint Bernard",
    "Samoieda",
    "Scottish Terrier",
    "Shetland Sheepdog",
    "Shih Tzu",
    "Shar Pei",
    "Spitz Alemao",
    "Springer Spaniel",
    "Staffordshire Bull Terrier",
    "Weimaraner",
    "West Highland White Terrier",
    "Whippet",
    "Yorkshire Terrier",
  ],
  Felina: [
    "SRD",
    "Abissinio",
    "American Shorthair",
    "Angora",
    "Balinese",
    "Bengal",
    "Birmanes",
    "British Shorthair",
    "Burmese",
    "Chartreux",
    "Cornish Rex",
    "Devon Rex",
    "European Shorthair",
    "Exotico Shorthair",
    "Havana Brown",
    "Korat",
    "Maine Coon",
    "Norwegian Forest",
    "Oriental Shorthair",
    "Persa",
    "Pixie Bob",
    "Ragdoll",
    "Russo Azul",
    "Savannah",
    "Scottish Fold",
    "Siamese",
    "Somali",
    "Sphynx",
    "Tonquines",
  ],
  Equina: [
    "SRD",
    "Quarto de Milha",
    "Mangalarga Marchador",
    "Crioulo",
    "Puro Sangue Ingles",
    "Appaloosa",
  ],
  Outra: ["SRD"],
};

const DEFAULT_RACAS = ["SRD"];
const STORAGE_KEY = "fortcordis:racas-custom-por-especie";
const AJUSTES_STORAGE_KEY = "fortcordis:racas-ajustes-por-especie";

export type RacasCustomPorEspecie = Record<string, string[]>;

export interface AjusteRacasDaEspecie {
  removidas: string[];
  renomeadas: Record<string, string>;
}

export type AjustesRacasPorEspecie = Record<string, AjusteRacasDaEspecie>;

export interface RacaCatalogoItem {
  id: string;
  nome: string;
  nomeOriginal: string;
  origem: "padrao" | "personalizada";
}

const normalizarChave = (value: string): string =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLocaleLowerCase("pt-BR");

const ordenarRacas = <T extends { nome: string }>(racas: T[]): T[] =>
  [...racas].sort((a, b) =>
    a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" }),
  );

const criarIdRaca = (origem: RacaCatalogoItem["origem"], nome: string): string =>
  `${origem}:${normalizarChave(nome)}`;

const ajusteVazio = (): AjusteRacasDaEspecie => ({
  removidas: [],
  renomeadas: {},
});

function pushUniqueCaseInsensitive(list: string[], value: string) {
  const normalized = value.toLowerCase();
  if (!list.some((item) => item.toLowerCase() === normalized)) {
    list.push(value);
  }
}

export function getRacasCatalogo(
  especie?: string,
  racasExtras: string[] = [],
  ajustesPorEspecie: AjustesRacasPorEspecie = {},
): RacaCatalogoItem[] {
  const base = RACAS_POR_ESPECIE[especie || ""] || DEFAULT_RACAS;
  const ajustes = ajustesPorEspecie[especie || ""] || ajusteVazio();
  const removidas = new Set(ajustes.removidas || []);
  const catalogo: RacaCatalogoItem[] = [];

  for (const raca of base) {
    const id = criarIdRaca("padrao", raca);
    if (removidas.has(id)) continue;

    catalogo.push({
      id,
      nome: (ajustes.renomeadas?.[id] || raca).trim(),
      nomeOriginal: raca,
      origem: "padrao",
    });
  }

  for (const extra of racasExtras) {
    const raca = (extra || "").trim();
    if (!raca) continue;
    const id = criarIdRaca("personalizada", raca);
    if (removidas.has(id)) continue;

    catalogo.push({
      id,
      nome: (ajustes.renomeadas?.[id] || raca).trim(),
      nomeOriginal: raca,
      origem: "personalizada",
    });
  }

  const idsPorNome = new Set<string>();
  return ordenarRacas(
    catalogo.filter((item) => {
      const chave = normalizarChave(item.nome);
      if (!chave || idsPorNome.has(chave)) return false;
      idsPorNome.add(chave);
      return true;
    }),
  );
}

export function getRacaOptions(
  especie?: string,
  racaAtual?: string,
  racasExtras: string[] = [],
  ajustesPorEspecie: AjustesRacasPorEspecie = {},
): string[] {
  const opcoes = getRacasCatalogo(especie, racasExtras, ajustesPorEspecie).map((item) => item.nome);
  const atual = (racaAtual || "").trim();
  if (atual) {
    pushUniqueCaseInsensitive(opcoes, atual);
  }

  return ordenarRacas(opcoes.map((nome) => ({ nome }))).map((item) => item.nome);
}

export function addRacaCustomPorEspecie(
  mapaAtual: RacasCustomPorEspecie,
  especie: string,
  novaRaca: string,
): RacasCustomPorEspecie {
  const especieAtual = (especie || "").trim();
  const raca = (novaRaca || "").trim();
  if (!especieAtual || !raca) return mapaAtual;

  const listaAtual = mapaAtual[especieAtual] || [];
  if (listaAtual.some((item) => item.toLowerCase() === raca.toLowerCase())) {
    return mapaAtual;
  }

  return {
    ...mapaAtual,
    [especieAtual]: ordenarRacas([...listaAtual, raca].map((nome) => ({ nome }))).map((item) => item.nome),
  };
}

export function editarRacaCatalogo(
  mapaAtual: RacasCustomPorEspecie,
  ajustesAtuais: AjustesRacasPorEspecie,
  especie: string,
  raca: RacaCatalogoItem,
  novoNome: string,
): { racasCustomPorEspecie: RacasCustomPorEspecie; ajustesPorEspecie: AjustesRacasPorEspecie } {
  const especieAtual = (especie || "").trim();
  const nomeAtualizado = (novoNome || "").trim();
  if (!especieAtual || !nomeAtualizado) {
    return { racasCustomPorEspecie: mapaAtual, ajustesPorEspecie: ajustesAtuais };
  }

  if (raca.origem === "personalizada") {
    const listaAtual = mapaAtual[especieAtual] || [];
    return {
      racasCustomPorEspecie: {
        ...mapaAtual,
        [especieAtual]: ordenarRacas(
          listaAtual.map((item) => ({
            nome: normalizarChave(item) === normalizarChave(raca.nomeOriginal) ? nomeAtualizado : item,
          })),
        ).map((item) => item.nome),
      },
      ajustesPorEspecie: ajustesAtuais,
    };
  }

  const ajusteAtual = ajustesAtuais[especieAtual] || ajusteVazio();
  return {
    racasCustomPorEspecie: mapaAtual,
    ajustesPorEspecie: {
      ...ajustesAtuais,
      [especieAtual]: {
        removidas: ajusteAtual.removidas || [],
        renomeadas: {
          ...(ajusteAtual.renomeadas || {}),
          [raca.id]: nomeAtualizado,
        },
      },
    },
  };
}

export function excluirRacaCatalogo(
  mapaAtual: RacasCustomPorEspecie,
  ajustesAtuais: AjustesRacasPorEspecie,
  especie: string,
  raca: RacaCatalogoItem,
): { racasCustomPorEspecie: RacasCustomPorEspecie; ajustesPorEspecie: AjustesRacasPorEspecie } {
  const especieAtual = (especie || "").trim();
  if (!especieAtual) {
    return { racasCustomPorEspecie: mapaAtual, ajustesPorEspecie: ajustesAtuais };
  }

  if (raca.origem === "personalizada") {
    const listaAtual = mapaAtual[especieAtual] || [];
    const proximaLista = listaAtual.filter(
      (item) => normalizarChave(item) !== normalizarChave(raca.nomeOriginal),
    );
    const proximoMapa = { ...mapaAtual };
    if (proximaLista.length) {
      proximoMapa[especieAtual] = proximaLista;
    } else {
      delete proximoMapa[especieAtual];
    }
    return { racasCustomPorEspecie: proximoMapa, ajustesPorEspecie: ajustesAtuais };
  }

  const ajusteAtual = ajustesAtuais[especieAtual] || ajusteVazio();
  const { [raca.id]: _racaRenomeada, ...renomeadasRestantes } = ajusteAtual.renomeadas || {};
  return {
    racasCustomPorEspecie: mapaAtual,
    ajustesPorEspecie: {
      ...ajustesAtuais,
      [especieAtual]: {
        removidas: Array.from(new Set([...(ajusteAtual.removidas || []), raca.id])),
        renomeadas: renomeadasRestantes,
      },
    },
  };
}

export function loadRacasCustomPorEspecie(): RacasCustomPorEspecie {
  if (typeof window === "undefined") return {};

  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};

    const resultado: RacasCustomPorEspecie = {};
    for (const [especie, racas] of Object.entries(parsed)) {
      if (!Array.isArray(racas)) continue;
      resultado[especie] = ordenarRacas(racas
        .map((item) => String(item || "").trim())
        .filter(Boolean)
        .map((nome) => ({ nome }))).map((item) => item.nome);
    }

    return resultado;
  } catch {
    return {};
  }
}

export function saveRacasCustomPorEspecie(mapaAtual: Record<string, string[]>) {
  if (typeof window === "undefined") return;

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(mapaAtual));
  } catch {
    // Ignora falhas de armazenamento (quota/permissão)
  }
}

export function loadAjustesRacasPorEspecie(): AjustesRacasPorEspecie {
  if (typeof window === "undefined") return {};

  try {
    const raw = localStorage.getItem(AJUSTES_STORAGE_KEY);
    if (!raw) return {};

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};

    const resultado: AjustesRacasPorEspecie = {};
    for (const [especie, valor] of Object.entries(parsed)) {
      if (!valor || typeof valor !== "object") continue;
      const ajuste = valor as Partial<AjusteRacasDaEspecie>;
      resultado[especie] = {
        removidas: Array.isArray(ajuste.removidas)
          ? ajuste.removidas.map((item) => String(item || "").trim()).filter(Boolean)
          : [],
        renomeadas: Object.fromEntries(
          Object.entries(ajuste.renomeadas || {})
            .map(([id, nome]) => [id.trim(), String(nome || "").trim()])
            .filter(([id, nome]) => Boolean(id && nome)),
        ),
      };
    }
    return resultado;
  } catch {
    return {};
  }
}

export function saveAjustesRacasPorEspecie(ajustes: AjustesRacasPorEspecie) {
  if (typeof window === "undefined") return;

  try {
    localStorage.setItem(AJUSTES_STORAGE_KEY, JSON.stringify(ajustes));
  } catch {
    // Ignora falhas de armazenamento (quota/permissão)
  }
}
