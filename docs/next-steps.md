# Siguientes pasos

Actualizado: 2026-10-03

## Software
1. **Refinar la sincronización de la boca** — investigación pendiente, ver [handoff-mouth-sync.md](handoff-mouth-sync.md).
2. **Fase 3: sonido por la bocina del pez** — cuando llegue el MAX98357A: activar la salida I2S en
   `bt_audio.cpp` (`set_stream_reader(..., true)` + pines de `wiring.md`) y retirar el reenvío por USB.
3. **Fase 5: micrófono → PC + comandos por voz ("Billy, …")** — ver [plan-voice-commands.md](plan-voice-commands.md).
4. **Fase 6: asistente** — servidor Python: voz → texto → IA → voz, y regresar el audio al pez.

## Hardware (se dejó para el final)
- **La cola no tiene fuerza suficiente**: se levanta con un empujón mínimo. Causa probable: el L298N
  deja ~4 V al motor. Opciones: 5.ª pila AA en serie, cambiar a **DRV8833**, y limpiar/lubricar el mecanismo
  (grasa de silicón o litio, no WD-40). Después de corregirlo, revisar `TAIL_REVERSED` en `motors.cpp`.
- **Comprar MAX98357A** (indispensable para sonido). Opcional: DRV8833.
- **Capacitor 1000 µF** entre VMS y GND del L298N (pendiente de conectar).
- **Motor del cuello** sin conectar (el L298N solo tiene 2 canales; requeriría otro driver).
- **Alimentación final**: hoy el ESP32 va por USB; definir cómo se alimenta dentro del pez.
- **Identificar colores de cable** de cada motor y del botón (tabla en `wiring.md`).
