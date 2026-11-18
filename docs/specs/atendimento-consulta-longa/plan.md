# Plano de entrega

1. Compartilhar os limites do lote dentro do backend. Adaptar a captura e o formulário à fila existente e incluir finalidade somente de transcrição.
2. Validar localmente o upload por fonte, a recuperação do lote, a preservação de texto e limites com dados fictícios. Conferir a decodificação completa em WebM e M4A com o provedor simulado.
3. Conferir no domínio de Stage um original acima de 30 MiB. A fila envia partes de até 8 MB, informa a posição persistida e valida o SHA-256 do original antes do processamento. O teto atual de 30 MiB por requisição nos vhosts continua aplicável.
4. Homologar Stage com cinco JPGs reproduzindo o relato anterior, um conjunto de 15 exames e áudio sintético de uma hora. Conferir captura física por navegador, retomada, contexto e revisão antes de promover.
