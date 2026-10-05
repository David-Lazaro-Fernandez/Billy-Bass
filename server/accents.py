"""Acentos: reescribe texto en español para que una voz de otro idioma lo pronuncie bien, sin perder su acento.

Una voz alemana de Piper leyendo español directo deforma muchas palabras, porque aplica la fonética del alemán
("doce" suena "doke", la "h" se pronuncia, "ie" se lee "i"). Reescribiendo el texto con ortografía alemana
("dosse", "oi", "bijen") se entiende mucho mejor y sigue sonando a alemán.
"""

import re

# (patrón, reemplazo), en orden. Los sonidos que otras reglas no deben volver a tocar se escriben primero con
# marcadores (① = "tsch", ② = "ch" alemana como la j española, ③ = g dura) y se restauran al final.
_GERMAN = [
    (r"ch", "①"),
    (r"gu([eiéí])", r"③\1"),         # gue/gui: g dura
    (r"gü", "③u"),
    (r"g([eiéí])", r"②\1"),          # ge/gi suena como j española
    (r"j", "②"),
    (r"qu([eiéí])", r"k\1"),
    (r"c([eiéí])", r"s\1"),
    (r"c", "k"),
    (r"z", "s"),
    (r"ll", "j"),                    # la j alemana suena como la ll / y
    (r"ñ", "nj"),
    (r"v", "b"),
    (r"\by\b", "i"),                 # la conjunción "y"
    (r"y\b", "i"),                   # hoy, muy
    (r"y", "j"),                     # yo, ayer
    (r"h", ""),                      # h muda (las de "ch" ya están protegidas)
    (r"(?<=[aeiouáéíóú])s(?=[aeiouáéíóú])", "ss"),  # entre vocales, una s alemana sonaría como z
    (r"ie", "i-e"),                  # en alemán "ie" se lee como una i larga ("bjen" / "ije" se entendían peor)
    (r"ei", "ej"),                   # en alemán "ei" se lee "ai"
    (r"eu", "e-u"),                  # y "eu" se lee "oi"
    (r"①", "tsch"),
    (r"②", "ch"),
    (r"③", "g"),
]

# Palabras que la personalidad dice en alemán: se dejan tal cual
GERMAN_WORDS = {"ja", "nein", "sehr", "gut", "danke", "bitte", "genau", "achtung", "wunderbar", "schnell", "mein",
                "freund", "kraft", "ach", "so", "jawohl", "guten", "tag", "morgen", "prost", "los", "natürlich"}


# Nombres que no siguen las reglas del español
SPECIAL = {"billy": "billi"}


def _german_word(word):
    if word.lower() in GERMAN_WORDS:
        return word
    if word.lower() in SPECIAL:
        return SPECIAL[word.lower()]
    word = word.lower()
    for pattern, replacement in _GERMAN:
        word = re.sub(pattern, replacement, word)
    return word


def german(text):
    return re.sub(r"[a-záéíóúüñ]+", lambda m: _german_word(m.group()), text, flags=re.IGNORECASE)


ACCENTS = {"aleman": german}


def apply(accent, text):
    """accent: nombre en ACCENTS (o vacío para no tocar el texto)."""
    return ACCENTS[accent](text) if accent in ACCENTS else text
