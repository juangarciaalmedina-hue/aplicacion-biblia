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

## Desarrollo local

Ejecutar la app:

```powershell
python main.py
```

Publicar una version web local:

```powershell
flet publish main.py --distpath dist
```

