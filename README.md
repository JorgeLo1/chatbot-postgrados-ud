# 🎓 Chatbot Postgrados - Universidad Distrital

Chatbot inteligente para información sobre programas de postgrado, construido con Rasa 3.6.

## 🚀 Características

- ✅ Consulta de **12+ programas** de postgrado
- ✅ Información sobre **costos, requisitos, fechas**
- ✅ Integración con **Oracle APEX**
- ✅ **Formulario de contacto** con validación
- ✅ Sistema de **cache** para optimizar rendimiento
- ✅ Búsqueda inteligente con **NLP en español**

---

## 📋 Requisitos Previos

- Python 3.10+
- pip 23.0+
- Git

---

## 🔧 Instalación Local

### 1. Clonar repositorio


### 2. Crear entorno virtual
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
```bash
cp .env.example .env
# Editar .env con tus credenciales
```

### 5. Entrenar modelo
```bash
rasa train
```

### 6. Iniciar servidores

**Terminal 1 - Action Server:**
```bash
rasa run actions
```

**Terminal 2 - Rasa Server:**
```bash
rasa run --enable-api --cors "*"
```

---

## 🐳 Docker (Recomendado)
```bash
# Construir imagen
docker build -t chatbot-ud .

# Ejecutar contenedor
docker run -p 5005:5005 --env-file .env chatbot-ud
```

---

## 🌐 Deploy en Render

### Opción A: Automático con Blueprint

1. Conectar repositorio en [Render](https://dashboard.render.com/)
2. Render detectará `render.yaml` automáticamente
3. Configurar variables de entorno
4. Deploy

### Opción B: Manual

Ver documentación completa en [DEPLOY.md](DEPLOY.md)

---

## 📡 API Endpoints

### REST Webhook
```bash
POST https://tu-app.onrender.com/webhooks/rest/webhook
Content-Type: application/json

{
  "sender": "user_123",
  "message": "hola"
}
```

### Health Check
```bash
GET https://tu-app.onrender.com/
```

---

## 🧪 Testing
```bash
# Pruebas conversacionales
rasa test

# Pruebas de NLU
rasa test nlu

# Pruebas de stories
rasa test core
```

---

## 📊 Estructura del Proyecto
```
chatbot-ud/
├── actions/           # Custom actions
├── data/              # Training data
├── models/            # Trained models (no versionado)
├── tests/             # Test stories
├── config.yml         # NLU pipeline
├── domain.yml         # Domain definition
├── endpoints.yml      # External services
├── credentials.yml    # Channel credentials
└── requirements.txt   # Dependencies
```

---

## 🔐 Variables de Entorno

| Variable | Descripción | Requerido |
|----------|-------------|-----------|
| `APEX_API_URL` | URL base de Oracle APEX | ✅ |
| `APEX_TIMEOUT` | Timeout de API (segundos) | ❌ |
| `ENABLE_CACHE` | Habilitar cache (True/False) | ❌ |
| `CACHE_TTL` | Tiempo de vida del cache (segundos) | ❌ |

---

## 🐛 Troubleshooting

### Error: "Model not found"
```bash
rasa train --fixed-model-name model
```

### Error: "Action server not reachable"
Verificar que `endpoints.yml` tenga la URL correcta del action server.

### Error: "Spacy model not found"
```bash
python -m spacy download es_core_news_md
```

---

## 📝 Licencia

Este proyecto es propiedad de la Universidad Distrital Francisco José de Caldas.

---

## 👥 Autores

-JORGE EDISON VELANDIA LOZANO

---
