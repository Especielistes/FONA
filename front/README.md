# FONA Frontend

Frontend estático preparado para Vercel.

Rutas:
- `/`
- `/calle/`
- `/casa/`

Por defecto el backend local es `http://localhost:8080` y el WebSocket `ws://localhost:8080/portero`.

En producción cambia `js/config.js` por las URLs HTTPS/WSS de Oracle, o define `window.FONA_API_URL` y `window.FONA_WS_URL`.

La cámara de la calle permanece en el navegador. El vídeo remoto para el panel de casa requerirá WebRTC/streaming; este ZIP no finge que esa parte ya existe.
