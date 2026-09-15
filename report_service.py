"""
report_service.py
==================

Capa de cálculo del MVP de diagnóstico ISO/IEC 27001:2022 + Ley 21.719 (Chile).

Toma las respuestas del cuestionario de 16 preguntas (`preguntas.json`) y las
expande contra los 93 controles del Anexo A
(`anexo_a_iso27001_2022_vectorizable.json`) para producir los dos
diccionarios de contexto que consumen las plantillas Jinja2:

    - generar_contexto_ley21719(...)  -> plantilla_informe_ley21719.md.j2
    - generar_contexto_iso(...)       -> plantilla_informe_iso27001.md.j2

También expone `generar_contextos(...)`, que calcula ambos a la vez
reutilizando el trabajo común (se recomienda usar esta función desde
app.py, ya que evita repetir la expansión de controles).

CONTRATO DE ENTRADA — diccionario `respuestas`
-----------------------------------------------
`respuestas` debe ser un dict keyed por el id de cada pregunta ("P1".."P16"),
donde cada valor tiene la forma:

    {
        "respuesta": "Sí" | "Parcial" | "No",
        "subrespuestas": ["Sí", "No", ...],   # alineadas por posición con
                                               # el array "subpreguntas" de
                                               # esa pregunta en preguntas.json
    }

Solo se conservan las subrespuestas cuya subpregunta corresponde
efectivamente según su "condicion" (siempre | parcial_no), de modo que
app.py puede enviar la lista completa de subrespuestas capturadas en el
formulario sin preocuparse de filtrar según la condición — este módulo lo
hace.

Todas las 16 preguntas deben estar presentes en `respuestas`; si falta
alguna se levanta un ValueError (fail-fast, para detectar un formulario
incompleto en desarrollo en vez de generar un informe silenciosamente
incorrecto).

SUPUESTOS METODOLÓGICOS (documentados también en las plantillas)
------------------------------------------------------------------
1. El estado de cada uno de los 93 controles ISO se infiere de la
   respuesta a la pregunta que lo agrupa (Sí -> Implementado,
   Parcial -> Parcialmente implementado, No -> No implementado).
2. La madurez Ley 21.719 pondera cada control por su `tipo_vinculo`
   (Fuerte=1.0, Parcial=0.5, Estructural=0.25, "No aplica directo"=excluido).
   Las preguntas sin controles ISO asociados (P14, P15, P16 — derechos
   ARCO+, base legal, modelo de prevención) son obligaciones puramente
   legales y se ponderan con peso pleno (1.0), igual que un vínculo "Fuerte".
3. La severidad de una brecha es "Alta" si la respuesta es "No", o si es
   "Parcial" pero la pregunta está vinculada a al menos un control
   "Fuerte" (o es una obligación puramente legal sin control ISO) — en
   ambos casos, diluir la severidad a "Media" ocultaría una brecha sobre
   una obligación central. En caso contrario, "Parcial" es "Media".
4. Para el informe ISO, la severidad de una brecha por control es "Alta"
   si el control está "No implementado" y "Media" si está
   "Parcialmente implementado".
Estos son supuestos razonables para un pre-diagnóstico automatizado, no
un análisis de riesgo formal — quedan explícitos aquí para que puedan
ajustarse fácilmente si el criterio de negocio cambia.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, date

try:
    import streamlit as st
    _cache_data = st.cache_data
except ImportError:  # permite importar/testear este módulo sin streamlit
    def _cache_data(func):
        return func

DATA_DIR = Path(__file__).parent
PREGUNTAS_PATH = DATA_DIR / "preguntas.json"
ANEXO_A_PATH = DATA_DIR / "anexo_a_iso27001_2022_vectorizable.json"

RESPUESTAS_VALIDAS = {"Sí", "Parcial", "No"}

SCORE_POR_RESPUESTA = {"Sí": 100.0, "Parcial": 50.0, "No": 0.0}

ESTADO_POR_RESPUESTA = {
    "Sí": "Implementado",
    "Parcial": "Parcialmente implementado",
    "No": "No implementado",
}

SCORE_POR_ESTADO = {
    "Implementado": 100.0,
    "Parcialmente implementado": 50.0,
    "No implementado": 0.0,
}

PESO_POR_TIPO_VINCULO = {
    "Fuerte": 1.0,
    "Parcial": 0.5,
    "Estructural": 0.25,
    "No aplica directo": 0.0,
}

DOMINIOS_ISO = ["Organizacional", "Personas", "Físicos", "Tecnológico"]

_DOMINIO_NORMALIZADO = {
    "organizacional": "Organizacional",
    "organizacionales": "Organizacional",
    "personas": "Personas",
    "físicos": "Físicos",
    "fisicos": "Físicos",
    "físico": "Físicos",
    "tecnológico": "Tecnológico",
    "tecnológicos": "Tecnológico",
    "tecnologico": "Tecnológico",
    "tecnologicos": "Tecnológico",
    "tecnológica": "Tecnológico",
}

RESPONSABLE_POR_DOMINIO_ISO = {
    "Organizacional": "Dirección / Encargado de Seguridad de la Información",
    "Personas": "Recursos Humanos / Encargado de Seguridad",
    "Físicos": "Administración / Facilities",
    "Tecnológico": "Equipo de TI / Infraestructura",
}

RESPONSABLE_POR_DOMINIO_LEY = {
    "Gobernanza y políticas": "Dirección / Gerencia General",
    "Roles y responsabilidades": "Dirección / Encargado de Cumplimiento",
    "Inventario y clasificación de la información": "Encargado de Seguridad de la Información",
    "Evaluación de riesgos": "Encargado de Seguridad de la Información / DPD",
    "Control de acceso e identidad": "Equipo de TI",
    "Protección técnica de los datos": "Equipo de TI",
    "Gestión de proveedores y cadena de suministro": "Área Legal / Compras",
    "Gestión de incidentes de seguridad": "Equipo de TI / Seguridad",
    "Continuidad y recuperación": "Equipo de TI",
    "Seguridad física": "Administración / Facilities",
    "Seguridad de redes e infraestructura": "Equipo de TI",
    "Desarrollo seguro y privacidad desde el diseño": "Equipo de Desarrollo",
    "Formación y concienciación": "Recursos Humanos",
    "Derechos de las personas sobre sus datos": "Encargado de Protección de Datos (DPD)",
    "Base legal del tratamiento": "Área Legal / DPD",
    "Modelo de prevención de infracciones": "Dirección / Área Legal",
}
RESPONSABLE_LEY_DEFAULT = "Encargado de Protección de Datos / Seguridad de la Información"

PLAZO_POR_SEVERIDAD = {"Alta": "30 días", "Media": "90 días", "Baja": "180 días"}

_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_es(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.day} de {_MESES_ES[d.month - 1]} de {d.year}"


def _normalizar_dominio(raw: str | None) -> str:
    if not raw:
        return "Organizacional"
    raw = raw.strip()
    if len(raw) > 2 and raw[1:3] == ". ":
        raw = raw.split(". ", 1)[1]
    return _DOMINIO_NORMALIZADO.get(raw.strip().lower(), raw.strip())


def _normalizar_codigo(control_id: str) -> str:
    """'ISO_5.1' -> '5.1' ; ya soporta también códigos ya sin prefijo."""
    return control_id.split("_", 1)[1] if control_id.startswith("ISO_") else control_id


def _redondear(valor: float) -> float:
    return round(valor, 1)


@_cache_data
def cargar_preguntas() -> list[dict]:
    with open(PREGUNTAS_PATH, encoding="utf-8") as f:
        return json.load(f)


@_cache_data
def cargar_controles() -> dict[str, dict]:
    """Devuelve un dict {codigo_sin_prefijo: control} a partir del anexo A."""
    with open(ANEXO_A_PATH, encoding="utf-8") as f:
        controles = json.load(f)
    lookup = {}
    for c in controles:
        codigo = _normalizar_codigo(c["control_id"])
        c = dict(c)
        c["domain"] = _normalizar_dominio(c.get("domain"))
        lookup[codigo] = c
    return lookup


def _validar_respuestas(preguntas: list[dict], respuestas: dict) -> None:
    faltantes = [p["id"] for p in preguntas if p["id"] not in respuestas]
    if faltantes:
        raise ValueError(
            f"Faltan respuestas para las preguntas: {', '.join(faltantes)}. "
            "El formulario debe completarse en su totalidad antes de generar "
            "los informes."
        )
    for p in preguntas:
        r = respuestas[p["id"]].get("respuesta")
        if r not in RESPUESTAS_VALIDAS:
            raise ValueError(
                f"Respuesta inválida para {p['id']}: {r!r}. "
                f"Debe ser una de {sorted(RESPUESTAS_VALIDAS)}."
            )


def _subpreguntas_respondidas(pregunta: dict, respuesta_principal: str, sub_respuestas: list) -> list[dict]:
    resultado = []
    for i, sub in enumerate(pregunta.get("subpreguntas", [])):
        condicion = sub.get("condicion", "siempre")
        aplica = condicion == "siempre" or (
            condicion == "parcial_no" and respuesta_principal in ("Parcial", "No")
        )
        if not aplica:
            continue
        if i < len(sub_respuestas) and sub_respuestas[i] not in (None, ""):
            resultado.append({"texto": sub["texto"], "respuesta": sub_respuestas[i]})
    return resultado


def _severidad_pregunta(pregunta: dict, respuesta: str, controles_lookup: dict) -> str | None:
    if respuesta == "Sí":
        return None
    if respuesta == "No":
        return "Alta"
    # respuesta == "Parcial"
    controles = pregunta.get("controles_iso", [])
    if not controles:
        return "Alta"  # obligación puramente legal (P14/P15/P16): sin control que la diluya
    for codigo in controles:
        control = controles_lookup.get(codigo)
        if control and control.get("ley_21719_tipo_vinculo") == "Fuerte":
            return "Alta"
    return "Media"


def _construir_preguntas_respondidas(preguntas: list[dict], respuestas: dict) -> list[dict]:
    salida = []
    for p in preguntas:
        r = respuestas[p["id"]]
        respuesta = r["respuesta"]
        sub_input = r.get("subrespuestas", [])
        salida.append({
            "id": p["id"],
            "dominio": p["dominio"],
            "texto_pregunta": p["texto_pregunta"],
            "respuesta": respuesta,
            "obligacion_ley_21719": p.get("obligacion_ley_21719"),
            "subpreguntas_respondidas": _subpreguntas_respondidas(p, respuesta, sub_input),
            "controles_iso": p.get("controles_iso", []),
        })
    return salida


def _mapa_pregunta_por_control(preguntas: list[dict]) -> dict[str, str]:
    """codigo_control -> id_pregunta que lo agrupa (para trazabilidad)."""
    mapa = {}
    for p in preguntas:
        for codigo in p.get("controles_iso", []):
            mapa[codigo] = p["id"]
    return mapa


def _calcular_madurez_ley21719(preguntas_respondidas: list[dict], controles_lookup: dict) -> float:
    numerador = 0.0
    denominador = 0.0
    for p in preguntas_respondidas:
        score = SCORE_POR_RESPUESTA[p["respuesta"]]
        controles = p["controles_iso"]
        if not controles:
            # obligación puramente legal (P14/P15/P16): peso pleno, sin ISO que medie
            numerador += 1.0 * score
            denominador += 1.0
            continue
        for codigo in controles:
            control = controles_lookup.get(codigo)
            tipo = control.get("ley_21719_tipo_vinculo") if control else "Estructural"
            peso = PESO_POR_TIPO_VINCULO.get(tipo, 0.0)
            if peso <= 0:
                continue
            numerador += peso * score
            denominador += peso
    return _redondear(numerador / denominador) if denominador else 0.0


def generar_contexto_ley21719(
    respuestas: dict,
    organizacion: str,
    alcance: str,
    preguntas: list[dict] | None = None,
    controles_lookup: dict | None = None,
) -> dict:
    """Construye el diccionario `contexto` para plantilla_informe_ley21719.md.j2."""
    preguntas = preguntas if preguntas is not None else cargar_preguntas()
    controles_lookup = controles_lookup if controles_lookup is not None else cargar_controles()
    _validar_respuestas(preguntas, respuestas)

    preguntas_respondidas = _construir_preguntas_respondidas(preguntas, respuestas)

    scores = [SCORE_POR_RESPUESTA[p["respuesta"]] for p in preguntas_respondidas]
    nivel_madurez_global = _redondear(sum(scores) / len(scores)) if scores else 0.0

    scores_iso = [
        SCORE_POR_RESPUESTA[p["respuesta"]] for p in preguntas_respondidas if p["controles_iso"]
    ]
    nivel_madurez_iso = _redondear(sum(scores_iso) / len(scores_iso)) if scores_iso else 0.0

    nivel_madurez_ley21719 = _calcular_madurez_ley21719(preguntas_respondidas, controles_lookup)

    gap_items = []
    for p in preguntas_respondidas:
        severidad = _severidad_pregunta(
            next(pp for pp in preguntas if pp["id"] == p["id"]), p["respuesta"], controles_lookup
        )
        if severidad:
            gap_items.append({**p, "severidad": severidad})
    orden_severidad = {"Alta": 0, "Media": 1, "Baja": 2}
    gap_items.sort(key=lambda g: (orden_severidad[g["severidad"]], g["id"]))

    plan_de_accion = []
    for item in gap_items:
        plan_de_accion.append({
            "hallazgo": f"{item['texto_pregunta']} (respuesta: {item['respuesta']})",
            "medida_correctiva": (
                f"Definir e implementar las medidas necesarias para cubrir: "
                f"{item['obligacion_ley_21719'] or item['dominio']}."
            ),
            "responsable_sugerido": RESPONSABLE_POR_DOMINIO_LEY.get(item["dominio"], RESPONSABLE_LEY_DEFAULT),
            "plazo_sugerido": PLAZO_POR_SEVERIDAD[item["severidad"]],
        })

    dictamen_final = (
        f"En base a las respuestas entregadas, {organizacion} presenta un nivel de "
        f"cumplimiento combinado del {nivel_madurez_global}% frente al marco de la "
        f"Ley N° 21.719 y el Anexo A de ISO/IEC 27001:2022 ({nivel_madurez_ley21719}% "
        f"específico en obligaciones de la Ley 21.719 y {nivel_madurez_iso}% en "
        f"controles ISO relacionados). Se identificaron {len(gap_items)} brechas de "
        f"un total de {len(preguntas_respondidas)} preguntas evaluadas.\n\n"
        "Este resultado es orientativo y se basa exclusivamente en la autoevaluación "
        "entregada; no reemplaza una auditoría de cumplimiento ni una asesoría legal "
        "especializada. Se recomienda priorizar las brechas de severidad alta "
        "detalladas en la Sección 8.1 y validar los resultados con un profesional "
        "competente antes de tomar decisiones formales de cumplimiento."
    )

    return {
        "organizacion": organizacion,
        "alcance": alcance,
        "fecha_generacion": _fecha_es(),
        "nivel_madurez_global": nivel_madurez_global,
        "nivel_madurez_iso": nivel_madurez_iso,
        "nivel_madurez_ley21719": nivel_madurez_ley21719,
        "preguntas_respondidas": preguntas_respondidas,
        "gap_items": gap_items,
        "plan_de_accion": plan_de_accion,
        "dictamen_final": dictamen_final,
    }


def generar_contexto_iso(
    respuestas: dict,
    organizacion: str,
    alcance: str,
    preguntas: list[dict] | None = None,
    controles_lookup: dict | None = None,
) -> dict:
    """Construye el diccionario `contexto_iso` para plantilla_informe_iso27001.md.j2."""
    preguntas = preguntas if preguntas is not None else cargar_preguntas()
    controles_lookup = controles_lookup if controles_lookup is not None else cargar_controles()
    _validar_respuestas(preguntas, respuestas)

    pregunta_por_control = _mapa_pregunta_por_control(preguntas)

    controles_soa = []
    for codigo, control in sorted(controles_lookup.items(), key=lambda kv: [int(x) for x in kv[0].split(".")]):
        pregunta_origen = pregunta_por_control.get(codigo)
        if pregunta_origen:
            respuesta = respuestas[pregunta_origen]["respuesta"]
            estado = ESTADO_POR_RESPUESTA[respuesta]
        else:
            # No debería ocurrir si preguntas.json cubre los 93 controles;
            # se deja como resguardo explícito en vez de fallar en silencio.
            estado = "No evaluado"
        controles_soa.append({
            "codigo": codigo,
            "nombre": control["title"],
            "dominio": control["domain"],
            "estado": estado,
            "pregunta_origen": pregunta_origen,
        })

    madurez_por_dominio = {}
    for dominio in DOMINIOS_ISO:
        del_dominio = [c for c in controles_soa if c["dominio"] == dominio]
        if del_dominio:
            promedio = sum(SCORE_POR_ESTADO.get(c["estado"], 0.0) for c in del_dominio) / len(del_dominio)
        else:
            promedio = 0.0
        madurez_por_dominio[dominio] = _redondear(promedio)

    nivel_madurez_global_iso = (
        _redondear(sum(SCORE_POR_ESTADO.get(c["estado"], 0.0) for c in controles_soa) / len(controles_soa))
        if controles_soa else 0.0
    )

    gap_items_iso = []
    for c in controles_soa:
        if c["estado"] == "No implementado":
            severidad = "Alta"
        elif c["estado"] == "Parcialmente implementado":
            severidad = "Media"
        else:
            continue
        gap_items_iso.append({**c, "severidad": severidad})
    orden_severidad = {"Alta": 0, "Media": 1, "Baja": 2}
    gap_items_iso.sort(key=lambda g: (orden_severidad[g["severidad"]], g["codigo"]))

    plan_de_accion_iso = []
    for item in gap_items_iso:
        control = controles_lookup.get(item["codigo"], {})
        descripcion = control.get("description", "")
        plan_de_accion_iso.append({
            "control": f"{item['codigo']} — {item['nombre']}",
            "hallazgo": f"Estado actual: {item['estado']}.",
            "medida_correctiva": f"Implementar o reforzar: {descripcion}" if descripcion else "Implementar el control indicado.",
            "responsable_sugerido": RESPONSABLE_POR_DOMINIO_ISO.get(item["dominio"], RESPONSABLE_LEY_DEFAULT),
            "plazo_sugerido": PLAZO_POR_SEVERIDAD[item["severidad"]],
        })

    dictamen_final_iso = (
        f"{organizacion} alcanza un nivel de madurez global del {nivel_madurez_global_iso}% "
        f"sobre los 93 controles del Anexo A de ISO/IEC 27001:2022 evaluados, con "
        f"{len(gap_items_iso)} controles en estado parcial o no implementado. "
        "Este resultado es un pre-diagnóstico orientativo, no una Declaración de "
        "Aplicabilidad formal ni evidencia de auditoría — ver advertencia al inicio "
        "de este documento."
    )

    return {
        "organizacion": organizacion,
        "alcance": alcance,
        "fecha_generacion": _fecha_es(),
        "nivel_madurez_global_iso": nivel_madurez_global_iso,
        "madurez_por_dominio": madurez_por_dominio,
        "controles_soa": controles_soa,
        "gap_items_iso": gap_items_iso,
        "plan_de_accion_iso": plan_de_accion_iso,
        "dictamen_final_iso": dictamen_final_iso,
    }


def generar_contextos(respuestas: dict, organizacion: str, alcance: str) -> tuple[dict, dict]:
    """Punto de entrada recomendado desde app.py: calcula ambos contextos
    reutilizando la carga de preguntas.json y anexo_a_iso27001_2022_vectorizable.json."""
    preguntas = cargar_preguntas()
    controles_lookup = cargar_controles()
    contexto = generar_contexto_ley21719(respuestas, organizacion, alcance, preguntas, controles_lookup)
    contexto_iso = generar_contexto_iso(respuestas, organizacion, alcance, preguntas, controles_lookup)
    return contexto, contexto_iso


if __name__ == "__main__":
    # Smoke test manual: python3 report_service.py
    # Genera respuestas de ejemplo (mezcla de Sí/Parcial/No) y renderiza
    # ambos informes con Jinja2 para verificar que no hay errores de
    # plantilla ni de cálculo.
    import random
    from jinja2 import Template

    random.seed(42)
    preguntas = cargar_preguntas()
    respuestas_demo = {}
    for p in preguntas:
        resp = random.choice(["Sí", "Parcial", "No"])
        subs = [random.choice(["Sí", "No"]) for _ in p.get("subpreguntas", [])]
        respuestas_demo[p["id"]] = {"respuesta": resp, "subrespuestas": subs}

    contexto, contexto_iso = generar_contextos(
        respuestas_demo, "Empresa Demo SpA", "Sistemas de e-commerce y CRM de clientes."
    )

    print("== Resumen Ley 21.719 ==")
    print("Madurez global:", contexto["nivel_madurez_global"])
    print("Madurez ISO:", contexto["nivel_madurez_iso"])
    print("Madurez Ley 21.719:", contexto["nivel_madurez_ley21719"])
    print("Gaps:", len(contexto["gap_items"]))

    print("\n== Resumen ISO 27001 ==")
    print("Madurez global ISO:", contexto_iso["nivel_madurez_global_iso"])
    print("Madurez por dominio:", contexto_iso["madurez_por_dominio"])
    print("Controles SoA:", len(contexto_iso["controles_soa"]))
    print("Gaps ISO:", len(contexto_iso["gap_items_iso"]))

    with open(DATA_DIR / "plantilla_informe_ley21719.md.j2", encoding="utf-8") as f:
        tpl_ley = Template(f.read(), trim_blocks=True, lstrip_blocks=True)
    with open(DATA_DIR / "plantilla_informe_iso27001.md.j2", encoding="utf-8") as f:
        tpl_iso = Template(f.read(), trim_blocks=True, lstrip_blocks=True)

    (DATA_DIR / "_salida_informe_ley21719.md").write_text(tpl_ley.render(**contexto), encoding="utf-8")
    (DATA_DIR / "_salida_informe_iso27001.md").write_text(tpl_iso.render(**contexto_iso), encoding="utf-8")
    print("\nInformes de prueba escritos en _salida_informe_ley21719.md y _salida_informe_iso27001.md")
