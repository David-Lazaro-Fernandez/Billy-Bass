#pragma once

#include <Arduino.h>

// Micrófono MAX4466 (GPIO 34) leído por DMA: el ADC muestrea solo, a ritmo fijo, y el código recoge bloques.
// A diferencia de micReadBlock() (analogRead en un bucle), no ocupa el CPU mientras espera y aguanta WiFi.
// Usa I2S0 en modo "ADC integrado", así que la bocina (MAX98357A) tendrá que ir en I2S1.

void micDmaBegin(int sampleRate);

// Espera hasta tener n muestras. Escala igual que analogRead (0–4095, reposo ~1930).
void micDmaRead(float *samples, int n);
