from typing import Any, Text, Dict, List, Optional
from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import (
    SlotSet,
    UserUtteranceReverted,
    FollowupAction,
    AllSlotsReset,      
    Restarted,          
    ConversationPaused  
)
import requests
import urllib3
import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Desactivar warnings SSL (solo para desarrollo/pruebas)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ✅ CONFIGURACIÓN OPTIMIZADA
APEX_API_BASE_URL = os.getenv("APEX_API_URL", "https://oracleapex.com/ords/udchatbot/chatbot")
APEX_TIMEOUT = int(os.getenv("APEX_TIMEOUT", "60"))
ENABLE_CACHE = os.getenv("ENABLE_CACHE", "True").lower() == "true"
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cache simple en memoria
_cache = {}

# Session global con headers tipo navegador
_session = requests.Session()
_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Content-Type': 'application/json'
})


# ============================================
# UTILIDADES
# ============================================

def get_from_cache(key: str) -> Optional[Any]:
    """Obtiene un valor del cache si está disponible y no ha expirado"""
    if not ENABLE_CACHE:
        return None
    
    if key in _cache:
        value, timestamp = _cache[key]
        if datetime.now() - timestamp < timedelta(seconds=CACHE_TTL):
            logger.info(f"✅ Cache hit para: {key}")
            return value
        else:
            del _cache[key]
    
    return None


def set_in_cache(key: str, value: Any):
    """Guarda un valor en el cache"""
    if ENABLE_CACHE:
        _cache[key] = (value, datetime.now())
        logger.info(f"💾 Valor guardado en cache: {key}")


def clear_cache():
    """Limpia todo el cache"""
    global _cache
    _cache = {}
    logger.info("🗑️ Cache limpiado")


def make_api_request(
    method: str,
    endpoint: str,
    data: Optional[Dict] = None,
    params: Optional[Dict] = None
) -> Optional[Dict]:
    
    endpoint_limpio = endpoint.strip('/')
    url = f"{APEX_API_BASE_URL}/{endpoint_limpio}"
    
    try:
        logger.info(f"🌐 API Request: {method} {url}")
        if params:
            logger.info(f"📋 Params: {params}")
        if data:
            logger.info(f"📋 Data: {data}")
        
        if method.upper() == "GET":
            response = _session.get(
                url, 
                params=params, 
                timeout=APEX_TIMEOUT,
                verify=False
            )
        elif method.upper() == "POST":
            response = _session.post(
                url, 
                json=data, 
                timeout=APEX_TIMEOUT,
                verify=False
            )
        else:
            logger.error(f"❌ Método HTTP no soportado: {method}")
            return None
        
        logger.info(f"📥 Response Status: {response.status_code}")
        logger.info(f"📦 Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        
        if response.status_code != 200:
            logger.error(f"❌ Error HTTP {response.status_code}")
            logger.error(f"Response: {response.text[:300]}")
            return None
        
        try:
            json_data = response.json()
        except ValueError as e:
            logger.error(f"❌ Error parseando JSON: {e}")
            logger.error(f"Raw content: {response.text[:300]}")
            return None
        
        # ✅ MANEJAR ESTRUCTURA DE ORACLE APEX
        if isinstance(json_data, dict):
            if json_data.get("status") == "error":
                logger.error(f"❌ Error del servidor APEX: {json_data.get('message')}")
                return None
            
            if json_data.get("status") == "success":
                datos = json_data.get("data", [])
                
                # CRÍTICO: Manejar array anidado [[...]]
                if isinstance(datos, list) and len(datos) > 0:
                    if isinstance(datos[0], list):
                        logger.warning("⚠️ Array anidado detectado. Corrigiendo...")
                        datos = datos[0]
                
                logger.info(f"✅ Respuesta exitosa. Registros: {len(datos) if isinstance(datos, list) else 'N/A'}")
                return {"status": "success", "data": datos}
        
        logger.warning(f"⚠️ Estructura JSON inesperada: {type(json_data)}")
        return json_data
    
    except requests.exceptions.Timeout:
        logger.error(f"⏱️ Timeout en petición a {url}")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"🔌 Error de conexión a {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error en petición: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"💥 Error inesperado: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def registrar_pregunta_sin_respuesta(
    postgrado_id: str,
    pregunta: str,
    usuario_telefono: str = None
) -> bool:
    try:
        # Validar entrada
        if not pregunta or len(pregunta.strip()) < 3:
            logger.warning("⚠️ Pregunta muy corta, no se registra")
            return False
        
        data = {
            "id_postgrado": int(postgrado_id) if postgrado_id else None,
            "pregunta": pregunta.strip()[:1000],  # Límite de 1000 caracteres
            "usuario_telefono": usuario_telefono[:50] if usuario_telefono else None
        }
        
        response = make_api_request(
            "POST",
            "faq/sin-respuesta",
            data=data
        )
        
        if response and response.get("status") == "success":
            id_pregunta = response.get('data', {}).get('id_pregunta')
            logger.info(f"✅ Pregunta sin respuesta registrada - ID: {id_pregunta}")
            return True
        else:
            logger.warning(f"⚠️ No se pudo registrar pregunta sin respuesta")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error registrando pregunta sin respuesta: {e}")
        return False

def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparaciones"""
    import unicodedata
    texto = texto.lower().strip()
    texto = ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )
    return texto


# ============================================
# ACTION: Saludo Inicial Mejorado
# ============================================

class ActionSaludoMejorado(Action):
    """Saludo inicial que pregunta por el programa de interés"""

    def name(self) -> Text:
        return "action_saludo_mejorado"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("👋 Ejecutando action_saludo_mejorado")
        
        mensaje = ( "¡Bienvenido! 🎓\n"
                     "Soy tu asistente virtual de Postgrados de la Facultad de Ingeniería.\n" )
        mensaje = ("📚 *¿Qué programa te interesa?*\n"
                     "Puedes:\n"
                     "• Escribir el nombre del programa (ej: 'avalúos', 'bioingeniería')\n"
                     "• Ver todos los programas escribiendo 'ver programas'\n" )
        
        dispatcher.utter_message(text=mensaje)
        
        return []


# ============================================
# ACTION: Listar Postgrados - OPTIMIZADA
# ============================================

class ActionListarPostgrados(Action):

    def name(self) -> Text:
        return "action_listar_postgrados"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("🚀 Ejecutando action_listar_postgrados")
        
        cache_key = "postgrados_list"
        postgrados = get_from_cache(cache_key)
        
        if postgrados is None:
            response = make_api_request("GET", "postgrados")
            
            if response and response.get("status") == "success":
                postgrados = response.get("data", [])
                
                if postgrados:
                    set_in_cache(cache_key, postgrados)
                    logger.info(f"✅ {len(postgrados)} postgrados obtenidos y cacheados")
            
            if not postgrados:
                logger.warning("⚠️ No se obtuvieron postgrados de la API")
                dispatcher.utter_message(
                    text="Lo siento, no pude obtener la lista de programas en este momento. Por favor, intenta más tarde."
                )
                return []
        
        if postgrados:
            # ✅ CONSTRUCCIÓN DEL MENSAJE COMPLETO
            mensaje = "📚 *Programas de Postgrado Disponibles:*\n\n"
            
            # Agrupar por facultad para mejor organización
            facultades = {}
            for pg in postgrados:
                facultad = pg.get('FACULTAD', pg.get('facultad', 'Sin Facultad'))
                if facultad not in facultades:
                    facultades[facultad] = []
                facultades[facultad].append(pg)
            
            # Construir lista numerada global
            contador = 1
            for facultad, programas in sorted(facultades.items()):
                mensaje += f"🏛️ *{facultad}*\n"
                
                for pg in programas:
                    nombre = pg.get('NOMBRE', pg.get('nombre', 'Sin nombre'))
                    mensaje += f"{contador}. {nombre}\n"
                    contador += 1
                
                mensaje += "\n"  # Separación entre facultades
            
            # Instrucciones finales
            mensaje += ("💡 *¿Cómo seleccionar?*\n"
                 "• Escribe el *número* (ej: 5)\n"
                 "• O escribe el *nombre* del programa\n"
                 "• O palabras clave (ej: 'avalúos', 'software')")
            
            dispatcher.utter_message(text=mensaje)
            
            # Guardar lista completa para selección posterior
            return [SlotSet("ultima_lista_postgrados", postgrados)]
        else:
            dispatcher.utter_message(
                text="No hay programas disponibles en este momento."
            )
            return []


# ============================================
# ACTION: Seleccionar Postgrado - HÍBRIDA MEJORADA
# ============================================

class ActionSeleccionarPostgrado(Action):
    """Busca un postgrado por nombre o número y guarda su ID en el slot"""

    def name(self) -> Text:
        return "action_seleccionar_postgrado"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("🔍 Ejecutando action_seleccionar_postgrado")
        
        postgrado_nombre = next(tracker.get_latest_entity_values("postgrado_nombre"), None)
        
        if not postgrado_nombre:
            postgrado_nombre = tracker.latest_message.get("text")
        
        logger.info(f"Buscando: '{postgrado_nombre}'")
        
        # Obtener lista de postgrados
        cache_key = "postgrados_list"
        postgrados = get_from_cache(cache_key)
        
        if not postgrados:
            response = make_api_request("GET", "postgrados")
            if response and response.get("status") == "success":
                postgrados = response.get("data", [])
                set_in_cache(cache_key, postgrados)
        
        if not postgrados:
            dispatcher.utter_message(
                text="Hubo un problema al buscar el programa. Por favor, intenta nuevamente."
            )
            return []
        
        texto_busqueda = str(postgrado_nombre).strip().lower()
    
        import re
        numero_match = re.search(r'\b(\d+)\b', texto_busqueda)
        
        if numero_match:
            numero = int(numero_match.group(1))
            logger.info(f"Detectado número de selección: {numero}")
            
            # Verificar si hay una lista previa guardada
            ultima_lista = tracker.get_slot("ultima_lista_postgrados")
            
            if ultima_lista and isinstance(ultima_lista, list):
                if 1 <= numero <= len(ultima_lista):
                    pg = ultima_lista[numero - 1]
                    return self._seleccionar_postgrado(pg, dispatcher)
                else:
                    dispatcher.utter_message(
                        text=f"El número {numero} no es válido. Por favor, elige un número entre 1 y {len(ultima_lista)}."
                    )
                    return []
            else:
                # No hay lista previa, buscar en todos los postgrados
                if 1 <= numero <= len(postgrados):
                    pg = postgrados[numero - 1]
                    return self._seleccionar_postgrado(pg, dispatcher)
        
        # BÚSQUEDA POR NOMBRE (mejorada con normalización)
        nombre_norm = normalizar_texto(postgrado_nombre)
        coincidencias = []
        
        # Primero: búsqueda exacta (ignorando acentos)
        for pg in postgrados:
            nombre_pg = pg.get('NOMBRE', pg.get('nombre', ''))
            if normalizar_texto(nombre_pg) == nombre_norm:
                coincidencias = [pg]
                break
        
        # Si no hay coincidencia exacta, búsqueda parcial
        if not coincidencias:
            for pg in postgrados:
                nombre_pg = pg.get('NOMBRE', pg.get('nombre', ''))
                nombre_pg_norm = normalizar_texto(nombre_pg)
                
                # Buscar palabras clave
                palabras_busqueda = nombre_norm.split()
                coincide = all(palabra in nombre_pg_norm for palabra in palabras_busqueda if len(palabra) > 2)
                
                if coincide or nombre_norm in nombre_pg_norm:
                    coincidencias.append(pg)
        
        # ✅ RESULTADOS
        if len(coincidencias) == 1:
            # Una sola coincidencia - SELECCIÓN AUTOMÁTICA
            return self._seleccionar_postgrado(coincidencias[0], dispatcher)
        
        elif len(coincidencias) > 1:
            # Múltiples coincidencias - GUARDAR LISTA PARA SELECCIÓN
            mensaje = f"Encontré {len(coincidencias)} programas relacionados:\n\n"
            
            for i, pg in enumerate(coincidencias[:10], 1):
                nombre = pg.get('NOMBRE', pg.get('nombre', 'Sin nombre'))
                facultad = pg.get('FACULTAD', pg.get('facultad', 'Sin facultad'))
                mensaje += f"{i}. *{nombre}*\n   🏛️ {facultad}\n\n"
            
            if len(coincidencias) > 10:
                mensaje += f"... y {len(coincidencias) - 10} más.\n\n"
            
            mensaje += "💡 *Escribe el número* o el nombre completo del programa que te interesa."
            dispatcher.utter_message(text=mensaje)
            
            return [SlotSet("ultima_lista_postgrados", coincidencias[:10])]
        
        else:
            # No encontrado - SUGERIR ALTERNATIVAS
            mensaje = (f"❌ No encontré el programa '{postgrado_nombre}'.\n\n"
                "💡 *Sugerencias:*\n"
                "• Verifica la escritura\n"
                "• Usa palabras clave (ej: 'avalúos', 'bioingeniería')\n"
                "• Escribe 'ver programas' para la lista completa")
            
            dispatcher.utter_message(text=mensaje)
            
            # Buscar programas similares
            similares = []
            palabras = nombre_norm.split()
            for pg in postgrados:
                nombre_pg_norm = normalizar_texto(pg.get('NOMBRE', pg.get('nombre', '')))
                for palabra in palabras:
                    if len(palabra) > 3 and palabra in nombre_pg_norm:
                        similares.append(pg)
                        break
            
            if similares:
                mensaje_similar = "\n🔍 *¿Te refieres a alguno de estos?*\n\n"
                for i, pg in enumerate(similares[:3], 1):
                    nombre = pg.get('NOMBRE', pg.get('nombre', ''))
                    mensaje_similar += f"{i}. {nombre}\n"
                dispatcher.utter_message(text=mensaje_similar)
                
                return [SlotSet("ultima_lista_postgrados", similares[:3])]
        
        return []
    
    def _seleccionar_postgrado(self, pg: Dict, dispatcher: CollectingDispatcher) -> List[Dict[Text, Any]]:
        """Método auxiliar para seleccionar un postgrado y mostrar el mensaje"""
        nombre = pg.get('NOMBRE', pg.get('nombre', 'Programa'))
        facultad = pg.get('FACULTAD', pg.get('facultad', 'Universidad'))
        id_postgrado = pg.get('ID_POSTGRADO', pg.get('id_postgrado', pg.get('ID', pg.get('id'))))
        
        mensaje = (f"✅ Perfecto, hablemos sobre *{nombre}* de la Facultad de {facultad}.\n\n"
                 "¿Qué quieres saber? Puedes preguntar sobre:\n"
                 "💰 Costos y becas\n"
                 "📋 Requisitos de admisión\n"
                 "📅 Fechas de inscripción\n"
                 "⏱️ Duración del programa\n"
                 "💻 Modalidad (presencial/virtual)\n"
                 "❓ O escribe tu pregunta libremente si no aparece en la lista.\n"
                 "🏠 Retornar al menú principal\n")
        
        dispatcher.utter_message(text=mensaje)
        
        return [
            SlotSet("postgrado_id", str(id_postgrado)),
            SlotSet("postgrado_nombre", nombre),
            SlotSet("ultima_lista_postgrados", None)  # Limpiar lista
        ]


# ============================================
# ACTION: Seleccionar Número - OPTIMIZADA
# ============================================

class ActionSeleccionarNumero(Action):
    """Maneja la selección de un postgrado por número de lista"""

    def name(self) -> Text:
        return "action_seleccionar_numero"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("🔢 Ejecutando action_seleccionar_numero")
        
        mensaje = tracker.latest_message.get("text", "")
        
        import re
        numero_match = re.search(r'\b(\d+)\b', mensaje)
        
        if not numero_match:
            dispatcher.utter_message(
                text="Por favor, especifica el número del programa que te interesa."
            )
            return []
        
        numero = int(numero_match.group(1))
        logger.info(f"Número seleccionado: {numero}")
        
        ultima_lista = tracker.get_slot("ultima_lista_postgrados")
        
        if not ultima_lista or not isinstance(ultima_lista, list):
            dispatcher.utter_message(
                text="No hay una lista activa. Por favor escribe 'ver programas' para ver todas las opciones."
            )
            return []
        
        if numero < 1 or numero > len(ultima_lista):
            dispatcher.utter_message(
                text=f"El número {numero} no es válido. Por favor, elige un número entre 1 y {len(ultima_lista)}."
            )
            return []
        
        pg = ultima_lista[numero - 1]
        nombre = pg.get('NOMBRE', pg.get('nombre', 'Programa'))
        facultad = pg.get('FACULTAD', pg.get('facultad', 'Universidad'))
        id_postgrado = pg.get('ID_POSTGRADO', pg.get('id_postgrado', pg.get('ID', pg.get('id'))))
        
        mensaje = (f"✅ Perfecto, hablemos sobre *{nombre}* de la Facultad de {facultad}.\n\n"
                 "¿Qué quieres saber? Puedes preguntar sobre:\n"
                 "💰 Costos y becas\n"
                 "📋 Requisitos de admisión\n"
                 "📅 Fechas de inscripción\n"
                 "⏱️ Duración del programa\n"
                 "💻 Modalidad (presencial/virtual)\n"
                 "❓ O escribe tu pregunta libremente si no aparece en la lista.\n"
                 "🏠 Retornar al menú principal\n")
        
        dispatcher.utter_message(text=mensaje)
        
        return [
            SlotSet("postgrado_id", str(id_postgrado)),
            SlotSet("postgrado_nombre", nombre),
            SlotSet("ultima_lista_postgrados", None)
        ]


# ============================================
# ACTION: Buscar FAQ 
# ============================================

class ActionBuscarFAQ(Action):

    def name(self) -> Text:
        return "action_buscar_faq"
    
    # ✅ MAPEO MEJORADO - Incluye palabras clave que el usuario usa
    INTENT_KEYWORDS = {
        "consultar_costos": {
            "keywords": ["costo", "precio", "valor", "cuanto cuesta", "matricula", "pagar", "inversion", "SMMLV", "salario"],
            "queries": ["costo", "cuanto cuesta", "valor matricula", "precio"]
        },
        "consultar_requisitos": {
            "keywords": ["requisito", "documento", "necesito", "piden", "admision", "titulo", "hoja vida", "certificado"],
            "queries": ["requisitos", "documentos necesarios", "que necesito"]
        },
        "consultar_fechas": {
            "keywords": ["fecha", "cuando", "inscripciones", "inicia", "abre", "cierra", "plazo", "calendario"],
            "queries": ["fechas inscripcion", "cuando inscripciones", "plazo"]
        },
        "consultar_duracion": {
            "keywords": ["duracion", "dura", "tiempo", "semestre", "año", "mes", "credito", "cuanto dura"],
            "queries": ["duracion", "cuanto dura", "semestres", "tiempo"]
        },
        "consultar_modalidad": {
            "keywords": ["modalidad", "virtual", "presencial", "horario", "online", "distancia", "sede", "hibrido"],
            "queries": ["modalidad", "virtual presencial", "horario"]
        },
        "consultar_plan_estudios": {
            "keywords": ["plan estudios", "materias", "pensum", "asignaturas", "contenido", "que se estudia"],
            "queries": ["plan estudios", "materias", "pensum"]
        },
        "solicitar_link_inscripcion": {
            "keywords": ["link", "enlace", "inscripcion", "donde inscribo", "portal", "pagina"],
            "queries": ["link inscripcion", "donde inscribo", "enlace"]
        },
        "consultar_dirigido": {
            "keywords": ["dirigido", "quien puede", "perfil", "profesionales", "carreras"],
            "queries": ["quien puede", "perfil ingreso", "dirigido"]
        },
        "consultar_proceso_admision": {
            "keywords": ["proceso", "como inscribirme", "pasos", "admision", "inscripcion"],
            "queries": ["como inscribirme", "pasos inscripcion", "proceso"]
        },
        "consultar_becas": {
            "keywords": ["beca", "descuento", "ayuda", "apoyo economico", "subsidio"],
            "queries": ["becas", "descuentos", "ayuda economica"]
        },
        "consultar_financiacion": {
            "keywords": ["financiacion", "cuotas", "credito", "pago", "facilidades"],
            "queries": ["financiacion", "cuotas", "opciones pago"]
        }
    }

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("❓ Ejecutando action_buscar_faq (MEJORADA)")
        
        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "el programa"
        
        if not postgrado_id:
            dispatcher.utter_message(
                text="Por favor, primero dime sobre qué programa necesitas información."
            )
            return [FollowupAction("action_listar_postgrados")]
        
        # Obtener intent y mensaje original
        intent = tracker.latest_message.get("intent", {}).get("name")
        user_message = tracker.latest_message.get("text", "").strip()
        confidence = tracker.latest_message.get("intent", {}).get("confidence", 0)
        
        logger.info(f"Intent: {intent} (conf: {confidence:.2f})")
        logger.info(f"Mensaje: '{user_message}'")
        
        # ✅ NUEVA ESTRATEGIA: Detección de palabras clave
        preguntas_a_probar = []
        
        # 1. Siempre incluir mensaje original primero
        if user_message:
            preguntas_a_probar.append(user_message)
        
        # 2. Si tenemos intent conocido, agregar sus queries
        if intent in self.INTENT_KEYWORDS:
            config = self.INTENT_KEYWORDS[intent]
            
            # Agregar queries predefinidas
            for query in config["queries"]:
                if query not in preguntas_a_probar:
                    preguntas_a_probar.append(query)
            
            logger.info(f"✅ Queries para {intent}: {config['queries']}")
        
        # 3. Detectar palabras clave en el mensaje del usuario
        user_lower = user_message.lower()
        detected_intents = []
        
        for intent_name, config in self.INTENT_KEYWORDS.items():
            for keyword in config["keywords"]:
                if keyword in user_lower:
                    detected_intents.append(intent_name)
                    break
        
        # Si detectamos intent por palabra clave, agregar sus queries
        if detected_intents and detected_intents[0] != intent:
            logger.info(f"🔍 Palabras clave detectadas: {detected_intents}")
            for detected_intent in detected_intents[:1]:  # Solo el primero
                for query in self.INTENT_KEYWORDS[detected_intent]["queries"][:2]:
                    if query not in preguntas_a_probar:
                        preguntas_a_probar.append(query)
        
        # 4. Limitar a máximo 4 intentos
        preguntas_a_probar = preguntas_a_probar[:4]
        logger.info(f"🔍 Probando {len(preguntas_a_probar)} variantes")
        
        # ✅ BÚSQUEDA SECUENCIAL
        for idx, pregunta in enumerate(preguntas_a_probar, 1):
            logger.info(f"Intento {idx}/{len(preguntas_a_probar)}: '{pregunta}'")
            
            # Cache
            cache_key = f"faq_{postgrado_id}_{self._normalizar_cache_key(pregunta)}"
            cached = get_from_cache(cache_key)
            
            if cached:
                logger.info(f"💾 Cache hit")
                mensaje = self._formatear_respuesta_completa(cached, intent, postgrado_nombre)
                dispatcher.utter_message(text=mensaje)
                return [SlotSet("ultima_respuesta", cached)]
            
            # Llamar API
            response = make_api_request(
                "GET",
                f"faq/buscar/{postgrado_id}",
                params={"pregunta": pregunta}
            )
            
            if response:
                respuesta = self._extraer_respuesta(response)
                
                if respuesta and self._es_respuesta_valida(respuesta):
                    logger.info(f"✅ Respuesta válida encontrada")
                    set_in_cache(cache_key, respuesta)
                    
                    mensaje = self._formatear_respuesta_completa(respuesta, intent, postgrado_nombre)
                    dispatcher.utter_message(text=mensaje)
                    return [SlotSet("ultima_respuesta", respuesta)]
        
        # ❌ No encontrado
        logger.warning(f"❌ No se encontró respuesta")
        mensaje = self._mensaje_no_encontrado(intent, postgrado_nombre, user_message)
        dispatcher.utter_message(text=mensaje)

        # ✅ REGISTRAR PREGUNTA SIN RESPUESTA
        postgrado_id = tracker.get_slot("postgrado_id")
        user_message = tracker.latest_message.get("text", "")
        usuario_id = tracker.sender_id
        
        if postgrado_id:
            registrar_pregunta_sin_respuesta(
                postgrado_id=postgrado_id,
                pregunta=user_message,
                usuario_telefono=usuario_id
            )
        
        mensaje = self._mensaje_no_encontrado(intent, postgrado_nombre, user_message)
        dispatcher.utter_message(text=mensaje)
        
        return []
    
    def _normalizar_cache_key(self, texto: str) -> str:
        """Crea key de cache normalizada"""
        texto_norm = normalizar_texto(texto)
        return texto_norm[:30]
    
    def _extraer_respuesta(self, response: Dict) -> Optional[str]:
        """Extrae respuesta de API"""
        if not response or not isinstance(response, dict):
            return None
        
        if response.get("status") == "success":
            data = response.get("data", {})
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            if isinstance(data, dict):
                return data.get("RESPUESTA", data.get("respuesta", ""))
        
        return response.get("RESPUESTA", response.get("respuesta", ""))
    
    def _es_respuesta_valida(self, respuesta: str) -> bool:
        """Valida que no sea mensaje de error"""
        if not respuesta or len(respuesta.strip()) < 15:
            return False
        
        resp_lower = respuesta.lower()
        
        errores = [
            'error:', 'no encontré', 'intenta reformular',
            'muy corta', 'código:', 'sqlcode', 'error interno'
        ]
        
        return not any(err in resp_lower for err in errores)
    
    def _formatear_respuesta_completa(
        self, respuesta: str, intent: str, postgrado_nombre: str
    ) -> str:
        """Formatea respuesta con sugerencias"""
        
        emoji_map = {
            "consultar_costos": "💰",
            "consultar_requisitos": "📋",
            "consultar_fechas": "📅",
            "consultar_duracion": "⏱️",
            "consultar_modalidad": "💻",
            "consultar_plan_estudios": "📚",
            "solicitar_link_inscripcion": "🔗",
            "consultar_dirigido": "👥",
            "consultar_becas": "🎓",
            "consultar_financiacion": "💳"
        }
        
        emoji = emoji_map.get(intent, "ℹ️")
        mensaje = f"{emoji} *{postgrado_nombre}*\n\n{respuesta}\n\n"
        
        # Sugerencias contextuales
        if intent == "consultar_costos":
            mensaje += "También: 📋 Requisitos • 📅 Fechas • 💳 Financiación"
        elif intent == "consultar_modalidad":
            mensaje += "También: ⏱️ Duración • 📅 Fechas • 🔗 Inscripción"
        elif intent == "consultar_duracion":
            mensaje += "También: 💻 Modalidad • 📚 Plan estudios • 💰 Costos"
        else:
            mensaje += "También: 💰 Costos • 📋 Requisitos • 📅 Fechas"
        
        mensaje += "\n\n🏠 'menú principal' para otros programas"
        
        return mensaje
    
    def _mensaje_no_encontrado(self, intent: str, postgrado: str, pregunta: str) -> str:
        """Mensaje cuando no hay respuesta"""
        
        mensaje = f"🤔 No encontré información sobre:\n*\"{pregunta}\"*\n\n"
        
        # Sugerencias según intent
        if intent == "consultar_modalidad":
            mensaje += "💡 Intenta:\n• 'modalidad'\n• 'es virtual o presencial'\n• 'horarios'\n\n"
        elif intent == "consultar_duracion":
            mensaje += "💡 Intenta:\n• 'cuanto dura'\n• 'duracion'\n• 'semestres'\n\n"
        elif intent == "consultar_proceso_admision":
            mensaje += "💡 Intenta:\n• 'como inscribirme'\n• 'proceso inscripcion'\n• 'link inscripcion'\n\n"
        else:
            mensaje += "💡 Puedo ayudarte con:\n💰 Costos • 📋 Requisitos • 📅 Fechas\n💻 Modalidad • ⏱️ Duración • 🔗 Inscripción\n\n"
        
        mensaje += "O escribe 'contactar asesor' para ayuda personalizada."
        
        return mensaje


# ============================================
# ACTION: Manejar Pregunta General
# ============================================

class ActionManejarPreguntaGeneral(Action):
    """Maneja preguntas generales cuando el usuario pide 'información' sin especificar qué"""

    def name(self) -> Text:
        return "action_manejar_pregunta_general"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("ℹ️ Ejecutando action_manejar_pregunta_general")
        
        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "el programa"
        
        if not postgrado_id:
            dispatcher.utter_message(
                text="Por favor, primero dime sobre qué programa necesitas información."
            )
            return [FollowupAction("action_listar_postgrados")]
        
        response = make_api_request(
            "GET",
            f"faq/buscar/{postgrado_id}",
            params={"pregunta": "informacion"}
        )
        
        if response and response.get("status") == "success":
            data = response.get("data", {})
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            respuesta = data.get("RESPUESTA", data.get("respuesta", ""))
            
            if respuesta:
                # ✅ UN SOLO MENSAJE con respuesta + opciones
                mensaje = f"ℹ️ *{postgrado_nombre}*\n\n{respuesta}\n\n"
                mensaje += ("📋 *¿Qué más te gustaría saber?*\n\n"
                         "💰 Costos y formas de pago\n"
                         "📋 Requisitos de admisión\n"
                         "📅 Fechas de inscripción\n"
                         "⏱️ Duración del programa\n"
                         "💻 Modalidad y horarios\n"
                         "📚 Plan de estudios\n"
                         "🔗 Link de inscripción\n"
                         "❓ O escribe tu pregunta libremente si no aparece en la lista.\n")
                
                dispatcher.utter_message(text=mensaje)
                return []
        
        # Si no hay información general, mostrar opciones
        mensaje = f"ℹ️ *Información sobre {postgrado_nombre}*\n\n"
        mensaje += ("¿Qué aspecto específico te interesa?\n\n"
                 "💰 Costos\n"
                 "📋 Requisitos\n"
                 "📅 Fechas\n"
                 "⏱️ Duración\n"
                 "💻 Modalidad\n"
                 "📚 Plan de estudios\n"
                 "🔗 Link de inscripción")
        
        dispatcher.utter_message(text=mensaje)
        
        return []


# ============================================
# ACTION: Guardar Historial
# ============================================

class ActionGuardarHistorial(Action):
    """Guarda la conversación en el historial"""

    def name(self) -> Text:
        return "action_guardar_historial"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("💾 Ejecutando action_guardar_historial")
        
        usuario_telefono = tracker.sender_id
        mensaje_usuario = tracker.latest_message.get("text")
        postgrado_id = tracker.get_slot("postgrado_id")
        ultima_respuesta = tracker.get_slot("ultima_respuesta")
        
        if not ultima_respuesta:
            eventos = tracker.events
            for evento in reversed(eventos):
                if evento.get("event") == "bot" and evento.get("text"):
                    ultima_respuesta = evento.get("text")
                    break
        
        data = {
            "usuario": usuario_telefono,
            "mensaje": mensaje_usuario,
            "respuesta": ultima_respuesta or "Sin respuesta",
            "id_postgrado": int(postgrado_id) if postgrado_id else None
        }
        
        response = make_api_request("POST", "historial", data=data)
        
        if response:
            logger.info("✅ Historial guardado correctamente")
        else:
            logger.warning("⚠️ No se pudo guardar el historial")
        
        return []


# ============================================
# ACTION: Contactar Asesor
# ============================================

class ActionContactarAsesor(Action):
    """
    Acción simplificada: solo valida postgrado y activa el form.
    El envío real se hace en action_enviar_datos_contacto
    """

    def name(self) -> Text:
        return "action_contactar_asesor"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("📞 Ejecutando action_contactar_asesor")
        
        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "postgrados"
        
        # ✅ VALIDACIÓN: Debe tener postgrado seleccionado
        if not postgrado_id:
            dispatcher.utter_message(
                text=(
                    "❌ Primero selecciona un programa de postgrado.\n\n"
                    "Escribe 'ver programas' para explorar las opciones."
                )
            )
            return [FollowupAction("action_listar_postgrados")]
        
        # ✅ MENSAJE INICIAL (UN SOLO MENSAJE)
        mensaje = (
            f"📞 *Contacto con Asesor - {postgrado_nombre}*\n\n"
            "Para que un especialista te contacte, necesito algunos datos.\n\n"
            "El proceso tomará solo 1 minuto. ¿Comenzamos?\n\n"
            "_(Escribe 'cancelar' en cualquier momento para detener)_"
        )
        
        dispatcher.utter_message(text=mensaje)
        
        # ✅ ACTIVAR FORMULARIO
        return [FollowupAction("datos_contacto_form")]


# ============================================
# ACTION: Default Fallback
# ============================================

class ActionDefaultFallback(Action):
    """Acción por defecto cuando no se entiende la intención - MEJORADA"""

    def name(self) -> Text:
        return "action_default_fallback"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("🤷 Ejecutando action_default_fallback")
        
        postgrado_id = tracker.get_slot("postgrado_id")
        contador = tracker.get_slot("contador_fallback") or 0
        mensaje_usuario = tracker.latest_message.get("text", "").lower()
        
        # ✅ NUEVO: Detectar despedidas implícitas
        despedidas_implicitas = [
            "nada mas", "nada más", "eso es todo", "solo eso", 
            "suficiente", "ya está", "ya esta", "listo", "perfecto",
            "no necesito mas", "no necesito más", "con eso"
        ]
        
        if any(despedida in mensaje_usuario for despedida in despedidas_implicitas):
            logger.info("✅ Despedida implícita detectada en fallback")
            dispatcher.utter_message(
                text="¡Perfecto! Si necesitas algo más, aquí estaré. ¡Hasta pronto! 👋"
            )
            return [
                SlotSet("contador_fallback", 0),
                FollowupAction("action_despedida")
            ]
        
        # Incrementar contador
        contador += 1
        logger.info(f"Contador fallback: {contador}/3")
        
        # ✅ ESCALAMIENTO GRADUAL - UN SOLO MENSAJE POR NIVEL
        if contador == 1:
            # Primer fallback: sugerencia amigable
            mensaje = "🤔 No estoy seguro de entender.\n\n"
            
            if not postgrado_id:
                mensaje += ("¿Quieres que te muestre los programas disponibles?\n\n"
                         "Escribe:\n• 'ver programas'\n• 'ayuda'\n• O el nombre de un programa")
            else:
                mensaje += ("Puedes preguntarme:\n"
                         "💰 ¿Cuánto cuesta?\n"
                         "📋 ¿Qué requisitos necesito?\n"
                         "📅 ¿Cuándo son las inscripciones?\n"
                         "📞 Contactar asesor")
            
            dispatcher.utter_message(text=mensaje)
            return [SlotSet("contador_fallback", contador)]
        
        elif contador == 2:
            # Segundo fallback: opciones más explícitas
            mensaje = "😅 Parece que no nos estamos entendiendo bien.\n\n"
            mensaje += "Te sugiero:\n\n"
            
            if postgrado_id:
                mensaje += ("1️⃣ Hacer una pregunta específica (ej: 'costos', 'fechas')\n"
                         "2️⃣ Cambiar de programa (escribe 'menú principal')\n"
                         "3️⃣ Hablar con un asesor (escribe 'asesor')")
            else:
                mensaje += ("1️⃣ Ver todos los programas → 'ver programas'\n"
                         "2️⃣ Buscar un programa específico → escribe su nombre\n"
                         "3️⃣ Pedir ayuda → 'ayuda'")
            
            dispatcher.utter_message(text=mensaje)
            return [SlotSet("contador_fallback", contador)]
        
        else:
            # Tercer fallback: escalar a humano
            mensaje = ("😔 Lamento no poder ayudarte de manera satisfactoria.\n\n"
                     "🤝 ¿Te gustaría hablar con un asesor humano?\n\n"
                     "Un especialista puede resolver tus dudas personalizadamente.\n\n"
                     "Escribe 'sí' o 'contactar asesor' para que te llamemos.")
            
            dispatcher.utter_message(text=mensaje)
            return [
                SlotSet("contador_fallback", 0),  # Resetear para próxima vez
                FollowupAction("action_escalar_a_humano")
            ]


# ============================================
# ACTION: Reiniciar Conversación
# ============================================

class ActionReiniciarConversacion(Action):
    """Reinicia la conversación y limpia todos los slots"""

    def name(self) -> Text:
        return "action_reiniciar_conversacion"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("🔄 Ejecutando action_reiniciar_conversacion")
        
        mensaje = ("🔄 *Conversación reiniciada*\n\n"
                 "¡Hola! Soy tu asistente virtual de Postgrados. 👋\n\n"
                 "📚 *¿Qué programa te interesa?*\n\n"
                 "Escribe el nombre del programa o 'ver programas' para ver todas las opciones.")
        
        dispatcher.utter_message(text=mensaje)
        
        return [AllSlotsReset()]


# ============================================
# ACTION: Despedida
# ============================================

class ActionDespedida(Action):
    """Maneja la despedida del usuario y cierra la conversación - MEJORADA"""

    def name(self) -> Text:
        return "action_despedida"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("👋 Ejecutando action_despedida")
        
        postgrado_nombre = tracker.get_slot("postgrado_nombre")
        intent = tracker.latest_message.get("intent", {}).get("name", "")
        
        # ✅ Mensajes personalizados según contexto (UN SOLO MENSAJE)
        if postgrado_nombre:
            mensaje = (f"👋 ¡Hasta pronto!\n\n"
                        f"Espero haber resuelto tus dudas sobre *{postgrado_nombre}*.\n\n"
                        "¡Mucho éxito en tu formación académica! 🎓")
        elif intent == "negate_and_end":
            # Usuario dijo "nada más" o similar
            mensaje = ("✅ ¡Perfecto!\n\n"
                        "Si tienes más preguntas en el futuro, no dudes en volver.\n\n"
                        "¡Éxitos! 🎓")
        else:
            # Despedida genérica
            mensaje = ("👋 ¡Hasta luego!\n\n"
                     "Recuerda que puedes volver cuando necesites información.\n\n"
                     "¡Que tengas un excelente día! 😊")
        
        # ✅ Enviar mensaje sin metadata (más simple)
        dispatcher.utter_message(text=mensaje)
        
        # ✅ Solo guardar historial si hubo conversación significativa
        eventos_usuario = [e for e in tracker.events if e.get("event") == "user"]
        
        if len(eventos_usuario) > 2:  # Si hubo más de 2 mensajes del usuario
            logger.info("💾 Guardando historial antes de despedirse")
            # Guardar historial
            usuario_telefono = tracker.sender_id
            postgrado_id = tracker.get_slot("postgrado_id")
            
            data = {
                "usuario": usuario_telefono,
                "mensaje": "Conversación finalizada",
                "respuesta": mensaje,
                "id_postgrado": int(postgrado_id) if postgrado_id else None
            }
            
            try:
                make_api_request("POST", "historial", data=data)
            except Exception as e:
                logger.error(f"Error guardando historial: {e}")
        
        # ✅ Eventos para finalizar limpiamente
        return [
            AllSlotsReset(),      # Limpia todos los slots
            Restarted()           # Reinicia la conversación
        ]


# ============================================
# FORM VALIDATION: Datos de Contacto
# ============================================

class ValidateDatosContactoForm(FormValidationAction):
    """Valida el formulario de datos de contacto"""

    def name(self) -> Text:
        return "validate_datos_contacto_form"

    def validate_nombre_completo(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        
        if not slot_value or len(slot_value.strip()) < 3:
            dispatcher.utter_message(
                text="Por favor, ingresa tu nombre completo (mínimo 3 caracteres)."
            )
            return {"nombre_completo": None}
        
        palabras = slot_value.strip().split()
        if len(palabras) < 2:
            dispatcher.utter_message(
                text="Por favor, ingresa tu nombre y apellido."
            )
            return {"nombre_completo": None}
        
        return {"nombre_completo": slot_value.strip()}

    def validate_email(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        
        import re
        
        if not slot_value:
            dispatcher.utter_message(
                text="Por favor, ingresa un correo electrónico válido."
            )
            return {"email": None}
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if not re.match(email_pattern, slot_value):
            dispatcher.utter_message(
                text="El formato del correo no es válido. Intenta de nuevo."
            )
            return {"email": None}
        
        return {"email": slot_value.lower().strip()}

    def validate_telefono(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        
        import re
        
        if not slot_value:
            dispatcher.utter_message(
                text="Por favor, ingresa un número de teléfono válido."
            )
            return {"telefono": None}
        
        telefono_limpio = re.sub(r'[^\d+]', '', slot_value)
        
        if len(telefono_limpio) < 7 or len(telefono_limpio) > 15:
            dispatcher.utter_message(
                text="El número debe tener entre 7 y 15 dígitos."
            )
            return {"telefono": None}
        
        return {"telefono": telefono_limpio}


# ============================================
# ACTION: Enviar Datos de Contacto
# ============================================

class ActionEnviarDatosContacto(Action):
    """
    Envía los datos completos a la API DESPUÉS de que el form termine
    """

    def name(self) -> Text:
        return "action_enviar_datos_contacto"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("📧 Ejecutando action_enviar_datos_contacto")
        
        # ✅ OBTENER DATOS DEL FORM (ya validados)
        nombre = tracker.get_slot("nombre_completo")
        email = tracker.get_slot("email")
        telefono = tracker.get_slot("telefono")
        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "postgrado"
        
        # ✅ MENSAJE CON TODOS LOS DATOS (para la API)
        mensaje_api = (
            f"Solicitud de contacto\n"
            f"Nombre: {nombre}\n"
            f"Email: {email}\n"
            f"Programa: {postgrado_nombre}"
        )
        
        # ✅ DATA PARA LA API
        data = {
            "telefono": telefono,
            "postgrado_id": int(postgrado_id),
            "mensaje": mensaje_api
        }
        
        logger.info(f"📤 Enviando a API: {data}")
        
        # ✅ LLAMAR A LA API
        response = make_api_request("POST", "contacto", data=data)
        
        # ✅ MANEJAR RESPUESTA
        if response and response.get("status") == "success":
            # ✅ UN SOLO MENSAJE DE ÉXITO
            mensaje = (
                f"✅ *¡Perfecto, {nombre}!* Tu solicitud ha sido registrada.\n\n"
                f"📧 Recibirás información en: {email}\n"
                f"📱 Te contactaremos al: {telefono}\n\n"
                "Un asesor especializado se comunicará contigo en las próximas 24 horas.\n\n"
                "💡 ¿Hay algo más en lo que pueda ayudarte?"
            )
            
            dispatcher.utter_message(text=mensaje)
            return [SlotSet("ultima_respuesta", mensaje)]
        
        elif response and response.get("status") == "error":
            error_msg = response.get("message", "Error desconocido")
            logger.error(f"❌ Error del servidor: {error_msg}")
            
            dispatcher.utter_message(
                text=(
                    f"❌ Hubo un problema al registrar tu solicitud:\n\n{error_msg}\n\n"
                    "Por favor, intenta nuevamente o escribe directamente a:\n"
                    "📧 postgrados@udistrital.edu.co"
                )
            )
        
        else:
            # Error de conexión
            dispatcher.utter_message(
                text=(
                    "❌ No pude conectar con el servidor en este momento.\n\n"
                    "Por favor, intenta nuevamente o contacta directamente:\n"
                    "📧 postgrados@udistrital.edu.co\n"
                    "📱 WhatsApp: +57 300 123 4567"
                )
            )
        
        return []


# ============================================
# ACTION: Obtener Información Específica
# ============================================

class ActionObtenerInfoEspecifica(Action):
    """Obtiene información específica de un postgrado"""

    def name(self) -> Text:
        return "action_obtener_info_especifica"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("ℹ️ Ejecutando action_obtener_info_especifica")
        
        postgrado_id = tracker.get_slot("postgrado_id")
        
        if not postgrado_id:
            dispatcher.utter_message(
                text="Por favor, primero selecciona un programa de postgrado."
            )
            return [FollowupAction("action_listar_postgrados")]
        
        intent = tracker.latest_message.get("intent", {}).get("name")
        
        response = make_api_request("GET", f"postgrados/{postgrado_id}")
        
        if not response or response.get("status") != "success":
            dispatcher.utter_message(
                text="No pude obtener esa información. ¿Quieres que un asesor te contacte?"
            )
            return []
        
        info = response.get("data", {})
        if isinstance(info, list) and len(info) > 0:
            info = info[0]
        
        # Extraer campos (compatible con mayúsculas y minúsculas)
        nombre = info.get('NOMBRE', info.get('nombre', 'Programa'))
        facultad = info.get('FACULTAD', info.get('facultad', 'Universidad'))
        descripcion = info.get('DESCRIPCION', info.get('descripcion', ''))
        costo = info.get('COSTO', info.get('costo', ''))
        duracion = info.get('DURACION', info.get('duracion', ''))
        modalidad = info.get('MODALIDAD', info.get('modalidad', ''))
        requisitos = info.get('REQUISITOS', info.get('requisitos', ''))
        fechas = info.get('FECHAS', info.get('fechas', ''))
        correo = info.get('CORREO_ELECTRONICO', info.get('correo_electronico', ''))
        
        # ✅ UN SOLO MENSAJE según el intent
        if intent == "preguntar_costo" and costo:
            mensaje = f"💰 *Información de Costos - {nombre}*\n\n{costo}"
        elif intent == "preguntar_fechas" and fechas:
            mensaje = f"📅 *Fechas Importantes - {nombre}*\n\n{fechas}"
        elif intent == "preguntar_requisitos" and requisitos:
            mensaje = f"📋 *Requisitos - {nombre}*\n\n{requisitos}"
        elif intent == "preguntar_duracion" and duracion:
            mensaje = f"⏱️ *Duración - {nombre}*\n\n{duracion}"
        elif intent == "preguntar_modalidad" and modalidad:
            mensaje = f"💻 *Modalidad - {nombre}*\n\n{modalidad}"
        else:
            # Información general en un solo mensaje
            mensaje = f"📚 *{nombre}*\n\n"
            mensaje += f"🏛️ Facultad: {facultad}\n\n"
            if descripcion:
                mensaje += f"📝 {descripcion}\n\n"
            if correo:
                mensaje += (f"📧 Contacto: {correo}\n\n"
                    "¿Qué información específica necesitas?\n"
                    "💰 Costos • 📅 Fechas • 📋 Requisitos • ⏱️ Duración • 💻 Modalidad")
        
        dispatcher.utter_message(text=mensaje)
        
        return []


# ============================================
# ACTION: Buscar FAQ Libre
# ============================================

class ActionBuscarFaqLibre(Action):
    """Búsqueda FAQ mejorada con registro de preguntas sin respuesta"""

    def name(self) -> Text:
        return "action_buscar_faq_libre"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "este programa"
        user_message = tracker.latest_message.get('text', '').strip()
        usuario_id = tracker.sender_id
        
        # ==================== VALIDACIONES PREVIAS ====================
        if not postgrado_id:
            dispatcher.utter_message(text=(
                "Necesito saber sobre qué programa preguntas. 🤔\n\n"
                "Escribe 'menú principal' para ver los programas disponibles."
            ))
            return []
        
        if len(user_message) < 3:
            dispatcher.utter_message(text=(
                "Tu pregunta es muy corta. ¿Podrías ser más específico? 😅"
            ))
            return []
        
        # ==================== CACHE ====================
        try:
            import hashlib
            pregunta_hash = hashlib.sha256(
                f"{postgrado_id}_{user_message.lower()}".encode()
            ).hexdigest()[:16]
            
            cache_key = f"faq_libre_{pregunta_hash}"
            cached_response = get_from_cache(cache_key)
            
            if cached_response:
                logger.info("💾 Cache hit")
                mensaje = self._formatear_respuesta(cached_response, postgrado_nombre, user_message)
                dispatcher.utter_message(text=mensaje)
                return [SlotSet("ultima_respuesta", cached_response)]
        except Exception as e:
            logger.warning(f"⚠️ Error en cache: {e}")
            cache_key = None
        
        # ==================== LLAMADA API ====================
        try:
            response = make_api_request(
                "GET",
                f"faq/buscar/{postgrado_id}",
                params={"pregunta": user_message}
            )
            
            if not response:
                logger.error("❌ Sin respuesta de API")
                # ✅ REGISTRAR PREGUNTA SIN RESPUESTA
                registrar_pregunta_sin_respuesta(
                    postgrado_id=postgrado_id,
                    pregunta=user_message,
                    usuario_telefono=usuario_id
                )
                self._enviar_mensaje_error_api(dispatcher)
                return []
            
            # ==================== EXTRAER RESPUESTA ====================
            respuesta = self._extraer_respuesta_apex(response)
            
            if not respuesta:
                logger.error("❌ No se pudo extraer respuesta")
                # ✅ REGISTRAR PREGUNTA SIN RESPUESTA
                registrar_pregunta_sin_respuesta(
                    postgrado_id=postgrado_id,
                    pregunta=user_message,
                    usuario_telefono=usuario_id
                )
                self._enviar_sugerencias(dispatcher, postgrado_nombre, user_message)
                return []
            
            logger.info(f"📄 Respuesta: {respuesta[:100]}...")
            
            # ==================== VALIDAR TIPO DE RESPUESTA ====================
            tipo_respuesta = self._clasificar_respuesta_apex(respuesta)
            
            if tipo_respuesta == "ERROR_TECNICO":
                logger.error(f"❌ Error técnico de APEX")
                # ✅ REGISTRAR PREGUNTA SIN RESPUESTA
                registrar_pregunta_sin_respuesta(
                    postgrado_id=postgrado_id,
                    pregunta=user_message,
                    usuario_telefono=usuario_id
                )
                self._enviar_mensaje_error_api(dispatcher)
                return []
            
            elif tipo_respuesta == "NO_ENCONTRADO":
                logger.info(f"ℹ️ APEX no encontró información específica")
                # ✅ REGISTRAR PREGUNTA SIN RESPUESTA
                registrar_pregunta_sin_respuesta(
                    postgrado_id=postgrado_id,
                    pregunta=user_message,
                    usuario_telefono=usuario_id
                )
                self._enviar_sugerencias(dispatcher, postgrado_nombre, user_message)
                return []
            
            elif tipo_respuesta == "RESPUESTA_VALIDA":
                logger.info(f"✅ Respuesta válida encontrada")
                
                if cache_key:
                    set_in_cache(cache_key, respuesta)
                
                mensaje = self._formatear_respuesta(respuesta, postgrado_nombre, user_message)
                dispatcher.utter_message(text=mensaje)
                return [SlotSet("ultima_respuesta", respuesta)]
            
            else:
                # RESPUESTA_AMBIGUA
                logger.warning(f"⚠️ Respuesta ambigua")
                mensaje = self._formatear_respuesta(respuesta, postgrado_nombre, user_message)
                dispatcher.utter_message(text=mensaje)
                return [SlotSet("ultima_respuesta", respuesta)]
        
        except requests.exceptions.Timeout:
            logger.error("⏱️ Timeout")
            # ✅ REGISTRAR PREGUNTA SIN RESPUESTA
            registrar_pregunta_sin_respuesta(
                postgrado_id=postgrado_id,
                pregunta=user_message,
                usuario_telefono=usuario_id
            )
            dispatcher.utter_message(text=(
                "La consulta está tardando más de lo normal. ⏱️\n\n"
                "Por favor, intenta nuevamente."
            ))
        
        except Exception as e:
            logger.error(f"❌ Error inesperado: {type(e).__name__}: {str(e)}")
            # ✅ REGISTRAR PREGUNTA SIN RESPUESTA
            registrar_pregunta_sin_respuesta(
                postgrado_id=postgrado_id,
                pregunta=user_message,
                usuario_telefono=usuario_id
            )
            self._enviar_mensaje_error_api(dispatcher)
        
        return []
    
    # ==================== MÉTODOS AUXILIARES ====================
    
    def _clasificar_respuesta_apex(self, respuesta: str) -> str:
        """
        ✅ CLASIFICACIÓN CORRECTA de respuestas APEX
        
        Returns:
            - "ERROR_TECNICO": Error del servidor/código
            - "NO_ENCONTRADO": APEX dice explícitamente "no encontré" (NO es error)
            - "RESPUESTA_VALIDA": Contenido útil
            - "RESPUESTA_AMBIGUA": Podría ser válida o genérica
        """
        if not respuesta or len(respuesta.strip()) < 10:
            return "ERROR_TECNICO"
        
        resp_lower = respuesta.lower()
        
        # ========== 1. ERRORES TÉCNICOS (servidor/código) ==========
        errores_tecnicos = [
            'error interno',
            'código:',
            '(código:',
            'sqlcode',
            'ora-',
            'exception',
            'stack trace',
            'null pointer'
        ]
        
        if any(err in resp_lower for err in errores_tecnicos):
            return "ERROR_TECNICO"
        
        # ========== 2. VALIDACIÓN DE INPUT (usuario escribió mal) ==========
        # Esto NO es error técnico, es feedback al usuario
        validaciones_input = [
            'error: id de postgrado',
            'error: por favor escribe',
            'tu pregunta es muy corta',
            '¿podrías ser más específico?'
        ]
        
        if any(val in resp_lower for val in validaciones_input):
            return "NO_ENCONTRADO"  # Tratar como "no encontrado"
        
        # ========== 3. NO ENCONTRADO (APEX no tiene info) ==========
        # ✅ ESTAS SON RESPUESTAS VÁLIDAS, no errores
        mensajes_no_encontrado = [
            'no encontré una respuesta exacta',
            'no encontré información específica',
            'intenta reformular',
            'no hay preguntas frecuentes disponibles',
            'no tengo información sobre',
            'no dispongo de datos'
        ]
        
        if any(msg in resp_lower for msg in mensajes_no_encontrado):
            return "NO_ENCONTRADO"
        
        # ========== 4. RESPUESTA VÁLIDA ==========
        # Indicadores de contenido útil
        indicadores_validos = [
            'el costo',
            'los requisitos',
            'la duración',
            'la modalidad',
            'las fechas',
            'el programa',
            'la especialización',
            'puedes',
            'debes',
            'necesitas',
            'se requiere',
            'smmlv',
            'semestre',
            'crédito',
            '$',
            'inscripción',
            'admisión'
        ]
        
        # Si tiene al menos 2 indicadores Y más de 50 caracteres
        contador = sum(1 for ind in indicadores_validos if ind in resp_lower)
        
        if contador >= 2 and len(respuesta) > 50:
            return "RESPUESTA_VALIDA"
        
        # Si tiene al menos 1 indicador Y más de 100 caracteres
        if contador >= 1 and len(respuesta) > 100:
            return "RESPUESTA_VALIDA"
        
        # ========== 5. RESPUESTA AMBIGUA ==========
        # Respuestas genéricas que podrían ser válidas
        return "RESPUESTA_AMBIGUA"
    
    def _extraer_respuesta_apex(self, response) -> Optional[str]:
        """Extrae respuesta de API (sin cambios)"""
        try:
            content_type = response.headers.get('Content-Type', '').lower()
            
            if 'application/json' in content_type:
                try:
                    data = response.json()
                    
                    if isinstance(data, dict) and 'data' in data:
                        data = data['data']
                    
                    if isinstance(data, dict) and 'respuesta' in data:
                        return str(data['respuesta']).strip()
                    
                    if isinstance(data, str):
                        return data.strip()
                    
                    return str(data).strip() if data else None
                    
                except ValueError:
                    pass
            
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"Error extrayendo respuesta: {e}")
            return None
    
    def _formatear_respuesta(self, respuesta: str, postgrado_nombre: str, 
                            pregunta_original: str) -> str:
        """Formatea respuesta con sugerencias contextuales"""
        
        mensaje = f"💡 *{postgrado_nombre}*\n\n{respuesta}\n\n"
        
        resp_lower = respuesta.lower()
        
        # Sugerencias según tema detectado
        if any(w in resp_lower for w in ['costo', 'precio', 'pago', 'valor']):
            mensaje += "También: 📋 Requisitos • 📅 Fechas • 💳 Financiación"
        
        elif any(w in resp_lower for w in ['convenio', 'empresa', 'alianza']):
            mensaje += "También: 💼 Prácticas • 🎓 Perfil egresados"
        
        elif any(w in resp_lower for w in ['parqueadero', 'biblioteca', 'laboratorio']):
            mensaje += "También: 💻 Modalidad • 📞 Contactar asesor"
        
        else:
            mensaje += "También: 💰 Costos • 📋 Requisitos • 📅 Fechas"
        
        mensaje += "\n\n🏠 'menú principal' para otros programas"
        
        return mensaje
    
    def _enviar_sugerencias(self, dispatcher: CollectingDispatcher, 
                           postgrado_nombre: str, pregunta: str):
        """Envía sugerencias cuando no hay respuesta específica"""
        
        mensaje = f"🤔 No encontré información específica sobre:\n"
        mensaje += f"*\"{pregunta}\"*\n\n"
        mensaje += f"para *{postgrado_nombre}*.\n\n"
        
        preg_lower = pregunta.lower()
        
        # Categorización inteligente
        if any(w in preg_lower for w in ['parquea', 'estaciona', 'cafeteria', 'wifi']):
            mensaje += ("🏢 *Instalaciones y servicios*\n"
                         "Esta información requiere asesoría personalizada.\n"
                         "Escribe 'contactar asesor'\n\n")
        
        elif any(w in preg_lower for w in ['convenio', 'intercambio', 'movilidad']):
            mensaje += "🌍 *Convenios y movilidad*\n"
            mensaje += "Escribe 'contactar asesor' para detalles actualizados.\n\n"
        
        else:
            mensaje += ("💡 *Temas disponibles*:\n"
                     "💰 Costos • 📋 Requisitos • 📅 Fechas\n"
                     "⏱️ Duración • 💻 Modalidad • 🔗 Inscripción\n\n")
        
        mensaje += "O escribe 'contactar asesor' para ayuda personalizada."
        
        dispatcher.utter_message(text=mensaje)
    
    def _enviar_mensaje_error_api(self, dispatcher: CollectingDispatcher):
        """Mensaje de error técnico"""
        dispatcher.utter_message(text=(
            "Hubo un problema técnico al consultar esa información. 😔\n\n"
            "Por favor:\n"
            "• Intenta con otra pregunta\n"
            "• Escribe 'contactar asesor'\n"
            "• O 'menú principal' para volver al inicio"
        ))

# ============================================
# ACTION: Reiniciar Slots
# ============================================

class ActionReiniciarSlots(Action):
    """Limpia todos los slots para volver al menú principal"""

    def name(self) -> Text:
        return "action_reiniciar_slots"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("🧹 Ejecutando action_reiniciar_slots")
        
        return [
            SlotSet("postgrado_id", None),
            SlotSet("postgrado_nombre", None),
            SlotSet("ultima_lista_postgrados", None),
            SlotSet("ultima_respuesta", None),
            SlotSet("contador_fallback", 0),
            SlotSet("nombre_completo", None),
            SlotSet("email", None),
            SlotSet("telefono", None)
        ]


# ============================================
# ACTION: Confirmar Cambio de Postgrado
# ============================================

class ActionConfirmarCambioPostgrado(Action):
    """Confirma cuando el usuario quiere cambiar de postgrado seleccionado"""

    def name(self) -> Text:
        return "action_confirmar_cambio_postgrado"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("🔄 Ejecutando action_confirmar_cambio_postgrado")
        
        postgrado_anterior = tracker.get_slot("postgrado_nombre")
        
        if postgrado_anterior:
            mensaje = f"📝 Entendido, cambiaremos de *{postgrado_anterior}* a otro programa.\n\n"
            dispatcher.utter_message(text=mensaje)
        
        return [
            SlotSet("postgrado_id", None),
            SlotSet("postgrado_nombre", None)
        ]


# ============================================
# ACTION: Validar Email
# ============================================

class ActionValidarEmail(Action):
    """Valida el formato del email durante el formulario"""

    def name(self) -> Text:
        return "action_validar_email"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("📧 Ejecutando action_validar_email")
        
        email = tracker.get_slot("email")
        
        if not email:
            return []
        
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if not re.match(email_pattern, email):
            dispatcher.utter_message(
                text="❌ El formato del correo no es válido.\n\n"
                     "Ejemplo: tucorreo@gmail.com\n\n"
                     "Por favor, intenta nuevamente."
            )
            return [SlotSet("email", None)]
        
        logger.info(f"✅ Email válido: {email}")
        return []


# ============================================
# ACTION: Manejar Negación
# ============================================

class ActionManejarNegacion(Action):
    """Maneja la negación del usuario según el contexto"""

    def name(self) -> Text:
        return "action_manejar_negacion"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("❌ Ejecutando action_manejar_negacion")
        
        postgrado_id = tracker.get_slot("postgrado_id")
        ultima_lista = tracker.get_slot("ultima_lista_postgrados")
        
        # ✅ UN SOLO MENSAJE según contexto
        if ultima_lista:
            mensaje = "Entendido. ¿Quieres buscar otro programa o necesitas ayuda?\n\n"
            mensaje += "Escribe el nombre del programa o 'ver programas' para la lista completa."
            dispatcher.utter_message(text=mensaje)
            return [SlotSet("ultima_lista_postgrados", None)]
        
        elif postgrado_id:
            mensaje = "¿Prefieres ver otro programa?\n\n"
            mensaje += "Escribe 'ver programas' o el nombre del programa que te interesa."
            dispatcher.utter_message(text=mensaje)
            return []
        
        else:
            mensaje = "Está bien. ¿En qué puedo ayudarte?\n\n"
            mensaje += "Puedo mostrarte los programas disponibles o responder tus preguntas."
            dispatcher.utter_message(text=mensaje)
            return []


# ============================================
# ACTION: Manejar Afirmación
# ============================================

class ActionManejarAfirmacion(Action):
    """Maneja la afirmación del usuario según el contexto"""

    def name(self) -> Text:
        return "action_manejar_afirmacion"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("✅ Ejecutando action_manejar_afirmacion")
        
        # Obtener el último bot event para entender el contexto
        eventos = list(tracker.events)
        ultimo_bot_message = None
        
        for evento in reversed(eventos):
            if evento.get("event") == "bot" and evento.get("text"):
                ultimo_bot_message = evento.get("text", "").lower()
                break
        
        # ✅ UN SOLO MENSAJE según contexto
        if ultimo_bot_message and ("asesor" in ultimo_bot_message or "contactar" in ultimo_bot_message):
            dispatcher.utter_message(
                text="Perfecto, voy a registrar tu solicitud de contacto. 📞"
            )
            return [FollowupAction("datos_contacto_form")]
        
        elif ultimo_bot_message and ("ayud" in ultimo_bot_message or "útil" in ultimo_bot_message):
            dispatcher.utter_message(
                text="¡Me alegra haberte ayudado! 😊\n\n¿Hay algo más que quieras saber?"
            )
            return []
        
        else:
            dispatcher.utter_message(
                text="Perfecto. ¿En qué más puedo ayudarte?"
            )
            return []


# ============================================
# ACTION: Escalar a Humano
# ============================================

class ActionEscalarAHumano(Action):
    """Ofrece contacto humano después de múltiples fallbacks"""

    def name(self) -> Text:
        return "action_escalar_a_humano"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("👤 Ejecutando action_escalar_a_humano")
        
        mensaje = ("😔 Disculpa, parece que no estoy pudiendo ayudarte correctamente.\n\n"
                     "🤝 *¿Te gustaría hablar con un asesor humano?*\n\n"
                     "Un especialista puede resolver tus dudas de manera personalizada.\n\n"
                     "📞 Escribe 'contactar asesor' o 'sí' para que te llamemos.")
        
        dispatcher.utter_message(text=mensaje)
        
        return [SlotSet("contador_fallback", 0)]


# ============================================
# ACTION: Limpiar Slots Antiguos
# ============================================

class ActionLimpiarSlotsAntiguos(Action):
    """Limpia slots que ya no son necesarios para mantener conversación fluida"""

    def name(self) -> Text:
        return "action_limpiar_slots_antiguos"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("🧹 Ejecutando action_limpiar_slots_antiguos")
        
        # Limpiar solo slots temporales, mantener postgrado seleccionado
        return [
            SlotSet("ultima_lista_postgrados", None),
            SlotSet("ultima_respuesta", None),
            SlotSet("contador_fallback", 0)
        ]


# ============================================
# ACTION: Log Unknown Intent
# ============================================

class ActionLogUnknownIntent(Action):
    """Registra intents desconocidos para análisis"""

    def name(self) -> Text:
        return "action_log_unknown_intent"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("❓ Ejecutando action_log_unknown_intent")
        
        mensaje_usuario = tracker.latest_message.get("text", "")
        intent = tracker.latest_message.get("intent", {}).get("name", "unknown")
        confidence = tracker.latest_message.get("intent", {}).get("confidence", 0)
        
        logger.warning(f"🔍 Intent desconocido detectado:")
        logger.warning(f"   Mensaje: '{mensaje_usuario}'")
        logger.warning(f"   Intent: {intent}")
        logger.warning(f"   Confidence: {confidence:.2f}")
        
        return []


# ============================================
# ACTION: Solicitar Programa 
# ============================================

class ActionSolicitarPrograma(Action):

    def name(self) -> Text:
        return "action_solicitar_programa"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("📋 Ejecutando action_solicitar_programa")
        
        # Obtener lista de postgrados
        cache_key = "postgrados_list"
        postgrados = get_from_cache(cache_key)
        
        if not postgrados:
            response = make_api_request("GET", "postgrados")
            if response and response.get("status") == "success":
                postgrados = response.get("data", [])
                set_in_cache(cache_key, postgrados)
        
        if not postgrados:
            dispatcher.utter_message(
                text="Lo siento, no pude obtener la lista de programas en este momento. Por favor, intenta más tarde."
            )
            return []
        
        # ✅ CONSTRUIR MENSAJE CONSOLIDADO (solicitud + lista)
        MAX_PROGRAMAS = 20
        
        mensaje = "📚 Para darte esa información, primero necesito saber qué programa te interesa.\n\n"
        mensaje += "*Programas Disponibles:*\n\n"
        
        for i, pg in enumerate(postgrados[:MAX_PROGRAMAS], 1):
            nombre = pg.get('NOMBRE', pg.get('nombre', 'Sin nombre'))
            facultad = pg.get('FACULTAD', pg.get('facultad', 'No especificada'))
            
            mensaje += f"{i}. *{nombre}*\n"
            mensaje += f"   🏛️ Facultad: {facultad}\n\n"
        
        if len(postgrados) > MAX_PROGRAMAS:
            mensaje += f"... y {len(postgrados) - MAX_PROGRAMAS} programas más.\n\n"
        
        mensaje += "💡 *Escribe el número* o el *nombre del programa* que te interesa."
        
        dispatcher.utter_message(text=mensaje)
        
        return [SlotSet("ultima_lista_postgrados", postgrados)]