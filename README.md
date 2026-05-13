# Chatbot Postgrados — Universidad Distrital Francisco José de Caldas

Chatbot conversacional en español construido con **Rasa Open Source 3.6** para responder consultas sobre programas de postgrado: costos, requisitos, fechas, modalidad y contactos. La información se obtiene en tiempo real desde **Oracle APEX** vía REST. Opera en dos canales: REST webhook (frontend SISIFO) y WhatsApp Cloud API.

---

## Requisitos

- Python 3.10 (Rasa 3.6 no es compatible con Python 3.11+)
- pip 23+
- Docker (para producción)
- spaCy `es_core_news_md` 3.5.0

---

## Instalación local

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download es_core_news_md

cp .env.example .env
# Completar .env con credenciales reales
```

### Entrenamiento y arranque

```bash
# Entrenar con nombre fijo (igual que en producción)
rasa train --fixed-model-name model

# Terminal 1 — Action Server
rasa run actions

# Terminal 2 — Rasa Server
rasa run --enable-api --cors "*"
```

### Generar datos dinámicos desde APEX

```bash
python fetch_training_data.py            # genera nlu_dynamic.yml + stories_dynamic.yml
python fetch_training_data.py --dry-run  # vista previa sin escribir
```

---

## Docker

```bash
docker build -t chatbot-rasa:latest .

docker run -d \
  --name chatbot-rasa \
  --restart unless-stopped \
  -p 5005:5005 \
  -p 5055:5055 \
  --env-file .env \
  chatbot-rasa:latest

docker logs -f chatbot-rasa
```

> El contenedor puede tardar 3–8 minutos en responder a `/status` porque el arranque incluye `fetch → train`.

---

## Despliegue en producción (Oracle Cloud)

El bot corre en **Oracle Cloud (Ubuntu 24, IP: 149.130.173.156)**.

### Chatbot principal (Docker)

El CI/CD en `.github/workflows/deploy-oracle.yml` se activa con cada push a `main`: conecta por SSH, hace `git pull`, reconstruye la imagen y reinicia el contenedor.

Para redespliegue manual:

```bash
ssh -i "ssh-key-2025-10-27.key" ubuntu@149.130.173.156
docker stop chatbot-rasa && docker rm chatbot-rasa
docker build -t chatbot-rasa:latest .
docker run -d --name chatbot-rasa --restart unless-stopped \
  -p 5005:5005 -p 5055:5055 --env-file .env chatbot-rasa:latest
docker logs -f chatbot-rasa
```

### Adaptador WhatsApp (tmux + ngrok)

El adaptador Flask corre **fuera del contenedor** en una sesión tmux. El CI/CD **no lo redesplega** — hacerlo manualmente si cambia `whatsapp_adapter.py`:

```bash
# Servicios (sesión "rasa")
tmux new -s rasa
bash start-whatsapp-adapter.sh
# Ctrl+b, d  → detach

# Túnel HTTPS (sesión "ngrok")
tmux new -s ngrok
ngrok http 5006
# Ctrl+b, d  → detach
```

Si la URL de ngrok cambia, actualizar el webhook en el [Meta Developer Dashboard](https://developers.facebook.com/apps).

### Verificación post-despliegue

```bash
curl http://localhost:5005/status
curl http://localhost:5055/health
curl http://localhost:5006/health
```

---

## Variables de entorno

Ver [.env.example](.env.example) para la lista completa. Variables clave:

| Variable | Descripción |
|----------|-------------|
| `APEX_API_URL` | URL base de Oracle APEX |
| `APEX_SSL_VERIFY` | `true` en producción siempre |
| `WHATSAPP_APP_SECRET` | Secreto Meta para verificación HMAC del webhook |
| `WHATSAPP_ACCESS_TOKEN` | Token de acceso de la app Meta |
| `BUSQUEDA_LOCAL_HABILITADA` | Habilita índice local FAQ (rapidfuzz + BM25) |
| `FAQ_INDEX_REFRESH_MINUTES` | Frecuencia de refresh del índice (default 10) |

---

## Pruebas

```bash
rasa test core --stories tests/test_stories.yml
rasa test nlu --nlu data/nlu.yml
rasa shell nlu   # evaluar predicción de un intent
```

---

## Estructura

```
chatbot-postgrados-ud/
├── .github/workflows/     # CI/CD → deploy-oracle.yml
├── actions/
│   ├── actions.py         # 30+ acciones custom
│   └── synonyms.yaml      # sinónimos de dominio (editable sin tocar código)
├── data/
│   ├── nlu.yml            # ejemplos estáticos de intents
│   ├── rules.yml          # reglas duras
│   ├── stories.yml        # flujos conversacionales
│   ├── nlu_dynamic.yml    # generado por fetch_training_data.py
│   └── stories_dynamic.yml
├── tests/
│   └── test_stories.yml
├── config.yml             # pipeline NLU + políticas
├── domain.yml             # intents, slots, responses, forms
├── endpoints.yml
├── fetch_training_data.py # genera datos desde APEX
├── whatsapp_adapter.py    # bridge WhatsApp ↔ Rasa
├── start.sh               # arranque en contenedor
├── start-whatsapp-adapter.sh
├── dockerfile
├── requirements.txt
└── .env.example
```

---

## Solución de problemas frecuentes

**"Model not found"**
```bash
rasa train --fixed-model-name model
```

**"Action server not reachable"**
Verificar que `endpoints.yml` apunte a `http://localhost:5055/webhook`.

**"spaCy model not found"**
```bash
python -m spacy download es_core_news_md
```

**"Redis no disponible"**
Normal en desarrollo — el adaptador cae a sesiones en memoria automáticamente.

---

## Licencia

Propiedad de la Universidad Distrital Francisco José de Caldas.

## Autor

Jorge Edison Velandia Lozano
