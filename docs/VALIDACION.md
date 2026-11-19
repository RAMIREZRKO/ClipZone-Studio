# Validación de ClipZone Studio

## Versión 0.2 — fases 1 y 2

Resultado final: **45 pruebas Python aprobadas, sin omisiones, y 4 pruebas de navegador aprobadas**. La compilación TypeScript/Vite, `pip check`, el diagnóstico de dependencias y la sintaxis de los cinco scripts PowerShell también son correctos.

Se conserva la validación de la fase 1 detallada debajo. La fase 2 añadió:

- Whisper `20250625` y PyTorch `2.15.0+cpu`; modelo multilingüe Tiny descargado del registro oficial y verificado por SHA256.
- Inferencia real, sin sustituir el motor, sobre una muestra hablada de aproximadamente 38 segundos generada con la voz local de Windows. Resultado: **95 palabras con marcas de tiempo y cinco propuestas puntuadas**.
- Generación de dos propuestas como MP4 de Facebook Reels, comprobando vídeo H.264, audio, 480×854 y descarga. El navegador también reproduce el resultado real.
- Pruebas de configuración inválida, falta de audio/modelo, historial persistido, recuperación tras interrupción, cancelación, reutilización de transcripción y selección de IDs válidos.
- Ranking con límites de duración, señales explicables, límites de puntuación, reducción de solapamientos y ausencia de propuestas inventadas cuando no hay habla utilizable.
- Recorrido real de UI: elegir Facebook Reels, analizar en inglés, revisar transcripción, seleccionar dos tarjetas, cargarlas en el editor, generar el lote y previsualizar los MP4. Se comprobó también la reutilización al volver de Exportaciones.
- Inspección de las capturas del panel de IA en escritorio y móvil, manteniendo el diseño negro/verde y sin desbordamientos.

Las pruebas rápidas de análisis sustituyen solo la inferencia mediante una fixture de pruebas; extracción de audio, procesos, SQLite y render siguen siendo reales. La prueba marcada `whisper` y la de navegador con `CLIPZONE_REAL_AI_E2E=1` ejecutaron el modelo Tiny real en esta entrega.

Capturas adicionales: [Momentos con IA](capturas/momentos-ia.png) y [Momentos con IA en móvil](capturas/momentos-ia-movil.png). Los modelos y las muestras de vídeo/audio siguen excluidos de Git.

Límites: no se ha medido calidad en un corpus amplio ni rendimiento de Base/Small, GPU o vídeos de varias horas. El ranking es heurístico sobre texto generado por Whisper y señales de audio; no predice viralidad. La inferencia se divide en bloques de 60 s, por lo que las frases en sus límites pueden requerir ajuste manual. Los subtítulos dinámicos y el seguimiento de sujetos continúan pendientes.

## Validación original de la fase 1

Entrega verificada el **17 de noviembre de 2026** (America/Bogota), en Windows x64. Se usaron vídeos sintéticos generados localmente con FFmpeg; no se importó ni modificó ningún vídeo personal del equipo.

## Entorno comprobado

| Dependencia | Versión |
|---|---|
| Python | 3.12.14, entorno `.venv` |
| Node.js | 24.15.0 |
| npm | 11.12.1 |
| FastAPI | 0.163.2 |
| Uvicorn | 0.54.0 |
| FFmpeg / FFprobe | 9.0.2 essentials, Gyan, Windows x64 |
| React / ReactDOM | 19.3.1 |
| Vite | 7.3.8 |
| TypeScript | 5.9.3 |
| Playwright | 1.65.1, navegador Microsoft Edge |

`scripts/doctor.py` comprobó los módulos Python, la ejecución de ambos binarios y los codificadores `libx264` y AAC. `pip check` no encontró dependencias rotas. `npm ls --depth=0` encontró todas las dependencias directas. Se incluyeron `backend/requirements.lock.txt` y `frontend/package-lock.json` para reproducir el entorno.

SHA256 del ZIP de FFmpeg utilizado: `60F467265B1E312373DBCD92200C2618A74850F98D3D078E94296BB3FA2047BA`. La URL del instalador apunta a la distribución vigente de Gyan y puede ofrecer una versión posterior en futuras instalaciones.

## Pruebas automatizadas

### Backend: 27 casos

- Ocho exportaciones reales: 9:16, 1:1, 4:5 y 16:9, cada una con imagen completa y recorte para llenar.
- Dimensiones, duración del intervalo, H.264, AAC y píxeles `yuv420p`, comprobados con FFprobe.
- Miniatura JPEG, reproducción por rangos HTTP 206 y descarga con nombre de archivo.
- Persistencia de biblioteca, original externo sin cambios y ausencia de rutas internas en respuestas.
- Rechazo de archivos inválidos, vacíos, extensiones ajenas, exceso de tamaño y ajustes fuera de rango.
- MKV con proxy, fuentes sin audio y normalización de píxeles anamórficos a SAR 1:1.
- Cancelación de trabajos activos y pendientes; recuperación y limpieza tras interrupción.
- Restricción de orígenes y manejo de identificadores inexistentes.

La suite pasa sin omitir renders. Starlette emite un aviso de obsolescencia sobre el adaptador de pruebas `httpx`; no afecta la aplicación ni los resultados. Su migración a `httpx2` puede hacerse al actualizar la infraestructura de pruebas.

### Navegador: 3 casos

- Importar la demo de 12 segundos, seleccionar 1–3 s, elegir 1:1, mover el foco y exportar a 480×480.
- Verificar proporción cuadrada de la previsualización y centrado al volver a imagen completa.
- Reproducir el intervalo y comprobar que se detiene en el segundo 3.
- Abrir el MP4 terminado, verificar sus dimensiones y duración, y descargarlo correctamente.
- Confirmar biblioteca persistente tras recargar y ausencia de errores JavaScript.
- Salir durante la reproducción, volver al editor y reproducir de nuevo.
- Verificar disposición de 390 píxeles sin desbordamiento, controles completos y cierre de diálogos con Escape.
- Verificar que la IA y los subtítulos se identifican como fases pendientes.

### Compilación y scripts

- TypeScript y `vite build`: correctos.
- Sintaxis de los tres scripts PowerShell: correcta.
- `compileall` de Python: correcto.
- El frontend compilado se sirve desde FastAPI, sin requerir Vite para usar la aplicación.

## Revisión visual

Se inspeccionaron las capturas reales en escritorio y móvil. Se corrigieron el tamaño proporcional de la vista previa, controles cortados en móvil y la disposición de los paneles. Capturas de la entrega:

- [Editor sin vídeo](capturas/editor-vacio.png)
- [Editor con vídeo](capturas/editor-con-video.png)
- [Exportaciones](capturas/exportaciones.png)
- [Vista móvil](capturas/editor-movil.png)

## Alcance de esta validación

Los renders de integración utilizan muestras cortas a 480p; el editor ofrece también 720p y 1080p. No se ha hecho una prueba de carga con archivos cercanos al límite de 20 GB, todos los códecs existentes, HDR o GPU. Las exportaciones utilizan CPU. La reproducción y el color pueden variar según el decodificador del navegador y la fuente; el MP4 final puede previsualizarse para su revisión.

En la fase 1 Whisper solo disponía de un adaptador. Su implementación y validación real están documentadas en la sección de la versión 0.2. Los subtítulos dinámicos y el seguimiento de sujetos siguen pendientes en [FASES.md](FASES.md).
