"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import api from "@/lib/axios";
import { erroTutor } from "@/lib/tutor-mesclagem";
import { formatarCpfVisual, formatarTelefoneVisual, normalizarCpf, normalizarTelefone } from "@/lib/atendimento-cadastro";

interface TutorRevisao {
  id: number; nome: string; telefone?: string | null; whatsapp?: string | null; email?: string | null;
  cpf?: string | null; identificacao_pendente: boolean; origem_cadastro?: string | null; versao: string;
  identificacao_confirmacao?: { usuario_nome: string; created_at: string; metodo: string; evidencia: string } | null;
}
interface Contato { id: number | null; tipo: string; valor: string; rotulo?: string; principal?: boolean }
interface Origem { id: number | null; descricao: string; clinica_id?: number | null }
interface Evento { id: number; acao: string; usuario_nome: string; created_at: string; metodo?: string; evidencia?: string; motivo?: string }
interface Candidato {
  id: number; nome: string; identificacao_pendente: boolean; telefone?: string; whatsapp?: string;
  origem_cadastro?: string; motivos: string[]; pets?: { id: number; nome: string }[];
}
const inputClass = "mt-1 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm";
const buttonClass = "rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium disabled:opacity-50";
const nomeMetodo: Record<string, string> = {
  atendimento_presencial: "No atendimento presencial", contato_com_tutor: "Em contato com o tutor",
  confirmacao_clinica: "Confirmado pela clínica", documento_conferido: "Documento conferido", outro: "Outro meio",
};
const nomeAcao: Record<string, string> = { confirmar: "Identidade confirmada", reabrir: "Identificação reaberta", invalidar: "Confirmação invalidada" };
function dataHora(value: string): string { return new Date(value).toLocaleString("pt-BR", { timeZone: "America/Fortaleza" }); }
function formularioTutor(data: TutorRevisao) {
  return { nome: data.nome || "", telefone: formatarTelefoneVisual(data.telefone || ""),
    whatsapp: formatarTelefoneVisual(data.whatsapp || ""), email: data.email || "", cpf: formatarCpfVisual(data.cpf || ""),
    origem_cadastro: data.origem_cadastro || "" };
}

/** Revisão opcional: não carrega sugestões nem interfere no salvamento do atendimento. */
type TutorRevisaoCadastroProps = { tutorId: number; onUpdated?: () => void | Promise<void> };
export default function TutorRevisaoCadastro(props: TutorRevisaoCadastroProps) {
  return <TutorRevisaoCadastroConteudo key={props.tutorId} {...props} />;
}

function TutorRevisaoCadastroConteudo({ tutorId, onUpdated }: TutorRevisaoCadastroProps) {
  const montado = useRef(true);
  useEffect(() => { montado.current = true; return () => { montado.current = false; }; }, []);
  const [aberto, setAberto] = useState(false);
  const [tutor, setTutor] = useState<TutorRevisao | null>(null);
  const [form, setForm] = useState({ nome: "", telefone: "", whatsapp: "", email: "", cpf: "", origem_cadastro: "" });
  const [contatos, setContatos] = useState<Contato[]>([]);
  const [origens, setOrigens] = useState<Origem[]>([]);
  const [historico, setHistorico] = useState<Evento[]>([]);
  const [candidatos, setCandidatos] = useState<Candidato[] | null>(null);
  const [descartes, setDescartes] = useState<Record<number, string>>({});
  const [metodo, setMetodo] = useState("");
  const [evidencia, setEvidencia] = useState("");
  const [reabrirMotivo, setReabrirMotivo] = useState("");
  const [contato, setContato] = useState({ tipo: "telefone", valor: "", rotulo: "" });
  const [origem, setOrigem] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [erro, setErro] = useState("");
  const [mensagem, setMensagem] = useState("");

  const carregar = useCallback(async (isCurrent: () => boolean = () => true, preservarFormulario = false) => {
    if (!montado.current) return;
    setLoading(true);
    const resultados = await Promise.allSettled([
      api.get(`/tutores/${tutorId}`), api.get(`/tutores/${tutorId}/contatos`),
      api.get(`/tutores/${tutorId}/origens`), api.get(`/tutores/${tutorId}/identificacao/historico`),
    ]);
    if (!montado.current || !isCurrent()) return;
    const [cadastro, listaContatos, listaOrigens, eventos] = resultados;
    if (cadastro.status === "fulfilled") {
      const data = cadastro.value.data as TutorRevisao;
      setTutor(data);
      if (!preservarFormulario) setForm(formularioTutor(data));
    } else setTutor(null);
    if (listaContatos.status === "fulfilled") setContatos(listaContatos.value.data.items);
    if (listaOrigens.status === "fulfilled") setOrigens(listaOrigens.value.data.items);
    if (eventos.status === "fulfilled") setHistorico(eventos.value.data.items);
    const falha = resultados.find((r) => r.status === "rejected");
    if (falha?.status === "rejected") setErro(erroTutor(falha.reason));
    setLoading(false);
  }, [tutorId]);

  useEffect(() => {
    setTutor(null); setContatos([]); setOrigens([]); setHistorico([]); setCandidatos(null);
    setErro(""); setMensagem(""); setEvidencia(""); setMetodo(""); setDescartes({});
    if (!aberto) return;
    let ativo = true;
    void carregar(() => ativo);
    return () => { ativo = false; };
  }, [aberto, carregar]);

  const executar = async (acao: () => Promise<void>) => {
    setBusy(true); setErro(""); setMensagem("");
    try { await acao(); } catch (error) { setErro(erroTutor(error)); } finally { setBusy(false); }
  };
  const atualizado = async (texto: string, preservarFormulario = false) => {
    if (!montado.current) return;
    await carregar(() => montado.current, preservarFormulario);
    if (!montado.current) return;
    setMensagem(texto);
    try { await onUpdated?.(); } catch {
      setErro("Os dados foram salvos, mas não foi possível atualizar o resumo do atendimento. Recarregue o cadastro para conferir.");
    }
  };
  const salvar = () => executar(async () => {
    await api.put(`/tutores/${tutorId}`, { ...form, telefone: normalizarTelefone(form.telefone),
      whatsapp: normalizarTelefone(form.whatsapp), cpf: normalizarCpf(form.cpf) });
    await atualizado("Dados do tutor atualizados. A confirmação da identidade é feita separadamente.");
  });
  const confirmar = () => executar(async () => {
    if (!tutor) return;
    await api.post(`/tutores/${tutorId}/identificacao/confirmar`, { metodo, evidencia: evidencia.trim(), versao: tutor.versao });
    setMetodo(""); setEvidencia(""); await atualizado("Identidade confirmada e registrada no histórico.");
  });
  const reabrir = () => executar(async () => {
    await api.post(`/tutores/${tutorId}/identificacao/reabrir`, { motivo: reabrirMotivo.trim() });
    setReabrirMotivo(""); await atualizado("Identificação marcada para nova conferência.");
  });
  const buscarDuplicidades = () => executar(async () => {
    const { data } = await api.get(`/tutores/${tutorId}/duplicidades`); setCandidatos(data.items);
  });
  const dadosAlterados = Boolean(tutor && JSON.stringify(form) !== JSON.stringify(formularioTutor(tutor)));

  return <details className="rounded-xl border border-slate-200 bg-white p-4" onToggle={(event) => setAberto(event.currentTarget.open)}>
    <summary className="cursor-pointer font-medium text-blue-800">Revisar cadastro do tutor #{tutorId} (opcional)</summary>
    {aberto && <div className="mt-4 space-y-5">
      <p className="text-sm text-slate-600">Complete o que souber durante o atendimento. A identificação pode continuar pendente.</p>
      {erro && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{erro}
        <button type="button" className="ml-2 underline" disabled={busy || loading} onClick={() => { setErro(""); void carregar(); }}>Recarregar cadastro</button></div>}
      {mensagem && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">{mensagem}</p>}
      {loading && <p role="status" className="text-sm">Carregando cadastro…</p>}
      {tutor && <>
        <section aria-label="Complementar dados do tutor" className="space-y-3">
          <h3 className="font-semibold">{tutor.nome} #{tutorId}</h3>
          <p className="text-sm">{tutor.identificacao_pendente ? "Identificação pendente" : "Identificação confirmada pela equipe"}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">Nome do tutor<input className={inputClass} value={form.nome} disabled={busy}
              onChange={(event) => setForm({ ...form, nome: event.target.value })} /></label>
            <label className="text-sm">Telefone do tutor<input className={inputClass} value={form.telefone} inputMode="tel" disabled={busy}
              onChange={(event) => setForm({ ...form, telefone: formatarTelefoneVisual(event.target.value) })} /></label>
            <label className="text-sm">WhatsApp do tutor<input className={inputClass} value={form.whatsapp} inputMode="tel" disabled={busy}
              onChange={(event) => setForm({ ...form, whatsapp: formatarTelefoneVisual(event.target.value) })} /></label>
            <label className="text-sm">E-mail do tutor<input className={inputClass} value={form.email} type="email" disabled={busy}
              onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
            <label className="text-sm">CPF do tutor (opcional)<input className={inputClass} value={form.cpf} inputMode="numeric" disabled={busy}
              onChange={(event) => setForm({ ...form, cpf: formatarCpfVisual(event.target.value) })} /></label>
            <label className="text-sm">Origem principal<input className={inputClass} value={form.origem_cadastro} disabled={busy}
              onChange={(event) => setForm({ ...form, origem_cadastro: event.target.value })} /></label>
          </div>
          <button type="button" className={buttonClass} disabled={busy || loading || !form.nome.trim()} onClick={() => void salvar()}>Salvar dados do tutor</button>
        </section>
        <details className="space-y-3 border-t pt-3"><summary className="cursor-pointer text-sm font-medium">Outros contatos e clínicas de origem</summary>
          <p className="text-sm text-slate-600">Um contato pode pertencer à família ou à clínica. Informar o vínculo ajuda a diferenciá-lo.</p>
          <ul className="space-y-1 text-sm">{contatos.map((c, i) => <li key={c.id ?? `legado-${i}`}>{c.tipo}: {c.valor}{c.rotulo ? ` · ${c.rotulo}` : ""}{c.principal ? " · principal" : ""}</li>)}</ul>
          <div className="grid gap-2 sm:grid-cols-3"><label className="text-sm">Tipo de contato<select className={inputClass} value={contato.tipo}
            onChange={(event) => setContato({ ...contato, tipo: event.target.value })}><option value="telefone">Telefone</option><option value="whatsapp">WhatsApp</option><option value="email">E-mail</option></select></label>
            <label className="text-sm">Contato adicional<input className={inputClass} value={contato.valor} onChange={(event) => setContato({ ...contato, valor: event.target.value })} /></label>
            <label className="text-sm">De quem é este contato?<input className={inputClass} placeholder="Ex.: tutor, cônjuge, clínica" value={contato.rotulo} onChange={(event) => setContato({ ...contato, rotulo: event.target.value })} /></label></div>
          <button type="button" className={buttonClass} disabled={busy || !contato.valor.trim()} onClick={() => void executar(async () => {
            await api.post(`/tutores/${tutorId}/contatos`, { ...contato, valor: contato.valor.trim(), rotulo: contato.rotulo.trim() });
            setContato({ tipo: "telefone", valor: "", rotulo: "" }); await atualizado("Contato adicional registrado.", dadosAlterados);
          })}>Adicionar contato</button>
          <ul className="space-y-1 text-sm">{origens.map((o, i) => <li key={o.id ?? `legado-${i}`}>{o.descricao}</li>)}</ul>
          <label className="block text-sm">Outra clínica ou origem<input className={inputClass} value={origem} onChange={(event) => setOrigem(event.target.value)} /></label>
          <button type="button" className={buttonClass} disabled={busy || !origem.trim()} onClick={() => void executar(async () => {
            await api.post(`/tutores/${tutorId}/origens`, { descricao: origem.trim() }); setOrigem(""); await atualizado("Origem adicional registrada.", dadosAlterados);
          })}>Adicionar origem</button>
        </details>
        <details className="space-y-3 border-t pt-3"><summary className="cursor-pointer text-sm font-medium">Confirmar identidade e consultar histórico</summary>
          {tutor.identificacao_confirmacao && <p className="text-sm">Confirmado por {tutor.identificacao_confirmacao.usuario_nome} em {dataHora(tutor.identificacao_confirmacao.created_at)} · {nomeMetodo[tutor.identificacao_confirmacao.metodo] || tutor.identificacao_confirmacao.metodo}. {tutor.identificacao_confirmacao.evidencia}</p>}
          {tutor.identificacao_pendente ? <>
            <label className="block text-sm">Como a identidade foi confirmada?<select className={inputClass} value={metodo} onChange={(event) => setMetodo(event.target.value)}>
              <option value="">Selecione quando tiver conferido</option>{Object.entries(nomeMetodo).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
            <label className="block text-sm">Evidência da confirmação<textarea className={inputClass} rows={2} value={evidencia} maxLength={2000}
              placeholder="Ex.: tutor confirmou o nome completo e os animais durante o atendimento" onChange={(event) => setEvidencia(event.target.value)} /></label>
            {dadosAlterados && <p className="text-sm text-amber-800">Salve os dados do tutor acima antes de confirmar a identidade.</p>}
            <button type="button" className={buttonClass} disabled={busy || loading || dadosAlterados || !tutor.versao || !metodo || evidencia.trim().length < 5} onClick={() => void confirmar()}>Confirmar identidade</button>
          </> : <>
            <label className="block text-sm">Motivo para conferir novamente<textarea className={inputClass} rows={2} value={reabrirMotivo} maxLength={2000} onChange={(event) => setReabrirMotivo(event.target.value)} /></label>
            <button type="button" className={buttonClass} disabled={busy || reabrirMotivo.trim().length < 5} onClick={() => void reabrir()}>Reabrir identificação pendente</button>
          </>}
          <ul className="space-y-2 text-sm">{historico.map((h) => <li key={h.id} className="border-t pt-2"><strong>{nomeAcao[h.acao] || h.acao}</strong> · {h.usuario_nome} · {dataHora(h.created_at)}<p>{h.metodo ? `${nomeMetodo[h.metodo] || h.metodo} · ` : ""}{h.evidencia || h.motivo}</p></li>)}</ul>
          {!historico.length && <p className="text-sm text-slate-600">Nenhuma confirmação de identidade registrada.</p>}
        </details>
        <section aria-label="Revisar possíveis duplicidades" className="space-y-3 border-t pt-3">
          <h3 className="font-medium">Possíveis cadastros da mesma pessoa</h3>
          <p className="text-sm text-slate-600">As coincidências são pistas para revisão. Um nome ou telefone igual pode pertencer a pessoas diferentes.</p>
          <button type="button" className={buttonClass} disabled={busy || loading} onClick={() => void buscarDuplicidades()}>Procurar possíveis duplicidades</button>
          {candidatos?.length === 0 && <p className="text-sm">Nenhum candidato encontrado pelos dados disponíveis.</p>}
          {candidatos?.map((c) => <article className="space-y-2 rounded-lg border p-3 text-sm" key={c.id}>
            <p className="font-medium">{c.nome} #{c.id}</p><p>{c.whatsapp || c.telefone || "Contato não informado"} · {c.origem_cadastro || "Origem não informada"}</p>
            <p>Animais: {c.pets?.map((p) => `${p.nome} #${p.id}`).join(", ") || "Nenhum vinculado"}</p>
            <p>Por que apareceu: {c.motivos.join("; ")}</p>
            <div className="flex flex-wrap gap-3"><Link href={`/tutores?tutor_id=${c.id}`} className="text-blue-700 underline">Abrir cadastro #{c.id}</Link>
              <Link href={`/tutores?principal_id=${tutorId}&secundario_id=${c.id}`} className="text-blue-700 underline">Revisar os dois cadastros para mesclagem</Link></div>
            <label className="block">Por que são pessoas diferentes?<input className={inputClass} value={descartes[c.id] || ""} onChange={(event) => setDescartes({ ...descartes, [c.id]: event.target.value })} /></label>
            <button type="button" className={buttonClass} disabled={busy || (descartes[c.id] || "").trim().length < 5} onClick={() => void executar(async () => {
              await api.post(`/tutores/${tutorId}/duplicidades/${c.id}/descartar`, { motivo: descartes[c.id].trim() });
              setCandidatos((prev) => prev?.filter((item) => item.id !== c.id) ?? null); setMensagem("Pessoas distintas registradas. Essa sugestão foi dispensada.");
            })}>Registrar que são pessoas diferentes</button>
          </article>)}
        </section>
      </>}
    </div>}
  </details>;
}
