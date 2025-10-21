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

# Copiar todo el proyecto
COPY . .

# Exponer puertos (Rasa: 5005, Actions: 5055)
EXPOSE 5005 5055

# Crear script de inicio
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "🚀 Iniciando servicios..."\n\
\n\
# Entrenar modelo si no existe\n\
if [ ! -d "models" ] || [ -z "$(ls -A models 2>/dev/null)" ]; then\n\
    echo "📚 Entrenando modelo..."\n\
    rasa train --fixed-model-name model\n\
fi\n\
\n\
# Iniciar action server en background\n\
echo "🔧 Iniciando Action Server en puerto 5055..."\n\
rasa run actions --port 5055 &\n\
\n\
# Esperar a que action server esté listo\n\
echo "⏳ Esperando Action Server..."\n\
sleep 15\n\
\n\
# Iniciar Rasa server\n\
echo "🤖 Iniciando Rasa Server en puerto ${PORT}..."\n\
exec rasa run \\\n\
    --enable-api \\\n\
    --cors "*" \\\n\
    --port ${PORT} \\\n\
    --debug\n\
'