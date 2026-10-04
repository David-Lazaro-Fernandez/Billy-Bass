#include <Arduino.h>
#include "gestures.h"
#include "motors.h"

enum Action { MOUTH_OPEN, MOUTH_SHUT, MOUTH_RELEASE, TAIL_OUT, TAIL_RELAX };

// Cada paso hace una acción y espera ms antes del siguiente. Abrir y cerrar la boca usa los mismos tiempos que
// mouth_sync.cpp: patada al abrir, motor al revés 80 ms para cerrar rápido, y soltar.
struct Step {
  Action action;
  uint16_t ms;
};

#define MOUTH_FLAP {MOUTH_OPEN, 150}, {MOUTH_SHUT, 80}, {MOUTH_RELEASE, 150}

static const Step LISTENING[] = {{MOUTH_OPEN, 150}, {MOUTH_SHUT, 80}, {MOUTH_RELEASE, 0}};
static const Step UNDERSTOOD[] = {{TAIL_OUT, 300}, {TAIL_RELAX, 0}};
static const Step NOT_UNDERSTOOD[] = {MOUTH_FLAP, MOUTH_FLAP};
static const Step DANCE[] = {
    {TAIL_OUT, 250}, {TAIL_RELAX, 100}, MOUTH_FLAP,
    {TAIL_OUT, 250}, {TAIL_RELAX, 100}, MOUTH_FLAP,
    {TAIL_OUT, 250}, {TAIL_RELAX, 100}, MOUTH_FLAP, MOUTH_FLAP,
    {TAIL_OUT, 250}, {TAIL_RELAX, 100}, MOUTH_FLAP,
    {TAIL_OUT, 400}, {TAIL_RELAX, 0},
};

static const Step *steps = nullptr;
static int stepCount = 0;
static int stepIndex = 0;
static unsigned long stepAt = 0;

static void perform(Action action) {
  switch (action) {
    case MOUTH_OPEN: mouthOpen(255); break;
    case MOUTH_SHUT: mouthShut(255); break;
    case MOUTH_RELEASE: mouthClose(); break;
    case TAIL_OUT: tailOut(255); break;
    case TAIL_RELAX: tailRelax(); break;
  }
}

void gestureStart(Gesture gesture) {
  switch (gesture) {
    case GESTURE_LISTENING: steps = LISTENING; stepCount = sizeof(LISTENING) / sizeof(Step); break;
    case GESTURE_UNDERSTOOD: steps = UNDERSTOOD; stepCount = sizeof(UNDERSTOOD) / sizeof(Step); break;
    case GESTURE_NOT_UNDERSTOOD:
      steps = NOT_UNDERSTOOD;
      stepCount = sizeof(NOT_UNDERSTOOD) / sizeof(Step);
      break;
    case GESTURE_DANCE: steps = DANCE; stepCount = sizeof(DANCE) / sizeof(Step); break;
  }
  motorsStopAll();
  stepIndex = 0;
  stepAt = millis();
  perform(steps[0].action);
}

void gestureStop() {
  steps = nullptr;
  motorsStopAll();
}

bool gestureUpdate() {
  if (!steps) return false;
  unsigned long now = millis();
  if (now - stepAt < steps[stepIndex].ms) return true;
  stepIndex++;
  if (stepIndex >= stepCount) {
    steps = nullptr;
    motorsStopAll();
    return false;
  }
  stepAt = now;
  perform(steps[stepIndex].action);
  return true;
}
