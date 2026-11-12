import type { Metadata } from "next";
import { LegalDocumentPage } from "@/components/legal/LegalDocumentPage";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Exclusão de Dados | Fort Cordis",
  description: "Instruções para solicitar acesso, correção ou exclusão de dados tratados pela Fort Cordis.",
  path: "/exclusao-de-dados",
});

export default function DataDeletionPage() {
  return (
    <LegalDocumentPage
      eyebrow="Solicitações de titulares"
      title="Exclusão de dados"
      description="Você pode solicitar acesso, correção ou exclusão dos dados pessoais associados ao FortCordis e ao canal oficial da Fort Cordis no WhatsApp."
    >
      <section>
        <h2>Como enviar a solicitação</h2>
        <p className="mt-3">
          Envie um email para{" "}
          <a href="mailto:martiniano.vet@fortcordis.com?subject=Exclus%C3%A3o%20de%20dados%20FortZap">
            martiniano.vet@fortcordis.com
          </a>{" "}
          com o assunto <strong>Exclusão de dados FortZap</strong>.
        </p>
        <p className="mt-3">Inclua somente:</p>
        <ul className="mt-3">
          <li>seu nome;</li>
          <li>o número de telefone com código do país;</li>
          <li>se a solicitação é de acesso, correção ou exclusão;</li>
          <li>uma descrição breve do vínculo com a Fort Cordis.</li>
        </ul>
        <p className="mt-3">Não envie diagnóstico, laudo, senha, código de autenticação ou outros dados clínicos por email.</p>
      </section>

      <section>
        <h2>Validação de identidade</h2>
        <p className="mt-3">
          Para impedir exclusões indevidas, poderemos solicitar confirmação pelo número cadastrado ou outra
          evidência mínima de identidade. Nunca solicitaremos sua senha ou código de autenticação.
        </p>
      </section>

      <section>
        <h2>Prazo e conclusão</h2>
        <p className="mt-3">
          Confirmaremos o recebimento e informaremos o andamento em até 15 dias. Quando a exclusão for aplicável,
          os dados serão eliminados ou anonimizados nos sistemas controlados pela Fort Cordis. Informaremos a
          conclusão pelo mesmo canal seguro utilizado para validar a solicitação.
        </p>
      </section>

      <section>
        <h2>Dados que podem ser preservados</h2>
        <p className="mt-3">
          Alguns registros podem ser mantidos quando necessários para cumprir obrigação legal ou regulatória,
          proteger direitos, prevenir fraude ou preservar a segurança do serviço. Nesses casos, o acesso permanece
          restrito e a finalidade é limitada ao motivo da retenção.
        </p>
      </section>

      <section>
        <h2>Mais informações</h2>
        <p className="mt-3">
          Consulte a <a href="/privacidade">Política de Privacidade</a> para saber quais dados tratamos e como eles
          são protegidos.
        </p>
      </section>
    </LegalDocumentPage>
  );
}
