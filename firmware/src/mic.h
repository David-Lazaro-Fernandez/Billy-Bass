#pragma once

#include <Arduino.h>

// Micrófono analógico MAX4466 conectado a un pin ADC1.

void micBegin();

// Volumen actual: amplitud pico a pico medida durante windowMs (0 = silencio, ~2000 = muy fuerte).
int micLevel(int windowMs = 30);

// Lee un bloque de n muestras a sampleRate Hz (bloqueante: tarda n / sampleRate segundos).
void micReadBlock(float *samples, int n, int sampleRate);
