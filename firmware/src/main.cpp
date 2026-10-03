// Billy Bass: la boca y la cola siguen el audio.
//
// Fuente de audio (se elige al compilar):
//   - Bluetooth (por defecto): el pez aparece como bocina "Billy Bass"; el audio del celular mueve la boca.
//     Mientras no hay amplificador, el audio se reenvía por USB (tools/usb_speaker.py lo reproduce en la PC).
//   - Micrófono (env micsync, -DAUDIO_SOURCE_MIC): reacciona a lo que escucha.
// La lógica de movimiento está en src/mouth_sync.cpp.

#include <Arduino.h>
#include "motors.h"
#include "mouth_sync.h"

#ifdef AUDIO_SOURCE_MIC
#include "mic.h"
#else
#include "bt_audio.h"
#include "usb_audio.h"
#endif

const int LED_PIN = 2;
const char *BT_NAME = "Billy Bass";

#ifdef AUDIO_SOURCE_MIC
const int SAMPLE_RATE = 8000;             // suficiente para la banda de voz (hasta 3 kHz)
const int BLOCK_SIZE = SAMPLE_RATE / 50;  // bloques de 20 ms
float block[BLOCK_SIZE];
#else
static int currentRate = 0;

// Se llama desde la tarea de Bluetooth con cada bloque de audio recibido
void onBluetoothAudio(const float *samples, int n, int sampleRate) {
  if (sampleRate != currentRate) {
    mouthSyncBegin(sampleRate);
    currentRate = sampleRate;
  }
  mouthSyncProcess(samples, n);
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
  mouthSyncBegin(SAMPLE_RATE);
  Serial.println("Billy Bass: sincronizando boca con el microfono");
#else
  btAudioBegin(BT_NAME, onBluetoothAudio);
  Serial.printf("Billy Bass: busca \"%s\" en el Bluetooth de tu celular\n", BT_NAME);
#endif
}

void loop() {
#ifdef AUDIO_SOURCE_MIC
  micReadBlock(block, BLOCK_SIZE, SAMPLE_RATE);
  mouthSyncProcess(block, BLOCK_SIZE);
#else
  usbAudioPump();
  delay(5);
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
    Serial.printf("voz=%5.0f ruido=%4.0f graves=%5.0f boca=%s%s\n", d.envelope, d.noiseFloor, d.bass,
                  d.mouthOpen ? "ABIERTA" : "cerrada", d.beat ? " [cola]" : "");
    lastPrint = millis();
  }
}
