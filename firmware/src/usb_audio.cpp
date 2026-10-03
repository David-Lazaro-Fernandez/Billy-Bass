#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/stream_buffer.h>
#include "usb_audio.h"

const int DECIMATION = 3;
const int BUFFER_BYTES = 16384;  // ~0.5 s de audio a 14.7 kHz
const int PACKET_SAMPLES = 256;

static StreamBufferHandle_t buffer = nullptr;
static volatile int outputRate = 0;

// Estado del diezmado entre bloques
static float accum = 0;
static int accumCount = 0;

void usbAudioBegin() {
  buffer = xStreamBufferCreate(BUFFER_BYTES, 1);
}

void usbAudioPush(const float *samples, int n, int sampleRate) {
  if (!buffer) return;
  outputRate = sampleRate / DECIMATION;

  int16_t out[400];
  int count = 0;
  for (int i = 0; i < n; i++) {
    // Promediar 3 muestras funciona como un filtro pasa-bajas sencillo antes de reducir la frecuencia
    accum += samples[i];
    if (++accumCount == DECIMATION) {
      float v = accum / DECIMATION * 16.0f;  // regresar de la escala ±2048 a ±32768
      out[count++] = (int16_t)constrain(v, -32768.0f, 32767.0f);
      accum = 0;
      accumCount = 0;
      if (count == 400) {
        xStreamBufferSend(buffer, out, count * 2, 0);  // si el buffer está lleno, se descarta
        count = 0;
      }
    }
  }
  if (count) xStreamBufferSend(buffer, out, count * 2, 0);
}

void usbAudioPump() {
  if (!buffer) return;
  int16_t packet[PACKET_SAMPLES];
  while (xStreamBufferBytesAvailable(buffer) >= PACKET_SAMPLES * 2) {
    size_t bytes = xStreamBufferReceive(buffer, packet, sizeof(packet), 0);
    uint16_t n = bytes / 2;
    uint16_t rate = outputRate;
    uint8_t header[6] = {0xAA, 0x55, (uint8_t)(rate & 0xFF), (uint8_t)(rate >> 8), (uint8_t)(n & 0xFF),
                         (uint8_t)(n >> 8)};
    Serial.write(header, sizeof(header));
    Serial.write((const uint8_t *)packet, n * 2);
  }
}
