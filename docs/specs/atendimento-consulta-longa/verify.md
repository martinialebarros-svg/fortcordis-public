# Verificação

| Critério | Status | Evidência |
| --- | --- | --- |
| O clique usa texto integral e exames já escolhidos | verificado localmente | Teste da tela envia os mesmos 15 JPGs a um único lote com a transcrição longa, sem gravar anexos adicionais. |
| Só a transcrição é executada ao solicitar transcrição do áudio longo | verificado localmente | A interface abre a fila e importa a transcrição uma vez. O teste da API verifica conclusão após a leitura do áudio, sem chamada à síntese. |
| Captura configurada para ultrapassar uma hora, leitura até o final | verificado localmente | Relógio e microfone simulados mantêm a captura em 60 minutos e finalizam aos 65. Dois arquivos sintéticos de 60 minutos foram lidos por FFmpeg até 3.600 s. WebM de 32.109.615 bytes e M4A de 44.072.165 bytes geraram oito trechos em ordem cada, entregues a um transcritor simulado. |
| Capacidade e limites de 15 exames | verificado localmente | API aceita 15 e rejeita 16. O teste de síntese preserva 1.500 achados em 15 fontes fictícias. Os testes de lote exercitam retomada de fonte e de síntese. |
| Retomada do envio do áudio em partes | verificado localmente | Teste da API verifica posição confirmada, conflitos de posição e de hash, reenvio e igualdade do original final. |
| Envio de original acima de 30 MiB e análise autenticada em Stage | aprovado em Stage | Áudio sintético de 60 minutos, 15 exames, 15 fontes confirmadas, Oito trechos, sete marcadores literais e uma variação reconhecível de palavra. Revisão obrigatória. Teste no SHA `4f4701ed002296e82c0c604e850169bb463a1393`, workflow `44332435608`. Ficha e lote removidos depois da conferência. |

195 testes de frontend e 89 de backend passaram. Três testes de integração com PostgreSQL ficaram fora do ambiente local. Passaram também a compilação do frontend, o lint das alterações, o guardrail SDD e a sintaxe do provisionador. Stage e produção não foram alterados.

A suíte ampla de Stage identificou uma simulação de lote legado sem contexto persistido. O teste foi ajustado para representar o registro real, sem campo de modo no contexto. A consulta do progresso foi mantida somente leitura.

A homologação usou as rotas instaladas, o upload e a consulta no domínio público e um processo de Stage limitado à ficha de teste para iniciar a fila e executar o provedor. Foi mantida a configuração pública do ambiente. O observador somente leitura registrou a conclusão antes da limpeza da ficha sintética. O acompanhamento periódico do operador local encerrou por incompatibilidade do tratamento de timeout no Python 3.10.

