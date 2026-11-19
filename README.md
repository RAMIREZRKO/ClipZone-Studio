# ClipZone Studio

Editor de vídeo **local para Windows**, con Python, FastAPI, FFmpeg y React + TypeScript. Interfaz en español, negro y verde neón. Inspirado en el flujo de clipping de OpusClip, con diseño propio y sin servicios de pago.

**Versión 0.3.0 · Subtítulos y campañas.** El editor manual y la generación múltiple con Whisper incorporan subtítulos dinámicos, traducciones editables y capas promocionales para TikTok, Instagram Reels, YouTube Shorts y Facebook Reels.

## Ejecutar una instalación ya preparada

Después de instalar las dependencias y compilar el editor, haz doble clic en **`Iniciar ClipZone.cmd`** dentro de la carpeta del proyecto. Mantén abierta la terminal del servidor mientras editas. Desde PowerShell, situado en esa carpeta, también puedes ejecutar:

```powershell
.\scripts\start.ps1 -Open
```

Abre [ClipZone Studio](http://127.0.0.1:8000). Cierra el servidor con `Ctrl+C`. Si PowerShell bloquea scripts, utiliza el `.cmd` o ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Open`; esa opción se aplica solo a ese proceso.

## Instalar desde cero

Requisitos: Windows 10/11 x64, **Python 3.12 recomendado** (mínimo 3.10), **Node.js 22.12+ o 24 LTS**, FFmpeg y FFprobe con `libx264` y AAC. RAM recomendada: 8 GB para edición y Whisper Tiny en CPU; Base y Small requieren más tiempo y memoria. Reserva espacio para una copia del original, proxies y exportaciones. Se necesita internet para instalar paquetes y descargar FFmpeg; la edición funciona después sin conexión.

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

| Función | Versión 0.3.0 |
|---|---|
| Importación | MP4, MOV, MKV, WebM, AVI, M4V, MTS y M2TS; copia local; límite configurable de 20 GB |
| Biblioteca | Originales, metadatos y miniaturas persistidos en SQLite |
| Recorte | Línea de tiempo con tiradores de entrada y salida, cursor independiente, zoom de 1× a 32× y ajuste por centésimas |
| Previsualización | Original, encuadre en directo y vista exacta renderizada con los ajustes de exportación |
| Formatos | 9:16, 1:1, 4:5 y 16:9 |
| Encuadre | Imagen completa con bandas, recorte para llenar con foco manual y fondo difuminado con intensidad regulable |
| Resolución | 480, 720 o 1080 píxeles en el lado corto; dimensiones pares para H.264 |
| Plataformas | Cuatro plataformas: TikTok, Instagram Reels, YouTube Shorts y Facebook Reels, más modo libre |
| Zona segura | Márgenes superior/inferior editables para colocar subtítulos. Las guías de edición se ocultan en el render |
| Exportación | MP4, vídeo H.264, audio AAC si existe, `yuv420p`, faststart; cola, progreso, cancelación y errores |
| Revisión | Reproducción del MP4 terminado y descarga desde Exportaciones |
| Almacenamiento | Eliminación individual o múltiple, opción de conservar copias, métricas locales y limpieza de temporales |
| IA local | Whisper Tiny/Base/Small, palabras con tiempos, ranking editorial, selección múltiple y generación de clips |
| Subtítulos | Pista editable, estilos Clásico, Hormozi, Karaoke y Minimalista, texto incrustado y archivos SRT/VTT opcionales |
| Campañas | Hasta 12 capas PNG y textos, plantillas guardadas y ejemplos para YouTube y Kick |
| Traducción | Pistas por idioma, edición manual, importación SRT/VTT y adaptador opcional a Argos Translate |
| Privacidad | Procesamiento en este equipo; sin cuentas, API externas, fuentes remotas ni analítica |

Los presets son **puntos de partida de edición**, no una validación de las reglas actuales de cada plataforma. Se permite cambiarlos. En vertical, 1080 produce 1080×1920; en 1:1, 1080×1080; en 4:5, 1080×1350; en horizontal, 1920×1080. La duración mínima es 0,1 s y la máxima por clip, 1 hora. Se puede importar un original largo y exportar varios intervalos.

## Flujo de trabajo

1. Arrastra un original al área de trabajo o pulsa **Importar vídeo**. El archivo original externo no se modifica.
2. Elige un preset y ajusta entrada/salida; la reproducción se detiene al final del intervalo.
3. Selecciona formato, resolución y encuadre. En **Llenar y recortar**, desplaza el foco para conservar el sujeto.
4. Pulsa **Exportar clip**. Los trabajos se procesan uno a uno para limitar la carga de CPU.
5. En **Exportaciones**, pulsa **Previsualizar** y revisa el archivo exacto antes de **Descargar**.

La guía verde es una herramienta de edición. **Vista exacta** y **Exportar** incrustan los subtítulos activos y las capas gráficas, sin la guía ni los controles de arrastre.

Puedes generar un vídeo sintético de 12 segundos con audio:

```powershell
.\.venv\Scripts\python.exe scripts/create_demo.py
```

Después importa `demo/clipzone-demo.mp4`. No se descarga contenido de terceros.

El vídeo de demostración se genera en tu equipo y está excluido de Git, igual que los vídeos importados y exportados.

## Reproductor y línea de tiempo

**Original** reproduce la fuente en su formato, con acceso a todo su metraje. **Encuadre en directo** muestra el corte y la composición conforme ajustas los controles. En **Ajustar completo**, un original horizontal ocupa solo la parte central de un lienzo vertical porque se conserva la imagen entera. **Fondo difuminado** rellena el área libre con una copia ampliada del mismo fotograma. La intensidad se regula en **Configura tu clip**.

Pulsa **Vista exacta** para generar y reproducir un MP4 con la resolución, el encuadre, el audio y el intervalo de exportación. El render se procesa en la misma cola que las exportaciones. Si cambias los ajustes, genera una nueva vista exacta. El encuadre en directo responde de inmediato y puede mostrar pequeñas diferencias en el desenfoque respecto al render de FFmpeg.

Arrastra los tiradores verdes para ajustar la entrada y la salida. Haz clic en la pista o arrastra el cursor blanco para buscar en el vídeo. El cursor conserva los límites del clip. Usa **Marcar entrada aquí** o **Marcar salida aquí** para fijar un límite en la posición actual. Si buscas fuera del intervalo en **Vista exacta**, el reproductor vuelve a **Encuadre en directo** para mostrar esa parte del vídeo.

Los tiempos se muestran en horas, minutos y segundos, con centésimas en los controles. Usa **+** y **−** para ajustar el zoom hasta 32×. En el cursor y los tiradores, las flechas avanzan o retroceden 0,01 s y **Mayús + flecha** ajusta 1 s. En **Ajuste de precisión** puedes escribir los límites en segundos.

## ClipZone Live 2.0

**Captura directa** mantiene el búfer de un canal público y autorizado de **Kick** o **Twitch** en el servidor local de ClipZone. Puedes cerrar la pestaña o el navegador después de iniciar la captura. Mantén el servidor de ClipZone en ejecución.

1. Instala la dependencia opcional desde la carpeta del proyecto y reinicia ClipZone:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r backend/requirements-live.txt
   .\scripts\start.ps1
   ```

2. Abre **ClipZone Live → Captura directa**. Pega la URL HTTPS de un canal autorizado, pulsa **Comprobar directo** y elige una de las calidades ofrecidas.
3. Pulsa **Iniciar captura**. El panel muestra la conexión, el tiempo transcurrido, la duración real del búfer y su espacio en disco.
4. Selecciona **30, 60, 90, 120 o 300 s**. Pulsa **Guardar fragmento** o **Ctrl + Alt + G** con ClipZone Live enfocado. El historial muestra la duración real que se guardó. Cada fragmento aparece en **Mis vídeos** y se puede abrir en Whisper, subtítulos o el editor de exportación.
5. Pulsa **Detener captura** para conservar el último búfer durante esa sesión. Puedes guardarlo también cuando finaliza el directo o falla la reconexión. El búfer se retira al iniciar otro canal o cerrar el servidor. Los clips importados se administran desde **Mis vídeos**.

Si la pestaña está cerrada, puedes guardar desde otra terminal de PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/live/direct/captures' -ContentType 'application/json' -Body '{"seconds":30}'
```

Se admite una captura directa simultánea. Streamlink usa sus conectores integrados en modo público, sin navegador ni credenciales de usuario. Los bloqueos de la plataforma se presentan como errores. FFmpeg conserva video y audio por copia de flujos cuando es posible. Guarda en MP4 y prueba MKV si el contenedor MP4 resulta incompatible. El inicio de un fragmento se ajusta a un segmento completo en un fotograma clave, por lo que puede durar algo menos que la duración elegida.

El búfer conserva una ventana de hasta cinco minutos más el segmento de corte cuando es necesario. El límite de disco es **512 MiB** por defecto. Se retiran los segmentos antiguos y se reservan **128 MiB** libres. La captura realiza hasta **tres reintentos** por sesión. Cuando se restablece la conexión, el nuevo material inicia un búfer continuo, sin concatenar el hueco con los segmentos anteriores.

**YouTube Live.** El conector de Streamlink contempla directos HLS y formatos con audio y video separados. Se mantiene fuera de la captura directa hasta validar esas variantes y las condiciones de acceso. Para emisiones autorizadas sigue disponible el método OBS. [Conectores de Streamlink](https://streamlink.github.io/latest/plugins.html) · [Conector de YouTube](https://github.com/streamlink/streamlink/blob/8.6.3/src/streamlink/plugins/youtube.py) · [Segmentador de FFmpeg](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment).

### Método alternativo con OBS Studio

ClipZone Live guarda fragmentos puntuales de transmisiones que tienes autorización para capturar. OBS mantiene el búfer de repetición en su equipo. ClipZone solicita un guardado solo al pulsar el botón o el atajo. El resto del editor funciona aunque OBS esté cerrado.

1. Abre **ClipZone Live → OBS Studio → Configurar OBS Studio** para ver la carpeta de repeticiones. Por defecto es `data/live-inbox`. Si ya usas otra carpeta para grabar con OBS, indícala mediante `CLIPZONE_OBS_REPLAY_DIR` con una ruta absoluta en un disco local.
2. En **OBS → Herramientas → Configuración del servidor WebSocket**, habilita el servidor de OBS WebSocket 5. El puerto predeterminado es **4455**. Mantén la autenticación de OBS activada y proporciona su contraseña al servidor de ClipZone desde la misma terminal de PowerShell:

   ```powershell
   $env:CLIPZONE_OBS_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'Contraseña de WebSocket de OBS' -AsSecureString)).Password
   .\scripts\start.ps1 -Open
   ```

3. En **OBS → Ajustes → Salida**, usa la misma carpeta como ruta de grabación, activa el **búfer de repetición** y fija **Tiempo máximo de repetición** en **90 s** para disponer de las tres duraciones. Si cambias la configuración, reinicia el búfer. Para evitar un proxy adicional, puedes usar MP4 con vídeo H.264 y audio AAC. MKV también se puede importar.
4. Pulsa **Iniciar búfer de repetición** en OBS. En ClipZone Live comprueba el estado y elige **30, 60 o 90 s**. Pulsa **Guardar fragmento** o **Ctrl + Alt + G** con ClipZone Live enfocado. Si el búfer aún no se ha llenado, se importa el tiempo disponible y el historial muestra la duración real.
5. Desde **Historial de capturas**, abre el vídeo en el editor, ve a **Analizar con Whisper**, **Subtítulos** o **Ir a exportar**. Whisper se inicia bajo demanda y usa los modelos ya instalados. Las capturas aparecen también en **Mis vídeos**.

La integración se conecta a OBS en `127.0.0.1`. ClipZone conserva la repetición que OBS escribe en su carpeta y administra su propia copia. Cuando hace falta recortar, FFmpeg procesa solo el final del fragmento con dos hilos de codificación. El panel informa del espacio libre en los dos destinos y requiere al menos 128 MiB libres antes de solicitar el guardado. Si retiras una captura de la biblioteca, el historial mantiene su entrada y la identifica como retirada. El atajo funciona con ClipZone Live enfocado en el navegador.

Consulta la [guía de OBS Studio](https://obsproject.com/kb/OBS-Studio-Overview) y el [protocolo OBS WebSocket 5](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).

## Biblioteca, exportaciones y almacenamiento

En **Mis vídeos** y **Exportaciones**, pulsa **Eliminar** en un elemento o marca varios y pulsa **Eliminar selección**. Por defecto se quita el registro y se conservan los archivos en disco. Si seleccionas **Borrar los archivos administrados**, también se eliminan las copias de ClipZone. Quitar un vídeo retira sus análisis y vistas previas del historial. Los clips exportados asociados se conservan. Los archivos originales que importaste desde fuera de ClipZone permanecen en su ubicación.

Los procesos activos deben terminar o cancelarse antes del borrado. Si Windows mantiene un archivo bloqueado, cierra la aplicación que lo usa y vuelve a intentarlo. Los resultados se informan por elemento. SQLite registra las operaciones físicas para recuperar movimientos incompletos y liberar archivos en cuarentena al reiniciar o limpiar.

**Almacenamiento** muestra cantidades, tamaño de vídeos y clips, transcripciones, temporales, SQLite y pesos de Whisper. Las transcripciones son parte de SQLite y no se suman dos veces al total. Las copias conservadas tras quitar un registro siguen contando en el disco. **Limpiar temporales** elimina vistas exactas inactivas, restos de análisis o subidas y reintenta la cuarentena. Conserva las transcripciones disponibles y los archivos en uso.

## Fase 2: transcripción y clips automáticos

La edición manual sigue funcionando sin instalar IA. Para activar el análisis, primero instala el proyecto y después ejecuta **una sola vez**, desde su carpeta:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-ai.ps1 -DependenciesOnly
```

Esto instala `openai-whisper` y PyTorch. En **Momentos con IA** selecciona un modelo y pulsa **Instalar** para descargarlo y verificar su SHA256. Tiny ocupa aproximadamente 76 MB, Base 145 MB y Small 484 MB. Para instalar desde PowerShell, usa `-Model base`, `-Model tiny` o `-Model small` en lugar de `-DependenciesOnly`. Los modelos se guardan en `models/whisper`, excluido de Git. Se necesita conexión para instalar y descargar; **el análisis y la exportación se ejecutan localmente, sin claves ni APIs de pago**. La descarga presenta progreso en bytes y porcentaje cuando el servidor anuncia el tamaño. Puedes cancelarla desde el panel.

1. Importa un vídeo con voz y selecciona **Momentos con IA** en la barra lateral.
2. Elige un modelo instalado, el idioma (o detección automática), duración mínima/máxima y número máximo de propuestas. Se admiten intervalos de 1 a 180 segundos y hasta 20 propuestas.
3. Pulsa **Analizar vídeo**. El progreso recorre extracción de audio, carga del modelo, transcripción y ranking; puedes cancelar o seguir usando el editor.
4. Revisa la transcripción y las tarjetas puntuadas. **Revisar en editor** carga el intervalo para escucharlo y ajustar un clip manualmente.
5. Marca varias tarjetas, o **Seleccionar todos**. Configura la plataforma, formato, resolución y encuadre en el editor; esos ajustes se aplicarán a todo el lote.
6. Pulsa **Generar seleccionados**. Cada MP4 aparece en Exportaciones con su progreso, vista previa y descarga.

Los análisis y sus propuestas sobreviven a reinicios. El selector **Análisis guardados** permite recuperar un resultado anterior. Si mantienes el mismo modelo e idioma, **Reutilizar transcripción** permite cambiar duraciones o cantidad de propuestas sin ejecutar Whisper de nuevo. Para volver a inferir el audio, desmarca esa opción.

Tiny, Base y Small pueden coexistir. El gestor comprueba el SHA‑256 de cada modelo y guarda una descarga como `.pt` solo cuando está completa y verificada. Reintenta fallos transitorios de red y descargas truncadas. Una instalación interrumpida puede recuperar un temporal completo con SHA‑256 válido. Para comprobar los modelos sin descargarlos, ejecuta desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe scripts/download_model.py --verify
```

Si falla una instalación, el panel muestra una causa específica. En `data/whisper-downloads.log` (o en la carpeta definida por `CLIPZONE_DATA_DIR`) quedan los intentos, los códigos de error, los bytes recibidos y el resultado de verificación.

La configuración inicial para el Ryzen 5 4500 es **Base, CPU con 4 hilos, 15–45 s, ocho propuestas y reutilización activada**. Puedes limitar a dos hilos para dejar más CPU libre o elegir seis para darle prioridad al análisis. Para comparar Base y Small, analiza el mismo vídeo con el mismo idioma y número de hilos, desmarca **Reutilizar transcripción** y alterna los resultados en **Análisis guardados**. Cada análisis nuevo muestra su tiempo de ejecución. La precisión se compara revisando el texto junto al audio. El motor usa CPU y conserva los pesos oficiales y las transcripciones existentes. Se revisaron los requisitos de [faster-whisper](https://github.com/SYSTRAN/faster-whisper#requirements) y [CTranslate2](https://opennmt.net/CTranslate2/installation.html) para Python 3.12 en Windows x64. La aplicación usa el motor actual de Whisper y su adaptador permite evaluar otro motor en el futuro.

La puntuación es editorial (0–100), calculada localmente a partir de la transcripción de Whisper: densidad de voz, preguntas o ideas con gancho, cierre de frase y energía relativa del audio. No se usa un LLM remoto ni se predice viralidad. El ranking inicial reconoce señales léxicas principalmente en español e inglés. Puede devolver menos propuestas si no hay suficientes fragmentos distintos. Un vídeo sin audio se rechaza; silencio o habla insuficiente pueden producir una transcripción vacía. Revisa el contexto y corrige los límites en el editor antes de compartir.

Facebook Reels es la cuarta plataforma, con preset editable 9:16, 30 s, margen superior del 12 % e inferior del 22 %. Son guías de edición, no una validación de las normas de Facebook. También se puede exportar manualmente a esta plataforma.

Para generar una muestra hablada sin descargar contenido, usa la voz integrada de Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\create_ai_demo.ps1
```

Importa `demo/phase2-spoken-demo.mp4`, elige **Inglés** y prueba duraciones de 3 a 12 segundos. El script requiere una voz de Windows instalada; la muestra y su WAV permanecen fuera de Git.

## Subtítulos dinámicos, traducción y campañas

1. Importa y selecciona un vídeo. En **Momentos con IA**, conserva **Detectar automáticamente** o indica manualmente el idioma del audio. Ejecuta el análisis con un modelo ya instalado. El panel muestra el idioma detectado o indica la selección manual. El historial se reutiliza solo si coinciden el vídeo, el modelo y el modo o idioma solicitado.
2. Abre **Subtítulos dinámicos**, selecciona un análisis completado y pulsa **Generar desde Whisper**. Puedes añadir segmentos manualmente. Ajusta tiempos en segundos del vídeo original, corrige texto, divide, combina, elimina o usa búsqueda y reemplazo. **Guardar subtítulos** guarda las ediciones en otra pista de SQLite. La transcripción de Whisper queda disponible en el historial.
3. Elige **Clásico**, **Hormozi**, **Karaoke** o **Minimalista**. Ajusta tipografía, colores, contorno, sombra, fondo, alineación, posición en la zona segura y palabras por línea. Los segmentos corregidos o traducidos conservan sus tiempos de frase. Cuando las palabras cambian, su resaltado se reparte dentro del intervalo en vez de usar marcas de palabras distintas.
4. Elige **Idioma de los subtítulos** para trabajar en una traducción separada. Escribe o corrige cada traducción o importa un SRT/VTT con la misma cantidad y orden de segmentos. La aplicación usa el texto importado y conserva los tiempos de la pista de origen. Al exportar ese idioma se omiten los segmentos sin traducción.
5. En **Gráficos y plantillas**, importa tus PNG transparentes y añade textos. Arrastra cada capa en **Encuadre en directo**, usa las flechas con la capa enfocada o introduce la posición numérica. Controla tamaño, opacidad y tiempos relativos a cada clip. **Todo el clip** mantiene la capa durante el fragmento completo. Límites por PNG: 16 MB y 4096 × 4096.
6. Aplica un ejemplo de **Campaña de YouTube** o **Campaña de Kick**, asigna tu propio logo y edita los mensajes. Guarda la plantilla con tus ajustes. Al usar **Generar seleccionados** en Momentos con IA, cada clip del lote recibe esa composición. Las plantillas guardan ajustes y referencias a PNG, mientras que cada vídeo aporta su propia pista de subtítulos.
7. Activa **Activar subtítulos** para incrustarlos. Marca **Archivos SRT y VTT** si también quieres descargas separadas. Esto funciona en combinación con los subtítulos incrustados o por separado. Usa **Vista exacta** para revisar el MP4 antes de exportar. Guarda las ediciones de texto y tiempo para regenerar **Vista exacta**.

**Encuadre en directo**, **Vista exacta** y el MP4 dibujan los subtítulos con FFmpeg y libass en el mismo lienzo de salida. La posición y los márgenes superior e inferior se miden sobre todo el lienzo. Esto incluye las bandas de **Ajustar completo** y el fondo de **Fondo difuminado**. Un cambio de estilo, idioma, zona segura o revisión invalida **Vista exacta** y permite regenerarla con los ajustes actuales.

**Instalación opcional de Argos Translate.** La edición e importación están listas en la instalación base. ClipZone puede invocar un entorno local de Argos que ya tenga el par directo instalado, como es→en o en→es. Se verificaron Python 3.12 x64 en este equipo y los requisitos publicados de Argos y CTranslate2 para Windows. El adaptador usa CPU con cuatro hilos, un proceso a la vez y segmentos por página. La inferencia real de Argos requiere los paquetes de cada dirección. [Argos Translate](https://argos-translate.readthedocs.io/en/latest/index.html) · [CTranslate2 para Windows](https://opennmt.net/CTranslate2/installation.html)

Si ya tienes ese entorno, configura su ejecutable desde PowerShell antes de iniciar ClipZone:

```powershell
$env:CLIPZONE_ARGOS_PYTHON = 'C:\ruta\argos-venv\Scripts\python.exe'
.\scripts\start.ps1 -Open
```

Selecciona un idioma distinto al audio y pulsa **Traducir página con Argos**. El adaptador verifica el par instalado y procesa solo audio ya transcrito. El proceso utiliza los archivos locales existentes. Puedes seguir importando o editando las traducciones manualmente en cualquier instalación.

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

Para las pruebas completas de navegador, con el puerto 8013 libre:

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

Playwright inicia y cierra una API aislada; sus datos van a `test-results/e2e-data`, sin usar tu biblioteca. Verifica importación, recorte, reproducción, encuadre, render, vista previa, descarga, persistencia, tamaño móvil y diálogos. Capturas de pruebas en `test-results/screenshots` y trazas en `test-results/browser`.

La suite también comprueba análisis persistidos, cancelación, cache de transcripción, puntuación, validación de selecciones y generación múltiple. Las pruebas rápidas sustituyen únicamente la inferencia para ser reproducibles; la extracción y los renders son reales. La prueba Python marcada `whisper` ejecuta el modelo real cuando Tiny y la demo hablada están instalados; de lo contrario se omite con un motivo explícito.

Para incluir también el flujo de IA real en el navegador, después de instalar Tiny y generar la muestra:

```powershell
# Desde frontend, con el puerto 8013 libre:
$env:CLIPZONE_BROWSER_CHANNEL = 'msedge'
$env:CLIPZONE_REAL_AI_E2E = '1'
npm run test:e2e
```

## Datos y configuración

```text
data/
  clipzone.sqlite3  # biblioteca y trabajos
  uploads/          # copias de los originales
  previews/         # proxies de reproducción
  thumbnails/       # JPEG
  exports/          # MP4 finales
  analysis/         # PCM/JSON temporales; se limpian al terminar
  drafts/           # vistas exactas renderizadas; se pueden limpiar
  quarantine/       # archivos transitorios del borrado recuperable
  graphics/         # archivos PNG administrados para capas y plantillas
```

| Variable de entorno | Uso |
|---|---|
| `CLIPZONE_MODEL_DIR` | Carpeta de modelos Whisper; predeterminado: `models/whisper` |
| `CLIPZONE_DATA_DIR` | Carpeta alternativa para datos locales |
| `CLIPZONE_FFMPEG` | Ruta completa a `ffmpeg.exe` |
| `CLIPZONE_OBS_PORT` | Puerto local del servidor WebSocket de OBS, predeterminado `4455` |
| `CLIPZONE_OBS_PASSWORD` | Contraseña del servidor WebSocket de OBS, leída solo por el backend |
| `CLIPZONE_OBS_REPLAY_DIR` | Carpeta local de repeticiones, predeterminada `live-inbox` dentro de `CLIPZONE_DATA_DIR` |
| `CLIPZONE_DIRECT_BUFFER_MB` | Límite de la carpeta temporal de captura directa en MiB. Valor predeterminado `512` y rango de 32 a 8192 |
| `CLIPZONE_FFPROBE` | Ruta completa a `ffprobe.exe` |
| `CLIPZONE_MAX_UPLOAD_GB` | Límite entero en GB; predeterminado: `20` |

Establécelas en PowerShell antes de iniciar. Haz copia de `data` con el servidor detenido. La biblioteca y las exportaciones sobreviven a reinicios; las decisiones de edición sin exportar no se guardan como borradores. Los ajustes de cada exportación se conservan. Los trabajos interrumpidos por un cierre inesperado se marcan como fallidos al reiniciar y pueden volver a editarse. Usa la opción de borrado físico explícita cuando quieras recuperar el espacio de los originales importados o las exportaciones.

El servidor escucha exclusivamente en `127.0.0.1`; los hosts y orígenes admitidos se limitan al desarrollo local. No está diseñado como servicio público ni multiusuario. FFmpeg se invoca con argumentos separados, sin shell, y se restringen los protocolos de entrada a archivos y pipes locales.

## Arquitectura y siguientes fases

Consulta [la arquitectura](docs/ARQUITECTURA.md), [el plan de fases](docs/FASES.md) y [la validación](docs/VALIDACION.md).

En la fase 4, el encuadre automático por rostros podrá usar el mismo render que **Vista exacta** y **Exportar**. El ranking de momentos, el análisis contextual y la gestión de campañas e ingresos tienen ciclos distintos y pueden evolucionar como módulos independientes.

```text
backend/app/
  config.py           # rutas, límites, detección de binarios
  database.py         # persistencia SQLite
  models.py           # validación y dimensiones
  main.py             # API, importación y streaming
  services/media.py   # FFprobe, encuadre y comandos FFmpeg
  services/jobs.py    # cola, progreso y cancelación
  services/analysis.py # cola de análisis y cancelación del subproceso
  services/storage.py  # rutas administradas, borrado recuperable y limpieza
  captions.py         # edición, persistencia y recorte de pistas
  composition.py      # estilos ASS, capas de texto y archivos SRT/VTT
  campaigns.py        # PNG locales y plantillas
  translation.py     # importación y adaptador Argos local
  ai/contracts.py     # palabras y contratos de IA
  ai/whisper_local.py # adaptador al modelo local
  ai/worker.py        # inferencia por bloques de 60 s en CPU
  ai/detector.py      # candidatos, puntuación y eliminación de duplicados
  ai/routes.py        # análisis, resultados y generación múltiple
  ai/model_files.py   # descarga explícita y verificación de modelos
frontend/src/
  App.tsx             # editor, biblioteca y exportaciones
  components/AnalysisPanel.tsx # configuración, propuestas, selección y transcripción
  api.ts              # cliente tipado y subida con progreso
  styles.css          # diseño adaptable negro / verde neón
  readability.css     # tipografía, contraste y controles de edición
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
