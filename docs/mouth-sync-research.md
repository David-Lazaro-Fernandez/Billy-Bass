# Investigación: sincronización de la boca

Creado: 2026-10-03 · Responde a `handoff-mouth-sync.md`.

## Resumen
- **Sí hay un patrón común**, y es el que ya usamos: RMS de una banda → envolvente (ataque rápido, caída
  lenta) → umbral con histéresis → pulsos de motor con tiempos mínimos. Nadie hace algo mucho más
  sofisticado en el microcontrolador.
- Lo que separa a los proyectos que "se ven bien" de los demás son tres detalles, y nos faltan los tres:
  1. constantes de tiempo en **ms**, no por bloque;
  2. umbral **relativo al nivel reciente** (AGC / pico móvil), no fijo;
  3. cerrar la boca en los **valles** entre sílabas aunque el volumen siga alto.
- Para música, **ningún proyecto separa la voz en tiempo real en el MCU**. Los que funcionan bien usan pistas
  separadas de antemano (voz para la boca, batería para la cola). Con audio Bluetooth del celular eso no se
  puede, así que propongo un truco barato: la voz casi siempre va al centro de la mezcla estéreo.
- Para el asistente (audio conocido de antemano), lo mejor es calcular la boca **en el servidor** y mandar los
  tiempos junto con el audio.

## 1. Proyectos revisados

Revisé el código de cada uno, no solo el README. "Licencia" importa solo si se copia código; las ideas y los
valores de parámetros se pueden usar libremente.

| Proyecto | Técnica de boca | Parámetros relevantes | Qué tomar | Licencia / estado |
|---|---|---|---|---|
| [Cian911/billy-ai](https://github.com/Cian911/billy-ai) (ESPHome, ESP32) | RMS → envolvente con constantes de **tiempo** (`exp(-bloque_ms / tau_ms)`) → EMA → umbral → pulsos abrir / "mantener" / cerrar | ataque 8 ms, caída 120 ms; abre > 6 %; pulso de mantener cada 140 ms; cierre de emergencia a 900 ms; abrir 110 ms al 80 %, cerrar 160 ms en reversa al 75 % | La fórmula de constantes de tiempo (problema 1). Confirma lo de "patear y luego sostener" que ya hacemos | MIT · activo (mar 2026) |
| [mptsolutions/My_Assistant_Billy](https://github.com/mptsolutions/My_Assistant_Billy) (ESPHome, ESP32-S3) | Usa el componente de billy-ai. Un pulso de 80 ms por cada cruce del umbral; el resorte cierra | ataque 5 ms, caída 35 ms, umbral 20 %, mínimo 170 ms entre pulsos | Muestra que con caída corta (~35 ms) y pulsos cortos se logra "una apertura por sílaba" sin máquina de estados | MIT · activo (sep 2026) |
| [ryandrake08/billy](https://github.com/ryandrake08/billy) (ESP-IDF, ESP32-S3) | RMS por bloque de 10.7 ms → envolvente normalizada → **3 niveles** (cerrada / media / abierta) | ataque 0.6, caída 0.15 (por bloque); media > 0.3, abierta > 0.65 de una referencia fija; media = 80 % de PWM | En pruebas de banco encontraron que el motor **casi no se mueve por debajo de ~65 %** de PWM, pero 80 % sí da una posición intermedia visible. Vale la pena probarlo cuando tengamos el DRV8833 (problema 4) | Apache-2.0 · activo (sep 2026) |
| [TheDougMiester/Talking-Skull-with-WiFi-controls](https://github.com/TheDougMiester/Talking-Skull-with-WiFi-controls) (ESP32-S3, servo) | FFT. **Vocales 300–1000 Hz abren; sibilantes 2.5–6 kHz restan.** Normaliza contra el **pico móvil** × 1.25 y aplica una curva `x^1.7` | ataque 0.70, caída 0.20, retención 50 ms, supresión de sibilantes 0.65, margen sobre el pico 1.25. Usa audio estéreo con **voz aislada en el canal izquierdo** | El mejor documentado. Su `CALIBRATION.md` describe exactamente nuestro riesgo: "la boca se queda abierta todo el tiempo" con voz comprimida → lo arreglaron con margen sobre el pico + curva expansiva + caída más rápida. Ideas para los problemas 2 y 3 | MIT (el código fuente no está en el repo, solo binarios y documentación) |
| [Thokoop/billy-b-assistant](https://github.com/Thokoop/billy-b-assistant) (Raspberry Pi, OpenAI Realtime) | Voz: RMS por bloque de 40 ms > 1500 → pulso de boca cuya fuerza y duración escalan con el volumen. **Canciones: usa `vocals.wav` para la boca y `drums.wav` para la cola**, separados de antemano | umbral 1500 (de ±32768), mínimo 150 ms entre pulsos, pulso 15–70 ms | Confirma que para música, el camino práctico es separar las pistas antes | Licencia propia "uso personal y educativo": no copiar código · activo (sep 2026) |
| [E2119A/ESP32-Big-Mouth-Billy-Bass](https://github.com/E2119A/ESP32-Big-Mouth-Billy-Bass) (ESP32, A2DP, tesis) | FFT de 256 puntos; boca si el promedio 300–1500 Hz > umbral fijo; cola si graves 0–150 Hz (log) > umbral | boca abierta 100 ms fijos; cola ≥ 250 ms entre golpes; suavizado de graves 0.2 | Es casi nuestra misma arquitectura (A2DP en ESP32). Sirve de comparación: umbral fijo y sin histéresis, sufre lo mismo que nosotros | Sin licencia · sep 2025 |
| [ViennaMike/ChatterPi](https://github.com/ViennaMike/ChatterPi) (Raspberry Pi, servo) | Tres estilos: umbral único ("Scary Terry"), multinivel ("Jawduino") y multinivel con **pasa-banda 500–2500 Hz** (estilo "Wee Little Talker") | Butterworth orden 6; 50 actualizaciones/s; retraso configurable del audio | Recoge los estilos clásicos de las placas de Halloween. El retraso del audio es nuestro "look-ahead" | Sin archivo de licencia · jun 2024 |
| [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) | Reconocimiento de fonemas offline → 6–9 formas de boca (A–F, G, H, X) con tiempos | Salida TSV/JSON/XML; tiene reconocedor **"phonetic" para idiomas que no son inglés** | Para el asistente, en el servidor (ver §4) | MIT · activo |
| [Azure Speech: visemas](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-speech-synthesis-viseme) | El TTS emite eventos `VisemeReceived` (ID 0–21 + desfase en ticks de 100 ns) durante la síntesis | 0 = silencio, 21 = p/b/m (labios cerrados), 1–11 = vocales | Para el asistente si se usa Azure. Revisar que el locale en español soporte visemas | Servicio de pago |
| [Amazon Polly: speech marks](https://docs.aws.amazon.com/polly/latest/dg/speechmarks.html) | Pides las marcas (JSON, `{"time":…, "type":"viseme", "value":"p"}`) en una **petición aparte** del audio | — | Igual que Azure, pero son dos llamadas | Servicio de pago |
| [Demucs](https://github.com/facebookresearch/demucs) | Separación de voz / batería / bajo / otros | En CPU tarda ~1.5× la duración de la canción | Solo sirve si la música sale del servidor, no del celular | MIT · **archivado** (ene 2025); el fork del autor solo recibe arreglos |

No incluidos: `vxguo1/billy-fish` (no se pudo clonar; parece privado o borrado), `billai-bass` (la boca es
un script de prueba, sin sincronización con audio), GillGPT (la boca la mueve una FPGA; no revisado a fondo).

## 2. El patrón común y cómo encaja

```
audio ─► banda de voz ─► RMS ─► envolvente (ataque ~5–20 ms, caída ~35–120 ms)
                                   │
                    normalizar contra el pico reciente (AGC)   ◄── solo los mejores
                                   │
                    umbral con histéresis + tiempos mínimos ─► pulsos de motor
```

Nuestra arquitectura ya tiene esa forma. No hace falta FFT: con biquads ya tenemos la banda de voz, y una FFT
no da nada que no den 2–3 biquads más. Las mejoras van **dentro** de las etapas actuales.

## 3. Cambios propuestos a `mouth_sync.cpp`

En orden de prioridad. Los tres primeros son baratos y deberían notarse; el 4 y el 5 son experimentos.

### 3.1 Constantes de tiempo en ms (problema 1)
Convertir cada coeficiente a `coef = 1 − exp(−bloque_ms / tau_ms)`, con `bloque_ms = n × 1000 / sampleRate`.
Los valores equivalentes a los actuales (calculados para bloques de 20 ms) son:

| Ajuste actual | Valor por bloque | Constante de tiempo equivalente |
|---|---|---|
| `ATTACK` | 0.6 | **22 ms** |
| `RELEASE` | 0.25 | **70 ms** |
| `FLOOR_RISE` | 0.0005 | **40 s** |
| promedio de graves | 0.05 | **390 ms** |

```cpp
const float ATTACK_MS = 22, RELEASE_MS = 70, FLOOR_RISE_MS = 40000, BASS_AVG_MS = 390;

static float coef(float blockMs, float tauMs) { return 1.0f - expf(-blockMs / tauMs); }

// en mouthSyncProcess():
float blockMs = n * 1000.0f / sampleRate;   // guardar sampleRate en mouthSyncBegin()
envelope += coef(blockMs, voice > envelope ? ATTACK_MS : RELEASE_MS) * (voice - envelope);
```
Con esto el comportamiento no cambia con el micrófono, y queda igual con Bluetooth.

### 3.2 Umbral relativo al pico reciente: AGC (problema 2)
Seguir el **pico** de la envolvente (sube al instante, baja con constante de ~3 s) y poner los umbrales como
fracción de ese pico, además del ruido de fondo:

```cpp
const float PEAK_DECAY_MS = 3000;
const float OPEN_OF_PEAK = 0.30;   // abre arriba de −10 dB del pico reciente
const float CLOSE_OF_PEAK = 0.18;  // cierra abajo de −15 dB
float minLevel;                    // 80 con micrófono (ruido de motores); ~15 con Bluetooth (−43 dBFS)

if (envelope > peak) peak = envelope;
else peak += coef(blockMs, PEAK_DECAY_MS) * (envelope - peak);
peak = max(peak, minLevel * 2);    // que el silencio no se "amplifique"

float openLevel  = max({noiseFloor * OPEN_RATIO,  peak * OPEN_OF_PEAK,  minLevel});
float closeLevel = max({noiseFloor * CLOSE_RATIO, peak * CLOSE_OF_PEAK, minLevel * 0.7f});
```
- Así deja de importar el volumen del celular o de la canción.
- `minLevel` pasa a depender de la fuente: con Bluetooth el silencio digital es 0, así que se puede bajar mucho.
  Sugiero agregarlo como parámetro: `mouthSyncBegin(sampleRate, minLevel)`.
- La lección de la calavera: con voz muy comprimida la envolvente vive cerca del pico. Por eso el umbral queda
  bastante por debajo del pico (0.30), y el cierre por sílaba lo da el 3.3, no este umbral.

### 3.3 Cerrar en los valles entre sílabas (voz) y sostener en notas largas (canto)
Es el cambio que más ayuda a los dos objetivos a la vez. Hoy la boca solo cierra si la voz cae bajo un nivel
absoluto. En habla continua la envolvente baja ~6–15 dB entre sílabas, pero quizá no lo suficiente para cruzar
el umbral, y la boca se queda abierta toda la frase. En cambio, una nota sostenida casi no baja (el vibrato es
de ±1–2 dB).

Regla: **cerrar cuando la envolvente cae a una fracción del máximo alcanzado desde que se abrió; reabrir cuando
sube sobre el mínimo alcanzado desde que se cerró.**

```cpp
const float DIP_RATIO = 0.55;     // cierra si cae −5 dB bajo el máximo de esta apertura
const float REOPEN_RATIO = 1.6;   // reabre si sube +4 dB sobre el valle

static float localMax = 0, localMin = 0;

// HOLD:   localMax = max(localMax, envelope);
//         bool dip = envelope < localMax * DIP_RATIO;
//         cerrar si (quiet || dip) && now - openedAt >= MIN_OPEN_MS
// CLOSED: localMin = min(localMin, envelope);
//         abrir si envelope > openLevel && envelope > localMin * REOPEN_RATIO && ...
// Al abrir: localMax = envelope.  Al cerrar: localMin = envelope.
```
- Habla: cierra en cada valle, aunque el volumen general sea alto → una apertura por sílaba.
- Nota larga: no hay valle → la boca se queda abierta (hasta `MAX_HOLD_MS`).
- Batería sobre una nota larga: un golpe sube `localMax` y, cuando el golpe pasa, la caída puede activar `dip`.
  Por eso el filtro de banda importa (3.4) y `DIP_RATIO` no debe ser muy alto. Ajustar a oído entre 0.45 y 0.65.
- Límite mecánico: `MIN_OPEN_MS + SHUT_MS + MIN_CLOSED_MS = 240 ms` → máximo ~4 sílabas/s. El habla va a 4–6.
  Probar `MIN_CLOSED_MS = 40`.

### 3.4 Banda de voz más estrecha + restar sibilantes (problema 3, parcial)
- Pasa-bajas de la voz: **3000 → 1500 Hz**. La energía de las vocales (lo que abre la boca) está en
  300–1000 Hz; arriba de 1.5 kHz hay sobre todo platillos, guitarras con distorsión y sibilantes. E2119A usa
  300–1500; la calavera, 300–1000.
- Banda de sibilantes (solo Bluetooth, porque el micrófono muestrea a 8 kHz): pasa-altas 2500 Hz + pasa-bajas
  6000 Hz. `drive = max(0, voz − 0.65 × sibilantes)` (valor de la calavera). Hace que la "s" y la "f" cierren
  la boca y le resta peso a los platillos.
- Costo: 2 biquads más por muestra a 44.1 kHz. Insignificante.

### 3.5 Experimento: usar el centro de la mezcla estéreo (problema 3, música)
Esto **no lo vi en ningún proyecto** revisado: es una propuesta mía, sin probar. Casi todas las mezclas ponen
la voz principal al centro y abren a los lados guitarras, sintetizadores, coros y reverberación. Con A2DP
tenemos L y R, pero `bt_audio.cpp` los mezcla a mono antes de llegar aquí.

- `bt_audio.cpp`: mandar `mid = (L+R)/2` y `side = (L−R)/2` (dos bloques).
- `mouth_sync.cpp`: pasar ambos por la banda de voz y usar `drive = max(0, vozMid − SIDE_WEIGHT × vozSide)`,
  con `SIDE_WEIGHT = 1.0`. Con el micrófono, `side = nullptr` y queda como hoy.
- Limitaciones: no ayuda con grabaciones mono ni con instrumentos al centro (bombo, caja, bajo; los dos
  primeros ya los quita la banda de voz). La reverb de la voz se cancela en parte.
- Cómo evaluarlo: imprimir `vozSide / vozMid` en el monitor serie con canciones con y sin voz.

### 3.6 Cola (problema 5)
Con Bluetooth los graves sí llegan completos (el problema del MAX4466 es solo con micrófono). Lo de hoy
(energía de graves contra su promedio) es una versión simple de "onset detection" y alcanza para este motor.
Basta con:
- expresar el promedio en ms (390 ms, ver 3.1);
- comparar contra el promedio **antes** de actualizarlo (ya se hace así) y exigir que la energía esté
  **subiendo** respecto al bloque anterior (`bass > lastBass * 1.2`), para no disparar en notas largas de bajo.

No vale la pena el "spectral flux" completo mientras la cola tenga el problema mecánico de `next-steps.md`.

### 3.7 Look-ahead (cuando haya amplificador en el ESP32)
- Retrasar el audio de salida unos 100–120 ms para compensar lo que tarda en abrir el motor. A 44.1 kHz mono
  de 16 bits son ~10 KB de búfer: cabe sin PSRAM. ChatterPi tiene ese mismo retraso configurable.
- Ojo con las pruebas actuales: el audio sale por USB hacia la PC (`usb_speaker.py`), que agrega su propia
  latencia, así que **hoy la boca probablemente va adelantada** respecto a lo que se oye. Tenerlo en cuenta
  antes de juzgar la sincronía a oído.

### Valores iniciales sugeridos

| Ajuste | Hoy | Propuesto |
|---|---|---|
| Ataque / caída | 0.6 / 0.25 por bloque | 22 ms / 70 ms |
| Banda de voz | 300–3000 Hz | 300–1500 Hz |
| Supresión de sibilantes | — | 2.5–6 kHz, peso 0.65 (solo Bluetooth) |
| Umbral mínimo | 80 | 80 micrófono / 15 Bluetooth |
| Pico (AGC) | — | caída 3 s; abre 0.30 × pico, cierra 0.18 × pico |
| Cierre en valle / reapertura | — | 0.55 × máximo local / 1.6 × mínimo local |
| `MIN_CLOSED_MS` | 60 | 40 |

## 4. Propuesta aparte: la boca del asistente calculada en el servidor

Cuando el pez hable con la voz del asistente, el audio completo se conoce antes de reproducirlo. Ahí no hace
falta adivinar en tiempo real:

1. El servidor genera el TTS y calcula una **pista de boca**: lista de `(t_ms, abrir|cerrar)`.
2. La manda junto con el audio. El ESP32 la ejecuta contra el **reloj del audio** (muestras reproducidas, no
   `millis()`), restando ~120 ms de latencia del motor a cada evento.

Cómo calcular la pista, de más simple a más fino:
- **A. La misma envolvente, pero offline**: correr el algoritmo del §3 en Python sobre el WAV completo. Sin
  dependencias nuevas, y se puede ajustar viendo una gráfica. **Recomendado para empezar.**
- **B. Rhubarb Lip Sync** (MIT, offline, con reconocedor fonético para español). Mapear `A` (p/b/m) y `X`
  (reposo) → cerrada; `C`, `D`, `E`, `H` → abierta; `B`, `F`, `G` → cerrada o un pulso corto. Ventaja: cierra en
  p/b/m aunque haya volumen, que es justo lo que delata un lip sync malo.
- **C. Visemas del TTS** (Azure o Polly), si se usa uno de esos servicios. Mapeo Azure: 0 y 21 → cerrada,
  1–11 → abierta, el resto → pulso corto. Ya vienen alineados con el audio.

Para música servida desde el servidor (no desde el celular) aplica la misma idea con separación de pistas:
Demucs (archivado, pero funciona) → envolvente de la voz para la boca, golpes de la batería para la cola. Es lo
mismo que hace billy-b-assistant con sus `vocals.wav` / `drums.wav`.

## Siguiente paso sugerido
Aplicar 3.1 + 3.2 + 3.3 juntos (tocan las mismas líneas), probar con los cuatro casos de `handoff-mouth-sync.md`
y luego decidir si 3.4 y 3.5 hacen falta. Agregar `pico` y `máx. local` a la línea del monitor serie ayuda a
ajustar.
