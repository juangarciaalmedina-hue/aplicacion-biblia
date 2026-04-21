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

La app esta preparada para publicarse en Netlify como sitio estatico generado por Flet.

### Archivos ya preparados

- `netlify.toml`: define el comando de build y la carpeta publicada.
- `pyproject.toml`: fuerza `route_url_strategy = "hash"` para que la navegacion funcione bien en hosting estatico.

### Como desplegar en Netlify

1. Importa este repositorio en Netlify.
2. Deja que Netlify use la configuracion del archivo `netlify.toml`.
3. Lanza el deploy.

Netlify ejecutara este flujo:

```bash
pip install -r requirements.txt
flet publish . --distpath dist --route-url-strategy hash
```

### Limitaciones de la version web

- La `GROQ_API_KEY` no se guarda en `.env` en web. Se guarda en el navegador del usuario.
- La exportacion a PDF y la apertura de carpetas locales no estan disponibles en Netlify.
- Si quieres que la IA funcione en la version web, el usuario tendra que pegar su propia `GROQ_API_KEY` dentro de la app.

## GitHub Pages

La app tambien queda preparada para publicarse en GitHub Pages mediante GitHub Actions.

### Archivo preparado

- `.github/workflows/github-pages.yml`: construye la web con `flet build web` y la despliega en Pages.

### Como activarlo

1. Sube este repositorio a GitHub.
2. En GitHub, abre `Settings > Pages`.
3. En `Build and deployment`, selecciona `GitHub Actions`.
4. Haz push a `main` o lanza el workflow desde la pestana `Actions`.

### URL base

- Si el repo es de proyecto, por ejemplo `usuario/aplicacion-biblia`, el workflow publica bajo `/aplicacion-biblia/`.
- Si el repo se llama `usuario.github.io`, el workflow usa `/`.
