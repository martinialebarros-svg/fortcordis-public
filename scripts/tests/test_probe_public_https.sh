#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_UNDER_TEST="${REPO_ROOT}/scripts/probe_public_https.sh"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${FIXTURE_ROOT}"' EXIT

fail() {
  echo "[test-public-https-probe] $*" >&2
  exit 1
}

mkdir -p "${FIXTURE_ROOT}/bin"
cat >"${FIXTURE_ROOT}/bin/curl" <<EOF
#!/usr/bin/env bash
set -euo pipefail
counter_file="${FIXTURE_ROOT}/curl-count"
count=0
if [[ -f "\${counter_file}" ]]; then
  count="\$(<"\${counter_file}")"
fi
count=\$((count + 1))
printf '%s' "\${count}" >"\${counter_file}"
if (( count == 1 )); then
  printf 'http=200 remote_ip=216.238.116.77 http_version=2 time_connect_s=0.010 time_tls_s=0.020 time_total_s=0.030'
  exit 0
fi
printf 'http=000 remote_ip= http_version=0 time_connect_s=0.000 time_tls_s=0.000 time_total_s=4.000'
exit 28
EOF
chmod +x "${FIXTURE_ROOT}/bin/curl"

output="$(PATH="${FIXTURE_ROOT}/bin:${PATH}" \
  PROBE_URL=https://app.stage.fortcordis.com.br/dashboard \
  PROBE_LABEL=stage_dashboard \
  PROBE_ATTEMPTS=2 \
  PROBE_INTERVAL_SECONDS=0 \
  bash "${SCRIPT_UNDER_TEST}")"

printf '%s\n' "${output}" | grep -Fqx 'PUBLIC_HTTPS_PROBE label=stage_dashboard attempts=2' || fail "missing header"
printf '%s\n' "${output}" | grep -Fq 'attempt=1 curl_exit=0 http=200' || fail "did not record successful probe"
printf '%s\n' "${output}" | grep -Fq 'attempt=2 curl_exit=28 http=000' || fail "did not record failed transport"
printf '%s\n' "${output}" | grep -Fqx 'PUBLIC_HTTPS_PROBE_SUMMARY label=stage_dashboard success=1 failure=1' || fail "wrong summary"

if grep -Eq -- '--cookie|Authorization:|Bearer |rm -rf' "${SCRIPT_UNDER_TEST}"; then
  fail "probe risks carrying credentials or mutations"
fi

echo "Public HTTPS probe tests passed."
