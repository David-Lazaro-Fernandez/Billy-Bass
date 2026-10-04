# Plan: comandos por voz

Creado: 2026-10-03 · Estado: **plan, sin empezar**

## Decisiones tomadas
- **Comandos**: primero una lista fija para controlar el pez; después el mismo flujo pasa las frases
  desconocidas al asistente con IA (fase 6).
- **Activación**: palabra **"Billy"**, con escucha continua.
- **Proceso**: en la **PC de la red local** (servidor Python en `server/`), sin nube.

## Arquitectura

```
ESP32                                    PC (server/)
─────                                    ────────────
micrófono ─► ADC por DMA, 16 kHz ─UDP─►  búfer ─► VAD (¿hay voz?) ─► detección de "Billy"
                                                                       │
                                                         Whisper (texto, español)
                                                                       │
                                                       ¿comando fijo? ──no──► (fase 6: IA)
                                                                       │sí
motores / Bluetooth ◄──── comando (JSON corto por UDP) ◄───────────────┘
```

El ESP32 no reconoce voz: solo captura y envía audio, y ejecuta comandos. No hay alternativa razonable en
esta placa: MultiNet (comandos de Espressif) solo corre en ESP32-S3/P4, y casi todos los modelos de WakeNet
(palabra de activación) necesitan PSRAM, que este ESP32 no tiene.

## Fase A: capturar y enviar audio (ESP32)

**A1. Captura por DMA a 16 kHz.** Hoy `micReadBlock()` llama `analogRead()` en un bucle activo a 8 kHz.
Para escuchar todo el tiempo con WiFi encendido hace falta el ADC en modo continuo: I2S0 en modo
"ADC integrado", que el core de Arduino instalado (2.0.17) soporta. GPIO 34 es ADC1, compatible con este modo.
- Whisper y openWakeWord esperan 16 kHz y 16 bits.
- I2S0 queda ocupado por el ADC, así que el MAX98357A (fase 3) tendrá que usar **I2S1**. La librería A2DP
  permite elegir el puerto.

**A2. WiFi + envío por UDP.** Paquetes de 20 ms (320 muestras = 640 bytes) con número de secuencia y una
bandera de "ocupado" (motores o bocina activos). Son 32 KB/s; perder algún paquete no importa.
- La red y la IP de la PC van en `firmware/src/secrets.h`, que se agrega a `.gitignore`.
- Los comandos de regreso llegan por el mismo socket, como JSON corto: `{"id":7,"cmd":"pausa"}`. El ESP32
  responde con un acuse para que el servidor reenvíe si se pierde.

**A3. Prueba crítica: Bluetooth + WiFi a la vez.** El ESP32 clásico comparte una sola radio entre Bluetooth y
WiFi, y sin PSRAM la RAM es justa. Medir el heap libre con A2DP conectado y el envío UDP activo, y escuchar si
la música se corta. Según el resultado:
- **Funciona**: el pez escucha "Billy" incluso mientras suena música.
- **No funciona**: dos modos, *bocina* (Bluetooth) y *asistente* (WiFi), y se cambia con el botón frontal
  (en modo bocina el micrófono no envía nada).

Hacer A3 **antes** de invertir en el servidor, porque cambia el diseño.

## Fase B: servidor (PC)

**B1. Receptor y grabación.** Recibir el UDP, reordenar con la secuencia y guardar WAV. Primer hito:
**escuchar cómo suena el micrófono del pez a 1–3 m**, con los motores quietos y en movimiento. El MAX4466 por
el ADC de 12 bits es ruidoso, y si la calidad no alcanza para Whisper, hay que cambiar de micrófono (ver Riesgos).

**B2. VAD.** Silero VAD (corre en CPU, ~1 ms por bloque) corta el flujo en frases. Solo las frases llegan a
Whisper.

**B3. Detección de "Billy", versión 1, sin entrenar nada.** Pasar cada frase por voz a texto local (Vosk con
la lista de palabras de los comandos; ver B5. Alternativa: `faster-whisper` modelo `small`, `language="es"`)
y aceptar si el texto empieza con algo parecido a
"Billy" (`billy`, `bili`, `billi`, `vili`; comparación difusa con `rapidfuzz`). El resto de la frase es el
comando: "Billy, pausa" funciona en una sola frase. Si solo dijo "Billy", el pez hace un gesto y la siguiente
frase (hasta ~5 s) es el comando.
- Ventaja: funciona en español desde el día uno.
- Costo: el reconocedor corre con cada frase que se oye (TV, conversación). Con Vosk es poco; con Whisper
  `small`, ~0.5–1 s por frase de 2 s en CPU. Aceptable para empezar en ambos casos.

**B4. Detección de "Billy", versión 2, solo si la v1 es lenta o se activa sola.** Entrenar un modelo propio de
openWakeWord con su notebook de Colab (datos sintéticos, menos de 1 h). Corre sobre el flujo cada 80 ms, y
Whisper solo se usa después de la activación.
- Riesgo: openWakeWord solo soporta inglés oficialmente. "Billy" suena casi igual en español, pero hay que
  validarlo con grabaciones reales del pez.
- Licencias: el código es Apache-2.0; los modelos preentrenados son CC BY-NC-SA (uso no comercial).

**B5. Comandos: texto → puntaje de parecido → acción.** No hace falta entender lenguaje: basta con comparar
lo transcrito contra la lista de frases de cada comando y quedarse con la que más se parece.
1. Normalizar: minúsculas, sin acentos ni signos. `"Billy, modo boisina!"` → `billy modo boisina`.
2. Si la primera palabra no se parece a "Billy" (≥ 0.75), ignorar la frase.
3. Comparar el resto contra cada frase de la tabla (`rapidfuzz`, de 0 a 1) y ordenar.
4. **Ejecutar solo si el mejor puntaje es ≥ 0.80 y le saca ≥ 0.15 al segundo.** Si no, el pez hace el gesto
   de "no entendí". El margen evita confundir comandos parecidos.

Prueba con `difflib` (2026-10-03), sobre transcripciones simuladas:

| Se transcribió | 1.º | 2.º | Resultado |
|---|---|---|---|
| Billy modo boisina | modo_bocina 0.87 | modo_asistente 0.62 | modo bocina |
| billy pasa | pausa 0.89 | play 0.50 | pausa |
| billy siguente | siguiente 0.94 | play ("sigue") 0.77 | siguiente (margen 0.17, apenas pasa) |
| billy qué hora es | callate 0.47 | — | no entendí (fase 6: a la IA) |
| oye qué tal | — | — | ignorada (sin "Billy") |

Escoger sinónimos que **no se parezcan entre sí** (p. ej., "sigue" y "siguiente" quedan cerca; usar
"continúa" para reanudar).

**Opción más simple que Whisper para esto: Vosk** (Apache-2.0, modelo en español de ~50 MB, CPU). Se le puede
pasar la lista de palabras permitidas ("billy", "modo", "bocina", "pausa"…) y solo transcribe esas. Así
"boisina" ni siquiera aparece, y cuesta mucho menos que Whisper con cada frase. Recomendado para empezar; Whisper
queda para las preguntas libres de la fase 6.

**B6. Medio dúplex.** Mientras la bandera "ocupado" esté activa, el servidor ignora las activaciones. Así el
pez no se activa con el zumbido de sus motores (el PWM de 1 kHz se cuela al micrófono) ni, más adelante, con su
propia voz. Interrumpirlo mientras habla queda para después.

## Lista inicial de comandos (propuesta, ajustar)

| Dices | Hace | Requiere |
|---|---|---|
| "pausa", "para", "play", "continúa" | Pausa / reanuda la música del celular | AVRCP: la librería A2DP tiene `play()` / `pause()` |
| "siguiente", "anterior" | Cambia de canción | AVRCP: `next()` / `previous()` |
| "súbele", "bájale" | Volumen | AVRCP / `set_volume()` |
| "cállate", "quieto" | Detiene boca y cola, sin parar la música | — |
| "muévete" / "baila" | Rutina de boca + cola | — |
| "duérmete" / "despierta" | Desactiva / activa los motores | — |
| "modo bocina" / "modo asistente" | Cambia de modo (si A3 obliga a tener dos) | — |
| "canta" | Reproduce una canción | Bocina (MAX98357A) |

**Confirmación sin bocina**: mientras no llegue el amplificador, el pez responde con gestos. Por ejemplo:
un aleteo de cola = "entendido", dos aperturas de boca = "no entendí".

## Riesgos
1. **Calidad del micrófono**: el ADC del ESP32 rinde ~9–10 bits efectivos y el MAX4466 capta el ruido de los
   motores. Si B1 suena mal, la solución barata es un micrófono I2S digital (INMP441), que se conecta por I2S y
   deja libre el ADC.
2. **Bluetooth + WiFi** (A3): puede obligar a tener dos modos.
3. **Falsas activaciones** con la TV o con la música: medirlas (ver Validación) y ajustar la comparación
   difusa o pasar a B4.
4. **Dependencia de la PC**: si la PC está apagada, el pez sigue funcionando como bocina, pero sin comandos de voz.

## Validación
- Grabar con el micrófono del pez: 50 veces "Billy + comando" desde 1, 2 y 3 m, y 30 min de ruido normal
  (TV, conversación, música por el mismo pez).
- Metas: **≥ 90 % de comandos reconocidos a 2 m** y **≤ 1 activación falsa por hora**.
- Guardar esas grabaciones en `server/testdata/` (fuera de git si pesan mucho) para repetir la prueba en cada cambio.

## Resultados (2026-10-03)
- **Captura**: el ADC por I2S no respeta 8 ni 16 kHz (da 44 y 88 kHz); 22, 32 y 44 kHz sí salen bien. Se
  muestrea a 32 kHz y se reduce a 16 kHz en software (`mic_dma.cpp`): ~15 940 muestras/s, 0 paquetes perdidos.
- **Micrófono MAX4466 sin cambios**: la voz queda ~27 dB sobre el ruido en vocales y ~17 dB en consonantes.
  Los motores suben el ruido ~6 dB, sobre todo tonos en ~1150 y ~1730 Hz.
- **Vosk `small-es-0.42` con vocabulario limitado** (`server/transcribe_wav.py`), grabación a 1 y 3 m sin
  motores: **41 comandos correctos, 0 equivocados**. Fallaron ~5 frases en las que no se oyó "Billy". La
  transcripción libre (sin limitar el vocabulario) es inservible para esto.
- Lecciones: las palabras van **con acentos** (`bájale`, `cállate`; `súbele` no existe en el modelo) y hay que
  pasar el JSON con `ensure_ascii=False`. Vosk a veces pierde "modo" de "modo bocina": "bocina" sola también
  cuenta.
- Falta medir: comandos con los motores en movimiento y activaciones falsas con TV/música durante 30 min.

## Orden de trabajo
1. A1 + A2 + B1: enviar audio y **escucharlo**. Decide si sirve el micrófono.
2. A3: Bluetooth + WiFi. Decide uno o dos modos.
3. B2 + B3 + B5 con 3 comandos (pausa, siguiente, cállate) de punta a punta.
4. Completar la lista de comandos y medir con la validación.
5. B4 solo si hace falta. Luego, fase 6 (IA para las frases que no son comandos).
