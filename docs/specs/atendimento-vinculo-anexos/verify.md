# Verificação do vínculo pelo envio

| Critério | Status | Evidência |
| --- | --- | --- |
| Síntese com demográficos divergentes ou ausentes | Verificado localmente | Regressões do validador, da síntese e do harness sintético preservam a identificação lida e permitem a análise. |
| Aproveitamento de achados com revisão profissional | Verificado localmente | Testes de seleção e incorporação mantêm evidência, fonte, página, confiança e aprovação clínica por item. Leitura incerta permanece limitada. |
| Lote legado usa as leituras e a transcrição existentes | Verificado localmente | Teste do worker conta uma leitura e duas sínteses após mudança clínica. Os testes de lotes antigos preservam originais, transcrição e resultados isolados. |
| Cadastro do mesmo paciente e isolamento entre pacientes/usuários | Verificado localmente | Testes de contexto preservam o vínculo pelo ID. Mudança de peso clínico exige atualização da síntese com os mesmos arquivos. Troca de paciente e usuário continua protegida. |
| Interface sem confirmações adicionais e com proveniência | Verificado localmente | Componentes testados e percurso local com API fictícia. Exame de Jully disponível no atendimento de Julie, com origem consultável. Uma inclusão ocorre depois da aprovação clínica. |
| Compatibilidade com memória e revisão desatualizada | Verificado localmente | Cache legado bloqueado, edições e itens já aplicados são recuperados. A atualização da síntese libera a revisão e conserva a prevenção de inclusão automática ou repetida. |
| Tipos, lint, build e SDD | Verificado localmente | 2.980 testes Vitest e 23 testes Node aprovados, além de tipos, lint completo, build, sintaxe Python e guardrail SDD. |
| Concorrência em PostgreSQL descartável | Verificado localmente | Oito cenários passaram em PostgreSQL 17 temporário, incluindo exclusividade do worker e decisões concorrentes legadas. O cluster foi encerrado após os testes. |
| Homologação em Stage | Pendente | Validar o candidato isolado instalado antes da promoção. |

A validação local usa dados fictícios e provedores simulados. O backend ampliado passou em 179 testes e 74 subtests, incluindo PostgreSQL, com zero casos pulados.

A prova de navegador usa o componente da aplicação com API fictícia. Ela verifica o percurso da interface e não certifica uma instalação ou uma análise clínica real. Os materiais de visualização ficam fora do repositório público.

A verificação de produção será executada após a promoção autorizada, com workflow terminal, SHA instalado, serviços, rotas, bundles e preservação dos dados.
