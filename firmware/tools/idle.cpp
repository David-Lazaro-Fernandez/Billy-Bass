// Herramienta: deja todos los motores apagados (IN1-IN4 en LOW). Útil para "pausar" el pez.

#include <Arduino.h>

const int PINS[] = {18, 19, 16, 17};

void setup() {
  Serial.begin(115200);
  for (int pin : PINS) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  Serial.println("Motores en pausa");
}

void loop() {
  delay(1000);
}
