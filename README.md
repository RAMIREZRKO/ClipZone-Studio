# ClipZone Studio

Editor de vídeo **local para Windows**, con Python, FastAPI, FFmpeg y React + TypeScript. Interfaz en español, negro y verde neón. Inspirado en el flujo de clipping de OpusClip, con diseño propio y sin servicios de pago.

**Versión 0.1 · Fase 1 funcional.** Importa originales, selecciona un intervalo, previsualiza el encuadre, exporta un MP4 y revisa el resultado antes de descargarlo. La detección de momentos con IA y los subtítulos dinámicos son fases posteriores; no están activados en esta versión.

## Ejecutar una instalación ya preparada

Después de instalar las dependencias y compilar el editor, haz doble clic en **`Iniciar ClipZone.cmd`** dentro de la carpeta del proyecto. Mantén abierta la terminal del servidor mientras editas. Desde PowerShell, situado en esa carpeta, también puedes ejecutar:

```powershell
.\scripts\start.ps1 -Open
```

Abre [ClipZone Studio](http://127.0.0.1:8000). Cierra el servidor con `Ctrl+C`. Si PowerShell bloquea scripts, utiliza el `.cmd` o ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Open`; esa opción se aplica solo a ese proceso.

## Instalar desde cero

Requisitos: Windows 10/11 x64, **Python 3.12 recomendado** (mínimo 3.10), **Node.js 22.12+ o 24 LTS**, FFmpeg y FFprobe con `libx264` y AAC. RAM recomendada: 8 GB para edición; la IA futura requerirá más recursos. Reserva espacio para una copia del original, proxies y exportaciones. Se necesita internet para instalar paquetes y descargar FFmpeg; la edición funciona después sin conexión.

1. Instala Python desde [python.org](https://www.python.org/downloads/windows/) y Node desde [nodejs.org](https://nodejs.org/en/download). Abre una terminal nueva.
2. Descarga el proyecto como ZIP o clónalo con [Git](https://git-scm.com/downloads). Sustituye `TU_USUARIO` por el propietario del repositorio una vez publicado:

```powershell
git clone https://github.com/TU_USUARIO/clipzone-studio.git
cd clipzone-studio
```

   Si ya tienes la carpeta original, abre PowerShell en ella y omite el clonado. Las dependencias, FFmpeg, los modelos y los vídeos locales no se incluyen en Git: se instalan o generan por separado.

3. Ejecuta desde la carpeta del proyecto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -DownloadFFmpeg
```

El script crea `.venv`, instala las versiones verificadas del backend, usa `npm ci` con el lockfile, compila React, comprueba codificadores y ejecuta pruebas reales de vídeo. `-DownloadFFmpeg` descarga la distribución essentials para Windows x64 de [Gyan](https://www.gyan.dev/ffmpeg/builds/), enlazada por la [página oficial de FFmpeg](https://ffmpeg.org/download.html). Los binarios se guardan en `tools/ffmpeg/bin`, sin cambiar el PATH del sistema. Revisa la licencia incluida con esa distribución antes de redistribuir los binarios.

Si ya tienes FFmpeg y FFprobe en PATH, omite `-DownloadFFmpeg`. Si Python no se detecta, utiliza `-Python 'C:\ruta\python.exe'`. En arquitecturas distintas de Windows x64, instala FFmpeg para tu equipo y configura las rutas.

4. Inicia con `Iniciar ClipZone.cmd` o `scripts/start.ps1 -Open`. Si el navegador no se abre, entra en [http://127.0.0.1:8000](http://127.0.0.1:8000). No cierres la terminal mientras utilices el editor.

Diagnóstico independiente:

```powershell
.\.venv\Scripts\python.exe scripts/doctor.py
```

## Qué incluye

| Función | Fase 1 |
|---|---|
| Importación | MP4, MOV, MKV, WebM, AVI, M4V, MTS y M2TS; copia local; límite configurable de 20 GB |
| Biblioteca | Originales, metadatos y miniaturas persistidos en SQLite |
| Recorte | Entrada/salida en segundos, controles de rango, duración rápida de 15/30/60 s o vídeo completo |
| Previsualización | Reproducción del intervalo, sonido, encuadre y foco; proxy H.264/AAC para fuentes incompatibles |
| Formatos | 9:16, 1:1, 4:5 y 16:9 |
| Encuadre | Imagen completa con bandas o recorte para llenar; foco horizontal y vertical; sin estirar |
| Resolución | 480, 720 o 1080 píxeles en el lado corto; dimensiones pares para H.264 |
| Plataformas | Presets editables para TikTok, Reels y Shorts, más modo libre |
| Zona segura | Márgenes superior/inferior editables y guías visuales; no se imprimen en la exportación |
| Exportación | MP4, vídeo H.264, audio AAC si existe, `yuv420p`, faststart; cola, progreso, cancelación y errores |
| Revisión | Reproducción del MP4 terminado y descarga desde Exportaciones |
| Privacidad | Procesamiento en este equipo; sin cuentas, API externas, fuentes remotas ni analítica |

Los presets son **puntos de partida de edición**, no una validación de las reglas actuales de cada plataforma. Se permite cambiarlos. En vertical, 1080 produce 1080×1920; en 1:1, 1080×1080; en 4:5, 1080×1350; en horizontal, 1920×1080. La duración mínima es 0,1 s y la máxima por clip, 1 hora. Se puede importar un original largo y exportar varios intervalos.

## Flujo de trabajo

1. Arrastra un original al área de trabajo o pulsa **Importar vídeo**. El archivo original externo no se modifica.
2. Elige un preset y ajusta entrada/salida; la reproducción se detiene al final del intervalo.
3. Selecciona formato, resolución y encuadre. En **Llenar y recortar**, desplaza el foco para conservar el sujeto.
4. Pulsa **Exportar clip**. Los trabajos se procesan uno a uno para limitar la carga de CPU.
5. En **Exportaciones**, pulsa **Previsualizar** y revisa el archivo exacto antes de **Descargar**.

La guía verde de subtítulos es solo una referencia. El MP4 exportado no contiene ese texto ni la guía. Whisper, la selección por IA y el render de subtítulos se desarrollarán en las siguientes fases.

Puedes generar un vídeo sintético de 12 segundos con audio:

```powershell
.\.venv\Scripts\python.exe scripts/create_demo.py
```

Después importa `demo/clipzone-demo.mp4`. No se descarga contenido de terceros.

El vídeo de demostración se genera en tu equipo y está excluido de Git, igual que los vídeos importados y exportados.

## Desarrollo

Terminal 1, API:

```powershell
.\scripts\start.ps1 -Dev
```

Terminal 2, React con recarga:

```powershell
cd frontend
npm run dev
```

Abre [el editor de desarrollo](http://127.0.0.1:5173). Vite reenvía `/api` al servidor local. La documentación interactiva de FastAPI está en [Swagger UI](http://127.0.0.1:8000/docs). Para actualizar la versión servida por FastAPI, ejecuta `npm run build` desde `frontend` y reinicia el servidor si no existía `dist` al arrancar.

## Pruebas

```powershell
.\scripts\test.ps1
cd frontend
npm run build
```

La suite Python verifica los ocho encuadres (cuatro formatos × dos modos) con codificación real, duración, audio, píxeles, HTTP Range, persistencia, archivos inválidos, límites, proxy de MKV, fuentes sin audio, normalización anamórfica, cancelación y recuperación tras interrupciones. FFmpeg es obligatorio: las pruebas no simulan el render.

Para las pruebas completas de navegador, con el puerto 8000 libre:

```powershell
# Desde frontend, después de generar demo/clipzone-demo.mp4:
npx playwright install chromium
npm run test:e2e
```

Si tienes Microsoft Edge instalado, puedes evitar descargar Chromium:

```powershell
$env:CLIPZONE_BROWSER_CHANNEL = 'msedge'
npm run test:e2e
```

Playwright inicia y cierra una API aislada; sus datos van a `test-results/e2e-data`, sin usar tu biblioteca. Verifica importación, recorte, reproducción, encuadre, render, vista previa, descarga, persistencia, tamaño móvil y diálogos. Capturas en `docs/capturas`; trazas de fallos en `test-results/browser`.

## Datos y configuración

```text
data/
  clipzone.sqlite3  # biblioteca y trabajos
  uploads/          # copias de los originales
  previews/         # proxies de reproducción
  thumbnails/       # JPEG
  exports/          # MP4 finales
```

| Variable de entorno | Uso |
|---|---|
| `CLIPZONE_DATA_DIR` | Carpeta alternativa para datos locales |
| `CLIPZONE_FFMPEG` | Ruta completa a `ffmpeg.exe` |
| `CLIPZONE_FFPROBE` | Ruta completa a `ffprobe.exe` |
| `CLIPZONE_MAX_UPLOAD_GB` | Límite entero en GB; predeterminado: `20` |

Establécelas en PowerShell antes de iniciar. Haz copia de `data` con el servidor detenido. La biblioteca y las exportaciones sobreviven a reinicios; las decisiones de edición sin exportar no se guardan como borradores. Los ajustes de cada exportación se conservan. Los trabajos interrumpidos por un cierre inesperado se marcan como fallidos al reiniciar y pueden volver a editarse. No hay borrado automático de originales ni exportaciones.

El servidor escucha exclusivamente en `127.0.0.1`; los hosts y orígenes admitidos se limitan al desarrollo local. No está diseñado como servicio público ni multiusuario. FFmpeg se invoca con argumentos separados, sin shell, y se restringen los protocolos de entrada a archivos y pipes locales.

## Arquitectura y siguientes fases

Consulta [la arquitectura](docs/ARQUITECTURA.md), [el plan de fases](docs/FASES.md) y [la validación](docs/VALIDACION.md).

```text
backend/app/
  config.py           # rutas, límites, detección de binarios
  database.py         # persistencia SQLite
  models.py           # validación y dimensiones
  main.py             # API, importación y streaming
  services/media.py   # FFprobe, encuadre y comandos FFmpeg
  services/jobs.py    # cola, progreso y cancelación
  ai/contracts.py     # interfaces de transcripción y detección
  ai/whisper_local.py # adaptador opcional, todavía sin conexión al editor
frontend/src/
  App.tsx             # editor, biblioteca y exportaciones
  api.ts              # cliente tipado y subida con progreso
  styles.css          # diseño adaptable negro / verde neón
scripts/              # instalar, iniciar, diagnosticar, probar y generar demo
```

Referencias técnicas: [FastAPI UploadFile](https://fastapi.tiangolo.com/tutorial/request-files/), [filtros de FFmpeg](https://ffmpeg.org/ffmpeg-filters.html), [Vite](https://vite.dev/guide/) y [Whisper local](https://github.com/openai/whisper). No se necesita una clave de OpenAI.

## Publicar en GitHub como clipzone-studio

La copia local queda preparada con un repositorio Git, rama `main` y commit inicial. Los pasos siguientes publican ese commit; no necesitas inicializar Git de nuevo.

1. Inicia sesión en GitHub y abre [Crear repositorio](https://github.com/new).
2. Escribe **`clipzone-studio`** como nombre y elige la visibilidad que prefieras.
3. Crea el repositorio **vacío**, sin añadir README, `.gitignore` ni licencia desde GitHub: el código y la documentación ya existen localmente.
4. Abre PowerShell en la carpeta original de ClipZone Studio. Sustituye `TU_USUARIO` por tu usuario u organización de GitHub y ejecuta:

```powershell
git remote add origin https://github.com/TU_USUARIO/clipzone-studio.git
git remote -v
git push -u origin main
```

Si Git solicita autenticación, sigue el inicio de sesión del navegador que ofrezca Git Credential Manager. No escribas contraseñas ni tokens en la URL del remoto ni en archivos del proyecto. Si aparece `remote origin already exists`, consulta `git remote -v`; si la URL es incorrecta, corrígela con `git remote set-url origin https://github.com/TU_USUARIO/clipzone-studio.git`.

Antes de subir, puedes revisar los archivos del commit y el estado local:

```powershell
git ls-files
git status
```

`.gitignore` excluye dependencias, compilaciones, FFmpeg, modelos de IA, vídeos y audio, bases de datos, temporales y archivos habituales de credenciales. **Ignorar archivos no los elimina:** la biblioteca, los originales, los modelos y las exportaciones permanecen en tu equipo. El código, los scripts, la documentación y los lockfiles sí se versionan. Las capturas de documentación proceden de los vídeos sintéticos de prueba.

Para guardar cambios posteriores:

```powershell
git add .
git commit -m "Describe el cambio realizado"
git push
```

La preparación local no crea un repositorio remoto ni publica archivos automáticamente. Referencia: [guía oficial de GitHub para publicar código local](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github?platform=windows).
