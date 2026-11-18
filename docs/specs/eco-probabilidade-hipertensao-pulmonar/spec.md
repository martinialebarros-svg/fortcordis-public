# Especificação — Probabilidade de HP

## Base clínica e limites

- Reinero et al., 2020, DOI 10.1111/jvim.15725, tabelas 2–3: https://pmc.ncbi.nlm.nih.gov/articles/PMC7097566/.
- Visser et al., 2016, Diagnostic Value of Right Pulmonary Artery Distensibility Index in Dogs with Pulmonary Hypertension: Comparison with Doppler Echocardiographic Estimates of Pulmonary Arterial Pressure. DOI 10.1111/jvim.13911: https://pmc.ncbi.nlm.nih.gov/articles/PMC4913611/.
- Felinos: a matriz canina não tem validação equivalente identificada. Registrar achados e cálculos descritivos, sem graduação automática canina. A revisão específica de Rolph e Cavanaugh (2022), DOI 10.1177/1098612X221127233, descreve essa lacuna.

| TRV m/s | 0 sítios | 1 sítio | 2 sítios | 3 sítios |
| --- | --- | --- | --- | --- |
| ≤3,0 ou explicitamente não mensurável | baixa | baixa | intermediária | alta |
| >3,0 e ≤3,4 | intermediária | intermediária | alta | alta |
| >3,4 | intermediária | alta | alta | alta |

A tabela original sobrepõe a escrita “≤3,0” e “3,0 a 3,4”. Convenção explícita: exatamente 3,0 pertence à primeira faixa e exatamente 3,4 à segunda.

Sítios (cada um conta uma vez): ventrículos/septo; artéria pulmonar; átrio direito/veia cava caudal. VE pequeno/subpreenchido não é critério para HP por cardiopatia esquerda. Obstrução da via de saída do VD impede a interpretação usual da TRV e da PSAP. Qualidade e ausência de obstrução exigem confirmação humana.

## Contrato

- Opt-in `HP_ativa=sim`. Sem ativação, preservar apresentação legada e omitir seção/bibliografia HP.
- `HP_TRV`: vazio / adequado (Doppler contínuo confiável) / nao_mensuravel. Número ausente ou zero não representa não mensurável.
- `HP_VSVD`: vazio / sem_obstrucao / obstrucao.
- `HP_ventriculos`, `HP_arteria_pulmonar`, `HP_atrio_cava`: vazio / sem_sinais / com_sinais.
- `HP_suporte_automatico`: sim / nao; exclusão explícita para medidas de técnica inadequada. Sugestões positivas não preenchem sítios silenciosamente.
- Novas medidas opcionais: `HP_RPAD` (% direto), `HP_RPA_max`/`HP_RPA_min` (mm, mesmo local/ciclo), `HP_TA`/`HP_TE` (ms, mesmo traçado), `HP_IP_inicio` (m/s, início da diástole). Não reutilizar `IP_Vmax` genérico para a fase inicial.
- RPAD = (máximo − mínimo)/máximo ×100, quando o par é válido. Par parcial/inválido não produz índice nem é substituído silenciosamente pelo índice digitado. Sem par, aceitar índice direto de 0 a100. TA/TE exige 0<TA≤TE. TA isolado depende da técnica e não usa 58 ms como corte universal.
- Sugestões de sítio pulmonar: AP/Ao>1,0, PR inicial>2,5 m/s, RPAD<30%, TA/TE<0,30. Remodelamento AD leve/moderado/importante sugere o sítio AD/cava. Não derivar sinais ventriculares de TAPSE, DIVEd ou texto não revisado.
- Importação determinística pode reconhecer RPAD explicitamente em %, e TA/TE com rótulo pulmonar e unidade de tempo explícitos; não importar confirmações de qualidade, sítios ou revisão. Rótulos genéricos TA/ET ou unidade ausente não estabelecem aquisição pulmonar. Conservar evidência de origem e conflitos sem calcular média.
- Cálculos derivados devem continuar positivos/finitos depois de conversões; overflow ou underflow de AP/Ao impede classificação e pede revisão.
- Sugestão positiva pendente de aceitação impede uma classe contraditória; o médico pode excluir o suporte métrico explicitamente. Ausência de medida nunca confirma sítio sem sinais.
- `HP_revisao`: JSON de contexto normalizado, gravado somente por confirmação explícita. Mudança de entradas, espécie ou reimportação relevante (mesmo valor) invalida; recuperação literal de rascunho preserva. Campos HP de confirmação não são importados.
- Contexto ordenado: HP_ativa, HP_TRV, HP_VSVD, três sítios, HP_suporte_automatico, IT_Vmax, AP_Ao, AP, Ao_nivel_AP, suas duas unidades confirmadas, Remodelamento_AD e seis medidas HP. Números normalizados semanticamente; blanks/zeros distintos.
- Classificação exige espécie canina, revisão válida, TRV revisada e ausência de obstrução. Baixa/intermediária exigem três sítios avaliados; alta pode ser apresentada quando os sítios positivos mínimos já a tornam inequívoca, explicitando os não avaliados. Esta guarda para incompletos é escolha de segurança da implementação, não novo corte publicado.
- PSAP permanece estimativa complementar. Com HP ativa, só utilizável após revisão válida, TRV adequada positiva e VSVD sem obstrução; não usar PSAP para escolher a classe. Preservar valores brutos mesmo quando não utilizáveis.
- IT Vmax e gradiente históricos também são omitidos da projeção PDF quando o sinal atual é explicitamente não mensurável. O dado armazenado não é apagado. A projeção não reescreve texto médico salvo.
- Backend recalcula o resultado; não confiar em classe recebida do cliente. Persistência e codec devem preservar enums, zero, campos limpos e texto multilinha sem injetar chaves na descrição. Sem migração.
- PDF tem seção própria e fonte bibliográfica no final, após análise qualitativa; não sobrescrever a conclusão do médico ou banco de frases. Modelo novo e edição compartilham o mesmo componente.

## Aceitação

| ID | Critério |
| --- | --- |
| HP-01 | Matriz, limites 3,0/3,4 e não mensurável corretos, sem usar PSAP como classificador. |
| HP-02 | Incompletos, obstrução, qualidade não confirmada e espécie não suportada não produzem falsa baixa. |
| HP-03 | Três sítios contados uma vez e sugestões com origem explícita; ausência não inferida. |
| HP-04 | RPAD/TA-TE/PR inicial corretos; técnica e valores inválidos não fabricam dados. |
| HP-05 | Alterações/reimportações invalidam revisão; rascunho e reabertura preservam valores literais. |
| HP-06 | Round-trip novo/edição/atualização atômica, codec, blanks/zero/notas seguros. |
| HP-07 | PDF/portal recalculam classe e incluem fontes, sem modificar conclusão ou dados brutos. |
| HP-08 | IA não contradiz a matriz canina nem inventa graduação felina. |
| HP-09 | UI rápida, compartilhada, utilizável por teclado e tela estreita. |
| HP-10 | Regressões pertinentes, tipos/lint/build e paridade TS/Python aprovados. |

## Correção da revisão e publicação pública

A estruturação conserva toda a coorte original de medidas, incluindo DIVEd e SIVd, ao validar o selo e a ambiguidade dos diâmetros de AP/Ao. Referências e prompt numérico usam somente a projeção sanitizada; unidades confirmadas são convertidas uma vez. O contexto bruto separado alimenta exclusivamente os gates HP/PSAP/TRV. Nenhuma passagem regenera a confirmação veterinária.

O selo inclui a máscara de ambiguidade de AP/Ao calculada pela mesma gramática numérica em Python e TypeScript. Alterar a coorte e mudar essa máscara invalida a revisão. Suporte automático excluído pelo examinador não libera uma razão dimensional ambígua. Revisão ausente, TRV não mensurável, obstrução e espécie não suportada mantêm suas proteções.

A publicação de 16/11/2026 limita-se ao módulo estruturado de HP e à correção do selo. Mantém a produção pública atual, o fluxo de rascunho e o responsável financeiro da OS. Não promove comparação histórica, mudanças gerais de aliases, WhatsApp ou migrações paralelas. Não muda limiares, flags, credenciais ou dados clínicos.

Cache ECO: `2026-11-16-eco-public-hp-reviewed-context-v38`; PDFs em cache anteriores exigem regeneração. O renderer de pressão arterial permanece igual.

| ID | Critério adicional |
| --- | --- |
| HP-11 | Selo válido permanece válido com DIVEd/SIVd; mudança real da coorte invalida; nenhuma conversão dupla ou reseleção silenciosa. |
| HP-12 | Antes da promoção, comprovar que somente HP difere da base pública de produção e preparar a árvore de restauração com todos os blobs/modos paralelos preservados. |

HP-12 é o aceite da preparação verificável antes da promoção. A instalação em produção e a restauração efetiva de Stage continuam obrigatórias para encerrar a entrega; são etapas operacionais posteriores, registradas separadamente no checklist de `verify.md`. Uma árvore preparada ou um teste em Stage não comprova que essas etapas já ocorreram.

## Apresentação da avaliação no PDF

A avaliação fica em uma tabela da análise quantitativa após Regurgitações, com a largura, a tipografia e as linhas alternadas das tabelas de medidas. As colunas Parâmetro e Avaliação organizam a síntese, a velocidade da IT, os sítios anatômicos, as métricas de suporte e as notas. A tabela explicita pendências de revisão e acomoda observações multilinha. Em continuação de página, repete o título e o cabeçalho.

Prévia e emissão usam o mesmo layout e os mesmos critérios clínicos do módulo. A conclusão permanece no início e as fontes após a análise qualitativa. A versão de cache ECO `2026-11-18-eco-hp-table-layout-v39` permite que futuras gerações usem o novo layout.
