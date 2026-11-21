# ClipZone Studio

Editor de vídeo **local para Windows**, con Python, FastAPI, FFmpeg y React + TypeScript. Interfaz en español, negro y verde neón. Inspirado en el flujo de clipping de OpusClip, con diseño propio y sin servicios de pago.

**Versión 4.0.0.** MultiStream incorpora YouTube Live junto a Kick y Twitch. El editor y la generación múltiple con Whisper mantienen subtítulos dinámicos, traducciones editables y capas promocionales para TikTok, Instagram Reels, YouTube Shorts y Facebook Reels.

## Ejecutar una instalación ya preparada

Después de instalar las dependencias y compilar el editor, haz doble clic en **`Iniciar ClipZone.cmd`** dentro de la carpeta del proyecto. Mantén abierta la terminal del servidor mientras editas. Desde PowerShell, situado en esa carpeta, también puedes ejecutar:

```powershell
.\scripts\start.ps1 -Open
```

El iniciador abre [ClipZone Studio](http://127.0.0.1:8000) cuando el servidor responde. Si ya está activa la misma versión del proyecto con tu biblioteca, abre el navegador desde esa instancia. Guarda los búferes y usa `Ctrl+C` en la terminal para cerrar el servidor antes de cambiar de versión. Si PowerShell bloquea scripts, utiliza el `.cmd` o ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Open`. Esa opción se aplica solo a ese proceso.

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

| Función | Versión 4.0.0 |
|---|---|
| Importación | MP4, MOV, MKV, WebM, AVI, M4V, MTS y M2TS; copia local; límite configurable de 20 GB |
| Biblioteca | Originales, metadatos y miniaturas persistidos en SQLite |
| Recorte | Línea de tiempo con tiradores de entrada y salida, cursor independiente, zoom de 1× a 32× y ajuste por centésimas |
| Previsualización | Original, encuadre en directo y vista exacta renderizada con los ajustes de exportación |
| Formatos | 9:16, 1:1, 4:5 y 16:9 |
| Encuadre | Imagen completa con bandas, recorte para llenar con foco manual, fondo difuminado y modo dividido Streamer + Gameplay |
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

## Encuadre Streamer + Gameplay

1. Importa un vídeo que ya incluya la cámara del streamer. En **Configura tu clip → Encuadre**, selecciona **Streamer + Gameplay**.
2. Pulsa **Editar regiones en Original**. Elige **Cámara** o **Gameplay** para mover su rectángulo y ajustar sus esquinas. También puedes escribir **X**, **Y**, **Ancho** y **Alto** en **Coordenadas del recorte**.
3. Selecciona la distribución, de 20/80 a 50/50 entre los presets, o usa **Distribución personalizada** para asignar entre 10% y 90% a la cámara. Marca **Invertir cámara y gameplay** para mostrar la cámara abajo.
4. Ajusta el zoom y el desplazamiento X/Y de cada región. Ambos paneles se llenan mediante recorte y el panel de gameplay usa exclusivamente la parte de su selección que queda fuera de la cámara. **Restablecer encuadre** recupera la distribución, el orden, el zoom y el desplazamiento iniciales y conserva los rectángulos seleccionados. Vuelve a **Encuadre en directo** para revisar ambas regiones.
5. En **Subtítulos dinámicos → Estilo y posición de subtítulos**, elige **Entre cámara y gameplay** o **Posición manual**. Ajusta la posición horizontal sobre el lienzo y la posición vertical dentro de la zona segura configurada. Los logos y textos promocionales se posicionan sobre todo el lienzo.
6. Usa **Vista exacta** para revisar el render final y **Exportar clip** para obtener el MP4. Las tres vistas parten de los mismos rectángulos y dimensiones de composición.

En **Gráficos y plantillas**, guarda el encuadre con un nombre como «Westcol · vertical», «Auronplay · directo» o «TheDonato · gameplay» después de ajustar las regiones a la fuente. Las coordenadas se guardan como proporciones del original, así que sirven también al cambiar la resolución de una fuente con la misma composición. Si la cámara cambia de posición entre emisiones, actualiza el rectángulo en la plantilla.

Las propuestas de **Momentos con IA** usan el encuadre actual para exportar varios clips. En **ClipZone Live → AutoClipping IA**, la opción **Plantilla para editar candidatos** aparece al guardar una plantilla con encuadre dividido. Selecciónala y pulsa **Editar** en un candidato para abrirlo con esa composición. La captura automática conserva el fragmento fuente y el encuadre se aplica al exportar.

## ClipZone Live 4.0

**MultiStream IA** permite registrar canales autorizados de **Kick**, **Twitch** y **YouTube Live**. En **Límite de capturas simultáneas** puedes elegir **4, 6, 8 o 10** para las tres plataformas en conjunto. Puedes registrar más canales y cerrar el navegador mientras ClipZone sigue en ejecución.

1. Instala la dependencia opcional desde la carpeta del proyecto y reinicia ClipZone:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r backend/requirements-live.txt
   .\scripts\start.ps1
   ```

2. Abre **ClipZone Live → Captura directa**, pega la URL HTTPS y pulsa **Añadir canal**. Para elegir una calidad, pulsa **Comprobar directo** en su tarjeta. La lista y los ajustes se guardan entre reinicios.
3. Pulsa **Iniciar captura** en cada tarjeta que quieras grabar. Cada canal muestra su propia comprobación, conexión, captura y estado de AutoClipping. Si un canal está desconectado, vuelve a comprobarlo antes de iniciar. Puedes guardar mientras su búfer conserve un segmento disponible.
4. En la tarjeta, elige **30, 60, 90, 120 o 300 s** y pulsa **Guardar fragmento**. **AutoClipping y atajo** selecciona el canal que recibe **Ctrl + Alt + G** y abre sus ajustes automáticos. El historial muestra la duración real y permite abrir el fragmento en el editor, Whisper, subtítulos o exportación.
5. Pulsa **Detener captura** para conservar el último búfer y guardarlo desde la tarjeta. Cuando los búferes ocupan la capacidad configurada, iniciar un canal nuevo reutiliza el búfer detenido más antiguo que esté libre. Al reducir el límite, las capturas que ya están en curso continúan y se admiten nuevas cuando haya capacidad. **Eliminar canal** retira sus ajustes y su búfer temporal. Los clips importados siguen en **Mis vídeos**.

Si la pestaña está cerrada, puedes guardar desde otra terminal de PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/live/direct/captures?streamer=kick%3Ami_canal' -ContentType 'application/json' -Body '{"seconds":30}'
```

Usa el identificador de plataforma y canal, como `kick:mi_canal` o `twitch:mi_canal`. Streamlink usa sus conectores integrados en modo público. FFmpeg conserva video y audio por copia de flujos cuando es posible. Guarda en MP4 y prueba MKV si hace falta. El inicio se ajusta a un segmento completo en un fotograma clave.

Cada búfer conserva hasta cinco minutos con un límite predeterminado de **512 MiB** en el disco seleccionado. Con ese tamaño, 4, 6, 8 y 10 búferes ocupan como máximo **2, 3, 4 y 5 GiB** respectivamente. Streamlink usa un búfer de transferencia de **16 MiB** por captura. ClipZone retira segmentos antiguos, avisa al quedar **10 GB** libres y detiene la captura al llegar a **5 GB**. La captura realiza hasta tres reintentos por sesión. Tras una reconexión, el material nuevo inicia un búfer continuo.

**YouTube Live.** Introduce un enlace `https://www.youtube.com/@canal/live`, `https://www.youtube.com/watch?v=ID`, `https://www.youtube.com/live/ID` o `https://youtu.be/ID`. ClipZone identifica el canal y conserva una sola tarjeta con sus preferencias. Añadir otro enlace del mismo canal actualiza la URL cuando su captura está detenida. Usa `@canal/live` para futuras emisiones del canal o el enlace al vídeo para una emisión concreta.

**Comprobar directo** distingue emisiones activas, programadas, finalizadas, vídeos bajo demanda y canales desconectados. La captura empieza cuando YouTube confirma que el enlace está en directo y Streamlink ofrece una calidad HLS compatible. Selecciona 720p, 1080p o 1080p60 cuando estén disponibles. Streamlink y FFmpeg combinan las pistas en las variantes HLS que entregan el audio por separado. Si el inicio de un fragmento de YouTube cae entre fotogramas clave, FFmpeg recorta al tiempo solicitado al guardar, lo que puede tardar más. ClipZone se conecta sin iniciar sesión y trata las restricciones como errores de acceso. [Conector de YouTube de Streamlink](https://github.com/streamlink/streamlink/blob/8.6.3/src/streamlink/plugins/youtube.py)

### AutoClipping IA

1. Instala el detector local de voz con `.\.venv\Scripts\python.exe -m pip install -r backend/requirements-autoclip.txt` y reinicia ClipZone. Instala **Whisper Tiny** desde **Momentos con IA** para AutoClipping.
2. Inicia una transmisión autorizada desde **Captura directa** y activa **AutoClipping IA**. Elige el modo por canal, una duración de **30, 60 o 90 s**, la sensibilidad, el umbral editorial, los segundos anteriores y posteriores, la frecuencia mínima y el máximo por hora.
3. En **Gameplay**, AutoClipping busca acciones y resultados del juego cerca de los eventos detectados. **IRL / Just Chatting** toma muestras de habla sostenida y busca pasajes con anécdotas, revelaciones, preguntas con respuesta, humor, posturas argumentadas y reacciones emocionales. **Mixto** combina ambas vías. Whisper Tiny transcribe hasta **24 s** por candidato en la cola compartida. El análisis de IRL utiliza el contexto del pasaje y funciona con conversaciones de volumen estable. Penaliza la repetición y la baja confianza de la transcripción, con señales en español e inglés. Los canales guardados como **Reacciones del streamer** pasan a **IRL / Just Chatting** y conservan sus ajustes de duración, umbral e intervalo.
4. Revisa los motivos y abre **Señales de la puntuación** para ver las señales consideradas. Las notas del historial anterior conservan su valor original. **Editar** conserva el candidato, lo incorpora a **Mis vídeos** y abre el editor.

La ventana termina tras los segundos posteriores configurados. **Segundos anteriores** indica el mínimo que debe existir antes del evento. Cada canal mantiene un candidato en proceso y hasta cuatro señales recientes como alternativas. El intervalo mínimo se cuenta desde el último candidato guardado. AutoClipping y los análisis manuales comparten una cola con una inferencia de Whisper a la vez. Las inferencias de AutoClipping usan dos hilos y pueden esperar hasta 60 s en la cola. La extracción de audio y los renders de candidatos se serializan entre canales.

Abre **Diagnóstico del canal** para consultar segmentos con audio, transcripciones, puntuación máxima, motivos acumulados de filtrado y omisión, y el último error. Los estados de cola y transcripción se muestran por separado.

La cuota de candidatos pendientes es de **5 GB** de forma predeterminada. En **AutoClipping IA → Límite de almacenamiento de candidatos** puedes elegir **1, 5, 10 o 20 GB**. La cuota es compartida entre canales y se guarda en la biblioteca. Al llenarla o reducirla, se conservan los candidatos existentes. Conservar o descartar un candidato libera su espacio temporal. El búfer directo mantiene su límite de **512 MiB** por canal.

Puedes guardar la puntuación y desactivar AutoClipping con el canal detenido o desconectado. Al detenerse la captura se cancela el análisis de ese canal y se conservan sus preferencias y los candidatos ya guardados. Si otra instancia está utilizando la biblioteca, el inicio indica la ruta en uso y cómo cerrar el servidor existente. [Detector de voz WebRTC para Python](https://github.com/daanzu/py-webrtcvad-wheels).

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

Desde **Almacenamiento → Cambiar carpeta** puedes examinar las unidades locales o escribir una ruta absoluta, por ejemplo `E:\ClipZone\data`. Elige una carpeta vacía o una que aún no exista. Detén las capturas directas y el búfer de OBS antes de programar el cambio. Luego cierra la terminal del servidor con **Ctrl+C** y vuelve a abrir ClipZone Studio.

Durante el siguiente arranque, ClipZone copia la biblioteca, verifica cada archivo con SHA-256, comprueba SQLite y actualiza sus rutas administradas. Solo después activa la nueva carpeta y retira las copias anteriores verificadas. La pantalla de almacenamiento indica el resultado o si quedaron copias antiguas. Si la verificación falla, la biblioteca original sigue disponible y puedes cancelar o reintentar el cambio. Los destinos externos al almacenamiento, como una carpeta de OBS configurada aparte o los modelos de Whisper, conservan su ubicación. Si OBS usaba `live-inbox`, actualiza la carpeta de grabaciones del perfil de OBS tras la migración.

La pantalla muestra el espacio libre y la capacidad del disco seleccionado. ClipZone avisa con **10 GB** libres, y con **5 GB** detiene las capturas directas y el búfer de OBS vinculado a su carpeta de repeticiones. El espacio de los temporales de análisis se recupera automáticamente tras 24 horas, y las vistas exactas caducan a los siete días. La caché de vistas exactas completadas admite hasta **1 GB**; se empieza por liberar las más antiguas. Los vídeos importados y las exportaciones finales se conservan.

Si arrancas con `CLIPZONE_DATA_DIR`, esa ruta fija prevalece sobre la selección de la instalación. Para una instancia aislada con su propio selector, añade `CLIPZONE_STORAGE_CONFIG` con la ruta de su archivo de configuración.

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
5. En **Gráficos y plantillas**, importa PNG transparentes y añade capas de texto. Arrastra cada capa en **Encuadre en directo**, usa las flechas con la capa enfocada o introduce la posición numérica. Límites por PNG: 16 MB y 4096 × 4096.
6. Aplica un ejemplo de **Campaña de YouTube** o **Campaña de Kick**, asigna tu propio logo y edita los mensajes. Guarda la plantilla con tus ajustes. Al usar **Generar seleccionados** en Momentos con IA, cada clip del lote recibe esa composición. Las plantillas guardan ajustes y referencias a PNG, mientras que cada vídeo aporta su propia pista de subtítulos.
7. Activa **Activar subtítulos** para incrustarlos. Marca **Archivos SRT y VTT** si también quieres descargas separadas. Esto funciona en combinación con los subtítulos incrustados o por separado. Usa **Vista exacta** para revisar el MP4 antes de exportar. Guarda las ediciones de texto y tiempo para regenerar **Vista exacta**.

**Encuadre en directo**, **Vista exacta** y el MP4 dibujan los subtítulos con FFmpeg y libass en el mismo lienzo de salida. La posición y los márgenes superior e inferior se miden sobre todo el lienzo. Esto incluye las bandas de **Ajustar completo** y el fondo de **Fondo difuminado**. Un cambio de estilo, idioma, zona segura o revisión invalida **Vista exacta** y permite regenerarla con los ajustes actuales.

### Editor de texto

- Pulsa **Agregar texto** o **Crear texto gancho**. El nombre toma el contenido de la capa. Para editar el nombre, abre **Opciones avanzadas de la capa**. También puedes duplicar, ocultar o eliminar cada capa.
- Pulsa **Insertar emoji** en **Contenido** y elige una categoría o busca por nombre. El emoji se inserta en el cursor o reemplaza la selección. Puedes pegar más emojis Unicode, incluidas banderas y secuencias de varios caracteres. El selector, **Encuadre en directo**, **Vista exacta** y el MP4 usan gráficos a color locales. [Twemoji 17.0.3 · CC BY 4.0](backend/app/emoji/ATTRIBUTION.md)
- En **Estilo**, elige uno de los seis preajustes o personaliza la tipografía, la alineación, el fondo, el contorno y la sombra. El fondo se ajusta al bloque de texto y tiene su propia opacidad. Guarda el estilo con un nombre para reutilizarlo en otra capa, incluido un gancho.
- En **Duración**, arrastra los dos extremos para fijar la aparición y la desaparición. Los segundos son relativos al inicio del clip. **Mostrar durante todo el clip** sigue la duración actual. Para escribir segundos exactos, abre **Tiempos avanzados**.
- La vista en directo genera el PNG del texto con Pillow. **Vista exacta** y la exportación usan el mismo PNG y FFmpeg lo coloca en el video. Las capas guardadas con el formato anterior conservan su estilo hasta que se edita su apariencia o contenido.

Las fuentes Montserrat, Poppins, Anton y Roboto se incluyen con sus licencias OFL. Arial e Impact se cargan desde Windows. Si faltan, ClipZone usa Roboto y Anton respectivamente. [Google Fonts, revisión de las fuentes incluidas](https://github.com/google/fonts/tree/869789e84da92782c144d83d69b64cec54905b5f/ofl)

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
| `CLIPZONE_DIRECT_BUFFER_MB` | Límite del búfer de captura directa por canal en MiB. Valor predeterminado `512` y rango de 32 a 8192 |
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
