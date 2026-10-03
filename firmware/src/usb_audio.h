#pragma once

#include <Arduino.h>

// Reenvía audio por el puerto serie USB para escucharlo en las bocinas de la PC (solo para pruebas,
// mientras no hay amplificador). Lo reproduce tools/usb_speaker.py.
//
// Formato de cada paquete:  0xAA 0x55 | uint16 sampleRate | uint16 n | n x int16 (little endian)
// Los mensajes de texto (Serial.print) pueden ir entre paquetes; el script los muestra aparte.
//
// El audio se reduce a 1/3 de la frecuencia de muestreo (44.1 kHz -> 14.7 kHz) para que quepa en el USB.

const int USB_AUDIO_BAUD = 921600;

void usbAudioBegin();

// Llamar desde la tarea de Bluetooth: guarda el audio en un buffer (no bloquea).
void usbAudioPush(const float *samples, int n, int sampleRate);

// Llamar desde loop(): manda por USB lo que haya en el buffer. Solo loop() escribe en Serial,
// así los paquetes de audio y los mensajes de texto no se mezclan.
void usbAudioPump();
