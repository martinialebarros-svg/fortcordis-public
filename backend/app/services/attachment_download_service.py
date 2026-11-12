from __future__ import annotations

import ipaddress
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote, urlparse

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import settings


@dataclass(frozen=True)
class AttachmentDownloadSource:
    kind: str
    value: str


def _is_public_address(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    # `is_global` cobre privado/loopback/link-local/reservado E faixas
    # especiais como CGNAT (100.64.0.0/10, RFC 6598 - usada por infra/metadata
    # interna em algumas nuvens, ex.: Alibaba Cloud) que a combinacao manual
    # anterior nao cobria. Mas `is_global` NAO exclui multicast (IANA trata
    # multicast como uma classe de endereco a parte, nao "privado") - mantem
    # essa checagem explicita.
    return ip.is_global and not ip.is_multicast


DNS_RESOLUTION_TIMEOUT_SECONDS = 2.0


def _hostname_resolves_to_public_address(hostname: str) -> bool:
    """Anexos "externo" apontam para URLs livres colocadas pelo usuario, mas o
    download e feito pelo SERVIDOR (proxy) - sem essa checagem, um usuario
    autenticado poderia usar o proprio backend para alcancar servicos
    internos/metadata (SSRF), inclusive vazando PORTAL_REMOTE_STORAGE_AUTH_TOKEN
    se o host tambem estivesse na allowlist de confianca.

    Timeout curto e deliberado, aplicado via thread separada (nao
    socket.setdefaulttimeout, que e global/process-wide e afetaria outras
    threads concorrentes no mesmo processo): esta funcao roda em rotas
    sincronas de listagem do portal (thread do pool), disparada para todo
    anexo com URL externa - sem timeout, um host com DNS deliberadamente
    lento travaria a thread ate o timeout do resolver do SO (negacao de
    servico)."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(socket.getaddrinfo, hostname, None)
        try:
            addr_infos = future.result(timeout=DNS_RESOLUTION_TIMEOUT_SECONDS)
        except (socket.gaierror, FutureTimeoutError, OSError):
            return False
    finally:
        # shutdown(wait=False): se a resolucao estourou o timeout, a thread
        # de fundo pode continuar bloqueada por muito mais tempo - nao
        # esperar por ela aqui e o que de fato limita a espera da thread
        # chamadora a DNS_RESOLUTION_TIMEOUT_SECONDS.
        executor.shutdown(wait=False)
    if not addr_infos:
        return False
    return all(_is_public_address(info[4][0]) for info in addr_infos)


def _normalize_remote_url(raw_value: str | None) -> str | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if not _hostname_resolves_to_public_address(parsed.hostname):
        return None
    return value


def resolve_attachment_download_source(attachment) -> AttachmentDownloadSource | None:
    local_path = str(getattr(attachment, "caminho_arquivo", "") or "").strip()
    if local_path and os.path.exists(local_path):
        return AttachmentDownloadSource(kind="local_file", value=local_path)

    remote_url = _normalize_remote_url(getattr(attachment, "url", None))
    if remote_url:
        return AttachmentDownloadSource(kind="remote_url", value=remote_url)

    return None


def attachment_has_download_source(attachment) -> bool:
    return resolve_attachment_download_source(attachment) is not None


PDF_MAGIC_BYTES = b"%PDF-"


def _bytes_look_like_pdf(chunk: bytes) -> bool:
    return chunk.lstrip(b"\x00\r\n\t ").startswith(PDF_MAGIC_BYTES)


def attachment_is_verified_pdf(attachment) -> bool:
    """Confirma que o anexo E DE FATO um PDF (bytes magicos "%PDF-" no inicio
    do conteudo real), complementar a attachment_has_download_source (que so
    confirma que existe ALGO baixavel, nao que o conteudo seja um PDF valido).
    Usado no gate de liberar_exame_no_portal, que concede acesso ao tutor/
    clinica parceira com base nisso. Qualquer falha (arquivo ausente, rede,
    conteudo que nao comeca com %PDF-) e fail-closed: retorna False."""
    source = resolve_attachment_download_source(attachment)
    if not source:
        return False

    if source.kind == "local_file":
        try:
            with open(source.value, "rb") as arquivo:
                return _bytes_look_like_pdf(arquivo.read(1024))
        except OSError:
            return False

    client = httpx.Client(
        follow_redirects=False,
        timeout=max(1, int(settings.PORTAL_REMOTE_STORAGE_TIMEOUT_SECONDS or 20)),
    )
    try:
        headers = {**_build_remote_headers(source.value), "Range": "bytes=0-1023"}
        request = client.build_request("GET", source.value, headers=headers)
        response = client.send(request, stream=True)
        try:
            if response.is_redirect or response.status_code not in (200, 206):
                return False
            chunk = next(response.iter_bytes(), b"")
            return _bytes_look_like_pdf(chunk)
        finally:
            response.close()
    except httpx.HTTPError:
        return False
    finally:
        client.close()


def _is_trusted_storage_host(hostname: str) -> bool:
    trusted_hosts = {
        host.strip().lower()
        for host in str(settings.PORTAL_REMOTE_STORAGE_TRUSTED_HOSTS or "").split(",")
        if host.strip()
    }
    return hostname.lower() in trusted_hosts


def _build_remote_headers(url: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    token = str(settings.PORTAL_REMOTE_STORAGE_AUTH_TOKEN or "").strip()
    if not token:
        return headers

    # O token de storage remoto e um segredo do sistema - so pode ser enviado
    # ao host configurado como storage legitimo, nunca a uma URL livre que o
    # usuario colou como "link anexo" (isso vazaria o token para qualquer
    # servidor de terceiros que o usuario apontar).
    hostname = urlparse(url).hostname or ""
    if not _is_trusted_storage_host(hostname):
        return headers

    header_name = str(settings.PORTAL_REMOTE_STORAGE_AUTH_HEADER or "").strip() or "Authorization"
    if header_name.lower() == "authorization" and not token.lower().startswith(("bearer ", "basic ")):
        headers[header_name] = f"Bearer {token}"
    else:
        headers[header_name] = token
    return headers


def _build_content_disposition(filename: str | None) -> str:
    resolved = str(filename or "").strip() or "anexo.bin"
    return f"attachment; filename*=UTF-8''{quote(resolved)}"


def _iter_remote_response_bytes(client: httpx.Client, response: httpx.Response) -> Iterator[bytes]:
    try:
        for chunk in response.iter_bytes():
            if chunk:
                yield chunk
    finally:
        response.close()
        client.close()


def _build_remote_download_response(attachment, source: AttachmentDownloadSource, *, missing_detail: str):
    client = httpx.Client(
        # Redirects nao sao seguidos: um host inicialmente valido (IP publico)
        # poderia redirecionar para um destino interno/privado, contornando a
        # validacao de _hostname_resolves_to_public_address feita so na URL
        # original.
        follow_redirects=False,
        timeout=max(1, int(settings.PORTAL_REMOTE_STORAGE_TIMEOUT_SECONDS or 20)),
    )
    try:
        request = client.build_request("GET", source.value, headers=_build_remote_headers(source.value))
        response = client.send(request, stream=True)
        if response.is_redirect:
            response.close()
            client.close()
            raise HTTPException(status_code=502, detail="Storage do anexo respondeu com redirecionamento.")
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            exc.response.close()
        except Exception:
            pass
        client.close()
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail=missing_detail) from exc
        raise HTTPException(status_code=502, detail="Falha ao acessar storage do anexo.") from exc
    except httpx.HTTPError as exc:
        client.close()
        raise HTTPException(status_code=502, detail="Falha ao acessar storage do anexo.") from exc

    media_type = str(getattr(attachment, "mime_type", "") or "").strip()
    if not media_type:
        media_type = str(response.headers.get("content-type") or "application/octet-stream")

    headers = {"Content-Disposition": _build_content_disposition(getattr(attachment, "nome_original", None))}
    content_length = response.headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length

    return StreamingResponse(
        _iter_remote_response_bytes(client, response),
        media_type=media_type,
        headers=headers,
    )


def build_attachment_download_response(attachment, *, missing_detail: str):
    source = resolve_attachment_download_source(attachment)
    if not source:
        raise HTTPException(status_code=404, detail=missing_detail)

    if source.kind == "local_file":
        return FileResponse(
            path=source.value,
            media_type=getattr(attachment, "mime_type", None) or "application/octet-stream",
            filename=getattr(attachment, "nome_original", None) or f"anexo_{getattr(attachment, 'id', 'arquivo')}",
        )

    return _build_remote_download_response(attachment, source, missing_detail=missing_detail)
