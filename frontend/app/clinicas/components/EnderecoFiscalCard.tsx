"use client";

import { useEffect, useState } from "react";
import api from "@/lib/axios";

type Endereco = {
  cnpj: string; endereco: string; numero: string; complemento: string;
  bairro: string; cidade: string; estado: string; cep: string; fonte_url: string;
};
const VAZIO: Endereco = { cnpj: "", endereco: "", numero: "", complemento: "", bairro: "", cidade: "", estado: "CE", cep: "", fonte_url: "" };
const CAMPOS: [keyof Endereco, string][] = [
  ["cnpj", "CNPJ do cartão"], ["endereco", "Logradouro fiscal"], ["numero", "Número fiscal"],
  ["complemento", "Complemento fiscal"], ["bairro", "Bairro fiscal"], ["cidade", "Cidade fiscal"],
  ["estado", "UF fiscal"], ["cep", "CEP fiscal"], ["fonte_url", "Link da fonte consultada"],
];
const LIMITES: Record<keyof Endereco, number> = { cnpj: 18, endereco: 255, numero: 30, complemento: 255, bairro: 150, cidade: 150, estado: 2, cep: 9, fonte_url: 1000 };

export default function EnderecoFiscalCard({ clinicaId }: { clinicaId: number }) {
  const [endereco, setEndereco] = useState<Endereco>(VAZIO);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [erro, setErro] = useState("");
  const [sucesso, setSucesso] = useState("");
  const [tentativa, setTentativa] = useState(0);

  useEffect(() => {
    let ativo = true;
    setLoading(true); setErro(""); setSucesso("");
    api.get(`/clinicas/${clinicaId}`).then(({ data }) => {
      if (!ativo) return;
      const salvo = data.endereco_fiscal;
      setEndereco(Object.fromEntries(CAMPOS.map(([campo]) => [campo, salvo?.[campo] ?? (campo === "cnpj" ? data.cnpj || "" : VAZIO[campo])])) as Endereco);
    }).catch(() => { if (ativo) setErro("Não foi possível carregar o endereço fiscal."); })
      .finally(() => { if (ativo) setLoading(false); });
    return () => { ativo = false; };
  }, [clinicaId, tentativa]);

  const salvar = async () => {
    setSaving(true); setErro(""); setSucesso("");
    try {
      await api.put(`/clinicas/${clinicaId}/endereco-fiscal`, endereco);
      setSucesso("Endereço fiscal salvo para os próximos pacotes. Localização e CEP de rotas preservados.");
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
      setErro(typeof detail === "string" ? detail : "Confira o CNPJ salvo na clínica, o endereço completo, a UF, o CEP e o link da fonte.");
    } finally { setSaving(false); }
  };

  return (
    <section className="fc-clinic-form-section" aria-label="Endereço fiscal para o contador">
      <h2>Endereço fiscal para o contador</h2>
      <p className="text-sm text-gray-600">Informe o endereço completo do cartão de CNPJ. Ele será usado nos próximos pacotes para o contador. O endereço, CEP e pin usados nas rotas continuam no cadastro de localização.</p>
      <p className="text-sm text-gray-600">Sem endereço fiscal separado, o pacote usa o endereço do cadastro. Salve o CNPJ da clínica antes de cadastrar o endereço fiscal.</p>
      {loading ? <p role="status">Carregando endereço fiscal...</p> : (
        <>
          {erro && <div role="alert" className="text-red-700">{erro} <button type="button" onClick={() => setTentativa(v => v + 1)} disabled={saving}>Recarregar endereço salvo</button></div>}
          {sucesso && <p role="status" className="text-green-700">{sucesso}</p>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            {CAMPOS.map(([campo, label]) => <label key={campo} className="text-sm text-gray-700">
              {label}
              <input value={endereco[campo]} maxLength={LIMITES[campo]} type={campo === "fonte_url" ? "url" : "text"}
                disabled={saving} onChange={e => { setEndereco(prev => ({ ...prev, [campo]: e.target.value })); setSucesso(""); }}
                className="block w-full border rounded px-3 py-2" />
            </label>)}
          </div>
          <button type="button" disabled={saving} onClick={salvar} className="mt-4 px-4 py-2 rounded bg-blue-600 text-white disabled:opacity-50">{saving ? "Salvando endereço fiscal..." : "Salvar endereço fiscal"}</button>
        </>
      )}
    </section>
  );
}
