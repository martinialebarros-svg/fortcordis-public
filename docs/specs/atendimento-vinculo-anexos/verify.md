# Verificação do vínculo pelo envio

| Critério | Status | Evidência |
| --- | --- | --- |
| Síntese com demográficos divergentes ou ausentes | Verificado localmente | Regressões do validador, da síntese e do harness sintético preservam a identificação lida e permitem a análise. |
| Aproveitamento de achados com revisão profissional | Verificado localmente | Testes de seleção e incorporação mantêm evidência, fonte, página, confiança e aprovação clínica por item. Leitura incerta permanece limitada. |
| Lote legado usa as leituras e a transcrição existentes | Verificado localmente | Teste do worker conta uma leitura e duas sínteses após mudança clínica. Os testes de lotes antigos preservam originais, transcrição e resultados isolados. |
| Cadastro do mesmo paciente e isolamento entre pacientes/usuários | Verificado localmente | Testes de contexto preservam o vínculo pelo ID. Mudança de peso clínico exige atualização da síntese com os mesmos arquivos. Troca de paciente e usuário continua protegida. |
| Interface sem confirmações adicionais e com proveniência | Verificado localmente | Componentes testados e percurso local com API fictícia. Exame de Jully disponível no atendimento de Julie, com origem consultável. Uma inclusão ocorre depois da aprovação clínica. |
| Compatibilidade com memória e revisão desatualizada | Verificado localmente | Cache legado bloqueado, edições e itens já aplicados são recuperados. A atualização da síntese libera a revisão e conserva a prevenção de inclusão automática ou repetida. |
| Serialização da revisão de áudio com contexto salvo | Verificado localmente | Os 15 testes do módulo de transcrição passaram também pelo runner unittest do deploy. Fixture fornece contexto salvo válido, mantendo a validação do paciente e as assertions de transcrição e revisão por áudio. |
| Tipos, lint, build e SDD | Verificado localmente | 2.980 testes Vitest e 23 testes Node aprovados, além de tipos, lint completo, build, sintaxe Python e guardrail SDD. |
| Concorrência em PostgreSQL descartável | Verificado localmente | Oito cenários passaram em PostgreSQL 17 temporário, incluindo exclusividade do worker e decisões concorrentes legadas. O cluster foi encerrado após os testes. |
| Homologação em Stage | Aprovado em Stage | SHA `89f6b008`, workflow `45093320410` terminal com sucesso. Canário autenticado fictício sem confirmações por arquivo, com retomada legada e mudança de peso. Originais preservados e limpeza confirmada. |

A validação local usa dados fictícios e provedores simulados. O backend ampliado passou em 179 testes e 74 subtests, incluindo PostgreSQL, com zero casos pulados.

A prova de navegador usa o componente da aplicação com API fictícia. Ela verifica o percurso da interface e não certifica uma instalação ou uma análise clínica real. Os materiais de visualização ficam fora do repositório público.

A verificação de produção será executada após a promoção autorizada, com workflow terminal, SHA instalado, serviços, rotas, bundles e preservação dos dados.

O primeiro gate completo da candidata isolada `2e0a2a28` executou 2.747 testes e encontrou uma fixture antiga que chamava `serialize(None, job)` sem contexto/banco. A instalação foi dispensada pelo gate. A fixture foi atualizada para fornecer contexto sintético, preservando a validação real e todas as assertions. Regressão ampliada posterior com 190 testes e 85 subtestes aprovados; oito casos PostgreSQL ficaram sem URL nesse ensaio, já cobertos pela execução PostgreSQL documentada acima. O runner unittest do módulo passou 15/15.

## Homologação instalada em Stage — 22/11/2026

O candidato isolado `89f6b008ddd0dbd3d72888be34fade3e1fd91756` passou no workflow de instalação e nos CIs independentes. A suíte principal do backend passou em 2.747 testes, seguida das regressões PostgreSQL e dos gates de frontend. O instalador preservou e restaurou os seis arquivos runtime existentes, passou no canário autenticado padrão e no exercício de restauração de backup.

O canário específico usou cadastro, documentos e áudio inteiramente fictícios, com provedores simulados e zero chamadas OpenAI. Foram três uploads iniciais, duas leituras PDF, um processamento de áudio e três sínteses. A análise inicial aceitou grafia, raça, idade e peso documentais divergentes sem confirmação por arquivo. O legado bloqueado foi projetado sem reescrever o JSON histórico e retomado no mesmo lote. Correções cadastrais mantiveram o vínculo. A mudança de peso clínico atualizou somente a síntese. As retomadas tiveram zero reenvios, releituras e retranscrições. Revisão veterinária e auditoria permaneceram obrigatórias.

Os três originais, suas leituras, transcrição e decisões históricas permaneceram íntegros durante o ensaio. O lote e o cadastro fictício foram removidos e a auditoria foi preservada. A inspeção final confirmou zero lotes próprios e limpeza concluída. IA global de Stage continuou desativada. Os snapshots dos ambientes confirmaram preservação de runtime, configuração, originais e lotes existentes, com sete filas sem trabalhos ativos.

O smoke serviu onze bundles idênticos aos arquivos instalados, incluindo o chunk dinâmico do assistente. Os três marcadores novos estavam presentes e os quatro controles antigos de confirmação ausentes. Os três domínios de Stage responderam corretamente, a API protegida manteve 401 sem sessão e health/ready retornaram 200. O teste não certifica leitura ou interpretação real pelo modelo e não alterou prontuários reais.
