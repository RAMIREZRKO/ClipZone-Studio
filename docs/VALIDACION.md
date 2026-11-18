# Validación de la fase 1

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

Whisper tiene un adaptador opcional y contratos, pero no se ha instalado ni probado en esta fase. La detección de momentos, los subtítulos dinámicos y el seguimiento de sujetos no están implementados. El plan de aceptación de esas funciones está en [FASES.md](FASES.md).
