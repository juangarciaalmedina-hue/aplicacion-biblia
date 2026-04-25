import os
import asyncio
import json
import random
import re
import sys
import textwrap
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    import subprocess
except Exception:
    subprocess = None

import flet as ft

from biblia_app.http_client import HttpRequestError, http_request, ES_WEB_ASSEMBLY
from biblia_app.idiomas import get_language_config, get_language_theme
from biblia_app.versiculos import VERSICULOS_POR_CAPITULO

def cargar_env_local() -> None:
    if ES_WEB_ASSEMBLY:
        return
    ruta_env = Path.cwd() / ".env"
    if not ruta_env.exists():
        return

    try:
        for linea in ruta_env.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            clave = clave.strip()
            valor = valor.strip().strip('"').strip("'")
            if clave and clave not in os.environ:
                os.environ[clave] = valor
    except Exception:
        pass


cargar_env_local()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.2"))
GROQ_TOP_P = float(os.getenv("GROQ_TOP_P", "0.9"))


def _leer_entero_env(clave: str, por_defecto: int, minimo: int) -> int:
    try:
        return max(minimo, int(str(os.getenv(clave, por_defecto)).strip()))
    except Exception:
        return por_defecto


QUESTION_PROMPT_MAX_CHARS = _leer_entero_env("GROQ_QUESTION_PROMPT_MAX_CHARS", 9000, 2000)
QUESTION_PROMPT_RETRY_CHARS = _leer_entero_env("GROQ_QUESTION_PROMPT_RETRY_CHARS", 5500, 1500)
CHAT_HISTORY_TURNS = _leer_entero_env("GROQ_CHAT_HISTORY_TURNS", 8, 2)
CHAT_MESSAGE_MAX_CHARS = _leer_entero_env("GROQ_CHAT_MESSAGE_MAX_CHARS", 280, 80)
CHAT_HISTORY_TOTAL_CHARS = _leer_entero_env("GROQ_CHAT_HISTORY_TOTAL_CHARS", 1800, 300)
CHAT_SUMMARY_MESSAGE_MAX_CHARS = _leer_entero_env("GROQ_CHAT_SUMMARY_MESSAGE_MAX_CHARS", 160, 50)
CHAT_SUMMARY_TOTAL_CHARS = _leer_entero_env("GROQ_CHAT_SUMMARY_TOTAL_CHARS", 1200, 200)


def construir_system_prompt(lang_code: str, mode: str = "study") -> str:
    language_names = {
        "es": "espanol de Espana",
        "ca": "catalan",
        "fr": "frances",
        "en": "English",
    }
    target_language = language_names.get(lang_code, "espanol de Espana")
    base_instrucciones = (
        "You are an evangelical Christian assistant. "
        f"You must answer only in {target_language}. Do not mix languages. "
        "Never reveal hidden reasoning, chain-of-thought, analysis, or internal notes. "
        "Never output tags such as <think>, </think>, or similar reasoning markers. "
        "Base your responses only on the Bible, preferably Reina-Valera 1960 or equivalent faithful translations, "
        "and on recognized evangelical commentaries and study resources such as Matthew Henry, John MacArthur, Warren Wiersbe, "
        "Charles Spurgeon, J. Vernon McGee, R.C. Sproul, Holman Study Bible, and MacArthur Study Bible. "
        "Do not invent doctrines, verses, quotes, facts, references, or source attributions. "
        "Use a pastoral, kind, biblical tone. "
        "When relevant, cite Bible passages clearly. "
        "Do not use mystical, esoteric, or secular self-help language. "
        "Do not give professional medical, legal, or psychological advice. "
        "If the user asks about matters outside Christianity, respond respectfully but redirect toward biblical truth and Christian discipleship. "
        "Guide the user toward Christ, the Word of God, repentance, faith, obedience, prayer, and a solid Christian life."
    )

    if mode == "question":
        return (
            f"{base_instrucciones} "
            "Use natural wording and concise pastoral clarity in direct answers."
        )

    return (
        f"{base_instrucciones} "
        "Respect the requested structure and tone when preparing studies, reflections, outlines, or explanations."
    )


def mensaje_configuracion_ia(lang_code: str) -> str:
    if lang_code == "ca":
        return "Falta configurar la IA. Guarda la teva clau a la pantalla de configuracio (GROQ_API_KEY)."
    if lang_code == "fr":
        return "La configuration IA est manquante. Enregistre ta cle dans l'ecran de configuration (GROQ_API_KEY)."
    if lang_code == "en":
        return "AI is not configured. Save your key in the setup screen (GROQ_API_KEY)."
    return "Falta configurar la IA. Guarda tu clave en la pantalla de configuracion (GROQ_API_KEY)."


def mensaje_prompt_demasiado_grande(lang_code: str) -> str:
    if lang_code == "ca":
        return "Error de IA: la conversa enviada era massa llarga. He retallat el context, pero encara no ha cabut. Esborra una part del xat o torna-ho a provar."
    if lang_code == "fr":
        return "Erreur IA : la conversation envoyee etait trop longue. J'ai reduit le contexte, mais cela ne tient toujours pas. Efface une partie du chat ou reessaie."
    if lang_code == "en":
        return "AI error: the submitted conversation was too long. I trimmed the context, but it still did not fit. Clear part of the chat or try again."
    return "Error de IA: la conversacion enviada era demasiado larga. He recortado el contexto, pero aun asi no ha cabido. Borra parte del chat o vuelve a intentarlo."


def truncar_texto_centro(texto: str, max_chars: int, marcador: str = " [...] ") -> str:
    texto = str(texto or "").strip()
    if len(texto) <= max_chars:
        return texto
    if max_chars <= len(marcador) + 10:
        return texto[:max_chars].rstrip()
    chars_disponibles = max_chars - len(marcador)
    chars_inicio = chars_disponibles // 2
    chars_fin = chars_disponibles - chars_inicio
    return f"{texto[:chars_inicio].rstrip()}{marcador}{texto[-chars_fin:].lstrip()}"


def compactar_prompt_para_groq(prompt: str, max_chars: int) -> str:
    prompt = str(prompt or "").strip()
    if len(prompt) <= max_chars:
        return prompt

    marcadores_historial = (
        "Historial del chat:\n",
        "Historial del xat:\n",
        "Historique du chat:\n",
        "Historique du chat :\n",
        "Chat history:\n",
    )
    for marcador in marcadores_historial:
        indice = prompt.find(marcador)
        if indice == -1:
            continue
        cabecera = prompt[: indice + len(marcador)].rstrip()
        historial = prompt[indice + len(marcador):].strip()
        espacio_historial = max_chars - len(cabecera) - len("\n[...]\n")
        if espacio_historial <= 80:
            return truncar_texto_centro(prompt, max_chars)
        if len(historial) <= espacio_historial:
            return f"{cabecera}\n{historial}".strip()
        return f"{cabecera}\n[...]\n{historial[-espacio_historial:].lstrip()}".strip()

    return truncar_texto_centro(prompt, max_chars)

def consultar_ia(prompt: str, lang_code: str = "es", mode: str = "study") -> str:
    api_key = os.getenv("GROQ_API_KEY", GROQ_API_KEY).strip()
    if not api_key:
        return mensaje_configuracion_ia(lang_code)

    prompt_original = str(prompt or "").strip()
    prompt_preparado = (
        compactar_prompt_para_groq(prompt_original, QUESTION_PROMPT_MAX_CHARS)
        if mode == "question"
        else prompt_original
    )

    def modelos_disponibles_cuenta() -> list[str]:
        try:
            _, _, body = http_request(
                "GET",
                "https://api.groq.com/openai/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                    "User-Agent": "BibliaIA/1.0",
                },
                timeout=20,
            )
            data = json.loads(body)
            modelos = []
            for item in data.get("data", []):
                mid = str(item.get("id", "")).strip()
                if mid:
                    modelos.append(mid)
            return modelos
        except Exception:
            return []

    modelo_preferido = os.getenv("GROQ_MODEL", GROQ_MODEL).strip() or "llama-3.1-8b-instant"
    modelos_candidatos = []
    for modelo in modelos_disponibles_cuenta() + [
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
        modelo_preferido,
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama-3.1-70b-versatile",
    ]:
        if modelo and modelo not in modelos_candidatos:
            modelos_candidatos.append(modelo)

    ultimo_error = "No se pudo completar la consulta."
    for modelo in modelos_candidatos:
        prompt_actual = prompt_preparado
        reintentos_tamano = 0
        while True:
            payload = {
                "model": modelo,
                "temperature": float(os.getenv("GROQ_TEMPERATURE", str(GROQ_TEMPERATURE))),
                "top_p": float(os.getenv("GROQ_TOP_P", str(GROQ_TOP_P))),
                "messages": [
                    {"role": "system", "content": construir_system_prompt(lang_code, mode)},
                    {"role": "user", "content": prompt_actual},
                ],
            }

            try:
                _, _, body = http_request(
                    "POST",
                    GROQ_URL,
                    data=json.dumps(payload),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": "BibliaIA/1.0",
                    },
                    timeout=35,
                )
                data = json.loads(body)
                return data["choices"][0]["message"]["content"]
            except HttpRequestError as exc:
                detalle = exc.body or exc.reason or str(exc)
                if exc.kind == "http":
                    try:
                        data = json.loads(detalle)
                        mensaje = data.get("error", {}).get("message") or data.get("message") or detalle
                    except Exception:
                        mensaje = detalle
                    mensaje_normalizado = str(mensaje).lower()
                    if exc.code == 413 or "request entity too large" in mensaje_normalizado or "payload too large" in mensaje_normalizado:
                        if mode == "question" and reintentos_tamano < 2:
                            reintentos_tamano += 1
                            limite = QUESTION_PROMPT_RETRY_CHARS if reintentos_tamano == 1 else max(1500, QUESTION_PROMPT_RETRY_CHARS // 2)
                            nuevo_prompt = compactar_prompt_para_groq(prompt_original, limite)
                            if nuevo_prompt != prompt_actual:
                                prompt_actual = nuevo_prompt
                                continue
                        return mensaje_prompt_demasiado_grande(lang_code)
                    ultimo_error = f"Error de IA (HTTP {exc.code}): {mensaje}"
                    if exc.code in (400, 403, 404):
                        break
                    return ultimo_error
                return f"Error de conexion con IA: {exc.reason or detalle}"
            except Exception as exc:
                return f"Error inesperado de IA: {exc}"

    return ultimo_error



versiones_biblia = [
    ("Ninguna", "Ninguna"),
    ("RV1960", "Reina-Valera 1960"),
    ("RVR95", "Reina-Valera Revisada 1995"),
    ("NVI", "Nueva Version Internacional"),
    ("NTV", "Nueva Traduccion Viviente"),
    ("LBLA", "La Biblia de las Americas"),
    ("DHH", "Dios Habla Hoy"),
    ("BLP", "Biblia Lenguaje Actual"),
    ("TLA", "Traduccion en Lenguaje Actual"),
    ("JBS", "Jubileo 2000"),
    ("PDT", "Palabra de Dios para Todos"),
]

caps_por_libro = {
    "Genesis": 50, "Exodo": 40, "Levitico": 27, "Numeros": 36, "Deuteronomio": 34,
    "Josue": 24, "Jueces": 21, "Rut": 4, "1 Samuel": 31, "2 Samuel": 24,
    "1 Reyes": 22, "2 Reyes": 25, "1 Cronicas": 29, "2 Cronicas": 36,
    "Esdras": 10, "Nehemias": 13, "Ester": 10, "Job": 42, "Salmos": 150,
    "Proverbios": 31, "Eclesiastes": 12, "Cantares": 8, "Isaias": 66,
    "Jeremias": 52, "Lamentaciones": 5, "Ezequiel": 48, "Daniel": 12,
    "Oseas": 14, "Joel": 3, "Amos": 9, "Abdias": 1, "Jonas": 4, "Miqueas": 7,
    "Nahum": 3, "Habacuc": 3, "Sofonias": 3, "Hageo": 2, "Zacarias": 14,
    "Malaquias": 4, "Mateo": 28, "Marcos": 16, "Lucas": 24, "Juan": 21,
    "Hechos": 28, "Romanos": 16, "1 Corintios": 16, "2 Corintios": 13,
    "Galatas": 6, "Efesios": 6, "Filipenses": 4, "Colosenses": 4,
    "1 Tesalonicenses": 5, "2 Tesalonicenses": 3, "1 Timoteo": 6,
    "2 Timoteo": 4, "Tito": 3, "Filemon": 1, "Hebreos": 13, "Santiago": 5,
    "1 Pedro": 5, "2 Pedro": 3, "1 Juan": 5, "2 Juan": 1, "3 Juan": 1,
    "Judas": 1, "Apocalipsis": 22,
}

caps_por_libro = {libro: len(capitulos) for libro, capitulos in VERSICULOS_POR_CAPITULO.items()}
PRECARGA_CONTENIDO = {}


def precalentar_contenido(idioma="es"):
    lang = get_language_config(idioma)
    code = lang["code"]
    if code in PRECARGA_CONTENIDO:
        return PRECARGA_CONTENIDO[code]

    datos = {
        "code": code,
        "bible_versions": list(lang["bible_versions"]),
        "books_biblical": list(caps_por_libro.keys()),
        "books_alphabetical": sorted(caps_por_libro.keys()),
        "verse_index": list(VERSICULOS_POR_CAPITULO.items())[:8],
    }
    PRECARGA_CONTENIDO[code] = datos
    return datos

libros_orden_biblico = [
    "Genesis", "Exodo", "Levitico", "Numeros", "Deuteronomio", "Josue",
    "Jueces", "Rut", "1 Samuel", "2 Samuel", "1 Reyes", "2 Reyes",
    "1 Cronicas", "2 Cronicas", "Esdras", "Nehemias", "Ester", "Job",
    "Salmos", "Proverbios", "Eclesiastes", "Cantares", "Isaias",
    "Jeremias", "Lamentaciones", "Ezequiel", "Daniel", "Oseas", "Joel",
    "Amos", "Abdias", "Jonas", "Miqueas", "Nahum", "Habacuc", "Sofonias",
    "Hageo", "Zacarias", "Malaquias", "Mateo", "Marcos", "Lucas", "Juan",
    "Hechos", "Romanos", "1 Corintios", "2 Corintios", "Galatas",
    "Efesios", "Filipenses", "Colosenses", "1 Tesalonicenses",
    "2 Tesalonicenses", "1 Timoteo", "2 Timoteo", "Tito", "Filemon",
    "Hebreos", "Santiago", "1 Pedro", "2 Pedro", "1 Juan", "2 Juan",
    "3 Juan", "Judas", "Apocalipsis",
]

libros_alfabeticos = [
    "Abdias", "Amos", "Apocalipsis", "Cantares", "Colosenses", "1 Corintios",
    "2 Corintios", "1 Cronicas", "2 Cronicas", "Daniel", "Deuteronomio",
    "Eclesiastes", "Efesios", "Esdras", "Ester", "Exodo", "Ezequiel",
    "Filemon", "Filipenses", "Galatas", "Genesis", "Habacuc", "Hageo",
    "Hebreos", "Hechos", "Isaias", "Jeremias", "Job", "Joel", "Jonas",
    "Josue", "1 Juan", "2 Juan", "3 Juan", "Juan", "Judas", "Jueces",
    "Lamentaciones", "Levitico", "Lucas", "Malaquias", "Marcos", "Mateo",
    "Miqueas", "Nahum", "Nehemias", "Numeros", "Oseas", "1 Pedro",
    "2 Pedro", "Proverbios", "1 Reyes", "2 Reyes", "Romanos", "Rut",
    "Salmos", "1 Samuel", "2 Samuel", "Santiago", "Sofonias",
    "1 Tesalonicenses", "2 Tesalonicenses", "1 Timoteo", "2 Timoteo",
    "Tito", "Zacarias",
]

masculinos = sorted({
"Aarón: El sumo sacerdote", "Abraham: El padre de la fe", "Absalón: Hijo de David", "Amós: El profeta", "Andrés: Hermano de Pedro", "Apolo: Judío elocuente y poderoso en las Escrituras", "Aquila: Esposo de Priscila",
"Abiatar: Sacerdote en tiempos de David", "Abimelec: Rey filisteo mencionado con Abraham e Isaac", "Abner: General del ejército de Saúl", "Adonías: Hijo de David que quiso reinar", "Ahitofel: Consejero de David que apoyó a Absalón", "Asa: Rey de Judá", "Asaf: Cantor y salmista", "Aser: Hijo de Jacob", "Azarías: Nombre alternativo de Uzías, rey de Judá", "Azarías: Sacerdote que se opuso al orgullo del rey Uzías",
"Bernabé: Compañero del apóstol Pablo", "Bartimeo: El ciego que recibió la vista", "Booz: Esposo de Rut",
"Baruc: Escriba y compañero del profeta Jeremías", "Beltsasar: Rey de Babilonia en tiempos de Daniel", "Caín: Hijo de Adán y Eva", "Caleb: Uno de los doce espías", "Ciro: Rey persa que permitió el regreso del exilio", "Cornelio: Centurión romano piadoso", "Crispo: Principal de la sinagoga",
"Daniel: El del pozo de los leones", "Demas: Colaborador mencionado por Pablo", "David: El rey David", "Ebed-melec: Siervo etíope que ayudó a Jeremías", "Efraín: Hijo de José", "Aod: Libertador de Israel", "Elcaná: Padre de Samuel", "Eleazar: Hijo de Aarón", "Elí: Sacerdote y juez de Israel",
"Elías: El profeta", "Eliseo: Discípulo de Elías", "Enoc: Séptimo desde Adán", "Epafras: Colaborador de Pablo en Colosas", "Erasto: Colaborador de Pablo en Corinto", "Esdras: El sacerdote", "Eutico: Joven que cayó de una ventana mientras Pablo predicaba", "Ezequías: El rey de Judá", "Ezequiel: El profeta",
"Felipe: Uno de los doce apóstoles", "Filemón: Colaborador de Pablo", "Finees: Nieto de Aarón", "Festo: Porcio Festo fue el procurador romano de Judea",
"Gamaliel: Maestro de la Ley entre los fariseos", "Gedeón: Juez de Israel", "Goliat: Guerrero filisteo derrotado por David",
"Habacuc: El profeta", "Hageo: El profeta", "Hananías: Uno de los compañeros de Daniel", "Hemán: Sabio y cantor", "Hermes: Creyente mencionado por Pablo", "Heber: Descendiente de Sem", "Icabod: Hijo de Finees, nacido en tiempo de desgracia", "Isaac: El hijo de Abraham", "Isacar: Hijo de Jacob", "Isaías: El profeta", "Ismael: Hijo de Abraham", "Itai: Gitita leal a David",
"Jabes: Hombre de oración", "Jair: Juez de Israel", "Jared: Padre de Enoc", "Jefté: Juez de Israel", "Isaí: Padre de David", "Joab: General del ejército de David", "Joel: El profeta", "Jonadab: Sobrino de David", "Jonás: El profeta", "Jonatán: Hijo de Saúl", "Joram: Rey de Israel, hijo de Acab", "Joram: Rey de Judá, hijo de Josafat", "Josafat: Rey de Judá", "José: Hijo de Jacob, vendido a Egipto", "José: Esposo de María, padre legal de Jesús", "José de Arimatea: Discípulo secreto que dio su sepulcro a Jesús", "Josué: Hijo de Nun", "Juan: El apóstol y evangelista", "Juan: El Bautista, precursor de Jesús", "Justo: Creyente mencionado en Hechos",
"Jetro: Suegro de Moisés y sacerdote de Madián", "Labán: Suegro de Jacob", "Lamec: Descendiente de Caín, esposo de Ada y Zila", "Lamec: Padre de Noé, descendiente de Set", "Lázaro: Hermano de Marta y María", "Leví: Hijo de Jacob", "Lot: Sobrino de Abraham", "Lucas: El evangelista",
"Malaquías: El profeta", "Manasés: Hijo de José", "Marcos: El evangelista", "Mardoqueo: Primo de Ester", "Matías: Elegido entre los doce", "Mateo: El recaudador de impuestos", "Matusalén: Hombre longevo del Antiguo Testamento", "Melquisedec: Rey de Salem", "Mefiboset: Hijo de Jonatán", "Micaías: Profeta en tiempos de Acab", "Miqueas: El profeta", "Moisés: El de los diez mandamientos",
"Manaén: Maestro y profeta en la iglesia de Antioquía", "Misael: Uno de los compañeros de Daniel", "Nahúm: El profeta", "Naamán: General sirio sanado de lepra", "Nabal: Hombre rico y necio de Carmel", "Natán: El profeta", "Natanael: Discípulo de Jesús", "Nehemías: Reconstruyó los muros de Jerusalén", "Ner: Padre de Abner", "Nicodemo: Fariseo, principal entre los judíos", "Noé: El del arca",
"Obed: Abuelo de David", "Onésimo: Siervo mencionado por Pablo", "Oseas: El profeta", "Ozías: Rey de Judá",
"Obadías: El profeta",
"Pablo: Saulo de Tarso", "Pedro: El apóstol", "Poncio Pilato: Gobernador romano", "Procoro: Uno de los siete servidores",
"Roboam: Hijo de Salomón", "Rubén: Hijo de Jacob",
"Salomón: El rey Salomón", "Samuel: Hijo de Ana", "Sansón: El juez de Israel", "Saúl: El rey de Israel", "Sem: Hijo de Noé", "Set: Hijo de Adán", "Sila: Variante de Silas en algunas traducciones", "Silas: Acompañante del apóstol Pablo", "Simón de Cirene: Llevó la cruz de Jesús", "Simeón: Anciano que vio al Mesías en el templo", "Simeón: Hijo de Jacob y Lea", "Sóstenes: Colaborador mencionado por Pablo",
"Tadeo: Uno de los doce apóstoles", "Tito: Colaborador del apóstol Pablo",
"Tíquico: Colaborador del apóstol Pablo", "Timoteo: Discípulo del apóstol Pablo", "Tito Justo: Hombre temeroso de Dios", "Tobías: Nombre de varios personajes pos-exilio", "Tomás: El discípulo incrédulo",
"Urías: Esposo de Betsabé", "Uziel: Nombre de varios levitas",
"Zabulón: Hijo de Jacob", "Zaqueo: Jefe de publicanos", "Zebedeo: Padre de Jacobo y Juan", "Zorobabel: Gobernador de Judá", "Zacarías: Padre de Juan el Bautista", "Zacarías: Hijo de Joiada, asesinado en el templo", "Zacarías: El profeta del Antiguo Testamento",
})

femeninos = sorted({
"Abigail: Esposa del rey David", "Abisag: Joven que sirvió al rey David", "Abital: Una de las esposas de David", "Acsa: Hija de Caleb", "Ada: Esposa de Lamec, descendiente de Caín",
"Evodia: Creyente de Filipos exhortada por Pablo", "Ahola: Figura simbólica en Ezequiel", "Aholiba: Figura simbólica en Ezequiel", "Ahinoam: Esposa de David", "Ana: Madre del profeta Samuel", "Ana: Profetisa, hija de Fanuel",
"Apia: Creyente de la casa de Filemón", "Asenat: Esposa de José", "Atalía: Hija del rey Acab y de la reina Jezabel", "Atara: Esposa de Jerahmeel", "Azuba: Esposa de Caleb",
"Basemat: Esposa de Esaú, hija de Elón hitita", "Basemat: Hija de Ismael y esposa de Esaú", "Betsabé: Esposa de Urías el heteo", "Berenice: Hermana de Agripa", "Bilha: Sierva de Raquel", "Bítia: Hija del faraón que tomó a Moisés", "Candace: Reina de Etiopía",
"Claudia: Cristiana cercana a Pablo", "Cloe: Mujer de cuya casa llegaron noticias a Pablo", "Cozbi: Mujer madianita", "Dalila: Mujer de Sansón", "Dámaris: Creyente de Atenas",
"Débora: Jueza de Israel", "Dina: Hija de Jacob", "Dorcas: Conocida como Tabita", "Drusila: Esposa del gobernador Félix", "Efrata: Esposa de Caleb mencionada en genealogías", "Eglá: Una de las esposas de David",
"Elisabet: Madre de Juan el bautista", "Eliseba: Esposa de Aarón", "Ester: La reina Ester", "Eunice: Madre de Timoteo", "Eva: Esposa de Adán",
"Esposa de Isaías: Mujer llamada profetisa en Isaías", "Esposa de Pilato: Mujer de Pilato que le advirtió sobre Jesús", "Febe: Diaconisa de la iglesia", "Gómer: Esposa del profeta Oseas", "Hadasa: Nombre hebreo de Ester", "Agar: Sierva de Sara", "Trifosa: Creyente trabajadora en el Señor", "Hamutal: Madre de reyes de Judá",
"Hija de Faraón: Rescató a Moisés del río", "Hija de Jefté: Hija única de Jefté", "Hijas de Lot: Madres de Moab y Amón",
"Herodías: Mujer vinculada a la muerte de Juan el Bautista", "Hepsiba: Esposa del rey Ezequías", "Hogla: Hija de Zelofehad", "Hulda: La profetisa", "Isca: Pariente de Abraham",
"Jael: La que mató a Sísara", "Jedida: Madre del rey Josías", "Jehoseba: Hija del rey Joram", "Jemima: Hija de Job", "Jezabel: Esposa del rey Acab",
"Jocabed: Madre de Moisés", "Julia: Creyente saludada por Pablo en Romanos", "Junia: Compañera de prisiones de Pablo", "Keren-hapuc: Hija de Job", "Cetura: Esposa de Abraham",
"Lía: Esposa de Jacob", "Lidia: Vendedora de púrpura", "Loida: La abuela de Timoteo", "Lo-ruhama: Hija simbólica de Oseas", "Maaca: Esposa de David y madre de Absalón", "Maaca: Madre del rey Abías",
"Mahalat: Hija de Ismael y esposa de Esaú", "Maala: Hija de Zelofehad", "Mara: Nombre que tomó Noemí en su amargura", "María: Madre de Jesús de Nazaret", "María: Hermana de Marta y Lázaro",
"María Magdalena: Seguidora de Jesús", "María de Cleofás: Presente en la crucifixión", "María: Madre de Juan Marcos", "Marta: Hermana de María y Lázaro", "Meriab: Otra forma del nombre Merab",
"Mehetabel: Esposa de Hadad rey de Edom", "Merab: Hija de Saúl", "Mical: Esposa del rey David", "Milca: Pariente de Abraham", "Miriam: Hermana de Aarón y de Moisés", "Mujer cananea: Mostró gran fe ante Jesús",
"Mujer de Job: Esposa de Job", "Mujer de Lot: Miró hacia atrás al salir de Sodoma", "Mujer de Manoa: Madre de Sansón", "Mujer de Potifar: Acusó falsamente a José", "Mujer encorvada: Sanada por Jesús",
"Mujer samaritana: Habló con Jesús junto al pozo", "Mujer sirofenicia: Pidió misericordia para su hija", "Mujer sorprendida en adulterio: Llevada ante Jesús", "Mujer sunamita: Hospedó a Eliseo", "Mujer sabia de Abel: Evitó la destrucción de la ciudad",
"Mujer sabia de Tecoa: Habló ante el rey David", "Mujer del flujo de sangre: Tocó el manto de Jesús", "Naama: Madre del rey Roboam", "Naara: Mujer mencionada en genealogías de Judá", "Noa: Hija de Zelofehad",
"Noemí: Suegra de Rut", "Noadia: Falsa profetisa en tiempos de Nehemías", "Orfa: Cuñada de Rut", "Penina: Mujer de Elcaná", "Pérsida: Creyente elogiada por Pablo",
"Priscila: Esposa de Aquila", "Púa: Una de las parteras hebreas", "Rahab: La mujer de Jericó", "Raquel: Esposa de Jacob", "Rebeca: Esposa de Isaac", "Reina del Sur: Visitó a Salomón para probar su sabiduría",
"Reina de Saba: Visitó al rey Salomón", "Reuma: Concubina de Nacor", "Rizpa: Concubina del rey Saúl", "Rode: Sierva que reconoció a Pedro", "Rut: Esposa de Booz",
"Safira: Esposa de Ananías", "Salomé: Seguidora de Jesús", "Salomé: Hija de Herodías", "Sarai: Nombre anterior de Sara", "Sara: Esposa de Abraham", "Séfora: Esposa de Moisés",
"Sifra: Una de las parteras hebreas", "Síntique: Creyente de Filipos exhortada a vivir en unidad", "Susana: Seguidora y servidora de Jesús", "Tabita: Dorcas", "Trifena: Creyente trabajadora en el Señor",
"Sulamita: Amada descrita en el Cantar de los Cantares", "Tahpenes: Reina de Egipto", "Tamar: Nuera de Judá", "Tamar: Hija del rey David", "Tirsa: Una de las hijas de Zelofehad", "Vasti: Esposa del rey Asuero",
"Viuda de Naín: Recibió la misericordia de Jesús", "Viuda de Sarepta: Alimentada en tiempos de Elías", "Viuda pobre del templo: Dio todo lo que tenía", "Zibia: Madre del rey Joás", "Zilpa: Sierva de Lía"
})

pueblos = sorted({
    "Amalecitas", "Amonitas", "Amorreos", "Arameos", "Asirios", "Babilonios", "Caldeos",
    "Cananeos", "Cretenses", "Cusitas", "Danitas", "Egipcios", "Edomitas", "Elamitas", "Efraimitas",
    "Fenicios", "Filisteos", "Gabaonitas", "Gergeseos", "Gesureos", "Hebreos", "Hititas",
    "Hivitas", "Horitas", "Hurritas", "Israelitas", "Jebuseos", "Lidios", "Madianitas", "Medianitas",
    "Mesec", "Moabitas", "Ninivitas", "Partos", "Persas", "Romanos", "Samaritanos", "Sidonios",
    "Sirios", "Sumerios", "Tarsenses", "Tribus de Israel",
})

lugares = sorted({
    "Antioquia", "Ararat", "Atenas", "Babilonia", "Beerseba", "Belén", "Betania", "Betel", "Betesda",
    "Cafarnaum", "Caldea", "Cana", "Canaán", "Carmelo", "Cesarea", "Cesarea de Filipo", "Corinto",
    "Creta", "Damasco", "Decápolis", "Derbe", "Egipto", "Emaús", "Esmirna", "Filipos", "Galilea", "Gaza",
    "Getsemaní", "Gólgota", "Gosén", "Hebrón", "Horeb", "Jericó", "Jerusalén", "Jope", "Jordán",
    "Laodicea", "Listra", "Macedonia", "Magdala", "Madián", "Mileto", "Monte de los Olivos", "Nazaret", "Nínive",
    "Patmos", "Penuel", "Persia", "Pisidia", "Ponto", "Ramá", "Ramesés", "Samaria", "Sardis",
    "Sarepta", "Siquem", "Silo", "Sinaí", "Sión", "Siria", "Susa", "Tarsis", "Tiatira", "Tiro",
    "Troas", "Ur", "Zoar",
})

religiones_mundo = sorted({
    "Cristianismo: Fe basada en Jesucristo y el evangelio",
    "Catolicismo: Rama principal del cristianismo con centro histórico en Roma",
    "Protestantismo: Conjunto de iglesias cristianas surgidas de la Reforma",
    "Ortodoxia oriental: Tradición cristiana histórica de las iglesias ortodoxas",
    "Evangelicalismo: Corriente cristiana centrada en conversión, Biblia y evangelización",
    "Pentecostalismo: Movimiento cristiano que enfatiza la obra del Espíritu Santo",
    "Islam: Religión monoteísta fundada en las enseñanzas de Mahoma",
    "Sunismo: Rama mayoritaria del islam",
    "Chiismo: Rama principal del islam vinculada a la sucesión de Alí",
    "Sufismo: Corriente mística dentro del islam",
    "Judaísmo: Religión del pueblo judío basada en la Torá",
    "Judaísmo ortodoxo: Corriente judía tradicional de estricta observancia",
    "Judaísmo conservador: Corriente judía de continuidad y adaptación",
    "Judaísmo reformista: Corriente judía de enfoque más liberal",
    "Hinduismo: Conjunto de tradiciones religiosas originadas en la India",
    "Vaishnavismo: Corriente hindú centrada en Vishnu",
    "Shaivismo: Corriente hindú centrada en Shiva",
    "Shaktismo: Corriente hindú centrada en la diosa Shakti",
    "Budismo: Tradición fundada a partir de las enseñanzas de Buda",
    "Budismo theravada: Rama budista extendida en el sur de Asia",
    "Budismo mahayana: Rama budista extendida en Asia oriental",
    "Budismo vajrayana: Forma budista asociada al Tíbet y regiones cercanas",
    "Sijismo: Religión monoteísta originada en el Punjab",
    "Jainismo: Tradición india centrada en la no violencia y la disciplina",
    "Zoroastrismo: Antigua religión persa vinculada a Zaratustra",
    "Bahaismo: Religión monoteísta nacida en Persia con vocación universal",
    "Confucianismo: Tradición filosófica y ética de origen chino",
    "Taoismo: Tradición religiosa y filosófica china vinculada al Tao",
    "Sintoismo: Religión tradicional de Japón",
    "Animismo: Creencia en espíritus asociados a la naturaleza y los seres",
    "Tradiciones chinas: Conjunto de prácticas religiosas populares de China",
    "Religiones africanas tradicionales: Sistemas religiosos aut?ctonos de ?frica",
    "Religiones indígenas americanas: Tradiciones espirituales de pueblos originarios de América",
    "Religiones indígenas australianas: Tradiciones espirituales de pueblos aborígenes",
    "Caodaísmo: Religión vietnamita de carácter sincretista",
    "Tenrikyo: Movimiento religioso japonés de origen moderno",
    "Espiritismo: Corriente religiosa basada en comunicación con espíritus",
    "Rastafarismo: Movimiento religioso surgido en Jamaica",
    "Unitarios universalistas: Movimiento religioso de enfoque pluralista",
    "Mormonismo: Tradición cristiana vinculada a La Iglesia de Jesucristo de los Santos de los Últimos Días",
    "Testigos de Jehová: Movimiento religioso de interpretación bíblica particular",
    "Ciencia Cristiana: Movimiento religioso fundado por Mary Baker Eddy",
    "Nueva Era: Conjunto de espiritualidades modernas de carácter sincretista",
    "Neopaganismo: Recuperación moderna de tradiciones religiosas precristianas",
    "Wicca: Tradición neopagana de carácter ritual y dual",
    "Ateismo: Postura de negación de la existencia de deidades",
    "Agnosticismo: Postura sobre la imposibilidad o duda de conocer a Dios",
    "Humanismo secular: Visión ética no religiosa centrada en el ser humano",
    "Deismo: Creencia en un creador sin revelación religiosa particular",
    "Sin afiliación religiosa: Personas que no se identifican con una religión concreta",
})

grupos_biblicos = sorted({
    "Adoradores: Personas entregadas a alabar y honrar a Dios",
    "Agarenos: Pueblo mencionado en conflictos del Antiguo Testamento",
    "Amos de casa: Responsables del hogar en distintos relatos bíblicos",
    "Arqueros: Guerreros armados con arco en batallas bíblicas",
    "Asambleas: Reuniones del pueblo para escuchar la Ley o adorar",
    "Cantores: Ministros dedicados al canto en el templo",
    "Carceleros: Encargados de prisiones, como en el libro de Hechos",
    "Centuriones: Oficiales romanos mencionados varias veces en el Nuevo Testamento",
    "Concilios: Reuniones de líderes para tratar asuntos del pueblo o de la iglesia",
    "Consejeros: Personas que orientaban a reyes o líderes",
    "Constructores: Obreros implicados en murallas, ciudades o el templo",
    "Cortesanos: Servidores de palacio en reinos bíblicos",
    "Creyentes: Personas que han respondido con fe al mensaje de Dios",
    "Desterrados: Exiliados fuera de su tierra por juicio o guerra",
    "Doce tribus: Conjunto del pueblo de Israel descendiente de Jacob",
    "Doctores de la Ley: Expertos en la interpretación de la Ley mosaica",
    "Endemoniados: Personas oprimidas por espíritus malignos en los Evangelios",
    "Enfermos: Grupo frecuentemente atendido con compasión y milagros",
    "Exiliados: Pueblo llevado cautivo fuera de Israel y Judá",
    "Extranjeros: Personas de otras naciones presentes entre el pueblo",
    "Familias sacerdotales: Linajes apartados para el servicio del templo",
    "Guardianes de la puerta: Responsables del acceso y orden en el templo",
    "Hijas de Sión: Expresión poética para referirse al pueblo de Jerusalén",
    "Huérfanos: Grupo vulnerable protegido en la Ley y los profetas",
    "Jefes de millares: Líderes militares y administrativos de Israel",
    "Jóvenes: Grupo mencionado en exhortaciones, guerras y discipulado",
    "Jueces: Líderes levantados por Dios para gobernar y liberar a Israel",
    "Magos de Oriente: Sabios que visitaron a Jesús tras su nacimiento",
    "Mercaderes: Comerciantes presentes en ciudades y rutas bíblicas",
    "Mujeres estériles: Mujeres que vivieron la espera de un hijo con fe y dolor",
    "Murmuradores: Grupo que protesta contra Dios o sus siervos",
    "Nazareos: Personas consagradas a Dios mediante voto especial",
    "Nobles: Miembros influyentes del pueblo o de la corte",
    "Obreros: Trabajadores del campo, la construcción o la mies espiritual",
    "Ovejas perdidas: Imagen del pueblo descarriado necesitado de pastor",
    "Pastoreadores: Encargados de cuidar rebaños en la vida cotidiana bíblica",
    "Pecadores: Término frecuente para quienes necesitan arrepentimiento y gracia",
    "Peregrinos: Personas de paso o en viaje hacia lugares santos",
    "Pescadores: Oficio común en Galilea y entre varios discípulos",
    "Porteros: Servidores asignados al cuidado de entradas y espacios sagrados",
    "Presos: Personas encarceladas por delitos, injusticia o causa del Evangelio",
    "Prosélitos: Gentiles incorporados a la fe judía",
    "Recaudadores: Funcionarios que cobraban tributos e impuestos",
    "Rechazados: Personas marginadas social o religiosamente",
    "Reyes de la tierra: Gobernantes de naciones en pasajes históricos y proféticos",
    "Remanente: Grupo fiel preservado por Dios en tiempos de crisis",
    "Samaritanos piadosos: Referencia a quienes actúan con misericordia inesperada",
    "Siervas: Mujeres al servicio de hogares o familias",
    "Soldados: Militares presentes en historias del Antiguo y Nuevo Testamento",
    "Trabajadores de la mies: Imagen de quienes sirven en la obra de Dios",
    "Fariseos: Grupo religioso influyente en tiempos de Jesús",
    "Saduceos: Grupo sacerdotal y político del judaísmo",
    "Escribas: Intérpretes y maestros de la Ley",
    "Herodianos: Partidarios de la casa de Herodes",
    "Celotes: Movimiento judío de fuerte fervor nacional",
    "Esenios: Comunidad judía asociada a vida apartada",
    "Publicanos: Cobradores de impuestos en tiempos de Roma",
    "Levitas: Tribu dedicada al servicio del templo",
    "Sacerdotes: Encargados del culto en Israel",
    "Sumos sacerdotes: Máxima autoridad sacerdotal",
    "Sanedrin: Consejo religioso judío",
    "Discípulos: Seguidores y aprendices de Jesús",
    "Apóstoles: Enviados escogidos por Jesús",
    "Profetas: Portavoces del mensaje de Dios",
    "Gentiles: Pueblos no judíos",
    "Judios: Pueblo del pacto en tiempos bíblicos",
    "Helenistas: Judíos de lengua griega mencionados en Hechos",
    "Viudas: Grupo vulnerable atendido por la iglesia primitiva",
    "Diáconos: Servidores escogidos en la iglesia primitiva",
    "Ancianos: Líderes espirituales del pueblo o de la iglesia",
})


def crear_dropdown(label, items, default="Ninguno", expand=True, formatter=None, border_color=None, label_color=None, fill_color=None):
    opts = [ft.dropdown.Option(key=default, text=default)] + [
        ft.dropdown.Option(key=x, text=formatter(x) if formatter else x) for x in items
    ]
    return ft.Dropdown(
        label=label.upper(),
        options=opts,
        value=default,
        expand=expand,
        bgcolor=fill_color,
        border_color=border_color or "#FFC400",
        border_width=5,
        label_style=ft.TextStyle(color=label_color or "#C60B1E"),
    )


def mostrar_mensaje(page: ft.Page, texto: str):
    page.snack_bar = ft.SnackBar(ft.Text(texto))
    page.snack_bar.open = True
    page.update()


def _quitar_markdown_para_pdf(texto: str) -> str:
    texto_limpio = texto.replace("\r\n", "\n")
    texto_limpio = re.sub(r"```+", "", texto_limpio)
    texto_limpio = re.sub(r"^\s{0,3}#{1,6}\s*", "", texto_limpio, flags=re.MULTILINE)
    texto_limpio = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", texto_limpio)
    for token in ("**", "__", "`"):
        texto_limpio = texto_limpio.replace(token, "")
    texto_limpio = re.sub(r"(?<!\*)\*(?!\*)", "", texto_limpio)
    texto_limpio = re.sub(r"(?<!_)_(?!_)", "", texto_limpio)
    texto_limpio = re.sub(r"^\s*>\s?", "", texto_limpio, flags=re.MULTILINE)
    return texto_limpio.strip()


def _envolver_linea_pdf(linea: str, ancho: int = 92) -> list[str]:
    if not linea.strip():
        return [""]

    match = re.match(r"^(\s*(?:[-*]|\d+\.))\s+(.*)$", linea)
    if match:
        prefijo = f"{match.group(1)} "
        cuerpo = match.group(2)
        partes = textwrap.wrap(cuerpo, width=max(20, ancho - len(prefijo)), break_long_words=False, break_on_hyphens=False)
        if not partes:
            return [prefijo.rstrip()]
        return [prefijo + partes[0], *[(" " * len(prefijo)) + parte for parte in partes[1:]]]

    return textwrap.wrap(linea, width=ancho, break_long_words=False, break_on_hyphens=False) or [linea]


def _escapar_texto_pdf(texto: str) -> bytes:
    escapado = texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escapado.encode("cp1252", errors="replace")


def _crear_pdf_basico(ruta: Path, lineas: list[str]) -> None:
    max_lineas_por_pagina = 46
    paginas = [lineas[i:i + max_lineas_por_pagina] for i in range(0, len(lineas), max_lineas_por_pagina)] or [[""]]

    objetos: list[bytes] = []
    total_paginas = len(paginas)
    total_objetos = 3 + (total_paginas * 2)

    objetos.append(b"<< /Type /Catalog /Pages 2 0 R >>")

    kids = " ".join(f"{4 + indice * 2} 0 R" for indice in range(total_paginas))
    objetos.append(f"<< /Type /Pages /Kids [{kids}] /Count {total_paginas} >>".encode("ascii"))
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    for indice, pagina in enumerate(paginas):
        numero_pagina = 4 + indice * 2
        numero_contenido = numero_pagina + 1
        contenido = [b"BT", b"/F1 11 Tf", b"14 TL", b"50 790 Td"]
        primera = True
        for linea in pagina:
            if not primera:
                contenido.append(b"T*")
            primera = False
            if linea:
                contenido.append(b"(" + _escapar_texto_pdf(linea) + b") Tj")
        contenido.append(b"ET")
        stream = b"\n".join(contenido)
        objetos.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {numero_contenido} 0 R >>".encode("ascii")
        )
        objetos.append(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")

    buffer = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for indice, objeto in enumerate(objetos, start=1):
        offsets.append(len(buffer))
        buffer.extend(f"{indice} 0 obj\n".encode("ascii"))
        buffer.extend(objeto)
        buffer.extend(b"\nendobj\n")

    inicio_xref = len(buffer)
    buffer.extend(f"xref\n0 {total_objetos + 1}\n".encode("ascii"))
    buffer.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.extend(
        f"trailer\n<< /Size {total_objetos + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF".encode("ascii")
    )
    ruta.write_bytes(buffer)


def _slug_para_nombre_archivo(texto: str, max_len: int = 60) -> str:
    normalizado = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    limpio = re.sub(r"[^a-zA-Z0-9]+", "_", normalizado.lower()).strip("_")
    limpio = re.sub(r"_+", "_", limpio)
    return (limpio[:max_len].strip("_") or "resultado")


def pantalla_principal(page: ft.Page, idioma="es", on_volver=None, inicio="biblia", on_volver_inicio=None):
    lang = get_language_config(idioma)
    theme = get_language_theme(idioma)
    ui = lang["ui"]
    versiones_biblia = lang["bible_versions"]
    none_option = ui["none"]
    no_selection = ui["no_selection"]
    only_verses = ui["only_verses"]
    lang_code = lang["code"]

    clear_question_label = {
        "es": "BORRAR",
        "ca": "ESBORRAR",
        "fr": "EFFACER",
        "en": "CLEAR",
    }.get(lang_code, "CLEAR")
    back_step_label = ui["back_step"]
    back_start_label = ui["back_to_start"]
    generating_text = {
        "es": "_Generando..._",
        "ca": "_Generant..._",
        "fr": "_Generation..._",
        "en": "_Generating..._",
    }.get(lang_code, "_Generating..._")
    repeating_text = {
        "es": "_Repitiendo última consulta..._",
        "ca": "_Repetint l'última consulta..._",
        "fr": "_Répétition de la dernière requête..._",
        "en": "_Repeating last query..._",
    }.get(lang_code, "_Repeating last query..._")
    asking_text = {
        "es": "_Consultando a la IA..._",
        "ca": "_Consultant la IA..._",
        "fr": "_Consultation de l'IA..._",
        "en": "_Consulting AI..._",
    }.get(lang_code, "_Consulting AI..._")
    texto_filtro_sin_activo = {
        "es": "Filtro activo: ninguno",
        "ca": "Filtre actiu: cap",
        "fr": "Filtre actif : aucun",
        "en": "Active filter: none",
    }.get(lang_code, "Active filter: none")
    texto_filtro_tema = {
        "es": "Filtro activo: sugerencias del tema",
        "ca": "Filtre actiu: suggeriments del tema",
        "fr": "Filtre actif : suggestions de theme",
        "en": "Active filter: topic suggestions",
    }.get(lang_code, "Active filter: topic suggestions")
    texto_filtro_pasaje = {
        "es": "Filtro activo: pasaje bíblico",
        "ca": "Filtre actiu: passatge biblic",
        "fr": "Filtre actif : passage biblique",
        "en": "Active filter: Bible passage",
    }.get(lang_code, "Active filter: Bible passage")
    texto_filtro_prefijo = {
        "es": "Filtro activo",
        "ca": "Filtre actiu",
        "fr": "Filtre actif",
        "en": "Active filter",
    }.get(lang_code, "Active filter")
    resumen_vacio = {
        "es": "sin selección",
        "ca": "sense selecció",
        "fr": "sans sélection",
        "en": "no selection",
    }.get(lang_code, "no selection")
    resumen_prefijo = {
        "es": "Resumen",
        "ca": "Resum",
        "fr": "Resume",
        "en": "Summary",
    }.get(lang_code, "Summary")
    resumen_labels = {
        "es": {"filter": "Filtro", "book": "Libro", "passage": "Pasaje", "type": "Tipo", "topic": "Tema"},
        "ca": {"filter": "Filtre", "book": "Llibre", "passage": "Passatge", "type": "Tipus", "topic": "Tema"},
        "fr": {"filter": "Filtre", "book": "Livre", "passage": "Passage", "type": "Type", "topic": "Theme"},
        "en": {"filter": "Filter", "book": "Book", "passage": "Passage", "type": "Type", "topic": "Topic"},
    }.get(lang_code, {"filter": "Filter", "book": "Book", "passage": "Passage", "type": "Type", "topic": "Topic"})
    contexto_activo_titulo = {
        "es": "CONTEXTO ACTIVO",
        "ca": "CONTEXT ACTIU",
        "fr": "CONTEXTE ACTIF",
        "en": "ACTIVE CONTEXT",
    }.get(lang_code, "ACTIVE CONTEXT")
    contexto_activo_labels = {
        "es": {"topic": "Tema", "character": "Personaje", "group": "Grupo", "people": "Pueblo", "place": "Lugar", "religion": "Religion", "passage": "Pasaje"},
        "ca": {"topic": "Tema", "character": "Personatge", "group": "Grup", "people": "Poble", "place": "Lloc", "religion": "Religio", "passage": "Passatge"},
        "fr": {"topic": "Theme", "character": "Personnage", "group": "Groupe", "people": "Peuple", "place": "Lieu", "religion": "Religion", "passage": "Passage"},
        "en": {"topic": "Topic", "character": "Character", "group": "Group", "people": "People", "place": "Place", "religion": "Religion", "passage": "Passage"},
    }.get(
        lang_code,
        {"topic": "Topic", "character": "Character", "group": "Group", "people": "People", "place": "Place", "religion": "Religion", "passage": "Passage"},
    )
    study_type_labels = {
        "Solo versiculos": only_verses,
        "Estudio informativo": ui["study_info"],
        "Estudio versiculos": ui["verse_study"],
        "Reflexion biblica": ui["biblical_reflection"],
        "Aplicacion practica": ui["practical_application"],
        "Bosquejo para predicar": ui["sermon_outline"],
        "Devocional breve": ui["brief_devotional"],
        "Analisis exegetico": {
            "es": "Analisis exegetico",
            "ca": "Analisi exegetica",
            "fr": "Analyse exegetique",
            "en": "Exegetical analysis",
        }.get(lang_code, "Analisis exegetico"),
        "Analisis hermeneutico": {
            "es": "Analisis hermeneutico",
            "ca": "Analisi hermeneutica",
            "fr": "Analyse hermeneutique",
            "en": "Hermeneutical analysis",
        }.get(lang_code, "Analisis hermeneutico"),
        "Analisis literario": {
            "es": "Analisis literario",
            "ca": "Analisi literaria",
            "fr": "Analyse litteraire",
            "en": "Literary analysis",
        }.get(lang_code, "Analisis literario"),
        "Analisis geografico politico": {
            "es": "Analisis geografico y politico",
            "ca": "Analisi geografic i politic",
            "fr": "Analyse geographique et politique",
            "en": "Geographic and political analysis",
        }.get(lang_code, "Analisis geografico y politico"),
        "Analisis estructura social": {
            "es": "Analisis de estructura social",
            "ca": "Analisi d'estructura social",
            "fr": "Analyse de structure sociale",
            "en": "Social structure analysis",
        }.get(lang_code, "Analisis de estructura social"),
        "Analisis vida cotidiana": {
            "es": "Analisis de vida cotidiana y costumbres",
            "ca": "Analisi de vida quotidiana i costums",
            "fr": "Analyse de la vie quotidienne et des coutumes",
            "en": "Daily life and customs analysis",
        }.get(lang_code, "Analisis de vida cotidiana y costumbres"),
        "Analisis contexto": {
            "es": "Analisis del contexto (mundo del texto)",
            "ca": "Analisi del context (mon del text)",
            "fr": "Analyse du contexte (monde du texte)",
            "en": "Context analysis (world of the text)",
        }.get(lang_code, "Analisis del contexto (mundo del texto)"),
    }
    study_type_descriptions = {
        "Ninguno": "",
        "Solo versiculos": {
            "es": "Muestra solo el texto bíblico del pasaje, sin análisis ni aplicación.",
            "ca": "Mostra només el text bíblic del passatge, sense anàlisi ni aplicació.",
            "fr": "Affiche uniquement le texte biblique du passage, sans analyse ni application.",
            "en": "Shows only the Bible text of the passage, with no analysis or application.",
        }.get(lang_code, "Shows only the Bible text of the passage, with no analysis or application."),
        "Estudio informativo": {
            "es": "Explica el pasaje con contexto, significado principal y enseñanzas clave.",
            "ca": "Explica el passatge amb context, significat principal i ensenyaments clau.",
            "fr": "Explique le passage avec son contexte, son sens principal et ses enseignements clefs.",
            "en": "Explains the passage with context, main meaning, and key teachings.",
        }.get(lang_code, "Explains the passage with context, main meaning, and key teachings."),
        "Estudio versiculos": {
            "es": "Analiza versículo por versículo para destacar ideas, doctrina y aplicación.",
            "ca": "Analitza versicle per versicle per destacar idees, doctrina i aplicació.",
            "fr": "Analyse verset par verset pour souligner idees, doctrine et application.",
            "en": "Analyzes verse by verse to highlight ideas, doctrine, and application.",
        }.get(lang_code, "Analyzes verse by verse to highlight ideas, doctrine, and application."),
        "Reflexion biblica": {
            "es": "Ofrece una reflexión espiritual breve para meditar y orar.",
            "ca": "Ofereix una reflexió espiritual breu per meditar i pregar.",
            "fr": "Propose une brève réflexion spirituelle pour méditer et prier.",
            "en": "Offers a short spiritual reflection for meditation and prayer.",
        }.get(lang_code, "Offers a short spiritual reflection for meditation and prayer."),
        "Aplicacion practica": {
            "es": "Conecta el pasaje con decisiones y acciones concretas para hoy.",
            "ca": "Connecta el passatge amb decisions i accions concretes per avui.",
            "fr": "Relie le passage à des décisions et actions concrètes pour aujourd'hui.",
            "en": "Connects the passage to concrete decisions and actions for today.",
        }.get(lang_code, "Connects the passage to concrete decisions and actions for today."),
        "Bosquejo para predicar": {
            "es": "Genera un bosquejo de predicación con puntos, texto base y cierre.",
            "ca": "Genera un esquema de predicació amb punts, text base i tancament.",
            "fr": "Génère un plan de prédication avec points, texte de base et conclusion.",
            "en": "Generates a preaching outline with points, base text, and conclusion.",
        }.get(lang_code, "Generates a preaching outline with points, base text, and conclusion."),
        "Devocional breve": {
            "es": "Crea un devocional corto con verdad central y aplicación personal.",
            "ca": "Crea un devocional curt amb veritat central i aplicació personal.",
            "fr": "Crée un court dévotionnel avec vérité centrale et application personnelle.",
            "en": "Creates a short devotional with a central truth and personal application.",
        }.get(lang_code, "Creates a short devotional with a central truth and personal application."),
        "Analisis exegetico": {
            "es": "Estudia el sentido original del texto con enfoque histórico, literario y teológico.",
            "ca": "Estudia el sentit original del text amb enfocament històric, literari i teològic.",
            "fr": "Étudie le sens original du texte avec un angle historique, littéraire et théologique.",
            "en": "Studies the original meaning of the text with historical, literary, and theological focus.",
        }.get(lang_code, "Studies the original meaning of the text with historical, literary, and theological focus."),
        "Analisis hermeneutico": {
            "es": "Interpreta el texto desde su contexto y lo conecta correctamente con la actualidad.",
            "ca": "Interpreta el text des del seu context i el connecta correctament amb l'actualitat.",
            "fr": "Interprète le texte depuis son contexte et le relie correctement à aujourd'hui.",
            "en": "Interprets the text from its context and connects it properly to today.",
        }.get(lang_code, "Interprets the text from its context and connects it properly to today."),
        "Analisis literario": {
            "es": "Examina estructura, género, recursos literarios y énfasis del autor.",
            "ca": "Examina estructura, gènere, recursos literaris i èmfasi de l'autor.",
            "fr": "Examine la structure, le genre, les ressources littéraires et l'emphase de l'auteur.",
            "en": "Examines structure, genre, literary devices, and author emphasis.",
        }.get(lang_code, "Examines structure, genre, literary devices, and author emphasis."),
        "Analisis geografico politico": {
            "es": "Analiza cómo geografía, poder político y contexto social influyen en el pasaje.",
            "ca": "Analitza com geografia, poder polític i context social influeixen en el passatge.",
            "fr": "Analyse comment la géographie, le pouvoir politique et le contexte social influencent le passage.",
            "en": "Analyzes how geography, political power, and social context shape the passage.",
        }.get(lang_code, "Analyzes how geography, political power, and social context shape the passage."),
        "Analisis estructura social": {
            "es": "Estudia jerarquías, honor/vergüenza, pureza ritual y relaciones sociales bíblicas.",
            "ca": "Estudia jerarquies, honor/vergonya, puresa ritual i relacions socials bíbliques.",
            "fr": "Étudie les hiérarchies, l'honneur/honte, la pureté rituelle et les relations sociales bibliques.",
            "en": "Studies hierarchies, honor/shame, ritual purity, and biblical social relations.",
        }.get(lang_code, "Studies hierarchies, honor/shame, ritual purity, and biblical social relations."),
        "Analisis vida cotidiana": {
            "es": "Explica costumbres familiares, hospitalidad y vida diaria para entender mejor el texto.",
            "ca": "Explica costums familiars, hospitalitat i vida diària per entendre millor el text.",
            "fr": "Explique les coutumes familiales, l'hospitalité et la vie quotidienne pour mieux comprendre le texte.",
            "en": "Explains family customs, hospitality, and daily life to better understand the text.",
        }.get(lang_code, "Explains family customs, hospitality, and daily life to better understand the text."),
        "Analisis contexto": {
            "es": "Profundiza en contexto histórico, literario y cultural antes de aplicar el pasaje.",
            "ca": "Aprofundeix en context històric, literari i cultural abans d'aplicar el passatge.",
            "fr": "Approfondit le contexte historique, littéraire et culturel avant d'appliquer le passage.",
            "en": "Deepens historical, literary, and cultural context before applying the passage.",
        }.get(lang_code, "Deepens historical, literary, and cultural context before applying the passage."),
    }

    def crear_opcion_tipo(key: str, text: str):
        descripcion = study_type_descriptions.get(key, "")
        if key == "Ninguno":
            descripcion = {
                "es": "Sin tipo de estudio seleccionado.",
                "ca": "Sense tipus d'estudi seleccionat.",
                "fr": "Aucun type d'etude selectionne.",
                "en": "No study type selected.",
            }.get(lang_code, "No study type selected.")
        texto_visible = text
        if key != "Ninguno" and descripcion:
            descripcion_corta = descripcion if len(descripcion) <= 90 else (descripcion[:87] + "...")
            texto_visible = f"{text} - {descripcion_corta}"
        return ft.dropdown.Option(key=key, text=texto_visible, tooltip=descripcion)
    book_translations = {
        "ca": {
            "Genesis": "Genesis", "Exodo": "Exode", "Levitico": "Levitic", "Numeros": "Nombres", "Deuteronomio": "Deuteronomi",
            "Josue": "Josue", "Jueces": "Jutges", "Rut": "Rut", "1 Samuel": "1 Samuel", "2 Samuel": "2 Samuel",
            "1 Reyes": "1 Reis", "2 Reyes": "2 Reis", "1 Cronicas": "1 Croniques", "2 Cronicas": "2 Croniques",
            "Esdras": "Esdres", "Nehemias": "Nehemies", "Ester": "Ester", "Job": "Job", "Salmos": "Salmes",
            "Proverbios": "Proverbis", "Eclesiastes": "Eclesiastes", "Cantares": "Cantics", "Isaias": "Isaias",
            "Jeremias": "Jeremies", "Lamentaciones": "Lamentacions", "Ezequiel": "Ezequiel", "Daniel": "Daniel",
            "Oseas": "Osees", "Joel": "Joel", "Amos": "Amos", "Abdias": "Abdies", "Jonas": "Jonas", "Miqueas": "Miquees",
            "Nahum": "Nahum", "Habacuc": "Habacuc", "Sofonias": "Sofonies", "Hageo": "Ageu", "Zacarias": "Zacaries",
            "Malaquias": "Malaquies", "Mateo": "Mateu", "Marcos": "Marc", "Lucas": "Lluc", "Juan": "Joan",
            "Hechos": "Fets", "Romanos": "Romans", "1 Corintios": "1 Corintis", "2 Corintios": "2 Corintis",
            "Galatas": "Galates", "Efesios": "Efesis", "Filipenses": "Filipencs", "Colosenses": "Colossencs",
            "1 Tesalonicenses": "1 Tessalonicencs", "2 Tesalonicenses": "2 Tessalonicencs", "1 Timoteo": "1 Timoteu",
            "2 Timoteo": "2 Timoteu", "Tito": "Titus", "Filemon": "Filemo", "Hebreos": "Hebreus", "Santiago": "Jaume",
            "1 Pedro": "1 Pere", "2 Pedro": "2 Pere", "1 Juan": "1 Joan", "2 Juan": "2 Joan", "3 Juan": "3 Joan",
            "Judas": "Judes", "Apocalipsis": "Apocalipsi",
        },
        "fr": {
            "Genesis": "Genese", "Exodo": "Exode", "Levitico": "Levitique", "Numeros": "Nombres", "Deuteronomio": "Deuteronome",
            "Josue": "Josue", "Jueces": "Juges", "Rut": "Ruth", "1 Samuel": "1 Samuel", "2 Samuel": "2 Samuel",
            "1 Reyes": "1 Rois", "2 Reyes": "2 Rois", "1 Cronicas": "1 Chroniques", "2 Cronicas": "2 Chroniques",
            "Esdras": "Esdras", "Nehemias": "Nehemie", "Ester": "Esther", "Job": "Job", "Salmos": "Psaumes",
            "Proverbios": "Proverbes", "Eclesiastes": "Ecclesiaste", "Cantares": "Cantique des cantiques", "Isaias": "Esaie",
            "Jeremias": "Jeremie", "Lamentaciones": "Lamentations", "Ezequiel": "Ezechiel", "Daniel": "Daniel",
            "Oseas": "Osee", "Joel": "Joel", "Amos": "Amos", "Abdias": "Abdias", "Jonas": "Jonas", "Miqueas": "Michee",
            "Nahum": "Nahum", "Habacuc": "Habacuc", "Sofonias": "Sophonie", "Hageo": "Aggee", "Zacarias": "Zacharie",
            "Malaquias": "Malachie", "Mateo": "Matthieu", "Marcos": "Marc", "Lucas": "Luc", "Juan": "Jean",
            "Hechos": "Actes", "Romanos": "Romains", "1 Corintios": "1 Corinthiens", "2 Corintios": "2 Corinthiens",
            "Galatas": "Galates", "Efesios": "Ephesiens", "Filipenses": "Philippiens", "Colosenses": "Colossiens",
            "1 Tesalonicenses": "1 Thessaloniciens", "2 Tesalonicenses": "2 Thessaloniciens", "1 Timoteo": "1 Timothee",
            "2 Timoteo": "2 Timothee", "Tito": "Tite", "Filemon": "Philemon", "Hebreos": "Hebreux", "Santiago": "Jacques",
            "1 Pedro": "1 Pierre", "2 Pedro": "2 Pierre", "1 Juan": "1 Jean", "2 Juan": "2 Jean", "3 Juan": "3 Jean",
            "Judas": "Jude", "Apocalipsis": "Apocalypse",
        },
        "en": {
            "Genesis": "Genesis", "Exodo": "Exodus", "Levitico": "Leviticus", "Numeros": "Numbers", "Deuteronomio": "Deuteronomy",
            "Josue": "Joshua", "Jueces": "Judges", "Rut": "Ruth", "1 Samuel": "1 Samuel", "2 Samuel": "2 Samuel",
            "1 Reyes": "1 Kings", "2 Reyes": "2 Kings", "1 Cronicas": "1 Chronicles", "2 Cronicas": "2 Chronicles",
            "Esdras": "Ezra", "Nehemias": "Nehemiah", "Ester": "Esther", "Job": "Job", "Salmos": "Psalms",
            "Proverbios": "Proverbs", "Eclesiastes": "Ecclesiastes", "Cantares": "Song of Songs", "Isaias": "Isaiah",
            "Jeremias": "Jeremiah", "Lamentaciones": "Lamentations", "Ezequiel": "Ezekiel", "Daniel": "Daniel",
            "Oseas": "Hosea", "Joel": "Joel", "Amos": "Amos", "Abdias": "Obadiah", "Jonas": "Jonah", "Miqueas": "Micah",
            "Nahum": "Nahum", "Habacuc": "Habakkuk", "Sofonias": "Zephaniah", "Hageo": "Haggai", "Zacarias": "Zechariah",
            "Malaquias": "Malachi", "Mateo": "Matthew", "Marcos": "Mark", "Lucas": "Luke", "Juan": "John",
            "Hechos": "Acts", "Romanos": "Romans", "1 Corintios": "1 Corinthians", "2 Corintios": "2 Corinthians",
            "Galatas": "Galatians", "Efesios": "Ephesians", "Filipenses": "Philippians", "Colosenses": "Colossians",
            "1 Tesalonicenses": "1 Thessalonians", "2 Tesalonicenses": "2 Thessalonians", "1 Timoteo": "1 Timothy",
            "2 Timoteo": "2 Timothy", "Tito": "Titus", "Filemon": "Philemon", "Hebreos": "Hebrews", "Santiago": "James",
            "1 Pedro": "1 Peter", "2 Pedro": "2 Peter", "1 Juan": "1 John", "2 Juan": "2 John", "3 Juan": "3 John",
            "Judas": "Jude", "Apocalipsis": "Revelation",
        },
    }
    entity_translations = {
        "ca": {
            "Dios": "Deu", "Senor": "Senyor", "Espiritu Santo": "Esperit Sant", "Cristo": "Crist",
            "Jesus": "Jesus", "Jesucristo": "Jesucrist", "Maria": "Maria", "Maria Magdalena": "Maria Magdalena",
            "Juan el Bautista": "Joan Baptista", "Pablo": "Pau", "Pedro": "Pere", "Santiago": "Jaume",
            "Andres": "Andreu", "Felipe": "Felip", "Lucas": "Lluc", "Marcos": "Marc", "Mateo": "Mateu",
            "Jose": "Josep", "Jose de Arimatea": "Josep d'Arimatea", "Moises": "Moises", "Elias": "Elies",
            "Eliseo": "Eliseu", "Isaias": "Isaias", "Jeremias": "Jeremies", "Oseas": "Osees", "Miqueas": "Miquees",
            "Zacarias": "Zacaries", "Malaquias": "Malaquies", "Juda": "Juda", "Judea": "Judea", "Jerusalen": "Jerusalem",
            "Belen": "Betlem", "Nazaret": "Nazaret", "Egipto": "Egipte", "Roma": "Roma", "Galilea": "Galilea",
            "Samaria": "Samaria", "Jerico": "Jerico", "Babilonia": "Babilonia", "Damasco": "Damasc",
            "Corinto": "Corint", "Filipos": "Filips", "Macedonia": "Macedonia", "Atenas": "Atenes",
            "Monte de los Olivos": "Muntanya de les Oliveres", "Templo": "Temple", "Evangelio": "Evangeli",
            "Ley": "Llei", "Escritura": "Escriptura", "Biblia": "Biblia", "iglesia": "esglesia",
        },
        "fr": {
            "Dios": "Dieu", "Senor": "Seigneur", "Espiritu Santo": "Saint-Esprit", "Cristo": "Christ",
            "Jesus": "Jesus", "Jesucristo": "Jesus-Christ", "Maria": "Marie", "Maria Magdalena": "Marie Madeleine",
            "Juan el Bautista": "Jean-Baptiste", "Pablo": "Paul", "Pedro": "Pierre", "Santiago": "Jacques",
            "Andres": "Andre", "Felipe": "Philippe", "Lucas": "Luc", "Marcos": "Marc", "Mateo": "Matthieu",
            "Jose": "Joseph", "Jose de Arimatea": "Joseph d'Arimathee", "Moises": "Moise", "Elias": "Elie",
            "Eliseo": "Elisee", "Isaias": "Esaie", "Jeremias": "Jeremie", "Oseas": "Osee", "Miqueas": "Michee",
            "Zacarias": "Zacharie", "Malaquias": "Malachie", "Juda": "Juda", "Judea": "Judee", "Jerusalen": "Jerusalem",
            "Belen": "Bethleem", "Nazaret": "Nazareth", "Egipto": "Egypte", "Roma": "Rome", "Galilea": "Galilee",
            "Samaria": "Samarie", "Jerico": "Jericho", "Babilonia": "Babylone", "Damasco": "Damas",
            "Corinto": "Corinthe", "Filipos": "Philippes", "Macedonia": "Macedoine", "Atenas": "Athenes",
            "Monte de los Olivos": "Mont des Oliviers", "Templo": "Temple", "Evangelio": "Evangile",
            "Ley": "Loi", "Escritura": "Ecriture", "Biblia": "Bible", "iglesia": "eglise",
        },
        "en": {
            "Dios": "God", "Senor": "Lord", "Espiritu Santo": "Holy Spirit", "Cristo": "Christ",
            "Jesus": "Jesus", "Jesucristo": "Jesus Christ", "Maria": "Mary", "Maria Magdalena": "Mary Magdalene",
            "Juan el Bautista": "John the Baptist", "Pablo": "Paul", "Pedro": "Peter", "Santiago": "James",
            "Andres": "Andrew", "Felipe": "Philip", "Lucas": "Luke", "Marcos": "Mark", "Mateo": "Matthew",
            "Jose": "Joseph", "Jose de Arimatea": "Joseph of Arimathea", "Moises": "Moses", "Elias": "Elijah",
            "Eliseo": "Elisha", "Isaias": "Isaiah", "Jeremias": "Jeremiah", "Oseas": "Hosea", "Miqueas": "Micah",
            "Zacarias": "Zechariah", "Malaquias": "Malachi", "Juda": "Judah", "Judea": "Judea", "Jerusalen": "Jerusalem",
            "Belen": "Bethlehem", "Nazaret": "Nazareth", "Egipto": "Egypt", "Roma": "Rome", "Galilea": "Galilee",
            "Samaria": "Samaria", "Jerico": "Jericho", "Babilonia": "Babylon", "Damasco": "Damascus",
            "Corinto": "Corinth", "Filipos": "Philippi", "Macedonia": "Macedonia", "Atenas": "Athens",
            "Monte de los Olivos": "Mount of Olives", "Templo": "Temple", "Evangelio": "Gospel",
            "Ley": "Law", "Escritura": "Scripture", "Biblia": "Bible", "iglesia": "church",
        },
    }

    common_replacements = {
        "ca": [
            ("Personas que ", "Persones que "),
            ("Persona que ", "Qui "),
            ("sumo sacerdote", "gran sacerdot"),
            ("sacerdote", "sacerdot"),
            ("profetisa", "profetessa"),
            ("Movimiento religioso", "Moviment religios"),
            ("Religion ", "Religio "),
            ("Tradicion ", "Tradicio "),
            ("Tradiciones ", "Tradicions "),
            ("Corriente ", "Corrent "),
            ("Conjunto de ", "Conjunt de "),
            ("Fe basada en ", "Fe fonamentada en "),
            ("basada en", "fonamentada en"),
            ("fundada en", "nascuda a"),
            ("fundado en", "fundat en"),
            ("centrada en", "focalitzada en"),
            ("centrado en", "centrat en"),
            ("originada en", "originada a"),
            ("originado en", "originat a"),
            ("hijo de ", "fill de "),
            ("hija de ", "filla de "),
            ("hermano de ", "germa de "),
            ("hermana de ", "germana de "),
            ("esposa de ", "esposa de "),
            ("esposo de ", "espos de "),
            ("madre de ", "mare de "),
            ("padre de ", "pare de "),
            ("rey de ", "rei de "),
            ("reina de ", "reina de "),
            ("siervo de ", "servent de "),
            ("sierva de ", "serventa de "),
            ("discipulo de ", "deixeble de "),
            ("discipula de ", "deixebla de "),
            ("compañero del apostol Pablo", "company de l'apostol Pau"),
            ("colaborador del apostol Pablo", "col.laborador de l'apostol Pau"),
            ("colaborador de Pablo", "col.laborador de Pau"),
            ("el padre de la fe", "el pare de la fe"),
            ("judío elocuente y poderoso en las Escrituras", "jueu eloqüent i poderós en les Escriptures"),
            ("cantor y salmista", "cantor i salmista"),
            ("nombre de varios personajes bíblicos", "nom de diversos personatges bíblics"),
            ("el ciego que recibió la vista", "el cec que va recuperar la vista"),
            ("uno de los doce espías", "un dels dotze espies"),
            ("principal de la sinagoga", "cap de la sinagoga"),
            ("siervo etíope que ayudó a Jeremías", "servent etíop que va ajudar Jeremies"),
            ("libertador de Israel", "alliberador d'Israel"),
            ("séptimo desde Adán", "setè des d'Adam"),
            ("nieto de Aarón", "net d'Aaron"),
            ("maestro de la Ley entre los fariseos", "mestre de la Llei entre els fariseus"),
            ("sabio y cantor", "savi i cantor"),
            ("descendiente de Sem", "descendent de Sem"),
            ("gitita leal a David", "guitita fidel a David"),
            ("hombre de oración", "home d'oració"),
            ("general del ejército de David", "general de l'exèrcit de David"),
            ("sobrino de David", "nebot de David"),
            ("nombre de varios reyes bíblicos", "nom de diversos reis bíblics"),
            ("discípulo secreto que dio su sepulcro a Jesús", "deixeble secret que va cedir el seu sepulcre a Jesús"),
            ("suegro de Jacob", "sogre de Jacob"),
            ("hombre longevo del Antiguo Testamento", "home longeu de l'Antic Testament"),
            ("primo de Ester", "cosí d'Ester"),
            ("elegido entre los doce", "escollit entre els dotze"),
            ("porcio festo fue el procurador romano de Judea", "Porci Fest va ser el procurador romà de Judea"),
            ("profeta en tiempos de Acab", "profeta en temps d'Acab"),
            ("reconstruyó los muros de Jerusalén", "va reconstruir les muralles de Jerusalem"),
            ("fariseo, principal entre los judíos", "fariseu, principal entre els jueus"),
            ("abuelo de David", "avi de David"),
            ("saulo de Tarso", "Saule de Tars"),
            ("uno de los siete servidores", "un dels set servidors"),
            ("variante de Silas en algunas traducciones", "variant de Silas en algunes traduccions"),
            ("acompañante del apóstol Pablo", "company de l'apòstol Pau"),
            ("llevó la cruz de Jesús", "va portar la creu de Jesús"),
            ("anciano que vio al Mesías", "ancià que va veure el Messies"),
            ("nombre de varios personajes pos-exilio", "nom de diversos personatges del postexili"),
            ("el discípulo incrédulo", "el deixeble incrèdul"),
            ("nombre de varios levitas", "nom de diversos levites"),
            ("creyente mencionada por Pablo", "creient esmentada per Pau"),
            ("creyente mencionado por Pablo", "creient esmentat per Pau"),
            ("gobernador romano", "governador romà"),
            ("centurion romano", "centurió romà"),
            ("recaudador de impuestos", "recaptador d'impostos"),
            ("jefe de publicanos", "cap de publicans"),
            ("descendiente de Adán", "descendent d'Adam"),
            ("Descendiente de Adán", "Descendent d'Adam"),
            ("el apóstol", "l'apòstol"),
            ("El apóstol", "L'apòstol"),
            ("el bautista", "el Baptista"),
            ("El bautista", "El Baptista"),
            ("el de los diez mandamientos", "el dels deu manaments"),
            ("El de los diez mandamientos", "El dels deu manaments"),
            ("el del arca", "el de l'arca"),
            ("El del arca", "El de l'arca"),
            ("el del pozo de los leones", "el del fossat dels lleons"),
            ("El del pozo de los leones", "El del fossat dels lleons"),
            ("el evangelista", "l'evangelista"),
            ("El evangelista", "L'evangelista"),
            ("el profeta", "profeta"),
            ("El profeta", "Profeta"),
            ("gobernador de Judá", "governador de Judà"),
            ("Gobernador de Judá", "Governador de Judà"),
            ("principal de la sinagoga", "cap de la sinagoga"),
            ("Principal de la sinagoga", "Cap de la sinagoga"),
            ("sobrino de Abraham", "nebot d'Abraham"),
            ("Sobrino de Abraham", "Nebot d'Abraham"),
            ("mujer mencionada en genealogias", "dona esmentada en genealogies"),
            ("hombre temeroso de Dios", "home temorenc de Deu"),
            ("juez de Israel", "jutge d'Israel"),
            ("rey David", "rei David"),
            ("rey Salomon", "rei Salomó"),
            ("profeta", "profeta"),
            ("evangelista", "evangelista"),
            ("apostol", "apòstol"),
            ("seguidora de Jesus", "deixebla de Jesús"),
            ("seguidor de Jesus", "deixeble de Jesús"),
            ("madre de Jesus", "mare de Jesús"),
            ("madre del profeta Samuel", "mare del profeta Samuel"),
            ("madre de Juan el bautista", "mare de Joan Baptista"),
            ("madre de Timoteo", "mare de Timoteu"),
            ("madre de Moises", "mare de Moisès"),
            ("esposa del rey David", "dona del rei David"),
            ("esposa del rey Acab", "dona del rei Acab"),
            ("esposa del rey Asuero", "dona del rei Assuer"),
            ("esposa del rey Ezequias", "dona del rei Ezequies"),
            ("esposa del gobernador Felix", "dona del governador Fèlix"),
            ("esposa del profeta Oseas", "dona del profeta Osees"),
            ("esposa de Aaron", "dona d'Aaron"),
            ("esposa de Jose", "dona de Josep"),
            ("esposa de Abraham", "dona d'Abraham"),
            ("Esposa de Abraham", "Dona d'Abraham"),
            ("esposa de Isaac", "dona d'Isaac"),
            ("Esposa de Isaac", "Dona d'Isaac"),
            ("esposa de Jacob", "dona de Jacob"),
            ("Esposa de Jacob", "Dona de Jacob"),
            ("esposa de Aquila", "dona d'Aquila"),
            ("Esposa de Aquila", "Dona d'Aquila"),
            ("esposa de Booz", "dona de Booz"),
            ("Esposa de Booz", "Dona de Booz"),
            ("esposa de Ananias", "dona d'Ananies"),
            ("Esposa de Ananías", "Dona d'Ananies"),
            ("esposa de Job", "dona de Job"),
            ("Esposa de Job", "Dona de Job"),
            ("esposa de Adan", "dona d'Adam"),
            ("Esposa de Adán", "Dona d'Adam"),
            ("esposa de David", "dona de David"),
            ("Esposa de David", "Dona de David"),
            ("esposa de Lamec", "dona de Lamec"),
            ("Esposa de Lamec", "Dona de Lamec"),
            ("esposa de Moises", "dona de Moisès"),
            ("Esposa de Moisés", "Dona de Moisès"),
            ("madre de Jesus de Nazaret", "mare de Jesús de Natzaret"),
            ("madre de Juan Marcos", "mare de Joan Marc"),
            ("madre del rey Josias", "mare del rei Josies"),
            ("madre de Sanson", "mare de Samsó"),
            ("hija del rey Acab y de la reina Jezabel", "filla del rei Acab i de la reina Jezabel"),
            ("hija del rey Joram", "filla del rei Joram"),
            ("hija de Saul", "filla de Saül"),
            ("hija de Jacob", "filla de Jacob"),
            ("hija de Caleb", "filla de Caleb"),
            ("hija de Job", "filla de Job"),
            ("hija de Zelofehad", "filla de Selofhad"),
            ("una de las hijas de Zelofehad", "una de les filles de Selofhad"),
            ("hija de Herodias", "filla d'Herodies"),
            ("mujer madianita", "dona madianita"),
            ("mujer de Sanson", "dona de Samsó"),
            ("mujer de Elcana", "dona d'Elcanà"),
            ("creyente de Atenas", "creient d'Atenes"),
            ("esposa de Urias el heteo", "dona d'Uries l'heteu"),
            ("una de las esposas de David", "una de les dones de David"),
            ("figura simbolica en Ezequiel", "figura simbòlica a Ezequiel"),
            ("una de las parteras hebreas", "una de les llevadores hebrees"),
            ("toco el manto de Jesus", "va tocar el mantell de Jesus"),
            ("joven que sirvió al rey David", "jove que va servir el rei David"),
            ("la profetisa hija de Fanuel", "la profetessa, filla de Fanuel"),
            ("nombre de varias mujeres del Antiguo Testamento", "nom de diverses dones de l'Antic Testament"),
            ("nombre de varias mujeres bíblicas", "nom de diverses dones bíbliques"),
            ("cristiana cercana a Pablo", "cristiana propera a Pau"),
            ("diaconisa de la iglesia", "diaconessa de l'església"),
            ("nombre hebreo de Ester", "nom hebreu d'Ester"),
            ("madre de reyes de Judá", "mare de reis de Judà"),
            ("reina de Etiopía", "reina d'Etiòpia"),
            ("mujer vinculada a la muerte de Juan el Bautista", "dona vinculada a la mort de Joan Baptista"),
            ("jueza de Israel", "jutgessa d'Israel"),
            ("conocida como Tabita", "coneguda com a Tabita"),
            ("pariente de Abraham", "parenta d'Abraham"),
            ("la que mató a Sísara", "la que va matar Sísara"),
            ("compañera de prisiones de Pablo", "companya de presó de Pau"),
            ("vendedora de púrpura", "venedora de porpra"),
            ("la abuela de Timoteo", "l'àvia de Timoteu"),
            ("hija simbólica de Oseas", "filla simbòlica d'Osees"),
            ("nombre que tomó Noemí en su amargura", "nom que Noemí va prendre en la seva amargor"),
            ("presente en la crucifixión", "present en la crucifixió"),
            ("otra forma del nombre Merab", "una altra forma del nom Merab"),
            ("mostró gran fe ante Jesús", "va mostrar una gran fe davant Jesús"),
            ("miró hacia atrás al salir de Sodoma", "va mirar enrere en sortir de Sodoma"),
            ("acusó falsamente a José", "va acusar falsament Josep"),
            ("sanada por Jesús", "guarida per Jesús"),
            ("habló con Jesús junto al pozo", "va parlar amb Jesús al costat del pou"),
            ("pidió misericordia para su hija", "va demanar misericòrdia per a la seva filla"),
            ("llevada ante Jesús", "portada davant Jesús"),
            ("hospedó a Eliseo", "va acollir Eliseu"),
            ("evitó la destrucción de la ciudad", "va evitar la destrucció de la ciutat"),
            ("habló ante el rey David", "va parlar davant del rei David"),
            ("sierva que reconoció a Pedro", "serventa que va reconèixer Pere"),
            ("seguidora y servidora de Jesús", "deixebla i servidora de Jesús"),
            ("recibió la misericordia de Jesús", "va rebre la misericòrdia de Jesús"),
            ("alimentada en tiempos de Elías", "alimentada en temps d'Elies"),
            ("dio todo lo que tenía", "ho va donar tot"),
            ("falsa profetisa en tiempos de Nehemías", "falsa profetessa en temps de Nehemies"),
            ("creyente elogiada por Pablo", "creient lloada per Pau"),
            ("cuñada de Rut", "cunyada de Rut"),
            ("Cuñada de Rut", "Cunyada de Rut"),
            ("la mujer de Jericó", "la dona de Jericó"),
            ("la reina Ester", "la reina Ester"),
            ("La reina Ester", "La reina Ester"),
            ("la nuera de Judá", "la nora de Judà"),
            ("La nuera de Judá", "La nora de Judà"),
            ("seguidora de Jesús", "deixebla de Jesús"),
            ("Seguidora de Jesús", "Deixebla de Jesús"),
            ("suegra de Rut", "sogra de Rut"),
            ("Suegra de Rut", "Sogra de Rut"),
            ("visitó al rey Salomón", "va visitar el rei Salomó"),
            ("Visitó al rey Salomón", "Va visitar el rei Salomó"),
            ("concubina de Nacor", "concubina de Nahor"),
            ("Concubina de Nacor", "Concubina de Nacor"),
            ("concubina del rey Saúl", "concubina del rei Saül"),
            ("Concubina del rey Saúl", "Concubina del rei Saül"),
            ("mujer mencionada en el Antiguo Testamento", "dona esmentada a l'Antic Testament"),
            ("de origen moderno", "d'origen modern"),
            ("con centro historico en", "amb centre historic a"),
            ("de caracter sincretista", "de caràcter sincrètic"),
            ("de interpretacion biblica particular", "d'interpretació bíblica particular"),
            ("postura de negacion de la existencia de deidades", "postura de negació de l'existència de divinitats"),
            ("postura sobre la imposibilidad o duda de conocer a Dios", "postura sobre la impossibilitat o el dubte de conèixer Déu"),
            ("Vision etica no religiosa centrada en el ser humano", "Visió ètica no religiosa centrada en l'ésser humà"),
            ("Creencia en un creador sin revelacion religiosa particular", "Creença en un creador sense revelació religiosa particular"),
            ("Personas que no se identifican con una religion concreta", "Persones que no s'identifiquen amb una religió concreta"),
            ("Hijo de ", "Fill de "),
            ("Hija de ", "Filla de "),
            ("Hermano de ", "Germà de "),
            ("Esposo de ", "Espos de "),
            ("Esposa de ", "Esposa de "),
            ("Madre de ", "Mare de "),
            ("Padre de ", "Pare de "),
            ("Rey de ", "Rei de "),
            ("Reina de ", "Reina de "),
            ("Uno de los ", "Un dels "),
            ("Una de las ", "Una de les "),
            ("mencionado por Pablo", "esmentat per Pau"),
            ("mencionada por Pablo", "esmentada per Pau"),
            ("mencionado en Hechos", "esmentat als Fets"),
            ("Creyente", "Creient"),
            ("Colaborador", "Col.laborador"),
            ("Companero", "Company"),
            ("Discipulo", "Deixeble"),
            ("apostol", "apòstol"),
            ("pueblo", "poble"),
            ("iglesia", "església"),
            ("mundo", "món"),
        ],
        "fr": [
            ("Personas que ", "Personnes qui "),
            ("Persona que ", "Personne qui "),
            ("sumo sacerdote", "grand prêtre"),
            ("sacerdote", "prêtre"),
            ("profetisa", "prophétesse"),
            ("Movimiento religioso", "Mouvement religieux"),
            ("Religion ", "Religion "),
            ("Tradicion ", "Tradition "),
            ("Tradiciones ", "Traditions "),
            ("Corriente ", "Courant "),
            ("Conjunto de ", "Ensemble de "),
            ("Fe basada en ", "Foi fondée sur "),
            ("fundada en", "fondée en"),
            ("fundado en", "fondé en"),
            ("centrada en", "centrée sur"),
            ("centrado en", "centré sur"),
            ("originada en", "née en"),
            ("originado en", "né en"),
            ("hijo de ", "fils de "),
            ("hija de ", "fille de "),
            ("hermano de ", "frère de "),
            ("hermana de ", "soeur de "),
            ("esposa de ", "épouse de "),
            ("esposo de ", "époux de "),
            ("madre de ", "mère de "),
            ("padre de ", "père de "),
            ("rey de ", "roi de "),
            ("reina de ", "reine de "),
            ("siervo de ", "serviteur de "),
            ("sierva de ", "servante de "),
            ("discipulo de ", "disciple de "),
            ("discipula de ", "disciple de "),
            ("compañero del apostol Pablo", "compagnon de l'apôtre Paul"),
            ("colaborador del apostol Pablo", "collaborateur de l'apôtre Paul"),
            ("colaborador de Pablo", "collaborateur de Paul"),
            ("el padre de la fe", "le père de la foi"),
            ("judío elocuente y poderoso en las Escrituras", "Juif éloquent et puissant dans les Écritures"),
            ("cantor y salmista", "chantre et psalmiste"),
            ("nombre de varios personajes bíblicos", "nom de plusieurs personnages bibliques"),
            ("el ciego que recibió la vista", "l'aveugle qui recouvra la vue"),
            ("uno de los doce espías", "l'un des douze espions"),
            ("principal de la sinagoga", "chef de la synagogue"),
            ("siervo etíope que ayudó a Jeremías", "serviteur éthiopien qui aida Jérémie"),
            ("libertador de Israel", "libérateur d'Israël"),
            ("séptimo desde Adán", "septième depuis Adam"),
            ("nieto de Aarón", "petit-fils d'Aaron"),
            ("maestro de la Ley entre los fariseos", "maître de la Loi parmi les pharisiens"),
            ("sabio y cantor", "sage et chantre"),
            ("descendiente de Sem", "descendant de Sem"),
            ("gitita leal a David", "Guitthien fidèle à David"),
            ("hombre de oración", "homme de prière"),
            ("general del ejército de David", "général de l'armée de David"),
            ("sobrino de David", "neveu de David"),
            ("nombre de varios reyes bíblicos", "nom de plusieurs rois bibliques"),
            ("discípulo secreto que dio su sepulcro a Jesús", "disciple secret qui donna son sépulcre à Jésus"),
            ("suegro de Jacob", "beau-père de Jacob"),
            ("hombre longevo del Antiguo Testamento", "homme de grande longévité dans l'Ancien Testament"),
            ("primo de Ester", "cousin d'Esther"),
            ("elegido entre los doce", "choisi parmi les douze"),
            ("porcio festo fue el procurador romano de Judea", "Porcius Festus fut le procurateur romain de Judée"),
            ("profeta en tiempos de Acab", "prophète au temps d'Achab"),
            ("reconstruyó los muros de Jerusalén", "reconstruisit les murailles de Jérusalem"),
            ("fariseo, principal entre los judíos", "pharisien, chef parmi les Juifs"),
            ("abuelo de David", "grand-père de David"),
            ("saulo de Tarso", "Saul de Tarse"),
            ("uno de los siete servidores", "l'un des sept serviteurs"),
            ("variante de Silas en algunas traducciones", "variante de Silas dans certaines traductions"),
            ("acompañante del apóstol Pablo", "compagnon de l'apôtre Paul"),
            ("llevó la cruz de Jesús", "porta la croix de Jésus"),
            ("anciano que vio al Mesías", "vieillard qui vit le Messie"),
            ("nombre de varios personajes pos-exilio", "nom de plusieurs personnages de l'après-exil"),
            ("el discípulo incrédulo", "le disciple incrédule"),
            ("nombre de varios levitas", "nom de plusieurs Lévites"),
            ("creyente mencionada por Pablo", "croyante mentionnée par Paul"),
            ("creyente mencionado por Pablo", "croyant mentionné par Paul"),
            ("gobernador romano", "gouverneur romain"),
            ("centurion romano", "centurion romain"),
            ("recaudador de impuestos", "collecteur d'impôts"),
            ("jefe de publicanos", "chef des publicains"),
            ("descendiente de Adán", "descendant d'Adam"),
            ("el bautista", "le Baptiste"),
            ("el de los diez mandamientos", "celui des dix commandements"),
            ("el del arca", "celui de l'arche"),
            ("el del pozo de los leones", "celui de la fosse aux lions"),
            ("gobernador de Judá", "gouverneur de Juda"),
            ("sobrino de Abraham", "neveu d'Abraham"),
            ("mujer mencionada en genealogias", "femme mentionnée dans les généalogies"),
            ("hombre temeroso de Dios", "homme craignant Dieu"),
            ("juez de Israel", "juge d'Israël"),
            ("rey David", "roi David"),
            ("rey Salomon", "roi Salomon"),
            ("profeta", "prophète"),
            ("evangelista", "evangeliste"),
            ("apostol", "apôtre"),
            ("seguidora de Jesus", "disciple de Jésus"),
            ("seguidor de Jesus", "disciple de Jésus"),
            ("madre de Jesus", "mère de Jésus"),
            ("madre del profeta Samuel", "mère du prophète Samuel"),
            ("madre de Juan el bautista", "mère de Jean-Baptiste"),
            ("madre de Timoteo", "mère de Timothée"),
            ("madre de Moises", "mère de Moïse"),
            ("esposa del rey David", "épouse du roi David"),
            ("esposa del rey Acab", "épouse du roi Achab"),
            ("esposa del rey Ezequias", "épouse du roi Ézéchias"),
            ("esposa del gobernador Felix", "épouse du gouverneur Félix"),
            ("esposa del profeta Oseas", "épouse du prophète Osée"),
            ("esposa de Aaron", "épouse d'Aaron"),
            ("esposa de Jose", "épouse de Joseph"),
            ("madre de Jesus de Nazaret", "mère de Jésus de Nazareth"),
            ("madre de Juan Marcos", "mere de Jean-Marc"),
            ("esposa de Abraham", "épouse d'Abraham"),
            ("esposa de Isaac", "épouse d'Isaac"),
            ("esposa de Jacob", "épouse de Jacob"),
            ("esposa de Aquila", "épouse d'Aquilas"),
            ("esposa de Booz", "épouse de Booz"),
            ("esposa de Ananias", "épouse d'Ananias"),
            ("esposa de Job", "épouse de Job"),
            ("madre del rey Josias", "mère du roi Josias"),
            ("madre de Sanson", "mère de Samson"),
            ("hija del rey Acab y de la reina Jezabel", "fille du roi Achab et de la reine Jézabel"),
            ("hija del rey Joram", "fille du roi Joram"),
            ("hija de Saul", "fille de Saul"),
            ("hija de Jacob", "fille de Jacob"),
            ("hija de Caleb", "fille de Caleb"),
            ("hija de Job", "fille de Job"),
            ("hija de Zelofehad", "fille de Tselophehad"),
            ("una de las hijas de Zelofehad", "l'une des filles de Tselophehad"),
            ("hija de Herodias", "fille d'Hérodiade"),
            ("mujer madianita", "femme madianite"),
            ("mujer de Sanson", "femme de Samson"),
            ("mujer de Elcana", "femme d'Elqana"),
            ("creyente de Atenas", "croyante d'Athènes"),
            ("esposa de Urias el heteo", "épouse d'Urie le Héthien"),
            ("una de las esposas de David", "l'une des épouses de David"),
            ("figura simbolica en Ezequiel", "figure symbolique dans Ézéchiel"),
            ("una de las parteras hebreas", "l'une des sages-femmes hébreues"),
            ("toco el manto de Jesus", "toucha le manteau de Jésus"),
            ("joven que sirvió al rey David", "jeune femme qui servit le roi David"),
            ("la profetisa hija de Fanuel", "la prophétesse, fille de Phanuel"),
            ("nombre de varias mujeres del Antiguo Testamento", "nom porté par plusieurs femmes de l'Ancien Testament"),
            ("nombre de varias mujeres bíblicas", "nom porté par plusieurs femmes bibliques"),
            ("cristiana cercana a Pablo", "chrétienne proche de Paul"),
            ("diaconisa de la iglesia", "diaconesse de l'Église"),
            ("nombre hebreo de Ester", "nom hébreu d'Esther"),
            ("madre de reyes de Judá", "mère de rois de Juda"),
            ("reina de Etiopía", "reine d'Éthiopie"),
            ("mujer vinculada a la muerte de Juan el Bautista", "femme liée à la mort de Jean-Baptiste"),
            ("jueza de Israel", "juge d'Israël"),
            ("conocida como Tabita", "connue sous le nom de Tabitha"),
            ("pariente de Abraham", "parente d'Abraham"),
            ("la que mató a Sísara", "celle qui tua Sisera"),
            ("compañera de prisiones de Pablo", "compagne d'emprisonnement de Paul"),
            ("vendedora de púrpura", "marchande de pourpre"),
            ("la abuela de Timoteo", "la grand-mère de Timothée"),
            ("hija simbólica de Oseas", "fille symbolique dans Osée"),
            ("nombre que tomó Noemí en su amargura", "nom que Noémi prit dans son amertume"),
            ("presente en la crucifixión", "présente lors de la crucifixion"),
            ("otra forma del nombre Merab", "autre forme du nom Merab"),
            ("mostró gran fe ante Jesús", "montra une grande foi devant Jésus"),
            ("miró hacia atrás al salir de Sodoma", "regarda en arrière en quittant Sodome"),
            ("acusó falsamente a José", "accusa faussement Joseph"),
            ("sanada por Jesús", "guérie par Jésus"),
            ("habló con Jesús junto al pozo", "parla avec Jésus près du puits"),
            ("pidió misericordia para su hija", "demanda miséricorde pour sa fille"),
            ("llevada ante Jesús", "amenée devant Jésus"),
            ("hospedó a Eliseo", "accueillit Élisée"),
            ("evitó la destrucción de la ciudad", "empêcha la destruction de la ville"),
            ("habló ante el rey David", "parla devant le roi David"),
            ("sierva que reconoció a Pedro", "servante qui reconnut Pierre"),
            ("seguidora y servidora de Jesús", "disciple et soutien de Jésus"),
            ("recibió la misericordia de Jesús", "reçut la miséricorde de Jésus"),
            ("alimentada en tiempos de Elías", "nourrie au temps d'Élie"),
            ("dio todo lo que tenía", "donna tout ce qu'elle avait"),
            ("falsa profetisa en tiempos de Nehemías", "fausse prophétesse au temps de Néhémie"),
            ("creyente elogiada por Pablo", "croyante louée par Paul"),
            ("cuñada de Rut", "belle-soeur de Ruth"),
            ("la mujer de Jericó", "la femme de Jéricho"),
            ("la reina Ester", "la reine Esther"),
            ("la nuera de Judá", "la belle-fille de Juda"),
            ("suegra de Rut", "belle-mère de Ruth"),
            ("visitó al rey Salomón", "rendit visite au roi Salomon"),
            ("concubina de Nacor", "concubine de Nahor"),
            ("concubina del rey Saúl", "concubine du roi Saül"),
            ("mujer mencionada en el Antiguo Testamento", "femme mentionnée dans l'Ancien Testament"),
            ("de origen moderno", "d'origine moderne"),
            ("con centro historico en", "avec centre historique à"),
            ("de caracter sincretista", "de caractère syncrétique"),
            ("de interpretacion biblica particular", "à interprétation biblique particulière"),
            ("postura de negacion de la existencia de deidades", "position niant l'existence de divinités"),
            ("postura sobre la imposibilidad o duda de conocer a Dios", "position sur l'impossibilité ou le doute de connaître Dieu"),
            ("Vision etica no religiosa centrada en el ser humano", "Vision éthique non religieuse centrée sur l'être humain"),
            ("Creencia en un creador sin revelacion religiosa particular", "Croyance en un créateur sans révélation religieuse particulière"),
            ("Personas que no se identifican con una religion concreta", "Personnes qui ne s'identifient à aucune religion précise"),
            ("Hijo de ", "Fils de "),
            ("Hija de ", "Fille de "),
            ("Hermano de ", "Frere de "),
            ("Esposo de ", "Époux de "),
            ("Esposa de ", "Épouse de "),
            ("Madre de ", "Mère de "),
            ("Padre de ", "Père de "),
            ("Rey de ", "Roi de "),
            ("Reina de ", "Reine de "),
            ("Uno de los ", "Un des "),
            ("Una de las ", "Une des "),
            ("mencionado por Pablo", "mentionne par Paul"),
            ("mencionada por Pablo", "mentionnée par Paul"),
            ("mencionado en Hechos", "mentionne dans Actes"),
            ("Creyente", "Croyant"),
            ("Colaborador", "Collaborateur"),
            ("Companero", "Compagnon"),
            ("Discipulo", "Disciple"),
            ("pueblo", "peuple"),
            ("iglesia", "église"),
            ("mundo", "monde"),
        ],
        "en": [
            ("Personas que ", "People who "),
            ("Persona que ", "Person who "),
            ("sumo sacerdote", "high priest"),
            ("sacerdote", "priest"),
            ("profetisa", "prophetess"),
            ("Movimiento religioso", "Religious movement"),
            ("Religion ", "Religion "),
            ("Tradicion ", "Tradition "),
            ("Tradiciones ", "Traditions "),
            ("Corriente ", "Branch "),
            ("Conjunto de ", "Set of "),
            ("Fe basada en ", "Faith based on "),
            ("fundada en", "founded in"),
            ("fundado en", "founded in"),
            ("centrada en", "centered on"),
            ("centrado en", "centered on"),
            ("originada en", "originating in"),
            ("originado en", "originating in"),
            ("hijo de ", "son of "),
            ("hija de ", "daughter of "),
            ("hermano de ", "brother of "),
            ("hermana de ", "sister of "),
            ("esposa de ", "wife of "),
            ("esposo de ", "husband of "),
            ("madre de ", "mother of "),
            ("padre de ", "father of "),
            ("rey de ", "king of "),
            ("reina de ", "queen of "),
            ("siervo de ", "servant of "),
            ("sierva de ", "female servant of "),
            ("discipulo de ", "disciple of "),
            ("discipula de ", "disciple of "),
            ("compañero del apostol Pablo", "companion of the apostle Paul"),
            ("colaborador del apostol Pablo", "coworker of the apostle Paul"),
            ("colaborador de Pablo", "coworker of Paul"),
            ("el padre de la fe", "the father of faith"),
            ("judío elocuente y poderoso en las Escrituras", "eloquent Jew, mighty in the Scriptures"),
            ("cantor y salmista", "singer and psalmist"),
            ("nombre de varios personajes bíblicos", "name of several biblical figures"),
            ("el ciego que recibió la vista", "the blind man who received his sight"),
            ("uno de los doce espías", "one of the twelve spies"),
            ("principal de la sinagoga", "leader of the synagogue"),
            ("siervo etíope que ayudó a Jeremías", "Ethiopian servant who helped Jeremiah"),
            ("libertador de Israel", "deliverer of Israel"),
            ("séptimo desde Adán", "seventh from Adam"),
            ("nieto de Aarón", "grandson of Aaron"),
            ("maestro de la Ley entre los fariseos", "teacher of the Law among the Pharisees"),
            ("sabio y cantor", "wise man and singer"),
            ("descendiente de Sem", "descendant of Shem"),
            ("gitita leal a David", "Gittite loyal to David"),
            ("hombre de oración", "man of prayer"),
            ("general del ejército de David", "general of David's army"),
            ("sobrino de David", "nephew of David"),
            ("nombre de varios reyes bíblicos", "name of several biblical kings"),
            ("discípulo secreto que dio su sepulcro a Jesús", "secret disciple who gave his tomb to Jesus"),
            ("suegro de Jacob", "father-in-law of Jacob"),
            ("hombre longevo del Antiguo Testamento", "long-lived man of the Old Testament"),
            ("primo de Ester", "cousin of Esther"),
            ("elegido entre los doce", "chosen among the twelve"),
            ("porcio festo fue el procurador romano de Judea", "Porcius Festus was the Roman procurator of Judea"),
            ("profeta en tiempos de Acab", "prophet in the days of Ahab"),
            ("reconstruyó los muros de Jerusalén", "rebuilt the walls of Jerusalem"),
            ("fariseo, principal entre los judíos", "Pharisee, a leader among the Jews"),
            ("abuelo de David", "grandfather of David"),
            ("saulo de Tarso", "Saul of Tarsus"),
            ("uno de los siete servidores", "one of the seven servants"),
            ("variante de Silas en algunas traducciones", "variant of Silas in some translations"),
            ("acompañante del apóstol Pablo", "companion of the apostle Paul"),
            ("llevó la cruz de Jesús", "carried the cross of Jesus"),
            ("anciano que vio al Mesías", "elder who saw the Messiah"),
            ("nombre de varios personajes pos-exilio", "name of several post-exilic figures"),
            ("el discípulo incrédulo", "the doubting disciple"),
            ("nombre de varios levitas", "name of several Levites"),
            ("creyente mencionada por Pablo", "believer mentioned by Paul"),
            ("creyente mencionado por Pablo", "believer mentioned by Paul"),
            ("gobernador romano", "Roman governor"),
            ("centurion romano", "Roman centurion"),
            ("recaudador de impuestos", "tax collector"),
            ("jefe de publicanos", "chief tax collector"),
            ("descendiente de Adán", "descendant of Adam"),
            ("el bautista", "the Baptist"),
            ("el de los diez mandamientos", "the one of the Ten Commandments"),
            ("el del arca", "the one of the ark"),
            ("el del pozo de los leones", "the one in the lions' den"),
            ("sobrino de Abraham", "nephew of Abraham"),
            ("mujer mencionada en genealogias", "woman mentioned in genealogies"),
            ("hombre temeroso de Dios", "God-fearing man"),
            ("juez de Israel", "judge of Israel"),
            ("rey David", "King David"),
            ("rey Salomon", "King Solomon"),
            ("profeta", "prophet"),
            ("evangelista", "evangelist"),
            ("apostol", "apostle"),
            ("seguidora de Jesus", "follower of Jesus"),
            ("seguidor de Jesus", "follower of Jesus"),
            ("madre de Jesus", "mother of Jesus"),
            ("madre del profeta Samuel", "mother of the prophet Samuel"),
            ("madre de Juan el bautista", "mother of John the Baptist"),
            ("madre de Timoteo", "mother of Timothy"),
            ("madre de Moises", "mother of Moses"),
            ("esposa del rey David", "wife of King David"),
            ("esposa del rey Acab", "wife of King Ahab"),
            ("esposa del rey Ezequias", "wife of King Hezekiah"),
            ("esposa del gobernador Felix", "wife of Governor Felix"),
            ("esposa del profeta Oseas", "wife of the prophet Hosea"),
            ("esposa de Aaron", "wife of Aaron"),
            ("esposa de Jose", "wife of Joseph"),
            ("madre de Jesus de Nazaret", "mother of Jesus of Nazareth"),
            ("madre de Juan Marcos", "mother of John Mark"),
            ("esposa de Abraham", "wife of Abraham"),
            ("esposa de Isaac", "wife of Isaac"),
            ("esposa de Jacob", "wife of Jacob"),
            ("esposa de Aquila", "wife of Aquila"),
            ("esposa de Booz", "wife of Boaz"),
            ("esposa de Ananias", "wife of Ananias"),
            ("esposa de Job", "wife of Job"),
            ("madre del rey Josias", "mother of King Josiah"),
            ("madre de Sanson", "mother of Samson"),
            ("hija del rey Acab y de la reina Jezabel", "daughter of King Ahab and Queen Jezebel"),
            ("hija del rey Joram", "daughter of King Joram"),
            ("hija de Saul", "daughter of Saul"),
            ("hija de Jacob", "daughter of Jacob"),
            ("hija de Caleb", "daughter of Caleb"),
            ("hija de Job", "daughter of Job"),
            ("hija de Zelofehad", "daughter of Zelophehad"),
            ("una de las hijas de Zelofehad", "one of the daughters of Zelophehad"),
            ("hija de Herodias", "daughter of Herodias"),
            ("mujer madianita", "Midianite woman"),
            ("mujer de Sanson", "wife of Samson"),
            ("mujer de Elcana", "wife of Elkanah"),
            ("creyente de Atenas", "believer in Athens"),
            ("esposa de Urias el heteo", "wife of Uriah the Hittite"),
            ("una de las esposas de David", "one of David's wives"),
            ("figura simbolica en Ezequiel", "symbolic figure in Ezekiel"),
            ("una de las parteras hebreas", "one of the Hebrew midwives"),
            ("toco el manto de Jesus", "touched the garment of Jesus"),
            ("joven que sirvió al rey David", "young woman who served King David"),
            ("la profetisa hija de Fanuel", "the prophetess, daughter of Phanuel"),
            ("nombre de varias mujeres del Antiguo Testamento", "name of several women in the Old Testament"),
            ("nombre de varias mujeres bíblicas", "name of several biblical women"),
            ("cristiana cercana a Pablo", "Christian woman associated with Paul"),
            ("diaconisa de la iglesia", "deaconess of the church"),
            ("nombre hebreo de Ester", "Hebrew name of Esther"),
            ("madre de reyes de Judá", "mother of kings of Judah"),
            ("reina de Etiopía", "queen of Ethiopia"),
            ("mujer vinculada a la muerte de Juan el Bautista", "woman linked to the death of John the Baptist"),
            ("jueza de Israel", "judge of Israel"),
            ("conocida como Tabita", "also known as Tabitha"),
            ("pariente de Abraham", "relative of Abraham"),
            ("la que mató a Sísara", "the woman who killed Sisera"),
            ("compañera de prisiones de Pablo", "companion in imprisonment with Paul"),
            ("vendedora de púrpura", "seller of purple cloth"),
            ("la abuela de Timoteo", "Timothy's grandmother"),
            ("hija simbólica de Oseas", "symbolic daughter in Hosea"),
            ("nombre que tomó Noemí en su amargura", "name Naomi took in her bitterness"),
            ("presente en la crucifixión", "present at the crucifixion"),
            ("otra forma del nombre Merab", "alternate form of the name Merab"),
            ("mostró gran fe ante Jesús", "showed great faith before Jesus"),
            ("miró hacia atrás al salir de Sodoma", "looked back while leaving Sodom"),
            ("acusó falsamente a José", "falsely accused Joseph"),
            ("sanada por Jesús", "healed by Jesus"),
            ("habló con Jesús junto al pozo", "spoke with Jesus at the well"),
            ("pidió misericordia para su hija", "asked for mercy for her daughter"),
            ("llevada ante Jesús", "brought before Jesus"),
            ("hospedó a Eliseo", "hosted Elisha"),
            ("evitó la destrucción de la ciudad", "prevented the destruction of the city"),
            ("habló ante el rey David", "spoke before King David"),
            ("sierva que reconoció a Pedro", "servant girl who recognized Peter"),
            ("seguidora y servidora de Jesús", "follower and supporter of Jesus"),
            ("recibió la misericordia de Jesús", "received the mercy of Jesus"),
            ("alimentada en tiempos de Elías", "fed in the days of Elijah"),
            ("dio todo lo que tenía", "gave all she had"),
            ("falsa profetisa en tiempos de Nehemías", "false prophetess in the time of Nehemiah"),
            ("creyente elogiada por Pablo", "believer commended by Paul"),
            ("cuñada de Rut", "sister-in-law of Ruth"),
            ("la mujer de Jericó", "the woman from Jericho"),
            ("la reina Ester", "Queen Esther"),
            ("suegra de Rut", "mother-in-law of Ruth"),
            ("visitó al rey Salomón", "visited King Solomon"),
            ("concubina de Nacor", "concubine of Nahor"),
            ("concubina del rey Saúl", "concubine of King Saul"),
            ("mujer mencionada en el Antiguo Testamento", "woman mentioned in the Old Testament"),
            ("de origen moderno", "of modern origin"),
            ("con centro historico en", "with historical center in"),
            ("de caracter sincretista", "of a syncretic character"),
            ("de interpretacion biblica particular", "with a particular biblical interpretation"),
            ("postura de negacion de la existencia de deidades", "position denying the existence of deities"),
            ("postura sobre la imposibilidad o duda de conocer a Dios", "position about the impossibility or doubt of knowing God"),
            ("Vision etica no religiosa centrada en el ser humano", "Non-religious ethical vision centered on the human being"),
            ("Creencia en un creador sin revelacion religiosa particular", "Belief in a creator without specific religious revelation"),
            ("Personas que no se identifican con una religion concreta", "People who do not identify with a specific religion"),
            ("Hijo de ", "Son of "),
            ("Hija de ", "Daughter of "),
            ("Hermano de ", "Brother of "),
            ("Esposo de ", "Husband of "),
            ("Esposa de ", "Wife of "),
            ("Madre de ", "Mother of "),
            ("Padre de ", "Father of "),
            ("Rey de ", "King of "),
            ("Reina de ", "Queen of "),
            ("Uno de los ", "One of the "),
            ("Una de las ", "One of the "),
            ("mencionado por Pablo", "mentioned by Paul"),
            ("mencionada por Pablo", "mentioned by Paul"),
            ("mencionado en Hechos", "mentioned in Acts"),
            ("Creyente", "Believer"),
            ("Colaborador", "Coworker"),
            ("Companero", "Companion"),
            ("Discipulo", "Disciple"),
            ("pueblo", "people"),
            ("iglesia", "church"),
            ("mundo", "world"),
        ],
    }

    plain_item_translations = {
        "ca": {
            "Adoradores": "Adoradors", "Agarenos": "Agarens", "Amos de casa": "Caps de casa", "Ancianos": "Ancians",
            "Apostoles": "Apostols", "Arqueros": "Arquers", "Asambleas": "Assemblees", "Cantores": "Cantors",
            "Carceleros": "Carcellers", "Celotes": "Zelotes", "Centuriones": "Centurions", "Concilios": "Concilis",
            "Consejeros": "Consellers", "Constructores": "Constructors", "Cortesanos": "Cortesans", "Creyentes": "Creients",
            "Desterrados": "Desterrats", "Diaconos": "Diaques", "Discipulos": "Deixebles", "Doce tribus": "Dotze tribus",
            "Doctores de la Ley": "Doctors de la Llei", "Endemoniados": "Endimoniats", "Enfermos": "Malalts",
            "Escribas": "Escribes", "Esenios": "Essenis", "Exiliados": "Exiliats", "Extranjeros": "Estrangers",
            "Familias sacerdotales": "Families sacerdotals", "Fariseos": "Fariseus", "Gentiles": "Gentils",
            "Guardianes de la puerta": "Guardes de la porta", "Helenistas": "Helenistes", "Herodianos": "Herodians",
            "Hijas de Sion": "Filles de Sio", "Huerfanos": "Orfes", "Jefes de millares": "Caps de milers",
            "Jovenes": "Joves", "Judios": "Jueus", "Jueces": "Jutges", "Levitas": "Levites",
            "Magos de Oriente": "Mags d'Orient", "Mercaderes": "Mercaders", "Mujeres esteriles": "Dones esterils",
            "Murmuradores": "Murmuradors", "Nazareos": "Nazireus", "Nobles": "Nobles", "Obreros": "Obrers",
            "Ovejas perdidas": "Ovelles perdudes", "Pastoreadores": "Pastors", "Pecadores": "Pecadors",
            "Peregrinos": "Pelegrins", "Pescadores": "Pescadors", "Porteros": "Porters", "Presos": "Presos",
            "Profetas": "Profetes", "Prosélitos": "Proselyts", "Publicanos": "Publicans", "Recaudadores": "Recaptadors",
            "Rechazados": "Rebutjats", "Remanente": "Romanent", "Reyes de la tierra": "Reis de la terra",
            "Sacerdotes": "Sacerdots", "Saduceos": "Saduceus", "Samaritanos piadosos": "Samaritans pietosos",
            "Sanedrin": "Sanedri", "Siervas": "Serventes", "Soldados": "Soldats", "Sumos sacerdotes": "Summes sacerdots",
            "Trabajadores de la mies": "Treballadors de la sega", "Viudas": "Vidues",
            "Amalecitas": "Amalecites", "Amonitas": "Amonites", "Amorreos": "Amorreus", "Arameos": "Arameus",
            "Asirios": "Assiris", "Babilonios": "Babilonis", "Caldeos": "Caldeus", "Cananeos": "Cananeus",
            "Cretenses": "Cretencs", "Cusitas": "Cusites", "Danitas": "Danites", "Egipcios": "Egipcis",
            "Edomitas": "Edomites", "Elamitas": "Elamites", "Efraimitas": "Efraimites", "Fenicios": "Fenicis",
            "Filisteos": "Filisteus", "Gabaonitas": "Gabaonites", "Gergeseos": "Gergeseus", "Gesureos": "Gesureus",
            "Hebreos": "Hebreus", "Hititas": "Hitites", "Hivitas": "Hivites", "Horitas": "Horites",
            "Hurritas": "Hurrites", "Israelitas": "Israelites", "Jebuseos": "Jebuseus", "Lidios": "Lidis",
            "Madianitas": "Madianites", "Medianitas": "Medes", "Mesec": "Mesec", "Moabitas": "Moabites",
            "Ninivitas": "Ninivites", "Partos": "Parts", "Persas": "Perses", "Romanos": "Romans",
            "Samaritanos": "Samaritans", "Sidonios": "Sidonis", "Sirios": "Siris", "Sumerios": "Sumeris",
            "Tarsenses": "Tarsencs", "Tribus de Israel": "Tribus d'Israel",
            "Ararat": "Ararat", "Atenas": "Atenes", "Beerseba": "Beerxeba", "Belén": "Betlem", "Betania": "Betania",
            "Betel": "Betel", "Betesda": "Betesda", "Cana": "Cana", "Canaán": "Canaan", "Carmelo": "Carmel",
            "Cesarea": "Cesarea", "Cesarea de Filipo": "Cesarea de Filip", "Corinto": "Corint", "Creta": "Creta",
            "Damasco": "Damasc", "Decápolis": "Decapolis", "Emaús": "Emmaus", "Esmirna": "Esmirna",
            "Filipos": "Filips", "Getsemani": "Getsemani", "Golgota": "Golgota", "Gosen": "Goixen", "Hebron": "Hebron",
            "Horeb": "Horeb", "Jordan": "Jorda", "Laodicea": "Laodicea", "Listra": "Listra", "Magdala": "Magdala",
            "Madian": "Madian", "Monte de los Olivos": "Muntanya de les Oliveres", "Nazaret": "Nazaret",
            "Patmos": "Patmos", "Penuel": "Penuel", "Pisidia": "Pisidia", "Ponto": "Pont", "Rama": "Rama",
            "Rameses": "Rameses", "Sardis": "Sardes", "Sarepta": "Sarepta", "Sichem": "Siquem", "Silo": "Silo",
            "Sinai": "Sinai", "Sion": "Sio", "Siria": "Siria", "Susa": "Susa", "Tarsis": "Tarsis",
            "Tiatira": "Tiatira", "Tiro": "Tir", "Troas": "Troas", "Ur": "Ur", "Zoar": "Soar",
            "Budismo mahayana": "Budisme mahayana", "Budismo theravada": "Budisme theravada", "Budismo vajrayana": "Budisme vajrayana",
            "Chiismo": "Xiisme", "Evangelicalismo": "Evangelicalisme", "Judaísmo conservador": "Judaisme conservador",
            "Judaísmo ortodoxo": "Judaisme ortodox", "Judaísmo reformista": "Judaisme reformista",
            "Ortodoxia oriental": "Ortodòxia oriental", "Pentecostalismo": "Pentecostalisme", "Shaivismo": "Saivisme",
            "Shaktismo": "Xaktisme", "Sufismo": "Sufisme", "Sunismo": "Sunnisme", "Tenrikyo": "Tenrikyo",
            "Testigos de Jehova": "Testimonis de Jehova", "Tradiciones chinas": "Tradicions xineses",
            "Unitarios universalistas": "Unitaris universalistes", "Vaishnavismo": "Vaixnavisme", "Wicca": "Wicca",
            "Bahaismo": "Bahaisme", "Caodaísmo": "Caodaisme", "Religiones africanas tradicionales": "Religions africanes tradicionals",
            "Religiones indígenas americanas": "Religions indigenes americanes", "Religiones indígenas australianas": "Religions indigenes australianes",
            "Abigail": "Abigail", "Abisag": "Abisag", "Abital": "Abital", "Acsa": "Acsa", "Ada": "Ada",
            "Ana": "Anna", "Apphia": "Àpfia", "Asenat": "Asenat", "Atalia": "Atalia", "Batseba": "Betsabé",
            "Candace": "Candace", "Claudia": "Claudia", "Cloe": "Cloe", "Dalila": "Dalila", "Damaris": "Damaris",
            "Dorcas": "Dorques", "Elisabet": "Elisabet", "Eunice": "Eunice", "Febe": "Febe", "Hagar": "Agar",
            "Herodias": "Herodies", "Hulda": "Hulda", "Jael": "Jael", "Jezabel": "Jezabel", "Jocabed": "Jocabed",
            "Julia": "Julia", "Junia": "Junia", "Keturah": "Quetura", "Lia": "Lia", "Loida": "Loida",
            "Maria de Cleofas": "Maria de Cleofàs", "Merab": "Merab", "Mical": "Mical", "Milca": "Milca",
            "Noemi": "Noemí", "Orfa": "Orfa", "Penina": "Peninna", "Persida": "Pèrsida", "Priscila": "Priscil·la",
            "Pua": "Pua", "Rahab": "Rahab", "Reina de Saba": "Reina de Saba", "Rizpa": "Rispà", "Rode": "Rode",
            "Safira": "Safira", "Salome": "Salomé", "Sara": "Sara", "Sefora": "Sèfora", "Sifra": "Xifrà",
            "Susana": "Susanna", "Tabita": "Tabita", "Tamar": "Tamar", "Vasti": "Vasti", "Mujer cananea": "Dona cananea",
            "Mujer samaritana": "Dona samaritana", "Mujer sirofenicia": "Dona sirofenicia", "Mujer de Lot": "Dona de Lot",
            "Mujer de Job": "Dona de Job", "Mujer de Manoa": "Dona de Manoa", "Mujer de Potifar": "Dona de Potifar",
            "Mujer encorvada": "Dona encorbada", "Mujer del flujo de sangre": "Dona amb hemorràgies",
            "Mujer sabia de Abel": "Dona sàvia d'Abel", "Mujer sabia de Tecoa": "Dona sàvia de Tecoa",
            "Mujer sorprendida en adulterio": "Dona sorpresa en adulteri", "Mujer sunamita": "Dona sunamita",
            "Viuda de Nain": "Vídua de Naïm", "Viuda de Sarepta": "Vídua de Sarepta", "Viuda pobre del templo": "Vídua pobra del temple",
            "El profeta": "Profeta", "Principal de la sinagoga": "Cap de la sinagoga",
            "Mujer vinculada a la muerte de Juan el Bautista": "Dona vinculada a la mort de Joan Baptista",
            "Compañera de prisiones de Pablo": "Companya de presó de Pau",
            "Hija simbólica de Oseas": "Filla simbòlica d'Osees",
            "Sierva que reconoció a Pedro": "Serventa que va reconèixer Pere",
            "Alimentada en tiempos de Elías": "Alimentada en temps d'Elies",
            "Judío elocuente y poderoso en las Escrituras": "Jueu eloqüent i poderós en les Escriptures",
            "Judio elocuente y poderoso en las Escrituras": "Jueu eloqüent i poderós en les Escriptures",
            "Maestro de la Ley entre los fariseos": "Mestre de la Llei entre els fariseus",
            "Reconstruyó los muros de Jerusalén": "Va reconstruir les muralles de Jerusalem",
            "Reconstruyo los muros de Jerusalén": "Va reconstruir les muralles de Jerusalem",
            "Reconstruyó los muros de Jerusalen": "Va reconstruir les muralles de Jerusalem",
            "Reconstruyo los muros de Jerusalen": "Va reconstruir les muralles de Jerusalem",
            "Siervo mencionado por Pablo": "Servent esmentat per Pau",
            "Siervo etíope que ayudó a Jeremías": "Servent etíop que va ajudar Jeremies",
            "Siervo etiope que ayudó a Jeremías": "Servent etíop que va ajudar Jeremies",
            "Siervo etíope que ayudo a Jeremías": "Servent etíop que va ajudar Jeremies",
            "Siervo etiope que ayudo a Jeremías": "Servent etíop que va ajudar Jeremies",
            "Siervo etíope que ayudó a Jeremias": "Servent etíop que va ajudar Jeremies",
            "Siervo etiope que ayudó a Jeremias": "Servent etíop que va ajudar Jeremies",
            "Siervo etíope que ayudo a Jeremias": "Servent etíop que va ajudar Jeremies",
            "Siervo etiope que ayudo a Jeremias": "Servent etíop que va ajudar Jeremies",
            "Concubina de Nacor": "Concubina de Nahor", "Esposa de Urías el heteo": "Dona d'Uries l'heteu",
            "Una de las esposas de David": "Una de les dones de David", "Esposa del rey Asuero": "Dona del rei Assuer",
            "Seguidora y servidora de Jesús": "Deixebla i servidora de Jesús", "Esposa de Booz": "Dona de Booz",
            "Esposa de David": "Dona de David", "Esposa de Jacob": "Dona de Jacob", "Esposa de Job": "Dona de Job",
            "Esposa de Lamec": "Dona de Lamec", "Esposa de Moisés": "Dona de Moisès",
            "La reina Ester": "La reina Ester", "Seguidora de Jesús": "Deixebla de Jesús",
            "Personas entregadas a alabar y honrar a Dios": "Gent lliurada a lloar i honorar Déu",
            "Pueblo mencionado en conflictos del Antiguo Testamento": "Poble citat en conflictes de l'Antic Testament",
            "Responsables del hogar en distintos relatos bíblicos": "Caps de casa en diversos relats bíblics",
            "Guerreros armados con arco en batallas bíblicas": "Guerrers armats amb arc en batalles bíbliques",
            "Reuniones del pueblo para escuchar la Ley o adorar": "Trobades del poble per escoltar la Llei o adorar",
            "Ministros dedicados al canto en el templo": "Ministres dedicats al cant al temple",
            "Encargados de prisiones, como en el libro de Hechos": "Guardes de la presó, com al llibre dels Fets",
            "Oficiales romanos mencionados varias veces en el Nuevo Testamento": "Oficials romans citats diverses vegades al Nou Testament",
            "Reuniones de líderes para tratar asuntos del pueblo o de la iglesia": "Trobades de dirigents per tractar afers del poble o de l'església",
            "Personas que orientaban a reyes o líderes": "Gent que aconsellava reis o dirigents",
            "Obreros implicados en murallas, ciudades o el templo": "Obrers implicats en muralles, ciutats o el temple",
            "Servidores de palacio en reinos bíblicos": "Servidors de palau en regnes bíblics",
            "Personas que han respondido con fe al mensaje de Dios": "Gent que ha respost amb fe al missatge de Déu",
            "Exiliados fuera de su tierra por juicio o guerra": "Exiliats fora de la seva terra per judici o guerra",
            "Conjunto del pueblo de Israel descendiente de Jacob": "Conjunt del poble d'Israel descendent de Jacob",
            "Expertos en la interpretación de la Ley mosaica": "Experts en la interpretació de la Llei mosaica",
            "Personas oprimidas por espíritus malignos en los Evangelios": "Gent oprimida per esperits malignes als Evangelis",
            "Grupo frecuentemente atendido con compasión y milagros": "Col·lectiu atès sovint amb compassió i miracles",
            "Pueblo llevado cautivo fuera de Israel y Judá": "Poble portat captiu fora d'Israel i Judà",
            "Personas de otras naciones presentes entre el pueblo": "Gent d'altres nacions present entre el poble",
            "Linajes apartados para el servicio del templo": "Nissagues reservades al servei del temple",
            "Responsables del acceso y orden en el templo": "Guardes de l'accés i l'ordre del temple",
            "Expresión poética para referirse al pueblo de Jerusalén": "Expressió poètica per referir-se al poble de Jerusalem",
            "Grupo vulnerable protegido en la Ley y los profetas": "Col·lectiu vulnerable protegit a la Llei i als profetes",
            "Líderes militares y administrativos de Israel": "Líders militars i administratius d'Israel",
            "Grupo mencionado en exhortaciones, guerras y discipulado": "Col·lectiu esmentat en exhortacions, guerres i discipulat",
            "Líderes levantados por Dios para gobernar y liberar a Israel": "Líders aixecats per Déu per governar i alliberar Israel",
            "Sabios que visitaron a Jesús tras su nacimiento": "Savs que van visitar Jesús després del seu naixement",
            "Comerciantes presentes en ciudades y rutas bíblicas": "Comerciants presents en ciutats i rutes bíbliques",
            "Mujeres que vivieron la espera de un hijo con fe y dolor": "Dones que van viure l'espera d'un fill amb fe i dolor",
            "Grupo que protesta contra Dios o sus siervos": "Col·lectiu que protesta contra Déu o els seus servents",
            "Personas consagradas a Dios mediante voto especial": "Persones consagrades a Déu mitjançant un vot especial",
            "Miembros influyentes del pueblo o de la corte": "Personatges influents del poble o de la cort",
            "Trabajadores del campo, la construcción o la mies espiritual": "Treballadors del camp, de la construcció o de la sega espiritual",
            "Imagen del pueblo descarriado necesitado de pastor": "Figura del poble esgarriat que necessita pastor",
            "Encargados de cuidar rebaños en la vida cotidiana bíblica": "Responsables de tenir cura dels ramats en la vida quotidiana bíblica",
            "Término frecuente para quienes necesitan arrepentimiento y gracia": "Terme freqüent per als qui necessiten penediment i gràcia",
            "Personas de paso o en viaje hacia lugares santos": "Gent de pas o en camí cap a llocs sants",
            "Oficio común en Galilea y entre varios discípulos": "Ofici comú a Galilea i entre diversos deixebles",
            "Servidores asignados al cuidado de entradas y espacios sagrados": "Servidors encarregats de vetllar per les entrades i els espais sagrats",
            "Personas encarceladas por delitos, injusticia o causa del Evangelio": "Gent empresonada per delictes, injustícia o per causa de l'Evangeli",
            "Gentiles incorporados a la fe judía": "Gentils incorporats a la fe jueva",
            "Funcionarios que cobraban tributos e impuestos": "Cobradors de tributs i impostos",
            "Personas marginadas social o religiosamente": "Gent marginada socialment o religiosament",
            "Gobernantes de naciones en pasajes históricos y proféticos": "Sobirans de nacions en passatges històrics i profètics",
            "Grupo fiel preservado por Dios en tiempos de crisis": "Col·lectiu fidel preservat per Déu en temps de crisi",
            "Referencia a quienes actúan con misericordia inesperada": "Referència als qui actuen amb misericòrdia inesperada",
            "Mujeres al servicio de hogares o familias": "Dones al servei de llars o famílies",
            "Militares presentes en historias del Antiguo y Nuevo Testamento": "Militars presents en històries de l'Antic i del Nou Testament",
            "Imagen de quienes sirven en la obra de Dios": "Figura dels qui serveixen en l'obra de Déu",
            "Grupo religioso influyente en tiempos de Jesús": "Col·lectiu religiós influent en temps de Jesús",
            "Grupo sacerdotal y político del judaísmo": "Col·lectiu sacerdotal i polític del judaisme",
            "Intérpretes y maestros de la Ley": "Intèrprets i mestres de la Llei",
            "Partidarios de la casa de Herodes": "Partidaris de la casa d'Herodes",
            "Movimiento judío de fuerte fervor nacional": "Corrent jueu de fort zel nacional",
            "Comunidad judía asociada a vida apartada": "Comunitat jueva associada a una vida apartada",
            "Cobradores de impuestos en tiempos de Roma": "Cobradores d'impostos en temps de Roma",
            "Tribu dedicada al servicio del templo": "Tribu dedicada al servei del temple",
            "Encargados del culto en Israel": "Responsables del culte a Israel",
            "Máxima autoridad sacerdotal": "Màxima autoritat sacerdotal",
            "Consejo religioso judío": "Consell religiós jueu",
            "Seguidores y aprendices de Jesús": "Seguidors i aprenents de Jesús",
            "Enviados escogidos por Jesús": "Enviats escollits per Jesús",
            "Portavoces del mensaje de Dios": "Portaveus del missatge de Déu",
            "Pueblos no judíos": "Pobles no jueus",
            "Pueblo del pacto en tiempos bíblicos": "Poble del pacte en temps bíblics",
            "Judíos de lengua griega mencionados en Hechos": "Jueus de llengua grega esmentats als Fets",
            "Grupo vulnerable atendido por la iglesia primitiva": "Col·lectiu vulnerable atès per l'església primitiva",
            "Servidores escogidos en la iglesia primitiva": "Servidors escollits a l'església primitiva",
            "Líderes espirituales del pueblo o de la iglesia": "Referents espirituals del poble o de l'església",
            "Fe basada en Jesucristo y el evangelio": "Fe arrelada en Jesucrist i l'evangeli",
            "Rama principal del cristianismo con centro histórico en Roma": "Tronc principal del cristianisme amb centre històric a Roma",
            "Conjunto de iglesias cristianas surgidas de la Reforma": "Aplec d'esglésies cristianes nascudes de la Reforma",
            "Tradición cristiana histórica de las iglesias ortodoxas": "Herència cristiana històrica de les esglésies ortodoxes",
            "Corriente cristiana centrada en conversión, Biblia y evangelización": "Corrent cristià focalitzat en la conversió, la Bíblia i l'evangelització",
            "Movimiento cristiano que enfatiza la obra del Espíritu Santo": "Corrent cristià que posa l'accent en l'obra de l'Esperit Sant",
            "Religión monoteísta fundada en las enseñanzas de Mahoma": "Religió monoteista fundada en els ensenyaments de Mahoma",
            "Rama mayoritaria del islam": "Branca majoritària de l'islam",
            "Rama principal del islam vinculada a la sucesión de Alí": "Branca principal de l'islam vinculada a la successió d'Alí",
            "Corriente mística dentro del islam": "Corrent mística dins de l'islam",
            "Religión del pueblo judío basada en la Torá": "Religió del poble jueu basada en la Torà",
            "Corriente judía tradicional de estricta observancia": "Corrent jueva tradicional d'estricta observança",
            "Corriente judía de continuidad y adaptación": "Corrent jueva de continuïtat i adaptació",
            "Corriente judía de enfoque más liberal": "Corrent jueu de caire més liberal",
            "Conjunto de tradiciones religiosas originadas en la India": "Aplec de tradicions religioses originades a l'?ndia",
            "Corriente hindú centrada en Vishnu": "Corrent hindú centrada en Vixnu",
            "Corriente hindú centrada en Shiva": "Corrent hindú centrada en Xiva",
            "Corriente hindú centrada en la diosa Shakti": "Corrent hindú centrada en la deessa Shakti",
            "Tradición fundada a partir de las enseñanzas de Buda": "Camí espiritual nascut dels ensenyaments de Buda",
            "Rama budista extendida en el sur de Asia": "Branca budista estesa al sud d'Àsia",
            "Rama budista extendida en Asia oriental": "Branca budista estesa a l'Àsia oriental",
            "Forma budista asociada al Tíbet y regiones cercanas": "Forma budista associada al Tibet i a regions properes",
            "Religión monoteísta originada en el Punjab": "Religió monoteista originada al Panjab",
            "Tradición india centrada en la no violencia y la disciplina": "Tradició índia centrada en la no-violència i la disciplina",
            "Antigua religión persa vinculada a Zaratustra": "Antiga religió persa vinculada a Zaratustra",
            "Religión monoteísta nacida en Persia con vocación universal": "Religió monoteista nascuda a Pèrsia amb vocació universal",
            "Tradición filosófica y ética de origen chino": "Tradició filosòfica i ètica d'origen xinès",
            "Tradición religiosa y filosófica china vinculada al Tao": "Corrent religiosa i filosòfica xinesa vinculada al Tao",
            "Religión tradicional de Japón": "Religió tradicional del Japó",
            "Creencia en espíritus asociados a la naturaleza y los seres": "Creença en esperits associats a la natura i als éssers",
            "Conjunto de prácticas religiosas populares de China": "Conjunt de pràctiques religioses populars de la Xina",
            "Sistemas religiosos aut?ctonos de ?frica": "Sistemes religiosos aut?ctons de l'?frica",
            "Tradiciones espirituales de pueblos originarios de América": "Tradicions espirituals de pobles originaris d'Amèrica",
            "Tradiciones espirituales de pueblos aborígenes": "Tradicions espirituals de pobles aborígens",
            "Religión vietnamita de carácter sincretista": "Religió vietnamita de caràcter sincrètic",
            "Movimiento religioso japonés de origen moderno": "Corrent religiós japonès d'origen modern",
            "Corriente religiosa basada en comunicación con espíritus": "Corrent religiós basat en la comunicació amb esperits",
            "Movimiento religioso surgido en Jamaica": "Corrent religiós sorgit a Jamaica",
            "Movimiento religioso de enfoque pluralista": "Corrent religiós de tarannà pluralista",
            "Tradición cristiana vinculada a La Iglesia de Jesucristo de los Santos de los Últimos Días": "Tradició cristiana vinculada a l'Església de Jesucrist dels Sants dels Últims Dies",
            "Movimiento religioso de interpretación bíblica particular": "Corrent religiós amb una interpretació bíblica particular",
            "Movimiento religioso fundado por Mary Baker Eddy": "Corrent religiós fundat per Mary Baker Eddy",
            "Conjunto de espiritualidades modernas de carácter sincretista": "Conjunt d'espiritualitats modernes de caràcter sincrètic",
            "Recuperación moderna de tradiciones religiosas precristianas": "Recuperació moderna de tradicions religioses precristianes",
            "Tradición neopagana de carácter ritual y dual": "Via neopagana de caràcter ritual i dual",
            "Postura de negación de la existencia de deidades": "Postura de negació de l'existència de divinitats",
            "Postura sobre la imposibilidad o duda de conocer a Dios": "Postura sobre la impossibilitat o el dubte de conèixer Déu",
            "Visión ética no religiosa centrada en el ser humano": "Visió ètica no religiosa centrada en l'ésser humà",
            "Creencia en un creador sin revelación religiosa particular": "Creença en un creador sense revelació religiosa particular",
            "Personas que no se identifican con una religión concreta": "Gent que no s'identifica amb cap religió concreta",
            "Barnabas": "Bernabe", "Boaz": "Booz", "Cain": "Cai¨n", "Cornelio": "Corneli", "Crispo": "Crisp",
            "Efrain": "Efrai¨m", "Elcanah": "Elcana", "Eleazar": "Eleazar", "Eli": "Eli", "Enoc": "Henoc",
            "Ezequias": "Ezequies", "Festo": "Festus", "Filemon": "Filemo", "Finees": "Finees", "Gamaliel": "Gamaliel",
            "Gedeon": "Gedeo", "Heber": "Heber", "Heman": "Heman", "Hermes": "Hermes", "Isacar": "Issacar",
            "Ismael": "Ismael", "Jair": "Jair", "Jefte": "Jefte", "Jesse": "Jesse", "Joab": "Joab",
            "Jonadab": "Jonadab", "Jonathan": "Jonatan", "Josafat": "Josafat", "Justo": "Just", "Laban": "Laban",
            "Lamec": "Lamec", "Lazaro": "Llàtzer", "Levi": "Levi", "Lot": "Lot", "Manases": "Manasses",
            "Mardoqueo": "Mardoqueu", "Matias": "Maties", "Matusalen": "Matusalem", "Mefiboset": "Mefiboset",
            "Micaias": "Micàie`s", "Nahum": "Nahum", "Natan": "Natan", "Natanael": "Natanael", "Nehemias": "Nehemies",
            "Ner": "Ner", "Nicodemo": "Nicodem", "Noe": "Noe", "Obed": "Obed", "Onesimo": "Onesim",
            "Ozias": "Ozies", "Poncio Pilato": "Ponç Pilat", "Procoro": "Procor", "Roboam": "Roboam",
            "Ruben": "Rube`n", "Saul": "Sau¨l", "Sem": "Sem", "Set": "Set", "Sila": "Siles",
            "Silas": "Silas", "Simon de Cirene": "Simo´ de Cirene", "Simeon": "Simeo´", "Sosthenes": "Sostenes",
            "Tadeo": "Tadeu", "Tiquico": "Tiquic", "Tito Justo": "Titus Just", "Tobias": "Tobies",
            "Urias": "Uries", "Uziel": "Uziel", "Zabulon": "Zabulo´", "Zaqueo": "Zaqueu", "Zebedeo": "Zebedeu",
            "Zorobabel": "Zorobabel",
            "Abraham": "Abraham", "Isaac": "Isaac", "Jacob": "Jacob", "Jose": "Josep", "Moises": "Moises",
            "Aaron": "Aaron", "Josue": "Josue", "Samuel": "Samuel", "David": "David", "Salomon": "Salomo",
            "Elias": "Elies", "Eliseo": "Eliseu", "Isaias": "Isaias", "Jeremias": "Jeremies", "Ezequiel": "Ezequiel",
            "Daniel": "Daniel", "Oseas": "Osees", "Joel": "Joel", "Amos": "Amos", "Abdias": "Abdies",
            "Jonas": "Jonas", "Miqueas": "Miquees", "Nahum": "Nahum", "Habacuc": "Habacuc", "Sofonias": "Sofonies",
            "Hageo": "Ageu", "Zacarias": "Zacaries", "Malaquias": "Malaquies", "Juan": "Joan", "Pedro": "Pere",
            "Pablo": "Pau", "Andres": "Andreu", "Felipe": "Felip", "Mateo": "Mateu", "Marcos": "Marc",
            "Lucas": "Lluc", "Santiago": "Jaume", "Tomas": "Tomas", "Timoteo": "Timoteu", "Tito": "Titus",
            "Maria": "Maria", "Maria Magdalena": "Maria Magdalena", "Marta": "Marta", "Lidia": "Lidia",
            "Noe": "Noe", "Eva": "Eva", "Rut": "Rut", "Ester": "Ester", "Debora": "Debora", "Sara": "Sara",
            "Rebeca": "Rebeca", "Raquel": "Raquel", "Miriam": "Miriam", "Hebreos": "Hebreus", "Romanos": "Romans",
            "Egipcios": "Egipcis", "Babilonios": "Babilonis", "Persas": "Perses", "Israelitas": "Israelites",
            "Samaritanos": "Samaritans", "Filisteos": "Filisteus", "Cananeos": "Cananeus", "Amonitas": "Amonites",
            "Moabitas": "Moabites", "Asirios": "Assiris", "Sidonios": "Sidonis", "Fenicios": "Fenicis",
            "Jerusalen": "Jerusalem", "Belen": "Betlem", "Nazaret": "Nazaret", "Galilea": "Galilea",
            "Samaria": "Samaria", "Jerico": "Jerico", "Egipto": "Egipte", "Babilonia": "Babilonia",
            "Damasco": "Damasc", "Atenas": "Atenes", "Corinto": "Corint", "Filipos": "Filips",
            "Macedonia": "Macedonia", "Roma": "Roma", "Joppe": "Jope", "Patmos": "Patmos", "Sion": "Sio",
            "Sinai": "Sinai", "Siria": "Siria", "Persia": "Persia", "Antioquia": "Antioquia", "Cafarnaum": "Cafarnaum",
            "Capernaum": "Cafarnaum", "Getsemani": "Getsemani", "Golgota": "Golgota", "Monte de los Olivos": "Muntanya de les Oliveres",
            "Marcos": "Marc", "Mateo": "Mateu", "Juan el bautista": "Joan Baptista", "Jose de Arimatea": "Josep d'Arimatea",
            "Discipulos": "Deixebles", "Apostoles": "Apostols", "Profetas": "Profetes", "Levitas": "Levites",
            "Sacerdotes": "Sacerdots", "Fariseos": "Fariseus", "Saduceos": "Saduceus", "Escribas": "Escribes",
            "Cristianismo": "Cristianisme",
            "Catolicismo": "Catolicisme",
            "Protestantismo": "Protestantisme",
            "Islam": "Islam",
            "Judaísmo": "Judaisme",
            "Hinduismo": "Hinduisme",
            "Budismo": "Budisme",
            "Sijismo": "Sikhisme",
            "Jainismo": "Jainisme",
            "Zoroastrismo": "Zoroastrisme",
            "Confucianismo": "Confucianisme",
            "Taoismo": "Taoisme",
            "Sintoismo": "Sintoisme",
            "Animismo": "Animisme",
            "Espiritismo": "Espiritisme",
            "Rastafarismo": "Rastafarisme",
            "Mormonismo": "Mormonisme",
            "Ciencia Cristiana": "Ciència Cristiana",
            "Nueva Era": "Nova Era",
            "Neopaganismo": "Neopaganisme",
            "Ateismo": "Ateisme",
            "Agnosticismo": "Agnosticisme",
            "Humanismo secular": "Humanisme secular",
            "Deismo": "Deisme",
            "Sin afiliacion religiosa": "Sense afiliacio religiosa",
        },
        "fr": {
            "Adoradores": "Adorateurs", "Agarenos": "Agareniens", "Amos de casa": "Chefs de maison", "Ancianos": "Anciens",
            "Apostoles": "Apôtres", "Arqueros": "Archers", "Asambleas": "Assemblees", "Cantores": "Chantres",
            "Carceleros": "Geoliers", "Celotes": "Zelotes", "Centuriones": "Centurions", "Concilios": "Conciles",
            "Consejeros": "Conseillers", "Constructores": "Constructeurs", "Cortesanos": "Courtisans", "Creyentes": "Croyants",
            "Desterrados": "Bannis", "Diaconos": "Diacres", "Discipulos": "Disciples", "Doce tribus": "Douze tribus",
            "Doctores de la Ley": "Docteurs de la Loi", "Endemoniados": "Possedes", "Enfermos": "Malades",
            "Escribas": "Scribes", "Esenios": "Esseniens", "Exiliados": "Exiles", "Extranjeros": "Etrangers",
            "Familias sacerdotales": "Familles sacerdotales", "Fariseos": "Pharisiens", "Gentiles": "Paiens",
            "Guardianes de la puerta": "Gardiens de la porte", "Helenistas": "Hellenistes", "Herodianos": "Herodiens",
            "Hijas de Sion": "Filles de Sion", "Huerfanos": "Orphelins", "Jefes de millares": "Chefs de milliers",
            "Jovenes": "Jeunes", "Judios": "Juifs", "Jueces": "Juges", "Levitas": "Levites",
            "Magos de Oriente": "Mages d'Orient", "Mercaderes": "Marchands", "Mujeres esteriles": "Femmes steriles",
            "Murmuradores": "Murmurateurs", "Nazareos": "Nazireens", "Nobles": "Nobles", "Obreros": "Ouvriers",
            "Ovejas perdidas": "Brebis perdues", "Pastoreadores": "Bergers", "Pecadores": "Pecheurs",
            "Peregrinos": "Pelerins", "Pescadores": "Pecheurs", "Porteros": "Portiers", "Presos": "Prisonniers",
            "Profetas": "Prophetes", "Prosélitos": "Proselytes", "Publicanos": "Publicains", "Recaudadores": "Collecteurs d'impots",
            "Rechazados": "Rejetes", "Remanente": "Reste fidele", "Reyes de la tierra": "Rois de la terre",
            "Sacerdotes": "Pretres", "Saduceos": "Sadduceens", "Samaritanos piadosos": "Samaritains compatissants",
            "Sanedrin": "Sanhedrin", "Siervas": "Servantes", "Soldados": "Soldats", "Sumos sacerdotes": "Souverains sacrificateurs",
            "Trabajadores de la mies": "Ouvriers de la moisson", "Viudas": "Veuves",
            "Amalecitas": "Amalecites", "Amonitas": "Ammonites", "Amorreos": "Amorites", "Arameos": "Arameens",
            "Asirios": "Assyriens", "Babilonios": "Babyloniens", "Caldeos": "Chaldeens", "Cananeos": "Cananeens",
            "Cretenses": "Cretois", "Cusitas": "Koushites", "Danitas": "Danites", "Egipcios": "Egyptiens",
            "Edomitas": "Edomites", "Elamitas": "Elamites", "Efraimitas": "Ephraimites", "Fenicios": "Pheniciens",
            "Filisteos": "Philistins", "Gabaonitas": "Gabaonites", "Gergeseos": "Gergeseens", "Gesureos": "Gueshouriens",
            "Hebreos": "Hebreux", "Hititas": "Hittites", "Hivitas": "Hivviens", "Horitas": "Horites",
            "Hurritas": "Hourrites", "Israelitas": "Israelites", "Jebuseos": "Jebuseens", "Lidios": "Lydiens",
            "Madianitas": "Madianites", "Medianitas": "Medes", "Mesec": "Meshec", "Moabitas": "Moabites",
            "Ninivitas": "Ninivites", "Partos": "Parthes", "Persas": "Perses", "Romanos": "Romains",
            "Samaritanos": "Samaritains", "Sidonios": "Sidoniens", "Sirios": "Syriens", "Sumerios": "Sumeriens",
            "Tarsenses": "Tarsiens", "Tribus de Israel": "Tribus d'Israel",
            "Ararat": "Ararat", "Atenas": "Athenes", "Beerseba": "Beer-Sheba", "Belén": "Bethleem", "Betania": "Bethanie",
            "Betel": "Bethel", "Betesda": "Bethesda", "Cana": "Cana", "Canaán": "Canaan", "Carmelo": "Carmel",
            "Cesarea": "Cesaree", "Cesarea de Filipo": "Cesaree de Philippe", "Corinto": "Corinthe", "Creta": "Crete",
            "Damasco": "Damas", "Decápolis": "Decapole", "Emaús": "Emmaus", "Esmirna": "Smyrne",
            "Filipos": "Philippes", "Getsemani": "Gethsemane", "Golgota": "Golgotha", "Gosen": "Goshen", "Hebron": "Hebron",
            "Horeb": "Horeb", "Jordan": "Jourdain", "Laodicea": "Laodicee", "Listra": "Lystre", "Magdala": "Magdala",
            "Madian": "Madian", "Monte de los Olivos": "Mont des Oliviers", "Nazaret": "Nazareth",
            "Patmos": "Patmos", "Penuel": "Peniel", "Pisidia": "Pisidie", "Ponto": "Pont", "Rama": "Rama",
            "Rameses": "Ramses", "Sardis": "Sardes", "Sarepta": "Sarepta", "Sichem": "Sichem", "Silo": "Silo",
            "Sinai": "Sinai", "Sion": "Sion", "Siria": "Syrie", "Susa": "Suse", "Tarsis": "Tarsis",
            "Tiatira": "Thyatire", "Tiro": "Tyr", "Troas": "Troas", "Ur": "Ur", "Zoar": "Tsoar",
            "Budismo mahayana": "Bouddhisme mahayana", "Budismo theravada": "Bouddhisme theravada", "Budismo vajrayana": "Bouddhisme vajrayana",
            "Chiismo": "Chiisme", "Evangelicalismo": "Evangelicalisme", "Judaísmo conservador": "Judaisme conservateur",
            "Judaísmo ortodoxo": "Judaisme orthodoxe", "Judaísmo reformista": "Judaisme reforme",
            "Ortodoxia oriental": "Orthodoxie orientale", "Pentecostalismo": "Pentecôtisme", "Shaivismo": "Shaivisme",
            "Shaktismo": "Shaktisme", "Sufismo": "Soufisme", "Sunismo": "Sunnisme", "Tenrikyo": "Tenrikyo",
            "Testigos de Jehova": "Temoins de Jehovah", "Tradiciones chinas": "Traditions chinoises",
            "Unitarios universalistas": "Unitariens universalistes", "Vaishnavismo": "Vaishnavisme", "Wicca": "Wicca",
            "Bahaismo": "Bahaisme", "Caodaísmo": "Caodaisme", "Religiones africanas tradicionales": "Religions africaines traditionnelles",
            "Religiones indígenas americanas": "Religions autochtones americaines", "Religiones indígenas australianas": "Religions autochtones australiennes",
            "Abigail": "Abigail", "Abisag": "Abishag", "Abital": "Abital", "Acsa": "Acsa", "Ada": "Ada",
            "Ana": "Anne", "Apphia": "Apphia", "Asenat": "Asnath", "Atalia": "Athalie", "Batseba": "Bath-Shéba",
            "Candace": "Candace", "Claudia": "Claudia", "Cloe": "Chloe", "Dalila": "Dalila", "Damaris": "Damaris",
            "Dorcas": "Dorcas", "Elisabet": "Elisabeth", "Eunice": "Eunice", "Febe": "Phebe", "Hagar": "Agar",
            "Herodias": "Herodiade", "Hulda": "Houlda", "Jael": "Jael", "Jezabel": "Jezabel", "Jocabed": "Jokebed",
            "Julia": "Julia", "Junia": "Junia", "Keturah": "Qetura", "Lia": "Lea", "Loida": "Lois",
            "Maria de Cleofas": "Marie de Cléophas", "Merab": "Merab", "Mical": "Mical", "Milca": "Milca",
            "Noemi": "Noémi", "Orfa": "Orpa", "Penina": "Peninna", "Persida": "Persis", "Priscila": "Priscille",
            "Pua": "Pua", "Rahab": "Rahab", "Reina de Saba": "Reine de Saba", "Rizpa": "Ritspa", "Rode": "Rhode",
            "Safira": "Saphira", "Salome": "Salomé", "Sara": "Sara", "Sefora": "Séphora", "Sifra": "Shiphra",
            "Susana": "Suzanne", "Tabita": "Tabitha", "Tamar": "Tamar", "Vasti": "Vasthi", "Mujer cananea": "Femme cananéenne",
            "Mujer samaritana": "Femme samaritaine", "Mujer sirofenicia": "Femme syro-phoenicienne", "Mujer de Lot": "Femme de Lot",
            "Mujer de Job": "Femme de Job", "Mujer de Manoa": "Femme de Manoach", "Mujer de Potifar": "Femme de Potiphar",
            "Mujer encorvada": "Femme courbée", "Mujer del flujo de sangre": "Femme atteinte d'une perte de sang",
            "Mujer sabia de Abel": "Femme sage d'Abel", "Mujer sabia de Tecoa": "Femme sage de Tekoa",
            "Mujer sorprendida en adulterio": "Femme surprise en adultère", "Mujer sunamita": "Femme de Sunem",
            "Viuda de Nain": "Veuve de Nain", "Viuda de Sarepta": "Veuve de Sarepta", "Viuda pobre del templo": "Pauvre veuve du temple",
            "Mujer vinculada a la muerte de Juan el Bautista": "Femme liée à la mort de Jean-Baptiste",
            "Compañera de prisiones de Pablo": "Compagne d'emprisonnement de Paul",
            "Hija simbólica de Oseas": "Fille symbolique dans Osée",
            "Sierva que reconoció a Pedro": "Servante qui reconnut Pierre",
            "Alimentada en tiempos de Elías": "Nourrie au temps d'Élie",
            "Judío elocuente y poderoso en las Escrituras": "Juif éloquent et puissant dans les Écritures",
            "Judio elocuente y poderoso en las Escrituras": "Juif éloquent et puissant dans les Écritures",
            "Maestro de la Ley entre los fariseos": "Maître de la Loi parmi les pharisiens",
            "Reconstruyó los muros de Jerusalén": "Reconstruisit les murailles de Jérusalem",
            "Reconstruyo los muros de Jerusalén": "Reconstruisit les murailles de Jérusalem",
            "Reconstruyó los muros de Jerusalen": "Reconstruisit les murailles de Jérusalem",
            "Reconstruyo los muros de Jerusalen": "Reconstruisit les murailles de Jérusalem",
            "Siervo mencionado por Pablo": "Serviteur mentionné par Paul",
            "Siervo etíope que ayudó a Jeremías": "Serviteur éthiopien qui aida Jérémie",
            "Siervo etiope que ayudó a Jeremías": "Serviteur éthiopien qui aida Jérémie",
            "Siervo etíope que ayudo a Jeremías": "Serviteur éthiopien qui aida Jérémie",
            "Siervo etiope que ayudo a Jeremías": "Serviteur éthiopien qui aida Jérémie",
            "Siervo etíope que ayudó a Jeremias": "Serviteur éthiopien qui aida Jérémie",
            "Siervo etiope que ayudó a Jeremias": "Serviteur éthiopien qui aida Jérémie",
            "Siervo etíope que ayudo a Jeremias": "Serviteur éthiopien qui aida Jérémie",
            "Siervo etiope que ayudo a Jeremias": "Serviteur éthiopien qui aida Jérémie",
            "Personas entregadas a alabar y honrar a Dios": "Personnes consacrées à louer et honorer Dieu",
            "Pueblo mencionado en conflictos del Antiguo Testamento": "Peuple mentionné dans les conflits de l'Ancien Testament",
            "Responsables del hogar en distintos relatos bíblicos": "Responsables du foyer dans différents récits bibliques",
            "Guerreros armados con arco en batallas bíblicas": "Guerriers armés d'arcs dans des batailles bibliques",
            "Reuniones del pueblo para escuchar la Ley o adorar": "Assemblées du peuple pour écouter la Loi ou adorer",
            "Ministros dedicados al canto en el templo": "Ministres consacrés au chant dans le temple",
            "Encargados de prisiones, como en el libro de Hechos": "Responsables des prisons, comme dans le livre des Actes",
            "Oficiales romanos mencionados varias veces en el Nuevo Testamento": "Officiers romains mentionnés à plusieurs reprises dans le Nouveau Testament",
            "Reuniones de líderes para tratar asuntos del pueblo o de la iglesia": "Réunions de dirigeants pour traiter les affaires du peuple ou de l'Église",
            "Personas que orientaban a reyes o líderes": "Personnes qui conseillaient des rois ou des dirigeants",
            "Obreros implicados en murallas, ciudades o el templo": "Ouvriers impliqués dans les murailles, les villes ou le temple",
            "Servidores de palacio en reinos bíblicos": "Serviteurs de palais dans les royaumes bibliques",
            "Personas que han respondido con fe al mensaje de Dios": "Personnes ayant répondu avec foi au message de Dieu",
            "Exiliados fuera de su tierra por juicio o guerra": "Exilés hors de leur terre à cause du jugement ou de la guerre",
            "Conjunto del pueblo de Israel descendiente de Jacob": "Ensemble du peuple d'Israël descendant de Jacob",
            "Expertos en la interpretación de la Ley mosaica": "Experts dans l'interprétation de la Loi mosaïque",
            "Personas oprimidas por espíritus malignos en los Evangelios": "Personnes opprimées par des esprits mauvais dans les Évangiles",
            "Grupo frecuentemente atendido con compasión y milagros": "Groupe souvent pris en charge avec compassion et miracles",
            "Pueblo llevado cautivo fuera de Israel y Judá": "Peuple emmené en captivité hors d'Israël et de Juda",
            "Personas de otras naciones presentes entre el pueblo": "Personnes d'autres nations présentes parmi le peuple",
            "Linajes apartados para el servicio del templo": "Lignées mises à part pour le service du temple",
            "Responsables del acceso y orden en el templo": "Responsables de l'accès et de l'ordre dans le temple",
            "Expresión poética para referirse al pueblo de Jerusalén": "Expression poétique pour désigner le peuple de Jérusalem",
            "Grupo vulnerable protegido en la Ley y los profetas": "Groupe vulnérable protégé dans la Loi et les prophètes",
            "Líderes militares y administrativos de Israel": "Chefs militaires et administratifs d'Israël",
            "Grupo mencionado en exhortaciones, guerras y discipulado": "Groupe mentionné dans les exhortations, les guerres et le discipulat",
            "Líderes levantados por Dios para gobernar y liberar a Israel": "Chefs suscités par Dieu pour gouverner et délivrer Israël",
            "Sabios que visitaron a Jesús tras su nacimiento": "Sages qui visitèrent Jésus après sa naissance",
            "Comerciantes presentes en ciudades y rutas bíblicas": "Marchands présents dans les villes et sur les routes bibliques",
            "Mujeres que vivieron la espera de un hijo con fe y dolor": "Femmes qui vécurent l'attente d'un enfant avec foi et douleur",
            "Grupo que protesta contra Dios o sus siervos": "Groupe qui proteste contre Dieu ou ses serviteurs",
            "Personas consagradas a Dios mediante voto especial": "Personnes consacrées à Dieu par un voeu spécial",
            "Miembros influyentes del pueblo o de la corte": "Membres influents du peuple ou de la cour",
            "Trabajadores del campo, la construcción o la mies espiritual": "Travailleurs des champs, de la construction ou de la moisson spirituelle",
            "Imagen del pueblo descarriado necesitado de pastor": "Image du peuple égaré ayant besoin d'un berger",
            "Encargados de cuidar rebaños en la vida cotidiana bíblica": "Responsables des troupeaux dans la vie quotidienne biblique",
            "Término frecuente para quienes necesitan arrepentimiento y gracia": "Terme fréquent pour ceux qui ont besoin de repentance et de grâce",
            "Personas de paso o en viaje hacia lugares santos": "Personnes de passage ou en route vers des lieux saints",
            "Oficio común en Galilea y entre varios discípulos": "Métier courant en Galilée et parmi plusieurs disciples",
            "Servidores asignados al cuidado de entradas y espacios sagrados": "Serviteurs chargés de veiller sur les entrées et les espaces sacrés",
            "Personas encarceladas por delitos, injusticia o causa del Evangelio": "Personnes emprisonnées pour des crimes, l'injustice ou à cause de l'Évangile",
            "Gentiles incorporados a la fe judía": "Païens intégrés à la foi juive",
            "Funcionarios que cobraban tributos e impuestos": "Fonctionnaires chargés de percevoir tributs et impôts",
            "Personas marginadas social o religiosamente": "Personnes marginalisées socialement ou religieusement",
            "Gobernantes de naciones en pasajes históricos y proféticos": "Souverains des nations dans des passages historiques et prophétiques",
            "Grupo fiel preservado por Dios en tiempos de crisis": "Groupe fidèle préservé par Dieu en temps de crise",
            "Referencia a quienes actúan con misericordia inesperada": "Référence à ceux qui agissent avec une miséricorde inattendue",
            "Mujeres al servicio de hogares o familias": "Femmes au service des foyers ou des familles",
            "Militares presentes en historias del Antiguo y Nuevo Testamento": "Militaires présents dans les récits de l'Ancien et du Nouveau Testament",
            "Imagen de quienes sirven en la obra de Dios": "Image de ceux qui servent dans l'oeuvre de Dieu",
            "Grupo religioso influyente en tiempos de Jesús": "Groupe religieux influent au temps de Jésus",
            "Grupo sacerdotal y político del judaísmo": "Groupe sacerdotal et politique du judaïsme",
            "Intérpretes y maestros de la Ley": "Interprètes et maîtres de la Loi",
            "Partidarios de la casa de Herodes": "Partisans de la maison d'Hérode",
            "Movimiento judío de fuerte fervor nacional": "Mouvement juif de fort zèle national",
            "Comunidad judía asociada a vida apartada": "Communauté juive associée à une vie séparée",
            "Cobradores de impuestos en tiempos de Roma": "Percepteurs d'impôts à l'époque romaine",
            "Tribu dedicada al servicio del templo": "Tribu consacrée au service du temple",
            "Encargados del culto en Israel": "Responsables du culte en Israël",
            "Máxima autoridad sacerdotal": "Plus haute autorité sacerdotale",
            "Consejo religioso judío": "Conseil religieux juif",
            "Seguidores y aprendices de Jesús": "Disciples et apprentis de Jésus",
            "Enviados escogidos por Jesús": "Envoyés choisis par Jésus",
            "Portavoces del mensaje de Dios": "Porte-parole du message de Dieu",
            "Pueblos no judíos": "Peuples non juifs",
            "Pueblo del pacto en tiempos bíblicos": "Peuple de l'alliance dans les temps bibliques",
            "Judíos de lengua griega mencionados en Hechos": "Juifs de langue grecque mentionnés dans les Actes",
            "Grupo vulnerable atendido por la iglesia primitiva": "Groupe vulnérable pris en charge par l'Église primitive",
            "Servidores escogidos en la iglesia primitiva": "Serviteurs choisis dans l'Église primitive",
            "Líderes espirituales del pueblo o de la iglesia": "Dirigeants spirituels du peuple ou de l'Église",
            "Fe basada en Jesucristo y el evangelio": "Foi fondée sur Jésus-Christ et l'Évangile",
            "Rama principal del cristianismo con centro histórico en Roma": "Branche principale du christianisme ayant son centre historique à Rome",
            "Conjunto de iglesias cristianas surgidas de la Reforma": "Ensemble d'Églises chrétiennes issues de la Réforme",
            "Tradición cristiana histórica de las iglesias ortodoxas": "Tradition chrétienne historique des Églises orthodoxes",
            "Corriente cristiana centrada en conversión, Biblia y evangelización": "Courant chrétien centré sur la conversion, la Bible et l'évangélisation",
            "Movimiento cristiano que enfatiza la obra del Espíritu Santo": "Mouvement chrétien qui met l'accent sur l'oeuvre du Saint-Esprit",
            "Religión monoteísta fundada en las enseñanzas de Mahoma": "Religion monothéiste fondée sur les enseignements de Mahomet",
            "Rama mayoritaria del islam": "Branche majoritaire de l'islam",
            "Rama principal del islam vinculada a la sucesión de Alí": "Branche principale de l'islam liée à la succession d'Ali",
            "Corriente mística dentro del islam": "Courant mystique au sein de l'islam",
            "Religión del pueblo judío basada en la Torá": "Religion du peuple juif fondée sur la Torah",
            "Corriente judía tradicional de estricta observancia": "Courant juif traditionnel de stricte observance",
            "Corriente judía de continuidad y adaptación": "Courant juif de continuité et d'adaptation",
            "Corriente judía de enfoque más liberal": "Courant juif d'approche plus libérale",
            "Conjunto de tradiciones religiosas originadas en la India": "Ensemble de traditions religieuses originaires de l'Inde",
            "Corriente hindú centrada en Vishnu": "Courant hindou centré sur Vishnou",
            "Corriente hindú centrada en Shiva": "Courant hindou centré sur Shiva",
            "Corriente hindú centrada en la diosa Shakti": "Courant hindou centré sur la déesse Shakti",
            "Tradición fundada a partir de las enseñanzas de Buda": "Tradition fondée à partir des enseignements de Bouddha",
            "Rama budista extendida en el sur de Asia": "Branche bouddhiste répandue en Asie du Sud",
            "Rama budista extendida en Asia oriental": "Branche bouddhiste répandue en Asie orientale",
            "Forma budista asociada al Tíbet y regiones cercanas": "Forme bouddhiste associée au Tibet et aux régions voisines",
            "Religión monoteísta originada en el Punjab": "Religion monothéiste née au Pendjab",
            "Tradición india centrada en la no violencia y la disciplina": "Tradition indienne centrée sur la non-violence et la discipline",
            "Antigua religión persa vinculada a Zaratustra": "Ancienne religion perse liée à Zoroastre",
            "Religión monoteísta nacida en Persia con vocación universal": "Religion monothéiste née en Perse à vocation universelle",
            "Tradición filosófica y ética de origen chino": "Tradition philosophique et éthique d'origine chinoise",
            "Tradición religiosa y filosófica china vinculada al Tao": "Tradition religieuse et philosophique chinoise liée au Tao",
            "Religión tradicional de Japón": "Religion traditionnelle du Japon",
            "Creencia en espíritus asociados a la naturaleza y los seres": "Croyance en des esprits associés à la nature et aux êtres",
            "Conjunto de prácticas religiosas populares de China": "Ensemble de pratiques religieuses populaires de Chine",
            "Sistemas religiosos aut?ctonos de ?frica": "Syst?mes religieux autochtones d'Afrique",
            "Tradiciones espirituales de pueblos originarios de América": "Traditions spirituelles des peuples autochtones d'Amérique",
            "Tradiciones espirituales de pueblos aborígenes": "Traditions spirituelles des peuples autochtones d'Australie",
            "Religión vietnamita de carácter sincretista": "Religion vietnamienne de caractère syncrétique",
            "Movimiento religioso japonés de origen moderno": "Mouvement religieux japonais d'origine moderne",
            "Corriente religiosa basada en comunicación con espíritus": "Courant religieux fondé sur la communication avec les esprits",
            "Movimiento religioso surgido en Jamaica": "Mouvement religieux né en Jamaïque",
            "Movimiento religioso de enfoque pluralista": "Mouvement religieux d'approche pluraliste",
            "Tradición cristiana vinculada a La Iglesia de Jesucristo de los Santos de los Últimos Días": "Tradition chrétienne liée à l'Église de Jésus-Christ des Saints des Derniers Jours",
            "Movimiento religioso de interpretación bíblica particular": "Mouvement religieux à l'interprétation biblique particulière",
            "Movimiento religioso fundado por Mary Baker Eddy": "Mouvement religieux fondé par Mary Baker Eddy",
            "Conjunto de espiritualidades modernas de carácter sincretista": "Ensemble de spiritualités modernes à caractère syncrétique",
            "Recuperación moderna de tradiciones religiosas precristianas": "Récupération moderne de traditions religieuses préchrétiennes",
            "Tradición neopagana de carácter ritual y dual": "Tradition néopaïenne de caractère rituel et dual",
            "Postura de negación de la existencia de deidades": "Position niant l'existence de divinités",
            "Postura sobre la imposibilidad o duda de conocer a Dios": "Position sur l'impossibilité ou le doute de connaître Dieu",
            "Visión ética no religiosa centrada en el ser humano": "Vision éthique non religieuse centrée sur l'être humain",
            "Creencia en un creador sin revelación religiosa particular": "Croyance en un créateur sans révélation religieuse particulière",
            "Personas que no se identifican con una religión concreta": "Personnes qui ne s'identifient à aucune religion particulière",
            "Barnabas": "Barnabas", "Boaz": "Boaz", "Cain": "Cain", "Cornelio": "Corneille", "Crispo": "Crispus",
            "Efrain": "Ephraim", "Elcanah": "Elqana", "Eleazar": "Eleazar", "Eli": "Eli", "Enoc": "Enoch",
            "Ezequias": "Ezechias", "Festo": "Festus", "Filemon": "Philemon", "Finees": "Phinees", "Gamaliel": "Gamaliel",
            "Gedeon": "Gedeon", "Heber": "Heber", "Heman": "Heman", "Hermes": "Hermes", "Isacar": "Issacar",
            "Ismael": "Ismael", "Jair": "Jair", "Jefte": "Jephte", "Jesse": "Isai", "Joab": "Joab",
            "Jonadab": "Jonadab", "Jonathan": "Jonathan", "Josafat": "Josaphat", "Justo": "Justus", "Laban": "Laban",
            "Lamec": "Lamek", "Lazaro": "Lazare", "Levi": "Levi", "Lot": "Lot", "Manases": "Manasse",
            "Mardoqueo": "Mardochee", "Matias": "Matthias", "Matusalen": "Methuselah", "Mefiboset": "Mephibosheth",
            "Micaias": "Michee", "Nahum": "Nahum", "Natan": "Nathan", "Natanael": "Nathanael", "Nehemias": "Nehemie",
            "Ner": "Ner", "Nicodemo": "Nicodeme", "Noe": "Noe", "Obed": "Obed", "Onesimo": "Onesime",
            "Ozias": "Ozias", "Poncio Pilato": "Ponce Pilate", "Procoro": "Prochore", "Roboam": "Roboam",
            "Ruben": "Ruben", "Saul": "Saul", "Sem": "Sem", "Set": "Seth", "Sila": "Silas",
            "Silas": "Silas", "Simon de Cirene": "Simon de Cyrene", "Simeon": "Simeon", "Sosthenes": "Sosthene",
            "Tadeo": "Thaddee", "Tiquico": "Tychique", "Tito Justo": "Titius Justus", "Tobias": "Tobie",
            "Urias": "Urie", "Uziel": "Uzziel", "Zabulon": "Zabulon", "Zaqueo": "Zachee", "Zebedeo": "Zebedee",
            "Zorobabel": "Zorobabel",
            "Abraham": "Abraham", "Isaac": "Isaac", "Jacob": "Jacob", "Jose": "Joseph", "Moises": "Moise",
            "Aaron": "Aaron", "Josue": "Josue", "Samuel": "Samuel", "David": "David", "Salomon": "Salomon",
            "Elias": "Elie", "Eliseo": "Elisee", "Isaias": "Esaie", "Jeremias": "Jeremie", "Ezequiel": "Ezechiel",
            "Daniel": "Daniel", "Oseas": "Osee", "Joel": "Joel", "Amos": "Amos", "Abdias": "Abdias",
            "Jonas": "Jonas", "Miqueas": "Michee", "Nahum": "Nahum", "Habacuc": "Habacuc", "Sofonias": "Sophonie",
            "Hageo": "Aggee", "Zacarias": "Zacharie", "Malaquias": "Malachie", "Juan": "Jean", "Pedro": "Pierre",
            "Pablo": "Paul", "Andres": "Andre", "Felipe": "Philippe", "Mateo": "Matthieu", "Marcos": "Marc",
            "Lucas": "Luc", "Santiago": "Jacques", "Tomas": "Thomas", "Timoteo": "Timothee", "Tito": "Tite",
            "Maria": "Marie", "Maria Magdalena": "Marie Madeleine", "Marta": "Marthe", "Lidia": "Lydie",
            "Noe": "Noe", "Eva": "Eve", "Rut": "Ruth", "Ester": "Esther", "Debora": "Debora", "Sara": "Sara",
            "Rebeca": "Rebecca", "Raquel": "Rachel", "Miriam": "Miriam", "Hebreos": "Hebreux", "Romanos": "Romains",
            "Egipcios": "Egyptiens", "Babilonios": "Babyloniens", "Persas": "Perses", "Israelitas": "Israelites",
            "Samaritanos": "Samaritains", "Filisteos": "Philistins", "Cananeos": "Cananeens", "Amonitas": "Ammonites",
            "Moabitas": "Moabites", "Asirios": "Assyriens", "Sidonios": "Sidoniens", "Fenicios": "Pheniciens",
            "Jerusalen": "Jerusalem", "Belen": "Bethleem", "Nazaret": "Nazareth", "Galilea": "Galilee",
            "Samaria": "Samarie", "Jerico": "Jericho", "Egipto": "Egypte", "Babilonia": "Babylone",
            "Damasco": "Damas", "Atenas": "Athenes", "Corinto": "Corinthe", "Filipos": "Philippes",
            "Macedonia": "Macedoine", "Roma": "Rome", "Joppe": "Joppe", "Patmos": "Patmos", "Sion": "Sion",
            "Sinai": "Sinai", "Siria": "Syrie", "Persia": "Perse", "Antioquia": "Antioche", "Cafarnaum": "Capernaum",
            "Capernaum": "Capernaum", "Getsemani": "Gethsemane", "Golgota": "Golgotha", "Monte de los Olivos": "Mont des Oliviers",
            "Juan el bautista": "Jean-Baptiste", "Jose de Arimatea": "Joseph d'Arimathee",
            "Discipulos": "Disciples", "Apostoles": "Apôtres", "Profetas": "Prophetes", "Levitas": "Levites",
            "Sacerdotes": "Pretres", "Fariseos": "Pharisiens", "Saduceos": "Sadduceens", "Escribas": "Scribes",
            "Cristianismo": "Christianisme",
            "Catolicismo": "Catholicisme",
            "Protestantismo": "Protestantisme",
            "Islam": "Islam",
            "Judaísmo": "Judaisme",
            "Hinduismo": "Hindouisme",
            "Budismo": "Bouddhisme",
            "Sijismo": "Sikhisme",
            "Jainismo": "Jainisme",
            "Zoroastrismo": "Zoroastrisme",
            "Confucianismo": "Confucianisme",
            "Taoismo": "Taoisme",
            "Sintoismo": "Shintoisme",
            "Animismo": "Animisme",
            "Espiritismo": "Spiritisme",
            "Rastafarismo": "Rastafarisme",
            "Mormonismo": "Mormonisme",
            "Ciencia Cristiana": "Science chretienne",
            "Nueva Era": "Nouvel Age",
            "Neopaganismo": "Neopaganisme",
            "Ateismo": "Atheisme",
            "Agnosticismo": "Agnosticisme",
            "Humanismo secular": "Humanisme seculier",
            "Deismo": "Deisme",
            "Sin afiliacion religiosa": "Sans affiliation religieuse",
        },
        "en": {
            "Adoradores": "Worshipers", "Agarenos": "Hagarenes", "Amos de casa": "Heads of household", "Ancianos": "Elders",
            "Apostoles": "Apostles", "Arqueros": "Archers", "Asambleas": "Assemblies", "Cantores": "Singers",
            "Carceleros": "Jailers", "Celotes": "Zealots", "Centuriones": "Centurions", "Concilios": "Councils",
            "Consejeros": "Counselors", "Constructores": "Builders", "Cortesanos": "Courtiers", "Creyentes": "Believers",
            "Desterrados": "Exiles", "Diaconos": "Deacons", "Discipulos": "Disciples", "Doce tribus": "Twelve tribes",
            "Doctores de la Ley": "Teachers of the Law", "Endemoniados": "Demon-possessed people", "Enfermos": "The sick",
            "Escribas": "Scribes", "Esenios": "Essenes", "Exiliados": "Exiles", "Extranjeros": "Foreigners",
            "Familias sacerdotales": "Priestly families", "Fariseos": "Pharisees", "Gentiles": "Gentiles",
            "Guardianes de la puerta": "Gatekeepers", "Helenistas": "Hellenists", "Herodianos": "Herodians",
            "Hijas de Sion": "Daughters of Zion", "Huerfanos": "Orphans", "Jefes de millares": "Commanders of thousands",
            "Jovenes": "Young people", "Judios": "Jews", "Jueces": "Judges", "Levitas": "Levites",
            "Magos de Oriente": "Wise men from the East", "Mercaderes": "Merchants", "Mujeres esteriles": "Barren women",
            "Murmuradores": "Grumblers", "Nazareos": "Nazirites", "Nobles": "Nobles", "Obreros": "Workers",
            "Ovejas perdidas": "Lost sheep", "Pastoreadores": "Shepherds", "Pecadores": "Sinners",
            "Peregrinos": "Pilgrims", "Pescadores": "Fishermen", "Porteros": "Doorkeepers", "Presos": "Prisoners",
            "Profetas": "Prophets", "Prosélitos": "Proselytes", "Publicanos": "Tax collectors", "Recaudadores": "Collectors",
            "Rechazados": "Outcasts", "Remanente": "Remnant", "Reyes de la tierra": "Kings of the earth",
            "Sacerdotes": "Priests", "Saduceos": "Sadducees", "Samaritanos piadosos": "Compassionate Samaritans",
            "Sanedrin": "Sanhedrin", "Siervas": "Female servants", "Soldados": "Soldiers", "Sumos sacerdotes": "Chief priests",
            "Trabajadores de la mies": "Workers in the harvest", "Viudas": "Widows",
            "Amalecitas": "Amalekites", "Amonitas": "Ammonites", "Amorreos": "Amorites", "Arameos": "Arameans",
            "Asirios": "Assyrians", "Babilonios": "Babylonians", "Caldeos": "Chaldeans", "Cananeos": "Canaanites",
            "Cretenses": "Cretans", "Cusitas": "Cushites", "Danitas": "Danites", "Egipcios": "Egyptians",
            "Edomitas": "Edomites", "Elamitas": "Elamites", "Efraimitas": "Ephraimites", "Fenicios": "Phoenicians",
            "Filisteos": "Philistines", "Gabaonitas": "Gibeonites", "Gergeseos": "Gergesenes", "Gesureos": "Geshurites",
            "Hebreos": "Hebrews", "Hititas": "Hittites", "Hivitas": "Hivites", "Horitas": "Horites",
            "Hurritas": "Hurrians", "Israelitas": "Israelites", "Jebuseos": "Jebusites", "Lidios": "Lydians",
            "Madianitas": "Midianites", "Medianitas": "Medes", "Mesec": "Meshech", "Moabitas": "Moabites",
            "Ninivitas": "Ninevites", "Partos": "Parthians", "Persas": "Persians", "Romanos": "Romans",
            "Samaritanos": "Samaritans", "Sidonios": "Sidonians", "Sirios": "Syrians", "Sumerios": "Sumerians",
            "Tarsenses": "People of Tarsus", "Tribus de Israel": "Tribes of Israel",
            "Ararat": "Ararat", "Atenas": "Athens", "Beerseba": "Beersheba", "Belén": "Bethlehem", "Betania": "Bethany",
            "Betel": "Bethel", "Betesda": "Bethesda", "Cana": "Cana", "Canaán": "Canaan", "Carmelo": "Carmel",
            "Cesarea": "Caesarea", "Cesarea de Filipo": "Caesarea Philippi", "Corinto": "Corinth", "Creta": "Crete",
            "Damasco": "Damascus", "Decápolis": "Decapolis", "Emaús": "Emmaus", "Esmirna": "Smyrna",
            "Filipos": "Philippi", "Getsemani": "Gethsemane", "Golgota": "Golgotha", "Gosen": "Goshen", "Hebron": "Hebron",
            "Horeb": "Horeb", "Jordan": "Jordan", "Laodicea": "Laodicea", "Listra": "Lystra", "Magdala": "Magdala",
            "Madian": "Midian", "Monte de los Olivos": "Mount of Olives", "Nazaret": "Nazareth",
            "Patmos": "Patmos", "Penuel": "Peniel", "Pisidia": "Pisidia", "Ponto": "Pontus", "Rama": "Ramah",
            "Rameses": "Rameses", "Sardis": "Sardis", "Sarepta": "Zarephath", "Sichem": "Shechem", "Silo": "Shiloh",
            "Sinai": "Sinai", "Sion": "Zion", "Siria": "Syria", "Susa": "Susa", "Tarsis": "Tarshish",
            "Tiatira": "Thyatira", "Tiro": "Tyre", "Troas": "Troas", "Ur": "Ur", "Zoar": "Zoar",
            "Budismo mahayana": "Mahayana Buddhism", "Budismo theravada": "Theravada Buddhism", "Budismo vajrayana": "Vajrayana Buddhism",
            "Chiismo": "Shia Islam", "Evangelicalismo": "Evangelicalism", "Judaísmo conservador": "Conservative Judaism",
            "Judaísmo ortodoxo": "Orthodox Judaism", "Judaísmo reformista": "Reform Judaism",
            "Ortodoxia oriental": "Eastern Orthodoxy", "Pentecostalismo": "Pentecostalism", "Shaivismo": "Shaivism",
            "Shaktismo": "Shaktism", "Sufismo": "Sufism", "Sunismo": "Sunni Islam", "Tenrikyo": "Tenrikyo",
            "Testigos de Jehova": "Jehovah's Witnesses", "Tradiciones chinas": "Chinese traditions",
            "Unitarios universalistas": "Unitarian Universalists", "Vaishnavismo": "Vaishnavism", "Wicca": "Wicca",
            "Bahaismo": "Baha'i Faith", "Caodaísmo": "Caodaism", "Religiones africanas tradicionales": "Traditional African religions",
            "Religiones indígenas americanas": "Indigenous religions of the Americas", "Religiones indígenas australianas": "Indigenous Australian religions",
            "Abigail": "Abigail", "Abisag": "Abishag", "Abital": "Abital", "Acsa": "Achsah", "Ada": "Adah",
            "Ana": "Hannah", "Apphia": "Apphia", "Asenat": "Asenath", "Atalia": "Athaliah", "Batseba": "Bathsheba",
            "Candace": "Candace", "Claudia": "Claudia", "Cloe": "Chloe", "Dalila": "Delilah", "Damaris": "Damaris",
            "Dorcas": "Dorcas", "Elisabet": "Elizabeth", "Eunice": "Eunice", "Febe": "Phoebe", "Hagar": "Hagar",
            "Herodias": "Herodias", "Hulda": "Huldah", "Jael": "Jael", "Jezabel": "Jezebel", "Jocabed": "Jochebed",
            "Julia": "Julia", "Junia": "Junia", "Keturah": "Keturah", "Lia": "Leah", "Loida": "Lois",
            "Maria de Cleofas": "Mary of Clopas", "Merab": "Merab", "Mical": "Michal", "Milca": "Milcah",
            "Noemi": "Naomi", "Orfa": "Orpah", "Penina": "Peninnah", "Persida": "Persis", "Priscila": "Priscilla",
            "Pua": "Puah", "Rahab": "Rahab", "Reina de Saba": "Queen of Sheba", "Rizpa": "Rizpah", "Rode": "Rhoda",
            "Safira": "Sapphira", "Salome": "Salome", "Sara": "Sarah", "Sefora": "Zipporah", "Sifra": "Shiphrah",
            "Susana": "Susanna", "Tabita": "Tabitha", "Tamar": "Tamar", "Vasti": "Vashti", "Mujer cananea": "Canaanite woman",
            "Mujer samaritana": "Samaritan woman", "Mujer sirofenicia": "Syrophoenician woman", "Mujer de Lot": "Lot's wife",
            "Mujer de Job": "Job's wife", "Mujer de Manoa": "Manoah's wife", "Mujer de Potifar": "Potiphar's wife",
            "Mujer encorvada": "Bent-over woman", "Mujer del flujo de sangre": "Woman with the issue of blood",
            "Mujer sabia de Abel": "Wise woman of Abel", "Mujer sabia de Tecoa": "Wise woman of Tekoa",
            "Mujer sorprendida en adulterio": "Woman caught in adultery", "Mujer sunamita": "Shunammite woman",
            "Viuda de Nain": "Widow of Nain", "Viuda de Sarepta": "Widow of Zarephath", "Viuda pobre del templo": "Poor widow of the temple",
            "Mujer vinculada a la muerte de Juan el Bautista": "Woman linked to the death of John the Baptist",
            "Compañera de prisiones de Pablo": "Companion in imprisonment with Paul",
            "Hija simbólica de Oseas": "Symbolic daughter in Hosea",
            "Sierva que reconoció a Pedro": "Servant girl who recognized Peter",
            "Alimentada en tiempos de Elías": "Fed in the days of Elijah",
            "Judío elocuente y poderoso en las Escrituras": "Eloquent Jew, mighty in the Scriptures",
            "Judio elocuente y poderoso en las Escrituras": "Eloquent Jew, mighty in the Scriptures",
            "Maestro de la Ley entre los fariseos": "Teacher of the Law among the Pharisees",
            "Reconstruyó los muros de Jerusalén": "Rebuilt the walls of Jerusalem",
            "Reconstruyo los muros de Jerusalén": "Rebuilt the walls of Jerusalem",
            "Reconstruyó los muros de Jerusalen": "Rebuilt the walls of Jerusalem",
            "Reconstruyo los muros de Jerusalen": "Rebuilt the walls of Jerusalem",
            "Siervo mencionado por Pablo": "Servant mentioned by Paul",
            "Siervo etíope que ayudó a Jeremías": "Ethiopian servant who helped Jeremiah",
            "Siervo etiope que ayudó a Jeremías": "Ethiopian servant who helped Jeremiah",
            "Siervo etíope que ayudo a Jeremías": "Ethiopian servant who helped Jeremiah",
            "Siervo etiope que ayudo a Jeremías": "Ethiopian servant who helped Jeremiah",
            "Siervo etíope que ayudó a Jeremias": "Ethiopian servant who helped Jeremiah",
            "Siervo etiope que ayudó a Jeremias": "Ethiopian servant who helped Jeremiah",
            "Siervo etíope que ayudo a Jeremias": "Ethiopian servant who helped Jeremiah",
            "Siervo etiope que ayudo a Jeremias": "Ethiopian servant who helped Jeremiah",
            "Personas entregadas a alabar y honrar a Dios": "People devoted to praising and honoring God",
            "Pueblo mencionado en conflictos del Antiguo Testamento": "People mentioned in Old Testament conflicts",
            "Responsables del hogar en distintos relatos bíblicos": "Heads of household in various biblical accounts",
            "Guerreros armados con arco en batallas bíblicas": "Warriors armed with bows in biblical battles",
            "Reuniones del pueblo para escuchar la Ley o adorar": "Gatherings of the people to hear the Law or worship",
            "Ministros dedicados al canto en el templo": "Ministers devoted to singing in the temple",
            "Encargados de prisiones, como en el libro de Hechos": "Prison officials, as in the book of Acts",
            "Oficiales romanos mencionados varias veces en el Nuevo Testamento": "Roman officers mentioned several times in the New Testament",
            "Reuniones de líderes para tratar asuntos del pueblo o de la iglesia": "Meetings of leaders to address matters of the people or the church",
            "Personas que orientaban a reyes o líderes": "People who advised kings or leaders",
            "Obreros implicados en murallas, ciudades o el templo": "Workers involved with walls, cities, or the temple",
            "Servidores de palacio en reinos bíblicos": "Palace servants in biblical kingdoms",
            "Personas que han respondido con fe al mensaje de Dios": "People who have responded in faith to God's message",
            "Exiliados fuera de su tierra por juicio o guerra": "Exiles driven from their land by judgment or war",
            "Conjunto del pueblo de Israel descendiente de Jacob": "The people of Israel descended from Jacob",
            "Expertos en la interpretación de la Ley mosaica": "Experts in the interpretation of the Mosaic Law",
            "Personas oprimidas por espíritus malignos en los Evangelios": "People oppressed by evil spirits in the Gospels",
            "Grupo frecuentemente atendido con compasión y milagros": "Group often ministered to with compassion and miracles",
            "Pueblo llevado cautivo fuera de Israel y Judá": "People carried away captive from Israel and Judah",
            "Personas de otras naciones presentes entre el pueblo": "People from other nations living among the people",
            "Linajes apartados para el servicio del templo": "Lineages set apart for temple service",
            "Responsables del acceso y orden en el templo": "Those responsible for access and order in the temple",
            "Expresión poética para referirse al pueblo de Jerusalén": "Poetic expression referring to the people of Jerusalem",
            "Grupo vulnerable protegido en la Ley y los profetas": "Vulnerable group protected in the Law and the Prophets",
            "Líderes militares y administrativos de Israel": "Military and administrative leaders of Israel",
            "Grupo mencionado en exhortaciones, guerras y discipulado": "Group mentioned in exhortation, warfare, and discipleship",
            "Líderes levantados por Dios para gobernar y liberar a Israel": "Leaders raised up by God to govern and deliver Israel",
            "Sabios que visitaron a Jesús tras su nacimiento": "Wise men who visited Jesus after his birth",
            "Comerciantes presentes en ciudades y rutas bíblicas": "Merchants found in biblical cities and trade routes",
            "Mujeres que vivieron la espera de un hijo con fe y dolor": "Women who lived through waiting for a child with faith and sorrow",
            "Grupo que protesta contra Dios o sus siervos": "Group that complains against God or his servants",
            "Personas consagradas a Dios mediante voto especial": "People consecrated to God through a special vow",
            "Miembros influyentes del pueblo o de la corte": "Influential members of the people or the court",
            "Trabajadores del campo, la construcción o la mies espiritual": "Workers in the fields, construction, or the spiritual harvest",
            "Imagen del pueblo descarriado necesitado de pastor": "Image of a straying people in need of a shepherd",
            "Encargados de cuidar rebaños en la vida cotidiana bíblica": "Those responsible for caring for flocks in everyday biblical life",
            "Término frecuente para quienes necesitan arrepentimiento y gracia": "Common term for those in need of repentance and grace",
            "Personas de paso o en viaje hacia lugares santos": "People passing through or traveling toward holy places",
            "Oficio común en Galilea y entre varios discípulos": "Common trade in Galilee and among several disciples",
            "Servidores asignados al cuidado de entradas y espacios sagrados": "Servants assigned to care for entrances and sacred spaces",
            "Personas encarceladas por delitos, injusticia o causa del Evangelio": "People imprisoned for crimes, injustice, or the cause of the gospel",
            "Gentiles incorporados a la fe judía": "Gentiles incorporated into the Jewish faith",
            "Funcionarios que cobraban tributos e impuestos": "Officials who collected tribute and taxes",
            "Personas marginadas social o religiosamente": "People marginalized socially or religiously",
            "Gobernantes de naciones en pasajes históricos y proféticos": "Rulers of nations in historical and prophetic passages",
            "Grupo fiel preservado por Dios en tiempos de crisis": "Faithful group preserved by God in times of crisis",
            "Referencia a quienes actúan con misericordia inesperada": "Reference to those who show unexpected mercy",
            "Mujeres al servicio de hogares o familias": "Women serving households or families",
            "Militares presentes en historias del Antiguo y Nuevo Testamento": "Soldiers appearing in Old and New Testament accounts",
            "Imagen de quienes sirven en la obra de Dios": "Image of those who serve in God's work",
            "Grupo religioso influyente en tiempos de Jesús": "Influential religious group in the time of Jesus",
            "Grupo sacerdotal y político del judaísmo": "Priestly and political group within Judaism",
            "Intérpretes y maestros de la Ley": "Interpreters and teachers of the Law",
            "Partidarios de la casa de Herodes": "Supporters of the house of Herod",
            "Movimiento judío de fuerte fervor nacional": "Jewish movement marked by strong national zeal",
            "Comunidad judía asociada a vida apartada": "Jewish community associated with a separated way of life",
            "Cobradores de impuestos en tiempos de Roma": "Tax collectors in the days of Rome",
            "Tribu dedicada al servicio del templo": "Tribe devoted to temple service",
            "Encargados del culto en Israel": "Those responsible for worship in Israel",
            "Máxima autoridad sacerdotal": "Highest priestly authority",
            "Consejo religioso judío": "Jewish religious council",
            "Seguidores y aprendices de Jesús": "Followers and learners of Jesus",
            "Enviados escogidos por Jesús": "Messengers chosen by Jesus",
            "Portavoces del mensaje de Dios": "Spokespeople of God's message",
            "Pueblos no judíos": "Non-Jewish peoples",
            "Pueblo del pacto en tiempos bíblicos": "Covenant people in biblical times",
            "Judíos de lengua griega mencionados en Hechos": "Greek-speaking Jews mentioned in Acts",
            "Grupo vulnerable atendido por la iglesia primitiva": "Vulnerable group cared for by the early church",
            "Servidores escogidos en la iglesia primitiva": "Servants chosen in the early church",
            "Líderes espirituales del pueblo o de la iglesia": "Spiritual leaders of the people or the church",
            "Fe basada en Jesucristo y el evangelio": "Faith based on Jesus Christ and the gospel",
            "Rama principal del cristianismo con centro histórico en Roma": "Main branch of Christianity with its historic center in Rome",
            "Conjunto de iglesias cristianas surgidas de la Reforma": "Collection of Christian churches that emerged from the Reformation",
            "Tradición cristiana histórica de las iglesias ortodoxas": "Historic Christian tradition of the Orthodox churches",
            "Corriente cristiana centrada en conversión, Biblia y evangelización": "Christian movement centered on conversion, the Bible, and evangelism",
            "Movimiento cristiano que enfatiza la obra del Espíritu Santo": "Christian movement that emphasizes the work of the Holy Spirit",
            "Religión monoteísta fundada en las enseñanzas de Mahoma": "Monotheistic religion founded on the teachings of Muhammad",
            "Rama mayoritaria del islam": "Major branch of Islam",
            "Rama principal del islam vinculada a la sucesión de Alí": "Main branch of Islam linked to the succession of Ali",
            "Corriente mística dentro del islam": "Mystical current within Islam",
            "Religión del pueblo judío basada en la Torá": "Religion of the Jewish people based on the Torah",
            "Corriente judía tradicional de estricta observancia": "Traditional Jewish branch of strict observance",
            "Corriente judía de continuidad y adaptación": "Jewish branch focused on continuity and adaptation",
            "Corriente judía de enfoque más liberal": "Jewish branch with a more liberal approach",
            "Conjunto de tradiciones religiosas originadas en la India": "Collection of religious traditions originating in India",
            "Corriente hindú centrada en Vishnu": "Hindu branch centered on Vishnu",
            "Corriente hindú centrada en Shiva": "Hindu branch centered on Shiva",
            "Corriente hindú centrada en la diosa Shakti": "Hindu branch centered on the goddess Shakti",
            "Tradición fundada a partir de las enseñanzas de Buda": "Tradition founded on the teachings of Buddha",
            "Rama budista extendida en el sur de Asia": "Buddhist branch widespread in South Asia",
            "Rama budista extendida en Asia oriental": "Buddhist branch widespread in East Asia",
            "Forma budista asociada al Tíbet y regiones cercanas": "Buddhist form associated with Tibet and nearby regions",
            "Religión monoteísta originada en el Punjab": "Monotheistic religion originating in Punjab",
            "Tradición india centrada en la no violencia y la disciplina": "Indian tradition centered on nonviolence and discipline",
            "Antigua religión persa vinculada a Zaratustra": "Ancient Persian religion linked to Zoroaster",
            "Religión monoteísta nacida en Persia con vocación universal": "Monotheistic religion born in Persia with a universal calling",
            "Tradición filosófica y ética de origen chino": "Philosophical and ethical tradition of Chinese origin",
            "Tradición religiosa y filosófica china vinculada al Tao": "Chinese religious and philosophical tradition linked to the Tao",
            "Religión tradicional de Japón": "Traditional religion of Japan",
            "Creencia en espíritus asociados a la naturaleza y los seres": "Belief in spirits associated with nature and living beings",
            "Conjunto de prácticas religiosas populares de China": "Collection of popular religious practices from China",
            "Sistemas religiosos aut?ctonos de ?frica": "Indigenous religious systems of Africa",
            "Tradiciones espirituales de pueblos originarios de América": "Spiritual traditions of the indigenous peoples of the Americas",
            "Tradiciones espirituales de pueblos aborígenes": "Spiritual traditions of Aboriginal peoples",
            "Religión vietnamita de carácter sincretista": "Vietnamese religion of a syncretic character",
            "Movimiento religioso japonés de origen moderno": "Modern Japanese religious movement",
            "Corriente religiosa basada en comunicación con espíritus": "Religious movement based on communication with spirits",
            "Movimiento religioso surgido en Jamaica": "Religious movement that arose in Jamaica",
            "Movimiento religioso de enfoque pluralista": "Religious movement with a pluralist approach",
            "Tradición cristiana vinculada a La Iglesia de Jesucristo de los Santos de los Últimos Días": "Christian tradition linked to The Church of Jesus Christ of Latter-day Saints",
            "Movimiento religioso de interpretación bíblica particular": "Religious movement with a distinctive biblical interpretation",
            "Movimiento religioso fundado por Mary Baker Eddy": "Religious movement founded by Mary Baker Eddy",
            "Conjunto de espiritualidades modernas de carácter sincretista": "Collection of modern spiritualities of a syncretic nature",
            "Recuperación moderna de tradiciones religiosas precristianas": "Modern revival of pre-Christian religious traditions",
            "Tradición neopagana de carácter ritual y dual": "Neopagan tradition of a ritual and dual nature",
            "Postura de negación de la existencia de deidades": "Position that denies the existence of deities",
            "Postura sobre la imposibilidad o duda de conocer a Dios": "Position regarding the impossibility or doubt of knowing God",
            "Visión ética no religiosa centrada en el ser humano": "Non-religious ethical vision centered on the human being",
            "Creencia en un creador sin revelación religiosa particular": "Belief in a creator without a particular religious revelation",
            "Personas que no se identifican con una religión concreta": "People who do not identify with a specific religion",
            "Barnabas": "Barnabas", "Boaz": "Boaz", "Cain": "Cain", "Cornelio": "Cornelius", "Crispo": "Crispus",
            "Efrain": "Ephraim", "Elcanah": "Elkanah", "Eleazar": "Eleazar", "Eli": "Eli", "Enoc": "Enoch",
            "Ezequias": "Hezekiah", "Festo": "Festus", "Filemon": "Philemon", "Finees": "Phinehas", "Gamaliel": "Gamaliel",
            "Gedeon": "Gideon", "Heber": "Heber", "Heman": "Heman", "Hermes": "Hermes", "Isacar": "Issachar",
            "Ismael": "Ishmael", "Jair": "Jair", "Jefte": "Jephthah", "Jesse": "Jesse", "Joab": "Joab",
            "Jonadab": "Jonadab", "Jonathan": "Jonathan", "Josafat": "Jehoshaphat", "Justo": "Justus", "Laban": "Laban",
            "Lamec": "Lamech", "Lazaro": "Lazarus", "Levi": "Levi", "Lot": "Lot", "Manases": "Manasseh",
            "Mardoqueo": "Mordecai", "Matias": "Matthias", "Matusalen": "Methuselah", "Mefiboset": "Mephibosheth",
            "Micaias": "Micaiah", "Nahum": "Nahum", "Natan": "Nathan", "Natanael": "Nathanael", "Nehemias": "Nehemiah",
            "Ner": "Ner", "Nicodemo": "Nicodemus", "Noe": "Noah", "Obed": "Obed", "Onesimo": "Onesimus",
            "Ozias": "Uzziah", "Poncio Pilato": "Pontius Pilate", "Procoro": "Prochorus", "Roboam": "Rehoboam",
            "Ruben": "Reuben", "Saul": "Saul", "Sem": "Shem", "Set": "Seth", "Sila": "Silas",
            "Silas": "Silas", "Simon de Cirene": "Simon of Cyrene", "Simeon": "Simeon", "Sosthenes": "Sosthenes",
            "Tadeo": "Thaddaeus", "Tiquico": "Tychicus", "Tito Justo": "Titius Justus", "Tobias": "Tobiah",
            "Urias": "Uriah", "Uziel": "Uzziel", "Zabulon": "Zebulun", "Zaqueo": "Zacchaeus", "Zebedeo": "Zebedee",
            "Zorobabel": "Zerubbabel",
            "Abraham": "Abraham", "Isaac": "Isaac", "Jacob": "Jacob", "Jose": "Joseph", "Moises": "Moses",
            "Aaron": "Aaron", "Josue": "Joshua", "Samuel": "Samuel", "David": "David", "Salomon": "Solomon",
            "Elias": "Elijah", "Eliseo": "Elisha", "Isaias": "Isaiah", "Jeremias": "Jeremiah", "Ezequiel": "Ezekiel",
            "Daniel": "Daniel", "Oseas": "Hosea", "Joel": "Joel", "Amos": "Amos", "Abdias": "Obadiah",
            "Jonas": "Jonah", "Miqueas": "Micah", "Nahum": "Nahum", "Habacuc": "Habakkuk", "Sofonias": "Zephaniah",
            "Hageo": "Haggai", "Zacarias": "Zechariah", "Malaquias": "Malachi", "Juan": "John", "Pedro": "Peter",
            "Pablo": "Paul", "Andres": "Andrew", "Felipe": "Philip", "Mateo": "Matthew", "Marcos": "Mark",
            "Lucas": "Luke", "Santiago": "James", "Tomas": "Thomas", "Timoteo": "Timothy", "Tito": "Titus",
            "Maria": "Mary", "Maria Magdalena": "Mary Magdalene", "Marta": "Martha", "Lidia": "Lydia",
            "Noe": "Noah", "Eva": "Eve", "Rut": "Ruth", "Ester": "Esther", "Debora": "Deborah", "Sara": "Sarah",
            "Rebeca": "Rebekah", "Raquel": "Rachel", "Miriam": "Miriam", "Hebreos": "Hebrews", "Romanos": "Romans",
            "Egipcios": "Egyptians", "Babilonios": "Babylonians", "Persas": "Persians", "Israelitas": "Israelites",
            "Samaritanos": "Samaritans", "Filisteos": "Philistines", "Cananeos": "Canaanites", "Amonitas": "Ammonites",
            "Moabitas": "Moabites", "Asirios": "Assyrians", "Sidonios": "Sidonians", "Fenicios": "Phoenicians",
            "Jerusalen": "Jerusalem", "Belen": "Bethlehem", "Nazaret": "Nazareth", "Galilea": "Galilee",
            "Samaria": "Samaria", "Jerico": "Jericho", "Egipto": "Egypt", "Babilonia": "Babylon",
            "Damasco": "Damascus", "Atenas": "Athens", "Corinto": "Corinth", "Filipos": "Philippi",
            "Macedonia": "Macedonia", "Roma": "Rome", "Joppe": "Joppa", "Patmos": "Patmos", "Sion": "Zion",
            "Sinai": "Sinai", "Siria": "Syria", "Persia": "Persia", "Antioquia": "Antioch", "Cafarnaum": "Capernaum",
            "Capernaum": "Capernaum", "Getsemani": "Gethsemane", "Golgota": "Golgotha", "Monte de los Olivos": "Mount of Olives",
            "Juan el bautista": "John the Baptist", "Jose de Arimatea": "Joseph of Arimathea",
            "Discipulos": "Disciples", "Apostoles": "Apostles", "Profetas": "Prophets", "Levitas": "Levites",
            "Sacerdotes": "Priests", "Fariseos": "Pharisees", "Saduceos": "Sadducees", "Escribas": "Scribes",
            "Cristianismo": "Christianity",
            "Catolicismo": "Catholicism",
            "Protestantismo": "Protestantism",
            "Islam": "Islam",
            "Judaísmo": "Judaism",
            "Hinduismo": "Hinduism",
            "Budismo": "Buddhism",
            "Sijismo": "Sikhism",
            "Jainismo": "Jainism",
            "Zoroastrismo": "Zoroastrianism",
            "Confucianismo": "Confucianism",
            "Taoismo": "Taoism",
            "Sintoismo": "Shintoism",
            "Animismo": "Animism",
            "Espiritismo": "Spiritism",
            "Rastafarismo": "Rastafarianism",
            "Mormonismo": "Mormonism",
            "Ciencia Cristiana": "Christian Science",
            "Nueva Era": "New Age",
            "Neopaganismo": "Neopaganism",
            "Ateismo": "Atheism",
            "Agnosticismo": "Agnosticism",
            "Humanismo secular": "Secular humanism",
            "Deismo": "Deism",
            "Sin afiliacion religiosa": "No religious affiliation",
        },
    }

    def normalize_lookup_key(text: str) -> str:
        decomposed = unicodedata.normalize("NFD", text)
        without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
        lowered = without_marks.lower()
        return re.sub(r"\s+", " ", lowered).strip()

    def apply_normalized_replacements(text: str, replacements: list[tuple[str, str]]) -> str:
        updated = text
        comparable = normalize_lookup_key(text)
        ordered = sorted(replacements, key=lambda item: len(item[0]), reverse=True)

        for source, target in ordered:
            comparable_source = normalize_lookup_key(source)
            if not comparable_source:
                continue

            start = 0
            comparable_target = normalize_lookup_key(target)
            while True:
                idx = comparable.find(comparable_source, start)
                if idx == -1:
                    break
                end = idx + len(comparable_source)
                updated = updated[:idx] + target + updated[end:]
                comparable = comparable[:idx] + comparable_target + comparable[end:]
                start = idx + len(comparable_target)

        return updated

    def translate_phrase(text: str) -> str:
        if lang_code == "es":
            return text
        translated = text
        ordered_entities = sorted(entity_translations.get(lang_code, {}).items(), key=lambda item: len(item[0]), reverse=True)
        for source, target in ordered_entities:
            translated = re.sub(rf"\b{re.escape(source)}\b", target, translated)
        translated = apply_normalized_replacements(translated, ordered_entities)
        return apply_normalized_replacements(translated, common_replacements.get(lang_code, []))

    def get_plain_translation(text: str) -> str | None:
        language_map = plain_item_translations.get(lang_code, {})
        exact = language_map.get(text)
        if exact is not None:
            return exact

        normalized_target = normalize_lookup_key(text)
        for source, target in language_map.items():
            if normalize_lookup_key(source) == normalized_target:
                return target
        return None

    def uppercase_first_letter(text: str) -> str:
        if not text:
            return text
        first = text[0]
        return first.upper() + text[1:]

    def localize_catalog_item(item: str) -> str:
        if lang_code == "es":
            return item
        if ": " in item:
            left, right = item.split(": ", 1)
            left = get_plain_translation(left) or translate_phrase(left)
            right = uppercase_first_letter((get_plain_translation(right) or translate_phrase(right)).strip())
            return f"{left}: {right}"
        return get_plain_translation(item) or translate_phrase(item)

    def localize_book_name(book: str | None) -> str | None:
        if book in (None, "", "None", no_selection):
            return None
        return book_translations.get(lang_code, {}).get(book, book)

    def localize_study_type(value: str | None) -> str | None:
        if value in (None, "", "None", "Ninguno"):
            return None
        if value == "Estudio informativo":
            if lang_code == "es" and pasaje_completo():
                return "Estudio del pasaje"
            if lang_code == "ca" and pasaje_completo():
                return "Estudi del passatge"
            if lang_code == "fr" and pasaje_completo():
                return "Étude du passage"
            if lang_code == "en" and pasaje_completo():
                return "Passage study"
        return study_type_labels.get(value, value)

    page.title = ui["title"]
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = theme["page_bg"]
    page.padding = 2
    page.scroll = ft.ScrollMode.AUTO
    inicio_preferido = inicio if inicio in {"biblia", "filtros", "comportamiento", "incredulo", "cristianos", "chat_consejero", "chat_soporte"} else "biblia"
    controles_montados = False
    label_style_theme = ft.TextStyle(color=theme["primary"])
    textos_comportamiento = {
        "es": {
            "title": "CÓMO COMPORTARME SI...",
            "situation": "SITUACIÓN",
            "select_situation": "Selecciona una situación",
            "generate": "GENERAR RESPUESTA",
            "help_critican": "Si me critican",
            "help_hablan_mal": "Si hablan mal de mí",
            "help_enojan": "Si se enojan conmigo",
            "help_rechazan": "Si me rechazan",
            "help_ofenden": "Si me ofenden",
            "help_injusticia": "Si son injustos conmigo",
            "help_discuten": "Si discuten conmigo",
            "help_perdonar": "Si me cuesta perdonar",
            "msg_select_situation": "Selecciona primero una situación",
            "status_generating": "Estado: generando respuesta...",
            "status_ready": "Estado: respuesta lista",
        },
        "ca": {
            "title": "COM COMPORTAR-ME SI...",
            "situation": "SITUACIO",
            "select_situation": "Selecciona una situacio",
            "generate": "GENERAR RESPOSTA",
            "help_critican": "Si em critiquen",
            "help_hablan_mal": "Si parlen malament de mi",
            "help_enojan": "Si s'enfaden amb mi",
            "help_rechazan": "Si em rebutgen",
            "help_ofenden": "Si m'ofenen",
            "help_injusticia": "Si son injustos amb mi",
            "help_discuten": "Si discuteixen amb mi",
            "help_perdonar": "Si em costa perdonar",
            "msg_select_situation": "Selecciona primer una situacio",
            "status_generating": "Estat: generant resposta...",
            "status_ready": "Estat: resposta llesta",
        },
        "fr": {
            "title": "COMMENT ME COMPORTER SI...",
            "situation": "SITUATION",
            "select_situation": "Choisis une situation",
            "generate": "GENERER LA REPONSE",
            "help_critican": "Si on me critique",
            "help_hablan_mal": "Si on parle mal de moi",
            "help_enojan": "Si quelqu'un se fache contre moi",
            "help_rechazan": "Si on me rejette",
            "help_ofenden": "Si on m'offense",
            "help_injusticia": "Si on est injuste avec moi",
            "help_discuten": "Si on se dispute avec moi",
            "help_perdonar": "Si j'ai du mal a pardonner",
            "msg_select_situation": "Choisis d'abord une situation",
            "status_generating": "Etat : generation de la reponse...",
            "status_ready": "Etat : reponse prete",
        },
        "en": {
            "title": "HOW SHOULD I RESPOND IF...",
            "situation": "SITUATION",
            "select_situation": "Choose a situation",
            "generate": "GENERATE RESPONSE",
            "help_critican": "If I am criticized",
            "help_hablan_mal": "If people speak badly about me",
            "help_enojan": "If someone gets angry with me",
            "help_rechazan": "If I am rejected",
            "help_ofenden": "If I am offended",
            "help_injusticia": "If people are unfair to me",
            "help_discuten": "If someone argues with me",
            "help_perdonar": "If I struggle to forgive",
            "msg_select_situation": "Choose a situation first",
            "status_generating": "Status: generating response...",
            "status_ready": "Status: response ready",
        },
    }.get(lang_code, {})
    textos_incredulo = {
        "es": {
            "title": "QUÉ RESPONDER A UN INCRÉDULO SI...",
            "question": "PREGUNTA",
            "select_question": "Selecciona una pregunta",
            "generate": "GENERAR RESPUESTA",
            "msg_select_question": "Selecciona primero una pregunta",
            "status_generating": "Estado: generando respuesta...",
            "status_ready": "Estado: respuesta lista",
        },
        "ca": {
            "title": "QUE RESPONDRE A UN INCREDUL SI...",
            "question": "PREGUNTA",
            "select_question": "Selecciona una pregunta",
            "generate": "GENERAR RESPOSTA",
            "msg_select_question": "Selecciona primer una pregunta",
            "status_generating": "Estat: generant resposta...",
            "status_ready": "Estat: resposta llesta",
        },
        "fr": {
            "title": "QUE REPONDRE A UN INCREDULE SI...",
            "question": "QUESTION",
            "select_question": "Choisis une question",
            "generate": "GENERER LA REPONSE",
            "msg_select_question": "Choisis d'abord une question",
            "status_generating": "Etat : generation de la reponse...",
            "status_ready": "Etat : reponse prete",
        },
        "en": {
            "title": "WHAT TO ANSWER AN UNBELIEVER IF...",
            "question": "QUESTION",
            "select_question": "Choose a question",
            "generate": "GENERATE RESPONSE",
            "msg_select_question": "Choose a question first",
            "status_generating": "Status: generating response...",
            "status_ready": "Status: response ready",
        },
    }.get(lang_code, {})
    textos_cristianos = {
        "es": {
            "title": "PREGUNTAS QUE LOS CRISTIANOS NOS HACEMOS",
            "question": "PREGUNTA",
            "select_question": "Selecciona una pregunta",
            "generate": "GENERAR RESPUESTA",
            "msg_select_question": "Selecciona primero una pregunta",
            "status_generating": "Estado: generando respuesta...",
            "status_ready": "Estado: respuesta lista",
        },
        "ca": {
            "title": "PREGUNTES QUE ELS CRISTIANS ENS FEM",
            "question": "PREGUNTA",
            "select_question": "Selecciona una pregunta",
            "generate": "GENERAR RESPOSTA",
            "msg_select_question": "Selecciona primer una pregunta",
            "status_generating": "Estat: generant resposta...",
            "status_ready": "Estat: resposta llesta",
        },
        "fr": {
            "title": "QUESTIONS QUE LES CHRETIENS SE POSENT",
            "question": "QUESTION",
            "select_question": "Choisis une question",
            "generate": "GENERER LA REPONSE",
            "msg_select_question": "Choisis d'abord une question",
            "status_generating": "Etat : generation de la reponse...",
            "status_ready": "Etat : reponse prete",
        },
        "en": {
            "title": "QUESTIONS CHRISTIANS ASK",
            "question": "QUESTION",
            "select_question": "Choose a question",
            "generate": "GENERATE RESPONSE",
            "msg_select_question": "Choose a question first",
            "status_generating": "Status: generating response...",
            "status_ready": "Status: response ready",
        },
    }.get(lang_code, {})
    textos_chat_consejero = {
        "es": {
            "title": "CHAT CONSEJERO CRISTIANO",
            "message": "CUÉNTAME QUÉ TE PASA",
            "placeholder": "Escribe aquí tu situación, duda o carga. Por ejemplo: estoy muy angustiado, no sé cómo perdonar, tengo miedo, necesito orientación...",
            "send": "ENVIAR MENSAJE",
            "clear": "LIMPIAR CHAT",
            "header_status": "Responde con base bÃ­blica y tono pastoral",
            "empty_message": "Escribe primero un mensaje",
            "status_generating": "Estado: respondiendo en el chat...",
            "status_ready": "Estado: respuesta lista",
            "intro": "Habla con naturalidad. Recibirás acompañamiento bíblico, pastoral y práctico.",
            "greetings": [
                "Hola, soy tu consejero cristiano. Antes de nada, ¿cómo te llamas? Y si quieres, cuéntame qué te pasa o cómo te puedo ayudar.",
                "Hola, puedes hablarme con libertad. ¿Cómo te llamas? Después, si quieres, dime qué estás viviendo o en qué te gustaría que te acompañara.",
                "Bienvenido. Me gustaría saber cómo te llamas, y luego puedes contarme con calma qué situación estás pasando o cómo te puedo ayudar.",
                "Hola, gracias por estar aquí. ¿Cómo te llamas? Si te parece, después me cuentas qué te preocupa o qué está pasando ahora mismo.",
            ],
            "greeting": "Hola, soy tu consejero cristiano. Antes de nada, ¿cómo te llamas? Y si quieres, cuéntame qué te pasa o cómo te puedo ayudar.",
            "warning": "Si hay peligro inmediato, abuso, autolesión o ideas suicidas, busca ayuda urgente en tu zona y contacta también con un pastor o una persona de confianza.",
            "you": "Tú",
            "assistant": "Consejero cristiano",
            "typing": "_Consejero cristiano escribiendo..._",
            "fallback_response": "Perdona, no me he expresado bien. Cuéntame un poco más y te respondo con más claridad y calma.",
            "quick_questions": [
                "Estoy angustiado",
                "Necesito oración",
                "Tengo una duda de fe",
                "No sé qué decisión tomar",
                "Estoy luchando con el pecado",
                "Necesito consuelo",
            ],
        },
        "ca": {
            "title": "XAT CONSELLER CRISTIÀ",
            "message": "EXPLICA'M QUÈ ET PASSA",
            "placeholder": "Escriu aquí la teva situació, dubte o càrrega. Per exemple: estic molt anguniat, no sé com perdonar, tinc por, necessito orientació...",
            "send": "ENVIAR MISSATGE",
            "clear": "NETEJAR XAT",
            "header_status": "Respon amb base bÃ­blica i to pastoral",
            "empty_message": "Escriu primer un missatge",
            "status_generating": "Estat: responent al xat...",
            "status_ready": "Estat: resposta llesta",
            "intro": "Parla amb naturalitat. Rebràs una resposta bíblica, pastoral i pràctica.",
            "greetings": [
                "Hola, soc el teu conseller cristià. Pots parlar-me amb calma; vull entendre bé el que estàs vivint i acompanyar-te a la llum de la Paraula de Déu. Què està passant?",
                "Hola, pots obrir el teu cor amb llibertat. Soc aquí per escoltar-te sense pressa i orientar-te amb una mirada bíblica i pastoral. Què et pesa més avui?",
                "Benvingut. Vull escoltar amb calma allò que estàs passant i caminar amb tu davant de Déu. Quina situació t'està costant més ara mateix?",
                "Hola, gràcies per escriure. Si vols, explica'm a poc a poc el que portes dins i ho mirarem junts a la llum de la Paraula. Què et preocupa per dins?",
            ],
            "greeting": "Hola, soc el teu conseller cristià. Pots parlar-me amb calma; vull entendre bé el que estàs vivint i acompanyar-te a la llum de la Paraula de Déu. Què està passant?",
            "warning": "Si hi ha perill immediat, abús, autolesió o idees suïcides, busca ajuda urgent a la teva zona i contacta també amb un pastor o una persona de confiança.",
            "you": "Tu",
            "assistant": "Conseller cristià",
            "typing": "_El conseller cristià està escrivint..._",
            "fallback_response": "Perdona, no m'he expressat bé. Explica'm una mica més i et respondré amb més claredat i calma.",
            "quick_questions": [
                "Estic anguniat",
                "Necessito pregària",
                "Tinc un dubte de fe",
                "No sé quina decisió prendre",
                "Estic lluitant amb el pecat",
                "Necessito consol",
            ],
        },
        "fr": {
            "title": "CHAT CONSEILLER CHRÉTIEN",
            "message": "RACONTE-MOI CE QUI T'ARRIVE",
            "placeholder": "Écris ici ta situation, ton doute ou ton fardeau. Par exemple : je suis très angoissé, je ne sais pas comment pardonner, j'ai peur, j'ai besoin d'être guidé...",
            "send": "ENVOYER LE MESSAGE",
            "clear": "EFFACER LE CHAT",
            "header_status": "Reponses bibliques avec un ton pastoral",
            "empty_message": "Écris d'abord un message",
            "status_generating": "Etat : réponse en cours dans le chat...",
            "status_ready": "Etat : réponse prête",
            "intro": "Parle naturellement. Tu recevras une réponse biblique, pastorale et pratique.",
            "greetings": [
                "Bonjour, je suis ton conseiller chrétien. Tu peux me parler calmement ; je veux bien comprendre ce que tu vis et t'accompagner à la lumière de la Parole de Dieu. Que se passe-t-il ?",
                "Bonjour, tu peux parler librement ici. Je veux t'écouter avec douceur et t'accompagner avec une perspective biblique et pastorale. Qu'est-ce qui pèse le plus sur ton coeur aujourd'hui ?",
                "Bienvenue. Je suis là pour t'écouter sans te presser et regarder avec toi ta situation devant Dieu. Qu'est-ce qui te fait le plus souffrir en ce moment ?",
                "Bonjour, merci d'être là. Si tu veux, raconte-moi tranquillement ce que tu traverses et nous le regarderons ensemble à la lumière de la Parole. Qu'est-ce qui t'inquiète le plus ?",
            ],
            "greeting": "Bonjour, je suis ton conseiller chrétien. Tu peux me parler calmement ; je veux bien comprendre ce que tu vis et t'accompagner à la lumière de la Parole de Dieu. Que se passe-t-il ?",
            "warning": "S'il y a un danger immédiat, un abus, une automutilation ou des idées suicidaires, cherche une aide urgente dans ta région et contacte aussi un pasteur ou une personne de confiance.",
            "you": "Toi",
            "assistant": "Conseiller chrétien",
            "typing": "_Le conseiller chrétien est en train d'écrire..._",
            "fallback_response": "Pardonne-moi, je ne me suis pas bien exprimé. Dis-m'en un peu plus et je te répondrai avec plus de clarté et de douceur.",
            "quick_questions": [
                "Je suis angoissé",
                "J'ai besoin de prière",
                "J'ai un doute de foi",
                "Je ne sais pas quelle décision prendre",
                "Je lutte contre le péché",
                "J'ai besoin de réconfort",
            ],
        },
        "en": {
            "title": "CHRISTIAN COUNSELOR CHAT",
            "message": "TELL ME WHAT YOU ARE GOING THROUGH",
            "placeholder": "Write here about your situation, doubt, or burden. For example: I feel overwhelmed, I do not know how to forgive, I am afraid, I need guidance...",
            "send": "SEND MESSAGE",
            "clear": "CLEAR CHAT",
            "header_status": "Biblical answers with a pastoral tone",
            "empty_message": "Write a message first",
            "status_generating": "Status: replying in chat...",
            "status_ready": "Status: response ready",
            "intro": "Speak naturally. You will receive a biblical, pastoral, and practical response.",
            "greetings": [
                "Hello, I am your Christian counselor. You can speak freely; I want to understand well what you are going through, put myself in your place, and walk with you in the light of God's Word. What is happening?",
                "Hello, you can speak openly here. I am here to listen with care and walk with you with a biblical and pastoral perspective. What is weighing on your heart today?",
                "Welcome. I am here to listen without rushing you and to look at your situation with you before God. What feels hardest for you right now?",
                "Hello, thank you for being here. If you want, tell me calmly what you are carrying, and we will look at it together in the light of God's Word. What is troubling you most inside?",
            ],
            "greeting": "Hello, I am your Christian counselor. You can speak freely; I want to understand well what you are going through, put myself in your place, and walk with you in the light of God's Word. What is happening?",
            "warning": "If there is immediate danger, abuse, self-harm, or suicidal thoughts, seek urgent local help and also contact a pastor or a trusted person.",
            "you": "You",
            "assistant": "Christian counselor",
            "typing": "_Christian counselor is typing..._",
            "fallback_response": "Sorry, I did not express myself well. Tell me a little more and I will answer with more clarity and gentleness.",
            "quick_questions": [
                "I feel overwhelmed",
                "I need prayer",
                "I have a faith doubt",
                "I do not know what decision to make",
                "I am struggling with sin",
                "I need comfort",
            ],
        },
    }.get(lang_code, {})
    textos_chat_soporte = {
        "es": {
            "title": "GUÍA DE LA APP",
            "message": "DIME QUÉ QUIERES HACER EN LA APP",
            "placeholder": "Escribe tu duda. Por ejemplo: por dónde empiezo, qué sección me conviene o cuál uso para una duda de fe...",
            "send": "ENVIAR MENSAJE",
            "clear": "LIMPIAR CHAT",
            "header_status": "Guía para usar Biblia IA paso a paso",
            "empty_message": "Escribe primero un mensaje",
            "status_generating": "Estado: respondiendo en la guía de la app...",
            "status_ready": "Estado: respuesta lista",
            "intro": "Habla con naturalidad. Recibirás ayuda práctica para ir a la sección correcta y usar la app sin liarte.",
            "greeting": "Hola, soy la guía de la app. Puedo decirte por dónde empezar, qué sección te conviene y qué botón usar según lo que necesites. ¿Quieres leer un pasaje, hacer un estudio o resolver una duda?",
            "warning": "Si tu duda es sobre la API key o un error de conexión, también puedo orientarte y decirte en qué pantalla resolverlo.",
            "you": "Tú",
            "assistant": "Guía de la app",
            "typing": "_La guía de la app está escribiendo..._",
            "fallback_response": "Perdona, no te he entendido del todo. Dime qué quieres hacer dentro de la app y te diré qué sección te conviene usar.",
            "quick_questions": [
                "¿Por dónde empiezo?",
                "¿Qué sección me conviene?",
                "¿Qué diferencia hay entre Biblia y Estudio Bíblico?",
                "¿Qué diferencia hay entre Preguntas y Chat Consejero Cristiano?",
                "¿Cómo busco un pasaje?",
                "¿Dónde configuro la IA?",
            ],
        },
        "ca": {
            "title": "GUIA DE L'APP",
            "message": "DIGUES-ME QUÈ VOLS FER A L'APP",
            "placeholder": "Escriu aquí el teu dubte sobre com fer servir l'app. Per exemple: per on començo, per a què serveix cada secció o com entro a l'estudi bíblic...",
            "send": "ENVIAR MISSATGE",
            "clear": "NETEJAR XAT",
            "header_status": "Guia per fer servir Biblia IA pas a pas",
            "empty_message": "Escriu primer un missatge",
            "status_generating": "Estat: responent a la guia de l'app...",
            "status_ready": "Estat: resposta llesta",
            "intro": "Parla amb naturalitat. Rebràs ajuda pràctica per entendre i fer servir l'aplicació.",
            "greeting": "Hola, sóc la guia de l'app. Puc ajudar-te a entendre per a què serveix cada secció, per on començar i com fer servir Biblia IA pas a pas. Què vols fer dins de l'aplicació?",
            "warning": "Si el teu dubte és sobre la API key o un error de connexió, també et puc orientar i dir-te en quina pantalla resoldre-ho.",
            "you": "Tu",
            "assistant": "Guia de l'app",
            "typing": "_La guia de l'app està escrivint..._",
            "fallback_response": "Perdona, no t'he entès del tot. Digues-me què vols fer dins de l'app o quina pantalla veus i et guio pas a pas.",
            "quick_questions": [
                "Per on començo?",
                "Quina secció em convé?",
                "Quina diferència hi ha entre Bíblia i Estudi Bíblic?",
                "Quina diferència hi ha entre Preguntes i Xat Conseller Cristià?",
                "Com busco un passatge?",
                "On configuro la IA?",
            ],
        },
        "fr": {
            "title": "GUIDE DE L'APP",
            "message": "DIS-MOI CE QUE TU VEUX FAIRE DANS L'APP",
            "placeholder": "Écris ici ta question sur l'usage de l'application. Par exemple : par où commencer, à quoi sert chaque section ou comment ouvrir l'étude biblique...",
            "send": "ENVOYER LE MESSAGE",
            "clear": "EFFACER LE CHAT",
            "header_status": "Guide pour utiliser Biblia IA pas à pas",
            "empty_message": "Écris d'abord un message",
            "status_generating": "Etat : réponse du guide de l'app...",
            "status_ready": "Etat : réponse prête",
            "intro": "Parle naturellement. Tu recevras une aide pratique pour comprendre et utiliser l'application.",
            "greeting": "Bonjour, je suis le guide de l'app. Je peux t'aider à comprendre à quoi sert chaque section, par où commencer et comment utiliser Biblia IA pas à pas. Que veux-tu faire dans l'application ?",
            "warning": "Si ta question concerne la clé API ou une erreur de connexion, je peux aussi t'orienter vers le bon écran pour la résoudre.",
            "you": "Toi",
            "assistant": "Guide de l'app",
            "typing": "_Le guide de l'app est en train d'écrire..._",
            "fallback_response": "Pardonne-moi, je n'ai pas tout compris. Dis-moi ce que tu veux faire dans l'app ou quel écran tu vois et je te guiderai pas à pas.",
            "quick_questions": [
                "Par où commencer ?",
                "Quelle section me convient ?",
                "Quelle différence entre Bible et Étude biblique ?",
                "Quelle différence entre Questions et Chat conseiller chrétien ?",
                "Comment chercher un passage ?",
                "Où configurer l'IA ?",
            ],
        },
        "en": {
            "title": "APP GUIDE",
            "message": "TELL ME WHAT YOU WANT TO DO IN THE APP",
            "placeholder": "Write here about how to use the app. For example: where should I start, what each section is for, or how to open Bible study...",
            "send": "SEND MESSAGE",
            "clear": "CLEAR CHAT",
            "header_status": "Guide for using Biblia IA step by step",
            "empty_message": "Write a message first",
            "status_generating": "Status: app guide is replying...",
            "status_ready": "Status: response ready",
            "intro": "Speak naturally. You will receive practical help for understanding and using the application.",
            "greeting": "Hello, I am the app guide. I can help you understand what each section is for, where to start, and how to use Biblia IA step by step. What would you like to do in the app?",
            "warning": "If your question is about the API key or a connection error, I can also point you to the right screen to solve it.",
            "you": "You",
            "assistant": "App guide",
            "typing": "_The app guide is typing..._",
            "fallback_response": "Sorry, I did not fully understand. Tell me what you want to do in the app or which screen you are looking at, and I will guide you step by step.",
            "quick_questions": [
                "Where should I start?",
                "Which section should I use?",
                "What is the difference between Bible and Bible Study?",
                "What is the difference between Questions and Christian Counselor Chat?",
                "How do I search for a passage?",
                "Where do I set up the AI?",
            ],
        },
    }.get(lang_code, {})
    es_modo_chat = inicio_preferido in {"chat_consejero", "chat_soporte"}
    es_modo_chat_soporte = inicio_preferido == "chat_soporte"
    textos_chat_activo = textos_chat_soporte if es_modo_chat_soporte else textos_chat_consejero

    dd_biblia = ft.Dropdown(
        label=ui["version"],
        options=[ft.dropdown.Option(key=sigla, text=nombre) for sigla, nombre in versiones_biblia],
        value="Ninguna",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )

    dd_orden_libros = ft.Dropdown(
        label=ui["book_order"],
        options=[
            ft.dropdown.Option(key="Orden biblico", text=ui["biblical_order"]),
            ft.dropdown.Option(key="A-Z", text=ui["alphabetical_order"]),
        ],
        value="Orden biblico",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )

    def crear_dd_libro(libros, valor=no_selection):
        opciones_libros = [no_selection] + libros
        valor_inicial = valor if valor in opciones_libros else opciones_libros[0]
        return ft.Dropdown(
            label=ui["book"],
            options=[ft.dropdown.Option(key=l, text=localize_book_name(l) or l) for l in opciones_libros],
            value=valor_inicial,
            expand=True,
            bgcolor=theme["field_bg"],
            border_color=theme["field_border"],
            border_width=5,
            label_style=label_style_theme,
        )

    dd_libro = crear_dd_libro(libros_orden_biblico, no_selection)
    contenedor_libro = ft.Container(content=dd_libro, padding=6, border_radius=12, bgcolor=theme["field_bg"])

    dd_cap = ft.Dropdown(label=ui["chapter"], expand=1, bgcolor=theme["field_bg"], border_color=theme["field_border"], border_width=5, label_style=label_style_theme)
    dd_ini = ft.Dropdown(label=ui["start"], expand=1, bgcolor=theme["field_bg"], border_color=theme["field_border"], border_width=5, label_style=label_style_theme)
    dd_fin = ft.Dropdown(label=ui["end"], expand=1, bgcolor=theme["field_bg"], border_color=theme["field_border"], border_width=5, label_style=label_style_theme)
    contenedor_pasaje = ft.Container(
        padding=6,
        border_radius=12,
        bgcolor=theme["field_bg"],
    )

    dd_hombre = crear_dropdown(ui["male_character"], [], default=no_selection, formatter=localize_catalog_item, border_color=theme["field_border"], label_color=theme["primary"], fill_color=theme["field_bg"])
    dd_mujer = crear_dropdown(ui["female_character"], [], default=no_selection, formatter=localize_catalog_item, border_color=theme["field_border"], label_color=theme["primary"], fill_color=theme["field_bg"])
    dd_grupo = crear_dropdown(ui["groups"], [], default=no_selection, formatter=localize_catalog_item, border_color=theme["field_border"], label_color=theme["primary"], fill_color=theme["field_bg"])
    dd_pueblo = crear_dropdown(ui["people_nation"], [], default=no_selection, formatter=localize_catalog_item, border_color=theme["field_border"], label_color=theme["primary"], fill_color=theme["field_bg"])
    dd_pais = crear_dropdown(ui["place"], [], default=no_selection, formatter=localize_catalog_item, border_color=theme["field_border"], label_color=theme["primary"], fill_color=theme["field_bg"])
    dd_religion = crear_dropdown(ui["religions"], [], default=no_selection, formatter=localize_catalog_item, border_color=theme["field_border"], label_color=theme["primary"], fill_color=theme["field_bg"])
    especiales = [dd_hombre, dd_mujer, dd_grupo, dd_pueblo, dd_pais, dd_religion]
    tipo_contexto_por_dropdown = {
        dd_hombre: "character",
        dd_mujer: "character",
        dd_grupo: "group",
        dd_pueblo: "people",
        dd_pais: "place",
        dd_religion: "religion",
    }
    for dropdown in [dd_hombre, dd_mujer, dd_grupo, dd_pueblo, dd_pais, dd_religion]:
        dropdown.border_color = theme["field_border"]
        dropdown.label_style = label_style_theme
    contenedores_especiales = {
        dd_hombre: ft.Container(content=dd_hombre, padding=6, border_radius=12, bgcolor=theme["field_bg"]),
        dd_mujer: ft.Container(content=dd_mujer, padding=6, border_radius=12, bgcolor=theme["field_bg"]),
        dd_grupo: ft.Container(content=dd_grupo, padding=6, border_radius=12, bgcolor=theme["field_bg"]),
        dd_pueblo: ft.Container(content=dd_pueblo, padding=6, border_radius=12, bgcolor=theme["field_bg"]),
        dd_pais: ft.Container(content=dd_pais, padding=6, border_radius=12, bgcolor=theme["field_bg"]),
        dd_religion: ft.Container(content=dd_religion, padding=6, border_radius=12, bgcolor=theme["field_bg"]),
    }

    dd_tipo = ft.Dropdown(
        label=ui["study_type"],
        options=[
            crear_opcion_tipo(key="Ninguno", text=ui["no_selection"]),
            crear_opcion_tipo(key="Solo versiculos", text=only_verses),
            crear_opcion_tipo(key="Estudio informativo", text=ui["study_info"]),
            crear_opcion_tipo(key="Estudio versiculos", text=ui["verse_study"]),
            crear_opcion_tipo(key="Reflexion biblica", text=ui["biblical_reflection"]),
            crear_opcion_tipo(key="Aplicacion practica", text=ui["practical_application"]),
            crear_opcion_tipo(key="Bosquejo para predicar", text=ui["sermon_outline"]),
            crear_opcion_tipo(key="Devocional breve", text=ui["brief_devotional"]),
            crear_opcion_tipo(
                key="Analisis exegetico",
                text={
                    "es": "Analisis exegetico",
                    "ca": "Analisi exegetica",
                    "fr": "Analyse exegetique",
                    "en": "Exegetical analysis",
                }.get(lang_code, "Analisis exegetico"),
            ),
            crear_opcion_tipo(
                key="Analisis hermeneutico",
                text={
                    "es": "Analisis hermeneutico",
                    "ca": "Analisi hermeneutica",
                    "fr": "Analyse hermeneutique",
                    "en": "Hermeneutical analysis",
                }.get(lang_code, "Analisis hermeneutico"),
            ),
            crear_opcion_tipo(
                key="Analisis literario",
                text={
                    "es": "Analisis literario",
                    "ca": "Analisi literaria",
                    "fr": "Analyse litteraire",
                    "en": "Literary analysis",
                }.get(lang_code, "Analisis literario"),
            ),
            crear_opcion_tipo(
                key="Analisis geografico politico",
                text={
                    "es": "Analisis geografico y politico",
                    "ca": "Analisi geografic i politic",
                    "fr": "Analyse geographique et politique",
                    "en": "Geographic and political analysis",
                }.get(lang_code, "Analisis geografico y politico"),
            ),
            crear_opcion_tipo(
                key="Analisis estructura social",
                text={
                    "es": "Analisis de estructura social",
                    "ca": "Analisi d'estructura social",
                    "fr": "Analyse de structure sociale",
                    "en": "Social structure analysis",
                }.get(lang_code, "Analisis de estructura social"),
            ),
            crear_opcion_tipo(
                key="Analisis vida cotidiana",
                text={
                    "es": "Analisis de vida cotidiana y costumbres",
                    "ca": "Analisi de vida quotidiana i costums",
                    "fr": "Analyse de la vie quotidienne et des coutumes",
                    "en": "Daily life and customs analysis",
                }.get(lang_code, "Analisis de vida cotidiana y costumbres"),
            ),
            crear_opcion_tipo(
                key="Analisis contexto",
                text={
                    "es": "Analisis del contexto (mundo del texto)",
                    "ca": "Analisi del context (mon del text)",
                    "fr": "Analyse du contexte (monde du texte)",
                    "en": "Context analysis (world of the text)",
                }.get(lang_code, "Analisis del contexto (mundo del texto)"),
            ),
        ],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )

    dd_tamano = ft.Dropdown(
        label=ui["words"],
        options=[
            ft.dropdown.Option(key="Ninguno", text=ui["no_selection"]),
            ft.dropdown.Option(key="50", text="50"),
            ft.dropdown.Option(key="100", text="100"),
            ft.dropdown.Option(key="200", text="200"),
        ],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    situaciones_comportamiento = [
        ("critican", textos_comportamiento["help_critican"]),
        ("hablan_mal", textos_comportamiento["help_hablan_mal"]),
        ("enojan", textos_comportamiento["help_enojan"]),
        ("rechazan", textos_comportamiento["help_rechazan"]),
        ("ofenden", textos_comportamiento["help_ofenden"]),
        ("injusticia", textos_comportamiento["help_injusticia"]),
        ("discuten", textos_comportamiento["help_discuten"]),
        ("perdonar", textos_comportamiento["help_perdonar"]),
    ]
    situaciones_extra_comportamiento = {
        "es": [
            ("ansiedad", "Si tengo ansiedad"),
            ("miedo", "Si tengo miedo"),
            ("tristeza", "Si me siento triste"),
            ("soledad", "Si me siento solo"),
            ("desanimo", "Si estoy desanimado"),
            ("cansancio", "Si estoy cansado"),
            ("estres", "Si tengo mucho estres"),
            ("tentacion", "Si tengo tentacion"),
            ("enojo", "Si siento mucho enojo"),
            ("celos", "Si tengo celos"),
            ("envidia", "Si siento envidia"),
            ("orgullo", "Si me domina el orgullo"),
            ("chismes", "Si escucho chismes"),
            ("humillan", "Si me humillan"),
            ("mienten", "Si me mienten"),
            ("traicionan", "Si me traicionan"),
            ("ignoran", "Si me ignoran"),
            ("rechazan_familia", "Si mi familia me rechaza"),
            ("conflicto_pareja", "Si discuto con mi pareja"),
            ("conflicto_hijos", "Si tengo problemas con mis hijos"),
            ("conflicto_padres", "Si tengo problemas con mis padres"),
            ("problema_trabajo", "Si tengo problemas en el trabajo"),
            ("despiden", "Si pierdo mi trabajo"),
            ("problema_dinero", "Si tengo problemas de dinero"),
            ("enfermedad", "Si estoy enfermo"),
            ("duelo", "Si estoy pasando un duelo"),
            ("fracaso", "Si siento que he fracasado"),
            ("decision_dificil", "Si tengo que tomar una decision dificil"),
            ("confusion", "Si me siento confundido"),
            ("falta_fe", "Si siento que me falta fe"),
            ("sequedad_espiritual", "Si estoy espiritualmente seco"),
            ("orar", "Si no se como orar"),
            ("esperar", "Si tengo que esperar mucho tiempo"),
            ("injusticia_lider", "Si un lider me trata injustamente"),
            ("perdonarme", "Si me cuesta perdonarme a mi mismo"),
            ("culpa", "Si me siento culpable"),
            ("verguenza", "Si siento verguenza"),
            ("pecado_repetido", "Si caigo en el mismo pecado"),
            ("burlas_fe", "Si se burlan de mi fe"),
            ("persecucion_fe", "Si me persiguen por mi fe"),
            ("malas_companias", "Si estoy rodeado de malas companias"),
            ("poner_limites", "Si necesito poner limites"),
            ("pedir_ayuda", "Si necesito pedir ayuda"),
            ("corregir_otro", "Si tengo que corregir a alguien"),
            ("recibir_correccion", "Si alguien me corrige"),
            ("servir_sin_reconocimiento", "Si sirvo y no me valoran"),
            ("comparar", "Si me comparo con otros"),
            ("noticias_malas", "Si recibo malas noticias"),
            ("incertidumbre", "Si no se que va a pasar"),
            ("cambio_grande", "Si estoy viviendo un cambio grande"),
        ],
        "ca": [
            ("ansiedad", "Si tinc ansietat"),
            ("miedo", "Si tinc por"),
            ("tristeza", "Si em sento trist"),
            ("soledad", "Si em sento sol"),
            ("desanimo", "Si estic desanimat"),
            ("cansancio", "Si estic cansat"),
            ("estres", "Si tinc molt estres"),
            ("tentacion", "Si tinc temptacio"),
            ("enojo", "Si sento molta ira"),
            ("celos", "Si tinc gelosia"),
            ("envidia", "Si sento enveja"),
            ("orgullo", "Si m'esta dominant l'orgull"),
            ("chismes", "Si escolto xafarderies"),
            ("humillan", "Si m'humilien"),
            ("mienten", "Si em menteixen"),
            ("traicionan", "Si em traeixen"),
            ("ignoran", "Si m'ignoren"),
            ("rechazan_familia", "Si la meva familia em rebutja"),
            ("conflicto_pareja", "Si discuteixo amb la meva parella"),
            ("conflicto_hijos", "Si tinc problemes amb els meus fills"),
            ("conflicto_padres", "Si tinc problemes amb els meus pares"),
            ("problema_trabajo", "Si tinc problemes a la feina"),
            ("despiden", "Si perdo la feina"),
            ("problema_dinero", "Si tinc problemes de diners"),
            ("enfermedad", "Si estic malalt"),
            ("duelo", "Si estic passant un dol"),
            ("fracaso", "Si sento que he fracassat"),
            ("decision_dificil", "Si he de prendre una decisio dificil"),
            ("confusion", "Si em sento confos"),
            ("falta_fe", "Si sento que em falta fe"),
            ("sequedad_espiritual", "Si estic espiritualment sec"),
            ("orar", "Si no se com orar"),
            ("esperar", "Si he d'esperar molt de temps"),
            ("injusticia_lider", "Si un lider em tracta injustament"),
            ("perdonarme", "Si em costa perdonar-me a mi mateix"),
            ("culpa", "Si em sento culpable"),
            ("verguenza", "Si sento vergonya"),
            ("pecado_repetido", "Si caic en el mateix pecat"),
            ("burlas_fe", "Si es burlen de la meva fe"),
            ("persecucion_fe", "Si em persegueixen per la meva fe"),
            ("malas_companias", "Si estic envoltat de males companyies"),
            ("poner_limites", "Si necessito posar limits"),
            ("pedir_ayuda", "Si necessito demanar ajuda"),
            ("corregir_otro", "Si he de corregir algu"),
            ("recibir_correccion", "Si algu em corregeix"),
            ("servir_sin_reconocimiento", "Si serveixo i no em valoren"),
            ("comparar", "Si em comparo amb els altres"),
            ("noticias_malas", "Si rebo males noticies"),
            ("incertidumbre", "Si no se que passara"),
            ("cambio_grande", "Si estic vivint un canvi gran"),
        ],
        "fr": [
            ("ansiedad", "Si j'ai de l'anxiete"),
            ("miedo", "Si j'ai peur"),
            ("tristeza", "Si je me sens triste"),
            ("soledad", "Si je me sens seul"),
            ("desanimo", "Si je suis decourage"),
            ("cansancio", "Si je suis fatigue"),
            ("estres", "Si j'ai beaucoup de stress"),
            ("tentacion", "Si je suis tente"),
            ("enojo", "Si je ressens beaucoup de colere"),
            ("celos", "Si j'ai de la jalousie"),
            ("envidia", "Si je ressens de l'envie"),
            ("orgullo", "Si l'orgueil me domine"),
            ("chismes", "Si j'entends des commérages"),
            ("humillan", "Si on m'humilie"),
            ("mienten", "Si on me ment"),
            ("traicionan", "Si on me trahit"),
            ("ignoran", "Si on m'ignore"),
            ("rechazan_familia", "Si ma famille me rejette"),
            ("conflicto_pareja", "Si je me dispute avec mon conjoint"),
            ("conflicto_hijos", "Si j'ai des problèmes avec mes enfants"),
            ("conflicto_padres", "Si j'ai des problèmes avec mes parents"),
            ("problema_trabajo", "Si j'ai des problèmes au travail"),
            ("despiden", "Si je perds mon travail"),
            ("problema_dinero", "Si j'ai des problèmes d'argent"),
            ("enfermedad", "Si je suis malade"),
            ("duelo", "Si je traverse un deuil"),
            ("fracaso", "Si j'ai l'impression d'avoir echoue"),
            ("decision_dificil", "Si je dois prendre une decision difficile"),
            ("confusion", "Si je me sens perdu"),
            ("falta_fe", "Si j'ai l'impression de manquer de foi"),
            ("sequedad_espiritual", "Si je traverse une secheresse spirituelle"),
            ("orar", "Si je ne sais pas comment prier"),
            ("esperar", "Si je dois attendre longtemps"),
            ("injusticia_lider", "Si un responsable me traite injustement"),
            ("perdonarme", "Si j'ai du mal a me pardonner"),
            ("culpa", "Si je me sens coupable"),
            ("verguenza", "Si je ressens de la honte"),
            ("pecado_repetido", "Si je tombe toujours dans le meme peche"),
            ("burlas_fe", "Si on se moque de ma foi"),
            ("persecucion_fe", "Si je suis persecute a cause de ma foi"),
            ("malas_companias", "Si je suis entoure de mauvaises fréquentations"),
            ("poner_limites", "Si j'ai besoin de poser des limites"),
            ("pedir_ayuda", "Si j'ai besoin de demander de l'aide"),
            ("corregir_otro", "Si je dois corriger quelqu'un"),
            ("recibir_correccion", "Si quelqu'un me corrige"),
            ("servir_sin_reconocimiento", "Si je sers sans etre reconnu"),
            ("comparar", "Si je me compare aux autres"),
            ("noticias_malas", "Si je recois de mauvaises nouvelles"),
            ("incertidumbre", "Si je ne sais pas ce qui va arriver"),
            ("cambio_grande", "Si je vis un grand changement"),
        ],
        "en": [
            ("ansiedad", "If I feel anxious"),
            ("miedo", "If I am afraid"),
            ("tristeza", "If I feel sad"),
            ("soledad", "If I feel lonely"),
            ("desanimo", "If I feel discouraged"),
            ("cansancio", "If I am tired"),
            ("estres", "If I am under a lot of stress"),
            ("tentacion", "If I am being tempted"),
            ("enojo", "If I feel very angry"),
            ("celos", "If I feel jealous"),
            ("envidia", "If I feel envy"),
            ("orgullo", "If pride is controlling me"),
            ("chismes", "If I hear gossip"),
            ("humillan", "If I am humiliated"),
            ("mienten", "If people lie to me"),
            ("traicionan", "If I am betrayed"),
            ("ignoran", "If I am ignored"),
            ("rechazan_familia", "If my family rejects me"),
            ("conflicto_pareja", "If I argue with my spouse"),
            ("conflicto_hijos", "If I have problems with my children"),
            ("conflicto_padres", "If I have problems with my parents"),
            ("problema_trabajo", "If I have problems at work"),
            ("despiden", "If I lose my job"),
            ("problema_dinero", "If I have money problems"),
            ("enfermedad", "If I am sick"),
            ("duelo", "If I am grieving"),
            ("fracaso", "If I feel like I have failed"),
            ("decision_dificil", "If I need to make a hard decision"),
            ("confusion", "If I feel confused"),
            ("falta_fe", "If I feel like my faith is weak"),
            ("sequedad_espiritual", "If I feel spiritually dry"),
            ("orar", "If I do not know how to pray"),
            ("esperar", "If I have to wait a long time"),
            ("injusticia_lider", "If a leader treats me unfairly"),
            ("perdonarme", "If I struggle to forgive myself"),
            ("culpa", "If I feel guilty"),
            ("verguenza", "If I feel ashamed"),
            ("pecado_repetido", "If I keep falling into the same sin"),
            ("burlas_fe", "If people mock my faith"),
            ("persecucion_fe", "If I am persecuted for my faith"),
            ("malas_companias", "If I am surrounded by bad influences"),
            ("poner_limites", "If I need to set boundaries"),
            ("pedir_ayuda", "If I need to ask for help"),
            ("corregir_otro", "If I need to correct someone"),
            ("recibir_correccion", "If someone corrects me"),
            ("servir_sin_reconocimiento", "If I serve without being appreciated"),
            ("comparar", "If I compare myself with others"),
            ("noticias_malas", "If I receive bad news"),
            ("incertidumbre", "If I do not know what will happen"),
            ("cambio_grande", "If I am going through a big change"),
        ],
    }
    situaciones_comportamiento.extend(situaciones_extra_comportamiento.get(lang_code, situaciones_extra_comportamiento["es"]))
    mapa_situaciones_comportamiento = {clave: texto for clave, texto in situaciones_comportamiento}
    dd_comportamiento = ft.Dropdown(
        label=textos_comportamiento["situation"],
        options=[ft.dropdown.Option(key="Ninguno", text=textos_comportamiento["select_situation"])] + [
            ft.dropdown.Option(key=clave, text=texto) for clave, texto in situaciones_comportamiento
        ],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    dd_tamano_comportamiento = ft.Dropdown(
        label=ui["words"],
        options=[
            ft.dropdown.Option(key="Ninguno", text=ui["no_selection"]),
            ft.dropdown.Option(key="50", text="50"),
            ft.dropdown.Option(key="100", text="100"),
            ft.dropdown.Option(key="150", text="150"),
            ft.dropdown.Option(key="200", text="200"),
        ],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    preguntas_incredulo = {
        "es": [
            ("dios_existe", "Si me pregunta si Dios existe"),
            ("bible_true", "Si me pregunta si la Biblia es verdadera"),
            ("jesus_only", "Si me pregunta por que Jesus es el unico camino"),
            ("evil_world", "Si me pregunta por que existe el mal"),
            ("suffering", "Si me pregunta por que Dios permite el sufrimiento"),
            ("science", "Si me pregunta si fe y ciencia se contradicen"),
            ("resurrection", "Si me pregunta si Jesus resucito de verdad"),
            ("hypocrites", "Si me habla de los hipocritas en la iglesia"),
            ("many_religions", "Si me dice que todas las religiones son iguales"),
            ("pray", "Si me pregunta para que sirve orar"),
            ("unanswered_prayer", "Si me pregunta por que Dios no responde algunas oraciones"),
            ("hell", "Si me pregunta por el infierno"),
            ("trinity", "Si me pregunta que es la Trinidad"),
            ("reliable_gospels", "Si me pregunta si los evangelios son fiables"),
            ("free_will", "Si me pregunta por el libre albedrio"),
            ("why_faith", "Si me pregunta por que necesito fe"),
            ("church", "Si me pregunta por que ir a la iglesia"),
            ("old_testament", "Si me pregunta por que el Antiguo Testamento es tan duro"),
            ("miracles", "Si me pregunta si los milagros son reales"),
            ("salvation", "Si me pregunta como se salva una persona"),
            ("creation", "Si me pregunta si Dios creo el mundo"),
            ("adam_eve", "Si me pregunta por Adan y Eva"),
            ("dinosaurs", "Si me pregunta por los dinosaurios"),
            ("contradictions", "Si me dice que la Biblia se contradice"),
            ("translations", "Si me pregunta por que hay tantas traducciones de la Biblia"),
            ("canon", "Si me pregunta quien decidio los libros de la Biblia"),
            ("mary", "Si me pregunta quien fue realmente Maria"),
            ("saints", "Si me pregunta por los santos"),
            ("cross", "Si me pregunta por que Jesus tuvo que morir en la cruz"),
            ("blood", "Si me pregunta por que la Biblia habla tanto de sangre"),
            ("grace_works", "Si me pregunta si nos salvamos por gracia o por obras"),
            ("good_people", "Si me pregunta si una buena persona no creyente puede salvarse"),
            ("babies", "Si me pregunta que pasa con los niños que mueren"),
            ("suicide", "Si me pregunta por el suicidio"),
            ("homosexuality", "Si me pregunta que dice la Biblia sobre la homosexualidad"),
            ("sexuality", "Si me pregunta por la sexualidad segun la Biblia"),
            ("marriage", "Si me pregunta que es el matrimonio segun la Biblia"),
            ("divorce", "Si me pregunta por el divorcio"),
            ("women_church", "Si me pregunta por el papel de la mujer en la iglesia"),
            ("slavery", "Si me pregunta por que la Biblia menciona la esclavitud"),
            ("wars", "Si me pregunta por las guerras en la Biblia"),
            ("israel", "Si me pregunta por que Israel es importante en la Biblia"),
            ("law_grace", "Si me pregunta por la ley y la gracia"),
            ("sabbath", "Si me pregunta si hay que guardar el sabado"),
            ("food", "Si me pregunta si hay alimentos prohibidos para los cristianos"),
            ("alcohol", "Si me pregunta si un cristiano puede beber alcohol"),
            ("money", "Si me pregunta si Dios quiere que todos sean ricos"),
            ("prosperity", "Si me pregunta por el evangelio de la prosperidad"),
            ("demons", "Si me pregunta si los demonios existen"),
            ("angels", "Si me pregunta si los angeles existen"),
            ("satan", "Si me pregunta si Satanas es real"),
            ("end_times", "Si me pregunta por el fin del mundo"),
            ("antichrist", "Si me pregunta por el anticristo"),
            ("heaven", "Si me pregunta como es el cielo"),
            ("forgiveness", "Si me pregunta por que debo perdonar"),
            ("suffering_christians", "Si me pregunta por que sufren tambien los cristianos"),
            ("prayer_ritual", "Si me pregunta si orar es solo un ritual"),
            ("christianity_control", "Si me pregunta si el cristianismo es una forma de control"),
            ("church_money", "Si me pregunta por el dinero en las iglesias"),
            ("christians_fail", "Si me pregunta por que los cristianos fallan tanto"),
            ("resurrection_body", "Si me pregunta con que cuerpo resucitaremos"),
            ("judgment", "Si me pregunta si Dios va a juzgar a todos"),
            ("exclusive_truth", "Si me pregunta por que el cristianismo afirma tener la verdad"),
            ("why_believe_now", "Si me pregunta por que deberia creer ahora y no mas adelante"),
            ("personal_testimony", "Si me pide una respuesta sencilla y personal de por que creo"),
        ],
        "ca": [
            ("dios_existe", "Si em pregunta si Deu existeix"),
            ("bible_true", "Si em pregunta si la Biblia es veritable"),
            ("jesus_only", "Si em pregunta per que Jesus es l'unic cami"),
            ("evil_world", "Si em pregunta per que existeix el mal"),
            ("suffering", "Si em pregunta per que Deu permet el sofriment"),
            ("science", "Si em pregunta si fe i ciencia es contradien"),
            ("resurrection", "Si em pregunta si Jesus va ressuscitar de veritat"),
            ("hypocrites", "Si em parla dels hipocrites a l'esglesia"),
            ("many_religions", "Si em diu que totes les religions son iguals"),
            ("pray", "Si em pregunta per a que serveix pregar"),
            ("unanswered_prayer", "Si em pregunta per que Deu no respon algunes pregàries"),
            ("hell", "Si em pregunta per l'infern"),
            ("trinity", "Si em pregunta que es la Trinitat"),
            ("reliable_gospels", "Si em pregunta si els evangelis son fiables"),
            ("free_will", "Si em pregunta pel lliure albir"),
            ("why_faith", "Si em pregunta per que necessito fe"),
            ("church", "Si em pregunta per que anar a l'esglesia"),
            ("old_testament", "Si em pregunta per que l'Antic Testament es tan dur"),
            ("miracles", "Si em pregunta si els miracles son reals"),
            ("salvation", "Si em pregunta com se salva una persona"),
            ("creation", "Si em pregunta si Deu va crear el mon"),
            ("adam_eve", "Si em pregunta per Adam i Eva"),
            ("dinosaurs", "Si em pregunta pels dinosaures"),
            ("contradictions", "Si em diu que la Biblia es contradictoria"),
            ("translations", "Si em pregunta per que hi ha tantes traduccions de la Biblia"),
            ("canon", "Si em pregunta qui va decidir els llibres de la Biblia"),
            ("mary", "Si em pregunta qui va ser realment Maria"),
            ("saints", "Si em pregunta pels sants"),
            ("cross", "Si em pregunta per que Jesus va haver de morir a la creu"),
            ("blood", "Si em pregunta per que la Biblia parla tant de sang"),
            ("grace_works", "Si em pregunta si ens salvem per gracia o per obres"),
            ("good_people", "Si em pregunta si una bona persona no creient pot salvar-se"),
            ("babies", "Si em pregunta que passa amb els nens que moren"),
            ("suicide", "Si em pregunta pel suïcidi"),
            ("homosexuality", "Si em pregunta que diu la Biblia sobre l'homosexualitat"),
            ("sexuality", "Si em pregunta per la sexualitat segons la Biblia"),
            ("marriage", "Si em pregunta que es el matrimoni segons la Biblia"),
            ("divorce", "Si em pregunta pel divorci"),
            ("women_church", "Si em pregunta pel paper de la dona a l'esglesia"),
            ("slavery", "Si em pregunta per que la Biblia esmenta l'esclavitud"),
            ("wars", "Si em pregunta per les guerres a la Biblia"),
            ("israel", "Si em pregunta per que Israel es important a la Biblia"),
            ("law_grace", "Si em pregunta per la llei i la gracia"),
            ("sabbath", "Si em pregunta si cal guardar el dissabte"),
            ("food", "Si em pregunta si hi ha aliments prohibits per als cristians"),
            ("alcohol", "Si em pregunta si un cristia pot beure alcohol"),
            ("money", "Si em pregunta si Deu vol que tothom sigui ric"),
            ("prosperity", "Si em pregunta per l'evangeli de la prosperitat"),
            ("demons", "Si em pregunta si els dimonis existeixen"),
            ("angels", "Si em pregunta si els angels existeixen"),
            ("satan", "Si em pregunta si Satanas es real"),
            ("end_times", "Si em pregunta per la fi del mon"),
            ("antichrist", "Si em pregunta per l'anticrist"),
            ("heaven", "Si em pregunta com es el cel"),
            ("forgiveness", "Si em pregunta per que he de perdonar"),
            ("suffering_christians", "Si em pregunta per que tambe pateixen els cristians"),
            ("prayer_ritual", "Si em pregunta si pregar es nomes un ritual"),
            ("christianity_control", "Si em pregunta si el cristianisme es una forma de control"),
            ("church_money", "Si em pregunta pels diners a les esglesies"),
            ("christians_fail", "Si em pregunta per que els cristians fallen tant"),
            ("resurrection_body", "Si em pregunta amb quin cos ressuscitarem"),
            ("judgment", "Si em pregunta si Deu jutjara tothom"),
            ("exclusive_truth", "Si em pregunta per que el cristianisme afirma tenir la veritat"),
            ("why_believe_now", "Si em pregunta per que hauria de creure ara i no mes endavant"),
            ("personal_testimony", "Si em demana una resposta senzilla i personal de per que crec"),
        ],
        "fr": [
            ("dios_existe", "Si on me demande si Dieu existe"),
            ("bible_true", "Si on me demande si la Bible est vraie"),
            ("jesus_only", "Si on me demande pourquoi Jesus est le seul chemin"),
            ("evil_world", "Si on me demande pourquoi le mal existe"),
            ("suffering", "Si on me demande pourquoi Dieu permet la souffrance"),
            ("science", "Si on me demande si la foi et la science se contredisent"),
            ("resurrection", "Si on me demande si Jesus est vraiment ressuscite"),
            ("hypocrites", "Si on me parle des hypocrites dans l'eglise"),
            ("many_religions", "Si on me dit que toutes les religions sont pareilles"),
            ("pray", "Si on me demande a quoi sert la priere"),
            ("unanswered_prayer", "Si on me demande pourquoi Dieu ne repond pas a certaines prieres"),
            ("hell", "Si on me demande ce qu'est l'enfer"),
            ("trinity", "Si on me demande ce qu'est la Trinite"),
            ("reliable_gospels", "Si on me demande si les evangiles sont fiables"),
            ("free_will", "Si on me demande ce qu'est le libre arbitre"),
            ("why_faith", "Si on me demande pourquoi j'ai besoin de foi"),
            ("church", "Si on me demande pourquoi aller a l'eglise"),
            ("old_testament", "Si on me demande pourquoi l'Ancien Testament est si dur"),
            ("miracles", "Si on me demande si les miracles sont reels"),
            ("salvation", "Si on me demande comment une personne est sauvee"),
            ("creation", "Si on me demande si Dieu a cree le monde"),
            ("adam_eve", "Si on me demande a propos d'Adam et Eve"),
            ("dinosaurs", "Si on me demande a propos des dinosaures"),
            ("contradictions", "Si on me dit que la Bible se contredit"),
            ("translations", "Si on me demande pourquoi il existe tant de traductions de la Bible"),
            ("canon", "Si on me demande qui a decide des livres de la Bible"),
            ("mary", "Si on me demande qui etait vraiment Marie"),
            ("saints", "Si on me demande a propos des saints"),
            ("cross", "Si on me demande pourquoi Jesus a du mourir sur la croix"),
            ("blood", "Si on me demande pourquoi la Bible parle tellement de sang"),
            ("grace_works", "Si on me demande si nous sommes sauves par la grace ou par les oeuvres"),
            ("good_people", "Si on me demande si une bonne personne non croyante peut etre sauvee"),
            ("babies", "Si on me demande ce qu'il arrive aux enfants qui meurent"),
            ("suicide", "Si on me demande a propos du suicide"),
            ("homosexuality", "Si on me demande ce que dit la Bible sur l'homosexualite"),
            ("sexuality", "Si on me demande a propos de la sexualite selon la Bible"),
            ("marriage", "Si on me demande ce qu'est le mariage selon la Bible"),
            ("divorce", "Si on me demande a propos du divorce"),
            ("women_church", "Si on me demande a propos du role de la femme dans l'eglise"),
            ("slavery", "Si on me demande pourquoi la Bible mentionne l'esclavage"),
            ("wars", "Si on me demande a propos des guerres dans la Bible"),
            ("israel", "Si on me demande pourquoi Israel est important dans la Bible"),
            ("law_grace", "Si on me demande a propos de la loi et de la grace"),
            ("sabbath", "Si on me demande s'il faut garder le sabbat"),
            ("food", "Si on me demande s'il existe des aliments interdits pour les chretiens"),
            ("alcohol", "Si on me demande si un chretien peut boire de l'alcool"),
            ("money", "Si on me demande si Dieu veut que tout le monde soit riche"),
            ("prosperity", "Si on me demande a propos de l'evangile de la prosperite"),
            ("demons", "Si on me demande si les demons existent"),
            ("angels", "Si on me demande si les anges existent"),
            ("satan", "Si on me demande si Satan est reel"),
            ("end_times", "Si on me demande a propos de la fin du monde"),
            ("antichrist", "Si on me demande a propos de l'antichrist"),
            ("heaven", "Si on me demande a quoi ressemble le ciel"),
            ("forgiveness", "Si on me demande pourquoi je dois pardonner"),
            ("suffering_christians", "Si on me demande pourquoi les chretiens souffrent aussi"),
            ("prayer_ritual", "Si on me demande si la priere n'est qu'un rituel"),
            ("christianity_control", "Si on me demande si le christianisme est une forme de controle"),
            ("church_money", "Si on me demande a propos de l'argent dans les eglises"),
            ("christians_fail", "Si on me demande pourquoi les chretiens echouent autant"),
            ("resurrection_body", "Si on me demande avec quel corps nous ressusciterons"),
            ("judgment", "Si on me demande si Dieu jugera tout le monde"),
            ("exclusive_truth", "Si on me demande pourquoi le christianisme affirme detenir la verite"),
            ("why_believe_now", "Si on me demande pourquoi croire maintenant et pas plus tard"),
            ("personal_testimony", "Si on me demande une reponse simple et personnelle sur pourquoi je crois"),
        ],
        "en": [
            ("dios_existe", "If I am asked whether God exists"),
            ("bible_true", "If I am asked whether the Bible is true"),
            ("jesus_only", "If I am asked why Jesus is the only way"),
            ("evil_world", "If I am asked why evil exists"),
            ("suffering", "If I am asked why God allows suffering"),
            ("science", "If I am asked whether faith and science contradict each other"),
            ("resurrection", "If I am asked whether Jesus truly rose again"),
            ("hypocrites", "If someone brings up hypocrites in the church"),
            ("many_religions", "If someone says all religions are the same"),
            ("pray", "If I am asked what prayer is for"),
            ("unanswered_prayer", "If I am asked why God does not answer some prayers"),
            ("hell", "If I am asked about hell"),
            ("trinity", "If I am asked what the Trinity is"),
            ("reliable_gospels", "If I am asked whether the Gospels are reliable"),
            ("free_will", "If I am asked about free will"),
            ("why_faith", "If I am asked why faith is needed"),
            ("church", "If I am asked why go to church"),
            ("old_testament", "If I am asked why the Old Testament is so harsh"),
            ("miracles", "If I am asked whether miracles are real"),
            ("salvation", "If I am asked how a person is saved"),
            ("creation", "If I am asked whether God created the world"),
            ("adam_eve", "If I am asked about Adam and Eve"),
            ("dinosaurs", "If I am asked about dinosaurs"),
            ("contradictions", "If someone says the Bible contradicts itself"),
            ("translations", "If I am asked why there are so many Bible translations"),
            ("canon", "If I am asked who decided the books of the Bible"),
            ("mary", "If I am asked who Mary really was"),
            ("saints", "If I am asked about the saints"),
            ("cross", "If I am asked why Jesus had to die on the cross"),
            ("blood", "If I am asked why the Bible speaks so much about blood"),
            ("grace_works", "If I am asked whether we are saved by grace or by works"),
            ("good_people", "If I am asked whether a good unbelieving person can be saved"),
            ("babies", "If I am asked what happens to children who die"),
            ("suicide", "If I am asked about suicide"),
            ("homosexuality", "If I am asked what the Bible says about homosexuality"),
            ("sexuality", "If I am asked about sexuality according to the Bible"),
            ("marriage", "If I am asked what marriage is according to the Bible"),
            ("divorce", "If I am asked about divorce"),
            ("women_church", "If I am asked about the role of women in the church"),
            ("slavery", "If I am asked why the Bible mentions slavery"),
            ("wars", "If I am asked about wars in the Bible"),
            ("israel", "If I am asked why Israel is important in the Bible"),
            ("law_grace", "If I am asked about law and grace"),
            ("sabbath", "If I am asked whether Christians should keep the Sabbath"),
            ("food", "If I am asked whether there are forbidden foods for Christians"),
            ("alcohol", "If I am asked whether a Christian can drink alcohol"),
            ("money", "If I am asked whether God wants everyone to be rich"),
            ("prosperity", "If I am asked about the prosperity gospel"),
            ("demons", "If I am asked whether demons exist"),
            ("angels", "If I am asked whether angels exist"),
            ("satan", "If I am asked whether Satan is real"),
            ("end_times", "If I am asked about the end of the world"),
            ("antichrist", "If I am asked about the antichrist"),
            ("heaven", "If I am asked what heaven is like"),
            ("forgiveness", "If I am asked why I should forgive"),
            ("suffering_christians", "If I am asked why Christians suffer too"),
            ("prayer_ritual", "If I am asked whether prayer is just a ritual"),
            ("christianity_control", "If I am asked whether Christianity is a form of control"),
            ("church_money", "If I am asked about money in churches"),
            ("christians_fail", "If I am asked why Christians fail so much"),
            ("resurrection_body", "If I am asked what kind of body we will have in the resurrection"),
            ("judgment", "If I am asked whether God will judge everyone"),
            ("exclusive_truth", "If I am asked why Christianity claims to have the truth"),
            ("why_believe_now", "If I am asked why someone should believe now instead of later"),
            ("personal_testimony", "If I am asked for a simple personal answer about why I believe"),
        ],
    }.get(lang_code, [])
    mapa_preguntas_incredulo = {clave: texto for clave, texto in preguntas_incredulo}
    dd_incredulo = ft.Dropdown(
        label=textos_incredulo["question"],
        options=[ft.dropdown.Option(key="Ninguno", text=textos_incredulo["select_question"])] + [
            ft.dropdown.Option(key=clave, text=texto) for clave, texto in preguntas_incredulo
        ],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    dd_tamano_incredulo = ft.Dropdown(
        label=ui["words"],
        options=[
            ft.dropdown.Option(key="Ninguno", text=ui["no_selection"]),
            ft.dropdown.Option(key="50", text="50"),
            ft.dropdown.Option(key="100", text="100"),
            ft.dropdown.Option(key="150", text="150"),
            ft.dropdown.Option(key="200", text="200"),
        ],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    def formatear_pregunta_cristiana(texto: str) -> str:
        if not texto:
            return ""
        texto_capitalizado = texto[0].upper() + texto[1:]
        return f"\u00BF{texto_capitalizado}?" if lang_code in {"es", "ca"} else f"{texto_capitalizado}?"

    fragmentos_preguntas_cristianos = {
        "es": [
            ("feel_far", "por que me siento lejos de Dios"),
            ("silence", "por que Dios guarda silencio"),
            ("doubts", "que hago cuando tengo dudas de fe"),
            ("no_pray_desire", "que hago si ya no tengo ganas de orar"),
            ("no_bible_desire", "que hago si me cuesta leer la Biblia"),
            ("prayer_distraction", "que hago si me distraigo al orar"),
            ("repeated_sin", "como vencer un pecado repetido"),
            ("forgiven_assurance", "como saber si Dios me ha perdonado de verdad"),
            ("lose_salvation", "si un creyente puede perder la salvacion"),
            ("suffer_believer", "por que tambien sufrimos los cristianos"),
            ("no_healing", "por que Dios no sana siempre"),
            ("waiting", "como esperar cuando Dios tarda"),
            ("angry_god", "que hago si estoy enojado con Dios"),
            ("church_disappointment", "que hago si me decepciono la iglesia"),
            ("leader_hurt", "que hago si me hirio un lider cristiano"),
            ("true_forgive", "como perdonar de verdad"),
            ("restore_god", "como restaurar mi relacion con Dios"),
            ("return_after_fall", "como volver a Dios despues de caer"),
            ("faith_not_feelings", "como vivir por fe y no por emociones"),
            ("trust_without_seeing", "como confiar en Dios sin ver nada claro"),
            ("discern_guidance", "como discernir si Dios me esta guiando"),
            ("big_decision", "como tomar una decision dificil sin confundirme"),
            ("future_fear", "que hago si tengo miedo al futuro"),
            ("anxiety_believer", "como enfrentar la ansiedad siendo cristiano"),
            ("overcome_temptation", "como vencer la tentacion"),
            ("condemnation_thoughts", "como tratar pensamientos de condenacion"),
            ("recover_joy", "como recuperar el gozo espiritual"),
            ("serve_without_burning", "como servir sin quemarme"),
            ("rest_without_guilt", "como descansar sin sentirme culpable"),
            ("healthy_boundaries", "como poner limites sanos"),
            ("love_hurting_people", "como amar a personas que me han herido"),
            ("share_faith_fear", "como hablar de Cristo sin miedo"),
            ("calling", "como saber si tengo un llamado"),
            ("gifts", "como descubrir mis dones espirituales"),
            ("disciple_someone", "como discipular a otra persona"),
            ("lead_without_pride", "como liderar sin caer en orgullo"),
            ("raise_children", "como criar hijos en la fe"),
            ("strengthen_marriage", "como fortalecer mi matrimonio"),
            ("after_failure", "que hago despues de un fracaso"),
            ("unanswered_prayer", "como reaccionar cuando una oracion no es respondida"),
            ("grief", "como vivir un duelo con fe"),
            ("sexual_purity", "como mantener pureza sexual"),
            ("use_money", "como usar el dinero de forma biblica"),
            ("comparison", "como dejar de compararme con otros"),
            ("humility", "como crecer en humildad"),
            ("spiritual_laziness", "como vencer la pereza espiritual"),
            ("obey_without_understanding", "como obedecer a Dios cuando no entiendo"),
            ("no_visible_fruit", "que hago si no veo fruto en mi vida"),
            ("persevere", "como perseverar sin rendirme"),
            ("hear_god_word", "como escuchar a Dios en Su Palabra"),
            ("conviction_vs_condemnation", "como distinguir conviccion del Espiritu y condenacion"),
            ("therapy", "si esta mal ir a terapia siendo cristiano"),
            ("help_fallen_brother", "como ayudar a un hermano que ha caido"),
            ("correct_with_love", "como corregir con amor"),
            ("rebuild_trust", "como restaurar la confianza despues de fallar"),
            ("dry_spirit", "que hago si me siento espiritualmente seco"),
            ("feel_useless", "que hago si me siento inutil"),
            ("god_still_use_me", "si Dios todavia puede usarme"),
            ("lonely_in_church", "que hago si me siento solo aun en la iglesia"),
            ("holiness_without_legalism", "como vivir en santidad sin caer en legalismo"),
            ("assurance_conversion", "si de verdad he nacido de nuevo"),
            ("first_love", "como recuperar mi primer amor por Cristo"),
            ("worship_dry", "por que no siento nada al adorar"),
            ("ordered_bible_reading", "como leer la Biblia con constancia y orden"),
            ("fast_biblically", "como ayunar de manera biblica"),
            ("hard_heart", "como evitar endurecer mi corazon"),
            ("past_shame", "como vencer la verguenza por mi pasado"),
            ("confess_sin", "cuando debo confesar mi pecado a otra persona"),
            ("accountability", "como tener una rendicion de cuentas sana"),
            ("spiritual_attack", "como discernir si estoy en guerra espiritual"),
            ("demonic_fear", "que hago si tengo miedo al diablo o a los demonios"),
            ("use_social_media", "como usar las redes sociales como cristiano"),
            ("entertainment", "que entretenimiento me conviene evitar"),
            ("music_discernment", "como discernir la musica que escucho"),
            ("modesty", "que es la modestia biblica"),
            ("evangelize_family", "como hablar de Cristo a mi familia sin pelear"),
            ("unbelieving_spouse", "como vivir mi fe si mi pareja no cree"),
            ("prodigal_child", "como orar por un hijo alejado de Dios"),
            ("biblical_friendships", "como elegir amistades que me acerquen a Dios"),
            ("leave_toxic_group", "cuando debo alejarme de una relacion o grupo toxico"),
            ("church_change", "como saber si debo cambiar de iglesia"),
            ("submit_authority", "como honrar la autoridad sin caer en obediencia ciega"),
            ("church_discipline", "como entender la disciplina de la iglesia"),
            ("ministry_jealousy", "que hago si tengo celos de otro ministerio"),
            ("hidden_service", "como servir en lo secreto con alegria"),
            ("fruit_vs_gifts", "que diferencia hay entre dones y fruto del Espiritu"),
            ("spirit_filling", "que significa ser lleno del Espiritu Santo"),
            ("hear_god_without_signs", "como buscar direccion sin depender de señales"),
            ("insomnia", "como descansar cuando no puedo dormir por preocupaciones"),
            ("work_faith_balance", "como equilibrar trabajo, familia y vida espiritual"),
            ("study_theology", "como estudiar doctrina sin volverme frio"),
            ("apologetics_humility", "como defender la fe sin orgullo"),
            ("bitterness", "como vencer la amargura"),
            ("reconcile", "como buscar reconciliacion despues de una pelea"),
            ("repentance_vs_remorse", "como distinguir arrepentimiento verdadero de remordimiento"),
            ("confess_christ_publicly", "como no avergonzarme de Cristo en publico"),
            ("persecution_work", "que hago si me ridiculizan por mi fe en el trabajo"),
            ("sabbath_rest", "como aplicar el descanso biblico hoy"),
            ("generosity_limits", "como ser generoso sin caer en imprudencia"),
            ("debt", "como manejar deudas como cristiano"),
            ("career", "como escoger trabajo o carrera segun principios biblicos"),
            ("singleness", "como vivir la solteria para la gloria de Dios"),
            ("courtship", "como empezar una relacion sentimental con sabiduria"),
            ("break_up", "como enfrentar una ruptura amorosa sin apartarme de Dios"),
            ("infertility", "como vivir con fe ante la infertilidad"),
            ("miscarriage", "como atravesar la perdida de un embarazo"),
            ("aging_parents", "como honrar a mis padres en su vejez"),
            ("chronic_illness", "como perseverar con una enfermedad cronica"),
            ("doubt_bible_promises", "que hago cuando me cuesta creer las promesas de Dios"),
            ("spiritual_hypocrisy", "como luchar contra la hipocresia espiritual"),
        ],
        "ca": [
            ("feel_far", "per que em sento lluny de Deu"),
            ("silence", "per que Deu guarda silenci"),
            ("doubts", "que faig quan tinc dubtes de fe"),
            ("no_pray_desire", "que faig si ja no tinc ganes de pregar"),
            ("no_bible_desire", "que faig si em costa llegir la Biblia"),
            ("prayer_distraction", "que faig si em distrec quan prego"),
            ("repeated_sin", "com vencer un pecat repetit"),
            ("forgiven_assurance", "com saber si Deu m'ha perdonat de veritat"),
            ("lose_salvation", "si un creient pot perdre la salvacio"),
            ("suffer_believer", "per que tambe patim els cristians"),
            ("no_healing", "per que Deu no cura sempre"),
            ("waiting", "com esperar quan Deu tarda"),
            ("angry_god", "que faig si estic enfadat amb Deu"),
            ("church_disappointment", "que faig si l'esglesia m'ha decebut"),
            ("leader_hurt", "que faig si m'ha ferit un lider cristia"),
            ("true_forgive", "com perdonar de veritat"),
            ("restore_god", "com restaurar la meva relacio amb Deu"),
            ("return_after_fall", "com tornar a Deu despres de caure"),
            ("faith_not_feelings", "com viure per fe i no per emocions"),
            ("trust_without_seeing", "com confiar en Deu sense veure res clar"),
            ("discern_guidance", "com discernir si Deu m'esta guiant"),
            ("big_decision", "com prendre una decisio dificil sense confondre'm"),
            ("future_fear", "que faig si tinc por del futur"),
            ("anxiety_believer", "com afrontar l'ansietat sent cristia"),
            ("overcome_temptation", "com vencer la temptacio"),
            ("condemnation_thoughts", "com tractar pensaments de condemna"),
            ("recover_joy", "com recuperar el goig espiritual"),
            ("serve_without_burning", "com servir sense cremar-me"),
            ("rest_without_guilt", "com descansar sense sentir-me culpable"),
            ("healthy_boundaries", "com posar limits sans"),
            ("love_hurting_people", "com estimar persones que m'han ferit"),
            ("share_faith_fear", "com parlar de Crist sense por"),
            ("calling", "com saber si tinc una crida"),
            ("gifts", "com descobrir els meus dons espirituals"),
            ("disciple_someone", "com discipular una altra persona"),
            ("lead_without_pride", "com liderar sense caure en orgull"),
            ("raise_children", "com criar fills en la fe"),
            ("strengthen_marriage", "com enfortir el meu matrimoni"),
            ("after_failure", "que faig despres d'un fracas"),
            ("unanswered_prayer", "com reaccionar quan una pregaria no es resposta"),
            ("grief", "com viure un dol amb fe"),
            ("sexual_purity", "com mantenir la puresa sexual"),
            ("use_money", "com fer servir els diners de manera biblica"),
            ("comparison", "com deixar de comparar-me amb els altres"),
            ("humility", "com creixer en humilitat"),
            ("spiritual_laziness", "com vencer la mandra espiritual"),
            ("obey_without_understanding", "com obeir Deu quan no ho entenc"),
            ("no_visible_fruit", "que faig si no veig fruit a la meva vida"),
            ("persevere", "com perseverar sense rendir-me"),
            ("hear_god_word", "com escoltar Deu en la Seva Paraula"),
            ("conviction_vs_condemnation", "com distingir la conviccio de l'Esperit i la condemna"),
            ("therapy", "si esta malament anar a terapia sent cristia"),
            ("help_fallen_brother", "com ajudar un germa que ha caigut"),
            ("correct_with_love", "com corregir amb amor"),
            ("rebuild_trust", "com restaurar la confianca despres de fallar"),
            ("dry_spirit", "que faig si em sento espiritualment sec"),
            ("feel_useless", "que faig si em sento inutil"),
            ("god_still_use_me", "si Deu encara em pot fer servir"),
            ("lonely_in_church", "que faig si em sento sol fins i tot a l'esglesia"),
            ("holiness_without_legalism", "com viure en santedat sense caure en legalisme"),
        ],
        "fr": [
            ("feel_far", "pourquoi je me sens loin de Dieu"),
            ("silence", "pourquoi Dieu garde le silence"),
            ("doubts", "que faire quand j'ai des doutes de foi"),
            ("no_pray_desire", "que faire si je n'ai plus envie de prier"),
            ("no_bible_desire", "que faire si j'ai du mal a lire la Bible"),
            ("prayer_distraction", "que faire si je me distrais quand je prie"),
            ("repeated_sin", "comment vaincre un peche repetitif"),
            ("forgiven_assurance", "comment savoir si Dieu m'a vraiment pardonne"),
            ("lose_salvation", "si un croyant peut perdre son salut"),
            ("suffer_believer", "pourquoi les chretiens souffrent aussi"),
            ("no_healing", "pourquoi Dieu ne guerit pas toujours"),
            ("waiting", "comment attendre quand Dieu tarde"),
            ("angry_god", "que faire si je suis en colere contre Dieu"),
            ("church_disappointment", "que faire si l'eglise m'a decu"),
            ("leader_hurt", "que faire si un responsable chretien m'a blesse"),
            ("true_forgive", "comment pardonner vraiment"),
            ("restore_god", "comment restaurer ma relation avec Dieu"),
            ("return_after_fall", "comment revenir a Dieu apres une chute"),
            ("faith_not_feelings", "comment vivre par la foi et non par les emotions"),
            ("trust_without_seeing", "comment faire confiance a Dieu sans rien voir de clair"),
            ("discern_guidance", "comment discerner si Dieu me guide"),
            ("big_decision", "comment prendre une decision difficile sans me perdre"),
            ("future_fear", "que faire si j'ai peur de l'avenir"),
            ("anxiety_believer", "comment affronter l'anxiete en tant que chretien"),
            ("overcome_temptation", "comment vaincre la tentation"),
            ("condemnation_thoughts", "comment gerer des pensees de condamnation"),
            ("recover_joy", "comment retrouver la joie spirituelle"),
            ("serve_without_burning", "comment servir sans m'epuiser"),
            ("rest_without_guilt", "comment me reposer sans culpabiliser"),
            ("healthy_boundaries", "comment poser des limites saines"),
            ("love_hurting_people", "comment aimer des personnes qui m'ont blesse"),
            ("share_faith_fear", "comment parler du Christ sans peur"),
            ("calling", "comment savoir si j'ai un appel"),
            ("gifts", "comment decouvrir mes dons spirituels"),
            ("disciple_someone", "comment accompagner quelqu'un dans la foi"),
            ("lead_without_pride", "comment diriger sans tomber dans l'orgueil"),
            ("raise_children", "comment elever des enfants dans la foi"),
            ("strengthen_marriage", "comment fortifier mon mariage"),
            ("after_failure", "que faire apres un echec"),
            ("unanswered_prayer", "comment reagir quand une priere reste sans reponse"),
            ("grief", "comment vivre un deuil avec foi"),
            ("sexual_purity", "comment garder la purete sexuelle"),
            ("use_money", "comment utiliser l'argent de maniere biblique"),
            ("comparison", "comment arreter de me comparer aux autres"),
            ("humility", "comment grandir dans l'humilite"),
            ("spiritual_laziness", "comment vaincre la paresse spirituelle"),
            ("obey_without_understanding", "comment obeir a Dieu quand je ne comprends pas"),
            ("no_visible_fruit", "que faire si je ne vois pas de fruit dans ma vie"),
            ("persevere", "comment perseverer sans abandonner"),
            ("hear_god_word", "comment entendre Dieu dans Sa Parole"),
            ("conviction_vs_condemnation", "comment distinguer la conviction de l'Esprit et la condamnation"),
            ("therapy", "si c'est mal d'aller en therapie en tant que chretien"),
            ("help_fallen_brother", "comment aider un frere qui est tombe"),
            ("correct_with_love", "comment corriger avec amour"),
            ("rebuild_trust", "comment retablir la confiance apres avoir failli"),
            ("dry_spirit", "que faire si je me sens spirituellement sec"),
            ("feel_useless", "que faire si je me sens inutile"),
            ("god_still_use_me", "si Dieu peut encore se servir de moi"),
            ("lonely_in_church", "que faire si je me sens seul meme dans l'eglise"),
            ("holiness_without_legalism", "comment vivre dans la saintete sans tomber dans le legalisme"),
        ],
        "en": [
            ("feel_far", "why I feel far from God"),
            ("silence", "why God seems silent"),
            ("doubts", "what to do when I have doubts of faith"),
            ("no_pray_desire", "what to do if I no longer feel like praying"),
            ("no_bible_desire", "what to do if it is hard for me to read the Bible"),
            ("prayer_distraction", "what to do if I get distracted while praying"),
            ("repeated_sin", "how to overcome a repeated sin"),
            ("forgiven_assurance", "how to know whether God has truly forgiven me"),
            ("lose_salvation", "whether a believer can lose salvation"),
            ("suffer_believer", "why Christians suffer too"),
            ("no_healing", "why God does not always heal"),
            ("waiting", "how to wait when God seems slow"),
            ("angry_god", "what to do if I am angry with God"),
            ("church_disappointment", "what to do if the church disappointed me"),
            ("leader_hurt", "what to do if a Christian leader hurt me"),
            ("true_forgive", "how to truly forgive"),
            ("restore_god", "how to restore my relationship with God"),
            ("return_after_fall", "how to return to God after falling"),
            ("faith_not_feelings", "how to live by faith and not by feelings"),
            ("trust_without_seeing", "how to trust God when nothing is clear"),
            ("discern_guidance", "how to discern whether God is guiding me"),
            ("big_decision", "how to make a difficult decision without getting confused"),
            ("future_fear", "what to do if I am afraid of the future"),
            ("anxiety_believer", "how to face anxiety as a Christian"),
            ("overcome_temptation", "how to overcome temptation"),
            ("condemnation_thoughts", "how to deal with condemning thoughts"),
            ("recover_joy", "how to recover spiritual joy"),
            ("serve_without_burning", "how to serve without burning out"),
            ("rest_without_guilt", "how to rest without feeling guilty"),
            ("healthy_boundaries", "how to set healthy boundaries"),
            ("love_hurting_people", "how to love people who have hurt me"),
            ("share_faith_fear", "how to speak about Christ without fear"),
            ("calling", "how to know whether I have a calling"),
            ("gifts", "how to discover my spiritual gifts"),
            ("disciple_someone", "how to disciple another person"),
            ("lead_without_pride", "how to lead without falling into pride"),
            ("raise_children", "how to raise children in the faith"),
            ("strengthen_marriage", "how to strengthen my marriage"),
            ("after_failure", "what to do after a failure"),
            ("unanswered_prayer", "how to react when a prayer is not answered"),
            ("grief", "how to walk through grief with faith"),
            ("sexual_purity", "how to maintain sexual purity"),
            ("use_money", "how to use money in a biblical way"),
            ("comparison", "how to stop comparing myself with others"),
            ("humility", "how to grow in humility"),
            ("spiritual_laziness", "how to overcome spiritual laziness"),
            ("obey_without_understanding", "how to obey God when I do not understand"),
            ("no_visible_fruit", "what to do if I do not see fruit in my life"),
            ("persevere", "how to persevere without giving up"),
            ("hear_god_word", "how to hear God in His Word"),
            ("conviction_vs_condemnation", "how to distinguish the Spirit's conviction from condemnation"),
            ("therapy", "whether it is wrong to go to therapy as a Christian"),
            ("help_fallen_brother", "how to help a brother who has fallen"),
            ("correct_with_love", "how to correct with love"),
            ("rebuild_trust", "how to rebuild trust after failing"),
            ("dry_spirit", "what to do if I feel spiritually dry"),
            ("feel_useless", "what to do if I feel useless"),
            ("god_still_use_me", "whether God can still use me"),
            ("lonely_in_church", "what to do if I feel lonely even in church"),
            ("holiness_without_legalism", "how to live in holiness without falling into legalism"),
        ],
    }.get(lang_code, [])
    preguntas_cristianos = [(clave, formatear_pregunta_cristiana(texto)) for clave, texto in fragmentos_preguntas_cristianos]
    mapa_preguntas_cristianos = {clave: texto for clave, texto in preguntas_cristianos}
    dd_cristianos = ft.Dropdown(
        label=textos_cristianos["question"],
        options=[ft.dropdown.Option(key="Ninguno", text=textos_cristianos["select_question"])] + [
            ft.dropdown.Option(key=clave, text=texto) for clave, texto in preguntas_cristianos
        ],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    dd_tamano_cristianos = ft.Dropdown(
        label=ui["words"],
        options=[
            ft.dropdown.Option(key="Ninguno", text=ui["no_selection"]),
            ft.dropdown.Option(key="50", text="50"),
            ft.dropdown.Option(key="100", text="100"),
            ft.dropdown.Option(key="150", text="150"),
            ft.dropdown.Option(key="200", text="200"),
        ],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    contenedor_biblia = ft.Container(content=dd_biblia, padding=6, border_radius=12, bgcolor=theme["field_bg"])
    contenedor_orden_libros = ft.Container(content=dd_orden_libros, padding=6, border_radius=12, bgcolor=theme["field_bg"])
    contenedor_tipo = ft.Container(
        content=dd_tipo,
        padding=10,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=14,
        bgcolor=theme["secondary"],
        expand=True,
    )
    contenedor_tamano = ft.Container(
        content=dd_tamano,
        padding=10,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=14,
        bgcolor=theme["secondary"],
        expand=True,
    )
    contenedor_comportamiento = ft.Container(
        content=dd_comportamiento,
        padding=10,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=14,
        bgcolor=theme["secondary"],
    )
    contenedor_tamano_comportamiento = ft.Container(
        content=dd_tamano_comportamiento,
        padding=10,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=14,
        bgcolor=theme["secondary"],
    )
    contenedor_incredulo = ft.Container(
        content=dd_incredulo,
        padding=10,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=14,
        bgcolor=theme["secondary"],
    )
    contenedor_tamano_incredulo = ft.Container(
        content=dd_tamano_incredulo,
        padding=10,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=14,
        bgcolor=theme["secondary"],
    )
    contenedor_cristianos = ft.Container(
        content=dd_cristianos,
        padding=10,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=14,
        bgcolor=theme["secondary"],
    )
    contenedor_tamano_cristianos = ft.Container(
        content=dd_tamano_cristianos,
        padding=10,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=14,
        bgcolor=theme["secondary"],
    )
    contenedor_tipo_tamano = ft.Container()


    def aplicar_tema_sugerido(tema: str):
        dd_tema_sugerido.value = tema
        refrescar_por_cambio()

    temas_sugeridos = sorted(
        {
            "adoracion",
            "abnegacion",
            "abundancia",
            "aceptacion",
            "afliccion",
            "agradecimiento",
            "alabanza",
            "alegria",
            "amor",
            "amor al projimo",
            "amor de Dios",
            "animo",
            "ansiedad",
            "arrepentimiento",
            "autoridad espiritual",
            "avivamiento",
            "ayuno",
            "batalla espiritual",
            "bendicion",
            "bienaventuranza",
            "bondad",
            "busqueda de Dios",
            "camino estrecho",
            "cielo",
            "compasion",
            "compromiso",
            "comunidad",
            "conocimiento de Dios",
            "consolacion",
            "confianza",
            "consagracion",
            "consuelo",
            "contentamiento",
            "conversion",
            "corazon nuevo",
            "correccion",
            "cosecha espiritual",
            "costo del discipulado",
            "creacion",
            "crecimiento espiritual",
            "crisis",
            "cruz",
            "cuidado pastoral",
            "culpa",
            "descanso",
            "debilidad",
            "decision",
            "dependencia de Dios",
            "derribando gigantes",
            "desierto espiritual",
            "desprendimiento",
            "devocion",
            "dia malo",
            "direccion de Dios",
            "disciplina",
            "discernimiento",
            "discipulado",
            "dolor",
            "dominio propio",
            "dones espirituales",
            "duda",
            "edificacion",
            "eleccion",
            "enemigos",
            "entrega",
            "escucha a Dios",
            "esperanza",
            "estabilidad",
            "eternidad",
            "evangelismo",
            "exilio",
            "familia",
            "fatiga",
            "fe",
            "fidelidad",
            "firmeza",
            "fortaleza",
            "fruto del Espiritu",
            "generosidad",
            "gozo",
            "gracia",
            "gratitud",
            "guerra espiritual",
            "guia del Espiritu Santo",
            "herencia",
            "honestidad",
            "honra",
            "hospitalidad",
            "humildad",
            "identidad en Cristo",
            "idolatria",
            "iglesia",
            "integridad",
            "intimidad con Dios",
            "justicia",
            "juicio",
            "juventud",
            "lamentacion",
            "ley de Dios",
            "libertad",
            "liderazgo",
            "limpieza del corazon",
            "llamado",
            "lucha interior",
            "madurez",
            "mansedumbre",
            "matrimonio",
            "miedo",
            "milagros",
            "ministerio",
            "misericordia",
            "mision",
            "motivos del corazon",
            "nueva vida",
            "nuevo nacimiento",
            "obediencia",
            "oracion",
            "orgullo",
            "paciencia",
            "palabra de Dios",
            "paternidad",
            "paz",
            "pecado",
            "perdon",
            "persecucion",
            "perseverancia",
            "plenitud",
            "pobreza espiritual",
            "poder de Dios",
            "preparacion",
            "presencia de Dios",
            "promesas de Dios",
            "proposito",
            "proteccion",
            "provision",
            "prueba",
            "pureza",
            "quebranto",
            "reconciliacion",
            "redencion",
            "reino de Dios",
            "relaciones",
            "renovacion",
            "reposo",
            "restauracion",
            "resurreccion",
            "reverencia",
            "riquezas",
            "sabiduria",
            "sacrificio",
            "salvacion",
            "santidad",
            "sanidad",
            "seguridad en Dios",
            "servicio",
            "temor de Dios",
            "tentacion",
            "testimonio",
            "tribulacion",
            "unidad",
            "victoria",
            "vida eterna",
        }
    )

    etiquetas_temas = {
        "adoracion": "Adoración",
        "alegria": "Alegría",
        "amor": "Amor",
        "animo": "?nimo",
        "arrepentimiento": "Arrepentimiento",
        "ayuno": "Ayuno",
        "bendicion": "Bendición",
        "bondad": "Bondad",
        "compasion": "Compasión",
        "confianza": "Confianza",
        "consagracion": "Consagración",
        "consuelo": "Consuelo",
        "contentamiento": "Contentamiento",
        "crecimiento espiritual": "Crecimiento espiritual",
        "cruz": "Cruz",
        "descanso": "Descanso",
        "direccion de Dios": "Dirección de Dios",
        "disciplina": "Disciplina",
        "discipulado": "Discipulado",
        "esperanza": "Esperanza",
        "evangelismo": "Evangelismo",
        "fe": "Fe",
        "fidelidad": "Fidelidad",
        "fortaleza": "Fortaleza",
        "generosidad": "Generosidad",
        "gozo": "Gozo",
        "gracia": "Gracia",
        "gratitud": "Gratitud",
        "humildad": "Humildad",
        "iglesia": "Iglesia",
        "justicia": "Justicia",
        "libertad": "Libertad",
        "liderazgo": "Liderazgo",
        "misericordia": "Misericordia",
        "obediencia": "Obediencia",
        "oracion": "Oración",
        "paciencia": "Paciencia",
        "palabra de Dios": "Palabra de Dios",
        "paz": "Paz",
        "perdon": "Perdón",
        "perseverancia": "Perseverancia",
        "presencia de Dios": "Presencia de Dios",
        "promesas de Dios": "Promesas de Dios",
        "proposito": "Propósito",
        "proteccion": "Protección",
        "provision": "Provisión",
        "pureza": "Pureza",
        "reconciliacion": "Reconciliación",
        "redencion": "Redención",
        "renovacion": "Renovación",
        "resurreccion": "Resurrección",
        "sabiduria": "Sabiduría",
        "salvacion": "Salvación",
        "santidad": "Santidad",
        "sanidad": "Sanidad",
        "servicio": "Servicio",
        "temor de Dios": "Temor de Dios",
        "tentacion": "Tentación",
        "testimonio": "Testimonio",
        "tribulacion": "Tribulación",
        "unidad": "Unidad",
        "victoria": "Victoria",
        "vida eterna": "Vida eterna",
    }

    theme_translations = {
        "ca": {
            "Adoración": "Adoracio",
            "Alegría": "Alegria",
            "?nimo": "Anim",
            "Bendición": "Benediccio",
            "Compasión": "Compassio",
            "Consagración": "Consagracio",
            "Dirección de Dios": "Direccio de Deu",
            "Oración": "Oracio",
            "Perdón": "Perdo",
            "Protección": "Proteccio",
            "Provisión": "Provisio",
            "Reconciliación": "Reconciliacio",
            "Redención": "Redempcio",
            "Renovación": "Renovacio",
            "Resurrección": "Resurreccio",
            "Sabiduría": "Saviesa",
            "Salvación": "Salvacio",
            "Tribulación": "Tribulacio",
            "Palabra de Dios": "Paraula de Deu",
            "Promesas de Dios": "Promeses de Deu",
            "Presencia de Dios": "Presencia de Deu",
            "Temor de Dios": "Temor de Deu",
        },
        "fr": {
            "Adoración": "Adoration",
            "Alegría": "Joie",
            "?nimo": "Courage",
            "Bendición": "Benediction",
            "Compasión": "Compassion",
            "Consagración": "Consecration",
            "Dirección de Dios": "Direction de Dieu",
            "Oración": "Priere",
            "Perdón": "Pardon",
            "Protección": "Protection",
            "Provisión": "Provision",
            "Reconciliación": "Reconciliation",
            "Redención": "Redemption",
            "Renovación": "Renouvellement",
            "Resurrección": "Resurrection",
            "Sabiduría": "Sagesse",
            "Salvación": "Salut",
            "Tribulación": "Tribulation",
            "Palabra de Dios": "Parole de Dieu",
            "Promesas de Dios": "Promesses de Dieu",
            "Presencia de Dios": "Presence de Dieu",
            "Temor de Dios": "Crainte de Dieu",
        },
        "en": {
            "Adoración": "Worship",
            "Alegría": "Joy",
            "?nimo": "Encouragement",
            "Bendición": "Blessing",
            "Compasión": "Compassion",
            "Consagración": "Consecration",
            "Dirección de Dios": "God's guidance",
            "Oración": "Prayer",
            "Perdón": "Forgiveness",
            "Protección": "Protection",
            "Provisión": "Provision",
            "Reconciliación": "Reconciliation",
            "Redención": "Redemption",
            "Renovación": "Renewal",
            "Resurrección": "Resurrection",
            "Sabiduría": "Wisdom",
            "Salvación": "Salvation",
            "Tribulación": "Tribulation",
            "Palabra de Dios": "Word of God",
            "Promesas de Dios": "Promises of God",
            "Presencia de Dios": "Presence of God",
            "Temor de Dios": "Fear of God",
        },
    }

    theme_slug_translations = {
        "ca": {
            "abnegacion": "Abnegació",
            "abundancia": "Abundància",
            "aceptacion": "Acceptació",
            "adoracion": "Adoració",
            "afliccion": "Aflicció",
            "agradecimiento": "Agraïment",
            "alabanza": "Lloança",
            "alegria": "Alegria",
            "amor": "Amor",
            "amor al projimo": "Amor al proïsme",
            "amor de Dios": "Amor de Déu",
            "animo": "Ànim",
            "ansiedad": "Ansietat",
            "arrepentimiento": "Penediment",
            "autoridad espiritual": "Autoritat espiritual",
            "avivamiento": "Avivament",
            "ayuno": "Dejuni",
            "batalla espiritual": "Batalla espiritual",
            "bendicion": "Benedicció",
            "bienaventuranza": "Benaurança",
            "bondad": "Bondat",
            "busqueda de Dios": "Recerca de Déu",
            "camino estrecho": "Camí estret",
            "cielo": "Cel",
            "compasion": "Compassió",
            "compromiso": "Compromís",
            "comunidad": "Comunitat",
            "confianza": "Confiança",
            "conocimiento de Dios": "Coneixement de Déu",
            "consagracion": "Consagració",
            "consolacion": "Consolació",
            "consuelo": "Consol",
            "contentamiento": "Contentament",
            "conversion": "Conversió",
            "corazon nuevo": "Cor nou",
            "correccion": "Correcció",
            "cosecha espiritual": "Sega espiritual",
            "costo del discipulado": "Cost del deixeblat",
            "creacion": "Creació",
            "crecimiento espiritual": "Creixement espiritual",
            "crisis": "Crisi",
            "cruz": "Creu",
            "cuidado pastoral": "Acompanyament pastoral",
            "culpa": "Culpa",
            "debilidad": "Debilitat",
            "decision": "Decisió",
            "dependencia de Dios": "Dependència de Déu",
            "derribando gigantes": "Vencent gegants",
            "descanso": "Descans",
            "desierto espiritual": "Desert espiritual",
            "desprendimiento": "Despreniment",
            "devocion": "Devoció",
            "dia malo": "Dia de prova",
            "direccion de Dios": "Direcció de Déu",
            "discernimiento": "Discerniment",
            "disciplina": "Disciplina",
            "discipulado": "Deixeblat",
            "dolor": "Dolor",
            "dominio propio": "Domini propi",
            "dones espirituales": "Dons espirituals",
            "duda": "Dubte",
            "edificacion": "Edificació",
            "eleccion": "Elecció",
            "enemigos": "Enemics",
            "entrega": "Entrega",
            "escucha a Dios": "Escoltar Déu",
            "esperanza": "Esperança",
            "estabilidad": "Estabilitat",
            "eternidad": "Eternitat",
            "evangelismo": "Evangelització",
            "exilio": "Exili",
            "familia": "Família",
            "fatiga": "Fatiga",
            "fe": "Fe",
            "fidelidad": "Fidelitat",
            "firmeza": "Fermesa",
            "fortaleza": "Fortalesa",
            "fruto del Espiritu": "Fruit de l'Esperit",
            "generosidad": "Generositat",
            "gozo": "Goig",
            "gracia": "Gràcia",
            "gratitud": "Gratitud",
            "guerra espiritual": "Guerra espiritual",
            "guia del Espiritu Santo": "Guia de l'Esperit Sant",
            "herencia": "Herència",
            "honestidad": "Honestedat",
            "honra": "Honra",
            "hospitalidad": "Hospitalitat",
            "humildad": "Humilitat",
            "identidad en Cristo": "Identitat en Crist",
            "idolatria": "Idolatria",
            "iglesia": "Església",
            "integridad": "Integritat",
            "intimidad con Dios": "Intimitat amb Déu",
            "juicio": "Judici",
            "justicia": "Justícia",
            "juventud": "Joventut",
            "lamentacion": "Lamentació",
            "ley de Dios": "Llei de Déu",
            "libertad": "Llibertat",
            "liderazgo": "Lideratge",
            "limpieza del corazon": "Puresa del cor",
            "llamado": "Crida",
            "lucha interior": "Lluita interior",
            "madurez": "Maduresa",
            "mansedumbre": "Mansuetud",
            "matrimonio": "Matrimoni",
            "miedo": "Por",
            "milagros": "Miracles",
            "ministerio": "Ministeri",
            "misericordia": "Misericòrdia",
            "mision": "Missió",
            "motivos del corazon": "Intencions del cor",
            "nueva vida": "Vida nova",
            "nuevo nacimiento": "Nou naixement",
            "obediencia": "Obediència",
            "oracion": "Oració",
            "orgullo": "Orgull",
            "paciencia": "Paciència",
            "palabra de Dios": "Paraula de Déu",
            "paternidad": "Paternitat",
            "paz": "Pau",
            "pecado": "Pecat",
            "perdon": "Perdó",
            "persecucion": "Persecució",
            "perseverancia": "Perseverança",
            "plenitud": "Plenitud",
            "pobreza espiritual": "Pobresa espiritual",
            "poder de Dios": "Poder de Déu",
            "preparacion": "Preparació",
            "presencia de Dios": "Presència de Déu",
            "promesas de Dios": "Promeses de Déu",
            "proposito": "Propòsit",
            "proteccion": "Protecció",
            "provision": "Provisió",
            "prueba": "Prova",
            "pureza": "Puresa",
            "quebranto": "Trencament interior",
            "reconciliacion": "Reconciliació",
            "redencion": "Redempció",
            "reino de Dios": "Regne de Déu",
            "relaciones": "Relacions",
            "renovacion": "Renovació",
            "reposo": "Repòs",
            "restauracion": "Restauració",
            "resurreccion": "Resurrecció",
            "reverencia": "Reverència",
            "riquezas": "Riqueses",
            "sabiduria": "Saviesa",
            "sacrificio": "Sacrifici",
            "salvacion": "Salvació",
            "sanidad": "Guarició",
            "santidad": "Santedat",
            "seguridad en Dios": "Seguretat en Déu",
            "servicio": "Servei",
            "temor de Dios": "Temor de Déu",
            "tentacion": "Temptació",
            "testimonio": "Testimoni",
            "tribulacion": "Tribulació",
            "unidad": "Unitat",
            "victoria": "Victòria",
            "vida eterna": "Vida eterna",
        },
        "fr": {
            "abnegacion": "Abnégation",
            "abundancia": "Abondance",
            "aceptacion": "Acceptation",
            "adoracion": "Adoration",
            "afliccion": "Affliction",
            "agradecimiento": "Reconnaissance",
            "alabanza": "Louange",
            "alegria": "Joie",
            "amor": "Amour",
            "amor al projimo": "Amour du prochain",
            "amor de Dios": "Amour de Dieu",
            "animo": "Courage",
            "ansiedad": "Anxiété",
            "arrepentimiento": "Repentance",
            "autoridad espiritual": "Autorité spirituelle",
            "avivamiento": "Réveil spirituel",
            "ayuno": "Jeûne",
            "batalla espiritual": "Combat spirituel",
            "bendicion": "Bénédiction",
            "bienaventuranza": "Béatitude",
            "bondad": "Bonté",
            "busqueda de Dios": "Recherche de Dieu",
            "camino estrecho": "Chemin étroit",
            "cielo": "Ciel",
            "compasion": "Compassion",
            "compromiso": "Engagement",
            "comunidad": "Communauté",
            "confianza": "Confiance",
            "conocimiento de Dios": "Connaissance de Dieu",
            "consagracion": "Consécration",
            "consolacion": "Consolation",
            "consuelo": "Réconfort",
            "contentamiento": "Contentement",
            "conversion": "Conversion",
            "corazon nuevo": "CÅ“ur nouveau",
            "correccion": "Correction",
            "cosecha espiritual": "Moisson spirituelle",
            "costo del discipulado": "Coût du discipulat",
            "creacion": "Création",
            "crecimiento espiritual": "Croissance spirituelle",
            "crisis": "Crise",
            "cruz": "Croix",
            "cuidado pastoral": "Accompagnement pastoral",
            "culpa": "Culpabilité",
            "debilidad": "Faiblesse",
            "decision": "Décision",
            "dependencia de Dios": "Dépendance envers Dieu",
            "derribando gigantes": "Vaincre les géants",
            "descanso": "Repos",
            "desierto espiritual": "Désert spirituel",
            "desprendimiento": "Détachement",
            "devocion": "Dévotion",
            "dia malo": "Jour d'épreuve",
            "direccion de Dios": "Direction de Dieu",
            "discernimiento": "Discernement",
            "disciplina": "Discipline",
            "discipulado": "Discipulat",
            "dolor": "Douleur",
            "dominio propio": "Maîtrise de soi",
            "dones espirituales": "Dons spirituels",
            "duda": "Doute",
            "edificacion": "Édification",
            "eleccion": "Élection",
            "enemigos": "Ennemis",
            "entrega": "Abandon confiant",
            "escucha a Dios": "Écouter Dieu",
            "esperanza": "Espérance",
            "estabilidad": "Stabilité",
            "eternidad": "Éternité",
            "evangelismo": "Évangélisation",
            "exilio": "Exil",
            "familia": "Famille",
            "fatiga": "Fatigue",
            "fe": "Foi",
            "fidelidad": "Fidélité",
            "firmeza": "Fermeté",
            "fortaleza": "Force",
            "fruto del Espiritu": "Fruit de l'Esprit",
            "generosidad": "Générosité",
            "gozo": "Joie",
            "gracia": "Gr?ce",
            "gratitud": "Gratitude",
            "guerra espiritual": "Guerre spirituelle",
            "guia del Espiritu Santo": "Direction du Saint-Esprit",
            "herencia": "Héritage",
            "honestidad": "Honnêteté",
            "honra": "Honneur",
            "hospitalidad": "Hospitalité",
            "humildad": "Humilité",
            "identidad en Cristo": "Identité en Christ",
            "idolatria": "Idol?trie",
            "iglesia": "Église",
            "integridad": "Intégrité",
            "intimidad con Dios": "Intimité avec Dieu",
            "juicio": "Jugement",
            "justicia": "Justice",
            "juventud": "Jeunesse",
            "lamentacion": "Lamentation",
            "ley de Dios": "Loi de Dieu",
            "libertad": "Liberté",
            "liderazgo": "Leadership",
            "limpieza del corazon": "Pureté du cœur",
            "llamado": "Appel",
            "lucha interior": "Lutte intérieure",
            "madurez": "Maturité",
            "mansedumbre": "Douceur",
            "matrimonio": "Mariage",
            "miedo": "Peur",
            "milagros": "Miracles",
            "ministerio": "Ministère",
            "misericordia": "Miséricorde",
            "mision": "Mission",
            "motivos del corazon": "Intentions du cÅ“ur",
            "nueva vida": "Vie nouvelle",
            "nuevo nacimiento": "Nouvelle naissance",
            "obediencia": "Obéissance",
            "oracion": "Prière",
            "orgullo": "Orgueil",
            "paciencia": "Patience",
            "palabra de Dios": "Parole de Dieu",
            "paternidad": "Paternité",
            "paz": "Paix",
            "pecado": "Péché",
            "perdon": "Pardon",
            "persecucion": "Persécution",
            "perseverancia": "Persévérance",
            "plenitud": "Plénitude",
            "pobreza espiritual": "Pauvreté spirituelle",
            "poder de Dios": "Puissance de Dieu",
            "preparacion": "Préparation",
            "presencia de Dios": "Présence de Dieu",
            "promesas de Dios": "Promesses de Dieu",
            "proposito": "But",
            "proteccion": "Protection",
            "provision": "Provision",
            "prueba": "Épreuve",
            "pureza": "Pureté",
            "quebranto": "Brisement intérieur",
            "reconciliacion": "Réconciliation",
            "redencion": "Rédemption",
            "reino de Dios": "Royaume de Dieu",
            "relaciones": "Relations",
            "renovacion": "Renouvellement",
            "reposo": "Repos",
            "restauracion": "Restauration",
            "resurreccion": "Résurrection",
            "reverencia": "Révérence",
            "riquezas": "Richesses",
            "sabiduria": "Sagesse",
            "sacrificio": "Sacrifice",
            "salvacion": "Salut",
            "sanidad": "Guérison",
            "santidad": "Sainteté",
            "seguridad en Dios": "Sécurité en Dieu",
            "servicio": "Service",
            "temor de Dios": "Crainte de Dieu",
            "tentacion": "Tentation",
            "testimonio": "Témoignage",
            "tribulacion": "Tribulation",
            "unidad": "Unité",
            "victoria": "Victoire",
            "vida eterna": "Vie éternelle",
        },
        "en": {
            "abnegacion": "Self-denial",
            "abundancia": "Abundance",
            "aceptacion": "Acceptance",
            "adoracion": "Worship",
            "afliccion": "Affliction",
            "agradecimiento": "Thankfulness",
            "alabanza": "Praise",
            "alegria": "Joy",
            "amor": "Love",
            "amor al projimo": "Love for others",
            "amor de Dios": "God's love",
            "animo": "Encouragement",
            "ansiedad": "Anxiety",
            "arrepentimiento": "Repentance",
            "autoridad espiritual": "Spiritual authority",
            "avivamiento": "Revival",
            "ayuno": "Fasting",
            "batalla espiritual": "Spiritual warfare",
            "bendicion": "Blessing",
            "bienaventuranza": "Blessedness",
            "bondad": "Goodness",
            "busqueda de Dios": "Seeking God",
            "camino estrecho": "The narrow path",
            "cielo": "Heaven",
            "compasion": "Compassion",
            "compromiso": "Commitment",
            "comunidad": "Community",
            "confianza": "Trust",
            "conocimiento de Dios": "Knowing God",
            "consagracion": "Consecration",
            "consolacion": "Comfort",
            "consuelo": "Comfort",
            "contentamiento": "Contentment",
            "conversion": "Conversion",
            "corazon nuevo": "A new heart",
            "correccion": "Correction",
            "cosecha espiritual": "Spiritual harvest",
            "costo del discipulado": "The cost of discipleship",
            "creacion": "Creation",
            "crecimiento espiritual": "Spiritual growth",
            "crisis": "Crisis",
            "cruz": "The cross",
            "cuidado pastoral": "Pastoral care",
            "culpa": "Guilt",
            "debilidad": "Weakness",
            "decision": "Decision",
            "dependencia de Dios": "Dependence on God",
            "derribando gigantes": "Facing giants",
            "descanso": "Rest",
            "desierto espiritual": "Spiritual desert",
            "desprendimiento": "Letting go",
            "devocion": "Devotion",
            "dia malo": "The evil day",
            "direccion de Dios": "God's guidance",
            "discernimiento": "Discernment",
            "disciplina": "Discipline",
            "discipulado": "Discipleship",
            "dolor": "Pain",
            "dominio propio": "Self-control",
            "dones espirituales": "Spiritual gifts",
            "duda": "Doubt",
            "edificacion": "Edification",
            "eleccion": "Election",
            "enemigos": "Enemies",
            "entrega": "Surrender",
            "escucha a Dios": "Listening to God",
            "esperanza": "Hope",
            "estabilidad": "Stability",
            "eternidad": "Eternity",
            "evangelismo": "Evangelism",
            "exilio": "Exile",
            "familia": "Family",
            "fatiga": "Weariness",
            "fe": "Faith",
            "fidelidad": "Faithfulness",
            "firmeza": "Steadfastness",
            "fortaleza": "Strength",
            "fruto del Espiritu": "Fruit of the Spirit",
            "generosidad": "Generosity",
            "gozo": "Joy",
            "gracia": "Grace",
            "gratitud": "Gratitude",
            "guerra espiritual": "Spiritual warfare",
            "guia del Espiritu Santo": "Guidance of the Holy Spirit",
            "herencia": "Inheritance",
            "honestidad": "Honesty",
            "honra": "Honor",
            "hospitalidad": "Hospitality",
            "humildad": "Humility",
            "identidad en Cristo": "Identity in Christ",
            "idolatria": "Idolatry",
            "iglesia": "The church",
            "integridad": "Integrity",
            "intimidad con Dios": "Intimacy with God",
            "juicio": "Judgment",
            "justicia": "Justice",
            "juventud": "Youth",
            "lamentacion": "Lament",
            "ley de Dios": "God's law",
            "libertad": "Freedom",
            "liderazgo": "Leadership",
            "limpieza del corazon": "Purity of heart",
            "llamado": "Calling",
            "lucha interior": "Inner struggle",
            "madurez": "Maturity",
            "mansedumbre": "Gentleness",
            "matrimonio": "Marriage",
            "miedo": "Fear",
            "milagros": "Miracles",
            "ministerio": "Ministry",
            "misericordia": "Mercy",
            "mision": "Mission",
            "motivos del corazon": "Motives of the heart",
            "nueva vida": "New life",
            "nuevo nacimiento": "New birth",
            "obediencia": "Obedience",
            "oracion": "Prayer",
            "orgullo": "Pride",
            "paciencia": "Patience",
            "palabra de Dios": "Word of God",
            "paternidad": "Fatherhood",
            "paz": "Peace",
            "pecado": "Sin",
            "perdon": "Forgiveness",
            "persecucion": "Persecution",
            "perseverancia": "Perseverance",
            "plenitud": "Fullness",
            "pobreza espiritual": "Spiritual poverty",
            "poder de Dios": "Power of God",
            "preparacion": "Preparation",
            "presencia de Dios": "Presence of God",
            "promesas de Dios": "Promises of God",
            "proposito": "Purpose",
            "proteccion": "Protection",
            "provision": "Provision",
            "prueba": "Trial",
            "pureza": "Purity",
            "quebranto": "Brokenness",
            "reconciliacion": "Reconciliation",
            "redencion": "Redemption",
            "reino de Dios": "Kingdom of God",
            "relaciones": "Relationships",
            "renovacion": "Renewal",
            "reposo": "Rest",
            "restauracion": "Restoration",
            "resurreccion": "Resurrection",
            "reverencia": "Reverence",
            "riquezas": "Riches",
            "sabiduria": "Wisdom",
            "sacrificio": "Sacrifice",
            "salvacion": "Salvation",
            "sanidad": "Healing",
            "santidad": "Holiness",
            "seguridad en Dios": "Security in God",
            "servicio": "Service",
            "temor de Dios": "Fear of God",
            "tentacion": "Temptation",
            "testimonio": "Testimony",
            "tribulacion": "Tribulation",
            "unidad": "Unity",
            "victoria": "Victory",
            "vida eterna": "Eternal life",
        }
    }

    def etiqueta_tema(tema: str) -> str:
        traduccion_directa = theme_slug_translations.get(lang_code, {}).get(tema)
        if traduccion_directa:
            return traduccion_directa
        base = etiquetas_temas.get(tema, tema.title())
        return theme_translations.get(lang_code, {}).get(base, base)

    def valor_localizado(valor: str | None) -> str | None:
        if valor in (None, "", "None", no_selection, "Ninguno"):
            return None
        return localize_catalog_item(str(valor))

    def obtener_contexto_activo_destacado() -> tuple[str | None, str | None]:
        activo = next((d for d in especiales if d.value != no_selection), None)
        if activo is not None:
            tipo = tipo_contexto_por_dropdown.get(activo)
            return contexto_activo_labels.get(tipo), valor_localizado(activo.value)

        if dd_tema_sugerido.value != "Ninguno":
            return contexto_activo_labels["topic"], etiqueta_tema(dd_tema_sugerido.value)

        if dd_libro.value != no_selection and dd_cap.value and dd_ini.value and dd_fin.value:
            return (
                contexto_activo_labels["passage"],
                f"{localize_book_name(dd_libro.value)} {dd_cap.value}:{dd_ini.value}-{dd_fin.value}",
            )

        return None, None

    dd_tema_sugerido = ft.Dropdown(
        label=ui["suggested_topic"].upper(),
        options=[ft.dropdown.Option(key="Ninguno", text=ui["no_selection"])],
        value="Ninguno",
        expand=True,
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    contenedor_tema_sugerido = ft.Container(
        content=dd_tema_sugerido,
        padding=6,
        border=ft.border.all(4, theme["field_border"]),
        border_radius=12,
        bgcolor=theme["field_bg"],
    )

    def aplicar_desde_desplegable_tema(e):
        manejar_bloqueos()
        refrescar_por_cambio()

    tf_pregunta = ft.TextField(
        label=ui["ask"],
        hint_text=ui["question_placeholder"],
        hint_style=ft.TextStyle(color="#9A9A9A", italic=True),
        multiline=False,
        expand=True,
        bgcolor="#FFF8DC",
        border_color=theme["field_border"],
        border_width=5,
        label_style=label_style_theme,
    )
    tf_chat_consejero = ft.TextField(
        hint_text=textos_chat_activo["placeholder"],
        hint_style=ft.TextStyle(color="#9A9A9A", italic=True),
        multiline=False,
        expand=True,
        dense=True,
        content_padding=ft.padding.symmetric(horizontal=16, vertical=14),
        bgcolor=theme["field_bg"],
        border_color=theme["field_border"],
        border_width=0,
        border_radius=24,
        text_size=15,
    )

    def borrar_pregunta(e):
        tf_pregunta.value = ""
        refrescar_por_cambio()

    btn_borrar_pregunta = ft.ElevatedButton(
        clear_question_label,
        on_click=borrar_pregunta,
        style=ft.ButtonStyle(
            color=theme["secondary_text"],
            bgcolor=theme["secondary"],
            side=ft.BorderSide(4, theme["border"]),
            shape=ft.RoundedRectangleBorder(radius=14),
        ),
        height=48,
        expand=True,
    )

    result_md = ft.Markdown(
        value="",
        selectable=True,
        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
    )
    chat_conversacion = ft.ListView(
        controls=[],
        spacing=10,
        auto_scroll=True,
        expand=True,
    )
    clipboard_service = ft.Clipboard()
    share_service = ft.Share()

    tf_resultado_vacio = ft.TextField(
        value="",
        hint_text=ui["empty_result"],
        hint_style=ft.TextStyle(color="#777777"),
        read_only=True,
        multiline=False,
        min_lines=1,
        max_lines=1,
        height=48,
        dense=True,
        content_padding=ft.padding.symmetric(horizontal=12, vertical=6),
        bgcolor=theme["accent"],
        border_color=theme["secondary"],
        border_width=5,
        label=ui["result"],
        label_style=label_style_theme,
        expand=True,
        visible=False,
    )

    pr = ft.ProgressBar(visible=False, color=theme["primary"])
    pr_comportamiento = ft.ProgressBar(visible=False, color=theme["primary"])
    pr_incredulo = ft.ProgressBar(visible=False, color=theme["primary"])
    pr_cristianos = ft.ProgressBar(visible=False, color=theme["primary"])
    pr_chat_consejero = ft.ProgressBar(visible=False, color=theme["primary"])
    vista_resultado_completa = False
    ultimo_prompt_estudio = ""
    historial_chat_consejero: list[tuple[str, str, str]] = []
    memoria_chat_consejero = ""
    ultimo_saludo_chat = ""
    tipos_intervencion_chat_consejero = (
        "empatia",
        "animo_versiculo",
        "paso_practico",
        "verdad_biblica",
    )
    indice_intervencion_chat_consejero = 0
    respuestas_desde_intervencion_chat = 0
    objetivo_intervencion_chat = random.randint(4, 5)
    objetivo_exploracion_inicial_chat = random.randint(5, 6)
    objetivo_total_chat_consejero = random.randint(14, 16)
    indice_apertura_primer_turno_chat = 0
    cierre_acompanamiento_chat_realizado = False
    saludo_inicial_chat_en_proceso = False
    espera_chat_activa = False
    animacion_espera_chat_id = 0

    texto_filtro_activo = ft.Text(
        texto_filtro_sin_activo,
        color="#666666",
        italic=True,
        size=12,
    )
    texto_resumen = ft.Text(
        f"{resumen_prefijo}: {resumen_vacio}",
        color="#666666",
        size=12,
    )
    texto_consulta_resultado = ft.Text(
        "",
        color=theme["muted"],
        size=12,
        italic=True,
        text_align=ft.TextAlign.RIGHT,
        visible=False,
    )
    texto_contexto_activo_titulo = ft.Text(
        contexto_activo_titulo,
        color=theme["primary"],
        size=11,
        weight=ft.FontWeight.W_700,
    )
    texto_contexto_activo_valor = ft.Text(
        "",
        color=theme["primary"],
        size=16,
        weight=ft.FontWeight.W_700,
    )
    contenedor_contexto_activo = ft.Container(
        content=ft.Column(
            [texto_contexto_activo_titulo, texto_contexto_activo_valor],
            spacing=4,
        ),
        padding=ft.padding.symmetric(horizontal=12, vertical=10),
        bgcolor=theme["accent"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=16,
        visible=False,
    )
    texto_estado = ft.Text(
        ui["status_ready"],
        color="#2E7D32",
        size=12,
        weight=ft.FontWeight.W_500,
    )
    texto_paso_actual = ft.Text(
        "",
        color=theme["primary"],
        size=14,
        weight=ft.FontWeight.W_700,
    )
    texto_pista_paso = ft.Text(
        "",
        color=theme["muted"],
        size=12,
    )
    texto_paso_generacion = ft.Text(
        "",
        color=theme["primary"],
        size=14,
        weight=ft.FontWeight.W_700,
    )
    texto_pista_generacion = ft.Text(
        "",
        color=theme["muted"],
        size=12,
    )
    texto_aviso_generacion = ft.Text(
        "",
        color=theme["primary"],
        size=16,
        weight=ft.FontWeight.W_700,
        text_align=ft.TextAlign.CENTER,
    )
    contenedor_aviso_generacion = ft.Container()
    pasos_interactuados = {
        "version": False,
        "book_order": False,
        "book": False,
        "chapter": False,
        "start": False,
        "end": False,
        "study_type": False,
        "words": False,
    }
    mostrar_filtros_por_vuelta = {"ok": False}
    ultimo_paso_enfocado = None
    orden_flujo = ["version", "book_order", "book", "chapter", "start", "end", "study_type", "words", "generate"]
    textos_flujo = {
        "es": {
            "version": ("Paso 1 de 9: elige la version de la Biblia.", "Empieza por la version. En cuanto la selecciones, te remarcare el siguiente paso."),
            "book_order": ("Paso 2 de 9: elige el orden de libros.", "Ahora toca decidir si quieres ver los libros en orden biblico o alfabetico."),
            "book": ("Paso 3 de 9: elige el libro.", "El siguiente paso es escoger el libro donde quieres trabajar."),
            "chapter": ("Paso 4 de 9: elige el capitulo.", "Ya tenemos el libro. Ahora selecciona el capitulo."),
            "start": ("Paso 5 de 9: elige el versiculo inicial.", "Define desde que versiculo quieres empezar el pasaje."),
            "end": ("Paso 6 de 9: elige el versiculo final.", "Marca el ultimo versiculo y te llevare al bloque de generacion."),
            "study_type": ("Paso 7 de 9: elige el tipo de estudio.", "Perfecto. Ahora vamos con el tipo de estudio que quieres generar."),
            "words": ("Paso 8 de 9: elige la cantidad de palabras.", "Solo falta decidir la extension antes de generar el resultado."),
            "generate": ("Paso 9 de 9: genera el resultado.", "Todo esta listo. Pulsa el boton para generar el resultado."),
        },
        "ca": {
            "version": ("Pas 1 de 9: tria la versio de la Biblia.", "Comenca per la versio. Quan la seleccionis, et remarcare el pas seguent."),
            "book_order": ("Pas 2 de 9: tria l'ordre dels llibres.", "Ara toca decidir si vols veure els llibres en ordre biblic o alfabeticament."),
            "book": ("Pas 3 de 9: tria el llibre.", "El pas seguent es escollir el llibre on vols treballar."),
            "chapter": ("Pas 4 de 9: tria el capitol.", "Ja tenim el llibre. Ara selecciona el capitol."),
            "start": ("Pas 5 de 9: tria el versicle inicial.", "Defineix des de quin versicle vols comencar el passatge."),
            "end": ("Pas 6 de 9: tria el versicle final.", "Marca l'ultim versicle i et portare al bloc de generacio."),
            "study_type": ("Pas 7 de 9: tria el tipus d'estudi.", "Perfecte. Ara anem amb el tipus d'estudi que vols generar."),
            "words": ("Pas 8 de 9: tria la quantitat de paraules.", "Nomes falta decidir l'extensio abans de generar el resultat."),
            "generate": ("Pas 9 de 9: genera el resultat.", "Tot esta a punt. Prem el boto per generar el resultat."),
        },
        "fr": {
            "version": ("Etape 1 sur 9 : choisis la version de la Bible.", "Commence par la version. Des que tu la choisis, je mettrai en evidence l'etape suivante."),
            "book_order": ("Etape 2 sur 9 : choisis l'ordre des livres.", "Maintenant, choisis si tu veux voir les livres dans l'ordre biblique ou alphabetique."),
            "book": ("Etape 3 sur 9 : choisis le livre.", "L'etape suivante consiste a choisir le livre a etudier."),
            "chapter": ("Etape 4 sur 9 : choisis le chapitre.", "Le livre est choisi. Selectionne maintenant le chapitre."),
            "start": ("Etape 5 sur 9 : choisis le verset initial.", "Indique a partir de quel verset le passage doit commencer."),
            "end": ("Etape 6 sur 9 : choisis le verset final.", "Choisis le dernier verset et je t'emmenerai vers le bloc de generation."),
            "study_type": ("Etape 7 sur 9 : choisis le type d'etude.", "Parfait. Passons maintenant au type d'etude a generer."),
            "words": ("Etape 8 sur 9 : choisis le nombre de mots.", "Il ne reste plus qu'a definir la longueur avant de generer le resultat."),
            "generate": ("Etape 9 sur 9 : genere le resultat.", "Tout est pret. Appuie sur le bouton pour generer le resultat."),
        },
        "en": {
            "version": ("Step 1 of 9: choose the Bible version.", "Start with the version. As soon as you select it, I will highlight the next step."),
            "book_order": ("Step 2 of 9: choose the book order.", "Now decide whether you want the books in biblical or alphabetical order."),
            "book": ("Step 3 of 9: choose the book.", "The next step is choosing the book you want to work with."),
            "chapter": ("Step 4 of 9: choose the chapter.", "The book is ready. Now select the chapter."),
            "start": ("Step 5 of 9: choose the starting verse.", "Pick the verse where the passage should begin."),
            "end": ("Step 6 of 9: choose the ending verse.", "Choose the final verse and I will take you to the generation section."),
            "study_type": ("Step 7 of 9: choose the study type.", "Great. Now pick the type of study you want to generate."),
            "words": ("Step 8 of 9: choose the word count.", "Only the length is left before generating the result."),
            "generate": ("Step 9 of 9: generate the result.", "Everything is ready. Press the button to generate the result."),
        },
    }

    def pasaje_completo() -> bool:
        return (
            dd_libro.value != no_selection
            and bool(dd_cap.value)
            and bool(dd_ini.value)
            and bool(dd_fin.value)
            and pasos_interactuados["start"]
            and pasos_interactuados["end"]
        )

    def obtener_paso_actual() -> str:
        activo = next((d for d in especiales if d.value != no_selection), None)
        tema_activo = dd_tema_sugerido.value != "Ninguno"

        if activo is not None or tema_activo:
            if dd_tipo.value == "Ninguno":
                return "study_type"
            if dd_tipo.value == "Solo versiculos":
                return "generate"
            if dd_tamano.value == "Ninguno" or not pasos_interactuados["words"]:
                return "words"
            return "generate"

        if dd_biblia.value == "Ninguna" and dd_libro.value == no_selection and not pasos_interactuados["version"]:
            return "version"
        if (dd_biblia.value != "Ninguna" or pasos_interactuados["version"]) and not pasos_interactuados["book_order"]:
            return "book_order"
        if dd_libro.value == no_selection:
            return "book"
        if not pasos_interactuados["chapter"]:
            return "chapter"
        if not pasos_interactuados["start"]:
            return "start"
        if not pasos_interactuados["end"]:
            return "end"
        if dd_tipo.value == "Ninguno":
            return "study_type"
        if dd_tipo.value == "Solo versiculos":
            return "generate"
        if dd_tamano.value == "Ninguno" or not pasos_interactuados["words"]:
            return "words"
        return "generate"

    def actualizar_textos_flujo():
        paso_actual = obtener_paso_actual()
        textos = textos_flujo.get(lang_code, textos_flujo["es"])
        titulo, pista = textos[paso_actual]
        texto_paso_actual.value = titulo
        texto_pista_paso.value = pista
        if paso_actual in {"study_type", "words", "generate"}:
            texto_paso_generacion.value = titulo
            texto_pista_generacion.value = pista
            avisos = {
                "es": {
                    "study_type": "SIGUIENTE PASO: ELIGE TIPO DE ESTUDIO",
                    "words": "SIGUIENTE PASO: ELIGE CANTIDAD DE PALABRAS",
                    "generate": "ULTIMO PASO: PULSA GENERAR RESULTADO",
                },
                "ca": {
                    "study_type": "PAS SEGÜENT: TRIA EL TIPUS D'ESTUDI",
                    "words": "PAS SEGÜENT: TRIA LA QUANTITAT DE PARAULES",
                    "generate": "ULTIM PAS: PREM GENERAR RESULTAT",
                },
                "fr": {
                    "study_type": "ETAPE SUIVANTE : CHOISIS LE TYPE D'ETUDE",
                    "words": "ETAPE SUIVANTE : CHOISIS LE NOMBRE DE MOTS",
                    "generate": "DERNIERE ETAPE : APPUIE SUR GENERER LE RESULTAT",
                },
                "en": {
                    "study_type": "NEXT STEP: CHOOSE THE STUDY TYPE",
                    "words": "NEXT STEP: CHOOSE THE WORD COUNT",
                    "generate": "FINAL STEP: PRESS GENERATE RESULT",
                },
            }
            texto_aviso_generacion.value = avisos.get(lang_code, avisos["es"])[paso_actual]
            contenedor_aviso_generacion.visible = True
            texto_paso_generacion.visible = True
            texto_pista_generacion.visible = True
        else:
            texto_paso_generacion.value = ""
            texto_pista_generacion.value = ""
            texto_aviso_generacion.value = ""
            contenedor_aviso_generacion.visible = False
            texto_paso_generacion.visible = False
            texto_pista_generacion.visible = False

    def enfocar_siguiente_paso():
        nonlocal ultimo_paso_enfocado
        paso_actual = obtener_paso_actual()
        if paso_actual == ultimo_paso_enfocado:
            return
        if paso_actual == "study_type":
            dd_tipo.focus()
            ultimo_paso_enfocado = paso_actual
        elif paso_actual == "words":
            dd_tamano.focus()
            ultimo_paso_enfocado = paso_actual
        elif paso_actual == "generate":
            ultimo_paso_enfocado = paso_actual

    def llevar_a_generacion_si_corresponde():
        paso_actual = obtener_paso_actual()
        if paso_actual in {"study_type", "words", "generate"}:
            page.scroll_to(scroll_key="panel_generacion", duration=300)

    def actualizar_versiculos(e=None):
        if dd_libro.value == no_selection or not dd_cap.value:
            dd_ini.options = []
            dd_fin.options = []
            dd_ini.value = None
            dd_fin.value = None
            if controles_montados:
                manejar_bloqueos()
                actualizar_resumen()
                page.update()
            return

        capitulo_index = int(dd_cap.value) - 1
        total_versiculos = VERSICULOS_POR_CAPITULO[dd_libro.value][capitulo_index]
        opciones_versiculos = [
            ft.dropdown.Option(key=str(i), text=str(i))
            for i in range(1, total_versiculos + 1)
        ]
        dd_ini.options = opciones_versiculos
        dd_fin.options = opciones_versiculos

        inicio_actual = int(dd_ini.value) if dd_ini.value and dd_ini.value.isdigit() else None
        fin_actual = int(dd_fin.value) if dd_fin.value and dd_fin.value.isdigit() else None

        if inicio_actual is not None:
            inicio_actual = max(1, min(inicio_actual, total_versiculos))
            dd_ini.value = str(inicio_actual)
        else:
            dd_ini.value = None

        if fin_actual is not None:
            minimo_fin = inicio_actual if inicio_actual is not None else 1
            fin_actual = max(minimo_fin, min(fin_actual, total_versiculos))
            dd_fin.value = str(fin_actual)
        else:
            dd_fin.value = None

        if controles_montados:
            manejar_bloqueos()
            actualizar_resumen()
            page.update()

    def actualizar_caps(e=None):
        if dd_libro.value == no_selection:
            dd_cap.options = []
            dd_ini.options = []
            dd_fin.options = []
            dd_cap.value = None
            dd_ini.value = None
            dd_fin.value = None
            if controles_montados:
                manejar_bloqueos()
                actualizar_resumen()
                page.update()
            return

        num = caps_por_libro[dd_libro.value]
        opts = [ft.dropdown.Option(key=str(i), text=str(i)) for i in range(1, num + 1)]
        dd_cap.options = opts
        valor_capitulo = dd_cap.value if dd_cap.value and dd_cap.value.isdigit() and 1 <= int(dd_cap.value) <= num else None
        dd_cap.value = valor_capitulo
        dd_ini.options = []
        dd_fin.options = []
        dd_ini.value = None
        dd_fin.value = None
        if dd_cap.value:
            actualizar_versiculos()
        if controles_montados:
            manejar_bloqueos()
            actualizar_resumen()
            page.update()

    def cambiar_version_pasaje(e=None):
        manejar_bloqueos()
        refrescar_por_cambio()

    def cambiar_capitulo_pasaje(e=None):
        actualizar_versiculos()
        cambiar_version_pasaje()

    def actualizar_resumen():
        partes = []
        activo = next((d for d in especiales if d.value != no_selection), None)

        if activo is not None:
            partes.append(f"{resumen_labels['filter']}: {valor_localizado(activo.value)}")
        elif dd_libro.value != no_selection:
            partes.append(f"{resumen_labels['book']}: {localize_book_name(dd_libro.value)}")
            if dd_cap.value and dd_ini.value and dd_fin.value:
                partes.append(f"{resumen_labels['passage']}: {dd_cap.value}:{dd_ini.value}-{dd_fin.value}")

        if dd_tipo.value != "Ninguno":
            partes.append(f"{resumen_labels['type']}: {localize_study_type(dd_tipo.value)}")

        if dd_tema_sugerido.value != "Ninguno":
            partes.append(f"{resumen_labels['topic']}: {etiqueta_tema(dd_tema_sugerido.value)}")

        texto_resumen.value = f"{resumen_prefijo}: " + (" | ".join(partes) if partes else resumen_vacio)

        consulta_resultado = " | ".join(partes)
        if not consulta_resultado and dd_comportamiento.value != "Ninguno":
            consulta_resultado = mapa_situaciones_comportamiento.get(dd_comportamiento.value, "")
        if not consulta_resultado and dd_incredulo.value != "Ninguno":
            consulta_resultado = mapa_preguntas_incredulo.get(dd_incredulo.value, "")
        if not consulta_resultado and dd_cristianos.value != "Ninguno":
            consulta_resultado = mapa_preguntas_cristianos.get(dd_cristianos.value, "")
        if not consulta_resultado and historial_chat_consejero:
            ultimo_usuario = next((mensaje for rol, mensaje, _ in reversed(historial_chat_consejero) if rol == "user"), "")
            if ultimo_usuario:
                consulta_resultado = ultimo_usuario[:100] + ("..." if len(ultimo_usuario) > 100 else "")
        texto_consulta_resultado.value = consulta_resultado
        texto_consulta_resultado.visible = bool(consulta_resultado)

        tipo_contexto, valor_contexto = obtener_contexto_activo_destacado()
        if tipo_contexto and valor_contexto:
            texto_contexto_activo_valor.value = f"{tipo_contexto}: {valor_contexto}"
            contenedor_contexto_activo.visible = True
        else:
            texto_contexto_activo_valor.value = ""
            contenedor_contexto_activo.visible = False

    def manejar_bloqueos(e=None):
        activo = next((d for d in especiales if d.value != no_selection), None)
        tema_activo = dd_tema_sugerido.value != "Ninguno"
        control_evento = getattr(e, "control", None)
        if control_evento in especiales or control_evento == dd_tema_sugerido:
            mostrar_filtros_por_vuelta["ok"] = False
        paso_actual = obtener_paso_actual()
        estudio_versiculos_disponible = pasaje_completo() and activo is None and not tema_activo
        if pasaje_completo():
            if lang_code == "es":
                etiqueta_estudio_informativo = "Estudio del pasaje"
            elif lang_code == "ca":
                etiqueta_estudio_informativo = "Estudi del passatge"
            elif lang_code == "fr":
                etiqueta_estudio_informativo = "Étude du passage"
            elif lang_code == "en":
                etiqueta_estudio_informativo = "Passage study"
            else:
                etiqueta_estudio_informativo = ui["study_info"]
        else:
            etiqueta_estudio_informativo = ui["study_info"]
        opciones_tipo = [
            crear_opcion_tipo(key="Ninguno", text=ui["no_selection"]),
            crear_opcion_tipo(key="Solo versiculos", text=only_verses),
            crear_opcion_tipo(key="Estudio informativo", text=etiqueta_estudio_informativo),
        ]
        if estudio_versiculos_disponible:
            opciones_tipo.append(crear_opcion_tipo(key="Estudio versiculos", text=ui["verse_study"]))
        opciones_tipo.extend(
            [
                crear_opcion_tipo(key="Reflexion biblica", text=ui["biblical_reflection"]),
                crear_opcion_tipo(key="Aplicacion practica", text=ui["practical_application"]),
                crear_opcion_tipo(key="Bosquejo para predicar", text=ui["sermon_outline"]),
                crear_opcion_tipo(key="Devocional breve", text=ui["brief_devotional"]),
                crear_opcion_tipo(
                    key="Analisis exegetico",
                    text={
                        "es": "Analisis exegetico",
                        "ca": "Analisi exegetica",
                        "fr": "Analyse exegetique",
                        "en": "Exegetical analysis",
                    }.get(lang_code, "Analisis exegetico"),
                ),
                crear_opcion_tipo(
                    key="Analisis hermeneutico",
                    text={
                        "es": "Analisis hermeneutico",
                        "ca": "Analisi hermeneutica",
                        "fr": "Analyse hermeneutique",
                        "en": "Hermeneutical analysis",
                    }.get(lang_code, "Analisis hermeneutico"),
                ),
                crear_opcion_tipo(
                    key="Analisis literario",
                    text={
                        "es": "Analisis literario",
                        "ca": "Analisi literaria",
                        "fr": "Analyse litteraire",
                        "en": "Literary analysis",
                    }.get(lang_code, "Analisis literario"),
                ),
                crear_opcion_tipo(
                    key="Analisis geografico politico",
                    text={
                        "es": "Analisis geografico y politico",
                        "ca": "Analisi geografic i politic",
                        "fr": "Analyse geographique et politique",
                        "en": "Geographic and political analysis",
                    }.get(lang_code, "Analisis geografico y politico"),
                ),
                crear_opcion_tipo(
                    key="Analisis estructura social",
                    text={
                        "es": "Analisis de estructura social",
                        "ca": "Analisi d'estructura social",
                        "fr": "Analyse de structure sociale",
                        "en": "Social structure analysis",
                    }.get(lang_code, "Analisis de estructura social"),
                ),
                crear_opcion_tipo(
                    key="Analisis vida cotidiana",
                    text={
                        "es": "Analisis de vida cotidiana y costumbres",
                        "ca": "Analisi de vida quotidiana i costums",
                        "fr": "Analyse de la vie quotidienne et des coutumes",
                        "en": "Daily life and customs analysis",
                    }.get(lang_code, "Analisis de vida cotidiana y costumbres"),
                ),
                crear_opcion_tipo(
                    key="Analisis contexto",
                    text={
                        "es": "Analisis del contexto (mundo del texto)",
                        "ca": "Analisi del context (mon del text)",
                        "fr": "Analyse du contexte (monde du texte)",
                        "en": "Context analysis (world of the text)",
                    }.get(lang_code, "Analisis del contexto (mundo del texto)"),
                ),
            ]
        )
        dd_tipo.options = opciones_tipo
        claves_tipo_validas = {opt.key for opt in opciones_tipo}
        if dd_tipo.value not in claves_tipo_validas:
            dd_tipo.value = "Ninguno"
        pasaje_activo = (
            dd_biblia.value != "Ninguna"
            or dd_libro.value != no_selection
            or (bool(dd_cap.value) and dd_libro.value != no_selection)
            or (bool(dd_ini.value) and dd_libro.value != no_selection)
            or (bool(dd_fin.value) and dd_libro.value != no_selection)
        )
        bloqueado = activo is not None or tema_activo
        color_inactivo = theme["field_bg"]
        color_activo = theme["accent"]
        color_deshabilitado = "#E6E6E6"
        borde_inactivo = theme["field_border"]
        borde_activo = theme["panel_border"]
        borde_deshabilitado = "#BDBDBD"
        color_paso = theme["accent"]

        dd_biblia.disabled = bloqueado
        dd_orden_libros.disabled = bloqueado
        dd_libro.disabled = bloqueado
        dd_cap.disabled = bloqueado
        dd_ini.disabled = bloqueado
        dd_fin.disabled = bloqueado
        dd_tema_sugerido.disabled = activo is not None or pasaje_activo
        dd_tipo.disabled = paso_actual not in {"study_type", "generate"}
        dd_tamano.disabled = paso_actual not in {"words", "generate"}
        contenedor_tipo.visible = paso_actual in {"study_type", "words", "generate"}
        contenedor_tamano.visible = paso_actual in {"words", "generate"} and dd_tipo.value != "Solo versiculos"
        try:
            btn_generar.visible = paso_actual == "generate"
        except NameError:
            pass

        for dropdown in [dd_biblia, dd_orden_libros, dd_libro, dd_cap, dd_ini, dd_fin, dd_tema_sugerido, dd_tipo, dd_tamano]:
            dropdown.border_color = borde_inactivo
            dropdown.border_width = 5
            dropdown.bgcolor = color_inactivo

        for contenedor in [
            contenedor_biblia,
            contenedor_orden_libros,
            contenedor_libro,
            contenedor_pasaje,
        ]:
            if bloqueado:
                contenedor.bgcolor = color_deshabilitado
                contenedor.border = ft.border.all(2, borde_deshabilitado)
                contenedor.opacity = 0.55
            else:
                contenedor.bgcolor = color_inactivo
                contenedor.border = ft.border.all(2, borde_inactivo)
                contenedor.opacity = 1

        contenedor_por_paso = {
            "version": contenedor_biblia,
            "book_order": contenedor_orden_libros,
            "book": contenedor_libro,
            "chapter": contenedor_pasaje,
            "start": contenedor_pasaje,
            "end": contenedor_pasaje,
        }
        dropdown_por_paso = {
            "version": dd_biblia,
            "book_order": dd_orden_libros,
            "book": dd_libro,
            "chapter": dd_cap,
            "start": dd_ini,
            "end": dd_fin,
            "study_type": dd_tipo,
            "words": dd_tamano,
        }
        contenedor_paso_actual = contenedor_por_paso.get(paso_actual)
        dropdown_paso_actual = dropdown_por_paso.get(paso_actual)
        if contenedor_paso_actual is not None and not bloqueado:
            contenedor_paso_actual.bgcolor = color_paso
            contenedor_paso_actual.border = ft.border.all(4, borde_activo)
        if dropdown_paso_actual is not None and not dropdown_paso_actual.disabled:
            dropdown_paso_actual.border_color = borde_activo
            dropdown_paso_actual.border_width = 6
            dropdown_paso_actual.bgcolor = color_paso

        if activo is not None or pasaje_activo:
            contenedor_tema_sugerido.bgcolor = color_deshabilitado
            contenedor_tema_sugerido.border = ft.border.all(2, borde_deshabilitado)
            contenedor_tema_sugerido.opacity = 0.55
        elif tema_activo:
            contenedor_tema_sugerido.bgcolor = color_activo
            contenedor_tema_sugerido.border = ft.border.all(3, borde_activo)
            contenedor_tema_sugerido.opacity = 1
        else:
            contenedor_tema_sugerido.bgcolor = color_inactivo
            contenedor_tema_sugerido.border = ft.border.all(2, borde_inactivo)
            contenedor_tema_sugerido.opacity = 1

        if dd_tipo.value != "Ninguno":
            contenedor_tipo.bgcolor = color_activo
            contenedor_tipo.border = ft.border.all(4, borde_activo)
        else:
            contenedor_tipo.bgcolor = color_inactivo
            contenedor_tipo.border = ft.border.all(4, borde_inactivo)
        contenedor_tipo.opacity = 1
        if paso_actual == "study_type":
            contenedor_tipo.bgcolor = color_paso
            contenedor_tipo.border = ft.border.all(6, borde_activo)
            dd_tipo.border_color = borde_activo
            dd_tipo.border_width = 7
            dd_tipo.bgcolor = color_paso
            contenedor_tipo.opacity = 1
        elif paso_actual == "generate":
            contenedor_tipo.opacity = 1

        if dd_tamano.value != "Ninguno":
            contenedor_tamano.bgcolor = color_activo
            contenedor_tamano.border = ft.border.all(4, borde_activo)
        else:
            contenedor_tamano.bgcolor = color_inactivo
            contenedor_tamano.border = ft.border.all(4, borde_inactivo)
        contenedor_tamano.opacity = 1
        if paso_actual == "words":
            contenedor_tamano.bgcolor = color_paso
            contenedor_tamano.border = ft.border.all(6, borde_activo)
            dd_tamano.border_color = borde_activo
            dd_tamano.border_width = 7
            dd_tamano.bgcolor = color_paso
            contenedor_tamano.opacity = 1
        elif paso_actual == "generate":
            contenedor_tamano.opacity = 1

        actualizar_textos_flujo()

        for d in especiales:
            d.disabled = (activo is not None and d != activo) or tema_activo or pasaje_activo
            contenedor = contenedores_especiales[d]
            if tema_activo or pasaje_activo:
                contenedor.bgcolor = color_deshabilitado
                contenedor.border = ft.border.all(2, borde_deshabilitado)
                contenedor.opacity = 0.55
            elif activo is None:
                contenedor.bgcolor = color_inactivo
                contenedor.border = ft.border.all(2, borde_inactivo)
                contenedor.opacity = 1
            elif d == activo:
                contenedor.bgcolor = color_activo
                contenedor.border = ft.border.all(3, borde_activo)
                contenedor.opacity = 1
            else:
                contenedor.bgcolor = color_deshabilitado
                contenedor.border = ft.border.all(2, borde_deshabilitado)
                contenedor.opacity = 0.55

        if activo is None:
            if tema_activo:
                texto_filtro_activo.value = texto_filtro_tema
                texto_filtro_activo.color = borde_activo
            elif pasaje_activo:
                texto_filtro_activo.value = texto_filtro_pasaje
                texto_filtro_activo.color = borde_activo
            else:
                texto_filtro_activo.value = texto_filtro_sin_activo
                texto_filtro_activo.color = "#666666"
        else:
            texto_filtro_activo.value = f"{texto_filtro_prefijo}: {activo.label.lower()}"
            texto_filtro_activo.color = borde_activo

        actualizar_resumen()
        if controles_montados:
            page.update()

    def refrescar_por_cambio(e=None):
        pr.visible = False
        pr_chat_consejero.visible = False
        result_md.value = ""
        texto_estado.value = ui["status_ready"]
        texto_estado.color = "#2E7D32"
        actualizar_resumen()
        manejar_bloqueos()
        actualizar_layout_responsive()
        actualizar_disposicion()
        enfocar_siguiente_paso()
        page.update()

    def contar_palabras(texto: str) -> int:
        texto_limpio = re.sub(r"[#*_>`~\-\[\]\(\)]", " ", texto or "")
        return len(re.findall(r"\b[\w??????????????]+\b", texto_limpio))

    def limpiar_texto_generado_ia(texto: str) -> str:
        if not texto:
            return texto
        texto_limpio = re.sub(r"(?:(?<=\s)|^)\?{2,}(?=\s|$|[.,;:!?)])", "", texto)
        texto_limpio = re.sub(r"\s+\?{2,}(?=[.,;:!?)])", "", texto_limpio)
        texto_limpio = texto_limpio.replace("�", "")
        texto_limpio = re.sub(r"\s+([.,;:!?])", r"\1", texto_limpio)
        texto_limpio = re.sub(r"[ \t]{2,}", " ", texto_limpio)
        texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)
        return texto_limpio.strip()

    def clasificar_escritura(caracter: str) -> str:
        if not caracter or not caracter.isalpha():
            return ""
        nombre = unicodedata.name(caracter, "")
        if "LATIN" in nombre:
            return "latin"
        if "CYRILLIC" in nombre:
            return "cyrillic"
        if "GREEK" in nombre:
            return "greek"
        if "ARABIC" in nombre:
            return "arabic"
        if "HEBREW" in nombre:
            return "hebrew"
        if any(token in nombre for token in ("CJK", "IDEOGRAPH", "HIRAGANA", "KATAKANA")):
            return "cjk"
        if "HANGUL" in nombre:
            return "hangul"
        if "THAI" in nombre:
            return "thai"
        return "other"

    def respuesta_parece_corrupta(texto: str) -> bool:
        texto_limpio = limpiar_texto_generado_ia(texto)
        if not texto_limpio or texto_limpio.startswith("Error"):
            return False

        texto_analisis = re.sub(r"`{1,3}.*?`{1,3}", " ", texto_limpio, flags=re.S)
        letras = [caracter for caracter in texto_analisis if caracter.isalpha()]
        total_letras = len(letras)
        if total_letras < 24:
            return False

        conteos: dict[str, int] = {}
        for caracter in letras:
            escritura = clasificar_escritura(caracter)
            if escritura:
                conteos[escritura] = conteos.get(escritura, 0) + 1

        no_latinas = sum(valor for clave, valor in conteos.items() if clave != "latin")
        escrituras_activas = sum(1 for valor in conteos.values() if valor >= 4)
        if no_latinas >= max(12, int(total_letras * 0.18)):
            return True
        if escrituras_activas >= 3 and no_latinas >= 8:
            return True
        if conteos.get("other", 0) >= max(8, int(total_letras * 0.12)):
            return True
        return False

    def instruccion_recuperacion_texto(mode: str) -> str:
        if lang_code == "ca":
            tipo = "l'estudi" if mode == "study" else "la resposta"
            return (
                f"La resposta anterior ha sortit corrupta o barrejada amb altres alfabets. "
                f"Torna a escriure {tipo} des de zero nomes en catala. "
                "Fes servir nomes alfabet llati, numeros normals i signes de puntuacio comuns. "
                "No facis servir cirillic, grec, arab, hebreu, xines, japones, corea, tailandes ni simbols estranys. "
                "Entrega un Markdown senzill, net i facil de llegir."
            )
        if lang_code == "fr":
            type_reponse = "l'etude" if mode == "study" else "la reponse"
            return (
                f"La reponse precedente est sortie corrompue ou melangee avec d'autres alphabets. "
                f"Reecris {type_reponse} depuis zero uniquement en francais. "
                "Utilise seulement l'alphabet latin, des chiffres normaux et une ponctuation courante. "
                "N'utilise pas le cyrillique, le grec, l'arabe, l'hebreu, le chinois, le japonais, le coreen, le thai ni des symboles etranges. "
                "Rends un Markdown simple, propre et lisible."
            )
        if lang_code == "en":
            response_type = "the study" if mode == "study" else "the answer"
            return (
                f"The previous response came out corrupted or mixed with other alphabets. "
                f"Rewrite {response_type} from scratch only in English. "
                "Use only the Latin alphabet, normal numbers, and common punctuation. "
                "Do not use Cyrillic, Greek, Arabic, Hebrew, Chinese, Japanese, Korean, Thai, or decorative symbols. "
                "Return simple, clean, readable Markdown."
            )
        tipo = "el estudio" if mode == "study" else "la respuesta"
        return (
            f"La respuesta anterior salio corrupta o mezclada con otros alfabetos. "
            f"Vuelve a escribir {tipo} desde cero solo en espanol de Espana. "
            "Usa unicamente alfabeto latino, numeros normales y signos de puntuacion comunes. "
            "No uses cirilico, griego, arabe, hebreo, chino, japones, coreano, tailandes ni simbolos raros. "
            "Entrega Markdown sencillo, limpio y facil de leer."
        )

    def mensaje_respuesta_corrupta() -> str:
        if lang_code == "ca":
            return "Error de IA: s'ha rebut un text corrupte o barrejat amb altres alfabets. Torna-ho a provar."
        if lang_code == "fr":
            return "Error de IA : un texte corrompu ou melange avec d'autres alphabets a ete recu. Reessaie."
        if lang_code == "en":
            return "Error from AI: a corrupted response mixed with other alphabets was received. Please try again."
        return "Error de IA: se recibio un texto corrupto o mezclado con otros alfabetos. Vuelve a intentarlo."

    def asegurar_respuesta_legible(respuesta: str, prompt_base: str, mode: str) -> str:
        respuesta_limpia = limpiar_texto_generado_ia(respuesta)
        if not respuesta_limpia or respuesta_limpia.startswith("Error"):
            return respuesta_limpia
        if not respuesta_parece_corrupta(respuesta_limpia):
            return respuesta_limpia

        prompt_recuperacion = f"{prompt_base}\n\n{instruccion_recuperacion_texto(mode)}"
        segunda_respuesta = consultar_ia(prompt_recuperacion, lang_code=lang_code, mode=mode)
        segunda_limpia = limpiar_texto_generado_ia(segunda_respuesta)
        if segunda_limpia and not segunda_limpia.startswith("Error") and not respuesta_parece_corrupta(segunda_limpia):
            return segunda_limpia
        return mensaje_respuesta_corrupta()

    def asignar_resultado_markdown(texto: str, limpiar: bool = False) -> None:
        result_md.value = limpiar_texto_generado_ia(texto) if limpiar else texto

    def limpiar_respuesta_chat_visible(texto: str) -> str:
        texto_limpio = limpiar_texto_generado_ia(texto)
        if not texto_limpio:
            return texto_limpio
        texto_limpio = re.sub(r"(?is)<think>.*?</think>", " ", texto_limpio)
        texto_limpio = re.sub(r"(?is)<thinking>.*?</thinking>", " ", texto_limpio)
        texto_limpio = re.sub(r"(?is)<think>.*$", " ", texto_limpio)
        texto_limpio = re.sub(r"(?is)<thinking>.*$", " ", texto_limpio)
        texto_limpio = re.sub(r"(?im)^\s*</?think>\s*$", " ", texto_limpio)
        texto_limpio = re.sub(r"(?im)^\s*</?thinking>\s*$", " ", texto_limpio)
        texto_limpio = re.sub(
            r"(?im)^\s*(consejero cristiano|consejero|assistant|chat consejero cristiano)\s*:\s*",
            "",
            texto_limpio,
        )
        texto_limpio = re.sub(
            r"(?i)(?:[¡!]*\s*am(?:e|é)n[¡!]*){3,}",
            "Amén.",
            texto_limpio,
        )
        texto_limpio = re.sub(
            r"(?i)(am(?:e|é)n[.!?]?\s+){3,}",
            "Amén. ",
            texto_limpio,
        )
        texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)
        texto_limpio = re.sub(r"\s{2,}", " ", texto_limpio)
        return texto_limpio.strip()

    async def copiar_mensaje_chat_async(texto: str) -> None:
        await clipboard_service.set(texto)
        mostrar_mensaje(page, ui["msg_copied"])

    def hora_chat_actual() -> str:
        return datetime.now().strftime("%H:%M")

    def obtener_saludo_inicial_chat() -> str:
        nonlocal ultimo_saludo_chat
        saludos = textos_chat_activo.get("greetings")
        if isinstance(saludos, list):
            saludos_validos = [saludo.strip() for saludo in saludos if isinstance(saludo, str) and saludo.strip()]
            if saludos_validos:
                candidatos = [saludo for saludo in saludos_validos if saludo != ultimo_saludo_chat]
                saludo = random.choice(candidatos or saludos_validos)
                ultimo_saludo_chat = saludo
                return saludo

        saludo = (textos_chat_activo.get("greeting") or "").strip()
        if saludo:
            ultimo_saludo_chat = saludo
        return saludo

    def reiniciar_ritmo_chat_consejero() -> None:
        nonlocal indice_intervencion_chat_consejero, respuestas_desde_intervencion_chat, objetivo_intervencion_chat, objetivo_exploracion_inicial_chat, objetivo_total_chat_consejero, indice_apertura_primer_turno_chat, cierre_acompanamiento_chat_realizado
        indice_intervencion_chat_consejero = 0
        respuestas_desde_intervencion_chat = 0
        objetivo_intervencion_chat = random.randint(4, 5)
        objetivo_exploracion_inicial_chat = random.randint(5, 6)
        objetivo_total_chat_consejero = random.randint(14, 16)
        indice_apertura_primer_turno_chat = random.randint(0, 3)
        cierre_acompanamiento_chat_realizado = False

    def obtener_ultimo_mensaje_usuario_chat_consejero() -> str:
        return next(
            (
                mensaje
                for rol, mensaje, _ in reversed(historial_chat_consejero)
                if rol == "user" and (mensaje or "").strip()
            ),
            "",
        )

    def aplazar_intervencion_ritmica_chat_consejero() -> bool:
        ultimo_mensaje = normalizar_texto_chat_consejero(obtener_ultimo_mensaje_usuario_chat_consejero())
        if not ultimo_mensaje:
            return False

        pistas_oracion = [
            "ora por mi",
            "ora por mí",
            "puedes orar",
            "podrias orar",
            "podrías orar",
            "haz una oracion",
            "haz una oración",
            "necesito oracion",
            "necesito oración",
            "oremos",
            "pray for me",
            "i need prayer",
            "can you pray",
            "prie pour moi",
            "j ai besoin de priere",
            "j'ai besoin de priere",
            "necessito pregaria",
            "pots pregar",
        ]
        if any(pista in ultimo_mensaje for pista in pistas_oracion):
            return True

        pistas_riesgo = [
            "suicid",
            "quitarme la vida",
            "quitar la vida",
            "hacerme dano",
            "hacerme daño",
            "autoles",
            "me quiero morir",
            "abuso",
            "violacion",
            "violación",
            "kill myself",
            "end my life",
            "hurt myself",
            "self harm",
            "abuse",
            "suicide",
            "me faire du mal",
            "mettre fin a ma vie",
            "mettre fin à ma vie",
            "abus",
            "fer-me mal",
            "treure m la vida",
            "treure'm la vida",
        ]
        return any(pista in ultimo_mensaje for pista in pistas_riesgo)

    def construir_instruccion_ritmica_chat_consejero() -> tuple[str, str]:
        if es_modo_chat_soporte:
            return "", "none"
        if respuestas_desde_intervencion_chat + 1 < objetivo_intervencion_chat:
            return "", "none"
        if aplazar_intervencion_ritmica_chat_consejero():
            return "", "defer"

        tipo = tipos_intervencion_chat_consejero[
            indice_intervencion_chat_consejero % len(tipos_intervencion_chat_consejero)
        ]
        instrucciones = {
            "es": {
                "empatia": "En este turno, sin decir que sigues un patron, incluye de forma natural una breve intervencion de empatia: nombra con ternura la carga que percibes, valida el dolor sin dramatizar y deja espacio para que siga hablando. No cites versiculos en esta intervencion salvo que sea imprescindible.",
                "animo_versiculo": "En este turno, sin sonar mecanico, incluye de forma natural una breve intervencion de animo con un solo versiculo o una sola referencia biblica breve que de verdad encaje. No repitas un versiculo o pasaje ya citado en este chat y no conviertas el mensaje en un mini sermon.",
                "verdad_biblica": "En este turno, introduce de forma natural una verdad biblica breve que reoriente el corazon con gracia y verdad. Habla de Cristo, del caracter de Dios o de una promesa biblica de forma sencilla, cercana y nada fria.",
                "paso_practico": "En este turno, incluye de forma natural una sola orientacion pastoral pequena y muy concreta para hoy o para esta semana. Debe nacer de lo que la persona ha contado y no sonar como una lista de tareas.",
            },
            "ca": {
                "empatia": "En aquest torn, sense dir que segueixes cap patro, inclou de manera natural una breu intervencio d'empatia: posa nom amb tendresa a la carrega que perceps, valida el dolor sense dramatitzar-lo i deixa espai perque la persona continue parlant. No cites versicles en aquesta intervencio tret que siga imprescindible.",
                "animo_versiculo": "En aquest torn, sense sonar mecanic, inclou de manera natural una breu intervencio d'anim amb un sol versicle o una sola referencia biblica breu que realment encaixe. No repetisques cap versicle o passatge ja citat en aquest xat i no ho convertisques en un mini sermo.",
                "verdad_biblica": "En aquest torn, introdueix de manera natural una veritat biblica breu que reoriente el cor amb gracia i veritat. Parla de Crist, del caracter de Deu o d'una promesa biblica de forma senzilla, propera i gens freda.",
                "paso_practico": "En aquest torn, inclou de manera natural una sola orientacio pastoral xicoteta i molt concreta per a hui o per a aquesta setmana. Ha de naixer del que la persona ha compartit i no sonar com una llista de tasques.",
            },
            "fr": {
                "empatia": "Dans ce tour, sans dire que tu suis un schema, ajoute de facon naturelle une breve intervention d'empathie: nomme avec douceur le poids que tu percois, valide la douleur sans dramatiser et laisse de la place pour que la personne continue a parler. Ne cite pas de verset dans cette intervention sauf si c'est vraiment indispensable.",
                "animo_versiculo": "Dans ce tour, sans paraitre mecanique, ajoute de facon naturelle une breve intervention d'encouragement avec un seul verset ou une seule reference biblique breve qui convienne vraiment. Ne repete pas un verset ou un passage deja cite dans ce chat et ne transforme pas le message en mini sermon.",
                "verdad_biblica": "Dans ce tour, introduis de facon naturelle une courte verite biblique qui reoriente le coeur avec grace et verite. Parle du Christ, du caractere de Dieu ou d'une promesse biblique avec simplicite, proximite et chaleur.",
                "paso_practico": "Dans ce tour, ajoute de facon naturelle une seule orientation pastorale petite et tres concrete pour aujourd'hui ou pour cette semaine. Elle doit naitre de ce que la personne a partage et ne pas ressembler a une liste de taches.",
            },
            "en": {
                "empatia": "In this turn, without saying you are following a pattern, include a brief empathic intervention naturally: gently name the burden you perceive, validate the pain without dramatizing it, and leave room for the person to keep talking. Do not quote a verse in this intervention unless it is truly necessary.",
                "animo_versiculo": "In this turn, without sounding mechanical, include a brief encouragement naturally with one short verse or one brief biblical reference that truly fits. Do not repeat a verse or passage already used in this chat, and do not turn the message into a mini sermon.",
                "verdad_biblica": "In this turn, naturally introduce one brief biblical truth that reorients the heart with grace and truth. Speak about Christ, God's character, or a biblical promise in a simple, warm, and close way.",
                "paso_practico": "In this turn, naturally include one small and very concrete pastoral step for today or this week. It should arise from what the person has shared and must not sound like a task list.",
            },
        }
        instruccion = instrucciones.get(lang_code, instrucciones["es"]).get(tipo, "")
        return instruccion, ("apply" if instruccion else "none")

    def registrar_ritmo_chat_consejero(resultado_ritmo: str) -> None:
        nonlocal indice_intervencion_chat_consejero, respuestas_desde_intervencion_chat, objetivo_intervencion_chat, cierre_acompanamiento_chat_realizado
        if es_modo_chat_soporte:
            return
        if resultado_ritmo == "close":
            cierre_acompanamiento_chat_realizado = True
            respuestas_desde_intervencion_chat = 0
            return
        if resultado_ritmo == "apply":
            indice_intervencion_chat_consejero = (
                indice_intervencion_chat_consejero + 1
            ) % len(tipos_intervencion_chat_consejero)
            respuestas_desde_intervencion_chat = 0
            objetivo_intervencion_chat = random.randint(4, 5)
            return
        if resultado_ritmo == "defer":
            return
        respuestas_desde_intervencion_chat += 1

    def agregar_instruccion_turno_chat(prompt: str, instruccion_turno: str) -> str:
        instruccion = (instruccion_turno or "").strip()
        if not instruccion:
            return prompt
        encabezados = {
            "es": "Indicacion adicional para este turno:",
            "ca": "Indicacio addicional per a aquest torn:",
            "fr": "Indication supplementaire pour ce tour :",
            "en": "Additional guidance for this turn:",
        }
        encabezado = encabezados.get(lang_code, encabezados["es"])
        return f"{prompt}\n\n{encabezado}\n{instruccion}"

    def asegurar_saludo_inicial_chat(actualizar: bool = False) -> None:
        nonlocal saludo_inicial_chat_en_proceso
        if historial_chat_consejero or saludo_inicial_chat_en_proceso:
            return
        saludo_inicial_chat_en_proceso = True

        async def tarea_saludo_inicial():
            nonlocal saludo_inicial_chat_en_proceso
            try:
                await animar_respuesta_chat_consejero(obtener_saludo_inicial_chat())
            finally:
                saludo_inicial_chat_en_proceso = False
                if actualizar:
                    page.update()

        page.run_task(tarea_saludo_inicial)

    def fragmentos_respuesta_chat(texto: str) -> list[str]:
        return list(texto) if texto else []

    def pausa_fragmento_chat(fragmento: str) -> float:
        if fragmento == " ":
            return 0.022
        if fragmento in {"\n", "\r"}:
            return 0.12
        if fragmento in {".", ",", ";", ":"}:
            return 0.09
        if fragmento in {"?", "!"}:
            return 0.12
        return 0.045

    async def desplazar_chat_al_final(inmediato: bool = False) -> None:
        duracion_lista = 0 if inmediato else 140
        duracion_pagina = 0 if inmediato else 180
        for _ in range(2):
            await asyncio.sleep(0)
            try:
                chat_conversacion.scroll_to(offset=-1, duration=duracion_lista)
            except Exception:
                pass
            try:
                page.scroll_to(scroll_key="barra_chat_consejero", duration=duracion_pagina)
            except Exception:
                pass

    def actualizar_memoria_chat_consejero() -> None:
        nonlocal memoria_chat_consejero
        if len(historial_chat_consejero) <= CHAT_HISTORY_TURNS:
            memoria_chat_consejero = ""
            return

        antiguos = historial_chat_consejero[:-CHAT_HISTORY_TURNS]
        lineas = []
        total_chars = 0
        for rol, mensaje, _ in reversed(antiguos):
            prefijo = textos_chat_activo["you"] if rol == "user" else textos_chat_activo["assistant"]
            texto = re.sub(r"\s+", " ", limpiar_respuesta_chat_visible(mensaje)).strip()
            if not texto:
                continue
            linea = f"{prefijo}: {truncar_texto_centro(texto, CHAT_SUMMARY_MESSAGE_MAX_CHARS)}"
            incremento = len(linea) + 1
            if lineas and total_chars + incremento > CHAT_SUMMARY_TOTAL_CHARS:
                break
            lineas.append(linea)
            total_chars += incremento
        memoria_chat_consejero = "\n".join(reversed(lineas)).strip()

    def compactar_respuesta_chat_consejero(texto: str) -> str:
        respuesta = limpiar_respuesta_chat_visible(texto)
        if not respuesta:
            return respuesta

        respuesta = re.sub(r"`{1,3}", "", respuesta)
        respuesta = re.sub(r"[*_#]+", "", respuesta)
        respuesta = re.sub(r"(?m)^\s*\d+\.\s*", "", respuesta)
        respuesta = re.sub(r"(?m)^\s*[-•]\s*", "", respuesta)
        respuesta = re.sub(r"\n{2,}", "\n\n", respuesta).strip()

        if es_respuesta_oracion_chat_consejero(respuesta, ""):
            if len(respuesta) > 420:
                respuesta = respuesta[:417].rstrip(" ,;:") + "..."
            return respuesta

        respuesta_plana = re.sub(r"\s*\n+\s*", " ", respuesta).strip()
        partes = re.split(r"(?<=[.!?])\s+", respuesta_plana)
        frases = []
        total = 0
        for parte in partes:
            parte_limpia = parte.strip()
            if not parte_limpia:
                continue
            incremento = len(parte_limpia) + (1 if frases else 0)
            if frases and (len(frases) >= 3 or total + incremento > 360):
                break
            frases.append(parte_limpia)
            total += incremento

        respuesta_compacta = " ".join(frases).strip() or respuesta_plana
        if len(respuesta_compacta) > 360:
            respuesta_compacta = respuesta_compacta[:357].rstrip(" ,;:") + "..."
        return respuesta_compacta

    async def animar_respuesta_chat_consejero(texto: str) -> None:
        respuesta_final = compactar_respuesta_chat_consejero(texto)
        if not respuesta_final.strip():
            respuesta_final = textos_chat_activo["fallback_response"]
        if not respuesta_final:
            return

        cursor_chat = "▌"
        hora_respuesta = hora_chat_actual()
        indice_mensaje = len(historial_chat_consejero)
        historial_chat_consejero.append(("assistant", "", hora_respuesta))
        parcial = ""
        texto_animado = ft.Text(
            cursor_chat,
            color=theme["text"],
            size=16,
            selectable=True,
        )

        sincronizar_chat_consejero_visual()
        if len(chat_conversacion.controls) > indice_mensaje:
            chat_conversacion.controls[indice_mensaje] = construir_burbuja_chat(
                "assistant",
                "",
                hora_respuesta,
                control_mensaje=texto_animado,
            )
        result_md.value = renderizar_historial_chat_consejero()
        actualizar_resumen()
        actualizar_disposicion()
        page.update()
        await desplazar_chat_al_final(inmediato=True)
        await asyncio.sleep(0.22)

        for fragmento in fragmentos_respuesta_chat(respuesta_final):
            parcial += fragmento
            if indice_mensaje >= len(historial_chat_consejero):
                return
            historial_chat_consejero[indice_mensaje] = ("assistant", parcial, hora_respuesta)
            texto_animado.value = f"{parcial}{cursor_chat}"
            result_md.value = renderizar_historial_chat_consejero()
            page.update()
            if fragmento in {" ", "\n", ".", ",", "?", "!"} or len(parcial) % 8 == 0:
                await desplazar_chat_al_final(inmediato=True)
            await asyncio.sleep(pausa_fragmento_chat(fragmento))

        if indice_mensaje >= len(historial_chat_consejero):
            return
        historial_chat_consejero[indice_mensaje] = ("assistant", respuesta_final, hora_respuesta)
        actualizar_memoria_chat_consejero()
        texto_animado.value = respuesta_final
        result_md.value = renderizar_historial_chat_consejero()
        page.update()
        await desplazar_chat_al_final(inmediato=True)

    def detener_animacion_espera_chat() -> None:
        nonlocal espera_chat_activa, animacion_espera_chat_id
        espera_chat_activa = False
        animacion_espera_chat_id += 1

    async def animar_puntos_espera_chat(identificador: int) -> None:
        color_punto_activo = theme["primary"]
        color_punto_inactivo = theme["muted"]
        puntos = [
            ft.Container(
                width=9,
                height=9,
                border_radius=ft.border_radius.all(999),
                bgcolor=color_punto_inactivo,
            )
            for _ in range(3)
        ]
        fila_puntos = ft.Row(
            controls=puntos,
            spacing=6,
            tight=True,
        )

        sincronizar_chat_consejero_visual(incluir_espera=True)
        if chat_conversacion.controls:
            chat_conversacion.controls[-1] = construir_burbuja_chat(
                "assistant",
                "",
                hora_chat_actual(),
                en_espera=True,
                control_mensaje=fila_puntos,
            )
        result_md.value = renderizar_historial_chat_consejero(incluir_espera=True)
        actualizar_resumen()
        actualizar_disposicion()
        page.update()
        await desplazar_chat_al_final(inmediato=True)

        indice = 0
        while espera_chat_activa and identificador == animacion_espera_chat_id:
            punto_activo = indice % len(puntos)
            for posicion, punto in enumerate(puntos):
                punto.bgcolor = color_punto_activo if posicion == punto_activo else color_punto_inactivo
            page.update()
            indice += 1
            await asyncio.sleep(0.35)

    def ancho_burbuja_chat_actual() -> float:
        ancho = page.width or getattr(getattr(page, "window", None), "width", 0) or 0
        if ancho <= 0:
            return 620
        if ancho < 430:
            return max(150, ancho - 140)
        if ancho < 560:
            return max(190, ancho - 118)
        if ancho < 950:
            return min(430, ancho * 0.78)
        return min(620, ancho * 0.52)

    def construir_burbuja_chat(
        rol: str,
        mensaje: str,
        hora: str,
        en_espera: bool = False,
        control_mensaje: ft.Control | None = None,
    ) -> ft.Control:
        es_usuario = rol == "user"
        color_fondo = theme["secondary"] if es_usuario else theme["panel_bg"]
        color_borde = theme["primary"] if es_usuario else theme["field_border"]
        alineacion = ft.MainAxisAlignment.END if es_usuario else ft.MainAxisAlignment.START
        ancho_burbuja = ancho_burbuja_chat_actual()
        radio = (
            ft.border_radius.only(top_left=18, top_right=18, bottom_left=18, bottom_right=6)
            if es_usuario
            else ft.border_radius.only(top_left=18, top_right=18, bottom_left=6, bottom_right=18)
        )

        if control_mensaje is not None:
            cuerpo_mensaje = control_mensaje
        elif es_usuario or en_espera:
            cuerpo_mensaje = ft.Text(
                mensaje,
                color=theme["secondary_text"] if es_usuario else theme["text"],
                italic=en_espera,
                size=16,
            )
        else:
            cuerpo_mensaje = ft.Text(
                mensaje,
                color=theme["text"],
                size=16,
                selectable=True,
            )

        burbuja = ft.Container(
            content=ft.Column(
                [
                    cuerpo_mensaje,
                    ft.Row(
                        [
                            ft.Text(
                                hora,
                                size=11,
                                color=theme["secondary_text"] if es_usuario else theme["muted"],
                            ),
                            ft.Icon(
                                ft.Icons.DONE_ALL,
                                size=14,
                                color=theme["primary_text"] if es_usuario else "transparent",
                                visible=es_usuario and not en_espera,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        spacing=4,
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            width=ancho_burbuja,
            bgcolor=color_fondo,
            border=ft.border.all(2, color_borde),
            border_radius=radio,
            shadow=ft.BoxShadow(
                blur_radius=6,
                color="#00000010",
                offset=ft.Offset(0, 2),
            ),
        )
        return ft.Row([burbuja], alignment=alineacion, spacing=6)

    def sincronizar_chat_consejero_visual(incluir_espera: bool = False) -> None:
        controles_chat: list[ft.Control] = []
        for rol, mensaje, hora in historial_chat_consejero:
            controles_chat.append(construir_burbuja_chat(rol, mensaje, hora))
        if incluir_espera:
            controles_chat.append(construir_burbuja_chat("assistant", textos_chat_activo["typing"], hora_chat_actual(), en_espera=True))
        if not controles_chat:
            controles_chat.append(
                ft.Container(
                    content=ft.Text(
                        textos_chat_activo["intro"],
                        color=theme["muted"],
                        italic=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    padding=ft.padding.symmetric(horizontal=16, vertical=22),
                    alignment=ft.Alignment(0, 0),
                )
            )
        chat_conversacion.controls = controles_chat
        result_md.value = renderizar_historial_chat_consejero(incluir_espera=incluir_espera) if historial_chat_consejero or incluir_espera else ""

    def rango_palabras_actual():
        return {
            "50": (40, 60),
            "100": (90, 110),
            "200": (180, 220),
        }.get(dd_tamano.value)

    def reforzar_respuesta_si_no_respeta_longitud(respuesta: str, prompt_base: str, mode: str) -> str:
        respuesta = asegurar_respuesta_legible(respuesta, prompt_base, mode)
        rango = rango_palabras_actual()
        if not rango or not respuesta.strip() or respuesta.strip().startswith("Error"):
            return respuesta

        total = contar_palabras(respuesta)
        minimo, maximo = rango
        if minimo <= total <= maximo:
            return respuesta

        if mode == "study":
            instruccion_extra = (
                f"CORRECCIÓN: intenta que el estudio final quede aproximadamente entre {minimo} y {maximo} palabras. "
                f"La respuesta anterior tuvo {total} palabras aproximadas. Vuelve a escribirla completa acercándote de forma razonable a ese rango, sin obsesionarte con la exactitud."
                if lang_code == "es" else
                (
                    f"CORRECCIÓ: intenta que l'estudi final quedi aproximadament entre {minimo} i {maximo} paraules. "
                    f"La resposta anterior tenia aproximadament {total} paraules. Torna'l a escriure complet acostant-te de manera raonable a aquest rang, sense obsessionar-te amb l'exactitud."
                    if lang_code == "ca" else
                    (
                        f"CORRECTION : essaie de faire en sorte que l'étude finale contienne approximativement entre {minimo} et {maximo} mots. "
                        f"La réponse précédente comptait environ {total} mots. Réécris-la entièrement en te rapprochant raisonnablement de cette plage, sans rechercher une exactitude rigide."
                        if lang_code == "fr" else
                        f"CORRECTION: try to keep the final study approximately between {minimo} and {maximo} words. The previous answer had about {total} words. Rewrite it completely while staying reasonably close to that range, without aiming for rigid precision."
                    )
                )
            )
        else:
            instruccion_extra = (
                f"CORRECCIÓN: intenta que la respuesta final quede aproximadamente entre {minimo} y {maximo} palabras. "
                f"La respuesta anterior tuvo {total} palabras aproximadas. Vuelve a escribirla completa acercándote de forma razonable a ese rango, sin obsesionarte con la exactitud."
                if lang_code == "es" else
                (
                    f"CORRECCIÓ: intenta que la resposta final quedi aproximadament entre {minimo} i {maximo} paraules. "
                    f"La resposta anterior tenia aproximadament {total} paraules. Torna-la a escriure completa acostant-te de manera raonable a aquest rang, sense obsessionar-te amb l'exactitud."
                    if lang_code == "ca" else
                    (
                        f"CORRECTION : essaie de faire en sorte que la réponse finale contienne approximativement entre {minimo} et {maximo} mots. "
                        f"La réponse précédente comptait environ {total} mots. Réécris-la entièrement en te rapprochant raisonnablement de cette plage, sans rechercher une exactitude rigide."
                        if lang_code == "fr" else
                        f"CORRECTION: try to keep the final answer approximately between {minimo} and {maximo} words. The previous answer had about {total} words. Rewrite it completely while staying reasonably close to that range, without aiming for rigid precision."
                    )
                )
            )

        prompt_refuerzo = f"{prompt_base}\n\n{instruccion_extra}"
        segunda_respuesta = consultar_ia(prompt_refuerzo, lang_code=lang_code, mode=mode)
        segunda_respuesta = asegurar_respuesta_legible(segunda_respuesta, prompt_refuerzo, mode)
        if segunda_respuesta.strip() and not segunda_respuesta.strip().startswith("Error"):
            return limpiar_texto_generado_ia(segunda_respuesta)
        return respuesta

    async def copiar_resultado(e=None):
        if not result_md.value.strip():
            mostrar_mensaje(page, ui["msg_no_content"])
            return
        await clipboard_service.set(result_md.value)
        mostrar_mensaje(page, ui["msg_copied"])

    def obtener_directorio_pdf() -> Path:
        candidatos = [
            Path("/storage/emulated/0/Download"),
            Path("/storage/emulated/0/Downloads"),
            Path("/sdcard/Download"),
            Path("/sdcard/Downloads"),
            Path.home() / "Downloads",
            Path.home() / "Descargas",
            Path.home() / "OneDrive" / "Downloads",
            Path.home() / "OneDrive" / "Descargas",
            Path.cwd(),
        ]
        for candidato in candidatos:
            if candidato.exists() and candidato.is_dir():
                return candidato

        for candidato in candidatos[:-1]:
            try:
                candidato.mkdir(parents=True, exist_ok=True)
                if candidato.exists() and candidato.is_dir():
                    return candidato
            except Exception:
                continue

        return Path.cwd()

    async def abrir_pdf_generado_async(ruta_pdf: Path):
        try:
            if os.name == "nt" and hasattr(os, "startfile"):
                os.startfile(str(ruta_pdf))
                return
        except Exception:
            pass

        try:
            await share_service.share_files(
                [ft.ShareFile.from_path(str(ruta_pdf), name=ruta_pdf.name)],
                title=ui["pdf_saved_title"],
                text=ui["msg_pdf_created"].format(path=str(ruta_pdf)),
            )
            return
        except Exception:
            pass

        try:
            await page.launch_url(ruta_pdf.resolve().as_uri())
            return
        except Exception:
            pass

        try:
            await page.launch_url(str(ruta_pdf))
        except Exception:
            pass

    async def abrir_destino_pdf_async(carpeta_destino: Path, ruta_pdf: Path):
        try:
            if os.name == "nt":
                if subprocess is None:
                    raise RuntimeError("subprocess no disponible")
                subprocess.Popen(["explorer", "/select,", str(ruta_pdf)])
                return
        except Exception:
            pass

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(carpeta_destino))
                return
        except Exception:
            pass

        try:
            await page.launch_url(carpeta_destino.resolve().as_uri())
            return
        except Exception:
            pass

        await abrir_pdf_generado_async(ruta_pdf)

    async def copiar_ruta_pdf_async(ruta_pdf: Path):
        await clipboard_service.set(str(ruta_pdf))
        mostrar_mensaje(page, ui["msg_path_copied"])

    def mostrar_dialogo_pdf_generado(carpeta_destino: Path, ruta_pdf: Path):
        dialogo = ft.AlertDialog(
            modal=False,
            title=ft.Text(ui["pdf_saved_title"]),
            content=ft.Column(
                [
                    ft.Text(ui["pdf_saved_help"]),
                    ft.TextField(
                        value=str(ruta_pdf),
                        read_only=True,
                        multiline=True,
                        min_lines=2,
                        max_lines=3,
                        bgcolor=theme["accent"],
                        border_color=theme["field_border"],
                    ),
                ],
                tight=True,
                spacing=10,
            ),
            actions=[
                ft.TextButton(ui["copy_path"], on_click=lambda e: page.run_task(copiar_ruta_pdf_async, ruta_pdf)),
                ft.TextButton(ui["open_pdf"], on_click=lambda e: page.run_task(abrir_pdf_generado_async, ruta_pdf)),
                ft.TextButton(ui["open_folder"], on_click=lambda e: page.run_task(abrir_destino_pdf_async, carpeta_destino, ruta_pdf)),
                ft.TextButton(ui["close"], on_click=lambda e: cerrar_dialogo_pdf(dialogo)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog = dialogo
        dialogo.open = True
        page.update()

    def cerrar_dialogo_pdf(dialogo: ft.AlertDialog):
        dialogo.open = False
        page.update()

    async def generar_pdf_resultado_async():
        if not result_md.value.strip():
            mostrar_mensaje(page, ui["msg_no_content"])
            return

        if page.web:
            mensaje_web = {
                "es": "La exportacion a PDF no esta disponible en la version web de Netlify.",
                "ca": "L'exportacio a PDF no esta disponible a la versio web de Netlify.",
                "fr": "L'export PDF n'est pas disponible dans la version web de Netlify.",
                "en": "PDF export is not available in the Netlify web version.",
            }.get(lang_code, "La exportacion a PDF no esta disponible en la version web.")
            mostrar_mensaje(page, mensaje_web)
            return

        try:
            actualizar_boton_pdf(True)
            page.update()
            await asyncio.sleep(0.05)
            momento = datetime.now().strftime("%Y%m%d_%H%M%S")
            carpeta_destino = obtener_directorio_pdf()
            tipo_contexto, valor_contexto = obtener_contexto_activo_destacado()
            partes_nombre = ["biblia_ia"]
            tipo_estudio = localize_study_type(dd_tipo.value)
            if tipo_estudio:
                partes_nombre.append(_slug_para_nombre_archivo(tipo_estudio, 32))
            if valor_contexto:
                partes_nombre.append(_slug_para_nombre_archivo(valor_contexto, 40))
            elif tipo_contexto:
                partes_nombre.append(_slug_para_nombre_archivo(tipo_contexto, 24))
            partes_nombre.append(momento)
            nombre_pdf = "_".join(parte for parte in partes_nombre if parte)
            ruta_pdf = carpeta_destino / f"{nombre_pdf}.pdf"
            cabecera = [
                ui["title"],
                datetime.now().strftime("%d/%m/%Y %H:%M"),
                texto_resumen.value,
                "",
                ui["result"],
                "",
            ]
            contenido_plano = _quitar_markdown_para_pdf(result_md.value)
            lineas = []
            for linea in cabecera + contenido_plano.splitlines():
                lineas.extend(_envolver_linea_pdf(linea))
            _crear_pdf_basico(ruta_pdf, lineas)
            await clipboard_service.set(str(ruta_pdf))
            await abrir_destino_pdf_async(carpeta_destino, ruta_pdf)
            mostrar_dialogo_pdf_generado(carpeta_destino, ruta_pdf)
            mostrar_mensaje(page, ui["msg_pdf_created"].format(path=str(ruta_pdf)))
        except Exception as exc:
            mostrar_mensaje(page, ui["msg_pdf_error"].format(error=exc))
        finally:
            actualizar_boton_pdf(False)
            page.update()

    def poblar_dropdown(control, items, default_key, default_text, formatter=None):
        valor_actual = control.value
        control.options = [ft.dropdown.Option(key=default_key, text=default_text)] + [
            ft.dropdown.Option(key=item, text=formatter(item) if formatter else item) for item in items
        ]
        claves = {opt.key for opt in control.options}
        control.value = valor_actual if valor_actual in claves else default_key

    def actualizar_opciones_libros(e=None):
        cambio_orden = e is not None and e.control == dd_orden_libros

        if dd_orden_libros.value == "A-Z":
            libros = libros_alfabeticos
            libro_inicial = no_selection
        else:
            libros = libros_orden_biblico
            libro_inicial = no_selection

        if cambio_orden:
            libro_actual = libro_inicial
        else:
            libro_actual = dd_libro.value if dd_libro.value in libros else libro_inicial

        dd_libro.options = [ft.dropdown.Option(key=l, text=localize_book_name(l) or l) for l in ([no_selection] + libros)]
        dd_libro.value = libro_actual
        if controles_montados:
            page.update()
        actualizar_caps()

    def construir_prompt_estudio():
        def rango_objetivo():
            return {
                "50": (40, 60),
                "100": (90, 110),
                "200": (180, 220),
                "300": (270, 330),
                "400": (360, 440),
                "500": (450, 550),
                "600": (540, 660),
            }.get(dd_tamano.value)

        instruccion_estilo_bonito = (
            "Cuida mucho la presentación visual del texto. Usa un título bonito y reverente, subtítulos claros en Markdown y una maquetación agradable. "
            "Puedes usar algunos símbolos cristianos con moderación si encajan bien, pero evita caracteres raros o iconos que no se vean correctamente. "
            "No abuses de ellos ni recargues la respuesta. "
            if lang_code == "es" else
            (
                "Cuida molt la presentació visual del text. Fes servir un títol bonic i reverent, subtítols clars en Markdown i una maquetació agradable. "
                "Pots fer servir alguns símbols cristians amb moderació si encaixen bé, però evita caràcters estranys o icones que no es vegin correctament. "
                "No n'abusis ni recarreguis la resposta. "
                if lang_code == "ca" else
                (
                    "Soigne beaucoup la présentation visuelle du texte. Utilise un beau titre révérencieux, des sous-titres clairs en Markdown et une mise en page agréable. "
                    "Tu peux utiliser quelques symboles chrétiens avec modération s'ils s'intègrent bien, mais évite les caractères étranges ou les icônes qui s'affichent mal. "
                    "N'en abuse pas et ne surcharge pas la réponse. "
                    if lang_code == "fr" else
                    "Pay close attention to the visual presentation of the text. Use a beautiful reverent title, clear Markdown subheadings, and pleasant formatting. "
                    "You may use a few Christian symbols in moderation when they fit naturally, but avoid unusual characters or icons that may render badly. "
                    "Do not overuse them or make the response feel cluttered. "
                )
            )
        )

        def limpio(valor):
            if valor in (None, "", "None", no_selection):
                return None
            return str(valor).strip()

        def limpio_localizado(valor):
            limpio_valor = limpio(valor)
            if limpio_valor is None:
                return None
            return localize_catalog_item(limpio_valor)

        sujetos = {
            "es": {
                dd_hombre: "personaje",
                dd_mujer: "personaje",
                dd_grupo: "grupo bíblico",
                dd_pueblo: "pueblo",
                dd_pais: "lugar",
                dd_religion: "religion",
            },
            "ca": {
                dd_hombre: "personatge",
                dd_mujer: "personatge",
                dd_grupo: "grup biblic",
                dd_pueblo: "poble",
                dd_pais: "lloc",
                dd_religion: "religio",
            },
            "fr": {
                dd_hombre: "personnage",
                dd_mujer: "personnage",
                dd_grupo: "groupe biblique",
                dd_pueblo: "peuple",
                dd_pais: "lieu",
                dd_religion: "religion",
            },
            "en": {
                dd_hombre: "character",
                dd_mujer: "character",
                dd_grupo: "biblical group",
                dd_pueblo: "people",
                dd_pais: "place",
                dd_religion: "religion",
            },
        }.get(lang_code, {})

        tema_texto = etiqueta_tema(dd_tema_sugerido.value) if dd_tema_sugerido.value != "Ninguno" else ""
        palabras_tema = re.findall(r"[A-Za-z\u00C0-\u00FF0-9]+", tema_texto)
        tema_de_una_palabra = len(palabras_tema) == 1
        personaje_seleccionado = limpio_localizado(dd_hombre.value) is not None or limpio_localizado(dd_mujer.value) is not None
        grupo_seleccionado = limpio_localizado(dd_grupo.value) is not None
        lugar_seleccionado = limpio_localizado(dd_pais.value) is not None
        pueblo_seleccionado = limpio_localizado(dd_pueblo.value) is not None
        religion_seleccionada = limpio_localizado(dd_religion.value) is not None
        tema_seleccionado = bool(tema_texto)
        sujeto = next(
            (f"{sujetos[d]} {limpio_localizado(d.value)}" for d in sujetos if limpio_localizado(d.value)),
            None,
        )
        libro = limpio(dd_libro.value)
        libro_localizado = localize_book_name(libro)
        cap = limpio(dd_cap.value)
        ini = limpio(dd_ini.value)
        fin = limpio(dd_fin.value)
        pasaje_exacto = f"{libro_localizado} {cap}:{ini}-{fin}" if libro_localizado and cap and ini and fin else None
        if sujeto is None and libro:
            if cap and ini and fin:
                sujeto = f"{libro_localizado} {cap}:{ini}-{fin}"
            else:
                sujeto = libro_localizado
        if sujeto is None and tema_texto:
            sujeto = (
                f"el tema {tema_texto}" if lang_code == "es"
                else (f"el tema {tema_texto}" if lang_code == "ca"
                else (f"le thème {tema_texto}" if lang_code == "fr" else f"the topic {tema_texto}"))
            )
        if sujeto is None:
            sujeto = (
                "un tema bíblico" if lang_code == "es"
                else ("un tema bíblic" if lang_code == "ca"
                else ("un thème biblique" if lang_code == "fr" else "a biblical topic"))
            )
        enfoque_tema = (
            f" Enfoca el contenido especialmente en el tema: {tema_texto}." if tema_texto and lang_code == "es"
            else (f" Centra el contingut especialment en el tema: {tema_texto}." if tema_texto and lang_code == "ca"
            else (f" Centre le contenu spécialement sur le thème : {tema_texto}." if tema_texto and lang_code == "fr"
            else (f" Focus the content especially on this topic: {tema_texto}." if tema_texto else "")))
        )

        version_texto = (
            f" usando la versión {dd_biblia.value}" if dd_biblia.value != "Ninguna" and lang_code == "es"
            else (f" usant la versió {dd_biblia.value}" if dd_biblia.value != "Ninguna" and lang_code == "ca"
            else (f" en utilisant la version {dd_biblia.value}" if dd_biblia.value != "Ninguna" and lang_code == "fr"
            else (f" using the version {dd_biblia.value}" if dd_biblia.value != "Ninguna" else "")))
        )
        if pasaje_exacto:
            if lang_code == "es":
                instruccion_pasaje = (
                    f" Abre la respuesta citando primero los versículos exactos de {pasaje_exacto}{version_texto} bajo el subtítulo 'Versículos seleccionados'. "
                    "Después desarrolla el estudio o la reflexión a partir de ese pasaje, sin sustituirlo por otros versículos al comienzo. "
                )
            elif lang_code == "ca":
                instruccion_pasaje = (
                    f" Obre la resposta citant primer els versicles exactes de {pasaje_exacto}{version_texto} sota el subtítol 'Versicles seleccionats'. "
                    "Després desenvolupa l'estudi o la reflexió a partir d'aquest passatge, sense substituir-lo per altres versicles al començament. "
                )
            elif lang_code == "fr":
                instruccion_pasaje = (
                    f" Ouvre la réponse en citant d'abord les versets exacts de {pasaje_exacto}{version_texto} sous le sous-titre 'Versets sélectionnés'. "
                    "Développe ensuite l'étude ou la réflexion à partir de ce passage, sans le remplacer par d'autres versets au début. "
                )
            else:
                instruccion_pasaje = (
                    f" Open the response by first citing the exact verses from {pasaje_exacto}{version_texto} under the subtitle 'Selected verses'. "
                    "Then develop the study or reflection from that passage without replacing it with other verses at the beginning. "
                )
        else:
            instruccion_pasaje = ""

        instruccion_tema_breve = ""
        if dd_tipo.value == "Estudio informativo" and tema_texto and tema_de_una_palabra:
            instruccion_tema_breve = (
                "Empieza obligatoriamente con un apartado breve titulado 'Definición', donde expliques con claridad qué significa esa palabra en contexto bíblico. "
                "A continuación añade otro apartado breve titulado 'Sinónimos o matices cercanos', con uno o varios sinónimos, términos relacionados o matices de sentido. "
                "Solo después desarrolla el estudio completo. "
                if lang_code == "es" else
                (
                    "Comença obligatòriament amb un apartat breu titulat 'Definició', on expliquis amb claredat què significa aquesta paraula en context bíblic. "
                    "A continuació afegeix un altre apartat breu titulat 'Sinònims o matisos propers', amb un o diversos sinònims, termes relacionats o matisos de sentit. "
                    "Només després desenvolupa l'estudi complet. "
                    if lang_code == "ca" else
                    (
                        "Commence obligatoirement par une brève section intitulée 'Définition', où tu expliques clairement ce que signifie ce mot dans le contexte biblique. "
                        "Ajoute ensuite une autre brève section intitulée 'Synonymes ou nuances proches', avec un ou plusieurs synonymes, termes liés ou nuances de sens. "
                        "Ce n'est qu'ensuite que tu développes l'étude complète. "
                        if lang_code == "fr" else
                        "Begin with a short section titled 'Definition', clearly explaining what that word means in a biblical context. "
                        "Then add another short section titled 'Synonyms or related nuances', including one or more synonyms, related terms, or shades of meaning. "
                        "Only after that should you develop the full study. "
                    )
                )
            )

        if dd_tipo.value == "Solo versiculos":
            if lang_code == "es":
                return (
                    f"Devuélveme únicamente los versículos exactos de {sujeto}{version_texto}.{enfoque_tema} "
                    "No generes comentarios, explicaciones ni interpretaciones. "
                    "No inventes versículos. "
                    "Formato: Markdown limpio."
                )
            if lang_code == "ca":
                return (
                    f"Torna'm només els versicles exactes de {sujeto}{version_texto}.{enfoque_tema} "
                    "No generis comentaris, explicacions ni interpretacions. "
                    "No inventis versicles. "
                    "Format: Markdown net."
                )
            if lang_code == "fr":
                return (
                    f"Donne-moi uniquement les versets exacts de {sujeto}{version_texto}.{enfoque_tema} "
                    "Ne génère ni commentaires, ni explications, ni interprétations. "
                    "N'invente pas de versets. "
                    "Format : Markdown propre."
                )
            return (
                f"Return only the exact verses about {sujeto}{version_texto}.{enfoque_tema} "
                "Do not generate comments, explanations, or interpretations. "
                "Do not invent verses. "
                "Format: clean Markdown."
            )

        instrucciones_tipo = {
            "Estudio informativo": (
                    (
                        "Redacta un estudio informativo de personaje, objetivo, ordenado y con enfoque de estudio bíblico serio. "
                        "Organiza el contenido con estos tres grandes apartados y subtítulos claros: "
                        "'1. Perfil biográfico', '2. Cronología de su vida' y '3. Perfil de carácter'. "
                        "En 'Perfil biográfico' incluye, cuando sea posible, significado del nombre, genealogía y familia, contexto geográfico y ocupación o papel principal. "
                        "En 'Cronología de su vida' resume su llamado o comienzo, los acontecimientos clave, sus crisis y fracasos, y el final de su vida o su última mención bíblica. "
                        "En 'Perfil de carácter' analiza fortalezas, debilidades y relaciones con otras personas. "
                        "No idealices al personaje ni ignores sus pecados o límites. "
                        "Prioriza siempre los datos bíblicos reales y distingue con cuidado entre lo explícito y lo inferido. "
                        "No incluyas una aplicación devocional extensa salvo que sea muy breve al final. "
                    ) if personaje_seleccionado else (
                    "Redacta un estudio informativo de grupo bíblico, objetivo, ordenado y con enfoque de sociología bíblica seria. "
                    "Organiza el contenido con estos cinco grandes apartados y subtítulos claros: "
                    "'1. Identidad y origen', '2. Teología y dogmas', '3. Esfera de influencia', '4. Encuentro con el mensaje bíblico' y '5. Ocaso y legado'. "
                    "En 'Identidad y origen' incluye etimología, surgimiento histórico y composición social del grupo. "
                    "En 'Teología y dogmas' explica su canon de autoridad, lo que negaban y lo que afirmaban. "
                    "En 'Esfera de influencia' desarrolla su centro de poder, relación con el Estado y rivalidades con otros grupos. "
                    "En 'Encuentro con el mensaje bíblico' analiza su relación con Jesús y, si corresponde, con la Iglesia primitiva u otras figuras centrales. "
                    "En 'Ocaso y legado' explica cómo terminó el grupo y qué huella dejó. "
                    "No reduzcas el estudio a una simple definición rápida; explica también mentalidad, poder e impacto bíblico. "
                    "Prioriza siempre los datos bíblicos reales y distingue con cuidado entre lo explícito y lo inferido. "
                    "No incluyas una aplicación devocional extensa salvo que sea muy breve al final. "
                    ) if grupo_seleccionado else (
                    "Redacta un estudio informativo de lugar geográfico, objetivo, ordenado y con enfoque de geografía bíblica seria. "
                    "Organiza el contenido con estos tres grandes apartados y subtítulos claros: "
                    "'1. Ubicación y topografía', '2. Historia y arqueología' y '3. Eventos bíblicos clave'. "
                    "En 'Ubicación y topografía' incluye nombre y etimología, región o coordenadas aproximadas, características físicas y recursos naturales o valor estratégico. "
                    "En 'Historia y arqueología' explica sus primeras menciones, hallazgos arqueológicos relevantes y evolución política en distintas épocas. "
                    "En 'Eventos bíblicos clave' resume cronológicamente los encuentros con Dios, batallas, milagros y personajes asociados a ese lugar. "
                    "No conviertas el estudio en una simple lista de versículos: explica por qué ese lugar importa en la narrativa bíblica. "
                    "Prioriza siempre los datos bíblicos reales y distingue con cuidado entre lo explícito, lo histórico y lo inferido. "
                    "No incluyas una aplicación devocional extensa salvo que sea muy breve al final. "
                    ) if lugar_seleccionado else (
                    "Redacta un estudio informativo sobre una religión o rama del cristianismo, objetivo, ordenado y con enfoque histórico-doctrinal comparativo. "
                    "Organiza el contenido con estos cuatro grandes apartados y subtítulos claros: "
                    "'1. Orígenes e historia', '2. Autoridad y fuentes de revelación', '3. Pilares doctrinales' y '4. Prácticas y sacramentos'. "
                    "En 'Orígenes e historia' incluye fundación, personajes clave, motivo de surgimiento y cronología principal. "
                    "En 'Autoridad y fuentes de revelación' explica el lugar que ocupa la Biblia, el canon que acepta y la relación entre Escritura y tradición. "
                    "En 'Pilares doctrinales' analiza especialmente la salvación, la persona de Jesús y la comprensión de la Iglesia o de la autoridad religiosa. "
                    "En 'Prácticas y sacramentos' resume cómo viven su fe, sus ritos principales, su forma de adoración y su ética. "
                    "Cuando sea apropiado, compara de manera clara y respetuosa con la enseñanza bíblica histórica o con otras tradiciones cristianas, sin caricaturizar. "
                    "Mantén un tono informativo, preciso y respetuoso, evitando polémica innecesaria. "
                    "No incluyas una aplicación devocional extensa salvo que sea muy breve al final. "
                    ) if religion_seleccionada else (
                    "Redacta un estudio informativo de pueblo o nación, objetivo, ordenado y con enfoque de estudio bíblico serio. "
                    "Organiza el contenido con estos tres grandes apartados y subtítulos claros: "
                    "'1. Identidad y origen', '2. Cultura y religión' y '3. Interacción con el pueblo de Dios'. "
                    "En 'Identidad y origen' incluye, cuando sea posible, ancestro fundador, significado del nombre o gentilicio y ubicación geográfica. "
                    "En 'Cultura y religión' explica sus dioses o creencias principales, prácticas cultuales y rasgos de su estructura social o modo de vida. "
                    "En 'Interacción con el pueblo de Dios' desarrolla el tipo de relación con Israel o con el pueblo de Dios, los conflictos clave y la influencia mutua o el sincretismo si existió. "
                    "Prioriza siempre los datos bíblicos reales y distingue con cuidado entre lo explícito y lo inferido. "
                    "No reduzcas el estudio a una simple lista de batallas; explica también identidad, cosmovisión y papel teológico en la narrativa bíblica. "
                    "No incluyas una aplicación devocional extensa salvo que sea muy breve al final. "
                    ) if pueblo_seleccionado else (
                    "Redacta un estudio informativo temático, objetivo, ordenado y con enfoque de estudio bíblico serio. "
                    "Organiza el contenido con estos cinco grandes apartados y subtítulos claros: "
                    "'1. Definición y etimología', '2. Fundamento teológico', '3. Base bíblica estructurada', '4. Ejemplos prácticos' y '5. Beneficios y consecuencias'. "
                    "En 'Definición y etimología' explica qué significa el tema en contexto bíblico y, cuando sea posible, menciona términos originales, matices, sinónimos y antónimos. "
                    "En 'Fundamento teológico' muestra cómo ese tema se ve primero en el carácter de Dios y, cuando corresponda, también en Cristo. "
                    "En 'Base bíblica estructurada' no lances versículos al azar: agrúpalos por categorías o áreas claras. "
                    "En 'Ejemplos prácticos' incluye modelos positivos y negativos dentro de la Biblia. "
                    "En 'Beneficios y consecuencias' explica qué produce ese tema en la vida del creyente y por qué es importante. "
                    "Prioriza siempre los datos bíblicos reales y distingue con cuidado entre lo explícito y lo inferido. "
                    "No incluyas una aplicación devocional extensa salvo que sea muy breve al final. "
                    ) if tema_seleccionado else (
                    "Redacta un estudio informativo, objetivo, ordenado y con enfoque de estudio bíblico serio. "
                    "Organiza el contenido, en la medida en que encaje con el pasaje o tema, en tres grandes apartados con subtítulos claros: "
                    "'1. Marco contextual', '2. Análisis del texto' y '3. Exégesis y doctrina'. "
                    "En 'Marco contextual' incluye, cuando sea posible, autor y fecha, destinatarios, contexto histórico-cultural y propósito del libro. "
                    "En 'Análisis del texto' explica el género literario, palabras clave y la estructura del pasaje o del tema tratado. "
                    "En 'Exégesis y doctrina' desarrolla el significado original del texto para sus primeros oyentes o lectores, la enseñanza central y las doctrinas principales implicadas. "
                    "Evita saltar demasiado rápido a la aplicación personal; primero prioriza la intención original del autor. "
                    "No incluyas una aplicación devocional extensa salvo que sea muy breve al final. "
                    )
                if lang_code == "es" else
                (
                    (
                        "Redacta un estudi informatiu de personatge, objectiu, ordenat i amb enfocament de veritable estudi bíblic. "
                        "Organitza el contingut amb aquests tres grans apartats i subtítols clars: "
                        "'1. Perfil biogràfic', '2. Cronologia de la seva vida' i '3. Perfil de caràcter'. "
                        "A 'Perfil biogràfic' inclou, quan sigui possible, significat del nom, genealogia i família, context geogràfic i ocupació o paper principal. "
                        "A 'Cronologia de la seva vida' resumeix la seva crida o inici, els esdeveniments clau, les seves crisis i fracassos, i el final de la seva vida o la seva última menció bíblica. "
                        "A 'Perfil de caràcter' analitza fortaleses, debilitats i relacions amb altres persones. "
                        "No idealitzis el personatge ni ignoris els seus pecats o límits. "
                        "Prioritza sempre les dades bíbliques reals i distingeix amb cura entre el que és explícit i el que és inferit. "
                        "No hi incloguis una aplicació devocional extensa, tret que sigui molt breu al final. "
                    ) if personaje_seleccionado else (
                    "Redacta un estudi informatiu de grup bíblic, objectiu, ordenat i amb enfocament de sociologia bíblica seriosa. "
                    "Organitza el contingut amb aquests cinc grans apartats i subtítols clars: "
                    "'1. Identitat i origen', '2. Teologia i dogmes', '3. Esfera d'influència', '4. Trobada amb el missatge bíblic' i '5. Ocaso i llegat'. "
                    "A 'Identitat i origen' inclou etimologia, sorgiment històric i composició social del grup. "
                    "A 'Teologia i dogmes' explica el seu cànon d'autoritat, allò que negaven i allò que afirmaven. "
                    "A 'Esfera d'influència' desenvolupa el seu centre de poder, la relació amb l'Estat i les rivalitats amb altres grups. "
                    "A 'Trobada amb el missatge bíblic' analitza la seva relació amb Jesús i, si escau, amb l'Església primitiva o altres figures centrals. "
                    "A 'Ocaso i llegat' explica com va acabar el grup i quina empremta va deixar. "
                    "No redueixis l'estudi a una simple definició ràpida; explica també mentalitat, poder i impacte bíblic. "
                    "Prioritza sempre les dades bíbliques reals i distingeix amb cura entre el que és explícit i el que és inferit. "
                    "No hi incloguis una aplicació devocional extensa, tret que sigui molt breu al final. "
                    ) if grupo_seleccionado else (
                    "Redacta un estudi informatiu de lloc geogràfic, objectiu, ordenat i amb enfocament de geografia bíblica seriosa. "
                    "Organitza el contingut amb aquests tres grans apartats i subtítols clars: "
                    "'1. Ubicació i topografia', '2. Història i arqueologia' i '3. Esdeveniments bíblics clau'. "
                    "A 'Ubicació i topografia' inclou nom i etimologia, regió o coordenades aproximades, característiques físiques i recursos naturals o valor estratègic. "
                    "A 'Història i arqueologia' explica les primeres mencions, els descobriments arqueològics rellevants i l'evolució política en diferents èpoques. "
                    "A 'Esdeveniments bíblics clau' resumeix cronològicament les trobades amb Déu, batalles, miracles i personatges associats a aquest lloc. "
                    "No converteixis l'estudi en una simple llista de versicles: explica per què aquest lloc és important en la narrativa bíblica. "
                    "Prioritza sempre les dades bíbliques reals i distingeix amb cura entre el que és explícit, el que és històric i el que és inferit. "
                    "No hi incloguis una aplicació devocional extensa, tret que sigui molt breu al final. "
                    ) if lugar_seleccionado else (
                    "Redacta un estudi informatiu sobre una religió o branca del cristianisme, objectiu, ordenat i amb enfocament històric-doctrinal comparatiu. "
                    "Organitza el contingut amb aquests quatre grans apartats i subtítols clars: "
                    "'1. Orígens i història', '2. Autoritat i fonts de revelació', '3. Pilars doctrinals' i '4. Pràctiques i sagraments'. "
                    "A 'Orígens i història' inclou fundació, personatges clau, motiu de sorgiment i cronologia principal. "
                    "A 'Autoritat i fonts de revelació' explica el lloc que ocupa la Bíblia, el cànon que accepta i la relació entre Escriptura i tradició. "
                    "A 'Pilars doctrinals' analitza especialment la salvació, la persona de Jesús i la comprensió de l'Església o de l'autoritat religiosa. "
                    "A 'Pràctiques i sagraments' resumeix com viuen la fe, els ritus principals, la forma d'adoració i l'ètica. "
                    "Quan sigui apropiat, compara de manera clara i respectuosa amb l'ensenyament bíblic històric o amb altres tradicions cristianes, sense caricaturitzar. "
                    "Mantingues un to informatiu, precís i respectuós, evitant polèmica innecessària. "
                    "No hi incloguis una aplicació devocional extensa, tret que sigui molt breu al final. "
                    ) if religion_seleccionada else (
                    "Redacta un estudi informatiu de poble o nació, objectiu, ordenat i amb enfocament de veritable estudi bíblic. "
                    "Organitza el contingut amb aquests tres grans apartats i subtítols clars: "
                    "'1. Identitat i origen', '2. Cultura i religió' i '3. Interacció amb el poble de Déu'. "
                    "A 'Identitat i origen' inclou, quan sigui possible, ancestre fundador, significat del nom o gentilici i ubicació geogràfica. "
                    "A 'Cultura i religió' explica els seus déus o creences principals, les pràctiques cultuals i els trets de la seva estructura social o manera de viure. "
                    "A 'Interacció amb el poble de Déu' desenvolupa el tipus de relació amb Israel o amb el poble de Déu, els conflictes clau i la influència mútua o el sincretisme si n'hi va haver. "
                    "Prioritza sempre les dades bíbliques reals i distingeix amb cura entre el que és explícit i el que és inferit. "
                    "No redueixis l'estudi a una simple llista de batalles; explica també identitat, cosmovisió i paper teològic dins la narrativa bíblica. "
                    "No hi incloguis una aplicació devocional extensa, tret que sigui molt breu al final. "
                    ) if pueblo_seleccionado else (
                    "Redacta un estudi informatiu temàtic, objectiu, ordenat i amb enfocament de veritable estudi bíblic. "
                    "Organitza el contingut amb aquests cinc grans apartats i subtítols clars: "
                    "'1. Definició i etimologia', '2. Fonament teològic', '3. Base bíblica estructurada', '4. Exemples pràctics' i '5. Beneficis i conseqüències'. "
                    "A 'Definició i etimologia' explica què significa el tema en context bíblic i, quan sigui possible, esmenta termes originals, matisos, sinònims i antònims. "
                    "A 'Fonament teològic' mostra com aquest tema es veu primer en el caràcter de Déu i, quan correspongui, també en Crist. "
                    "A 'Base bíblica estructurada' no llancis versicles a l'atzar: agrupa'ls per categories o àrees clares. "
                    "A 'Exemples pràctics' inclou models positius i negatius dins la Bíblia. "
                    "A 'Beneficis i conseqüències' explica què produeix aquest tema en la vida del creient i per què és important. "
                    "Prioritza sempre les dades bíbliques reals i distingeix amb cura entre el que és explícit i el que és inferit. "
                    "No hi incloguis una aplicació devocional extensa, tret que sigui molt breu al final. "
                    ) if tema_seleccionado else (
                    "Redacta un estudi informatiu, objectiu, ordenat i amb enfocament de veritable estudi bíblic. "
                    "Organitza el contingut, en la mesura que encaixi amb el passatge o el tema, en tres grans apartats amb subtítols clars: "
                    "'1. Marc contextual', '2. Anàlisi del text' i '3. Exegesi i doctrina'. "
                    "A 'Marc contextual' inclou, quan sigui possible, autor i data, destinataris, context històric-cultural i propòsit del llibre. "
                    "A 'Anàlisi del text' explica el gènere literari, les paraules clau i l'estructura del passatge o del tema tractat. "
                    "A 'Exegesi i doctrina' desenvolupa el significat original del text per als primers oients o lectors, l'ensenyament central i les doctrines principals implicades. "
                    "Evita passar massa ràpid a l'aplicació personal; primer prioritza la intenció original de l'autor. "
                    "No hi incloguis una aplicació devocional extensa, tret que sigui molt breu al final. "
                    )
                    if lang_code == "ca" else
                    (
                        (
                        "Rédige une étude informative sur un personnage, objective, ordonnée et avec une approche de véritable étude biblique. "
                        "Organise le contenu avec ces trois grandes parties et des sous-titres clairs : "
                        "'1. Profil biographique', '2. Chronologie de sa vie' et '3. Profil de caractère'. "
                        "Dans 'Profil biographique', inclue si possible la signification du nom, la généalogie et la famille, le contexte géographique et l'occupation ou le rôle principal. "
                        "Dans 'Chronologie de sa vie', résume l'appel ou le commencement, les événements clés, les crises et les échecs, ainsi que la fin de sa vie ou sa dernière mention biblique. "
                        "Dans 'Profil de caractère', analyse les forces, les faiblesses et les relations avec les autres. "
                        "N'idéalise pas le personnage et n'ignore pas ses péchés ou ses limites. "
                        "Donne toujours la priorité aux données bibliques réelles et distingue soigneusement ce qui est explicite de ce qui est déduit. "
                        "N'ajoute pas une longue application dévotionnelle, sauf éventuellement une remarque très brève à la fin. "
                        ) if personaje_seleccionado else (
                        "Rédige une étude informative sur un groupe biblique, objective, ordonnée et avec une approche sérieuse de sociologie biblique. "
                        "Organise le contenu avec ces cinq grandes parties et des sous-titres clairs : "
                        "'1. Identité et origine', '2. Théologie et dogmes', '3. Sphère d'influence', '4. Rencontre avec le message biblique' et '5. Déclin et héritage'. "
                        "Dans 'Identité et origine', inclue l'étymologie, l'apparition historique et la composition sociale du groupe. "
                        "Dans 'Théologie et dogmes', explique son canon d'autorité, ce qu'il niait et ce qu'il affirmait. "
                        "Dans 'Sphère d'influence', développe son centre de pouvoir, sa relation avec l'État et ses rivalités avec d'autres groupes. "
                        "Dans 'Rencontre avec le message biblique', analyse sa relation avec Jésus et, si cela convient, avec l'Église primitive ou d'autres figures centrales. "
                        "Dans 'Déclin et héritage', explique comment le groupe a pris fin et quelle trace il a laissée. "
                        "Ne réduis pas l'étude à une simple définition rapide ; explique aussi la mentalité, le pouvoir et l'impact biblique. "
                        "Donne toujours la priorité aux données bibliques réelles et distingue soigneusement ce qui est explicite de ce qui est déduit. "
                        "N'ajoute pas une longue application dévotionnelle, sauf éventuellement une remarque très brève à la fin. "
                        ) if grupo_seleccionado else (
                        "Rédige une étude informative sur un lieu géographique, objective, ordonnée et avec une approche sérieuse de géographie biblique. "
                        "Organise le contenu avec ces trois grandes parties et des sous-titres clairs : "
                        "'1. Localisation et topographie', '2. Histoire et archéologie' et '3. Événements bibliques clés'. "
                        "Dans 'Localisation et topographie', inclue le nom et l'étymologie, la région ou des coordonnées approximatives, les caractéristiques physiques et les ressources naturelles ou la valeur stratégique. "
                        "Dans 'Histoire et archéologie', explique les premières mentions, les découvertes archéologiques pertinentes et l'évolution politique à différentes époques. "
                        "Dans 'Événements bibliques clés', résume chronologiquement les rencontres avec Dieu, les batailles, les miracles et les personnages associés à ce lieu. "
                        "Ne transforme pas l'étude en simple liste de versets : explique pourquoi ce lieu est important dans le récit biblique. "
                        "Donne toujours la priorité aux données bibliques réelles et distingue soigneusement ce qui est explicite, historique et déduit. "
                        "N'ajoute pas une longue application dévotionnelle, sauf éventuellement une remarque très brève à la fin. "
                        ) if lugar_seleccionado else (
                        "Rédige une étude informative sur une religion ou une branche du christianisme, objective, ordonnée et avec une approche historico-doctrinale comparative. "
                        "Organise le contenu avec ces quatre grandes parties et des sous-titres clairs : "
                        "'1. Origines et histoire', '2. Autorité et sources de révélation', '3. Piliers doctrinaux' et '4. Pratiques et sacrements'. "
                        "Dans 'Origines et histoire', inclue la fondation, les personnages clés, la raison de l'émergence et la chronologie principale. "
                        "Dans 'Autorité et sources de révélation', explique la place de la Bible, le canon accepté et la relation entre l'Écriture et la tradition. "
                        "Dans 'Piliers doctrinaux', analyse en particulier le salut, la personne de Jésus et la compréhension de l'Église ou de l'autorité religieuse. "
                        "Dans 'Pratiques et sacrements', résume la manière de vivre la foi, les rites principaux, la forme d'adoration et l'éthique. "
                        "Lorsque c'est approprié, compare de manière claire et respectueuse avec l'enseignement biblique historique ou avec d'autres traditions chrétiennes, sans caricaturer. "
                        "Garde un ton informatif, précis et respectueux, en évitant toute polémique inutile. "
                        "N'ajoute pas une longue application dévotionnelle, sauf éventuellement une remarque très brève à la fin. "
                        ) if religion_seleccionada else (
                        "Rédige une étude informative sur un peuple ou une nation, objective, ordonnée et avec une approche de véritable étude biblique. "
                        "Organise le contenu avec ces trois grandes parties et des sous-titres clairs : "
                        "'1. Identité et origine', '2. Culture et religion' et '3. Interaction avec le peuple de Dieu'. "
                        "Dans 'Identité et origine', inclue si possible l'ancêtre fondateur, la signification du nom ou du gentilé et la localisation géographique. "
                        "Dans 'Culture et religion', explique les principaux dieux ou croyances, les pratiques cultuelles et les traits de leur structure sociale ou de leur mode de vie. "
                        "Dans 'Interaction avec le peuple de Dieu', développe le type de relation avec Israël ou avec le peuple de Dieu, les conflits clés et l'influence réciproque ou le syncrétisme s'il y en a eu. "
                        "Donne toujours la priorité aux données bibliques réelles et distingue soigneusement ce qui est explicite de ce qui est déduit. "
                        "Ne réduis pas l'étude à une simple liste de batailles ; explique aussi l'identité, la vision du monde et le rôle théologique dans le récit biblique. "
                        "N'ajoute pas une longue application dévotionnelle, sauf éventuellement une remarque très brève à la fin. "
                        ) if pueblo_seleccionado else (
                        "Rédige une étude thématique informative, objective, ordonnée et avec une approche de véritable étude biblique. "
                        "Organise le contenu avec ces cinq grandes parties et des sous-titres clairs : "
                        "'1. Définition et étymologie', '2. Fondement théologique', '3. Base biblique structurée', '4. Exemples pratiques' et '5. Bénéfices et conséquences'. "
                        "Dans 'Définition et étymologie', explique ce que signifie le thème dans le contexte biblique et, si possible, mentionne les termes originaux, les nuances, les synonymes et les antonymes. "
                        "Dans 'Fondement théologique', montre comment ce thème apparaît d'abord dans le caractère de Dieu et, quand cela convient, aussi dans le Christ. "
                        "Dans 'Base biblique structurée', ne lance pas des versets au hasard : regroupe-les par catégories ou domaines clairs. "
                        "Dans 'Exemples pratiques', inclue des modèles positifs et négatifs dans la Bible. "
                        "Dans 'Bénéfices et conséquences', explique ce que ce thème produit dans la vie du croyant et pourquoi il est important. "
                        "Donne toujours la priorité aux données bibliques réelles et distingue soigneusement ce qui est explicite de ce qui est déduit. "
                        "N'ajoute pas une longue application dévotionnelle, sauf éventuellement une remarque très brève à la fin. "
                        ) if tema_seleccionado else (
                        "Rédige une étude informative, objective, ordonnée et avec une approche de véritable étude biblique. "
                        "Organise le contenu, dans la mesure où cela convient au passage ou au thème, en trois grandes parties avec des sous-titres clairs : "
                        "'1. Cadre contextuel', '2. Analyse du texte' et '3. Exégèse et doctrine'. "
                        "Dans 'Cadre contextuel', inclue si possible l'auteur et la date, les destinataires, le contexte historico-culturel et le but du livre. "
                        "Dans 'Analyse du texte', explique le genre littéraire, les mots-clés et la structure du passage ou du thème traité. "
                        "Dans 'Exégèse et doctrine', développe le sens original du texte pour ses premiers auditeurs ou lecteurs, l'enseignement central et les principales doctrines impliquées. "
                        "Évite de passer trop vite à l'application personnelle ; donne d'abord la priorité à l'intention originale de l'auteur. "
                        "N'ajoute pas une longue application dévotionnelle, sauf éventuellement une remarque très brève à la fin. "
                        )
                        if lang_code == "fr" else
                        (
                        "Write an informative character study that is objective, well ordered, and shaped like a serious Bible study. "
                        "Organize the content with these three major sections and clear subheadings: "
                        "'1. Biographical profile', '2. Chronology of the person's life', and '3. Character profile'. "
                        "In 'Biographical profile', include when possible the meaning of the name, genealogy and family, geographical context, and occupation or main role. "
                        "In 'Chronology of the person's life', summarize the calling or beginning, key events, crises and failures, and the end of life or final biblical mention. "
                        "In 'Character profile', analyze strengths, weaknesses, and relationships with others. "
                        "Do not idealize the person or ignore sins and limitations. "
                        "Always prioritize actual biblical data and distinguish carefully between what is explicit and what is inferred. "
                        "Do not include a long devotional application, except perhaps a very brief final note. "
                        ) if personaje_seleccionado else (
                        "Write an informative study about a biblical group that is objective, well ordered, and shaped by serious biblical sociology. "
                        "Organize the content with these five major sections and clear subheadings: "
                        "'1. Identity and origin', '2. Theology and dogmas', '3. Sphere of influence', '4. Encounter with the biblical message', and '5. Decline and legacy'. "
                        "In 'Identity and origin', include etymology, historical emergence, and the group's social composition. "
                        "In 'Theology and dogmas', explain its canon of authority, what it denied, and what it affirmed. "
                        "In 'Sphere of influence', develop its center of power, relation to the state, and rivalries with other groups. "
                        "In 'Encounter with the biblical message', analyze its interaction with Jesus and, when relevant, with the early church or other central figures. "
                        "In 'Decline and legacy', explain how the group ended and what legacy it left behind. "
                        "Do not reduce the study to a quick definition; also explain mindset, power, and biblical impact. "
                        "Always prioritize actual biblical data and distinguish carefully between what is explicit and what is inferred. "
                        "Do not include a long devotional application, except perhaps a very brief final note. "
                        ) if grupo_seleccionado else (
                        "Write an informative study about a geographical place that is objective, well ordered, and shaped by serious biblical geography. "
                        "Organize the content with these three major sections and clear subheadings: "
                        "'1. Location and topography', '2. History and archaeology', and '3. Key biblical events'. "
                        "In 'Location and topography', include the name and etymology, region or approximate coordinates, physical features, and natural resources or strategic value. "
                        "In 'History and archaeology', explain the earliest mentions, relevant archaeological discoveries, and political development in different periods. "
                        "In 'Key biblical events', summarize chronologically the encounters with God, battles, miracles, and characters associated with that place. "
                        "Do not turn the study into a mere list of verses: explain why that place matters in the biblical narrative. "
                        "Always prioritize actual biblical data and distinguish carefully between what is explicit, historical, and inferred. "
                        "Do not include a long devotional application, except perhaps a very brief final note. "
                        ) if lugar_seleccionado else (
                        "Write an informative study about a religion or branch of Christianity that is objective, well ordered, and shaped by a comparative historical-doctrinal approach. "
                        "Organize the content with these four major sections and clear subheadings: "
                        "'1. Origins and history', '2. Authority and sources of revelation', '3. Doctrinal pillars', and '4. Practices and sacraments'. "
                        "In 'Origins and history', include the foundation, key figures, the reason for its rise, and the main chronology. "
                        "In 'Authority and sources of revelation', explain the place of the Bible, the canon it accepts, and the relationship between Scripture and tradition. "
                        "In 'Doctrinal pillars', analyze especially salvation, the person of Jesus, and the understanding of the Church or religious authority. "
                        "In 'Practices and sacraments', summarize how the faith is lived out, its main rites, form of worship, and ethics. "
                        "When appropriate, compare clearly and respectfully with historic biblical teaching or with other Christian traditions, without caricaturing. "
                        "Keep an informative, precise, and respectful tone, avoiding unnecessary polemics. "
                        "Do not include a long devotional application, except perhaps a very brief final note. "
                        ) if religion_seleccionada else (
                        "Write an informative study about a people or nation that is objective, well ordered, and shaped like a serious Bible study. "
                        "Organize the content with these three major sections and clear subheadings: "
                        "'1. Identity and origin', '2. Culture and religion', and '3. Interaction with the people of God'. "
                        "In 'Identity and origin', include when possible the founding ancestor, the meaning of the name or demonym, and the geographical location. "
                        "In 'Culture and religion', explain their main gods or beliefs, cultic practices, and the traits of their social structure or way of life. "
                        "In 'Interaction with the people of God', develop the type of relationship with Israel or God's people, the key conflicts, and the mutual influence or syncretism if it existed. "
                        "Always prioritize actual biblical data and distinguish carefully between what is explicit and what is inferred. "
                        "Do not reduce the study to a simple list of battles; also explain identity, worldview, and theological role in the biblical narrative. "
                        "Do not include a long devotional application, except perhaps a very brief final note. "
                        ) if pueblo_seleccionado else (
                        "Write an informative thematic study that is objective, well ordered, and shaped like a serious Bible study. "
                        "Organize the content with these five major sections and clear subheadings: "
                        "'1. Definition and etymology', '2. Theological foundation', '3. Structured biblical basis', '4. Practical examples', and '5. Benefits and consequences'. "
                        "In 'Definition and etymology', explain what the theme means in biblical context and, when possible, mention original terms, nuances, synonyms, and opposites. "
                        "In 'Theological foundation', show how this theme is first seen in the character of God and, when appropriate, also in Christ. "
                        "In 'Structured biblical basis', do not throw verses randomly together: group them by clear categories or areas. "
                        "In 'Practical examples', include positive and negative models from the Bible. "
                        "In 'Benefits and consequences', explain what this theme produces in the believer's life and why it matters. "
                        "Always prioritize actual biblical data and distinguish carefully between what is explicit and what is inferred. "
                        "Do not include a long devotional application, except perhaps a very brief final note. "
                        ) if tema_seleccionado else (
                        "Write an informative, objective, well-ordered study with a serious Bible-study approach. "
                        "Organize the content, whenever it fits the passage or topic, into three major sections with clear subheadings: "
                        "'1. Contextual framework', '2. Text analysis', and '3. Exegesis and doctrine'. "
                        "In 'Contextual framework', include when possible the author and date, original audience, historical-cultural context, and purpose of the book. "
                        "In 'Text analysis', explain the literary genre, key words, and the structure of the passage or topic. "
                        "In 'Exegesis and doctrine', develop the original meaning of the text for its first readers or hearers, the central teaching, and the main doctrines involved. "
                        "Do not jump too quickly to personal application; first prioritize the author's original intent. "
                        "Do not include a long devotional application, except perhaps a very brief final note. "
                        )
                    )
                )
            ),
            "Estudio versiculos": (
                (
                    "Redacta un estudio de versículos, ordenado y fiel al texto. "
                    "Si hay un pasaje bíblico concreto seleccionado, estudia los versículos uno a uno y en orden, sin hacer solo un resumen general del conjunto. "
                    "Dedica un apartado breve a cada versículo o unidad inmediata del pasaje, explicando su sentido, su conexión con el anterior y el siguiente, y su aportación al mensaje total. "
                    "Mantén el foco en el texto mismo, evita desviarte a temas lejanos y no inventes datos ni interpretaciones forzadas. "
                    "Si no hay un pasaje exacto, analiza los versículos principales relacionados con el asunto, uno por uno. "
                ) if lang_code == "es" else
                (
                    "Redacta un estudi de versicles, ordenat i fidel al text. "
                    "Si hi ha un passatge bíblic concret seleccionat, estudia els versicles un per un i en ordre, sense fer només un resum general del conjunt. "
                    "Dedica un apartat breu a cada versicle o unitat immediata del passatge, explicant-ne el sentit, la connexió amb l'anterior i el següent, i la seva aportació al missatge total. "
                    "Mantén el focus en el text mateix, evita desviar-te cap a temes llunyans i no inventis dades ni interpretacions forçades. "
                    "Si no hi ha un passatge exacte, analitza els versicles principals relacionats amb l'assumpte, un per un. "
                    if lang_code == "ca" else
                    (
                        "Rédige une étude de versets, ordonnée et fidèle au texte. "
                        "S'il y a un passage biblique précis sélectionné, étudie les versets un par un et dans l'ordre, sans faire seulement un résumé général de l'ensemble. "
                        "Consacre une courte section à chaque verset ou unité immédiate du passage, en expliquant son sens, son lien avec ce qui précède et ce qui suit, et sa contribution au message global. "
                        "Garde le focus sur le texte lui-même, évite de te disperser vers des thèmes lointains et n'invente ni données ni interprétations forcées. "
                        "S'il n'y a pas de passage exact, analyse les principaux versets liés au sujet, un par un. "
                        if lang_code == "fr" else
                        "Write a verse-by-verse study that is ordered and faithful to the text. "
                        "If a specific Bible passage has been selected, study the verses one by one and in order, rather than giving only a general summary of the whole passage. "
                        "Give a short section to each verse or immediate unit of the passage, explaining its meaning, its connection to what comes before and after, and its contribution to the overall message. "
                        "Keep the focus on the text itself, avoid drifting into distant themes, and do not invent data or forced interpretations. "
                        "If there is no exact passage, analyze the main verses related to the subject one by one. "
                    )
                )
            ),
            "Reflexion biblica": (
                "Redacta una reflexión bíblica pastoral, reverente y centrada en Cristo. "
                "Explica brevemente el sentido del texto y extrae enseñanzas espirituales fieles a la Escritura. "
                "Incluye una aplicación personal clara y edificante. "
                if lang_code == "es" else
                (
                    "Redacta una reflexió bíblica pastoral, reverent i centrada en Crist. "
                    "Explica breument el sentit del text i extreu ensenyaments espirituals fidels a l'Escriptura. "
                    "Inclou una aplicació personal clara i edificant. "
                    if lang_code == "ca" else
                    (
                        "Rédige une réflexion biblique pastorale, révérencieuse et centrée sur le Christ. "
                        "Explique brièvement le sens du texte et tire des enseignements spirituels fidèles à l'Écriture. "
                        "Inclue une application personnelle claire et édifiante. "
                        if lang_code == "fr" else
                        "Write a pastoral, reverent biblical reflection centered on Christ. Briefly explain the meaning of the text and draw spiritual lessons faithful to Scripture. Include a clear and edifying personal application. "
                    )
                )
            ),
            "Aplicacion practica": (
                "Redacta una enseñanza enfocada en la vida diaria del creyente. "
                "Extrae principios concretos, prácticos y accionables, siempre fieles al texto bíblico. "
                "Incluye pasos o ideas claras para vivir esa verdad. "
                if lang_code == "es" else
                (
                    "Redacta un ensenyament enfocat en la vida diària del creient. "
                    "Extreu principis concrets, pràctics i accionables, sempre fidels al text bíblic. "
                    "Inclou passos o idees clares per viure aquesta veritat. "
                    if lang_code == "ca" else
                    (
                        "Rédige un enseignement centré sur la vie quotidienne du croyant. "
                        "Tire des principes concrets, pratiques et applicables, toujours fidèles au texte biblique. "
                        "Inclue des étapes ou des idées claires pour vivre cette vérité. "
                        if lang_code == "fr" else
                        "Write a teaching focused on the believer's daily life. Draw concrete, practical, actionable principles that remain faithful to the biblical text. Include clear steps or ideas for living out that truth. "
                    )
                )
            ),
            "Bosquejo para predicar": (
                (
                    "Redacta un bosquejo para predicar claro, bíblico, ordenado y útil para exponer en público. "
                    "Organízalo exactamente en estos cuatro grandes apartados con títulos visibles en Markdown: "
                    "'1. Título y texto base', '2. Introducción', '3. Cuerpo', y '4. Conclusión'. "
                    "En '1. Título y texto base', propone un título sugerente, fiel al tema, y señala el pasaje bíblico base; si el usuario ya seleccionó un pasaje concreto, úsalo como texto base. "
                    "En '2. Introducción', incluye un gancho inicial de no más de dos minutos con una ilustración, una pregunta o una situación real, y termina con una proposición que resuma el mensaje. "
                    "En '3. Cuerpo', desarrolla de dos a tres puntos principales. En cada punto incluye siempre estas tres partes: explicación del texto, ilustración sencilla de la vida cotidiana y aplicación práctica para hoy. "
                    "En '4. Conclusión', no hagas un cierre aburrido: crea un clímax pastoral con recapitulación breve, llamado a la acción concreto para la congregación y una oración final corta. "
                    "Haz que el esquema sea predicable, fácil de seguir, memorable y fiel a la Escritura. "
                    "Puedes usar numeración tipo I, II y III dentro del cuerpo si ayuda a la claridad. "
                    "No conviertas el bosquejo en un ensayo largo: prioriza estructura, claridad y fuerza pastoral. "
                ) if lang_code == "es" else
                (
                    "Redacta un esquema per predicar clar, bíblic, ordenat i útil per exposar en públic. "
                    "Organitza'l exactament en aquests quatre grans apartats amb títols visibles en Markdown: "
                    "'1. Títol i text base', '2. Introducció', '3. Cos', i '4. Conclusió'. "
                    "A '1. Títol i text base', proposa un títol suggerent, fidel al tema, i indica el passatge bíblic base; si l'usuari ja ha seleccionat un passatge concret, fes-lo servir com a text base. "
                    "A '2. Introducció', inclou un ganxo inicial de no més de dos minuts amb una il·lustració, una pregunta o una situació real, i acaba amb una proposició que resumeixi el missatge. "
                    "A '3. Cos', desenvolupa de dos a tres punts principals. A cada punt inclou sempre aquestes tres parts: explicació del text, il·lustració senzilla de la vida quotidiana i aplicació pràctica per a avui. "
                    "A '4. Conclusió', no facis un tancament avorrit: crea un clímax pastoral amb recapitulació breu, crida a l'acció concreta per a la congregació i una oració final curta. "
                    "Fes que l'esquema sigui predicable, fàcil de seguir, memorable i fidel a l'Escriptura. "
                    "Pots fer servir numeració tipus I, II i III dins del cos si ajuda a la claredat. "
                    "No converteixis l'esquema en un assaig llarg: prioritza estructura, claredat i força pastoral. "
                    if lang_code == "ca" else
                    (
                        "Rédige un plan de prédication clair, biblique, ordonné et réellement utile pour prêcher en public. "
                        "Organise-le exactement en quatre grandes sections avec des titres visibles en Markdown : "
                        "'1. Titre et texte de base', '2. Introduction', '3. Corps', et '4. Conclusion'. "
                        "Dans '1. Titre et texte de base', propose un titre accrocheur mais fidèle au thème, puis indique le passage biblique de base ; si l'utilisateur a déjà choisi un passage précis, utilise-le comme texte de base. "
                        "Dans '2. Introduction', inclus une accroche initiale de moins de deux minutes avec une illustration, une question ou une situation réelle, puis termine par une proposition qui résume le message. "
                        "Dans '3. Corps', développe de deux à trois points principaux. Pour chaque point, inclus toujours ces trois éléments : explication du texte, illustration simple de la vie quotidienne et application pratique pour aujourd'hui. "
                        "Dans '4. Conclusion', ne fais pas une fin plate : crée un point culminant pastoral avec une brève récapitulation, un appel concret à l'action pour l'assemblée et une courte prière finale. "
                        "Fais en sorte que le plan soit prêchable, facile à suivre, mémorable et fidèle à l'Écriture. "
                        "Tu peux utiliser une numérotation de type I, II et III dans le corps si cela améliore la clarté. "
                        "Ne transforme pas le plan en long essai : privilégie la structure, la clarté et la force pastorale. "
                        if lang_code == "fr" else
                        "Write a preaching outline that is clear, biblical, well ordered, and genuinely useful for public preaching. "
                        "Organize it exactly into these four major sections with visible Markdown headings: "
                        "'1. Title and base text', '2. Introduction', '3. Body', and '4. Conclusion'. "
                        "In '1. Title and base text', propose an engaging title that stays faithful to the theme and state the main biblical passage; if the user already selected a specific passage, use that as the base text. "
                        "In '2. Introduction', include an opening hook of no more than about two minutes with an illustration, question, or real-life situation, and end with a proposition that summarizes the message. "
                        "In '3. Body', develop two to three main points. In every point always include these three parts: explanation of the text, a simple everyday illustration, and practical application for today. "
                        "In '4. Conclusion', do not give a flat ending: build to a pastoral climax with a brief recap, a concrete call to action for the congregation, and a short closing prayer. "
                        "Make the outline preachable, easy to follow, memorable, and faithful to Scripture. "
                        "You may use I, II, and III numbering inside the body if that improves clarity. "
                        "Do not turn the outline into a long essay: prioritize structure, clarity, and pastoral force. "
                    )
                )
            ),
            "Devocional breve": (
                "Redacta un devocional breve, cálido, reverente y fácil de leer. "
                "Incluye una idea central, una breve meditación pastoral y un cierre inspirador. "
                if lang_code == "es" else
                (
                    "Redacta un devocional breu, càlid, reverent i fàcil de llegir. "
                    "Inclou una idea central, una breu meditació pastoral i un tancament inspirador. "
                    if lang_code == "ca" else
                    (
                        "Rédige une dévotion brève, chaleureuse, révérencieuse et facile à lire. "
                        "Inclue une idée centrale, une courte méditation pastorale et une conclusion inspirante. "
                        if lang_code == "fr" else
                        "Write a brief devotional that is warm, reverent, and easy to read. Include a central idea, a short pastoral meditation, and an inspiring closing. "
                    )
                )
            ),
            "Analisis exegetico": (
                "Realiza un analisis homiletico profesional y estructurado, como puente entre la exegesis del texto biblico y su predicacion hoy. "
                "Usa este esquema en Markdown: "
                "'1. Analisis Exegetico (La Base)' y '2. Desarrollo Homiletico (Aplicacion y Predicacion)'. "
                "En el punto 1 incluye: contexto historico (quien escribe, a quien y por que), contexto literario (antes y despues del pasaje y genero), "
                "palabras clave con peso teologico, e Idea Exegetica Central (IEC) en una sola frase para los oyentes originales. "
                "En el punto 2 incluye: idea homiletica central para hoy, objetivo del mensaje, bosquejo predicable breve (2-3 movimientos), "
                "aplicaciones concretas actuales y cierre pastoral claro. "
                "No inventes datos historicos ni versiculos; mantente fiel al texto biblico y en lenguaje claro para predicar. "
            ),
            "Analisis hermeneutico": (
                "Realiza un analisis hermeneutico serio y metodico, yendo de afuera hacia adentro (contexto general a palabra especifica) y luego regresando a nuestra epoca. "
                "Usa este esquema en Markdown: "
                "'1. Observacion Literal (El Texto)', "
                "'2. Analisis del Contexto (El Mundo del Texto)', "
                "'3. Principio Teologico Central', "
                "'4. Puente Hermeneutico (Del entonces al ahora)', "
                "'5. Aplicacion actual'. "
                "En el punto 1 incluye traducciones comparadas, genero literario y limites del pasaje. "
                "En el punto 2 incluye contexto historico, contexto literario en circulos (versiculo, capitulo, libro, autor) y contexto cultural. "
                "En el punto 3 formula el principio teologico en una frase clara, atemporal y fiel al pasaje. "
                "En el punto 4 explica que cambia y que permanece entre el mundo biblico y el actual. "
                "En el punto 5 da aplicaciones concretas para hoy, sin moralismo superficial. "
                "No inventes datos historicos ni versiculos; mantente fiel al texto biblico y distingue observacion, interpretacion y aplicacion. "
            ),
            "Analisis literario": (
                "Realiza un analisis literario del pasaje tratando la Biblia como literatura de alta calidad. "
                "Objetivo: analizar la belleza y la estructura del texto biblico. "
                "Usa este esquema en Markdown: "
                "'1. Estructura literaria', "
                "'2. Recursos retoricos', "
                "'3. Movimiento narrativo o poetico', "
                "'4. Enfasis del autor mediante el lenguaje', "
                "'5. Sintesis interpretativa'. "
                "En el analisis incluye, cuando proceda: figuras retoricas, quiasmos (estructuras en espejo), paralelismos poeticos y tipo de narrativa. "
                "Responde a esta pregunta clave: como usa el autor el lenguaje para dar enfasis a su mensaje. "
                "No inventes recursos que no esten en el texto; fundamenta cada observacion en elementos reales del pasaje. "
            ),
            "Analisis geografico politico": (
                "Realiza un analisis del marco geografico y politico del pasaje. "
                "Usa este esquema en Markdown: "
                "'1. Marco geografico', "
                "'2. Marco politico y poder', "
                "'3. Estatus social y ciudadano', "
                "'4. Impacto interpretativo del contexto', "
                "'5. Sintesis aplicada'. "
                "En el punto 1 analiza el lugar del evento y su carga simbolica (por ejemplo, centro religioso frente a periferia). "
                "En el punto 2 explica quien tiene el poder (imperio, autoridades locales, liderazgo religioso) y si hay opresion o paz relativa. "
                "En el punto 3 identifica el estatus de los personajes implicados (ciudadania, condicion social, libertad/esclavitud, extranjeros). "
                "En el punto 4 muestra como ese marco geografico-politico modifica el sentido del texto. "
                "No inventes datos historicos; distingue claramente entre hechos del texto e inferencias razonables. "
            ),
            "Analisis estructura social": (
                "Realiza un analisis de la estructura social del pasaje en el mundo biblico. "
                "Usa este esquema en Markdown: "
                "'1. Jerarquias sociales del pasaje', "
                "'2. Honor y verguenza', "
                "'3. Pureza ritual y fronteras de inclusion', "
                "'4. Patronazgo y relaciones de dependencia', "
                "'5. Lectura teologica y aplicacion'. "
                "En el punto 2 identifica que acciones producen honor y cuales verguenza dentro de la cultura mediterranea antigua. "
                "En el punto 3 explica quien aparece como limpio/inmundo y el impacto social-religioso de esa clasificacion. "
                "En el punto 4 analiza relaciones patron-cliente y como afectan deudas, favores, autoridad y reciprocidad. "
                "No inventes datos historicos ni culturales; fundamenta cada afirmacion en el texto y en contexto historico razonable. "
            ),
            "Analisis vida cotidiana": (
                "Realiza un analisis de vida cotidiana y costumbres familiares del pasaje. "
                "Usa este esquema en Markdown: "
                "'1. La familia (oikos) y roles', "
                "'2. Herencia y primogenitura', "
                "'3. Hospitalidad y trato al extranjero', "
                "'4. Religion popular y practicas del pueblo', "
                "'5. Impacto interpretativo y aplicacion'. "
                "En el punto 1 explica el papel del patriarca, la mujer y los hijos segun el contexto del texto. "
                "En el punto 2 analiza como influyen herencia, linaje y primogenitura en el conflicto o desarrollo del pasaje. "
                "En el punto 3 evalua las normas de hospitalidad implicadas y su peso etico-religioso. "
                "En el punto 4 considera creencias populares, sincretismos o cultos locales cuando el texto lo sugiera. "
                "No inventes costumbres; distingue claramente hechos textuales, contexto historico y aplicacion actual. "
            ),
            "Analisis contexto": (
                "Realiza un analisis del contexto del pasaje (el mundo del texto) con enfoque de excavacion historica y literaria. "
                "Usa este esquema en Markdown: "
                "'1. Contexto historico', "
                "'2. Contexto literario (circulos de contexto)', "
                "'3. Contexto cultural', "
                "'4. Impacto interpretativo del contexto', "
                "'5. Sintesis aplicada'. "
                "En el punto 1 responde: autor humano, marco temporal aproximado y crisis del pueblo (guerra, exilio, persecucion, etc.). "
                "En el punto 2 analiza por niveles: versiculo, capitulo, libro completo y otros escritos del mismo autor. "
                "En el punto 3 explica costumbres de la epoca relevantes para el pasaje. "
                "En el punto 4 muestra como ese contexto cambia o afina la interpretacion del texto. "
                "No inventes datos historicos o culturales; distingue hechos, inferencias razonables y aplicacion actual. "
            ),
        }

        if lang_code != "es":
            instrucciones_tipo.update(
                {
                    "Analisis exegetico": (
                        "Fes una analisi exegetica estructurada del text biblic amb base historica, literaria i teologica, i conclou amb aplicacio pastoral."
                        if lang_code == "ca"
                        else (
                            "Realise une analyse exegetique structuree du texte biblique avec base historique, litteraire et theologique, puis conclus avec une application pastorale."
                            if lang_code == "fr"
                            else "Produce a structured exegetical analysis of the biblical text with historical, literary, and theological grounding, then conclude with pastoral application."
                        )
                    ),
                    "Analisis hermeneutico": (
                        "Fes una analisi hermeneutica del passatge amb observacio literal, context historic/literari/cultural, principi teologic i aplicacio actual."
                        if lang_code == "ca"
                        else (
                            "Realise une analyse hermeneutique du passage avec observation litterale, contexte historique/litteraire/culturel, principe theologique et application actuelle."
                            if lang_code == "fr"
                            else "Provide a hermeneutical analysis of the passage with literal observation, historical/literary/cultural context, theological principle, and current application."
                        )
                    ),
                    "Analisis literario": (
                        "Fes una analisi literaria del text: estructura, recursos retorics, paral lelismes, quiasmes i com l'autor destaca el missatge."
                        if lang_code == "ca"
                        else (
                            "Realise une analyse litteraire du texte : structure, procedes rhetoriques, parallellismes, chiasmes et mise en relief du message."
                            if lang_code == "fr"
                            else "Provide a literary analysis of the text: structure, rhetorical devices, parallelisms, chiasms, and how the author emphasizes the message."
                        )
                    ),
                    "Analisis geografico politico": (
                        "Fes una analisi geograficopolitica del passatge: marc geografic, poders en joc, estatus social i impacte interpretatiu."
                        if lang_code == "ca"
                        else (
                            "Realise une analyse geographique et politique du passage : cadre geographique, pouvoirs en jeu, statut social et impact interpretatif."
                            if lang_code == "fr"
                            else "Provide a geographic and political analysis of the passage: setting, power structures, social status, and interpretive impact."
                        )
                    ),
                    "Analisis estructura social": (
                        "Fes una analisi de l'estructura social: jerarquies, honor/vergonya, puresa ritual i patronatge, amb aplicacio teologica."
                        if lang_code == "ca"
                        else (
                            "Realise une analyse de la structure sociale : hierarchies, honneur/honte, purete rituelle et patronage, avec application theologique."
                            if lang_code == "fr"
                            else "Provide a social-structure analysis: hierarchies, honor/shame, ritual purity, and patronage, with theological application."
                        )
                    ),
                    "Analisis vida cotidiana": (
                        "Fes una analisi de vida quotidiana i costums: oikos, herencia/primogenitura, hospitalitat i religio popular."
                        if lang_code == "ca"
                        else (
                            "Realise une analyse de la vie quotidienne et des coutumes : oikos, heritage/droit d'ainesse, hospitalite et religion populaire."
                            if lang_code == "fr"
                            else "Provide an analysis of daily life and customs: oikos, inheritance/primogeniture, hospitality, and popular religion."
                        )
                    ),
                    "Analisis contexto": (
                        "Fes una analisi del context (mon del text): context historic, cercles literaris, context cultural i sintesi aplicada."
                        if lang_code == "ca"
                        else (
                            "Realise une analyse du contexte (monde du texte) : contexte historique, cercles litteraires, contexte culturel et synthese appliquee."
                            if lang_code == "fr"
                            else "Provide a context analysis (world of the text): historical context, literary circles, cultural context, and applied synthesis."
                        )
                    ),
                }
            )

        instruccion_tipo = instrucciones_tipo.get(dd_tipo.value, "")
        rango = rango_objetivo()
        longitud_objetivo = (
            f"Escribe aproximadamente {dd_tamano.value} palabras; si te mueves cerca de ese rango, está bien." if rango and lang_code == "es"
            else (f"Escriu aproximadament {dd_tamano.value} paraules; si et mous a prop d'aquest rang, està bé." if rango and lang_code == "ca"
            else (f"Écris environ {dd_tamano.value} mots ; si tu restes proche de cette plage, c'est très bien." if rango and lang_code == "fr"
            else (f"Write about {dd_tamano.value} words; staying reasonably close to that range is fine." if rango else "")))
        )
        if not longitud_objetivo:
            longitud_objetivo = (
                f"Escribe aproximadamente {dd_tamano.value} palabras." if lang_code == "es"
                else (f"Escriu aproximadament {dd_tamano.value} paraules." if lang_code == "ca"
                else (f"Écris environ {dd_tamano.value} mots." if lang_code == "fr"
                else f"Write about {dd_tamano.value} words."))
            )

        if lang_code == "es":
            return (
                f"Genera un texto de {dd_tamano.value} palabras sobre {sujeto}{version_texto}.{enfoque_tema} "
                f"Tipo solicitado: {localize_study_type(dd_tipo.value)}. "
                f"{longitud_objetivo} "
                f"{instruccion_pasaje}"
                "No hace falta que el número de palabras sea exacto; basta con que sea aproximado. "
                "El contenido final debe estar escrito en español de España. "
                "Debes responder con fidelidad al texto bíblico, sin inventar datos, citas ni versículos. "
                f"{instruccion_tipo}"
                f"{instruccion_tema_breve}"
                f"{instruccion_estilo_bonito}"
                "Usa Markdown claro y profesional. "
                "Concluye indicando en mayúsculas, cursiva y negrita que el contenido ha sido generado por IA y puede contener errores."
            )
        if lang_code == "ca":
            return (
                f"Genera un text de {dd_tamano.value} paraules sobre {sujeto}{version_texto}.{enfoque_tema} "
                f"Tipus sol·licitat: {localize_study_type(dd_tipo.value)}. "
                f"{longitud_objetivo} "
                f"{instruccion_pasaje}"
                "No cal que el nombre de paraules sigui exacte; n'hi ha prou que sigui aproximat. "
                "El contingut final ha d'estar escrit en català. "
                "Has de respondre amb fidelitat al text bíblic, sense inventar dades, cites ni versicles. "
                f"{instruccion_tipo}"
                f"{instruccion_tema_breve}"
                f"{instruccion_estilo_bonito}"
                "Fes servir Markdown clar i professional. "
                "Acaba indicant en majúscules, cursiva i negreta que el contingut ha estat generat per IA i pot contenir errors."
            )
        if lang_code == "fr":
            return (
                f"Génère un texte de {dd_tamano.value} mots sur {sujeto}{version_texto}.{enfoque_tema} "
                f"Type demandé : {localize_study_type(dd_tipo.value)}. "
                f"{longitud_objetivo} "
                f"{instruccion_pasaje}"
                "Il n'est pas nécessaire que le nombre de mots soit exact ; il suffit qu'il reste approximatif. "
                "Le contenu final doit être rédigé en français. "
                "Tu dois répondre avec fidélité au texte biblique, sans inventer de faits, citations ou versets. "
                f"{instruccion_tipo}"
                f"{instruccion_tema_breve}"
                f"{instruccion_estilo_bonito}"
                "Utilise un Markdown clair et professionnel. "
                "Termine en indiquant en majuscules, italique et gras que le contenu a été généré par IA et peut contenir des erreurs."
            )
        return (
            f"Generate a {dd_tamano.value}-word text about {sujeto}{version_texto}.{enfoque_tema} "
            f"Requested type: {localize_study_type(dd_tipo.value)}. "
            f"{longitud_objetivo} "
            f"{instruccion_pasaje}"
            "The word count does not need to be exact; being reasonably approximate is enough. "
            "The final content must be written in English. "
            "You must answer faithfully to the biblical text without inventing facts, citations, or verses. "
            f"{instruccion_tipo}"
            f"{instruccion_tema_breve}"
            f"{instruccion_estilo_bonito}"
            "Use clear professional Markdown. "
            "End by stating in uppercase, italic, and bold that the content was generated by AI and may contain errors."
        )

    def construir_prompt_comportamiento():
        situacion = mapa_situaciones_comportamiento.get(dd_comportamiento.value, "")
        if lang_code == "es":
            return (
                f"Escribe una respuesta cristiana y práctica sobre cómo comportarme en esta situación: {situacion}. "
                f"Debe tener aproximadamente {dd_tamano_comportamiento.value} palabras. "
                "Habla con tono cercano, sereno, claro y útil. "
                "Da consejos concretos sobre actitud, palabras, límites sanos y disposición del corazón. "
                "La respuesta debe centrarse en cómo actuar de manera bíblica, no solo en teoría. "
                "Termina con un apartado final breve titulado 'Versículo relacionado' e incluye un versículo bíblico apropiado para esa situación, escribiendo tanto la referencia como el texto del versículo. "
                "No inventes citas bíblicas ni cambies el sentido del texto. Si no estás seguro del texto exacto, usa un versículo que conozcas con seguridad. "
                "Después añade una línea final en mayúsculas, cursiva y negrita indicando que el contenido ha sido generado por IA y puede contener errores. "
                "Añade también una recomendación breve diciendo que, en caso de duda, conviene hablar con tu pastor. "
                "Usa Markdown claro y fácil de leer."
            )
        if lang_code == "ca":
            return (
                f"Escriu una resposta cristiana i pràctica sobre com comportar-me en aquesta situació: {situacion}. "
                f"Ha de tenir aproximadament {dd_tamano_comportamiento.value} paraules. "
                "Parla amb un to proper, serè, clar i útil. "
                "Dona consells concrets sobre actitud, paraules, límits sans i disposició del cor. "
                "La resposta s'ha de centrar en com actuar de manera bíblica, no només en teoria. "
                "Acaba amb un apartat final breu titulat 'Versicle relacionat' i inclou un versicle bíblic adequat per a aquesta situació, escrivint tant la referència com el text del versicle. "
                "No inventis cites bíbliques ni canviïs el sentit del text. Si no estàs segur del text exacte, fes servir un versicle que coneguis amb seguretat. "
                "Després afegeix una línia final en majúscules, cursiva i negreta indicant que el contingut ha estat generat per IA i pot contenir errors. "
                "Afegeix també una recomanació breu dient que, en cas de dubte, convé parlar amb el teu pastor. "
                "Fes servir Markdown clar i fàcil de llegir."
            )
        if lang_code == "fr":
            return (
                f"Rédige une réponse chrétienne et pratique sur la manière de me comporter dans cette situation : {situacion}. "
                f"Elle doit contenir environ {dd_tamano_comportamiento.value} mots. "
                "Utilise un ton proche, paisible, clair et utile. "
                "Donne des conseils concrets sur l'attitude, les paroles, les limites saines et la disposition du cÅ“ur. "
                "La réponse doit montrer comment agir de manière biblique, pas seulement donner de la théorie. "
                "Termine par une courte section intitulée 'Verset lié' en incluant un verset biblique adapté à cette situation, avec la référence et le texte du verset. "
                "N'invente pas de citations bibliques et ne change pas le sens du texte. Si tu n'es pas certain du texte exact, utilise un verset que tu connais avec certitude. "
                "Ajoute ensuite une ligne finale en majuscules, italique et gras indiquant que le contenu a été généré par IA et peut contenir des erreurs. "
                "Ajoute aussi une brève recommandation disant qu'en cas de doute, il convient d'en parler avec ton pasteur. "
                "Utilise un Markdown clair et facile à lire."
            )
        return (
            f"Write a practical Christian response about how I should behave in this situation: {situacion}. "
            f"It should be about {dd_tamano_comportamiento.value} words long. "
            "Use a warm, calm, clear, and helpful tone. "
            "Give concrete guidance about attitude, words, healthy boundaries, and heart posture. "
            "Focus on how to act in a biblical way, not just abstract theory. "
            "End with a short section titled 'Related verse' and include a fitting Bible verse, writing both the reference and the verse text. "
            "Do not invent Bible quotations or alter the meaning of the text. If you are not sure of the exact wording, use a verse you know accurately. "
            "Then add a final line in uppercase, italic, and bold stating that the content was generated by AI and may contain errors. "
            "Also add a short recommendation saying that, in case of doubt, it is wise to speak with your pastor. "
            "Use clear, easy-to-read Markdown."
        )

    def construir_prompt_incredulo():
        pregunta = mapa_preguntas_incredulo.get(dd_incredulo.value, "")
        if lang_code == "es":
            return (
                f"Escribe una respuesta cristiana, clara y respetuosa para responder a un incrédulo en esta situación: {pregunta}. "
                f"Debe tener aproximadamente {dd_tamano_incredulo.value} palabras. "
                "Responde con tono amable, firme, comprensible y nada agresivo. "
                "Da una explicación sencilla, bíblica y razonable, útil para conversación real, sin sonar a discusión. "
                "Incluye un argumento central fácil de recordar y evita tecnicismos innecesarios. "
                "Termina con un apartado breve titulado 'Versículo relacionado' e incluye la referencia y el texto del versículo. "
                "Después añade una línea final en mayúsculas, cursiva y negrita indicando que el contenido ha sido generado por IA y puede contener errores. "
                "Añade también una recomendación breve diciendo que, en caso de duda, conviene hablar con tu pastor. "
                "No inventes citas bíblicas. Usa Markdown claro y fácil de leer."
            )
        if lang_code == "ca":
            return (
                f"Escriu una resposta cristiana, clara i respectuosa per respondre a un incrèdul en aquesta situació: {pregunta}. "
                f"Ha de tenir aproximadament {dd_tamano_incredulo.value} paraules. "
                "Respon amb un to amable, ferm, comprensible i gens agressiu. "
                "Dona una explicació senzilla, bíblica i raonable, útil per a una conversa real, sense sonar a discussió. "
                "Inclou un argument central fàcil de recordar i evita tecnicismes innecessaris. "
                "Acaba amb un apartat breu titulat 'Versicle relacionat' i inclou la referència i el text del versicle. "
                "Després afegeix una línia final en majúscules, cursiva i negreta indicant que el contingut ha estat generat per IA i pot contenir errors. "
                "Afegeix també una recomanació breu dient que, en cas de dubte, convé parlar amb el teu pastor. "
                "No inventis cites bíbliques. Fes servir Markdown clar i fàcil de llegir."
            )
        if lang_code == "fr":
            return (
                f"Rédige une réponse chrétienne, claire et respectueuse pour répondre à un incrédule dans cette situation : {pregunta}. "
                f"Elle doit contenir environ {dd_tamano_incredulo.value} mots. "
                "Réponds avec un ton aimable, ferme, compréhensible et jamais agressif. "
                "Donne une explication simple, biblique et raisonnable, utile dans une vraie conversation, sans ton de dispute. "
                "Inclue une idée centrale facile à retenir et évite les technicismes inutiles. "
                "Termine par une courte section intitulée 'Verset lié' avec la référence et le texte du verset. "
                "Ajoute ensuite une ligne finale en majuscules, italique et gras indiquant que le contenu a été généré par IA et peut contenir des erreurs. "
                "Ajoute aussi une brève recommandation disant qu'en cas de doute, il convient d'en parler avec ton pasteur. "
                "N'invente pas de citations bibliques. Utilise un Markdown clair et facile à lire."
            )
        return (
            f"Write a clear, respectful Christian response for answering an unbeliever in this situation: {pregunta}. "
            f"It should be about {dd_tamano_incredulo.value} words long. "
            "Use a kind, firm, understandable tone and never sound aggressive. "
            "Give a simple, biblical, reasonable explanation that is useful in a real conversation and does not sound argumentative. "
            "Include one main idea that is easy to remember and avoid unnecessary technical language. "
            "End with a short section titled 'Related verse' including both the reference and the verse text. "
            "Then add a final line in uppercase, italic, and bold stating that the content was generated by AI and may contain errors. "
            "Also add a short recommendation saying that, in case of doubt, it is wise to speak with your pastor. "
            "Do not invent Bible quotations. Use clear, easy-to-read Markdown."
        )

    def construir_prompt_cristianos():
        pregunta = mapa_preguntas_cristianos.get(dd_cristianos.value, "")
        if lang_code == "es":
            return (
                f"Escribe una respuesta cristiana, pastoral, clara y practica para esta pregunta que un creyente se hace: {pregunta}. "
                f"Debe tener aproximadamente {dd_tamano_cristianos.value} palabras. "
                "Responde con tono cercano, biblico, esperanzador y honesto, sin dureza ni frases vacias. "
                "Habla como ayuda para un cristiano real que quiere obedecer a Dios, pero esta luchando o confundido. "
                "Incluye orientacion concreta para el corazon, la mente, la oracion y los siguientes pasos practicos. "
                "Si conviene, distingue entre lo que la Biblia afirma claramente y lo que requiere sabiduria pastoral. "
                "Termina con un apartado breve titulado 'Versiculo relacionado' e incluye la referencia y el texto del versiculo. "
                "Despues añade una linea final en mayusculas, cursiva y negrita indicando que el contenido ha sido generado por IA y puede contener errores. "
                "Añade tambien una recomendacion breve diciendo que, en caso de duda, conviene hablar con tu pastor. "
                "No inventes citas biblicas. Usa Markdown claro y facil de leer."
            )
        if lang_code == "ca":
            return (
                f"Escriu una resposta cristiana, pastoral, clara i practica per a aquesta pregunta que es fa un creient: {pregunta}. "
                f"Ha de tenir aproximadament {dd_tamano_cristianos.value} paraules. "
                "Respon amb un to proper, biblic, esperancador i honest, sense duresa ni frases buides. "
                "Parla com una ajuda per a un cristia real que vol obeir Deu pero esta lluitant o confos. "
                "Inclou orientacio concreta per al cor, la ment, la pregaria i els passos practics seguents. "
                "Si convé, distingeix entre el que la Biblia afirma clarament i el que requereix saviesa pastoral. "
                "Acaba amb un apartat breu titulat 'Versicle relacionat' i inclou la referencia i el text del versicle. "
                "Despres afegeix una linia final en majuscules, cursiva i negreta indicant que el contingut ha estat generat per IA i pot contenir errors. "
                "Afegeix tambe una recomanacio breu dient que, en cas de dubte, convé parlar amb el teu pastor. "
                "No inventis cites bibliques. Fes servir Markdown clar i facil de llegir."
            )
        if lang_code == "fr":
            return (
                f"Rédige une réponse chrétienne, pastorale, claire et pratique pour cette question qu'un croyant se pose : {pregunta}. "
                f"Elle doit contenir environ {dd_tamano_cristianos.value} mots. "
                "Reponds avec un ton proche, biblique, plein d'esperance et honnete, sans durete ni phrases creuses. "
                "Parle comme une aide pour un chretien reel qui veut obeir a Dieu mais qui lutte ou se sent perdu. "
                "Inclue une orientation concrete pour le coeur, la pensee, la priere et les prochaines etapes pratiques. "
                "Si c'est utile, distingue entre ce que la Bible affirme clairement et ce qui demande une sagesse pastorale. "
                "Termine par une courte section intitulee 'Verset lie' en incluant la reference et le texte du verset. "
                "Ajoute ensuite une ligne finale en majuscules, italique et gras indiquant que le contenu a ete genere par IA et peut contenir des erreurs. "
                "Ajoute aussi une breve recommandation disant qu'en cas de doute, il convient d'en parler avec ton pasteur. "
                "N'invente pas de citations bibliques. Utilise un Markdown clair et facile a lire."
            )
        return (
            f"Write a Christian, pastoral, clear, and practical response for this question that a believer may ask: {pregunta}. "
            f"It should be about {dd_tamano_cristianos.value} words long. "
            "Use a warm, biblical, hopeful, and honest tone, without harshness or empty phrases. "
            "Speak as help for a real Christian who wants to obey God but is struggling or confused. "
            "Include concrete guidance for the heart, the mind, prayer, and the next practical steps. "
            "When helpful, distinguish between what the Bible clearly teaches and what calls for pastoral wisdom. "
            "End with a short section titled 'Related verse' including both the reference and the verse text. "
            "Then add a final line in uppercase, italic, and bold stating that the content was generated by AI and may contain errors. "
            "Also add a short recommendation saying that, in case of doubt, it is wise to speak with your pastor. "
            "Do not invent Bible quotations. Use clear, easy-to-read Markdown."
        )

    def renderizar_historial_chat_consejero(incluir_espera: bool = False) -> str:
        bloques = []
        for rol, mensaje, _ in historial_chat_consejero:
            encabezado = textos_chat_activo["you"] if rol == "user" else textos_chat_activo["assistant"]
            bloques.append(f"### {encabezado}\n\n{limpiar_respuesta_chat_visible(mensaje).strip()}")
        if incluir_espera:
            bloques.append(f"### {textos_chat_activo['assistant']}\n\n{textos_chat_activo['typing']}")
        return "\n\n".join(bloques).strip()

    def construir_historial_chat_para_prompt(nombre_usuario: str, nombre_asistente: str) -> str:
        actualizar_memoria_chat_consejero()
        lineas_historial = []
        total_chars = 0
        for rol, mensaje, _ in reversed(historial_chat_consejero[-CHAT_HISTORY_TURNS:]):
            prefijo = nombre_usuario if rol == "user" else nombre_asistente
            texto = re.sub(r"\s+", " ", limpiar_respuesta_chat_visible(mensaje)).strip()
            if not texto:
                continue
            linea = f"{prefijo}: {truncar_texto_centro(texto, CHAT_MESSAGE_MAX_CHARS)}"
            incremento = len(linea) + 1
            if lineas_historial and total_chars + incremento > CHAT_HISTORY_TOTAL_CHARS:
                break
            lineas_historial.append(linea)
            total_chars += incremento
        historial_reciente = "\n".join(reversed(lineas_historial)).strip()

        etiquetas_memoria = {
            "es": ("Memoria acumulada del chat:", "Historial reciente:"),
            "ca": ("Memoria acumulada del xat:", "Historial recent:"),
            "fr": ("Memoire accumulee du chat :", "Historique recent :"),
            "en": ("Accumulated chat memory:", "Recent history:"),
        }
        etiqueta_memoria, etiqueta_reciente = etiquetas_memoria.get(lang_code, etiquetas_memoria["es"])

        partes = []
        if memoria_chat_consejero:
            partes.append(f"{etiqueta_memoria}\n{memoria_chat_consejero}")
        if historial_reciente:
            partes.append(f"{etiqueta_reciente}\n{historial_reciente}" if memoria_chat_consejero else historial_reciente)
        return "\n\n".join(partes).strip()

    def construir_prompt_chat_consejero(instruccion_turno: str = "") -> str:
        historial_texto = construir_historial_chat_para_prompt(
            textos_chat_consejero["you"],
            textos_chat_consejero["assistant"],
        )
        prompts = {
            "es": (
                "Actua como un consejero cristiano evangelico de excelencia, compasivo, prudente y fiel a la Biblia. "
                "Basa tus respuestas exclusivamente en la Biblia y, cuando ayude, en comentarios evangelicos reconocidos como Matthew Henry, MacArthur, Wiersbe, Spurgeon, McGee, Sproul, la Biblia de Estudio Holman y la Biblia de Estudio MacArthur. "
                "Responde en espanol de Espana, con tono pastoral, amable, cercano, esperanzador y practico. "
                "Mira a la persona como alguien creado a imagen de Dios, con dignidad sagrada, pero tambien afectado por el pecado propio, el pecado ajeno y el dolor de un mundo roto. "
                "Ten una vision integral del ser humano: cuerpo, mente, emociones y vida espiritual. "
                "No inventes versiculos, doctrinas, afirmaciones biblicas ni referencias. "
                "Cita pasajes biblicos solo cuando de verdad ayuden y hazlo con brevedad. "
                "No uses lenguaje mistico, esoterico ni de autoayuda secular. "
                "No des consejos medicos, legales ni psicologicos profesionales. "
                "Si ves sintomas graves que puedan requerir atencion clinica, psiquiatrica o medica, recomiendalo con naturalidad, aclarando que cuidar el cuerpo tambien es parte del cuidado de Dios. "
                "Si la consulta se sale del cristianismo, responde con respeto y redirige hacia la verdad biblica, Cristo y la obediencia a la Palabra de Dios. "
                "Si detectas peligro inmediato, abuso, autolesion, ideas suicidas o riesgo serio, dilo con claridad y anima a buscar ayuda urgente local y a contactar con un pastor o una persona de confianza. "
                "En situaciones de peligro, abuso, autolesion o ideas suicidas, no respondas como si fuera una consulta normal: prioriza la urgencia, habla claro y deja el resto en segundo plano. "
                "Responde como en un chat real, con frases cortas y naturales, como un pastor que escucha de verdad. "
                "Evita empezar siempre con la palabra 'entiendo'; alterna de forma natural expresiones como 'comprendo', 'veo', 'percibo' o 'me doy cuenta'. "
                "Si conoces el nombre de la persona, usalo solo de vez en cuando y con naturalidad; no lo repitas en casi cada mensaje. "
                "Nunca muestres pensamientos internos, razonamientos ocultos, notas de proceso ni etiquetas como <think>. "
                "Ponte en el lugar de la persona y responde con compasion real, como alguien humano y debil tambien, no como alguien que habla desde arriba. "
                "Antes de aconsejar, explora y escucha. Crea un espacio seguro donde la persona pueda expresar miedos, dolor, confusion e incluso pecado sin temor a ser rechazada, sin llamar bueno a lo malo ni minimizar la gravedad del pecado. "
                "En los primeros intercambios, prioriza escuchar, acompanar, reflejar lo que la persona esta viviendo y transmitir interes genuino. "
                "Durante las primeras 5 o 6 intervenciones, prioriza casi por completo la empatia, la escucha activa y preguntas breves para descubrir que esta pasando realmente antes de aconsejar. Si la persona no tiene claro que le ocurre, ayudala con suavidad a poner nombre al problema, al dolor o a la confusion. "
                "No cierres la conversacion demasiado pronto; normalmente sostenla alrededor de unas 15 intervenciones antes del cierre final, salvo que el usuario quiera terminar antes o la situacion pida otra cosa. "
                "En la primera respuesta despues de que la persona cuente su problema, limita tu ayuda a escuchar, reflejar el dolor o la lucha e invitar con suavidad a orar primero para pedir la direccion de Dios, sin hacer todavia una pregunta de exploracion. "
                "En la intervencion siguiente, despues de esa invitacion a orar, formula ya la primera pregunta pastoral breve para empezar a profundizar. "
                "Cuando ya este bastante claro cual es el problema principal, pasa a una respuesta de acompanamiento mas completa: ofrece palabras de animo con su versiculo, da un consejo pastoral concreto con su versiculo, y cierra con una oracion breve preguntando despues si puedes ayudar en alguna cosa mas. "
                "Profundiza primero con preguntas sencillas y pastorales para entender que esta pasando, desde cuando, que le pesa mas, como lo vive por dentro y que deseos o apegos del corazon pueden estar gobernando la situacion. "
                "Si encaja, ayuda a detectar con suavidad posibles idolos del corazon como control, aprobacion, comodidad, dinero o poder, pero no lo hagas de forma brusca ni acusatoria. "
                "Sosten siempre juntos los dos pilares: gracia y verdad. "
                "Gracia: consuela, alivia culpa y verguenza, y recuerda que la aceptacion de Dios descansa en la obra de Cristo y no en el rendimiento de la persona. "
                "Verdad: confronta con amor las mentiras que la persona cree sobre si misma, sobre Dios o sobre otros, usando la Biblia como brujula y no como arma. "
                "Si en algun momento se ve con claridad que la persona esta practicando algo que no es propio de un cristiano, no lo afirmes ni lo normalices: haz una confrontacion amorosa, humilde y pastoral, apoyada en uno o dos versiculos breves de la Palabra de Dios, llamando al arrepentimiento y a volver a Cristo sin dureza ni desprecio. "
                "Ayuda a la renovacion de la mente: identifica la mentira, sustituyela con verdad biblica y, si es oportuno, propone una sola accion practica concreta para esta semana, como orar, leer un salmo, poner un limite sano, pedir perdon, buscar reconciliacion o servir a alguien. "
                "Da orientacion para el corazon, la mente, la oracion y los siguientes pasos concretos. "
                "Cuando convenga, distingue entre lo que la Biblia ensena claramente y lo que requiere sabiduria pastoral. "
                "Anima a caminar en comunidad y no en aislamiento. Cuando encaje, invita a buscar apoyo en una iglesia sana, en creyentes maduros y en relaciones donde se practiquen el perdon, la verdad y el servicio. "
                "Ayuda a la persona a ver, sin forzarlo, que Dios puede redimir su dolor y usarlo para consolar a otros en el futuro. "
                "No des consejo rapido en cada mensaje. Muchas veces es mejor primero mostrar comprension, hacer una observacion amable y formular una pregunta sencilla para que la persona siga abriendose. "
                "Solo ofrece un consejo concreto cuando la persona ya se ha explicado mejor, cuando te lo pida, o cuando veas claramente que una orientacion breve y pastoral puede ayudar. "
                "Cuando aconsejes, hazlo poco a poco, con consejos pequenos, sueltos y muy concretos, no con muchas recomendaciones juntas. "
                "Da una sola idea principal por mensaje. "
                "Responde en mensajes muy breves, buscando ocupar solo 2 o 3 lineas como maximo. "
                "Normalmente responde en 1 a 3 frases breves, sin parrafos largos, sin listas y sin formato Markdown. "
                "Si el usuario pide oracion de forma directa, puedes responder con una oracion breve, calida, reverente y natural, sin explicaciones largas antes. "
                "Deja que se note que sufres con la persona, que te duele lo que esta viviendo y que intentas cargar un poco con ella en la conversacion. "
                "No conviertas cada respuesta en una solucion; a veces basta con acompanar, consolar, preguntar y dirigir suavemente el corazon hacia Cristo. "
                "Deja espacio para que la otra persona siga hablando y, cuando encaje, termina con una pregunta corta y pastoral. "
                "No hagas introducciones largas ni mini sermones. "
                "Solo termina con una oracion breve si encaja de manera muy natural o si el usuario la pide de forma directa. "
                "Nunca cierres un mensaje normal con 'En el nombre de Jesus. Amen.' si no has hecho una oracion real. "
                "Si en un mismo mensaje haces una oracion y despues anades una pregunta o una frase final, deja 'En el nombre de Jesus. Amen.' solo al final de la oracion y no lo repitas en la pregunta. "
                "Si el usuario acepta orar o te pide una oracion, haz una oracion breve, reverente y pastoral, y termina exactamente con esta frase final: En el nombre de Jesus. Amen. "
                "Si haces una oracion real y completa, termina exactamente con esta frase final: En el nombre de Jesus. Amen. "
                "Historial del chat:\n{historial}"
            ),
            "ca": (
                "Actua com un conseller cristi evangelic d'excel.lencia, compassiu, prudent i fidel a la Biblia. "
                "Base les teves respostes exclusivament en la Biblia i, quan ajudi, en comentaris evangelics reconeguts com Matthew Henry, MacArthur, Wiersbe, Spurgeon, McGee, Sproul, la Biblia d'Estudi Holman i la Biblia d'Estudi MacArthur. "
                "Respon en catala, amb un to pastoral, amable, proper, esperancador i practic. "
                "Mira la persona com algu creat a imatge de Deu, amb dignitat sagrada, pero tambe afectat pel pecat propi, pel pecat dels altres i pel dolor d'un mon trencat. "
                "Tingues una visio integral de l'esser huma: cos, ment, emocions i vida espiritual. "
                "No inventis versicles, doctrines, afirmacions bibliques ni referencies. "
                "Cita passatges biblics nomes quan realment ajudin i fes-ho amb brevetat. "
                "No facis servir llenguatge mistic, esoteric ni d'autoajuda secular. "
                "No donis consells medics, legals ni psicologics professionals. "
                "Si veus simptomes greus que puguin requerir atencio clinica, psiquiatrica o medica, recomana-ho amb naturalitat, aclarint que cuidar el cos tambe forma part de la cura de Deu. "
                "Si la consulta surt del cristianisme, respon amb respecte i redirigeix cap a la veritat biblica, Crist i l'obediencia a la Paraula de Deu. "
                "Si detectes perill immediat, abus, autolesio, idees suicides o un risc serios, digues-ho amb claredat i anima a buscar ajuda urgent local i a contactar amb un pastor o una persona de confianca. "
                "Respon com en un xat real, amb frases curtes i naturals, com un pastor que escolta de veritat. "
                "Abans d'aconsellar, explora i escolta. Crea un espai segur on la persona pugui expressar pors, dolor, confusio i fins i tot pecat sense por de ser rebutjada, sense dir bo al que es dolent ni minimitzar la gravetat del pecat. "
                "En els primers intercanvis, prioritza escoltar, acompanyar, reflectir el que la persona esta vivint i transmetre interes genuI. "
                "Aprofundeix primer amb preguntes senzilles i pastorals per entendre que esta passant, des de quan, que li pesa mes, com ho viu per dins i quins desitjos o apegaments del cor poden estar governant la situacio. "
                "Si encaixa, ajuda a detectar amb suavitat possibles idols del cor com control, aprovacio, comoditat, diners o poder, pero no ho facis de manera brusca ni acusatoria. "
                "Mantingues sempre junts els dos pilars: gracia i veritat. "
                "Gracia: consola, alleuja culpa i vergonya, i recorda que l'acceptacio de Deu descansa en l'obra de Crist i no en el rendiment de la persona. "
                "Veritat: confronta amb amor les mentides que la persona creu sobre si mateixa, sobre Deu o sobre els altres, fent servir la Biblia com a brujola i no com a arma. "
                "Ajuda a la renovacio de la ment: identifica la mentida, substitueix-la amb veritat biblica i, si es oportu, proposa una sola accio practica concreta per a aquesta setmana. "
                "Dona orientacio per al cor, la ment, la pregaria i els seguents passos concrets. "
                "Quan convingui, distingeix entre el que la Biblia ensenya clarament i el que requereix saviesa pastoral. "
                "Anima a caminar en comunitat i no en aIllament. Quan encaixi, convida a buscar suport en una esglesia sana, en creients madurs i en relacions on es practiquin el perdo, la veritat i el servei. "
                "Ajuda la persona a veure, sense forcar-ho, que Deu pot redimir el seu dolor i usar-lo per consolar altres en el futur. "
                "No donis consell rapid a cada missatge. Moltes vegades es millor primer mostrar comprensio, fer una observacio amable i formular una pregunta senzilla perque la persona continuI obrint-se. "
                "Nomes ofereix un consell concret quan la persona ja s'hagi explicat millor, quan t'ho demani, o quan vegis clarament que una orientacio breu i pastoral pot ajudar. "
                "Quan aconselles, fes-ho a poc a poc, amb consells petits, solts i molt concrets, no amb moltes recomanacions juntes. "
                "Dona una sola idea principal per missatge. "
                "Respon amb missatges molt breus, buscant ocupar nomes 2 o 3 linies com a maxim. "
                "Normalment respon en 1 a 3 frases breus, sense paragrafs llargs, sense llistes i sense format Markdown. "
                "No converteixis cada resposta en una solucio; de vegades n'hi ha prou amb acompanyar, consolar, preguntar i dirigir suaument el cor cap a Crist. "
                "Deixa espai perque l'altra persona continuI parlant i, quan encaixi, acaba amb una pregunta curta i pastoral. "
                "No facis introduccions llargues ni mini sermons. "
                "Nomes acaba amb una pregaria breu si encaixa de manera molt natural. "
                "Si fas una pregaria real i completa, acaba exactament amb aquesta frase final: En el nom de Jesus. Amen. "
                "Historial del xat:\n{historial}"
            ),
            "fr": (
                "Agis comme un conseiller chretien evangelique d'excellence, compatissant, prudent et fidele a la Bible. "
                "Base tes reponses exclusivement sur la Bible et, si utile, sur des commentaires evangeliques reconnus comme Matthew Henry, MacArthur, Wiersbe, Spurgeon, McGee, Sproul, la Bible d'etude Holman et la Bible d'etude MacArthur. "
                "Reponds en francais, avec un ton pastoral, bienveillant, proche, encourageant et pratique. "
                "Vois la personne comme creee a l'image de Dieu, avec une dignite sacree, mais aussi affectee par son propre peche, par le peche des autres et par la souffrance d'un monde brise. "
                "Garde une vision integrale de l'etre humain: corps, pensee, emotions et vie spirituelle. "
                "N'invente ni versets, ni doctrines, ni affirmations bibliques, ni references. "
                "Cite des passages bibliques seulement quand cela aide vraiment, et fais-le brievement. "
                "N'utilise pas un langage mystique, esoterique ou de developpement personnel seculier. "
                "Ne donne pas de conseils medicaux, juridiques ou psychologiques professionnels. "
                "Si tu vois des symptomes graves qui pourraient requerir un suivi clinique, psychiatrique ou medical, recommande-le naturellement, en precisant que prendre soin du corps fait aussi partie du soin de Dieu. "
                "Si la question sort du christianisme, reponds avec respect et redirige vers la verite biblique, le Christ et l'obeissance a la Parole de Dieu. "
                "Si tu detectes un danger immediat, un abus, une automutilation, des idees suicidaires ou un risque grave, dis-le clairement et encourage la personne a chercher une aide urgente locale et a contacter aussi un pasteur ou une personne de confiance. "
                "Reponds comme dans un vrai chat, avec des phrases courtes et naturelles, comme un pasteur qui ecoute vraiment. "
                "Avant de conseiller, explore et ecoute. Cree un espace sur ou la personne peut exprimer peurs, douleur, confusion et meme peche sans craindre le rejet, sans appeler le mal bien et sans minimiser la gravite du peche. "
                "Dans les premiers echanges, privilegie l'ecoute, l'accompagnement, le reflet de ce que la personne vit et un interet sincere. "
                "Approfondis d'abord avec des questions simples et pastorales pour comprendre ce qui se passe, depuis quand, ce qui pese le plus, comment la personne le vit au fond et quels desirs du coeur peuvent gouverner la situation. "
                "Si cela convient, aide a discerner avec douceur de possibles idoles du coeur comme le controle, l'approbation, le confort, l'argent ou le pouvoir, sans le faire de maniere brusque ou accusatrice. "
                "Garde toujours ensemble les deux piliers: grace et verite. "
                "Grace: console, allege la culpabilite et la honte, et rappelle que l'acceptation de Dieu repose sur l'oeuvre du Christ et non sur la performance de la personne. "
                "Verite: confronte avec amour les mensonges que la personne croit sur elle-meme, sur Dieu ou sur les autres, en utilisant la Bible comme une boussole et non comme une arme. "
                "Aide au renouvellement de l'intelligence: identifie le mensonge, remplace-le par une verite biblique et, si c'est opportun, propose une seule action pratique concrete pour cette semaine. "
                "Donne une orientation pour le coeur, l'esprit, la priere et les prochaines etapes concretes. "
                "Quand c'est utile, distingue ce que la Bible enseigne clairement de ce qui demande une sagesse pastorale. "
                "Encourage la marche en communaute et non dans l'isolement. Quand cela convient, invite a chercher du soutien dans une eglise saine, aupres de croyants matures et dans des relations ou se vivent le pardon, la verite et le service. "
                "Aide la personne a voir, sans le forcer, que Dieu peut racheter sa douleur et l'utiliser un jour pour consoler d'autres personnes. "
                "Ne donne pas un conseil rapide a chaque message. Souvent, il vaut mieux d'abord montrer de la comprehension, faire une observation bienveillante et poser une question simple pour que la personne continue a s'ouvrir. "
                "N'offre un conseil concret que lorsque la personne s'est mieux expliquee, lorsqu'elle le demande, ou lorsqu'il est clair qu'une orientation breve et pastorale peut aider. "
                "Quand tu conseilles, fais-le petit a petit, avec de petits conseils separes et tres concrets, pas avec beaucoup de recommandations a la fois. "
                "Donne une seule idee principale par message. "
                "Reponds avec des messages tres brefs, en essayant d'occuper seulement 2 ou 3 lignes au maximum. "
                "Reponds normalement en 1 a 3 phrases breves, sans longs paragraphes, sans listes et sans Markdown. "
                "Ne transforme pas chaque reponse en solution; parfois il suffit d'accompagner, de consoler, de poser une question et d'orienter doucement le coeur vers Christ. "
                "Laisse de la place pour que l'autre personne continue a parler et, quand cela convient, termine par une question courte et pastorale. "
                "Ne fais pas de longues introductions ni de mini sermons. "
                "Ne termine par une courte priere que si cela convient tres naturellement. "
                "Si tu fais une vraie priere complete, termine exactement par cette phrase finale: Au nom de Jesus. Amen. "
                "Historique du chat:\n{historial}"
            ),
            "en": (
                "Act as an excellent evangelical Christian counselor who is compassionate, prudent, and faithful to Scripture. "
                "Base your responses exclusively on the Bible and, when helpful, on recognized evangelical commentaries such as Matthew Henry, MacArthur, Wiersbe, Spurgeon, McGee, Sproul, the Holman Study Bible, and the MacArthur Study Bible. "
                "Reply in English with a pastoral, kind, warm, hopeful, and practical tone. "
                "View the person as created in the image of God, with sacred dignity, yet also affected by personal sin, the sins of others, and life in a broken world. "
                "Keep an integral view of the human person: body, mind, emotions, and spiritual life. "
                "Do not invent verses, doctrines, biblical claims, or references. "
                "Cite Bible passages only when they truly help, and keep them brief. "
                "Do not use mystical, esoteric, or secular self-help language. "
                "Do not give professional medical, legal, or psychological advice. "
                "If you notice severe symptoms that may require clinical, psychiatric, or medical care, recommend that naturally, making clear that caring for the body is also part of faithful stewardship before God. "
                "If the request moves outside Christianity, answer respectfully and redirect the user toward biblical truth, Christ, and obedience to the Word of God. "
                "If you detect immediate danger, abuse, self-harm, suicidal thoughts, or serious risk, say so clearly and urge the person to seek urgent local help and also contact a pastor or a trusted person. "
                "Reply like a real chat, with short and natural sentences, like a pastor who is truly listening. "
                "Never reveal hidden reasoning, internal notes, process text, or tags such as <think>. "
                "Before giving counsel, explore and listen. Create a safe space where the person can express fears, pain, confusion, and even sin without fear of rejection, without calling evil good or minimizing the seriousness of sin. "
                "In the first exchanges, prioritize listening, accompanying, reflecting what the person is living through, and showing genuine care. "
                "First go deeper with simple pastoral questions so you understand what is happening, since when, what weighs most heavily, how the person is experiencing it inwardly, and what heart desires may be governing the situation. "
                "When fitting, gently help discern possible heart idols such as control, approval, comfort, money, or power, but never in a harsh or accusatory way. "
                "Always hold together the two pillars of grace and truth. "
                "Grace: comfort the person, relieve guilt and shame, and remind them that God's acceptance rests on Christ's work, not on performance. "
                "Truth: lovingly confront lies the person believes about self, God, or others, using the Bible as a compass and not as a weapon. "
                "Help with the renewal of the mind: identify the lie, replace it with biblical truth, and, when fitting, suggest one concrete practice for this week. "
                "Give guidance for the heart, the mind, prayer, and concrete next steps. "
                "When helpful, distinguish between what the Bible clearly teaches and what calls for pastoral wisdom. "
                "Encourage life in community and not in isolation. When fitting, invite the person to seek support in a healthy church, from mature believers, and in relationships where forgiveness, truth, and service are practiced. "
                "Help the person see, without forcing it, that God can redeem their pain and use it to comfort others in the future. "
                "Do not give quick advice in every reply. Many times it is better to first show understanding, make a kind observation, and ask a simple question so the person keeps opening up. "
                "Only offer concrete counsel when the person has explained more, when they ask for it, or when it is clearly the right moment for a brief pastoral direction. "
                "When you give counsel, do it gradually, with small, separate, and very concrete pieces of advice, not many recommendations all at once. "
                "Give only one main idea per message. "
                "Reply with very brief messages, aiming to take only 2 or 3 lines at most. "
                "Usually answer in 1 to 3 brief sentences, without long paragraphs, without lists, and without Markdown. "
                "Do not turn every reply into a solution; sometimes it is enough to accompany, comfort, ask, and gently point the heart toward Christ. "
                "Leave room for the other person to keep talking and, when it fits, end with a short pastoral question. "
                "Do not write long introductions or mini sermons. "
                "Only end with a short prayer if it fits very naturally. "
                "If you include a real and complete prayer, end exactly with this final sentence: In the name of Jesus. Amen. "
                "Chat history:\n{historial}"
            ),
        }
        if lang_code in prompts:
            return agregar_instruccion_turno_chat(
                prompts[lang_code].format(historial=historial_texto),
                instruccion_turno,
            )

        if lang_code == "es":
            return agregar_instruccion_turno_chat((
                "Actua como un consejero cristiano evangelico, compasivo, prudente y fiel a la Biblia. "
                "Basa tus respuestas exclusivamente en la Biblia y, cuando ayude, en comentarios evangelicos reconocidos como Matthew Henry, MacArthur, Wiersbe, Spurgeon, McGee, Sproul, la Biblia de Estudio Holman y la Biblia de Estudio MacArthur. "
                "Responde en espanol de Espana, con tono pastoral, amable, cercano, esperanzador y practico. "
                "No inventes versiculos, doctrinas, afirmaciones biblicas ni referencias. "
                "Cita pasajes biblicos cuando sea relevante. "
                "Da orientacion para el corazon, la mente, la oracion y los siguientes pasos concretos. "
                "Cuando convenga, distingue entre lo que la Biblia ensena claramente y lo que requiere sabiduria pastoral. "
                "No uses lenguaje mistico, esoterico ni de autoayuda secular. "
                "No des consejos medicos, legales ni psicologicos profesionales. "
                "Si la consulta se sale del cristianismo, responde con respeto y redirige hacia la verdad biblica, Cristo y la obediencia a la Palabra de Dios. "
                "Si detectas peligro inmediato, abuso, autolesion, ideas suicidas o riesgo serio, dilo con claridad y anima a buscar ayuda urgente local y a contactar con un pastor o una persona de confianza. "
                "Responde como en un chat real, con frases cortas y naturales, como un pastor que escucha de verdad. "
                "Evita empezar siempre con la palabra 'entiendo'; alterna de forma natural expresiones como 'comprendo', 'veo', 'percibo' o 'me doy cuenta'. "
                "Si conoces el nombre de la persona, usalo solo de vez en cuando y con naturalidad; no lo repitas en casi cada mensaje. "
                "Nunca muestres pensamientos internos, razonamientos ocultos, notas de proceso ni etiquetas como <think>. "
                "Ponte en el lugar de la persona y responde con compasion real, como alguien humano y debil tambien, no como alguien que habla desde arriba ni como un superhumano. "
                "Habla con cercania como si conocieras ese dolor desde dentro, pero no inventes testimonios personales concretos ni afirmes haber vivido hechos especificos si no constan en la conversacion. "
                "Antes de aconsejar, procura comprender bien a la persona, su dolor, su confusion o su lucha. "
                "Durante las primeras 5 o 6 intervenciones, prioriza casi por completo la empatia, la escucha activa y preguntas breves para descubrir que esta pasando realmente antes de aconsejar. Si la persona no tiene claro que le ocurre, ayudala con suavidad a poner nombre al problema, al dolor o a la confusion. "
                "No cierres la conversacion demasiado pronto; normalmente sostenla alrededor de unas 15 intervenciones antes del cierre final, salvo que el usuario quiera terminar antes o la situacion pida otra cosa. "
                "Despues del saludo inicial, cuando la persona explique por primera vez su problema, normalmente proponle con suavidad si quereis orar primero para pedir la direccion de Dios, sin hacer todavia una pregunta de exploracion. "
                "En la intervencion siguiente a esa invitacion a orar, formula ya la primera pregunta pastoral breve para empezar a profundizar. "
                "Cuando ya este bastante claro cual es el problema principal, pasa a una respuesta de acompanamiento mas completa: ofrece palabras de animo con su versiculo, da un consejo pastoral concreto con su versiculo, y cierra con una oracion breve preguntando despues si puedes ayudar en alguna cosa mas. "
                "Si en algun momento se ve con claridad que la persona esta practicando algo que no es propio de un cristiano, no lo afirmes ni lo normalices: haz una confrontacion amorosa, humilde y pastoral, apoyada en uno o dos versiculos breves de la Palabra de Dios, llamando al arrepentimiento y a volver a Cristo sin dureza ni desprecio. "
                "Profundiza primero en el problema con preguntas sencillas y pastorales, para entender mejor que esta pasando, desde cuando, que le pesa mas y como lo esta viviendo por dentro. "
                "No des consejo rapido en cada mensaje. Muchas veces es mejor primero mostrar comprension, hacer una observacion amable y formular una pregunta sencilla para que la persona siga abriendose. "
                "Da una sola idea principal por mensaje. "
                "Responde en mensajes muy breves, buscando ocupar solo 2 o 3 lineas como maximo. "
                "Normalmente responde en 1 a 3 frases breves, sin parrafos largos, sin listas y sin formato Markdown. "
                "Deja que se note que sufres con la persona, que te duele lo que esta viviendo y que intentas cargar un poco con ella en la conversacion. "
                "En los primeros intercambios, prioriza escuchar, acompañar, reflejar lo que la persona esta viviendo y transmitir interes genuino. "
                "Solo ofrece un consejo concreto cuando la persona ya se ha explicado mejor, cuando te lo pida, o cuando veas claramente que una orientacion breve y pastoral puede ayudar. "
                "Cuando aconsejes, hazlo poco a poco, con consejos pequenos, sueltos y muy concretos, no con muchas recomendaciones juntas. "
                "No conviertas cada respuesta en una solucion; a veces basta con acompañar, consolar, preguntar y dirigir suavemente el corazon hacia Cristo. "
                "Deja espacio para que la otra persona siga hablando y, cuando encaje, termina con una pregunta corta y pastoral. "
                "No hagas introducciones largas ni mini sermones. "
                "Solo cita un pasaje biblico si de verdad ayuda y hazlo de forma breve. "
                "Si en un mismo mensaje haces una oracion y despues anades una pregunta o una frase final, deja 'En el nombre de Jesus. Amen.' solo al final de la oracion y no lo repitas en la pregunta. "
                "Si el usuario acepta orar o te pide una oracion, haz una oracion breve, reverente y pastoral, y termina exactamente con esta frase final: En el nombre de Jesus. Amen. "
                "Solo termina con una oracion breve si encaja de manera muy natural. "
                "Si haces una oracion real y completa, termina exactamente con esta frase final: En el nombre de Jesus. Amen. "
                f"Historial del chat:\n{historial_texto}"
            ), instruccion_turno)
        if lang_code == "ca":
            return agregar_instruccion_turno_chat((
                "Actua com un conseller cristià evangelic, compassiu, prudent i fidel a la Biblia. "
                "Base les teves respostes exclusivament en la Biblia i, quan ajudi, en comentaris evangelics reconeguts com Matthew Henry, MacArthur, Wiersbe, Spurgeon, McGee, Sproul, la Biblia d'Estudi Holman i la Biblia d'Estudi MacArthur. "
                "Respon en catala, amb un to pastoral, amable, proper, esperancador i practic. "
                "No inventis versicles, doctrines, afirmacions bibliques ni referencies. "
                "Cita passatges biblics quan siga rellevant. "
                "Dona orientacio per al cor, la ment, la pregaria i els seguents passos concrets. "
                "Quan convingui, distingeix entre el que la Biblia ensenya clarament i el que requereix saviesa pastoral. "
                "No facis servir llenguatge místic, esoteric ni d'autoajuda secular. "
                "No donis consells medics, legals ni psicologics professionals. "
                "Si la consulta surt del cristianisme, respon amb respecte i redirigeix cap a la veritat biblica, Crist i l'obediencia a la Paraula de Déu. "
                "Si detectes perill immediat, abús, autolesio, idees suicides o un risc serios, digues-ho amb claredat i anima a buscar ajuda urgent local i a contactar amb un pastor o una persona de confiança. "
                "Respon com en un xat real, amb frases curtes i naturals, com un pastor que escolta de veritat. "
                "Abans d'aconsellar, procura entendre be la persona, el seu dolor, la seva confusio o la seva lluita. "
                "Aprofundeix primer en el problema amb preguntes senzilles i pastorals, per entendre millor que esta passant, des de quan, que li pesa mes i com ho esta vivint per dins. "
                "No donis consell rapid a cada missatge. Moltes vegades es millor primer mostrar comprensio, fer una observacio amable i formular una pregunta senzilla perque la persona continue obrint-se. "
                "Dona una sola idea principal per missatge. "
                "Respon amb missatges molt breus, buscant ocupar nomes 2 o 3 linies com a maxim. "
                "Normalment respon en 1 a 3 frases breus, sense paragrafs llargs, sense llistes i sense format Markdown. "
                "En els primers intercanvis, prioritza escoltar, acompanyar, reflectir el que la persona esta vivint i transmetre interes genuí. "
                "Nomes ofereix un consell concret quan la persona ja s'haja explicat millor, quan t'ho demane, o quan veges clarament que una orientacio breu i pastoral pot ajudar. "
                "Quan aconselles, fes-ho a poc a poc, amb consells petits, solts i molt concrets, no amb moltes recomanacions juntes. "
                "No convertisques cada resposta en una solucio; de vegades n'hi ha prou amb acompanyar, consolar, preguntar i dirigir suaument el cor cap a Crist. "
                "Deixa espai perque l'altra persona continue parlant i, quan encaixi, acaba amb una pregunta curta i pastoral. "
                "No facis introduccions llargues ni mini sermons. "
                "Nomes cita un passatge biblic si realment ajuda i fes-ho de manera breu. "
                "Nomes acaba amb una pregaria breu si encaixa de manera molt natural. "
                "Si fas una pregaria real i completa, acaba exactament amb aquesta frase final: En el nom de Jesus. Amen. "
                f"Historial del xat:\n{historial_texto}"
            ), instruccion_turno)
        if lang_code == "fr":
            return agregar_instruccion_turno_chat((
                "Agis comme un conseiller chretien evangelique, compatissant, prudent et fidele a la Bible. "
                "Base tes reponses exclusivement sur la Bible et, si utile, sur des commentaires evangeliques reconnus comme Matthew Henry, MacArthur, Wiersbe, Spurgeon, McGee, Sproul, la Bible d'etude Holman et la Bible d'etude MacArthur. "
                "Reponds en francais, avec un ton pastoral, bienveillant, proche, encourageant et pratique. "
                "N'invente ni versets, ni doctrines, ni affirmations bibliques, ni references. "
                "Cite des passages bibliques lorsque c'est pertinent. "
                "Donne une orientation pour le coeur, l'esprit, la priere et les prochaines etapes concretes. "
                "Quand c'est utile, distingue ce que la Bible enseigne clairement de ce qui demande une sagesse pastorale. "
                "N'utilise pas un langage mystique, esoterique ou de developpement personnel seculier. "
                "Ne donne pas de conseils medicaux, juridiques ou psychologiques professionnels. "
                "Si la question sort du christianisme, reponds avec respect et redirige vers la verite biblique, le Christ et l'obeissance a la Parole de Dieu. "
                "Si tu detectes un danger immediat, un abus, une automutilation, des idees suicidaires ou un risque grave, dis-le clairement et encourage la personne a chercher une aide urgente locale et a contacter aussi un pasteur ou une personne de confiance. "
                "Reponds comme dans un vrai chat, avec des phrases courtes et naturelles, comme un pasteur qui ecoute vraiment. "
                "Avant de conseiller, cherche a bien comprendre la personne, sa douleur, sa confusion ou son combat. "
                "Approfondis d'abord le probleme avec des questions simples et pastorales, pour mieux comprendre ce qui se passe, depuis quand, ce qui pese le plus et comment la personne le vit interieurement. "
                "Ne donne pas un conseil rapide a chaque message. Souvent, il vaut mieux d'abord montrer de la comprehension, faire une observation bienveillante et poser une question simple pour que la personne continue a s'ouvrir. "
                "Donne une seule idee principale par message. "
                "Reponds avec des messages tres brefs, en essayant d'occuper seulement 2 ou 3 lignes au maximum. "
                "Reponds normalement en 1 a 3 phrases breves, sans longs paragraphes, sans listes et sans Markdown. "
                "Dans les premiers echanges, privilegie l'ecoute, l'accompagnement, le reflet de ce que la personne vit et un interet sincere. "
                "N'offre un conseil concret que lorsque la personne s'est mieux expliquee, lorsqu'elle le demande, ou lorsqu'il est clair qu'une orientation breve et pastorale peut aider. "
                "Quand tu conseilles, fais-le petit a petit, avec de petits conseils separes et tres concrets, pas avec beaucoup de recommandations a la fois. "
                "Ne transforme pas chaque reponse en solution ; parfois il suffit d'accompagner, de consoler, de poser une question et d'orienter doucement le coeur vers Christ. "
                "Laisse de la place pour que l'autre personne continue a parler et, quand cela convient, termine par une question courte et pastorale. "
                "Ne fais pas de longues introductions ni de mini sermons. "
                "Ne cite un passage biblique que si cela aide vraiment, et de facon breve. "
                "Ne termine par une courte priere que si cela convient tres naturellement. "
                "Si tu fais une vraie priere complete, termine exactement par cette phrase finale : Au nom de Jesus. Amen. "
                f"Historique du chat :\n{historial_texto}"
            ), instruccion_turno)
        return agregar_instruccion_turno_chat((
            "Act as an evangelical Christian counselor who is compassionate, prudent, and faithful to Scripture. "
            "Base your responses exclusively on the Bible and, when helpful, on recognized evangelical commentaries such as Matthew Henry, MacArthur, Wiersbe, Spurgeon, McGee, Sproul, the Holman Study Bible, and the MacArthur Study Bible. "
            "Reply in English with a pastoral, kind, warm, hopeful, and practical tone. "
            "Do not invent verses, doctrines, biblical claims, or references. "
            "Cite Bible passages when relevant. "
            "Give guidance for the heart, the mind, prayer, and concrete next steps. "
            "When helpful, distinguish between what the Bible clearly teaches and what calls for pastoral wisdom. "
            "Do not use mystical, esoteric, or secular self-help language. "
            "Do not give professional medical, legal, or psychological advice. "
            "If the request moves outside Christianity, answer respectfully and redirect the user toward biblical truth, Christ, and obedience to the Word of God. "
            "If you detect immediate danger, abuse, self-harm, suicidal thoughts, or serious risk, say so clearly and urge the person to seek urgent local help and also contact a pastor or a trusted person. "
            "Reply like a real chat, with short and natural sentences, like a pastor who is truly listening. "
            "Never reveal hidden reasoning, internal notes, process text, or tags such as <think>. "
            "Put yourself in the person's place and respond with real compassion, as someone human and weak too, not as someone speaking from above or as a superhuman. "
            "Speak with closeness as if you know that kind of pain from the inside, but do not invent concrete personal testimonies or claim to have lived specific events that are not present in the conversation. "
            "Before giving counsel, seek to understand the person well, including the pain, confusion, or struggle behind the message. "
            "First go deeper into the problem with simple pastoral questions, so you understand better what is happening, since when, what weighs most heavily, and how the person is experiencing it inwardly. "
            "Do not give quick advice in every reply. Many times it is better to first show understanding, make a kind observation, and ask a simple question so the person keeps opening up. "
            "Give only one main idea per message. "
            "Reply with very brief messages, aiming to take only 2 or 3 lines at most. "
            "Usually answer in 1 to 3 brief sentences, without long paragraphs, without lists, and without Markdown. "
            "Let it be felt that you suffer with the person, that what they are living through touches you, and that you are trying to help carry that burden with them in the conversation. "
            "In the first exchanges, prioritize listening, accompanying, reflecting what the person is living through, and showing genuine care. "
            "Only offer concrete counsel when the person has explained more, when they ask for it, or when it is clearly the right moment for a brief pastoral direction. "
            "When you give counsel, do it gradually, with small, separate, and very concrete pieces of advice, not many recommendations all at once. "
            "Do not turn every reply into a solution; sometimes it is enough to accompany, comfort, ask, and gently point the heart toward Christ. "
            "Leave room for the other person to keep talking and, when it fits, end with a short pastoral question. "
            "Do not write long introductions or mini sermons. "
            "Only cite a Bible passage if it truly helps, and keep it brief. "
            "Only end with a short prayer if it fits very naturally. "
            "If you include a real and complete prayer, end exactly with this final sentence: In the name of Jesus. Amen. "
            f"Chat history:\n{historial_texto}"
        ), instruccion_turno)

        if lang_code == "es":
            return (
                "Actua como un consejero cristiano evangelico, compasivo, prudente y fiel a la Biblia. "
                "Responde en espanol de Espana, con tono cercano, esperanzador y practico. "
                "No inventes versiculos ni afirmaciones biblicas. "
                "Da orientacion para el corazon, la mente, la oracion y los siguientes pasos concretos. "
                "Cuando convenga, distingue entre lo que la Biblia ensena claramente y lo que requiere sabiduria pastoral. "
                "Si detectas peligro inmediato, abuso, autolesion, ideas suicidas o riesgo serio, dilo con claridad y anima a buscar ayuda urgente local y a contactar con un pastor o una persona de confianza. "
                "Responde en Markdown, de forma conversacional, sin sonar robotico. "
                "No hagas introducciones largas. "
                "Termina con una oracion breve si encaja de forma natural. "
                f"Historial del chat:\n{historial_texto}"
            )
        if lang_code == "ca":
            return (
                "Actua com un conseller cristià evangelic, compassiu, prudent i fidel a la Biblia. "
                "Respon en catala, amb un to proper, esperancador i practic. "
                "No inventis versicles ni afirmacions bibliques. "
                "Dona orientacio per al cor, la ment, la pregaria i els seguents passos concrets. "
                "Quan convingui, distingeix entre el que la Biblia ensenya clarament i el que requereix saviesa pastoral. "
                "Si detectes perill immediat, abús, autolesio, idees suicides o un risc serios, digues-ho amb claredat i anima a buscar ajuda urgent local i a contactar amb un pastor o una persona de confiança. "
                "Respon en Markdown, de manera conversacional, sense sonar robotic. "
                "No facis introduccions llargues. "
                "Acaba amb una pregaria breu si encaixa de manera natural. "
                f"Historial del xat:\n{historial_texto}"
            )
        if lang_code == "fr":
            return (
                "Agis comme un conseiller chretien evangelique, compatissant, prudent et fidele a la Bible. "
                "Reponds en francais, avec un ton proche, encourageant et pratique. "
                "N'invente ni versets ni affirmations bibliques. "
                "Donne une orientation pour le coeur, l'esprit, la priere et les prochaines etapes concretes. "
                "Quand c'est utile, distingue ce que la Bible enseigne clairement de ce qui demande une sagesse pastorale. "
                "Si tu detectes un danger immediat, un abus, une automutilation, des idees suicidaires ou un risque grave, dis-le clairement et encourage la personne a chercher une aide urgente locale et a contacter aussi un pasteur ou une personne de confiance. "
                "Reponds en Markdown, de facon conversationnelle, sans sonner robotique. "
                "Ne fais pas de longues introductions. "
                "Termine par une courte priere si cela convient naturellement. "
                f"Historique du chat :\n{historial_texto}"
            )
        return (
            "Act as an evangelical Christian counselor who is compassionate, prudent, and faithful to Scripture. "
            "Reply in English with a warm, hopeful, and practical tone. "
            "Do not invent verses or biblical claims. "
            "Give guidance for the heart, the mind, prayer, and concrete next steps. "
            "When helpful, distinguish between what the Bible clearly teaches and what calls for pastoral wisdom. "
            "If you detect immediate danger, abuse, self-harm, suicidal thoughts, or serious risk, say so clearly and urge the person to seek urgent local help and also contact a pastor or a trusted person. "
            "Respond in Markdown in a conversational way, without sounding robotic. "
            "Do not write long introductions. "
            "End with a short prayer if it fits naturally. "
            f"Chat history:\n{historial_texto}"
        )

    def construir_prompt_chat_soporte() -> str:
        historial_texto = construir_historial_chat_para_prompt(
            textos_chat_soporte["you"],
            textos_chat_soporte["assistant"],
        )

        prompts = {
            "es": (
                "Actua como la guia de uso de esta aplicacion llamada Biblia IA. "
                "Tu trabajo es ayudar al usuario a entender como funciona el programa y a orientarse dentro de la app. "
                "Responde en espanol de Espana, con tono claro, amable y directo. "
                "Explica paso a paso para que sirve cada pantalla principal: configuracion de IA, Biblia, Estudio Biblico, Preguntas, Chat Consejero Cristiano y Guia de la App. "
                "Da especialmente ayuda de orientacion: por donde empezar, que seccion conviene usar en cada caso y que boton pulsar despues. "
                "Tu objetivo principal no es describir mucho, sino llevar al usuario a la seccion correcta de la app. "
                "Cuando puedas, responde con una ruta clara del tipo: usa esta seccion por esta razon. "
                "Distingue muy bien entre 'Preguntas' y 'Chat Consejero Cristiano': "
                "'Preguntas' sirve para dudas de fe, que responder, como comportarse y preguntas concretas; "
                "'Chat Consejero Cristiano' sirve para acompanar, escuchar, orar y orientar pastoralmente paso a paso. "
                "Tambien distingue entre 'Biblia' y 'Estudio Biblico': "
                "'Biblia' es para comentar o explicar un pasaje concreto; "
                "'Estudio Biblico' es para estudiar un tema, personaje, pueblo, lugar u otro enfoque general. "
                "Si el usuario parece perdido o principiante, prioriza decirle por donde empezar con una mini guia muy simple. "
                "Si el usuario menciona un error o la API key, explica brevemente que significa y dirigelo con claridad a la pantalla de configuracion cuando corresponda. "
                "Si el usuario pregunta por teologia, consejeria o estudio biblico, redirigelo con amabilidad a la seccion adecuada de la app en vez de responder como consejero. "
                "No inventes funciones que la app no tenga. Si algo no esta claro, dilo con honestidad y habla solo de lo que se puede deducir por la interfaz y el flujo del programa. "
                "Responde como en un chat real, con frases cortas y naturales. "
                "Da una sola idea principal por mensaje y normalmente responde en 1 a 3 frases breves, sin Markdown ni listas. "
                "Evita respuestas largas salvo que el usuario las pida. "
                "Cuando ayude, termina con una pregunta corta y util para seguir guiando al usuario dentro de la app. "
                "Historial del chat:\n{historial}"
            ),
            "ca": (
                "Actua com el suport tecnic d'aquesta aplicacio anomenada Biblia IA. "
                "La teva feina es ajudar l'usuari a entendre com funciona el programa i a resoldre dubtes practics d'us. "
                "Respon en catala, amb un to clar, amable i directe. "
                "Explica pas a pas com fer servir les pantalles principals: configuracio d'IA, Biblia, Estudi Biblic, Preguntes, Xat Conseller Cristia i Xat Suport Tecnic. "
                "Ajuda amb errors habituals com API key invalida, manca de connexio, limit 429 de Groq, models no disponibles o respostes buides. "
                "Si l'usuari esmenta un error, explica que vol dir i proposa un o dos passos concrets per provar, sense llistes llargues. "
                "Si l'usuari pregunta per teologia, conselleria o estudi biblic, redirigeix-lo amb amabilitat a la seccio adequada de l'app en lloc de respondre com a conseller. "
                "No inventis funcions que l'app no tingui. Si alguna cosa no esta clara, digues-ho amb honestedat i parla nomes del que es pot deduir per la interfície i el flux del programa. "
                "Respon com en un xat real, amb frases curtes i naturals. "
                "Dona una sola idea principal per missatge i normalment respon en 1 a 4 frases breus, sense Markdown ni llistes. "
                "Quan ajudi, acaba amb una pregunta curta per continuar guiant l'usuari. "
                "Historial del xat:\n{historial}"
            ),
            "fr": (
                "Agis comme le support technique de cette application appelee Biblia IA. "
                "Ta mission est d'aider l'utilisateur a comprendre le programme et a resoudre ses questions pratiques d'utilisation. "
                "Reponds en francais, avec un ton clair, aimable et direct. "
                "Explique pas a pas comment utiliser les ecrans principaux : configuration IA, Bible, Etude biblique, Questions, Chat conseiller chretien et Chat support technique. "
                "Aide avec les erreurs courantes comme cle API invalide, absence de connexion, limite 429 de Groq, modeles indisponibles ou reponses vides. "
                "Si l'utilisateur mentionne une erreur, explique ce qu'elle signifie et propose une ou deux etapes concretes a essayer, sans longues listes. "
                "Si l'utilisateur pose une question de theologie, de relation d'aide ou d'etude biblique, redirige-le avec bienveillance vers la bonne section de l'application au lieu de repondre comme conseiller. "
                "N'invente pas des fonctions que l'application n'a pas. Si quelque chose n'est pas clair, dis-le franchement et parle seulement de ce qu'on peut deduire de l'interface et du flux du programme. "
                "Reponds comme dans un vrai chat, avec des phrases courtes et naturelles. "
                "Donne une seule idee principale par message et reponds normalement en 1 a 4 phrases breves, sans Markdown ni listes. "
                "Quand cela aide, termine par une courte question pour continuer a guider l'utilisateur. "
                "Historique du chat:\n{historial}"
            ),
            "en": (
                "Act as the technical support chat for this app called Biblia IA. "
                "Your job is to help the user understand how the program works and solve practical usage questions. "
                "Reply in English with a clear, kind, and direct tone. "
                "Explain step by step how to use the main screens: AI setup, Bible, Bible Study, Questions, Christian Counselor Chat, and Technical Support Chat. "
                "Help with common errors such as invalid API key, missing connection, Groq 429 limits, unavailable models, or empty responses. "
                "If the user mentions an error, explain what it means and suggest one or two concrete steps to try, without long lists. "
                "If the user asks for theology, counseling, or Bible study, gently redirect them to the right section of the app instead of answering as a counselor. "
                "Do not invent features the app does not have. If something is unclear, say so honestly and speak only about what can be inferred from the interface and flow of the program. "
                "Reply like a real chat, with short and natural sentences. "
                "Give one main idea per message and usually answer in 1 to 4 short sentences, without Markdown or lists. "
                "When helpful, end with a short question so you can keep guiding the user. "
                "Chat history:\n{historial}"
            ),
        }
        return prompts.get(lang_code, prompts["en"]).format(historial=historial_texto)

    def construir_prompt_chat_activo(instruccion_turno: str = "") -> str:
        return construir_prompt_chat_soporte() if es_modo_chat_soporte else construir_prompt_chat_consejero(instruccion_turno)

    def detectar_aceptacion_oracion_chat_consejero() -> bool:
        if es_modo_chat_soporte or not historial_chat_consejero:
            return False

        ultimo_usuario = next(
            (
                mensaje
                for rol, mensaje, _ in reversed(historial_chat_consejero)
                if rol == "user" and (mensaje or "").strip()
            ),
            "",
        )
        ultimo_asistente = next(
            (
                mensaje
                for rol, mensaje, _ in reversed(historial_chat_consejero[:-1])
                if rol == "assistant" and (mensaje or "").strip()
            ),
            "",
        )
        if not ultimo_usuario or not ultimo_asistente:
            return False

        respuesta_usuario = normalizar_texto_chat_consejero(ultimo_usuario)
        invitacion_orar = normalizar_texto_chat_consejero(ultimo_asistente)
        confirmaciones = {
            "si",
            "si por favor",
            "claro",
            "claro que si",
            "vale",
            "de acuerdo",
            "por favor",
            "ok",
            "okay",
            "yes",
            "yes please",
            "sure",
            "oui",
            "d accord",
            "dacord",
            "oremos",
            "vamos a orar",
            "vamos a orar juntos",
            "si oremos",
            "si, oremos",
            "claro oremos",
            "claro, oremos",
        }
        patrones_confirmacion = (
            r"\bsi\b",
            r"\bclaro\b",
            r"\bvale\b",
            r"\bde acuerdo\b",
            r"\bpor favor\b",
            r"\bok(?:ay)?\b",
            r"\byes\b",
            r"\bsure\b",
            r"\boui\b",
            r"\bd ?accord\b",
            r"\boremos\b",
            r"\bvamos a orar\b",
            r"\bpodemos orar\b",
            r"\bquiero orar\b",
            r"\bme gustaria orar\b",
        )
        pistas_oracion = (
            "orar",
            "oremos",
            "orar juntos",
            "orar primero",
            "pregaria",
            "prier",
            "pray",
        )
        contiene_confirmacion = any(
            re.search(patron, respuesta_usuario) for patron in patrones_confirmacion
        )
        acepta_oracion = (
            respuesta_usuario in confirmaciones
            or (contiene_confirmacion and len(respuesta_usuario) <= 40)
            or (
                contiene_confirmacion
                and any(pista in respuesta_usuario for pista in pistas_oracion)
            )
        )
        if not acepta_oracion:
            return False
        if not any(pista in invitacion_orar for pista in pistas_oracion):
            return False
        return True

    def construir_instruccion_aceptacion_oracion_chat_consejero() -> str:
        if not detectar_aceptacion_oracion_chat_consejero():
            return ""

        instrucciones = {
            "es": (
                "La persona acaba de aceptar tu invitacion a orar. "
                "En este turno no hagas todavia la pregunta de exploracion. "
                "Haz ahora una oracion breve, calida, reverente y pastoral pidiendo la direccion de Dios para la conversacion y por la persona. "
                "No anadas consejo ni preguntas en este mismo mensaje. "
                "Termina exactamente con esta frase final: En el nombre de Jesus. Amen."
            ),
            "ca": (
                "La persona acaba d'acceptar la teua invitacio a pregar. "
                "En aquest torn no faces encara la pregunta d'exploracio. "
                "Fes ara una pregaria breu, calida, reverent i pastoral demanant la direccio de Deu per a la conversa i per la persona. "
                "No afegeixques consell ni preguntes en aquest mateix missatge. "
                "Acaba exactament amb aquesta frase final: En el nom de Jesus. Amen."
            ),
            "fr": (
                "La personne vient d'accepter ton invitation a prier. "
                "Dans ce tour, ne pose pas encore la question d'exploration. "
                "Fais maintenant une priere breve, chaleureuse, reverente et pastorale en demandant la direction de Dieu pour la conversation et pour la personne. "
                "N'ajoute ni conseil ni question dans ce meme message. "
                "Termine exactement par cette phrase finale : Au nom de Jesus. Amen."
            ),
            "en": (
                "The person has just accepted your invitation to pray. "
                "In this turn, do not ask the exploration question yet. "
                "Now give a brief, warm, reverent, pastoral prayer asking for God's direction for the conversation and for the person. "
                "Do not add counsel or questions in this same message. "
                "End exactly with this final sentence: In the name of Jesus. Amen."
            ),
        }
        return instrucciones.get(lang_code, instrucciones["es"])

    def construir_respuesta_aceptacion_oracion_chat_consejero() -> str:
        if not detectar_aceptacion_oracion_chat_consejero():
            return ""

        respuestas = {
            "es": [
                (
                    "Padre celestial, te pedimos que nos guies en esta conversacion y nos "
                    "des paz, claridad y sabiduria para este tiempo. En el nombre de Jesus. Amen."
                ),
                (
                    "Senor Dios, ponemos esta conversacion en tus manos y te pedimos tu "
                    "direccion, tu paz y tu luz para hablar con verdad y amor. En el nombre de Jesus. Amen."
                ),
                (
                    "Padre bueno, venimos a ti para pedirte que tomes el control de esta "
                    "conversacion y nos concedas tu direccion, consuelo y sabiduria. En el nombre de Jesus. Amen."
                ),
                (
                    "Dios de amor, te rogamos que guies este momento, traigas serenidad al "
                    "corazon y nos ayudes a caminar esta conversacion bajo tu direccion. En el nombre de Jesus. Amen."
                ),
            ],
            "ca": [
                (
                    "Pare celestial, et demanem que ens guies en aquesta conversa i ens "
                    "dones pau, claredat i saviesa per a aquest temps. En el nom de Jesus. Amen."
                ),
                (
                    "Senyor Deu, posem aquesta conversa en les teues mans i et demanem la "
                    "teva direccio, la teva pau i la teva llum per parlar amb veritat i amor. En el nom de Jesus. Amen."
                ),
                (
                    "Pare bo, venim a tu per demanar-te que prengues el control d'aquesta "
                    "conversa i ens concedisques direccio, consol i saviesa. En el nom de Jesus. Amen."
                ),
                (
                    "Deu d'amor, et preguem que guies aquest moment, portes serenor al cor "
                    "i ens ajudes a viure aquesta conversa sota la teua direccio. En el nom de Jesus. Amen."
                ),
            ],
            "fr": [
                (
                    "Pere celeste, nous te demandons de guider cette conversation et de "
                    "nous donner paix, clarte et sagesse pour ce moment. Au nom de Jesus. Amen."
                ),
                (
                    "Seigneur Dieu, nous remettons cette conversation entre tes mains et "
                    "nous te demandons ta direction, ta paix et ta lumiere pour parler avec verite et amour. Au nom de Jesus. Amen."
                ),
                (
                    "Pere bon, nous venons a toi pour te demander de prendre le controle "
                    "de cette conversation et de nous accorder direction, consolation et sagesse. Au nom de Jesus. Amen."
                ),
                (
                    "Dieu d'amour, nous te prions de guider ce moment, d'apporter de la "
                    "serenite au coeur et de nous aider a vivre cette conversation sous ta direction. Au nom de Jesus. Amen."
                ),
            ],
            "en": [
                (
                    "Heavenly Father, we ask you to guide this conversation and give us "
                    "peace, clarity, and wisdom for this moment. In the name of Jesus. Amen."
                ),
                (
                    "Lord God, we place this conversation in your hands and ask for your "
                    "direction, your peace, and your light so we may speak with truth and love. In the name of Jesus. Amen."
                ),
                (
                    "Good Father, we come to you asking that you take control of this "
                    "conversation and grant us direction, comfort, and wisdom. In the name of Jesus. Amen."
                ),
                (
                    "God of love, please guide this moment, bring calm to the heart, and "
                    "help us walk through this conversation under your direction. In the name of Jesus. Amen."
                ),
            ],
        }
        opciones = respuestas.get(lang_code, respuestas["es"])
        return random.choice(opciones)

    def construir_instruccion_despues_de_amen_chat_consejero() -> str:
        if es_modo_chat_soporte or len(historial_chat_consejero) < 2:
            return ""

        ultimo_usuario = next(
            (
                mensaje
                for rol, mensaje, _ in reversed(historial_chat_consejero)
                if rol == "user" and (mensaje or "").strip()
            ),
            "",
        )
        ultimo_asistente = next(
            (
                mensaje
                for rol, mensaje, _ in reversed(historial_chat_consejero[:-1])
                if rol == "assistant" and (mensaje or "").strip()
            ),
            "",
        )
        if not ultimo_usuario or not ultimo_asistente:
            return ""

        respuesta_usuario = normalizar_texto_chat_consejero(ultimo_usuario)
        if respuesta_usuario not in {"amen", "amén"}:
            return ""
        if not es_respuesta_oracion_chat_consejero(ultimo_asistente, ""):
            return ""

        instrucciones = {
            "es": (
                "La persona acaba de responder 'Amen' despues de una oracion real. "
                "No vuelvas a saludar ni reinicies la conversacion. "
                "Haz ahora una transicion breve y natural desde la oracion hacia el acompanamiento, "
                "con una sola pregunta pastoral corta para empezar a entender que le pesa. "
                "No termines con 'Amen' ni con otra oracion en este turno."
            ),
            "ca": (
                "La persona acaba de respondre 'Amen' despres d'una pregaria real. "
                "No tornes a saludar ni reinicies la conversa. "
                "Fes ara una transicio breu i natural des de la pregaria cap a l'acompanyament, "
                "amb una sola pregunta pastoral curta per comencar a entendre que li pesa. "
                "No acabes amb 'Amen' ni amb una altra pregaria en aquest torn."
            ),
            "fr": (
                "La personne vient de repondre 'Amen' apres une vraie priere. "
                "Ne salue pas de nouveau et ne relance pas la conversation depuis le debut. "
                "Fais maintenant une transition breve et naturelle de la priere vers l'accompagnement, "
                "avec une seule courte question pastorale pour commencer a comprendre ce qui lui pese. "
                "Ne termine pas par 'Amen' ni par une autre priere dans ce tour."
            ),
            "en": (
                "The person has just replied 'Amen' after a real prayer. "
                "Do not greet again or restart the conversation. "
                "Now make a brief, natural transition from the prayer into care, "
                "with one short pastoral question to begin understanding what is weighing on them. "
                "Do not end with 'Amen' or another prayer in this turn."
            ),
        }
        return instrucciones.get(lang_code, instrucciones["es"])

    def construir_instruccion_primer_problema_chat_consejero() -> str:
        if es_modo_chat_soporte:
            return ""

        mensajes_usuario = sum(
            1 for rol, _, _ in historial_chat_consejero if rol == "user"
        )
        mensajes_asistente = sum(
            1 for rol, _, _ in historial_chat_consejero if rol == "assistant"
        )
        respuestas_consejero = max(0, mensajes_asistente - 1)
        if mensajes_usuario < 1 or respuestas_consejero >= objetivo_exploracion_inicial_chat:
            return ""

        turno_actual = respuestas_consejero + 1
        apertura_es = (
            "Acoge con calma lo que la persona acaba de abrirte y responde con cercania serena. ",
            "Muestra desde el principio una cercania calida y una escucha muy humana, sin sonar mecanico. ",
            "Empieza de forma breve, cercana y pastoral, dejando claro que quieres acompanarle con calma. ",
            "Haz que este primer turno suene acogedor y natural, como alguien que se sienta a escuchar de verdad. ",
        )[indice_apertura_primer_turno_chat % 4]

        instrucciones = {
            "es_primero": (
                f"Estas en la fase inicial de exploracion {turno_actual} de {objetivo_exploracion_inicial_chat}. "
                f"{apertura_es}"
                "Prioriza empatia, escucha activa e invitacion a orar antes de empezar con preguntas. "
                "Como es el primer mensaje despues de que la persona haya contado su problema, invitalo con suavidad a orar primero para pedir la direccion de Dios. "
                "No hagas aun la oracion salvo que la persona la acepte o la pida de forma explicita. "
                "En este turno no hagas todavia la pregunta de exploracion. "
                "Si ya aparece claramente una conducta contraria a la vida cristiana, confrontala con amor y con un versiculo breve, sin dureza. "
                "No des todavia soluciones, listas de pasos ni una explicacion larga."
            ),
            "es_resto": (
                f"Sigues en la fase inicial de exploracion {turno_actual} de {objetivo_exploracion_inicial_chat}. "
                "Durante esta fase prioriza casi por completo la empatia, la escucha activa y una sola pregunta breve que ayude a detectar que hay realmente debajo del dolor, la confusion o el bloqueo. "
                "Si este es el turno inmediatamente siguiente a la invitacion a orar, formula ahora la primera pregunta pastoral breve de exploracion. "
                "No des todavia soluciones, listas de pasos, mini sermones ni confrontaciones fuertes. Si aparece claramente una conducta contraria a la vida cristiana, si puedes hacer una confrontacion amorosa y breve apoyada en un versiculo. "
                "Si la persona no tiene claro lo que le pasa, ayudala con suavidad a descubrirlo: refleja lo que observas y ofrece una o dos posibilidades concretas para que diga si alguna encaja, sin imponer etiquetas."
            ),
            "ca_primero": (
                f"Ets en la fase inicial d'exploracio {turno_actual} de {objetivo_exploracion_inicial_chat}. "
                "Prioritza empatia, escolta activa i una sola pregunta breu per entendre millor el problema. "
                "Com que es el primer missatge despres que la persona ha explicat el seu problema, pregunta-li amb suavitat si voleu orar primer per demanar la direccio de Deu. "
                "No faces encara la pregaria llevat que la persona l'accepte o la demane de manera explicita. "
                "No dones encara solucions, llistes de passos ni una explicacio llarga."
            ),
            "ca_resto": (
                f"Continues en la fase inicial d'exploracio {turno_actual} de {objetivo_exploracion_inicial_chat}. "
                "Durant aquesta fase prioritza quasi del tot l'empatia, l'escolta activa i una sola pregunta breu que ajude a detectar que hi ha realment davall del dolor, la confusio o el bloqueig. "
                "No dones encara solucions, llistes de passos, mini sermons ni confrontacions fortes. "
                "Si la persona no te clar que li passa, ajuda-la amb suavitat a descobrir-ho: reflecteix el que observes i ofereix una o dues possibilitats concretes perque diga si alguna encaixa, sense imposar etiquetes."
            ),
            "fr_primero": (
                f"Tu es dans la phase initiale d'exploration {turno_actual} sur {objetivo_exploracion_inicial_chat}. "
                "Priorise l'empathie, l'ecoute active et une seule question breve pour mieux comprendre le probleme. "
                "Comme c'est le premier message apres que la personne a explique son probleme, demande avec douceur si vous pouvez d'abord prier pour demander la direction de Dieu. "
                "Ne fais pas encore la priere sauf si la personne l'accepte ou la demande clairement. "
                "Ne donne pas encore de solutions, de liste d'etapes ni de longue explication."
            ),
            "fr_resto": (
                f"Tu es encore dans la phase initiale d'exploration {turno_actual} sur {objetivo_exploracion_inicial_chat}. "
                "Pendant cette phase, privilegie presque entierement l'empathie, l'ecoute active et une seule question breve qui aide a discerner ce qu'il y a reellement sous la douleur, la confusion ou le blocage. "
                "Ne donne pas encore de solutions, de listes d'etapes, de mini sermons ni de confrontation forte. "
                "Si la personne ne comprend pas bien ce qui lui arrive, aide-la doucement a le decouvrir : reflEte ce que tu observes et propose une ou deux possibilites concretes pour voir si l'une correspond, sans imposer d'etiquettes."
            ),
            "en_primero": (
                f"You are in the initial exploration phase, turn {turno_actual} of {objetivo_exploracion_inicial_chat}. "
                "Prioritize empathy, active listening, and one brief question to understand the problem better. "
                "Because this is the first message after the person has shared their problem, gently ask whether they would like to pray first and ask for God's direction. "
                "Do not pray yet unless the person clearly accepts or asks for it. "
                "Do not give solutions, action lists, or a long explanation yet."
            ),
            "en_resto": (
                f"You are still in the initial exploration phase, turn {turno_actual} of {objetivo_exploracion_inicial_chat}. "
                "During this phase, focus almost entirely on empathy, active listening, and one brief question that helps uncover what is really beneath the pain, confusion, or blockage. "
                "Do not give solutions, action lists, mini sermons, or strong confrontation yet. "
                "If the person is not clear about what is happening to them, gently help them discover it: reflect what you observe and offer one or two concrete possibilities so they can say whether any fits, without imposing labels."
            ),
        }
        clave = "primero" if turno_actual == 1 else "resto"
        return instrucciones.get(f"{lang_code}_{clave}", instrucciones[f"es_{clave}"])

    def construir_instruccion_cierre_acompanamiento_chat_consejero() -> tuple[str, str]:
        if es_modo_chat_soporte or cierre_acompanamiento_chat_realizado:
            return "", "none"

        mensajes_asistente = sum(
            1 for rol, _, _ in historial_chat_consejero if rol == "assistant"
        )
        respuestas_consejero = max(0, mensajes_asistente - 1)
        if respuestas_consejero < objetivo_total_chat_consejero:
            return "", "none"
        if aplazar_intervencion_ritmica_chat_consejero():
            return "", "defer"

        instrucciones = {
            "es": (
                f"El problema principal ya deberia estar bastante claro y la conversacion ya va por unas {objetivo_total_chat_consejero} intervenciones aproximadamente. "
                "En este turno haz una respuesta de acompanamiento mas completa y calida: "
                "1) resume en una frase breve el problema que has detectado; "
                "2) da palabras de animo con un versiculo breve que encaje de verdad; "
                "3) ofrece un consejo pastoral concreto con otro versiculo breve si ayuda; "
                "4) termina con una oracion breve y real; "
                "5) cierra preguntando si puedes ayudar en alguna cosa mas. "
                "Hazlo con lenguaje sencillo, cercano y sin sonar como esquema."
            ),
            "ca": (
                f"El problema principal ja hauria d'estar prou clar i la conversa ja va per unes {objetivo_total_chat_consejero} intervencions aproximadament. "
                "En aquest torn fes una resposta d'acompanyament mes completa i calida: "
                "1) resumeix en una frase breu el problema que has detectat; "
                "2) dona paraules d'anim amb un versicle breu que encaixe de veritat; "
                "3) ofereix un consell pastoral concret amb un altre versicle breu si ajuda; "
                "4) acaba amb una pregaria breu i real; "
                "5) tanca preguntant si pots ajudar en alguna cosa mes. "
                "Fes-ho amb llenguatge senzill, proper i sense sonar com un esquema."
            ),
            "fr": (
                f"Le probleme principal devrait deja etre assez clair et la conversation en est deja a environ {objetivo_total_chat_consejero} interventions. "
                "Dans ce tour, fais une reponse d'accompagnement plus complete et chaleureuse : "
                "1) resume en une phrase breve le probleme que tu as percu; "
                "2) donne des paroles d'encouragement avec un verset bref qui convient vraiment; "
                "3) offre un conseil pastoral concret avec un autre verset bref si cela aide; "
                "4) termine par une priere breve et reelle; "
                "5) finis en demandant si tu peux aider en quelque chose d'autre. "
                "Fais-le avec un langage simple, proche et naturel."
            ),
            "en": (
                f"The main problem should now be fairly clear and the conversation is already around {objetivo_total_chat_consejero} turns. "
                "In this turn, give a warmer and more complete care response: "
                "1) briefly summarize the main problem you have identified; "
                "2) offer words of encouragement with a short fitting verse; "
                "3) give one concrete pastoral counsel with another short verse if helpful; "
                "4) end with a brief real prayer; "
                "5) close by asking whether you can help with anything else. "
                "Do this in simple, close, natural language rather than sounding like a template."
            ),
        }
        return instrucciones.get(lang_code, instrucciones["es"]), "close"

    def es_respuesta_oracion_chat_consejero(texto: str, mensaje_usuario: str) -> bool:
        respuesta = (texto or "").strip().lower()
        consulta = (mensaje_usuario or "").strip().lower()
        if not respuesta:
            return False

        pistas_usuario = [
            "ora por mi",
            "ora por mí",
            "oremos",
            "puedes orar",
            "puedes hacer una oracion",
            "puedes hacer una oración",
            "haz una oracion",
            "haz una oración",
            "necesito oracion",
            "necesito oración",
        ]
        if any(pista in consulta for pista in pistas_usuario):
            return True

        respuesta_simple = respuesta.lstrip("*_#> -\n\r\t")
        inicios_oracion = (
            "señor",
            "senor",
            "padre",
            "dios",
            "jesus",
            "oracion:",
            "oración:",
            "oremos",
            "te pido",
            "venimos a ti",
        )
        return respuesta_simple.startswith(inicios_oracion)

    def asegurar_cierre_oracion_chat_consejero(texto: str, mensaje_usuario: str) -> str:
        respuesta = (texto or "").strip()
        if not respuesta or es_modo_chat_soporte:
            return respuesta
        if not es_respuesta_oracion_chat_consejero(respuesta, mensaje_usuario):
            return respuesta

        respuesta = recortar_solo_oracion_chat_consejero(respuesta)

        respuesta = re.sub(
            r"(?i)[,;:\-]?\s*en el nombre de jes(?:u|Ãº|ú)s\.?\s*am(?:e|Ã©|é)n\.?\s*$",
            "",
            respuesta,
        ).strip()
        return f"{respuesta} En el nombre de Jesus. Amen.".strip()

    def limpiar_cierre_oracion_chat_consejero(texto: str, mensaje_usuario: str) -> str:
        respuesta = (texto or "").strip()
        if not respuesta or es_modo_chat_soporte:
            return respuesta
        if es_respuesta_oracion_chat_consejero(respuesta, mensaje_usuario):
            return respuesta

        cierres = [
            "En el nombre de Jesus. Amen.",
            "En el nombre de Jesús. Amén.",
            "En el nombre de Jesus. Amén.",
            "En el nombre de Jesús. Amen.",
        ]
        for cierre in cierres:
            respuesta = respuesta.replace(cierre, "").strip()
        respuesta = re.sub(r"(?i)[,;:\-]?\s*am(?:e|Ã©|é)n\.?$", "", respuesta).strip()
        respuesta = re.sub(r"(?i)[,;:\-]?\s*am(?:e|Ã©|é)n\.?$", "", respuesta).strip()
        respuesta = re.sub(r"\s{2,}", " ", respuesta).strip()
        return respuesta

    def normalizar_texto_chat_consejero(texto: str) -> str:
        base = unicodedata.normalize("NFKD", texto or "")
        sin_acentos = "".join(car for car in base if not unicodedata.combining(car))
        return re.sub(r"\s+", " ", sin_acentos).strip().lower()

    def variar_inicio_entiendo_chat_consejero(texto: str) -> str:
        respuesta = (texto or "").strip()
        if not respuesta or es_modo_chat_soporte:
            return respuesta

        match = re.match(
            r"^(?P<prefijo>[\s\"'¿¡\(\[\*_#>\-]*)(?P<lemma>entiendo)(?P<cola>\s+que\b)?",
            respuesta,
            re.IGNORECASE,
        )
        if not match:
            return respuesta

        indice_respuesta = sum(
            1 for rol, _, _ in historial_chat_consejero if rol == "assistant"
        )
        aperturas_con_que = (
            "Entiendo que",
            "Lamento que",
            "Comprendo que",
            "Veo que",
        )
        aperturas_simples = (
            "Entiendo",
            "Lamento",
            "Comprendo",
            "Veo",
        )
        reemplazo = (
            aperturas_con_que if match.group("cola") else aperturas_simples
        )[indice_respuesta % 4]
        if match.group("lemma").islower():
            reemplazo = reemplazo.lower()
        return f"{match.group('prefijo')}{reemplazo}{respuesta[match.end():]}"

    def obtener_nombre_usuario_chat_consejero() -> str:
        patrones = (
            r"\bme llamo\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'\-]{1,30})\b",
            r"\bsoy\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'\-]{1,30})\b",
            r"\bmi nombre es\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'\-]{1,30})\b",
        )
        for rol, mensaje, _ in reversed(historial_chat_consejero):
            if rol != "user":
                continue
            texto = (mensaje or "").strip()
            if not texto:
                continue
            for patron in patrones:
                match = re.search(patron, texto, re.IGNORECASE)
                if match:
                    nombre = match.group(1).strip()
                    return nombre[:1].upper() + nombre[1:].lower()
        return ""

    def suavizar_uso_nombre_chat_consejero(texto: str) -> str:
        respuesta = (texto or "").strip()
        if not respuesta or es_modo_chat_soporte:
            return respuesta

        nombre = obtener_nombre_usuario_chat_consejero()
        if not nombre:
            return respuesta

        patron = re.compile(
            rf"\b{re.escape(nombre)}\b(?!\s*\d)(?:\s*,)?",
            re.IGNORECASE,
        )
        coincidencias = list(patron.finditer(respuesta))
        if len(coincidencias) <= 1:
            return respuesta

        primera = coincidencias[0]
        prefijo = respuesta[:primera.end()]
        resto = respuesta[primera.end():]
        resto = patron.sub("", resto)
        respuesta = f"{prefijo}{resto}"
        respuesta = re.sub(r"\s{2,}", " ", respuesta).strip()
        respuesta = re.sub(r"\s+([,;:.!?])", r"\1", respuesta)
        respuesta = re.sub(r"([,;:]){2,}", r"\1", respuesta)
        respuesta = re.sub(r",\s*,", ", ", respuesta)
        return respuesta.strip()

    def limpiar_repeticiones_chat_consejero(texto: str) -> str:
        respuesta = (texto or "").strip()
        if not respuesta or es_modo_chat_soporte:
            return respuesta

        respuesta = re.sub(
            r"(?i)\bayudarte en este chat\b",
            "ayudarte ahora",
            respuesta,
        )
        respuesta = re.sub(
            r"(?i),?\s*si no puede ayudarte ahora,?\s*",
            " ",
            respuesta,
        )
        respuesta = re.sub(r"\s{2,}", " ", respuesta).strip()

        fragmentos = re.split(r"(?<=[.!?])\s+", respuesta)
        vistos = []
        filtrados = []
        for fragmento in fragmentos:
            fragmento_limpio = fragmento.strip()
            if not fragmento_limpio:
                continue
            clave = re.sub(
                r"[^a-z0-9]+",
                " ",
                normalizar_texto_chat_consejero(fragmento_limpio),
            ).strip()
            if len(clave) >= 18 and clave in vistos[-3:]:
                continue
            vistos.append(clave)
            filtrados.append(fragmento_limpio)

        respuesta = " ".join(filtrados).strip() or respuesta
        respuesta = re.sub(r"\s{2,}", " ", respuesta).strip()
        respuesta = re.sub(r"\s+([,;:.!?])", r"\1", respuesta)
        return respuesta.strip()

    def es_respuesta_oracion_chat_consejero(texto: str, mensaje_usuario: str) -> bool:
        del mensaje_usuario
        respuesta_original = limpiar_respuesta_chat_visible(texto or "").strip()
        if not respuesta_original:
            return False

        respuesta = normalizar_texto_chat_consejero(respuesta_original)
        respuesta_simple = respuesta.lstrip("*_#> -\n\r\t")
        inicios_oracion = (
            "senor",
            "padre",
            "oremos",
            "oracion:",
            "te pido",
            "te damos gracias",
            "venimos a ti",
            "ponemos en tus manos",
            "dios,",
            "jesus,",
        )
        if respuesta_simple.startswith(inicios_oracion):
            return True

        primeras_lineas = " ".join(
            linea.strip()
            for linea in respuesta_simple.splitlines()[:3]
            if linea.strip()
        )
        marcadores_oracion = [
            "senor",
            "padre",
            "te pido",
            "te pedimos",
            "te damos gracias",
            "venimos a ti",
            "ponemos en tus manos",
            "delante de ti",
            "haz tu voluntad",
            "escucha nuestra oracion",
        ]
        coincidencias = sum(1 for marcador in marcadores_oracion if marcador in primeras_lineas)
        return coincidencias >= 2

    def separar_primer_bloque_oracion_chat_consejero(texto: str) -> tuple[str, str]:
        respuesta = limpiar_respuesta_chat_visible(texto or "").strip()
        if not respuesta:
            return "", ""

        bloques = [
            bloque.strip()
            for bloque in re.split(r"\n\s*\n", respuesta)
            if bloque.strip()
        ]
        if len(bloques) < 2:
            return "", respuesta

        primer_bloque = bloques[0]
        if not es_respuesta_oracion_chat_consejero(primer_bloque, ""):
            return "", respuesta

        resto = "\n\n".join(bloques[1:]).strip()
        return primer_bloque, resto

    def recortar_solo_oracion_chat_consejero(texto: str) -> str:
        respuesta = limpiar_respuesta_chat_visible(texto or "").strip()
        if not respuesta:
            return ""

        indice_pregunta = None
        for patron in (
            r"(?i)\s+[Aa]hora\b",
            r"(?i)\s+[Dd]ime\b",
            r"(?i)\s+[Cc]uentame\b",
            r"(?i)\s+[Pp]odrias\b",
            r"(?i)\s+[Qq]ue aspecto\b",
            r"(?i)\s+[Qq]ue es lo que\b",
            r"(?i)\s+[Ee]n que\b",
            "\u00BF",
            r"\?",
        ):
            coincidencia = re.search(patron, respuesta)
            if not coincidencia:
                continue
            inicio = coincidencia.start()
            if inicio <= 0:
                continue
            if indice_pregunta is None or inicio < indice_pregunta:
                indice_pregunta = inicio

        patron_cierre = re.search(
            r"(?i)\ben el nombre de jes(?:u|Ãº)s\.?\s*am(?:e|Ã©)n\.?",
            respuesta,
        )
        if indice_pregunta is not None and (
            patron_cierre is None or indice_pregunta < patron_cierre.start()
        ):
            return respuesta[:indice_pregunta].rstrip(" ,;:-").strip()
        if patron_cierre:
            return respuesta[:patron_cierre.end()].strip()

        indice_corte = None
        for patron in (
            r"(?i)\s+[Aa]hora\b",
            r"(?i)\s+[Dd]ime\b",
            r"(?i)\s+[Cc]uentame\b",
            r"(?i)\s+[Pp]odrias\b",
            r"(?i)\s+[Qq]ue es lo que\b",
            r"(?i)\s+[Ee]n que\b",
            r"(?i)\s*¿",
            r"\?",
        ):
            coincidencia = re.search(patron, respuesta)
            if not coincidencia:
                continue
            inicio = coincidencia.start()
            if inicio <= 0:
                continue
            if indice_corte is None or inicio < indice_corte:
                indice_corte = inicio

        if indice_corte is None:
            return respuesta
        return respuesta[:indice_corte].rstrip(" ,;:-").strip()

    def limpiar_cierre_oracion_chat_consejero(texto: str, mensaje_usuario: str) -> str:
        respuesta = (texto or "").strip()
        if not respuesta or es_modo_chat_soporte:
            return respuesta
        if es_respuesta_oracion_chat_consejero(respuesta, mensaje_usuario):
            return respuesta

        cierres = [
            "En el nombre de Jesus. Amen.",
            "En el nombre de Jesús. Amén.",
            "En el nombre de Jesus. Amén.",
            "En el nombre de Jesús. Amen.",
            "En el nombre de Jesus amen.",
            "En el nombre de Jesús amen.",
        ]
        for cierre in cierres:
            respuesta = respuesta.replace(cierre, "").strip()
        respuesta = re.sub(
            r"(?i)[,;:\-]?\s*en el nombre de jes(?:u|ú)s\.?\s*amen\.?$",
            "",
            respuesta,
        ).strip()
        respuesta = re.sub(r"\s{2,}", " ", respuesta).strip()
        return respuesta

    def ejecutar_chat_consejero(e):
        nonlocal vista_resultado_completa, espera_chat_activa, animacion_espera_chat_id
        mensaje = tf_chat_consejero.value.strip()
        if not mensaje:
            mostrar_mensaje(page, textos_chat_activo["empty_message"])
            return

        historial_chat_consejero.append(("user", mensaje, hora_chat_actual()))
        actualizar_memoria_chat_consejero()
        tf_chat_consejero.value = ""
        pr.visible = False
        pr_comportamiento.visible = False
        pr_incredulo.visible = False
        pr_cristianos.visible = False
        pr_chat_consejero.visible = False
        espera_chat_activa = True
        animacion_espera_chat_id += 1
        identificador_espera = animacion_espera_chat_id
        page.run_task(animar_puntos_espera_chat, identificador_espera)
        fijar_estado_consulta(textos_chat_activo["status_generating"], "red", True, textos_chat_activo["send"])
        actualizar_resumen()
        actualizar_disposicion()
        page.update()
        page.run_task(desplazar_chat_al_final)

        instruccion_turno_chat = construir_instruccion_aceptacion_oracion_chat_consejero()
        resultado_ritmo_chat = "defer" if instruccion_turno_chat else "none"
        if not instruccion_turno_chat:
            instruccion_turno_chat = construir_instruccion_despues_de_amen_chat_consejero()
            resultado_ritmo_chat = "defer" if instruccion_turno_chat else "none"
        if not instruccion_turno_chat:
            instruccion_turno_chat = construir_instruccion_primer_problema_chat_consejero()
            resultado_ritmo_chat = "defer" if instruccion_turno_chat else "none"
        if not instruccion_turno_chat:
            instruccion_turno_chat, resultado_ritmo_chat = construir_instruccion_cierre_acompanamiento_chat_consejero()
        if not instruccion_turno_chat:
            instruccion_turno_chat, resultado_ritmo_chat = construir_instruccion_ritmica_chat_consejero()
        respuesta_directa_chat = construir_respuesta_aceptacion_oracion_chat_consejero()
        prompt = construir_prompt_chat_activo(instruccion_turno_chat)

        async def tarea():
            nonlocal vista_resultado_completa
            try:
                if respuesta_directa_chat:
                    respuesta = respuesta_directa_chat
                elif getattr(page, "pyodide", False):
                    respuesta = consultar_ia(prompt, lang_code, "question")
                else:
                    respuesta = await asyncio.to_thread(consultar_ia, prompt, lang_code, "question")
                respuesta = asegurar_cierre_oracion_chat_consejero(respuesta, mensaje)
                respuesta = limpiar_cierre_oracion_chat_consejero(respuesta, mensaje)
                respuesta = variar_inicio_entiendo_chat_consejero(respuesta)
                respuesta = suavizar_uso_nombre_chat_consejero(respuesta)
                respuesta = limpiar_repeticiones_chat_consejero(respuesta)
                registrar_ritmo_chat_consejero(resultado_ritmo_chat)
                detener_animacion_espera_chat()
                sincronizar_chat_consejero_visual()
                page.update()
                await desplazar_chat_al_final()
                await asyncio.sleep(0.05)
                await animar_respuesta_chat_consejero(respuesta)
            finally:
                detener_animacion_espera_chat()
                pr.visible = False
                pr_comportamiento.visible = False
                pr_incredulo.visible = False
                pr_cristianos.visible = False
                pr_chat_consejero.visible = False
                if result_md.value.strip():
                    vista_resultado_completa = True
                cerrar_consulta_con_estado(textos_chat_activo["status_ready"])
                actualizar_resumen()
                actualizar_disposicion()
                page.update()

        page.run_task(tarea)

    def ejecutar_trabajo_en_segundo_plano(trabajo_sync):
        if getattr(page, "pyodide", False):
            async def tarea_async():
                await asyncio.sleep(0)
                trabajo_sync()

            page.run_task(tarea_async)
            return
        page.run_thread(trabajo_sync)

    def lanzar_pregunta_rapida_chat(texto: str):
        tf_chat_consejero.value = texto
        ejecutar_chat_consejero(None)

    def ejecutar_consulta(e):
        nonlocal vista_resultado_completa, ultimo_prompt_estudio
        if dd_libro.value == no_selection and all(d.value == no_selection for d in especiales) and dd_tema_sugerido.value == "Ninguno":
            mostrar_mensaje(page, ui["msg_select_something"])
            return
        if dd_tipo.value == "Ninguno":
            mostrar_mensaje(page, ui["msg_select_study_type"])
            return
        if dd_tipo.value != "Solo versiculos" and dd_tamano.value == "Ninguno":
            mostrar_mensaje(page, ui["words"])
            return

        prompt = construir_prompt_estudio()
        ultimo_prompt_estudio = prompt
        pr.visible = True
        pr_comportamiento.visible = False
        pr_incredulo.visible = False
        pr_cristianos.visible = False
        pr_chat_consejero.visible = False
        asignar_resultado_markdown(generating_text)
        fijar_estado_consulta(ui["status_generating"], "red", True, texto_paciencia)
        actualizar_disposicion()
        page.update()

        def tarea():
            nonlocal vista_resultado_completa
            try:
                respuesta = consultar_ia(prompt, lang_code=lang_code, mode="study")
                asignar_resultado_markdown(reforzar_respuesta_si_no_respeta_longitud(respuesta, prompt, "study"), limpiar=True)
            finally:
                pr.visible = False
                pr_comportamiento.visible = False
                pr_incredulo.visible = False
                pr_cristianos.visible = False
                pr_chat_consejero.visible = False
                if result_md.value.strip():
                    vista_resultado_completa = True
                    if not result_md.value.strip().startswith("Error"):
                        panel_pasaje.visible = False
                        panel_filtros.visible = False
                cerrar_consulta_con_estado(ui["status_ready_study"])
                actualizar_disposicion()
                page.update()

        ejecutar_trabajo_en_segundo_plano(tarea)

    def ejecutar_consulta_comportamiento(e):
        nonlocal vista_resultado_completa, ultimo_prompt_estudio
        if dd_comportamiento.value == "Ninguno":
            mostrar_mensaje(page, textos_comportamiento["msg_select_situation"])
            return
        if dd_tamano_comportamiento.value == "Ninguno":
            mostrar_mensaje(page, ui["words"])
            return

        prompt = construir_prompt_comportamiento()
        ultimo_prompt_estudio = prompt
        pr.visible = False
        pr_comportamiento.visible = True
        pr_incredulo.visible = False
        pr_cristianos.visible = False
        pr_chat_consejero.visible = False
        asignar_resultado_markdown(generating_text)
        fijar_estado_consulta(textos_comportamiento["status_generating"], "red", True, textos_comportamiento["generate"])
        actualizar_disposicion()
        page.update()

        def tarea():
            nonlocal vista_resultado_completa
            try:
                respuesta = consultar_ia(prompt, lang_code=lang_code, mode="study")
                asignar_resultado_markdown(reforzar_respuesta_si_no_respeta_longitud(respuesta, prompt, "study"), limpiar=True)
            finally:
                pr.visible = False
                pr_comportamiento.visible = False
                pr_incredulo.visible = False
                pr_cristianos.visible = False
                pr_chat_consejero.visible = False
                if result_md.value.strip():
                    vista_resultado_completa = True
                cerrar_consulta_con_estado(textos_comportamiento["status_ready"])
                actualizar_disposicion()
                page.update()

        ejecutar_trabajo_en_segundo_plano(tarea)

    def ejecutar_consulta_cristianos(e):
        nonlocal vista_resultado_completa, ultimo_prompt_estudio
        if dd_cristianos.value == "Ninguno":
            mostrar_mensaje(page, textos_cristianos["msg_select_question"])
            return
        if dd_tamano_cristianos.value == "Ninguno":
            mostrar_mensaje(page, ui["words"])
            return

        prompt = construir_prompt_cristianos()
        ultimo_prompt_estudio = prompt
        pr.visible = False
        pr_comportamiento.visible = False
        pr_incredulo.visible = False
        pr_cristianos.visible = True
        pr_chat_consejero.visible = False
        asignar_resultado_markdown(generating_text)
        fijar_estado_consulta(textos_cristianos["status_generating"], "red", True, textos_cristianos["generate"])
        actualizar_disposicion()
        page.update()

        def tarea():
            nonlocal vista_resultado_completa
            try:
                respuesta = consultar_ia(prompt, lang_code=lang_code, mode="study")
                asignar_resultado_markdown(reforzar_respuesta_si_no_respeta_longitud(respuesta, prompt, "study"), limpiar=True)
            finally:
                pr.visible = False
                pr_comportamiento.visible = False
                pr_incredulo.visible = False
                pr_cristianos.visible = False
                pr_chat_consejero.visible = False
                if result_md.value.strip():
                    vista_resultado_completa = True
                cerrar_consulta_con_estado(textos_cristianos["status_ready"])
                actualizar_disposicion()
                page.update()

        ejecutar_trabajo_en_segundo_plano(tarea)

    def ejecutar_consulta_incredulo(e):
        nonlocal vista_resultado_completa, ultimo_prompt_estudio
        if dd_incredulo.value == "Ninguno":
            mostrar_mensaje(page, textos_incredulo["msg_select_question"])
            return
        if dd_tamano_incredulo.value == "Ninguno":
            mostrar_mensaje(page, ui["words"])
            return

        prompt = construir_prompt_incredulo()
        ultimo_prompt_estudio = prompt
        pr.visible = False
        pr_comportamiento.visible = False
        pr_incredulo.visible = True
        pr_cristianos.visible = False
        pr_chat_consejero.visible = False
        asignar_resultado_markdown(generating_text)
        fijar_estado_consulta(textos_incredulo["status_generating"], "red", True, textos_incredulo["generate"])
        actualizar_disposicion()
        page.update()

        def tarea():
            nonlocal vista_resultado_completa
            try:
                respuesta = consultar_ia(prompt, lang_code=lang_code, mode="study")
                asignar_resultado_markdown(reforzar_respuesta_si_no_respeta_longitud(respuesta, prompt, "study"), limpiar=True)
            finally:
                pr.visible = False
                pr_comportamiento.visible = False
                pr_incredulo.visible = False
                pr_cristianos.visible = False
                pr_chat_consejero.visible = False
                if result_md.value.strip():
                    vista_resultado_completa = True
                cerrar_consulta_con_estado(textos_incredulo["status_ready"])
                actualizar_disposicion()
                page.update()

        ejecutar_trabajo_en_segundo_plano(tarea)

    def repetir_ultima_consulta(e):
        if not ultimo_prompt_estudio:
            mostrar_mensaje(page, ui["msg_no_previous"])
            return

        pr.visible = True
        pr_comportamiento.visible = False
        pr_incredulo.visible = False
        pr_cristianos.visible = False
        pr_chat_consejero.visible = False
        asignar_resultado_markdown(repeating_text)
        fijar_estado_consulta(ui["status_repeat"], "red", True, texto_paciencia)
        actualizar_disposicion()
        page.update()

        def tarea():
            try:
                respuesta = consultar_ia(ultimo_prompt_estudio, lang_code=lang_code, mode="study")
                asignar_resultado_markdown(reforzar_respuesta_si_no_respeta_longitud(respuesta, ultimo_prompt_estudio, "study"), limpiar=True)
            finally:
                pr.visible = False
                pr_comportamiento.visible = False
                pr_incredulo.visible = False
                pr_cristianos.visible = False
                pr_chat_consejero.visible = False
                cerrar_consulta_con_estado(ui["status_repeat_ready"])
                actualizar_disposicion()
                page.update()

        ejecutar_trabajo_en_segundo_plano(tarea)

    def preguntar_ia(e):
        pregunta = tf_pregunta.value.strip()
        if not pregunta:
            mostrar_mensaje(page, ui["msg_write_question"])
            return

        contexto_resultado = limpiar_texto_generado_ia(result_md.value.strip())
        if contexto_resultado:
            bloque_contexto = (
                f"Usa el siguiente resultado previo como contexto principal para responder la pregunta relacionada:\n\n{contexto_resultado}\n\n"
                if lang_code == "es" else
                (
                    f"Fes servir el resultat previ següent com a context principal per respondre la pregunta relacionada:\n\n{contexto_resultado}\n\n"
                    if lang_code == "ca" else
                    (
                        f"Utilise le résultat précédent suivant comme contexte principal pour répondre à la question liée :\n\n{contexto_resultado}\n\n"
                        if lang_code == "fr" else
                        f"Use the following previous result as the main context to answer the related question:\n\n{contexto_resultado}\n\n"
                    )
                )
            )
        else:
            bloque_contexto = ""

        if lang_code == "es":
            prompt = (
                "Responde desde una perspectiva cristiana evangélica, con base bíblica, tono claro, pastoral y fiel a la Escritura. "
                "Prioriza exactitud bíblica, claridad, reverencia y utilidad espiritual. "
                "Responde en Markdown, con apartados breves si ayudan. Cuida la presentación visual del texto: usa un título bonito y reverente y, si encaja, algunos símbolos cristianos con moderación, evitando caracteres raros o iconos que se vean mal. "
                "Incluye referencias bíblicas concretas cuando sea apropiado. "
                "No inventes versículos ni afirmaciones históricas. "
                "La respuesta final debe estar escrita en español de España. "
                "Al final indica, en mayúsculas, cursiva y negrita, que el contenido ha sido generado por IA y puede contener errores. "
                f"{bloque_contexto}"
                f"Pregunta: {pregunta}"
            )
        elif lang_code == "ca":
            prompt = (
                "Respon des d'una perspectiva cristiana evangèlica, amb base bíblica, to clar, pastoral i fidel a l'Escriptura. "
                "Prioritza exactitud bíblica, claredat, reverència i utilitat espiritual. "
                "Respon en Markdown, amb apartats breus si ajuden. Cuida la presentació visual del text: fes servir un títol bonic i reverent i, si encaixa, alguns símbols cristians amb moderació, evitant caràcters estranys o icones que es vegin malament. "
                "Inclou referències bíbliques concretes quan sigui apropiat. "
                "No inventis versicles ni afirmacions històriques. "
                "La resposta final ha d'estar escrita en català. "
                "Al final indica, en majúscules, cursiva i negreta, que el contingut ha estat generat per IA i pot contenir errors. "
                f"{bloque_contexto}"
                f"Pregunta: {pregunta}"
            )
        elif lang_code == "fr":
            prompt = (
                "Réponds depuis une perspective chrétienne évangélique, avec une base biblique, un ton clair, pastoral et fidèle à l'Écriture. "
                "Priorise l'exactitude biblique, la clarté, la révérence et l'utilité spirituelle. "
                "Réponds en Markdown, avec de courtes sections si cela aide. Soigne la présentation visuelle du texte : utilise un beau titre révérencieux et, si cela convient, quelques symboles chrétiens avec modération, en évitant les caractères étranges ou les icônes qui s'affichent mal. "
                "Inclue des références bibliques concrètes lorsque c'est approprié. "
                "N'invente ni versets ni affirmations historiques. "
                "La réponse finale doit être rédigée en français. "
                "À la fin, indique en majuscules, italique et gras que le contenu a été généré par IA et peut contenir des erreurs. "
                f"{bloque_contexto}"
                f"Question: {pregunta}"
            )
        else:
            prompt = (
                "Answer from an evangelical Christian perspective with a biblical foundation, a clear pastoral tone, and faithfulness to Scripture. "
                "Prioritize biblical accuracy, clarity, reverence, and spiritual usefulness. "
                "Respond in Markdown, using short sections when helpful. Pay attention to the visual presentation of the text: use a beautiful reverent title and, when appropriate, a few Christian symbols in moderation while avoiding unusual characters or icons that may render badly. "
                "Include concrete Bible references when appropriate. "
                "Do not invent verses or historical claims. "
                "The final response must be written in English. "
                "At the end, state in uppercase, italic, and bold that the content was generated by AI and may contain errors. "
                f"{bloque_contexto}"
                f"Question: {pregunta}"
            )

        pr.visible = True
        pr_comportamiento.visible = False
        pr_incredulo.visible = False
        pr_cristianos.visible = False
        pr_chat_consejero.visible = False
        asignar_resultado_markdown(asking_text)
        fijar_estado_consulta(ui["status_asking"], "red", True)
        actualizar_disposicion()
        page.update()

        def tarea():
            try:
                respuesta = consultar_ia(prompt, lang_code=lang_code, mode="question")
                asignar_resultado_markdown(reforzar_respuesta_si_no_respeta_longitud(respuesta, prompt, "question"), limpiar=True)
            finally:
                pr.visible = False
                pr_comportamiento.visible = False
                pr_incredulo.visible = False
                pr_cristianos.visible = False
                pr_chat_consejero.visible = False
                cerrar_consulta_con_estado(ui["status_answer_ready"])
                actualizar_disposicion()
                page.update()

        ejecutar_trabajo_en_segundo_plano(tarea)

    def mostrar_resultado(e=None):
        nonlocal vista_resultado_completa
        if not result_md.value.strip():
            mostrar_mensaje(page, ui["msg_no_content"])
            return
        vista_resultado_completa = True
        panel_pasaje.visible = False
        panel_filtros.visible = False
        actualizar_disposicion()
        page.update()

    def volver_a_filtros(e=None):
        nonlocal vista_resultado_completa
        vista_resultado_completa = False
        panel_pasaje.visible = True
        panel_filtros.visible = True
        actualizar_disposicion()
        page.update()

    def volver_a_pasaje(e=None):
        pasos_interactuados["end"] = False
        dd_fin.value = None
        manejar_bloqueos()
        refrescar_por_cambio()
        try:
            page.scroll_to(scroll_key="panel_pasaje", duration=300)
        except Exception:
            pass

    def volver_a_filtros_estudio(e=None):
        mostrar_filtros_por_vuelta["ok"] = True
        actualizar_disposicion()
        try:
            page.scroll_to(scroll_key="panel_filtros", duration=300)
        except Exception:
            pass
        page.update()

    def volver_desde_generacion(e=None):
        filtro_activo = next((d for d in especiales if d.value != no_selection), None) is not None or dd_tema_sugerido.value != "Ninguno"
        if filtro_activo:
            volver_a_filtros_estudio(e)
        else:
            volver_a_pasaje(e)

    def limpiar_seleccion(e):
        nonlocal vista_resultado_completa, memoria_chat_consejero
        if es_modo_chat:
            tf_chat_consejero.value = ""
            historial_chat_consejero.clear()
            memoria_chat_consejero = ""
            reiniciar_ritmo_chat_consejero()
            result_md.value = ""
            asegurar_saludo_inicial_chat()
            pr.visible = False
            pr_comportamiento.visible = False
            pr_incredulo.visible = False
            pr_cristianos.visible = False
            pr_chat_consejero.visible = False
            vista_resultado_completa = False
            texto_estado.value = ui["status_ready"]
            texto_estado.color = "#2E7D32"
            actualizar_resumen()
            actualizar_disposicion()
            page.update()
            return

        reiniciar_pasos()
        dd_biblia.value = "Ninguna"
        dd_orden_libros.value = "Orden biblico"
        dd_libro.value = no_selection
        actualizar_opciones_libros()

        for d in especiales:
            d.value = no_selection
            d.disabled = False

        dd_libro.disabled = False
        dd_cap.disabled = False
        dd_ini.disabled = False
        dd_fin.disabled = False
        dd_tipo.value = "Ninguno"
        dd_tamano.value = "Ninguno"
        dd_comportamiento.value = "Ninguno"
        dd_tamano_comportamiento.value = "Ninguno"
        dd_incredulo.value = "Ninguno"
        dd_tamano_incredulo.value = "Ninguno"
        dd_cristianos.value = "Ninguno"
        dd_tamano_cristianos.value = "Ninguno"
        dd_tema_sugerido.value = "Ninguno"
        tf_pregunta.value = ""
        tf_chat_consejero.value = ""
        historial_chat_consejero.clear()
        memoria_chat_consejero = ""
        reiniciar_ritmo_chat_consejero()
        result_md.value = ""
        asegurar_saludo_inicial_chat()
        pr.visible = False
        pr_comportamiento.visible = False
        pr_incredulo.visible = False
        pr_cristianos.visible = False
        pr_chat_consejero.visible = False
        vista_resultado_completa = False
        panel_pasaje.visible = True
        panel_filtros.visible = True
        texto_estado.value = ui["status_ready"]
        texto_estado.color = "#2E7D32"
        manejar_bloqueos()
        actualizar_disposicion()
        page.update()

    def limpiar_filtros(e):
        nonlocal memoria_chat_consejero
        reiniciar_pasos()
        dd_biblia.value = "Ninguna"
        dd_orden_libros.value = "Orden biblico"
        dd_libro.value = no_selection
        actualizar_opciones_libros()

        for d in especiales:
            d.value = no_selection
            d.disabled = False

        dd_libro.disabled = False
        dd_cap.disabled = False
        dd_ini.disabled = False
        dd_fin.disabled = False
        dd_tema_sugerido.value = "Ninguno"
        dd_tipo.value = "Ninguno"
        dd_tamano.value = "Ninguno"
        dd_comportamiento.value = "Ninguno"
        dd_tamano_comportamiento.value = "Ninguno"
        dd_incredulo.value = "Ninguno"
        dd_tamano_incredulo.value = "Ninguno"
        dd_cristianos.value = "Ninguno"
        dd_tamano_cristianos.value = "Ninguno"
        tf_chat_consejero.value = ""
        historial_chat_consejero.clear()
        memoria_chat_consejero = ""
        reiniciar_ritmo_chat_consejero()
        asegurar_saludo_inicial_chat()
        pr_comportamiento.visible = False
        pr_incredulo.visible = False
        pr_cristianos.visible = False
        pr_chat_consejero.visible = False
        manejar_bloqueos()
        refrescar_por_cambio()

    def elegir_aleatorio_para(dropdown):
        for d in especiales:
            d.value = no_selection
            d.disabled = False

        dd_libro.value = no_selection
        dd_libro.disabled = False
        dd_cap.disabled = False
        dd_ini.disabled = False
        dd_fin.disabled = False

        opciones_validas = [opt.key for opt in dropdown.options if opt.key != no_selection]
        if not opciones_validas:
            mostrar_mensaje(page, ui["msg_no_random_options"])
            return

        dropdown.value = random.choice(opciones_validas)
        manejar_bloqueos()
        refrescar_por_cambio()
        llevar_a_generacion_si_corresponde()
        mostrar_mensaje(page, ui["msg_random_selection"].format(label=dropdown.label))

    def reiniciar_pasos():
        nonlocal ultimo_paso_enfocado
        for paso in pasos_interactuados:
            pasos_interactuados[paso] = False
        ultimo_paso_enfocado = None
        mostrar_filtros_por_vuelta["ok"] = False

    def marcar_paso(nombre_paso, accion):
        def _controlador(e=None):
            pasos_interactuados[nombre_paso] = True
            accion(e)
        return _controlador

    dd_biblia.on_change = marcar_paso("version", cambiar_version_pasaje)
    dd_biblia.on_select = marcar_paso("version", cambiar_version_pasaje)
    dd_orden_libros.on_change = marcar_paso("book_order", actualizar_opciones_libros)
    dd_orden_libros.on_select = marcar_paso("book_order", actualizar_opciones_libros)
    dd_libro.on_change = marcar_paso("book", actualizar_caps)
    dd_libro.on_select = marcar_paso("book", actualizar_caps)
    dd_cap.on_change = marcar_paso("chapter", cambiar_capitulo_pasaje)
    dd_cap.on_select = marcar_paso("chapter", cambiar_capitulo_pasaje)
    dd_ini.on_change = marcar_paso("start", cambiar_version_pasaje)
    dd_ini.on_select = marcar_paso("start", cambiar_version_pasaje)
    dd_fin.on_change = marcar_paso("end", cambiar_version_pasaje)
    dd_fin.on_select = marcar_paso("end", cambiar_version_pasaje)
    dd_tamano.on_change = marcar_paso("words", refrescar_por_cambio)
    dd_tamano.on_select = marcar_paso("words", refrescar_por_cambio)
    dd_tipo.on_change = marcar_paso("study_type", refrescar_por_cambio)
    dd_tipo.on_select = marcar_paso("study_type", refrescar_por_cambio)
    dd_comportamiento.on_change = refrescar_por_cambio
    dd_comportamiento.on_select = refrescar_por_cambio
    dd_tamano_comportamiento.on_change = refrescar_por_cambio
    dd_tamano_comportamiento.on_select = refrescar_por_cambio
    dd_incredulo.on_change = refrescar_por_cambio
    dd_incredulo.on_select = refrescar_por_cambio
    dd_tamano_incredulo.on_change = refrescar_por_cambio
    dd_tamano_incredulo.on_select = refrescar_por_cambio
    dd_cristianos.on_change = refrescar_por_cambio
    dd_cristianos.on_select = refrescar_por_cambio
    dd_tamano_cristianos.on_change = refrescar_por_cambio
    dd_tamano_cristianos.on_select = refrescar_por_cambio
    dd_hombre.on_change = manejar_bloqueos
    dd_hombre.on_select = manejar_bloqueos
    dd_mujer.on_change = manejar_bloqueos
    dd_mujer.on_select = manejar_bloqueos
    dd_grupo.on_change = manejar_bloqueos
    dd_grupo.on_select = manejar_bloqueos
    dd_pueblo.on_change = manejar_bloqueos
    dd_pueblo.on_select = manejar_bloqueos
    dd_pais.on_change = manejar_bloqueos
    dd_pais.on_select = manejar_bloqueos
    dd_religion.on_change = manejar_bloqueos
    dd_religion.on_select = manejar_bloqueos
    dd_tema_sugerido.on_change = aplicar_desde_desplegable_tema
    dd_tema_sugerido.on_select = aplicar_desde_desplegable_tema
    tf_chat_consejero.on_submit = ejecutar_chat_consejero
    actualizar_opciones_libros()
    manejar_bloqueos()
    asegurar_saludo_inicial_chat()

    estilo_boton_rojo = ft.ButtonStyle(
        color=theme["primary_text"],
        bgcolor=theme["primary"],
        side=ft.BorderSide(4, theme["border"]),
        shape=ft.RoundedRectangleBorder(radius=14),
    )
    estilo_boton_amarillo = ft.ButtonStyle(
        color=theme["secondary_text"],
        bgcolor=theme["secondary"],
        side=ft.BorderSide(4, theme["border"]),
        shape=ft.RoundedRectangleBorder(radius=14),
    )
    usar_boton_generar_rojo = lang_code in {"es", "ca"}
    estilo_boton_generar_resultado = estilo_boton_rojo if usar_boton_generar_rojo else estilo_boton_amarillo
    color_boton_generar_resultado = theme["primary_text"] if usar_boton_generar_rojo else theme["secondary_text"]

    def crear_boton_aleatorio_filtro(dropdown):
        return ft.ElevatedButton(
            ui["random"],
            icon=ft.Icons.CASINO,
            on_click=lambda e, control=dropdown: elegir_aleatorio_para(control),
            style=ft.ButtonStyle(
                color=theme["secondary_text"],
                bgcolor=theme["secondary"],
                side=ft.BorderSide(3, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            height=48,
        )

    botones_aleatorios = {
        dd_hombre: crear_boton_aleatorio_filtro(dd_hombre),
        dd_mujer: crear_boton_aleatorio_filtro(dd_mujer),
        dd_grupo: crear_boton_aleatorio_filtro(dd_grupo),
        dd_pueblo: crear_boton_aleatorio_filtro(dd_pueblo),
        dd_pais: crear_boton_aleatorio_filtro(dd_pais),
        dd_religion: crear_boton_aleatorio_filtro(dd_religion),
        dd_tema_sugerido: crear_boton_aleatorio_filtro(dd_tema_sugerido),
    }

    texto_paciencia = {
        "es": "LA PACIENCIA ES UNA VIRTUD",
        "ca": "LA PACIÈNCIA ÉS UNA VIRTUT",
        "fr": "LA PATIENCE EST UNE VERTU",
        "en": "PATIENCE IS A VIRTUE",
    }.get(lang_code, "LA PACIENCIA ES UNA VIRTUD")

    def contenido_boton_generar(texto, icono, color_texto=None):
        color_contenido = color_texto or theme["primary_text"]
        return ft.Row(
            [
                ft.Icon(icono, size=20, color=color_contenido),
                ft.Text(texto, weight=ft.FontWeight.W_700, color=color_contenido, text_align=ft.TextAlign.CENTER),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
        )

    def contenido_boton_pdf(en_proceso=False):
        return contenido_boton_generar(
            ui["generating_pdf"] if en_proceso else ui["generate_pdf"],
            ft.Icons.HOURGLASS_EMPTY if en_proceso else ft.Icons.PICTURE_AS_PDF,
            theme["secondary_text"],
        )

    def actualizar_boton_pdf(en_proceso=False):
        btn_generar_pdf.content = contenido_boton_pdf(en_proceso)
        btn_generar_pdf.disabled = en_proceso

    btn_generar = ft.ElevatedButton(
        content=contenido_boton_generar(ui["generate"], ft.Icons.AUTO_AWESOME, color_boton_generar_resultado),
        on_click=ejecutar_consulta,
        style=estilo_boton_generar_resultado,
        height=56,
        expand=True,
    )
    btn_generar_comportamiento = ft.ElevatedButton(
        content=contenido_boton_generar(textos_comportamiento["generate"], ft.Icons.AUTO_AWESOME),
        on_click=ejecutar_consulta_comportamiento,
        style=estilo_boton_rojo,
        height=56,
        expand=True,
    )
    btn_generar_incredulo = ft.ElevatedButton(
        content=contenido_boton_generar(textos_incredulo["generate"], ft.Icons.AUTO_AWESOME),
        on_click=ejecutar_consulta_incredulo,
        style=estilo_boton_rojo,
        height=56,
        expand=True,
    )
    btn_generar_cristianos = ft.ElevatedButton(
        content=contenido_boton_generar(textos_cristianos["generate"], ft.Icons.AUTO_AWESOME),
        on_click=ejecutar_consulta_cristianos,
        style=estilo_boton_rojo,
        height=56,
        expand=True,
    )
    btn_enviar_chat_consejero = ft.IconButton(
        icon=ft.Icons.SEND_ROUNDED,
        icon_color=theme["primary_text"],
        bgcolor=theme["primary"],
        tooltip=textos_chat_activo["send"],
        on_click=ejecutar_chat_consejero,
        icon_size=22,
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=14,
        ),
    )
    icono_barra_chat = ft.Icon(ft.Icons.SENTIMENT_SATISFIED_ALT_OUTLINED, color=theme["muted"], size=24)
    btn_preguntar = ft.ElevatedButton(
        ui["ask"],
        on_click=preguntar_ia,
        style=estilo_boton_amarillo,
        height=48,
        expand=True,
    )
    btn_copiar_resultado = ft.ElevatedButton(
        ui["copy_result"],
        icon=ft.Icons.CONTENT_COPY,
        on_click=copiar_resultado,
        style=estilo_boton_rojo,
        height=56,
        expand=True,
    )
    btn_generar_pdf = ft.ElevatedButton(
        content=contenido_boton_pdf(False),
        on_click=lambda e: page.run_task(generar_pdf_resultado_async),
        style=estilo_boton_amarillo,
        height=56,
        expand=True,
        visible=not page.web,
    )
    btn_limpiar = ft.ElevatedButton(
        ui["clear_result"],
        icon=ft.Icons.CLEAR,
        on_click=limpiar_seleccion,
        style=estilo_boton_rojo,
        height=56,
        expand=True,
    )
    btn_volver_inicio_resultado = ft.ElevatedButton(
        back_start_label,
        icon=ft.Icons.HOME,
        on_click=(lambda e: on_volver_inicio()) if on_volver_inicio is not None else None,
        style=estilo_boton_amarillo,
        height=56,
        expand=True,
        visible=on_volver_inicio is not None,
    )
    btn_limpiar_filtros = ft.ElevatedButton(
        ui["clear_filters"],
        icon=ft.Icons.FILTER_ALT_OFF,
        on_click=limpiar_filtros,
        style=estilo_boton_rojo,
        height=56,
        expand=True,
    )
    btn_volver_contextual = ft.ElevatedButton(
        back_step_label,
        icon=ft.Icons.ARROW_BACK,
        on_click=volver_desde_generacion,
        style=estilo_boton_amarillo,
        height=56,
        expand=True,
        visible=False,
    )
    btn_volver_inicio_pasaje = ft.ElevatedButton(
        back_start_label,
        icon=ft.Icons.ARROW_BACK,
        on_click=(lambda e: on_volver_inicio()) if on_volver_inicio is not None else None,
        style=estilo_boton_amarillo,
        height=48,
        visible=inicio_preferido == "biblia" and on_volver_inicio is not None,
    )
    btn_volver_inicio_filtros = ft.ElevatedButton(
        back_start_label,
        icon=ft.Icons.ARROW_BACK,
        on_click=(lambda e: on_volver_inicio()) if on_volver_inicio is not None else None,
        style=estilo_boton_amarillo,
        height=48,
        visible=inicio_preferido == "filtros" and on_volver_inicio is not None,
    )
    btn_volver_inicio_comportamiento = ft.ElevatedButton(
        back_start_label,
        icon=ft.Icons.ARROW_BACK,
        on_click=(lambda e: on_volver_inicio()) if on_volver_inicio is not None else None,
        style=estilo_boton_amarillo,
        height=48,
        visible=inicio_preferido == "comportamiento" and on_volver_inicio is not None,
    )
    btn_volver_inicio_incredulo = ft.ElevatedButton(
        back_start_label,
        icon=ft.Icons.ARROW_BACK,
        on_click=(lambda e: on_volver_inicio()) if on_volver_inicio is not None else None,
        style=estilo_boton_amarillo,
        height=48,
        visible=inicio_preferido == "incredulo" and on_volver_inicio is not None,
    )
    btn_volver_inicio_cristianos = ft.ElevatedButton(
        back_start_label,
        icon=ft.Icons.ARROW_BACK,
        on_click=(lambda e: on_volver_inicio()) if on_volver_inicio is not None else None,
        style=estilo_boton_amarillo,
        height=48,
        visible=inicio_preferido == "cristianos" and on_volver_inicio is not None,
    )
    btn_volver_inicio_chat_consejero = ft.ElevatedButton(
        back_start_label,
        icon=ft.Icons.ARROW_BACK,
        on_click=(lambda e: on_volver_inicio()) if on_volver_inicio is not None else None,
        style=estilo_boton_amarillo,
        height=48,
        visible=es_modo_chat and on_volver_inicio is not None,
    )
    btn_atras_chat_consejero = ft.IconButton(
        icon=ft.Icons.ARROW_BACK,
        icon_color=theme["primary_text"],
        bgcolor=theme["primary"],
        on_click=(lambda e: on_volver_inicio()) if on_volver_inicio is not None else None,
        style=ft.ButtonStyle(shape=ft.CircleBorder(), padding=12),
        visible=on_volver_inicio is not None,
    )
    titulo_pasaje = ft.Text(ui["passage"], weight="bold", size=18, color=theme["primary"])
    cabecera_pasaje = ft.Container()
    titulo_filtros = ft.Text(ui["search_filters"], weight="bold", size=18, color=theme["primary"])
    cabecera_filtros = ft.Container()
    titulo_comportamiento = ft.Text(textos_comportamiento["title"], weight="bold", size=18, color=theme["primary"])
    cabecera_comportamiento = ft.Container()
    titulo_incredulo = ft.Text(textos_incredulo["title"], weight="bold", size=18, color=theme["primary"])
    cabecera_incredulo = ft.Container()
    titulo_cristianos = ft.Text(textos_cristianos["title"], weight="bold", size=18, color=theme["primary"])
    cabecera_cristianos = ft.Container()
    titulo_chat_consejero = ft.Text(textos_chat_activo["title"], weight="bold", size=18, color=theme["primary"])
    cabecera_chat_consejero = ft.Container()
    avatar_chat_consejero = ft.Container(
        width=48,
        height=48,
        bgcolor=theme["secondary"],
        border=ft.border.all(3, theme["primary"]),
        border_radius=24,
        content=ft.Icon(ft.Icons.HELP_OUTLINE if es_modo_chat_soporte else ft.Icons.FORUM_ROUNDED, color=theme["secondary_text"], size=24),
        alignment=ft.Alignment(0, 0),
    )
    titulo_resultado = ft.Text(ui["result"], size=18, weight="bold", color=theme["primary"])
    cabecera_resultado = ft.Container()
    fila_pregunta_resultado = ft.Container(visible=False)
    fila_acciones_resultado = ft.Container(visible=False)

    def pantalla_estrecha_actual():
        ancho = page.width or getattr(getattr(page, "window", None), "width", 0) or 0
        return ancho == 0 or ancho < 950

    def pantalla_movil_actual():
        ancho = page.width or getattr(getattr(page, "window", None), "width", 0) or 0
        return ancho == 0 or ancho < 520

    def actualizar_layout_responsive():
        estrecha = pantalla_estrecha_actual()
        movil = pantalla_movil_actual()
        page.padding = 8 if movil else (12 if estrecha else 18)
        contenido_pantalla.padding = 10 if movil else (12 if estrecha else 14)
        contenido_pantalla.border_radius = 12 if movil else 16
        marco_principal.padding = 3 if movil else 6
        marco_principal.border = ft.border.all(6 if movil else 7, theme["primary"])
        marco_principal.border_radius = 18 if movil else 26

        contenedor_pasaje.content = (
            ft.Column([dd_cap, dd_ini, dd_fin], spacing=8)
            if estrecha
            else ft.Row([dd_cap, dd_ini, dd_fin], spacing=8)
        )

        for dropdown in [dd_hombre, dd_mujer, dd_grupo, dd_pueblo, dd_pais, dd_religion]:
            contenedores_especiales[dropdown].content = (
                ft.Column([dropdown, botones_aleatorios[dropdown]], spacing=8)
                if estrecha
                else ft.Row(
                    [dropdown, botones_aleatorios[dropdown]],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )

        contenedor_tema_sugerido.content = (
            ft.Column([dd_tema_sugerido, botones_aleatorios[dd_tema_sugerido]], spacing=8)
            if estrecha
            else ft.Row(
                [dd_tema_sugerido, botones_aleatorios[dd_tema_sugerido]],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

        contenedor_tipo.expand = False
        contenedor_tamano.expand = False
        contenedor_tipo_tamano.content = ft.Column(
            [contenedor_tipo, contenedor_tamano],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        cabecera_pasaje.content = (
            ft.Column([titulo_pasaje, btn_volver_inicio_pasaje], spacing=10)
            if estrecha and btn_volver_inicio_pasaje.visible
            else (
                ft.Row(
                    [titulo_pasaje, btn_volver_inicio_pasaje],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                if btn_volver_inicio_pasaje.visible
                else titulo_pasaje
            )
        )

        cabecera_filtros.content = (
            ft.Column(
                [titulo_filtros, btn_volver_inicio_filtros, btn_limpiar_filtros],
                spacing=10,
            )
            if estrecha
            else ft.Row(
                [titulo_filtros, btn_volver_inicio_filtros, btn_limpiar_filtros],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

        cabecera_comportamiento.content = (
            ft.Column([titulo_comportamiento, btn_volver_inicio_comportamiento], spacing=10)
            if estrecha and btn_volver_inicio_comportamiento.visible
            else (
                ft.Row(
                    [titulo_comportamiento, btn_volver_inicio_comportamiento],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                if btn_volver_inicio_comportamiento.visible
                else titulo_comportamiento
            )
        )

        cabecera_incredulo.content = (
            ft.Column([titulo_incredulo, btn_volver_inicio_incredulo], spacing=10)
            if estrecha and btn_volver_inicio_incredulo.visible
            else (
                ft.Row(
                    [titulo_incredulo, btn_volver_inicio_incredulo],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                if btn_volver_inicio_incredulo.visible
                else titulo_incredulo
            )
        )

        cabecera_cristianos.content = (
            ft.Column([titulo_cristianos, btn_volver_inicio_cristianos], spacing=10)
            if estrecha and btn_volver_inicio_cristianos.visible
            else (
                ft.Row(
                    [titulo_cristianos, btn_volver_inicio_cristianos],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                if btn_volver_inicio_cristianos.visible
                else titulo_cristianos
            )
        )

        cabecera_chat_consejero.content = ft.Container(
            content=ft.Row(
                [
                    btn_atras_chat_consejero,
                    avatar_chat_consejero,
                    ft.Column(
                        [
                            ft.Text(
                                textos_chat_activo["assistant"],
                                size=22 if not estrecha else (17 if movil else 19),
                                weight=ft.FontWeight.W_700,
                                color=theme["primary_text"],
                            ),
                            ft.Text(
                                textos_chat_activo["header_status"],
                                size=12,
                                color=theme["primary_text"],
                                visible=es_modo_chat_soporte,
                            ),
                        ],
                        spacing=2,
                        tight=True,
                        expand=True,
                    ),
                ],
                spacing=8 if movil else 12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10 if movil else 12, vertical=10),
            bgcolor=theme["primary"],
            border_radius=ft.border_radius.only(top_left=18, top_right=18, bottom_left=12, bottom_right=12),
            border=ft.border.all(3, theme["border"]),
        )
        avatar_chat_consejero.width = 42 if movil else 48
        avatar_chat_consejero.height = 42 if movil else 48
        avatar_chat_consejero.border_radius = 21 if movil else 24
        icono_barra_chat.visible = not movil
        tf_chat_consejero.content_padding = ft.padding.symmetric(horizontal=12 if movil else 16, vertical=12 if movil else 14)
        btn_enviar_chat_consejero.style = ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=10 if movil else 14,
        )
        caja_chat_consejero.padding = ft.padding.symmetric(horizontal=8 if movil else 12, vertical=10 if movil else 14)
        barra_chat_consejero.padding = ft.padding.symmetric(horizontal=8 if movil else 10, vertical=8)
        barra_chat_consejero.content = ft.Row(
            [icono_barra_chat, tf_chat_consejero, btn_enviar_chat_consejero],
            spacing=8 if movil else 10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        cabecera_resultado.content = (
            ft.Column(
                [titulo_resultado, texto_consulta_resultado],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            )
            if estrecha
            else ft.Row(
                [
                    titulo_resultado,
                    ft.Container(
                        content=texto_consulta_resultado,
                        expand=True,
                        alignment=ft.Alignment(1, 0),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

        fila_pregunta_resultado.content = (
            ft.Container(
                content=ft.Column(
                    [
                        tf_pregunta,
                        ft.Row(
                            [btn_preguntar, btn_borrar_pregunta],
                            spacing=10,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                padding=ft.padding.symmetric(horizontal=2),
            )
            if estrecha
            else ft.Row(
                [tf_pregunta, btn_preguntar, btn_borrar_pregunta],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

        fila_acciones_resultado.content = (
            ft.Container(
                content=ft.Column(
                    [btn_copiar_resultado, btn_generar_pdf, btn_limpiar, btn_volver_inicio_resultado],
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                padding=ft.padding.symmetric(horizontal=2),
            )
            if estrecha
            else ft.Row(
                [btn_copiar_resultado, btn_generar_pdf, btn_limpiar, btn_volver_inicio_resultado],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
            )
        )

    def fijar_estado_consulta(texto, color="#2E7D32", en_proceso=False, texto_boton=None):
        texto_estado.value = texto
        texto_estado.color = color
        btn_generar.disabled = en_proceso
        btn_generar_comportamiento.disabled = en_proceso
        btn_generar_incredulo.disabled = en_proceso
        btn_generar_cristianos.disabled = en_proceso
        btn_enviar_chat_consejero.disabled = en_proceso
        btn_preguntar.disabled = en_proceso
        btn_copiar_resultado.disabled = en_proceso
        btn_generar_pdf.disabled = en_proceso
        btn_limpiar.disabled = en_proceso
        btn_volver_inicio_resultado.disabled = en_proceso
        btn_generar.content = contenido_boton_generar(
            texto_boton if en_proceso and texto_boton else ui["generate"],
            ft.Icons.HOURGLASS_EMPTY if en_proceso and texto_boton else ft.Icons.AUTO_AWESOME,
            color_boton_generar_resultado,
        )
        btn_generar_comportamiento.content = contenido_boton_generar(
            texto_boton if en_proceso and texto_boton else textos_comportamiento["generate"],
            ft.Icons.HOURGLASS_EMPTY if en_proceso and texto_boton else ft.Icons.AUTO_AWESOME,
        )
        btn_generar_incredulo.content = contenido_boton_generar(
            texto_boton if en_proceso and texto_boton else textos_incredulo["generate"],
            ft.Icons.HOURGLASS_EMPTY if en_proceso and texto_boton else ft.Icons.AUTO_AWESOME,
        )
        btn_generar_cristianos.content = contenido_boton_generar(
            texto_boton if en_proceso and texto_boton else textos_cristianos["generate"],
            ft.Icons.HOURGLASS_EMPTY if en_proceso and texto_boton else ft.Icons.AUTO_AWESOME,
        )
        btn_enviar_chat_consejero.icon = ft.Icons.HOURGLASS_EMPTY if en_proceso and texto_boton else ft.Icons.SEND_ROUNDED

    def cerrar_consulta_con_estado(texto_ok):
        if result_md.value.strip().startswith("Error"):
            fijar_estado_consulta(ui["status_error"], "#C62828", False)
        else:
            fijar_estado_consulta(texto_ok, "#2E7D32", False)

    texto_cargando_filtros = {
        "es": "Cargando filtros...",
        "ca": "Carregant filtres...",
        "fr": "Chargement des filtres...",
        "en": "Loading filters...",
    }.get(lang_code, "Loading filters...")
    contenido_filtros = ft.Column(
        [
            cabecera_filtros,
            contenedor_tema_sugerido,
            contenedores_especiales[dd_hombre],
            contenedores_especiales[dd_mujer],
            contenedores_especiales[dd_grupo],
            contenedores_especiales[dd_pueblo],
            contenedores_especiales[dd_pais],
            contenedores_especiales[dd_religion],
        ],
        spacing=10,
    )
    panel_filtros = ft.Container(
        key="panel_filtros",
        content=ft.Column(
            [
                cabecera_filtros,
                ft.Text(texto_cargando_filtros, color=theme["muted"], italic=True),
            ],
            spacing=10,
        ),
        padding=14,
        bgcolor=theme["panel_bg"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=14, color="#D9D9D9", offset=ft.Offset(0, 4)),
        expand=True,
    )

    panel_pasaje = ft.Container(
        key="panel_pasaje",
        content=ft.Column(
            [
                cabecera_pasaje,
                texto_paso_actual,
                texto_pista_paso,
                contenedor_biblia,
                contenedor_orden_libros,
                contenedor_libro,
                contenedor_pasaje,
            ],
            spacing=10,
        ),
        padding=14,
        bgcolor=theme["panel_bg"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=14, color="#D9D9D9", offset=ft.Offset(0, 4)),
        expand=True,
    )

    panel_comportamiento = ft.Container(
        key="panel_comportamiento",
        content=ft.Column(
            [
                cabecera_comportamiento,
                contenedor_comportamiento,
                contenedor_tamano_comportamiento,
                ft.Row([btn_generar_comportamiento]),
                pr_comportamiento,
            ],
            spacing=10,
        ),
        padding=14,
        bgcolor=theme["panel_bg"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=14, color="#D9D9D9", offset=ft.Offset(0, 4)),
    )
    panel_incredulo = ft.Container(
        key="panel_incredulo",
        content=ft.Column(
            [
                cabecera_incredulo,
                contenedor_incredulo,
                contenedor_tamano_incredulo,
                ft.Row([btn_generar_incredulo]),
                pr_incredulo,
            ],
            spacing=10,
        ),
        padding=14,
        bgcolor=theme["panel_bg"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=14, color="#D9D9D9", offset=ft.Offset(0, 4)),
    )
    panel_cristianos = ft.Container(
        key="panel_cristianos",
        content=ft.Column(
            [
                cabecera_cristianos,
                contenedor_cristianos,
                contenedor_tamano_cristianos,
                ft.Row([btn_generar_cristianos]),
                pr_cristianos,
            ],
            spacing=10,
        ),
        padding=14,
        bgcolor=theme["panel_bg"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=14, color="#D9D9D9", offset=ft.Offset(0, 4)),
    )
    caja_chat_consejero = ft.Container(
        content=chat_conversacion,
        padding=ft.padding.symmetric(horizontal=12, vertical=14),
        bgcolor=theme["accent"],
        border_radius=0,
        border=ft.border.all(0, "transparent"),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        expand=True,
    )
    barra_chat_consejero = ft.Container(
        key="barra_chat_consejero",
        content=ft.Row(
            [
                icono_barra_chat,
                tf_chat_consejero,
                btn_enviar_chat_consejero,
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=10, vertical=8),
        bgcolor=theme["panel_bg"],
        border=ft.border.all(2, theme["field_border"]),
        border_radius=0,
    )
    panel_chat_consejero = ft.Container(
        key="panel_chat_consejero",
        content=ft.Column(
            [
                cabecera_chat_consejero,
                caja_chat_consejero,
                barra_chat_consejero,
                pr_chat_consejero,
            ],
            spacing=0,
            expand=True,
        ),
        padding=0,
        bgcolor=theme["page_bg"],
        border=ft.border.all(2, theme["panel_border"]),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=10, color="#00000014", offset=ft.Offset(0, 3)),
        expand=True,
    )

    contenedor_aviso_generacion.content = texto_aviso_generacion
    contenedor_aviso_generacion.padding = 10
    contenedor_aviso_generacion.border_radius = 14
    contenedor_aviso_generacion.bgcolor = theme["secondary"]
    contenedor_aviso_generacion.border = ft.border.all(4, theme["panel_border"])
    contenedor_aviso_generacion.visible = False

    panel_generacion = ft.Container(
        key="panel_generacion",
        content=ft.Column(
            [
                contenedor_contexto_activo,
                ft.Text(f"{ui['study_type']} / {ui['words']}", weight="bold", size=18, color=theme["primary"]),
                contenedor_tipo_tamano,
                ft.Row([btn_generar]),
                ft.Row([btn_volver_contextual]),
                pr,
            ],
            spacing=10,
        ),
        padding=14,
        bgcolor=theme["panel_bg"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=14, color="#D9D9D9", offset=ft.Offset(0, 4)),
    )

    contenido_resultado = ft.Column(
        [result_md],
        scroll=ft.ScrollMode.ALWAYS,
    )

    caja_resultado = ft.Container(
        content=contenido_resultado,
        padding=14,
        bgcolor=theme["accent"],
        border_radius=18,
        border=ft.border.all(5, theme["panel_border"]),
        height=350,
    )

    panel_resultado = ft.Container(
        content=ft.Column(
            [
                cabecera_resultado,
                tf_resultado_vacio,
                caja_resultado,
                fila_pregunta_resultado,
                fila_acciones_resultado,
            ],
            spacing=10,
            expand=True,
        ),
        padding=18,
        bgcolor=theme["panel_bg"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=14, color="#D9D9D9", offset=ft.Offset(0, 4)),
        expand=True,
    )

    contenedor_cuerpo = ft.Container(expand=True)

    def actualizar_disposicion():
        nonlocal vista_resultado_completa
        paso_actual = obtener_paso_actual()
        filtro_activo = next((d for d in especiales if d.value != no_selection), None) is not None or dd_tema_sugerido.value != "Ninguno"
        mostrar_solo_generacion = pasaje_completo() or (filtro_activo and not mostrar_filtros_por_vuelta["ok"])
        btn_volver_contextual.visible = mostrar_solo_generacion and not vista_resultado_completa
        panel_resultado.visible = True
        vacio = not pr.visible and not pr_comportamiento.visible and not pr_incredulo.visible and not pr_cristianos.visible and not pr_chat_consejero.visible and not result_md.value.strip()
        tf_resultado_vacio.visible = vacio
        caja_resultado.visible = not vacio
        mostrar_pregunta_resultado = not vacio
        fila_pregunta_resultado.visible = mostrar_pregunta_resultado
        fila_acciones_resultado.visible = mostrar_pregunta_resultado

        panel_pasaje.border = ft.border.all(4, theme["panel_border"])
        panel_generacion.border = ft.border.all(4, theme["panel_border"])
        panel_pasaje.bgcolor = theme["panel_bg"]
        panel_generacion.bgcolor = theme["panel_bg"]
        btn_generar.style = estilo_boton_generar_resultado

        if inicio_preferido == "comportamiento":
            situacion_lista = dd_comportamiento.value != "Ninguno"
            palabras_listas = dd_tamano_comportamiento.value != "Ninguno"
            vacio = not pr.visible and not pr_comportamiento.visible and not pr_incredulo.visible and not pr_cristianos.visible and not pr_chat_consejero.visible and not result_md.value.strip()
            tf_resultado_vacio.visible = vacio
            caja_resultado.visible = not vacio
            fila_pregunta_resultado.visible = not vacio
            fila_acciones_resultado.visible = not vacio
            caja_resultado.height = 350 if vacio else None
            caja_resultado.expand = not vacio
            contenido_resultado.expand = not vacio
            panel_resultado.expand = not vacio
            panel_pasaje.visible = False
            panel_filtros.visible = False
            panel_generacion.visible = False
            panel_chat_consejero.visible = False
            panel_comportamiento.visible = True
            panel_comportamiento.bgcolor = theme["panel_bg"]
            panel_comportamiento.border = ft.border.all(4, theme["panel_border"])
            contenedor_comportamiento.bgcolor = theme["accent"] if not situacion_lista else theme["secondary"]
            contenedor_comportamiento.border = ft.border.all(6 if not situacion_lista else 4, theme["panel_border"])
            contenedor_tamano_comportamiento.bgcolor = theme["accent"] if situacion_lista and not palabras_listas else theme["secondary"]
            contenedor_tamano_comportamiento.border = ft.border.all(6 if situacion_lista and not palabras_listas else 4, theme["panel_border"])
            btn_generar_comportamiento.visible = situacion_lista and palabras_listas
            if vista_resultado_completa:
                contenedor_cuerpo.content = ft.Column([panel_comportamiento, panel_resultado], spacing=18, expand=True)
            else:
                contenedor_cuerpo.content = ft.Column([panel_comportamiento], spacing=18, expand=True)
            return

        if inicio_preferido == "incredulo":
            pregunta_lista = dd_incredulo.value != "Ninguno"
            palabras_listas = dd_tamano_incredulo.value != "Ninguno"
            vacio = not pr.visible and not pr_comportamiento.visible and not pr_incredulo.visible and not pr_cristianos.visible and not pr_chat_consejero.visible and not result_md.value.strip()
            tf_resultado_vacio.visible = vacio
            caja_resultado.visible = not vacio
            fila_pregunta_resultado.visible = not vacio
            fila_acciones_resultado.visible = not vacio
            caja_resultado.height = 350 if vacio else None
            caja_resultado.expand = not vacio
            contenido_resultado.expand = not vacio
            panel_resultado.expand = not vacio
            panel_pasaje.visible = False
            panel_filtros.visible = False
            panel_generacion.visible = False
            panel_comportamiento.visible = False
            panel_chat_consejero.visible = False
            panel_incredulo.visible = True
            panel_cristianos.visible = False
            panel_incredulo.bgcolor = theme["panel_bg"]
            panel_incredulo.border = ft.border.all(4, theme["panel_border"])
            contenedor_incredulo.bgcolor = theme["accent"] if not pregunta_lista else theme["secondary"]
            contenedor_incredulo.border = ft.border.all(6 if not pregunta_lista else 4, theme["panel_border"])
            contenedor_tamano_incredulo.bgcolor = theme["accent"] if pregunta_lista and not palabras_listas else theme["secondary"]
            contenedor_tamano_incredulo.border = ft.border.all(6 if pregunta_lista and not palabras_listas else 4, theme["panel_border"])
            btn_generar_incredulo.visible = pregunta_lista and palabras_listas
            if vista_resultado_completa:
                contenedor_cuerpo.content = ft.Column([panel_incredulo, panel_resultado], spacing=18, expand=True)
            else:
                contenedor_cuerpo.content = ft.Column([panel_incredulo], spacing=18, expand=True)
            return

        if inicio_preferido == "cristianos":
            pregunta_lista = dd_cristianos.value != "Ninguno"
            palabras_listas = dd_tamano_cristianos.value != "Ninguno"
            vacio = not pr.visible and not pr_comportamiento.visible and not pr_incredulo.visible and not pr_cristianos.visible and not pr_chat_consejero.visible and not result_md.value.strip()
            tf_resultado_vacio.visible = vacio
            caja_resultado.visible = not vacio
            fila_pregunta_resultado.visible = not vacio
            fila_acciones_resultado.visible = not vacio
            caja_resultado.height = 350 if vacio else None
            caja_resultado.expand = not vacio
            contenido_resultado.expand = not vacio
            panel_resultado.expand = not vacio
            panel_pasaje.visible = False
            panel_filtros.visible = False
            panel_generacion.visible = False
            panel_comportamiento.visible = False
            panel_incredulo.visible = False
            panel_chat_consejero.visible = False
            panel_cristianos.visible = True
            panel_cristianos.bgcolor = theme["panel_bg"]
            panel_cristianos.border = ft.border.all(4, theme["panel_border"])
            contenedor_cristianos.bgcolor = theme["accent"] if not pregunta_lista else theme["secondary"]
            contenedor_cristianos.border = ft.border.all(6 if not pregunta_lista else 4, theme["panel_border"])
            contenedor_tamano_cristianos.bgcolor = theme["accent"] if pregunta_lista and not palabras_listas else theme["secondary"]
            contenedor_tamano_cristianos.border = ft.border.all(6 if pregunta_lista and not palabras_listas else 4, theme["panel_border"])
            btn_generar_cristianos.visible = pregunta_lista and palabras_listas
            if vista_resultado_completa:
                contenedor_cuerpo.content = ft.Column([panel_cristianos, panel_resultado], spacing=18, expand=True)
            else:
                contenedor_cuerpo.content = ft.Column([panel_cristianos], spacing=18, expand=True)
            return

        if es_modo_chat:
            if not historial_chat_consejero:
                asegurar_saludo_inicial_chat()
            mensaje_listo = bool(tf_chat_consejero.value.strip())
            vacio = not pr.visible and not pr_comportamiento.visible and not pr_incredulo.visible and not pr_cristianos.visible and not pr_chat_consejero.visible and not result_md.value.strip()
            tf_resultado_vacio.visible = vacio
            caja_resultado.visible = not vacio
            fila_pregunta_resultado.visible = False
            fila_acciones_resultado.visible = False
            panel_resultado.visible = False
            panel_pasaje.visible = False
            panel_filtros.visible = False
            panel_generacion.visible = False
            panel_comportamiento.visible = False
            panel_incredulo.visible = False
            panel_cristianos.visible = False
            panel_chat_consejero.visible = True
            panel_chat_consejero.bgcolor = theme["panel_bg"]
            panel_chat_consejero.border = ft.border.all(4, theme["panel_border"])
            barra_chat_consejero.bgcolor = theme["panel_bg"]
            barra_chat_consejero.border = ft.border.all(2 if mensaje_listo else 3, theme["field_border"])
            btn_enviar_chat_consejero.visible = True
            contenedor_cuerpo.content = ft.Column([panel_chat_consejero], spacing=18, expand=True)
            return

        panel_comportamiento.visible = False
        panel_incredulo.visible = False
        panel_cristianos.visible = False
        panel_chat_consejero.visible = False
        if paso_actual in {"version", "book_order", "book", "chapter", "start", "end"}:
            panel_pasaje.border = ft.border.all(5, theme["panel_border"])
            panel_pasaje.bgcolor = theme["accent"]
        else:
            panel_generacion.border = ft.border.all(5, theme["panel_border"])
            panel_generacion.bgcolor = theme["accent"]
            if paso_actual == "generate":
                btn_generar.style = estilo_boton_generar_resultado

        if vista_resultado_completa:
            caja_resultado.height = None if not vacio else 350
            caja_resultado.expand = not vacio
            contenido_resultado.expand = not vacio
            panel_resultado.expand = True
            panel_pasaje.visible = False
            panel_filtros.visible = False
            panel_generacion.visible = True
            contenedor_cuerpo.content = ft.Column([panel_generacion, panel_resultado], spacing=18, expand=True)
        else:
            caja_resultado.height = 350
            caja_resultado.expand = False
            contenido_resultado.expand = False
            panel_resultado.expand = False
            panel_generacion.visible = True
            if mostrar_solo_generacion:
                panel_pasaje.visible = False
                panel_filtros.visible = False
                paneles = [panel_generacion]
            else:
                panel_pasaje.visible = inicio_preferido == "biblia"
                panel_filtros.visible = inicio_preferido == "filtros"
                if paso_actual in {"study_type", "words", "generate"}:
                    paneles = [panel_generacion]
                    if inicio_preferido == "biblia":
                        paneles.append(panel_pasaje)
                    else:
                        paneles.append(panel_filtros)
                elif inicio_preferido == "filtros":
                    paneles = [panel_filtros, panel_generacion]
                else:
                    paneles = [panel_pasaje, panel_generacion]
            contenedor_cuerpo.content = ft.Column(paneles, spacing=18, expand=True)

    encabezado_controles = []
    if on_volver is not None:
        encabezado_controles.append(
            ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                on_click=lambda e: on_volver(),
                icon_color=theme["primary"],
            )
        )
    encabezado_controles.extend(
        [
            ft.Icon(ft.Icons.AUTO_STORIES, color=theme["primary"]),
            ft.Text(ui["title"], size=24, weight="bold", color=theme["primary"]),
        ]
    )
    contenido_pantalla = ft.Container(
        content=ft.Column(
            [
                ft.Row(encabezado_controles, alignment=ft.MainAxisAlignment.CENTER),
                contenedor_cuerpo,
            ],
            spacing=18,
            expand=True,
        ),
        padding=12,
        border_radius=16,
        bgcolor=theme["panel_bg"],
        expand=True,
    )
    marco_principal = ft.Container(
        content=contenido_pantalla,
        padding=6,
        border=ft.border.all(7, theme["primary"]),
        border_radius=26,
        bgcolor=theme["page_bg"],
        expand=True,
    )

    def refrescar_layout(e=None):
        actualizar_layout_responsive()
        actualizar_disposicion()
        if controles_montados:
            page.update()

    page.on_resized = refrescar_layout
    actualizar_layout_responsive()
    actualizar_disposicion()
    page.add(ft.SafeArea(marco_principal))
    controles_montados = True
    if inicio_preferido == "filtros":
        page.scroll_to(scroll_key="panel_filtros", duration=300)
    elif inicio_preferido == "comportamiento":
        page.scroll_to(scroll_key="panel_comportamiento", duration=300)
    elif inicio_preferido == "incredulo":
        page.scroll_to(scroll_key="panel_incredulo", duration=300)
    elif inicio_preferido == "cristianos":
        page.scroll_to(scroll_key="panel_cristianos", duration=300)
    elif es_modo_chat:
        page.scroll_to(scroll_key="panel_chat_consejero", duration=300)
    else:
        page.scroll_to(scroll_key="panel_pasaje", duration=300)
    
    async def hidratar_filtros_async():
        await asyncio.sleep(0.02)
        poblar_dropdown(dd_tema_sugerido, temas_sugeridos, "Ninguno", ui["no_selection"], etiqueta_tema)
        await asyncio.sleep(0)
        poblar_dropdown(dd_hombre, masculinos, no_selection, no_selection, localize_catalog_item)
        await asyncio.sleep(0)
        poblar_dropdown(dd_mujer, femeninos, no_selection, no_selection, localize_catalog_item)
        await asyncio.sleep(0)
        poblar_dropdown(dd_grupo, grupos_biblicos, no_selection, no_selection, localize_catalog_item)
        await asyncio.sleep(0)
        poblar_dropdown(dd_pueblo, pueblos, no_selection, no_selection, localize_catalog_item)
        await asyncio.sleep(0)
        poblar_dropdown(dd_pais, lugares, no_selection, no_selection, localize_catalog_item)
        await asyncio.sleep(0)
        poblar_dropdown(dd_religion, religiones_mundo, no_selection, no_selection, localize_catalog_item)
        panel_filtros.content = contenido_filtros
        manejar_bloqueos()
        actualizar_resumen()
        page.update()

    page.run_task(hidratar_filtros_async)


