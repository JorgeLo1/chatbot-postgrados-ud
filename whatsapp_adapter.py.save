#!/usr/bin/env python3
"""
WhatsApp Business API Adapter for Rasa
Recibe webhooks de WhatsApp y los envía a Rasa REST API
"""

from flask import Flask, request, jsonify
import requests
import os
import logging
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "postgrados_ud_webhook_token_2025_")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
RASA_URL = os.getenv("RASA_URL", "http://localhost:5005/webhooks/rest/webhook")
WHATSAPP_API_URL = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============================================
# WEBHOOK: Verificación GET
# ============================================
@app.route('/webhooks/whatsapp/webhook', methods=['GET'])
def verify_webhook():
    """
    Meta envía una petición GET para verificar el webhook
    """
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    logger.info(f"📥 Verificación webhook recibida: mode={mode}, token={token[:10]}...")
    
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        logger.info("✅ Webhook verificado exitosamente")
        return challenge, 200
    else:
        logger.error("❌ Verificación fallida: token incorrecto")
        return 'Forbidden', 403

# ============================================
# WEBHOOK: Recibir mensajes POST
# ============================================
@app.route('/webhooks/whatsapp/webhook', methods=['POST'])
def receive_message():
    """
    Recibe mensajes de WhatsApp y los envía a Rasa
    """
    try:
        data = request.get_json()
        logger.info(f"📱 Webhook recibido: {data}")
        
        # Verificar estructura del webhook
        if not data.get('entry'):
            logger.warning("⚠️ Webhook sin 'entry', ignorando")
            return jsonify({"status": "ok"}), 200
        
        # Extraer información del mensaje
        for entry in data['entry']:
            for change in entry.get('changes', []):
                value = change.get('value', {})
                
                # Mensajes entrantes
                if 'messages' in value:
                    for message in value['messages']:
                        process_incoming_message(message, value)
                
                # Estados de mensaje (leído, entregado, etc.)
                if 'statuses' in value:
                    logger.info(f"📊 Estado de mensaje: {value['statuses']}")
        
        return jsonify({"status": "ok"}), 200
    
    except Exception as e:
        logger.error(f"❌ Error procesando webhook: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================================
# PROCESAR MENSAJE ENTRANTE
# ============================================
def process_incoming_message(message, value):
    """
    Procesa un mensaje de WhatsApp y lo envía a Rasa
    """
    try:
        # Extraer datos
        from_number = message.get('from')
        message_type = message.get('type')
        timestamp = message.get('timestamp')
        
        logger.info(f"👤 Mensaje de {from_number} - Tipo: {message_type}")
        
        # Solo procesar mensajes de texto por ahora
        if message_type != 'text':
            logger.info(f"⚠️ Tipo de mensaje no soportado: {message_type}")
            send_whatsapp_message(
                from_number, 
                "Lo siento, solo puedo procesar mensajes de texto por ahora. 📝"
            )
            return
        
        # Obtener texto del mensaje
        text = message.get('text', {}).get('body', '')
        
        if not text:
            logger.warning("⚠️ Mensaje sin texto")
            return
        
        logger.info(f"💬 Texto recibido: '{text}'")
        
        # Enviar a Rasa
        rasa_response = send_to_rasa(from_number, text)
        
        # Enviar respuesta(s) a WhatsApp
        if rasa_response:
            for response in rasa_response:
                response_text = response.get('text', '')
                if response_text:
                    send_whatsapp_message(from_number, response_text)
        else:
            logger.error("❌ Sin respuesta de Rasa")
            send_whatsapp_message(
                from_number,
                "Disculpa, tuve un problema procesando tu mensaje. Por favor intenta nuevamente."
            )
    
    except Exception as e:
        logger.error(f"❌ Error procesando mensaje: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ============================================
# ENVIAR A RASA
# ============================================
def send_to_rasa(sender_id, message):
    """
    Envía mensaje a Rasa y obtiene respuesta
    """
    try:
        payload = {
            "sender": sender_id,
            "message": message
        }
        
        logger.info(f"🤖 Enviando a Rasa: {payload}")
        
        response = requests.post(
            RASA_URL,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            rasa_response = response.json()
            logger.info(f"✅ Respuesta de Rasa: {rasa_response}")
            return rasa_response
        else:
            logger.error(f"❌ Error de Rasa: {response.status_code} - {response.text}")
            return None
    
    except requests.exceptions.Timeout:
        logger.error("⏱️ Timeout al conectar con Rasa")
        return None
    except Exception as e:
        logger.error(f"❌ Error enviando a Rasa: {e}")
        return None

# ============================================
# ENVIAR MENSAJE A WHATSAPP
# ============================================
def send_whatsapp_message(to_number, text):
    """
    Envía mensaje a WhatsApp usando la API de Meta
    """
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
        
        logger.info(f"📤 Enviando a WhatsApp: {to_number}")
        
        response = requests.post(
            WHATSAPP_API_URL,
            headers=headers,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Mensaje enviado exitosamente")
            return True
        else:
            logger.error(f"❌ Error enviando mensaje: {response.status_code} - {response.text}")
            return False
    
    except Exception as e:
        logger.error(f"❌ Error en send_whatsapp_message: {e}")
        return False

# ============================================
# HEALTH CHECK
# ============================================
@app.route('/health', methods=['GET'])
def health():
    """Endpoint para verificar que el servicio está vivo"""
    return jsonify({
        "status": "ok",
        "service": "WhatsApp Adapter",
        "rasa_url": RASA_URL,
        "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID)
    }), 200

@app.route('/', methods=['GET'])
def root():
    """Endpoint raíz"""
    return jsonify({
        "service": "WhatsApp to Rasa Adapter",
        "status": "running",
        "endpoints": {
            "webhook": "/webhooks/whatsapp/webhook",
            "health": "/health"
        }
    }), 200

# ============================================
# INICIAR SERVIDOR
# ============================================
if __name__ == '__main__':
    port = int(os.getenv('WHATSAPP_ADAPTER_PORT', 5006))
    
    logger.info("=" * 50)
    logger.info("🚀 Iniciando WhatsApp Adapter")
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🤖 Rasa URL: {RASA_URL}")
    logger.info(f"📱 WhatsApp Phone ID: {WHATSAPP_PHONE_ID}")
    logger.info(f"🔐 Token configurado: {'✅' if WHATSAPP_TOKEN else '❌'}")
    logger.info("=" * 50)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )
