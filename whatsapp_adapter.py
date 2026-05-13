#!/usr/bin/env python3
"""WhatsApp Business API Adapter con manejo de timeout por inactividad."""

from flask import Flask, request, jsonify
import requests
import os
import json
import logging
import hmac
import hashlib
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import redis  # Para persistencia (opcional pero recomendado)

load_dotenv()

# Configuración
VERIFY_TOKEN      = os.getenv("WHATSAPP_VERIFY_TOKEN", "postgrados_ud_webhook_token_2025_")
WHATSAPP_TOKEN    = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
RASA_URL          = os.getenv("RASA_URL", "http://localhost:5005/webhooks/rest/webhook")
WHATSAPP_API_URL  = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"

# Timeout configuration
WARNING_SECONDS = int(os.getenv("INACTIVITY_WARNING_TIME", "240"))  # 4 minutos
TIMEOUT_SECONDS = int(os.getenv("INACTIVITY_TIMEOUT",      "300"))  # 5 minutos
CHECK_INTERVAL  = 30  # Revisar cada 30 segundos (más preciso)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# PERSISTENCIA DE SESIONES
class SessionStore:
    """Almacenamiento de sesiones con respaldo en Redis (si está disponible)"""
    
    def __init__(self):
        self.sessions = {}  # Fallback en memoria
        self.use_redis = False
        
        # Intentar conectar a Redis (opcional pero recomendado)
        try:
            self.redis = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                password=os.getenv("REDIS_PASSWORD", None),
                decode_responses=True
            )
            self.redis.ping()
            self.use_redis = True
            logger.info("Redis conectado - sesiones persistentes")
        except:
            logger.warning("Redis no disponible - usando memoria (las sesiones se perderán al reiniciar)")
    
    def get(self, phone_number):
        """Obtiene sesión"""
        if self.use_redis:
            data = self.redis.get(f"session:{phone_number}")
            return json.loads(data) if data else None
        return self.sessions.get(phone_number)
    
    def set(self, phone_number, data):
        """Guarda sesión"""
        if self.use_redis:
            self.redis.setex(
                f"session:{phone_number}",
                TIMEOUT_SECONDS + 60,  # Expira después del timeout + margen
                json.dumps(data)
            )
        else:
            self.sessions[phone_number] = data
    
    def delete(self, phone_number):
        """Elimina sesión"""
        if self.use_redis:
            self.redis.delete(f"session:{phone_number}")
        else:
            self.sessions.pop(phone_number, None)
    
    def get_all(self):
        """Obtiene todas las sesiones activas"""
        if self.use_redis:
            keys = self.redis.keys("session:*")
            sessions = {}
            for key in keys:
                phone = key.replace("session:", "")
                data = self.redis.get(key)
                if data:
                    sessions[phone] = json.loads(data)
            return sessions
        return self.sessions.copy()

# Instancia global del store
session_store = SessionStore()

# GESTIÓN DE SESIONES
def registrar_actividad(phone_number: str):
    """Registra actividad del usuario"""
    ahora = datetime.now()
    session_store.set(phone_number, {
        "last_activity": ahora.isoformat(),
        "warned": False,
        "phone": phone_number
    })
    logger.info(f"Actividad registrada: {phone_number}")

def cerrar_sesion_en_rasa(phone_number: str):
    """Envía /reiniciar a Rasa para limpiar el estado"""
    try:
        requests.post(
            RASA_URL,
            json={"sender": phone_number, "message": "/reiniciar"},
            timeout=10
        )
        logger.info(f"Sesión Rasa cerrada para {phone_number}")
    except Exception as e:
        logger.error(f"Error cerrando sesión Rasa: {e}")

def verificar_inactividad():
    """Job que corre cada CHECK_INTERVAL segundos"""
    ahora = datetime.now()
    sessions = session_store.get_all()
    
    for phone_number, datos in sessions.items():
        try:
            last_activity = datetime.fromisoformat(datos["last_activity"])
            segundos_inactivo = (ahora - last_activity).total_seconds()
            warned = datos.get("warned", False)
            
            logger.debug(f"{phone_number}: {segundos_inactivo:.0f}s inactivo")
            
            # CASO 1: Timeout - cerrar sesión
            if segundos_inactivo >= TIMEOUT_SECONDS:
                logger.info(f"Timeout para {phone_number}")
                
                mensaje = (
                    f"👋 ¡Hasta pronto!\n\n"
                    f"Tu sesión se cerró por inactividad.\n\n"
                    f"Cuando quieras, escribe *hola* y seguimos. 🎓"
                )
                
                # Enviar mensaje de cierre
                send_whatsapp_message(phone_number, mensaje)
                
                # Cerrar sesión en Rasa
                cerrar_sesion_en_rasa(phone_number)
                
                # Eliminar sesión
                session_store.delete(phone_number)
            
            # CASO 2: Advertencia (solo si no se ha mostrado)
            elif segundos_inactivo >= WARNING_SECONDS and not warned:
                segundos_restantes = TIMEOUT_SECONDS - segundos_inactivo
                minutos = segundos_restantes // 60
                segundos = segundos_restantes % 60
                
                logger.info(f"Advertencia para {phone_number}")
                
                tiempo_str = f"{int(minutos)} min" if minutos >= 1 else f"{int(segundos)} seg"
                mensaje = (
                    f"¿Sigues ahí? 😊\n\n"
                    f"Si no hay actividad en {tiempo_str} cierro la sesión.\n\n"
                    f"Escribe cualquier cosa para continuar."
                )
                
                send_whatsapp_message(phone_number, mensaje)
                
                # Marcar como advertido
                datos["warned"] = True
                session_store.set(phone_number, datos)
        
        except Exception as e:
            logger.error(f"Error procesando {phone_number}: {e}")

# WEBHOOKS
@app.route('/webhooks/whatsapp/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return challenge, 200
    return 'Forbidden', 403


def _verificar_firma_hmac(body_crudo: bytes, firma_header: str) -> bool:
    """Verifica X-Hub-Signature-256 usando HMAC-SHA256 sobre el body crudo.
    Ref: https://developers.facebook.com/docs/graph-api/webhooks/getting-started#verification-requests
    """
    if not firma_header or not firma_header.startswith("sha256="):
        return False
    firma_recibida = firma_header[len("sha256="):]
    firma_calculada = hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        body_crudo,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(firma_calculada, firma_recibida)


@app.route('/webhooks/whatsapp/webhook', methods=['POST'])
def receive_message():
    # Verificar firma HMAC antes de procesar el payload
    if WHATSAPP_APP_SECRET:
        body_crudo = request.get_data()
        firma_header = request.headers.get("X-Hub-Signature-256", "")
        if not firma_header:
            logger.warning("Peticion POST sin X-Hub-Signature-256 rechazada")
            return jsonify({"error": "missing signature"}), 403
        if not _verificar_firma_hmac(body_crudo, firma_header):
            logger.warning("Firma HMAC invalida en peticion POST al webhook")
            return jsonify({"error": "invalid signature"}), 403
    else:
        logger.warning("WHATSAPP_APP_SECRET no configurado — verificacion HMAC deshabilitada")

    try:
        data = request.get_json()
        
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                
                # Procesar mensajes entrantes
                for message in value.get('messages', []):
                    if message.get('type') == 'text':
                        from_number = message['from']
                        text = message['text']['body']
                        
                        logger.info(f"De {from_number}: {text}")
                        
                        # REGISTRAR ACTIVIDAD (esto evita el timeout)
                        registrar_actividad(from_number)
                        
                        # Enviar a Rasa
                        rasa_responses = send_to_rasa(from_number, text)
                        
                        # Enviar respuestas a WhatsApp
                        for response in rasa_responses or []:
                            if response.get('text'):
                                send_whatsapp_message(from_number, response['text'])
        
        return jsonify({"status": "ok"}), 200
    
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"status": "error"}), 500

# FUNCIONES AUXILIARES
def send_to_rasa(sender_id, message):
    """Envía mensaje a Rasa"""
    try:
        response = requests.post(
            RASA_URL,
            json={"sender": sender_id, "message": message},
            timeout=30
        )
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error(f"Error enviando a Rasa: {e}")
        return None

def send_whatsapp_message(to_number, text):
    """Envía mensaje a WhatsApp usando Meta API"""
    try:
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text
            }
        }
        
        response = requests.post(
            WHATSAPP_API_URL,
            headers=headers,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"Mensaje enviado a {to_number}")
            return True
        else:
            logger.error(f"Error {response.status_code}: {response.text}")
            return False
    
    except Exception as e:
        logger.error(f"Error en send_whatsapp_message: {e}")
        return False

# HEALTH CHECK
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "WhatsApp Adapter",
        "active_sessions": len(session_store.get_all()),
        "warning_time": WARNING_SECONDS,
        "timeout": TIMEOUT_SECONDS
    })

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "service": "WhatsApp to Rasa Adapter",
        "status": "running",
        "endpoints": {
            "webhook": "/webhooks/whatsapp/webhook",
            "health": "/health"
        }
    })

# INICIO
if __name__ == '__main__':
    port = int(os.getenv('WHATSAPP_ADAPTER_PORT', 5006))
    
    logger.info("=" * 50)
    logger.info("Iniciando WhatsApp Adapter (con timeout gestionado)")
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🤖 Rasa URL: {RASA_URL}")
    logger.info(f"⏱️  Warning: {WARNING_SECONDS}s | Timeout: {TIMEOUT_SECONDS}s")
    logger.info("=" * 50)
    
    # Iniciar scheduler para verificar inactividad
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        verificar_inactividad,
        trigger="interval",
        seconds=CHECK_INTERVAL,
        id="verificar_inactividad",
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"⏰ Scheduler iniciado (revisión cada {CHECK_INTERVAL}s)")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )