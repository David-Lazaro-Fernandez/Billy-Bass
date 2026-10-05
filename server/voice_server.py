"""Billy en tiempo real: comandos de voz y preguntas libres al asistente.

    pez (firmware: env bassvoice) --audio UDP--> este script --Vosk--> ¿comando? --sí--> comando al pez
                                                                         │no, pero hubo "Billy" + más voz
                                                    Whisper -> DeepSeek -> voz (assistant.py) -> bocinas de la PC
                                                                                     └──> voz al pez: mueve la boca

Uso:
    python server/voice_server.py
    python server/voice_server.py --sin-asistente     # solo comandos (no carga Whisper, DeepSeek ni la voz)

Respuestas que se mandan al pez además de los comandos:
    escuchando   oyó "Billy" (solo, o con una pregunta que ya se está procesando)
    no_entendi   oyó "Billy" y algo que no es comando ni pregunta
Si el pez se estuvo moviendo (bandera "ocupado") durante más de la mitad de una frase, se descarta: es ruido de
sus motores o su propia voz (salvo "pausa" / "cállate", que sirven para pararlo). Mientras Billy piensa y habla,
no se le hacen más preguntas.
"""

import argparse
import json
import pathlib
import threading
import time

import numpy as np
from vosk import KaldiRecognizer, Model, SetLogLevel

import commands
from fish_link import FishLink

MODEL = pathlib.Path(__file__).parent / "models" / "vosk-model-small-es-0.42"
SAMPLE_RATE = 16000
LISTEN_WINDOW_S = 5
MAX_BUSY_FRACTION = 0.5

# ¿Hubo una pregunta después de "Billy"? Vosk solo conoce los comandos: con una pregunta reconoce "billy" y
# sigue escuchando la voz que no entiende. Medido con el micrófono del pez: tras un comando la cola (audio después
# de la última palabra reconocida) dura 0.5–1.1 s y queda bajo −20 dBFS; con pregunta, 1.4–1.6 s y −6 a −16 dBFS.
QUESTION_TAIL_S = 1.2
QUESTION_TAIL_DBFS = -20
SPEECH_DBFS = -20  # para una pregunta sin "Billy" dentro de la ventana de escucha


def make_recognizer(model):
    recognizer = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(commands.grammar(), ensure_ascii=False))
    recognizer.SetWords(True)
    return recognizer


def peak_dbfs(pcm):
    """Volumen máximo en bloques de 20 ms (dBFS)."""
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    n = len(x) // 320 * 320
    if n == 0:
        return -100.0
    rms = np.sqrt((x[:n].reshape(-1, 320) ** 2).mean(axis=1))
    return float(20 * np.log10(max(rms.max(), 1) / 32768))


class AssistantWorker:
    """Atiende las preguntas en otro hilo, para que la recepción del micrófono no se detenga."""

    def __init__(self, link):
        from assistant import Assistant
        self.link = link
        self.assistant = Assistant(speak=True)
        self.busy = threading.Event()
        print("Cargando Whisper, DeepSeek y la voz de Billy...")
        start = time.time()
        self.assistant.transcribe(np.zeros(SAMPLE_RATE, dtype="<i2").tobytes())  # carga Whisper
        self.assistant.warm_up()
        print(f"Asistente listo en {time.time() - start:.1f} s")

    def ask(self, pcm=None, text=None):
        """Procesa una pregunta (audio a 16 kHz, o texto ya reconocido) si no hay otra en curso. Devuelve si la
        tomó."""
        if self.busy.is_set():
            return False
        self.busy.set()
        threading.Thread(target=self._run, args=(pcm, text), daemon=True).start()
        return True

    def _run(self, pcm, text):
        start = time.time()
        try:
            if text is None:
                text = self.assistant.transcribe(pcm)
                print(f"   Whisper ({time.time() - start:.1f} s): \"{text}\"")
                if not text or len(text.strip(" .,¿?¡!")) < 2:
                    self.link.send_command("no_entendi")
                    return
            cmd, reply = self.assistant.respond(text, log=lambda m: print(f"   {m}"), sink=self.link.send_audio)
            if cmd and cmd.startswith(commands.PERSONALITY_PREFIX):
                print(f"   -> personalidad {cmd[len(commands.PERSONALITY_PREFIX):]}: {reply}")
            elif cmd:
                self.link.send_command(cmd)
                print(f"   -> {cmd.upper()} (era un comando)")
            else:
                print(f"   Billy: {reply}  ({time.time() - start:.1f} s en total)")
        except Exception as e:
            print(f"   error del asistente: {e}")
            self.link.send_command("no_entendi")
        finally:
            time.sleep(0.5)  # que no se oiga a sí mismo con el eco de las bocinas
            self.busy.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--sin-asistente", action="store_true")
    args = parser.parse_args()

    SetLogLevel(-1)
    recognizer = make_recognizer(Model(str(MODEL)))
    link = FishLink(args.port)
    worker = None if args.sin_asistente else AssistantWorker(link)
    print(f"Escuchando al pez en el puerto UDP {args.port}. Di \"Billy, baila\" o \"Billy, ¿qué hora es?\". "
          "(Ctrl+C para salir)")

    listening_until = 0  # después de "Billy" solo, la siguiente frase no necesita "Billy"
    utterance = bytearray()  # audio de la frase actual (desde el último resultado de Vosk)
    utterance_start = 0.0    # en segundos del flujo, como los tiempos de palabra de Vosk
    stream_seconds = 0.0
    busy_packets = total_packets = 0

    def audio_since(seconds):
        offset = max(0, int((seconds - utterance_start) * SAMPLE_RATE)) * 2
        return bytes(utterance[offset:])

    def question(pcm, stamp, text):
        if worker and worker.ask(pcm):
            link.send_command("escuchando")
            print(f"{stamp}  \"{text}\"  -> PREGUNTA ({len(pcm) / 2 / SAMPLE_RATE:.1f} s de audio a Whisper)")
        elif worker:
            print(f"{stamp}  \"{text}\"  -> (ignorado: Billy está respondiendo)")
        else:
            link.send_command("no_entendi")
            print(f"{stamp}  \"{text}\"  -> no entendí (asistente desactivado)")

    def handle(result):
        nonlocal listening_until
        stamp = time.strftime("%H:%M:%S")
        text = result.get("text", "").replace("[unk]", "").strip()
        words = [w for w in result.get("result", []) if w["word"] != "[unk]"]
        if worker and worker.busy.is_set():
            if text:
                print(f"{stamp}  \"{text}\"  -> (ignorado: Billy está respondiendo)")
            return

        listening = time.time() < listening_until
        cmd, scores, reason = commands.match(text, require_wake=not listening) if text else (None, [], "vacío")
        moving = busy_packets > MAX_BUSY_FRACTION * total_packets
        # "pausa" (o "cállate", "detente") pasa aunque el pez se esté moviendo: es justo para pararlo
        if moving and cmd != "pausa":
            if text:
                print(f"{stamp}  \"{text}\"  -> (ignorado: el pez se estaba moviendo)")
            return
        top = ", ".join(f"{c}:{s:.2f}" for s, c in scores[:2])
        if cmd and cmd.startswith(commands.PERSONALITY_PREFIX):
            # "Billy, modo pirata": lo atiende el asistente (cambia y se presenta), no el pez
            listening_until = 0
            if worker and worker.ask(text=text):
                link.send_command("escuchando")
                print(f"{stamp}  \"{text}\"  -> {cmd}")
            else:
                print(f"{stamp}  \"{text}\"  -> (sin asistente o respondiendo: no se cambió)")
            return
        if cmd:
            link.send_command(cmd)
            listening_until = 0
            print(f"{stamp}  \"{text}\"  -> {cmd.upper()}  ({top})")
            return

        tail_from = words[-1]["end"] if words else utterance_start
        tail = audio_since(tail_from)
        has_question = (len(tail) / 2 / SAMPLE_RATE >= QUESTION_TAIL_S and peak_dbfs(tail) >= QUESTION_TAIL_DBFS)
        wake_words = [w for w in words if commands.similarity(commands.normalize(w["word"]), "billy") >= 0.75]

        if wake_words and (has_question or reason != "solo Billy"):
            # "Billy, <algo que no es comando>": desde el final del último "billy" es la pregunta
            listening_until = 0
            question(audio_since(wake_words[-1]["end"]), stamp, text)
        elif reason == "solo Billy":
            link.send_command("escuchando")
            listening_until = time.time() + LISTEN_WINDOW_S
            print(f"{stamp}  \"{text}\"  -> escuchando...")
        elif listening and peak_dbfs(bytes(utterance)) >= SPEECH_DBFS:
            listening_until = 0
            question(bytes(utterance), stamp, text or "(pregunta)")
        elif text:
            print(f"{stamp}  \"{text}\"  -> -  ({reason})")

    try:
        while True:
            packet = link.receive(timeout=0.5)
            if packet is None:
                continue
            busy_packets += packet.busy
            total_packets += 1
            utterance += packet.pcm
            stream_seconds += len(packet.pcm) / 2 / SAMPLE_RATE
            if recognizer.AcceptWaveform(packet.pcm):
                handle(json.loads(recognizer.Result()))
                utterance = bytearray()
                utterance_start = stream_seconds
                busy_packets = total_packets = 0
    except KeyboardInterrupt:
        pass
    finally:
        if worker:
            worker.assistant.close()


if __name__ == "__main__":
    main()
