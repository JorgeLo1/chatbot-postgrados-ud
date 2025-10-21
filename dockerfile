FROM python:3.10-slim

# Variables de entorno
ENV PYTHONUNBUFFERED=1 \
    RASA_HOME=/app \
    PORT=5005

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Crear directorio de trabajo
WORKDIR /app

# Copiar requirements e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar archivos de configuración primero (para mejor cache)
COPY domain.yml config.yml credentials.yml endpoints.yml ./
COPY data/ ./data/
COPY actions/ ./actions/

# Entrenar modelo DURANTE el build
RUN echo "📚 Entrenando modelo durante el build..." && \
    rasa train --fixed-model-name model && \
    echo "✅ Modelo entrenado correctamente"

# Copiar el resto de archivos del proyecto
COPY . .

# Exponer puertos (Rasa usa el puerto de la variable $PORT)
EXPOSE $PORT

# Crear script de inicio
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "🚀 Iniciando servicios..."\n\
\n\
# Verificar que el modelo existe\n\
if [ ! -f "models/model.tar.gz" ]; then\n\
    echo "❌ Error: Modelo no encontrado. Entrenando..."\n\
    rasa train --fixed-model-name model\n\
fi\n\
\n\
# Iniciar Action Server en background\n\
echo "🔧 Iniciando Action Server en puerto 5055..."\n\
rasa run actions --port 5055 &\n\
ACTION_PID=$!\n\
\n\
# Esperar a que el Action Server esté listo\n\
echo "⏳ Esperando Action Server..."\n\
for i in {1..30}; do\n\
    if nc -z localhost 5055 2>/dev/null; then\n\
        echo "✅ Action Server listo"\n\
        break\n\
    fi\n\
    if [ $i -eq 30 ]; then\n\
        echo "❌ Timeout esperando Action Server"\n\
        exit 1\n\
    fi\n\
    sleep 1\n\
done\n\
\n\
# Iniciar Rasa Server con conector REST\n\
echo "🤖 Iniciando Rasa Server en puerto ${PORT} con conector REST..."\n\
exec rasa run \\\n\
    --enable-api \\\n\
    --cors "*" \\\n\
    --port ${PORT} \\\n\
    --credentials credentials.yml\n' > /app/start.sh

# Dar permisos de ejecución al script
RUN chmod +x /app/start.sh

# Comando de inicio
CMD ["/app/start.sh"]