# Especificação

## Requisitos

- RF-001: selecionar a referência de Gunther-Harrington et al. (2021; publicação online 2020), DOI 10.1177/1098612X20946461, somente para felinos com idade reconhecida dentro de 6–16 semanas e peso positivo informado. Não inventar mínimo/máximo de peso: a fonte informa mediana e IQR, sem amplitude observada.
- RF-002: disponibilizar dimensões do VE separadamente por modo M/eixo curto e 2D/eixo longo, preservando unidade mm do sistema e fonte em cm. Exigir confirmação do protocolo compatível; não presumir confirmação a partir da medida.
- RF-003: usar exclusivamente os intervalos agrupados do Suplemento 1 como consulta neutra, sem ajuste por peso e sem classificação automática. Não implementar a Tabela 2 nem reconstruir seus limites a partir do Suplemento 3, devido às inconsistências documentadas. Não confundir os IC90 dos limites com os intervalos de referência; não atribuir nível95% não explícito aos intervalos do suplemento.
- RF-004: bloquear intervalos adultos/legados sem validação pediátrica para felinos em crescimento ou com faixa etária simples que possa incluir menos de 12 meses, mesmo com catálogo completo, preservando seus valores em catalog_ranges.
- RF-005: recalcular ao mudar idade, peso, técnica ou protocolo. API, fallback frontend, prévia e PDF devem concordar. Não aplicar dados M em campos 2D nem recuperar limites pediátricos antigos em outro contexto.
- RF-006: apresentar população, método, estatística e DOI e incluir bibliografia pertinente no PDF. Ausência de faixa não significa anormalidade. Nenhum diagnóstico, assinatura, salvamento ou emissão automática.

## Critérios de aceitação

- CA-001: caso sintético de três meses encontra intervalos pediátricos de consulta com catálogo vazio e completo após protocolo confirmado.
- CA-002: limites de idade, peso ausente/inválido e técnica/protocolo incompatível não expõem números pediátricos. Nenhum intervalo pediátrico produz classificação automática, mesmo quando disponível.
- CA-003: tabela, unidade, fonte e estatística correspondem à publicação verificada.
- CA-004: troca de contexto invalida limites anteriores; adultos/cães mantêm comportamento existente.
- CA-005: comparação, projeção e PDF concordam, com bibliografia correta e campos preservados.

## Evidência

Pesquisa e decisões de transcrição em literature.md. Os dados numéricos só serão incorporados após conferência da fonte primária.

## Contrato da consulta pediátrica

`pediatric_reference` contém fonte, DOI, população, idade em semanas, domínio etário e `ranges` por chave canônica. Cada faixa tem `status`, `lower`, `upper`, `unit`, `text`, `reason`, `source`, `doi` e `statistic=published_cohort_reference_interval`. O status disponível é `descriptive`; os limites genéricos `*_min/max` permanecem nulos e a comparação retorna `nao_avaliado`. Sem idade/método compatíveis, status `requires_method`/`unavailable`, sem números. Valores são originais do suplemento, não média±DP.

18 chaves: seis dimensões M, encurtamento M, seis dimensões 2D, Aorta/AE/AE:Ao e velocidades máximas aórtica/pulmonar. Não reutilizar a medida Ao para Ao_nivel_AP nem LAD para AE_diametro_max.

Confirmação `Pediatria_protocolo=gunther_harrington_2021_sem_sedacao`. Técnica do VE identificada no exame e confirmada pelo novo protocolo; 2D exige `VE_vista_2D=eixo_longo`. AE/Ao exige `AE_Ao_metodo=2d_eixo_curto_diastole_inicial`. A interface explica cordoalhas/leading-edge, modo M eixo curto, 2D eixo longo, AoCW apical e pulmonarPW direito após a valva. A confirmação é do examinador, não extraída de números ou aplicada automaticamente.

Conversão etária determinística: mês = 30,4375 dias, ano = 365,25 dias. O sufixo literal `(estimada)` é aceito para durações explicitamente informadas, como no cadastro do sistema; não confere precisão adicional à idade original. Texto sem unidade, faixa etária, idade negativa ou apenas ano estimado não valida o domínio de 6–16 semanas. A seleção usa a idade registrada para o exame e não cria uma data de nascimento. Ao trocar a idade, pediatria é removida; resposta adulta nova é requerida para recuperar fontes adultas do catálogo no frontend. Nenhum dado do paciente é alterado.

Faixas numéricas simples como `1–2 meses` acionam proteção conservadora contra dados adultos, mas não autorizam intervalos pediátricos: a idade em semanas permanece não confirmada. Uma faixa exclusivamente adulta como `1–2 anos` não é convertida em contexto pediátrico. Ao resolver referência armazenada, omitir a idade preserva o contexto; passar `None`/`null` explicitamente remove a idade anterior e a referência pediátrica.

O parser legado pode identificar modo M/2D ao reabrir um registro contendo apenas uma família de medidas. Essa inferência existente não confirma o novo protocolo pediátrico: sem a ação explícita `Pediatria_protocolo`, nenhum intervalo pediátrico é disponibilizado. O operador confirma o protocolo para as técnicas exibidas/obtidas no exame.

## Estabilidade do editor durante a publicação

A suíte remota revelou um temporizador de mensagem de sucesso da tela de novo laudo que continuava após desmontar o editor. Os quatro avisos temporários mantêm as durações existentes de 4/5 segundos, mas seus temporizadores são cancelados ao sair da tela; respostas tardias não agendam novos avisos após desmontagem. Não altera carregamento de pacientes, edição clínica, emissão ou os dados das referências.
