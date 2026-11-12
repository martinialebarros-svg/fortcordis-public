"use client";

import { useEffect, useRef, useState } from "react";
import api from "@/lib/axios";
import { lerErroFiscal } from "@/lib/fiscal-fechamento";
import type { FiscalRotinaClinica } from "@/lib/fiscal-rotina";

export default function FiscalRotinaPreferencias({ clinicas, disabled, onSaved, onRefresh, onBusyChange }: {
  clinicas: FiscalRotinaClinica[];
  disabled: boolean;
  onSaved: (item: FiscalRotinaClinica) => void;
  onRefresh: () => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const [clinicaId, setClinicaId] = useState("");
  const item = clinicas.find((row) => row.clinica_id === Number(clinicaId));
  const [modo, setModo] = useState<"semanal" | "por_servico">("semanal");
  const [dependeNF, setDependeNF] = useState(false);
  const [saving, setSaving] = useState(false);
  const [erro, setErro] = useState("");
  const [conflito, setConflito] = useState(false);
  const [sucesso, setSucesso] = useState("");
  const savingRef = useRef(false);
  useEffect(() => {
    setModo(item?.modo || "semanal");
    setDependeNF(item?.pagamento_depende_nf || false);
    setErro(""); setConflito(false);
  }, [item]);

  async function salvar() {
    if (!item || savingRef.current || disabled || conflito) return;
    savingRef.current = true;
    setSaving(true); onBusyChange(true); setErro(""); setSucesso("");
    try {
      const response = await api.put<FiscalRotinaClinica>(`/fiscal/rotinas/clinicas/${item.clinica_id}`, {
        modo, pagamento_depende_nf: dependeNF, versao_esperada: item.versao,
      });
      onSaved(response.data);
      setSucesso("Preferência salva. A prévia foi atualizada.");
    } catch (error) {
      setErro((await lerErroFiscal(error, "Não foi possível salvar a preferência.")).mensagem);
      setConflito((error as { response?: { status?: number } }).response?.status === 409);
    } finally {
      savingRef.current = false;
      setSaving(false); onBusyChange(false);
    }
  }

  return <details className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <summary className="cursor-pointer font-semibold text-slate-900">Preferências por clínica</summary>
    <p className="mt-2 text-sm text-slate-600">O padrão é semanal, domingo às 17h de Fortaleza. A preparação e o envio continuam sob sua decisão.</p>
    <div className="mt-3"><label htmlFor="fiscal-preferencia-clinica" className="mb-1 block text-sm">Configurar clínica</label>
      <select id="fiscal-preferencia-clinica" value={clinicaId} disabled={disabled || saving} onChange={(event) => { setClinicaId(event.target.value); setSucesso(""); }} className="w-full rounded-lg border px-3 py-2 text-sm sm:max-w-xl"><option value="">Selecione uma clínica</option>{clinicas.map((row) => <option key={row.clinica_id} value={row.clinica_id}>{row.nome}{row.origem === "vet_fauna" ? " · preferência Vet Fauna" : ""}</option>)}</select>
    </div>
    {item && <div className="mt-3 space-y-3">
      {item.origem === "vet_fauna" && <p className="text-sm text-amber-900">Preferência inicial da Vet Fauna: informações por serviço, com pagamento dependente da nota.</p>}
      <div><label htmlFor="fiscal-preferencia-modo" className="mb-1 block text-sm">Preparação das informações</label><select id="fiscal-preferencia-modo" value={modo} disabled={disabled || saving} onChange={(event) => { setModo(event.target.value as "semanal" | "por_servico"); setSucesso(""); }} className="rounded-lg border px-3 py-2 text-sm"><option value="semanal">Semanal · domingo às 17h</option><option value="por_servico">Por serviço · uma OS por pacote</option></select></div>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={dependeNF} disabled={disabled || saving} onChange={(event) => { setDependeNF(event.target.checked); setSucesso(""); }} className="mt-1" /><span>O pagamento desta clínica depende da apresentação da nota fiscal.</span></label>
      <button type="button" onClick={() => void salvar()} disabled={disabled || saving || conflito} className="rounded-lg bg-teal-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{saving ? "Salvando preferência..." : "Salvar preferência"}</button>
    </div>}
    {erro && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800"><p>{erro}</p>{conflito && <button type="button" onClick={onRefresh} className="mt-2 font-semibold underline">Atualizar preferências antes de tentar novamente</button>}</div>}
    {sucesso && <p role="status" className="mt-3 text-sm text-emerald-800">{sucesso}</p>}
  </details>;
}
