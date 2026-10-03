#include <Arduino.h>
#include <math.h>
#include "motors.h"
#include "mouth_sync.h"

// ---------- Ajustes ----------

// Boca: abre cuando la voz supera OPEN_RATIO veces el ruido de fondo, cierra bajo CLOSE_RATIO.
// Dos umbrales distintos (histéresis) evitan que la boca tiemble en el límite.
const float OPEN_RATIO = 3.0;
const float CLOSE_RATIO = 2.0;
const float MIN_OPEN_LEVEL = 80;  // nunca abrir por debajo de esto; arriba del ruido de los motores (~40)

// Envolvente: sube rápido (ataque) y baja más lento (caída), por bloque de ~20 ms.
const float ATTACK = 0.6;
const float RELEASE = 0.25;

// Ruido de fondo: baja rápido, sube muy lento (así una nota de 10 s no se vuelve "ruido").
const float FLOOR_RISE = 0.0005;

// Motor de la boca: abre a fuerza completa, sostiene con menos fuerza para no calentarlo.
// Con el L298N el PWM a 1 kHz se escucha (y el micrófono lo capta como voz), así que se sostiene a fuerza
// completa. Con un DRV8833 a 20 kHz se puede bajar para que el motor no se caliente.
const uint8_t HOLD_STRENGTH = 255;
const unsigned long KICK_MS = 120;        // fuerza completa al abrir
const unsigned long SHUT_MS = 80;         // motor al revés para cerrarla rápido
const unsigned long MIN_OPEN_MS = 100;
const unsigned long MIN_CLOSED_MS = 60;
const unsigned long MAX_HOLD_MS = 15000;  // protección: no sostener más de 15 s

// Cola: se mueve con golpes de graves (batería / bajo) y, mientras haya sonido, cada TAIL_INTERVAL_MS
// (el MAX4466 capta pocos graves, así que los golpes solos casi no la mueven).
const float BEAT_RATIO = 1.6;             // golpe = graves 1.6 veces arriba de su promedio
const float MIN_BEAT_LEVEL = 30;
const unsigned long BEAT_GAP_MS = 400;    // mínimo entre movimientos de cola
const unsigned long TAIL_INTERVAL_MS = 1500;
const unsigned long TAIL_MS = 300;

// ---------- Filtros biquad (fórmulas del Audio EQ Cookbook de R. Bristow-Johnson) ----------

struct Biquad {
  float b0, b1, b2, a1, a2;
  float x1 = 0, x2 = 0, y1 = 0, y2 = 0;

  float process(float x) {
    float y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1;
    x1 = x;
    y2 = y1;
    y1 = y;
    return y;
  }
};

static Biquad makeFilter(bool highPass, float freq, int sampleRate) {
  const float q = 0.7071;  // Butterworth: respuesta plana
  float w0 = 2 * PI * freq / sampleRate;
  float cosw = cosf(w0);
  float alpha = sinf(w0) / (2 * q);
  float a0 = 1 + alpha;
  Biquad f;
  if (highPass) {
    f.b0 = (1 + cosw) / 2 / a0;
    f.b1 = -(1 + cosw) / a0;
  } else {
    f.b0 = (1 - cosw) / 2 / a0;
    f.b1 = (1 - cosw) / a0;
  }
  f.b2 = f.b0;
  f.a1 = -2 * cosw / a0;
  f.a2 = (1 - alpha) / a0;
  return f;
}

// ---------- Estado ----------

static Biquad voiceHighPass, voiceLowPass, bassHighPass, bassLowPass;

enum MouthState { CLOSED, KICK, HOLD, SHUTTING };
static MouthState state = CLOSED;
static unsigned long stateAt = 0;
static unsigned long openedAt = 0;

static float envelope = 0;
static float noiseFloor = -1;  // -1 = todavía sin medir
static float bassAverage = 0;
static float lastBass = 0;
static bool lastBeat = false;
static unsigned long lastBeatAt = 0;
static unsigned long tailUntil = 0;

void mouthSyncBegin(int sampleRate) {
  voiceHighPass = makeFilter(true, 300, sampleRate);
  voiceLowPass = makeFilter(false, 3000, sampleRate);
  bassHighPass = makeFilter(true, 40, sampleRate);  // también quita el nivel de DC
  bassLowPass = makeFilter(false, 150, sampleRate);
}

static void setState(MouthState s, unsigned long now) {
  state = s;
  stateAt = now;
}

static void updateMouth(unsigned long now) {
  float openLevel = max(noiseFloor * OPEN_RATIO, MIN_OPEN_LEVEL);
  float closeLevel = max(noiseFloor * CLOSE_RATIO, MIN_OPEN_LEVEL * 0.7f);

  switch (state) {
    case CLOSED:
      if (envelope > openLevel && now - stateAt >= MIN_CLOSED_MS) {
        mouthOpen(255);
        openedAt = now;
        setState(KICK, now);
      }
      break;
    case KICK:
      if (now - stateAt >= KICK_MS) {
        mouthOpen(HOLD_STRENGTH);
        setState(HOLD, now);
      }
      break;
    case HOLD: {
      bool quiet = envelope < closeLevel && now - openedAt >= MIN_OPEN_MS;
      if (quiet || now - openedAt > MAX_HOLD_MS) {
        mouthShut(255);
        setState(SHUTTING, now);
      }
      break;
    }
    case SHUTTING:
      if (now - stateAt >= SHUT_MS) {
        mouthClose();
        setState(CLOSED, now);
      }
      break;
  }
}

static void updateTail(unsigned long now, float bass) {
  bool soundPresent = state != CLOSED;
  lastBeat = bass > bassAverage * BEAT_RATIO && bass > MIN_BEAT_LEVEL && now - lastBeatAt > BEAT_GAP_MS;
  bool periodic = soundPresent && now - lastBeatAt > TAIL_INTERVAL_MS;
  if (lastBeat || periodic) {
    tailOut();
    tailUntil = now + TAIL_MS;
    lastBeatAt = now;
  }
  bassAverage += 0.05f * (bass - bassAverage);

  if (tailUntil && now > tailUntil) {
    tailRelax();
    tailUntil = 0;
  }
}

void mouthSyncProcess(const float *samples, int n) {
  // Volumen (RMS) de cada banda en este bloque
  float voiceSum = 0, bassSum = 0;
  for (int i = 0; i < n; i++) {
    float v = voiceLowPass.process(voiceHighPass.process(samples[i]));
    float b = bassLowPass.process(bassHighPass.process(samples[i]));
    voiceSum += v * v;
    bassSum += b * b;
  }
  float voice = sqrtf(voiceSum / n);
  float bass = sqrtf(bassSum / n);

  // Envolvente con ataque rápido y caída lenta
  envelope += (voice > envelope ? ATTACK : RELEASE) * (voice - envelope);

  // Ruido de fondo: sigue al mínimo, sube muy despacio
  if (noiseFloor < 0 || envelope < noiseFloor) {
    noiseFloor = envelope;
  } else {
    noiseFloor += FLOOR_RISE * (envelope - noiseFloor);
  }

  unsigned long now = millis();
  updateMouth(now);
  updateTail(now, bass);
  lastBass = bass;
}

MouthSyncDebug mouthSyncDebug() {
  return {envelope, noiseFloor, lastBass, state == KICK || state == HOLD, lastBeat};
}
