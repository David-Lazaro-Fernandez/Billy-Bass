#pragma once

#include <Arduino.h>

// Control de los motores del Billy Bass a través de un driver L298N o DRV8833 (misma lógica IN1/IN2).
// Este modelo tiene 3 motores (boca, cuello, cola); por ahora se usan boca y cola.

void motorsBegin();

// Boca: abre con fuerza (0-255). mouthShut la jala de regreso girando al revés;
// mouthClose suelta el motor (el resorte termina de cerrarla).
void mouthOpen(uint8_t strength = 255);
void mouthShut(uint8_t strength = 255);
void mouthClose();

// Cola: la mueve con fuerza (0-255), la regresa soltando el motor.
void tailOut(uint8_t strength = 255);
void tailRelax();

void motorsStopAll();
