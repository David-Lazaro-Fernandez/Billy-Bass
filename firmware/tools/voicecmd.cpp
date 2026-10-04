// Comandos por voz, sin Bluetooth todavía: el pez manda el micrófono a la PC (server/voice_server.py), la PC
// reconoce "Billy, <comando>" y le regresa el comando; el pez responde con un gesto.
//   pio run -e voicecmd -t upload        (requiere src/secrets.h)
//   python server/voice_server.py
//
// Los comandos de música (pausa, siguiente, volumen...) solo se confirman con un gesto: necesitan el Bluetooth,
// que se junta con el WiFi en el siguiente paso (A3 en docs/plan-voice-commands.md).

#include <Arduino.h>
#include "gestures.h"
#include "mic_dma.h"
#include "motors.h"
#include "voice_link.h"

const int LED_PIN = 2;
const int SAMPLE_RATE = 16000;
const int BLOCK_SIZE = SAMPLE_RATE / 50;  // bloques de 20 ms

static float block[BLOCK_SIZE];

static void runCommand(const char *command) {
  Serial.printf("Comando: %s\n", command);
  if (strcmp(command, "escuchando") == 0) {
    gestureStart(GESTURE_LISTENING);
  } else if (strcmp(command, "no_entendi") == 0) {
    gestureStart(GESTURE_NOT_UNDERSTOOD);
  } else if (strcmp(command, "baila") == 0) {
    gestureStart(GESTURE_DANCE);
  } else if (strcmp(command, "callate") == 0) {
    gestureStop();  // quedarse quieto es la respuesta
  } else {
    // pausa, play, siguiente, anterior, volumen, modos: todavía sin Bluetooth
    Serial.println("  (este comando necesita el Bluetooth; por ahora solo se confirma)");
    gestureStart(GESTURE_UNDERSTOOD);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  motorsBegin();
  voiceLinkBegin(15000);
  micDmaBegin(SAMPLE_RATE);
  Serial.println("Di \"Billy, baila\" (el servidor debe estar corriendo)");
}

void loop() {
  micDmaRead(block, BLOCK_SIZE);
  bool busy = gestureUpdate();  // mientras se mueve, el servidor ignora lo que oye (ruido de motores)
  voiceLinkSend(block, BLOCK_SIZE, SAMPLE_RATE, busy);

  char command[32];
  if (voiceLinkPollCommand(command, sizeof(command))) runCommand(command);

  digitalWrite(LED_PIN, voiceLinkConnected() ? HIGH : LOW);
}
