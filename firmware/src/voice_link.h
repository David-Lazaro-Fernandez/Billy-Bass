#pragma once

#include <Arduino.h>

// Envía el audio del micrófono a la PC (server/mic_receiver.py) por WiFi, en paquetes UDP.
//
// Formato de cada paquete (little endian):
//   'B' 'L' | uint8 versión (1) | uint8 banderas (bit 0 = ocupado: motores o bocina activos)
//   | uint32 secuencia | uint16 sampleRate | uint16 n | n x int16
//
// Comandos de regreso (texto, por el mismo socket): el servidor manda "CMD <id> <nombre>" y el pez responde
// "ACK <id>". Si el acuse no llega, el servidor reenvía con el mismo id y el pez no lo ejecuta dos veces.
//
// Voz de Billy de regreso (mientras no hay bocina, solo para mover la boca), paquetes de 20 ms al ritmo real:
//   'B' 'A' | uint8 versión (1) | uint8 0 | uint32 secuencia | uint16 sampleRate | uint16 n | n x int16
//
// La red y la IP de la PC están en secrets.h (copiar secrets.example.h).

// Se conecta al WiFi; espera hasta timeoutMs. Devuelve si quedó conectado.
bool voiceLinkBegin(unsigned long timeoutMs);
bool voiceLinkConnected();

// samples en la escala de analogRead (0–4095); aquí se quita el nivel de DC y se pasa a 16 bits.
void voiceLinkSend(const float *samples, int n, int sampleRate, bool busy);

uint32_t voiceLinkPacketsSent();

// Recibe la voz de Billy que manda el servidor (muestras de 16 bits).
typedef void (*VoiceLinkAudioCallback)(const int16_t *samples, int n, int sampleRate);
void voiceLinkOnAudio(VoiceLinkAudioCallback callback);

// Atiende lo que llegó del servidor: la voz va al callback de voiceLinkOnAudio; si llegó un comando nuevo, lo
// copia en command (p. ej. "baila") y devuelve true.
bool voiceLinkPollCommand(char *command, int size);
