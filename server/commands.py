"""Comandos de voz: de un texto transcrito al comando que más se le parece.

Regla (docs/plan-voice-commands.md, B5): la frase debe empezar con algo parecido a "Billy"; el resto se
compara contra las frases de cada comando y se ejecuta el mejor solo si su puntaje es >= MIN_SCORE y le saca
>= MIN_MARGIN al segundo.
"""

import re
import unicodedata

from rapidfuzz import fuzz

import personalities

WAKE_WORDS = ["billy", "bili", "billi", "vili", "bily", "willy"]
PREFIXES = ["oye"]  # "oye Billy, pausa" también vale
WAKE_MIN_SCORE = 0.75
MIN_SCORE = 0.80
MIN_MARGIN = 0.15

# comando -> frases que lo activan (elegir frases que no se parezcan entre sí). Se escriben con acentos: así
# están en el vocabulario de Vosk ("bajale" sin acento no existe; "súbele" no existe de ninguna forma).
COMMANDS = {
    "pausa": ["pausa", "para", "detente", "cállate", "silencio"],  # pausa la música y detiene al pez
    "play": ["play", "continúa"],
    "siguiente": ["siguiente"],
    "anterior": ["anterior"],
    "subir_volumen": ["sube", "súbele"],
    "bajar_volumen": ["baja", "bájale"],
    "baila": ["baila", "muévete"],
}
# "Billy, modo pirata" cambia de personalidad (las lee de server/personalidades/). Estos los atiende el servidor,
# no el pez. (modo bocina / modo asistente se quitaron: con Bluetooth y WiFi juntos no hacen falta modos.)
PERSONALITY_PREFIX = "personalidad:"
COMMANDS.update({f"{PERSONALITY_PREFIX}{p.key}": [f"modo {p.name}"] for p in personalities.load_all().values()})


def normalize(text):
    """Minúsculas, sin acentos ni signos: "¡Billy, súbele!" -> "billy subele"."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z ]", " ", text).split())


def similarity(a, b):
    return fuzz.ratio(a, b) / 100


def grammar():
    """Frases que el reconocedor puede oír: "billy <comando>" completas, más "billy" solo.

    Con frases completas, si con música se oye "pausa" y algo parecido a "billy" antes, Vosk completa la
    frase en vez de perder el "billy". Medido con ruido agregado: 39 comandos contra 34 con palabras sueltas.
    ("quieto" se quitó: convertía "Billy, ¿qué hora es?" en un comando.)
    """
    phrases = set()
    for wake in ["billy", "willy", "oye billy"]:
        phrases.add(wake)
        for options in COMMANDS.values():
            phrases.update(f"{wake} {p}" for p in options)
    return sorted(phrases) + ["[unk]"]


def match(text, require_wake=True):
    """Devuelve (comando o None, puntajes ordenados [(puntaje, comando)...], motivo).

    require_wake=False: la frase no necesita empezar con "Billy" (se usa justo después de oír "Billy" solo).
    """
    words = normalize(text).split()
    while words and words[0] in PREFIXES:
        words = words[1:]
    if not words:
        return None, [], "vacío"
    if words and max(similarity(words[0], w) for w in WAKE_WORDS) >= WAKE_MIN_SCORE:
        words = words[1:]
    elif require_wake:
        return None, [], "no empieza con Billy"
    rest = " ".join(words)
    if not rest:
        return None, [], "solo Billy"

    scores = sorted(((max(similarity(rest, normalize(p)) for p in phrases), cmd) for cmd, phrases in COMMANDS.items()),
                    reverse=True)
    best, second = scores[0], scores[1]
    if best[0] < MIN_SCORE:
        return None, scores, "no se parece a ningún comando"
    if best[0] - second[0] < MIN_MARGIN:
        return None, scores, "ambiguo"
    return best[1], scores, "ok"
