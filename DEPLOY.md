# 🚀 Guía de Deploy en Render

## Requisitos

- Cuenta en [Render](https://render.com) (gratis)
- Repositorio en GitHub con el código
- Variables de entorno configuradas

---

## Pasos de Deploy

### 1. Preparar Repositorio
```bash
git add .
git commit -m "Ready for Render deploy"
git push origin main
```

### 2. Conectar Render con GitHub

1. Ir a https://dashboard.render.com/
2. Click en **New → Web Service**
3. Conectar tu cuenta de GitHub
4. Autorizar acceso al repositorio

### 3. Configurar Servicio

**Configuración básica:**
- **Name:** `chatbot-postgrados-ud`
- **Environment:** Docker
- **Region:** Oregon (más cercano a Colombia)
- **Branch:** main
- **Plan:** Free

**Build & Deploy:**
- Render detectará automáticamente el `Dockerfile`
- Build Command: (dejar vacío, usa Dockerfile)
- Start Command: (dejar vacío, usa ENTRYPOINT)

### 4. Variables de Entorno

Agregar en **Environment Variables:**
```
APEX_API_URL=https://oracleapex.com/ords/udchatbot/chatbot
APEX_TIMEOUT=60
ENABLE_CACHE=True
CACHE_TTL=3600
PORT=5005
```

### 5. Deploy

1. Click en **Create Web Service**
2. Esperar 10-15 minutos (primera vez tarda más)
3. Una vez completado, tendrás una URL como:
```
   https://chatbot-postgrados-ud.onrender.com
```

---

## Verificar Deploy

### Test 1: Health Check
```bash
curl https://chatbot-postgrados-ud.onrender.com/
```

### Test 2: Webhook
```bash
curl -X POST https://chatbot-postgrados-ud.onrender.com/webhooks/rest/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "test_user",
    "message": "hola"
  }'
```

**Respuesta esperada:**
```json
[
  {
    "recipient_id": "test_user",
    "text": "¡Bienvenido! 🎓..."
  }
]
```

---

## Troubleshooting

### Error: "Build failed"

**Causa:** Dependencias faltantes o incompatibles

**Solución:**
1. Verificar `requirements.txt`
2. Revisar logs en Render dashboard
3. Ajustar versiones si es necesario

### Error: "Service unhealthy"

**Causa:** El servicio tarda en iniciar

**Solución:**
1. Render Free tier entra en "sleep" después de 15 min de inactividad
2. Primera petición puede tardar 30-60 segundos
3. Considerar upgrade a plan Starter ($7/mes) para evitar sleep

### Error: "Action server not reachable"

**Causa:** El action server no inició correctamente

**Solución:**
1. Ir a Logs en Render dashboard
2. Buscar línea: `🔧 Iniciando Action Server...`
3. Si falta, aumentar sleep en `docker-entrypoint.sh`:
```bash
   sleep 20  # Era 15, aumentar a 20
```

---

## Limitaciones Free Tier

| Recurso | Límite |
|---------|--------|
| RAM | 512 MB |
| CPU | Compartido |
| Sleep | Después de 15 min inactividad |
| Build time | 15 minutos |
| Bandwidth | 100 GB/mes |

**Recomendaciones:**
- Para producción, considerar plan Starter ($7/mes)
- Implementar health checks externos (UptimeRobot gratis)
- Optimizar modelo reduciendo epochs si falla por RAM

---

## Monitoreo

### Logs en tiempo real
```bash
# Usando Render CLI
render logs -f chatbot-postgrados-ud
```

### Métricas

Dashboard → Service → Metrics:
- Response times
- Error rates
- Memory usage
- Restart count

---

## Actualizaciones
```bash
# Hacer cambios en código
git add .
git commit -m "Feat: nueva funcionalidad"
git push origin main

# Render auto-detecta cambios y re-deploya
```

---

## URLs Importantes

- **Dashboard:** https://dashboard.render.com/
- **Docs:** https://render.com/docs
- **Status:** https://status.render.com/