# Conexiones (wiring)

## Hardware
- **ESP32-D0WD-V3** (rev 3.1), DevKit de 38 pines, 4MB flash. Puente USB: CP2102 (puerto COM5)
- **Billy Bass (Gemmy)**: funciona completo con su electrónica original (probado)
  - **3 motores**: boca, cuello y cola (por ahora se usan boca y cola)
  - Bocina 8 Ω / 0.5 W (cables blancos)
  - Botón frontal
  - 4 pilas AA en serie (~5.7–6 V)

## Componentes disponibles
- **L298N** (Keyes, REV02): driver de los motores
- **MAX4466**: micrófono analógico con ganancia ajustable (tornillo atrás), patas soldadas
- **Capacitores 1000 µF** (16 V y 50 V): filtro en la alimentación de motores (aún sin conectar)
- **Potenciómetro RV24YN B502** (5 kΩ lineal): perilla de volumen / sensibilidad (aún sin conectar)
- **HC-05 (ZS-040)**: no se usa, el ESP32 ya trae Bluetooth
- **XH-M543**: amplificador de 2×50 W, necesita 12–26 V; demasiado grande para el pez
- Por comprar: amplificador **MAX98357A** (indispensable para sonido); opcional DRV8833 (más fuerza en motores)

## Montaje actual
El ESP32 está **fuera del protoboard**, conectado con jumpers macho-hembra (hembra en la patita del ESP32).
El protoboard sirve de puente: cada jumper del ESP32 llega a la misma fila que el jumper del L298N o la pata del micrófono.

### Ubicación de los pines (la placa no tiene etiquetas)
Chip metálico hacia arriba, antena lejos de ti (USB hacia ti). Se cuentan las patitas desde la punta de la antena.

| Lado derecho (verificado con `tools/pinfinder.cpp`) | | Lado izquierdo (diseño estándar) | |
|---|---|---|---|
| Patita 1 | GND | Patita 1 | 3V3 |
| Patita 8 | GPIO 19 | Patita 5 | GPIO 34 (verificado con el micrófono) |
| Patita 9 | GPIO 18 | Patita 14 | GND |
| Patita 10 | GPIO 5 (**no usar**) | Patita 19 | 5V (**no confundir con 3V3**) |
| Patita 11 | GPIO 17 | | |
| Patita 12 | GPIO 16 | | |
| Patita 13 | GPIO 4 | | |

## Conexión del L298N
| L298N | Va a | Notas |
|---|---|---|
| IN1 | ESP32 GPIO 18 | motor boca |
| IN2 | ESP32 GPIO 19 | motor boca |
| IN3 | ESP32 GPIO 16 | motor cola |
| IN4 | ESP32 GPIO 17 | motor cola |
| ENA, ENB | jumpers puestos | siempre habilitados; el PWM va por IN1–IN4 |
| Jumper 5V (verde, junto al 78M05) | puesto | el regulador da la lógica desde las pilas |
| 5V (borne) | **vacío** | es una salida del regulador |
| VMS | + pilas (~6 V) | los motores reciben ~4 V por la caída del L298N |
| GND (borne) | **− pilas directo al tornillo** + jumper al riel azul | tierra común; ver lecciones abajo |
| MOTOR A | motor **boca** | |
| MOTOR B | motor **cola** | |
| Capacitor 1000 µF (pendiente) | entre VMS (+) y GND (−) | respetar polaridad (franja = −) |

## Conexión del micrófono MAX4466
Las patas del micrófono van directo al protoboard, cada una en una fila distinta.

| MAX4466 | Va a |
|---|---|
| VCC | ESP32 3V3 (**no 5V**) |
| GND | riel azul |
| OUT | ESP32 GPIO 34 |

Lecturas medidas: OUT en reposo ~1.66 V (`centro` ≈ 1930); silencio `nivel` ~150–300; voz ~1100–1900.
Las etiquetas del micrófono están en orden opuesto en cada cara (VCC·GND·OUT vs OUT·GND·VCC).

## Pines ESP32 (plan completo)
| Función | Pin ESP32 | Va a | Estado |
|---|---|---|---|
| LED integrado | GPIO 2 | (en la placa) | en uso |
| Motor boca IN1 | GPIO 18 | L298N IN1 | en uso |
| Motor boca IN2 | GPIO 19 | L298N IN2 | en uso |
| Motor cola IN1 | GPIO 16 | L298N IN3 | en uso |
| Motor cola IN2 | GPIO 17 | L298N IN4 | en uso |
| Micrófono OUT | GPIO 34 | MAX4466 OUT (ADC1, solo entrada) | en uso |
| Amplificador BCLK | GPIO 26 | MAX98357A BCLK | pendiente |
| Amplificador LRC | GPIO 25 | MAX98357A LRC | pendiente |
| Amplificador DIN | GPIO 22 | MAX98357A DIN | pendiente |
| Perilla (pata central) | GPIO 35 | Potenciómetro 5 kΩ (extremos a 3.3 V y GND) | pendiente |
| Botón frontal | GPIO 4 | botón → GND (pull-up interno) | pendiente |

> No usar ADC2 para el micrófono ni la perilla: deja de funcionar cuando el WiFi está activo.

## Alimentación (durante desarrollo)
- ESP32: por USB
- Motores (L298N VMS) y, más adelante, el amplificador: pilas del pez (~6 V)
- **GND común** entre pilas, L298N, micrófono y ESP32

## Lecciones aprendidas
- **Tierra del L298N**: si VMS–GND (tornillos) marca 0 V, el GND del L298N no está unido al − de las pilas.
  Síntomas: LED rojo apagado, LEDs de IN a medias, motores sin fuerza o quietos.
- **GPIO 5**: conectar IN3 ahí hizo que el ESP32 se reiniciara en bucle (`boot:0x12`). Nunca conectar nada a GPIO 5.
- **PWM con L298N**: a 20 kHz casi no entrega corriente; se usa 1 kHz.
- **Boca**: soltar el motor no basta para cerrarla rápido; se jala de regreso girando al revés (`mouthShut`).
- **Motores cruzados**: si la boca hace lo de la cola y viceversa, se corrige en `motors.cpp` (pines) o cambiando de borne.
- **Desconectar pilas** cuando no se prueba: el programa corre en bucle y gasta pilas / calienta motores.

## Evitar
GPIO 0, 2, 5, 12, 15 (pines de arranque) y 6–11 (memoria flash interna).
