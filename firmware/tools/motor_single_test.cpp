// Herramienta: mueve un solo motor del L298N a corriente completa, en ambos sentidos.
// Sirve para identificar qué motor está conectado en cada canal y si funciona.
// El canal se elige con build_flags en platformio.ini (envs motora / motorb).
// Con WIGGLE_MS definido, cambia de sentido cada WIGGLE_MS (vaivén) para destrabar o medir fuerza.

#include <Arduino.h>

#ifndef MOTOR_NAME
#define MOTOR_NAME "A"
#define PIN_1 18
#define PIN_2 19
#endif

void setup() {
  Serial.begin(115200);
  pinMode(PIN_1, OUTPUT);
  pinMode(PIN_2, OUTPUT);
  digitalWrite(PIN_1, LOW);
  digitalWrite(PIN_2, LOW);
  Serial.println("Prueba del MOTOR " MOTOR_NAME);
}

#ifdef WIGGLE_MS
void loop() {
  digitalWrite(PIN_1, HIGH);
  delay(WIGGLE_MS);
  digitalWrite(PIN_1, LOW);
  delay(50);  // pausa breve: invertir de golpe genera picos de corriente
  digitalWrite(PIN_2, HIGH);
  delay(WIGGLE_MS);
  digitalWrite(PIN_2, LOW);
  delay(50);
}
#else
void loop() {
  Serial.println("Motor " MOTOR_NAME ": sentido 1");
  digitalWrite(PIN_1, HIGH);
  delay(2000);
  digitalWrite(PIN_1, LOW);
  delay(1000);

  Serial.println("Motor " MOTOR_NAME ": sentido 2");
  digitalWrite(PIN_2, HIGH);
  delay(2000);
  digitalWrite(PIN_2, LOW);
  delay(1000);
}
#endif
