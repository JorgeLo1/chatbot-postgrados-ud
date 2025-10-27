#!/bin/bash
set -e

echo "🚀 Iniciando servicios de Rasa..."

# Puertos por defecto
RASA_PORT=${RASA_PORT:-5005}
ACTION_PORT=${ACTION_PORT:-5055}

echo "📍 Puerto Rasa Server: ${RASA_PORT}"
echo "📍 Puerto Action Server: ${ACTION_PORT}"

# Verificar que existe el modelo
if [ ! -f "models/model.tar.gz" ]; then
    echo "❌ Modelo no encontrado. Entrenando..."
    rasa train --fixed-model-name model
    echo "✅ Modelo entrenado"
fi

# Iniciar Action Server en background
echo "🔧 Iniciando Action Server..."
rasa run actions --port ${ACTION_PORT} &
ACTION_PID=$!

# Esperar a que Action Server esté listo
echo "⏳ Esperando Action Server..."
for i in {1..30}; do
    if curl -s http://localhost:${ACTION_PORT}/health > /dev/null 2>&1; then
        echo "✅ Action Server está listo"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Timeout esperando Action Server"
        exit 1
    fi
    sleep 2
done

# Iniciar Rasa Server
echo "🤖 Iniciando Rasa Server en puerto ${RASA_PORT}..."
exec rasa run \
    --enable-api \
    --cors "*" \
    --port ${RASA_PORT} \
    --log-level info \
    --endpoints endpoints.yml \
    --credentials credentials.yml