"""
seed_qdrant.py

Script de carga inicial: vectoriza los 93 controles del Anexo A
(ISO 27001:2022 + crosswalk Ley 21.719) y los sube a una base Qdrant
LOCAL EMBEBIDA (sin servicio en la nube, sin Docker).

Se ejecuta UNA SOLA VEZ (o cada vez que el dataset de controles cambie).
La app de Streamlit (app.py) NO debe llamar a este script en cada
consulta ni en cada arranque — solo lee de ./qdrant_data, ya poblado.

ANTES DE CORRER:
1. pip install "qdrant-client[fastembed]"
   (instala qdrant-client + fastembed juntos; NO instala sentence-transformers ni torch)
2. Ajusta DATASET_PATH si el JSON no está en la misma carpeta.
3. Corre: python seed_qdrant.py
"""

import json
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

# --- Configuración ---
DATASET_PATH = "anexo_a_iso27001_2022_vectorizable.json"
QDRANT_LOCAL_PATH = "./qdrant_data"   # carpeta local embebida, sin servidor externo
COLLECTION_NAME = "anexo_a_iso27001"
MODEL_NAME = "intfloat/multilingual-e5-small"
VECTOR_SIZE = 384

# --- 1. Registrar manualmente el modelo e5-small en fastembed ---
# fastembed NO trae este modelo soportado por defecto (solo trae la versión
# "large", más pesada). Se registra usando la conversión ONNX ya publicada
# del mismo modelo exacto (Xenova/multilingual-e5-small), para mantener
# el mismo modelo y las mismas 384 dimensiones que se usaron previamente.
try:
    TextEmbedding.add_custom_model(
        model=MODEL_NAME,
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf="Xenova/multilingual-e5-small"),
        dim=VECTOR_SIZE,
        model_file="onnx/model.onnx",
    )
except ValueError:
    # Ya estaba registrado en esta sesión/entorno — no es un error real.
    pass

# --- 2. Cargar el dataset de 93 controles ---
dataset_path = Path(DATASET_PATH)
if not dataset_path.exists():
    raise SystemExit(
        f"No se encontró '{DATASET_PATH}'. Verifica que el archivo "
        f"anexo_a_iso27001_2022_vectorizable.json esté en esta misma carpeta."
    )

with open(dataset_path, encoding="utf-8") as f:
    controles = json.load(f)

print(f"{len(controles)} controles cargados desde {DATASET_PATH}")

# --- 3. Construir el texto a indexar por control (protocolo E5: prefijo "passage: ") ---
def construir_texto(control: dict) -> str:
    ejemplos_txt = " ".join(control.get("ejemplos", []))
    return f"passage: {control['title']}. {control['description']} {ejemplos_txt}"

textos = [construir_texto(c) for c in controles]

# --- 4. Generar embeddings con fastembed (ONNX, CPU, sin torch) ---
print(f"Cargando modelo {MODEL_NAME} (vía fastembed, primera vez descarga ~470MB)...")
model = TextEmbedding(model_name=MODEL_NAME)

print("Generando embeddings de los 93 controles...")
embeddings = list(model.embed(textos))

# --- 5. Conectar a Qdrant en modo local embebido y crear la colección ---
client = QdrantClient(path=QDRANT_LOCAL_PATH)

if not client.collection_exists(COLLECTION_NAME):
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    print(f"Colección '{COLLECTION_NAME}' creada en {QDRANT_LOCAL_PATH}")
else:
    print(f"Colección '{COLLECTION_NAME}' ya existía en {QDRANT_LOCAL_PATH}, se reutiliza.")

# --- 6. Armar los puntos (vector + payload con todos los metadatos) ---
puntos = []
for i, (control, vector) in enumerate(zip(controles, embeddings)):
    payload = {
        "control_id": control["control_id"],
        "framework": control["framework"],
        "domain": control["domain"],
        "title": control["title"],
        "description": control["description"],
        "ejemplos": control["ejemplos"],
        "nist_mapping": control.get("nist_mapping"),
        "nist_mapping_status": control.get("nist_mapping_status"),
        "ley_21719_ref": control.get("ley_21719_ref"),
        "fuentes_referencia": control.get("fuentes_referencia", []),
    }
    puntos.append(
        PointStruct(id=i, vector=vector.tolist(), payload=payload)
    )

# --- 7. Subir todo en un solo batch ---
client.upsert(collection_name=COLLECTION_NAME, points=puntos)
print(f"{len(puntos)} controles indexados en Qdrant local ('{QDRANT_LOCAL_PATH}').")

# --- 8. Prueba rápida de búsqueda ---
pregunta = "¿Cómo protejo los datos de pacientes cuando ya no los necesito?"
query_vector = list(model.embed([f"query: {pregunta}"]))[0]

resultados = client.query_points(
    collection_name=COLLECTION_NAME,
    query=query_vector.tolist(),
    limit=3,
).points

print(f"\nPrueba de búsqueda: '{pregunta}'")
for r in resultados:
    print(f"  [{r.score:.3f}] {r.payload['control_id']} - {r.payload['title']}")

print(
    "\nListo. La app (app.py / qdrant_service.py) debe abrir esta misma "
    f"colección con QdrantClient(path='{QDRANT_LOCAL_PATH}'), sin volver "
    "a correr este script salvo que el dataset de controles cambie."
)
