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
    piper      solo Piper (por defecto; lo más rápido, <1 s por frase)
    piper_rvc  Piper + conversión RVC (Claude convertida a Jorge, 13 semitonos abajo; ~3–7 s por frase en CPU)
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

import accents  # noqa: E402
import personalities  # noqa: E402
import voice_effects  # noqa: E402
import tools  # noqa: E402  (lee WEATHER_CITY del .env al importarse)

SAMPLE_RATE = 16000
WHISPER_MODEL = "small"  # en CPU; "base" es más rápido y menos preciso
DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"
HISTORY_TURNS = 3  # intercambios recordados para preguntas de seguimiento

# Al presentarse tras "Billy, modo X" (se le manda al modelo como si fuera la pregunta)
INTRO_PROMPT = "(Te acaban de cambiar a esta personalidad. Preséntate en una sola frase corta, ya con tu nuevo estilo.)"


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
        self.personality = os.environ.get("PERSONALIDAD", personalities.DEFAULT)

    def set_personality(self, key):
        self.personality = key
        self.history.clear()  # si no, sigue hablando con el estilo de las respuestas anteriores

    def ask_stream(self, question, log=None):
        """Genera la respuesta por pedazos de texto conforme llegan; ejecuta las funciones que pida el modelo."""
        log = log or (lambda message: None)
        # La personalidad va siempre idéntica al inicio de cada petición: DeepSeek guarda en caché ese prefijo y lo
        # cobra ~50 veces más barato. Se relee del disco: se puede editar sin reiniciar.
        persona = personalities.system_prompt(self.personality)
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
        self.default = env_path("PIPER_VOICE", "models/piper/es_MX-claude-high.onnx")
        self.voices = {}
        self._load(self.default)
        # Las voces de las personalidades se cargan desde el inicio: la primera carga tarda ~5 s
        for p in personalities.load_all().values():
            path = self._path(p.voice)
            if path != self.default:
                self._load(path)

    def _path(self, voice):
        candidate = SERVER_DIR / "models" / "piper" / f"{voice}.onnx"
        return str(candidate) if voice and candidate.exists() else self.default

    def _load(self, path):
        if path not in self.voices:
            from piper import PiperVoice
            self.voices[path] = PiperVoice.load(path)
        return self.voices[path]

    def synthesize(self, text, voice=None, emotion=None):
        """Devuelve (pcm int16 bytes, frecuencia). voice: nombre de un modelo en models/piper/ (p. ej. el de la
        personalidad); si no existe, se usa la voz por defecto. emotion: hablante de una voz con varios (p. ej.
        "angry" en thorsten_emotional)."""
        import io
        from piper import SynthesisConfig
        model = self._load(self._path(voice))
        speakers = model.config.speaker_id_map or {}
        config = SynthesisConfig(speaker_id=speakers[emotion]) if emotion in speakers else None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            model.synthesize_wav(clean_for_speech(text), w, syn_config=config)
        buf.seek(0)
        with wave.open(buf, "rb") as w:
            return w.readframes(w.getnframes()), w.getframerate()


class RvcProcess:
    """rvc_worker.py corriendo en server/.venv-rvc (otro entorno de Python); el modelo se carga una vez."""

    HEADER = struct.Struct("<II")

    def __init__(self, model=None, index=None, version=None):
        """model / index: rutas al .pth y al .index; por defecto, RVC_MODEL / RVC_INDEX del .env.
        version: "v1" o "v2" (por defecto RVC_VERSION o v2)."""
        env = dict(os.environ, RVC_MODEL=model or env_path("RVC_MODEL", "models/Jorge-v2/model.pth"),
                   RVC_INDEX=index if index is not None else env_path("RVC_INDEX", "models/Jorge-v2/model.index"),
                   RVC_PITCH=os.environ.get("RVC_PITCH", "-13"), RVC_F0=os.environ.get("RVC_F0", "pm"),
                   RVC_VERSION=version or os.environ.get("RVC_VERSION", "v2"), PYTHONUTF8="1")
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

    def configure(self, **settings):
        """Cambia pitch, f0, index_rate, protect o rms_mix_rate sin recargar el modelo."""
        import json
        data = json.dumps(settings).encode()
        self.process.stdin.write(self.HEADER.pack(0xFFFFFFFF, len(data)) + data)
        self.process.stdin.flush()
        self.process.stdout.read(self.HEADER.size)

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
        self.engine = os.environ.get("TTS_ENGINE", "piper")
        self.rvc = None
        if self.engine == "polly":
            self.tts = PollyTTS()
        else:
            self.tts = PiperTTS()
            if self.engine == "piper_rvc":
                self.rvc = RvcProcess()

    def synthesize(self, text, voice=None, emotion=None, effect=None):
        """voice / emotion: voz de Piper de la personalidad (Polly los ignora). effect: voice_effects.py."""
        if isinstance(self.tts, PiperTTS):
            pcm, rate = self.tts.synthesize(text, voice, emotion)
        else:
            pcm, rate = self.tts.synthesize(text)
        if self.rvc:
            pcm, rate = self.rvc.convert(pcm, rate)
        return voice_effects.apply(effect, pcm, rate), rate

    def close(self):
        if self.rvc:
            self.rvc.close()


class Player:
    """Reproduce pedazos en orden por las bocinas de la PC (hasta que el pez tenga bocina)."""

    def __init__(self, log, sink=None):
        """sink(pcm, frecuencia): opcional, recibe cada pedazo mientras suena (p. ej. para mover la boca del pez)
        y debe tardar lo que dura el audio."""
        self.queue = queue.Queue()
        self.log = log
        self.sink = sink
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
            if self.sink:
                self.sink(pcm, rate)
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

    def respond(self, text, log=print, sink=None):
        """Si es un comando lo devuelve; si no, responde en voz alta en cadena. Devuelve (comando, respuesta).

        sink(pcm, frecuencia): recibe además cada frase mientras suena (ver Player).
        """
        cmd, _, _ = commands.match(text, require_wake=False)
        if cmd and not cmd.startswith(commands.PERSONALITY_PREFIX):
            return cmd, None
        self.warm_up()
        if cmd:  # "Billy, modo pirata": cambia y se presenta con la personalidad nueva
            self._brain.set_personality(cmd[len(commands.PERSONALITY_PREFIX):])
            text = INTRO_PROMPT
        current = personalities.load_all().get(self._brain.personality)
        voice = current.voice if current else None
        # el acento reescribe el texto para la voz de Piper de la personalidad; con Polly lo leería deformado
        accent = current.accent if current and self._voice and self._voice.engine.startswith("piper") else ""
        emotion = current.emotion if current else None
        effect = current.effect if current else None
        start = time.time()

        def stamp(message):
            log(f"{time.time() - start:5.2f} s  {message}")

        player = Player(stamp, sink) if self.speak else None
        reply = []
        for i, sentence in enumerate(sentences(self._timed(self._brain.ask_stream(text, stamp), stamp)), start=1):
            stamp(f"frase {i}: \"{sentence}\"")
            reply.append(sentence)
            if player:
                # el acento solo cambia lo que lee la voz, no el texto de la respuesta
                pcm, rate = self._voice.synthesize(accents.apply(accent, sentence), voice, emotion, effect)
                stamp(f"voz lista frase {i} ({len(pcm) / 2 / rate:.1f} s de audio)")
                player.add(pcm, rate, f"frase {i}")
        if player:
            player.finish()
        stamp("fin")
        return cmd, " ".join(reply)

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
            print(f"Es un comando: {cmd} (no se llama al LLM)\n" if cmd and not reply else f"Billy: {reply}\n")
    finally:
        assistant.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
