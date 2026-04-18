# Biblia App

Aplicacion creada con Flet para mostrar contenido biblico y habilitar funciones de IA mediante Groq.

## Tecnologias

- Python 3.10 o superior
- Flet
- Certifi
- Groq API para las funciones de IA

## Estructura

- `main.py`: punto de entrada principal de la app.
- `src/biblia_app/`: codigo de la aplicacion.
- `pyproject.toml`: configuracion de Flet y Briefcase.
- `.env.example`: ejemplo de variables de entorno para desarrollo local.

## Puesta en marcha local

1. Crea un entorno virtual.
2. Instala las dependencias.
3. Copia `.env.example` a `.env`.
4. Anade tu `GROQ_API_KEY` real al `.env`.
5. Ejecuta la app.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
py main.py
```

## Variables de entorno

- `GROQ_API_KEY`: clave para habilitar las respuestas de IA.
- `GROQ_MODEL`: modelo de Groq que quieres usar. Si no lo cambias, la app usa `llama-3.1-8b-instant`.

## GitHub

Este repositorio ya esta preparado para subirse sin incluir archivos locales o sensibles:

- `.env` no se versiona.
- `build/`, `dist/` y `.venv/` no se versionan.
- Hay un `.env.example` para que otros sepan que variables configurar.

## Siguiente paso: Netlify

La app esta hecha con Flet, asi que para Netlify lo normal sera publicar una version web generada a partir del proyecto, no subir el codigo Python tal cual como si fuera un sitio estatico simple. Cuando quieras, preparo ese flujo contigo.
