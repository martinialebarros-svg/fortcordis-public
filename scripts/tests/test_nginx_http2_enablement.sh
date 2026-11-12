#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_UNDER_TEST="${REPO_ROOT}/scripts/ensure_nginx_http2.sh"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${FIXTURE_ROOT}"' EXIT

stage_host="app.stage.fortcordis.com.br"
production_host="app.fortcordis.com.br"
institutional_br_host="fortcordis.com.br"
institutional_com_host="fortcordis.com"
expected_hosts="${stage_host},${production_host},${institutional_br_host},${institutional_com_host}"
site_names=("fortcordis-stage" "fortcordis-app" "fortcordis-com-br" "fortcordis-www")
site_hosts=("${stage_host}" "${production_host}" "${institutional_br_host}" "${institutional_com_host}")

fail() {
  echo "[test-nginx-http2] $*" >&2
  exit 1
}

make_fake_bin() {
  local fake_bin="$1"
  mkdir -p "${fake_bin}"

  cat > "${fake_bin}/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-n" ]]; then
  shift
fi
exec "$@"
EOF

  cat > "${fake_bin}/nginx" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-V" ]]; then
  if [[ "${FAKE_NGINX_HTTP2_MODULE:-1}" == "1" ]]; then
    echo 'nginx version: nginx/1.27.0 --with-http_v2_module' >&2
  fi
  exit 0
fi
test "${FAKE_NGINX_TEST_FAIL:-0}" != "1"
EOF

  cat > "${fake_bin}/readlink" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-f" ]]; then
  shift
fi
exec /usr/bin/readlink "$@"
EOF

  cat > "${fake_bin}/systemctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
test "${1:-}" = "reload"
test "${2:-}" = "nginx"
EOF

  cat > "${fake_bin}/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
for argument in "$@"; do
  if [[ "${argument}" == "--resolve" ]]; then
    if [[ "${FAKE_HTTP2_LOCAL_WARMUP_CALLS:-0}" != "0" ]] && [[ -n "${FAKE_CURL_STATE_FILE:-}" ]]; then
      current_calls=0
      if [[ -f "${FAKE_CURL_STATE_FILE}" ]]; then
        read -r current_calls < "${FAKE_CURL_STATE_FILE}"
      fi
      printf '%s\n' "$((current_calls + 1))" > "${FAKE_CURL_STATE_FILE}"
      if [[ "${current_calls}" -lt "${FAKE_HTTP2_LOCAL_WARMUP_CALLS}" ]]; then
        printf '1'
        exit 0
      fi
    fi
    printf '%s' "${FAKE_HTTP_VERSION:-2}"
    exit 0
  fi
done
if [[ "${FAKE_HTTP2_EXTERNAL_FAIL:-0}" == "1" ]]; then
  printf '1'
  exit 0
fi
printf '%s' "${FAKE_HTTP_VERSION:-2}"
EOF

  chmod +x "${fake_bin}/sudo" "${fake_bin}/nginx" "${fake_bin}/systemctl" "${fake_bin}/curl" "${fake_bin}/readlink"
}

write_site() {
  local site_root="$1"
  local enabled_root="$2"
  local name="$3"
  local host="$4"
  mkdir -p "${site_root}" "${enabled_root}"
  cat > "${site_root}/${name}" <<EOF
server {
    listen 443 ssl; # managed by test
    listen [::]:443 ssl; # managed by test
    server_name ${host};
}
EOF
  ln -s "${site_root}/${name}" "${enabled_root}/${name}"
}

write_all_sites() {
  local site_root="$1"
  local enabled_root="$2"
  local index

  for index in "${!site_names[@]}"; do
    write_site "${site_root}" "${enabled_root}" "${site_names[${index}]}" "${site_hosts[${index}]}"
  done
}

assert_http2_enabled() {
  local site_root="$1"
  local site_name
  local site_file

  for site_name in "${site_names[@]}"; do
    site_file="${site_root}/${site_name}"
    grep -Fqx '    listen 443 ssl http2; # managed by test' "${site_file}" || fail "IPv4 HTTP/2 directive was not added to ${site_file}."
    grep -Fqx '    listen [::]:443 ssl http2; # managed by test' "${site_file}" || fail "IPv6 HTTP/2 directive was not added to ${site_file}."
  done
}

assert_original_config_restored() {
  local site_root="$1"
  local site_name
  local site_file

  for site_name in "${site_names[@]}"; do
    site_file="${site_root}/${site_name}"
    grep -Fqx '    listen 443 ssl; # managed by test' "${site_file}" || fail "Rollback did not restore ${site_file}."
    if grep -Fq 'http2' "${site_file}"; then
      fail "Rollback left an HTTP/2 directive in ${site_file}."
    fi
  done
}

checksums() {
  local site_root="$1"
  (
    cd "${site_root}"
    sha256sum "${site_names[@]}"
  )
}

run_script() {
  local site_root="$1"
  local enabled_root="$2"
  shift 2
  PATH="${FIXTURE_ROOT}/bin:${PATH}" \
    ENABLE_NGINX_HTTP2=1 \
    NGINX_HTTP2_SITE_ROOT="${site_root}" \
    NGINX_HTTP2_ENABLED_ROOT="${enabled_root}" \
    NGINX_HTTP2_EXPECTED_HOSTS="${expected_hosts}" \
    "$@" bash "${SCRIPT_UNDER_TEST}"
}

make_fake_bin "${FIXTURE_ROOT}/bin"

site_root="${FIXTURE_ROOT}/sites-success"
enabled_root="${FIXTURE_ROOT}/enabled-success"
write_all_sites "${site_root}" "${enabled_root}"
run_script "${site_root}" "${enabled_root}" env
assert_http2_enabled "${site_root}"

warmup_root="${FIXTURE_ROOT}/sites-warmup"
warmup_enabled_root="${FIXTURE_ROOT}/enabled-warmup"
warmup_state_file="${FIXTURE_ROOT}/curl-warmup-count"
write_all_sites "${warmup_root}" "${warmup_enabled_root}"
run_script "${warmup_root}" "${warmup_enabled_root}" env \
  FAKE_HTTP2_LOCAL_WARMUP_CALLS=2 \
  FAKE_CURL_STATE_FILE="${warmup_state_file}"
assert_http2_enabled "${warmup_root}"
test "$(cat "${warmup_state_file}")" = "6" || fail "HTTP/2 verification did not retry the local probe."

before_idempotency="$(checksums "${site_root}")"
run_script "${site_root}" "${enabled_root}" env
after_idempotency="$(checksums "${site_root}")"
test "${before_idempotency}" = "${after_idempotency}" || fail "Second execution changed an already-enabled vhost."

rollback_root="${FIXTURE_ROOT}/sites-rollback"
rollback_enabled_root="${FIXTURE_ROOT}/enabled-rollback"
write_all_sites "${rollback_root}" "${rollback_enabled_root}"
if run_script "${rollback_root}" "${rollback_enabled_root}" env FAKE_NGINX_TEST_FAIL=1; then
  fail "Nginx validation failure was accepted."
fi
assert_original_config_restored "${rollback_root}"

protocol_rollback_root="${FIXTURE_ROOT}/sites-protocol-rollback"
protocol_rollback_enabled_root="${FIXTURE_ROOT}/enabled-protocol-rollback"
write_all_sites "${protocol_rollback_root}" "${protocol_rollback_enabled_root}"
if run_script "${protocol_rollback_root}" "${protocol_rollback_enabled_root}" env FAKE_HTTP_VERSION=1; then
  fail "HTTP/1.1 negotiation was accepted."
fi
assert_original_config_restored "${protocol_rollback_root}"

external_rollback_root="${FIXTURE_ROOT}/sites-external-rollback"
external_rollback_enabled_root="${FIXTURE_ROOT}/enabled-external-rollback"
write_all_sites "${external_rollback_root}" "${external_rollback_enabled_root}"
if run_script "${external_rollback_root}" "${external_rollback_enabled_root}" env FAKE_HTTP2_EXTERNAL_FAIL=1; then
  fail "External HTTP/1.1 negotiation was accepted."
fi
assert_original_config_restored "${external_rollback_root}"

module_failure_root="${FIXTURE_ROOT}/sites-module-failure"
module_failure_enabled_root="${FIXTURE_ROOT}/enabled-module-failure"
write_all_sites "${module_failure_root}" "${module_failure_enabled_root}"
if run_script "${module_failure_root}" "${module_failure_enabled_root}" env FAKE_NGINX_HTTP2_MODULE=0; then
  fail "Missing Nginx HTTP/2 module was accepted."
fi
assert_original_config_restored "${module_failure_root}"

ambiguous_root="${FIXTURE_ROOT}/sites-ambiguous"
ambiguous_enabled_root="${FIXTURE_ROOT}/enabled-ambiguous"
write_all_sites "${ambiguous_root}" "${ambiguous_enabled_root}"
cp "${ambiguous_root}/fortcordis-stage" "${ambiguous_root}/fortcordis-stage-copy"
ln -s "${ambiguous_root}/fortcordis-stage-copy" "${ambiguous_enabled_root}/fortcordis-stage-copy"
if run_script "${ambiguous_root}" "${ambiguous_enabled_root}" env; then
  fail "Ambiguous vhost discovery was accepted."
fi
assert_original_config_restored "${ambiguous_root}"

echo "Nginx HTTP/2 enablement tests passed."
