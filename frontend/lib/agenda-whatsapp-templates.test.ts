import { describe, expect, it } from "vitest";
import { isValidAgendaWhatsAppServiceName, renderAgendaWhatsAppTemplate } from "./agenda-whatsapp-templates";

const appointment = ["Clínica teste", "Rex", "15/10/2026", "14:00"];

describe("modelos WhatsApp da agenda", () => {
  it("inclui o serviço composto inteiro na variante de cinco parâmetros", () => {
    const service = "Consulta cardiológica + Ecocardiograma + Eletrocardiograma";
    expect(renderAgendaWhatsAppTemplate("appointmentReminderService", [...appointment, service])).toBe(
      "Olá, Clínica teste. Lembramos que o atendimento de Rex está agendado para 15/10/2026, às 14:00. " +
      `Serviço agendado: ${service}. Confira o serviço e o horário. Se precisar corrigir ou incluir outro serviço, ` +
      "toque em Solicitar alteração e envie o que deve ser ajustado.",
    );
    const normalized = renderAgendaWhatsAppTemplate("appointmentReminderService", [
      "Clínica  teste", ...appointment.slice(1), "  Consulta cardiológica   +\n Ecocardiograma\t+  Eletrocardiograma  ",
    ]);
    expect(normalized).toContain(`Serviço agendado: ${service}.`);
    expect(normalized).toContain("Olá, Clínica  teste.");
  });

  it.each(["", "   ", "s".repeat(301)])("recusa serviço ausente ou acima do limite sem inventar nem truncar", (service) => {
    expect(() => renderAgendaWhatsAppTemplate("appointmentReminderService", [...appointment, service])).toThrow(/Confira o serviço salvo/);
    expect(isValidAgendaWhatsAppServiceName(service)).toBe(false);
  });

  it("aceita o nome completo no limite de 300 caracteres e exige o quinto parâmetro", () => {
    const service = "s".repeat(300);
    expect(renderAgendaWhatsAppTemplate("appointmentReminderService", [...appointment, service])).toContain(service);
    expect(() => renderAgendaWhatsAppTemplate("appointmentReminderService", appointment)).toThrow(/exige 5 variáveis/);
    expect(isValidAgendaWhatsAppServiceName(undefined)).toBe(false);
  });

  it("mantém explícito o lembrete legado de quatro parâmetros", () => {
    expect(renderAgendaWhatsAppTemplate("appointmentReminder", appointment)).toBe(
      "Olá, Clínica teste. Lembramos que o atendimento de Rex está confirmado para 15/10/2026, às 14:00. " +
      "Se precisar alterar o horário, use uma das opções abaixo.",
    );
    expect(() => renderAgendaWhatsAppTemplate("appointmentReminder", [...appointment, "Consulta"])).toThrow(/exige 4 variáveis/);
  });

  it("preserva o quinto parâmetro da reserva como prazo de confirmação", () => {
    expect(renderAgendaWhatsAppTemplate("reservation", [...appointment, "14/10/2026 às 17:00"])).toBe(
      "Olá, Clínica teste. A Fort Cordis reservou o atendimento de Rex para 15/10/2026, às 14:00. " +
      "Confirme até 14/10/2026 às 17:00. Após esse prazo, o horário poderá ser disponibilizado para outros clientes automaticamente.",
    );
  });
});
