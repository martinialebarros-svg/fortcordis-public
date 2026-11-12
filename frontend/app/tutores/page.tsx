"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import { useCurrentUser } from "@/lib/useCurrentUser";
import TutorIdentificacaoFields, { type TutorIdentificacao } from "@/components/TutorIdentificacaoFields";
import TutorRevisaoCadastro from "@/components/TutorRevisaoCadastro";
import { formatarCpfVisual, formatarTelefoneVisual, normalizarCpf, normalizarTelefone } from "@/lib/atendimento-cadastro";
import { chaveOperacaoTutor, concluirOperacaoTutor, erroTutor, formatarValorTutor, nomesCamposTutor, nomesVinculosTutor, resultadoCampoTutor,
  type EscolhaTutor, type PreviaMesclagem, type PreviaReversaoMesclagem, type ValorTutor } from "@/lib/tutor-mesclagem";

interface TutorLista {
  id: number; nome: string; telefone?: string; whatsapp?: string; email?: string;
  endereco_resumo?: string; identificacao_pendente: boolean; origem_cadastro?: string;
  pets?: { id: number; nome: string }[];
  proximo_atendimento?: string | null;
}
interface TutorForm extends TutorIdentificacao {
  id?: number; nome: string; telefone: string; whatsapp: string; email: string; cpf: string;
}
interface Historico {
  id: number; principal_id: number; secundario_id: number; usuario_nome: string; motivo: string; created_at: string;
  detalhes: { antes: { principal: Record<string, ValorTutor>; secundario: Record<string, ValorTutor> };
    resultado: Record<string, ValorTutor>; vinculos_movidos: Record<string, number[]> };
  reversao?: { usuario_nome: string; motivo: string; created_at: string } | null;
}
const vazio = (): TutorForm => ({ nome: "", telefone: "", whatsapp: "", email: "", cpf: "",
  identificacao_pendente: true, origem_cadastro: "", identificacao_observacoes: "" });
const inputClass = "w-full rounded-lg border border-slate-300 bg-white p-2";
const buttonClass = "rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium disabled:opacity-50";

export default function TutoresPage() {
  const user = useCurrentUser();
  const admin = Array.isArray(user?.papeis) && user.papeis.some((role) => {
    const nome = typeof role === "string" ? role : (role as { nome?: unknown })?.nome;
    return typeof nome === "string" && nome.toLowerCase() === "admin";
  });
  const [items, setItems] = useState<TutorLista[]>([]);
  const [busca, setBusca] = useState("");
  const [pendentes, setPendentes] = useState("todos");
  const [origem, setOrigem] = useState("");
  const [ordenar, setOrdenar] = useState("proximo_atendimento");
  const [pagina, setPagina] = useState(0);
  const [total, setTotal] = useState(0);
  const [versao, setVersao] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [erro, setErro] = useState("");
  const [mensagem, setMensagem] = useState("");
  const [form, setForm] = useState<TutorForm | null>(null);
  const [principal, setPrincipal] = useState<number | null>(null);
  const [secundario, setSecundario] = useState<number | null>(null);
  const [previa, setPrevia] = useState<PreviaMesclagem | null>(null);
  const [escolhas, setEscolhas] = useState<Record<string, EscolhaTutor>>({});
  const [motivo, setMotivo] = useState("");
  const [confirmar, setConfirmar] = useState(false);
  const [historico, setHistorico] = useState<{ tutorId: number; items: Historico[] } | null>(null);
  const [reversao, setReversao] = useState<{ id: number; previa: PreviaReversaoMesclagem } | null>(null);
  const [motivoReversao, setMotivoReversao] = useState("");
  const [confirmarReversao, setConfirmarReversao] = useState(false);
  const previaRef = useRef<HTMLElement>(null);
  const historicoRef = useRef<HTMLElement>(null);

  useEffect(() => { if (previa) previaRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }); }, [previa]);
  useEffect(() => { if (historico) historicoRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }); }, [historico]);

  useEffect(() => {
    let ativo = true;
    setLoading(true);
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ skip: String(pagina * 50), limit: "50" });
      if (busca.trim()) params.set("busca", busca.trim());
      if (pendentes !== "todos") params.set("pendentes", pendentes);
      if (origem.trim()) params.set("origem", origem.trim());
      params.set("ordenar", ordenar);
      api.get(`/tutores?${params}`).then((response) => {
        if (!ativo) return;
        setItems(response.data.items); setTotal(response.data.total);
      }).catch((error: unknown) => {
        if (ativo) { setItems([]); setErro(erroTutor(error)); }
      }).finally(() => { if (ativo) setLoading(false); });
    }, 250);
    return () => { ativo = false; window.clearTimeout(timer); };
  }, [busca, pagina, versao, pendentes, origem, ordenar]);

  const limparPrevia = () => { setPrevia(null); setEscolhas({}); setConfirmar(false); setMotivo(""); };
  const executar = useCallback(async (action: () => Promise<void>) => {
    setBusy(true); setErro(""); setMensagem("");
    try { await action(); } catch (error) { setErro(erroTutor(error)); } finally { setBusy(false); }
  }, []);
  const editar = useCallback((id: number) => executar(async () => {
    const { data } = await api.get(`/tutores/${id}`);
    setForm({ id: data.id, nome: data.nome ?? "", telefone: data.telefone ?? "", whatsapp: data.whatsapp ?? "",
      email: data.email ?? "", cpf: data.cpf ?? "", identificacao_pendente: data.identificacao_pendente,
      origem_cadastro: data.origem_cadastro ?? "", identificacao_observacoes: data.identificacao_observacoes ?? "" });
  }), [executar]);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = Number(params.get("tutor_id"));
    if (Number.isSafeInteger(id) && id > 0) { setBusca(`#${id}`); void editar(id); }
    const principalId = Number(params.get("principal_id"));
    const secundarioId = Number(params.get("secundario_id"));
    if (principalId > 0 && secundarioId > 0 && principalId !== secundarioId) {
      setPrincipal(principalId); setSecundario(secundarioId);
    }
  }, [editar]);
  const salvar = () => executar(async () => {
    if (!form) return;
    const payload = { ...form, telefone: normalizarTelefone(form.telefone), whatsapp: normalizarTelefone(form.whatsapp), cpf: normalizarCpf(form.cpf) };
    if (form.id) await api.put(`/tutores/${form.id}`, payload);
    else {
      const chave_operacao = await chaveOperacaoTutor("novo-tutores", payload);
      await api.post("/tutores", { ...payload, chave_operacao });
      concluirOperacaoTutor("novo-tutores");
    }
    setForm(null); limparPrevia(); setVersao((v) => v + 1); setMensagem("Cadastro salvo.");
  });
  const gerarPrevia = () => executar(async () => {
    limparPrevia();
    const { data } = await api.post("/tutores/mesclagens/previa", { principal_id: principal, secundario_id: secundario });
    setPrevia(data);
  });
  const mesclar = () => executar(async () => {
    if (!previa) return;
    const payload = { principal_id: previa.principal.id, secundario_id: previa.secundario.id,
      token_previa: previa.token_previa, escolhas, motivo: motivo.trim(), confirmar };
    const chave_operacao = await chaveOperacaoTutor("mesclagem-tutores", payload);
    try {
      await api.post("/tutores/mesclagens", { ...payload, chave_operacao });
    } catch (error) {
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 409 || status === 422) limparPrevia();
      throw error;
    }
    concluirOperacaoTutor("mesclagem-tutores");
    setMensagem(`Mesclagem concluída. O cadastro #${previa.principal.id} é o principal; o histórico foi preservado.`);
    setPrincipal(null); setSecundario(null); limparPrevia(); setHistorico(null); setVersao((v) => v + 1);
  });
  const abrirHistorico = (id: number) => executar(async () => {
    const { data } = await api.get(`/tutores/${id}/mesclagens`);
    setHistorico({ tutorId: id, items: data.items });
  });
  const prepararReversao = (id: number) => executar(async () => {
    setReversao(null); setMotivoReversao(""); setConfirmarReversao(false);
    const { data } = await api.post(`/tutores/mesclagens/${id}/reversao/previa`);
    setReversao({ id, previa: data });
  });
  const reverter = () => executar(async () => {
    if (!reversao) return;
    const payload = { token_previa: reversao.previa.token_previa, motivo: motivoReversao.trim(), confirmar: confirmarReversao };
    const chave_operacao = await chaveOperacaoTutor(`reversao-tutores-${reversao.id}`, payload);
    try {
      await api.post(`/tutores/mesclagens/${reversao.id}/reversao`, { ...payload, chave_operacao });
    } catch (error) {
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 409 || status === 422) setReversao(null);
      throw error;
    }
    concluirOperacaoTutor(`reversao-tutores-${reversao.id}`);
    setReversao(null); setHistorico(null); setVersao((v) => v + 1);
    setMensagem("Mesclagem revertida. Os vínculos e os dois cadastros foram restaurados com registro no histórico.");
  });
  const podeMesclar = previa && !previa.bloqueios.length && confirmar && motivo.trim().length >= 5
    && previa.conflitos.every((campo) => escolhas[campo]);

  return <DashboardLayout><div className="mx-auto max-w-6xl space-y-6 p-4 text-slate-800 md:p-6">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div><Link href="/pacientes" className="text-sm text-blue-700">← Pacientes</Link>
        <h1 className="mt-2 text-3xl font-semibold">Tutores</h1>
        <p className="mt-2 text-slate-600">Cadastros separados para pessoas com o mesmo nome. Confirme a identidade antes de reutilizar um cadastro.</p></div>
      <button className={buttonClass} disabled={busy} onClick={() => { concluirOperacaoTutor("novo-tutores"); setForm(vazio()); limparPrevia(); }}>Novo tutor</button>
    </header>
    {erro && <div role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{erro}
      <button className="ml-3 underline" onClick={() => { setErro(""); setVersao((v) => v + 1); }}>Tentar novamente</button></div>}
    {mensagem && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-emerald-900">{mensagem}</p>}
    {form && <form className="grid gap-4 rounded-2xl border bg-white p-5 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); void salvar(); }}>
      <h2 className="col-span-full text-xl font-semibold">{form.id ? `Editar tutor #${form.id}` : "Novo cadastro separado"}</h2>
      <p className="col-span-full text-sm text-slate-600">{form.id
        ? "Complemente os dados disponíveis. A confirmação da identidade fica na revisão opcional abaixo."
        : "Salvar um novo cadastro sempre cria outra pessoa, mesmo que o nome coincida."}</p>
      <label className="col-span-full text-sm">Nome<input required className={`${inputClass} mt-1`} value={form.nome} autoComplete="name"
        onChange={(event) => setForm({ ...form, nome: event.target.value })} /></label>
      <details className="col-span-full space-y-3"><summary className="cursor-pointer text-sm font-medium text-blue-700">Contato e outros dados (opcional)</summary>
      <div className="grid gap-3 md:grid-cols-2">{(["telefone", "whatsapp", "email", "cpf"] as const).map((campo) => <label key={campo} className="text-sm">{nomesCamposTutor[campo]}
        <input type={campo === "email" ? "email" : "text"} inputMode={campo === "email" ? "email" : campo === "cpf" ? "numeric" : "tel"} className={inputClass}
          value={form[campo]} onChange={(event) => setForm({ ...form, [campo]: campo === "cpf" ? formatarCpfVisual(event.target.value)
            : campo === "email" ? event.target.value : formatarTelefoneVisual(event.target.value) })} /></label>)}</div></details>
      <TutorIdentificacaoFields value={form} onChange={(value) => setForm({ ...form, ...value })} />
      <div className="col-span-full flex gap-2"><button disabled={busy || !form.nome.trim()} className={buttonClass}>Salvar cadastro</button>
        <button type="button" disabled={busy} className={buttonClass} onClick={() => setForm(null)}>Cancelar</button></div>
    </form>}
    {form?.id && <TutorRevisaoCadastro tutorId={form.id} onUpdated={() => { setVersao((v) => v + 1); void editar(form.id!); }} />}
    <section aria-label="Fila de revisão dos cadastros" className="grid gap-3 rounded-xl border bg-white p-4 md:grid-cols-3">
      <label className="text-sm">Situação da identificação<select className={`${inputClass} mt-1`} value={pendentes} onChange={(event) => { setPendentes(event.target.value); setPagina(0); }}>
        <option value="todos">Todos os cadastros</option><option value="true">Somente pendentes</option><option value="false">Somente confirmados</option></select></label>
      <label className="text-sm">Clínica ou origem<input className={`${inputClass} mt-1`} value={origem} placeholder="Filtrar pela origem" onChange={(event) => { setOrigem(event.target.value); setPagina(0); }} /></label>
      <label className="text-sm">Ordenar cadastros<select className={`${inputClass} mt-1`} value={ordenar} onChange={(event) => { setOrdenar(event.target.value); setPagina(0); }}>
        <option value="proximo_atendimento">Próximos atendimentos primeiro</option><option value="antigos">Cadastros mais antigos primeiro</option></select></label>
      <p className="text-sm text-slate-600 md:col-span-3">Use a fila para complementar os dados no atendimento. A pendência não impede o agendamento.</p>
    </section>
    <label className="block text-sm font-medium">Buscar tutor, contato, origem ou animal
      <input className={`${inputClass} mt-1`} placeholder="Nome, #código, CPF, telefone ou animal" value={busca} onChange={(event) => { setBusca(event.target.value); setPagina(0); }} /></label>
    {admin && <section aria-label="Selecionar cadastros para mesclagem" className="flex flex-wrap items-center gap-3 rounded-xl bg-slate-100 p-4">
      <p>Principal: <strong>{principal ? `#${principal}` : "selecione"}</strong> · Secundário: <strong>{secundario ? `#${secundario}` : "selecione"}</strong></p>
      <button className={buttonClass} disabled={busy || !principal || !secundario || principal === secundario}
        onClick={() => void gerarPrevia()}>Comparar cadastros</button>
      <button className={buttonClass} disabled={busy} onClick={() => { setPrincipal(null); setSecundario(null); limparPrevia(); }}>Limpar seleção</button>
    </section>}
    {loading ? <p role="status">Carregando tutores…</p> : <div className="grid gap-3 md:grid-cols-2">
      {items.map((tutor) => <article key={tutor.id} className="space-y-2 rounded-xl border bg-white p-4">
        <h2 className="font-semibold">{tutor.nome} <span className="text-slate-500">#{tutor.id}</span></h2>
        <p className={tutor.identificacao_pendente ? "text-sm text-amber-800" : "text-sm text-emerald-800"}>{tutor.identificacao_pendente ? "Identificação pendente" : "Identificação confirmada pela equipe"}</p>
        <p className="text-sm">{tutor.whatsapp || tutor.telefone || "Contato não informado"} · {tutor.origem_cadastro || "Origem não informada"}</p>
        <p className="text-sm text-slate-600">{tutor.endereco_resumo || "Endereço não informado"}</p>
        <p className="text-sm">Animais: {tutor.pets?.map((pet) => `${pet.nome} #${pet.id}`).join(", ") || "Nenhum vinculado"}</p>
        {tutor.proximo_atendimento && <p className="text-sm text-blue-800">Próximo atendimento: {new Date(tutor.proximo_atendimento).toLocaleString("pt-BR", { timeZone: "America/Fortaleza" })}</p>}
        <div className="flex flex-wrap gap-2"><button className={buttonClass} disabled={busy} onClick={() => void editar(tutor.id)}>Editar #{tutor.id}</button>
          {admin && <><button className={buttonClass} disabled={busy || tutor.id === secundario} aria-pressed={principal === tutor.id}
            onClick={() => { setPrincipal(tutor.id); limparPrevia(); }}>Manter #{tutor.id} como principal</button>
          <button className={buttonClass} disabled={busy || tutor.id === principal} aria-pressed={secundario === tutor.id}
            onClick={() => { setSecundario(tutor.id); limparPrevia(); }}>Mesclar #{tutor.id} no principal</button>
          <button className={buttonClass} disabled={busy} onClick={() => void abrirHistorico(tutor.id)}>Histórico #{tutor.id}</button></>}
        </div>
      </article>)}
      {!items.length && <p>Nenhum tutor encontrado.</p>}
    </div>}
    <nav className="flex items-center gap-3" aria-label="Paginação de tutores">
      <button className={buttonClass} disabled={loading || pagina === 0} onClick={() => setPagina((p) => p - 1)}>Anterior</button>
      <span>{total} cadastro(s) · Página {pagina + 1}</span>
      <button className={buttonClass} disabled={loading || (pagina + 1) * 50 >= total} onClick={() => setPagina((p) => p + 1)}>Próxima</button>
    </nav>
    {previa && <section ref={previaRef} aria-label="Prévia da mesclagem" className="scroll-mt-16 space-y-4 rounded-2xl border-2 border-blue-200 bg-white p-5">
      <h2 className="text-xl font-semibold">Revisar mesclagem: #{previa.secundario.id} → #{previa.principal.id}</h2>
      <p>Escolha os dados que devem ficar. O endereço e sua localização são mantidos juntos. Os animais permanecem separados, mesmo quando têm nomes iguais.</p>
      {previa.bloqueios.map((v) => <p role="alert" className="text-red-800" key={v}>{v}</p>)}
      {previa.avisos.map((v) => <p className="text-amber-800" key={v}>{v}</p>)}
      <p className="text-sm text-slate-600 md:hidden">Deslize a tabela para comparar os dois cadastros e o resultado.</p>
      <div className="overflow-x-auto"><table className="w-full min-w-[680px] border-collapse text-left text-sm"><thead><tr>
        <th className="p-2">Campo</th><th className="p-2">Principal #{previa.principal.id}</th><th className="p-2">Secundário #{previa.secundario.id}</th><th className="p-2">Resultado</th>
      </tr></thead><tbody>{previa.campos.map((campo) => <tr key={campo} className="border-t align-top">
        <th className="p-2">{nomesCamposTutor[campo]}{previa.conflitos.includes(campo) && <span className="block font-normal text-amber-800">Escolha obrigatória</span>}</th>
        {(["principal", "secundario"] as const).map((lado) => <td className="max-w-xs p-2" key={lado}><label className="flex items-start gap-2">
          <input type="radio" name={`escolha-${campo}`} aria-label={`${nomesCamposTutor[campo]}: usar ${lado}`}
            disabled={busy}
            checked={escolhas[campo] === lado} onChange={() => { setEscolhas({ ...escolhas, [campo]: lado }); setConfirmar(false); }} />
          <span className="break-words">{formatarValorTutor(previa[lado][campo])}</span></label></td>)}
        <td className="max-w-xs break-words p-2">{previa.conflitos.includes(campo) && !escolhas[campo] ? "Aguardando escolha" : formatarValorTutor(resultadoCampoTutor(previa, escolhas, campo))}</td>
      </tr>)}</tbody></table></div>
      <div><h3 className="font-semibold">Vínculos após a mesclagem</h3>
        <ul className="list-inside list-disc text-sm">{Object.entries(previa.vinculos).map(([tabela, n]) => <li key={tabela}>{nomesVinculosTutor[tabela] || tabela.replace(/_/g, " ")}: {n.principal} existentes + {n.secundario} transferidos = {n.principal + n.secundario}</li>)}</ul>
        <p className="mt-2 text-sm">Animais: {previa.pets.map((p) => `${p.nome} #${p.id}`).join(", ") || "Nenhum"}</p>
      </div>
      <label className="block text-sm font-medium">Motivo e evidência de que é a mesma pessoa
        <textarea className={`${inputClass} mt-1`} value={motivo} rows={2} maxLength={2000}
          disabled={busy}
          onChange={(event) => { setMotivo(event.target.value); setConfirmar(false); }} /></label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" disabled={busy} checked={confirmar} onChange={(event) => setConfirmar(event.target.checked)} />
        Revisei os dados e confirmo que os dois cadastros pertencem à mesma pessoa. O secundário ficará arquivado como mesclado e a operação ficará no histórico.</label>
      <div className="flex gap-2"><button className={`${buttonClass} bg-blue-700 text-white`} disabled={busy || !podeMesclar} onClick={() => void mesclar()}>Confirmar mesclagem</button>
        <button className={buttonClass} disabled={busy} onClick={limparPrevia}>Cancelar mesclagem</button></div>
    </section>}
    {historico && <section ref={historicoRef} aria-label="Histórico de mesclagens" className="scroll-mt-16 space-y-3 rounded-xl border bg-white p-5">
      <div className="flex justify-between"><h2 className="text-xl font-semibold">Histórico do tutor #{historico.tutorId}</h2>
        <button className={buttonClass} onClick={() => setHistorico(null)}>Fechar histórico</button></div>
      {!historico.items.length && <p>Nenhuma mesclagem registrada.</p>}
      {historico.items.map((h) => <article className="space-y-2 border-t pt-3" key={h.id}>
        <p className="font-medium">#{h.secundario_id} mesclado em #{h.principal_id}</p>
        <p className="text-sm">{new Date(h.created_at).toLocaleString("pt-BR", { timeZone: "America/Fortaleza" })} · {h.usuario_nome}</p>
        <p>{h.motivo}</p>
        {h.reversao ? <p className="text-sm text-amber-800">Revertida por {h.reversao.usuario_nome} em {new Date(h.reversao.created_at).toLocaleString("pt-BR", { timeZone: "America/Fortaleza" })}. {h.reversao.motivo}</p>
          : <button className={buttonClass} disabled={busy} onClick={() => void prepararReversao(h.id)}>Revisar reversão da mesclagem #{h.id}</button>}
        <details><summary className="cursor-pointer text-sm text-blue-700">Ver dados anteriores, resultado e vínculos transferidos</summary>
          <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead><tr>
            <th className="p-2">Campo</th><th className="p-2">Principal antes</th><th className="p-2">Secundário antes</th><th className="p-2">Resultado</th>
          </tr></thead><tbody>{Object.keys(nomesCamposTutor).map((campo) => <tr className="border-t align-top" key={campo}>
            <th className="p-2">{nomesCamposTutor[campo]}</th>
            <td className="max-w-xs break-words p-2">{formatarValorTutor(h.detalhes.antes.principal[campo] ?? null)}</td>
            <td className="max-w-xs break-words p-2">{formatarValorTutor(h.detalhes.antes.secundario[campo] ?? null)}</td>
            <td className="max-w-xs break-words p-2">{formatarValorTutor(h.detalhes.resultado[campo] ?? null)}</td>
          </tr>)}</tbody></table></div>
          <ul className="mt-3 text-sm">{Object.entries(h.detalhes.vinculos_movidos).map(([tabela, ids]) => <li key={tabela}>
            {nomesVinculosTutor[tabela] || tabela.replace(/_/g, " ")}: {ids.map((id) => `#${id}`).join(", ")}
          </li>)}</ul></details>
      </article>)}
    </section>}
    {reversao && <section aria-label="Prévia da reversão" className="space-y-4 rounded-xl border-2 border-amber-200 bg-white p-5">
      <h2 className="text-xl font-semibold">Revisar reversão: separar #{reversao.previa.secundario_id} de #{reversao.previa.principal_id}</h2>
      <p className="text-sm text-slate-600">A reversão só é permitida quando os cadastros e seus vínculos permanecem como ficaram na mesclagem. O histórico será preservado.</p>
      {reversao.previa.bloqueios.map((bloqueio) => <p role="alert" className="text-sm text-red-800" key={bloqueio}>{bloqueio}</p>)}
      {reversao.previa.avisos.map((aviso) => <p className="text-sm text-amber-800" key={aviso}>{aviso}</p>)}
      <ul className="list-inside list-disc text-sm">{Object.entries(reversao.previa.vinculos).map(([tabela, quantidade]) => <li key={tabela}>
        {nomesVinculosTutor[tabela] || tabela.replace(/_/g, " ")}: {quantidade} vínculo(s) a restaurar
      </li>)}</ul>
      <label className="block text-sm">Motivo da reversão<textarea className={`${inputClass} mt-1`} rows={2} value={motivoReversao} maxLength={2000} disabled={busy}
        onChange={(event) => { setMotivoReversao(event.target.value); setConfirmarReversao(false); }} /></label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmarReversao} disabled={busy || reversao.previa.bloqueios.length > 0}
        onChange={(event) => setConfirmarReversao(event.target.checked)} />Revisei a separação e confirmo a restauração dos cadastros e vínculos originais.</label>
      <div className="flex flex-wrap gap-2"><button className={buttonClass} disabled={busy || reversao.previa.bloqueios.length > 0 || motivoReversao.trim().length < 5 || !confirmarReversao}
        onClick={() => void reverter()}>Confirmar reversão</button>
        <button className={buttonClass} disabled={busy} onClick={() => setReversao(null)}>Cancelar reversão</button></div>
    </section>}
  </div></DashboardLayout>;
}
