# Verificação

A VPS informou HEAD 407f202e60f3e5fc965e28547f8b7d4a4d20155a. A cópia pública inicial usou 676a591d, uma versão posterior que isolou o módulo aprovado de hipertensão pulmonar e retirou temporariamente outros trabalhos.

Os 59 arquivos de código e testes restaurados foram comparados byte a byte com a revisão instalada. A alteração do workflow repõe três etapas de teste de gestão e mantém as condições de branch, ambiente e ativação. Não foram encontrados padrões de chaves privadas, tokens de provedores, tokens GitHub ou JWTs nos arquivos restaurados. Isso não substitui uma auditoria integral.

O usuário confirmou backup local das frases e do diff na VPS antes desta etapa. Testes automatizados e CI serão registrados após execução. A migração da VPS e das credenciais permanece por concluir.

Validação local: 151 testes passaram, além de 112 subtestes; 9 testes de PostgreSQL foram ignorados por ausência de instância local. O workflow de stage mantém as etapas de PostgreSQL restauradas para validação no Actions. Guardrail SDD e as restrições dos jobs de deploy foram validados localmente.

Verificação de privacidade adicional: git check-ignore confirmou a exclusão padrão de 13 exemplos representativos dos backups e diagnósticos informados pela VPS. Nenhum desses arquivos foi lido ou enviado ao repositório público.
