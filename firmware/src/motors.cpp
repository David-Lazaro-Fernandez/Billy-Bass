#include <Arduino.h>
#include "motors.h"

// Pines hacia el driver de motores (ver docs/wiring.md)
const int MOUTH_IN1 = 18;  // L298N IN1 (MOTOR A)
const int MOUTH_IN2 = 19;  // L298N IN2
const int TAIL_IN1 = 16;   // L298N IN3 (MOTOR B)
const int TAIL_IN2 = 17;   // L298N IN4

// Canales PWM del ESP32, uno por pin
const int CH_MOUTH_IN1 = 0;
const int CH_MOUTH_IN2 = 1;
const int CH_TAIL_IN1 = 2;
const int CH_TAIL_IN2 = 3;

// Si un motor se mueve en el sentido contrario, cambia su valor a true.
const bool TAIL_REVERSED = true;  // en este pez la cola sale con IN4
const bool MOUTH_REVERSED = true;  // en este pez la boca abre con IN2

// El L298N es lento: a 20 kHz casi no entrega corriente. 1 kHz funciona (se escucha un leve zumbido).
// Con un DRV8833 se puede volver a 20 kHz.
const int PWM_FREQ = 1000;
const int PWM_BITS = 8;  // fuerza de 0 a 255

static void setupChannel(int pin, int channel) {
  ledcSetup(channel, PWM_FREQ, PWM_BITS);
  ledcAttachPin(pin, channel);
  ledcWrite(channel, 0);
}

// Un canal del driver: IN1 con PWM = un sentido, IN2 con PWM = el otro, ambos en 0 = libre.
static void drive(int ch1, int ch2, int speed) {
  if (speed > 0) {
    ledcWrite(ch1, speed);
    ledcWrite(ch2, 0);
  } else if (speed < 0) {
    ledcWrite(ch1, 0);
    ledcWrite(ch2, -speed);
  } else {
    ledcWrite(ch1, 0);
    ledcWrite(ch2, 0);
  }
}

void motorsBegin() {
  setupChannel(TAIL_IN1, CH_TAIL_IN1);
  setupChannel(TAIL_IN2, CH_TAIL_IN2);
  setupChannel(MOUTH_IN1, CH_MOUTH_IN1);
  setupChannel(MOUTH_IN2, CH_MOUTH_IN2);
}

void mouthOpen(uint8_t strength) { drive(CH_MOUTH_IN1, CH_MOUTH_IN2, MOUTH_REVERSED ? -strength : strength); }
void mouthShut(uint8_t strength) { drive(CH_MOUTH_IN1, CH_MOUTH_IN2, MOUTH_REVERSED ? strength : -strength); }
void mouthClose() { drive(CH_MOUTH_IN1, CH_MOUTH_IN2, 0); }

void tailOut(uint8_t strength) { drive(CH_TAIL_IN1, CH_TAIL_IN2, TAIL_REVERSED ? -strength : strength); }
void tailRelax() { drive(CH_TAIL_IN1, CH_TAIL_IN2, 0); }

void motorsStopAll() {
  mouthClose();
  tailRelax();
}
