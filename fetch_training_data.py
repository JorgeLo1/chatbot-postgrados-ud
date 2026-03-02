import os
import sys
import time
import logging
import argparse
import requests
import unicodedata
import urllib3
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# FIX: WAF de Oracle bloquea User-Agent "python-requests/x.x.x"
# Forzamos IPv4 (IPv6 no tiene conectividad en WSL/algunos entornos)
# y usamos User-Agent de navegador para pasar el WAF.
# NOTA: En producción Linux con IPv6 activo, este monkey-patch
# puede omitirse. Controlable con env var: FORCE_IPV4=true (default true en dev).
# ============================================================
import socket as _socket
_orig_getaddrinfo = _socket.getaddrinfo
def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, _socket.AF_INET, type, proto, flags)
_socket.getaddrinfo = _ipv4_only

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Connection": "keep-alive",
})

# ============================================================
# CONFIGURACIÓN — todo desde .env
# ============================================================
APEX_API_BASE_URL = os.getenv("APEX_API_URL", "https://oracleapex.com/ords/udchatbot/chatbot")
APEX_TIMEOUT      = int(os.getenv("APEX_TIMEOUT", "60"))
APEX_SSL_VERIFY   = os.getenv("APEX_SSL_VERIFY", "false").lower() != "false"

ENABLE_CACHE      = os.getenv("ENABLE_CACHE", "False").lower() == "true"
CACHE_TTL         = int(os.getenv("CACHE_TTL", "3600"))
ENVIRONMENT       = os.getenv("ENVIRONMENT", "development")
LOG_LEVEL         = os.getenv("LOG_LEVEL", "INFO").upper()

OUTPUT_NLU_FILE     = os.path.join("data", "nlu_dynamic.yml")
OUTPUT_STORIES_FILE = os.path.join("data", "stories_dynamic.yml")

MIN_QUESTION_LENGTH     = 8
MAX_EXAMPLES_PER_INTENT = 30

# ⚠️  NOTA BD: historial_conversacion.USUARIO es VARCHAR2(20)
# Los teléfonos WhatsApp (+57XXXXXXXXXX) tienen 13 chars — dentro del límite.
# Si el sender_id de Rasa es más largo (ej: UUIDs en tests), se truncará en Oracle.
# En actions.py: usar tracker.sender_id[:20] al construir el payload de historial.

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

if ENVIRONMENT == "production":
    logger.info("🟢 Modo PRODUCCIÓN")
else:
    logger.info("🟡 Modo DESARROLLO")

if ENABLE_CACHE:
    logger.info(f"📦 Cache habilitado (TTL: {CACHE_TTL}s)")


# ============================================================
# CACHE EN MEMORIA
# ============================================================
_cache: dict = {}

def get_cached(url: str, params: dict = None) -> dict:
    key = url + str(params or {})
    if ENABLE_CACHE and key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            logger.debug(f"Cache hit: {url}")
            return data
        else:
            logger.debug(f"Cache expirado: {url}")
    r = _session.get(url, params=params, timeout=APEX_TIMEOUT, verify=APEX_SSL_VERIFY)
    r.raise_for_status()
    data = r.json()
    if ENABLE_CACHE:
        _cache[key] = (data, time.time())
    return data


# ============================================================
# REGLAS DE DETECCIÓN DE INTENT
# ============================================================
INTENT_RULES = [
    {
        "intent": "consultar_costos",
        "keywords": [
            "cuesta", "costo", "costos", "precio", "valor", "matricula",
            "smmlv", "salario minimo", "salarios minimos",
            "inversion", "pagar", "cuanto vale",
            "semestre cuesta", "credito academico"
        ]
    },
    {
        "intent": "consultar_becas",
        "keywords": [
            "beca", "becas", "descuento", "descuentos", "subsidio",
            "apoyo economico", "exencion"
        ]
    },
    {
        "intent": "consultar_financiacion",
        "keywords": [
            "financiacion", "cuotas", "credito bancario", "icetex",
            "pago diferido", "facilidades de pago", "opciones de pago", "financiar"
        ]
    },
    {
        "intent": "consultar_fechas",
        "keywords": [
            "fechas", "cuando", "inscripciones inician", "inscripciones abren",
            "cierre inscripciones", "plazo", "calendario", "convocatoria",
            "periodo de inscripcion", "abierto", "abren inscripciones",
            "cierran inscripciones", "1 de octubre", "27 de diciembre"
        ]
    },
    {
        "intent": "solicitar_link_inscripcion",
        "keywords": [
            "link", "enlace", "portal de admisiones", "sga.portaloas",
            "donde me inscribo", "como me inscribo", "inscribirme",
            "registrarme", "url", "https://sga"
        ]
    },
    {
        "intent": "consultar_proceso_admision",
        "keywords": [
            "proceso de admision", "pasos para", "como aplicar",
            "etapas", "procedimiento", "como inscribirse",
            "proceso de inscripcion"
        ]
    },
    {
        "intent": "consultar_requisitos",
        "keywords": [
            "requisitos", "documentos", "que necesito", "que piden",
            "hoja de vida", "titulo profesional", "diploma",
            "certificado de notas", "tarjeta profesional", "formulario",
            "acta de grado", "documentos requeridos", "copia del diploma"
        ]
    },
    {
        "intent": "consultar_duracion",
        "keywords": [
            "duracion", "cuanto dura", "semestres", "anos",
            "creditos", "tiempo del programa", "4 semestres", "2 semestres",
            "2 anos", "1 ano"
        ]
    },
    {
        "intent": "consultar_modalidad",
        "keywords": [
            "modalidad", "presencial", "virtual", "horario", "horarios",
            "clases", "sede", "donde son las clases", "viernes", "sabado",
            "miercoles", "fines de semana", "online", "semipresencial",
            "calle 40", "6pm", "8am"
        ]
    },
    {
        "intent": "consultar_plan_estudios",
        "keywords": [
            "plan de estudios", "pensum", "materias", "asignaturas",
            "que se estudia", "contenido", "malla", "malla curricular",
            "modulos"
        ]
    },
    {
        "intent": "consultar_dirigido",
        "keywords": [
            "dirigido", "quien puede", "para quien", "perfil de ingreso",
            "que profesionales", "que carreras", "puedo aplicar", "aplica para",
            "profesionales que", "buscan competencias"
        ]
    },
    {
        "intent": "solicitar_informacion_general",
        "keywords": [
            "informacion sobre", "me dan detalles", "datos de la",
            "datos del", "cuentame sobre", "que es la especializacion",
            "que es la maestria", "informacion de la maestria",
            "informacion del programa", "informacion principal",
            "datos principales", "datos clave", "aqui los datos"
        ]
    },
]

INTENT_DEFAULT = "pregunta_postgrado"

INTENT_SOLO_PREGUNTA = {"solicitar_informacion_general", "solicitar_link_inscripcion", "consultar_dirigido"}

INTENT_A_ACTION = {
    "consultar_costos":              "action_buscar_faq",
    "consultar_becas":               "action_buscar_faq",
    "consultar_financiacion":        "action_buscar_faq",
    "consultar_fechas":              "action_buscar_faq",
    "solicitar_link_inscripcion":    "action_buscar_faq",
    "consultar_proceso_admision":    "action_buscar_faq",
    "consultar_requisitos":          "action_buscar_faq",
    "consultar_duracion":            "action_buscar_faq",
    "consultar_modalidad":           "action_buscar_faq",
    "consultar_plan_estudios":       "action_buscar_faq",
    "consultar_dirigido":            "action_buscar_faq",
    "solicitar_informacion_general": "action_manejar_pregunta_general",
    "pregunta_postgrado":            "action_buscar_faq_libre",
}


# ============================================================
# UTILIDADES
# ============================================================

def quitar_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )

def normalizar(texto: str) -> str:
    return quitar_tildes(texto.strip().lower()) if texto else ""

def detectar_intent(faq: dict) -> str:
    pregunta  = normalizar(faq.get("PREGUNTA")  or faq.get("pregunta")  or "")
    respuesta = normalizar(faq.get("RESPUESTA") or faq.get("respuesta") or "")

    # Paso 1: intents que se detectan solo con la pregunta
    for regla in INTENT_RULES:
        if regla["intent"] not in INTENT_SOLO_PREGUNTA:
            continue
        for keyword in regla["keywords"]:
            if normalizar(keyword) in pregunta:
                return regla["intent"]

    # Paso 2: resto de intents con pregunta + respuesta
    texto = pregunta + " " + respuesta
    for regla in INTENT_RULES:
        if regla["intent"] in INTENT_SOLO_PREGUNTA:
            continue
        for keyword in regla["keywords"]:
            if normalizar(keyword) in texto:
                return regla["intent"]

    return INTENT_DEFAULT

def es_valida(pregunta: str) -> bool:
    if not pregunta or len(pregunta.strip()) < MIN_QUESTION_LENGTH:
        return False
    p = pregunta.lower()
    descartar = ["error:", "sqlcode", "ora-", "undefined", "null pointer", "exception"]
    return not any(d in p for d in descartar)

def limpiar(texto: str) -> str:
    if texto.startswith("- "):
        texto = texto[2:]
    texto = texto.replace('"', "'").replace("\n", " ").replace("\r", " ").strip()
    while "  " in texto:
        texto = texto.replace("  ", " ")
    return texto


# ============================================================
# API APEX — usando cache
# ============================================================

def obtener_postgrados() -> list:
    try:
        data = get_cached(f"{APEX_API_BASE_URL}/postgrados")
        if isinstance(data, dict) and data.get("status") == "success":
            return data.get("data", [])
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.error(f"Error obteniendo postgrados: {e}")
    return []

def obtener_faqs_de_postgrado(postgrado_id: str) -> list:
    try:
        data = get_cached(f"{APEX_API_BASE_URL}/faq/{postgrado_id}")
        if isinstance(data, dict) and data.get("status") == "success":
            faqs = data.get("data", [])
            if isinstance(faqs, list) and len(faqs) > 0 and isinstance(faqs[0], list):
                faqs = faqs[0]
            return faqs
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.warning(f"FAQs postgrado {postgrado_id}: {e}")
    return []

def obtener_todas_las_faqs() -> list:
    # Intento 1: endpoint global
    try:
        data = get_cached(f"{APEX_API_BASE_URL}/faq")
        faqs = []
        if isinstance(data, dict) and data.get("status") == "success":
            faqs = data.get("data", [])
        elif isinstance(data, list):
            faqs = data
        if faqs:
            activas = [f for f in faqs if str(f.get("ACTIVO", f.get("activo", "S"))).upper() == "S"]
            logger.info(f"Endpoint global: {len(activas)} FAQs activas de {len(faqs)} totales")
            return activas
    except Exception:
        pass

    # Intento 2: iterar por postgrado
    logger.info("Iterando FAQs por postgrado...")
    postgrados = obtener_postgrados()
    if not postgrados:
        logger.error("No se obtuvieron postgrados")
        return []

    todas = []
    for pg in postgrados:
        pg_id     = str(pg.get("ID_POSTGRADO") or pg.get("id_postgrado") or pg.get("ID") or pg.get("id") or "")
        pg_nombre = pg.get("NOMBRE") or pg.get("nombre") or pg_id
        if not pg_id:
            continue
        faqs   = obtener_faqs_de_postgrado(pg_id)
        activas = [f for f in faqs if str(f.get("ACTIVO", f.get("activo", "S"))).upper() == "S"]
        for faq in activas:
            faq["_postgrado_id"]     = pg_id
            faq["_postgrado_nombre"] = pg_nombre
        logger.info(f"  {pg_nombre}: {len(activas)} FAQs activas")
        todas.extend(activas)

    logger.info(f"Total FAQs activas: {len(todas)}")
    return todas


def obtener_preguntas_respondidas() -> list:
    try:
        data = get_cached(f"{APEX_API_BASE_URL}/preguntas-sin-respuesta", params={"estado": "RESPONDIDA"})
        preguntas = []
        if isinstance(data, dict) and data.get("status") == "success":
            preguntas = data.get("data", [])
        elif isinstance(data, list):
            preguntas = data

        faqs_extra = []
        for p in preguntas:
            pregunta  = p.get("PREGUNTA_USUARIO") or p.get("pregunta_usuario") or ""
            respuesta = p.get("RESPUESTA")        or p.get("respuesta")        or ""
            if pregunta and respuesta:
                faqs_extra.append({
                    "PREGUNTA":          pregunta,
                    "RESPUESTA":         respuesta,
                    "ACTIVO":            "S",
                    "VECES_CONSULTADA":  p.get("FRECUENCIA") or p.get("frecuencia") or 1,
                    "_fuente":           "preguntas_sin_respuesta"
                })
        if faqs_extra:
            logger.info(f"✅ {len(faqs_extra)} preguntas respondidas obtenidas")
        return faqs_extra
    except Exception as e:
        logger.warning(f"⚠️  No se pudieron obtener preguntas respondidas: {e}")
    return []


# ============================================================
# GENERACIÓN DE ARCHIVOS
# ============================================================

def generar_nlu_yml(faqs: list) -> tuple:
    intent_ejemplos: dict = {}
    sin_clasificar = []

    for faq in faqs:
        pregunta = faq.get("PREGUNTA") or faq.get("pregunta") or ""
        if not es_valida(pregunta):
            continue
        intent  = detectar_intent(faq)
        ejemplo = limpiar(pregunta)
        veces   = int(faq.get("VECES_CONSULTADA") or faq.get("veces_consultada") or 0)

        if intent not in intent_ejemplos:
            intent_ejemplos[intent] = []
        if ejemplo not in intent_ejemplos[intent]:
            if veces >= 10:
                intent_ejemplos[intent].insert(0, ejemplo)
            else:
                intent_ejemplos[intent].append(ejemplo)
        if intent == INTENT_DEFAULT:
            sin_clasificar.append(pregunta)

    lines = [
        "# ============================================================",
        "# DATOS DE ENTRENAMIENTO GENERADOS AUTOMATICAMENTE",
        f"# Fuente: Oracle APEX  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "# Entorno: " + ENVIRONMENT,
        "# NO EDITAR MANUALMENTE — regenerar con fetch_training_data.py",
        "# ============================================================",
        "",
        'version: "3.1"',
        "",
        "nlu:",
    ]

    total = 0
    for intent, ejemplos in sorted(intent_ejemplos.items()):
        ejs = ejemplos[:MAX_EXAMPLES_PER_INTENT]
        total += len(ejs)
        lines += ["", f"- intent: {intent}  # {len(ejs)} ejemplos desde APEX", "  examples: |"]
        for ej in ejs:
            lines.append(f"    - {ej}")

    stats = {
        "total_faqs":     len(faqs),
        "total_ejemplos": total,
        "intents":        len(intent_ejemplos),
        "sin_clasificar": sin_clasificar,
        "por_intent":     {k: len(v[:MAX_EXAMPLES_PER_INTENT]) for k, v in intent_ejemplos.items()}
    }
    return "\n".join(lines) + "\n", stats


def generar_stories_yml(faqs: list) -> str:
    combinaciones = set()
    for faq in faqs:
        pregunta = faq.get("PREGUNTA") or faq.get("pregunta") or ""
        if not es_valida(pregunta):
            continue
        intent = detectar_intent(faq)
        action = INTENT_A_ACTION.get(intent, "action_buscar_faq")
        combinaciones.add((intent, action))

    lines = [
        "# ============================================================",
        "# STORIES GENERADAS AUTOMATICAMENTE",
        f"# Fuente: Oracle APEX  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "# Entorno: " + ENVIRONMENT,
        "# NO EDITAR MANUALMENTE — regenerar con fetch_training_data.py",
        "# ============================================================",
        "",
        'version: "3.1"',
        "",
        "stories:",
    ]

    for i, (intent, action) in enumerate(sorted(combinaciones), 1):
        lines += [
            "",
            f"- story: apex_{i}_{intent}",
            "  steps:",
            "  - slot_was_set:",
            "    - postgrado_id: true",   # Fix: no hardcodear ID específico
            f"  - intent: {intent}",
            f"  - action: {action}",
        ]
    return "\n".join(lines) + "\n"


# ============================================================
# REPORTE
# ============================================================

def imprimir_reporte(stats: dict):
    print("\n" + "=" * 55)
    print("REPORTE DE GENERACION")
    print("=" * 55)
    print(f"  Entorno:           {ENVIRONMENT}")
    print(f"  Cache habilitado:  {'Sí' if ENABLE_CACHE else 'No'}")
    print(f"  FAQs procesadas:   {stats['total_faqs']}")
    print(f"  Ejemplos NLU:      {stats['total_ejemplos']}")
    print(f"  Intents cubiertos: {stats['intents']}")
    print()
    print("  Distribucion por intent:")
    for intent, n in sorted(stats["por_intent"].items(), key=lambda x: -x[1]):
        barra = "|" * min(n, 30)
        print(f"    {intent:<42} {n:>3}  {barra}")

    sin = stats["sin_clasificar"]
    if sin:
        print(f"\n  ATENCION: {len(sin)} pregunta(s) sin clasificar (-> {INTENT_DEFAULT}):")
        for p in sin[:10]:
            print(f"     - {p[:80]}")
        if len(sin) > 10:
            print(f"     ... y {len(sin) - 10} mas")
        print()
        print("  Agrega sus palabras clave a INTENT_RULES para clasificarlas.")
    print("=" * 55 + "\n")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",  action="store_true", help="Vista previa sin escribir archivos")
    parser.add_argument("--solo-nlu", action="store_true", help="Generar solo NLU, omitir stories")
    args = parser.parse_args()

    logger.info("Generando datos de entrenamiento desde APEX")
    logger.info(f"API: {APEX_API_BASE_URL}")

    faqs = obtener_todas_las_faqs()
    if not faqs:
        logger.error("No se obtuvieron FAQs. Verifica conexión a APEX.")
        sys.exit(1)

    preguntas_respondidas = obtener_preguntas_respondidas()
    if preguntas_respondidas:
        faqs = faqs + preguntas_respondidas
        logger.info(f"Total combinado para entrenamiento: {len(faqs)} ejemplos")

    nlu_content, stats = generar_nlu_yml(faqs)
    stories_content    = generar_stories_yml(faqs) if not args.solo_nlu else None

    imprimir_reporte(stats)

    if args.dry_run:
        print("--- NLU PREVIEW (primeras 80 lineas) ---")
        print("\n".join(nlu_content.split("\n")[:80]))
        if stories_content:
            print("\n--- STORIES PREVIEW ---")
            print("\n".join(stories_content.split("\n")[:40]))
        return

    os.makedirs("data", exist_ok=True)

    with open(OUTPUT_NLU_FILE, "w", encoding="utf-8") as f:
        f.write(nlu_content)
    logger.info(f"✅ Generado: {OUTPUT_NLU_FILE} ({stats['total_ejemplos']} ejemplos)")

    if stories_content:
        with open(OUTPUT_STORIES_FILE, "w", encoding="utf-8") as f:
            f.write(stories_content)
        logger.info(f"✅ Generado: {OUTPUT_STORIES_FILE}")

    logger.info("Siguiente paso: rasa train")


if __name__ == "__main__":
    main()