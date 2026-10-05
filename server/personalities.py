"""Personalidades de Billy: un archivo por personalidad en server/personalidades/.

Cada archivo (p. ej. pirata.md) empieza con un encabezado y sigue con la descripción:
    nombre: pirata              <- cómo se pide: "Billy, modo pirata" (debe existir en el vocabulario de Vosk)
    voz: es_MX-ald-medium       <- voz de Piper (archivo en server/models/piper/), opcional
    acento: aleman              <- opcional: reescribe el texto para una voz de otro idioma (accents.py)
    emocion: angry              <- opcional: para voces con varias emociones (thorsten_emotional: amused, angry,
                                   disgusted, drunk, neutral, sleepy, surprised, whisper)
    efecto: rasposo             <- opcional: efecto de audio (voice_effects.py)
    ---
    Eres un viejo lobo de mar...

_base.md tiene las reglas comunes a todas ({modos} se reemplaza por la lista de nombres). Los archivos se releen
en cada pregunta, así que se pueden editar sin reiniciar; una personalidad nueva sí necesita reiniciar el
servidor de voz, porque su nombre tiene que entrar a la gramática de Vosk.
"""

import pathlib
from dataclasses import dataclass

DIR = pathlib.Path(__file__).resolve().parent / "personalidades"
DEFAULT = "normal"


@dataclass
class Personality:
    key: str    # nombre del archivo, sin acentos: "dramatico"
    name: str   # como se dice: "dramático"
    voice: str   # modelo de Piper, o "" para la voz por defecto
    accent: str  # reescritura del texto para la voz (accents.py), o ""
    emotion: str  # hablante de una voz con varias emociones (p. ej. "angry" en thorsten_emotional), o ""
    effect: str  # efecto de audio (voice_effects.py), o ""
    text: str


def _parse(path):
    header, _, body = path.read_text(encoding="utf-8").partition("\n---\n")
    fields = dict(line.split(":", 1) for line in header.splitlines() if ":" in line)
    fields = {k.strip(): v.strip() for k, v in fields.items()}
    return Personality(path.stem, fields.get("nombre", path.stem), fields.get("voz", ""), fields.get("acento", ""),
                       fields.get("emocion", ""), fields.get("efecto", ""), body.strip())


def load_all():
    return {p.stem: _parse(p) for p in sorted(DIR.glob("*.md")) if not p.stem.startswith("_")}


def system_prompt(key):
    personalities = load_all()
    current = personalities.get(key) or personalities[DEFAULT]
    base = (DIR / "_base.md").read_text(encoding="utf-8")
    base = base.replace("{modos}", ", ".join(p.name for p in personalities.values()))
    return f"{base.strip()}\n\nPERSONALIDAD ACTUAL: {current.name}\n{current.text}\n"
