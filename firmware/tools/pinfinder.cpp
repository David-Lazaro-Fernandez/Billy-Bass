// Herramienta: identifica qué GPIO hay en cada fila del protoboard.
// Conecta un jumper a GND y toca cada pin: el monitor serie dice cuál GPIO es.

#include <Arduino.h>

// Pines con pull-up interno (se omiten TX/RX, flash 6-11 y 34-39 que no tienen pull-up)
const int PINS[] = {0, 2, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33};
const int NUM_PINS = sizeof(PINS) / sizeof(PINS[0]);
bool wasLow[NUM_PINS];

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < NUM_PINS; i++) {
    pinMode(PINS[i], INPUT_PULLUP);
    wasLow[i] = false;
  }
  delay(100);
  Serial.println("Buscador de pines listo: toca cada pin con un jumper conectado a GND");
}

void loop() {
  for (int i = 0; i < NUM_PINS; i++) {
    bool low = digitalRead(PINS[i]) == LOW;
    if (low && !wasLow[i]) {
      Serial.printf(">>> Tocaste GPIO %d\n", PINS[i]);
    }
    wasLow[i] = low;
  }
  delay(30);
}
