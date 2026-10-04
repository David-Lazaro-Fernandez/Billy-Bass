"""Asistente: pregunta (audio o texto) -> Whisper -> ¿comando? -> DeepSeek -> voz, todo en cadena.

Ver docs/plan-assistant.md. Las claves van en server/.env (copiar .env.example).

La respuesta se dice mientras se genera: DeepSeek manda el texto en streaming, se corta en frases, y cada frase
pasa por la voz (Piper, y opcionalmente RVC) y a la bocina; la frase 1 suena mientras se prepara la 2.

Uso, sin el pez:
    python server/assistant.py "¿qué hora es?"          # texto directo
    python server/assistant.py --wav archivo.wav        # transcribe un WAV de 16 kHz y responde
    python server/assistant.py --wav archivo.wav --desde 11.5 --hasta 14
    python server/assistant.py --mic                    # graba 5 s del micrófono de la PC y responde
    python server/assistant.py ... --sin-voz            # solo texto

Voz (TTS_ENGINE en .env):
    piper_rvc  Piper + conversión RVC (por defecto: Claude convertida a Jorge, 13 semitonos abajo)
    piper      solo Piper (lo más rápido)
    polly      Amazon Polly (requiere claves de AWS)
"""

import argparse
import collections
import os
import pathlib
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import wave

import numpy as np
from dotenv import load_dotenv

import commands

SERVER_DIR = pathlib.Path(__file__).resolve().parent
load_dotenv(SERVER_DIR / ".env")

import tools  # noqa: E402  (lee WEATHER_CITY del .env al importarse)

SAMPLE_RATE = 16000
WHISPER_MODEL = "small"  # en CPU; "base" es más rápido y menos preciso
DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"
HISTORY_TURNS = 3  # intercambios recordados para preguntas de seguimiento

# La personalidad va siempre idéntica al inicio de cada petición: DeepSeek guarda en caché ese prefijo y lo
# cobra ~50 veces más barato. Por eso la hora va junto a la pregunta y no aquí.
PERSONA_FILE = SERVER_DIR / "billy_persona.md"


def env_path(name, default):
    """Ruta del .env relativa a server/."""
    return str((SERVER_DIR / os.environ.get(name, default)).resolve())


class Transcriber:
    """Whisper local (faster-whisper) para preguntas libres."""

    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

    def transcribe(self, pcm):
        """pcm: int16 mono a 16 kHz (bytes o arreglo). Devuelve el texto."""
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        segments, _ = self.model.transcribe(audio, language="es", beam_size=5, vad_filter=True,
                                            initial_prompt="Billy")
        return " ".join(s.text.strip() for s in segments).strip()


class Brain:
    """DeepSeek por su API compatible con OpenAI, en streaming."""

    def __init__(self):
        from openai import OpenAI
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key.startswith("sk-") or key == "sk-...":
            raise SystemExit("Falta DEEPSEEK_API_KEY en server/.env")
        self.client = OpenAI(api_key=key, base_url=DEEPSEEK_URL)
        self.history = collections.deque(maxlen=HISTORY_TURNS * 2)

    def ask_stream(self, question, log=None):
        """Genera la respuesta por pedazos de texto conforme llegan; ejecuta las funciones que pida el modelo."""
        log = log or (lambda message: None)
        persona = PERSONA_FILE.read_text(encoding="utf-8")  # se relee: se puede editar sin reiniciar
        # Lo nuevo va al final; se guarda en el historial tal cual se mandó para que el siguiente prefijo coincida
        user_message = {"role": "user", "content": f"{question}\n\n(Ahora es {tools.now_in_spanish()}.)"}
        messages = [{"role": "system", "content": persona}] + list(self.history) + [user_message]
        answer = ""
        for _ in range(3):  # pregunta -> función(es) -> respuesta; máximo dos rondas de funciones
            calls = {}
            for event in self._stream(messages):
                if event.usage:
                    hit = getattr(event.usage, "prompt_cache_hit_tokens", 0) or 0
                    log(f"tokens: entrada {event.usage.prompt_tokens} ({hit} del caché), "
                        f"salida {event.usage.completion_tokens}")
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                if delta.content:
                    answer += delta.content
                    yield delta.content
                for tc in delta.tool_calls or []:  # las llamadas a funciones llegan en pedazos
                    call = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    call["id"] += tc.id or ""
                    call["name"] += (tc.function.name or "") if tc.function else ""
                    call["arguments"] += (tc.function.arguments or "") if tc.function else ""
            if not calls:
                break
            messages.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in calls.values()]})
            for c in calls.values():
                log(f"función {c['name']}({c['arguments']})")
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": tools.call(c["name"],
                                                                                                c["arguments"])})
        self.history += [user_message, {"role": "assistant", "content": answer}]

    def _stream(self, messages):
        # Sin "pensar": con el modo de razonamiento (activo por defecto) gasta cientos de tokens antes de responder
        return self.client.chat.completions.create(model=DEEPSEEK_MODEL, messages=messages, max_tokens=200,
                                                   temperature=0.8, stream=True, tools=tools.TOOLS,
                                                   stream_options={"include_usage": True},
                                                   extra_body={"thinking": {"type": "disabled"}})


def sentences(deltas, max_chars=140):
    """Junta los pedazos de texto y los suelta por frase (o por coma si una frase se alarga mucho)."""
    buffer = ""
    for delta in deltas:
        buffer += delta
        while True:
            # fin de frase: . ! ? … seguido de espacio (así "3.5" no corta)
            match = re.search(r"[.!?…]+[\"')\]]*\s", buffer)
            if not match and len(buffer) > max_chars:
                match = re.search(r".*[,;:]\s", buffer)
            if not match:
                break
            sentence, buffer = buffer[:match.end()].strip(), buffer[match.end():]
            if sentence:
                yield sentence
    if buffer.strip():
        yield buffer.strip()


def clean_for_speech(text):
    return re.sub(r"[*_#`>]", "", text).strip()


class PiperTTS:
    def __init__(self):
        from piper import PiperVoice
        self.voice = PiperVoice.load(env_path("PIPER_VOICE", "models/piper/es_MX-claude-high.onnx"))

    def synthesize(self, text):
        """Devuelve (pcm int16 bytes, frecuencia)."""
        import io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self.voice.synthesize_wav(clean_for_speech(text), w)
        buf.seek(0)
        with wave.open(buf, "rb") as w:
            return w.readframes(w.getnframes()), w.getframerate()


class RvcProcess:
    """rvc_worker.py corriendo en server/.venv-rvc (otro entorno de Python); el modelo se carga una vez."""

    HEADER = struct.Struct("<II")

    def __init__(self):
        env = dict(os.environ, RVC_MODEL=env_path("RVC_MODEL", "models/Jorge-v2/model.pth"),
                   RVC_INDEX=env_path("RVC_INDEX", "models/Jorge-v2/model.index"),
                   RVC_PITCH=os.environ.get("RVC_PITCH", "-13"), RVC_F0=os.environ.get("RVC_F0", "pm"),
                   PYTHONUTF8="1")
        python = SERVER_DIR / ".venv-rvc" / "Scripts" / "python.exe"
        self.process = subprocess.Popen([str(python), str(SERVER_DIR / "rvc_worker.py")], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        log = []
        while True:  # esperar a que cargue el modelo
            line = self.process.stderr.readline().decode(errors="replace")
            if not line:
                raise SystemExit("rvc_worker terminó:\n" + "".join(log[-20:]))
            log.append(line)
            if "rvc_worker listo" in line:
                break
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self):
        for _ in self.process.stderr:  # que el búfer de stderr no se llene y bloquee al worker
            pass

    def convert(self, pcm, rate):
        self.process.stdin.write(self.HEADER.pack(rate, len(pcm) // 2) + pcm)
        self.process.stdin.flush()
        out_rate, n = self.HEADER.unpack(self.process.stdout.read(self.HEADER.size))
        return self.process.stdout.read(n * 2), out_rate

    def close(self):
        try:
            self.process.stdin.write(self.HEADER.pack(0, 0))
            self.process.stdin.flush()
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill()


class PollyTTS:
    """Amazon Polly. Voces en español de México: Mia (standard, neural, generative) y Andrés (neural, generative).

    Precio por millón de caracteres: standard $4, neural $16, generative $30 (2026-10-03).
    """

    def __init__(self):
        import boto3
        self.client = boto3.client("polly", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        self.voice = os.environ.get("POLLY_VOICE", "Andres")
        self.engine = os.environ.get("POLLY_ENGINE", "neural")

    def synthesize(self, text):
        response = self.client.synthesize_speech(Text=clean_for_speech(text), OutputFormat="pcm",
                                                 SampleRate=str(SAMPLE_RATE), VoiceId=self.voice,
                                                 Engine=self.engine)
        return response["AudioStream"].read(), SAMPLE_RATE


class Voice:
    """Texto -> (pcm, frecuencia) con el motor elegido en TTS_ENGINE."""

    def __init__(self):
        self.engine = os.environ.get("TTS_ENGINE", "piper_rvc")
        self.rvc = None
        if self.engine == "polly":
            self.tts = PollyTTS()
        else:
            self.tts = PiperTTS()
            if self.engine == "piper_rvc":
                self.rvc = RvcProcess()

    def synthesize(self, text):
        pcm, rate = self.tts.synthesize(text)
        if self.rvc:
            pcm, rate = self.rvc.convert(pcm, rate)
        return pcm, rate

    def close(self):
        if self.rvc:
            self.rvc.close()


class Player:
    """Reproduce pedazos en orden por las bocinas de la PC (hasta que el pez tenga bocina)."""

    def __init__(self, log):
        self.queue = queue.Queue()
        self.log = log
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        import sounddevice as sd
        while True:
            item = self.queue.get()
            if item is None:
                return
            pcm, rate, label = item
            self.log(f"suena    {label}")
            sd.play(np.frombuffer(pcm, dtype="<i2"), rate)
            sd.wait()
            self.log(f"terminó  {label}")

    def add(self, pcm, rate, label):
        self.queue.put((pcm, rate, label))

    def finish(self):
        self.queue.put(None)
        self.thread.join()


class Assistant:
    """Une las piezas. Cada una se crea al primer uso, así se puede probar sin todas las claves."""

    def __init__(self, speak=True):
        self.speak = speak
        self._transcriber = self._brain = self._voice = None

    def transcribe(self, pcm):
        if not self._transcriber:
            self._transcriber = Transcriber()
        return self._transcriber.transcribe(pcm)

    def warm_up(self):
        """Carga los modelos antes de la primera pregunta (RVC tarda varios segundos en arrancar)."""
        if not self._brain:
            self._brain = Brain()
        if self.speak and not self._voice:
            self._voice = Voice()

    def respond(self, text, log=print):
        """Si es un comando lo devuelve; si no, responde en voz alta en cadena. Devuelve (comando, respuesta)."""
        cmd, _, _ = commands.match(text, require_wake=False)
        if cmd:
            return cmd, None
        self.warm_up()
        start = time.time()

        def stamp(message):
            log(f"{time.time() - start:5.2f} s  {message}")

        player = Player(stamp) if self.speak else None
        reply = []
        for i, sentence in enumerate(sentences(self._timed(self._brain.ask_stream(text, stamp), stamp)), start=1):
            stamp(f"frase {i}: \"{sentence}\"")
            reply.append(sentence)
            if player:
                pcm, rate = self._voice.synthesize(sentence)
                stamp(f"voz lista frase {i} ({len(pcm) / 2 / rate:.1f} s de audio)")
                player.add(pcm, rate, f"frase {i}")
        if player:
            player.finish()
        stamp("fin")
        return None, " ".join(reply)

    @staticmethod
    def _timed(deltas, stamp):
        first = True
        for delta in deltas:
            if first:
                stamp("primer texto de DeepSeek")
                first = False
            yield delta

    def close(self):
        if self._voice:
            self._voice.close()


def read_wav(path, start=None, end=None):
    with wave.open(path, "rb") as wav:
        if wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != 1:
            raise SystemExit("El WAV debe ser mono a 16 kHz (como los de server/recordings/)")
        pcm = wav.readframes(wav.getnframes())
    a = int((start or 0) * SAMPLE_RATE) * 2
    b = int(end * SAMPLE_RATE) * 2 if end else len(pcm)
    return pcm[a:b]


def record_mic(seconds):
    import sounddevice as sd
    print(f"Habla ({seconds:.0f} s)...")
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocking=True)
    return audio.tobytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("texto", nargs="*", help="pregunta(s) escrita(s); varias se hacen en orden")
    parser.add_argument("--wav")
    parser.add_argument("--desde", type=float)
    parser.add_argument("--hasta", type=float)
    parser.add_argument("--mic", action="store_true")
    parser.add_argument("--sin-voz", action="store_true")
    args = parser.parse_args()

    assistant = Assistant(speak=not args.sin_voz)
    questions = list(args.texto)
    if args.wav or args.mic:
        pcm = read_wav(args.wav, args.desde, args.hasta) if args.wav else record_mic(5)
        start = time.time()
        text = assistant.transcribe(pcm)
        print(f"Whisper ({time.time() - start:.1f} s): \"{text}\"")
        questions.insert(0, text)
    if not questions:
        raise SystemExit("No hay pregunta (¿WAV sin voz?)")

    print("Cargando DeepSeek y la voz...")
    start = time.time()
    assistant.warm_up()
    print(f"Listo en {time.time() - start:.1f} s\n")
    try:
        for question in questions:
            print(f"Pregunta: {question}")
            cmd, reply = assistant.respond(question)
            print(f"Es un comando: {cmd} (no se llama al LLM)\n" if cmd else f"Billy: {reply}\n")
    finally:
        assistant.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
