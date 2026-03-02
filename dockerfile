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

# Copiar archivos de configuración de Rasa
COPY config.yml domain.yml credentials.yml endpoints.yml ./

# Copiar datos de entrenamiento base (nlu.yml, stories.yml, rules.yml)
# Estos son los datos ESTÁTICOS — fetch_training_data.py generará
# nlu_dynamic.yml y stories_dynamic.yml en tiempo de ejecución
COPY data/ ./data/

# Copiar actions y adaptadores
COPY actions/ ./actions/
COPY whatsapp_adapter.py ./

# Copiar script de entrenamiento dinámico
# (se ejecutará en start.sh, NO aquí)
COPY fetch_training_data.py ./

# Copiar script de inicio
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Exponer puertos
EXPOSE 5005 5055 5006

# Comando de inicio
CMD ["/app/start.sh"]