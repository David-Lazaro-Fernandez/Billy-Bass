#pragma once

#include <Arduino.h>

// El ESP32 aparece como bocina Bluetooth (A2DP) y entrega el audio recibido en bloques mono.
// Por ahora no se reproduce: falta el amplificador MAX98357A (fase 3).

// Recibe muestras mono en float (escala de ±2048, igual que el micrófono) a sampleRate Hz.
typedef void (*BtAudioCallback)(const float *samples, int n, int sampleRate);

void btAudioBegin(const char *deviceName, BtAudioCallback callback);
bool btAudioConnected();
