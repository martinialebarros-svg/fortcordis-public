#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_UNDER_TEST="${REPO_ROOT}/scripts/inventory_nginx_tls_listeners.sh"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${FIXTURE_ROOT}"' EXIT

fail() {
  echo "[test-nginx-tls-inventory] $*" >&2
  exit 1
}

make_fake_bin() {
  local fake_bin="$1"
  mkdir -p "${fake_bin}"

  cat >"${fake_bin}/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-n" ]]; then
  shift
  if [[ "${1:-}" == "true" ]]; then
    exit 1
  fi
fi
if [[ "${1:-}" == "-S" ]]; then
  shift
  test "${1:-}" = "-p"
  shift 2
  read -r password
fi
exec "$@"
EOF

  cat >"${fake_bin}/nginx" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -v)
    echo 'nginx version: nginx/1.27.0' >&2
    ;;
  -T)
    cat <<'CONFIG'
# configuration file /etc/nginx/nginx.conf:
http2 on;
# configuration file /etc/nginx/sites-enabled/fortcordis-app:
server {
    listen 443 ssl;
    server_name app.stage.fortcordis.com.br app.fortcordis.com.br;
}
# configuration file /etc/nginx/sites-enabled/fortcordis-www:
server {
    listen 443 ssl;
    server_name fortcordis.com www.fortcordis.com;
}
CONFIG
    ;;
  *)
    exit 1
    ;;
esac
EOF

  cat >"${fake_bin}/ss" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo 'LISTEN 0 511 0.0.0.0:443 0.0.0.0:*'
EOF

  cat >"${fake_bin}/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '2 200'
EOF

  chmod +x "${fake_bin}/sudo" "${fake_bin}/nginx" "${fake_bin}/ss" "${fake_bin}/curl"
}

make_fake_bin "${FIXTURE_ROOT}/bin"
output="$(PATH="${FIXTURE_ROOT}/bin:${PATH}" SUDO_PASSWORD=test-password bash "${SCRIPT_UNDER_TEST}")"

printf '%s\n' "${output}" | grep -Fqx 'NGINX_VERSION nginx version: nginx/1.27.0' || fail "did not report the Nginx version"
printf '%s\n' "${output}" | grep -Fqx 'SOCKET local=0.0.0.0:443' || fail "did not report the TLS socket"
printf '%s\n' "${output}" | grep -Fqx 'GLOBAL file=/etc/nginx/nginx.conf directive=http2 on;' || fail "did not report global HTTP/2"
printf '%s\n' "${output}" | grep -Fqx 'VHOST file=/etc/nginx/sites-enabled/fortcordis-app listen=listen 443 ssl; server_name=server_name app.stage.fortcordis.com.br app.fortcordis.com.br; http2=absent' || fail "did not report the app vhost"
printf '%s\n' "${output}" | grep -Fqx 'VHOST file=/etc/nginx/sites-enabled/fortcordis-www listen=listen 443 ssl; server_name=server_name fortcordis.com www.fortcordis.com; http2=absent' || fail "did not report the institutional vhost"
printf '%s\n' "${output}" | grep -Fqx 'ALPN host=app.stage.fortcordis.com.br protocol=2 status=200' || fail "did not report the stage ALPN probe"
printf '%s\n' "${output}" | grep -Fqx 'ALPN host=app.fortcordis.com.br protocol=2 status=200' || fail "did not report the production ALPN probe"

if printf '%s\n' "${output}" | grep -Fq 'test-password'; then
  fail "inventory output exposed the sudo password"
fi

echo "Nginx TLS listener inventory tests passed."
