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

## Fase 2 — Whisper y selección asistida (implementada)

- Instalación explícita de Whisper/PyTorch y Tiny, Base o Small, con verificación SHA256 del modelo oficial.
- Extracción local de audio PCM mono a 16 kHz; inferencia CPU por bloques de 60 s y palabras con tiempos.
- Cola independiente con progreso, cancelación real del proceso y recuperación tras interrupciones.
- Análisis persistidos, historial y reutilización de transcripción para ajustar las propuestas.
- Ranking editorial de 0 a 100 por densidad de voz, preguntas/ideas con gancho, cierre y energía relativa. Sin predicción de viralidad.
- Duraciones de 1–180 s, hasta 20 propuestas, reducción de duplicados y selección múltiple.
- Revisión en el editor y generación de varios MP4 con la cola existente.
- Facebook Reels como cuarta plataforma, conservando las otras tres y el modo libre.

Verificado con inferencia real de Whisper Tiny en CPU: la muestra hablada produjo 95 palabras y cinco propuestas. Se exportaron dos propuestas a Facebook Reels con dimensiones y audio comprobados. Las pruebas rápidas también cubren errores, reutilización y cancelación. Base/Small están disponibles para instalar, sin benchmark en esta entrega. La revisión manual del contexto sigue siendo necesaria.

Mejoras posteriores opcionales: segmentación de habla más avanzada, un modelo semántico local y medición de calidad en más idiomas y estilos de vídeo.

## Fase 3 — Subtítulos dinámicos, traducción y campañas

- Detección automática del idioma del audio por defecto, con selección manual e historial compatible.
- Pistas editables a partir de palabras y tiempos de Whisper, con edición, división, combinación, borrado y sustitución de texto.
- Clásico, Hormozi, Karaoke y Minimalista, con estilos configurables y zonas seguras.
- Traducciones por idioma con importación SRT/VTT, edición y un adaptador para Argos local cuando el par está instalado.
- Capas PNG y texto, arrastre, escalado, opacidad y visibilidad por intervalo del clip.
- Plantillas guardadas y ejemplos de YouTube y Kick con espacios para los logos del usuario.
- FFmpeg compartido entre vista exacta y MP4, SRT/VTT opcionales y aplicación de plantillas a generación múltiple.

## Fase 4 — Reencuadre inteligente y flujo ampliado (pendiente)

- Detección y seguimiento local de rostros/sujetos.
- Suavizado del movimiento de recorte y corrección manual por puntos.
- Ampliar las exportaciones por lotes, duplicación de presets y borradores persistentes.
- Empaquetado Windows con instalador y revisión de licencias de FFmpeg/modelos.

Criterio de aceptación: seguimiento estable entre escenas, ausencia de estiramiento, corrección manual y exportaciones reproducibles en un equipo Windows limpio.

No se integran servicios de pago en estas fases. Cualquier integración remota futura será una decisión explícita del proyecto.
