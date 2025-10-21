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
    """
    ✅ VERSIÓN OPTIMIZADA - Realiza petición HTTP a la API de Apex
    
    Args:
        method: GET o POST
        endpoint: endpoint relativo (ej: 'postgrados' o 'faq/buscar/7')
        data: datos para POST
        params: parámetros query para GET (ej: {'pregunta': 'valor'})
    
    Returns:
        Respuesta JSON o None si hay error
    """
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
        
        mensaje = "¡Bienvenido! 🎓\n\n"
        mensaje += "Soy tu asistente virtual de Postgrados de la Universidad.\n\n"
        mensaje += "📚 *¿Qué programa te interesa?*\n\n"
        mensaje += "Puedes:\n"
        mensaje += "• Escribir el nombre del programa (ej: 'avalúos', 'bioingeniería')\n"
        mensaje += "• Ver todos los programas escribiendo 'ver programas'\n"
        
        dispatcher.utter_message(text=mensaje)
        
        return []


# ============================================
# ACTION: Listar Postgrados - OPTIMIZADA
# ============================================

class ActionListarPostgrados(Action):
    """Lista todos los programas de postgrado disponibles"""

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
            # Mostrar entre 10 y 13 programas 
            MAX_PROGRAMAS_MOSTRAR = 20
            
            mensaje = "📚 *Programas de Postgrado Disponibles:*\n\n"
            
            for i, pg in enumerate(postgrados[:MAX_PROGRAMAS_MOSTRAR], 1):
                nombre = pg.get('NOMBRE', pg.get('nombre', 'Sin nombre'))
                facultad = pg.get('FACULTAD', pg.get('facultad', 'No especificada'))
                
                mensaje += f"{i}. *{nombre}*\n"
                mensaje += f"   🏛️ Facultad: {facultad}\n\n"
            
            if len(postgrados) > MAX_PROGRAMAS_MOSTRAR:
                mensaje += f"... y {len(postgrados) - MAX_PROGRAMAS_MOSTRAR} programas más.\n\n"
            
            mensaje += "💡 *Escribe el número* o el *nombre del programa* que te interesa."
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
        
        # ✅ DETECCIÓN DE NÚMERO MEJORADA
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
        
        # ✅ BÚSQUEDA POR NOMBRE (mejorada con normalización)
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
            mensaje = f"❌ No encontré el programa '{postgrado_nombre}'.\n\n"
            mensaje += "💡 *Sugerencias:*\n"
            mensaje += "• Verifica la escritura\n"
            mensaje += "• Usa palabras clave (ej: 'avalúos', 'bioingeniería')\n"
            mensaje += "• Escribe 'ver programas' para la lista completa"
            
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
        
        mensaje = f"✅ Perfecto, hablemos sobre *{nombre}* de la Facultad de {facultad}.\n\n"
        mensaje += "¿Qué quieres saber? Puedes preguntar sobre:\n"
        mensaje += "💰 Costos y becas\n"
        mensaje += "📋 Requisitos de admisión\n"
        mensaje += "📅 Fechas de inscripción\n"
        mensaje += "⏱️ Duración del programa\n"
        mensaje += "💻 Modalidad (presencial/virtual)\n"
        mensaje += "📞 Solicitar contacto con un asesor\n"
        mensaje += "🏠 Retornar al menú principal\n"
        
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
        
        mensaje = f"✅ Perfecto, hablemos sobre *{nombre}* de la Facultad de {facultad}.\n\n"
        mensaje += "¿Qué quieres saber? Puedes preguntar sobre:\n"
        mensaje += "💰 Costos y becas\n"
        mensaje += "📋 Requisitos de admisión\n"
        mensaje += "📅 Fechas de inscripción\n"
        mensaje += "⏱️ Duración del programa\n"
        mensaje += "💻 Modalidad (presencial/virtual)\n"
        mensaje += "📞 O solicitar contacto con un asesor\n"
        mensaje += "🏠 Retornar al menú principal\n"
        
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
    """Busca una respuesta en la base de datos de FAQs con mapeo inteligente de intents"""

    def name(self) -> Text:
        return "action_buscar_faq"
    
    # Mapeo optimizado de intents a preguntas
    INTENT_TO_QUESTION_MAP = {
        "consultar_costos": [
            "costo",
            "cuanto cuesta",
            "valor de la matricula",
            "precio del programa"
        ],
        "consultar_requisitos": [
            "requisitos",
            "que necesito",
            "documentos necesarios",
            "requisitos de admision"
        ],
        "consultar_fechas": [
            "fechas de inscripcion",
            "cuando son las inscripciones",
            "cuando puedo inscribirme"
        ],
        "consultar_duracion": [
            "duracion",
            "cuanto dura",
            "semestres"
        ],
        "consultar_modalidad": [
            "modalidad",
            "presencial o virtual",
            "horario"
        ],
        "consultar_plan_estudios": [
            "plan de estudios",
            "materias",
            "pensum"
        ],
        "solicitar_link_inscripcion": [
            "link de inscripcion",
            "donde me inscribo",
            "enlace para inscribirme"
        ],
        "consultar_dirigido": [
            "a quien va dirigido",
            "perfil de ingreso",
            "quien puede aplicar"
        ],
        "consultar_proceso_admision": [
            "proceso de admision",
            "como me inscribo",
            "pasos para inscribirme"
        ],
        "solicitar_informacion_general": [
            "informacion general",
            "detalles del programa",
            "informacion"
        ],
        "consultar_becas": [
            "becas",
            "descuentos",
            "ayuda economica"
        ],
        "consultar_financiacion": [
            "financiacion",
            "opciones de pago",
            "cuotas",
            "como puedo pagar"
        ]
    }

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("❓ Ejecutando action_buscar_faq")
        
        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "el programa"
        
        if not postgrado_id:
            dispatcher.utter_message(
                text="Por favor, primero dime sobre qué programa necesitas información. Escribe 'ver programas' para conocer las opciones."
            )
            return [FollowupAction("action_listar_postgrados")]
        
        intent = tracker.latest_message.get("intent", {}).get("name")
        user_message = tracker.latest_message.get("text", "")
        confidence = tracker.latest_message.get("intent", {}).get("confidence", 0)
        
        logger.info(f"Intent: {intent} (conf: {confidence:.2f}) | Mensaje: '{user_message}'")
        logger.info(f"Postgrado ID: {postgrado_id} | Nombre: {postgrado_nombre}")
        
        # ✅ ESTRATEGIA DE BÚSQUEDA MÚLTIPLE
        preguntas_a_probar = []
        
        # Si el intent es reconocido con buena confianza, usar preguntas optimizadas
        if intent in self.INTENT_TO_QUESTION_MAP and confidence > 0.65:
            preguntas_a_probar.extend(self.INTENT_TO_QUESTION_MAP[intent])
            logger.info(f"✅ Usando preguntas optimizadas para intent: {intent}")
        
        # Siempre incluir el mensaje original del usuario
        preguntas_a_probar.append(user_message.lower())
        
        logger.info(f"🔍 Intentando con {len(preguntas_a_probar)} variantes de búsqueda")
        
        # Intentar con cada pregunta hasta encontrar respuesta
        for idx, pregunta in enumerate(preguntas_a_probar, 1):
            logger.info(f"Intento {idx}/{len(preguntas_a_probar)}: '{pregunta}'")
            
            # Verificar cache
            cache_key = f"faq_{postgrado_id}_{normalizar_texto(pregunta[:30])}"
            cached_response = get_from_cache(cache_key)
            
            if cached_response:
                logger.info(f"💾 Cache hit con pregunta: {pregunta}")
                dispatcher.utter_message(text=cached_response)
                self._mostrar_opciones_adicionales(dispatcher, intent)
                return [SlotSet("ultima_respuesta", cached_response)]
            
            # Llamar a la API
            response = make_api_request(
                "GET",
                f"faq/buscar/{postgrado_id}",
                params={"pregunta": pregunta}
            )
            
            if response:
                respuesta = self._extraer_respuesta(response)
                
                if respuesta and not self._es_respuesta_error(respuesta):
                    logger.info(f"✅ Respuesta encontrada con pregunta: '{pregunta}'")
                    set_in_cache(cache_key, respuesta)
                    
                    mensaje_formateado = self._formatear_respuesta(respuesta, intent, postgrado_nombre)

                    if not mensaje_formateado:
                        logger.info(f"⚠️ Respuesta formateada inválida")
                        continue  # Intentar con la siguiente pregunta

                    dispatcher.utter_message(text=mensaje_formateado)
                    self._mostrar_opciones_adicionales(dispatcher, intent)
                    
                    return [SlotSet("ultima_respuesta", respuesta)]
                else:
                    logger.info(f"⚠️ Respuesta no válida con pregunta: '{pregunta}'")
        
        # Si no se encontró respuesta después de todos los intentos
        logger.warning(f"❌ No se encontró respuesta después de {len(preguntas_a_probar)} intentos")
        
        mensaje = f"🤔 No tengo información específica sobre eso para *{postgrado_nombre}*.\n\n"
        if intent == "consultar_costos":
            mensaje += "📞 Para conocer los costos exactos, te recomiendo contactar a un asesor.\n"
            mensaje += "¿Quieres que registre tu solicitud de contacto?"
        elif intent == "consultar_fechas":
            mensaje += "📅 Las fechas pueden variar. ¿Quieres que un asesor te informe?\n"
            mensaje += "Escribe 'contactar asesor' para que te llamemos."
        else:
            mensaje += self._sugerir_alternativas(intent)
        
        dispatcher.utter_message(text=mensaje)
        return []
    
    def _extraer_respuesta(self, response: Dict) -> Optional[str]:
        """Extrae la respuesta del objeto de respuesta de la API"""
        if not response or not isinstance(response, dict):
            return None
        
        if response.get("status") == "success":
            data = response.get("data", {})
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            if isinstance(data, dict):
                return data.get("RESPUESTA", data.get("respuesta", ""))
        
        return response.get("RESPUESTA", response.get("respuesta", ""))
    
    def _es_respuesta_error(self, respuesta: str) -> bool:
        """Verifica si la respuesta es un mensaje de error"""
        if not respuesta or len(respuesta.strip()) < 10:
            return True
        
        errores = [
            "no encontré",
            "no se encontró",
            "no hay",
            "error",
            "no disponible",
            "no tengo información"
        ]
        
        respuesta_lower = respuesta.lower()
        return any(error in respuesta_lower for error in errores)
    
    def _formatear_respuesta(self, respuesta: str, intent: str, postgrado_nombre: str) -> str:
        """Formatea la respuesta con emojis según el intent"""

        if not respuesta or len(respuesta.strip()) < 10:
            return None  # Indicar que no hay respuesta válida
        
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
            "consultar_financiacion": "💳",
            "consultar_proceso_admision": "📝"
        }
        
        emoji = emoji_map.get(intent, "ℹ️")
        
        # No agregar header si la respuesta ya tiene emoji
        if respuesta.strip().startswith(tuple(emoji_map.values())):
            return respuesta
        
        return f"{emoji} *{postgrado_nombre}*\n\n{respuesta}"
    
    def _mostrar_opciones_adicionales(self, dispatcher: CollectingDispatcher, intent: str):
        """Muestra opciones adicionales basadas en el intent actual"""
        
        opciones_map = {
            "consultar_costos": "También puedes preguntar sobre:\n📋 Requisitos • 📅 Fechas • 💳 Financiación • \n🏠 O retornar al menú principal",
            "consultar_requisitos": "También puedes preguntar sobre:\n💰 Costos • 📅 Fechas • 🔗 Link de inscripción • \n🏠 O retornar al menú principal",
            "consultar_fechas": "También puedes preguntar sobre:\n💰 Costos • 📋 Requisitos • 🔗 Link de inscripción • \n🏠 O retornar al menú principal",
            "solicitar_link_inscripcion": "También puedes preguntar sobre:\n💰 Costos • 📋 Requisitos • 📅 Fechas • \n🏠 O retornar al menú principal",
            "consultar_financiacion": "También puedes preguntar sobre:\n💰 Costos • 📋 Requisitos • 🎓 Becas • \n🏠 O retornar al menú principal",
            "consultar_plan_estudios": "También puedes preguntar sobre:\n⏱️ Duración • 💻 Modalidad • 💰 Costos • \n🏠 O retornar al menú principal"
        }
        
        if intent in opciones_map:
            dispatcher.utter_message(text=f"\n{opciones_map[intent]}")
    
    def _sugerir_alternativas(self, intent: str) -> str:
        """Sugiere preguntas alternativas basadas en el intent"""
        return "Puedo ayudarte con:\n💰 Costos\n📋 Requisitos\n📅 Fechas\n🔗 Link de inscripción\n💳 Financiación\n🎓 Becas\n📞 O contactar a un asesor"


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
                dispatcher.utter_message(text=respuesta)
                
                mensaje_opciones = "\n📋 *¿Qué más te gustaría saber?*\n\n"
                mensaje_opciones += "💰 Costos y formas de pago\n"
                mensaje_opciones += "📋 Requisitos de admisión\n"
                mensaje_opciones += "📅 Fechas de inscripción\n"
                mensaje_opciones += "⏱️ Duración del programa\n"
                mensaje_opciones += "💻 Modalidad y horarios\n"
                mensaje_opciones += "📚 Plan de estudios\n"
                mensaje_opciones += "🔗 Link de inscripción\n"
                mensaje_opciones += "📞 Contactar un asesor"
                
                dispatcher.utter_message(text=mensaje_opciones)
                return []
        
        mensaje = f"ℹ️ *Información sobre {postgrado_nombre}*\n\n"
        mensaje += "¿Qué aspecto específico te interesa?\n\n"
        mensaje += "💰 Costos\n"
        mensaje += "📋 Requisitos\n"
        mensaje += "📅 Fechas\n"
        mensaje += "⏱️ Duración\n"
        mensaje += "💻 Modalidad\n"
        mensaje += "📚 Plan de estudios\n"
        mensaje += "🔗 Link de inscripción"
        
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
    """Registra solicitud de contacto - SOLICITA TELÉFONO AL USUARIO"""

    def name(self) -> Text:
        return "action_contactar_asesor"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        
        logger.info("📞 Ejecutando action_contactar_asesor")
        
        # ✅ OBTENER TELÉFONO DEL SLOT (debe ser llenado por un form)
        telefono_usuario = tracker.get_slot("telefono")
        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "postgrados"
        mensaje_usuario = tracker.latest_message.get("text", "")
        
        # ✅ VALIDAR QUE TENGAMOS POSTGRADO
        if not postgrado_id:
            dispatcher.utter_message(
                text="❌ Primero selecciona un programa de postgrado.\n\nEscribe 'ver programas' para explorar las opciones."
            )
            return [FollowupAction("action_listar_postgrados")]
        
        # ✅ SI NO TENEMOS TELÉFONO, ACTIVAR FORMULARIO
        if not telefono_usuario:
            dispatcher.utter_message(
                text="📱 Para que un asesor te contacte, necesito tu número de teléfono.\n\n"
                     "Por favor, escribe tu número (con código de país si es internacional).\n"
                     "Ejemplo: +573001234567"
            )
            # Activar el form para recopilar datos
            return [FollowupAction("datos_contacto_form")]
        
        # ✅ VALIDAR FORMATO DE TELÉFONO ANTES DE ENVIAR
        import re
        telefono_limpio = re.sub(r'[^\d+]', '', telefono_usuario)
        
        if not re.match(r'^\+?[0-9]{10,15}$', telefono_limpio):
            dispatcher.utter_message(
                text=f"❌ El teléfono '{telefono_usuario}' no tiene un formato válido.\n\n"
                     "Debe contener entre 10 y 15 dígitos.\n"
                     "Ejemplo: +573001234567 o 3001234567"
            )
            return [SlotSet("telefono", None)]
        
        # ✅ PREPARAR DATA PARA LA API
        data = {
            "telefono": telefono_limpio,
            "postgrado_id": int(postgrado_id),  # Ya validado que existe
            "mensaje": mensaje_usuario or f"Solicitud de contacto desde chatbot para {postgrado_nombre}"
        }
        
        logger.info(f"📤 Enviando a API: {data}")
        
        # ✅ LLAMAR A LA API
        response = make_api_request("POST", "contacto", data=data)
        
        # ✅ MANEJAR RESPUESTA
        if response and response.get("status") == "success":
            mensaje = f"✅ *¡Perfecto!* Tu solicitud ha sido registrada.\n\n"
            mensaje += f"📞 Un asesor especializado en *{postgrado_nombre}* "
            mensaje += f"te contactará pronto al número *{telefono_limpio}*.\n\n"
            
            # Mostrar correo de contacto si viene en la respuesta
            if response.get("correo_contacto"):
                mensaje += f"📧 También puedes escribir a: {response.get('correo_contacto')}\n\n"
            
            mensaje += "💡 ¿Hay algo más en lo que pueda ayudarte?"
            
            dispatcher.utter_message(text=mensaje)
            
            return [SlotSet("ultima_respuesta", mensaje)]
        
        # ✅ MANEJO DE ERRORES ESPECÍFICOS
        elif response and response.get("status") == "error":
            error_msg = response.get("message", "Error desconocido")
            logger.error(f"❌ Error del servidor: {error_msg}")
            
            if "teléfono" in error_msg.lower():
                dispatcher.utter_message(
                    text=f"❌ Hubo un problema con el número de teléfono:\n\n{error_msg}\n\n"
                         "Por favor, verifica el formato e intenta nuevamente."
                )
                return [SlotSet("telefono", None)]
            
            elif "postgrado" in error_msg.lower():
                dispatcher.utter_message(
                    text=f"❌ {error_msg}\n\nPor favor, selecciona un programa válido."
                )
                return [
                    SlotSet("postgrado_id", None),
                    FollowupAction("action_listar_postgrados")
                ]
            
            else:
                dispatcher.utter_message(
                    text=f"❌ Error al procesar tu solicitud:\n\n{error_msg}\n\n"
                         "Por favor, intenta nuevamente más tarde."
                )
        
        else:
            # Error de conexión o timeout
            dispatcher.utter_message(
                text="❌ No pude conectar con el servidor en este momento.\n\n"
                     "Por favor, intenta nuevamente o escribe directamente a:\n"
                     "📧 postgrados@udistrital.edu.co\n"
                     "📱 WhatsApp: +57 300 123 4567"
            )
        
        return []


# ============================================
# ACTION: Default Fallback
# ============================================

class ActionDefaultFallback(Action):
    """Acción por defecto cuando no se entiende la intención"""

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
        contador += 1
        
        if contador >= 3:
            mensaje = "😕 Parece que no puedo ayudarte de manera satisfactoria.\n\n"
            mensaje += "¿Te gustaría que un asesor te contacte?"
            dispatcher.utter_message(text=mensaje)
            # ✅ CRÍTICO: Resetear contador y revertir utterance
            return [
                SlotSet("contador_fallback", 0),
                UserUtteranceReverted()  # 🔥 ESTO FALTABA
            ]
        else:
            mensaje = "🤔 No estoy seguro de haber entendido.\n\n"
            
            if not postgrado_id:
                mensaje += "Puedo:\n"
                mensaje += "📚 Mostrarte los programas disponibles\n"
                mensaje += "🔍 Buscar un programa específico\n"
                mensaje += "💬 Responder sobre costos, fechas, requisitos, etc.\n\n"
                mensaje += "¿Qué te gustaría hacer?"
            else:
                mensaje += "Puedes preguntarme sobre:\n"
                mensaje += "💰 Costos y formas de pago\n"
                mensaje += "📋 Requisitos de admisión\n"
                mensaje += "📅 Fechas de inscripción\n"
                mensaje += "💳 Opciones de financiación\n"
                mensaje += "📞 Contacto con un asesor\n"
                mensaje += "🏠 Retornar al menú principal\n"
            
            dispatcher.utter_message(text=mensaje)
            # ✅ CRÍTICO: Siempre revertir la utterance para evitar bucles
            return [
                SlotSet("contador_fallback", contador),
                UserUtteranceReverted()  
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
        
        mensaje = "🔄 *Conversación reiniciada*\n\n"
        mensaje += "¡Hola! Soy tu asistente virtual de Postgrados. 👋\n\n"
        mensaje += "📚 *¿Qué programa te interesa?*\n\n"
        mensaje += "Escribe el nombre del programa o 'ver programas' para ver todas las opciones."
        
        dispatcher.utter_message(text=mensaje)
        
        return [AllSlotsReset()]


# ============================================
# ACTION: Despedida
# ============================================

class ActionDespedida(Action):
    """Maneja la despedida del usuario y cierra la conversación"""

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
        
        mensaje = "👋 ¡Hasta pronto!\n\n"
        
        if postgrado_nombre:
            mensaje += f"Espero haber resuelto tus dudas sobre *{postgrado_nombre}*.\n\n"
        
        mensaje += "¡Mucho éxito en tu formación académica! 🎓\n\n"
        mensaje += "Si necesitas más información, no dudes en volver a consultarnos."
        
        # ✅ Enviar mensaje con metadata para cerrar el chat desde frontend
        dispatcher.utter_message(
            text=mensaje,
            metadata={
                "conversationPaused": True,
                "closeChat": True,
                "autoClose": 4  # Cerrar después de 4 segundos
            }
        )
        
        # ✅ Eventos para finalizar la conversación
        return [
            FollowupAction("action_guardar_historial"),  # Guardar antes de cerrar
            AllSlotsReset(),      # Limpia todos los slots
            Restarted(),          # Reinicia la conversación
            ConversationPaused()  # Pausa la conversación
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
    """Envía los datos de contacto completos a la base de datos"""

    def name(self) -> Text:
        return "action_enviar_datos_contacto"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any],) -> List[Dict[Text, Any]]:
        
        logger.info("📧 Ejecutando action_enviar_datos_contacto")
        
        nombre = tracker.get_slot("nombre_completo")
        email = tracker.get_slot("email")
        telefono = tracker.get_slot("telefono")
        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "postgrado"
        
        # ✅ CONSTRUIR MENSAJE CON TODOS LOS DATOS
        mensaje = f"Solicitud de contacto - Nombre: {nombre} - Email: {email} - Programa: {postgrado_nombre}"
        
        # ✅ DATA QUE TU API SÍ ACEPTA
        data = {
            "telefono": telefono,
            "postgrado_id": int(postgrado_id) if postgrado_id else None,
            "mensaje": mensaje
        }
        
        logger.info(f"🌐 API Request: POST https://oracleapex.com/ords/udchatbot/chatbot/contacto")
        logger.info(f"📋 Data: {data}")
        
        response = make_api_request("POST", "contacto", data=data)
        
        if response and response.get("status") == "success":
            mensaje_respuesta = f"✅ *¡Perfecto {nombre}!* Tus datos han sido registrados.\n\n"
            mensaje_respuesta += f"📧 Te enviaremos información a: {email}\n"
            mensaje_respuesta += f"📱 Y te contactaremos al: {telefono}\n\n"
            mensaje_respuesta += "Un asesor se comunicará contigo en las próximas 24 horas.\n\n"
            mensaje_respuesta += "¿Hay algo más en lo que pueda ayudarte?"
            dispatcher.utter_message(text=mensaje_respuesta)
        else:
            error_msg = response.get("message", "Error desconocido") if response else "Sin conexión"
            logger.error(f"❌ Error del servidor APEX: {error_msg}")
            dispatcher.utter_message(
                text="❌ Hubo un problema al registrar tus datos. Por favor, intenta nuevamente."
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
        
        # Formatear respuesta según el intent
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
            # Información general
            mensaje = f"📚 *{nombre}*\n\n"
            mensaje += f"🏛️ Facultad: {facultad}\n\n"
            if descripcion:
                mensaje += f"📝 {descripcion}\n\n"
            if correo:
                mensaje += f"📧 Contacto: {correo}\n\n"
            mensaje += "¿Qué información específica necesitas?\n"
            mensaje += "💰 Costos\n"
            mensaje += "📅 Fechas\n"
            mensaje += "📋 Requisitos\n"
            mensaje += "⏱️ Duración\n"
            mensaje += "💻 Modalidad"
        
        dispatcher.utter_message(text=mensaje)
        
        return []

# ============================================
# ACTION: Buscar preguntas distintas 
# ============================================

class ActionBuscarFaqLibre(Action):
    """
    Busca FAQs de forma libre usando la pregunta completa del usuario.
    Se ejecuta cuando el intent no es específico pero hay postgrado seleccionado.
    """

    def name(self) -> Text:
        return "action_buscar_faq_libre"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # Obtener datos del postgrado seleccionado
        postgrado_id = tracker.get_slot("postgrado_id")
        postgrado_nombre = tracker.get_slot("postgrado_nombre") or "este programa"
        
        # Obtener pregunta completa del usuario
        user_message = tracker.latest_message.get('text', '').strip()
        
        logger.info(f"🔍 Búsqueda libre FAQ")
        logger.info(f"   Postgrado ID: {postgrado_id}")
        logger.info(f"   Postgrado: {postgrado_nombre}")
        logger.info(f"   Pregunta: '{user_message}'")
        
        # Validar que haya postgrado (aunque la regla ya lo garantiza)
        if not postgrado_id:
            logger.warning("⚠️ No hay postgrado seleccionado")
            dispatcher.utter_message(text=(
                "Necesito saber sobre qué programa preguntas. 🤔\n\n"
                "Escribe 'menú principal' para ver los programas disponibles."
            ))
            return []
        
        # Validar longitud de pregunta
        if len(user_message) < 3:
            dispatcher.utter_message(text=(
                "Tu pregunta es muy corta. ¿Podrías ser más específico? 😅"
            ))
            return []
        
        try:
            # Construir URL de la API
            api_url = f"https://oracleapex.com/ords/udchatbot/chatbot/faq/buscar/{postgrado_id}"
            params = {"pregunta": user_message}
            
            logger.info(f"🌐 API Request: GET {api_url}")
            logger.info(f"📋 Params: {params}")
            
            # Llamar a la API
            response = requests.get(api_url, params=params, timeout=10)
            
            logger.info(f"📥 Response Status: {response.status_code}")
            logger.info(f"📦 Content-Type: {response.headers.get('Content-Type')}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Verificar estructura de respuesta
                if not data or 'respuesta' not in data:
                    logger.error(f"❌ Respuesta sin campo 'respuesta': {data}")
                    self._enviar_mensaje_error_estructura(dispatcher, postgrado_nombre)
                    return []
                
                respuesta = data.get('respuesta', '').strip()
                
                # Verificar si es mensaje de "no encontrado" de APEX
                if self._es_mensaje_no_encontrado(respuesta):
                    logger.warning(f"⚠️ APEX no encontró respuesta para: '{user_message}'")
                    self._enviar_sugerencias(dispatcher, postgrado_nombre)
                    return []
                
                # Respuesta exitosa encontrada
                logger.info(f"✅ Respuesta encontrada")
                logger.info(f"   ID FAQ: {data.get('id_faq', 'N/A')}")
                logger.info(f"   Prioridad: {data.get('prioridad', 'N/A')}")
                
                # Formatear y enviar respuesta
                mensaje = self._formatear_respuesta(respuesta, postgrado_nombre)
                dispatcher.utter_message(text=mensaje)
                
            elif response.status_code == 404:
                logger.warning(f"⚠️ Endpoint no encontrado: {api_url}")
                self._enviar_mensaje_error_api(dispatcher)
            
            else:
                logger.error(f"❌ Error HTTP {response.status_code}")
                logger.error(f"   Body: {response.text[:200]}")
                self._enviar_mensaje_error_api(dispatcher)
        
        except requests.exceptions.Timeout:
            logger.error("⏱️ Timeout en consulta a API")
            dispatcher.utter_message(text=(
                "La consulta está tardando más de lo normal. ⏱️\n\n"
                "Por favor, intenta nuevamente."
            ))
        
        except requests.exceptions.ConnectionError:
            logger.error("🔌 Error de conexión con API")
            dispatcher.utter_message(text=(
                "No pude conectarme con el servidor. 🔌\n\n"
                "Por favor, verifica tu conexión e intenta nuevamente."
            ))
        
        except Exception as e:
            logger.error(f"❌ Error inesperado: {type(e).__name__}: {str(e)}")
            self._enviar_mensaje_error_api(dispatcher)
        
        return []
    
    def _es_mensaje_no_encontrado(self, respuesta: str) -> bool:
        """Detecta si la respuesta de APEX indica que no encontró información."""
        respuesta_lower = respuesta.lower()
        palabras_clave = [
            'no encontré',
            'no encontre',
            'error al procesar',
            'error:',
            'intenta reformular',
            'intenta nuevamente'
        ]
        return any(palabra in respuesta_lower for palabra in palabras_clave)
    
    def _formatear_respuesta(self, respuesta: str, postgrado_nombre: str) -> str:
        """Formatea la respuesta de APEX para mostrarla al usuario."""
        mensaje = f"💡 *{postgrado_nombre}*\n\n{respuesta}"
        
        # Agregar sugerencias de seguimiento
        mensaje += "\n\n"
        mensaje += "También puedes preguntar sobre:\n"
        mensaje += "💰 Costos • 📋 Requisitos • 📅 Fechas • 💳 Financiación\n"
        mensaje += "📞 O solicitar contacto con un asesor"
        
        return mensaje
    
    def _enviar_sugerencias(self, dispatcher: CollectingDispatcher, postgrado_nombre: str):
        """Envía mensaje cuando APEX no encuentra información."""
        mensaje = (
            f"🤔 No encontré información específica sobre eso en *{postgrado_nombre}*.\n\n"
            "Puedes preguntarme sobre:\n"
            "💰 **Costos** - Valor de matrícula y créditos\n"
            "📋 **Requisitos** - Documentos y perfil de ingreso\n"
            "📅 **Fechas** - Inscripciones e inicio de clases\n"
            "⏱️ **Duración** - Tiempo y modalidad del programa\n"
            "💳 **Financiación** - Opciones de pago y becas\n"
            "📞 **Asesor** - Contacto personalizado\n\n"
            "O escribe 'menú principal' para ver otros programas."
        )
        dispatcher.utter_message(text=mensaje)
    
    def _enviar_mensaje_error_api(self, dispatcher: CollectingDispatcher):
        """Envía mensaje de error genérico de API."""
        dispatcher.utter_message(text=(
            "Hubo un problema al consultar esa información. 😔\n\n"
            "Por favor, intenta con otra pregunta o contacta a un asesor."
        ))
    
    def _enviar_mensaje_error_estructura(self, dispatcher: CollectingDispatcher, postgrado_nombre: str):
        """Envía mensaje cuando la respuesta de API tiene estructura incorrecta."""
        dispatcher.utter_message(text=(
            f"Hubo un problema al procesar la información de *{postgrado_nombre}*. 😕\n\n"
            "Por favor, intenta con otra pregunta o contacta a un asesor."
        ))

# ============================================
# AGREGAR AL FINAL DE TU actions.py (después de ActionBuscarFaqLibre)
# ============================================

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
        
        # Si hay lista activa, el usuario rechaza la lista
        if ultima_lista:
            mensaje = "Entendido. ¿Quieres buscar otro programa o necesitas ayuda?\n\n"
            mensaje += "Escribe el nombre del programa o 'ver programas' para la lista completa."
            dispatcher.utter_message(text=mensaje)
            return [SlotSet("ultima_lista_postgrados", None)]
        
        # Si hay postgrado seleccionado, ofrecer cambiar
        elif postgrado_id:
            mensaje = "¿Prefieres ver otro programa?\n\n"
            mensaje += "Escribe 'ver programas' o el nombre del programa que te interesa."
            dispatcher.utter_message(text=mensaje)
            return []
        
        # Sin contexto claro
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
        
        # Contexto: Oferta de contacto con asesor
        if ultimo_bot_message and ("asesor" in ultimo_bot_message or "contactar" in ultimo_bot_message):
            dispatcher.utter_message(
                text="Perfecto, voy a registrar tu solicitud de contacto. 📞"
            )
            return [FollowupAction("datos_contacto_form")]
        
        # Contexto: Pregunta si ayudó la información
        elif ultimo_bot_message and ("ayud" in ultimo_bot_message or "útil" in ultimo_bot_message):
            dispatcher.utter_message(
                text="¡Me alegra haberte ayudado! 😊\n\n¿Hay algo más que quieras saber?"
            )
            return []
        
        # Sin contexto específico
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
        
        mensaje = "😔 Disculpa, parece que no estoy pudiendo ayudarte correctamente.\n\n"
        mensaje += "🤝 *¿Te gustaría hablar con un asesor humano?*\n\n"
        mensaje += "Un especialista puede resolver tus dudas de manera personalizada.\n\n"
        mensaje += "📞 Escribe 'contactar asesor' o 'sí' para que te llamemos."
        
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
        
        # Aquí podrías enviar a una API de logging si tienes una
        # Por ahora solo logueamos localmente
        
        return []