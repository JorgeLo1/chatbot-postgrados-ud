#!/bin/bash
set -e

echo "╔════════════════════════════════════════╗"
echo "║  🚀 Iniciando Sistema Completo        ║"
echo "╚════════════════════════════════════════╝"

# =========================================================
# Cargar variables de entorno
# =========================================================
if [ -f ".env" ]; then
    echo "✅ Cargando .env"
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ Archivo .env no encontrado"
    exit 1
fi

echo "📍 Configuración de puertos:"
echo "   Rasa Server:      ${PORT:-5005}"
echo "   Action Server:    ${ACTION_SERVER_PORT:-5055}"
echo "   WhatsApp Adapter: ${WHATSAPP_ADAPTER_PORT:-5006}"

# =========================================================
# Detener procesos previos
# =========================================================
echo ""
echo "🛑 Deteniendo servicios previos..."
pkill -f "rasa run" || true
pkill -f "rasa run actions" || true
pkill -f "whatsapp_adapter.py" || true
sleep 2

# =========================================================
# Iniciar Action Server
# =========================================================
echo "🔧 Iniciando Action Server..."
nohup rasa run actions --port ${ACTION_SERVER_PORT:-5055} > action_server.log 2>&1 &
ACTION_PID=$!
sleep 5
echo "✅ Action Server PID: $ACTION_PID"

# Esperar a que el Action Server responda
for i in {1..30}; do
    if curl -s http://127.0.0.1:${ACTION_SERVER_PORT:-5055}/health > /dev/null; then
        echo "✅ Action Server está listo"
        break
    fi
    sleep 1
    echo -n "."
done
echo ""

# =========================================================
# Iniciar Rasa Server
# =========================================================
echo "🤖 Iniciando Rasa Server..."
nohup rasa run --enable-api --port ${PORT:-5005} --cors "*" > rasa_server.log 2>&1 &
RASA_PID=$!
sleep 8
echo "✅ Rasa Server PID: $RASA_PID"

for i in {1..30}; do
    if curl -s http://127.0.0.1:${PORT:-5005}/status > /dev/null; then
        echo "✅ Rasa Server está listo"
        break
    fi
    sleep 1
    echo -n "."
done
echo ""

# =========================================================
# Iniciar WhatsApp Adapter
# =========================================================
echo "📱 Iniciando WhatsApp Adapter..."
nohup python3.10 whatsapp_adapter.py > whatsapp_adapter.log 2>&1 &
ADAPTER_PID=$!
sleep 5
echo "✅ WhatsApp Adapter PID: $ADAPTER_PID"

echo "⏳ Esperando WhatsApp Adapter..."
for i in {1..40}; do
    if curl -s http://127.0.0.1:${WHATSAPP_ADAPTER_PORT:-5006}/health > /dev/null; then
        echo "✅ WhatsApp Adapter está listo"
        break
    fi
    sleep 1
    echo -n "."
done

if ! curl -s http://127.0.0.1:${WHATSAPP_ADAPTER_PORT:-5006}/health > /dev/null; then
    echo ""
    echo "❌ Timeout: WhatsApp Adapter no responde después de 40 segundos"
    echo "🔍 Revisa el log con:"
    echo "   tail -n 50 whatsapp_adapter.log"
    echo ""
    kill $ACTION_PID $RASA_PID 2>/dev/null || true
    exit 1
fi

# =========================================================
# Finalización
# =========================================================
echo ""
echo "=================================================="
echo "✅ Todos los servicios están en ejecución:"
echo "   - Rasa Server:      PID $RASA_PID"
echo "   - Action Server:    PID $ACTION_PID"
echo "   - WhatsApp Adapter: PID $ADAPTER_PID"
echo "=================================================="
echo ""
echo "🌐 Puedes probar salud con:"
echo "   curl http://127.0.0.1:${WHATSAPP_ADAPTER_PORT:-5006}/health"
echo ""
echo "🧠 Logs:"
echo "   tail -f rasa_server.log"
echo "   tail -f action_server.log"
echo "   tail -f whatsapp_adapter.log"
echo ""

