# Diagnóstico de Cumplimiento: ISO/IEC 27001:2022 + Ley N° 21.719

**Una herramienta que traduce dos marcos normativos densos — un estándar
internacional de seguridad de la información y la nueva ley chilena de
protección de datos — en un cuestionario de 16 preguntas que cualquier
organización puede responder en menos de 20 minutos.**

🔗 [Ver la aplicación en funcionamiento](https://iso27001-tracker.streamlit.app/)

---

## El problema

En Chile, la entrada en vigencia de la Ley N° 21.719 obliga a las
organizaciones a repensar cómo tratan datos personales — pero muchas ya
vienen implementando (o intentando implementar) controles de seguridad de
la información bajo ISO/IEC 27001. En la práctica, **son dos ejercicios de
cumplimiento que casi nadie conecta entre sí**, a pesar de que se
superponen en un porcentaje importante.

Esa superposición fue el punto de partida: construir un crosswalk
propio entre los 93 controles del Anexo A de ISO 27001 y las obligaciones
de la Ley 21.719, y convertirlo en una herramienta de autodiagnóstico que
cualquier organización —sin equipo legal ni de seguridad dedicado— pueda
usar para saber, en una primera aproximación, dónde está parada.

## Qué hace

1. Un cuestionario corto (16 preguntas, con su lenguaje ya traducido a
   algo entendible sin formación legal ni técnica previa) recoge el estado
   real de la organización.
2. Esas respuestas se expanden automáticamente contra los 93 controles del
   Anexo A, ponderando cada uno según su vínculo real con la Ley 21.719
   (no todos los controles pesan igual frente a la ley — esa ponderación
   es, en el fondo, análisis legal convertido en regla de negocio).
3. Se generan dos informes descargables en PDF — uno con enfoque legal
   (estructura inspirada en los informes de evaluación de impacto tipo
   AEPD/GDPR) y otro con enfoque ISO (una Declaración de Aplicabilidad
   simplificada) — con brechas priorizadas y un plan de acción sugerido.
4. Un asistente conversacional (RAG) resuelve dudas puntuales sobre los
   controles y los términos técnicos del cuestionario mientras se responde.

## Mi rol en este proyecto

Este proyecto nace de mi trabajo como abogada: el crosswalk entre los 93
controles ISO y la Ley 21.719, la lógica de ponderación (qué controles
son un vínculo "fuerte" con la ley y cuáles solo estructural), la
redacción de las plantillas de informe y todos los supuestos
metodológicos del diagnóstico son análisis legal propio.

La implementación técnica la construí con asistencia de IA (Claude, de
Anthropic), dirigiendo el desarrollo de principio a fin: definí la
arquitectura de la solución, tomé las decisiones de producto en cada
paso, probé cada funcionalidad, y resolví yo misma el despliegue
completo — incluyendo la configuración de la nube, el control de
versiones con Git/GitHub, y la depuración de errores en producción. No
soy ingeniera de software, pero este proyecto refleja algo que creo cada
vez más relevante en el mundo legal-tech: **la capacidad de traducir
criterio legal en un producto funcional real**, usando las herramientas
de IA disponibles hoy para cerrar la brecha con la implementación técnica.

## Sobre mí

Soy abogada, con Diplomado en Protección de Datos Personales y cursos en
Ciberseguridad e Inteligencia Artificial y actualmente trabajo como legal
solutions architect. Este proyecto es mi forma de explorar en la práctica
la intersección entre esas tres áreas — no como ejercicio académico, sino
como una herramienta que organizaciones reales podrían usar.

## Cómo está construido

Streamlit + Qdrant (búsqueda semántica local) + Groq (modelo de lenguaje
para el chatbot) + Jinja2 (generación de informes). El detalle completo de
arquitectura, instalación y ejecución está en [`README_TECNICO.md`](./README_TECNICO.md).

## Aviso

Esta es una herramienta de **pre-diagnóstico orientativo**. No reemplaza
una auditoría de cumplimiento formal, una certificación ISO, ni asesoría
legal profesional caso a caso.

---

📬 ¿Preguntas o comentarios sobre el proyecto? [abogada.gbarrientos@gmail.com](mailto:abogada.gbarrientos@gmail.com)
