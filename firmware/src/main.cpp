// Billy Bass: la boca y la cola siguen el audio.
//
// Fuente de audio (se elige al compilar):
//   - Bluetooth (por defecto): el pez aparece como bocina "Billy Bass"; el audio del celular mueve la boca.
//     Mientras no hay amplificador, el audio se reenvía por USB (tools/usb_speaker.py lo reproduce en la PC).
//   - Micrófono (env micsync, -DAUDIO_SOURCE_MIC): reacciona a lo que escucha.
// La lógica de movimiento está en src/mouth_sync.cpp.
//
// Con -DVOICE_COMMANDS (env bassvoice), además del Bluetooth: el micrófono va por WiFi a la PC
// (server/voice_server.py) y los comandos "Billy, pausa / siguiente / súbele / baila..." controlan el celular y
// el pez. Requiere src/secrets.h.

#include <Arduino.h>
#include "motors.h"
#include "mouth_sync.h"

#ifdef AUDIO_SOURCE_MIC
#include "mic.h"
#else
#include "bt_audio.h"
#include "usb_audio.h"
#endif

#ifdef VOICE_COMMANDS
#include "gestures.h"
#include "mic_dma.h"
#include "voice_link.h"

const int MIC_RATE = 16000;
const int MIC_BLOCK = MIC_RATE / 50;  // bloques de 20 ms
const int VOLUME_STEP = 16;           // de 127
static float micBlock[MIC_BLOCK];
static volatile bool gestureBusy = false;  // un gesto usa los motores: la boca deja de seguir la música

static void runVoiceCommand(const char *command) {
  Serial.printf("Comando: %s\n", command);
  if (strcmp(command, "escuchando") == 0) {
    gestureStart(GESTURE_LISTENING);
    return;
  }
  if (strcmp(command, "no_entendi") == 0) {
    gestureStart(GESTURE_NOT_UNDERSTOOD);
    return;
  }
  if (strcmp(command, "baila") == 0) {
    gestureStart(GESTURE_DANCE);
    return;
  }

  // Los demás se confirman con un aleteo de cola (que además corta un baile en curso)
  if (strcmp(command, "pausa") == 0) btAudioPause();  // también "cállate", "detente", "silencio"
  else if (strcmp(command, "play") == 0) btAudioPlay();
  else if (strcmp(command, "siguiente") == 0) btAudioNext();
  else if (strcmp(command, "anterior") == 0) btAudioPrevious();
  else if (strcmp(command, "subir_volumen") == 0) btAudioVolumeStep(VOLUME_STEP);
  else if (strcmp(command, "bajar_volumen") == 0) btAudioVolumeStep(-VOLUME_STEP);
  // modo_bocina / modo_asistente: con Bluetooth y WiFi juntos no hacen falta modos; solo se confirma
  gestureStart(GESTURE_UNDERSTOOD);
}
#endif

const int LED_PIN = 2;
const char *BT_NAME = "Billy Bass";

#ifdef AUDIO_SOURCE_MIC
const int SAMPLE_RATE = 8000;             // suficiente para la banda de voz (hasta 3 kHz)
const int BLOCK_SIZE = SAMPLE_RATE / 50;  // bloques de 20 ms
const float MIN_OPEN_LEVEL = 80;          // arriba del ruido de los motores (~40)
float block[BLOCK_SIZE];
#else
static int currentRate = 0;
const float MIN_OPEN_LEVEL = 15;  // ~−43 dBFS; el silencio digital es 0

// Se llama desde la tarea de Bluetooth con cada bloque de audio recibido
void onBluetoothAudio(const float *samples, int n, int sampleRate) {
  if (sampleRate != currentRate) {
    mouthSyncBegin(sampleRate, MIN_OPEN_LEVEL);
    currentRate = sampleRate;
  }
#ifdef VOICE_COMMANDS
  if (!gestureBusy) mouthSyncProcess(samples, n);
#else
  mouthSyncProcess(samples, n);
#endif
  usbAudioPush(samples, n, sampleRate);
}
#endif

void setup() {
#ifdef AUDIO_SOURCE_MIC
  Serial.begin(115200);
#else
  Serial.begin(USB_AUDIO_BAUD);
  usbAudioBegin();
#endif
  pinMode(LED_PIN, OUTPUT);
  motorsBegin();

#ifdef AUDIO_SOURCE_MIC
  micBegin();
  mouthSyncBegin(SAMPLE_RATE, MIN_OPEN_LEVEL);
  Serial.println("Billy Bass: sincronizando boca con el microfono");
#else
  btAudioBegin(BT_NAME, onBluetoothAudio);
  Serial.printf("Billy Bass: busca \"%s\" en el Bluetooth de tu celular\n", BT_NAME);
#endif
#ifdef VOICE_COMMANDS
  voiceLinkBegin(15000);
  micDmaBegin(MIC_RATE);
  Serial.printf("Comandos de voz activos. Memoria libre: %u bytes\n", ESP.getFreeHeap());
#endif
}

void loop() {
#ifdef AUDIO_SOURCE_MIC
  micReadBlock(block, BLOCK_SIZE, SAMPLE_RATE);
  mouthSyncProcess(block, BLOCK_SIZE);
#else
  usbAudioPump();
#ifdef VOICE_COMMANDS
  micDmaRead(micBlock, MIC_BLOCK);  // espera ~20 ms: marca el ritmo del loop
  gestureBusy = gestureUpdate();
  voiceLinkSend(micBlock, MIC_BLOCK, MIC_RATE, gestureBusy);
  char command[32];
  if (voiceLinkPollCommand(command, sizeof(command))) runVoiceCommand(command);
#else
  delay(5);
#endif
#endif

  MouthSyncDebug d = mouthSyncDebug();
  digitalWrite(LED_PIN, d.mouthOpen ? HIGH : LOW);

  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 500) {
#ifndef AUDIO_SOURCE_MIC
    if (!btAudioConnected()) {
      if (millis() - lastPrint > 3000) {
        Serial.println("Esperando conexion Bluetooth...");
        lastPrint = millis();
      }
      return;
    }
#endif
    Serial.printf("voz=%5.0f ruido=%4.0f pico=%5.0f graves=%5.0f boca=%s%s\n", d.envelope, d.noiseFloor,
                  d.peak, d.bass,
                  d.mouthOpen ? "ABIERTA" : "cerrada", d.beat ? " [cola]" : "");
#ifdef VOICE_COMMANDS
    Serial.printf("memoria libre=%u (minima=%u, bloque mayor=%u) wifi=%s\n", ESP.getFreeHeap(),
                  ESP.getMinFreeHeap(), ESP.getMaxAllocHeap(), voiceLinkConnected() ? "ok" : "NO");
#endif
    lastPrint = millis();
  }
}
