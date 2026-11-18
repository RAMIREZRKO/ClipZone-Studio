# Plan de desarrollo

## Fase 1 — Editor local funcional (implementada)

- Importación, metadatos, miniaturas y biblioteca persistente.
- Entrada y salida precisas, reproducción del intervalo y duraciones rápidas.
- Encuadre sin deformación: bandas o recorte con foco manual.
- 9:16, 1:1, 4:5, 16:9; 480/720/1080 en el lado corto.
- Presets de plataforma y guías de zona segura editables.
- Render MP4 H.264/AAC en cola con progreso y cancelación.
- Revisión y descarga del archivo final.
- Instalador, diagnóstico, demo, pruebas de integración y de navegador.

Criterio de aceptación: importar un archivo, elegir 1–3 s, exportarlo, comprobar duración y dimensiones con FFprobe y reproducir/descargar el MP4 desde la interfaz.

## Fase 2 — Whisper y selección asistida (pendiente)

1. Instalar Whisper opcionalmente y permitir elegir un modelo local, mostrando tamaño y recursos necesarios antes de descargarlo.
2. Extraer audio mono de 16 kHz, transcribir con marcas de tiempo por palabra y persistir el resultado.
3. Implementar detección local basada inicialmente en estructura de frases, pausas, densidad de voz y señales de energía; añadir un modelo semántico local opcional si los recursos lo permiten.
4. Proponer fragmentos puntuados con una razón legible, duraciones configurables y revisión humana. No prometer una predicción de viralidad.
5. Seleccionar propuestas y generar varios clips a través de la cola ya existente.

Existe un adaptador `WhisperLocal` que carga un archivo de pesos explícito; falta conectarlo a trabajos, almacenamiento, progreso y UI. `requirements-ai.txt` no se instala en el MVP. La integración de Whisper no está probada en esta entrega.

Criterio de aceptación: transcribir una muestra en español sin API, verificar que las palabras respetan el audio y que cada propuesta puede corregirse antes de renderizar. Probar CPU y cancelación, y medir RAM/tiempo con modelos tiny/base/small.

## Fase 3 — Subtítulos dinámicos (pendiente)

- Editor de transcripción y agrupación de frases.
- Estilos ASS con resaltado por palabra, tamaño, contraste y márgenes seguros.
- Quemado de subtítulos en FFmpeg y exportación opcional de SRT.
- Fuentes locales con licencia adecuada y vista previa del render.

Criterio de aceptación: texto sincronizado en clips que no empiezan en cero, acentos correctos, saltos de línea legibles y márgenes respetados en los cuatro formatos. Probar que cambiar el texto no introduce instrucciones en los filtros.

## Fase 4 — Reencuadre inteligente y flujo ampliado (pendiente)

- Detección y seguimiento local de rostros/sujetos.
- Suavizado del movimiento de recorte y corrección manual por puntos.
- Exportaciones por lotes, duplicación de presets y borradores persistentes.
- Empaquetado Windows con instalador y revisión de licencias de FFmpeg/modelos.

Criterio de aceptación: seguimiento estable entre escenas, ausencia de estiramiento, corrección manual y exportaciones reproducibles en un equipo Windows limpio.

No se integran servicios de pago en estas fases. Cualquier integración remota futura será una decisión explícita del proyecto.
