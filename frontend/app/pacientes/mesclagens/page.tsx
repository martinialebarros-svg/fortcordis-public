"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { ATENDIMENTO_OPERATIONAL_TIME_ZONE, isoToOptionalLocalInput } from "@/lib/atendimento-utils";

const rota = "/pacientes/mesclagens";
const button = "rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50";
const input = "mt-1 w-full rounded-xl border border-slate-300 px-3 py-2";
const grupos: Record<string, string> = {
  exames: "Exames", laudos: "Laudos", atendimentos_clinicos: "Atendimentos",
  agendamentos: "Agendamentos", alertas_clinicos: "Alertas clínicos", ordens_servico: "Ordens de serviço",
  contas_receber: "Contas a receber", creditos_financeiros: "Créditos financeiros", transacoes: "Transações",
};

type Ficha = {
  id: number; nome: string; tutor?: string | null; especie?: string | null; raca?: string | null;
  sexo?: string | null; nascimento?: string | null; microchip?: string | null;
};
type Vinculo = {
  id: number; paciente_id: number; status?: string; titulo?: string; tipo?: string; tipo_exame?: string;
  data_solicitacao?: string; data_resultado?: string; data_exame?: string; data_laudo?: string; data_atendimento?: string;
};
type Previa = {
  principal: Ficha; secundario: Ficha; bloqueios: string[]; token_previa: string;
  vinculos: Record<string, { principal: number; secundario: number }>;
  registros: Record<string, Vinculo[]>;
};
type Revisao = {
  id: number; principal_id: number; secundario_id: number; estado: string; criado_por: string; criado_em: string;
  principal_nome?: string; secundario_nome?: string; motivo?: string; confirmado_por?: string; confirmado_em?: string;
  evidencia?: { principal: Ficha; secundario: Ficha; movidos: Record<string, number[]> };
};
type Lista = { items: Revisao[]; tem_mais: boolean };

function erroDaApi(error: unknown): string {
  const e = error as { response?: { status?: number; data?: { detail?: unknown } } };
  if (e.response?.status === 403) return "Somente administradores podem revisar e mesclar pacientes.";
  const detalhe = e.response?.data?.detail;
  return typeof detalhe === "string" ? detalhe : "Não foi possível concluir a solicitação. Tente novamente.";
}

function data(value?: string | null, comHora = false) {
  if (!value) return "Data não informada";
  if (!comHora) {
    const local = isoToOptionalLocalInput(value);
    return local ? local.slice(0, 10).split("-").reverse().join("/") : value;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short", timeStyle: "short", timeZone: ATENDIMENTO_OPERATIONAL_TIME_ZONE,
  }).format(date);
}

function FichaResumo({ ficha, label }: { ficha: Ficha; label: string }) {
  return <div className="rounded-xl border border-slate-200 p-4">
    <h3 className="font-semibold">{label}</h3>
    <p className="mt-1">{ficha.nome} · <Link className="text-blue-800 underline" href={`/pacientes/${ficha.id}`}
      target="_blank" rel="noopener noreferrer">#{ficha.id}</Link></p>
    <p className="text-sm text-slate-600">Tutor: {ficha.tutor || "não informado"}</p>
    <dl className="mt-2 grid gap-x-3 gap-y-1 text-sm sm:grid-cols-2">
      {[
        ["Espécie", ficha.especie], ["Raça", ficha.raca], ["Sexo", ficha.sexo],
        ["Nascimento", ficha.nascimento ? data(ficha.nascimento) : null], ["Microchip", ficha.microchip],
      ].map(([k, v]) => <div key={k}><dt className="inline font-medium">{k}: </dt><dd className="inline">{v || "não informado"}</dd></div>)}
    </dl>
  </div>;
}

export default function MesclagensPacientesPage() {
  const [principal, setPrincipal] = useState("");
  const [secundario, setSecundario] = useState("");
  const [busca, setBusca] = useState("");
  const [encontrados, setEncontrados] = useState<Ficha[] | null>(null);
  const [previa, setPrevia] = useState<Previa | null>(null);
  const [motivo, setMotivo] = useState("");
  const [confirmar, setConfirmar] = useState(false);
  const [aba, setAba] = useState<"pendente" | "historico">("pendente");
  const [offset, setOffset] = useState(0);
  const [lista, setLista] = useState<Lista | null>(null);
  const [recarregar, setRecarregar] = useState(0);
  const [busy, setBusy] = useState(false);
  const [erro, setErro] = useState("");
  const [erroLista, setErroLista] = useState("");
  const [permitido, setPermitido] = useState<boolean | null>(null);
  const [mensagem, setMensagem] = useState("");
  const tituloPrevia = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (previa) {
      tituloPrevia.current?.scrollIntoView?.({ block: "start" });
      tituloPrevia.current?.focus({ preventScroll: true });
    }
  }, [previa]);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("paciente");
    if (id && /^\d+$/.test(id)) setPrincipal(id);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLista(null);
    setErroLista("");
    api.get<Lista>(rota, { params: { estado: aba, offset }, signal: controller.signal })
      .then(({ data }) => {
        if (!controller.signal.aborted) { setLista(data); setPermitido(true); }
      })
      .catch((e) => {
        if (controller.signal.aborted) return;
        if (e?.response?.status === 403) setPermitido(false);
        setErroLista(erroDaApi(e));
      });
    return () => controller.abort();
  }, [aba, offset, recarregar]);

  const p = Number(principal), s = Number(secundario);
  const dupla = Number.isSafeInteger(p) && Number.isSafeInteger(s) && p > 0 && s > 0 && p !== s;
  const payload = { principal_id: p, secundario_id: s };
  const limparPrevia = () => { setPrevia(null); setConfirmar(false); setMotivo(""); };
  const trocarDupla = (novoPrincipal: string, novoSecundario: string) => {
    setPrincipal(novoPrincipal); setSecundario(novoSecundario); limparPrevia(); setErro(""); setMensagem("");
  };
  const executar = async (acao: () => Promise<void>) => {
    if (busy || permitido !== true) return;
    setBusy(true); setErro(""); setMensagem("");
    try { await acao(); } catch (e) { setErro(erroDaApi(e)); }
    finally { setBusy(false); }
  };
  const carregarPrevia = (a: number, b: number) => executar(async () => {
    limparPrevia();
    const { data } = await api.post<Previa>(`${rota}/previa`, { principal_id: a, secundario_id: b });
    setPrevia(data);
  });
  const selecionarAba = (nova: typeof aba) => { setAba(nova); setOffset(0); };
  const pronto = previa && previa.principal.id === p && previa.secundario.id === s
    && !previa.bloqueios.length && confirmar && motivo.trim().length >= 5;

  return <DashboardLayout><main className="mx-auto max-w-5xl space-y-5 px-4 py-6 text-slate-900">
    <header>
      <Link href="/pacientes" className="text-sm text-blue-800 underline">Voltar para Pacientes</Link>
      <h1 className="mt-2 text-2xl font-bold">Revisão de duplicidade de pacientes</h1>
      <p className="mt-1 text-slate-600">Escolha os dois cadastros do mesmo animal. Você pode guardar a revisão e retomá-la depois.</p>
    </header>
    {erro && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-900">{erro}</p>}
    {mensagem && <p role="status" className="rounded-lg bg-green-50 p-3 text-green-900">{mensagem}</p>}
    {permitido === true && <>
      <section className="space-y-4 rounded-2xl border bg-white p-4" aria-label="Escolher os dois cadastros">
        <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => {
          event.preventDefault();
          void executar(async () => {
            setEncontrados(null);
            const { data } = await api.get<{ items?: Ficha[]; pacientes?: Ficha[] }>("/pacientes",
              { params: { search: busca.trim().replace(/^#/, ""), limit: 20 } });
            setEncontrados(data.items ?? data.pacientes ?? []);
          });
        }}>
          <label className="min-w-[14rem] flex-1 text-sm font-medium">Buscar paciente por nome ou código
            <input className={input} value={busca} onChange={(e) => { setBusca(e.target.value); setEncontrados(null); }} disabled={busy} />
          </label>
          <button className={button} disabled={busy || !busca.trim()}>Buscar</button>
        </form>
        {encontrados && (encontrados.length ? <ul className="space-y-2">
          {encontrados.map((f) => <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border p-2 text-sm">
            <span><strong>{f.nome} #{f.id}</strong> · {f.tutor || "Tutor não informado"}{f.especie ? ` · ${f.especie}` : ""}</span>
            <div className="flex flex-wrap gap-2">
              <button className={button} disabled={busy || f.id === s}
                onClick={() => trocarDupla(String(f.id), secundario)}>Manter #{f.id}</button>
              <button className={button} disabled={busy || f.id === p}
                onClick={() => trocarDupla(principal, String(f.id))}>Unir #{f.id} ao principal</button>
            </div>
          </li>)}
        </ul> : <p className="text-sm text-slate-600">Nenhum paciente ativo encontrado.</p>)}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm font-medium">Código do cadastro principal
            <input className={input} inputMode="numeric" value={principal} disabled={busy}
              onChange={(e) => trocarDupla(e.target.value.replace(/\D/g, ""), secundario)} />
          </label>
          <label className="text-sm font-medium">Código do cadastro secundário
            <input className={input} inputMode="numeric" value={secundario} disabled={busy}
              onChange={(e) => trocarDupla(principal, e.target.value.replace(/\D/g, ""))} />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={button} disabled={busy || !dupla} onClick={() => void carregarPrevia(p, s)}>Comparar cadastros</button>
          <button className={button} disabled={busy || !dupla} onClick={() => void executar(async () => {
            const { data } = await api.post<Revisao>(`${rota}/adiar`, payload);
            setMensagem(data.estado === "pendente" ? "Revisão guardada. Retome em Revisões pendentes." : "Essa revisão já foi encerrada.");
            selecionarAba(data.estado === "pendente" ? "pendente" : "historico"); setRecarregar((x) => x + 1);
          })}>Guardar para revisar depois</button>
        </div>
      </section>

      {previa && <section className="space-y-4 rounded-2xl border border-blue-200 bg-white p-4" aria-label="Prévia da mesclagem de pacientes">
        <h2 ref={tituloPrevia} tabIndex={-1} className="scroll-mt-24 text-lg font-bold">Prévia da mesclagem</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <FichaResumo ficha={previa.principal} label="Cadastro que será mantido" />
          <FichaResumo ficha={previa.secundario} label="Cadastro que será arquivado" />
        </div>
        <p className="text-sm text-slate-600">Os vínculos do secundário passam para o principal. O conteúdo dos registros e documentos emitidos é preservado.</p>
        {previa.bloqueios.length > 0 && <ul role="alert" className="list-disc rounded-xl bg-amber-50 p-4 pl-8 text-amber-950">
          {previa.bloqueios.map((b) => <li key={b}>{b}</li>)}
        </ul>}
        {["exames", "laudos", "atendimentos_clinicos"].map((key) => {
          const linhas = previa.registros[key] || [];
          const contagem = previa.vinculos[key];
          return <details key={key} open className="rounded-xl border p-3">
            <summary className="cursor-pointer font-semibold">{grupos[key]}: {contagem?.principal ?? 0} no principal · {contagem?.secundario ?? 0} no secundário</summary>
            {linhas.length ? <ul className="mt-2 max-h-64 divide-y overflow-auto text-sm">
              {linhas.map((r) => <li className="py-2" key={r.id}>
                <strong>#{r.id} {r.titulo || r.tipo_exame || r.tipo || ""}</strong>
                {" · "}{key === "exames" ? "Solicitação: " : key === "atendimentos_clinicos" ? "Atendimento: " : r.data_exame ? "Exame: " : "Laudo: "}
                {data(r.data_exame || r.data_laudo || r.data_solicitacao || r.data_atendimento)}
                {r.data_resultado ? ` · Resultado: ${data(r.data_resultado)}` : ""}
                {" · "}{r.status || "Sem status"}{" · "}
                {r.paciente_id === previa.secundario.id ? "Será vinculado ao principal" : "Já está no principal"}
              </li>)}
            </ul> : <p className="mt-2 text-sm text-slate-600">Nenhum registro vinculado.</p>}
          </details>;
        })}
        {Object.entries(previa.vinculos).some(([k, v]) => !previa.registros[k] && v.secundario) &&
          <details className="rounded-xl border p-3"><summary className="cursor-pointer font-semibold">Outros vínculos que serão transferidos</summary>
            <ul className="mt-2 text-sm">{Object.entries(previa.vinculos).filter(([k, v]) => !previa.registros[k] && v.secundario)
              .map(([k, v]) => <li key={k}>{grupos[k]}: {v.secundario}</li>)}</ul>
          </details>}
        <label className="block text-sm font-medium">Motivo da mesclagem
          <textarea className={input} maxLength={2000} value={motivo} disabled={busy || Boolean(previa.bloqueios.length)}
            onChange={(e) => { setMotivo(e.target.value); setConfirmar(false); }} />
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input className="mt-1" type="checkbox" checked={confirmar} disabled={busy || Boolean(previa.bloqueios.length)}
            onChange={(e) => setConfirmar(e.target.checked)} />
          Confirmei que é o mesmo animal e revisei os registros que serão vinculados ao cadastro principal.
        </label>
        <button className={`${button} bg-blue-800 text-white`} disabled={busy || !pronto} onClick={() => void executar(async () => {
          try {
            await api.post(`${rota}/confirmar`, { ...payload, token_previa: previa.token_previa, motivo: motivo.trim(), confirmar: true });
          } catch (e) {
            // A resposta pode ter se perdido; o servidor devolve o mesmo registro
            // para a repetição da confirmação. Se houver conflito, revise a prévia.
            if ((e as { response?: { status?: number } }).response?.status === 409) limparPrevia();
            throw e;
          }
          limparPrevia(); setSecundario("");
          setMensagem(`Mesclagem concluída. O cadastro #${p} foi mantido. Confira o registro no Histórico.`);
          selecionarAba("historico"); setRecarregar((x) => x + 1);
        })}>Confirmar mesclagem</button>
      </section>}
    </>}

    <section className="space-y-3 rounded-2xl border bg-white p-4" aria-label="Revisões e histórico">
      {permitido === true && <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy} aria-pressed={aba === "pendente"} onClick={() => selecionarAba("pendente")}>Revisões pendentes</button>
        <button className={button} disabled={busy} aria-pressed={aba === "historico"} onClick={() => selecionarAba("historico")}>Histórico</button>
      </div>}
      {erroLista ? <div role="alert" className="space-y-2"><p>{erroLista}</p>
        {permitido !== false && <button className={button} onClick={() => setRecarregar((v) => v + 1)}>Tentar novamente</button>}</div>
        : !lista ? <p role="status">Carregando revisões…</p> : !lista.items.length ? <p className="text-sm text-slate-600">Nenhum registro nesta lista.</p> :
          <ul className="space-y-3">{lista.items.map((r) => <li key={r.id} className="rounded-xl border p-3 text-sm">
            <strong>{r.secundario_nome || "Secundário"} #{r.secundario_id} → {r.principal_nome || "Principal"} #{r.principal_id}</strong>
            <p>Guardado por {r.criado_por} · {data(r.criado_em, true)}</p>
            {r.estado === "pendente" ? <button className={`${button} mt-2`} disabled={busy} onClick={() => {
              trocarDupla(String(r.principal_id), String(r.secundario_id));
              void carregarPrevia(r.principal_id, r.secundario_id);
            }}>Retomar revisão #{r.id}</button> : r.estado === "concluida" ? <>
              <p>Confirmado por {r.confirmado_por} · {data(r.confirmado_em, true)}</p>
              <p>Motivo: {r.motivo}</p>
              {r.evidencia && <details className="mt-2">
                <summary className="cursor-pointer font-medium">Ver registros transferidos</summary>
                <p>{r.evidencia.secundario.nome} → {r.evidencia.principal.nome}</p>
                <ul>{Object.entries(r.evidencia.movidos).map(([k, ids]) =>
                  <li key={k}>{grupos[k]}: {ids.map((id) => `#${id}`).join(", ")}</li>)}</ul>
              </details>}
            </> : <p>Revisão encerrada: um dos cadastros foi mesclado em outra operação.</p>}
          </li>)}</ul>}
      {lista && (offset > 0 || lista.tem_mais) && <nav aria-label="Páginas das revisões" className="flex gap-2">
        <button className={button} disabled={busy || !offset} onClick={() => setOffset((n) => Math.max(0, n - 50))}>Anterior</button>
        <button className={button} disabled={busy || !lista.tem_mais} onClick={() => setOffset((n) => n + 50)}>Próxima</button>
      </nav>}
    </section>
  </main></DashboardLayout>;
}
