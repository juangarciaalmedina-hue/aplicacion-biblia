import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def cargar_env_local() -> None:
    ruta_env = Path(".env")
    if not ruta_env.exists():
        return

    for linea in ruta_env.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        valor = valor.strip().strip('"').strip("'")
        if clave and clave not in os.environ:
            os.environ[clave] = valor


def main() -> int:
    cargar_env_local()

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    proxy_url = os.getenv("OPENROUTER_PROXY_URL", "").strip()
    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Responde solo: OK"}],
        "max_tokens": 5,
    }

    if proxy_url:
        if not proxy_url.lower().startswith("https://"):
            print("ERROR: OPENROUTER_PROXY_URL debe empezar por https://")
            return 1

        req = urllib.request.Request(
            proxy_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        destino = f"proxy {proxy_url}"
    else:
        if not api_key:
            print("ERROR: falta OPENROUTER_API_KEY o OPENROUTER_PROXY_URL en .env")
            return 1

        if not api_key.startswith("sk-or-"):
            print("ERROR: OPENROUTER_API_KEY no tiene formato esperado de OpenRouter")
            return 1

        req = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local.biblia-app",
                "X-Title": "Biblia App",
            },
            method="POST",
        )
        destino = f"OpenRouter directo con el modelo {model}"

    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as response:
            body = response.read().decode("utf-8")
        data = json.loads(body)
        text = data["choices"][0]["message"]["content"].strip()
        print(f"OK: validacion completada contra {destino}.")
        print(f"Respuesta de prueba: {text}")
        return 0
    except urllib.error.HTTPError as exc:
        try:
            detalle = exc.read().decode("utf-8")
        except Exception:
            detalle = str(exc)
        print(f"ERROR: el endpoint configurado devolvio HTTP {exc.code}.")
        print(detalle)
        return 1
    except urllib.error.URLError as exc:
        print(f"ERROR: no se pudo conectar con el endpoint configurado: {exc.reason}")
        return 1
    except Exception as exc:
        print(f"ERROR: fallo inesperado validando el endpoint configurado: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
