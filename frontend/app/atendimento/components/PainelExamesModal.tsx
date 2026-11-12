"use client";

import { useState } from "react";
import { ArrowLeft, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { parseCatalogoExameSinonimos } from "@/lib/catalogo-exames";
import Modal from "./Modal";
import type { LooseAtendimentoComponentProps } from "./component-props";

type PainelExamesModalProps = LooseAtendimentoComponentProps;

export default function PainelExamesModal(props: PainelExamesModalProps) {
  const {
    catalogoExames,
    customPaineis,
    editarPainelExame,
    excluirCatalogoExameCustomizado,
    excluirPainelExame,
    painelEmEdicao,
    painelFormCategoria,
    painelFormErro,
    painelFormItens,
    painelFormNome,
    painelFormSearch,
    painelModalMode,
    salvarCatalogoExameCustomizado,
    salvarPainelExame,
    setPainelEmEdicao,
    setPainelFormCategoria,
    setPainelFormErro,
    setPainelFormItens,
    setPainelFormNome,
    setPainelFormSearch,
    setPainelModalMode,
    setPainelModalOpen,
  } = props;

  const emptyCatalogoForm = () => ({
    nome: "",
    categoria: "",
    subcategoria: "",
    sinonimos: "",
    preparo: "",
    observacoes_padrao: "",
  });
  const [catalogoEditorOpen, setCatalogoEditorOpen] = useState(false);
  const [catalogoEmEdicao, setCatalogoEmEdicao] = useState<PainelExamesModalProps | null>(null);
  const [catalogoForm, setCatalogoForm] = useState(emptyCatalogoForm);
  const [catalogoFormErro, setCatalogoFormErro] = useState("");
  const [salvandoCatalogo, setSalvandoCatalogo] = useState(false);

  const exameCustomizado = (exame: PainelExamesModalProps) =>
    Boolean(exame?.customizado || String(exame?.codigo || "").startsWith("custom_exam_"));

  const fecharEditorCatalogo = () => {
    setCatalogoEditorOpen(false);
    setCatalogoEmEdicao(null);
    setCatalogoForm(emptyCatalogoForm());
    setCatalogoFormErro("");
  };

  const abrirNovoExameCatalogo = () => {
    setCatalogoEmEdicao(null);
    setCatalogoForm(emptyCatalogoForm());
    setCatalogoFormErro("");
    setCatalogoEditorOpen(true);
  };

  const abrirEdicaoExameCatalogo = (exame: PainelExamesModalProps) => {
    setCatalogoEmEdicao(exame);
    setCatalogoForm({
      nome: exame.nome || "",
      categoria: exame.categoria || "",
      subcategoria: exame.subcategoria || "",
      sinonimos: Array.isArray(exame.sinonimos) ? exame.sinonimos.join(", ") : "",
      preparo: exame.preparo || "",
      observacoes_padrao: exame.observacoes_padrao || "",
    });
    setCatalogoFormErro("");
    setCatalogoEditorOpen(true);
  };

  const atualizarCatalogoForm = (field: string, value: string) => {
    setCatalogoForm((current) => ({ ...current, [field]: value }));
  };

  const salvarExameCatalogo = async () => {
    const nome = catalogoForm.nome.trim();
    const categoria = catalogoForm.categoria.trim();
    if (nome.length < 2 || categoria.length < 2) {
      setCatalogoFormErro("Informe nome e categoria com pelo menos 2 caracteres.");
      return;
    }

    setSalvandoCatalogo(true);
    setCatalogoFormErro("");
    const result = await salvarCatalogoExameCustomizado(
      {
        nome,
        categoria,
        subcategoria: catalogoForm.subcategoria.trim(),
        especie_alvo: "",
        prioridade_padrao: "Rotina",
        valor_padrao: 0,
        preparo: catalogoForm.preparo.trim(),
        observacoes_padrao: catalogoForm.observacoes_padrao.trim(),
        sinonimos: parseCatalogoExameSinonimos(catalogoForm.sinonimos),
      },
      catalogoEmEdicao?.id
    );
    setSalvandoCatalogo(false);

    if (!result.ok) {
      setCatalogoFormErro(result.error);
      return;
    }
    if (!catalogoEmEdicao) {
      setPainelFormItens((current: number[]) =>
        current.includes(result.item.id) ? current : [...current, result.item.id]
      );
    }
    fecharEditorCatalogo();
  };

  const removerExameCatalogo = async (exame: PainelExamesModalProps) => {
    setCatalogoFormErro("");
    const result = await excluirCatalogoExameCustomizado(exame);
    if (!result.ok) {
      if (result.error) setCatalogoFormErro(result.error);
      return;
    }
    fecharEditorCatalogo();
  };

  const fecharModal = () => {
    setPainelModalOpen(false);
    setPainelModalMode("list");
  };

  return (
    <Modal
      titleId="painel-exames-modal-titulo"
      onClose={fecharModal}
      overlayClassName="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      contentClassName="relative w-full max-w-3xl max-h-[85vh] overflow-auto rounded-3xl bg-white shadow-2xl"
    >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
          <div className="flex items-center gap-3">
            {painelModalMode === "edit" ? (
              <button
                type="button"
                onClick={() => {
                  setPainelModalMode("list");
                  setPainelFormNome("");
                  setPainelFormItens([]);
                  setPainelEmEdicao(null);
                }}
                className="rounded-full bg-slate-100 p-2 hover:bg-slate-200"
              >
                <ArrowLeft className="h-4 w-4 text-slate-600" />
              </button>
            ) : null}
            <h3 id="painel-exames-modal-titulo" className="text-lg font-bold text-slate-900">
              {painelModalMode === "create"
                ? "Novo painel de exames"
                : painelModalMode === "edit"
                  ? `Editando: ${painelEmEdicao?.nome || ""}`
                  : "Gerenciar paineis"}
            </h3>
          </div>
          <button
            type="button"
            onClick={fecharModal}
            className="rounded-full bg-slate-100 p-2 hover:bg-slate-200"
          >
            <X className="h-4 w-4 text-slate-600" />
          </button>
        </div>

        <div className="px-6 py-4">
          {painelModalMode === "list" ? (
            <div>
              <div className="mb-4 flex justify-end">
                <button
                  type="button"
                  onClick={() => {
                    setPainelFormNome("");
                    setPainelFormCategoria("");
                    setPainelFormItens([]);
                    setPainelFormSearch("");
                    setPainelFormErro("");
                    setPainelModalMode("create");
                  }}
                  className="rounded-2xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
                >
                  + Novo painel
                </button>
              </div>
              {customPaineis.length === 0 ? (
                <p className="text-sm text-slate-500">Nenhum painel customizado. Crie seu primeiro painel.</p>
              ) : (
                <div className="space-y-2">
                  {customPaineis.map((painel: PainelExamesModalProps) => (
                    <div key={painel.id} className="flex items-center justify-between rounded-2xl border border-slate-200 px-4 py-3">
                      <div>
                        <p className="font-medium text-slate-900">{painel.nome}</p>
                        <p className="text-xs text-slate-500">
                          {painel.categoria || "Sem categoria"} · {painel.itens?.length || 0} exame(s)
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => editarPainelExame(painel)}
                          className="rounded-xl bg-sky-100 px-3 py-1.5 text-xs font-medium text-sky-700 hover:bg-sky-200"
                        >
                          Editar
                        </button>
                        <button
                          type="button"
                          onClick={() => excluirPainelExame(painel.id)}
                          className="rounded-xl bg-rose-100 p-1.5 text-rose-600 hover:bg-rose-200"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}

          {painelModalMode === "create" || painelModalMode === "edit" ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Nome do painel *</label>
                  <input
                    value={painelFormNome}
                    onChange={(e) => setPainelFormNome(e.target.value)}
                    placeholder="Ex: Cardiológico Básico"
                    className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-900"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Categoria</label>
                  <input
                    value={painelFormCategoria}
                    onChange={(e) => setPainelFormCategoria(e.target.value)}
                    placeholder="Ex: Cardiologia"
                    className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-900"
                  />
                </div>
              </div>

              {painelFormErro ? <p className="text-sm text-rose-600">{painelFormErro}</p> : null}

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label className="text-xs font-medium text-slate-600">
                    Exames ({painelFormItens.length} selecionado(s))
                  </label>
                  <button
                    type="button"
                    onClick={abrirNovoExameCatalogo}
                    className="rounded-xl bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-200"
                  >
                    + Novo exame
                  </button>
                </div>

                {catalogoEditorOpen ? (
                  <div className="mb-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <div>
                        <p className="text-sm font-semibold text-emerald-900">
                          {catalogoEmEdicao ? `Editar ${catalogoEmEdicao.nome}` : "Adicionar exame ao catalogo"}
                        </p>
                        <p className="text-xs text-emerald-700">
                          O item ficara disponivel para este e para os proximos paineis.
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={fecharEditorCatalogo}
                        className="rounded-full bg-white p-1.5 text-slate-500 hover:bg-emerald-100"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="text-xs font-medium text-slate-700">
                        Nome do exame *
                        <input
                          value={catalogoForm.nome}
                          onChange={(event) => atualizarCatalogoForm("nome", event.target.value)}
                          placeholder="Ex: Relacao proteina/creatinina urinaria"
                          className="mt-1 w-full rounded-xl border border-emerald-200 bg-white px-3 py-2 text-sm font-normal text-slate-900"
                        />
                      </label>
                      <label className="text-xs font-medium text-slate-700">
                        Categoria *
                        <input
                          value={catalogoForm.categoria}
                          onChange={(event) => atualizarCatalogoForm("categoria", event.target.value)}
                          placeholder="Ex: Laboratorio"
                          className="mt-1 w-full rounded-xl border border-emerald-200 bg-white px-3 py-2 text-sm font-normal text-slate-900"
                        />
                      </label>
                      <label className="text-xs font-medium text-slate-700">
                        Subcategoria
                        <input
                          value={catalogoForm.subcategoria}
                          onChange={(event) => atualizarCatalogoForm("subcategoria", event.target.value)}
                          placeholder="Ex: Urinaria"
                          className="mt-1 w-full rounded-xl border border-emerald-200 bg-white px-3 py-2 text-sm font-normal text-slate-900"
                        />
                      </label>
                      <label className="text-xs font-medium text-slate-700">
                        Sinonimos
                        <input
                          value={catalogoForm.sinonimos}
                          onChange={(event) => atualizarCatalogoForm("sinonimos", event.target.value)}
                          placeholder="Ex: RPCU, UPC"
                          className="mt-1 w-full rounded-xl border border-emerald-200 bg-white px-3 py-2 text-sm font-normal text-slate-900"
                        />
                      </label>
                    </div>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <label className="text-xs font-medium text-slate-700">
                        Preparo sugerido
                        <textarea
                          value={catalogoForm.preparo}
                          onChange={(event) => atualizarCatalogoForm("preparo", event.target.value)}
                          rows={2}
                          className="mt-1 w-full rounded-xl border border-emerald-200 bg-white px-3 py-2 text-sm font-normal text-slate-900"
                        />
                      </label>
                      <label className="text-xs font-medium text-slate-700">
                        Observacoes padrao
                        <textarea
                          value={catalogoForm.observacoes_padrao}
                          onChange={(event) => atualizarCatalogoForm("observacoes_padrao", event.target.value)}
                          rows={2}
                          className="mt-1 w-full rounded-xl border border-emerald-200 bg-white px-3 py-2 text-sm font-normal text-slate-900"
                        />
                      </label>
                    </div>

                    {catalogoFormErro ? <p className="mt-2 text-sm text-rose-600">{catalogoFormErro}</p> : null}

                    <div className="mt-3 flex flex-wrap justify-between gap-2">
                      <div>
                        {catalogoEmEdicao ? (
                          <button
                            type="button"
                            onClick={() => void removerExameCatalogo(catalogoEmEdicao)}
                            disabled={salvandoCatalogo}
                            className="rounded-xl bg-rose-100 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-200 disabled:opacity-50"
                          >
                            Remover do catalogo
                          </button>
                        ) : null}
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={fecharEditorCatalogo}
                          disabled={salvandoCatalogo}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                        >
                          Cancelar
                        </button>
                        <button
                          type="button"
                          onClick={() => void salvarExameCatalogo()}
                          disabled={salvandoCatalogo}
                          className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          {salvandoCatalogo ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                          {catalogoEmEdicao ? "Salvar exame" : "Adicionar e selecionar"}
                        </button>
                      </div>
                    </div>
                  </div>
                ) : null}

                <div className="mb-2">
                  <input
                    value={painelFormSearch}
                    onChange={(e) => setPainelFormSearch(e.target.value)}
                    placeholder="Buscar exame..."
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900"
                  />
                </div>
                {painelFormItens.length > 0 ? (
                  <div className="mb-3 rounded-2xl border border-blue-200 bg-blue-50 p-3">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-blue-700">Selecionados</p>
                    <div className="flex flex-wrap gap-1.5">
                      {painelFormItens.map((exameId: number) => {
                        const exam = catalogoExames.find((e: PainelExamesModalProps) => e.id === exameId);
                        if (!exam) return null;
                        return (
                          <span key={exameId} className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700">
                            {exam.nome}
                            {exameCustomizado(exam) ? (
                              <button
                                type="button"
                                onClick={() => abrirEdicaoExameCatalogo(exam)}
                                title="Editar exame customizado"
                                className="rounded-full bg-emerald-100 p-0.5 text-emerald-700 hover:bg-emerald-200"
                              >
                                <Pencil className="h-3 w-3" />
                              </button>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => setPainelFormItens((prev: number[]) => prev.filter((id) => id !== exameId))}
                              className="rounded-full bg-blue-200 p-0.5 hover:bg-blue-300"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                <div className="max-h-60 overflow-auto rounded-2xl border border-slate-200">
                  {catalogoExames
                    .filter(
                      (exame: PainelExamesModalProps) =>
                        !painelFormItens.includes(exame.id) &&
                        (painelFormSearch === "" ||
                          exame.nome.toLowerCase().includes(painelFormSearch.toLowerCase()) ||
                          exame.categoria.toLowerCase().includes(painelFormSearch.toLowerCase()))
                    )
                    .slice(0, 30)
                    .map((exame: PainelExamesModalProps) => (
                      <div
                        key={exame.id}
                        className="flex items-center border-b border-slate-100 last:border-b-0 hover:bg-sky-50"
                      >
                        <button
                          type="button"
                          onClick={() => setPainelFormItens((prev: number[]) => [...prev, exame.id])}
                          className="flex min-w-0 flex-1 items-center justify-between px-4 py-2.5 text-left text-sm"
                        >
                          <div className="min-w-0">
                            <p className="truncate font-medium text-slate-800">{exame.nome}</p>
                            <p className="truncate text-xs text-slate-500">{exame.categoria}</p>
                          </div>
                          <Plus className="ml-3 h-4 w-4 shrink-0 text-slate-400" />
                        </button>
                        {exameCustomizado(exame) ? (
                          <button
                            type="button"
                            onClick={() => abrirEdicaoExameCatalogo(exame)}
                            title="Editar exame customizado"
                            className="mr-2 rounded-lg bg-emerald-100 p-2 text-emerald-700 hover:bg-emerald-200"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                        ) : null}
                      </div>
                    ))}
                  {catalogoExames.filter(
                    (exame: PainelExamesModalProps) =>
                      !painelFormItens.includes(exame.id) &&
                      (painelFormSearch === "" ||
                        exame.nome.toLowerCase().includes(painelFormSearch.toLowerCase()) ||
                        exame.categoria.toLowerCase().includes(painelFormSearch.toLowerCase()))
                  ).length === 0 ? (
                    <p className="p-4 text-center text-sm text-slate-500">Nenhum exame disponivel.</p>
                  ) : null}
                </div>
              </div>

              <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
                <button
                  type="button"
                  onClick={() => {
                    setPainelModalMode("list");
                    setPainelFormNome("");
                    setPainelFormItens([]);
                    setPainelEmEdicao(null);
                  }}
                  className="rounded-2xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={() => salvarPainelExame(painelModalMode)}
                  className="rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700"
                >
                  {painelModalMode === "create" ? "Criar painel" : "Salvar alteracoes"}
                </button>
              </div>
            </div>
          ) : null}
        </div>
    </Modal>
  );
}
