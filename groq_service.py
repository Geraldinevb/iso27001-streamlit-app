"""
groq_service.py
================

Capa de generación (la "G" del RAG). Toma la pregunta del usuario, recupera
los controles más relevantes vía qdrant_service.py, y le pide a un modelo
de Groq que redacte una respuesta en lenguaje natural basada SOLO en ese
contexto recuperado.

Uso típico desde app.py (sidebar del chatbot):

    from groq_service import responder_chat

    # Respuesta completa (bloqueante):
    respuesta = responder_chat("¿Cómo protejo datos de pacientes?", historial)

    # Respuesta en streaming (para st.write_stream, más responsiva en la UI):
    for fragmento in responder_chat("¿Cómo protejo datos de pacientes?", historial, stream=True):
        ...

`historial` es la lista de turnos previos de la conversación (sin el
system prompt), con la forma:
    [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
Se recomienda guardarlo en st.session_state["chat_historial"] desde app.py.

CONFIGURACIÓN DE LA API KEY
----------------------------
Se busca GROQ_API_KEY en, en este orden:
    1. Variable de entorno (funciona con un archivo .env local + python-dotenv)
    2. st.secrets["GROQ_API_KEY"] (Streamlit Community Cloud -> Settings -> Secrets)
Si no se encuentra ninguna, se levanta un RuntimeError explícito al primer
intento de uso (no al importar el módulo), para que app.py pueda capturarlo
y mostrar un mensaje claro en la UI en vez de que la app crashee al cargar.

MODELO
------
Por defecto se usa "openai/gpt-oss-120b" (modelo de producción vigente en
GroqCloud, con buena capacidad de razonamiento). Si en el futuro Groq lo
deprecara, basta con cambiar GROQ_MODEL más abajo — revisa
https://console.groq.com/docs/models para la lista vigente.

Nota histórica: este archivo usó originalmente "llama-3.3-70b-versatile",
que Groq decomisionó (dejó de existir como modelo servible) — si vuelves a
ver un error 404 "model_not_found", es la misma causa: hay que actualizar
GROQ_MODEL a lo que esté vigente en ese momento.
"""

from __future__ import annotations

import os
from typing import Generator, Iterable

try:
    import streamlit as st
    _cache_resource = st.cache_resource
except ImportError:  # permite importar/testear este módulo sin streamlit
    def _cache_resource(*args, **kwargs):
        def _decorator(func):
            return func
        return _decorator if not args or not callable(args[0]) else args[0]

from dotenv import load_dotenv
from groq import Groq

from qdrant_service import buscar_controles, formatear_contexto

load_dotenv()  # no-op silencioso si no existe .env (ej. en Streamlit Cloud)

GROQ_MODEL = "openai/gpt-oss-120b"
TEMPERATURE = 0.2
MAX_TOKENS = 900
TOP_K_CONTROLES = 3

SYSTEM_PROMPT = """Eres un asistente de apoyo dentro de una herramienta de \
pre-diagnóstico de cumplimiento normativo para organizaciones en Chile. Tu \
función es ayudar a interpretar los controles del Anexo A de la norma \
ISO/IEC 27001:2022 y su relación con la Ley N° 21.719 de Protección de \
Datos Personales.

Reglas estrictas:
- Responde ÚNICAMENTE en base al CONTEXTO entregado en cada mensaje (viene \
de una búsqueda semántica sobre los 93 controles del Anexo A). No inventes \
controles, códigos ni obligaciones legales que no aparezcan en el contexto.
- Si el contexto está vacío o no es suficiente para responder con \
confianza, dilo explícitamente y sugiere reformular la pregunta o revisar \
el Anexo A directamente — no rellenes los vacíos con conocimiento general.
- Cuando cites un control, usa su código (ej. "control 5.1") para que el \
usuario pueda ubicarlo.
- No eres un abogado ni un auditor certificador: tus respuestas son \
orientativas. Si la pregunta busca un dictamen legal vinculante o una \
certificación, acláralo y recomienda asesoría profesional.
- Responde en español, de forma clara y concisa (idealmente menos de 200 \
palabras salvo que la pregunta requiera más detalle)."""


def _obtener_api_key() -> str | None:
    api_key = os.environ.get("GROQ_API_KEY")
    if api_key:
        return api_key
    try:
        import streamlit as st  # import local por si no está disponible
        return st.secrets.get("GROQ_API_KEY")
    except Exception:
        return None


@_cache_resource(show_spinner=False)
def _cliente_groq() -> Groq:
    api_key = _obtener_api_key()
    if not api_key:
        raise RuntimeError(
            "No se encontró GROQ_API_KEY. Defínela en un archivo .env "
            "(desarrollo local, ver .env.example) o en Settings -> Secrets "
            "si está desplegado en Streamlit Community Cloud."
        )
    return Groq(api_key=api_key)


def _construir_mensajes(pregunta_usuario: str, historial: list[dict] | None, contexto: str) -> list[dict]:
    if contexto:
        mensaje_usuario = (
            f"CONTEXTO (controles recuperados):\n{contexto}\n\n"
            f"PREGUNTA DEL USUARIO:\n{pregunta_usuario}"
        )
    else:
        mensaje_usuario = (
            "CONTEXTO (controles recuperados): (sin resultados relevantes para esta pregunta)\n\n"
            f"PREGUNTA DEL USUARIO:\n{pregunta_usuario}"
        )
    mensajes = [{"role": "system", "content": SYSTEM_PROMPT}]
    mensajes.extend(historial or [])
    mensajes.append({"role": "user", "content": mensaje_usuario})
    return mensajes


def _extraer_texto_stream(stream: Iterable) -> Generator[str, None, None]:
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def responder_chat(
    pregunta_usuario: str,
    historial: list[dict] | None = None,
    top_k: int = TOP_K_CONTROLES,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """
    Genera la respuesta del chatbot RAG a una pregunta del usuario.

    - stream=False (default): devuelve la respuesta completa como string.
    - stream=True: devuelve un generador de fragmentos de texto, pensado
      para usarse con st.write_stream(...) en la UI.

    Levanta RuntimeError si no hay GROQ_API_KEY configurada.
    """
    if not pregunta_usuario or not pregunta_usuario.strip():
        return "" if not stream else iter(())

    resultados = buscar_controles(pregunta_usuario, top_k=top_k)
    contexto = formatear_contexto(resultados)
    mensajes = _construir_mensajes(pregunta_usuario, historial, contexto)

    cliente = _cliente_groq()

    if not stream:
        respuesta = cliente.chat.completions.create(
            model=GROQ_MODEL,
            messages=mensajes,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        return respuesta.choices[0].message.content

    stream_respuesta = cliente.chat.completions.create(
        model=GROQ_MODEL,
        messages=mensajes,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    return _extraer_texto_stream(stream_respuesta)
