#!/usr/bin/env bash
set -euo pipefail

# Coleta somente-leitura para investigar qual configuracao governa o ALPN de
# hosts HTTPS. Nao cria arquivos, nao recarrega o Nginx e nao altera vhosts.

SUDO_PASSWORD="${SUDO_PASSWORD:-${VPS_SUDO_PASSWORD:-}}"
INVENTORY_HOSTS="${INVENTORY_HOSTS:-app.stage.fortcordis.com.br,app.fortcordis.com.br}"

log() {
  printf '[nginx-tls-inventory] %s\n' "$*"
}

fail() {
  printf '[nginx-tls-inventory] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

run_with_sudo() {
  if command -v sudo >/dev/null 2>&1; then
    if sudo -n true >/dev/null 2>&1; then
      sudo -n "$@"
      return
    fi

    if [[ -n "${SUDO_PASSWORD}" ]]; then
      printf '%s\n' "${SUDO_PASSWORD}" | sudo -S -p '' "$@"
      return
    fi
  fi

  "$@"
}

emit_selected_nginx_directives() {
  # `nginx -T` pode conter configuracoes que nao pertencem a esta investigacao.
  # O awk abaixo deixa sair somente caminho de arquivo, `listen`, `server_name`
  # e a diretiva global `http2`; nunca o conteudo integral dos arquivos.
  run_with_sudo nginx -T 2>&1 | awk '
    function trim(value) {
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      return value
    }
    function emit_server() {
      if (in_server && has_tls_listener) {
        printf "VHOST file=%s listen=%s server_name=%s http2=%s\n", current_file, listens, server_names, server_http2
      }
    }
    /^# configuration file / {
      current_file = $0
      sub(/^# configuration file /, "", current_file)
      sub(/:$/, "", current_file)
      next
    }
    {
      line = $0
      compact = trim(line)
    }
    !in_server && compact ~ /^http2[[:space:]]+(on|off);$/ {
      printf "GLOBAL file=%s directive=%s\n", current_file, compact
      next
    }
    !in_server && compact ~ /^server[[:space:]]*\{/ {
      in_server = 1
      brace_depth = gsub(/\{/, "{", line) - gsub(/\}/, "}", line)
      listens = ""
      server_names = ""
      server_http2 = "absent"
      has_tls_listener = 0
      next
    }
    in_server {
      if (compact ~ /^listen[[:space:]]+/) {
        if (listens != "") listens = listens " | "
        listens = listens compact
        if (compact ~ /(^|[^0-9])443([^0-9]|$)/) has_tls_listener = 1
      }
      if (compact ~ /^server_name[[:space:]]+/) {
        if (server_names != "") server_names = server_names " | "
        server_names = server_names compact
      }
      if (compact ~ /^http2[[:space:]]+(on|off);$/) {
        server_http2 = compact
      }
      brace_depth += gsub(/\{/, "{", line) - gsub(/\}/, "}", line)
      if (brace_depth == 0) {
        emit_server()
        in_server = 0
      }
    }
  '
}

emit_tls_socket() {
  if ! command -v ss >/dev/null 2>&1; then
    log "SOCKET unavailable=ss"
    return
  fi

  ss -ltnH 'sport = :443' | awk '{printf "SOCKET local=%s\n", $4}'
}

emit_alpn_probe() {
  local host protocol status

  IFS=',' read -r -a hosts <<<"${INVENTORY_HOSTS}"
  for host in "${hosts[@]}"; do
    host="$(printf '%s' "${host}" | tr -d '[:space:]')"
    [[ -n "${host}" ]] || continue

    if protocol_and_status="$(curl --silent --show-error --output /dev/null \
      --connect-timeout 6 --max-time 15 --http2 \
      --resolve "${host}:443:127.0.0.1" \
      --write-out '%{http_version} %{http_code}' "https://${host}/" 2>/dev/null)"; then
      read -r protocol status <<<"${protocol_and_status}"
      printf 'ALPN host=%s protocol=%s status=%s\n' "${host}" "${protocol:-none}" "${status:-000}"
    else
      printf 'ALPN host=%s protocol=unavailable status=000\n' "${host}"
    fi
  done
}

require_command nginx
require_command curl
require_command awk

log "start=read-only"
nginx_version="$(nginx -v 2>&1 || true)"
printf 'NGINX_VERSION %s\n' "${nginx_version:-unavailable}"
emit_tls_socket
emit_selected_nginx_directives || fail "could not read the active Nginx topology"
emit_alpn_probe
log "complete=read-only"
