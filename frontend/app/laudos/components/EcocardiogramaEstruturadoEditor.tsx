"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Layers3, Loader2, RefreshCw, Search, X } from "lucide-react";

import {
  type AspectoEcoEstruturadoTeste,
  type PayloadEcoEstruturadoTeste,
  type PresetEcoEstruturadoTeste,
  ordenarAspectos,
  presetCompativelComEspecie,
} from "@/lib/ecocardiograma-estruturado-teste";
import {
  aplicarPresetEcoEstruturadoTeste,
  atualizarFraseEcoEstruturadoTeste,
  carregarBancoEcoEstruturadoTeste,
  criarFraseEcoEstruturadoTeste,
  excluirPresetEcoEstruturadoTeste,
  salvarPresetEcoEstruturadoTeste,
} from "@/lib/frases-ecocardiograma-estruturado-teste-api";
import {
  type EcocardiogramaEstruturadoPersistido,
  normalizarEcocardiogramaEstruturado,
} from "@/lib/ecocardiograma-estruturado";
import {
  comporConclusaoDeFrases,
  comporRascunhoConclusaoDosAchados,
  type FormatoConclusaoEco,
  obterOpcoesDeGrauRelacionadas,
} from "@/lib/ecocardiograma-compositor";

import SeletorFraseConclusao from "./SeletorFraseConclusao";

interface EcocardiogramaEstruturadoEditorProps {
  value: EcocardiogramaEstruturadoPersistido;
  onChange: (next: EcocardiogramaEstruturadoPersistido) => void;
  especie?: string;
}

interface PresetForm {
  id?: number;
  label: string;
  key: string;
  patologia: string;
  grau: string;
  descricao: string;
  tags: string;
  ordem: string;
  selecoes: Record<string, string>;
}

type PresetSelecaoStatus = "matched" | "pending" | "empty" | "manual";

interface PresetDeteccaoInfo {
  status: PresetSelecaoStatus;
  textoAtual?: string;
}

interface ResultadoDeteccaoPreset {
  selecoes: Record<string, string>;
  deteccao: Record<string, PresetDeteccaoInfo>;
  totalComTexto: number;
  totalResolvido: number;
}

type OrigemAspectoStatus = "preset" | "alterado" | "manual" | "empty";
type ModoPreenchimentoEco = "preset" | "compositor";

interface SincronizacaoFraseOptions {
  silencioso?: boolean;
}

interface GrupoPresets {
  label: string;
  presets: PresetEcoEstruturadoTeste[];
}

const FILTRO_TODOS_PRESETS = "Todos";

function normalizarBuscaPreset(valor: string): string {
  return valor
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function getGrupoPreset(preset: PresetEcoEstruturadoTeste): string {
  return (
    String(preset.patologia || "").trim() ||
    (preset.tags || []).find((tag) => String(tag || "").trim()) ||
    "Sem classificacao"
  );
}

function normalizarTagsInput(tags: string): string[] {
  return tags
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function criarSelecoesPresetVazias(
  aspectos: AspectoEcoEstruturadoTeste[]
): Record<string, string> {
  return aspectos.reduce<Record<string, string>>((acc, aspecto) => {
    acc[aspecto.key] = "";
    return acc;
  }, {});
}

function resumirTexto(texto?: string, limite = 120): string {
  const normalizado = String(texto || "").replace(/\s+/g, " ").trim();
  if (normalizado.length <= limite) {
    return normalizado;
  }
  return `${normalizado.slice(0, limite - 3)}...`;
}

function getSelecaoStatusLabel(status: PresetSelecaoStatus): string {
  switch (status) {
    case "matched":
      return "Reconhecido";
    case "pending":
      return "Pendente";
    case "manual":
      return "Manual";
    default:
      return "Sem texto";
  }
}

function getSelecaoStatusClasses(status: PresetSelecaoStatus): string {
  switch (status) {
    case "matched":
      return "border-green-200 bg-green-50 text-green-700";
    case "pending":
      return "border-amber-200 bg-amber-50 text-amber-700";
    case "manual":
      return "border-blue-200 bg-blue-50 text-blue-700";
    default:
      return "border-gray-200 bg-gray-50 text-gray-500";
  }
}

function getOrigemAspectoLabel(status: OrigemAspectoStatus): string {
  switch (status) {
    case "preset":
      return "Do preset";
    case "alterado":
      return "Alterado";
    case "manual":
      return "Manual";
    default:
      return "Sem texto";
  }
}

function getOrigemAspectoClasses(status: OrigemAspectoStatus): string {
  switch (status) {
    case "preset":
      return "border-teal-200 bg-teal-50 text-teal-700";
    case "alterado":
      return "border-amber-200 bg-amber-50 text-amber-700";
    case "manual":
      return "border-blue-200 bg-blue-50 text-blue-700";
    default:
      return "border-gray-200 bg-gray-50 text-gray-500";
  }
}

function atualizarEstrutura(
  atual: EcocardiogramaEstruturadoPersistido,
  patch: Partial<EcocardiogramaEstruturadoPersistido>
): EcocardiogramaEstruturadoPersistido {
  return {
    ...atual,
    ...patch,
    updated_at: new Date().toISOString(),
  };
}

export default function EcocardiogramaEstruturadoEditor({
  value,
  onChange,
  especie,
}: EcocardiogramaEstruturadoEditorProps) {
  const [payload, setPayload] = useState<PayloadEcoEstruturadoTeste | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [error, setError] = useState("");
  const [hint, setHint] = useState("");
  const [presetSelecionadoId, setPresetSelecionadoId] = useState("");
  const [buscaPreset, setBuscaPreset] = useState("");
  const [grupoPresetFiltro, setGrupoPresetFiltro] = useState(FILTRO_TODOS_PRESETS);
  const [seletorPresetsAberto, setSeletorPresetsAberto] = useState(false);
  const [modoPreenchimento, setModoPreenchimento] = useState<ModoPreenchimentoEco>("preset");
  const [fraseSelecionadaPorAspecto, setFraseSelecionadaPorAspecto] = useState<Record<string, string>>(
    {}
  );
  const [conclusoesCompostasIds, setConclusoesCompostasIds] = useState<string[]>([]);
  const [formatoConclusao, setFormatoConclusao] = useState<FormatoConclusaoEco>("topicos");
  const [rascunhoConclusao, setRascunhoConclusao] = useState("");
  const [rascunhoConclusaoEditado, setRascunhoConclusaoEditado] = useState(false);
  const [assinaturaRascunhoConclusao, setAssinaturaRascunhoConclusao] = useState("");
  const [aplicandoPreset, setAplicandoPreset] = useState(false);
  const [salvandoPreset, setSalvandoPreset] = useState(false);
  const [atualizandoPresetSelecionado, setAtualizandoPresetSelecionado] = useState(false);
  const [propagandoFrasesSelecionadas, setPropagandoFrasesSelecionadas] = useState(false);
  const [salvandoNovaFraseAspecto, setSalvandoNovaFraseAspecto] = useState<string | null>(null);
  const [presetFormAberto, setPresetFormAberto] = useState(false);
  const [filtroAspectosPreset, setFiltroAspectosPreset] = useState<"all" | "pending">("all");
  const [presetDeteccao, setPresetDeteccao] = useState<Record<string, PresetDeteccaoInfo>>({});
  const [presetForm, setPresetForm] = useState<PresetForm>({
    label: "",
    key: "",
    patologia: "",
    grau: "",
    descricao: "",
    tags: "",
    ordem: "",
    selecoes: {},
  });
  const seletorPresetsRef = useRef<HTMLDivElement | null>(null);

  const estado = normalizarEcocardiogramaEstruturado(value);

  const carregarPayload = async (silencioso = false) => {
    try {
      setError("");
      setHint("");
      if (silencioso) {
        setReloading(true);
      } else {
        setLoading(true);
      }
      setPayload(await carregarBancoEcoEstruturadoTeste());
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Nao foi possivel carregar o banco estruturado de ecocardiograma."
      );
    } finally {
      setLoading(false);
      setReloading(false);
    }
  };

  useEffect(() => {
    carregarPayload();
  }, []);

  useEffect(() => {
    if (!seletorPresetsAberto) {
      return undefined;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (
        seletorPresetsRef.current &&
        !seletorPresetsRef.current.contains(event.target as Node)
      ) {
        setSeletorPresetsAberto(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [seletorPresetsAberto]);

  const aspectos = useMemo(
    () => ordenarAspectos(payload?.aspectos || []),
    [payload]
  );

  const presets = useMemo(
    () =>
      [...(payload?.presets || [])]
        .filter((preset) => Number(preset.ativo ?? 1) === 1)
        .filter((preset) => presetCompativelComEspecie(preset, especie))
        .sort((a, b) => {
          if ((a.ordem || 999) !== (b.ordem || 999)) {
            return (a.ordem || 999) - (b.ordem || 999);
          }
          return (a.label || "").localeCompare(b.label || "");
        }),
    [payload, especie]
  );
  const gruposPresetDisponiveis = useMemo(() => {
    const grupos = new Set<string>();
    presets.forEach((preset) => grupos.add(getGrupoPreset(preset)));
    return [FILTRO_TODOS_PRESETS, ...Array.from(grupos).sort((a, b) => a.localeCompare(b))];
  }, [presets]);
  const presetsFiltrados = useMemo(() => {
    const buscaNormalizada = normalizarBuscaPreset(buscaPreset);
    return presets.filter((preset) => {
      const grupo = getGrupoPreset(preset);
      if (grupoPresetFiltro !== FILTRO_TODOS_PRESETS && grupo !== grupoPresetFiltro) {
        return false;
      }

      if (!buscaNormalizada) {
        return true;
      }

      const camposBusca = [
        preset.label,
        preset.key,
        preset.patologia,
        preset.grau,
        preset.descricao,
        ...(preset.tags || []),
      ]
        .filter(Boolean)
        .join(" ");

      return normalizarBuscaPreset(camposBusca).includes(buscaNormalizada);
    });
  }, [buscaPreset, grupoPresetFiltro, presets]);
  const presetsAgrupados = useMemo<GrupoPresets[]>(() => {
    const grupos = new Map<string, PresetEcoEstruturadoTeste[]>();
    presetsFiltrados.forEach((preset) => {
      const grupo = getGrupoPreset(preset);
      grupos.set(grupo, [...(grupos.get(grupo) || []), preset]);
    });

    return Array.from(grupos.entries())
      .sort(([grupoA], [grupoB]) => grupoA.localeCompare(grupoB))
      .map(([label, itens]) => ({ label, presets: itens }));
  }, [presetsFiltrados]);
  const presetAtualLabel = presetSelecionadoId
    ? presets.find((preset) => String(preset.id) === presetSelecionadoId)?.label ||
      "Preset selecionado"
    : "Selecione um preset";
  const totalPendentes = useMemo(
    () =>
      aspectos.filter((aspecto) => presetDeteccao[aspecto.key]?.status === "pending").length,
    [aspectos, presetDeteccao]
  );
  const aspectosFormularioPreset = useMemo(
    () =>
      filtroAspectosPreset === "pending"
        ? aspectos.filter((aspecto) => presetDeteccao[aspecto.key]?.status === "pending")
        : aspectos,
    [aspectos, filtroAspectosPreset, presetDeteccao]
  );

  const presetAtual = useMemo(
    () => presets.find((preset) => String(preset.id) === presetSelecionadoId) || null,
    [presets, presetSelecionadoId]
  );
  const presetAplicado = useMemo(
    () => presets.find((preset) => preset.id === estado.preset_id) || null,
    [presets, estado.preset_id]
  );
  const origemAspectos = useMemo(
    () =>
      aspectos.reduce<Record<string, OrigemAspectoStatus>>((acc, aspecto) => {
        const textoAtual = String(estado.textos[aspecto.key] || "").trim();
        const textoPreset = String(estado.preset_textos?.[aspecto.key] || "").trim();
        if (!textoAtual) {
          acc[aspecto.key] = "empty";
        } else if (textoPreset && textoAtual === textoPreset) {
          acc[aspecto.key] = "preset";
        } else if (textoPreset && textoAtual !== textoPreset) {
          acc[aspecto.key] = "alterado";
        } else {
          acc[aspecto.key] = "manual";
        }
        return acc;
      }, {}),
    [aspectos, estado.preset_textos, estado.textos]
  );
  const resumoOrigem = useMemo(() => {
    return aspectos.reduce(
      (acc, aspecto) => {
        const status = origemAspectos[aspecto.key];
        if (status === "preset") acc.preset += 1;
        if (status === "alterado") acc.alterado += 1;
        if (status === "manual") acc.manual += 1;
        return acc;
      },
      { preset: 0, alterado: 0, manual: 0 }
    );
  }, [aspectos, origemAspectos]);
  const fraseSelecionadaEfetivaPorAspecto = useMemo(
    () =>
      aspectos.reduce<Record<string, string>>((acc, aspecto) => {
        const frasesAtivas = (aspecto.frases || []).filter(
          (frase) => Number(frase.ativo ?? 1) === 1
        );

        const selecaoExplicita = String(fraseSelecionadaPorAspecto[aspecto.key] || "").trim();
        if (
          selecaoExplicita &&
          frasesAtivas.some((frase) => String(frase.id) === selecaoExplicita)
        ) {
          acc[aspecto.key] = selecaoExplicita;
          return acc;
        }

        const textoAtual = String(estado.textos[aspecto.key] || "").trim();
        const frasePorTexto = frasesAtivas.find(
          (frase) => String(frase.texto || "").trim() === textoAtual
        );
        if (frasePorTexto?.id) {
          acc[aspecto.key] = String(frasePorTexto.id);
          return acc;
        }

        const selecaoPreset =
          (presetAplicado?.selecoes_resolvidas || []).find(
            (selecao) => selecao.aspecto === aspecto.key && selecao.frase_id
          ) ||
          (presetAplicado?.selecoes || []).find((selecao) => selecao.aspecto === aspecto.key);

        if (selecaoPreset?.frase_id) {
          const frasePorId = frasesAtivas.find(
            (frase) => Number(frase.id) === Number(selecaoPreset.frase_id)
          );
          if (frasePorId?.id) {
            acc[aspecto.key] = String(frasePorId.id);
            return acc;
          }
        }

        if (selecaoPreset?.frase_titulo) {
          const frasePorTitulo = frasesAtivas.find(
            (frase) =>
              String(frase.titulo || "").trim() === String(selecaoPreset.frase_titulo || "").trim()
          );
          if (frasePorTitulo?.id) {
            acc[aspecto.key] = String(frasePorTitulo.id);
            return acc;
          }
        }

        acc[aspecto.key] = "";
        return acc;
      }, {}),
    [aspectos, estado.textos, fraseSelecionadaPorAspecto, presetAplicado]
  );
  const frasesConclusaoAtivas = useMemo(
    () =>
      (aspectos.find((aspecto) => aspecto.key === "conclusao")?.frases || []).filter(
        (frase) => Number(frase.ativo ?? 1) === 1,
      ),
    [aspectos],
  );
  const textoConclusaoComposta = useMemo(
    () =>
      comporConclusaoDeFrases(
        frasesConclusaoAtivas,
        conclusoesCompostasIds,
        formatoConclusao,
      ),
    [conclusoesCompostasIds, formatoConclusao, frasesConclusaoAtivas],
  );
  const achadosParaConclusao = useMemo(
    () =>
      aspectos
        .filter((aspecto) => aspecto.key !== "conclusao")
        .map((aspecto) => {
          const fraseId = fraseSelecionadaEfetivaPorAspecto[aspecto.key];
          const frase = (aspecto.frases || []).find(
            (item) =>
              String(item.id) === String(fraseId || "") && Number(item.ativo ?? 1) === 1,
          );
          return {
            aspecto: aspecto.key,
            label: aspecto.label,
            texto: String(estado.textos[aspecto.key] || "").trim(),
            frase,
            origem: origemAspectos[aspecto.key],
          };
        }),
    [aspectos, estado.textos, fraseSelecionadaEfetivaPorAspecto, origemAspectos],
  );
  const conclusaoBasePreset = String(estado.preset_textos?.conclusao || "").trim();
  const textoRascunhoAutomatico = useMemo(
    () =>
      comporRascunhoConclusaoDosAchados(
        achadosParaConclusao,
        formatoConclusao,
        conclusaoBasePreset,
      ),
    [achadosParaConclusao, conclusaoBasePreset, formatoConclusao],
  );
  const assinaturaAchadosConclusao = useMemo(
    () =>
      JSON.stringify({
        formato: formatoConclusao,
        conclusaoBase: conclusaoBasePreset,
        achados: achadosParaConclusao.map((achado) => [
          achado.aspecto,
          achado.texto,
          achado.frase?.id || null,
          achado.origem,
        ]),
      }),
    [achadosParaConclusao, conclusaoBasePreset, formatoConclusao],
  );
  const rascunhoConclusaoDesatualizado =
    rascunhoConclusaoEditado && assinaturaRascunhoConclusao !== assinaturaAchadosConclusao;

  useEffect(() => {
    if (modoPreenchimento !== "compositor" || rascunhoConclusaoEditado) {
      return;
    }
    setRascunhoConclusao(textoRascunhoAutomatico);
    setAssinaturaRascunhoConclusao(assinaturaAchadosConclusao);
  }, [
    assinaturaAchadosConclusao,
    modoPreenchimento,
    rascunhoConclusaoEditado,
    textoRascunhoAutomatico,
  ]);

  useEffect(() => {
    if (!presets.length) {
      setPresetSelecionadoId("");
      return;
    }

    if (estado.preset_id && presets.some((preset) => preset.id === estado.preset_id)) {
      setPresetSelecionadoId(String(estado.preset_id));
      return;
    }

    setPresetSelecionadoId((prev) =>
      prev && presets.some((preset) => String(preset.id) === prev)
        ? prev
        : String(presets[0].id)
    );
  }, [presets, estado.preset_id]);

  useEffect(() => {
    if (!gruposPresetDisponiveis.includes(grupoPresetFiltro)) {
      setGrupoPresetFiltro(FILTRO_TODOS_PRESETS);
    }
  }, [grupoPresetFiltro, gruposPresetDisponiveis]);

  useEffect(() => {
    setPresetForm((prev) => ({
      ...prev,
      selecoes: Object.keys(prev.selecoes || {}).length
        ? { ...criarSelecoesPresetVazias(aspectos), ...prev.selecoes }
        : criarSelecoesPresetVazias(aspectos),
    }));
  }, [aspectos]);

  const limparFormularioPreset = () => {
    setFiltroAspectosPreset("all");
    setPresetDeteccao({});
    setPresetForm({
      label: "",
      key: "",
      patologia: "",
      grau: "",
      descricao: "",
      tags: "",
      ordem: "",
      selecoes: criarSelecoesPresetVazias(aspectos),
    });
  };

  const carregarPresetNoFormulario = (
    preset: PresetEcoEstruturadoTeste,
    modo: "edit" | "duplicate"
  ) => {
    const selecoes = criarSelecoesPresetVazias(aspectos);
    (preset.selecoes || []).forEach((selecao) => {
      if (selecao.aspecto) {
        selecoes[selecao.aspecto] =
          selecao.frase_titulo || (selecao.frase_id ? String(selecao.frase_id) : "");
      }
    });

    const sufixo = modo === "duplicate" ? " copia" : "";
    const statusBase = aspectos.reduce<Record<string, PresetDeteccaoInfo>>((acc, aspecto) => {
      const temSelecao = Boolean(selecoes[aspecto.key]);
      acc[aspecto.key] = { status: temSelecao ? "manual" : "empty" };
      return acc;
    }, {});
    setFiltroAspectosPreset("all");
    setPresetDeteccao(statusBase);
    setPresetForm({
      id: modo === "edit" ? preset.id : undefined,
      label: `${preset.label || ""}${sufixo}`.trim(),
      key: modo === "edit" ? preset.key || "" : "",
      patologia: preset.patologia || "",
      grau: preset.grau || "",
      descricao: preset.descricao || "",
      tags: (preset.tags || []).join(", "),
      ordem: String(preset.ordem || ""),
      selecoes,
    });
    setPresetFormAberto(true);
  };

  const aplicarPreset = async (modo: "merge" | "reset") => {
    if (!presetSelecionadoId || !presetAtual) {
      return;
    }

    const complementar = (presetAtual.tags || []).includes("complementar");
    const modoEfetivo = complementar ? "merge" : modo;

    try {
      setAplicandoPreset(true);
      setError("");
      const responseData = await aplicarPresetEcoEstruturadoTeste(presetSelecionadoId);

      const textos = responseData?.textos || {};
      const preset = responseData?.preset || {};
      const selecoesResolvidas: Array<{ aspecto?: string; frase_id?: number | string | null }> =
        Array.isArray(responseData?.selecoes_resolvidas)
        ? responseData.selecoes_resolvidas
        : [];
      setFraseSelecionadaPorAspecto(
        selecoesResolvidas.reduce((acc: Record<string, string>, selecao) => {
          if (selecao?.aspecto && selecao?.frase_id != null) {
            acc[String(selecao.aspecto)] = String(selecao.frase_id);
          }
          return acc;
        }, {})
      );
      const conclusaoPreset = selecoesResolvidas.find(
        (selecao) => selecao?.aspecto === "conclusao" && selecao?.frase_id != null,
      );
      setConclusoesCompostasIds(
        conclusaoPreset?.frase_id != null ? [String(conclusaoPreset.frase_id)] : [],
      );
      onChange(
        atualizarEstrutura(estado, {
          preset_id: Number(preset.id || presetSelecionadoId),
          preset_label: String(preset.label || ""),
          preset_textos: { ...textos },
          textos:
            modoEfetivo === "reset"
              ? { ...textos }
              : { ...estado.textos, ...textos },
        })
      );
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Nao foi possivel aplicar o preset selecionado."
      );
    } finally {
      setAplicandoPreset(false);
    }
  };

  const abrirNovoPreset = () => {
    setError("");
    setHint("");
    limparFormularioPreset();
    setPresetFormAberto(true);
  };

  const detectarSelecaoAtualParaPreset = (): ResultadoDeteccaoPreset => {
    const selecoes = criarSelecoesPresetVazias(aspectos);
    const deteccao: Record<string, PresetDeteccaoInfo> = {};
    let totalComTexto = 0;
    let totalResolvido = 0;

    aspectos.forEach((aspecto) => {
      const textoAtual = String(estado.textos[aspecto.key] || "").trim();
      if (!textoAtual) {
        deteccao[aspecto.key] = { status: "empty" };
        return;
      }

      totalComTexto += 1;
      const frase = (aspecto.frases || []).find(
        (item) =>
          Number(item.ativo ?? 1) === 1 &&
          String(item.texto || "").trim() === textoAtual
      );

      if (frase?.titulo) {
        selecoes[aspecto.key] = frase.titulo;
        deteccao[aspecto.key] = { status: "matched", textoAtual };
        totalResolvido += 1;
      } else {
        deteccao[aspecto.key] = { status: "pending", textoAtual };
      }
    });

    return {
      selecoes,
      deteccao,
      totalComTexto,
      totalResolvido,
    };
  };

  const criarPresetDaSelecaoAtual = () => {
    const { selecoes, deteccao, totalComTexto, totalResolvido } =
      detectarSelecaoAtualParaPreset();

    const labelBase = presetAtual?.label?.trim() || "Novo preset";
    setPresetDeteccao(deteccao);
    setPresetForm({
      id: undefined,
      label: `${labelBase} copia`.trim(),
      key: "",
      patologia: presetAtual?.patologia || "",
      grau: presetAtual?.grau || "",
      descricao: "Preset criado a partir da selecao atual do laudo.",
      tags: (presetAtual?.tags || []).join(", "),
      ordem: presetAtual?.ordem ? String(presetAtual.ordem) : "",
      selecoes,
    });
    setPresetFormAberto(true);
    setError("");

    if (totalComTexto === 0) {
      setFiltroAspectosPreset("all");
      setHint("Nao ha textos estruturados preenchidos para converter em preset.");
      return;
    }

    if (totalResolvido < totalComTexto) {
      setFiltroAspectosPreset("pending");
      setHint(
        `Preset preenchido parcialmente: ${totalResolvido} de ${totalComTexto} aspectos bateram exatamente com frases do banco.`
      );
      return;
    }

    setFiltroAspectosPreset("all");
    setHint(`Preset preenchido automaticamente com ${totalResolvido} aspectos reconhecidos.`);
  };

  const atualizarPresetSelecionadoComSelecaoAtual = async () => {
    if (!presetAtual) {
      return;
    }

    const { selecoes, deteccao, totalComTexto, totalResolvido } =
      detectarSelecaoAtualParaPreset();

    setPresetDeteccao(deteccao);
    setError("");

    if (totalComTexto === 0) {
      setFiltroAspectosPreset("all");
      setHint("Nao ha textos estruturados preenchidos para atualizar o preset.");
      return;
    }

    if (totalResolvido < totalComTexto) {
      setFiltroAspectosPreset("pending");
      setPresetForm({
        id: presetAtual.id,
        label: presetAtual.label || "",
        key: presetAtual.key || "",
        patologia: presetAtual.patologia || "",
        grau: presetAtual.grau || "",
        descricao: presetAtual.descricao || "",
        tags: (presetAtual.tags || []).join(", "),
        ordem: presetAtual.ordem ? String(presetAtual.ordem) : "",
        selecoes,
      });
      setPresetFormAberto(true);
      setHint(
        `Nao foi possivel atualizar diretamente. ${totalResolvido} de ${totalComTexto} aspectos bateram com frases do banco. Resolva os pendentes e salve o preset.`
      );
      return;
    }

    const selecoesPayload = Object.entries(selecoes)
      .map(([aspecto, referencia]) => {
        const valor = String(referencia || "").trim();
        if (!valor) {
          return null;
        }

        const aspectoItem = aspectos.find((item) => item.key === aspecto);
        const frase = (aspectoItem?.frases || []).find((item) => {
          const titulo = String(item.titulo || "").trim();
          return titulo === valor || String(item.id) === valor;
        });

        return {
          aspecto,
          frase_id: frase?.id,
          frase_titulo: frase?.titulo || valor,
        };
      })
      .filter(Boolean);

    if (!selecoesPayload.length) {
      setHint("Nao ha selecoes validas para atualizar o preset.");
      return;
    }

    try {
      setAtualizandoPresetSelecionado(true);
      await salvarPresetEcoEstruturadoTeste(
        {
          label: presetAtual.label || "",
          key: presetAtual.key || "",
          patologia: presetAtual.patologia || "",
          grau: presetAtual.grau || "",
          descricao: presetAtual.descricao || "",
          tags: presetAtual.tags || [],
          ordem: presetAtual.ordem,
          selecoes: selecoesPayload,
        },
        presetAtual.id
      );
      await carregarPayload(true);
      const presetTextosAtualizados = Object.entries(estado.textos).reduce<Record<string, string>>(
        (acc, [aspecto, texto]) => {
          const valor = String(texto || "").trim();
          if (valor) {
            acc[aspecto] = valor;
          }
          return acc;
        },
        {}
      );
      onChange(
        atualizarEstrutura(estado, {
          preset_id: presetAtual.id,
          preset_label: presetAtual.label || "",
          preset_textos: presetTextosAtualizados,
        })
      );
      setFiltroAspectosPreset("all");
      setHint(`Preset "${presetAtual.label}" atualizado com a selecao atual do laudo.`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Nao foi possivel atualizar o preset selecionado.");
    } finally {
      setAtualizandoPresetSelecionado(false);
    }
  };

  const salvarPreset = async () => {
    const label = presetForm.label.trim();
    if (!label) {
      setError("Informe o nome do preset.");
      return;
    }

    const selecoes = Object.entries(presetForm.selecoes || {})
      .map(([aspecto, referencia]) => {
        const valor = String(referencia || "").trim();
        if (!valor) {
          return null;
        }

        const aspectoItem = aspectos.find((item) => item.key === aspecto);
        const frase = (aspectoItem?.frases || []).find((item) => {
          const titulo = String(item.titulo || "").trim();
          return titulo === valor || String(item.id) === valor;
        });

        return {
          aspecto,
          frase_id: frase?.id,
          frase_titulo: frase?.titulo || valor,
        };
      })
      .filter(Boolean);

    if (selecoes.length === 0) {
      setError("Selecione pelo menos uma frase para o preset.");
      return;
    }

    try {
      setSalvandoPreset(true);
      setError("");
      setHint("");
      const payloadPreset = {
        label,
        key: presetForm.key.trim(),
        patologia: presetForm.patologia.trim(),
        grau: presetForm.grau.trim(),
        descricao: presetForm.descricao.trim(),
        tags: normalizarTagsInput(presetForm.tags),
        ordem: presetForm.ordem.trim() ? Number(presetForm.ordem) : undefined,
        selecoes,
      };

      if (presetForm.id) {
        await salvarPresetEcoEstruturadoTeste(payloadPreset, presetForm.id);
      } else {
        await salvarPresetEcoEstruturadoTeste(payloadPreset);
      }

      await carregarPayload(true);
      setPresetFormAberto(false);
      limparFormularioPreset();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Nao foi possivel salvar o preset.");
    } finally {
      setSalvandoPreset(false);
    }
  };

  const excluirPreset = async () => {
    if (!presetAtual) {
      return;
    }
    if (!window.confirm(`Excluir o preset "${presetAtual.label}"?`)) {
      return;
    }

    try {
      setError("");
      setHint("");
      await excluirPresetEcoEstruturadoTeste(Number(presetAtual.id));
      await carregarPayload(true);
      if (presetForm.id === presetAtual.id) {
        setPresetFormAberto(false);
        limparFormularioPreset();
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Nao foi possivel excluir o preset.");
    }
  };

  const aplicarFraseDoAspecto = (
    aspecto: AspectoEcoEstruturadoTeste,
    fraseIdInformada?: string,
  ) => {
    const fraseId = fraseIdInformada || fraseSelecionadaEfetivaPorAspecto[aspecto.key];
    const frase = (aspecto.frases || []).find(
      (item) => String(item.id) === fraseId && Number(item.ativo ?? 1) === 1
    );
    if (!frase) {
      return;
    }

    setFraseSelecionadaPorAspecto((prev) => ({
      ...prev,
      [aspecto.key]: String(frase.id),
    }));
    onChange(
      atualizarEstrutura(estado, {
        textos: {
          ...estado.textos,
          [aspecto.key]: String(frase.texto || "").trim(),
        },
      })
    );
  };

  const ativarModoCompositor = () => {
    const conclusaoAtualId = fraseSelecionadaEfetivaPorAspecto.conclusao;
    setModoPreenchimento("compositor");
    setConclusoesCompostasIds((atuais) =>
      atuais.length || !conclusaoAtualId ? atuais : [conclusaoAtualId],
    );
  };

  const aplicarConclusaoComposta = () => {
    if (!textoConclusaoComposta) {
      return;
    }
    setFraseSelecionadaPorAspecto((prev) => ({ ...prev, conclusao: "" }));
    onChange(
      atualizarEstrutura(estado, {
        textos: {
          ...estado.textos,
          conclusao: textoConclusaoComposta,
        },
      }),
    );
    setHint(
      `${conclusoesCompostasIds.length} frase(s) aprovada(s) aplicadas à conclusão para revisão.`,
    );
  };

  const atualizarRascunhoConclusao = () => {
    setRascunhoConclusao(textoRascunhoAutomatico);
    setRascunhoConclusaoEditado(false);
    setAssinaturaRascunhoConclusao(assinaturaAchadosConclusao);
    setHint("Rascunho atualizado a partir dos achados atuais. Revise antes de aplicar.");
  };

  const aplicarRascunhoConclusao = () => {
    const textoRevisado = rascunhoConclusao.trim();
    if (!textoRevisado) {
      return;
    }
    setFraseSelecionadaPorAspecto((prev) => ({ ...prev, conclusao: "" }));
    onChange(
      atualizarEstrutura(estado, {
        textos: {
          ...estado.textos,
          conclusao: textoRevisado,
        },
      }),
    );
    setHint("Rascunho revisado aplicado à conclusão do laudo.");
  };

  const atualizarTextoFraseNoPayloadLocal = (
    aspectoKey: string,
    fraseId: number,
    textoAtualizado: string
  ) => {
    setPayload((atual) => {
      if (!atual) {
        return atual;
      }
      return {
        ...atual,
        aspectos: (atual.aspectos || []).map((aspecto) => {
          if (aspecto.key !== aspectoKey) {
            return aspecto;
          }
          return {
            ...aspecto,
            frases: (aspecto.frases || []).map((frase) =>
              Number(frase.id) === Number(fraseId)
                ? {
                    ...frase,
                    texto: textoAtualizado,
                  }
                : frase
            ),
          };
        }),
      };
    });
  };

  const sincronizarFraseSelecionadaDoAspecto = async (
    aspecto: AspectoEcoEstruturadoTeste,
    options: SincronizacaoFraseOptions = {}
  ): Promise<boolean> => {
    const { silencioso = false } = options;

    const fraseId = String(fraseSelecionadaEfetivaPorAspecto[aspecto.key] || "").trim();
    if (!fraseId) {
      if (!silencioso) {
        setError(`Selecione uma frase em ${aspecto.label} antes de atualizar o banco.`);
      }
      return false;
    }

    const frase = (aspecto.frases || []).find(
      (item) => String(item.id) === fraseId && Number(item.ativo ?? 1) === 1
    );
    if (!frase?.id) {
      if (!silencioso) {
        setError(`Nao foi possivel localizar a frase selecionada em ${aspecto.label}.`);
      }
      return false;
    }

    const textoAtual = String(estado.textos[aspecto.key] || "").trim();
    if (!textoAtual) {
      if (!silencioso) {
        setError(`O texto de ${aspecto.label} esta vazio.`);
      }
      return false;
    }

    const textoBanco = String(frase.texto || "").trim();
    if (textoBanco === textoAtual) {
      return false;
    }

    try {
      if (!silencioso) {
        setError("");
        setHint("");
      }
      await atualizarFraseEcoEstruturadoTeste(Number(frase.id), {
        aspecto: aspecto.key,
        titulo: String(frase.titulo || "").trim(),
        texto: textoAtual,
        tags: Array.isArray(frase.tags) ? frase.tags : [],
        patologias: Array.isArray(frase.patologias) ? frase.patologias : [],
        ordem: frase.ordem,
      });

      atualizarTextoFraseNoPayloadLocal(aspecto.key, Number(frase.id), textoAtual);
      return true;
    } catch (err: any) {
      if (!silencioso) {
        setError(err?.response?.data?.detail || "Nao foi possivel atualizar a frase do banco.");
      } else {
        console.error("Falha ao propagar frase para o banco:", err);
      }
      return false;
    }
  };

  const propagarTextosSelecionadosParaBanco = async () => {
    if (!presetAtual) {
      return;
    }

    const confirmar = window.confirm(
      "Atualizar no banco as frases selecionadas com os textos atuais? Isso afeta todos os presets que usam essas frases."
    );
    if (!confirmar) {
      return;
    }

    try {
      setPropagandoFrasesSelecionadas(true);
      setError("");
      setHint("");

      let totalAtualizado = 0;

      for (const aspecto of aspectos) {
        const atualizado = await sincronizarFraseSelecionadaDoAspecto(aspecto, {
          silencioso: true,
        });
        if (atualizado) {
          totalAtualizado += 1;
        }
      }

      if (totalAtualizado === 0) {
        setHint("Nenhuma frase precisou de atualizacao no banco.");
      } else {
        setHint(
          `${totalAtualizado} frase(s) atualizada(s) no banco. A mudanca vale para todos os presets que usam essas frases.`
        );
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Nao foi possivel propagar as frases para o banco.");
    } finally {
      setPropagandoFrasesSelecionadas(false);
    }
  };

  const salvarNovaFraseDoAspecto = async (aspecto: AspectoEcoEstruturadoTeste) => {
    const textoAtual = String(estado.textos[aspecto.key] || "").trim();
    if (!textoAtual) {
      setError(`O texto de ${aspecto.label} esta vazio.`);
      return;
    }

    const tituloPadrao =
      aspecto.key === "conclusao" ? "Nova conclusao personalizada" : `Nova frase - ${aspecto.label}`;
    const tituloInformado = window.prompt(
      `Titulo da nova frase para ${aspecto.label}:`,
      tituloPadrao
    );
    const titulo = String(tituloInformado || "").trim();
    if (!titulo) {
      return;
    }

    const tagsInformadas = window.prompt(
      "Tags opcionais separadas por virgula:",
      aspecto.key === "conclusao" ? "conclusao, personalizado" : ""
    );

    try {
      setSalvandoNovaFraseAspecto(aspecto.key);
      setError("");
      setHint("");
      const responseData = await criarFraseEcoEstruturadoTeste({
        aspecto: aspecto.key,
        titulo,
        texto: textoAtual,
        tags: normalizarTagsInput(String(tagsInformadas || "")),
      });
      const novaFraseId = String(responseData?.id || "").trim();
      await carregarPayload(true);
      if (novaFraseId) {
        setFraseSelecionadaPorAspecto((prev) => ({
          ...prev,
          [aspecto.key]: novaFraseId,
        }));
      }
      setHint(`Frase "${titulo}" salva no banco em ${aspecto.label}.`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Nao foi possivel salvar a nova frase.");
    } finally {
      setSalvandoNovaFraseAspecto(null);
    }
  };

  if (loading) {
    return (
      <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Carregando ecocardiograma estruturado...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h4 className="font-medium text-gray-900">Ecocardiograma estruturado</h4>
          <p className="text-sm text-gray-600">
            Presets e frases por aspecto. Quando ativo, os blocos legados abaixo passam
            a ser gerados a partir desta estrutura. Edições feitas no laudo ficam apenas
            neste exame; a biblioteca só muda por uma ação explícita.
          </p>
        </div>
        <button
          type="button"
          onClick={() => carregarPayload(true)}
          disabled={reloading}
          className="inline-flex items-center gap-2 self-start rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm text-blue-700 hover:bg-blue-100 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${reloading ? "animate-spin" : ""}`} />
          Recarregar banco
        </button>
      </div>

      <label className="flex items-start gap-3 rounded-lg border border-blue-200 bg-white p-3">
        <input
          type="checkbox"
          checked={estado.usar_no_laudo}
          onChange={(e) =>
            onChange(
              atualizarEstrutura(estado, {
                usar_no_laudo: e.target.checked,
              })
            )
          }
          className="mt-1 h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
        />
        <span className="text-sm text-gray-700">
          Usar o estruturado para preencher o laudo oficial.
        </span>
      </label>

      <div className="rounded-lg border border-blue-200 bg-white p-3">
        <div className="mb-2 text-sm font-medium text-gray-900">Modo de preenchimento</div>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Modo de preenchimento do ecocardiograma">
          <button
            type="button"
            aria-pressed={modoPreenchimento === "preset"}
            onClick={() => setModoPreenchimento("preset")}
            className={`rounded-lg border px-3 py-2 text-sm ${
              modoPreenchimento === "preset"
                ? "border-teal-400 bg-teal-50 text-teal-800"
                : "border-gray-300 text-gray-700 hover:bg-gray-50"
            }`}
          >
            Preset rápido
          </button>
          <button
            type="button"
            aria-pressed={modoPreenchimento === "compositor"}
            onClick={ativarModoCompositor}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
              modoPreenchimento === "compositor"
                ? "border-teal-400 bg-teal-50 text-teal-800"
                : "border-gray-300 text-gray-700 hover:bg-gray-50"
            }`}
          >
            <Layers3 className="h-4 w-4" />
            Combinar achados
          </button>
        </div>
        <p className="mt-2 text-xs text-gray-500">
          {modoPreenchimento === "preset"
            ? "Use um preset completo para os exames que se encaixam no padrão habitual."
            : "Use o preset como base e substitua cada aspecto por uma única frase aprovada. A conclusão pode combinar várias frases."}
        </p>
      </div>

      {estado.preset_label ? (
        <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700">
          <span className="font-medium text-gray-900">Preset ativo:</span> {estado.preset_label}
          <span className="ml-3 text-gray-500">
            {resumoOrigem.preset} do preset, {resumoOrigem.alterado} alterado, {resumoOrigem.manual} manual
          </span>
        </div>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_auto]">
        <div ref={seletorPresetsRef} className="relative">
          <button
            type="button"
            onClick={() => setSeletorPresetsAberto((prev) => !prev)}
            className="flex min-h-[42px] w-full items-center justify-between gap-3 rounded-lg border border-gray-300 bg-white px-3 py-2 text-left text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
            aria-expanded={seletorPresetsAberto}
          >
            <span className={presetSelecionadoId ? "truncate text-gray-900" : "text-gray-500"}>
              {presetAtualLabel}
            </span>
            <ChevronDown
              className={`h-4 w-4 shrink-0 text-gray-500 transition-transform ${
                seletorPresetsAberto ? "rotate-180" : ""
              }`}
            />
          </button>

          {seletorPresetsAberto ? (
            <div className="absolute z-30 mt-2 w-full overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl">
              <div className="space-y-3 border-b border-gray-100 p-3">
                <div className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 focus-within:ring-2 focus-within:ring-teal-500">
                  <Search className="h-4 w-4 shrink-0 text-gray-400" />
                  <input
                    type="text"
                    value={buscaPreset}
                    onChange={(e) => setBuscaPreset(e.target.value)}
                    placeholder="Buscar por nome, patologia, grau ou tag"
                    className="min-w-0 flex-1 border-0 p-0 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-0"
                    autoFocus
                  />
                  {buscaPreset ? (
                    <button
                      type="button"
                      onClick={() => setBuscaPreset("")}
                      className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                      aria-label="Limpar busca"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  ) : null}
                </div>

                <div className="flex gap-2 overflow-x-auto pb-1">
                  {gruposPresetDisponiveis.map((grupo) => (
                    <button
                      key={grupo}
                      type="button"
                      onClick={() => setGrupoPresetFiltro(grupo)}
                      className={`shrink-0 rounded-full border px-3 py-1 text-xs font-medium ${
                        grupoPresetFiltro === grupo
                          ? "border-teal-500 bg-teal-50 text-teal-700"
                          : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
                      }`}
                    >
                      {grupo}
                    </button>
                  ))}
                </div>
              </div>

              <div className="max-h-80 overflow-y-auto p-2">
                {presetsAgrupados.length ? (
                  presetsAgrupados.map((grupo) => (
                    <div key={grupo.label} className="py-1">
                      <div className="px-2 py-1 text-xs font-semibold uppercase text-gray-500">
                        {grupo.label}
                      </div>
                      <div className="space-y-1">
                        {grupo.presets.map((preset) => {
                          const selecionado = String(preset.id) === presetSelecionadoId;
                          return (
                            <button
                              key={preset.id}
                              type="button"
                              onClick={() => {
                                setPresetSelecionadoId(String(preset.id));
                                setSeletorPresetsAberto(false);
                              }}
                              className={`flex w-full items-start gap-2 rounded-md px-2 py-2 text-left text-sm ${
                                selecionado
                                  ? "bg-blue-50 text-blue-700"
                                  : "text-gray-700 hover:bg-gray-50"
                              }`}
                            >
                              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
                                {selecionado ? <Check className="h-4 w-4" /> : null}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block font-medium">{preset.label}</span>
                                {[preset.grau, ...(preset.tags || [])]
                                  .filter(Boolean)
                                  .slice(0, 3)
                                  .length ? (
                                  <span className="mt-0.5 block truncate text-xs text-gray-500">
                                    {[preset.grau, ...(preset.tags || [])]
                                      .filter(Boolean)
                                      .slice(0, 3)
                                      .join(" | ")}
                                  </span>
                                ) : null}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="px-3 py-6 text-center text-sm text-gray-500">
                    Nenhum preset encontrado.
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>
        {modoPreenchimento === "compositor" ? (
          <button
            type="button"
            onClick={() => aplicarPreset(presetAtual?.tags?.includes("complementar") ? "merge" : "reset")}
            disabled={!presetSelecionadoId || aplicandoPreset}
            className="rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm text-teal-700 hover:bg-teal-50 disabled:opacity-50 lg:col-span-2"
          >
            {presetAtual?.tags?.includes("complementar") ? "Aplicar ao laudo atual" : "Aplicar como preset base"}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => aplicarPreset("merge")}
              disabled={!presetSelecionadoId || aplicandoPreset}
              className="rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm text-teal-700 hover:bg-teal-50 disabled:opacity-50"
            >
              Aplicar sobre atual
            </button>
            {!presetAtual?.tags?.includes("complementar") ? (
              <button
                type="button"
                onClick={() => aplicarPreset("reset")}
                disabled={!presetSelecionadoId || aplicandoPreset}
                className="rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
              >
                Zerar e aplicar
              </button>
            ) : null}
          </>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={abrirNovoPreset}
          className="rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm text-teal-700 hover:bg-teal-50"
        >
          Novo preset
        </button>
        <button
          type="button"
          onClick={criarPresetDaSelecaoAtual}
          className="rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm text-blue-700 hover:bg-blue-50"
        >
          Criar preset da selecao atual
        </button>
        <button
          type="button"
          onClick={atualizarPresetSelecionadoComSelecaoAtual}
          disabled={!presetAtual || atualizandoPresetSelecionado}
          className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm text-amber-700 hover:bg-amber-50 disabled:opacity-50"
        >
          {atualizandoPresetSelecionado ? "Atualizando preset..." : "Atualizar preset"}
        </button>
        <button
          type="button"
          onClick={propagarTextosSelecionadosParaBanco}
          disabled={!presetAtual || propagandoFrasesSelecionadas}
          className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
        >
          {propagandoFrasesSelecionadas ? "Propagando frases..." : "Propagar frases para banco"}
        </button>
        <button
          type="button"
          onClick={() => presetAtual && carregarPresetNoFormulario(presetAtual, "edit")}
          disabled={!presetAtual}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Editar preset
        </button>
        <button
          type="button"
          onClick={() => presetAtual && carregarPresetNoFormulario(presetAtual, "duplicate")}
          disabled={!presetAtual}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Duplicar preset
        </button>
        <button
          type="button"
          onClick={excluirPreset}
          disabled={!presetAtual}
          className="rounded-lg border border-red-300 bg-white px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
        >
          Excluir preset
        </button>
      </div>

      {presetFormAberto ? (
        <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <h5 className="text-sm font-medium text-gray-900">
              {presetForm.id ? "Editar preset" : "Novo preset"}
            </h5>
            <button
              type="button"
              onClick={() => {
                setPresetFormAberto(false);
                limparFormularioPreset();
              }}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Fechar
            </button>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <input
              value={presetForm.label}
              onChange={(e) => setPresetForm((prev) => ({ ...prev, label: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
              placeholder="Nome do preset"
            />
            <input
              value={presetForm.key}
              onChange={(e) => setPresetForm((prev) => ({ ...prev, key: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
              placeholder="Chave opcional"
            />
            <input
              value={presetForm.patologia}
              onChange={(e) => setPresetForm((prev) => ({ ...prev, patologia: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
              placeholder="Patologia"
            />
            <input
              value={presetForm.grau}
              onChange={(e) => setPresetForm((prev) => ({ ...prev, grau: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
              placeholder="Grau"
            />
            <input
              value={presetForm.tags}
              onChange={(e) => setPresetForm((prev) => ({ ...prev, tags: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500 md:col-span-2"
              placeholder="Tags separadas por virgula"
            />
            <input
              value={presetForm.ordem}
              onChange={(e) => setPresetForm((prev) => ({ ...prev, ordem: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
              placeholder="Ordem"
            />
            <textarea
              value={presetForm.descricao}
              onChange={(e) => setPresetForm((prev) => ({ ...prev, descricao: e.target.value }))}
              rows={3}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500 md:col-span-2"
              placeholder="Descricao do preset"
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <div className="text-sm text-gray-600">
              Aspectos no formulario:{" "}
              <span className="font-medium text-gray-900">
                {aspectosFormularioPreset.length}
              </span>
              {filtroAspectosPreset === "pending" ? (
                <span className="text-gray-500"> de {aspectos.length}</span>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setFiltroAspectosPreset("all")}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  filtroAspectosPreset === "all"
                    ? "border-teal-300 bg-teal-50 text-teal-700"
                    : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                }`}
              >
                Todos
              </button>
              <button
                type="button"
                onClick={() => setFiltroAspectosPreset("pending")}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  filtroAspectosPreset === "pending"
                    ? "border-amber-300 bg-amber-50 text-amber-700"
                    : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                }`}
              >
                Pendentes ({totalPendentes})
              </button>
            </div>
          </div>

          <div className="space-y-3">
            {!aspectosFormularioPreset.length && filtroAspectosPreset === "pending" ? (
              <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
                Nao ha aspectos pendentes neste preset.
              </div>
            ) : null}

            {aspectosFormularioPreset.map((aspecto) => {
              const frasesAtivas = (aspecto.frases || []).filter(
                (frase) => Number(frase.ativo ?? 1) === 1
              );
              const deteccao = presetDeteccao[aspecto.key] || { status: "empty" as PresetSelecaoStatus };
              return (
                <div key={aspecto.key} className="rounded-lg border border-gray-200 p-3">
                  <div className="mb-2 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                    <label className="text-sm font-medium text-gray-700">{aspecto.label}</label>
                    <span
                      className={`inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-xs font-medium ${getSelecaoStatusClasses(
                        deteccao.status
                      )}`}
                    >
                      {getSelecaoStatusLabel(deteccao.status)}
                    </span>
                  </div>
                  <select
                    value={presetForm.selecoes?.[aspecto.key] || ""}
                    onChange={(e) => {
                      const value = e.target.value;
                      setPresetForm((prev) => ({
                        ...prev,
                        selecoes: {
                          ...prev.selecoes,
                          [aspecto.key]: value,
                        },
                      }));
                      setPresetDeteccao((prev) => ({
                        ...prev,
                        [aspecto.key]: {
                          status: value ? "manual" : deteccao.textoAtual ? "pending" : "empty",
                          textoAtual: deteccao.textoAtual,
                        },
                      }));
                    }}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                  >
                    <option value="">Sem frase</option>
                    {frasesAtivas.map((frase) => (
                      <option key={frase.id} value={frase.titulo}>
                        {frase.titulo}
                      </option>
                    ))}
                  </select>
                  {deteccao.status === "pending" && deteccao.textoAtual ? (
                    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      Texto atual nao reconhecido automaticamente: &quot;{resumirTexto(deteccao.textoAtual)}&quot;
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={salvarPreset}
              disabled={salvandoPreset}
              className="rounded-lg bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-50"
            >
              {salvandoPreset ? "Salvando..." : presetForm.id ? "Atualizar preset" : "Salvar preset"}
            </button>
            <button
              type="button"
              onClick={() => {
                setPresetFormAberto(false);
                limparFormularioPreset();
              }}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >
              Cancelar
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {hint ? (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">
          {hint}
        </div>
      ) : null}

      <div className="space-y-4">
        {aspectos.map((aspecto) => {
          const frasesAtivas = (aspecto.frases || []).filter(
            (frase) => Number(frase.ativo ?? 1) === 1
          );
          const fraseSelecionadaId = fraseSelecionadaEfetivaPorAspecto[aspecto.key] || "";
          const opcoesDeGrau =
            aspecto.key === "conclusao"
              ? []
              : obterOpcoesDeGrauRelacionadas(frasesAtivas, fraseSelecionadaId);
          return (
            <div key={aspecto.key} className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="mb-2">
                <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                  <div className="text-sm font-medium text-gray-900">{aspecto.label}</div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-xs font-medium ${getOrigemAspectoClasses(
                        origemAspectos[aspecto.key]
                      )}`}
                    >
                      {getOrigemAspectoLabel(origemAspectos[aspecto.key])}
                    </span>
                  </div>
                </div>
                <div className="text-xs text-gray-500">{aspecto.placeholder}</div>
              </div>
              {modoPreenchimento === "compositor" && aspecto.key === "conclusao" ? (
                <div className="mb-3 space-y-3 rounded-lg border border-teal-100 bg-teal-50/40 p-3">
                  <div className="rounded-lg border border-teal-200 bg-white p-3">
                    <div className="text-sm font-semibold text-gray-900">
                      Rascunho automático dos achados
                    </div>
                    <p className="mt-1 text-xs text-gray-600">
                      Mantém integralmente a conclusão padrão do preset e acrescenta somente os
                      aspectos que você alterou ou preencheu manualmente. Não calcula estágio nem
                      cria diagnóstico.
                    </p>
                    <textarea
                      aria-label="Rascunho automático da conclusão"
                      value={rascunhoConclusao}
                      onChange={(event) => {
                        setRascunhoConclusao(event.target.value);
                        setRascunhoConclusaoEditado(true);
                      }}
                      placeholder="Escolha os achados acima para gerar o rascunho automaticamente."
                      rows={Math.max(4, Math.min(10, rascunhoConclusao.split("\n").length + 1))}
                      className="mt-3 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-100"
                    />
                    {rascunhoConclusaoDesatualizado ? (
                      <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                        Os achados mudaram depois da sua edição. Atualize o rascunho para refletir
                        as escolhas atuais; sua versão só será substituída ao confirmar.
                      </div>
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={atualizarRascunhoConclusao}
                        disabled={!textoRascunhoAutomatico}
                        className="rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm text-teal-700 hover:bg-teal-50 disabled:opacity-50"
                      >
                        Atualizar pelos achados
                      </button>
                      <button
                        type="button"
                        onClick={aplicarRascunhoConclusao}
                        disabled={!rascunhoConclusao.trim() || rascunhoConclusaoDesatualizado}
                        className="rounded-lg bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-50"
                      >
                        Aplicar rascunho revisado na conclusão
                      </button>
                    </div>
                  </div>
                  <div className="border-t border-teal-100 pt-3">
                    <div className="text-xs font-medium uppercase tracking-wide text-gray-500">
                      Ajuste opcional com frases prontas
                    </div>
                  </div>
                  <SeletorFraseConclusao
                    frases={frasesAtivas}
                    multiple
                    values={conclusoesCompostasIds}
                    onValuesChange={setConclusoesCompostasIds}
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-gray-600">Formato:</span>
                    <button
                      type="button"
                      aria-pressed={formatoConclusao === "topicos"}
                      onClick={() => setFormatoConclusao("topicos")}
                      className={`rounded-lg border px-3 py-1.5 text-xs ${
                        formatoConclusao === "topicos"
                          ? "border-teal-400 bg-white text-teal-800"
                          : "border-gray-300 bg-white text-gray-600"
                      }`}
                    >
                      Em tópicos
                    </button>
                    <button
                      type="button"
                      aria-pressed={formatoConclusao === "paragrafo"}
                      onClick={() => setFormatoConclusao("paragrafo")}
                      className={`rounded-lg border px-3 py-1.5 text-xs ${
                        formatoConclusao === "paragrafo"
                          ? "border-teal-400 bg-white text-teal-800"
                          : "border-gray-300 bg-white text-gray-600"
                      }`}
                    >
                      Em parágrafo
                    </button>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <div className="text-xs font-medium text-gray-700">Prévia da composição</div>
                    <div className="mt-1 whitespace-pre-wrap text-sm text-gray-600">
                      {textoConclusaoComposta || "Selecione uma ou mais frases aprovadas."}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={aplicarConclusaoComposta}
                    disabled={!textoConclusaoComposta}
                    className="rounded-lg bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-50"
                  >
                    Aplicar seleção manual de {conclusoesCompostasIds.length || ""} frase(s)
                  </button>
                </div>
              ) : (
                <div className="mb-3 flex flex-col items-start gap-2 lg:flex-row">
                  {aspecto.key === "conclusao" ? (
                    <SeletorFraseConclusao
                      frases={frasesAtivas}
                      value={fraseSelecionadaId}
                      onChange={(fraseId) =>
                        setFraseSelecionadaPorAspecto((prev) => ({
                          ...prev,
                          [aspecto.key]: fraseId,
                        }))
                      }
                    />
                  ) : modoPreenchimento === "compositor" ? (
                    <div className="w-full space-y-3">
                      {opcoesDeGrau.length ? (
                        <fieldset>
                          <legend className="mb-2 text-xs font-medium text-gray-600">
                            Variações de grau relacionadas
                          </legend>
                          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={`Grau de ${aspecto.label}`}>
                            {opcoesDeGrau.map((opcao) => {
                              const selecionada = String(opcao.frase.id) === fraseSelecionadaId;
                              return (
                                <button
                                  key={opcao.grau}
                                  type="button"
                                  role="radio"
                                  aria-checked={selecionada}
                                  onClick={() => aplicarFraseDoAspecto(aspecto, String(opcao.frase.id))}
                                  className={`rounded-lg border px-3 py-2 text-left text-sm ${
                                    selecionada
                                      ? "border-teal-400 bg-teal-50 text-teal-800"
                                      : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                                  }`}
                                >
                                  <span className="block font-medium">{opcao.label}</span>
                                  <span className="mt-0.5 block max-w-56 text-xs text-gray-500">
                                    {opcao.frase.titulo}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        </fieldset>
                      ) : null}
                      <label className="block">
                        <span className="mb-1 block text-xs text-gray-500">
                          Escolha única: a nova frase substitui somente este aspecto.
                        </span>
                        <select
                          aria-label={`Escolher frase para ${aspecto.label}`}
                          value={fraseSelecionadaId}
                          onChange={(e) => {
                            if (e.target.value) {
                              aplicarFraseDoAspecto(aspecto, e.target.value);
                            }
                          }}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="">Selecionar frase do banco</option>
                          {frasesAtivas.map((frase) => (
                            <option key={frase.id} value={String(frase.id)}>
                              {frase.titulo}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  ) : (
                    <select
                      value={fraseSelecionadaId}
                      onChange={(e) =>
                        setFraseSelecionadaPorAspecto((prev) => ({
                          ...prev,
                          [aspecto.key]: e.target.value,
                        }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                    >
                      <option value="">Selecionar frase do banco</option>
                      {frasesAtivas.map((frase) => (
                        <option key={frase.id} value={String(frase.id)}>
                          {frase.titulo}
                        </option>
                      ))}
                    </select>
                  )}
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {modoPreenchimento === "preset" ? (
                      <button
                        type="button"
                        onClick={() => aplicarFraseDoAspecto(aspecto)}
                        disabled={!fraseSelecionadaId}
                        className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                      >
                        Usar frase
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => salvarNovaFraseDoAspecto(aspecto)}
                      disabled={
                        !String(estado.textos[aspecto.key] || "").trim() ||
                        salvandoNovaFraseAspecto === aspecto.key
                      }
                      className="rounded-lg border border-teal-300 px-3 py-2 text-sm text-teal-700 hover:bg-teal-50 disabled:opacity-50"
                    >
                      {salvandoNovaFraseAspecto === aspecto.key
                        ? "Salvando..."
                        : "Salvar como nova frase"}
                    </button>
                  </div>
                </div>
              )}
              <textarea
                value={estado.textos[aspecto.key] || ""}
                onChange={(e) =>
                  {
                    onChange(
                      atualizarEstrutura(estado, {
                        textos: {
                          ...estado.textos,
                          [aspecto.key]: e.target.value,
                        },
                      })
                    );
                  }
                }
                rows={4}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                placeholder={aspecto.placeholder}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
