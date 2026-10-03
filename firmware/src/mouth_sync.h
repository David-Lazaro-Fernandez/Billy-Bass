#pragma once

#include <Arduino.h>

// Sincroniza la boca (y la cola) con un audio, venga de donde venga: micrófono, Bluetooth o TTS.
//
//   audio ─► filtro banda de voz (300–3000 Hz) ─► envolvente ─► BOCA (abrir / sostener / cerrar)
//         └► filtro de graves (40–150 Hz) ──────► golpes ────► COLA
//
// Se llama con bloques cortos de audio (~20 ms) y mueve los motores sin bloquear.

void mouthSyncBegin(int sampleRate);
void mouthSyncProcess(const float *samples, int n);

// Valores internos para ajustar umbrales por el monitor serie.
struct MouthSyncDebug {
  float envelope;    // volumen de la banda de voz, suavizado
  float noiseFloor;  // nivel de ruido de fondo estimado
  float bass;        // volumen de graves en el último bloque
  bool mouthOpen;
  bool beat;         // hubo golpe de graves en el último bloque
};
MouthSyncDebug mouthSyncDebug();
