// Herramienta: prueba de motores sin PWM (corriente completa).
// Cada canal gira 2 s en un sentido y 2 s en el otro, para diagnosticar conexiones.

#include <Arduino.h>

const int PINS[] = {18, 19, 16, 17};  // IN1, IN2, IN3, IN4
const char *NAMES[] = {"IN1 (motor A, sentido 1)", "IN2 (motor A, sentido 2)",
                       "IN3 (motor B, sentido 1)", "IN4 (motor B, sentido 2)"};

void setup() {
  Serial.begin(115200);
  for (int pin : PINS) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  Serial.println("Prueba de motores sin PWM");
}

void loop() {
  for (int i = 0; i < 4; i++) {
    Serial.printf("Encendido: %s\n", NAMES[i]);
    digitalWrite(PINS[i], HIGH);
    delay(2000);
    digitalWrite(PINS[i], LOW);
    Serial.println("Apagado");
    delay(1000);
  }
}
