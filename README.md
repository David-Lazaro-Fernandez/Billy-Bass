# Billy Bass Assistant

Convertir un Billy Bass en bocina Bluetooth y asistente de voz con un ESP32.

Me compré un Billy Bass en un tianguis por 500 MXN y como me encantan los Sopranos quise armar mi propio asistente
personal que me hable en forma de mojarra.

## Estructura
- `firmware/` — código C++ para el ESP32 (PlatformIO)
- `server/` — servidor Python (voz → texto → IA → voz)
- `tools/` — herramientas para la PC (`usb_speaker.py`: escuchar en la PC el audio que recibe el pez)
- `docs/` — conexiones, notas de hardware y pendientes

## Fases
1. [x] LED parpadeando
2. [x] Mover boca y cola con el driver de motores (L298N)
   - [x] Micrófono MAX4466: la boca sigue el sonido (envolvente + filtros de banda)
3. [ ] Reproducir sonido por la bocina (falta el amplificador MAX98357A)
4. [ ] Bocina Bluetooth + boca sincronizada
   - [x] El pez aparece como bocina "Billy Bass" y la boca sigue la música del celular
   - [x] Audio reenviado por USB a las bocinas de la PC para probar (`tools/usb_speaker.py`)
   - [ ] Refinar el algoritmo de la boca → ver [docs/handoff-mouth-sync.md](docs/handoff-mouth-sync.md)
   - [ ] Reproducir por la bocina del pez (requiere fase 3)
5. [ ] Grabar del micrófono y enviar a la PC
6. [ ] Asistente completo con IA

Pendientes de hardware y siguientes pasos: [docs/next-steps.md](docs/next-steps.md)

## Comandos útiles
Desde `firmware/` (PlatformIO en `C:\Users\david\.platformio\penv\Scripts\pio.exe`):

| Comando | Qué hace |
|---|---|
| `pio run -e esp32dev -t upload` | Programa principal: bocina Bluetooth + boca sincronizada |
| `pio run -e micsync -t upload` | Programa principal con el micrófono como fuente de audio |
| `pio run -e idle -t upload` | Pausa: todos los motores apagados |
| `pio run -e motora -t upload` / `motorb` | Prueba un solo motor en ambos sentidos |
| `pio run -e mictest -t upload` | Muestra el nivel del micrófono |
| `pio run -e micstream -t upload` | Manda el micrófono a la PC por WiFi (con `python server\mic_receiver.py`); requiere `src/secrets.h` |
| `pio run -e pinfinder -t upload` | Identifica qué GPIO hay en cada pin |

Desde la raíz: `python tools\usb_speaker.py` reproduce en la PC el audio que recibe el pez.
