// Herramienta: manda el micrófono a la PC por WiFi para escuchar su calidad.
//   pio run -e micstream -t upload        (antes: copiar src/secrets.example.h como src/secrets.h)
//   python server/mic_receiver.py         (en la PC; graba un WAV en server/recordings/)
//
// Por el monitor serie: la tecla "m" prende / apaga los motores. Con motores prendidos la boca sigue lo
// que oye el micrófono, para escuchar cuánto ruido de motor se cuela en la grabación.

#include <Arduino.h>
#include <WiFi.h>
#include "mic_dma.h"
#include "motors.h"
#include "mouth_sync.h"
#include "voice_link.h"

const int LED_PIN = 2;
const int SAMPLE_RATE = 16000;            // lo que esperan Vosk y Whisper
const int BLOCK_SIZE = SAMPLE_RATE / 50;  // bloques de 20 ms
const float MIN_OPEN_LEVEL = 80;          // arriba del ruido de los motores (~40)

static float block[BLOCK_SIZE];
static bool motorsOn = false;

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  motorsBegin();
  mouthSyncBegin(SAMPLE_RATE, MIN_OPEN_LEVEL);

  Serial.println("Conectando al WiFi...");
  voiceLinkBegin(15000);
  micDmaBegin(SAMPLE_RATE);
  Serial.println("Tecla m: prender / apagar motores");
}

void loop() {
  micDmaRead(block, BLOCK_SIZE);
  if (motorsOn) mouthSyncProcess(block, BLOCK_SIZE);
  bool busy = motorsOn && mouthSyncDebug().mouthOpen;
  voiceLinkSend(block, BLOCK_SIZE, SAMPLE_RATE, busy);
  digitalWrite(LED_PIN, voiceLinkConnected() ? HIGH : LOW);

  if (Serial.available() && Serial.read() == 'm') {
    motorsOn = !motorsOn;
    if (!motorsOn) motorsStopAll();
    Serial.printf("Motores %s\n", motorsOn ? "PRENDIDOS" : "apagados");
  }

  // Cada 2 s: muestras por segundo reales (debe dar ~16000) y estado del WiFi
  static unsigned long lastPrint = millis();
  static uint32_t samples = 0;
  samples += BLOCK_SIZE;
  if (millis() - lastPrint >= 2000) {
    float rate = samples * 1000.0f / (millis() - lastPrint);
    Serial.printf("muestras/s=%.0f paquetes=%u wifi=%s rssi=%d motores=%s\n", rate, voiceLinkPacketsSent(),
                  voiceLinkConnected() ? "ok" : "NO", WiFi.RSSI(), motorsOn ? "si" : "no");
    samples = 0;
    lastPrint = millis();
  }
}
