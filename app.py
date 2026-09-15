"""
app.py
======

MVP Streamlit — Diagnóstico ISO/IEC 27001:2022 + Ley 21.719 (Chile).

Flujo:
    1. Se piden "organizacion" y "alcance" (texto libre, NO son parte de las
       16 preguntas).
    2. Se muestra el formulario dinámico de 16 preguntas (con subpreguntas
       condicionales) leído desde preguntas.json.
    3. Al enviar, se calculan ambos informes vía report_service.py y se
       muestra el panel de resultados (heatmaps, gráficos, descargas).
    4. Botón de reinicio -> limpia todo el estado y vuelve al formulario.

Además, el sidebar incluye un chatbot RAG de apoyo (groq_service.py +
qdrant_service.py) que responde preguntas sobre los 93 controles del Anexo A,
disponible en todo momento (tanto durante el cuestionario como en el panel
de resultados).
"""

from __future__ import annotations

import io
from pathlib import Path

import markdown as md_lib
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from jinja2 import Template
from xhtml2pdf import pisa

from report_service import cargar_preguntas, generar_contextos
from groq_service import responder_chat

st.set_page_config(
    page_title="Diagnóstico ISO 27001 + Ley 21.719",
    page_icon="🛡️",
    layout="wide",
)

RESPUESTA_OPCIONES = ["Sí", "Parcial", "No"]


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------

def _init_state() -> None:
    st.session_state.setdefault("resultados", None)  # (contexto, contexto_iso) una vez generados
    st.session_state.setdefault("organizacion", "")
    st.session_state.setdefault("alcance", "")
    st.session_state.setdefault("chat_historial", [])


def _reiniciar() -> None:
    st.session_state.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Cuestionario
# ---------------------------------------------------------------------------

def _renderizar_cuestionario() -> None:
    st.title("🛡️ Diagnóstico de cumplimiento")
    st.caption("ISO/IEC 27001:2022 (Anexo A) + Ley N° 21.719 sobre Protección de Datos Personales")

    st.markdown("### Datos de la organización")
    col1, col2 = st.columns(2)
    with col1:
        organizacion = st.text_input(
            "Nombre de la organización",
            value=st.session_state["organizacion"],
            placeholder="Ej. Comercial Andes SpA",
        )
    with col2:
        alcance = st.text_area(
            "Alcance de la evaluación",
            value=st.session_state["alcance"],
            placeholder="Ej. Sistemas de e-commerce, CRM de clientes y su infraestructura asociada.",
            height=68,
        )
    st.session_state["organizacion"] = organizacion
    st.session_state["alcance"] = alcance

    st.divider()
    st.markdown("### Cuestionario (16 preguntas)")
    st.caption("Responde según la situación real de tu organización hoy. Algunas preguntas incluyen sub-preguntas de seguimiento.")

    preguntas = cargar_preguntas()
    respuestas: dict = {}

    for p in preguntas:
        st.markdown(f"**{p['id']}. {p['dominio']}**")
        respuesta = st.radio(
            p["texto_pregunta"],
            RESPUESTA_OPCIONES,
            key=f"resp_{p['id']}",
            horizontal=True,
            index=None,
        )

        sub_respuestas = []
        for i, sub in enumerate(p.get("subpreguntas", [])):
            condicion = sub.get("condicion", "siempre")
            aplica = condicion == "siempre" or (
                condicion == "parcial_no" and respuesta in ("Parcial", "No")
            )
            if aplica:
                sub_resp = st.radio(
                    f"↳ {sub['texto']}",
                    ["Sí", "No"],
                    key=f"resp_{p['id']}_sub{i}",
                    horizontal=True,
                    index=None,
                )
                sub_respuestas.append(sub_resp)
            else:
                sub_respuestas.append(None)

        respuestas[p["id"]] = {"respuesta": respuesta, "subrespuestas": sub_respuestas}
        st.markdown("")

    st.divider()

    faltantes = [p["id"] for p in preguntas if respuestas[p["id"]]["respuesta"] is None]
    if st.button("Generar diagnóstico", type="primary", use_container_width=True):
        if not organizacion.strip():
            st.error("Ingresa el nombre de la organización antes de continuar.")
        elif not alcance.strip():
            st.error("Ingresa el alcance de la evaluación antes de continuar.")
        elif faltantes:
            st.error(f"Faltan por responder: {', '.join(faltantes)}.")
        else:
            with st.spinner("Calculando diagnóstico..."):
                contexto, contexto_iso = generar_contextos(respuestas, organizacion.strip(), alcance.strip())
            st.session_state["resultados"] = {"contexto": contexto, "contexto_iso": contexto_iso}
            st.rerun()


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

def _heatmap_preguntas(contexto: dict) -> go.Figure:
    score_por_resp = {"Sí": 100, "Parcial": 50, "No": 0}
    preguntas = contexto["preguntas_respondidas"]
    etiquetas = [f"{p['id']} · {p['dominio']}" for p in preguntas][::-1]
    scores = [score_por_resp[p["respuesta"]] for p in preguntas][::-1]
    textos = [p["respuesta"] for p in preguntas][::-1]

    fig = go.Figure(data=go.Heatmap(
        z=[[s] for s in scores],
        y=etiquetas,
        x=["Nivel"],
        text=[[t] for t in textos],
        texttemplate="%{text}",
        colorscale="RdYlGn",
        zmin=0, zmax=100,
        showscale=False,
    ))
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10))
    return fig


def _heatmap_dominios_iso(contexto_iso: dict) -> go.Figure:
    madurez = contexto_iso["madurez_por_dominio"]
    dominios = list(madurez.keys())
    valores = list(madurez.values())

    fig = go.Figure(data=go.Heatmap(
        z=[valores],
        x=dominios,
        y=["Madurez ISO"],
        text=[[f"{v}%" for v in valores]],
        texttemplate="%{text}",
        colorscale="RdYlGn",
        zmin=0, zmax=100,
        showscale=True,
    ))
    fig.update_layout(height=180, margin=dict(l=10, r=10, t=10, b=10))
    return fig


def _grafico_severidad(gap_items: list) -> go.Figure:
    conteo = pd.Series([g["severidad"] for g in gap_items]).value_counts()
    orden = ["Alta", "Media", "Baja"]
    colores = {"Alta": "#d62728", "Media": "#f2c744", "Baja": "#2ca02c"}
    df = pd.DataFrame({
        "Severidad": [s for s in orden if s in conteo.index],
    })
    df["Brechas"] = df["Severidad"].map(conteo)
    fig = px.bar(
        df, x="Severidad", y="Brechas", color="Severidad",
        color_discrete_map=colores, text="Brechas",
    )
    fig.update_layout(height=320, showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
    return fig


APP_DIR = Path(__file__).parent

_PDF_CSS = """
<style>
    @page { size: A4; margin: 2cm; }
    body { font-family: Helvetica, sans-serif; font-size: 10pt; color: #1a1a1a; line-height: 1.4; }
    h1 { font-size: 18pt; color: #14304d; border-bottom: 2px solid #14304d; padding-bottom: 6px; }
    h2 { font-size: 14pt; color: #14304d; margin-top: 18px; }
    h3 { font-size: 12pt; color: #2c5282; margin-top: 14px; }
    table { width: 100%; margin: 10px 0; }
    th { background-color: #14304d; color: #ffffff; padding: 5px; font-size: 9pt; text-align: left; }
    td { border: 0.5px solid #cccccc; padding: 5px; font-size: 9pt; }
    tr:nth-child(even) { background-color: #f4f6f8; }
    blockquote { border-left: 3px solid #999999; padding-left: 10px; color: #555555; font-style: italic; }
    hr { border: none; border-top: 1px solid #cccccc; margin: 16px 0; }
    code { font-family: Courier, monospace; background-color: #f0f0f0; }
</style>
"""


def _render_informe_md(template_filename: str, contexto: dict) -> str:
    ruta_plantilla = APP_DIR / template_filename
    with open(ruta_plantilla, encoding="utf-8") as f:
        tpl = Template(f.read(), trim_blocks=True, lstrip_blocks=True)
    return tpl.render(**contexto)


def _markdown_a_pdf(texto_markdown: str) -> bytes:
    """Convierte el Markdown ya renderizado por Jinja2 a PDF (vía HTML + xhtml2pdf/reportlab,
    100% Python puro -- sin dependencias de sistema, para que funcione tal cual en
    Streamlit Community Cloud)."""
    html_cuerpo = md_lib.markdown(texto_markdown, extensions=["tables", "fenced_code"])
    html_completo = f"<html><head>{_PDF_CSS}</head><body>{html_cuerpo}</body></html>"
    buffer = io.BytesIO()
    resultado = pisa.CreatePDF(html_completo, dest=buffer, encoding="utf-8")
    if resultado.err:
        raise RuntimeError(f"No se pudo generar el PDF ({resultado.err} error(es) de conversión).")
    return buffer.getvalue()


def _renderizar_resultados() -> None:
    contexto = st.session_state["resultados"]["contexto"]
    contexto_iso = st.session_state["resultados"]["contexto_iso"]

    st.title("📊 Resultados del diagnóstico")
    st.caption(f"{contexto['organizacion']} — generado el {contexto['fecha_generacion']}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Madurez global", f"{contexto['nivel_madurez_global']}%")
    c2.metric("Ley N° 21.719", f"{contexto['nivel_madurez_ley21719']}%")
    c3.metric("ISO/IEC 27001 (Anexo A)", f"{contexto['nivel_madurez_iso']}%")

    st.markdown("#### Madurez por dominio ISO/IEC 27001")
    st.plotly_chart(_heatmap_dominios_iso(contexto_iso), use_container_width=True)

    col_izq, col_der = st.columns([1.3, 1])
    with col_izq:
        st.markdown("#### Nivel de respuesta por pregunta")
        st.plotly_chart(_heatmap_preguntas(contexto), use_container_width=True)
    with col_der:
        st.markdown("#### Brechas por severidad")
        if contexto["gap_items"]:
            st.plotly_chart(_grafico_severidad(contexto["gap_items"]), use_container_width=True)
        else:
            st.success("No se detectaron brechas en las preguntas evaluadas. 🎉")

        st.markdown("#### Plan de acción priorizado")
        if contexto["plan_de_accion"]:
            st.dataframe(
                pd.DataFrame(contexto["plan_de_accion"])[
                    ["hallazgo", "responsable_sugerido", "plazo_sugerido"]
                ].rename(columns={
                    "hallazgo": "Hallazgo",
                    "responsable_sugerido": "Responsable sugerido",
                    "plazo_sugerido": "Plazo sugerido",
                }),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.markdown("#### Descargar informes")
    informe_ley_md = _render_informe_md("plantilla_informe_ley21719.md.j2", contexto)
    informe_iso_md = _render_informe_md("plantilla_informe_iso27001.md.j2", contexto_iso)

    nombre_org = contexto["organizacion"].strip().replace(" ", "_")
    dcol1, dcol2 = st.columns(2)
    with dcol1:
        try:
            pdf_ley = _markdown_a_pdf(informe_ley_md)
            st.download_button(
                "⬇️ Informe Ley N° 21.719 (.pdf)",
                data=pdf_ley,
                file_name=f"informe_ley21719_{nombre_org}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except RuntimeError as e:
            st.error(f"No se pudo generar el PDF del informe Ley 21.719: {e}")
    with dcol2:
        try:
            pdf_iso = _markdown_a_pdf(informe_iso_md)
            st.download_button(
                "⬇️ Informe ISO/IEC 27001 — SoA simplificada (.pdf)",
                data=pdf_iso,
                file_name=f"informe_iso27001_{nombre_org}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except RuntimeError as e:
            st.error(f"No se pudo generar el PDF del informe ISO 27001: {e}")

    st.divider()
    if st.button("🔄 Reiniciar diagnóstico", use_container_width=True):
        _reiniciar()


# ---------------------------------------------------------------------------
# Chatbot (sidebar)
# ---------------------------------------------------------------------------

def _renderizar_chatbot() -> None:
    st.markdown("### 💬 Asistente de controles")
    st.caption(
        "Responde en base a los 93 controles del Anexo A (búsqueda semántica + Groq/Llama 3). "
        "No reemplaza asesoría legal ni una auditoría formal."
    )

    if st.session_state["chat_historial"]:
        if st.button("🗑️ Limpiar conversación", use_container_width=True):
            st.session_state["chat_historial"] = []
            st.rerun()

    for turno in st.session_state["chat_historial"]:
        with st.chat_message(turno["role"]):
            st.markdown(turno["content"])

    pregunta = st.chat_input("Pregunta sobre un control o una obligación...")
    if pregunta:
        st.session_state["chat_historial"].append({"role": "user", "content": pregunta})
        with st.chat_message("user"):
            st.markdown(pregunta)

        with st.chat_message("assistant"):
            try:
                historial_previo = st.session_state["chat_historial"][:-1]  # sin el turno recién agregado
                respuesta_completa = st.write_stream(
                    responder_chat(pregunta, historial=historial_previo, stream=True)
                )
            except RuntimeError as e:
                respuesta_completa = f"⚠️ {e}"
                st.error(respuesta_completa)
            except Exception as e:  # errores de red/API de Groq u otros imprevistos
                import traceback
                traceback.print_exc()  # queda en la terminal donde corre `streamlit run app.py`
                respuesta_completa = (
                    "⚠️ Ocurrió un problema al consultar el asistente. Intenta de nuevo en unos segundos."
                )
                st.error(respuesta_completa)
                with st.expander("Detalle técnico (para depurar)"):
                    st.code(f"{type(e).__name__}: {e}")

        st.session_state["chat_historial"].append({"role": "assistant", "content": respuesta_completa})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _init_state()

    with st.sidebar:
        st.markdown("### 🛡️ Diagnóstico ISO 27001 + Ley 21.719")
        st.caption(
            "Prototipo de pre-diagnóstico. No reemplaza una auditoría formal "
            "ni asesoría legal profesional."
        )
        st.divider()
        _renderizar_chatbot()

    if st.session_state["resultados"] is None:
        _renderizar_cuestionario()
    else:
        _renderizar_resultados()


if __name__ == "__main__":
    main()
