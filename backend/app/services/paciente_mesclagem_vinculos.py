"""Contratos explícitos: um campo legado de paciente não autoriza sua transferência."""

# Somente estas colunas são alteradas. Vínculos indiretos (anexo -> atendimento,
# documento -> laudo, pagamento -> OS) acompanham o registro original pelo seu ID.
TRANSFERIR = {
    "agendamentos": "paciente_id",
    "alertas_clinicos": "paciente_id",
    "atendimentos_clinicos": "paciente_id",
    "contas_receber": "paciente_id",
    "creditos_financeiros": "paciente_id",
    "exames": "paciente_id",
    "laudos": "paciente_id",
    "ordens_servico": "paciente_id",
    "transacoes": "paciente_id",
}
PRESERVAR = {"portal_access_challenges": "paciente_id", "ai_echo_sessions": "patient_id"}
