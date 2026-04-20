import sys
import urllib.error
import urllib.request

try:
    import ssl
except Exception:
    ssl = None

try:
    from js import XMLHttpRequest
except Exception:
    XMLHttpRequest = None


ES_WEB_ASSEMBLY = sys.platform == "emscripten"


class HttpRequestError(Exception):
    def __init__(
        self,
        kind: str,
        message: str = "",
        *,
        code: int | None = None,
        body: str = "",
        reason: str = "",
    ) -> None:
        super().__init__(message or reason or body or kind)
        self.kind = kind
        self.code = code
        self.body = body
        self.reason = reason or message


def _argumentos_urlopen_seguro() -> dict[str, object]:
    if ssl is None:
        return {}
    try:
        return {"context": ssl.create_default_context()}
    except Exception:
        return {}


def _http_request_web(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | str | None = None,
    timeout: int = 20,
) -> tuple[int, str, str]:
    if XMLHttpRequest is None:
        raise HttpRequestError("network", reason="XMLHttpRequest no disponible")

    xhr = XMLHttpRequest.new()
    try:
        xhr.open(method.upper(), url, False)
        xhr.timeout = int(timeout * 1000)
        for clave, valor in (headers or {}).items():
            xhr.setRequestHeader(clave, valor)
        payload = data.decode("utf-8") if isinstance(data, bytes) else data
        xhr.send(payload if payload is not None else None)
    except Exception as exc:
        raise HttpRequestError("network", reason=str(exc)) from exc

    status = int(getattr(xhr, "status", 0) or 0)
    body = str(getattr(xhr, "responseText", "") or "")
    try:
        content_type = str(xhr.getResponseHeader("Content-Type") or "")
    except Exception:
        content_type = ""

    if status == 0:
        raise HttpRequestError("network", reason=body or "respuesta vacia del navegador")
    if status >= 400:
        raise HttpRequestError("http", code=status, body=body, reason=body or f"HTTP {status}")
    return status, content_type, body


def _http_request_urllib(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 20,
) -> tuple[int, str, str]:
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, **_argumentos_urlopen_seguro()) as response:
            body = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
            return response.status, content_type, body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise HttpRequestError("http", code=exc.code, body=body, reason=str(exc)) from exc
    except urllib.error.URLError as exc:
        raise HttpRequestError("network", reason=str(exc.reason)) from exc


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | str | None = None,
    timeout: int = 20,
) -> tuple[int, str, str]:
    if ES_WEB_ASSEMBLY:
        return _http_request_web(method, url, headers=headers, data=data, timeout=timeout)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return _http_request_urllib(method, url, headers=headers, data=payload, timeout=timeout)
