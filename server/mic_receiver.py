"""Recibe por WiFi el audio del micrófono del pez y lo graba en un WAV.

Primer paso del plan de comandos por voz (docs/plan-voice-commands.md): escuchar si la calidad del
micrófono alcanza para reconocer voz.

    ESP32 (firmware/tools/micstream.cpp) --UDP--> este script --> server/recordings/AAAAMMDD-HHMMSS.wav

Uso:
    python server/mic_receiver.py              # graba hasta Ctrl+C
    python server/mic_receiver.py --seconds 30

La primera vez, Windows pregunta si Python puede usar la red: permitir en redes privadas.

Formato de cada paquete (ver firmware/src/voice_link.h), little endian:
    'B' 'L' | uint8 versión | uint8 banderas (bit 0 = ocupado) | uint32 secuencia
    | uint16 sampleRate | uint16 n | n x int16
"""

import argparse
import datetime
import math
import pathlib
import socket
import struct
import time
import wave

import numpy as np

HEADER = struct.Struct("<2sBBIHH")
RECORDINGS = pathlib.Path(__file__).parent / "recordings"


def level_bar(rms):
    """Nivel en dBFS y una barra de 0 a 40 caracteres (de −60 a 0 dBFS)."""
    db = 20 * math.log10(max(rms, 1) / 32768)
    filled = int(max(0, min(40, (db + 60) / 60 * 40)))
    return db, "#" * filled + "." * (40 - filled)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--seconds", type=float, default=0, help="duración; 0 = hasta Ctrl+C")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(1.0)
    print(f"Esperando audio del pez en el puerto UDP {args.port}... (Ctrl+C para terminar)")

    chunks = []  # bloques de audio en orden de secuencia; los perdidos se rellenan con silencio
    declared_rate = None
    expected_seq = None
    first_at = None
    total_samples = lost = busy_packets = packets = 0
    window_samples, window_start, window_sq = 0, time.time(), 0.0

    try:
        while True:
            if args.seconds and first_at and time.time() - first_at >= args.seconds:
                break
            try:
                data, sender = sock.recvfrom(4096)
            except socket.timeout:
                if first_at:
                    print("  (sin paquetes en el último segundo)")
                continue

            if len(data) < HEADER.size:
                continue
            magic, version, flags, seq, rate, n = HEADER.unpack_from(data)
            if magic != b"BL" or version != 1 or len(data) < HEADER.size + n * 2:
                continue
            samples = np.frombuffer(data, dtype="<i2", count=n, offset=HEADER.size)

            if first_at is None:
                first_at = window_start = time.time()
                declared_rate = rate
                print(f"Recibiendo de {sender[0]} a {rate} Hz")
            if expected_seq is not None and seq < expected_seq - 50:
                # La secuencia volvió a empezar: el pez se reinició. Se sigue grabando a partir de aquí.
                print(f"  (el pez se reinició; secuencia {expected_seq} -> {seq})")
                expected_seq = None
            if expected_seq is not None:
                if seq < expected_seq:
                    continue  # llegó tarde o repetido: ya se rellenó con silencio
                gap = seq - expected_seq
                if gap:
                    lost += gap
                    chunks.extend([np.zeros(n, dtype="<i2")] * gap)
            expected_seq = seq + 1

            chunks.append(samples.copy())
            packets += 1
            busy_packets += flags & 1
            total_samples += n
            window_samples += n
            window_sq += float(np.sum(samples.astype(np.float64) ** 2))

            now = time.time()
            if now - window_start >= 1.0:
                rms = math.sqrt(window_sq / max(window_samples, 1))
                db, bar = level_bar(rms)
                print(f"{window_samples / (now - window_start):6.0f} muestras/s  perdidos={lost:<4}  "
                      f"{db:6.1f} dBFS {bar}{'  [motores]' if flags & 1 else ''}")
                window_samples, window_start, window_sq = 0, now, 0.0
    except KeyboardInterrupt:
        pass

    if not chunks:
        print("No llegó audio. Revisa que el pez esté en la misma red y la IP en firmware/src/secrets.h")
        return

    # La frecuencia real puede no ser exactamente la declarada (el ADC del ESP32 no es preciso):
    # se avisa si difiere más de 3 %.
    elapsed = time.time() - first_at
    measured = total_samples / elapsed if elapsed > 0 else declared_rate
    if abs(measured - declared_rate) / declared_rate > 0.03:
        print(f"OJO: llegaron {measured:.0f} muestras/s pero el pez dice {declared_rate} Hz")

    RECORDINGS.mkdir(exist_ok=True)
    path = RECORDINGS / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".wav")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(declared_rate)
        wav.writeframes(np.concatenate(chunks).tobytes())

    seconds = sum(len(c) for c in chunks) / declared_rate
    print(f"\nGuardado {path} ({seconds:.1f} s, {packets} paquetes, {lost} perdidos, "
          f"{100 * busy_packets / max(packets, 1):.0f} % con motores)")


if __name__ == "__main__":
    main()
