"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import { BookOpen, Upload, Edit2, Save, X, Database, Ruler } from "lucide-react";
import type { ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { buildEchoReferenceCatalogForm, echoCatalogRange } from "@/lib/echo-reference-policy";

interface Referencia extends ReferenciaEco {
  id: number;
  especie: "Canina" | "Felina";
  peso_kg: number;
  lvid_d_min?: number;
  lvid_d_max?: number;
  ivs_d_min?: number;
  ivs_d_max?: number;
  lvpw_d_min?: number;
  lvpw_d_max?: number;
  lvid_s_min?: number;
  lvid_s_max?: number;
  ivs_s_min?: number;
  ivs_s_max?: number;
  lvpw_s_min?: number;
  lvpw_s_max?: number;
  fs_min?: number;
  fs_max?: number;
  fs_source?: string;
  ef_min?: number;
  ef_max?: number;
  ao_min?: number;
  ao_max?: number;
  la_min?: number;
  la_max?: number;
  la_ao_min?: number;
  la_ao_max?: number;
  vmax_ao_min?: number;
  vmax_ao_max?: number;
  vmax_pulm_min?: number;
  vmax_pulm_max?: number;
}

const CAMPOS_MEDIDAS = [
  { key: "lvid_d", label: "LVIDd", unidade: "mm" },
  { key: "lvid_s", label: "LVIDs", unidade: "mm" },
  { key: "ivs_d", label: "IVSd", unidade: "mm" },
  { key: "ivs_s", label: "IVSs", unidade: "mm" },
  { key: "lvpw_d", label: "LVPWd", unidade: "mm" },
  { key: "lvpw_s", label: "LVPWs", unidade: "mm" },
  { key: "fs", label: "FS", unidade: "%" },
  { key: "ef", label: "EF", unidade: "%" },
  { key: "tapse", label: "TAPSE", unidade: "mm" },
  { key: "ao", label: "Ao", unidade: "mm" },
  { key: "la", label: "LA", unidade: "mm" },
  { key: "la_ao", label: "LA/Ao", unidade: "" },
  { key: "vmax_ao", label: "Vmax aórtica", unidade: "m/s", step: "0.01" },
  { key: "vmax_pulm", label: "Vmax pulmonar", unidade: "m/s", step: "0.01" },
  { key: "mv_e", label: "Onda E", unidade: "m/s", step: "0.01" },
  { key: "mv_a", label: "Onda A", unidade: "m/s", step: "0.01" },
  { key: "mv_dt", label: "TD", unidade: "ms" },
];

const EDITABLE_PREFIXES = CAMPOS_MEDIDAS.filter((field) => field.key !== "fs" && field.key !== "ef").map((field) => field.key);
const POLICY_LABELS = { published: "Faixa publicada", catalog: "Faixa cadastrada; fonte não confirmada", requires_method: "Exige confirmação do método", blocked: "Comparação suspensa", unavailable: "Faixa indisponível", estimated: "Estimativa; sem comparação automática" };

export default function ReferenciasEcoPage() {
  const router = useRouter();
  const [referencias, setReferencias] = useState<Referencia[]>([]);
  const [loading, setLoading] = useState(true);
  const [especieFiltro, setEspecieFiltro] = useState("Canina");
  const [editando, setEditando] = useState<number | null>(null);
  const [formData, setFormData] = useState<Record<string, string | number | null>>({});
  const [importando, setImportando] = useState(false);
  const [fileCaninos, setFileCaninos] = useState<File | null>(null);
  const [fileFelinos, setFileFelinos] = useState<File | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarReferencias();
  }, [router, especieFiltro]);

  const carregarReferencias = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/referencias-eco?especie=${encodeURIComponent(especieFiltro)}`);
      const items = response.data?.items ?? [];
      setReferencias(Array.isArray(items) ? items : []);
    } catch (error) {
      console.error("Erro ao carregar referências:", error);
      setReferencias([]);
    } finally {
      setLoading(false);
    }
  };

  const handleEditar = (ref: Referencia) => {
    setEditando(ref.id);
    setFormData(buildEchoReferenceCatalogForm(ref, EDITABLE_PREFIXES));
  };

  const handleSalvar = async (id: number) => {
    try {
      await api.put(`/referencias-eco/${id}`, formData);
      setEditando(null);
      carregarReferencias();
      alert("Referência atualizada com sucesso!");
    } catch (error) {
      alert("Erro ao salvar referência");
    }
  };

  const handleChange = (campo: string, valor: string) => {
    const numValor = valor === "" ? null : parseFloat(valor);
    setFormData({ ...formData, [campo]: numValor });
  };

  const handleImportar = async () => {
    if (!fileCaninos && !fileFelinos) {
      alert("Selecione pelo menos um arquivo CSV (caninos e/ou felinos).");
      return;
    }
    try {
      setImportando(true);
      const form = new FormData();
      if (fileCaninos) form.append("caninos", fileCaninos);
      if (fileFelinos) form.append("felinos", fileFelinos);
      const { data } = await api.post<{ caninos: number; felinos: number; erros: string[] }>(
        "/referencias-eco/importar",
        form
      );
      const msg = [
        data.caninos > 0 ? `Caninos: ${data.caninos} referências importadas.` : "",
        data.felinos > 0 ? `Felinos: ${data.felinos} referências importadas.` : "",
        ...(data.erros || []),
      ].filter(Boolean).join(" ");
      alert(data.erros?.length ? `Importação concluída com avisos:\n${msg}` : `Importação concluída!\n${msg}`);
      setFileCaninos(null);
      setFileFelinos(null);
      // Recarrega a lista (evita cache)
      setReferencias([]);
      await carregarReferencias();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      alert("Erro ao importar: " + (err.response?.data?.detail || String(e)));
    } finally {
      setImportando(false);
    }
  };

  const pesosDisponiveis = referencias.map((referencia) => Number(referencia.peso_kg)).filter((peso) => Number.isFinite(peso));
  const faixaPeso = pesosDisponiveis.length
    ? `${Math.min(...pesosDisponiveis)} a ${Math.max(...pesosDisponiveis)} kg`
    : "—";

  return (
    <DashboardLayout>
      <div className="fc-eco-page">
        <header className="fc-eco-header">
          <div>
            <span className="fc-eco-kicker"><BookOpen className="h-4 w-4" />Biblioteca diagnóstica</span>
            <h1>Referências Ecocardiográficas</h1>
            <p>Faixas cadastradas por espécie, peso e medida cardíaca.</p>
          </div>
          <div className="fc-eco-species-tabs" role="tablist" aria-label="Espécie das referências">
            {[
              ["Canina", "Caninos"],
              ["Felina", "Felinos"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={especieFiltro === value}
                onClick={() => setEspecieFiltro(value)}
                className={`fc-eco-species-tab ${especieFiltro === value ? "fc-eco-species-tab-active" : ""}`}
              >
                {label}
              </button>
            ))}
          </div>
        </header>

        <p className="text-sm text-slate-600">
          A tabela mostra os números originais do cadastro. A comparação no laudo depende da fonte, da população e do método da medida.
          FS: modo M, intervalo de Visser et al. (2019) em cães adultos de 2,6 a 67,8 kg;
          Häggström et al. (2016) em gatos adultos de raça pura. FE por Teichholz:
          intervalo indisponível por falta de validação compatível com o método.
        </p>
        <section className="fc-eco-metrics" aria-label="Resumo da base de referências">
          <div className="fc-eco-metric fc-eco-metric-cordis">
            <Database className="h-5 w-5" />
            <strong>{referencias.length}</strong>
            <span>Faixas cadastradas</span>
          </div>
          <div className="fc-eco-metric fc-eco-metric-vital">
            <Ruler className="h-5 w-5" />
            <strong>{faixaPeso}</strong>
            <span>Cobertura de peso</span>
          </div>
          <div className="fc-eco-metric fc-eco-metric-ink">
            <BookOpen className="h-5 w-5" />
            <strong>{CAMPOS_MEDIDAS.length}</strong>
            <span>Medidas avaliadas</span>
          </div>
        </section>

        <section className="fc-eco-import">
          <div className="fc-eco-import-copy">
            <span>Atualização da base</span>
            <h2>Importar referências por CSV</h2>
            <p>O arquivo enviado substitui as referências existentes da respectiva espécie.</p>
          </div>
          <div className="fc-eco-import-controls">
            <div>
              <input
                id="eco-csv-caninos"
                type="file"
                accept=".csv"
                onChange={(e) => setFileCaninos(e.target.files?.[0] ?? null)}
                className="sr-only"
              />
              <label htmlFor="eco-csv-caninos" className="fc-eco-file-picker">
                <Upload className="h-4 w-4" />
                <span><small>CSV Caninos</small>{fileCaninos?.name || "Selecionar arquivo"}</span>
              </label>
            </div>
            <div>
              <input
                id="eco-csv-felinos"
                type="file"
                accept=".csv"
                onChange={(e) => setFileFelinos(e.target.files?.[0] ?? null)}
                className="sr-only"
              />
              <label htmlFor="eco-csv-felinos" className="fc-eco-file-picker">
                <Upload className="h-4 w-4" />
                <span><small>CSV Felinos</small>{fileFelinos?.name || "Selecionar arquivo"}</span>
              </label>
            </div>
            <button
              type="button"
              onClick={handleImportar}
              disabled={importando || (!fileCaninos && !fileFelinos)}
              className="fc-eco-import-button"
            >
              <Upload className="h-4 w-4" />
              {importando ? "Importando..." : "Importar CSV"}
            </button>
          </div>
        </section>

        <section className="fc-eco-table-panel">
          <div className="fc-eco-table-heading">
            <div>
              <span>Base ativa</span>
              <h2>{especieFiltro === "Canina" ? "Referências caninas" : "Referências felinas"}</h2>
            </div>
            <strong>{referencias.length} faixa(s)</strong>
          </div>

          <aside className="border-b border-slate-200 px-4 py-3 text-xs text-slate-600" aria-label="Evidência sobre velocidades de fluxo">
            <p>A comparação automática das velocidades de fluxo está suspensa: os limites do cadastro não têm intervalo individual validado para o método. Dados publicados para consulta:</p>
            {especieFiltro === "Canina" ? (
              <p>
                <a className="underline" href="https://www.scielo.br/j/pvb/a/JVtpYsn7zbTBB6xmpRXKVLs/?format=pdf&lang=pt" target="_blank" rel="noopener noreferrer">Petrus et al. (2010)</a>:
                {" "}30 cães de raças diferentes, Doppler pulsado; Vmax aórtica 1,26 ± 0,13 m/s e pulmonar 0,95 ± 0,18 m/s (médias ± DP, não limites de referência).
              </p>
            ) : (
              <p>
                <a className="underline" href="https://pubmed.ncbi.nlm.nih.gov/22854250/" target="_blank" rel="noopener noreferrer">Domanjko Petrič et al. (2012)</a>:
                {" "}53 gatos não sedados, Doppler pulsado; Vmax aórtica 0,77–1,40 m/s e pulmonar 0,65–1,21 m/s (extremos observados, não intervalo de referência de 95%).
              </p>
            )}
          </aside>

          {loading ? (
            <div className="fc-eco-loading"><span />Carregando referências...</div>
          ) : referencias.length === 0 ? (
            <div className="fc-eco-empty">
              <BookOpen className="h-6 w-6" />
              <strong>Nenhuma referência cadastrada</strong>
              <span>Importe um arquivo CSV para iniciar esta base.</span>
            </div>
          ) : (
            <div className="fc-eco-table-scroll">
              <table className="fc-eco-table">
                <thead>
                  <tr>
                    <th>Peso <span>kg</span></th>
                    {CAMPOS_MEDIDAS.map((campo) => (
                      <th key={campo.key}>
                        {campo.label}
                        <span>{campo.unidade || "índice"}</span>
                      </th>
                    ))}
                    <th>Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {referencias.map((ref) => (
                    <tr key={ref.id} className={editando === ref.id ? "fc-eco-row-editing" : ""}>
                      <td>
                        {editando === ref.id ? (
                          <input
                            type="number"
                            step="0.1"
                            value={formData.peso_kg || ""}
                            onChange={(e) => handleChange("peso_kg", e.target.value)}
                            className="fc-eco-weight-input"
                            aria-label="Peso em quilogramas"
                          />
                        ) : (
                          <strong>{ref.peso_kg}</strong>
                        )}
                      </td>

                      {CAMPOS_MEDIDAS.map((campo) => {
                        const minKey = `${campo.key}_min`;
                        const maxKey = `${campo.key}_max`;
                        const rawRange = echoCatalogRange(ref, campo.key);
                        const min = editando === ref.id && EDITABLE_PREFIXES.includes(campo.key) ? formData[minKey] : rawRange.min;
                        const max = editando === ref.id && EDITABLE_PREFIXES.includes(campo.key) ? formData[maxKey] : rawRange.max;
                        const metadata = ref.range_metadata?.[campo.key];

                        return (
                          <td key={campo.key}>
                            {editando === ref.id && campo.key !== "fs" && campo.key !== "ef" ? (
                              <div className="fc-eco-range-inputs">
                                <input
                                  type="number"
                                  step={"step" in campo ? campo.step : "0.1"}
                                  value={min ?? ""}
                                  onChange={(e) => handleChange(minKey as string, e.target.value)}
                                  placeholder="Min"
                                  aria-label={`${campo.label} mínimo`}
                                />
                                <input
                                  type="number"
                                  step={"step" in campo ? campo.step : "0.1"}
                                  value={max ?? ""}
                                  onChange={(e) => handleChange(maxKey as string, e.target.value)}
                                  placeholder="Máx"
                                  aria-label={`${campo.label} máximo`}
                                />
                              </div>
                            ) : (
                              <span className="fc-eco-range-value" title={metadata?.source || (campo.key === "fs" ? ref.fs_source : undefined)}>
                                {min != null && max != null ? `${min} – ${max}` : "—"}
                              </span>
                            )}
                            {metadata && <div className="mt-1 max-w-52 text-[10px] leading-snug text-slate-600" title={metadata.reason}>
                              <span>{POLICY_LABELS[metadata.status]}</span>
                              {(metadata.status === "published" || metadata.status === "requires_method")
                                && metadata.candidate_min != null && metadata.candidate_max != null && (
                                <span className="block">{metadata.status === "published" ? "Comparação" : "Candidata"}: {metadata.candidate_min} – {metadata.candidate_max}</span>
                              )}
                              {metadata.source && <span className="block">Fonte da comparação: {metadata.source}</span>}
                              {metadata.reason && <span className="block">{metadata.reason}</span>}
                            </div>}
                          </td>
                        );
                      })}

                      <td>
                        <div className="fc-eco-row-actions">
                          {editando === ref.id ? (
                            <>
                              <button onClick={() => handleSalvar(ref.id)} className="fc-eco-action-save" title="Salvar" aria-label={`Salvar referência de ${ref.peso_kg} kg`}>
                                <Save className="h-4 w-4" />
                              </button>
                              <button onClick={() => setEditando(null)} className="fc-eco-action-cancel" title="Cancelar" aria-label="Cancelar edição">
                                <X className="h-4 w-4" />
                              </button>
                            </>
                          ) : (
                            <button onClick={() => handleEditar(ref)} className="fc-eco-action-edit" title="Editar" aria-label={`Editar referência de ${ref.peso_kg} kg`}>
                              <Edit2 className="h-4 w-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
