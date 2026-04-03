# Checklist rapida para publicar Biblia IA en Play Store

Fecha de referencia: 3 de abril de 2026

## Tecnico

- Desplegar el proxy/backend publico para la IA.
- Confirmar que `OPENROUTER_PROXY_URL` responde por HTTPS.
- Compilar una APK o AAB usando el proxy, no la clave directa dentro de la app.
- Probar generacion de estudios y preguntas en un movil real.
- Probar generacion y apertura de PDF en Android.
- Verificar icono, nombre, version y estabilidad general.

## Privacidad y cumplimiento

- Publicar una politica de privacidad accesible publicamente.
- Revisar y adaptar [POLITICA_PRIVACIDAD.md](C:/Users/danie/OneDrive/Escritorio/APLICACION%20BIBLIA/POLITICA_PRIVACIDAD.md).
- Completar la seccion `Data safety` en Play Console.
- Declarar que las consultas del usuario se envian a un servicio externo de IA si esa es la configuracion publicada.
- Confirmar que la declaracion coincide con el comportamiento real de la app.

## Ficha de Play Store

- Preparar icono final.
- Preparar capturas de pantalla.
- Redactar descripcion corta y larga.
- Indicar correo de soporte.
- Añadir la URL publica de la politica de privacidad.

## Publicacion

- Generar la build final de publicacion.
- Firmar la build de release si corresponde.
- Subir a un track interno o cerrado antes de produccion.
- Probar instalacion, actualizacion y desinstalacion.

## Bloqueo actual del proyecto

El proyecto ya esta preparado para usar `OPENROUTER_PROXY_URL`, pero la URL probable `https://biblia-app.netlify.app/api/openrouter` devolvia `404` el 3 de abril de 2026. Hasta que exista un backend publico real, no conviene generar la APK final para Play Store.
