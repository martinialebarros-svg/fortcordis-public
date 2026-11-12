import type { Metadata } from "next";
import { LegalDocumentPage } from "@/components/legal/LegalDocumentPage";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Termos de Uso | Fort Cordis",
  description: "Termos aplicáveis ao sistema FortCordis e às comunicações pelo WhatsApp Business.",
  path: "/termos",
});

export default function TermsPage() {
  return (
    <LegalDocumentPage
      eyebrow="Regras de utilização"
      title="Termos de Uso"
      description="Estes termos regulam o uso do sistema FortCordis e dos canais digitais da Fort Cordis Cardiologia Veterinária, incluindo o WhatsApp Business."
    >
      <section>
        <h2>1. Finalidade do serviço</h2>
        <p className="mt-3">
          O FortCordis apoia a comunicação, o agendamento e a organização de informações relacionadas ao
          atendimento veterinário. Mensagens automáticas podem solicitar confirmação ou registrar pedidos de
          alteração de horário.
        </p>
      </section>

      <section>
        <h2>2. Canal não emergencial</h2>
        <p className="mt-3">
          O sistema e o WhatsApp não substituem avaliação veterinária e não devem ser usados como canal de
          emergência. Em situações urgentes, procure imediatamente um serviço veterinário adequado.
        </p>
      </section>

      <section>
        <h2>3. Responsabilidades do usuário</h2>
        <ul className="mt-3">
          <li>fornecer dados corretos e manter o número de contato atualizado;</li>
          <li>não tentar acessar informações de terceiros ou contornar controles de segurança;</li>
          <li>não usar o serviço para fraude, assédio, conteúdo ilícito ou envio automatizado não autorizado;</li>
          <li>informar à Fort Cordis se identificar uso indevido, mensagem incorreta ou falha de segurança.</li>
        </ul>
      </section>

      <section>
        <h2>4. Disponibilidade e alterações</h2>
        <p className="mt-3">
          Podemos realizar manutenção, corrigir falhas ou modificar funcionalidades para preservar a segurança e
          a qualidade do serviço. Quando possível, comunicações relevantes serão feitas pelos canais cadastrados.
        </p>
      </section>

      <section>
        <h2>5. Privacidade</h2>
        <p className="mt-3">
          O tratamento de dados pessoais segue nossa{" "}
          <a href="/privacidade">Política de Privacidade</a> e as leis aplicáveis.
        </p>
      </section>

      <section>
        <h2>6. Contato</h2>
        <p className="mt-3">
          Dúvidas sobre estes termos podem ser enviadas para{" "}
          <a href="mailto:martiniano.vet@fortcordis.com">martiniano.vet@fortcordis.com</a>.
        </p>
      </section>
    </LegalDocumentPage>
  );
}
