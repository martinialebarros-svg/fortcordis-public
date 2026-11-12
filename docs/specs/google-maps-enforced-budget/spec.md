# Requisitos

- `proposed-monitor-config.json` é uma proposta de configuração, não o estado de produção.
- `enabled` permanece `false` e `agenda_budget_mode` permanece `monitor`.
- Os limites por ação são validados por `backend/tests/test_google_maps_agenda_cache_first.py`.
- Este restauro documental não altera preços, limites nem ativa integrações.
