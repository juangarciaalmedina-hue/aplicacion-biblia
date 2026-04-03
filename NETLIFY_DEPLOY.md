# Desplegar Biblia IA en Netlify

Fecha de referencia: 3 de abril de 2026

## Objetivo

Usar Netlify para:

- publicar la version web,
- guardar `OPENROUTER_API_KEY` en el servidor,
- exponer un proxy seguro en `/api/openrouter`,
- y dar una URL HTTPS valida para `OPENROUTER_PROXY_URL`.

## 1. Subir el proyecto a GitHub

El repositorio debe estar en GitHub sin incluir `.env`, claves reales, ni carpetas de build.

## 2. Crear el sitio en Netlify

1. Entra en Netlify.
2. Pulsa `Add new site`.
3. Elige `Import an existing project`.
4. Conecta tu repositorio de GitHub.
5. Selecciona este proyecto.

Netlify deberia detectar `netlify.toml` y usar:

- comando de build: `python -m pip install --upgrade pip && pip install -r requirements.txt && flet publish main.py --distpath dist`
- carpeta publicada: `dist`
- funciones: `netlify/functions`

## 3. Variables de entorno en Netlify

En `Site configuration -> Environment variables` crea estas variables:

```text
OPENROUTER_API_KEY=tu_clave_nueva_de_openrouter
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_FALLBACK_MODELS=google/gemini-2.5-flash-lite,deepseek/deepseek-chat
OPENROUTER_TEMPERATURE=0.2
OPENROUTER_TOP_P=0.9
OPENROUTER_HTTP_REFERER=https://TU-SITIO.netlify.app
```

Importante:

- usa una clave nueva, no la antigua desactivada,
- no subas esa clave a GitHub,
- y sustituye `TU-SITIO.netlify.app` por tu URL real del sitio.

## 4. Primer despliegue

Lanza el deploy desde Netlify y espera a que termine.

## 5. Comprobar si Netlify esta vivo

Cuando el deploy termine, abre:

```text
https://TU-SITIO.netlify.app/api/health
```

Si todo esta bien, deberias ver JSON parecido a esto:

```json
{"ok":true,"service":"biblia-app-netlify","timestamp":"2026-04-03T10:00:00.000Z"}
```

Si eso responde, significa que:

- el sitio existe,
- las funciones de Netlify estan desplegadas,
- y la ruta de funciones ya funciona.

## 6. Comprobar el proxy de OpenRouter

Despues prueba:

```text
https://TU-SITIO.netlify.app/api/openrouter
```

Si lo abres en navegador con GET, es normal que no te devuelva una respuesta util para generar contenido. La validacion real debe hacerse con una peticion POST o con `python validar_openrouter.py` usando:

```text
OPENROUTER_PROXY_URL=https://TU-SITIO.netlify.app/api/openrouter
```

## 7. Configuracion local para compilar la APK

En tu `.env` local deja esto:

```text
OPENROUTER_PROXY_URL=https://TU-SITIO.netlify.app/api/openrouter
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_FALLBACK_MODELS=google/gemini-2.5-flash-lite,deepseek/deepseek-chat
OPENROUTER_TEMPERATURE=0.2
OPENROUTER_TOP_P=0.9
```

Si quieres, puedes conservar `OPENROUTER_API_KEY` solo para escritorio local, pero no hace falta para la APK si el proxy ya funciona.

## 8. Verificacion local

Con la URL del proxy ya puesta en `.env`, ejecuta:

```powershell
python validar_openrouter.py
```

Si responde `OK`, la app ya esta lista para compilar la APK usando el proxy.

## 9. Que hacer si sale 404

Si `https://TU-SITIO.netlify.app/api/health` devuelve `404`, significa normalmente una de estas cosas:

- el sitio aun no esta desplegado,
- la URL del sitio no es la correcta,
- el repositorio conectado no es el que contiene `netlify/functions`,
- o el deploy fallo antes de publicar las funciones.

## 10. Siguiente paso

Cuando `/api/health` funcione y `python validar_openrouter.py` responda `OK`, el siguiente paso natural es generar la APK ligera con ese proxy ya operativo.
