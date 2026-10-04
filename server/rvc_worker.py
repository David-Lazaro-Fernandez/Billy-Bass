"""Convierte pedazos de voz a la voz de un modelo RVC; corre como proceso aparte con server/.venv-rvc.

RVC necesita versiones de numpy y torch distintas a las del servidor, así que vive en su propio entorno y se
comunica por stdin/stdout. Lo arranca y lo usa assistant.py (clase RvcProcess); no hace falta correrlo a mano.

Protocolo binario (little endian), un pedido a la vez:
    pedido:    uint32 frecuencia | uint32 n | n x int16   (n = 0 para terminar)
    respuesta: uint32 frecuencia | uint32 n | n x int16
Todo lo que imprimen las librerías se manda a stderr para no ensuciar el protocolo.
"""

import os
import struct
import sys

# stdout queda solo para el protocolo; cualquier print (de Python o de C) va a stderr
protocol_out = os.fdopen(os.dup(1), "wb")
os.dup2(2, 1)
sys.stdout = sys.stderr

import torch  # noqa: E402  (antes que faiss: si no, la DLL de torch no carga en Windows)
import functools  # noqa: E402

import faiss  # noqa: E402
import librosa  # noqa: E402
import numpy as np  # noqa: E402
from rvc_python.infer import RVCInference  # noqa: E402

# El pipeline relee el índice del disco en cada conversión; con esto se lee una sola vez
faiss.read_index = functools.lru_cache(maxsize=4)(faiss.read_index)

HEADER = struct.Struct("<II")
PAD_S = 0.25  # relleno a cada lado de cada pedazo; el original (1 s) casi duplicaba el tiempo de pedazos cortos


def read_exact(stream, n):
    data = b""
    while len(data) < n:
        chunk = stream.read(n - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def main():
    model, index = os.environ["RVC_MODEL"], os.environ.get("RVC_INDEX", "")
    pitch = int(os.environ.get("RVC_PITCH", "0"))
    f0_method = os.environ.get("RVC_F0", "pm")
    version = os.environ.get("RVC_VERSION", "v2")

    rvc = RVCInference(device="cpu:0")
    rvc.load_model(model, version=version, index_path=index)
    vc, pipeline = rvc.vc, rvc.vc.pipeline
    pipeline.x_pad = PAD_S
    pipeline.t_pad = int(pipeline.sr * PAD_S)
    pipeline.t_pad_tgt = int(vc.tgt_sr * PAD_S)
    pipeline.t_pad2 = pipeline.t_pad * 2

    def convert(audio16k):
        peak = np.abs(audio16k).max() / 0.95
        if peak > 1:
            audio16k = audio16k / peak
        if vc.hubert_model is None:
            from rvc_python.modules.vc.utils import load_hubert
            vc.hubert_model = load_hubert(vc.config, vc.lib_dir)
        return pipeline.pipeline(vc.hubert_model, vc.net_g, 0, audio16k, "", [0, 0, 0], pitch, f0_method, index,
                                 rvc.index_rate, vc.if_f0, rvc.filter_radius, vc.tgt_sr, 0, rvc.rms_mix_rate,
                                 vc.version, rvc.protect, "")

    # Calentar todo el camino (remuestreo, tono, índice) con algo parecido a voz: con silencio no basta y el
    # primer pedazo real tardaba ~7 s
    t = np.arange(22050 * 2) / 22050
    vowel = (0.3 * np.sin(2 * np.pi * 140 * t) * (1 + np.sin(2 * np.pi * 3 * t))).astype(np.float32)
    for _ in range(2):
        convert(librosa.resample(vowel, orig_sr=22050, target_sr=16000))
    print(f"rvc_worker listo: {os.path.basename(model)}, tono {pitch}, {f0_method}", file=sys.stderr, flush=True)

    stdin = sys.stdin.buffer
    while True:
        try:
            rate, n = HEADER.unpack(read_exact(stdin, HEADER.size))
        except EOFError:
            break
        if n == 0:
            break
        pcm = np.frombuffer(read_exact(stdin, n * 2), dtype="<i2").astype(np.float32) / 32768
        audio16k = librosa.resample(pcm, orig_sr=rate, target_sr=16000) if rate != 16000 else pcm
        out = np.asarray(convert(audio16k), dtype="<i2")
        protocol_out.write(HEADER.pack(vc.tgt_sr, len(out)) + out.tobytes())
        protocol_out.flush()


if __name__ == "__main__":
    main()
