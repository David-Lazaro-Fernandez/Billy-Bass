# Handoff: refinar la sincronización de la boca

Creado: 2026-10-03 · Estado: **pendiente de investigación**

## Objetivo
Que la boca del Billy Bass se vea natural con dos tipos de audio:
- **Voz hablada** (asistente / TTS): abrir y cerrar con cada sílaba.
- **Música con canto**: seguir la voz, sostener la boca abierta en notas largas, e ignorar batería y bajo.

La pregunta concreta: **¿qué hacen otros proyectos (Billy Bass, animatrónicos con mandíbula, lip sync) y
existe un patrón común que convenga adoptar?** El entregable es una recomendación de cambios a
`firmware/src/mouth_sync.cpp`, no una reescritura completa.

## Estado actual (funciona, pero es mejorable)
Código: `firmware/src/mouth_sync.cpp`. Recibe bloques de audio de cualquier fuente (micrófono o Bluetooth)
y mueve los motores sin bloquear.

```
audio ─► pasa-altas 300 Hz ─► pasa-bajas 3 kHz ─► RMS por bloque ─► envolvente ─► máquina de estados ─► BOCA
      └► pasa-altas 40 Hz ─► pasa-bajas 150 Hz ─► RMS por bloque ─► detección de golpes ─────────────► COLA
```

- **Filtros**: biquads Butterworth (Audio EQ Cookbook).
- **Envolvente**: ataque `0.6`, caída `0.25` (coeficientes **por bloque**, no por tiempo).
- **Ruido de fondo**: sigue al mínimo de la envolvente; sube con `FLOOR_RISE = 0.0005`.
- **Umbrales**: abre si envolvente > `max(ruido × 3.0, 80)`, cierra si < `max(ruido × 2.0, 56)`.
- **Máquina de estados de la boca**: `CLOSED → KICK (120 ms a fuerza completa) → HOLD → SHUTTING (80 ms motor al revés) → CLOSED`.
  Mínimos: 100 ms abierta, 60 ms cerrada. Máximo 15 s sostenida.
- **Cola**: golpe si graves > promedio × 1.6 (y > 30), separados ≥ 400 ms; además cada 1.5 s mientras hay sonido.

Escala de las muestras: ±2048 (el micrófono ADC de 12 bits; el audio Bluetooth de 16 bits se divide entre 16).

## Problemas conocidos / sospechas
1. **Coeficientes por bloque**: con micrófono los bloques son de 20 ms; con Bluetooth llegan bloques de
   tamaño variable (hasta 1024 muestras a 44.1 kHz ≈ 23 ms). El ataque/caída cambia según la fuente.
   Convendría expresarlos como constantes de tiempo (ms).
2. **Umbral casi fijo con Bluetooth**: el silencio digital es 0, así que el ruido de fondo queda en ~0 y el
   umbral efectivo es el mínimo fijo (80). No se adapta al volumen de la canción ni al volumen del celular.
   Posible solución: normalización / control automático de ganancia (AGC) sobre la envolvente.
3. **Voz vs. instrumentos**: el filtro 300–3000 Hz deja pasar guitarras, sintetizadores, platillos, etc.
4. **Solo abierto/cerrado**: no hay posiciones intermedias (motor con resorte, sin sensor de posición).
5. **Cola**: el detector de golpes es básico; el MAX4466 casi no capta graves.

## Restricciones de hardware (importan para cualquier propuesta)
- Motor DC de la boca con resorte, **sin sensor de posición**. Driver L298N a ~4 V (pierde ~2 V).
- PWM a 1 kHz (el L298N no rinde a 20 kHz). El zumbido de 1 kHz se cuela al micrófono, por eso hoy se
  sostiene a fuerza completa. Con un DRV8833 a 20 kHz se podría sostener con PWM parcial.
- ESP32 clásico (240 MHz, 2 núcleos, sin PSRAM). El procesamiento corre dentro del callback de Bluetooth.
  Una FFT de 512 puntos (ESP-DSP) tarda ~1 ms: hay margen, pero no para modelos pesados.
- Latencia de la boca: el motor tarda ~100–150 ms en abrir. Si el audio se reproduce en el ESP32,
  se podría retrasar el audio para compensar ("look-ahead").

## Qué investigar
1. **Proyectos de Billy Bass**: buscar en GitHub cómo mueven la boca (envolvente, umbral, FFT, visemas).
   Términos sugeridos: `billy bass esp32`, `billy bass raspberry pi`, `big mouth billy bass alexa`,
   `billy bass home assistant`, `billy bass chatgpt`.
2. **Animatrónicos de Halloween** ("talking skull", "audio to servo", "jaw servo audio"): hay placas
   comerciales que convierten audio en movimiento de mandíbula; documentan buenos parámetros de
   envolvente y umbral.
3. **Lip sync por visemas** (para la voz del asistente, donde el audio se conoce de antemano):
   - Rhubarb Lip Sync (genera posiciones de boca a partir de un audio).
   - Visemas de servicios de TTS: Amazon Polly ("speech marks") y Azure Speech ("viseme events").
4. **Separación de voz para música** (procesar en el servidor, no en el ESP32): Demucs, Spleeter.
5. **Detección de ritmo** para la cola: onset detection / spectral flux.

Verificar que cada proyecto exista y esté mantenido antes de citarlo; anotar licencia si se reusa código.

## Entregables esperados
1. Tabla de proyectos revisados: enlace, técnica usada, parámetros relevantes, qué tomar.
2. El patrón común (si existe) y cómo encaja con la arquitectura actual.
3. Cambios concretos propuestos a `mouth_sync.cpp`, con valores iniciales de parámetros.
4. Si conviene, una propuesta separada para el asistente: visemas/tiempos calculados en el servidor
   y enviados junto con el audio (en vez de analizar el audio en el ESP32).

## Cómo probar
1. Subir el firmware: desde `firmware/`, `pio run -e esp32dev -t upload`.
2. Correr `python tools\usb_speaker.py` (escuchar en la PC lo que recibe el pez).
3. Conectar el celular a "Billy Bass" por Bluetooth y probar con:
   - un podcast o audiolibro (voz hablada);
   - una canción con notas largas sostenidas;
   - una canción con mucha batería;
   - silencio / pausa (la boca debe quedarse cerrada).
4. El monitor serie imprime `voz=… ruido=… graves=… boca=…` cada 500 ms (lo muestra `usb_speaker.py`).

Nota: la cola tiene poca fuerza por un problema mecánico pendiente (ver `next-steps.md`), así que su
movimiento puede no reflejar bien lo que manda el código.
