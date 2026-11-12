"use client";

import { useEffect, useRef, useState } from "react";
import api from "@/lib/axios";

type Props = {
  pacienteId?: number | null;
  clinicaId?: number | null;
  onSaldoCliente: (saldo: number) => void;
  onBusy?: (busy: boolean) => void;
  disabled?: boolean;
};
const moeda = (valor: number) => valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export default function BaixaCredito({ pacienteId, clinicaId, onSaldoCliente, onBusy, disabled }: Props) {
  const [aberto, setAberto] = useState(false);
  const [destino, setDestino] = useState("cliente");
  const [saldo, setSaldo] = useState(0);
  const [permitido, setPermitido] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const [valor, setValor] = useState("");
  const [motivo, setMotivo] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [mensagem, setMensagem] = useState("");
  const [erro, setErro] = useState("");
  const [ultimaBaixa, setUltimaBaixa] = useState<number | null>(null);
  const chave = useRef<string | null>(null);
  const enviando = useRef(false);
  const params = { tipo_destino: destino, paciente_id: pacienteId, clinica_id: clinicaId };

  useEffect(() => {
    if (!aberto) return;
    let ativo = true;
    setCarregando(true);
    setErro("");
    setSaldo(0);
    setPermitido(false);
    setValor("");
    setMensagem("");
    setUltimaBaixa(null);
    chave.current = null;
    api.get<{ saldo: number; pode_baixar: boolean }>("/financeiro/creditos/disponivel", {
      params: { tipo_destino: destino, paciente_id: pacienteId, clinica_id: clinicaId },
    }).then(({ data }) => {
      if (!ativo) return;
      setSaldo(data.saldo);
      setPermitido(data.pode_baixar);
    }).catch(() => {
      if (ativo) setErro("Nao foi possivel consultar o saldo. Feche e tente novamente.");
    }).finally(() => { if (ativo) setCarregando(false); });
    return () => { ativo = false; };
  }, [aberto, destino, pacienteId, clinicaId]);

  const baixar = async () => {
    if (enviando.current) return;
    enviando.current = true;
    onBusy?.(true);
    setSalvando(true);
    setErro("");
    setMensagem("");
    chave.current ??= crypto.randomUUID();
    try {
      const { data } = await api.post<{ saldo: number; movimento_id: number }>("/financeiro/creditos/baixar", {
        ...params, valor: Number(valor.replace(",", ".")), motivo: motivo.trim(), idempotency_key: chave.current,
      });
      setSaldo(data.saldo);
      setUltimaBaixa(data.movimento_id);
      if (destino === "cliente") onSaldoCliente(data.saldo);
      setValor("");
      setMotivo("");
      chave.current = null;
      setMensagem(`Credito baixado sem contrapartida. Saldo restante: ${moeda(data.saldo)}. A OS continua aguardando recebimento.`);
    } catch (error: unknown) {
      const detalhe = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setErro(typeof detalhe === "string" ? detalhe : "Nao foi possivel confirmar a baixa. Tente novamente com os mesmos dados.");
    } finally {
      enviando.current = false;
      setSalvando(false);
      onBusy?.(false);
    }
  };
  const desfazer = async () => {
    if (!ultimaBaixa || enviando.current) return;
    enviando.current = true;
    onBusy?.(true);
    setSalvando(true);
    setErro("");
    try {
      const { data } = await api.post<{ saldo: number }>(`/financeiro/creditos/${ultimaBaixa}/desfazer-baixa`);
      setSaldo(data.saldo);
      if (destino === "cliente") onSaldoCliente(data.saldo);
      setUltimaBaixa(null);
      setMensagem("Baixa desfeita; credito restaurado.");
    } catch {
      setErro("Nao foi possivel confirmar o desfazer. Tente novamente.");
    } finally { enviando.current = false; setSalvando(false); onBusy?.(false); }
  };
  const valorNumero = Number(valor.replace(",", "."));
  return (
    <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
      <button type="button" disabled={salvando || disabled} onClick={() => setAberto(!aberto)} className="font-medium text-gray-700 underline">
        {aberto ? "Fechar baixa de credito" : "Baixar credito sem contrapartida"}
      </button>
      {aberto && <fieldset disabled={disabled} className="mt-3 space-y-3">
        <p className="text-xs text-gray-600">Reduz o saldo de credito sem devolucao de dinheiro nem abatimento em OS. Esta acao e independente da confirmacao do recebimento.</p>
        <label className="block">Titular do credito
          <select aria-label="Titular do credito" value={destino} disabled={salvando} onChange={(e) => setDestino(e.target.value)} className="mt-1 w-full rounded border p-2">
            <option value="cliente">Cliente</option>
            {clinicaId && <option value="clinica">Clinica</option>}
          </select>
        </label>
        {carregando ? <p role="status">Consultando saldo...</p> : <p>Saldo disponivel: <strong>{moeda(saldo)}</strong></p>}
        {!carregando && !permitido && !erro && <p className="text-xs text-gray-600">Apenas administradores podem baixar creditos.</p>}
        {permitido && <>
          <label className="block">Valor do credito a baixar
            <input aria-label="Valor do credito a baixar" type="number" min="0.01" step="0.01" max={saldo} value={valor} disabled={salvando}
              onChange={(e) => { setValor(e.target.value); chave.current = null; }} className="mt-1 w-full rounded border p-2" />
          </label>
          <label className="block">Motivo da baixa
            <textarea aria-label="Motivo da baixa" value={motivo} maxLength={500} disabled={salvando}
              onChange={(e) => { setMotivo(e.target.value); chave.current = null; }} className="mt-1 w-full rounded border p-2" />
          </label>
          <button type="button" onClick={baixar} disabled={salvando || carregando || !Number.isFinite(valorNumero) || valorNumero <= 0 || valorNumero > saldo || motivo.trim().length < 3}
            className="rounded-lg bg-gray-800 px-3 py-2 font-medium text-white disabled:opacity-50">
            {salvando ? "Registrando baixa..." : `Confirmar baixa de ${moeda(valorNumero || 0)} sem contrapartida`}
          </button>
        </>}
        {erro && <p role="alert" className="text-red-700">{erro}</p>}
        {mensagem && <p role="status" className="text-emerald-700">{mensagem}</p>}
        {ultimaBaixa && <button type="button" disabled={salvando} onClick={desfazer} className="font-medium underline">Desfazer ultima baixa</button>}
      </fieldset>}
    </div>
  );
}
