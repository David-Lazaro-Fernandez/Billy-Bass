"""Pasa un WAV por Vosk y muestra qué comando reconocería en cada frase.

Sirve para medir con grabaciones reales del pez (server/recordings/) sin tener el pez conectado.

    python server/transcribe_wav.py server/recordings/20261003-151739.wav
    python server/transcribe_wav.py archivo.wav --libre     # sin limitar el vocabulario

Por defecto el reconocedor solo puede escuchar las frases de los comandos (commands.grammar()).
"""

import argparse
import json
import pathlib
import wave

from vosk import KaldiRecognizer, Model, SetLogLevel

import commands

MODEL = pathlib.Path(__file__).parent / "models" / "vosk-model-small-es-0.42"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wav")
    parser.add_argument("--libre", action="store_true", help="transcribir sin limitar el vocabulario")
    args = parser.parse_args()

    SetLogLevel(-1)
    wav = wave.open(args.wav, "rb")
    model = Model(str(MODEL))
    if args.libre:
        recognizer = KaldiRecognizer(model, wav.getframerate())
    else:
        recognizer = KaldiRecognizer(model, wav.getframerate(), json.dumps(commands.grammar(), ensure_ascii=False))
    recognizer.SetWords(True)

    def report(result):
        text = result.get("text", "")
        words = result.get("result", [])
        if not text or text == "[unk]":
            return
        start = words[0]["start"] if words else 0
        confidence = sum(w["conf"] for w in words) / len(words) if words else 0
        cmd, scores, reason = commands.match(text.replace("[unk]", ""))
        top = ", ".join(f"{c}:{s:.2f}" for s, c in scores[:2])
        print(f"{start:6.1f} s  conf={confidence:.2f}  \"{text}\"  ->  {cmd or '-'} ({reason}{'; ' + top if top else ''})")

    while True:
        data = wav.readframes(4000)
        if not data:
            break
        if recognizer.AcceptWaveform(data):
            report(json.loads(recognizer.Result()))
    report(json.loads(recognizer.FinalResult()))


if __name__ == "__main__":
    main()
