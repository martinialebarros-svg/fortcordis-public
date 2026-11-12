"use client";

import { useEffect, useRef, useState } from "react";
import api from "@/lib/axios";
import { erroTutor } from "@/lib/tutor-mesclagem";

export interface TutorExistenteDetail {
  id: number;
  nome?: string | null;
  telefone?: string | null;
  whatsapp?: string | null;
  email?: string | null;
  cpf?: string | null;
  cep?: string | null;
  endereco?: string | null;
  numero?: string | null;
  complemento?: string | null;
  bairro?: string | null;
  cidade?: string | null;
  estado?: string | null;
  identificacao_pendente?: boolean;
  origem_cadastro?: string | null;
  identificacao_observacoes?: string | null;
  ativo?: number | boolean | null;
  mesclado_em_id?: number | null;
}

interface TutorResultado extends TutorExistenteDetail {
  pets?: { id: number; nome: string }[];
}

export default function TutorExistenteSelector({ onSelect, onCancel }: {
  onSelect: (tutor: TutorExistenteDetail) => void;
  onCancel: () => void;
}) {
  const [busca, setBusca] = useState("");
  const [items, setItems] = useState<TutorResultado[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [erro, setErro] = useState("");
  const [tentativa, setTentativa] = useState(0);
  const selectionRequest = useRef(0);

  useEffect(() => () => { selectionRequest.current += 1; }, []);

  useEffect(() => {
    let active = true;
    const termo = busca.trim();
    setItems([]);
    setErro("");
    setLoading(Boolean(termo));
    if (!termo) return;
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ busca: termo, limit: "20" });
      api.get(`/tutores?${params}`).then(({ data }) => {
        if (active) setItems(data.items ?? []);
      }).catch((error: unknown) => {
        if (active) setErro(erroTutor(error));
      }).finally(() => {
        if (active) setLoading(false);
      });
    }, 250);
    return () => { active = false; window.clearTimeout(timer); };
  }, [busca, tentativa]);

  const selecionar = async (id: number) => {
    const request = ++selectionRequest.current;
    setSelectedId(id);
    setErro("");
    try {
      const { data } = await api.get<TutorExistenteDetail>(`/tutores/${id}`);
      if (request !== selectionRequest.current) return;
      if (data.id !== id || data.mesclado_em_id || data.ativo === 0 || data.ativo === false) {
        setErro("Este cadastro não está mais disponível. Atualize a busca e selecione um tutor ativo.");
        return;
      }
      onSelect(data);
    } catch (error) {
      if (request === selectionRequest.current) setErro(erroTutor(error));
    } finally {
      if (request === selectionRequest.current) setSelectedId(null);
    }
  };

  return <section aria-label="Selecionar tutor existente" className="mb-4 space-y-3 rounded-xl border border-blue-200 bg-blue-50 p-4">
    <div className="flex items-start justify-between gap-3">
      <div><h3 className="font-semibold text-slate-900">Selecionar tutor existente</h3>
        <p className="text-sm text-slate-600">Confira os animais e contatos antes de escolher. Pessoas com o mesmo nome permanecem separadas.</p></div>
      <button type="button" className="rounded-lg border bg-white px-3 py-2 text-sm" onClick={() => {
        selectionRequest.current += 1;
        onCancel();
      }}>Fechar busca</button>
    </div>
    <label className="block text-sm font-medium">Buscar por nome, ID, contato ou animal
      <input autoFocus value={busca} className="mt-1 w-full rounded-lg border bg-white p-2" onChange={(event) => {
        selectionRequest.current += 1;
        setSelectedId(null);
        setItems([]);
        setBusca(event.target.value);
      }} /></label>
    {erro && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{erro}
      <button type="button" className="ml-2 underline" onClick={() => setTentativa((v) => v + 1)}>Atualizar busca</button></div>}
    {loading ? <p role="status" className="text-sm">Buscando tutores…</p> : !busca.trim() ?
      <p className="text-sm text-slate-600">A busca é opcional. Você também pode cadastrar uma nova pessoa com os dados disponíveis.</p> :
      !items.length && !erro ? <p className="text-sm">Nenhum tutor encontrado.</p> : null}
    <div className="grid gap-2 md:grid-cols-2">
      {items.map((tutor) => <article key={tutor.id} className="space-y-1 rounded-lg border bg-white p-3 text-sm">
        <p className="font-semibold">{tutor.nome} #{tutor.id}</p>
        <p>{tutor.whatsapp || tutor.telefone || "Contato não informado"}</p>
        <p>{tutor.origem_cadastro || "Origem não informada"}</p>
        <p>{tutor.identificacao_pendente === false ? "Identificação confirmada" : "Identificação pendente"}</p>
        <p>Animais: {tutor.pets?.map((pet) => `${pet.nome} #${pet.id}`).join(", ") || "Nenhum vinculado"}</p>
        <button type="button" disabled={selectedId !== null} className="mt-2 rounded-lg border border-blue-300 px-3 py-2 font-medium text-blue-800 disabled:opacity-50"
          onClick={() => void selecionar(tutor.id)}>
          {selectedId === tutor.id ? "Carregando cadastro…" : `Selecionar ${tutor.nome} #${tutor.id}`}
        </button>
      </article>)}
    </div>
  </section>;
}
