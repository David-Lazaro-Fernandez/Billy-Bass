"""Comunicación con el pez por UDP (protocolo en firmware/src/voice_link.h).

Del pez llegan paquetes de audio; al pez se mandan comandos "CMD <id> <nombre>" y él responde "ACK <id>".
Si el acuse no llega, el comando se reenvía (el pez ignora ids repetidos). También se le manda la voz de Billy
(paquetes 'BA') para que mueva la boca mientras habla.
"""

import socket
import struct
import time
from dataclasses import dataclass

import numpy as np

HEADER = struct.Struct("<2sBBIHH")
RESEND_AFTER_S = 0.3
MAX_TRIES = 4
AUDIO_RATE = 16000
AUDIO_BLOCK = 320  # 20 ms


@dataclass
class AudioPacket:
    seq: int
    rate: int
    busy: bool
    pcm: bytes  # int16 little endian, mono


def parse_audio(data):
    if len(data) < HEADER.size:
        return None
    magic, version, flags, seq, rate, n = HEADER.unpack_from(data)
    if magic != b"BL" or version != 1 or len(data) < HEADER.size + n * 2:
        return None
    return AudioPacket(seq, rate, bool(flags & 1), data[HEADER.size:HEADER.size + n * 2])


class FishLink:
    def __init__(self, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", port))
        self.fish = None  # (ip, puerto) del pez, se aprende del primer paquete de audio
        self.next_id = int(time.time()) % 100000  # distinto en cada arranque: el pez ignora ids repetidos
        self.pending = {}  # id -> [nombre, intentos, último envío]
        self.audio_seq = 0

    def receive(self, timeout):
        """Devuelve el siguiente AudioPacket, o None si no llegó nada en timeout segundos."""
        self.sock.settimeout(timeout)
        while True:
            try:
                data, sender = self.sock.recvfrom(4096)
            except socket.timeout:
                self._resend()
                return None
            if data.startswith(b"ACK "):
                self.pending.pop(int(data[4:]), None)
                continue
            packet = parse_audio(data)
            if packet:
                if self.fish != sender:
                    print(f"Pez conectado desde {sender[0]}")
                    self.fish = sender
                self._resend()
                return packet

    def send_audio(self, pcm, rate):
        """Manda la voz de Billy al pez (para mover la boca) en paquetes de 20 ms al ritmo real.

        Bloquea lo que dure el audio: llamarlo mientras ese mismo audio suena en las bocinas.
        """
        if not self.fish:
            return
        samples = np.frombuffer(pcm, dtype="<i2")
        if rate != AUDIO_RATE:  # para la boca basta una interpolación simple
            positions = np.arange(0, len(samples), rate / AUDIO_RATE)
            samples = np.interp(positions, np.arange(len(samples)), samples).astype("<i2")
        start = time.time()
        for i, offset in enumerate(range(0, len(samples), AUDIO_BLOCK)):
            chunk = samples[offset:offset + AUDIO_BLOCK]
            self.sock.sendto(HEADER.pack(b"BA", 1, 0, self.audio_seq, AUDIO_RATE, len(chunk)) + chunk.tobytes(),
                             self.fish)
            self.audio_seq += 1
            wait = start + (i + 1) * AUDIO_BLOCK / AUDIO_RATE - time.time()
            if wait > 0:
                time.sleep(wait)

    def send_command(self, name):
        if not self.fish:
            return
        self.next_id += 1
        self.pending[self.next_id] = [name, 1, time.time()]
        self._send(self.next_id, name)

    def _send(self, command_id, name):
        self.sock.sendto(f"CMD {command_id} {name}".encode(), self.fish)

    def _resend(self):
        now = time.time()
        for command_id, entry in list(self.pending.items()):
            name, tries, sent_at = entry
            if now - sent_at < RESEND_AFTER_S:
                continue
            if tries >= MAX_TRIES:
                print(f"  ¡el pez no confirmó '{name}'!")
                del self.pending[command_id]
                continue
            entry[1], entry[2] = tries + 1, now
            self._send(command_id, name)
