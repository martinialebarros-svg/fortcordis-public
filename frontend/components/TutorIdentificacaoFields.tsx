"use client";

export interface TutorIdentificacao {
  identificacao_pendente: boolean;
  origem_cadastro: string;
  identificacao_observacoes: string;
}

export default function TutorIdentificacaoFields({ value, onChange }: {
  value: TutorIdentificacao;
  onChange: (value: TutorIdentificacao) => void;
}) {
  return (
    <fieldset className="col-span-full rounded-xl border border-slate-200 bg-slate-50 p-3">
      <legend className="px-1 text-sm font-medium text-slate-800">Identificação do tutor</legend>
      <p className="text-sm text-slate-700">{value.identificacao_pendente ? "Identificação pendente" : "Identificação confirmada pela equipe"}</p>
      <p className="mt-1 text-sm text-slate-600">Pode continuar com o primeiro nome. Os demais dados podem ser completados no atendimento.</p>
      <details className="mt-2 space-y-3">
      <summary className="cursor-pointer text-sm font-medium text-blue-700">Origem e observações (opcional)</summary>
      <label className="block text-sm">Origem do cadastro / clínica informante
        <input className="mt-1 w-full rounded-lg border bg-white p-2" value={value.origem_cadastro}
          onChange={(event) => onChange({ ...value, origem_cadastro: event.target.value })}
          placeholder="Ex.: Clínica Alfa" />
      </label>
      <label className="block text-sm">O que falta confirmar / observações da identificação
        <textarea className="mt-1 w-full rounded-lg border bg-white p-2" value={value.identificacao_observacoes}
          onChange={(event) => onChange({ ...value, identificacao_observacoes: event.target.value })}
          placeholder="Ex.: confirmar sobrenome e contato com a clínica" rows={2} />
      </label>
      </details>
    </fieldset>
  );
}
