# SECRET_KEY Rotation Runbook

This runbook defines how to rotate `SECRET_KEY` safely in Fort Cordis backend.

## Why this matters

- `SECRET_KEY` signs JWT tokens.
- Weak or default keys allow token forgery risk.
- In production (`APP_ENV=production`), startup now fails when the key is weak/default.

## Generate a strong key

Use one of the commands below:

```bash
openssl rand -base64 48
```

or

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Requirement: at least 32 chars and not placeholder/default.

## Rotation strategy (recommended)

1. Prepare maintenance window (or low-traffic window).
2. Generate new key and store in secret manager.
3. Update `SECRET_KEY` in stage environment.
4. Restart stage and verify:
   - `/health` returns healthy
   - `/ready` returns ready
   - login works
5. Deploy same key change to production.
6. Restart production instances.
7. Verify smoke checks and authentication flows.

## Impact and rollback

- Impact: all existing JWT tokens become invalid after key rotation.
- Expected user effect: users need to login again.
- Rollback:
  1. Revert `SECRET_KEY` to previous value in secret manager.
  2. Restart application.
  3. Confirm login and protected endpoints.

## Environment policy

- `APP_ENV=production` + `ENFORCE_STRONG_SECRET_KEY_IN_PRODUCTION=true`:
  startup blocks weak/default key.
- Development keeps local fallback behavior for convenience.

