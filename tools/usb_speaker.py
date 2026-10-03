"""Reproduce en las bocinas de la PC el audio que el ESP32 reenvía por USB.

Solo para pruebas, mientras el pez no tiene amplificador:

    celular --Bluetooth--> ESP32 --USB--> este script --> bocinas de la PC

Uso:
    pip install -r tools/requirements.txt
    python tools/usb_speaker.py            # usa COM5
    python tools/usb_speaker.py --port COM7

Formato de cada paquete (ver firmware/src/usb_audio.h):
    0xAA 0x55 | uint16 sampleRate | uint16 n | n x int16 (little endian)
Lo que llega entre paquetes es texto de diagnóstico del ESP32 y se muestra en la consola.
"""

import argparse
import collections
import struct
import threading

import numpy as np
import serial
import sounddevice as sd

BAUD = 921600
UPSAMPLE = 3  # el ESP32 reduce la frecuencia a 1/3; aquí se regresa (14.7 kHz -> 44.1 kHz)
MAX_SAMPLES = 2048  # paquetes más grandes se consideran basura (pérdida de sincronía)
JITTER_BUFFER_S = 0.08  # colchón contra variaciones de llegada; también es el retraso del audio


class AudioQueue:
    """Cola de muestras entre el hilo del puerto serie y el callback de audio."""

    def __init__(self):
        self.chunks = collections.deque()
        self.available = 0
        self.lock = threading.Lock()
        self.started = False

    def push(self, samples):
        with self.lock:
            self.chunks.append(samples)
            self.available += len(samples)

    def pop(self, n, start_threshold):
        out = np.zeros(n, dtype=np.float32)
        with self.lock:
            # Esperar a juntar un colchón antes de empezar (y después de cada corte)
            if not self.started:
                if self.available < start_threshold:
                    return out
                self.started = True
            # Si se acumuló de más (p. ej. mientras se abría la salida de audio), descartar lo viejo:
            # si no, ese atraso se queda para siempre y la música va detrás de la boca
            while self.available > 2 * start_threshold and len(self.chunks) > 1:
                self.available -= len(self.chunks.popleft())
            filled = 0
            while filled < n and self.chunks:
                chunk = self.chunks[0]
                take = min(n - filled, len(chunk))
                out[filled:filled + take] = chunk[:take]
                filled += take
                self.available -= take
                if take == len(chunk):
                    self.chunks.popleft()
                else:
                    self.chunks[0] = chunk[take:]
            if filled < n:
                self.started = False  # se vació: volver a juntar colchón
        return out


def upsample(samples):
    """Interpolación lineal x3: suficiente para escuchar la prueba."""
    x = np.arange(len(samples))
    x_new = np.arange(len(samples) * UPSAMPLE) / UPSAMPLE
    return np.interp(x_new, x, samples).astype(np.float32)


def read_serial(port, queue, rate_holder):
    ser = serial.Serial(port, BAUD, timeout=0.1)
    text = bytearray()
    buf = bytearray()
    while True:
        buf += ser.read(4096)
        while True:
            start = buf.find(b"\xaa\x55")
            if start < 0:
                # Todo es texto; conservar el último byte por si es el inicio de un encabezado
                keep = 1 if buf.endswith(b"\xaa") else 0
                text += buf[:len(buf) - keep]
                del buf[:len(buf) - keep]
                break
            text += buf[:start]
            del buf[:start]
            if len(buf) < 6:
                break
            rate, n = struct.unpack_from("<HH", buf, 2)
            if n == 0 or n > MAX_SAMPLES or rate < 4000:
                del buf[:2]  # encabezado falso: seguir buscando
                continue
            if len(buf) < 6 + n * 2:
                break
            samples = np.frombuffer(bytes(buf[6:6 + n * 2]), dtype="<i2").astype(np.float32) / 32768
            del buf[:6 + n * 2]
            rate_holder[0] = rate
            queue.push(upsample(samples))

        # Mostrar líneas de texto completas
        while b"\n" in text:
            line, _, rest = text.partition(b"\n")
            # Los mensajes de arranque del ESP32 van a otra velocidad (115200) y llegan como basura:
            # se conserva solo el texto legible después del último carácter inválido
            msg = line.decode(errors="replace").split("�")[-1].strip()
            if msg:
                print("[ESP32]", msg)
            text = bytearray(rest)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default="COM5")
    args = parser.parse_args()

    queue = AudioQueue()
    rate_holder = [0]
    threading.Thread(target=read_serial, args=(args.port, queue, rate_holder), daemon=True).start()

    print(f"Escuchando el ESP32 en {args.port}. Conecta el celular a 'Billy Bass' y pon música. Ctrl+C para salir.")
    stream = None
    current_rate = 0
    try:
        while True:
            sd.sleep(200)
            rate = rate_holder[0] * UPSAMPLE
            if rate and rate != current_rate:
                if stream:
                    stream.close()
                start_threshold = int(rate * JITTER_BUFFER_S)

                def callback(outdata, frames, time_info, status, threshold=start_threshold):
                    outdata[:, 0] = queue.pop(frames, threshold)

                stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32", callback=callback,
                                         latency="low")
                stream.start()
                current_rate = rate
                print(f"Reproduciendo audio a {rate} Hz")
    except KeyboardInterrupt:
        print("Adiós")
    finally:
        if stream:
            stream.close()


if __name__ == "__main__":
    main()
