#include <Arduino.h>
#include "mic.h"

const int MIC_PIN = 34;  // ADC1: sigue funcionando con WiFi activo

void micBegin() {
  analogReadResolution(12);        // valores de 0 a 4095
  analogSetAttenuation(ADC_11db);  // rango completo de 0 a 3.3 V
}

int micLevel(int windowMs) {
  int minVal = 4095, maxVal = 0;
  unsigned long start = millis();
  while (millis() - start < (unsigned long)windowMs) {
    int v = analogRead(MIC_PIN);
    if (v < minVal) minVal = v;
    if (v > maxVal) maxVal = v;
  }
  return maxVal - minVal;
}

void micReadBlock(float *samples, int n, int sampleRate) {
  const unsigned long period = 1000000UL / sampleRate;
  unsigned long next = micros();
  for (int i = 0; i < n; i++) {
    while ((long)(micros() - next) < 0) {
    }
    samples[i] = analogRead(MIC_PIN);  // el filtro pasa-altas de mouth_sync quita el nivel de DC (~1930)
    next += period;
  }
}
