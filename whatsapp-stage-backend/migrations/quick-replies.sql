-- Shared team phrases. A shortcut remains reserved while inactive so restoring
-- a phrase never changes what an existing shortcut means.
CREATE TABLE IF NOT EXISTS quick_replies (
  id BIGSERIAL PRIMARY KEY,
  title VARCHAR(100) NOT NULL CHECK (length(btrim(title)) > 0),
  body TEXT NOT NULL CHECK (length(btrim(body)) BETWEEN 1 AND 4096),
  category VARCHAR(60) NOT NULL DEFAULT '' CHECK (length(category) <= 60),
  shortcut VARCHAR(32) NOT NULL CHECK (shortcut ~ '^[a-z0-9_-]{2,32}$'),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  -- Stable seed identity preserves manual edits, renamed shortcuts and disabling.
  seed_key VARCHAR(60) UNIQUE,
  created_at TIMESTAMPTZ(3) NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ(3) NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS quick_replies_shortcut_lower_key
  ON quick_replies (lower(shortcut));

INSERT INTO quick_replies (title, body, category, shortcut, seed_key)
VALUES
  ('Saudação', 'Olá! Como podemos ajudar?', 'Geral', 'ola', 'welcome'),
  ('Em verificação', 'Recebemos sua mensagem e já estamos verificando.', 'Geral', 'verificando', 'checking'),
  ('À disposição', 'Obrigada. Permanecemos à disposição.', 'Geral', 'disposicao', 'closing')
ON CONFLICT DO NOTHING;
