"""
qdrant_service.py

Capa de consulta (retrieval) contra la base vectorial local de Qdrant,
ya poblada previamente por seed_qdrant.py (carpeta ./qdrant_data).

Este módulo NO llama a Groq ni redacta ninguna respuesta en lenguaje
natural — solo recupera los controles más relevantes para una consulta
del usuario. app.py es quien toma ese resultado y se lo pasa a Groq
como contexto para el flujo RAG del chatbot.

Uso típico desde app.py:

    from qdrant_service import buscar_controles, formatear_contexto

    resultados = buscar_controles("¿cómo protejo datos de pacientes?")
    contexto = formatear_contexto(resultados)
    # contexto se envía como parte del prompt a Groq/Llama 3
"""

import streamlit as st
from qdrant_client import QdrantClient
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

QDRANT_LOCAL_PATH = "./qdrant_data"
COLLECTION_NAME = "anexo_a_iso27001"
MODEL_NAME = "intfloat/multilingual-e5-small"


def _registrar_modelo_custom() -> None:
    """Registra e5-small en fastembed (no viene soportado por defecto).
    Debe llamarse antes de instanciar TextEmbedding. Es seguro llamarla
    más de una vez: si ya está registrado, ignora el ValueError."""
    try:
        TextEmbedding.add_custom_model(
            model=MODEL_NAME,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf="Xenova/multilingual-e5-small"),
            dim=384,
            model_file="onnx/model.onnx",
        )
    except ValueError:
        pass


@st.cache_resource(show_spinner="Cargando modelo de búsqueda semántica...")
def _cargar_modelo() -> TextEmbedding:
    """Carga el modelo de embeddings una sola vez por sesión de Streamlit.
    @st.cache_resource evita recargarlo en cada rerun de la app (cada
    interacción del usuario re-ejecuta el script completo de Streamlit)."""
    _registrar_modelo_custom()
    return TextEmbedding(model_name=MODEL_NAME)


@st.cache_resource(show_spinner=False)
def _conectar_qdrant() -> QdrantClient:
    """Abre la base Qdrant local embebida una sola vez por sesión.
    IMPORTANTE: Qdrant en modo local bloquea la carpeta mientras está
    abierta (ver archivo .lock) — un solo proceso a la vez puede tenerla
    abierta, lo cual es normal para una app de Streamlit de un solo
    proceso, pero no debe correrse en paralelo con seed_qdrant.py."""
    return QdrantClient(path=QDRANT_LOCAL_PATH)


def buscar_controles(pregunta_usuario: str, top_k: int = 3) -> list[dict]:
    """
    Busca los `top_k` controles más relevantes para una pregunta del
    usuario. Aplica el prefijo "query: " requerido por el protocolo E5
    (los controles ya fueron indexados con el prefijo "passage: " en
    seed_qdrant.py).

    Retorna una lista de dicts, cada uno con:
      - score: similitud (más cerca de 1.0 = más relevante)
      - control_id, framework, domain, title, description, ejemplos,
        nist_mapping, nist_mapping_status, ley_21719_ref, fuentes_referencia
    """
    if not pregunta_usuario or not pregunta_usuario.strip():
        return []

    modelo = _cargar_modelo()
    client = _conectar_qdrant()

    vector_consulta = list(modelo.embed([f"query: {pregunta_usuario}"]))[0]

    resultados = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector_consulta.tolist(),
        limit=top_k,
    ).points

    return [
        {"score": r.score, **r.payload}
        for r in resultados
    ]


def formatear_contexto(resultados: list[dict]) -> str:
    """
    Convierte los resultados de buscar_controles() en un bloque de texto
    plano, listo para insertarse en el prompt que se envía a Groq como
    contexto del flujo RAG. Si no hay resultados, devuelve un string
    vacío para que app.py pueda manejar ese caso explícitamente.
    """
    if not resultados:
        return ""

    bloques = []
    for r in resultados:
        partes = [
            f"Control: {r['control_id']} - {r['title']}",
            f"Dominio: {r['domain']}",
            f"Descripción: {r['description']}",
        ]
        if r.get("ejemplos"):
            ejemplos_txt = " | ".join(r["ejemplos"])
            partes.append(f"Ejemplos prácticos: {ejemplos_txt}")
        if r.get("ley_21719_ref"):
            partes.append(f"Referencia Ley 21.719: {r['ley_21719_ref']}")
        if r.get("nist_mapping"):
            partes.append(
                f"Referencia NIST CSF 2.0 (no oficial): {r['nist_mapping']}"
            )
        bloques.append("\n".join(partes))

    return "\n\n---\n\n".join(bloques)
