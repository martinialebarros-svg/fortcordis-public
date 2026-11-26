# Pesquisa e decisão clínica — 25/11/2026

## Fonte implementada

Gunther-Harrington CT et al. (2021; publicação online 19/08/2020). *Reference intervals for radiographic, echocardiographic and N-terminal pro B-type natriuretic peptide values in healthy kittens*. J Feline Med Surg 23(4):293–301. [Artigo primário](https://journals.sagepub.com/doi/10.1177/1098612X20946461), [Suplemento 1](https://journals.sagepub.com/doi/suppl/10.1177/1098612X20946461/suppl_file/sj-docx-1-jfm-10.1177_1098612x20946461.docx). Os suplementos oficiais foram obtidos pelo [EuropePMC](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10812212/supplementaryFiles), após indisponibilidade do download na editora.

88 filhotes domestic shorthair, 6–16 semanas, não sedados. Peso: mediana 1,3 kg, IQR 0,98–1,5 kg; mínimo/máximo não informados. Suplemento 1 traz intervalos agrupados calculados pelo método Robust/MedCalc, com IC 90% de cada limite entre parênteses. Os IC não são os limites de referência. O texto não explicita cobertura de 95% para os RI ecocardiográficos do suplemento; a implementação não inventa essa porcentagem. Intervalos agrupados não têm ajuste individual ao peso e requerem avaliação veterinária. A versão inicial usou apresentação neutra; por solicitação explícita posterior do usuário em 25/11/2026, a tela de comparação passou a indicar por cores apenas a posição numérica na faixa publicada. Essa indicação não estabelece normalidade/doença; PDF, IA e comparador genérico permanecem sem classificação pediátrica.

Métodos: medidas VE no nível das cordoalhas, leading-edge; modo M/eixo curto distinto de 2D/eixo longo. AE/Ao na vista basilar direita em diástole inicial; velocidade aórtica CW apical esquerda, pulmonar PW direita após a valva. Conversão cm→mm por fator 10, sem outras transformações numéricas.

## Tabelas não implementadas

Tabela 2 tem inconsistências confirmadas no HTML e PDF: LVIDd M a 2,5 kg apresenta média 1,43 cm fora do intervalo 1,18–1,40 cm; há limites não monotônicos em LVFWs M a 0,5 kg e IVSs M a 1,5 kg. Não houve errata encontrada na busca direcionada.

A reconstrução matemática com Suplemento 3 também não concordou com a cobertura de 95% indicada na Tabela 2. Exemplo LAD a 1 kg: intercepto −0,077 / SE 0,0461 e t(0,975; gl=86) ≈ 1,9879 produzem ≈ 0,678–1,034 cm, enquanto a tabela informa 0,70–1,00 cm. Esta é uma inferência matemática da revisão, não correção oficial dos autores. Não incorporar limites corrigidos por conta própria. A faixa 0,25–3 kg é domínio da tabulação, não amplitude comprovada da amostra; não transferi-la aos RI agrupados.

## Relevância profissional e fontes complementares

- [ACVIM/Luis Fuentes et al., 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7255676/), DOI 10.1111/jvim.15745: consenso internacional que enfatiza peso, método e contexto; cita Häggström 2016 e Schober 2017. É anterior à publicação pediátrica e não deve ser apresentado como endosso desse estudo.
- [Häggström et al., 2016](https://doi.org/10.1111/jvim.14569): 19.866 gatos de raça pura, subconjunto normal 18.460; referência adulta relevante, já existente no sistema. Não valida extrapolação pediátrica.
- [Schober et al., 2017](https://doi.org/10.1292/jvms.17-0250): 150 gatos saudáveis, alometria 2D; distingue modalidade e influência do peso, não substitui a população pediátrica.
- [Schille e Skrodzki, 1999](https://pubmed.ncbi.nlm.nih.gov/10528844/), DOI 10.1111/j.1740-8261.1999.tb00381.x: 35 gatos acompanhados de 2–12 semanas, modo M. Apenas resumo conferido; nenhum valor numérico implementado.

Não foi encontrada evidência que permita classificar publicações por adoção mundial. Relevância foi avaliada por aderência à população e método, publicação primária e citações em consenso, não por posição em busca. Não houve edição de prontuários nem interpretação diagnóstica de paciente real.
