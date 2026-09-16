# Diagnóstico ISO/IEC 27001:2022 + Ley N° 21.719 (Chile)

MVP en Streamlit que diagnostica el nivel de cumplimiento de una organización
frente al **Anexo A de ISO/IEC 27001:2022** y la **Ley N° 21.719** de
Protección de Datos Personales de Chile, a través de un cuestionario corto
(16 preguntas), un chatbot RAG de apoyo, y dos informes descargables en
PDF.

> ⚠️ **Este es un pre-diagnóstico orientativo.** No reemplaza una auditoría
> de cumplimiento formal, una Declaración de Aplicabilidad certificada, ni
> asesoría legal profesional. Ver el descargo de responsabilidad al inicio
> de cada informe generado.

---

## Índice

- [Arquitectura](#arquitectura)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Cómo funciona el diagnóstico](#cómo-funciona-el-diagnóstico)
- [Flujo del chatbot (RAG)](#flujo-del-chatbot-rag)
- [Instalación](#instalación)
- [Configuración de variables de entorno](#configuración-de-variables-de-entorno)
- [Ejecución](#ejecución)
- [Supuestos metodológicos](#supuestos-metodológicos)
- [Despliegue en Streamlit Community Cloud](#despliegue-en-streamlit-community-cloud)
- [Roadmap](#roadmap)

---

## Arquitectura

| Componente | Herramienta | Notas |
|---|---|---|
| Interfaz | [Streamlit](https://streamlit.io) | Formulario + panel de resultados + chatbot en sidebar |
| Base vectorial | [Qdrant](https://qdrant.tech) (local, embebido) | `QdrantClient(path="./qdrant_data")` — **no** Qdrant Cloud. Los datos vectorizados se versionan directamente en el repositorio (carpeta `qdrant_data/`), no como un servicio externo |
| Embeddings | [fastembed](https://github.com/qdrant/fastembed) | Modelo `intfloat/multilingual-e5-small`, registrado manualmente vía `add_custom_model()` a partir de la conversión ONNX `Xenova/multilingual-e5-small` (no viene soportado por defecto en fastembed). Se eligió fastembed en vez de `sentence-transformers` específicamente para evitar la dependencia de `torch` |
| Generación (chatbot) | [Groq API](https://console.groq.com) | Modelo configurable en `groq_service.py` (`GROQ_MODEL`). Actualmente `openai/gpt-oss-120b` — Groq retira modelos con relativa frecuencia; si ves un error `model_not_found`, revisa [console.groq.com/docs/models](https://console.groq.com/docs/models) y actualiza esa constante |
| Informes | [Jinja2](https://jinja.palletsprojects.com) + [xhtml2pdf](https://github.com/xhtml2pdf/xhtml2pdf) | Plantillas `.md.j2` → Markdown → HTML → PDF. `xhtml2pdf` (basado en `reportlab`) se eligió por ser 100% Python puro — no requiere librerías de sistema (Cairo/Pango), lo que evita configuración extra en Streamlit Cloud |
| Tema visual | `.streamlit/config.toml` | Paleta de azules oscuros nativa de Streamlit (fondo, sidebar, botones) |

## Estructura del repositorio

```
iso27001-streamlit-app/
├── .streamlit/
│   └── config.toml                          # Tema visual (paleta de azules oscuros)
├── app.py                                   # Interfaz Streamlit: formulario, resultados, chatbot
├── report_service.py                        # Expande las 16 respuestas a los 93 controles, calcula
│                                             # madurez y genera los contextos para las plantillas
├── groq_service.py                          # Conecta qdrant_service.py con la API de Groq (chatbot RAG)
├── qdrant_service.py                        # Capa de consulta semántica sobre Qdrant
├── seed_qdrant.py                           # Script de carga única: vectoriza los 93 controles
├── preguntas.json                           # Las 16 preguntas del cuestionario (fuente única)
├── anexo_a_iso27001_2022_vectorizable.json  # Los 93 controles del Anexo A + crosswalk con Ley 21.719
├── crosswalk_iso27001_ley21719.csv          # Los 93 controles clasificados frente a la Ley 21.719
├── plantilla_informe_ley21719.md.j2         # Plantilla del informe legal (estilo AEPD/GDPR)
├── plantilla_informe_iso27001.md.j2         # Plantilla del informe ISO (SoA simplificada)
├── qdrant_data/                             # Base vectorial de Qdrant, ya poblada (versionada en git)
├── requirements.txt
├── README.md                                # Presentación del proyecto
├── README_TECNICO.md                        # Este documento
├── .env                                     # Variables de entorno locales — NO se versiona (ver .gitignore)
└── .gitignore
```

## Cómo funciona el diagnóstico

1. El usuario ingresa el **nombre de la organización** y el **alcance** de
   la evaluación (texto libre — no son parte de las 16 preguntas).
2. Responde el cuestionario dinámico de 16 preguntas (`preguntas.json`),
   cada una con `Sí` / `Parcial` / `No`. Algunas incluyen subpreguntas de
   seguimiento que solo aparecen según la respuesta principal (condición
   `siempre` o `parcial_no`). Los términos técnicos (DPIA, Delegado de
   Protección de Datos, Aviso de Privacidad) tienen un tooltip con su
   explicación legal y el artículo de la Ley 21.719 correspondiente.
3. `report_service.py` expande esas 16 respuestas a los **93 controles**
   del Anexo A: el estado de cada control se infiere de la pregunta que lo
   agrupa (`Sí` → Implementado, `Parcial` → Parcialmente implementado,
   `No` → No implementado).
4. Se calculan tres indicadores de madurez (global, ISO, Ley 21.719 — este
   último ponderado por `tipo_vinculo`), se generan las brechas priorizadas
   por severidad y un plan de acción sugerido.
5. Se renderizan dos informes (Jinja2 → Markdown → HTML → PDF vía
   `xhtml2pdf`) y quedan disponibles para descarga directa desde la app.

## Flujo del chatbot (RAG)

El chatbot del sidebar (disponible en todo momento) responde preguntas
sobre los controles del Anexo A y su relación con la Ley 21.719:

```
Pregunta del usuario
        │
        ▼
qdrant_service.buscar_controles()      # búsqueda semántica (fastembed + Qdrant local)
        │  top-k controles más relevantes
        ▼
qdrant_service.formatear_contexto()    # arma el bloque de contexto en texto plano
        │
        ▼
groq_service.responder_chat()          # arma el prompt (system + contexto + historial)
        │  y llama a la API de Groq (streaming)
        ▼
Respuesta mostrada en el chat, en español, citando los códigos de control
```

El `system prompt` instruye al modelo a responder **únicamente** en base al
contexto recuperado y a decir explícitamente cuando no tiene información
suficiente, para minimizar alucinaciones — no se le pide "conocimiento
general" sobre ISO 27001 o la Ley 21.719 fuera de lo recuperado.

## Instalación

Requiere Python 3.11+.

```bash
git clone https://github.com/Geraldinevb/iso27001-streamlit-app.git
cd iso27001-streamlit-app

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

La base vectorial (`qdrant_data/`) ya viene poblada y versionada en el
repositorio — **no** es necesario correr `seed_qdrant.py` en una instalación
normal. Solo se vuelve a correr si cambias el contenido de
`anexo_a_iso27001_2022_vectorizable.json` y necesitas re-vectorizar los
controles:

```bash
python seed_qdrant.py
```

## Configuración de variables de entorno

Crea un archivo `.env` en la raíz del proyecto (nunca se sube a git — ya
está en `.gitignore`) con:

```
GROQ_API_KEY=tu_api_key_de_groq
```

Consíguela en [console.groq.com/keys](https://console.groq.com/keys) si
todavía no la tienes.

## Ejecución

```bash
streamlit run app.py
```

Esto abre la app en `http://localhost:8501`. El chatbot del sidebar
funciona apenas cargue la app (usa la `GROQ_API_KEY` del `.env`); el
cuestionario y los informes no dependen de Groq en absoluto — solo el chat.

## Supuestos metodológicos

Documentados en detalle en el docstring de `report_service.py`; en resumen:

- El estado de cada uno de los 93 controles se infiere de la respuesta a
  la pregunta que lo agrupa (no se evalúa control por control de forma
  independiente).
- La madurez frente a la Ley 21.719 pondera cada control por su
  `tipo_vinculo` (Fuerte=1.0, Parcial=0.5, Estructural=0.25, "No aplica
  directo"=excluido). Las preguntas sin controles ISO asociados (derechos
  ARCO+, base legal del tratamiento, modelo de prevención de infracciones)
  se ponderan con peso pleno, al ser obligaciones puramente legales.
- La severidad de una brecha es "Alta" si la respuesta es "No", o si es
  "Parcial" pero está vinculada a un control "Fuerte" (o es una obligación
  puramente legal sin control ISO asociado).

Estas reglas son ajustables — están aisladas en constantes al inicio de
`report_service.py` (`PESO_POR_TIPO_VINCULO`, `PLAZO_POR_SEVERIDAD`, etc.).

## Despliegue en Streamlit Community Cloud

1. Conecta este repositorio desde [share.streamlit.io](https://share.streamlit.io).
2. Selecciona `app.py` como archivo principal.
3. En **Settings → Secrets**, agrega (formato TOML):
   ```toml
   GROQ_API_KEY = "tu_api_key_de_groq"
   ```
   (el `.env` local no viaja al despliegue — Streamlit Cloud usa Secrets en
   su lugar; `groq_service.py` ya soporta ambos).
4. Deploy. La base vectorial (`qdrant_data/`) ya está versionada en el
   repo, así que el chatbot debería funcionar sin pasos adicionales.

## Roadmap

- [x] Cuestionario dinámico + expansión a 93 controles
- [x] Cálculo de madurez e informes descargables (PDF)
- [x] Chatbot RAG (Groq + Qdrant local)
- [x] Despliegue en Streamlit Community Cloud
- [x] Glosario/tooltips con lenguaje sencillo para términos técnicos del
      cuestionario (DPIA, Delegado de Protección de Datos, Aviso de
      Privacidad)
- [x] Tema visual propio
- [ ] Resumen ejecutivo en pantalla (hoy solo vive dentro del PDF)
- [ ] Preguntas sugeridas ("chips") en el chatbot
