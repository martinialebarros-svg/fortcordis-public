import api from "@/lib/axios";

interface CreditoSaldoItemApi {
  saldo?: number | null;
}

interface CreditoSaldoListaApi {
  items?: CreditoSaldoItemApi[];
}

interface ConsultaSaldoCreditoClienteParams {
  tutorId?: number | null;
  pacienteId?: number | null;
}

const toPositiveInt = (value?: number | null): number => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.trunc(parsed);
};

export const consultarSaldoCreditoCliente = async (
  params: ConsultaSaldoCreditoClienteParams
): Promise<number> => {
  const tutorId = toPositiveInt(params.tutorId);
  const pacienteId = toPositiveInt(params.pacienteId);
  if (!tutorId && !pacienteId) {
    return 0;
  }

  if (pacienteId) {
    const response = await api.get<{ saldo: number }>("/financeiro/creditos/disponivel", {
      params: { tipo_destino: "cliente", paciente_id: pacienteId },
    });
    const saldo = Number(response.data.saldo);
    return Number.isFinite(saldo) ? Number(saldo.toFixed(2)) : 0;
  }

  const query: Record<string, string | number | boolean> = {
    tipo_destino: "cliente",
  };
  if (tutorId) {
    query.tutor_id = tutorId;
  } else if (pacienteId) {
    query.paciente_id = pacienteId;
  }

  const response = await api.get<CreditoSaldoListaApi>("/financeiro/creditos/saldos", {
    params: query,
  });
  const items = Array.isArray(response.data?.items) ? response.data.items : [];
  const saldo = items.reduce((total, item) => total + Number(item?.saldo || 0), 0);
  if (!Number.isFinite(saldo)) {
    return 0;
  }
  return Number(saldo.toFixed(2));
};
