"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Copy,
  FileText,
  FolderOpen,
  Loader2,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Tag,
  Trash2,
} from "lucide-react";

import {
  type AspectoEcoEstruturadoTeste,
  type FraseEcoEstruturadoTeste,
  type PayloadEcoEstruturadoTeste,
  type PresetEcoEstruturadoTeste,
  ordenarAspectos,
} from "@/lib/ecocardiograma-estruturado-teste";
import {
  atualizarFraseEcoEstruturadoTeste,
  carregarBancoEcoEstruturadoTeste,
  criarFraseEcoEstruturadoTeste,
  duplicarFraseEcoEstruturadoTeste,
  duplicarPresetEcoEstruturadoTeste,
  excluirFraseEcoEstruturadoTeste,
  excluirPresetEcoEstruturadoTeste,
  restaurarFraseEcoEstruturadoTeste,
  restaurarPresetEcoEstruturadoTeste,
  salvarPresetEcoEstruturadoTeste,
} from "@/lib/frases-ecocardiograma-estruturado-teste-api";

interface FraseComAspecto {
  aspecto: AspectoEcoEstruturadoTeste;
  frase: FraseEcoEstruturadoTeste;
}

interface FraseFormState {
  id?: number;
  sourceAspecto: string;
  aspecto: string;
  titulo: string;
  texto: string;
  patologias: string;
  tags: string;
  ordem: string;
  ativo: boolean;
}

interface PresetFormState {
  id?: number;
  label: string;
  key: string;
  patologia: string;
  grau: string;
  descricao: string;
  tags: string;
  ordem: string;
  ativo: boolean;
  selecoes: Record<string, string>;
}

type SecaoBiblioteca = "frases" | "presets";
type StatusFiltro = "ativos" | "inativos" | "todos";

function normalizarListaInput(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function listaParaInput(value?: string[]): string {
  return (value || []).join(", ");
}

function textoNormalizado(value: unknown): string {
  return String(value || "").trim().toLowerCase();
}

function resumirTexto(texto?: string, limite = 140): string {
  const normalizado = String(texto || "").replace(/\s+/g, " ").trim();
  if (normalizado.length <= limite) {
    return normalizado;
  }
  return `${normalizado.slice(0, limite - 3)}...`;
}

function fraseFormVazio(aspecto = ""): FraseFormState {
  return {
    sourceAspecto: aspecto,
    aspecto,
    titulo: "",
    texto: "",
    patologias: "",
    tags: "",
    ordem: "",
    ativo: true,
  };
}

function presetFormVazio(aspectos: AspectoEcoEstruturadoTeste[]): PresetFormState {
  return {
    label: "",
    key: "",
    patologia: "",
    grau: "",
    descricao: "",
    tags: "",
    ordem: "",
    ativo: true,
    selecoes: aspectos.reduce<Record<string, string>>((acc, aspecto) => {
      acc[aspecto.key] = "";
      return acc;
    }, {}),
  };
}

function erroApi(err: any, fallback: string): string {
  return err?.response?.data?.detail || fallback;
}

export default function EcocardiogramaEstruturadoBiblioteca() {
  const [payload, setPayload] = useState<PayloadEcoEstruturadoTeste | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [secao, setSecao] = useState<SecaoBiblioteca>("frases");
  const [error, setError] = useState("");
  const [hint, setHint] = useState("");
  const [busca, setBusca] = useState("");
  const [filtroAspecto, setFiltroAspecto] = useState("");
  const [filtroPatologia, setFiltroPatologia] = useState("");
  const [filtroTag, setFiltroTag] = useState("");
  const [filtroStatus, setFiltroStatus] = useState<StatusFiltro>("ativos");
  const [gruposFrasesExpandidos, setGruposFrasesExpandidos] = useState<Set<string>>(new Set());
  const [fraseForm, setFraseForm] = useState<FraseFormState>(fraseFormVazio());
  const [presetForm, setPresetForm] = useState<PresetFormState>(presetFormVazio([]));

  const carregar = async (silencioso = false) => {
    try {
      setError("");
      if (silencioso) {
        setReloading(true);
      } else {
        setLoading(true);
      }
      const data = await carregarBancoEcoEstruturadoTeste();
      setPayload(data);
      const aspectosOrdenados = ordenarAspectos(data.aspectos || []);
      setFraseForm((prev) =>
        prev.aspecto
          ? prev
          : fraseFormVazio(aspectosOrdenados[0]?.key || "")
      );
      setPresetForm((prev) =>
        prev.label || prev.id ? prev : presetFormVazio(aspectosOrdenados)
      );
    } catch (err: any) {
      setError(erroApi(err, "Nao foi possivel carregar a biblioteca."));
    } finally {
      setLoading(false);
      setReloading(false);
    }
  };

  useEffect(() => {
    void carregar();
  }, []);

  const aspectos = useMemo(() => ordenarAspectos(payload?.aspectos || []), [payload]);

  const frases = useMemo<FraseComAspecto[]>(
    () =>
      aspectos.flatMap((aspecto) =>
        [...(aspecto.frases || [])]
          .sort((a, b) => {
            if ((a.ordem || 999) !== (b.ordem || 999)) {
              return (a.ordem || 999) - (b.ordem || 999);
            }
            return (a.titulo || "").localeCompare(b.titulo || "");
          })
          .map((frase) => ({ aspecto, frase }))
      ),
    [aspectos]
  );

  const presets = useMemo(
    () =>
      [...(payload?.presets || [])].sort((a, b) => {
        if ((a.ordem || 999) !== (b.ordem || 999)) {
          return (a.ordem || 999) - (b.ordem || 999);
        }
        return (a.label || "").localeCompare(b.label || "");
      }),
    [payload]
  );

  const patologias = useMemo(() => {
    const values = new Set<string>();
    frases.forEach(({ frase }) => (frase.patologias || []).forEach((item) => values.add(item)));
    presets.forEach((preset) => {
      if (preset.patologia) values.add(preset.patologia);
    });
    return [...values].sort((a, b) => a.localeCompare(b));
  }, [frases, presets]);

  const tags = useMemo(() => {
    const values = new Set<string>();
    frases.forEach(({ frase }) => (frase.tags || []).forEach((item) => values.add(item)));
    presets.forEach((preset) => (preset.tags || []).forEach((item) => values.add(item)));
    return [...values].sort((a, b) => a.localeCompare(b));
  }, [frases, presets]);

  const frasesFiltradas = useMemo(() => {
    const termo = textoNormalizado(busca);
    return frases.filter(({ aspecto, frase }) => {
      const ativo = Number(frase.ativo ?? 1) === 1;
      if (filtroStatus === "ativos" && !ativo) return false;
      if (filtroStatus === "inativos" && ativo) return false;
      if (filtroAspecto && aspecto.key !== filtroAspecto) return false;
      if (filtroPatologia && !(frase.patologias || []).includes(filtroPatologia)) return false;
      if (filtroTag && !(frase.tags || []).includes(filtroTag)) return false;
      if (!termo) return true;
      return [frase.titulo, frase.texto, aspecto.label, ...(frase.tags || []), ...(frase.patologias || [])]
        .join(" ")
        .toLowerCase()
        .includes(termo);
    });
  }, [busca, filtroAspecto, filtroPatologia, filtroStatus, filtroTag, frases]);

  const gruposFrases = useMemo(() => {
    const grupos = new Map<string, FraseComAspecto[]>();
    frasesFiltradas.forEach((item) => {
      const grupoPatologias = item.frase.patologias?.length ? item.frase.patologias : ["Sem patologia"];
      grupoPatologias.forEach((patologia) => {
        if (filtroPatologia && patologia !== filtroPatologia) return;
        grupos.set(patologia, [...(grupos.get(patologia) || []), item]);
      });
    });
    return [...grupos.entries()].sort(([a], [b]) => {
      if (a === "Sem patologia") return 1;
      if (b === "Sem patologia") return -1;
      return a.localeCompare(b);
    });
  }, [filtroPatologia, frasesFiltradas]);

  const filtrosForcamGruposExpandidos = Boolean(
    textoNormalizado(busca) || filtroPatologia || filtroTag
  );

  const alternarGrupoFrases = (patologia: string) => {
    setGruposFrasesExpandidos((atuais) => {
      const proximos = new Set(atuais);
      if (proximos.has(patologia)) {
        proximos.delete(patologia);
      } else {
        proximos.add(patologia);
      }
      return proximos;
    });
  };

  const presetsFiltrados = useMemo(() => {
    const termo = textoNormalizado(busca);
    return presets.filter((preset) => {
      const ativo = Number(preset.ativo ?? 1) === 1;
      if (filtroStatus === "ativos" && !ativo) return false;
      if (filtroStatus === "inativos" && ativo) return false;
      if (filtroPatologia && preset.patologia !== filtroPatologia) return false;
      if (filtroTag && !(preset.tags || []).includes(filtroTag)) return false;
      if (!termo) return true;
      return [preset.label, preset.key, preset.patologia, preset.grau, preset.descricao, ...(preset.tags || [])]
        .join(" ")
        .toLowerCase()
        .includes(termo);
    });
  }, [busca, filtroPatologia, filtroStatus, filtroTag, presets]);

  const frasePorAspectoEId = (aspectoKey: string, fraseId: string) => {
    const aspecto = aspectos.find((item) => item.key === aspectoKey);
    return (aspecto?.frases || []).find((frase) => String(frase.id) === fraseId) || null;
  };

  const selecionarFrase = (item: FraseComAspecto) => {
    setSecao("frases");
    setError("");
    setHint("");
    setFraseForm({
      id: item.frase.id,
      sourceAspecto: item.aspecto.key,
      aspecto: item.aspecto.key,
      titulo: item.frase.titulo || "",
      texto: item.frase.texto || "",
      patologias: listaParaInput(item.frase.patologias),
      tags: listaParaInput(item.frase.tags),
      ordem: item.frase.ordem ? String(item.frase.ordem) : "",
      ativo: Number(item.frase.ativo ?? 1) === 1,
    });
  };

  const novaFrase = () => {
    setSecao("frases");
    setFraseForm(fraseFormVazio(filtroAspecto || aspectos[0]?.key || ""));
    setHint("");
    setError("");
  };

  const salvarFrase = async () => {
    if (!fraseForm.titulo.trim() || !fraseForm.texto.trim()) {
      setError("Informe titulo e texto da frase.");
      return;
    }

    const body = {
      aspecto: fraseForm.sourceAspecto || fraseForm.aspecto,
      novo_aspecto: fraseForm.aspecto,
      titulo: fraseForm.titulo.trim(),
      texto: fraseForm.texto.trim(),
      patologias: normalizarListaInput(fraseForm.patologias),
      tags: normalizarListaInput(fraseForm.tags),
      ordem: fraseForm.ordem.trim() ? Number(fraseForm.ordem) : undefined,
      ativo: fraseForm.ativo ? 1 : 0,
    };

    try {
      setSaving(true);
      setError("");
      if (fraseForm.id) {
        await atualizarFraseEcoEstruturadoTeste(fraseForm.id, body);
        setHint(`Frase "${body.titulo}" atualizada.`);
      } else {
        const created = await criarFraseEcoEstruturadoTeste(body);
        setFraseForm((prev) => ({
          ...prev,
          id: created?.id,
          sourceAspecto: body.novo_aspecto,
        }));
        setHint(`Frase "${body.titulo}" criada.`);
      }
      await carregar(true);
      setFraseForm((prev) => ({ ...prev, sourceAspecto: body.novo_aspecto }));
    } catch (err: any) {
      setError(erroApi(err, "Nao foi possivel salvar a frase."));
    } finally {
      setSaving(false);
    }
  };

  const duplicarFrase = async () => {
    if (!fraseForm.id) return;
    try {
      setSaving(true);
      setError("");
      const clone = await duplicarFraseEcoEstruturadoTeste(fraseForm.id, {
        aspecto: fraseForm.sourceAspecto,
        novo_aspecto: fraseForm.aspecto,
        titulo: `${fraseForm.titulo.trim()} copia`,
        texto: fraseForm.texto,
        patologias: normalizarListaInput(fraseForm.patologias),
        tags: normalizarListaInput(fraseForm.tags),
      });
      await carregar(true);
      setFraseForm((prev) => ({
        ...prev,
        id: clone?.id,
        sourceAspecto: prev.aspecto,
        titulo: clone?.titulo || `${prev.titulo} copia`,
        ativo: true,
      }));
      setHint("Frase duplicada.");
    } catch (err: any) {
      setError(erroApi(err, "Nao foi possivel duplicar a frase."));
    } finally {
      setSaving(false);
    }
  };

  const alternarFraseAtiva = async () => {
    if (!fraseForm.id) return;
    try {
      setSaving(true);
      setError("");
      if (fraseForm.ativo) {
        await excluirFraseEcoEstruturadoTeste(fraseForm.id, { aspecto: fraseForm.sourceAspecto });
        setFraseForm((prev) => ({ ...prev, ativo: false }));
        setHint("Frase desativada.");
      } else {
        await restaurarFraseEcoEstruturadoTeste(fraseForm.id, { aspecto: fraseForm.sourceAspecto });
        setFraseForm((prev) => ({ ...prev, ativo: true }));
        setHint("Frase restaurada.");
      }
      await carregar(true);
    } catch (err: any) {
      setError(erroApi(err, "Nao foi possivel alterar o status da frase."));
    } finally {
      setSaving(false);
    }
  };

  const selecionarPreset = (preset: PresetEcoEstruturadoTeste) => {
    const selecoes = presetFormVazio(aspectos).selecoes;
    (preset.selecoes || []).forEach((selecao) => {
      const aspecto = aspectos.find((item) => item.key === selecao.aspecto);
      const frases = aspecto?.frases || [];
      const frase =
        (selecao.frase_id != null
          ? frases.find((item) => Number(item.id) === Number(selecao.frase_id))
          : null) ||
        frases.find((item) => item.titulo === selecao.frase_titulo);
      if (selecao.aspecto && frase) selecoes[selecao.aspecto] = String(frase.id);
    });
    setSecao("presets");
    setError("");
    setHint("");
    setPresetForm({
      id: preset.id,
      label: preset.label || "",
      key: preset.key || "",
      patologia: preset.patologia || "",
      grau: preset.grau || "",
      descricao: preset.descricao || "",
      tags: listaParaInput(preset.tags),
      ordem: preset.ordem ? String(preset.ordem) : "",
      ativo: Number(preset.ativo ?? 1) === 1,
      selecoes,
    });
  };

  const novoPreset = () => {
    setSecao("presets");
    setPresetForm(presetFormVazio(aspectos));
    setHint("");
    setError("");
  };

  const salvarPreset = async () => {
    if (!presetForm.label.trim()) {
      setError("Informe o nome do preset.");
      return;
    }

    const selecoes = Object.entries(presetForm.selecoes)
      .map(([aspecto, fraseId]) => {
        if (!fraseId) return null;
        const frase = frasePorAspectoEId(aspecto, fraseId);
        return {
          aspecto,
          frase_id: frase?.id || Number(fraseId),
          frase_titulo: frase?.titulo || "",
        };
      })
      .filter(Boolean);

    if (!selecoes.length) {
      setError("Selecione pelo menos uma frase para o preset.");
      return;
    }

    const body = {
      label: presetForm.label.trim(),
      key: presetForm.key.trim(),
      patologia: presetForm.patologia.trim(),
      grau: presetForm.grau.trim(),
      descricao: presetForm.descricao.trim(),
      tags: normalizarListaInput(presetForm.tags),
      ordem: presetForm.ordem.trim() ? Number(presetForm.ordem) : undefined,
      ativo: presetForm.ativo ? 1 : 0,
      selecoes,
    };

    try {
      setSaving(true);
      setError("");
      const saved = await salvarPresetEcoEstruturadoTeste(body, presetForm.id);
      await carregar(true);
      setPresetForm((prev) => ({ ...prev, id: saved?.id || prev.id }));
      setHint(`Preset "${body.label}" salvo.`);
    } catch (err: any) {
      setError(erroApi(err, "Nao foi possivel salvar o preset."));
    } finally {
      setSaving(false);
    }
  };

  const duplicarPreset = async () => {
    if (!presetForm.id) return;
    try {
      setSaving(true);
      setError("");
      const clone = await duplicarPresetEcoEstruturadoTeste(presetForm.id, {
        label: `${presetForm.label.trim()} copia`,
      });
      await carregar(true);
      if (clone?.id) {
        selecionarPreset(clone);
      }
      setHint("Preset duplicado.");
    } catch (err: any) {
      setError(erroApi(err, "Nao foi possivel duplicar o preset."));
    } finally {
      setSaving(false);
    }
  };

  const alternarPresetAtivo = async () => {
    if (!presetForm.id) return;
    try {
      setSaving(true);
      setError("");
      if (presetForm.ativo) {
        await excluirPresetEcoEstruturadoTeste(presetForm.id);
        setPresetForm((prev) => ({ ...prev, ativo: false }));
        setHint("Preset desativado.");
      } else {
        await restaurarPresetEcoEstruturadoTeste(presetForm.id);
        setPresetForm((prev) => ({ ...prev, ativo: true }));
        setHint("Preset restaurado.");
      }
      await carregar(true);
    } catch (err: any) {
      setError(erroApi(err, "Nao foi possivel alterar o status do preset."));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Carregando biblioteca...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="font-medium text-gray-900">Biblioteca de presets e frases</h3>
          <p className="text-sm text-gray-500">
            Organize frases por patologia, revise aspectos e mantenha presets prontos para a aba Qualitativa.
          </p>
        </div>
        <button
          type="button"
          onClick={() => carregar(true)}
          disabled={reloading}
          className="inline-flex items-center gap-2 self-start rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${reloading ? "animate-spin" : ""}`} />
          Recarregar
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setSecao("frases")}
          className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
            secao === "frases"
              ? "border-teal-300 bg-teal-50 text-teal-700"
              : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
          }`}
        >
          <FileText className="h-4 w-4" />
          Frases
        </button>
        <button
          type="button"
          onClick={() => setSecao("presets")}
          className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
            secao === "presets"
              ? "border-teal-300 bg-teal-50 text-teal-700"
              : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
          }`}
        >
          <FolderOpen className="h-4 w-4" />
          Presets
        </button>
      </div>

      <div className="grid gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 md:grid-cols-2 lg:grid-cols-5">
        <label className="relative lg:col-span-2">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
          <input
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm focus:ring-2 focus:ring-teal-500"
            placeholder="Buscar por titulo, texto ou tag"
          />
        </label>
        <select
          value={filtroPatologia}
          onChange={(e) => setFiltroPatologia(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
        >
          <option value="">Todas as patologias</option>
          {patologias.map((patologia) => (
            <option key={patologia} value={patologia}>
              {patologia}
            </option>
          ))}
        </select>
        <select
          value={filtroTag}
          onChange={(e) => setFiltroTag(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
        >
          <option value="">Todas as tags</option>
          {tags.map((tag) => (
            <option key={tag} value={tag}>
              {tag}
            </option>
          ))}
        </select>
        <select
          value={filtroStatus}
          onChange={(e) => setFiltroStatus(e.target.value as StatusFiltro)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
        >
          <option value="ativos">Ativos</option>
          <option value="inativos">Inativos</option>
          <option value="todos">Todos</option>
        </select>
        {secao === "frases" ? (
          <select
            value={filtroAspecto}
            onChange={(e) => setFiltroAspecto(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500 lg:col-span-2"
          >
            <option value="">Todos os aspectos</option>
            {aspectos.map((aspecto) => (
              <option key={aspecto.key} value={aspecto.key}>
                {aspecto.label}
              </option>
            ))}
          </select>
        ) : null}
      </div>

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

      {secao === "frases" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-gray-600">
                {frasesFiltradas.length} frase(s) encontradas
              </div>
              <button
                type="button"
                onClick={novaFrase}
                className="rounded-lg bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700"
              >
                Nova frase
              </button>
            </div>
            {gruposFrases.map(([patologia, itens], index) => {
              const expandido =
                filtrosForcamGruposExpandidos || gruposFrasesExpandidos.has(patologia);
              const conteudoId = `grupo-frases-${index}`;
              return (
                <section
                  key={patologia}
                  className="overflow-hidden rounded-lg border border-gray-200 bg-white"
                >
                  <button
                    type="button"
                    onClick={() => alternarGrupoFrases(patologia)}
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
                      <Tag className="h-4 w-4 shrink-0 text-teal-600" />
                      <span className="truncate">{patologia}</span>
                    </span>
                    <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-normal text-gray-600">
                      {itens.length} {itens.length === 1 ? "frase" : "frases"}
                    </span>
                  </button>
                  {expandido ? (
                    <div id={conteudoId} className="space-y-2 border-t border-gray-200 bg-gray-50/60 p-3">
                      {itens.map((item) => {
                        const ativo = Number(item.frase.ativo ?? 1) === 1;
                        const selected =
                          fraseForm.id === item.frase.id &&
                          fraseForm.sourceAspecto === item.aspecto.key;
                        return (
                          <button
                            key={`${item.aspecto.key}-${item.frase.id}`}
                            type="button"
                            onClick={() => selecionarFrase(item)}
                            className={`block w-full rounded-lg border bg-white p-3 text-left text-sm transition ${
                              selected
                                ? "border-teal-300 ring-2 ring-teal-100"
                                : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                            }`}
                          >
                            <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                              <div>
                                <div className="font-medium text-gray-900">{item.frase.titulo}</div>
                                <div className="text-xs text-gray-500">{item.aspecto.label}</div>
                              </div>
                              <span
                                className={`w-fit rounded-full border px-2 py-0.5 text-xs ${
                                  ativo
                                    ? "border-green-200 bg-green-50 text-green-700"
                                    : "border-gray-200 bg-gray-50 text-gray-500"
                                }`}
                              >
                                {ativo ? "Ativa" : "Inativa"}
                              </span>
                            </div>
                            <p className="mt-2 text-gray-600">{resumirTexto(item.frase.texto)}</p>
                            <div className="mt-2 flex flex-wrap gap-1">
                              {(item.frase.tags || []).map((tag) => (
                                <span key={tag} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                                  {tag}
                                </span>
                              ))}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                </section>
              );
            })}
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h4 className="text-sm font-medium text-gray-900">
                {fraseForm.id ? "Editar frase" : "Nova frase"}
              </h4>
              {fraseForm.id ? (
                <span className="text-xs text-gray-500">ID {fraseForm.id}</span>
              ) : null}
            </div>
            <div className="space-y-3">
              <input
                value={fraseForm.titulo}
                onChange={(e) => setFraseForm((prev) => ({ ...prev, titulo: e.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                placeholder="Titulo da frase"
              />
              <select
                value={fraseForm.aspecto}
                onChange={(e) => setFraseForm((prev) => ({ ...prev, aspecto: e.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
              >
                {aspectos.map((aspecto) => (
                  <option key={aspecto.key} value={aspecto.key}>
                    {aspecto.label}
                  </option>
                ))}
              </select>
              <textarea
                value={fraseForm.texto}
                onChange={(e) => setFraseForm((prev) => ({ ...prev, texto: e.target.value }))}
                rows={7}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                placeholder="Texto da frase"
              />
              <input
                value={fraseForm.patologias}
                onChange={(e) => setFraseForm((prev) => ({ ...prev, patologias: e.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                placeholder="Patologias separadas por virgula"
              />
              <input
                value={fraseForm.tags}
                onChange={(e) => setFraseForm((prev) => ({ ...prev, tags: e.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                placeholder="Tags separadas por virgula"
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <input
                  value={fraseForm.ordem}
                  onChange={(e) => setFraseForm((prev) => ({ ...prev, ordem: e.target.value }))}
                  className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                  placeholder="Ordem"
                />
                <label className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={fraseForm.ativo}
                    onChange={(e) => setFraseForm((prev) => ({ ...prev, ativo: e.target.checked }))}
                    className="h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                  />
                  Ativa
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={salvarFrase}
                  disabled={saving}
                  className="inline-flex items-center gap-2 rounded-lg bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-50"
                >
                  <Save className="h-4 w-4" />
                  Salvar
                </button>
                <button
                  type="button"
                  onClick={duplicarFrase}
                  disabled={!fraseForm.id || saving}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  <Copy className="h-4 w-4" />
                  Duplicar
                </button>
                <button
                  type="button"
                  onClick={alternarFraseAtiva}
                  disabled={!fraseForm.id || saving}
                  className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm disabled:opacity-50 ${
                    fraseForm.ativo
                      ? "border-red-300 text-red-700 hover:bg-red-50"
                      : "border-green-300 text-green-700 hover:bg-green-50"
                  }`}
                >
                  {fraseForm.ativo ? <Trash2 className="h-4 w-4" /> : <RotateCcw className="h-4 w-4" />}
                  {fraseForm.ativo ? "Desativar" : "Restaurar"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(400px,1fr)]">
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-gray-600">
                {presetsFiltrados.length} preset(s) encontrados
              </div>
              <button
                type="button"
                onClick={novoPreset}
                className="rounded-lg bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700"
              >
                Novo preset
              </button>
            </div>
            {presetsFiltrados.map((preset) => {
              const ativo = Number(preset.ativo ?? 1) === 1;
              const inativas = (preset.selecoes || []).filter((selecao) => {
                if (selecao.frase_id == null) return false;
                const frase = frasePorAspectoEId(selecao.aspecto, String(selecao.frase_id));
                return frase && Number(frase.ativo ?? 1) !== 1;
              }).length;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => selecionarPreset(preset)}
                  className={`block w-full rounded-lg border bg-white p-3 text-left text-sm ${
                    presetForm.id === preset.id
                      ? "border-teal-300 ring-2 ring-teal-100"
                      : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                  }`}
                >
                  <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="font-medium text-gray-900">{preset.label}</div>
                      <div className="text-xs text-gray-500">
                        {[preset.patologia, preset.grau].filter(Boolean).join(" | ") || "Sem classificacao"}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {inativas ? (
                        <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                          usa frase inativa
                        </span>
                      ) : null}
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs ${
                          ativo
                            ? "border-green-200 bg-green-50 text-green-700"
                            : "border-gray-200 bg-gray-50 text-gray-500"
                        }`}
                      >
                        {ativo ? "Ativo" : "Inativo"}
                      </span>
                    </div>
                  </div>
                  <p className="mt-2 text-gray-600">{resumirTexto(preset.descricao, 110)}</p>
                </button>
              );
            })}
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h4 className="text-sm font-medium text-gray-900">
                {presetForm.id ? "Editar preset" : "Novo preset"}
              </h4>
              {presetForm.id ? <span className="text-xs text-gray-500">ID {presetForm.id}</span> : null}
            </div>
            <div className="space-y-3">
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
                  placeholder="Chave"
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
                <label className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={presetForm.ativo}
                    onChange={(e) => setPresetForm((prev) => ({ ...prev, ativo: e.target.checked }))}
                    className="h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                  />
                  Ativo
                </label>
              </div>
              <textarea
                value={presetForm.descricao}
                onChange={(e) => setPresetForm((prev) => ({ ...prev, descricao: e.target.value }))}
                rows={3}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                placeholder="Descricao"
              />
              <div className="max-h-[520px] space-y-2 overflow-y-auto pr-1">
                {aspectos.map((aspecto) => {
                  const selectedId = presetForm.selecoes[aspecto.key] || "";
                  const selectedPhrase = selectedId ? frasePorAspectoEId(aspecto.key, selectedId) : null;
                  const activePhrases = (aspecto.frases || []).filter((frase) => Number(frase.ativo ?? 1) === 1);
                  const options = selectedPhrase && Number(selectedPhrase.ativo ?? 1) !== 1
                    ? [...activePhrases, selectedPhrase]
                    : activePhrases;
                  return (
                    <div key={aspecto.key} className="rounded-lg border border-gray-200 p-3">
                      <label className="mb-1 block text-sm font-medium text-gray-700">
                        {aspecto.label}
                      </label>
                      <select
                        value={selectedId}
                        onChange={(e) =>
                          setPresetForm((prev) => ({
                            ...prev,
                            selecoes: { ...prev.selecoes, [aspecto.key]: e.target.value },
                          }))
                        }
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">Sem frase</option>
                        {options.map((frase) => (
                          <option key={frase.id} value={String(frase.id)}>
                            {Number(frase.ativo ?? 1) === 1 ? frase.titulo : `${frase.titulo} (inativa)`}
                          </option>
                        ))}
                      </select>
                      {selectedPhrase && Number(selectedPhrase.ativo ?? 1) !== 1 ? (
                        <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700">
                          Este preset usa uma frase inativa.
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
                  disabled={saving}
                  className="inline-flex items-center gap-2 rounded-lg bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-50"
                >
                  <Save className="h-4 w-4" />
                  Salvar
                </button>
                <button
                  type="button"
                  onClick={duplicarPreset}
                  disabled={!presetForm.id || saving}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  <Copy className="h-4 w-4" />
                  Duplicar
                </button>
                <button
                  type="button"
                  onClick={alternarPresetAtivo}
                  disabled={!presetForm.id || saving}
                  className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm disabled:opacity-50 ${
                    presetForm.ativo
                      ? "border-red-300 text-red-700 hover:bg-red-50"
                      : "border-green-300 text-green-700 hover:bg-green-50"
                  }`}
                >
                  {presetForm.ativo ? <Trash2 className="h-4 w-4" /> : <RotateCcw className="h-4 w-4" />}
                  {presetForm.ativo ? "Desativar" : "Restaurar"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
