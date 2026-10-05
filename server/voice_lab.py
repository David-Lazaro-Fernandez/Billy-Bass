"""Laboratorio de voz (solo para desarrollo): prueba combinaciones de voz, SSML, pronunciación, RVC y efectos.

    streamlit run server/voice_lab.py

Cadena:  texto -> reglas de pronunciación -> origen (Polly con SSML, Piper, o tu voz grabada)
               -> RVC opcional (tono, índice...) -> efecto opcional -> se escucha cada etapa (+ Whisper)
Los presets (todos los ajustes) se guardan en server/voice_presets/*.json.
"""

import io
import json
import pathlib
import re
import sys
import time
import wave
from xml.sax.saxutils import escape, quoteattr

import numpy as np
import pandas as pd
import streamlit as st

if sys.platform == "win32":
    # En Windows, cuando el navegador cierra la conexión de golpe (cerrar o recargar la pestaña), asyncio imprime un
    # ConnectionResetError inofensivo al limpiarla. Se ignora solo ese caso.
    from asyncio.proactor_events import _ProactorBasePipeTransport

    if not getattr(_ProactorBasePipeTransport._call_connection_lost, "_billy_quiet", False):
        _original_connection_lost = _ProactorBasePipeTransport._call_connection_lost

        def _quiet_connection_lost(self, exc):
            try:
                _original_connection_lost(self, exc)
            except ConnectionResetError:
                pass

        _quiet_connection_lost._billy_quiet = True
        _ProactorBasePipeTransport._call_connection_lost = _quiet_connection_lost

SERVER_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))
import assistant  # noqa: E402  (carga server/.env)
import voice_effects  # noqa: E402

PRESETS_DIR = SERVER_DIR / "voice_presets"
MODELS_DIR = SERVER_DIR / "models"

POLLY_VOICES = {
    "Andres (es-MX, hombre)": "Andres", "Mia (es-MX, mujer)": "Mia", "Pedro (es-US, hombre)": "Pedro",
    "Lupe (es-US, mujer)": "Lupe", "Sergio (es-ES, hombre)": "Sergio", "Lucia (es-ES, mujer)": "Lucia",
    "Daniel (de-DE, hombre)": "Daniel", "Vicki (de-DE, mujer)": "Vicki", "Matthew (en-US, hombre)": "Matthew",
}
VOLUMES = ["", "x-soft", "soft", "medium", "loud", "x-loud", "+3dB", "+6dB", "-3dB", "-6dB"]
VOLUME_DB = {"x-soft": -12, "soft": -6, "medium": 0, "loud": 4, "x-loud": 8, "+3dB": 3, "+6dB": 6, "-3dB": -3,
             "-6dB": -6}
ENDINGS = ["igual", ".", "!", "?", "…", "¡…!", "¿…?"]
LANGS = ["", "es-MX", "es-US", "es-ES", "de-DE", "en-US"]
RULE_MODES = ["texto", "alias (SSML)", "fonema IPA (SSML)"]
MATCH_KINDS = ["palabra", "parte de palabra", "regex"]


# ---------- audio ----------

def wav_bytes(pcm, rate):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def read_wav(data):
    """WAV en bytes -> (pcm int16 mono, frecuencia)."""
    with wave.open(io.BytesIO(data), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("El WAV debe ser de 16 bits")
    x = np.frombuffer(frames, dtype="<i2")
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1).astype("<i2")
    return x.tobytes(), rate


def gain(pcm, db):
    if not db:
        return pcm
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) * 10 ** (db / 20)
    return np.clip(x, -32768, 32767).astype("<i2").tobytes()


def silence(ms, rate):
    return b"\x00\x00" * int(rate * ms / 1000)


def to_16k(pcm, rate):
    x = np.frombuffer(pcm, dtype="<i2")
    if rate == 16000:
        return pcm
    return np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x).astype("<i2").tobytes()


# ---------- texto, reglas y SSML ----------

def val(row, key, default=None):
    """Valor de una celda de la tabla; vacío o NaN -> default."""
    v = row.get(key)
    if v is None or v == "" or (isinstance(v, float) and np.isnan(v)):
        return default
    return v


def split_sentences(text):
    return [s.strip() for s in re.findall(r"[^.!?…]+[.!?…]*", text) if s.strip(" .!?…")]


def rule_pattern(rule):
    find = str(rule.get("buscar") or "")
    kind = rule.get("coincidencia") or "palabra"
    if kind == "regex":
        return find
    if kind == "parte de palabra":
        return re.escape(find)
    return r"(?<!\w)" + re.escape(find) + r"(?!\w)"


def apply_text_rules(text, rules):
    for r in rules:
        if r.get("activa", True) and r.get("buscar") and (r.get("modo") or "texto") == "texto":
            text = re.sub(rule_pattern(r), str(r.get("reemplazar") or ""), text, flags=re.IGNORECASE)
    return text


def apply_ssml_rules(escaped, rules):
    """Sobre texto ya escapado: palabras -> <sub alias> o <phoneme>."""
    for r in rules:
        mode = r.get("modo") or "texto"
        if not (r.get("activa", True) and r.get("buscar")) or mode == "texto":
            continue
        replacement = str(r.get("reemplazar") or "")
        if mode.startswith("alias"):
            tag = lambda m: f"<sub alias={quoteattr(replacement)}>{m.group(0)}</sub>"  # noqa: E731
        else:
            tag = lambda m: f'<phoneme alphabet="ipa" ph={quoteattr(replacement)}>{m.group(0)}</phoneme>'  # noqa: E731
        escaped = re.sub(rule_pattern(r), tag, escaped, flags=re.IGNORECASE)
    return escaped


# ---------- etiquetas: [angry] ¿Quién es [emphasis]Spáiderman? [pause] ... ----------

# emoción -> velocidad y volumen de la frase (y la emoción de Piper, si la voz la tiene)
EMOTIONS = {
    "angry": {"velocidad": 112, "volumen": "x-loud", "piper": "angry"},
    "shout": {"velocidad": 108, "volumen": "x-loud", "piper": "angry"},
    "excited": {"velocidad": 115, "volumen": "loud", "piper": "surprised"},
    "sad": {"velocidad": 85, "volumen": "soft", "piper": "sleepy"},
    "calm": {"velocidad": 92, "volumen": "medium", "piper": "neutral"},
    "whisper": {"velocidad": 90, "volumen": "x-soft", "piper": "whisper"},
}
ALIASES = {"enojado": "angry", "grito": "shout", "emocionado": "excited", "triste": "sad", "calmado": "calm",
           "susurro": "whisper", "enfasis": "emphasis", "énfasis": "emphasis", "pausa": "pause"}
TAG = re.compile(r"\[\s*([a-záéíóú]+)\s*(?:(\d+)\s*ms)?\s*\]", re.IGNORECASE)
DEFAULT_PAUSE_MS = 400

TAGGER_PROMPT = """Eres director de doblaje. Etiqueta el texto para un sintetizador de voz en español.
Etiquetas disponibles:
- [angry] [shout] [excited] [sad] [calm] [whisper]: emoción a partir de ese punto. Ponla al inicio y solo donde cambie.
- [emphasis]: justo antes de la palabra que se debe enfatizar. En cada frase marca la palabra clave (una, máximo dos).
- [pause]: pausa dramática entre frases o ideas.
Reglas: no cambies, quites ni agregues palabras; solo agrega etiquetas. Única excepción: nombres o palabras en inglés,
escríbelos como se pronuncian en español (Spider-Man -> Spáiderman). Responde solo con el texto etiquetado."""


def auto_tag(text):
    """DeepSeek etiqueta el texto (emociones, énfasis, pausas) como un director de doblaje."""
    import os
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=assistant.DEEPSEEK_URL)
    r = client.chat.completions.create(model=assistant.DEEPSEEK_MODEL, temperature=0.3, max_tokens=800,
                                       messages=[{"role": "system", "content": TAGGER_PROMPT},
                                                 {"role": "user", "content": text}],
                                       extra_body={"thinking": {"type": "disabled"}})
    return r.choices[0].message.content.strip()


def parse_tags(text):
    """Texto etiquetado -> filas de la tabla de entonación (una por frase). El énfasis se marca *así*."""
    rows, buffer, emotion, sentence_emotion, emphasis_next = [], "", None, None, False

    def flush(pause=None):
        nonlocal buffer, sentence_emotion
        sentence = buffer.strip()
        if sentence:
            style = EMOTIONS.get(sentence_emotion, {})
            rows.append({"frase": sentence, "velocidad": float(style.get("velocidad", np.nan)),
                         "volumen": style.get("volumen", ""), "tono": "", "final": "igual", "idioma": "",
                         "pausa_ms": float(pause) if pause is not None else np.nan,
                         "emocion": sentence_emotion or ""})
        elif pause is not None and rows:  # pausa justo después de una frase: se le suma a esa frase
            rows[-1]["pausa_ms"] = float(pause)
        buffer, sentence_emotion = "", emotion

    pos = 0
    for m in list(TAG.finditer(text)) + [None]:
        chunk = text[pos:m.start() if m else len(text)]
        if chunk:
            if emphasis_next:
                chunk = re.sub(r"^(\s*)([\w’'áéíóúüñÁÉÍÓÚÑ-]+)", r"\1*\2*", chunk, count=1)
                emphasis_next = False
            # cada fin de frase (. ! ? … seguido de espacio) cierra una fila
            pieces = re.split(r"(?<=[.!?…])\s+", chunk)
            for piece in pieces[:-1]:
                if not buffer.strip():
                    sentence_emotion = emotion
                buffer += piece
                flush()
            if not buffer.strip():
                sentence_emotion = emotion
            buffer += pieces[-1]
        if not m:
            break
        name = ALIASES.get(m.group(1).lower(), m.group(1).lower())
        if name in EMOTIONS:
            emotion = name
            if not buffer.strip():
                sentence_emotion = emotion
        elif name == "pause":
            flush(int(m.group(2)) if m.group(2) else DEFAULT_PAUSE_MS)
        elif name == "emphasis":
            emphasis_next = True
        pos = m.end()
    flush()
    return pd.DataFrame(rows)


def emphasis_markup(escaped, engine):
    """*palabra* -> énfasis según lo que acepte el motor de Polly."""
    if engine == "standard":
        return re.sub(r"\*([^*]+)\*", r'<emphasis level="strong">\1</emphasis>', escaped)
    if engine == "neural":
        # relativo a la frase: si la frase ya va en x-loud, un "x-loud" en la palabra no se notaría
        return re.sub(r"\*([^*]+)\*", r'<prosody volume="+6dB" rate="85%">\1</prosody>', escaped)
    return escaped.replace("*", "")  # generative: prosody solo alrededor de frases completas


def apply_ending(sentence, ending):
    if ending == "igual":
        return sentence
    core = sentence.strip().strip(".!?…¡¿").strip()
    return {"¡…!": f"¡{core}!", "¿…?": f"¿{core}?"}.get(ending, core + ending)


def build_ssml(rows, rules, defaults, engine):
    """rows: una por frase (velocidad, volumen, tono, pausa, final, idioma); vacío = valor por defecto."""
    parts = ["<speak>"]
    for row in rows:
        text = apply_text_rules(apply_ending(str(row["frase"]), val(row, "final", "igual")), rules)
        body = emphasis_markup(apply_ssml_rules(escape(text), rules), engine)
        lang = val(row, "idioma", defaults["idioma"])
        if lang:
            body = f'<lang xml:lang="{lang}">{body}</lang>'
        attrs = []
        rate = val(row, "velocidad", defaults["velocidad"])
        if rate and int(rate) != 100:
            attrs.append(f'rate="{int(rate)}%"')
        volume = val(row, "volumen", defaults["volumen"])
        if volume:
            attrs.append(f'volume="{volume}"')
        pitch = val(row, "tono", defaults["tono"])
        if pitch and engine == "standard":  # neural y generative no aceptan pitch
            attrs.append(f'pitch="{pitch}"')
        if attrs:
            body = f"<prosody {' '.join(attrs)}>{body}</prosody>"
        parts.append(f"  <s>{body}</s>")
        pause = val(row, "pausa_ms", defaults["pausa_ms"])
        if pause:
            parts.append(f'  <break time="{int(pause)}ms"/>')
    parts.append("</speak>")
    return "\n".join(parts)


# ---------- motores ----------

@st.cache_resource
def polly_client():
    import os
    import boto3
    return boto3.client("polly", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def synth_polly(ssml, voice, engine):
    r = polly_client().synthesize_speech(Text=ssml, TextType="ssml", OutputFormat="pcm", SampleRate="16000",
                                         VoiceId=voice, Engine=engine)
    return r["AudioStream"].read(), 16000


@st.cache_resource
def piper_voice(path):
    from piper import PiperVoice
    return PiperVoice.load(path)


def synth_piper(rows, rules, defaults, path, speaker, length_scale, noise_scale, noise_w):
    """Piper no entiende SSML: cada frase se genera aparte con su velocidad, volumen y pausa."""
    from piper import SynthesisConfig
    voice = piper_voice(path)
    speakers = voice.config.speaker_id_map or {}
    out, rate = b"", voice.config.sample_rate
    for row in rows:
        text = apply_text_rules(apply_ending(str(row["frase"]), val(row, "final", "igual")), rules).replace("*", "")
        speed = int(val(row, "velocidad", defaults["velocidad"]) or 100)
        # la emoción de la frase ([angry]...) elige la emoción de la voz, si la tiene (thorsten_emotional)
        emotion_speaker = EMOTIONS.get(val(row, "emocion", ""), {}).get("piper")
        row_speaker = speakers.get(emotion_speaker, speaker) if speakers else speaker
        cfg = SynthesisConfig(speaker_id=row_speaker, length_scale=length_scale * 100 / speed,
                              noise_scale=noise_scale, noise_w_scale=noise_w)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            voice.synthesize_wav(assistant.clean_for_speech(text), w, syn_config=cfg)
        pcm, rate = read_wav(buf.getvalue())
        out += gain(pcm, VOLUME_DB.get(val(row, "volumen", defaults["volumen"]), 0))
        out += silence(int(val(row, "pausa_ms", defaults["pausa_ms"]) or 0), rate)
    return out, rate


@st.cache_resource
def rvc_process(model, index, version):
    return assistant.RvcProcess(model=model, index=index, version=version)


@st.cache_resource
def transcriber():
    return assistant.Transcriber()


def rvc_models():
    """Modelos RVC: los .pth que tienen un .index al lado (así no se cuela, p. ej., el de XTTS)."""
    found = {}
    for pth in sorted(MODELS_DIR.rglob("*.pth")):
        indexes = sorted(pth.parent.glob("*.index"))
        if indexes:
            found[str(pth.relative_to(MODELS_DIR))] = (str(pth), str(indexes[0]))
    return found


def piper_models():
    return {p.stem: str(p) for p in sorted((MODELS_DIR / "piper").glob("*.onnx"))}


# ---------- presets ----------

WIDGET_KEYS = ["source", "polly_voice", "polly_engine", "piper_model", "piper_speaker", "length_scale",
               "noise_scale", "noise_w", "def_rate", "def_volume", "def_pitch", "def_pause", "def_lang",
               "pitch_st", "pitch_expr", "pitch_keep", "use_rvc", "rvc_model", "rvc_version", "rvc_pitch", "rvc_f0", "rvc_index_rate", "rvc_protect",
               "rvc_rms", "use_effect", "fx_pitch", "fx_formant", "fx_growl", "fx_growl_hz", "fx_drive",
               "whisper", "stream", "text", "use_tags", "tagged"]


def save_preset(name):
    PRESETS_DIR.mkdir(exist_ok=True)
    data = {"widgets": {k: st.session_state.get(k) for k in WIDGET_KEYS},
            "rules": st.session_state["rules"].to_dict("records"),
            "rows": st.session_state["rows"].to_dict("records")}
    (PRESETS_DIR / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_preset():
    name = st.session_state.get("preset_to_load")
    if not name:
        return
    data = json.loads((PRESETS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    for k, v in data["widgets"].items():
        if v is not None:
            st.session_state[k] = v
    st.session_state["rules"] = pd.DataFrame(data["rules"])
    st.session_state["rows"] = pd.DataFrame(data["rows"])
    st.session_state["rows_text"] = st.session_state.get("text", "")


# ---------- interfaz ----------

DEFAULT_TEXT = ("Parker, no te pago para que seas un artista sensible. Te pago porque... ¡Todavía no! Te pago porque, "
                "por alguna razón, ese Spider-Man psicópata posará para ti.")


def rows_for(text):
    return pd.DataFrame([{"frase": s, "velocidad": np.nan, "volumen": "", "tono": "", "pausa_ms": np.nan,
                          "final": "igual", "idioma": "", "emocion": ""} for s in split_sentences(text)])


def sidebar():
    sb = st.sidebar
    sb.header("Cadena de voz")
    source = sb.radio("Origen", ["Polly", "Piper", "Mi voz (grabar o subir WAV)"], key="source")
    if source == "Polly":
        sb.selectbox("Voz de Polly", list(POLLY_VOICES), key="polly_voice")
        sb.selectbox("Motor", ["neural", "generative", "standard"], key="polly_engine",
                     help="generative: más expresivo; pitch solo funciona en standard")
    elif source == "Piper":
        models = piper_models()
        names = list(models)
        default = names.index("es_MX-claude-high") if "es_MX-claude-high" in names else 0
        name = sb.selectbox("Modelo de Piper", names, index=default, key="piper_model")
        speakers = piper_voice(models[name]).config.speaker_id_map or {}
        if speakers:
            sb.selectbox("Emoción / hablante", list(speakers), key="piper_speaker")
        sb.slider("Duración (length_scale: >1 más lento)", 0.5, 2.0, 1.0, 0.05, key="length_scale")
        sb.slider("Variación de entonación (noise_scale)", 0.0, 1.5, 0.667, 0.01, key="noise_scale")
        sb.slider("Variación de ritmo (noise_w)", 0.0, 1.5, 0.8, 0.01, key="noise_w")

    sb.divider()
    sb.subheader("Tono")
    sb.slider("Tono (semitonos)", -12.0, 12.0, 0.0, 0.5, key="pitch_st",
              help="Sirve con cualquier origen (Polly neural/generative no aceptan pitch en SSML). Con RVC "
                   "activado, conviene usar el tono de RVC")
    sb.slider("Expresividad (rango de la entonación)", 0.3, 2.5, 1.0, 0.05, key="pitch_expr",
              help=">1: sube y baja más, suena más dramático o enojado; <1: más plano")
    sb.checkbox("Mantener formantes (que no suene a ardilla o cámara lenta)", value=True, key="pitch_keep")

    sb.divider()
    sb.checkbox("Convertir con RVC", key="use_rvc")
    if st.session_state.get("use_rvc"):
        models = rvc_models()
        sb.selectbox("Modelo RVC", list(models), key="rvc_model")
        sb.selectbox("Versión del modelo", ["v2", "v1"], key="rvc_version")
        sb.slider("Tono (semitonos)", -24, 24, 0, key="rvc_pitch")
        sb.selectbox("Método de tono", ["rmvpe", "pm", "harvest", "crepe"], key="rvc_f0",
                     help="rmvpe: más preciso; pm: más rápido")
        sb.slider("Peso del índice (más = más timbre del modelo)", 0.0, 1.0, 0.5, 0.05, key="rvc_index_rate")
        sb.slider("Proteger consonantes (0.5 = apagado)", 0.0, 0.5, 0.33, 0.01, key="rvc_protect")
        sb.slider("Volumen: 0 = sigue al original, 1 = del modelo", 0.0, 1.0, 1.0, 0.05, key="rvc_rms")

    sb.divider()
    sb.checkbox("Efecto rasposo", key="use_effect")
    if st.session_state.get("use_effect"):
        sb.slider("Tono", 0.5, 1.5, 1.0, 0.01, key="fx_pitch")
        sb.slider("Formantes (<1 = voz más grande)", 0.7, 1.3, 1.0, 0.01, key="fx_formant")
        sb.slider("Gruñido", 0.0, 0.8, 0.15, 0.01, key="fx_growl")
        sb.slider("Frecuencia del gruñido (Hz)", 20, 90, 45, key="fx_growl_hz")
        sb.slider("Saturación", 1.0, 8.0, 2.5, 0.1, key="fx_drive")

    sb.divider()
    sb.checkbox("Streaming: sonar por las bocinas de la PC frase por frase", value=True, key="stream",
                help="Empieza a sonar en cuanto está lista la primera frase, como Billy. El resultado completo "
                     "aparece igual abajo")
    sb.checkbox("Verificar con Whisper", value=True, key="whisper")
    sb.header("Presets")
    presets = sorted(p.stem for p in PRESETS_DIR.glob("*.json")) if PRESETS_DIR.exists() else []
    sb.selectbox("Cargar", [""] + presets, key="preset_to_load")
    sb.button("Cargar preset", on_click=load_preset, disabled=not presets)
    name = sb.text_input("Guardar como", placeholder="jj_enojado")
    if sb.button("Guardar preset", disabled=not name):
        save_preset(re.sub(r"[^\w-]", "_", name))
        sb.success(f"Guardado en voice_presets/{name}.json")


def main():
    st.set_page_config(page_title="Laboratorio de voz de Billy", layout="wide")
    st.title("Laboratorio de voz de Billy")
    if "rules" not in st.session_state:
        st.session_state["rules"] = pd.DataFrame([{"activa": True, "buscar": "Spider-Man", "reemplazar": "Spáiderman",
                                                   "modo": "texto", "coincidencia": "palabra"}])
    sidebar()
    source = st.session_state.get("source", "Polly")
    engine = st.session_state.get("polly_engine", "neural")

    recorded = None
    if source.startswith("Mi voz"):
        st.subheader("1. Tu voz")
        st.caption("Actúa la línea como quieres que suene; RVC le pone el timbre del modelo.")
        audio = st.audio_input("Grabar") or st.file_uploader("…o subir un WAV de 16 bits", type=["wav"])
        if audio:
            recorded = read_wav(audio.getvalue())
    else:
        st.subheader("1. Texto")
        text = st.text_area("Texto", DEFAULT_TEXT, height=90, key="text", label_visibility="collapsed")
        use_tags = st.checkbox("Usar etiquetas ([angry], [emphasis], [pause]…)", key="use_tags")
        if use_tags:
            if st.button("Etiquetar con IA (DeepSeek)"):
                with st.spinner("Etiquetando…"):
                    st.session_state["tagged"] = auto_tag(text)
            st.caption("Emociones: [angry] [shout] [excited] [sad] [calm] [whisper] (desde ese punto) · "
                       "[emphasis] antes de una palabra · [pause] o [pause 800ms]. Se puede editar a mano.")
            st.text_area("Texto etiquetado", key="tagged", height=120,
                         placeholder="[angry] ¿Quién es [emphasis]Spáiderman? [pause] ¡Es un [emphasis]criminal!")

        st.subheader("2. Pronunciación")
        st.caption("Reglas buscar → reemplazar. «texto» cambia lo que se lee (sirve en Polly y Piper); «alias» y "
                   "«fonema IPA» son SSML (solo Polly; el fonema funciona parcial en generative). "
                   "Ej.: ll → y, «Spider-Man» → «Spáiderman», o una «i» como fonema [ i ].")
        st.session_state["rules"] = st.data_editor(
            st.session_state["rules"], num_rows="dynamic", width="stretch", key="rules_editor",
            column_config={"modo": st.column_config.SelectboxColumn(options=RULE_MODES),
                           "coincidencia": st.column_config.SelectboxColumn(options=MATCH_KINDS),
                           "activa": st.column_config.CheckboxColumn()})

        st.subheader("3. Entonación")
        c = st.columns(5)
        c[0].number_input("Velocidad global (%)", 20, 200, 100, 5, key="def_rate")
        c[1].selectbox("Volumen global", VOLUMES, key="def_volume")
        c[2].text_input("Tono global (solo standard)", "", key="def_pitch", placeholder="+10% / low / x-high")
        c[3].number_input("Pausa entre frases (ms)", 0, 3000, 250, 50, key="def_pause")
        c[4].selectbox("Idioma (<lang>)", LANGS, key="def_lang",
                       help="Una voz de otro idioma lee el texto con su acento (p. ej. Daniel + es-MX)")
        if engine != "standard" and source == "Polly":
            st.caption("Con neural / generative, Polly ignora el tono (pitch); usa velocidad, volumen y la puntuación "
                       "final, o el tono de RVC.")
        # la tabla se rehace cuando cambia el texto (o el texto etiquetado, si se usan etiquetas)
        tagged = st.session_state.get("tagged", "") if use_tags else ""
        source_text = f"tags:{tagged}" if tagged else text
        if st.session_state.get("rows_text") != source_text:
            st.session_state["rows"] = parse_tags(tagged) if tagged else rows_for(text)
            st.session_state["rows_text"] = source_text
        st.caption("Cada frase puede cambiar sus valores; vacío = el global. «final» cambia la puntuación (¡…! suena "
                   "más enojado).")
        st.session_state["rows"] = st.data_editor(
            st.session_state["rows"], width="stretch", key="rows_editor", num_rows="fixed",
            column_config={"velocidad": st.column_config.NumberColumn(min_value=20, max_value=200, step=5),
                           "volumen": st.column_config.SelectboxColumn(options=VOLUMES),
                           "pausa_ms": st.column_config.NumberColumn(min_value=0, max_value=3000, step=50),
                           "final": st.column_config.SelectboxColumn(options=ENDINGS),
                           "idioma": st.column_config.SelectboxColumn(options=LANGS),
                           "emocion": st.column_config.SelectboxColumn(options=[""] + list(EMOTIONS))})

    defaults = {"velocidad": st.session_state.get("def_rate", 100), "volumen": st.session_state.get("def_volume", ""),
                "tono": st.session_state.get("def_pitch", ""), "pausa_ms": st.session_state.get("def_pause", 250),
                "idioma": st.session_state.get("def_lang", "")}
    rows = st.session_state["rows"].to_dict("records") if "rows" in st.session_state and not recorded else []
    rules = st.session_state["rules"].to_dict("records")

    ssml, manual = None, False
    if source == "Polly":
        st.subheader("4. SSML")
        generated = build_ssml(rows, rules, defaults, engine)
        manual = st.checkbox("Editar el SSML a mano")
        ssml = st.text_area("SSML", generated, height=220, disabled=not manual, key=f"ssml_{hash(generated)}")

    if st.button("Generar", type="primary"):
        generate(source, ssml, rows, rules, defaults, recorded, manual_ssml=source == "Polly" and manual)

    show_history()


def source_chunks(source, ssml, rows, rules, defaults, recorded, stream, manual_ssml):
    """Genera el audio de origen: todo de una vez, o frase por frase si stream (para empezar a sonar antes)."""
    ss = st.session_state
    if source == "Polly":
        voice, engine = POLLY_VOICES[ss["polly_voice"]], ss["polly_engine"]
        label = f"Polly {voice} ({engine})"
        if stream and not manual_ssml:  # el SSML editado a mano no se puede partir por frase
            for row in rows:
                yield (label, *synth_polly(build_ssml([row], rules, defaults, engine), voice, engine))
        else:
            yield (label, *synth_polly(ssml, voice, engine))
    elif source == "Piper":
        path = piper_models()[ss["piper_model"]]
        speakers = piper_voice(path).config.speaker_id_map or {}
        speaker = speakers.get(ss.get("piper_speaker")) if speakers else None
        args = (rules, defaults, path, speaker, ss["length_scale"], ss["noise_scale"], ss["noise_w"])
        label = f"Piper {ss['piper_model']}"
        for part in ([[row] for row in rows] if stream else [rows]):
            yield (label, *synth_piper(part, *args))
    else:
        yield ("Tu voz", *recorded)


def process(pcm, rate, times):
    """Tono -> RVC -> efecto sobre un pedazo de audio. Devuelve [(etapa, pcm, frecuencia)] después del origen."""
    ss = st.session_state
    stages = []

    def timed(name, start):
        times[name] = times.get(name, 0) + time.time() - start

    semitones, expressiveness = ss.get("pitch_st", 0.0), ss.get("pitch_expr", 1.0)
    if semitones or expressiveness != 1:
        t = time.time()
        pcm = voice_effects.pitch(pcm, rate, semitones, expressiveness, ss.get("pitch_keep", True))
        timed("tono", t)
        stages.append((f"Tono {semitones:+g} st, expresividad {expressiveness:g}", pcm, rate))
    if ss.get("use_rvc"):
        model, index = rvc_models()[ss["rvc_model"]]
        proc = rvc_process(model, index, ss["rvc_version"])
        proc.configure(pitch=ss["rvc_pitch"], f0=ss["rvc_f0"], index_rate=ss["rvc_index_rate"],
                       protect=ss["rvc_protect"], rms_mix_rate=ss["rvc_rms"])
        t = time.time()
        pcm, rate = proc.convert(pcm, rate)
        timed("RVC", t)
        stages.append((f"RVC {ss['rvc_model']} ({ss['rvc_pitch']:+d} st)", pcm, rate))
    if ss.get("use_effect"):
        t = time.time()
        pcm = voice_effects.raspy(pcm, rate, pitch=ss["fx_pitch"], formant=ss["fx_formant"], growl=ss["fx_growl"],
                                  growl_hz=ss["fx_growl_hz"], drive=ss["fx_drive"])
        timed("efecto", t)
        stages.append(("Efecto rasposo", pcm, rate))
    return stages


def generate(source, ssml, rows, rules, defaults, recorded, manual_ssml=False):
    ss = st.session_state
    if source.startswith("Mi voz") and not recorded:
        st.warning("Primero graba o sube tu voz.")
        return
    stream = ss.get("stream", False) and not source.startswith("Mi voz")
    times, joined = {}, []  # joined: por etapa, [nombre, pcm acumulado, frecuencia]
    player = assistant.Player(lambda m: None) if stream else None
    start = time.time()
    try:
        if ss.get("use_rvc"):
            model, index = rvc_models()[ss["rvc_model"]]
            with st.spinner("Cargando el modelo RVC (la primera vez tarda)…"):
                rvc_process(model, index, ss["rvc_version"])
        start = time.time()  # la carga del modelo (solo la primera vez) no cuenta como espera
        progress = st.empty()
        chunks = iter(source_chunks(source, ssml, rows, rules, defaults, recorded, stream, manual_ssml))
        i = 0
        while True:
            t = time.time()
            try:
                label, pcm, rate = next(chunks)
            except StopIteration:
                break
            times["origen"] = times.get("origen", 0) + time.time() - t
            i += 1
            stages = [(label, pcm, rate)] + process(pcm, rate, times)
            for k, (name, p, r) in enumerate(stages):
                if k == len(joined):
                    joined.append([name, b"", r])
                joined[k][1] += p
            if player:
                final_name, final_pcm, final_rate = stages[-1]
                player.add(final_pcm, final_rate, f"frase {i}")
                if i == 1:
                    times["primer audio"] = time.time() - start
                progress.caption(f"Sonando por las bocinas de la PC… frase {i} lista")
        if player:
            player.finish()
            progress.empty()
        final_name, final_pcm, final_rate = joined[-1]
        heard = transcriber().transcribe(to_16k(final_pcm, final_rate)) if ss.get("whisper") else None
    except Exception as e:
        st.error(f"Error: {e}")
        return
    stages = [tuple(s) for s in joined]

    ss.setdefault("history", []).insert(0, {
        "when": time.strftime("%H:%M:%S"), "stages": [(n, wav_bytes(p, r), len(p) / 2 / r) for n, p, r in stages],
        "times": times, "heard": heard, "ssml": ssml,
        "settings": {k: ss.get(k) for k in WIDGET_KEYS if k != "text"}})
    del ss["history"][8:]


def show_history():
    for i, item in enumerate(st.session_state.get("history", [])):
        with st.container(border=True):
            times = ", ".join(f"{k} {v:.1f} s" for k, v in item["times"].items())
            st.markdown(f"**{item['when']}** · {times}")
            cols = st.columns(len(item["stages"]))
            for col, (name, wav, seconds) in zip(cols, item["stages"]):
                col.caption(f"{name} · {seconds:.1f} s")
                col.audio(wav, format="audio/wav")
                col.download_button("Descargar", wav, file_name=f"billy_{item['when'].replace(':', '')}_{name[:12]}.wav",
                                    key=f"dl_{i}_{name}")
            if item["heard"] is not None:
                st.caption(f"Whisper entiende: «{item['heard']}»")
            with st.expander("Ajustes y SSML de esta prueba"):
                if item["ssml"]:
                    st.code(item["ssml"], language="xml")
                st.json(item["settings"])


if __name__ == "__main__":
    main()
