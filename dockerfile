FROM python:3.10-slim

# Variables de entorno para optimizar memoria
ENV PYTHONUNBUFFERED=1 \
    RASA_HOME=/app \
    PORT=5005 \
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
EXPOSE $PORT

# Script optimizado para usar menos memoria
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "🚀 Iniciando servicios (modo optimizado)..."\n\
echo "📍 Puerto Rasa Server: ${PORT}"\n\
echo "📍 Puerto Action Server: 5055"\n\
\n\
# Verificar modelo\n\
if [ ! -f "models/model.tar.gz" ]; then\n\
    echo "❌ Modelo no encontrado. Entrenando..."\n\
    rasa train --fixed-model-name model\n\
fi\n\
\n\
# Iniciar Action Server en background\n\
echo "🔧 Iniciando Action Server..."\n\
rasa run actions --port 5055 &\n\
ACTION_PID=$!\n\
\n\
# Esperar Action Server\n\
echo "⏳ Esperando Action Server..."\n\
for i in {1..20}; do\n\
    if nc -z localhost 5055 2>/dev/null; then\n\
        echo "✅ Action Server listo"\n\
        break\n\
    fi\n\
    [ $i -eq 20 ] && echo "❌ Timeout Action Server" && exit 1\n\
    sleep 1\n\
done\n\
\n\
# Iniciar Rasa Server (sin debug para ahorrar memoria)\n\
echo "🤖 Iniciando Rasa Server en puerto ${PORT}..."\n\
exec rasa run \\\n\
    --enable-api \\\n\
    --cors "*" \\\n\
    --port "${PORT}" \\\n\
    --credentials credentials.yml \\\n\
    --log-level WARNING\n' > /app/start.sh

RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]