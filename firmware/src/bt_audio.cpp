#include <Arduino.h>
#include "BluetoothA2DPSink.h"
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
  // false = no mandar el audio a I2S todavía (no hay amplificador)
  a2dpSink.set_stream_reader(onAudioData, false);
  a2dpSink.start(deviceName);
}

bool btAudioConnected() {
  return a2dpSink.is_connected();
}
