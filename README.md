# Biblia App

Aplicacion biblica hecha con Flet.

## Subir a GitHub

```powershell
git init -b main
git add .
git commit -m "Preparar despliegue en Netlify"
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

## Desplegar en Netlify

1. Importa el repositorio desde GitHub en Netlify.
2. Netlify leera `netlify.toml` automaticamente.
3. En `Site configuration -> Environment variables` crea estas variables:

```text
OPENROUTER_API_KEY=tu_clave_real
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_FALLBACK_MODELS=google/gemini-2.5-flash-lite,deepseek/deepseek-chat
OPENROUTER_TEMPERATURE=0.2
OPENROUTER_TOP_P=0.9
```

4. Lanza el primer deploy.

## Preparacion para Play Store

Para Android o iOS publicables, no metas `OPENROUTER_API_KEY` dentro de la app. La clave debe quedarse solo en el servidor y la app debe llamar a un proxy HTTPS.

En tu `.env` local para compilar la APK configura:

```text
OPENROUTER_PROXY_URL=https://tu-sitio.netlify.app/api/openrouter
```

La app usara ese proxy en Android/iOS y evitara enviar la clave desde la APK.

Antes de publicar en Google Play:

1. Despliega el proxy de Netlify o tu backend propio.
2. Comprueba que `OPENROUTER_PROXY_URL` responde.
3. Añade politica de privacidad.
4. Completa la seccion `Data safety` indicando que las consultas del usuario se envian a un servicio externo de IA para responder.

## Despliegue en Netlify

Tienes una guia paso a paso en [NETLIFY_DEPLOY.md](C:/Users/danie/OneDrive/Escritorio/APLICACION%20BIBLIA/NETLIFY_DEPLOY.md).

## Desarrollo local

Ejecutar la app:

```powershell
python main.py
```

Publicar una version web local:

```powershell
flet publish main.py --distpath dist
```
