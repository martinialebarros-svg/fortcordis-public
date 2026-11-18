# Verificação

| Critério | Estado | Evidência |
| --- | --- | --- |
| O clique usa texto integral e exames já escolhidos | verificado localmente | Teste da tela envia os mesmos 15 JPGs a um único lote com a transcrição longa, sem gravar anexos adicionais. |
| Só a transcrição é executada ao solicitar transcrição do áudio longo | verificado localmente | A interface abre a fila e importa a transcrição uma vez. O teste da API verifica conclusão após a leitura do áudio, sem chamada à síntese. |
| Captura configurada para ultrapassar uma hora, leitura até o final | verificado localmente | Relógio e microfone simulados mantêm a captura em 60 minutos e finalizam aos 65. Dois arquivos sintéticos de 60 minutos foram lidos por FFmpeg até 3.600 s. WebM de 32.109.615 bytes e M4A de 44.072.165 bytes geraram oito trechos em ordem cada, entregues a um transcritor simulado. |
| Capacidade e limites de 15 exames | verificado localmente | API aceita 15 e rejeita 16. O teste de síntese preserva 1.500 achados em 15 fontes fictícias. Os testes de lote exercitam retomada de fonte e de síntese. |
| Retomada do envio do áudio em partes | verificado localmente | Teste da API verifica posição confirmada, conflitos de posição e de hash, reenvio e igualdade do original final. |
| Envio de original acima de 30 MiB e análise autenticada em Stage | pendente | A validação local não acionou provedor externo. Homologar nos vhosts ativos com material fictício e registrar tempos e resultado antes de promover. |

195 testes de frontend e 89 de backend passaram. Três testes de integração com PostgreSQL ficaram fora do ambiente local. Passaram também a compilação do frontend, o lint das alterações, o guardrail SDD e a sintaxe do provisionador. Stage e produção não foram alterados.
