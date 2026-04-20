import asyncio
import json
import os
from pathlib import Path
import sys
import traceback
import unicodedata

try:
    import socket
except Exception:
    socket = None

try:
    import subprocess
except Exception:
    subprocess = None

if __package__ in (None, ""):
    ROOT = Path(__file__).resolve().parents[1]
    VENDOR_DIR = ROOT.parent / "vendor_py"
    if str(VENDOR_DIR) not in sys.path:
        sys.path.append(str(VENDOR_DIR))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

import flet as ft

from biblia_app.bienvenida import (
    pantalla_carga_saludo,
    pantalla_saludos,
    pantalla_selector_idioma,
    pantalla_selector_modo,
    pantalla_selector_preguntas,
)
from biblia_app.contenido import pantalla_principal, precalentar_contenido
from biblia_app.http_client import HttpRequestError, http_request
from biblia_app.idiomas import get_language_theme

ANULAR_SEGUNDA_PAGINA_SALUDOS = False
ANULAR_PAGINA_CONFIG_KEY = False
WEB_API_KEY_STORAGE_KEY = "com.jmgalmedina.biblia_app.groq_api_key"
GROQ_KEYS_URL = "https://console.groq.com/keys"


async def _resolver_resultado_async(resultado):
    if hasattr(resultado, "__await__"):
        return await resultado
    return resultado


def _obtener_servicio_almacenamiento(page: ft.Page):
    for atributo in ("shared_preferences", "client_storage"):
        servicio = getattr(page, atributo, None)
        if servicio is not None:
            return servicio
    return None


async def leer_api_key_guardada(page: ft.Page) -> str:
    servicio = _obtener_servicio_almacenamiento(page)
    if servicio is None:
        return ""
    getter = getattr(servicio, "get", None)
    if getter is None:
        return ""
    try:
        valor = await _resolver_resultado_async(getter(WEB_API_KEY_STORAGE_KEY))
    except Exception:
        return ""
    return valor.strip() if isinstance(valor, str) else ""


async def guardar_api_key_navegador(page: ft.Page, api_key: str) -> bool:
    servicio = _obtener_servicio_almacenamiento(page)
    if servicio is None:
        return False
    setter = getattr(servicio, "set", None)
    if setter is None:
        return False
    try:
        await _resolver_resultado_async(setter(WEB_API_KEY_STORAGE_KEY, api_key))
        return True
    except Exception:
        return False


def cabeceras_groq(api_key: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "BibliaIA/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def payload_validacion_groq() -> dict[str, object]:
    modelo = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip() or "llama-3.1-8b-instant"
    return {
        "model": modelo,
        "messages": [
            {"role": "system", "content": "Responde de forma breve y clara."},
            {"role": "user", "content": "Responde exactamente: conexion groq ok"},
        ],
        "max_tokens": 24,
        "temperature": 0,
    }


def ejecutar_prueba_groq(api_key: str) -> tuple[int, str, str]:
    return http_request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload_validacion_groq()),
        headers={
            **cabeceras_groq(api_key),
            "Content-Type": "application/json",
        },
        timeout=20,
    )


def guardar_variable_env(clave: str, valor: str, ruta: str = ".env") -> None:
    lineas = []
    path = Path(ruta)
    if path.exists():
        lineas = path.read_text(encoding="utf-8").splitlines()

    encontrada = False
    nuevas = []
    for linea in lineas:
        if "=" in linea and linea.split("=", 1)[0].strip() == clave:
            nuevas.append(f"{clave}={valor}")
            encontrada = True
        else:
            nuevas.append(linea)

    if not encontrada:
        nuevas.append(f"{clave}={valor}")

    contenido = "\n".join(nuevas).rstrip() + "\n"
    path.write_text(contenido, encoding="utf-8")


def validar_api_key_groq(api_key: str, lang_code: str = "es") -> tuple[bool, str]:
    textos = {
        "es": {
            "empty": "Escribe una API key.",
            "ok": "Conexion correcta. La API key parece valida.",
            "unauthorized": "API key invalida o revocada (401). Genera una nueva en Groq y vuelve a probar.",
            "forbidden": "API key sin permisos o bloqueada (403). Revisa tu cuenta/proyecto en Groq y crea una key nueva.",
            "browser_blocked": "La key puede ser valida, pero Groq/Cloudflare ha bloqueado esta prueba por la firma de la peticion. He ajustado la validacion para usar la misma firma que la llamada real.",
            "invalid_content_type": "Groq respondio sin JSON valido ({content_type}).",
            "empty_response": "Groq respondio sin contenido utilizable.",
            "http": "Error HTTP {code}: {msg}",
            "network": "Error de conexion: {reason}",
            "unexpected": "Error inesperado: {error}",
        },
        "ca": {
            "empty": "Escriu una API key.",
            "ok": "Connexio correcta. L'API key sembla valida.",
            "unauthorized": "API key invalida o revocada (401). Crea'n una de nova a Groq i torna-ho a provar.",
            "forbidden": "API key sense permisos o bloquejada (403). Revisa el teu compte/projecte a Groq i crea una key nova.",
            "browser_blocked": "La clau pot ser valida, pero Groq/Cloudflare ha bloquejat aquesta prova per la signatura de la peticio. He ajustat la validacio per usar la mateixa signatura que la crida real.",
            "invalid_content_type": "Groq ha respost sense JSON valid ({content_type}).",
            "empty_response": "Groq ha respost sense contingut utilitzable.",
            "http": "Error HTTP {code}: {msg}",
            "network": "Error de connexio: {reason}",
            "unexpected": "Error inesperat: {error}",
        },
        "fr": {
            "empty": "Saisis une cle API.",
            "ok": "Connexion correcte. La cle API semble valide.",
            "unauthorized": "Cle API invalide ou revoquee (401). Genere une nouvelle cle dans Groq puis reteste.",
            "forbidden": "Cle API sans autorisation ou bloquee (403). Verifie ton compte/projet Groq et cree une nouvelle cle.",
            "browser_blocked": "La cle peut etre valide, mais Groq/Cloudflare a bloque ce test a cause de la signature de la requete. J'ai ajuste la validation pour utiliser la meme signature que l'appel reel.",
            "invalid_content_type": "Groq a repondu sans JSON valide ({content_type}).",
            "empty_response": "Groq a repondu sans contenu exploitable.",
            "http": "Erreur HTTP {code} : {msg}",
            "network": "Erreur de connexion : {reason}",
            "unexpected": "Erreur inattendue : {error}",
        },
        "en": {
            "empty": "Enter an API key.",
            "ok": "Connection successful. The API key looks valid.",
            "unauthorized": "Invalid or revoked API key (401). Generate a new key in Groq and try again.",
            "forbidden": "API key has no permissions or is blocked (403). Check your Groq account/project and create a new key.",
            "browser_blocked": "The key may be valid, but Groq/Cloudflare blocked this check because of the request signature. I adjusted validation to use the same signature as the real API call.",
            "invalid_content_type": "Groq responded without valid JSON ({content_type}).",
            "empty_response": "Groq responded without usable content.",
            "http": "HTTP error {code}: {msg}",
            "network": "Connection error: {reason}",
            "unexpected": "Unexpected error: {error}",
        },
    }
    t = textos.get(lang_code, textos["es"])
    if not api_key:
        return False, t["empty"]

    try:
        status, content_type, body = ejecutar_prueba_groq(api_key)
        if "application/json" not in content_type.lower():
            return False, t["invalid_content_type"].format(content_type=content_type or "sin Content-Type")
        data = json.loads(body)
        choices = data.get("choices", [])
        content = ""
        if choices:
            message = choices[0].get("message", {})
            content = str(message.get("content", "")).strip()
        if 200 <= status < 300 and content:
            return True, t["ok"]
        if 200 <= status < 300:
            return False, t["empty_response"]
        return False, t["http"].format(code=status, msg=body[:180])
    except HttpRequestError as exc:
        if exc.kind == "network":
            return False, t["network"].format(reason=exc.reason or str(exc))
        detalle = exc.body or exc.reason or str(exc)
        try:
            data = json.loads(detalle)
            mensaje = data.get("error", {}).get("message") or data.get("message") or detalle
        except Exception:
            mensaje = detalle
        if exc.code == 401:
            return False, t["unauthorized"]
        if exc.code == 403:
            detalle_lower = mensaje.lower()
            if "browser_signature_banned" in detalle_lower or "error 1010" in detalle_lower:
                return False, t["browser_blocked"]
            return False, t["forbidden"]
        return False, t["http"].format(code=exc.code or "?", msg=mensaje)
    except Exception as exc:
        return False, t["unexpected"].format(error=exc)


def normalizar_texto_soporte(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(ch for ch in base if not unicodedata.combining(ch)).lower().strip()


def responder_soporte_local(pregunta: str, lang_code: str = "es") -> str:
    q = normalizar_texto_soporte(pregunta)

    def contiene(*fragmentos: str) -> bool:
        return any(fragmento in q for fragmento in fragmentos)

    def contiene_todos(*fragmentos: str) -> bool:
        return all(fragmento in q for fragmento in fragmentos)

    respuestas = {
        "es": {
            "get_key": "Para conseguir la key, pulsa 'Conseguir key gratuita'. Se abrira la pagina de Groq. Alli entras en tu cuenta, creas una key, la copias y vuelves aqui para pegarla.",
            "paste_key": "Pega la key en el cuadro donde pone 'Pegar API key de Groq'. Luego pulsa 'Probar conexion'. Si sale bien, ya puedes pulsar 'Siguiente'.",
            "save_env": "Cuando la key se guarda, la app la recuerda para que no tengas que escribirla otra vez.",
            "change_key": "Si quieres cambiar la key, borra la que hay, pega la nueva y vuelve a pulsar 'Probar conexion'.",
            "where_env": "La app guarda la key en un archivo interno. Normalmente no hace falta tocar nada ahi.",
            "what_key_for": "La key es como una llave. Sirve para que la app pueda conectarse y pedir respuestas de inteligencia artificial.",
            "key_cost": "Tener una key no suele costar dinero por si sola. Lo que puede tener coste es el uso que hagas del servicio, segun el plan que tengas. Tambien puede haber opciones gratis con limites.",
            "test_key": "Hazlo asi: pega la key, pulsa 'Probar conexion' y mira el mensaje. Si todo sale bien, ya puedes seguir.",
            "diagnostic": "El boton 'Diagnostico' hace una revision sencilla para decirte si el problema parece venir de internet, de la key o del servicio.",
            "error_401": "El error 401 suele significar que la key no es correcta. Puede estar mal copiada, incompleta o ya no valer. Lo mejor es crear otra y pegarla de nuevo.",
            "error_403": "El error 403 suele significar que la peticion no ha sido aceptada. A veces pasa por permisos o por un bloqueo temporal. Espera un poco y vuelve a probar.",
            "browser_blocked": "Si aparece algo como 'browser blocked', no siempre significa que la key este mal. A veces es solo un bloqueo de seguridad durante la prueba.",
            "error_429": "El error 429 quiere decir que has llegado al limite por un momento. Espera un poco y vuelve a intentarlo. Suele arreglarse solo.",
            "network": "Si no hay internet, la app no puede conectarse para usar la IA. Revisa la conexion y vuelve a probar. Esta ayuda local si funciona aunque no haya internet.",
            "timeout": "Si la prueba tarda mucho, puede ser porque internet va lento o porque el servicio tarda en responder. Espera un poco y prueba otra vez.",
            "browser": "Si no se abre el navegador, no pasa nada. Puedes abrirlo tu mismo y entrar en https://console.groq.com/keys.",
            "next": "El boton 'Siguiente' te deja entrar al resto de la app. Lo normal es pulsarlo cuando ya has pegado la key.",
            "model": "Si sale un error de modelo no disponible, significa que ese modelo no se puede usar ahora con esa cuenta. Normalmente se arregla usando otro o dejando el que viene por defecto.",
            "no_account": "Si no tienes cuenta de Groq, primero necesitas crear una en su web. Sin cuenta no se puede sacar una key.",
            "without_api": "Sin key puedes abrir la app, pero las respuestas de inteligencia artificial no funcionaran hasta que pongas una valida.",
            "save_problem": "Si parece que la key no se guarda, vuelve a pegarla con calma y despues pulsa 'Probar conexion' o 'Siguiente'.",
            "red_green": "Si el mensaje sale en verde, es buena senal: parece que todo ha ido bien. Si sale en rojo, hay algun problema y conviene leer el mensaje.",
            "empty_response": "Si la respuesta sale vacia, normalmente es algo temporal. Espera un poco y vuelve a probar.",
            "fallback": "Puedo ayudarte con dudas sencillas sobre la key: como conseguirla, donde pegarla, como probarla, que significan los errores y si puedes usar la app sin ella.",
        },
        "ca": {
            "get_key": "Per aconseguir la key, prem 'Aconseguir key gratuita'. A Groq inicia sessio, entra a 'API Keys', prem 'Create API Key', copia la clau i enganxa-la aqui.",
            "paste_key": "La key s'enganxa al camp 'Enganxa API key de Groq'. Despres prem 'Provar connexio' i, si tot va be, prem 'Seguent'.",
            "save_env": "Quan escrius una key i es valida o avances, l'app la desa al fitxer .env com GROQ_API_KEY.",
            "change_key": "Si vols canviar la key, enganxa la nova damunt de l'anterior i torna a provar o avancar. L'app substitueix el valor al .env.",
            "where_env": "El fitxer .env es desa a la carpeta del projecte i hi trobaras GROQ_API_KEY=la_teva_clau.",
            "what_key_for": "La API key serveix perque l'app s'identifiqui davant de Groq i pugui demanar respostes d'IA.",
            "key_cost": "La key en si no acostuma a tenir cost per crear-la o copiar-la. El possible cost depen del pla i de l'us que facis a Groq.",
            "test_key": "Primer enganxa la key i despres prem 'Provar connexio'. Si surt en verd, sembla correcta; si surt en vermell, mira el missatge d'error.",
            "diagnostic": "El boto 'Diagnostic' revisa DNS, connexio amb api.groq.com i si la resposta arriba en JSON.",
            "error_401": "L'error 401 sol voler dir que la API key es invalida, esta mal copiada o ha estat revocada.",
            "error_403": "L'error 403 sol indicar manca de permisos o bloqueig de la peticio.",
            "browser_blocked": "Si surt browser blocked o error semblant, no sempre vol dir que la key sigui dolenta. Pot ser un bloqueig de seguretat de Groq o Cloudflare.",
            "error_429": "L'error 429 vol dir que has arribat al limit temporal d'us. Espera uns segons i torna-ho a provar.",
            "network": "Si no hi ha connexio, revisa internet, DNS i que l'equip pugui arribar a api.groq.com.",
            "timeout": "Si la prova tarda massa, normalment es per xarxa lenta o resposta tardana del servidor.",
            "browser": "Si no s'obre el navegador, obre manualment https://console.groq.com/keys.",
            "next": "Prem 'Seguent' quan ja tinguis la key enganxada o desada.",
            "model": "Si surt un error de model no disponible, prova un altre model o deixa el predeterminat.",
            "no_account": "Si no tens compte de Groq, primer l'has de crear per poder generar una API key.",
            "without_api": "Pots obrir l'app sense API, pero les funcions d'IA necessiten una GROQ_API_KEY valida.",
            "save_problem": "Si sembla que la key no es desa, torna a escriure-la i prem provar o seguent.",
            "red_green": "Si surt en verd, ha anat be. Si surt en vermell, hi ha un problema amb la key, la xarxa o el servidor.",
            "empty_response": "Si Groq respon buit, normalment es un problema temporal del servei.",
            "fallback": "Et puc ajudar amb la key, canviar-la, .env, provar connexio, errors 401/403/429, navegador, usar l'app sense API o el pas seguent.",
        },
        "fr": {
            "get_key": "Pour obtenir la cle, clique sur 'Obtenir une cle gratuite'. Dans Groq, ouvre 'API Keys', clique sur 'Create API Key', copie la cle et colle-la ici.",
            "paste_key": "Colle la cle dans le champ API, puis clique sur 'Tester la connexion' et ensuite sur 'Suivant' si tout va bien.",
            "save_env": "Quand tu saisis une cle et que tu avances, l'application la garde dans le fichier .env sous GROQ_API_KEY.",
            "change_key": "Si tu veux changer la cle, colle la nouvelle a la place de l'ancienne puis refais le test ou avance.",
            "where_env": "Le fichier .env se trouve dans le dossier du projet et contient GROQ_API_KEY=ta_cle.",
            "what_key_for": "La cle API sert a identifier l'application aupres de Groq pour pouvoir demander des reponses d'IA.",
            "key_cost": "La cle elle-meme n'a generalement pas de cout. Le cout eventuel depend du plan et de l'usage dans Groq.",
            "test_key": "Colle d'abord la cle puis clique sur 'Tester la connexion'.",
            "diagnostic": "Le bouton 'Diagnostic' verifie DNS, l'acces a api.groq.com et la reponse JSON.",
            "error_401": "L'erreur 401 signifie souvent que la cle API est invalide ou revokee.",
            "error_403": "L'erreur 403 indique souvent un probleme d'autorisation ou un blocage.",
            "browser_blocked": "Si tu vois browser blocked ou un message proche, cela ne veut pas toujours dire que la cle est mauvaise. Cela peut etre un blocage de securite.",
            "error_429": "L'erreur 429 signifie que la limite temporaire a ete atteinte. Attends un peu puis recommence.",
            "network": "S'il n'y a pas de connexion, verifie internet, DNS et l'acces a api.groq.com.",
            "timeout": "Si le test prend trop de temps, c'est souvent un probleme reseau ou un service lent.",
            "browser": "Si le navigateur ne s'ouvre pas, ouvre manuellement https://console.groq.com/keys.",
            "next": "Clique sur 'Suivant' quand la cle est collee ou enregistree.",
            "model": "Si un modele n'est pas disponible, essaie un autre modele ou garde celui par defaut.",
            "no_account": "Si tu n'as pas de compte Groq, il faut d'abord en creer un pour obtenir une cle API.",
            "without_api": "Tu peux ouvrir l'application sans API, mais les fonctions IA demandent une GROQ_API_KEY valide.",
            "save_problem": "Si la cle ne semble pas etre enregistree, resaisis-la puis teste ou avance.",
            "red_green": "Le vert indique que le test a reussi. Le rouge indique un probleme avec la cle, le reseau ou la reponse.",
            "empty_response": "Si Groq repond sans contenu utile, il s'agit souvent d'un probleme temporaire.",
            "fallback": "Je peux aider avec la cle, son changement, .env, le test, les erreurs 401/403/429, le navigateur, l'usage sans API ou l'etape suivante.",
        },
        "en": {
            "get_key": "To get the key, click 'Get free key'. In Groq, open 'API Keys', click 'Create API Key', copy the key, and paste it here.",
            "paste_key": "Paste the key into the API field, then click 'Test connection' and finally 'Next' if everything looks fine.",
            "save_env": "When you enter a key and continue, the app saves it in the .env file as GROQ_API_KEY.",
            "change_key": "If you want to change the key, paste the new one over the old one and test again or continue. The app replaces the value in .env.",
            "where_env": "The .env file is stored in the project folder and contains a line like GROQ_API_KEY=your_key.",
            "what_key_for": "The API key lets the app identify itself to Groq so it can request AI responses.",
            "key_cost": "The key itself usually does not cost money to create or copy. Any cost depends on your Groq plan and how much you use it.",
            "test_key": "Paste the key first, then click 'Test connection'.",
            "diagnostic": "The 'Diagnostic' button checks DNS, access to api.groq.com, and whether the reply comes back as JSON.",
            "error_401": "Error 401 usually means the API key is invalid, badly copied, or revoked.",
            "error_403": "Error 403 usually means missing permissions or a blocked request.",
            "browser_blocked": "If you see browser blocked or a similar message, it does not always mean the key is bad. It can be a Groq or Cloudflare security block during testing.",
            "error_429": "Error 429 means a temporary usage limit was reached. Wait a few seconds and try again.",
            "network": "If there is no connection, check internet, DNS, and whether the device can reach api.groq.com.",
            "timeout": "If the test takes too long, it is often caused by slow network or a delayed server reply.",
            "browser": "If the browser does not open, manually open https://console.groq.com/keys.",
            "next": "Click 'Next' once the key is pasted or saved.",
            "model": "If a model is unavailable, try another model or keep the default one.",
            "no_account": "If you do not have a Groq account yet, you need to create one before you can generate an API key.",
            "without_api": "You can open the app without an API key, but AI features need a valid GROQ_API_KEY. The local help still works without it.",
            "save_problem": "If the key does not seem to save, type it again and then test or continue.",
            "red_green": "Green means the check went well. Red means the app detected a problem with the key, network, or server reply.",
            "empty_response": "If Groq replies with no usable content, it is usually a temporary service issue.",
            "fallback": "I can help with getting or changing the key, .env, testing, errors 401/403/429, browser blocked, browser issues, using the app without API, or the next step.",
        },
    }
    t = respuestas.get(lang_code, respuestas["es"])

    if contiene("browser_signature_banned", "browser blocked", "error 1010", "cloudflare") or contiene_todos("browser", "blocked"):
        return t["browser_blocked"]
    if contiene("para que sirve", "serveix", "a quoi sert", "what is it for", "what does it do") and contiene("key", "clave", "clau", "cle"):
        return t["what_key_for"]
    if contiene("coste", "cuesta", "precio", "pago", "gratis", "gratuita", "free", "cost", "billing") and contiene("key", "clave", "clau", "cle"):
        return t["key_cost"]
    if contiene("429", "rate limit", "limite", "tpm", "tokens per minute"):
        return t["error_429"]
    if contiene("401", "unauthorized", "invalida", "invalid", "revocada", "revoked"):
        return t["error_401"]
    if contiene("403", "forbidden", "bloqueada", "blocked", "cloudflare", "1010"):
        return t["error_403"]
    if contiene("sin api", "without api", "no api", "sin clave", "sin key", "without key") or (contiene("usar", "use") and contiene("sin", "without") and contiene("api", "key", "clave", "clau", "cle")):
        return t["without_api"]
    if contiene("cuenta", "account", "compte", "registrar", "registro", "sign up", "signup") and contiene("groq", "key", "clave", "clau", "cle"):
        return t["no_account"]
    if contiene("cambiar", "change", "canviar", "modifier", "reemplazar", "replace") and contiene("key", "clave", "clau", "cle"):
        return t["change_key"]
    if contiene(".env", "groq_api_key") and contiene("donde", "where", "on", "ou", "fitxer", "archivo", "file"):
        return t["where_env"]
    if contiene(
        "guardar",
        "save",
        "saved",
        "desar",
        "enregistrer",
        "no se guarda",
        "no guarda",
        "no me guarda",
        "desaparece",
        "se borra",
    ) and contiene("key", "clave", "clau", "cle"):
        return t["save_problem"]
    if contiene(
        "ya la pegue",
        "ya la he pegado",
        "ya pegue la key",
        "ya puse la key",
        "y ahora que",
        "ahora que hago",
    ) and contiene("key", "clave", "clau", "cle"):
        return t["test_key"]
    if contiene("verde", "green", "rojo", "red", "vermell") or (contiene("sale", "shows", "sort", "appears") and contiene("rojo", "red", "verde", "green")):
        return t["red_green"]
    if contiene("vacia", "vacio", "vacía", "empty response", "empty", "sin contenido", "no content", "usable content"):
        return t["empty_response"]
    if contiene("tarda", "timeout", "time out", "colgada", "se queda", "too long", "lent", "lento", "slow"):
        return t["timeout"]
    if contiene("dns", "conexion", "conexio", "connexion", "connection", "internet", "red", "network", "offline", "sin internet"):
        return t["network"]
    if contiene("diagnostico", "diagnostic", "diagnostique"):
        return t["diagnostic"]
    if contiene("navegador", "browser", "abrir web", "open browser", "url"):
        return t["browser"]
    if contiene(".env", "groq_api_key", "guardar", "save", "saved", "desar", "enregistrer"):
        return t["save_env"]
    if contiene(
        "probar",
        "test",
        "tester",
        "prov",
        "conexion",
        "connection",
        "como hago la prueba",
        "como pruebo",
        "como la pruebo",
        "quiero probar",
    ):
        return t["test_key"]
    if contiene(
        "pegar",
        "paste",
        "enganxa",
        "colle",
        "donde",
        "where",
        "poner",
        "pongo",
        "meter",
        "meto",
        "escribir",
        "escribo",
    ) and contiene("key", "clave", "clau", "cle"):
        return t["paste_key"]
    if contiene(
        "conseguir",
        "consigo",
        "obtener",
        "obtengo",
        "sacar",
        "saco",
        "crear",
        "create",
        "get free",
        "gratuita",
        "free key",
        "como tener",
        "donde consigo",
        "donde saco",
        "api key",
        "key",
        "clave",
        "clau",
        "cle",
    ):
        return t["get_key"]
    if contiene("modelo", "model", "404", "400", "not available", "no disponible"):
        return t["model"]
    if contiene("siguiente", "next", "seguent", "suivant"):
        return t["next"]
    return t["fallback"]


def detectar_intencion_soporte(pregunta: str, lang_code: str = "es") -> str:
    q = normalizar_texto_soporte(pregunta)

    def contiene(*fragmentos: str) -> bool:
        return any(fragmento in q for fragmento in fragmentos)

    def contiene_todos(*fragmentos: str) -> bool:
        return all(fragmento in q for fragmento in fragmentos)

    if not q:
        return "fallback"
    if contiene("rate limit reached", "http 429", "error 429", "tpm", "tokens per minute", "requested", "used"):
        return "error_429"
    if contiene("incorrect api key", "invalid api key", "api key invalida", "http 401", "error 401", "unauthorized", "revoked"):
        return "error_401"
    if contiene("browser_signature_banned", "browser blocked", "error 1010", "cloudflare", "access denied"):
        return "browser_blocked"
    if contiene("http 403", "error 403", "forbidden", "permission denied"):
        return "error_403"
    if contiene("model not found", "model_decommissioned", "does not exist", "not available", "unsupported model"):
        return "model"
    if contiene("timed out", "timeout", "time out", "read timed out"):
        return "timeout"
    if contiene("failed to establish a new connection", "name resolution", "max retries exceeded", "connection error", "offline", "sin internet"):
        return "network"
    if contiene("empty response", "sin contenido", "no content", "without usable content"):
        return "empty_response"
    if contiene("por donde empiezo", "por donde comienzo", "que hago primero", "que ago primero", "primer paso", "no se empezar", "no se por donde empezar"):
        return "start_here"
    if contiene("para que sirve", "serveix", "a quoi sert", "what is it for", "what does it do") and contiene("key", "clave", "clau", "cle"):
        return "what_key_for"
    if contiene("coste", "cuesta", "precio", "pago", "gratis", "gratuita", "free", "cost", "billing") and contiene("key", "clave", "clau", "cle"):
        return "key_cost"
    if contiene("429", "rate limit", "limite", "tokens per minute"):
        return "error_429"
    if contiene("401", "unauthorized", "invalida", "invalid", "revocada", "revoked"):
        return "error_401"
    if contiene("403", "forbidden", "bloqueada", "blocked"):
        return "error_403"
    if contiene("sin api", "without api", "no api", "sin clave", "sin key", "without key") or (contiene("usar", "use") and contiene("sin", "without") and contiene("api", "key", "clave", "clau", "cle")):
        return "without_api"
    if contiene("cuenta", "account", "compte", "registrar", "registro", "sign up", "signup") and contiene("groq", "key", "clave", "clau", "cle"):
        return "no_account"
    if contiene("cambiar", "change", "canviar", "modifier", "reemplazar", "replace", "borrar", "quitar") and contiene("key", "clave", "clau", "cle"):
        return "change_key"
    if contiene(".env", "groq_api_key") and contiene("donde", "where", "on", "ou", "fitxer", "archivo", "file"):
        return "where_env"
    if contiene(
        "guardar",
        "save",
        "saved",
        "desar",
        "enregistrer",
        "no se guarda",
        "no guarda",
        "no me guarda",
        "desaparece",
        "se borra",
        "medeja",
        "no medeja",
    ) and contiene("key", "clave", "clau", "cle"):
        return "save_problem"
    if contiene(
        "ya la pegue",
        "ya la he pegado",
        "ya pegue la key",
        "ya puse la key",
        "y ahora que",
        "ahora que hago",
    ) and contiene("key", "clave", "clau", "cle"):
        return "test_key"
    if contiene("verde", "green", "rojo", "red", "vermell") or (contiene("sale", "shows", "sort", "appears") and contiene("rojo", "red", "verde", "green")):
        return "red_green"
    if contiene("vacia", "vacio", "vacia", "empty response", "empty", "sin contenido", "no content", "usable content"):
        return "empty_response"
    if contiene("tarda", "timeout", "time out", "colgada", "se queda", "too long", "lent", "lento", "slow"):
        return "timeout"
    if contiene("dns", "conexion", "conexio", "connexion", "connection", "internet", "red", "network", "offline", "sin internet", "conecxion"):
        return "network"
    if contiene("diagnostico", "diagnostic", "diagnostique"):
        return "diagnostic"
    if contiene("navegador", "browser", "abrir web", "open browser", "url"):
        return "browser"
    if contiene(".env", "groq_api_key", "guardar", "save", "saved", "desar", "enregistrer"):
        return "save_env"
    if contiene(
        "probar",
        "test",
        "tester",
        "prov",
        "conexion",
        "connection",
        "como hago la prueba",
        "como pruebo",
        "como la pruebo",
        "quiero probar",
    ):
        return "test_key"
    if contiene(
        "pegar",
        "paste",
        "enganxa",
        "colle",
        "donde",
        "where",
        "poner",
        "pongo",
        "meter",
        "meto",
        "escribir",
        "escribo",
        "donde ba",
    ) and contiene("key", "clave", "clau", "cle"):
        return "paste_key"
    if (
        contiene("como consigo la key", "como obtener la key", "como sacar la key", "donde consigo la key", "donde saco la key")
        or (
            contiene(
                "conseguir",
                "consigo",
                "obtener",
                "obtengo",
                "sacar",
                "saco",
                "crear",
                "create",
                "get free",
                "gratuita",
                "free key",
                "como tener",
                "donde consigo",
                "donde saco",
            )
            and contiene("key", "clave", "clau", "cle")
        )
    ):
        return "get_key"
    if contiene("modelo", "model", "404", "400", "not available", "no disponible"):
        return "model"
    if contiene("siguiente", "next", "seguent", "suivant"):
        return "next"
    if contiene(
        "no funciona",
        "no furula",
        "no va",
        "no me deja",
        "no medeja",
        "me sale rojo",
        "me sale error",
        "que hago",
        "que ago",
        "ayuda",
    ):
        return "guided_check"
    return "fallback"


def resolver_soporte_local(pregunta: str, lang_code: str = "es", repeticiones: int = 0) -> tuple[str, str]:
    intent = detectar_intencion_soporte(pregunta, lang_code)
    if lang_code != "es":
        return intent, responder_soporte_local(pregunta, lang_code)

    respuestas = {
        "start_here": "Vamos paso a paso.\n1. Consigue la key.\n2. Pegala en esta pantalla.\n3. Pulsa 'Probar conexion'.\n4. Si sale bien, pulsa 'Siguiente'.",
        "get_key": "Para conseguir la key:\n1. Pulsa 'Conseguir key gratuita'.\n2. En Groq, inicia sesion.\n3. Entra en 'API Keys' y crea una nueva.\n4. Copiala y vuelve aqui.",
        "paste_key": "La key se pega en el cuadro que pone 'Pegar API key de Groq'. Cuando la pegues, pulsa 'Probar conexion'.",
        "save_env": "La app guarda la key por dentro para recordarla. No necesitas tocar archivos raros ni hacer nada tecnico.",
        "change_key": "Si quieres cambiar la key, borra la anterior, pega la nueva y vuelve a pulsar 'Probar conexion'.",
        "where_env": "La app guarda la key en un archivo interno. Para usar la app no hace falta abrirlo ni tocarlo.",
        "what_key_for": "La key es como una llave. Sirve para que la app pueda conectarse y pedir respuestas de inteligencia artificial.",
        "key_cost": "Tener una key no suele costar dinero por si sola. Lo que puede tener coste es el uso del servicio, segun el plan que tengas.",
        "test_key": "Despues de pegar la key, pulsa 'Probar conexion'. Si el mensaje sale bien, ya puedes pulsar 'Siguiente'.",
        "diagnostic": "El boton 'Diagnostico' revisa de forma sencilla si el problema parece venir de internet, de la key o del servicio.",
        "error_401": "El error 401 suele significar que la key no es correcta. Puede estar mal copiada, incompleta o ya no valer.",
        "error_403": "El error 403 suele significar que la peticion no ha sido aceptada. A veces es por permisos y otras por un bloqueo temporal.",
        "browser_blocked": "Si aparece 'browser blocked', no siempre significa que tu key este mal. A veces es solo un bloqueo de seguridad durante la prueba.",
        "error_429": "El error 429 quiere decir que has llegado al limite por un momento. Suele arreglarse esperando un poco y probando otra vez.",
        "network": "Si no hay internet o la conexion falla, la app no puede hablar con Groq. Esta ayuda local si sigue funcionando aunque no haya internet.",
        "timeout": "Si la prueba tarda mucho, normalmente es porque internet va lento o porque el servicio esta tardando en responder.",
        "browser": "Si no se abre el navegador, no pasa nada. Puedes abrirlo tu mismo y entrar en https://console.groq.com/keys.",
        "next": "El boton 'Siguiente' te deja entrar al resto de la app. Lo normal es usarlo cuando ya has pegado la key y la prueba ha ido bien.",
        "model": "Si sale un error de modelo no disponible, significa que ese modelo no se puede usar ahora con esa cuenta. Suele arreglarse usando otro modelo.",
        "no_account": "Si no tienes cuenta de Groq, primero necesitas crear una en su web. Sin cuenta no se puede sacar una key.",
        "without_api": "Sin key puedes abrir la app, pero las respuestas de inteligencia artificial no funcionaran hasta que pongas una valida.",
        "save_problem": "Si parece que la key no se guarda, vuelve a pegarla despacio y despues pulsa 'Probar conexion' o 'Siguiente'.",
        "red_green": "Si el mensaje sale en verde, es buena señal: parece que todo ha ido bien. Si sale en rojo, hay algun problema y conviene leer el texto.",
        "empty_response": "Si la respuesta sale vacia, normalmente es algo temporal. Espera un poco y vuelve a probar.",
        "guided_check": "Vamos a revisarlo sin tecnicismos.\n1. Mira si tienes internet.\n2. Comprueba si has pegado una key.\n3. Pulsa 'Probar conexion'.\n4. Si sale un mensaje rojo, pegamelo aqui.",
        "fallback": "Puedo ayudarte con cosas simples: conseguir la key, pegarla, probarla, entender errores o saber que hacer despues.",
    }
    respuestas_repetidas = {
        "get_key": "Te lo dejo mas facil.\n1. Pulsa el boton para conseguir la key.\n2. Crea la key en Groq.\n3. Copiala.\n4. Vuelve aqui y pegala.",
        "paste_key": "Muy simple: busca el cuadro de la key, pega la clave ahi y luego pulsa 'Probar conexion'.",
        "test_key": "Lo siguiente es esto: pulsa 'Probar conexion'. Si sale bien, despues pulsa 'Siguiente'.",
        "save_problem": "Prueba asi, despacio: pega la key otra vez y luego pulsa 'Probar conexion'. Si sigue igual, pega aqui el mensaje que salga.",
        "guided_check": "Te acompaño paso a paso.\n1. Internet.\n2. Key pegada.\n3. Pulsa 'Probar conexion'.\n4. Dime el mensaje exacto si falla.",
    }
    acciones = {
        "start_here": "pulsa 'Conseguir key gratuita'.",
        "get_key": "pulsa 'Conseguir key gratuita'.",
        "paste_key": "pega la key en el cuadro grande de esta pantalla.",
        "change_key": "borra la key actual y pega la nueva.",
        "what_key_for": "si ya la tienes, pegala y prueba la conexion.",
        "key_cost": "si quieres, consigue una key y prueba primero el plan gratis.",
        "test_key": "pulsa 'Probar conexion'.",
        "diagnostic": "pulsa 'Diagnostico' si no sabes donde esta el fallo.",
        "error_401": "crea una key nueva y vuelve a pegarla.",
        "error_403": "espera un poco y vuelve a probar.",
        "browser_blocked": "vuelve a probar dentro de un momento.",
        "error_429": "espera un poco y vuelve a pulsar 'Probar conexion'.",
        "network": "revisa internet y prueba otra vez.",
        "timeout": "espera un poco y vuelve a probar.",
        "browser": "abre tu navegador y entra en https://console.groq.com/keys.",
        "next": "pulsa 'Siguiente' cuando la prueba salga bien.",
        "model": "prueba de nuevo con el modelo que viene por defecto.",
        "no_account": "crea primero una cuenta en Groq.",
        "without_api": "si quieres respuestas de IA, consigue una key.",
        "save_problem": "vuelve a pegar la key y pulsa 'Probar conexion'.",
        "red_green": "si sale rojo, copia ese mensaje y pegalo aqui.",
        "empty_response": "vuelve a intentarlo dentro de un momento.",
        "guided_check": "dime o pega aqui el mensaje exacto que te salga.",
        "fallback": "preguntame, por ejemplo: 'como consigo la key'.",
    }
    con_calma = {
        "error_401",
        "error_403",
        "browser_blocked",
        "error_429",
        "network",
        "timeout",
        "model",
        "save_problem",
        "empty_response",
        "guided_check",
    }

    base = respuestas_repetidas.get(intent, respuestas["fallback"]) if repeticiones > 0 else respuestas.get(intent, respuestas["fallback"])
    partes = [base]
    if intent in con_calma:
        partes.append("No te preocupes, esto suele tener solucion.")
    paso = acciones.get(intent)
    if paso:
        partes.append(f"Haz esto ahora: {paso}")
    return intent, "\n\n".join(partes)


def mostrar_error(page: ft.Page, titulo: str, detalle: str):
    theme = get_language_theme("es")
    page.clean()
    page.add(
        ft.SafeArea(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.ERROR_OUTLINE, color=theme["primary"], size=48),
                        ft.Text(titulo, size=22, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            detalle,
                            selectable=True,
                            color=theme["text"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                ),
                padding=24,
                expand=True,
                alignment=ft.Alignment(0, 0),
            )
        )
    )
    page.update()


def main(page: ft.Page):
    def titulo_error(clave: str) -> str:
        titulos = {
            "welcome": {"es": "Error en bienvenida", "ca": "Error a la benvinguda", "fr": "Erreur dans l'accueil", "en": "Welcome error"},
            "greetings": {"es": "Error en saludos", "ca": "Error als missatges de salutacio", "fr": "Erreur dans les salutations", "en": "Greetings error"},
            "loading": {"es": "Error en carga", "ca": "Error en la carrega", "fr": "Erreur de chargement", "en": "Loading error"},
            "entry": {"es": "Error en seleccion de entrada", "ca": "Error en la seleccio d'entrada", "fr": "Erreur dans la selection d'entree", "en": "Entry selection error"},
            "content": {"es": "Error en contenido", "ca": "Error en el contingut", "fr": "Erreur dans le contenu", "en": "Content error"},
            "startup": {"es": "Error al iniciar", "ca": "Error en iniciar", "fr": "Erreur au demarrage", "en": "Startup error"},
        }
        return titulos.get(clave, titulos["startup"]).get(idioma_actual["code"], titulos["startup"]["es"])

    def detalle_error(exc: Exception) -> str:
        return f"{exc}\n\n{traceback.format_exc()}"

    def detectar_idioma_dispositivo() -> str:
        try:
            locale_cfg = getattr(page, "locale_configuration", None)
            current_locale = getattr(locale_cfg, "current_locale", None)
            if current_locale is None:
                return "es"
            locale_text = (
                getattr(current_locale, "language_code", None)
                or getattr(current_locale, "value", None)
                or str(current_locale)
            )
            locale_text = (locale_text or "").lower()
            if locale_text.startswith("ca"):
                return "ca"
            if locale_text.startswith("fr"):
                return "fr"
            if locale_text.startswith("en"):
                return "en"
        except Exception:
            pass
        return "es"

    page.title = "Biblia IA"
    page.bgcolor = get_language_theme("es")["page_bg"]
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    idioma_detectado = detectar_idioma_dispositivo()
    idioma_actual = {"code": idioma_detectado}
    precarga_lanzada = {"ok": False}

    async def precalentar_idioma_detectado_async(idioma: str):
        await asyncio.sleep(0.01)
        precalentar_contenido(idioma)

    def mostrar_selector_idioma():
        try:
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_selector_idioma(page, mostrar_config_ia),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
            if not precarga_lanzada["ok"]:
                precarga_lanzada["ok"] = True
                page.run_task(precalentar_idioma_detectado_async, idioma_detectado)
        except Exception as exc:
            mostrar_error(page, titulo_error("welcome"), detalle_error(exc))

    def mostrar_config_ia(idioma: str):
        if ANULAR_PAGINA_CONFIG_KEY:
            mostrar_saludos(idioma)
            return
        try:
            idioma_actual["code"] = idioma
            theme = get_language_theme(idioma)
            textos = {
                "es": {
                    "title": "Configuracion de IA (Inteligencia Artificial)",
                    "desc": "Proceso rapido: 1) Pulsa 'Conseguir key gratuita'. 2) En la pagina de Groq: inicia sesion, entra en 'API Keys', pulsa 'Create API Key' y copia la clave generada. 3) Vuelve a la app y pegala aqui. 4) Pulsa 'Probar conexion'. 5) Si todo va bien, pulsa 'Siguiente'. Nota: al ser una key gratuita, tiene limites de uso/consultas segun las politicas de Groq.",
                    "notice": "Aviso: si una key ya te funciona, no tienes que poner una nueva cada vez que abras el programa. Solo cambiala si deja de funcionar o si quieres usar otra distinta.",
                    "install_title": "Instalar la app",
                    "install_text": "Si el navegador lo permite, veras la opcion 'Instalar app'. En Android suele estar en el menu del navegador. En iPhone/iPad abre Compartir y pulsa 'Anadir a pantalla de inicio'.",
                    "label": "Pegar API key de Groq",
                    "hint": "Pegar aqui la key",
                    "save": "Guardar key",
                    "test": "Probar conexion",
                    "diagnostic": "Diagnostico",
                    "next": "Siguiente",
                    "back": "Volver",
                    "get_key": "Conseguir key gratuita",
                    "saved": "API key guardada en .env",
                    "saved_web": "API key guardada en este navegador",
                    "required": "Debes escribir una API key.",
                    "testing": "Probando conexion...",
                    "diagnostic_web": "El diagnostico avanzado no esta disponible en la version web. Usa 'Probar conexion'.",
                    "open_key_error": "No se pudo abrir el navegador. URL copiada al portapapeles.",
                    "open_key_ok": "Abriendo pagina de claves de Groq...",
                    "support_title": "Soporte local sin internet",
                    "support_desc": "Esta ayuda te orienta paso a paso aunque no haya internet. Sirve para dudas sobre la key, errores y que hacer despues.",
                    "support_placeholder": "Escribe tu duda con tus palabras. Ejemplo: como consigo la key, no me funciona, me sale error 429...",
                    "support_send": "Preguntar",
                    "support_empty": "Escribe una duda para el soporte local.",
                    "support_welcome": "Hola. Estoy para ayudarte paso a paso. Puedes preguntarme como conseguir la key, donde pegarla o que hacer si sale un error.",
                    "support_typing": "La ayuda local esta escribiendo...",
                    "support_suggestions": "Sugerencias para seguir",
                    "faq_key": "Como consigo la key",
                    "faq_429": "Error 429",
                    "faq_test": "Como pruebo la conexion",
                    "faq_save": "La key no se guarda",
                    "faq_401": "Error 401",
                    "faq_403": "Error 403",
                    "faq_key_for": "Para que sirve una key",
                    "faq_key_cost": "Tiene coste una key",
                    "faq_no_api": "Puedo usar la app sin API",
                },
                "ca": {
                    "title": "Configuracio d'IA (Intelligencia Artificial)",
                    "desc": "Proces rapid: 1) Prem 'Aconseguir key gratuita'. 2) A la pagina de Groq: inicia sessio, entra a 'API Keys', prem 'Create API Key' i copia la clau generada. 3) Torna a l'app i enganxa-la aqui. 4) Prem 'Provar connexio'. 5) Si tot va be, prem 'Seguent'. Nota: com que es una key gratuita, te limits d'us/consultes segons les politiques de Groq.",
                    "notice": "Avís: si una key ja et funciona, no n'has de posar una de nova cada vegada que obris el programa. Només cal canviar-la si deixa de funcionar o si en vols usar una altra.",
                    "install_title": "Installar l'app",
                    "install_text": "Si el navegador ho permet, veuras l'opcio 'Installar app'. A Android sol estar al menu del navegador. A iPhone/iPad obre Compartir i prem 'Afegir a la pantalla d'inici'.",
                    "label": "Enganxa API key de Groq",
                    "hint": "Enganxa aqui la key",
                    "save": "Desar key",
                    "test": "Provar connexio",
                    "diagnostic": "Diagnostic",
                    "next": "Seguent",
                    "back": "Tornar",
                    "get_key": "Aconseguir key gratuita",
                    "saved": "API key desada a .env",
                    "saved_web": "API key desada en aquest navegador",
                    "required": "Has d'escriure una API key.",
                    "testing": "Provant connexio...",
                    "diagnostic_web": "El diagnostic avancat no esta disponible a la versio web. Fes servir 'Provar connexio'.",
                    "open_key_error": "No s'ha pogut obrir el navegador. URL copiada al porta-retalls.",
                    "open_key_ok": "Obrint la pagina de claus de Groq...",
                    "support_title": "Suport local sense internet",
                    "support_desc": "Aquesta ajuda funciona encara que no hi hagi connexio amb Groq. Serveix per dubtes frequents sobre la API key, errors i configuracio.",
                    "support_placeholder": "Escriu un dubte. Exemple: error 429, on enganxo la key, com provo la connexio...",
                    "support_send": "Preguntar",
                    "support_empty": "Escriu un dubte per al suport local.",
                    "support_welcome": "Hola. Soc l'ajuda local de configuracio. Et puc orientar amb la API key, la prova de connexio, errors 401/403/429, .env, navegador o el pas seguent.",
                    "support_typing": "El suport local esta escrivint...",
                    "support_suggestions": "Suggeriments per continuar",
                    "faq_key": "Com aconseguir la key",
                    "faq_429": "Error 429",
                    "faq_test": "Com provar la connexio",
                    "faq_save": "La key no es desa",
                    "faq_401": "Error 401",
                    "faq_403": "Error 403",
                    "faq_key_for": "Per a que serveix una key",
                    "faq_key_cost": "Té cost una key",
                    "faq_no_api": "Puc usar l'app sense API",
                },
                "fr": {
                    "title": "Configuration IA (Intelligence Artificielle)",
                    "desc": "Processus rapide : 1) Clique 'Obtenir une cle gratuite'. 2) Sur la page Groq : connecte-toi, ouvre 'API Keys', clique sur 'Create API Key' et copie la cle generee. 3) Reviens dans l'app et colle-la ici. 4) Clique 'Tester la connexion'. 5) Si tout va bien, clique 'Suivant'. Remarque : comme la cle est gratuite, elle a des limites d'usage/de requetes selon les politiques de Groq.",
                    "notice": "Remarque : si une cle fonctionne deja, tu n'as pas besoin d'en mettre une nouvelle a chaque ouverture du programme. Change-la seulement si elle ne fonctionne plus ou si tu veux en utiliser une autre.",
                    "install_title": "Installer l'app",
                    "install_text": "Si le navigateur le permet, tu verras l'option 'Installer l'app'. Sur Android elle se trouve souvent dans le menu du navigateur. Sur iPhone/iPad ouvre Partager puis 'Sur l'ecran d'accueil'.",
                    "label": "Colle la cle API Groq",
                    "hint": "Colle ici la cle",
                    "save": "Enregistrer la cle",
                    "test": "Tester la connexion",
                    "diagnostic": "Diagnostic",
                    "next": "Suivant",
                    "back": "Retour",
                    "get_key": "Obtenir une cle gratuite",
                    "saved": "Cle API enregistree dans .env",
                    "saved_web": "Cle API enregistree dans ce navigateur",
                    "required": "Tu dois saisir une cle API.",
                    "testing": "Test de connexion...",
                    "diagnostic_web": "Le diagnostic avance n'est pas disponible dans la version web. Utilise 'Tester la connexion'.",
                    "open_key_error": "Impossible d'ouvrir le navigateur. URL copiee dans le presse-papiers.",
                    "open_key_ok": "Ouverture de la page des cles Groq...",
                    "support_title": "Support local sans internet",
                    "support_desc": "Cette aide fonctionne meme sans connexion a Groq. Elle sert pour les questions frequentes sur la cle API, les erreurs et la configuration.",
                    "support_placeholder": "Ecris une question. Exemple : erreur 429, ou coller la cle, comment tester la connexion...",
                    "support_send": "Demander",
                    "support_empty": "Ecris une question pour le support local.",
                    "support_welcome": "Bonjour. Je suis l'aide locale de configuration. Je peux t'aider avec la cle API, le test, les erreurs 401/403/429, .env, le navigateur ou l'etape suivante.",
                    "support_typing": "Le support local ecrit...",
                    "support_suggestions": "Suggestions pour continuer",
                    "faq_key": "Comment obtenir la cle",
                    "faq_429": "Erreur 429",
                    "faq_test": "Comment tester",
                    "faq_save": "La cle ne se garde pas",
                    "faq_401": "Erreur 401",
                    "faq_403": "Erreur 403",
                    "faq_key_for": "A quoi sert une cle",
                    "faq_key_cost": "Une cle a-t-elle un cout",
                    "faq_no_api": "Puis-je utiliser l'app sans API",
                },
                "en": {
                    "title": "AI Setup (Artificial Intelligence)",
                    "desc": "Quick process: 1) Click 'Get free key'. 2) On the Groq page: sign in, open 'API Keys', click 'Create API Key', and copy the generated key. 3) Return to the app and paste it here. 4) Click 'Test connection'. 5) If everything is fine, click 'Next'. Note: free keys have usage/query limits according to Groq policies.",
                    "notice": "Notice: if a key already works for you, you do not need to enter a new one every time you open the program. Change it only if it stops working or if you want to use a different one.",
                    "install_title": "Install the app",
                    "install_text": "If your browser supports it, you will see an 'Install app' option. On Android it is usually in the browser menu. On iPhone/iPad use Share and then 'Add to Home Screen'.",
                    "label": "Paste Groq API key",
                    "hint": "Paste key here",
                    "save": "Save key",
                    "test": "Test connection",
                    "diagnostic": "Diagnostic",
                    "next": "Next",
                    "back": "Back",
                    "get_key": "Get free key",
                    "saved": "API key saved in .env",
                    "saved_web": "API key saved in this browser",
                    "required": "You must enter an API key.",
                    "testing": "Testing connection...",
                    "diagnostic_web": "Advanced diagnostics are not available in the web version. Use 'Test connection'.",
                    "open_key_error": "Could not open browser. URL copied to clipboard.",
                    "open_key_ok": "Opening Groq keys page...",
                    "support_title": "Offline local support",
                    "support_desc": "This help works even if Groq is unreachable. It answers common questions about the API key, errors, and setup.",
                    "support_placeholder": "Write a question. Example: error 429, where do I paste the key, how do I test the connection...",
                    "support_send": "Ask",
                    "support_empty": "Write a question for local support.",
                    "support_welcome": "Hello. I am the local setup help. I can guide you with the API key, connection test, errors 401/403/429, .env, browser issues, or the next step.",
                    "support_typing": "Local help is typing...",
                    "support_suggestions": "Suggested next help",
                    "faq_key": "How to get the key",
                    "faq_429": "Error 429",
                    "faq_test": "How to test",
                    "faq_save": "Key is not saved",
                    "faq_401": "Error 401",
                    "faq_403": "Error 403",
                    "faq_key_for": "What is a key for",
                    "faq_key_cost": "Does a key cost money",
                    "faq_no_api": "Can I use the app without API",
                },
            }
            ui = textos.get(idioma, textos["es"])
            ancho_pagina = page.width or 420
            es_movil = ancho_pagina < 430
            page_padding = page.padding if isinstance(page.padding, (int, float)) else (12 if es_movil else 20)
            ancho_disponible = max(260, int(ancho_pagina - (page_padding * 2) - (8 if es_movil else 12)))
            ancho_panel = min(840, ancho_disponible)
            ancho_contenido = max(220 if es_movil else 240, ancho_panel - (28 if es_movil else 40))
            ancho_burbuja_soporte = max(150, min(420, ancho_contenido - (88 if es_movil else 28)))
            ancho_boton_key = min(360, ancho_contenido)
            alto_historial_soporte = 190 if es_movil else 220
            padding_panel = 14 if es_movil else 20
            padding_soporte = 12 if es_movil else 16

            valor_inicial = ""
            estado = ft.Text("", color=theme["text"], size=13)
            estado_soporte = ft.Text("", color=theme["muted"], size=12)
            input_key = ft.TextField(
                label=ui["label"],
                hint_text=ui["hint"],
                value=valor_inicial,
                password=True,
                can_reveal_password=True,
                width=ancho_contenido,
                autofocus=True,
            )
            historial_soporte = ft.ListView(
                controls=[],
                spacing=8,
                auto_scroll=True,
                height=alto_historial_soporte,
            )
            input_soporte = ft.TextField(
                hint_text=ui["support_placeholder"],
                dense=True,
                expand=True,
                bgcolor=theme["field_bg"],
                border_color=theme["field_border"],
                border_width=0,
                content_padding=ft.padding.symmetric(horizontal=14, vertical=12),
            )
            estado_dialogo_soporte = {"ultimo_intent": None, "repeticiones": 0}

            def burbuja_soporte(
                rol: str,
                texto: str,
                control_mensaje: ft.Control | None = None,
            ) -> ft.Control:
                es_usuario = rol == "user"
                return ft.Row(
                    [
                        ft.Container(
                            content=control_mensaje
                            or ft.Text(
                                texto,
                                color=theme["primary_text"] if es_usuario else theme["text"],
                                size=13,
                                selectable=not es_usuario,
                            ),
                            padding=ft.padding.symmetric(horizontal=12, vertical=10),
                            bgcolor=theme["primary"] if es_usuario else theme["accent"],
                            border=ft.border.all(2, theme["field_border"]),
                            border_radius=14,
                            width=ancho_burbuja_soporte,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END if es_usuario else ft.MainAxisAlignment.START,
                )

            def agregar_mensaje_soporte(rol: str, texto: str) -> None:
                historial_soporte.controls.append(burbuja_soporte(rol, texto))

            def desplazar_soporte_al_final() -> None:
                try:
                    historial_soporte.scroll_to(offset=-1, duration=180)
                except Exception:
                    pass

            def desplazar_pagina_a_soporte() -> None:
                try:
                    page.scroll_to(scroll_key="panel_soporte_historial", duration=220)
                except Exception:
                    try:
                        page.scroll_to(scroll_key="panel_soporte_local", duration=220)
                    except Exception:
                        pass
                try:
                    page.update()
                except Exception:
                    pass

            async def enfocar_respuesta_soporte() -> None:
                page.update()
                await asyncio.sleep(0.03)
                desplazar_pagina_a_soporte()
                desplazar_soporte_al_final()
                await asyncio.sleep(0.03)
                desplazar_pagina_a_soporte()
                desplazar_soporte_al_final()

            def pausa_caracter_soporte(caracter: str) -> float:
                if caracter in ".!?":
                    return 0.04
                if caracter in ",;:":
                    return 0.025
                if caracter == "\n":
                    return 0.02
                if caracter == " ":
                    return 0.008
                return 0.014

            async def animar_respuesta_soporte(texto: str) -> None:
                respuesta_final = (texto or "").strip()
                if not respuesta_final:
                    respuesta_final = ui["support_empty"]
                estado_soporte.value = ui["support_typing"]
                estado_soporte.color = theme["muted"]

                cursor_soporte = "▌"
                texto_animado = ft.Text(
                    cursor_soporte,
                    color=theme["text"],
                    size=13,
                    selectable=True,
                )
                historial_soporte.controls.append(
                    burbuja_soporte("assistant", "", control_mensaje=texto_animado)
                )
                page.update()
                await enfocar_respuesta_soporte()
                await asyncio.sleep(0.14)

                parcial = ""
                for caracter in respuesta_final:
                    parcial += caracter
                    texto_animado.value = f"{parcial}{cursor_soporte}"
                    page.update()
                    await enfocar_respuesta_soporte()
                    await asyncio.sleep(pausa_caracter_soporte(caracter))

                texto_animado.value = respuesta_final
                estado_soporte.value = ""
                page.update()
                await enfocar_respuesta_soporte()

            async def preguntar_soporte_local_async(texto: str | None = None):
                consulta_origen = texto if isinstance(texto, str) else (input_soporte.value or "")
                consulta = consulta_origen.strip()
                if not consulta:
                    estado_soporte.value = ui["support_empty"]
                    estado_soporte.color = ft.Colors.RED_400
                    page.update()
                    return
                agregar_mensaje_soporte("user", consulta)
                intent_detectado = detectar_intencion_soporte(consulta, idioma)
                if intent_detectado == estado_dialogo_soporte["ultimo_intent"]:
                    estado_dialogo_soporte["repeticiones"] += 1
                else:
                    estado_dialogo_soporte["repeticiones"] = 0
                estado_dialogo_soporte["ultimo_intent"] = intent_detectado
                intent_final, respuesta = resolver_soporte_local(
                    consulta,
                    idioma,
                    estado_dialogo_soporte["repeticiones"],
                )
                input_soporte.value = ""
                estado_soporte.value = ""
                estado_soporte.color = theme["muted"]
                page.update()
                await enfocar_respuesta_soporte()
                await animar_respuesta_soporte(respuesta)
                page.update()

            def preguntar_soporte_local(texto: str | None = None):
                page.run_task(preguntar_soporte_local_async, texto)

            agregar_mensaje_soporte("assistant", ui["support_welcome"])
            desplazar_soporte_al_final()

            def guardar_key(_=None):
                key = (input_key.value or "").strip()
                if not key:
                    estado.value = ui["required"]
                    estado.color = ft.Colors.RED_400
                    page.update()
                    return
                os.environ["GROQ_API_KEY"] = key
                if page.web:
                    page.run_task(guardar_api_key_navegador, page, key)
                    estado.value = ui["saved_web"]
                else:
                    guardar_variable_env("GROQ_API_KEY", key)
                    estado.value = ui["saved"]
                estado.color = ft.Colors.GREEN_400
                page.update()

            def probar_key(_=None):
                key = (input_key.value or "").strip()
                if not key:
                    estado.value = ui["required"]
                    estado.color = ft.Colors.RED_400
                    page.update()
                    return
                guardar_key()
                estado.value = ui["testing"]
                estado.color = theme["text"]
                page.update()
                ok, mensaje = validar_api_key_groq(key, idioma)
                estado.value = mensaje
                estado.color = ft.Colors.GREEN_400 if ok else ft.Colors.RED_400
                page.update()

            def diagnostico(_=None):
                if page.web:
                    estado.value = ui["diagnostic_web"]
                    estado.color = theme["text"]
                    page.update()
                    return
                host = "api.groq.com"
                key = (input_key.value or "").strip() or os.getenv("GROQ_API_KEY", "")
                partes = []

                try:
                    if socket is None:
                        raise RuntimeError("socket no disponible")
                    socket.gethostbyname(host)
                    partes.append("DNS: OK")
                except Exception as exc:
                    partes.append(f"DNS: ERROR ({exc})")

                try:
                    status, content_type, body = ejecutar_prueba_groq(key)
                    partes.append(f"CHAT: OK ({status})")
                    partes.append(f"JSON: OK ({'application/json' in content_type.lower()})")
                    data = json.loads(body)
                    partes.append(f"CHOICES: {len(data.get('choices', []))}")
                except HttpRequestError as exc:
                    if exc.kind == "http":
                        partes.append(f"CHAT: ERROR ({exc.code})")
                    else:
                        partes.append(f"RED: ERROR ({exc.reason})")
                except Exception as exc:
                    partes.append(f"GENERAL: ERROR ({exc})")

                estado.value = " | ".join(partes)
                estado.color = theme["text"]
                page.update()

            def abrir_web_groq(_=None):
                url = GROQ_KEYS_URL
                try:
                    page.launch_url(url, web_window_name="_blank")
                    estado.value = ui["open_key_ok"]
                    estado.color = theme["text"]
                except Exception:
                    try:
                        # Fallback para escritorio Windows cuando launch_url falla.
                        if subprocess is None:
                            raise RuntimeError("subprocess no disponible")
                        subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
                        estado.value = ui["open_key_ok"]
                        estado.color = theme["text"]
                    except Exception:
                        try:
                            page.set_clipboard(url)
                        except Exception:
                            pass
                        estado.value = f"{ui['open_key_error']} {url}"
                        estado.color = ft.Colors.AMBER_700
                page.update()

            def siguiente(_=None):
                if (input_key.value or "").strip():
                    guardar_key()
                mostrar_saludos(idioma)

            async def hidratar_api_key_navegador_async():
                if not page.web:
                    return
                api_key_guardada = await leer_api_key_guardada(page)
                if not api_key_guardada:
                    return
                os.environ["GROQ_API_KEY"] = api_key_guardada

            panel_soporte_local = ft.Container(
                key="panel_soporte_local",
                width=ancho_contenido,
                padding=padding_soporte,
                bgcolor=theme["accent"],
                border=ft.border.all(4, theme["field_border"]),
                border_radius=16,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.SUPPORT_AGENT, color=theme["primary"], size=28),
                                ft.Text(
                                    ui["support_title"],
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=theme["primary"],
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Text(
                            ui["support_desc"],
                            color=theme["text"],
                            size=13,
                        ),
                        ft.Container(
                            key="panel_soporte_historial",
                            content=historial_soporte,
                            height=alto_historial_soporte,
                            padding=8 if es_movil else 10,
                            bgcolor=theme["panel_bg"],
                            border=ft.border.all(2, theme["field_border"]),
                            border_radius=14,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ),
                        estado_soporte,
                        ft.Row(
                            [
                                input_soporte,
                                ft.IconButton(
                                    icon=ft.Icons.SEND_ROUNDED,
                                    icon_color=theme["primary_text"],
                                    bgcolor=theme["primary"],
                                    tooltip=ui["support_send"],
                                    on_click=lambda _: preguntar_soporte_local(),
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.ResponsiveRow(
                            [
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_key"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_key"]),
                                        width=9999,
                                    ),
                                ),
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_test"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_test"]),
                                        width=9999,
                                    ),
                                ),
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_save"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_save"]),
                                        width=9999,
                                    ),
                                ),
                            ],
                            spacing=8,
                            run_spacing=8,
                        ),
                        ft.ResponsiveRow(
                            [
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_key_for"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_key_for"]),
                                        width=9999,
                                    ),
                                ),
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_key_cost"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_key_cost"]),
                                        width=9999,
                                    ),
                                ),
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_no_api"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_no_api"]),
                                        width=9999,
                                    ),
                                ),
                            ],
                            spacing=8,
                            run_spacing=8,
                        ),
                        ft.ResponsiveRow(
                            [
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_429"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_429"]),
                                        width=9999,
                                    ),
                                ),
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_401"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_401"]),
                                        width=9999,
                                    ),
                                ),
                                ft.Container(
                                    col={"xs": 12, "sm": 4, "md": 4},
                                    content=ft.OutlinedButton(
                                        ui["faq_403"],
                                        on_click=lambda _: preguntar_soporte_local(ui["faq_403"]),
                                        width=9999,
                                    ),
                                ),
                            ],
                            spacing=8,
                            run_spacing=8,
                        ),
                    ],
                    spacing=12,
                ),
            )

            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.START
            page.add(
                ft.Container(
                    alignment=ft.Alignment(0, -1),
                    expand=True,
                    content=ft.Container(
                        width=ancho_panel,
                        padding=padding_panel,
                        bgcolor=theme["panel_bg"],
                        border=ft.border.all(5, theme["panel_border"]),
                        border_radius=20,
                        content=ft.Column(
                            [
                                ft.Icon(ft.Icons.KEY, color=theme["primary"], size=44),
                                ft.Text(
                                    ui["title"],
                                    size=28,
                                    weight=ft.FontWeight.BOLD,
                                    color=theme["primary"],
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Text(
                                    ui["desc"],
                                    color=theme["text"],
                                    size=14,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Container(
                                    content=ft.Row(
                                        [
                                            ft.Icon(ft.Icons.INFO_OUTLINE, color=theme["primary"], size=22),
                                            ft.Text(
                                                ui["notice"],
                                                color=theme["text"],
                                                size=13,
                                                expand=True,
                                            ),
                                        ],
                                        spacing=10,
                                        vertical_alignment=ft.CrossAxisAlignment.START,
                                    ),
                                    width=ancho_contenido,
                                    padding=14,
                                    bgcolor=theme["accent"],
                                    border=ft.border.all(3, theme["field_border"]),
                                    border_radius=14,
                                ),
                                ft.Container(
                                    visible=page.web,
                                    content=ft.Row(
                                        [
                                            ft.Icon(ft.Icons.DOWNLOAD_FOR_OFFLINE_OUTLINED, color=theme["primary"], size=22),
                                            ft.Column(
                                                [
                                                    ft.Text(
                                                        ui["install_title"],
                                                        color=theme["primary"],
                                                        size=15,
                                                        weight=ft.FontWeight.BOLD,
                                                    ),
                                                    ft.Text(
                                                        ui["install_text"],
                                                        color=theme["text"],
                                                        size=13,
                                                    ),
                                                ],
                                                spacing=4,
                                                expand=True,
                                                tight=True,
                                            ),
                                        ],
                                        spacing=10,
                                        vertical_alignment=ft.CrossAxisAlignment.START,
                                    ),
                                    width=ancho_contenido,
                                    padding=14,
                                    bgcolor="#FFF7CC",
                                    border=ft.border.all(3, theme["secondary"]),
                                    border_radius=14,
                                ),
                                ft.Container(
                                    col={"xs": 12, "sm": 12, "md": 12},
                                    content=ft.OutlinedButton(
                                        ui["get_key"],
                                        icon=ft.Icons.OPEN_IN_NEW,
                                        on_click=None if page.web else abrir_web_groq,
                                        url=GROQ_KEYS_URL if page.web else None,
                                        width=ancho_boton_key,
                                        style=ft.ButtonStyle(
                                            color=theme["text"],
                                            side=ft.BorderSide(4, theme["border"]),
                                            shape=ft.RoundedRectangleBorder(radius=14),
                                            padding=ft.padding.symmetric(vertical=12, horizontal=18),
                                        ),
                                    ),
                                ),
                                ft.Container(
                                    content=input_key,
                                    width=ancho_contenido,
                                    padding=6,
                                    bgcolor=theme["field_bg"],
                                    border=ft.border.all(4, theme["field_border"]),
                                    border_radius=14,
                                ),
                                estado,
                                ft.ResponsiveRow(
                                    [
                                        ft.Container(
                                            col={"xs": 12, "sm": 4, "md": 4},
                                            content=ft.ElevatedButton(
                                                ui["diagnostic"],
                                                icon=ft.Icons.MEDICAL_INFORMATION,
                                                on_click=diagnostico,
                                                width=9999,
                                                style=ft.ButtonStyle(
                                                    bgcolor=theme["secondary"],
                                                    color=theme["secondary_text"],
                                                    side=ft.BorderSide(4, theme["border"]),
                                                    shape=ft.RoundedRectangleBorder(radius=14),
                                                    padding=ft.padding.symmetric(vertical=14),
                                                ),
                                            ),
                                        ),
                                        ft.Container(
                                            col={"xs": 12, "sm": 4, "md": 4},
                                            content=ft.ElevatedButton(
                                                ui["test"],
                                                icon=ft.Icons.WIFI_FIND,
                                                on_click=probar_key,
                                                width=9999,
                                                style=ft.ButtonStyle(
                                                    bgcolor=theme["secondary"],
                                                    color=theme["secondary_text"],
                                                    side=ft.BorderSide(4, theme["border"]),
                                                    shape=ft.RoundedRectangleBorder(radius=14),
                                                    padding=ft.padding.symmetric(vertical=14),
                                                ),
                                            ),
                                        ),
                                        ft.Container(
                                            col={"xs": 12, "sm": 4, "md": 4},
                                            content=ft.ElevatedButton(
                                                ui["next"],
                                                icon=ft.Icons.ARROW_FORWARD,
                                                on_click=siguiente,
                                                width=9999,
                                                style=ft.ButtonStyle(
                                                    bgcolor=theme["primary"],
                                                    color=theme["primary_text"],
                                                    side=ft.BorderSide(4, theme["border"]),
                                                    shape=ft.RoundedRectangleBorder(radius=14),
                                                    padding=ft.padding.symmetric(vertical=14),
                                                ),
                                            ),
                                        ),
                                        ft.Container(
                                            col={"xs": 12, "sm": 12, "md": 12},
                                            content=ft.OutlinedButton(
                                                ui["back"],
                                                icon=ft.Icons.ARROW_BACK,
                                                on_click=lambda _: mostrar_selector_idioma(),
                                                width=9999,
                                                style=ft.ButtonStyle(
                                                    color=theme["text"],
                                                    side=ft.BorderSide(4, theme["border"]),
                                                    shape=ft.RoundedRectangleBorder(radius=14),
                                                    padding=ft.padding.symmetric(vertical=14),
                                                ),
                                            ),
                                        ),
                                    ],
                                    spacing=10,
                                    run_spacing=10,
                                ),
                                panel_soporte_local,
                            ],
                            spacing=14,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            tight=True,
                        ),
                    ),
                )
            )
            input_soporte.on_submit = lambda _: preguntar_soporte_local()
            page.run_task(hidratar_api_key_navegador_async)
            page.update()
        except Exception as exc:
            mostrar_error(page, titulo_error("welcome"), detalle_error(exc))
    def mostrar_saludos(idioma: str):
        if ANULAR_SEGUNDA_PAGINA_SALUDOS:
            mostrar_selector_modo_entrada(idioma)
            return
        try:
            idioma_actual["code"] = idioma
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_saludos(
                        page,
                        idioma,
                        lambda: mostrar_carga_saludo(idioma),
                        mostrar_selector_idioma,
                    ),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
        except Exception as exc:
            mostrar_error(page, titulo_error("greetings"), detalle_error(exc))

    def mostrar_carga_saludo(idioma: str):
        try:
            idioma_actual["code"] = idioma
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_carga_saludo(page, idioma),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
            page.run_task(cargar_contenido_async, idioma)
        except Exception as exc:
            mostrar_error(page, titulo_error("loading"), detalle_error(exc))

    async def cargar_contenido_async(idioma: str):
        await asyncio.sleep(10)
        mostrar_selector_modo_entrada(idioma)

    def volver_desde_selector_modo(idioma: str):
        if ANULAR_SEGUNDA_PAGINA_SALUDOS:
            mostrar_config_ia(idioma)
            return
        mostrar_saludos(idioma)

    def mostrar_selector_modo_entrada(idioma: str):
        try:
            idioma_actual["code"] = idioma
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_selector_modo(
                        page,
                        idioma,
                        lambda modo: mostrar_selector_preguntas(idioma) if modo == "preguntas" else mostrar_contenido(idioma, inicio=modo),
                        lambda: volver_desde_selector_modo(idioma),
                    ),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
        except Exception as exc:
            mostrar_error(page, titulo_error("entry"), detalle_error(exc))

    def mostrar_selector_preguntas(idioma: str):
        try:
            idioma_actual["code"] = idioma
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_selector_preguntas(
                        page,
                        idioma,
                        lambda modo: mostrar_contenido(idioma, inicio=modo),
                        lambda: mostrar_selector_modo_entrada(idioma),
                    ),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
        except Exception as exc:
            mostrar_error(page, titulo_error("entry"), detalle_error(exc))

    def mostrar_contenido(idioma: str | None = None, inicio: str = "biblia"):
        try:
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.START
            idioma_resuelto = idioma or idioma_actual["code"]
            if inicio in {"comportamiento", "incredulo", "cristianos"}:
                volver_a_inicio = lambda: mostrar_selector_preguntas(idioma_resuelto)
            else:
                volver_a_inicio = lambda: mostrar_selector_modo_entrada(idioma_resuelto)
            pantalla_principal(
                page,
                idioma=idioma_resuelto,
                on_volver=lambda: mostrar_saludos(idioma_resuelto),
                inicio=inicio,
                on_volver_inicio=volver_a_inicio,
            )
            page.update()
        except Exception as exc:
            mostrar_error(page, titulo_error("content"), detalle_error(exc))

    try:
        mostrar_selector_idioma()
    except Exception as exc:
        mostrar_error(page, titulo_error("startup"), detalle_error(exc))


if __name__ == "__main__":
    ft.app(target=main)







