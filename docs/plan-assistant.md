# Plan: asistente con IA (fase 6)

Creado: 2026-10-03 · Estado: **en desarrollo**

## Decisiones
- **Comandos**: siguen locales con Vosk (`server/commands.py`). El LLM solo entra si la frase empieza con
  "Billy" y **no** es un comando.
- **Voz a texto de preguntas libres**: `faster-whisper` en la PC (CPU, sin GPU NVIDIA → modelo `small`, int8).
- **LLM**: DeepSeek `deepseek-flash` (API compatible con OpenAI). ~$0.0002 USD por pregunta corta.
  El texto de las preguntas se procesa en China (aceptado). Cambiar de proveedor = cambiar URL, modelo y clave.
- **Texto a voz**: Amazon Polly, voz neural en español de México, salida PCM 16 kHz. Gratis 12 meses hasta
  1 M de caracteres al mes; después $16 por millón.
- **Claves**: `server/.env` (ignorado por git). AWS usa las credenciales normales de boto3 (`aws configure`
  o variables de entorno).

## Personalidad y funciones (2026-10-03)
- **Personalidades**: `server/personalidades/` (reglas comunes en `_base.md` + un archivo por personalidad, con su
  voz de Piper). Se cambia con "Billy, modo <nombre>": normal, mafioso, pirata, abuelito, dramático. Al cambiar se
  borra el historial y Billy se presenta. Para agregar una, copiar un archivo y reiniciar el servidor de voz (el
  nombre debe existir en el vocabulario de Vosk).
- **Personalidad en la petición**: se relee en cada pregunta. Va siempre idéntica al inicio de la
  petición para que DeepSeek la tome de su caché (~50× más barata); desde la segunda pregunta, 75–85 % de la
  entrada sale del caché. La hora va junto a la pregunta, no en la personalidad, para no romper ese prefijo.
- **Hora**: siempre de la Ciudad de México (UTC−6 fijo; sin horario de verano desde 2022), en `tools.py`.
- **Clima**: función `get_weather(ciudad, dia)` con Open-Meteo (gratis, sin clave, uso personal, CC-BY 4.0),
  caché de 10 minutos. Una pregunta de clima tarda ~3 s al primer texto (dos llamadas a DeepSeek).
- **Modo de razonamiento de DeepSeek desactivado** (`thinking: disabled`): activo por defecto, gastaba cientos de
  tokens antes de responder.

## Voz de Billy (2026-10-03)
Por defecto, solo Piper `es_MX-claude-high` (voz femenina, Apache 2.0): <1 s por frase. Se elige con
`TTS_ENGINE` en `server/.env` (`piper`, `piper_rvc` o `polly`).
- `piper_rvc` convierte la voz de Piper al modelo RVC "Jorge" v2, 13 semitonos abajo, tono `pm`. Suena mejor,
  pero en esta CPU (sin GPU NVIDIA) va a ~1–1.4× el tiempo real: la primera frase tardaba 6–10 s en sonar tras
  la pregunta. Se dejó de usar por la espera (2026-10-03); para volver a usarlo habría que acelerarlo (ONNX o GPU).
- Modelos (no van en git, en `server/models/`): Vosk `vosk-model-small-es-0.42`, Piper `es_MX-claude-high`
  (de `rhasspy/piper-voices`), RVC `Jorge-v2/model.pth` + `model.index`. Jorge es un modelo de aficionado sin
  licencia de una voz de Nuance (Loquendo): solo para uso personal.

### Instalar el entorno de RVC (Windows)
RVC necesita versiones viejas de numpy y su dependencia `fairseq` no compila sin Visual C++, así que vive en un
entorno aparte que `assistant.py` usa como proceso (`server/rvc_worker.py`):
```
py -3.11 -m venv server\.venv-rvc
server\.venv-rvc\Scripts\python -m pip install "pip<24.1"          # omegaconf 2.0.6 tiene metadatos que pip nuevo rechaza
server\.venv-rvc\Scripts\python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
server\.venv-rvc\Scripts\python -m pip install --no-deps rvc-python==0.1.5
server\.venv-rvc\Scripts\python -m pip install av faiss-cpu==1.7.3 "numpy<=1.23.5" omegaconf==2.0.6 praat-parselmouth pyworld soundfile torchcrepe loguru requests ffmpeg-python librosa transformers==4.46.3
xcopy /E /I server\rvc_fairseq_shim\fairseq server\.venv-rvc\Lib\site-packages\fairseq
```
El último paso instala un sustituto de `fairseq` (`server/rvc_fairseq_shim/`) que carga el mismo ContentVec desde
`transformers` (`lengyue233/content-vec-best`). En el proceso, importar `torch` antes que `faiss`: al revés, la DLL de
torch no carga en Windows.

## Flujo
```
audio del pez ─► Vosk (gramática de comandos)
                   ├─ "billy <comando>"           → comando al pez (como hoy)
                   ├─ "billy" + más voz después    → ese audio a Whisper ─┐
                   ├─ "billy" solo                 → gesto "escuchando"; la siguiente frase (5 s) va a Whisper
                   └─ sin "billy"                  → se ignora                                            │
                                                                                                          ▼
                               texto de Whisper ─► ¿se parece a un comando? ─sí─► comando al pez
                                                        │no
                                                   DeepSeek (respuesta de 1–2 frases, sabe fecha y hora)
                                                        │
                                                   Polly (PCM 16 kHz) ─► bocinas de la PC (hasta que haya MAX98357A)
```
- Whisper, DeepSeek y Polly corren en un hilo aparte: la recepción de audio no se detiene mientras piensa.
- Memoria de conversación: los últimos 3 intercambios, para preguntas de seguimiento ("¿y mañana?").

## Pasos
1. **Asistente sin el pez**: `server/assistant.py` con Whisper + DeepSeek + Polly, probado con texto, con un
   WAV y con el micrófono de la PC.
2. **Integración en `voice_server.py`**: detectar "billy + pregunta", recortar el audio de la pregunta y
   mandarlo al asistente.
3. **Boca**: mientras suena la respuesta, el pez mueve la boca. Primera versión: mandar el audio de la
   respuesta al pez y que `mouth_sync` lo siga. Después: *speech marks* de Polly (visemas).
4. **Bocina del pez** (requiere MAX98357A en I2S1): reproducir la respuesta en el pez en vez de la PC.

## Riesgos
- **Latencia**: ~3–5 s por pregunta (Whisper ~1 s, DeepSeek 1–3 s, Polly ~0.3 s). Un gesto de "pensando"
  ayuda a que no parezca colgado.
- **Whisper en CPU con música de fondo**: medirlo; si falla mucho, bajar el volumen (comando de voz) al oír
  "Billy" o usar un modelo más grande.
- **El pez se oye a sí mismo**: cuando hable por su bocina, ignorar el micrófono mientras habla (bandera
  "ocupado", como con los motores).
