"""Efectos para la voz de Billy, aplicados al audio ya generado (int16 mono).

    rasposo   más grave, con gruñido y saturación: voz enojada y desgastada
    pitch()   tono en semitonos y expresividad (cuánto sube y baja la entonación), para cualquier voz
"""

import numpy as np


def _shift(x, rate, pitch, formant):
    """Cambia tono y formantes con el vocoder WORLD (pyworld)."""
    import pyworld as pw
    f0, t = pw.dio(x, rate)
    f0 = pw.stonemask(x, f0, t, rate)
    sp = pw.cheaptrick(x, f0, t, rate)
    ap = pw.d4c(x, f0, t, rate)
    bins = np.arange(sp.shape[1])
    sp = np.array([np.interp(bins / formant, bins, frame, right=frame[-1]) for frame in sp])
    return pw.synthesize(f0 * pitch, sp, ap, rate)


def raspy(pcm, rate, pitch=0.85, formant=0.92, growl=0.35, growl_hz=45, drive=3.0):
    """pitch / formant < 1: más grave y "más grande". growl: profundidad del gruñido (modulación de amplitud
    a growl_hz, como una voz rasposa). drive: saturación (más = más áspera)."""
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768
    if pitch != 1 or formant != 1:
        x = _shift(x, rate, pitch, formant)
    t = np.arange(len(x)) / rate
    # el gruñido no es una frecuencia fija: se le mete un poco de variación para que no suene a motor
    jitter = np.cumsum(np.random.default_rng(0).normal(0, 0.002, len(x)))
    x = x * (1 - growl + growl * np.abs(np.sin(2 * np.pi * growl_hz * t + jitter)))
    x = np.tanh(drive * x) / np.tanh(drive)
    x = x / max(np.abs(x).max(), 1e-9) * 0.9
    return (x * 32767).astype("<i2").tobytes()


def pitch(pcm, rate, semitones=0.0, expressiveness=1.0, keep_formants=True):
    """semitones: sube o baja toda la voz. expressiveness: >1 exagera la entonación (más dramática / enojada),
    <1 la aplana. keep_formants: al cambiar el tono, la voz conserva su "tamaño" (si no, suena tipo ardilla o
    cámara lenta)."""
    import pyworld as pw
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768
    f0, t = pw.dio(x, rate)
    f0 = pw.stonemask(x, f0, t, rate)
    sp = pw.cheaptrick(x, f0, t, rate)
    ap = pw.d4c(x, f0, t, rate)
    voiced = f0 > 0
    if voiced.any() and expressiveness != 1:
        # en escala logarítmica (semitonos), alrededor del tono medio de la frase
        log_f0 = np.log2(f0[voiced])
        center = np.median(log_f0)
        f0[voiced] = 2 ** (center + (log_f0 - center) * expressiveness)
    ratio = 2 ** (semitones / 12)
    f0 = f0 * ratio
    if not keep_formants and ratio != 1:
        bins = np.arange(sp.shape[1])
        sp = np.array([np.interp(bins / ratio, bins, frame, right=frame[-1]) for frame in sp])
    y = pw.synthesize(f0, sp, ap, rate)
    y = y / max(np.abs(y).max(), 1e-9) * min(0.9, np.abs(x).max() * 1.1 + 1e-9)
    return (y * 32767).astype("<i2").tobytes()


EFFECTS = {"rasposo": raspy}


def apply(effect, pcm, rate):
    return EFFECTS[effect](pcm, rate) if effect in EFFECTS else pcm
