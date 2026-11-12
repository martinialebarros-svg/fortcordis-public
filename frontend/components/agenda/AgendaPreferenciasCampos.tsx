import {
  FILTROS_PREFERENCIA_VAZIOS, resolverPreferenciaAgenda, resumoPreferenciaAgenda,
  type FiltrosPreferenciaAgenda,
} from "@/lib/agenda-preferencias";

interface Props {
  value: FiltrosPreferenciaAgenda;
  referencia: string;
  onChange: (value: FiltrosPreferenciaAgenda) => void;
  disabled?: boolean;
}

export default function AgendaPreferenciasCampos({ value, referencia, onChange, disabled }: Props) {
  const resultado = resolverPreferenciaAgenda(value, referencia);
  const atualizar = (patch: Partial<FiltrosPreferenciaAgenda>) => onChange({ ...value, ...patch });
  const classe = "mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm";
  return (
    <fieldset disabled={disabled} className="rounded-lg border border-blue-200 bg-blue-50/40 p-3 space-y-3">
      <legend className="px-1 text-sm font-medium text-blue-900">Preferências deste atendimento</legend>
      <p className="text-xs text-gray-600">Informe o período que atende à clínica ou ao tutor antes de gerar as sugestões.</p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className="text-sm text-gray-700">Quando
          <select aria-label="Quando deseja o atendimento" className={classe} value={value.quando}
            onChange={(e) => atualizar({ quando: e.target.value as FiltrosPreferenciaAgenda["quando"] })}>
            <option value="sem_preferencia">Sem preferência de data</option>
            <option value="data">Data específica</option>
            <option value="esta_semana">Esta semana</option>
            <option value="proxima_semana">Próxima semana</option>
            <option value="intervalo">Intervalo de datas</option>
          </select>
        </label>
        <label className="text-sm text-gray-700">Turno
          <select aria-label="Turno desejado" className={classe} value={value.turno}
            onChange={(e) => atualizar({
              turno: e.target.value as FiltrosPreferenciaAgenda["turno"],
              ...(e.target.value === "a_partir_de" ? { horaFim: "" } : {}),
            })}>
            <option value="qualquer">Qualquer turno</option>
            <option value="manha">Manhã</option>
            <option value="tarde">Tarde</option>
            <option value="a_partir_de">A partir de</option>
            <option value="personalizado">Faixa personalizada</option>
          </select>
        </label>
        {(value.quando === "data" || value.quando === "intervalo") && (
          <label className="text-sm text-gray-700">{value.quando === "data" ? "Data desejada" : "Primeiro dia"}
            <input type="date" className={classe} value={value.dataInicio}
              onChange={(e) => atualizar({ dataInicio: e.target.value })} />
          </label>
        )}
        {value.quando === "intervalo" && (
          <label className="text-sm text-gray-700">Último dia
            <input type="date" className={classe} value={value.dataFim}
              onChange={(e) => atualizar({ dataFim: e.target.value })} />
          </label>
        )}
        {(value.turno === "a_partir_de" || value.turno === "personalizado") && <>
          <label className="text-sm text-gray-700">A partir de
            <input type="time" className={classe} value={value.horaInicio}
              onChange={(e) => atualizar({ horaInicio: e.target.value })} />
          </label>
          {value.turno === "personalizado" && (
            <label className="text-sm text-gray-700">Terminar até
              <input type="time" className={classe} value={value.horaFim}
                onChange={(e) => atualizar({ horaFim: e.target.value })} />
            </label>
          )}
        </>}
      </div>
      <p className={`text-xs ${resultado.erro ? "text-amber-800" : "text-blue-900"}`}>
        {resultado.erro || resumoPreferenciaAgenda(resultado.preferencia)}
      </p>
      {(resultado.preferencia || resultado.erro) && (
        <button type="button" onClick={() => onChange({ ...FILTROS_PREFERENCIA_VAZIOS })}
          className="text-xs font-medium text-blue-800 underline">Limpar preferências e ampliar busca</button>
      )}
    </fieldset>
  );
}
