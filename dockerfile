FROM python:3.10-slim

# Variables de entorno para optimizar memoria
ENV PYTHONUNBUFFERED=1 \
    RASA_HOME=/app \
    PYTHONOPTIMIZE=1 \
    TF_CPP_MIN_LOG_LEVEL=3 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

# Instalar dependencias del sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Crear directorio de trabajo
WORKDIR /app

# Copiar requirements e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar archivos de configuración
COPY domain.yml config.yml credentials.yml endpoints.yml ./
COPY data/ ./data/
COPY actions/ ./actions/

# Entrenar modelo DURANTE el build
RUN echo "📚 Entrenando modelo..." && \
    rasa train --fixed-model-name model && \
    echo "✅ Modelo entrenado"

# Copiar el resto de archivos
COPY . .

# Exponer puerto
EXPOSE 10000

# Crear script de inicio
COPY <<'EOF' /app/start.sh
#!/bin/bash
set -e

# Render asigna el puerto automáticamente, usa 10000 por defecto
RASA_PORT=${PORT:-10000}
ACTION_PORT=${ACTION_SERVER_PORT:-5055}

echo "🚀 Iniciando servicios (modo optimizado)..."
echo "📍 Puerto Rasa Server: ${RASA_PORT}"
echo "📍 Puerto Action Server: ${ACTION_PORT}"

# Verificar modelo
if [ ! -f "models/model.tar.gz" ]; then
    echo "❌ Modelo no encontrado. Entrenando..."
    rasa train --fixed-model-name model
fi

# Iniciar Action Server en background
echo "🔧 Iniciando Action Server..."
rasa run actions --port ${ACTION_PORT} &
ACTION_PID=$!

# Esperar Action Server
echo "⏳ Esperando Action Server..."
for i in {1..20}; do
    if nc -z localhost ${ACTION_PORT} 2>/dev/null; then
        echo "✅ Action Server listo"
        break
    fi
    [ $i -eq 20 ] && echo "❌ Timeout Action Server" && exit 1
    sleep 1
done

# Iniciar Rasa Server
echo "🤖 Iniciando Rasa Server en puerto ${RASA_PORT}..."
exec rasa run --enable-api --cors "*" --port "${RASA_PORT}" --credentials credentials.yml --log-level warning
EOF

RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]