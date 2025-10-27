FROM python:3.10-slim

# Variables de entorno básicas
ENV PYTHONUNBUFFERED=1 \
    RASA_HOME=/app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Crear directorio de trabajo
WORKDIR /app

# Copiar e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar todos los archivos del proyecto
COPY config.yml domain.yml credentials.yml endpoints.yml ./
COPY data/ ./data/
COPY actions/ ./actions/

# Entrenar el modelo
RUN echo "📚 Entrenando modelo de Rasa..." && \
    rasa train --fixed-model-name model && \
    echo "✅ Modelo entrenado exitosamente"

# Exponer puertos
EXPOSE 5005 5055

# Script de inicio
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Comando de inicio
CMD ["/app/start.sh"]