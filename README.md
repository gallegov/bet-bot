# 🤖 Bot de Contabilidad de Apuestas

Bot de Telegram que registra apuestas automáticamente desde capturas de pantalla,
las guarda en Google Sheets y comprueba los resultados vía APIs deportivas.

---

## Características

- 📸 **Registro automático** — manda una captura y Claude extrae todos los datos
- 📊 **Google Sheets** — contabilidad en tiempo real accesible desde móvil
- ⚽🏀🎾 **Fútbol, Baloncesto y Tenis** — resultados automáticos vía API
- /actualizar — resuelve todas las apuestas pendientes de golpe
- /stats — resumen con ROI, % acierto y beneficio neto

---

## Estructura del proyecto

```
bet-bot/
├── bot.py                  # Punto de entrada
├── setup_sheets.py         # Inicializa Google Sheets (ejecutar 1 vez)
├── requirements.txt
├── .env.example            # Copia a .env y rellena tus keys
├── config/
│   └── settings.py         # Variables de configuración
├── handlers/
│   ├── bet_handler.py      # Recibe y procesa capturas
│   ├── update_handler.py   # Comando /actualizar
│   └── stats_handler.py    # Comando /stats
└── services/
    ├── vision_service.py   # Claude Vision → extrae datos de imagen
    ├── sheets_service.py   # Lee/escribe en Google Sheets
    ├── sports_service.py   # Consulta APIs deportivas
    └── resolver_service.py # Decide si la apuesta ganó o perdió
```

---

## Instalación paso a paso

### 1. Python y dependencias

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Bot de Telegram

1. Abre Telegram y busca **@BotFather**
2. Escribe `/newbot` y sigue las instrucciones
3. Copia el token que te da (formato: `123456789:ABCdef...`)

### 3. Anthropic API (Claude Vision)

1. Regístrate en https://console.anthropic.com
2. Ve a **API Keys** → **Create Key**
3. Copia la key (empieza por `sk-ant-`)

> 💡 Coste estimado: ~0.003€ por captura analizada. Para 50 apuestas/mes → < 0.20€

### 4. Google Sheets

**Paso A: Crear proyecto en Google Cloud**
1. Ve a https://console.cloud.google.com
2. Crea un proyecto nuevo (ej: "bot-apuestas")
3. Activa las APIs:
   - Busca "Google Sheets API" → Habilitar
   - Busca "Google Drive API" → Habilitar

**Paso B: Crear cuenta de servicio**
1. Ve a IAM y administración → Cuentas de servicio
2. Crear cuenta de servicio → Dale un nombre
3. En "Claves" → Agregar clave → JSON → descarga el archivo
4. Renómbralo a `credentials.json` y ponlo en la carpeta del bot

**Paso C: Crear y compartir el Sheet**
1. Crea un Google Sheets vacío
2. Copia su ID de la URL: `docs.google.com/spreadsheets/d/**ID_AQUI**/edit`
3. Abre el archivo `credentials.json` y copia el valor de `client_email`
4. En el Google Sheet → Compartir → pega ese email → Editor

### 5. API deportiva (api-sports.io)

1. Regístrate en https://rapidapi.com
2. Suscríbete a **API-Football** (plan gratuito: 100 llamadas/día)
3. El mismo key sirve para baloncesto y tenis (misma plataforma)
4. Copia tu API Key desde el dashboard de RapidAPI

### 6. Configurar variables de entorno

```bash
cp .env.example .env
# Edita .env con tus datos reales
```

### 7. Inicializar Google Sheets

```bash
python setup_sheets.py
```

Esto crea las hojas "Apuestas" y "Resumen" con cabeceras y fórmulas automáticas.

### 8. Arrancar el bot

```bash
python bot.py
```

---

## Uso

| Acción | Cómo |
|---|---|
| Registrar apuesta | Envía foto/captura al bot |
| Comprobar resultados | Escribe `/actualizar` |
| Ver estadísticas | Escribe `/stats` |
| Ayuda | Escribe `/help` |

---

## Despliegue en servidor (opcional)

Para que el bot funcione 24/7 sin tener el PC encendido:

**Railway.app** (gratis):
1. Crea cuenta en https://railway.app
2. Conecta tu repositorio de GitHub
3. Añade las variables de entorno en el panel
4. El bot se despliega automáticamente

---

## Estructura del Google Sheet

### Hoja "Apuestas"
| ID | Fecha | Casa | Deporte | Evento | Fecha partido | Tipo | Descripción | Cuota | Importe | Estado | Resultado | Beneficio | Notas |

### Hoja "Resumen"
Estadísticas automáticas con fórmulas: total apostado, ROI, % acierto, balance neto.

---

## Coste mensual estimado (uso personal)

| Servicio | Coste |
|---|---|
| Telegram Bot | Gratis |
| Claude Vision (50 capturas) | ~0.20€ |
| Google Sheets API | Gratis |
| API-Football (plan free) | Gratis |
| **Total** | **~0.20€/mes** |
