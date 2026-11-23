# Associação dos anexos ao paciente do atendimento

## Comportamento

- RF-001 O envio de um arquivo por um usuário autorizado associa o documento ao paciente e ao atendimento selecionados. Nome, grafia, espécie, raça, idade, peso, data e estabelecimento descritos no documento não exigem uma confirmação adicional de vínculo para ler, sintetizar e revisar os achados.
- RF-002 A identificação extraída do documento permanece com a fonte original. O sistema conserva arquivos, páginas, datas, unidades, evidências literais e limitações da leitura. Os dados do cadastro continuam sendo a referência do atendimento e não são sobrescritos pelo documento.
- RF-003 A leitura e a síntese usam a associação estabelecida pelo envio. Diferenças demográficas ficam disponíveis uma vez por fonte, com linguagem informativa. Avisos de identidade repetidos em cada achado e painéis obrigatórios de confirmação de nome, idade ou raça deixam de integrar o percurso normal.
- RF-004 Um achado legível, de alta confiança e com fonte, página e evidência válidas pode ser revisado e selecionado mesmo quando os demográficos do documento divergem ou estão ausentes. Dados ilegíveis, evidência inválida, fonte desconhecida e página inválida continuam sujeitos às validações documentais existentes.
- RF-005 A incorporação exige a revisão e a ação do profissional. O envio não aprova achados, recomendações, diagnósticos, receitas ou documentos automaticamente.

## Conjuntos e resultados existentes

- RF-006 Resultados antigos bloqueados por identificação são projetados conforme a nova regra. Os avisos de impedimento gerados pelo próprio sistema são removidos da apresentação atual. Os documentos, as leituras originais e os registros históricos de decisão permanecem preservados.
- RF-007 Quando um lote já tem todas as fontes lidas e a síntese foi interrompida somente por identificação, uma ação de atualizar a análise executa a síntese com os mesmos documentos e a mesma transcrição. O fluxo não exige reenviar, reler ou retranscrever fontes concluídas.
- RF-008 Alterações demográficas no mesmo paciente não invalidam o vínculo do conjunto. A troca efetiva de paciente, de atendimento ou de usuário continua passando pelos controles de autorização existentes. Mudanças clínicas relevantes durante a execução continuam exigindo revisão atualizada da síntese.
- RF-009 Recuperação em memória e armazenamento do navegador respeitam o novo contrato. Uma revisão realmente desatualizada continua protegida contra incorporação até a atualização do resultado.
- RF-010 Falhas de leitura, retenção, integridade de arquivo e serviço de IA usam a recuperação existente. A nova associação documental não transforma uma leitura falha em resultado clínico.

## Aceite

1. Um lote fictício com grafias como Juli, Julli, Julie e Jully, descrições de raça e idades diferentes produz síntese revisável e achados elegíveis.
2. Um achado documental com alta confiança pode ser aprovado e incluído pelo profissional apesar de demográficos divergentes. O caso ilegível continua apresentando limitação de leitura.
3. Um lote legado bloqueado por identidade abre os achados existentes e permite executar somente a síntese. O teste confirma zero novas leituras ou transcrições.
4. O teste de contexto verifica mudança cadastral do mesmo paciente, troca efetiva de paciente, usuário diferente e revisão clínica desatualizada.
5. A interface mostra o vínculo pelo envio e a origem de cada arquivo, sem confirmações adicionais de identidade ou avisos de impedimento repetidos por achado.
