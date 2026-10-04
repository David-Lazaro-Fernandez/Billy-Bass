#include <Arduino.h>
#include "BluetoothA2DPSink.h"
#include "esp_avrc_api.h"
#include "bt_audio.h"

static BluetoothA2DPSink a2dpSink;
static BtAudioCallback userCallback = nullptr;

const int MAX_FRAMES = 1024;
static float monoBlock[MAX_FRAMES];

// A2DP entrega PCM de 16 bits, estéreo intercalado (L, R, L, R...), normalmente a 44.1 kHz.
static void onAudioData(const uint8_t *data, uint32_t length) {
  if (!userCallback) return;

  const int16_t *pcm = (const int16_t *)data;
  int frames = length / 4;  // 2 canales x 2 bytes
  int sampleRate = a2dpSink.sample_rate();

  for (int start = 0; start < frames; start += MAX_FRAMES) {
    int n = min(MAX_FRAMES, frames - start);
    for (int i = 0; i < n; i++) {
      int idx = (start + i) * 2;
      // Mezcla a mono y escala de ±32768 a ±2048 para usar los mismos umbrales que el micrófono
      monoBlock[i] = (pcm[idx] + pcm[idx + 1]) / 2.0f / 16.0f;
    }
    userCallback(monoBlock, n, sampleRate);
  }
}

void btAudioBegin(const char *deviceName, BtAudioCallback callback) {
  userCallback = callback;
  // I2S0 es del micrófono (mic_dma.cpp). Aunque la salida esté apagada, la librería configura y arranca su
  // puerto al conectar el celular: en I2S0 rompía el micrófono. La bocina (MAX98357A) irá en I2S1.
  a2dpSink.set_i2s_port(I2S_NUM_1);
  // false = no mandar el audio a I2S todavía (no hay amplificador)
  a2dpSink.set_stream_reader(onAudioData, false);
  a2dpSink.start(deviceName);
}

bool btAudioConnected() {
  return a2dpSink.is_connected();
}

// Botón de control remoto (AVRCP "passthrough"): presionar y soltar. La librería usa siempre la etiqueta de
// transacción 0, y algunos celulares descartan comandos repetidos; aquí cada envío usa una etiqueta nueva (0–15).
static void sendButton(uint8_t button, const char *name) {
  static uint8_t label = 0;
  esp_err_t pressed = esp_avrc_ct_send_passthrough_cmd(label, button, ESP_AVRC_PT_CMD_STATE_PRESSED);
  label = (label + 1) & 0x0F;
  delay(50);
  esp_err_t released = esp_avrc_ct_send_passthrough_cmd(label, button, ESP_AVRC_PT_CMD_STATE_RELEASED);
  label = (label + 1) & 0x0F;
  Serial.printf("AVRCP %s: %s / %s\n", name, esp_err_to_name(pressed), esp_err_to_name(released));
}

void btAudioPlay() {
  sendButton(ESP_AVRC_PT_CMD_PLAY, "play");
}

void btAudioPause() {
  sendButton(ESP_AVRC_PT_CMD_PAUSE, "pausa");
}

void btAudioNext() {
  sendButton(ESP_AVRC_PT_CMD_FORWARD, "siguiente");
}

void btAudioPrevious() {
  sendButton(ESP_AVRC_PT_CMD_BACKWARD, "anterior");
}

void btAudioVolumeStep(int step) {
  a2dpSink.set_volume(constrain(a2dpSink.get_volume() + step, 0, 127));
}
