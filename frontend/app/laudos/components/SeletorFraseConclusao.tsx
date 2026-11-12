"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Search,
  X,
} from "lucide-react";

import { type FraseEcoEstruturadoTeste } from "@/lib/ecocardiograma-estruturado-teste";

interface SeletorFraseConclusaoProps {
  frases: FraseEcoEstruturadoTeste[];
  value?: string;
  onChange?: (fraseId: string) => void;
  multiple?: boolean;
  values?: string[];
  onValuesChange?: (fraseIds: string[]) => void;
}

interface GrupoConclusoes {
  label: string;
  frases: FraseEcoEstruturadoTeste[];
}

interface AtalhoConclusao {
  key: string;
  label: string;
  corresponde: (frase: FraseEcoEstruturadoTeste) => boolean;
}

interface PosicaoPainelConclusao {
  top?: number;
  bottom?: number;
  left: number;
  width: number;
  maxHeight: number;
}

const STORAGE_CONCLUSOES_RECENTES = "fortcordis:eco:conclusoes-recentes";
const LIMITE_CONCLUSOES_RECENTES = 5;
const GRUPO_SEM_CLASSIFICACAO = "Outros achados";
const MARGEM_VIEWPORT = 12;
const ESPACO_ENTRE_GATILHO_E_PAINEL = 8;
const ALTURA_PREFERIDA_PAINEL = 620;
const LARGURA_MINIMA_DESKTOP = 672;

const ORDEM_GRUPOS_CONCLUSAO = [
  "Exame normal",
  "Doença valvar mixomatosa",
  "Cardiomiopatias",
  "Hipertensão pulmonar",
  "Cardiopatias congênitas",
  "Função e remodelamento cardíaco",
  "Pericárdio e efusões",
  "Dirofilariose",
  "Massas e trombos",
  "Outras valvopatias",
  "Grandes vasos",
  GRUPO_SEM_CLASSIFICACAO,
];

function normalizarBusca(valor: unknown): string {
  return String(valor || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function compararFrases(
  fraseA: FraseEcoEstruturadoTeste,
  fraseB: FraseEcoEstruturadoTeste,
): number {
  if ((fraseA.ordem || 999) !== (fraseB.ordem || 999)) {
    return (fraseA.ordem || 999) - (fraseB.ordem || 999);
  }
  return String(fraseA.titulo || "").localeCompare(String(fraseB.titulo || ""));
}

function camposBuscaFrase(frase: FraseEcoEstruturadoTeste): string {
  return normalizarBusca(
    [
      frase.titulo,
      frase.texto,
      ...(frase.tags || []),
      ...(frase.patologias || []),
    ].join(" "),
  );
}

function camposAtalhoFrase(frase: FraseEcoEstruturadoTeste): string {
  return normalizarBusca([frase.titulo, ...(frase.tags || [])].join(" "));
}

function contemToken(valor: string, token: string): boolean {
  return valor.split(/[^a-z0-9]+/).includes(normalizarBusca(token));
}

const ATALHOS_CONCLUSAO: AtalhoConclusao[] = [
  {
    key: "b1",
    label: "B1",
    corresponde: (frase) => contemToken(camposAtalhoFrase(frase), "b1"),
  },
  {
    key: "b2",
    label: "B2",
    corresponde: (frase) => contemToken(camposAtalhoFrase(frase), "b2"),
  },
  {
    key: "cd",
    label: "C/D",
    corresponde: (frase) => {
      const campos = camposAtalhoFrase(frase);
      return contemToken(campos, "c") || contemToken(campos, "d");
    },
  },
  {
    key: "dmvt",
    label: "DMVT",
    corresponde: (frase) => contemToken(camposAtalhoFrase(frase), "dmvt"),
  },
  {
    key: "hp",
    label: "HP",
    corresponde: (frase) => {
      const campos = camposBuscaFrase(frase);
      return (
        contemToken(campos, "hp") || campos.includes("hipertensao pulmonar")
      );
    },
  },
  {
    key: "ddg",
    label: "DDG",
    corresponde: (frase) => contemToken(camposBuscaFrase(frase), "ddg"),
  },
];

function resumirTexto(texto?: string, limite = 180): string {
  const normalizado = String(texto || "")
    .replace(/\s+/g, " ")
    .trim();
  if (normalizado.length <= limite) {
    return normalizado;
  }
  return `${normalizado.slice(0, limite - 3)}...`;
}

function ordenarGrupos(grupoA: string, grupoB: string): number {
  const indiceA = ORDEM_GRUPOS_CONCLUSAO.findIndex(
    (grupo) => normalizarBusca(grupo) === normalizarBusca(grupoA),
  );
  const indiceB = ORDEM_GRUPOS_CONCLUSAO.findIndex(
    (grupo) => normalizarBusca(grupo) === normalizarBusca(grupoB),
  );
  const ordemA = indiceA === -1 ? ORDEM_GRUPOS_CONCLUSAO.length - 1 : indiceA;
  const ordemB = indiceB === -1 ? ORDEM_GRUPOS_CONCLUSAO.length - 1 : indiceB;

  if (ordemA !== ordemB) {
    return ordemA - ordemB;
  }
  return grupoA.localeCompare(grupoB);
}

export default function SeletorFraseConclusao({
  frases,
  value = "",
  onChange,
  multiple = false,
  values = [],
  onValuesChange,
}: SeletorFraseConclusaoProps) {
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState("");
  const [atalhoAtivo, setAtalhoAtivo] = useState("");
  const [gruposExpandidos, setGruposExpandidos] = useState<Set<string>>(
    new Set(),
  );
  const [idsRecentes, setIdsRecentes] = useState<string[]>([]);
  const [posicaoPainel, setPosicaoPainel] =
    useState<PosicaoPainelConclusao | null>(null);
  const seletorRef = useRef<HTMLDivElement | null>(null);
  const painelRef = useRef<HTMLDivElement | null>(null);

  const atualizarPosicaoPainel = useCallback(() => {
    const seletor = seletorRef.current;
    if (!seletor) {
      return;
    }

    const retangulo = seletor.getBoundingClientRect();
    const larguraViewport =
      document.documentElement.clientWidth || window.innerWidth;
    const alturaViewport =
      document.documentElement.clientHeight || window.innerHeight;
    const larguraMaxima = Math.max(0, larguraViewport - MARGEM_VIEWPORT * 2);
    const larguraPreferida =
      larguraViewport >= 1024
        ? Math.max(retangulo.width, LARGURA_MINIMA_DESKTOP)
        : retangulo.width;
    const width = Math.min(larguraPreferida, larguraMaxima);
    const left = Math.min(
      Math.max(retangulo.left, MARGEM_VIEWPORT),
      Math.max(MARGEM_VIEWPORT, larguraViewport - MARGEM_VIEWPORT - width),
    );
    const espacoAbaixo = Math.max(
      0,
      alturaViewport -
        retangulo.bottom -
        ESPACO_ENTRE_GATILHO_E_PAINEL -
        MARGEM_VIEWPORT,
    );
    const espacoAcima = Math.max(
      0,
      retangulo.top - ESPACO_ENTRE_GATILHO_E_PAINEL - MARGEM_VIEWPORT,
    );
    const abrirAcima =
      espacoAbaixo < Math.min(ALTURA_PREFERIDA_PAINEL, 420) &&
      espacoAcima > espacoAbaixo;
    const espacoDisponivel = abrirAcima ? espacoAcima : espacoAbaixo;
    const maxHeight = Math.min(
      ALTURA_PREFERIDA_PAINEL,
      Math.max(120, espacoDisponivel),
    );

    setPosicaoPainel({
      top: abrirAcima
        ? undefined
        : retangulo.bottom + ESPACO_ENTRE_GATILHO_E_PAINEL,
      bottom: abrirAcima
        ? alturaViewport - retangulo.top + ESPACO_ENTRE_GATILHO_E_PAINEL
        : undefined,
      left,
      width,
      maxHeight,
    });
  }, []);

  useEffect(() => {
    if (!aberto) {
      setPosicaoPainel(null);
      return undefined;
    }

    atualizarPosicaoPainel();
    const handleScroll = (event: Event) => {
      if (painelRef.current?.contains(event.target as Node)) {
        return;
      }
      atualizarPosicaoPainel();
    };
    window.addEventListener("resize", atualizarPosicaoPainel);
    window.addEventListener("scroll", handleScroll, true);
    return () => {
      window.removeEventListener("resize", atualizarPosicaoPainel);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [aberto, atualizarPosicaoPainel]);

  useEffect(() => {
    try {
      const idsSalvos = JSON.parse(
        localStorage.getItem(STORAGE_CONCLUSOES_RECENTES) || "[]",
      );
      if (Array.isArray(idsSalvos)) {
        setIdsRecentes(
          idsSalvos
            .map((id) => String(id || ""))
            .filter(Boolean)
            .slice(0, LIMITE_CONCLUSOES_RECENTES),
        );
      }
    } catch {
      setIdsRecentes([]);
    }
  }, []);

  useEffect(() => {
    if (!aberto) {
      return undefined;
    }

    const fechar = () => {
      setAberto(false);
      setBusca("");
      setAtalhoAtivo("");
    };
    const handlePointerDown = (event: PointerEvent) => {
      const alvo = event.target as Node;
      if (
        seletorRef.current &&
        !seletorRef.current.contains(alvo) &&
        !painelRef.current?.contains(alvo)
      ) {
        fechar();
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        fechar();
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [aberto]);

  const frasesOrdenadas = useMemo(
    () =>
      [...frases]
        .filter(
          (frase) => Number(frase.ativo ?? 1) === 1 && frase.id !== undefined,
        )
        .sort(compararFrases),
    [frases],
  );

  const fraseSelecionada = useMemo(
    () => frasesOrdenadas.find((frase) => String(frase.id) === value) || null,
    [frasesOrdenadas, value],
  );
  const idsSelecionados = useMemo(
    () => new Set((multiple ? values : [value]).map(String).filter(Boolean)),
    [multiple, value, values],
  );
  const frasesSelecionadas = useMemo(
    () => frasesOrdenadas.filter((frase) => idsSelecionados.has(String(frase.id))),
    [frasesOrdenadas, idsSelecionados],
  );
  const temSelecao = multiple ? frasesSelecionadas.length > 0 : Boolean(fraseSelecionada);

  const atalhosDisponiveis = useMemo(
    () =>
      ATALHOS_CONCLUSAO.filter((atalho) =>
        frasesOrdenadas.some(atalho.corresponde),
      ),
    [frasesOrdenadas],
  );

  const frasesFiltradas = useMemo(() => {
    const buscaNormalizada = normalizarBusca(busca);
    const atalho = ATALHOS_CONCLUSAO.find((item) => item.key === atalhoAtivo);
    return frasesOrdenadas.filter((frase) => {
      if (atalho && !atalho.corresponde(frase)) {
        return false;
      }
      return (
        !buscaNormalizada || camposBuscaFrase(frase).includes(buscaNormalizada)
      );
    });
  }, [atalhoAtivo, busca, frasesOrdenadas]);

  const grupos = useMemo<GrupoConclusoes[]>(() => {
    const mapa = new Map<string, FraseEcoEstruturadoTeste[]>();
    frasesFiltradas.forEach((frase) => {
      const patologias = (frase.patologias || [])
        .map((patologia) => String(patologia || "").trim())
        .filter(Boolean);
      const gruposDaFrase = patologias.length
        ? Array.from(new Set(patologias))
        : [GRUPO_SEM_CLASSIFICACAO];
      gruposDaFrase.forEach((grupo) => {
        mapa.set(grupo, [...(mapa.get(grupo) || []), frase]);
      });
    });

    return Array.from(mapa.entries())
      .sort(([grupoA], [grupoB]) => ordenarGrupos(grupoA, grupoB))
      .map(([label, itens]) => ({ label, frases: itens.sort(compararFrases) }));
  }, [frasesFiltradas]);

  const frasesRecentes = useMemo(() => {
    const porId = new Map(
      frasesOrdenadas.map((frase) => [String(frase.id), frase]),
    );
    return idsRecentes
      .map((id) => porId.get(id))
      .filter(Boolean) as FraseEcoEstruturadoTeste[];
  }, [frasesOrdenadas, idsRecentes]);

  const filtrosAtivos = Boolean(normalizarBusca(busca) || atalhoAtivo);

  const fecharSeletor = () => {
    setAberto(false);
    setBusca("");
    setAtalhoAtivo("");
  };

  const selecionarFrase = (fraseId: string) => {
    const adicionandoSelecao = !idsSelecionados.has(fraseId);
    if (multiple) {
      const proximosIds = !adicionandoSelecao
        ? values.filter((id) => String(id) !== fraseId)
        : [...values.map(String), fraseId];
      onValuesChange?.(Array.from(new Set(proximosIds)));
    } else {
      onChange?.(fraseId);
    }
    if (fraseId && (!multiple || adicionandoSelecao)) {
      const proximosIds = [
        fraseId,
        ...idsRecentes.filter((id) => id !== fraseId),
      ].slice(0, LIMITE_CONCLUSOES_RECENTES);
      setIdsRecentes(proximosIds);
      try {
        localStorage.setItem(
          STORAGE_CONCLUSOES_RECENTES,
          JSON.stringify(proximosIds),
        );
      } catch {
        // O historico local e apenas uma conveniencia; a selecao clinica nao depende dele.
      }
    }
    if (!multiple) {
      fecharSeletor();
    }
  };

  const alternarGrupo = (grupo: string) => {
    if (filtrosAtivos) {
      return;
    }
    setGruposExpandidos((atuais) => {
      const proximos = new Set(atuais);
      if (proximos.has(grupo)) {
        proximos.delete(grupo);
      } else {
        proximos.add(grupo);
      }
      return proximos;
    });
  };

  const renderizarFrase = (frase: FraseEcoEstruturadoTeste) => {
    const fraseId = String(frase.id);
    const selecionada = idsSelecionados.has(fraseId);
    return (
      <button
        key={fraseId}
        type="button"
        onClick={() => selecionarFrase(fraseId)}
        aria-pressed={selecionada}
        className={`flex w-full items-start gap-2 rounded-md border px-3 py-2 text-left text-sm transition ${
          selecionada
            ? "border-teal-300 bg-teal-50 text-teal-800"
            : "border-transparent bg-white text-gray-700 hover:border-gray-200 hover:bg-gray-50"
        }`}
      >
        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
          {selecionada ? <Check className="h-4 w-4" /> : null}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-medium">{frase.titulo}</span>
          <span className="mt-0.5 block text-xs text-gray-500">
            {resumirTexto(frase.texto, 130)}
          </span>
          {(frase.tags || []).length ? (
            <span className="mt-1 flex flex-wrap gap-1">
              {(frase.tags || []).slice(0, 4).map((tag) => (
                <span
                  key={tag}
                  className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600"
                >
                  {tag}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      </button>
    );
  };

  return (
    <div ref={seletorRef} className="relative min-w-0 flex-1">
      <button
        type="button"
        onClick={() => setAberto((atual) => !atual)}
        aria-expanded={aberto}
        aria-controls="seletor-frases-conclusao"
        className="flex min-h-[42px] w-full items-center justify-between gap-3 rounded-lg border border-gray-300 bg-white px-3 py-2 text-left text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
      >
        <span
          className={
            temSelecao ? "truncate text-gray-900" : "text-gray-500"
          }
        >
          {multiple
            ? frasesSelecionadas.length
              ? `${frasesSelecionadas.length} frase(s) selecionada(s)`
              : "Selecionar frases para compor"
            : fraseSelecionada?.titulo || "Selecionar frase do banco"}
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-gray-500 transition-transform ${aberto ? "rotate-180" : ""}`}
        />
      </button>

      {aberto && posicaoPainel && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={painelRef}
              id="seletor-frases-conclusao"
              data-testid="seletor-frases-conclusao-painel"
              role="dialog"
              aria-label={
                multiple
                  ? "Selecionar frases para compor a conclusão"
                  : "Selecionar frase de conclusão"
              }
              style={posicaoPainel}
              className="fixed z-[100] flex flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl"
            >
              <div className="shrink-0 space-y-3 border-b border-gray-100 p-3">
                <div className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 focus-within:ring-2 focus-within:ring-teal-500">
                  <Search className="h-4 w-4 shrink-0 text-gray-400" />
                  <input
                    type="text"
                    value={busca}
                    onChange={(event) => setBusca(event.target.value)}
                    placeholder="Buscar por título, texto, patologia ou tag"
                    aria-label="Buscar conclusão"
                    className="min-w-0 flex-1 border-0 p-0 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-0"
                    autoFocus
                  />
                  {busca ? (
                    <button
                      type="button"
                      onClick={() => setBusca("")}
                      className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                      aria-label="Limpar busca de conclusão"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  ) : null}
                </div>

                {atalhosDisponiveis.length ? (
                  <div className="flex items-center gap-2 overflow-x-auto pb-1">
                    <span className="shrink-0 text-xs font-medium text-gray-500">
                      Atalhos:
                    </span>
                    {atalhosDisponiveis.map((atalho) => (
                      <button
                        key={atalho.key}
                        type="button"
                        onClick={() =>
                          setAtalhoAtivo((atual) =>
                            atual === atalho.key ? "" : atalho.key,
                          )
                        }
                        aria-pressed={atalhoAtivo === atalho.key}
                        className={`shrink-0 rounded-full border px-3 py-1 text-xs font-medium ${
                          atalhoAtivo === atalho.key
                            ? "border-teal-500 bg-teal-50 text-teal-700"
                            : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
                        }`}
                      >
                        {atalho.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain bg-gray-50/60 p-2">
                {!filtrosAtivos && frasesRecentes.length ? (
                  <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                    <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-3 py-2 text-sm font-medium text-gray-900">
                      <span className="flex items-center gap-2">
                        <Clock3 className="h-4 w-4 text-teal-600" />
                        Recentes
                      </span>
                      <span className="text-xs font-normal text-gray-500">
                        {frasesRecentes.length}
                      </span>
                    </div>
                    <div className="space-y-1 p-2">
                      {frasesRecentes.map(renderizarFrase)}
                    </div>
                  </section>
                ) : null}

                {grupos.length ? (
                  grupos.map((grupo, index) => {
                    const expandido =
                      filtrosAtivos || gruposExpandidos.has(grupo.label);
                    const conteudoId = `grupo-conclusoes-${index}`;
                    return (
                      <section
                        key={grupo.label}
                        className="overflow-hidden rounded-lg border border-gray-200 bg-white"
                      >
                        <button
                          type="button"
                          onClick={() => alternarGrupo(grupo.label)}
                          aria-expanded={expandido}
                          aria-controls={conteudoId}
                          className="flex w-full items-center justify-between gap-3 px-3 py-3 text-left text-sm font-medium text-gray-900 transition hover:bg-gray-50"
                        >
                          <span className="flex min-w-0 items-center gap-2">
                            {expandido ? (
                              <ChevronDown className="h-4 w-4 shrink-0 text-teal-600" />
                            ) : (
                              <ChevronRight className="h-4 w-4 shrink-0 text-teal-600" />
                            )}
                            <span className="truncate">{grupo.label}</span>
                          </span>
                          <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-normal text-gray-600">
                            {grupo.frases.length}{" "}
                            {grupo.frases.length === 1 ? "frase" : "frases"}
                          </span>
                        </button>
                        {expandido ? (
                          <div
                            id={conteudoId}
                            className="space-y-1 border-t border-gray-100 bg-gray-50/60 p-2"
                          >
                            {grupo.frases.map(renderizarFrase)}
                          </div>
                        ) : null}
                      </section>
                    );
                  })
                ) : (
                  <div className="rounded-lg border border-dashed border-gray-300 bg-white px-3 py-8 text-center text-sm text-gray-500">
                    Nenhuma conclusão encontrada.
                  </div>
                )}
              </div>
              {multiple ? (
                <div className="flex shrink-0 items-center justify-between gap-3 border-t border-gray-100 bg-white px-3 py-2">
                  <span className="text-xs text-gray-500">
                    {frasesSelecionadas.length} selecionada(s)
                  </span>
                  <button
                    type="button"
                    onClick={fecharSeletor}
                    className="rounded-lg bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700"
                  >
                    Concluir seleção
                  </button>
                </div>
              ) : null}
            </div>,
            document.body,
          )
        : null}

      {multiple && frasesSelecionadas.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {frasesSelecionadas.map((frase) => (
            <span
              key={frase.id}
              className="rounded-full border border-teal-100 bg-teal-50 px-2 py-1 text-xs text-teal-800"
            >
              {frase.titulo}
            </span>
          ))}
        </div>
      ) : fraseSelecionada ? (
        <div className="mt-2 rounded-lg border border-teal-100 bg-teal-50/60 px-3 py-2">
          <div className="text-xs font-medium text-teal-800">
            Prévia da frase selecionada
          </div>
          <p className="mt-1 text-xs text-gray-600">
            {resumirTexto(fraseSelecionada.texto)}
          </p>
        </div>
      ) : null}
    </div>
  );
}
