#pragma once

#include <Arduino.h>

// Gestos cortos de boca y cola para responder a la voz (mientras no hay bocina, son la única respuesta).
// No bloquean: gestureUpdate() avanza la secuencia y hay que llamarla en cada vuelta del loop.

enum Gesture {
  GESTURE_LISTENING,       // "¿sí?": abre la boca una vez (oyó "Billy" y espera el comando)
  GESTURE_UNDERSTOOD,      // aleteo de cola
  GESTURE_NOT_UNDERSTOOD,  // abre la boca dos veces
  GESTURE_DANCE,           // boca y cola alternadas unos segundos
};

void gestureStart(Gesture gesture);
void gestureStop();    // corta el gesto y suelta los motores
bool gestureUpdate();  // devuelve si hay un gesto en curso
