#!/bin/bash
set -e

echo "╔════════════════════════════════════════════╗"
echo "║  🚀 Iniciando Chatbot Postgrados UD       ║"
echo "╚════════════════════════════════════════════╝"

# =========================================================
# ✅ Cargar variables de entorno
# =========================================================
if [ -f ".env" ]; then
    echo "✅ Cargando .env"
    export $(grep -v '^#' .env | xargs)
else
    echo "⚠️  Archivo .env no encontrado — usando variables del sistema"
fi

RASA_PORT=${PORT:-5005}
ACTION_PORT=${ACTION_SERVER_PORT:-5055}
ADAPTER_PORT=${WHATSAPP_ADAPTER_PORT:-5006}

echo ""
echo "📍 Configuración:"
echo "   Rasa Server:      puerto ${RASA_PORT}"
echo "   Action Server:    puerto ${ACTION_PORT}"
echo "   WhatsApp Adapter: puerto ${ADAPTER_PORT}"
echo "   Entorno:          ${ENVIRONMENT:-development}"
echo ""

# =========================================================
# 📥 PASO 1: Descargar datos dinámicos desde APEX
# =========================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📥 PASO 1: Descargando FAQs desde APEX..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

mkdir -p data

if python3 fetch_training_data.py; then
    echo "✅ Datos dinámicos generados correctamente"

    # Verificar que los archivos se crearon
    if [ -f "data/nlu_dynamic.yml" ]; then
        NLU_LINES=$(wc -l < data/nlu_dynamic.yml)
        echo "   📄 nlu_dynamic.yml: ${NLU_LINES} líneas"
    fi
    if [ -f "data/stories_dynamic.yml" ]; then
        STORY_LINES=$(wc -l < data/stories_dynamic.yml)
        echo "   📄 stories_dynamic.yml: ${STORY_LINES} líneas"
    fi
else
    echo "⚠️  No se pudieron descargar datos de APEX"
    echo "   El bot entrenará solo con datos estáticos (nlu.yml, stories.yml)"
    echo "   Verifica la conexión a APEX_API_URL=${APEX_API_URL}"
fi

echo ""

# =========================================================
# 🧠 PASO 2: Entrenar modelo Rasa
# =========================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧠 PASO 2: Entrenando modelo de Rasa..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

mkdir -p models

if rasa train --fixed-model-name model; then
    echo "✅ Modelo entrenado exitosamente"
else
    echo "❌ Error al entrenar el modelo"
    # Si hay un modelo anterior, intentar usarlo
    if [ -f "models/model.tar.gz" ]; then
        echo "⚠️  Usando modelo anterior como fallback"
    else
        echo "❌ No hay modelo disponible. Abortando."
        exit 1
    fi
fi

echo ""

# =========================================================
# 🔧 PASO 3: Iniciar Action Server
# =========================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 PASO 3: Iniciando Action Server..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

rasa run actions --port ${ACTION_PORT} &
ACTION_PID=$!

echo "⏳ Esperando Action Server (puerto ${ACTION_PORT})..."
for i in {1..30}; do
    if curl -s http://localhost:${ACTION_PORT}/health > /dev/null 2>&1; then
        echo "✅ Action Server listo (PID: ${ACTION_PID})"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Timeout esperando Action Server"
        exit 1
    fi
    sleep 2
    echo -n "."
done

echo ""

# =========================================================
# 📱 PASO 4: Iniciar WhatsApp Adapter
# =========================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📱 PASO 4: Iniciando WhatsApp Adapter..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python3 whatsapp_adapter.py &
ADAPTER_PID=$!

echo "⏳ Esperando WhatsApp Adapter (puerto ${ADAPTER_PORT})..."
for i in {1..20}; do
    if curl -s http://localhost:${ADAPTER_PORT}/health > /dev/null 2>&1; then
        echo "✅ WhatsApp Adapter listo (PID: ${ADAPTER_PID})"
        break
    fi
    if [ $i -eq 20 ]; then
        echo "⚠️  WhatsApp Adapter no respondió — continuando de todas formas"
        break
    fi
    sleep 2
    echo -n "."
done

echo ""

# =========================================================
# 🤖 PASO 5: Iniciar Rasa Server (proceso principal)
# =========================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🤖 PASO 5: Iniciando Rasa Server..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Sistema completo en ejecución:"
echo "   Rasa Server:      http://localhost:${RASA_PORT}"
echo "   Action Server:    http://localhost:${ACTION_PORT}"
echo "   WhatsApp Adapter: http://localhost:${ADAPTER_PORT}"
echo ""

# exec reemplaza el proceso bash — Rasa queda como PID 1
exec rasa run \
    --enable-api \
    --cors "*" \
    --port ${RASA_PORT} \
    --endpoints endpoints.yml \
    --credentials credentials.yml