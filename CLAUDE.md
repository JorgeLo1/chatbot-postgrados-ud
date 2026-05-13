# CLAUDE.md

> ⚠️ **Archivo LOCAL — NO SUBIR al repositorio.**
> Este `CLAUDE.md` es una guía personal para Claude Code. No se versiona ni en `main` ni en `develop`. Contiene notas internas, IPs/credenciales del despliegue real, plan de fases en progreso y bitácora de cambios — material que no debe llegar al historial público del repositorio.
> Si por accidente aparece en `git status` como staged: `git restore --staged CLAUDE.md`. Confirmar que `.gitignore` contenga la línea `CLAUDE.md`.

---

Guía de trabajo para Claude Code (claude.ai/code) en este repositorio. Escrita en español para alineación con el equipo y con la documentación interna del proyecto.

---

## 1. Visión general del proyecto

Chatbot conversacional en español construido con **Rasa Open Source 3.6.21** para la Universidad Distrital Francisco José de Caldas. Responde consultas sobre programas de postgrado (costos, requisitos, becas, fechas, modalidad, contactos) tomando la información viva desde un backend **Oracle APEX** vía endpoints ORDS REST. Está desplegado en **Oracle Cloud (Ubuntu 24, IP: 149.130.173.156)** y opera en dos canales:

- **REST webhook**: usado por el frontend SISIFO (Angular/Go) — `POST /webhooks/rest/webhook`.
- **WhatsApp Cloud API**: a través de un adaptador Flask que media entre Meta y Rasa, gestionando sesiones e inactividad.

### Arquitectura de procesos

```
┌─────────────────────┐    ┌──────────────────────────────────────────┐
│ Cliente Web/SISIFO  │───▶│         Docker: chatbot-rasa             │
└─────────────────────┘    │  ┌─────────────┐   ┌──────────────────┐ │
                           │  │ Rasa Server │──▶│  Action Server   │ │
┌─────────────────────┐    │  │  port 5005  │   │   port 5055      │ │
│  WhatsApp Cloud API │    │  └─────────────┘   └──────────┬───────┘ │
│  (Meta Graph v18)   │    │  ┌──────────────────────────┐ │         │
└──────────┬──────────┘    │  │ WhatsApp Adapter (Flask) │ │         │
           │               │  │       port 5006          │ │         │
           ▼               │  └──────────────────────────┘ │         │
  https://xxx.ngrok-free   └──────────────────────────────────────────┘
  (systemd → auto-start)                                    │
                                                            ▼
                                                   ┌─────────────────┐
                                                   │ Oracle APEX ORDS│
                                                   │ (Backend FAQs)  │
                                                   └─────────────────┘
```

**Los 3 servicios corren dentro de Docker.** CI/CD los redesplega todos automáticamente en cada push a `main`. ngrok corre como servicio systemd en el host (arranque automático, dominio estático).

### Mapa de puertos

| Puerto | Servicio                              |
|--------|---------------------------------------|
| 5005   | Rasa REST API + webhook               |
| 5055   | Rasa Action Server                    |
| 5006   | Adaptador WhatsApp (Flask)            |

### Archivos clave (resumen rápido)

| Archivo | Líneas | Rol |
|--------|--------|-----|
| [actions/actions.py](actions/actions.py) | 2256 | 30+ acciones custom (monolítico — candidato a refactor en Fase 2) |
| [whatsapp_adapter.py](whatsapp_adapter.py) | 325 | Bridge WhatsApp ↔ Rasa con sesiones Redis + scheduler |
| [fetch_training_data.py](fetch_training_data.py) | 515 | Generación automática de NLU/stories desde APEX |
| [config.yml](config.yml) | 105 | Pipeline NLU (spaCy + DIET 200ep) y políticas (TED 150ep) |
| [domain.yml](domain.yml) | 328 | 31 intents · 4 entidades · 11 slots · forms · responses |
| [data/nlu.yml](data/nlu.yml) | 1724 | Ejemplos estáticos por intent |
| [data/stories.yml](data/stories.yml) | 771 | Flujos conversacionales |
| [data/rules.yml](data/rules.yml) | 226 | Reglas duras (saludos, navegación) |
| [start.sh](start.sh) | 153 | Arranque en contenedor (fetch → train → 3 procesos) |
| [dockerfile](dockerfile) | 47 | Imagen base `python:3.10-slim` |

---

## 2. Comandos comunes

### Desarrollo local

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download es_core_news_md

# Entrenamiento (con nombre fijo, como en producción)
rasa train --fixed-model-name model

# Levantar action server y rasa server (2 terminales)
rasa run actions
rasa run --enable-api --cors "*"
```

### Pruebas

```bash
rasa test core --stories tests/test_stories.yml   # historias
rasa test nlu --nlu data/nlu.yml                  # NLU
rasa test                                          # todo
rasa shell nlu                                     # evaluar predicción de intent
rasa interactive                                   # depuración interactiva
```

### Regenerar datos dinámicos desde APEX

```bash
python fetch_training_data.py            # genera nlu_dynamic.yml y stories_dynamic.yml
python fetch_training_data.py --dry-run  # vista previa sin escribir
python fetch_training_data.py --solo-nlu # omite stories
```

---

## 3. Despliegue en producción (Oracle Cloud)

### Conexión al servidor

```bash
ssh -i "ssh-key-2025-10-27.key" ubuntu@149.130.173.156
```

> La clave SSH debe estar en la ruta correcta localmente. No versionar la clave en el repo.

---

### Redespliegue (caso normal)

**Hacer push a `main`** → CI/CD hace todo automáticamente. No se necesita intervención manual.

Los tres servicios corren **dentro del contenedor Docker** (`start.sh` paso 3-4-5):
- Action Server (5055)
- WhatsApp Adapter (5006)
- Rasa Server (5005, PID 1)

El contenedor tarda **3–8 minutos** en responder a `/status` (fetch APEX → entrenamiento → inicio).

### Redespliegue manual (si CI/CD falla)

```bash
ssh -i "ssh-key-2025-10-27.key" ubuntu@149.130.173.156
cd ~/chatbot-postgrados-ud
git pull origin main
docker stop chatbot-rasa && docker rm chatbot-rasa
docker build -t chatbot-rasa:latest .
docker run -d \
  --name chatbot-rasa \
  --restart unless-stopped \
  -p 5005:5005 \
  -p 5055:5055 \
  -p 5006:5006 \
  --env-file .env \
  chatbot-rasa:latest
docker logs -f chatbot-rasa
```

### Verificación post-despliegue

```bash
curl http://localhost:5005/status   # Rasa Server
curl http://localhost:5055/health   # Action Server
curl http://localhost:5006/health   # WhatsApp Adapter
docker logs --tail 100 chatbot-rasa
docker stats chatbot-rasa
```

---

### ngrok — túnel HTTPS para WhatsApp

ngrok corre manualmente en sesión `tmux` apuntando a `localhost:5006` (puerto Docker).

```
Meta (Graph API)
      │
      ▼
https://xxx.ngrok-free.dev   ← configurada en Meta Dashboard
      │  (tmux ngrok → Oracle Cloud)
      ▼
http://localhost:5006        ← puerto expuesto por Docker (WhatsApp Adapter)
```

```bash
# Arrancar ngrok (si se cae o el servidor reinicia)
tmux new -s ngrok
ngrok http 5006
# Anotar la URL y actualizar Meta Dashboard si cambió
Ctrl+b, d   # detach

# Ver URL activa
curl http://localhost:4040/api/tunnels
```

> `start-whatsapp-adapter.sh` es solo para **desarrollo sin Docker**. No usar cuando el contenedor está corriendo — hay conflicto de puertos en 5005/5055/5006.

---

### CI/CD automático

`.github/workflows/deploy-oracle.yml` se activa con cada `push` a `main`:
1. Conecta por SSH a `149.130.173.156`.
2. Hace `git pull` del repositorio.
3. Reconstruye la imagen y reinicia el contenedor (incluye el WhatsApp Adapter en puerto 5006).

ngrok no se toca en CI/CD — systemd lo mantiene activo independientemente.

---

## 4. Flujo de arranque (`start.sh`)

1. Carga `.env` y exporta variables.
2. Ejecuta `fetch_training_data.py` → consume APEX y genera `data/nlu_dynamic.yml` + `data/stories_dynamic.yml`.
3. `rasa train --fixed-model-name model` (combina estático + dinámico).
4. Inicia **Action Server** (5055) en background, espera `/health`.
5. Inicia **WhatsApp Adapter** (5006) en background con scheduler APScheduler.
6. `exec rasa run` para que el Rasa Server quede como PID 1 (ideal para Docker).

---

## 5. Configuración NLU/Policies actual

### Pipeline NLU (`config.yml`)

- `SpacyNLP` + `SpacyTokenizer` con modelo `es_core_news_md` (3.5.0).
- `RegexFeaturizer` + `LexicalSyntacticFeaturizer` + `SpacyFeaturizer` (pooling mean).
- Dos `CountVectorsFeaturizer`: palabras (1–3 grams) y caracteres (1–4 char_wb) → robustez ante errores tipográficos.
- `DIETClassifier` (200 epochs, embedding_dim 40, softmax, dropouts esparso/denso 0.1).
- `EntitySynonymMapper` + `RegexEntityExtractor`.
- `FallbackClassifier` con **umbral 0.65** y ambigüedad 0.15.

### Policies

- `MemoizationPolicy` (history 5)
- `RulePolicy` (core_fallback 0.3, default `action_default_fallback`)
- `UnexpecTEDIntentPolicy` (100 ep)
- `TEDPolicy` (150 ep, history 8, embedding 40)

### Configuración de sesión

```yaml
session_expiration_time: 5     # minutos — alineado con timeout del adapter
carry_over_slots_to_new_session: false
```

---

## 6. Variables de entorno

`.env.example` documenta las variables. Las clave:

```bash
# Puertos
PORT=5005
ACTION_SERVER_PORT=5055
WHATSAPP_ADAPTER_PORT=5006

# Oracle APEX
APEX_API_URL=https://oracleapex.com/ords/udchatbot/chatbot
APEX_TIMEOUT=60-120
APEX_SSL_VERIFY=true            # NUNCA false en producción

# Cache (en memoria simple, NO Redis para FAQs aún)
ENABLE_CACHE=False
CACHE_TTL=3600

# WhatsApp Business (Meta Graph v18)
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...

# Sesiones / inactividad
INACTIVITY_TIMEOUT=300
INACTIVITY_WARNING_TIME=240

# Redis (opcional, fallback in-memory si no está disponible)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=...

# Modo
ENVIRONMENT=production|development
LOG_LEVEL=INFO|DEBUG
```

---

## 7. Integración con Oracle APEX

- **Base URL**: `https://oracleapex.com/ords/udchatbot/chatbot`
- **Swagger / OpenAPI**: `https://oracleapex.com/ords/udchatbot/open-api-catalog/chatbot/`

`actions.py` y `fetch_training_data.py` consumen endpoints REST publicados con ORDS:

| Endpoint                              | Método | Body / Params | Uso |
|---------------------------------------|--------|---------------|-----|
| `/postgrados`                         | GET    | —             | Listado de programas activos |
| `/postgrados/{id}`                    | GET    | path: `id`    | Detalle de un programa |
| `/faq`                                | GET    | —             | FAQs globales |
| `/faq/{id_postgrado}`                 | GET    | path: `id_postgrado` | FAQs por programa |
| `/faq/buscar/{id_postgrado}`          | GET    | path: `id_postgrado`, query: `pregunta` | Búsqueda fuzzy de FAQ |
| `/faq/sin-respuesta`                  | POST   | `{"body_text": "string"}` | Registra preguntas sin respuesta |
| `/buscar`                             | POST   | `{"nombre": "string"}` | Búsqueda de programas por nombre (LIKE `%nombre%` en `POSTGRADOS`). Retorna `id_postgrado`, `nombre`, `facultad`, `descripcion`. **No es búsqueda de FAQs.** Debería usarse en `ActionSeleccionarPostgrado` en lugar del filtro local actual. |
| `/historial`                          | POST   | `{"body_text": "string"}` | Log de conversación |
| `/contacto`                           | POST   | `{"body_text": "string"}` | Registro de formulario de contacto |

> **Nota**: `GET /preguntas-sin-respuesta` figura en documentación anterior pero **no aparece en el Swagger actual**. Verificar si sigue activo antes de usarlo.

### Comportamiento verificado de los endpoints clave

**`GET /faq/{id_postgrado}`**
- Filtra `ACTIVO='S'` y valida que el postgrado existe con `ESTADO='S'`.
- Ordena por `VECES_CONSULTADA DESC` — las FAQs más consultadas llegan primero.
- Retorna: `ID_FAQ`, `ID_POSTGRADO`, `PREGUNTA`, `RESPUESTA`, `VECES_CONSULTADA`, `ACTIVO`.
- Aprox. **decenas** de registros por programa. Carga total en memoria: trivial.

**`GET /faq`** (todas las FAQs de todos los programas)
- Join con `POSTGRADOS` — retorna también `POSTGRADO_NOMBRE` y `FACULTAD`.
- Solo FAQs con `ACTIVO='S'` de programas con `ESTADO='S'`.
- Ordenado por `ID_POSTGRADO, VECES_CONSULTADA DESC`.
- **Usar para cargar el índice local completo en 1 sola llamada** en lugar de N llamadas por programa.

**`POST /buscar`** — búsqueda de PROGRAMAS por nombre (no FAQs)
- Body: `{"nombre": "texto"}`. Hace `UPPER(nombre) LIKE '%texto%'` sobre `POSTGRADOS`.
- Retorna: `id_postgrado`, `nombre`, `facultad`, `descripcion`.
- **Debe reemplazar el filtro local de `ActionSeleccionarPostgrado`**: actualmente el código descarga todos los programas y filtra en Python. `POST /buscar` hace eso en Oracle con el LIKE correcto.

### Esquema de tablas (DDL real)

| Tabla | Columnas clave | Notas |
|-------|---------------|-------|
| `POSTGRADOS` | `ID_POSTGRADO`, `NOMBRE` VARCHAR2(100), `FACULTAD` VARCHAR2(50), `CORREO_ELECTRONICO` VARCHAR2(100), `DESCRIPCION` VARCHAR2(500), `ESTADO` VARCHAR2(1) | `ESTADO IN ('S','N')`. Trigger valida formato email. |
| `FAQ` | `ID_FAQ`, `ID_POSTGRADO` (FK), `PREGUNTA` VARCHAR2(1000), `RESPUESTA` CLOB, `ACTIVO` VARCHAR2(1), `VECES_CONSULTADA` NUMBER | `ACTIVO IN ('S','N')`. Dos triggers: auditoría → `LOG_MODIFICACION_FAQ`, auto-update `FECHA_MODIFICACION`. Índice compuesto `(ID_POSTGRADO, ACTIVO)`. |
| `HISTORIAL_CONVERSACION` | `ID_CONVERSACION`, `USUARIO` VARCHAR2(20), `MENSAJE_USUARIO` CLOB, `RESPUESTA_BOT` CLOB, `ID_POSTGRADO` NUMBER (nullable), `FECHA_HORA` DATE | Índices en `USUARIO` y `FECHA_HORA`. FK a POSTGRADOS con ON DELETE SET NULL. |
| `HISTORIAL_CONVERSACION_ARCHIVO` | Misma estructura que HISTORIAL_CONVERSACION | Sin PK ni identity. Tabla de archivo histórico, sin constraints. |
| `PREGUNTAS_SIN_RESPUESTA` | `ID_PREGUNTA`, `ID_POSTGRADO` (nullable FK), `PREGUNTA_USUARIO` VARCHAR2(1000), `USUARIO_TELEFONO` VARCHAR2(50), `RESPUESTA` CLOB, `ESTADO` VARCHAR2(20), `FRECUENCIA` NUMBER, `RESPONDIDO_POR` VARCHAR2(100), `NOTAS_ADMIN` VARCHAR2(500) | `ESTADO IN ('PENDIENTE','RESPONDIDA','DESCARTADA')`. Índices en `(ID_POSTGRADO, ESTADO)`, `ESTADO`, `FECHA_REGISTRO`. |
| `LOG_MODIFICACION_FAQ` | `ID_LOG`, `ID_FAQ` (FK), `ACCION` VARCHAR2(25), `FECHA_HORA`, `USERNAME_APEX` VARCHAR2(100) | Solo para auditoría interna de APEX. El chatbot no escribe aquí directamente. |

### Límites de columna críticos para el código

| Campo | Tipo | Límite | Acción en el bot |
|-------|------|--------|-----------------|
| `HISTORIAL_CONVERSACION.USUARIO` | VARCHAR2(20) | 20 chars | `tracker.sender_id[:20]` siempre |
| `PREGUNTAS_SIN_RESPUESTA.USUARIO_TELEFONO` | VARCHAR2(50) | 50 chars | Sin truncado necesario en uso normal |
| `FAQ.RESPUESTA` | CLOB | ilimitado | Truncar a 3800 chars antes de enviar por WhatsApp (límite Meta: 4096) |
| `POSTGRADOS.NOMBRE` | VARCHAR2(100) | 100 chars | — |
| `FAQ.PREGUNTA` | VARCHAR2(1000) | 1000 chars | — |

> ⚠️ Versión anterior de este archivo indicaba `USUARIO_TELEFONO VARCHAR2(15)` — **era incorrecto**. El DDL real es VARCHAR2(50).

### Campos de estado activo

- `POSTGRADOS.ESTADO = 'S'` → programa activo (filtrar en cliente).
- `FAQ.ACTIVO = 'S'` → FAQ activa (la función `buscar_faq` ya filtra esto).

### Función PL/SQL `buscar_faq` — algoritmo de scoring

Detrás del endpoint `GET /faq/buscar/{id_postgrado}?pregunta=...`. Retorna `CLOB` con la respuesta encontrada o un mensaje de error/no-encontrado.

**Pipeline de normalización** (en orden):
1. Mayúsculas + trim
2. TRANSLATE de acentos: `ÁÉÍÓÚÜÑ` → `AEIOUUN`
3. Elimina puntuación `?¿!¡.,;:()""''`
4. Correcciones ortográficas hardcodeadas (`BIOINGIENERIA` → `BIOINGENIERIA`, etc.)
5. Expande abreviaturas (`TI` → `TECNOLOGIA INFORMACION`, `SST`, `SIG`, `HSST`)
6. Normaliza sinónimos de acción (`QUISIERA`, `NECESITO`, `DAME`, etc. → espacio)
7. Elimina stopwords (`QUE`, `EL`, `LA`, `DE`, `COMO`, `PARA`, etc.)
8. Limpia espacios resultantes

**Scoring por niveles** (menor prioridad = mejor match):

| Nivel | Prioridad | Criterio |
|-------|-----------|---------|
| 1 | 5–7 | Coincidencia exacta (cruda / sin puntuación / normalizada) |
| 2 | 10–18 | Keyword temático bilateral: costos, requisitos, inscripción, fechas, plan de estudios, perfil, modalidad, información general, título |
| 3 | 20–24 | Semántico: pregunta usuario dentro de DB, DB dentro de usuario, coincidencia parcial fuerte, 4+ palabras clave |
| 4 | 30–35 | Parcial: 3 palabras ≥5 chars, 2 palabras ≥5 chars, 1 palabra ≥7 chars |
| 5 | 40 | Débil: 1 palabra 5–6 chars |
| — | 999 | Sin coincidencia → descartada (umbral `prioridad < 50`) |

**Desempate**: `veces_consultada DESC` → `LENGTH(pregunta) ASC` → `id_faq ASC`.

**Efecto secundario**: incrementa `FAQ.VECES_CONSULTADA` con COMMIT al encontrar resultado. Si el UPDATE falla, la respuesta se retorna igual (excepción silenciosa).

**Casos de retorno sin resultado**:
- ID de postgrado inválido o nulo
- Pregunta vacía o menor a 3 chars
- Sin FAQs activas para ese postgrado
- Ninguna FAQ supera el umbral de prioridad 50
- Respuesta encontrada pero CLOB vacío

### Monkey-patch IPv4 en `fetch_training_data.py`

El WAF de Oracle rechaza el `User-Agent` por defecto de `python-requests` y en Oracle Cloud (Ubuntu), la resolución DNS puede devolver IPv6 sin conectividad real. El script aplica dos workarounds:

1. **Override de `socket.getaddrinfo`** para forzar IPv4 (`AF_INET`).
2. **`User-Agent` de Chrome** para pasar el WAF.

**Este hack es necesario en el entorno de Oracle Cloud actual. No eliminar sin probar primero.** Pendiente implementar `FORCE_IPV4=true|false` (variable no existe aún) para poder desactivarlo en entornos donde IPv6 funcione correctamente.

---

## 8. Patrones del código

### `actions/actions.py` — utilidades compartidas

- `make_api_request(method, endpoint, data, params)` → único punto de salida HTTP. Maneja status, timeout, JSON anidado de APEX, fallbacks.
- `get_from_cache(key)` / `set_in_cache(key, value)` → caché en memoria con TTL (gobernado por `ENABLE_CACHE`).
- `normalizar_texto(texto)` → quita tildes y normaliza para comparaciones de nombre de programa.
- `registrar_pregunta_sin_respuesta(...)` → persiste preguntas que el bot no supo responder para curaduría manual posterior.

### Convenciones para nuevas acciones

1. Subclase `Action` con `name()` retornando `action_<snake_case>`.
2. Registrar en `domain.yml` bajo `actions:`.
3. Si dispara form: usar `FollowupAction("datos_contacto_form")`.
4. Para limpiar estado: emitir `SlotSet("...", None)` o `AllSlotsReset()`.
5. Para terminar conversación: `AllSlotsReset()` + `Restarted()`.

### Convenciones de datos de entrenamiento

- **Static intents** → `data/nlu.yml` con ≥ 10–15 ejemplos diversos por intent.
- **Dynamic intents** → generados en arranque por `fetch_training_data.py` (no editar a mano).
- Toda story/regla debe referenciar intents y actions registradas en `domain.yml`.
- Idioma: español, sin acentos en keywords de búsqueda (se normalizan en código).

---

## 9. Riesgos conocidos y deuda técnica

### Seguridad — pendiente de resolución

| Riesgo | Severidad | Estado |
|--------|-----------|--------|
| Sin verificación HMAC en webhook WhatsApp (`X-Hub-Signature-256`) | Alta | **Resuelto** — `_verificar_firma_hmac()` en `whatsapp_adapter.py` |
| Container corre como root (base `python:3.10-slim`) | Media | Pendiente Fase 0 |
| `APEX_SSL_VERIFY=false` como posible default si variable no seteada | Alta | **Resuelto** — default cambiado a `"true"` en `actions.py` |
| Token WhatsApp y credenciales APEX en `.env` sin gestor de secretos | Media | Pendiente Fase 1 |
| Sin rate limiting en adaptador Flask | Media | Pendiente Fase 1 |

### Vulnerabilidad CVE conocida y no parcheable

**CVE-2024-3660 (CVSS 9.3)** — Keras < 2.13: inyección de código arbitrario al cargar modelos H5.

Rasa 3.6 fija `numpy==1.23.5` que arrastra TensorFlow 2.12. No es posible actualizar TF sin romper Rasa OSS 3.6. **Riesgo real mitigado** porque los modelos solo se cargan desde builds propios del equipo (no se acepta input externo de modelos). Documentar este riesgo aceptado formalmente si la universidad requiere auditoría de seguridad.

**Python 3.11 no es compatible con Rasa 3.6** — PyPI declara `Requires: Python <3.11, >=3.8`. No intentar subir la versión de Python sin migrar primero el stack de Rasa.

### Arquitectura y código

- `actions.py` monolítico (2256 líneas, tras la limpieza de comentarios IA) — refactor planificado en Fase 2.
- Sin `tracker_store` persistente — conversaciones se pierden al reiniciar el contenedor.
- Sin retries/backoff en `make_api_request` — un timeout de APEX rompe la conversación.
- Caché solo en memoria dentro del Action Server.
- Lógica de mapeo intent↔keywords duplicada en `INTENT_KEYWORDS` y `INTENT_RULES`.
- Modelos `.tar.gz` commiteados en `models/` — limpiar con `git rm --cached`.

### Stack

- **Rasa OSS 3.6.21** es la versión final — no habrá más releases de Rasa Open Source. Migración a Rasa Pro CALM o reescritura es decisión estratégica a tomar en ≥6 meses con datos.
- **Adaptador WhatsApp** — corre dentro de Docker (puerto 5006 expuesto), redespliegue automático en CI/CD. ngrok gestionado por systemd (`chatbot-ngrok.service`) con dominio estático — sin intervención manual tras configuración inicial.
- **Ngrok Free con URL dinámica** — la URL HTTPS cambia en cada reinicio de ngrok. Si ngrok cae o el servidor reinicia, hay que actualizar manualmente la URL en Meta Developer Dashboard. Riesgo operativo real: el canal WhatsApp queda mudo hasta que se actualice. Solución a largo plazo: configurar SSL con nginx + certbot (Let's Encrypt) en el servidor para eliminar la dependencia de ngrok.

---

## 10. CI/CD actual

`.github/workflows/deploy-oracle.yml`:
- Trigger: `push` a `main`.
- Se conecta por SSH a Oracle Cloud (`149.130.173.156`), hace pull del código, reconstruye la imagen y reinicia el contenedor.
- Redesplega los tres servicios: Rasa Server, Action Server y WhatsApp Adapter (puerto 5006 expuesto).
- **No hay etapa de tests** ni linting antes del deploy — ver Fase 0.

La rama `develop` se usa para WIP. Mergear a `main` solo cuando esté listo para deploy.

---

## 11. Plan de mejoramiento por fases

Fases ordenadas por impacto real en producción, no por limpieza de código.

> **Producto en producción** — desde 2026-05-13 la prioridad operativa es **Fase A** (estabilización de búsqueda FAQ). Fases 0 y 1 pueden ejecutarse en paralelo porque tocan código aislado.

### Fase A — Estabilización y mejora exponencial de búsqueda FAQ (PRIORIDAD CRÍTICA, 5–6 semanas)

> **Producto ya en producción**. Esta fase precede al refactor mayor de Fase 2. Puede ejecutarse en paralelo con Fase 0 (seguridad) y Fase 1 (resiliencia) porque toca un módulo aislado de [actions/actions.py](actions/actions.py).

#### Diagnóstico del estado actual

El flujo de búsqueda tiene **tres problemas estructurales** identificados al analizar `ActionBuscarFAQ`, `ActionBuscarFaqLibre` y la función PL/SQL `buscar_faq`:

1. **Duplicación de trabajo Python ↔ Oracle**: `ActionBuscarFAQ` envía hasta **4 queries reescritas** al endpoint `faq/buscar/{id}?pregunta=...` para "compensar" lo que la función `buscar_faq` ya hace internamente (normalización 8 pasos + scoring 5 niveles). Cada query es un round-trip de hasta 60s. En el peor caso: **240s antes de fallback**.
2. **Dos acciones desincronizadas** (`ActionBuscarFAQ` ~270 líneas + `ActionBuscarFaqLibre` ~340 líneas) resolviendo el mismo problema con estrategias divergentes: la primera intent-driven con keywords predefinidas; la segunda con un único intento del mensaje crudo. Distintos caches, distinta clasificación de respuestas, distintos mensajes de error.
3. **No hay feedback loop**: las preguntas sin respuesta van a `PREGUNTAS_SIN_RESPUESTA`. Los admins las responden en APEX (`ESTADO='RESPONDIDA'`, `RESPUESTA` completa). Pero **el bot nunca lee esas respuestas curadas**. El conocimiento que el equipo genera se desperdicia hasta que alguien lo migre manualmente a `FAQ`.

**Caso especial — preguntas sin contexto**: si el usuario escribe "¿cuánto cuesta?" sin haber seleccionado programa, el bot lo rechaza con "primero dime sobre qué programa". Esto es una mala experiencia: el contexto está en la conversación previa pero no se usa.

#### Principios de diseño de esta fase

- **Sin downtime**: cambios incrementales, cada sub-fase deployable independientemente con feature flag.
- **Backward compatible**: si el camino nuevo falla, se cae al comportamiento actual (Oracle `buscar_faq`).
- **Medir antes de cambiar**: ninguna mejora sin baseline numérico.
- **Sin dependencias pesadas**: `spacy` ya está cargado (pipeline Rasa), `scikit-learn` transitivo. Solo se agregan `rapidfuzz` (~8 MB) y `rank-bm25` (~10 KB).

---

#### Sub-fase A.1 — Instrumentación y baseline (semana 1, riesgo cero)

> Medir antes de cambiar nada. Sin baseline numérico no se puede demostrar que las mejoras siguientes funcionan.

- [x] **Logging estructurado por búsqueda** (`logger.info` con `extra={...}`):
  - `sender_id` (truncado a 20), `postgrado_id`, `intent`, `confidence`
  - `query_original`, `query_enviada_i` (cada intento)
  - `n_intentos`, `respuesta_encontrada` (bool), `tipo_respuesta` (válida/no_encontrada/error)
  - `duracion_ms_total`, `duracion_ms_api`
  - `fuente`: `oracle | cache | local_faq | local_curadas | fallback`
- [ ] **Tabla `FAQ_BUSQUEDAS`** en Oracle (similar a `HISTORIAL_CONVERSACION`):
  ```sql
  CREATE TABLE FAQ_BUSQUEDAS (
    ID_BUSQUEDA NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    ID_POSTGRADO NUMBER,
    QUERY_ORIGINAL VARCHAR2(1000),
    QUERY_NORMALIZADA VARCHAR2(1000),
    ENCONTRADA VARCHAR2(1),       -- 'S' / 'N'
    NIVEL_SCORING NUMBER,          -- 5-999 si viene de Oracle
    FUENTE VARCHAR2(20),
    DURACION_MS NUMBER,
    FECHA_HORA DATE DEFAULT SYSDATE
  );
  ```
- [ ] **Baseline numérico** (1 semana de observación previa a cualquier cambio):
  - Hit rate global (% queries con respuesta)
  - Tasa de fallback (% que terminan en `PREGUNTAS_SIN_RESPUESTA`)
  - Tiempo p50/p95/p99 de respuesta
  - Top 20 queries fallidas (para curaduría inmediata)
  - Distribución de niveles de scoring (cuántos hits son nivel 2 vs nivel 4 vs nivel 5)

---

#### Sub-fase A.2 — Unificación y reducción de calls (semana 1–2, riesgo bajo)

> Una sola acción, una sola estrategia, menos round-trips.

- [x] **Fusionar `ActionBuscarFAQ` + `ActionBuscarFaqLibre`** en `ActionBuscarFaq` único. Ambos endpoints quedan registrados en `domain.yml` pero apuntan a la misma implementación (compatibilidad).
- [x] **Cache key unificado**:
  ```python
  def _cache_key(postgrado_id: str, texto: str) -> str:
      norm = unicodedata.normalize('NFD', texto.lower())
      norm = ''.join(c for c in norm if unicodedata.category(c) != 'Mn')
      norm = re.sub(r'\s+', ' ', norm).strip()
      return f"faq_{postgrado_id}_{hashlib.sha256(norm.encode()).hexdigest()[:16]}"
  ```
- [x] **Replicar normalización Oracle en Python** (mirror de los pasos 2–7 de `buscar_faq`):
  - TRANSLATE acentos: `ÁÉÍÓÚÜÑ` → `AEIOUUN`
  - Eliminar puntuación `?¿!¡.,;:()""''`
  - Aplicar correcciones ortográficas conocidas (`BIOINGIENERIA` → `BIOINGENIERIA`, etc.)
  - Expandir abreviaturas (`TI`, `SST`, `SIG`, `HSST`)
  - Eliminar stopwords (`QUE`, `EL`, `LA`, `DE`, ...)
  - **Ventaja**: la primera query ya llega normalizada → más probabilidad de hit nivel 1-2 + mejor cache hit rate.
- [x] **Singularización española** (regex, no requiere spacy):
  ```python
  def _singular_es(texto: str) -> str:
      result = []
      for p in texto.split():
          if len(p) > 4 and p.endswith('es') and p[-3] in 'lnsdz':
              result.append(p[:-2])   # "papeles" → "papel"
          elif len(p) > 3 and p.endswith('s') and not p.endswith('ss'):
              result.append(p[:-1])   # "costos" → "costo"
          else:
              result.append(p)
      return ' '.join(result)
  ```
  Cierra el gap real de Oracle: `\bCOSTO\b` no matchea "COSTOS" por la word boundary.
- [x] **Diccionario de sinónimos de dominio** en `actions/synonyms.yaml`:
  ```yaml
  costo:    [precio, valor, plata, cuanto, matricula, tarifa, vale, inversion]
  fecha:    [cuando, plazo, inscripcion, calendario, cronograma]
  modalidad: [virtual, presencial, online, distancia, horario, hibrido]
  requisito: [documento, papel, necesito, exigen, piden]
  inscribir: [registrar, matricular, aplicar, postular]
  ```
  Mantenido por el equipo de contenido, fácil de editar sin tocar código.
- [x] **Máximo 2 API calls** (no 4):
  1. Query normalizada (Oracle ya cubre acentos, stopwords, abreviaturas vía PL/SQL)
  2. Si retorna `NO_ENCONTRADO`: query con singularización + expansión de sinónimos
- [x] **Negative caching**: queries que retornaron `NO_ENCONTRADO` en últimos 5 min no se reintentan ni se registran de nuevo en `PREGUNTAS_SIN_RESPUESTA`. Evita inflar `FRECUENCIA` por reintentos rápidos del mismo usuario.

**Riesgo**: bajo. Comportamiento equivalente o mejor con el mismo backend.

---

#### Sub-fase A.3 — Aprovechar spacy ya cargado (semana 2–3, riesgo bajo)

> `es_core_news_md` ya está en `config.yml` (pipeline NLU). Está cargado en memoria del Rasa Server. El Action Server puede cargar una instancia separada sin costo de descarga.

- [x] **Cargar spacy en el Action Server**:
  ```python
  import spacy
  try:
      nlp = spacy.load("es_core_news_md")
      SPACY_DISPONIBLE = True
  except OSError:
      logger.warning("spacy es_core_news_md no disponible, búsqueda usa fallback regex")
      nlp = None
      SPACY_DISPONIBLE = False
  ```
- [x] **Lemmatización** (cubre plurales + conjugaciones de una vez):
  ```python
  def lematizar(texto: str) -> str:
      if not SPACY_DISPONIBLE: return _singular_es(texto)
      doc = nlp(texto)
      return " ".join(t.lemma_ for t in doc if not t.is_stop and not t.is_punct)
  ```
  - "los requisitos exigidos" → "requisito exigir"
  - "cuánto cuestan las matrículas" → "cuanto costar matrícula"
- [x] **Extracción de términos clave (POS tagging)**:
  ```python
  def extraer_terminos_clave(texto: str) -> str:
      if not SPACY_DISPONIBLE: return texto
      doc = nlp(texto)
      return " ".join(t.lemma_ for t in doc if t.pos_ in ("NOUN", "VERB", "PROPN"))
  ```
  Filtra ruido conversacional ("quisiera", "podría", "me gustaría saber").
- [x] **NER para inferir programa implícito**:
  - "cuesta avalúos" → spacy detecta "Avalúos" → buscar match en programas activos
  - Resuelve preguntas sin contexto explícito (ver A.6).
- [x] **Pipeline escalonado de queries** (max 3 intentos pero el 3º solo si A.4 no resolvió):
  1. Query normalizada (A.2)
  2. Query lematizada
  3. Solo términos clave (NOUN/VERB/PROPN)

---

#### Sub-fase A.4 — Índice local de FAQs (semana 3–4, riesgo medio, IMPACTO ALTO)

> Eliminar el round-trip a Oracle para queries comunes. Respuesta < 100 ms para el 60–80% de los casos.

**Concepto**: pre-cargar todas las FAQs activas al iniciar el Action Server. Matching local primero. Solo consultar Oracle si la confianza local es baja.

- [x] **Pre-fetch al arranque con 1 sola llamada** — `GET /faq` devuelve todas las FAQs de todos los programas activos en una sola request. Agrupar por `ID_POSTGRADO` en Python:
  ```python
  FAQ_INDEX: Dict[str, List[Dict]] = {}   # postgrado_id → lista de FAQs
  BM25_INDEX: Dict[str, Any] = {}          # postgrado_id → BM25Okapi

  def cargar_faq_index() -> None:
      resp = make_api_request("GET", "faq")
      if not resp or resp.get("status") != "success":
          logger.error("No se pudo cargar el índice de FAQs")
          return
      FAQ_INDEX.clear()
      for f in resp.get("data", []):
          pid = str(f.get("ID_POSTGRADO", ""))
          if not pid:
              continue
          FAQ_INDEX.setdefault(pid, []).append({
              "id_faq":        f.get("ID_FAQ"),
              "pregunta_norm": normalizar_query(f.get("PREGUNTA", "")),
              "respuesta":     f.get("RESPUESTA", ""),
              "veces":         f.get("VECES_CONSULTADA", 0),
          })
      for pid, faqs in FAQ_INDEX.items():
          corpus = [f["pregunta_norm"].split() for f in faqs if f["pregunta_norm"]]
          if corpus:
              BM25_INDEX[pid] = BM25Okapi(corpus)
      logger.info(f"Índice FAQ cargado: {sum(len(v) for v in FAQ_INDEX.values())} FAQs en {len(FAQ_INDEX)} programas")
  ```
- [x] **Refresh periódico**: APScheduler cada **10 minutos** (alineado con la escritura inmediata de FAQs desde `PREGUNTAS_SIN_RESPUESTA` respondidas). Variable `FAQ_INDEX_REFRESH_MINUTES=10`.
- [x] **Matching local con `rapidfuzz`** (MIT, mantenido activamente, sin C compiler en runtime):
  ```python
  from rapidfuzz import fuzz
  scores_fuzz = [
      (faq, fuzz.token_set_ratio(query_norm, faq["pregunta_norm"]))
      for faq in FAQ_INDEX.get(postgrado_id, [])
  ]
  ```
- [x] **BM25 como segundo motor** (`rank_bm25`, ~10 KB de código puro Python):
  ```python
  from rank_bm25 import BM25Okapi
  # Pre-computado al cargar el índice
  bm25_por_postgrado[id] = BM25Okapi([f["pregunta_norm"].split() for f in faqs])
  # En cada query:
  scores_bm25 = bm25_por_postgrado[postgrado_id].get_scores(query_norm.split())
  ```
- [x] **Score híbrido**:
  ```python
  score_final = 0.6 * score_fuzz + 0.4 * normalizar_bm25(score_bm25)
  ```
  - `score >= 80` → respuesta local directa (< 50 ms)
  - `60 <= score < 80` → consultar Oracle (puede tener mejor match)
  - `score < 60` → consultar Oracle directamente
- [x] **Tie-break por `VECES_CONSULTADA`**: si 2+ FAQs empatan en score, gana la más popular.
- [x] **Feature flag** `BUSQUEDA_LOCAL_HABILITADA=true|false` en `.env` para poder revertir sin re-deploy.

**Riesgo**: medio. Si el índice queda desactualizado, respuestas obsoletas. Mitigación: refresh agresivo + log de versión del índice + comparar checksum periódico contra Oracle.

---

#### Sub-fase A.5 — Feedback loop con curaduría (semana 4–5, riesgo bajo, IMPACTO MUY ALTO)

> **El loop ya está completo en APEX y es inmediato**: cuando un admin guarda una respuesta en `PREGUNTAS_SIN_RESPUESTA`, esa respuesta se escribe directamente en la tabla `FAQ` con `ACTIVO='S'` en el mismo acto. No hay trigger diferido ni proceso batch. La única latencia es el tiempo que tarda el índice local del bot en refrescarse.

```
Admin guarda respuesta en APEX
        │ (escritura directa, inmediata)
        ▼
    FAQ.ACTIVO = 'S'  ←  disponible para buscar_faq al instante
        │
        │  (único gap: refresh del índice local)
        ▼
FAQ_INDEX local del Action Server (se refresca cada N minutos)
        │
        ▼
Próxima query similar → bot responde correctamente
```

- [x] **No necesita índice separado (`CURADAS_INDEX`)**: `FAQ` ya unifica preguntas originales y curadas. Un solo `FAQ_INDEX` local con refresh frecuente es todo lo necesario.
- [x] **Reducir el intervalo de refresh del índice local** (A.4): de 60 min → **10 min**. Con escritura inmediata en Oracle, 10 min es el único gap real entre "admin responde" y "bot sabe responder".
- [x] **Mantener `registrar_pregunta_sin_respuesta`** sin cambios: sigue siendo el punto de entrada del ciclo. El flujo completo queda:
  ```
  Bot no encuentra → registra en PREGUNTAS_SIN_RESPUESTA (ESTADO='PENDIENTE')
  Admin responde en APEX → escribe directo a FAQ (ACTIVO='S') + ESTADO='RESPONDIDA'
  Máximo 10 min → refresh del índice local
  Siguiente query similar → bot responde
  ```
- [x] **`ID_POSTGRADO` del registro original se preserva**: confirmado — al crear la FAQ desde `PREGUNTAS_SIN_RESPUESTA` el `ID_POSTGRADO` de la pregunta original se mantiene. La búsqueda por programa funciona correctamente con las FAQs curadas.

---

#### Sub-fase A.6 — Preguntas sin contexto (semana 5, riesgo bajo)

> Resolver "¿cuánto cuesta?" sin requerir selección previa de programa.

- [x] **Inferencia de programa desde historial conversacional** (últimos ~10 eventos del tracker):
  ```python
  def inferir_postgrado(tracker) -> Optional[int]:
      # 1. Si hay slot postgrado_id activo, usarlo
      if tracker.get_slot("postgrado_id"): return tracker.get_slot("postgrado_id")
      # 2. Buscar en últimos N mensajes del usuario con spacy NER + matching
      for event in list(tracker.events)[-10:][::-1]:
          if event.get("event") == "user":
              candidato = _matchear_programa_en_texto(event.get("text", ""))
              if candidato: return candidato
      return None
  ```
- [x] **Detección de preguntas universales** (aplicables a todos los programas):
  - Si la query usa keywords genéricas (`requisitos`, `inscripción`, `becas`, `convocatoria`) sin nombre de programa → consultar `GET /faq` (FAQs globales).
  - Mostrar con disclaimer: _"Esta información aplica a todos los programas de postgrado. ¿Sobre cuál te gustaría detalles específicos?"_
- [ ] **Confirmación de inferencia cuando hay ambigüedad**:
  ```
  Bot: "Entiendo que preguntas sobre *Especialización en Avalúos*.
       Su costo es: [respuesta]
       
       ¿Era a este programa al que te referías? (sí/no/otro)"
  ```
  - Si 2+ programas matchean con score similar → mostrar opciones tipo lista.
- [ ] **Tracking del modo inferencia** en log: marcar si la respuesta vino de inferencia para evaluar tasa de acierto.

---

#### Sub-fase A.7 — Quality safeguards y operación (continuo a partir de A.1)

- [ ] **Dashboard de búsqueda** (APEX page o Grafana en Fase 5):
  - Hit rate por postgrado y por intent
  - Tiempo p50/p95 por fuente (`oracle | cache | local`)
  - Top 20 queries fallidas (curaduría prioritaria)
  - Top 20 FAQs más consultadas (validar contenido)
- [x] **Alertas** (stub implementado — integración Prometheus en Fase 5):
  - Hit rate baja > 10 % respecto al baseline
  - Tasa de fallback > 20 % en algún postgrado
  - p95 > 3 s
  - Índice local desactualizado (último refresh > 2 h)
- [ ] **Reporte semanal automático** vía email/Slack al equipo de contenido:
  - Top 10 preguntas sin respuesta (ordenadas por `FRECUENCIA`)
  - Top 10 FAQs más consultadas (`VECES_CONSULTADA`)
  - Programas con mayor tasa de fallback
- [ ] **A/B test mecanismo**: feature flag por sub-fase para revertir sin redeploy si hay regresión.

---

#### Impacto esperado (objetivo cuantitativo)

| Métrica | Antes (estimado) | Después (objetivo) |
|---------|------------------|--------------------|
| Hit rate global | ~60 % | ~85 % |
| Tiempo p50 | ~1500 ms | ~80 ms |
| Tiempo p95 worst case (4 calls) | ~6000 ms | ~1500 ms (1 call) |
| API calls promedio por búsqueda | 1.5 | 0.3 |
| Preguntas resueltas vía curaduría | 0 % | 15–25 % |
| Preguntas sin contexto resueltas | 0 % | 60–70 % |

#### Dependencias nuevas

```diff
# requirements.txt
+ rapidfuzz>=3.5.0,<4.0     # ~8 MB, fuzzy matching ultra-rápido (MIT, mantenido)
+ rank-bm25>=0.2.2          # ~10 KB, BM25 puro Python (Apache-2.0)
# spacy 3.5.4 ya está (pipeline Rasa)
# scikit-learn ya está (dependencia transitiva de Rasa, TfidfVectorizer disponible)
```

#### Orden estricto de implementación

1. **A.1 (instrumentación)** — sin esto no se puede medir nada.
2. **A.2 (unificación)** — habilita el resto del trabajo y ya da mejora medible.
3. **A.3 (spacy)** — mejora calidad sin riesgo de infraestructura.
4. **A.4 (índice local)** — mayor impacto en rendimiento.
5. **A.5 (feedback loop)** — mayor impacto en calidad de respuestas.
6. **A.6 (sin contexto)** — polish final, requiere A.3 (NER).
7. **A.7 (safeguards)** — continuo desde A.1.

#### Criterios de aceptación de Fase A

Antes de declarar Fase A cerrada y avanzar a Fase 2D (refactor estructural):

1. Hit rate global ≥ 80 % medido sobre 2 semanas consecutivas.
2. p95 < 2 s en respuestas de búsqueda.
3. Tasa de fallback < 15 %.
4. Al menos 10 % de queries resueltas vía índice de CURADAS (demuestra que el loop funciona).
5. Reporte semanal en producción durante 4 semanas sin alertas críticas.
6. `actions.py` con la búsqueda unificada en una sola clase + módulos auxiliares.
7. Feature flags todavía operativos (no eliminar hasta tener 1 mes sin necesidad de revert).

### Fase 0 — Seguridad inmediata + higiene (1–2 semanas, riesgo bajo)

> Objetivo: eliminar vulnerabilidades activas sin tocar comportamiento del bot.

**Seguridad — ejecutar primero:**

- [x] **Verificación HMAC en webhook WhatsApp**: agregar validación de `X-Hub-Signature-256` con `hmac.compare_digest()` sobre el body crudo antes del JSON parsing en `whatsapp_adapter.py`.
- [x] **`APEX_SSL_VERIFY=true` como default**: default cambiado a `"true"` en [actions/actions.py](actions/actions.py#L36).
- [ ] **Usuario no-root en Dockerfile**: `RUN useradd -m rasauser` + `USER rasauser`. Verificar paths de escritura de `models/` y logs.
- [ ] **Actualizar a Rasa 3.6.21**: una línea en `requirements.txt`. Incluye fix de bug en `full_retrieval_intent_name`.

**Higiene:**

- [x] **Limpiar comentarios generados por IA, separadores `# ===` y emojis en comentarios/docstrings**. *Hecho en commit `7f8e0f1` (rama `develop`, 2026-05-12).* Aplicado en `actions.py` (2420 → 2256 líneas), `whatsapp_adapter.py` (360 → 325), `fetch_training_data.py` (548 → 515), `start.sh`, `start-whatsapp-adapter.sh` y `config.yml`. **No** se tocaron `logger.*` ni mensajes al usuario — eso queda en el siguiente bullet.
- [x] Reemplazar logs con emojis por mensajes estructurados (`logger.info("...", extra={...})`). *Hecho en actions.py (49 líneas) y whatsapp_adapter.py (12 líneas).*
- [x] Configurar `ruff` + `black` + `isort` con `pyproject.toml`.
- [ ] Pre-commit hooks: ruff, black, detect-secrets, end-of-file-fixer.
- [x] Mover imports a top-level (`re`, `hashlib`, `unicodedata`, `traceback`). *Eliminados 5 import re internos + 1 import traceback interno.*
- [ ] Borrar modelos commiteados: `git rm --cached models/*.tar.gz`.
- [x] Corregir `README.md`: eliminadas referencias a Render, documentado despliegue real en Oracle Cloud, tmux, ngrok y Docker.
- [ ] Documentar formalmente `FORCE_IPV4` como variable pendiente de implementar.
- [ ] Documentar CVE-2024-3660 como riesgo aceptado en este archivo.

### Fase 1 — Resiliencia operativa (2–3 semanas, riesgo medio)

> Objetivo: que el bot sobreviva reinicios y caídas parciales de APEX.

- [ ] **Retries con backoff exponencial** en `make_api_request` usando `tenacity` (3 intentos, 1s/2s/4s). Cambio de ~15 líneas con impacto inmediato.
- [ ] **Tracker store persistente**: configurar `SQLTrackerStore` en `endpoints.yml` usando Oracle DB (ya disponible en Oracle Cloud, dialect `oracle` + `cx_Oracle`). **No añadir PostgreSQL como nueva dependencia de infraestructura.** Advertencia: no usar el mismo Redis como lock-store y tracker-store (bug conocido de Rasa).
- [ ] **Rate limiting** con `flask-limiter` en `whatsapp_adapter.py` (60 req/min por número).
- [ ] **Healthchecks** en `dockerfile` (`HEALTHCHECK CMD curl -f http://localhost:5005/status`).
- [ ] **Multi-stage Dockerfile**: builder con compiladores, runtime slim sin ellos.
- [ ] **Lock determinístico** con `pip-tools` (`requirements.in` → hashes).
- [ ] **Pipeline CI completo**: ruff → black → pytest → rasa data validate → build + Trivy.
- [ ] **Logging estructurado JSON** con `structlog`; campos: `sender_id`, `intent`, `confidence`, `action`, `duration_ms`.
- [ ] Mover credenciales a GitHub Secrets / Oracle Vault.

### Fase 2 — Correcciones y refactor de `actions.py` (2–3 semanas, riesgo medio)

> Objetivo: corregir bugs activos, eliminar código muerto y separar responsabilidades.
> Hacer después de Fase 1 (tracker store + retries estables). Sub-fases en orden estricto.

#### Sub-fase 2A — Bugs activos (corregir antes de cualquier otra cosa)

Estos ítems tienen impacto en producción ahora mismo.

**Bug 1 — `APEX_SSL_VERIFY` default inseguro** ([actions/actions.py:49](actions/actions.py#L49))
```python
# ACTUAL (inseguro): si la variable no está seteada, SSL queda desactivado
APEX_SSL_VERIFY = os.getenv("APEX_SSL_VERIFY", "false").lower() != "false"

# CORRECTO:
APEX_SSL_VERIFY = os.getenv("APEX_SSL_VERIFY", "true").lower() != "false"
```
- [x] Cambiar el default de `"false"` a `"true"` — aplicado en [actions/actions.py:36](actions/actions.py#L36).

**Bug 2 — `usuario_telefono` truncado a 15 chars siendo VARCHAR2(50)** ([actions/actions.py:208](actions/actions.py#L208))
```python
# ACTUAL (incorrecto — el DDL real es VARCHAR2(50), no VARCHAR2(15)):
'usuario_telefono': usuario_telefono[:15] if usuario_telefono else None
# CORRECTO:
'usuario_telefono': usuario_telefono[:50] if usuario_telefono else None
```
- [x] Corregir truncado `[:15]` → `[:50]` y comentario `VARCHAR2(15)` → `VARCHAR2(50)` en `registrar_pregunta_sin_respuesta`.

**Bug 3 — `ActionSeleccionarNumero` no guarda `postgrado_correo`** ([actions/actions.py:596–617](actions/actions.py#L596))

`ActionSeleccionarPostgrado._seleccionar_postgrado` guarda `SlotSet("postgrado_correo", correo)` (línea 532), pero `ActionSeleccionarNumero.run()` construye el mismo flujo a mano (líneas 596-617) sin setear `postgrado_correo`. Si el usuario selecciona por número, `ActionEnviarDatosContacto` recibe el slot vacío y el mensaje al asesor no incluye el correo del programa.
- [ ] Extraer `_seleccionar_postgrado` de `ActionSeleccionarPostgrado` a una función de módulo y reutilizarla en `ActionSeleccionarNumero`.

**Bug 4 — `ActionObtenerInfoEspecifica` consulta columnas que no existen en `POSTGRADOS`** ([actions/actions.py:1683–1688](actions/actions.py#L1683))
```python
# Estas columnas NO existen en la tabla POSTGRADOS (ver DDL en sección 7):
costo     = info.get('COSTO', ...)      # ← no existe
duracion  = info.get('DURACION', ...)   # ← no existe
modalidad = info.get('MODALIDAD', ...)  # ← no existe
requisitos = info.get('REQUISITOS', ...) # ← no existe
fechas    = info.get('FECHAS', ...)     # ← no existe
# POSTGRADOS solo tiene: ID_POSTGRADO, NOMBRE, FACULTAD, CORREO_ELECTRONICO, DESCRIPCION, ESTADO
```
La acción siempre cae en el branch de "información general" — código parcialmente muerto.
- [ ] Evaluar si la acción debe redirigir a `faq/buscar/{id}` en lugar de consultar `postgrados/{id}` para esos campos. Mientras tanto, eliminar las ramas `elif` que referencian columnas inexistentes.

#### Sub-fase 2B — Higiene específica de `actions.py`

- [ ] **CHANGELOG en el código** (líneas 26-38): eliminar el bloque `# CHANGELOG DE CORRECCIONES (v1.1)` — ese contexto pertenece al historial de git, no al código.
- [ ] **Imports dentro de funciones**: mover al top-level del módulo:
  - `import unicodedata` (dentro de `normalizar_texto`, línea 228)
  - `import hashlib` (dentro de `ActionBuscarFaqLibre.run()`, línea 1753)
  - `import traceback` (dentro del `except` de `make_api_request`, línea 188)
  - Los `import re` en líneas 401, 558, 1501, 1527 son redundantes (ya existe en la línea 18 top-level) — eliminarlos.
- [ ] **Separadores `# ===`**: quedaron pendientes del merge de `develop`. Re-aplicar limpieza o hacer merge de `develop` → `main`.
- [ ] **Emails y teléfonos hardcodeados** en mensajes de error de `ActionEnviarDatosContacto` (líneas 1622, 1630): usar el slot `postgrado_correo` o una variable de entorno `CONTACTO_FALLBACK_EMAIL`.

#### Sub-fase 2C — Código duplicado a eliminar

- [ ] **Fetch de postgrados repetido 4 veces** (líneas 291, 385, 574, 2365): extraer a función de módulo `_obtener_postgrados() -> List[Dict]` que encapsula el patrón `cache → API → set_cache`.
- [ ] **`ActionSeleccionarPostgrado` debe usar `POST /buscar`** en lugar de descargar todos los programas y filtrar en Python. El endpoint hace el `UPPER(nombre) LIKE '%texto%'` en Oracle directamente. Solo usar `GET /postgrados` completo para listar todos (sin búsqueda por nombre).
- [ ] **`_extraer_respuesta` duplicada**: `ActionBuscarFAQ._extraer_respuesta` (línea 797) y `ActionBuscarFaqLibre._extraer_respuesta_apex` (línea 1965) hacen lo mismo con distinta implementación. Unificar en función de módulo `extraer_respuesta_apex(response: Dict) -> Optional[str]`.
- [ ] **Keywords duplicadas**: `ActionBuscarFAQ.INTENT_KEYWORDS` (línea 630) y `ActionDefaultFallback._detectar_categoria_faq` (línea 1159) mapean intents/categorías a keywords de forma separada e inconsistente. Unificar en `actions/intents.yaml` como planificado en la Fase 2 original.
- [ ] **`ActionValidarEmail` redundante** (líneas 2133-2165): duplica exactamente la validación ya implementada en `ValidateDatosContactoForm.validate_email` (línea 1493). Evaluar eliminar la clase entera si no está referenciada en `domain.yml`/`rules.yml`.

#### Sub-fase 2D — Refactor de estructura (riesgo mayor, después de 2A-2C)

- [ ] Dividir en módulos: `apex_client.py` (HTTP + caché), `utils/text.py` (`normalizar_texto`, `extraer_respuesta_apex`), handlers por dominio (`faq_actions.py`, `contact_actions.py`, `navigation_actions.py`).
- [ ] `actions/config.py` con `pydantic-settings` para todas las variables de entorno del action server.
- [ ] Normalizar campos UPPER/lower de Oracle en el cliente APEX (no en cada handler): una sola función `normalizar_campos_oracle(data: Dict) -> Dict`.
- [ ] Tests unitarios con `pytest` — cobertura mínima 60% antes de declarar fase completa.

### Fase 3 — Analítica mínima viable (1–2 semanas, riesgo bajo)

> Objetivo: tener datos reales del NLU antes de tomar decisiones sobre el RAG.

- [ ] **Tabla `rasa_predictions`** en Oracle: `sender_id, intent, confidence, mensaje, timestamp, fallback`.
- [ ] **Reporte semanal automático** de tasa de fallback por intent. Alerta si supera 15% en algún intent.
- [ ] Re-evaluar umbral de `FallbackClassifier` (actualmente 0.65) con datos reales.
- [ ] OpenTelemetry + Prometheus + Grafana pospuesto a Fase 5.

### Fase 4 — RAG semántico sobre FAQs (3–4 semanas, riesgo medio-alto)

> Solo lanzar si los datos de Fase 3 confirman preguntas frecuentes sin cobertura NLU.

- [ ] Embeddings con `paraphrase-multilingual-MiniLM-L12-v2`.
- [ ] Vector store: Oracle Database 23c tiene soporte nativo de vectores (`VECTOR` datatype). Para versiones anteriores, usar FAISS en memoria en el Action Server (no añadir pgvector como dependencia).
- [ ] Pipeline RAG en `action_buscar_faq_libre` con umbral coseno ≥ 0.7.
- [ ] LLM opcional para similitud 0.5–0.7 con guardrails estrictos.
- [ ] Nunca permitir que el LLM invente costos, fechas o requisitos.

### Fase 5 — Observabilidad completa + multi-canal (3–4 semanas)

> Fusión de Fases 3 y 5 originales.

- [ ] OpenTelemetry + Prometheus + Grafana (SLOs: p95 < 1.5s, error rate < 2%).
- [ ] `BaseAdapter` + `adapters/whatsapp/`, `adapters/telegram/`.
- [ ] Mensajes ricos WhatsApp (button/list templates).
- [ ] Encuesta post-conversación + A/B testing de saludos.

### Fase 6 — Estrategia de stack (6+ meses, decisión estratégica)

> Tomar decisión solo cuando haya datos de Fases 3–4.

- Rasa OSS 3.6.21 es la versión final. No hay más releases.
- **Python 3.11 NO es compatible con Rasa 3.6** (`Requires: Python <3.11, >=3.8`). No intentar.
- Opciones: mantener Rasa 3.6 | migrar a Rasa Pro CALM (licencia comercial) | reescribir con LangGraph | híbrido RAG paralelo.
- Recomendación: evaluar después de medir impacto real de Fase 4.

---

## 12. Criterios de aceptación globales

Antes de cerrar cualquier fase:

1. Todos los tests pasan en CI (unitarios + `rasa data validate` + `rasa test nlu` mínimo).
2. La cobertura de tests no baja respecto a la rama `main`.
3. `ruff check` y `black --check` pasan sin advertencias.
4. `rasa shell` arranca localmente sin errores y responde a 5 mensajes golden-path.
5. La imagen Docker construye y el contenedor responde a `/status` en menos de 10 minutos.
6. El adaptador WhatsApp responde en `curl http://localhost:5006/health` (puerto Docker expuesto).
7. Las métricas Prometheus (a partir de Fase 5) reportan datos en local.
8. Documentación actualizada en `README.md` y este `CLAUDE.md`.

---

## 13. Convenciones de trabajo con Claude Code en este repo

- **Idioma**: comentarios, commits y documentación en español. Identificadores y nombres de clases/funciones en español (el código actual ya lo está).
- **No introducir cambios fuera del alcance** del PR: si se detecta un bug colateral, registrar issue.
- **Antes de tocar `domain.yml`**: confirmar que el cambio se refleja en `actions.py`, `rules.yml`, `stories.yml` y `nlu.yml`.
- **Nunca editar a mano** `data/nlu_dynamic.yml` ni `data/stories_dynamic.yml` (los regenera `fetch_training_data.py`).
- **Cambios al pipeline NLU** requieren documentar el motivo en el commit y correr `rasa test nlu --cross-validation`.
- **Mensajes al usuario**: español neutro, sin emojis excesivos; un mensaje por turno cuando sea posible.
- **Validación de entradas externas**: cualquier dato de Oracle APEX se considera no-confiable hasta normalizar (mayúsculas/minúsculas, `null`, listas anidadas).
- **Cambios en `whatsapp_adapter.py`** se redesplegan con CI igual que el resto del código.

---

## 14. Estructura del repositorio (snapshot actual)

```
chatbot-postgrados-ud/
├── .github/workflows/         # deploy-oracle.yml (CI/CD)
├── actions/
│   ├── __init__.py
│   └── actions.py             # 2256 líneas — refactor pendiente (Fase 2)
├── data/
│   ├── nlu.yml                # ejemplos estáticos
│   ├── rules.yml              # reglas duras
│   ├── stories.yml            # flujos
│   ├── nlu_dynamic.yml        # (generado, gitignored)
│   └── stories_dynamic.yml    # (generado, gitignored)
├── models/                    # *.tar.gz (gitignored; limpiar history)
├── tests/
│   └── test_stories.yml       # 10 stories de smoke
├── config.yml
├── credentials.yml
├── domain.yml
├── endpoints.yml
├── dockerfile
├── fetch_training_data.py
├── requirements.txt
├── start.sh
├── start-whatsapp-adapter.sh
├── whatsapp_adapter.py
└── .env / .env.example
```

---

## 15. Referencias útiles

- Rasa Open Source 3.6 docs: https://rasa.com/docs/rasa/3.x/
- Rasa SDK custom actions: https://rasa.com/docs/rasa/3.x/custom-actions
- Rasa tracker stores: https://legacy-docs-oss.rasa.com/docs/rasa/tracker-stores/
- Meta WhatsApp Cloud API: https://developers.facebook.com/docs/whatsapp/cloud-api
- WhatsApp webhook signature (HMAC): https://developers.facebook.com/docs/graph-api/webhooks/getting-started#verification-requests
- Oracle APEX ORDS: https://docs.oracle.com/en/database/oracle/oracle-rest-data-services/
- Oracle Vector DB (23c): https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/
- pgvector (alternativa si no Oracle 23c): https://github.com/pgvector/pgvector
- OpenTelemetry Python: https://opentelemetry.io/docs/instrumentation/python/
- CVE-2024-3660 (TF/Keras, riesgo aceptado): https://github.com/advisories/GHSA-x4wf-678h-2pmq

---

## 16. Bitácora de cambios documentados

Resumen de cambios significativos al proyecto que conviene tener visibles para Claude Code en futuras sesiones (complementa al historial de git, no lo reemplaza).

### 2026-05-12 — Reestructuración inicial (`develop` / commit `7f8e0f1`)

**Mensaje del commit (público):** `chore: Reestructuración del proyecto`.

**Lo que realmente se hizo en esta sesión:**

1. **Reescritura completa de este `CLAUDE.md` en español** con:
   - Visión general + arquitectura + mapa de puertos.
   - Despliegue real en Oracle Cloud (IP, SSH, Docker, tmux).
   - Diagnóstico de riesgos (seguridad, CVE-2024-3660, dependencias).
   - Plan de mejoramiento por fases (0–6).
   - Convenciones, criterios de aceptación y referencias.
2. **Limpieza de comentarios generados por IA** (alcance estricto: solo `#` y docstrings):
   - `actions/actions.py`: 2420 → 2256 líneas (−164).
   - `whatsapp_adapter.py`: 360 → 325 líneas (−35).
   - `fetch_training_data.py`: 548 → 515 líneas (−33).
   - `start.sh`, `start-whatsapp-adapter.sh`, `config.yml`: limpieza puntual.
   - Eliminados: bloque CHANGELOG, marcadores `# ✅ FIX-N`, `# UN SOLO MENSAJE`, `# NUEVA ESTRATEGIA`, `# ✅ MAPEO`, sufijos `OPTIMIZADA/MEJORADA/HÍBRIDA`, separadores `# ============` y emojis dentro de comentarios y docstrings.
   - **NO se modificaron**: `logger.*` (incluyen emojis), `dispatcher.utter_message(...)` (mensajes al usuario), `domain.yml.responses`, ni código funcional.
3. **Validación**: `py_compile` OK en los 3 `.py`, `bash -n` OK en los scripts.
4. **Git**: commit en `develop` fast-forward (5 commits incluyendo los previos de `main`), pusheado a `origin/develop`. `main` quedó intacto en `origin/main`.

### 2026-05-13 — Fase A creada: Estabilización y mejora exponencial de búsqueda FAQ

**Contexto**: producto ya en producción. La búsqueda FAQ es el corazón del bot — debe estabilizarse antes de refactors mayores.

**Plan documentado (7 sub-fases, 5–6 semanas)**:

1. **A.1 — Instrumentación** (semana 1): logging estructurado + tabla `FAQ_BUSQUEDAS` en Oracle + baseline numérico.
2. **A.2 — Unificación** (semana 1–2): fusionar `ActionBuscarFAQ` + `ActionBuscarFaqLibre`. Replicar normalización Oracle en Python. Singularización + diccionario de sinónimos en YAML. Max 2 API calls. Negative caching.
3. **A.3 — Spacy power-up** (semana 2–3): lemmatización, POS tagging, NER usando `es_core_news_md` ya cargado por el pipeline Rasa.
4. **A.4 — Índice local** (semana 3–4): pre-fetch FAQs por postgrado, búsqueda local con `rapidfuzz` + `rank-bm25` (sin embeddings). Solo Oracle si confianza local < 65. Impacto esperado: p50 1500ms → 80ms.
5. **A.5 — Feedback loop** (semana 4–5): aprovechar `PREGUNTAS_SIN_RESPUESTA` con `ESTADO='RESPONDIDA'` como segundo índice local. Cada curaduría del admin se vuelve respuesta automática.
6. **A.6 — Preguntas sin contexto** (semana 5): inferir programa desde historial conversacional con NER, FAQs globales para preguntas universales, confirmación cuando hay ambigüedad.
7. **A.7 — Quality safeguards** (continuo): dashboard, alertas, reporte semanal a curadores.

**Hallazgos clave del análisis**:
- Python y Oracle **duplican trabajo**: `ActionBuscarFAQ` envía hasta 4 queries reescritas para algo que `buscar_faq` ya hace internamente. Worst case: 240 s de espera.
- **Loop de curaduría ya funciona en APEX**: al responder una pregunta en `PREGUNTAS_SIN_RESPUESTA`, APEX la agrega automáticamente a `FAQ`. El problema no es el loop sino el tiempo de propagación al índice local del bot (hasta 60 min con el refresh actual). Reducir a 15 min cierra el gap.
- **`es_core_news_md` ya está en memoria** por el pipeline NLU → spacy es de costo cero adicional.
- **Sin embeddings necesarios**: TF-IDF + BM25 + fuzzy matching local resuelven el 80 % del problema sin transformer ni GPU (RAG queda como Fase 4 si los datos lo justifican).

**Dependencias nuevas mínimas**: `rapidfuzz` (~8 MB) y `rank-bm25` (~10 KB). spacy y scikit-learn ya disponibles.

**Métricas objetivo**:
- Hit rate: 60 % → 85 %
- p50: 1500 ms → 80 ms
- Preguntas sin contexto resueltas: 0 % → 60–70 %

**Prioridad**: Fase A puede correr en paralelo con Fase 0 (seguridad) y Fase 1 (resiliencia) porque toca código aislado. Debe preceder a Fase 2D (refactor estructural).

### 2026-05-13 — Análisis completo de `actions.py` y Fase 2 reescrita

**Lo que se analizó y documentó:**

1. **Bug 1** — `APEX_SSL_VERIFY` default `"false"` (línea 49): si la variable de entorno no está seteada, SSL queda desactivado. Corrección: cambiar default a `"true"`.
2. **Bug 2** — `usuario_telefono[:15]` en `registrar_pregunta_sin_respuesta` (línea 208): DDL real es VARCHAR2(50), no 15. El truncado corta números internacionales innecesariamente.
3. **Bug 3** — `ActionSeleccionarNumero` no guarda el slot `postgrado_correo` (línea 596-617): si el usuario selecciona por número en vez de por nombre, `ActionEnviarDatosContacto` envía el correo del programa vacío al asesor.
4. **Bug 4** — `ActionObtenerInfoEspecifica` consulta columnas `COSTO`, `DURACION`, `MODALIDAD`, `REQUISITOS`, `FECHAS` en la tabla `POSTGRADOS` (líneas 1683-1688), pero esas columnas no existen en el DDL real. La acción siempre cae al branch de "información general" — código parcialmente muerto.
5. **Higiene**: CHANGELOG en código (líneas 26-38), imports dentro de funciones (`unicodedata`, `hashlib`, `traceback`), emails/teléfonos hardcodeados en mensajes de error.
6. **Duplicaciones**: fetch de postgrados ×4, `_extraer_respuesta` ×2 con distinta implementación, keywords en `INTENT_KEYWORDS` y `_detectar_categoria_faq` inconsistentes, `ActionValidarEmail` duplica `ValidateDatosContactoForm.validate_email`.
7. **Fase 2 reescrita** en CLAUDE.md con sub-fases A-D ordenadas por riesgo.

### 2026-05-13 — Esquema real de Oracle y corrección de documentación

**Lo que se documentó en esta sesión:**

1. **DDL completo de las 6 tablas** incorporado a sección 7: `POSTGRADOS`, `FAQ`, `HISTORIAL_CONVERSACION`, `HISTORIAL_CONVERSACION_ARCHIVO`, `PREGUNTAS_SIN_RESPUESTA`, `LOG_MODIFICACION_FAQ`.
2. **Corrección de error existente**: `PREGUNTAS_SIN_RESPUESTA.USUARIO_TELEFONO` documentado como `VARCHAR2(15)` — el DDL real es `VARCHAR2(50)`. Corregido.
3. **Tabla `HISTORIAL_CONVERSACION_ARCHIVO`** documentada por primera vez: tabla de archivo sin PK ni constraints, misma estructura que HISTORIAL_CONVERSACION.
4. **Función `buscar_faq`** documentada en detalle: pipeline de 8 pasos de normalización, scoring de 5 niveles con tabla de prioridades, efecto secundario en `VECES_CONSULTADA`, casos de retorno sin resultado.
5. **Swagger URL confirmada**: `https://oracleapex.com/ords/udchatbot/open-api-catalog/chatbot/`

### 2026-05-13 — Documentación de ngrok y flujo tmux completo

**Lo que se documentó en esta sesión:**

1. **Arquitectura real del canal WhatsApp** clarificada: ngrok corre en el mismo servidor Oracle Cloud (no en local) como solución de HTTPS provisional al no tener SSL nativo.
2. **Sección 3 reescrita** con el paso a paso completo de las dos sesiones tmux:
   - Sesión `rasa`: `start-whatsapp-adapter.sh` (Action Server + Rasa Server + WhatsApp Adapter).
   - Sesión `ngrok`: `ngrok http 5006` con URL `https://xxx.ngrok-free.dev`.
3. **Riesgo añadido en sección 9**: URL dinámica de ngrok Free como punto de falla operativo del canal WhatsApp.
4. Cuenta de ngrok confirmada: `jeyle222@gmail.com` (Plan Free), versión 3.33.0.

**Pendientes inmediatos (resto de Fase 0):**

- Reemplazar logs con emojis por logging estructurado.
- `ruff` + `black` + `isort` + pre-commit hooks.
- Mover imports dentro-de-función al top-level (`re`, `hashlib`, `unicodedata`).
- `git rm --cached models/*.tar.gz`.
- Reescribir `README.md` (referencias a Render son obsoletas).
- Verificación HMAC en webhook WhatsApp.
- `APEX_SSL_VERIFY=true` como default.
- Usuario no-root en Dockerfile.

---

### 2026-05-13 — Implementación Fase A + correcciones Fase 0 y Fase 2A

**Tareas ejecutadas en esta sesión:**

#### Bug 2 — `usuario_telefono` truncado (Fase 2A confirmado)
- [actions/actions.py](actions/actions.py): línea `registrar_pregunta_sin_respuesta` — `[:15]` → `[:50]`, comentario `VARCHAR2(15)` → `VARCHAR2(50)`.

#### Seguridad HMAC — webhook WhatsApp (Fase 0)
- [whatsapp_adapter.py](whatsapp_adapter.py): añadidos `import hmac`, `import hashlib` al top-level. Variable `WHATSAPP_APP_SECRET` leída desde env. Función `_verificar_firma_hmac()` con `hmac.compare_digest()`. Verificación aplicada al POST `/webhooks/whatsapp/webhook` antes de `get_json()`. Si `WHATSAPP_APP_SECRET` no está configurado → warning + pass-through (no rompe producción).

#### Fase A — Estabilización búsqueda FAQ

**Infraestructura nueva en [actions/actions.py](actions/actions.py) (módulo-level):**
- `normalizar_query()`: espejo de los 7 pasos del PL/SQL `buscar_faq` (acentos, puntuación, correcciones ortográficas, abreviaturas, stopwords).
- `_singular_es()`: singularización española via regex para cerrar gap de plurales con Oracle.
- `_expandir_sinonimos()`: expansión desde `actions/synonyms.yaml`.
- `_cache_key_faq()`: cache key con SHA-256(16 chars) sobre texto normalizado.
- `lematizar()` y `extraer_terminos_clave()`: spaCy `es_core_news_md` con fallback regex. Flag `SPACY_DISPONIBLE`.
- `cargar_faq_index()`: pre-fetch de `GET /faq` (1 sola llamada) → `_FAQ_INDEX` + `_BM25_INDEX`. Llamada al arranque.
- `_buscar_en_indice_local()`: rapidfuzz + BM25 con score híbrido (0.6/0.4). Umbral ≥80 → local directo.
- `inferir_postgrado()`: slot activo → historial conversacional (últimos 10 eventos) → NER spaCy.
- `enviar_alerta_metrica()`: stub con `logger.warning` + `extra={}` (Prometheus en Fase 5).
- `_iniciar_scheduler_faq()`: APScheduler refresh cada `FAQ_INDEX_REFRESH_MINUTES` minutos (default 10).
- `_NEGATIVE_CACHE`: dict en memoria, TTL 5 minutos, evita reintentos de queries fallidas.

**Clase unificada `ActionBuscarFaq`** (reemplaza `ActionBuscarFAQ` + `ActionBuscarFaqLibre`):
- Pipeline: negative cache → cache positivo → índice local → Oracle intento 1 (query normalizada) → Oracle intento 2 (singular + sinónimos). Máx 2 API calls.
- A.1 logging estructurado: campos `sender_id`, `postgrado_id`, `intent`, `confidence`, `n_intentos`, `respuesta_encontrada`, `tipo_respuesta`, `duracion_ms_total`, `fuente`.
- A.6: preguntas universales → `GET /faq` con disclaimer. `inferir_postgrado()` antes de pedir contexto.
- Truncado CLOB a 3800 chars (límite WhatsApp).
- `ActionBuscarFAQ` y `ActionBuscarFaqLibre`: aliases de compatibilidad, no tocar `domain.yml` aún.
- `ActionBuscarFaqLibre` incluye comentario de bloque con el flujo completo del feedback loop (A.5).

**Archivo nuevo `actions/synonyms.yaml`**: 9 grupos de sinónimos de dominio editables sin tocar código.

#### Higiene Fase 0 (TAREA 4)
- **CHANGELOG eliminado** de `actions.py` (líneas 24-38 del original).
- **`APEX_SSL_VERIFY` default** corregido de `"false"` a `"true"` en [actions/actions.py](actions/actions.py).
- **Imports top-level**: `unicodedata`, `hashlib`, `traceback`, `yaml`, `pathlib.Path` añadidos al header. Eliminados 5 `import re` redundantes dentro de funciones y 1 `import traceback` dentro de `except`.
- **Logs sin emojis**: 49 líneas en `actions.py`, 12 en `whatsapp_adapter.py`. Emojis eliminados del prefijo de mensajes `logger.*`. Mensajes al usuario (`dispatcher.utter_message`) sin cambios.
- **`pyproject.toml`** creado con configuración de `ruff` (line-length 100, py310) y `black`.
- **`.env.example`** reescrito con todas las variables del proyecto incluyendo las nuevas de Fase A.

**Feature flags nuevos en `.env.example`:**
- `BUSQUEDA_LOCAL_HABILITADA=true` — habilita índice local + rapidfuzz/BM25.
- `FAQ_INDEX_REFRESH_MINUTES=10` — intervalo de refresh del índice.
- `FAQ_HIT_RATE_ALERT_THRESHOLD=0.70`
- `FAQ_FALLBACK_RATE_THRESHOLD=0.20`
- `FAQ_P95_MS_THRESHOLD=3000`

**Dependencias añadidas a `requirements.txt`:**
- `rapidfuzz>=3.5.0,<4.0`
- `rank-bm25>=0.2.2`

**Bugs colaterales detectados (NO corregidos en esta sesión — registrar como issues):**
- Bug 3: `ActionSeleccionarNumero` no guarda `postgrado_correo` (sigue pendiente Fase 2A).
- Bug 4: `ActionObtenerInfoEspecifica` consulta columnas inexistentes en `POSTGRADOS` (sigue pendiente Fase 2A).
- `ActionDefaultFallback._deberia_usar_faq_libre()` sigue redirigiendo a `action_buscar_faq_libre` por nombre — funciona porque es alias, pero el routing interno podría simplificarse en Fase 2D.

**Pendientes de esta sesión que quedaron fuera del alcance:**
- Tabla `FAQ_BUSQUEDAS` en Oracle para baseline numérico (requiere DDL en APEX — fuera del alcance del código Python).
- Pre-commit hooks (`detect-secrets`, `end-of-file-fixer`).
- `git rm --cached models/*.tar.gz`.
- Usuario no-root en Dockerfile.
- Actualizar `requirements.txt` a `rasa==3.6.21`.

---

### 2026-05-13 — Mensajes de inactividad + README + conflicto de merge

**Cambios:**

1. **Mensajes de inactividad reescritos** en [whatsapp_adapter.py](whatsapp_adapter.py) para alinearse con el tono del bot (`ActionDespedida`):
   - Timeout: `"👋 ¡Hasta pronto!\n\nTu sesión se cerró por inactividad.\n\nCuando quieras, escribe *hola* y seguimos. 🎓"`
   - Advertencia: `"¿Sigues ahí? 😊\n\nSi no hay actividad en {tiempo_str} cierro la sesión.\n\nEscribe cualquier cosa para continuar."` — `tiempo_str` muestra `"1 min"` o `"45 seg"` según corresponda.

2. **Conflicto de merge resuelto** en `whatsapp_adapter.py` (marcadores `<<<<<<`/`>>>>>>` del stash). Se mantuvo la función `_verificar_firma_hmac()` de la sesión anterior.

3. **`README.md` reescrito** — eliminadas todas las referencias a Render (`render.yaml`, `https://tu-app.onrender.com`, sección "Deploy en Render"). Documentado el despliegue real: Oracle Cloud, Docker, tmux, ngrok, CI/CD con SSH. Tabla de variables de entorno actualizada con las nuevas de Fase A.

4. **`CLAUDE.md` actualizado**: tabla de riesgos de seguridad (sección 9) marcada con estado "Resuelto" para HMAC y `APEX_SSL_VERIFY`. Checkbox `README.md` marcado `[x]`.