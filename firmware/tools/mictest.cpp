// Herramienta: prueba del micrófono MAX4466 en GPIO 34.
// Imprime el nivel de sonido como barra; sirve para verificar conexión y ajustar la ganancia.

#include <Arduino.h>

const int MIC_PIN = 34;
const int WINDOW_MS = 50;  // ventana para medir el volumen

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);        // valores de 0 a 4095
  analogSetAttenuation(ADC_11db);  // rango completo de 0 a 3.3 V
  Serial.println("Prueba de micrófono: habla cerca del micrófono");
}

void loop() {
  int minVal = 4095, maxVal = 0;
  long sum = 0, count = 0;
  unsigned long start = millis();
  while (millis() - start < WINDOW_MS) {
    int v = analogRead(MIC_PIN);
    if (v < minVal) minVal = v;
    if (v > maxVal) maxVal = v;
    sum += v;
    count++;
  }
  int level = maxVal - minVal;  // amplitud pico a pico = volumen
  int center = sum / count;     // en reposo debería rondar 2048 (la mitad de 3.3 V)

  int bars = map(constrain(level, 0, 2000), 0, 2000, 0, 40);
  Serial.printf("centro=%4d nivel=%4d |", center, level);
  for (int i = 0; i < bars; i++) Serial.print('#');
  Serial.println();
  delay(100);
}
