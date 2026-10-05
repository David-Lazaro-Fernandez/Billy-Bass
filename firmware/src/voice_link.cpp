#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#if __has_include("secrets.h")
#include "secrets.h"
#else
// Sin secrets.h el resto del firmware compila igual, pero el enlace no intenta conectarse.
#include "secrets.example.h"
#define VOICE_LINK_NO_SECRETS
#endif
#include "voice_link.h"

const int MAX_SAMPLES = 512;
const float DC_TRACK = 0.001;  // sigue el nivel de reposo del micrófono (~1930) muy despacio
const float GAIN = 16;         // de ±2048 (12 bits) a ±32768 (16 bits)

static uint32_t sequence = 0;
static float dcLevel = -1;     // -1 = todavía sin medir
static WiFiUDP *udp = nullptr;  // se crea al conectar: así el programa principal no carga WiFi si no lo usa
static long lastCommandId = -1;
static VoiceLinkAudioCallback audioCallback = nullptr;

// El socket escucha en SERVER_PORT: así el servidor responde a la misma dirección de la que llega el audio.
static bool ensureSocket() {
  if (!voiceLinkConnected()) return false;
  if (!udp) {
    udp = new WiFiUDP();
    udp->begin(SERVER_PORT);
  }
  return true;
}

bool voiceLinkBegin(unsigned long timeoutMs) {
#ifdef VOICE_LINK_NO_SECRETS
  Serial.println("Falta firmware/src/secrets.h (copia secrets.example.h y llena tu red)");
  return false;
#endif
  WiFi.mode(WIFI_STA);
  // El ahorro de energía del WiFi retrasa y agrupa los paquetes, pero con Bluetooth prendido es obligatorio
  // (el ESP32 aborta si se apaga: comparten la radio y se turnan durante el "sueño" del WiFi).
  WiFi.setSleep(btStarted());
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
    delay(100);
  }
  if (!voiceLinkConnected()) {
    Serial.println("Sin WiFi (se sigue intentando). Revisa la red en secrets.h");
    return false;
  }
  Serial.printf("WiFi conectado: IP del pez %s, mandando audio a %s:%d\n", WiFi.localIP().toString().c_str(),
                SERVER_IP, SERVER_PORT);
  return true;
}

bool voiceLinkConnected() {
  return WiFi.status() == WL_CONNECTED;
}

void voiceLinkSend(const float *samples, int n, int sampleRate, bool busy) {
  static uint8_t packet[12 + MAX_SAMPLES * 2];
  if (!ensureSocket()) return;
  n = min(n, MAX_SAMPLES);

  packet[0] = 'B';
  packet[1] = 'L';
  packet[2] = 1;
  packet[3] = busy ? 1 : 0;
  memcpy(packet + 4, &sequence, 4);
  uint16_t rate16 = sampleRate, n16 = n;
  memcpy(packet + 8, &rate16, 2);
  memcpy(packet + 10, &n16, 2);

  int16_t *pcm = (int16_t *)(packet + 12);
  for (int i = 0; i < n; i++) {
    if (dcLevel < 0) dcLevel = samples[i];
    dcLevel += DC_TRACK * (samples[i] - dcLevel);
    pcm[i] = constrain((samples[i] - dcLevel) * GAIN, -32768.0f, 32767.0f);
  }

  udp->beginPacket(SERVER_IP, SERVER_PORT);
  udp->write(packet, 12 + n * 2);
  udp->endPacket();
  sequence++;
}

void voiceLinkOnAudio(VoiceLinkAudioCallback callback) {
  audioCallback = callback;
}

bool voiceLinkPollCommand(char *command, int size) {
  static uint8_t packet[12 + MAX_SAMPLES * 2];
  if (!ensureSocket()) return false;

  // Puede haber varios paquetes de voz en espera (llegan 50 por segundo): se atienden todos
  while (udp->parsePacket()) {
    int len = udp->read(packet, sizeof(packet) - 1);
    if (len >= 12 && packet[0] == 'B' && packet[1] == 'A') {
      uint16_t rate, n;
      memcpy(&rate, packet + 8, 2);
      memcpy(&n, packet + 10, 2);
      if (audioCallback && 12 + n * 2 <= len) audioCallback((const int16_t *)(packet + 12), n, rate);
      continue;
    }
    if (len <= 0) continue;
    packet[len] = 0;

    long id;
    char name[32];
    if (sscanf((const char *)packet, "CMD %ld %31s", &id, name) != 2) continue;

    // Acuse siempre (aunque sea repetido): si el acuse anterior se perdió, el servidor deja de reenviar
    char ack[24];
    int ackLen = snprintf(ack, sizeof(ack), "ACK %ld", id);
    udp->beginPacket(udp->remoteIP(), udp->remotePort());
    udp->write((const uint8_t *)ack, ackLen);
    udp->endPacket();

    if (id == lastCommandId) continue;  // reenvío de uno ya ejecutado
    lastCommandId = id;
    strncpy(command, name, size - 1);
    command[size - 1] = 0;
    return true;
  }
  return false;
}

uint32_t voiceLinkPacketsSent() {
  return sequence;
}
