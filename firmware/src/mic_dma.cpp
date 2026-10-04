#include <Arduino.h>
#include <driver/adc.h>
#include <driver/i2s.h>
#include "mic_dma.h"

const i2s_port_t PORT = I2S_NUM_0;              // el modo ADC integrado solo existe en I2S0
const adc1_channel_t CHANNEL = ADC1_CHANNEL_6;  // GPIO 34
const int DMA_BUFFER_LEN = 640;                 // muestras por búfer de DMA (20 ms a 32 kHz)

// En modo ADC el driver no respeta frecuencias bajas: medido el 2026-10-03, pedir 8 o 16 kHz da 44 y 88 kHz,
// pero 22, 32 y 44 kHz salen bien (~0.4 % abajo). Por eso se muestrea al doble y se reduce a la mitad
// en software, con un pasa-bajas antes para que lo de arriba de 8 kHz no se "doble" hacia la voz.
const int OVERSAMPLE = 2;

// Pasa-bajas Butterworth de 4.º orden (dos biquads) a 0.4 × la frecuencia final, aplicado a la frecuencia
// del ADC. Fórmulas del Audio EQ Cookbook, igual que en mouth_sync.cpp.
struct LowPass {
  float b0, b1, b2, a1, a2;
  float x1 = 0, x2 = 0, y1 = 0, y2 = 0;

  void setup(float freq, int sampleRate, float q) {
    float w0 = 2 * PI * freq / sampleRate;
    float cosw = cosf(w0);
    float alpha = sinf(w0) / (2 * q);
    float a0 = 1 + alpha;
    b0 = (1 - cosw) / 2 / a0;
    b1 = (1 - cosw) / a0;
    b2 = b0;
    a1 = -2 * cosw / a0;
    a2 = (1 - alpha) / a0;
  }

  float process(float x) {
    float y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1;
    x1 = x;
    y2 = y1;
    y1 = y;
    return y;
  }
};

static LowPass stage1, stage2;

void micDmaBegin(int sampleRate) {
  int adcRate = sampleRate * OVERSAMPLE;
  stage1.setup(sampleRate * 0.4f, adcRate, 0.5412);  // Q de las dos etapas de un Butterworth de 4.º orden
  stage2.setup(sampleRate * 0.4f, adcRate, 1.3066);

  i2s_config_t config = {};
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_ADC_BUILT_IN);
  config.sample_rate = adcRate;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.dma_buf_count = 4;
  config.dma_buf_len = DMA_BUFFER_LEN;
  i2s_driver_install(PORT, &config, 0, nullptr);
  i2s_set_adc_mode(ADC_UNIT_1, CHANNEL);
  adc1_config_channel_atten(CHANNEL, ADC_ATTEN_DB_12);  // rango completo de 0 a 3.3 V
  i2s_adc_enable(PORT);
}

void micDmaRead(float *samples, int n) {
  static uint16_t raw[DMA_BUFFER_LEN];
  int done = 0;
  while (done < n) {
    int want = min((n - done) * OVERSAMPLE, DMA_BUFFER_LEN);  // siempre par
    size_t bytes = 0;
    i2s_read(PORT, raw, want * sizeof(uint16_t), &bytes, portMAX_DELAY);
    int got = bytes / sizeof(uint16_t) & ~1;
    for (int i = 0; i < got; i++) {
      // El DMA del ESP32 entrega las muestras en pares invertidos (1, 0, 3, 2...): i ^ 1 las ordena.
      // Los 4 bits altos de cada palabra son el número de canal; los 12 bajos, la lectura.
      float filtered = stage2.process(stage1.process(raw[i ^ 1] & 0x0FFF));
      if (i % OVERSAMPLE == OVERSAMPLE - 1) samples[done++] = filtered;
    }
  }
}
