import type { Metadata } from "next";
import { LegalDocumentPage } from "@/components/legal/LegalDocumentPage";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Política de Privacidade | Fort Cordis",
  description: "Como a Fort Cordis trata dados pessoais no sistema e nas comunicações pelo WhatsApp.",
  path: "/privacidade",
});

export default function PrivacyPage() {
  return (
    <LegalDocumentPage
      eyebrow="Privacidade e proteção de dados"
      title="Política de Privacidade"
      description="Esta política explica como a Fort Cordis Cardiologia Veterinária trata dados pessoais no sistema FortCordis e nas comunicações realizadas pelo WhatsApp Business."
    >
      <section>
        <h2>1. Quem controla os dados</h2>
        <p className="mt-3">
          A Fort Cordis Cardiologia Veterinária é responsável pelo tratamento descrito nesta política.
          Dúvidas e solicitações podem ser enviadas para{" "}
          <a href="mailto:martiniano.vet@fortcordis.com">martiniano.vet@fortcordis.com</a>.
        </p>
      </section>

      <section>
        <h2>2. Dados tratados</h2>
        <p className="mt-3">Podemos tratar somente os dados necessários para prestar e proteger o serviço, como:</p>
        <ul className="mt-3">
          <li>nome, número de telefone e vínculo com o paciente veterinário;</li>
          <li>dados operacionais de agendamento, como data, horário e prazo de confirmação;</li>
          <li>mensagens e respostas enviadas pelos canais oficiais da Fort Cordis;</li>
          <li>identificadores técnicos, registros de entrega, leitura, falha e auditoria de segurança.</li>
        </ul>
      </section>

      <section>
        <h2>3. Finalidades</h2>
        <p className="mt-3">Usamos esses dados para:</p>
        <ul className="mt-3">
          <li>organizar atendimentos e enviar confirmações ou avisos relacionados ao serviço;</li>
          <li>registrar confirmações e solicitações de alteração de agendamento;</li>
          <li>responder contatos iniciados pelo cliente e manter a continuidade do atendimento;</li>
          <li>prevenir abuso, investigar falhas e cumprir obrigações legais ou regulatórias.</li>
        </ul>
      </section>

      <section>
        <h2>4. WhatsApp e fornecedores</h2>
        <p className="mt-3">
          As comunicações pelo WhatsApp utilizam a Plataforma WhatsApp Business da Meta. Dados estritamente
          necessários também podem ser processados por provedores de hospedagem, segurança e infraestrutura
          contratados pela Fort Cordis. Não vendemos dados pessoais.
        </p>
      </section>

      <section>
        <h2>5. Retenção e segurança</h2>
        <p className="mt-3">
          Os dados são mantidos pelo tempo necessário às finalidades informadas, à segurança do serviço e às
          obrigações aplicáveis. Adotamos controle de acesso, autenticação, registros de auditoria e proteção de
          segredos técnicos. O acesso é limitado a profissionais e fornecedores autorizados.
        </p>
      </section>

      <section>
        <h2>6. Seus direitos</h2>
        <p className="mt-3">
          Você pode solicitar confirmação do tratamento, acesso, correção, anonimização, bloqueio, portabilidade
          ou exclusão quando aplicável, além de informações sobre compartilhamento. Consulte também as{" "}
          <a href="/exclusao-de-dados">instruções de exclusão de dados</a>.
        </p>
      </section>

      <section>
        <h2>7. Alterações desta política</h2>
        <p className="mt-3">
          Esta página pode ser atualizada para refletir mudanças no serviço ou em requisitos legais. A data da
          versão vigente será sempre indicada no início do documento.
        </p>
      </section>
    </LegalDocumentPage>
  );
}
