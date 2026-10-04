"""Comandos por voz en tiempo real: oye al pez, reconoce "Billy, <comando>" y se lo manda.

    pez (firmware/tools/voicecmd.cpp) --audio UDP--> este script --Vosk--> commands.match() --comando--> pez

Uso:
    python server/voice_server.py

Respuestas que se mandan al pez además de los comandos:
    escuchando   oyó "Billy" solo: la siguiente frase (hasta LISTEN_WINDOW_S) es el comando
    no_entendi   oyó "Billy" pero lo demás no se parece a ningún comando
Si el pez se estuvo moviendo (bandera "ocupado") durante más de la mitad de una frase, se descarta: es ruido
de sus motores (salvo "pausa" / "cállate", que sirven para pararlo). Un gesto corto (como "escuchando") no anula la frase
que viene.
"""

import argparse
import json
import pathlib
import time

from vosk import KaldiRecognizer, Model, SetLogLevel

import commands
from fish_link import FishLink

MODEL = pathlib.Path(__file__).parent / "models" / "vosk-model-small-es-0.42"
SAMPLE_RATE = 16000
LISTEN_WINDOW_S = 5
MAX_BUSY_FRACTION = 0.5


def make_recognizer(model):
    recognizer = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(commands.grammar(), ensure_ascii=False))
    recognizer.SetWords(True)
    return recognizer


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=5005)
    args = parser.parse_args()

    SetLogLevel(-1)
    recognizer = make_recognizer(Model(str(MODEL)))
    link = FishLink(args.port)
    print(f"Escuchando al pez en el puerto UDP {args.port}. Di \"Billy, baila\". (Ctrl+C para salir)")

    listening_until = 0  # después de "Billy" solo, la siguiente frase no necesita "Billy"
    busy_packets = total_packets = 0  # de la frase actual

    def handle(text):
        nonlocal listening_until
        text = text.replace("[unk]", "").strip()
        if not text:
            return
        stamp = time.strftime("%H:%M:%S")
        listening = time.time() < listening_until
        cmd, scores, reason = commands.match(text, require_wake=not listening)
        # "pausa" (o "cállate", "detente") pasa aunque el pez se esté moviendo: es justo para pararlo
        if busy_packets > MAX_BUSY_FRACTION * total_packets and cmd != "pausa":
            print(f"{stamp}  \"{text}\"  -> (ignorado: el pez se estaba moviendo)")
            return
        top = ", ".join(f"{c}:{s:.2f}" for s, c in scores[:2])
        if cmd:
            link.send_command(cmd)
            listening_until = 0
            print(f"{stamp}  \"{text}\"  -> {cmd.upper()}  ({top})")
        elif reason == "solo Billy":
            link.send_command("escuchando")
            listening_until = time.time() + LISTEN_WINDOW_S
            print(f"{stamp}  \"{text}\"  -> escuchando...")
        elif reason in ("no se parece a ningún comando", "ambiguo"):
            link.send_command("no_entendi")
            listening_until = 0
            print(f"{stamp}  \"{text}\"  -> no entendí ({reason}; {top})")
        else:
            print(f"{stamp}  \"{text}\"  -> -  ({reason})")

    try:
        while True:
            packet = link.receive(timeout=0.5)
            if packet is None:
                continue
            busy_packets += packet.busy
            total_packets += 1
            if recognizer.AcceptWaveform(packet.pcm):
                handle(json.loads(recognizer.Result()).get("text", ""))
                busy_packets = total_packets = 0
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
