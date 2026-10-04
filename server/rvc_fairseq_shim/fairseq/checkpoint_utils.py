"""load_model_ensemble_and_task() compatible con lo que usa rvc-python, con ContentVec de transformers.

lengyue233/content-vec-best es la conversión del mismo checkpoint que RVC llama hubert_base.pt, incluida
final_proj (768 -> 256), que necesitan los modelos RVC v1.
"""
import torch
from torch import nn
from transformers import HubertModel

MODEL_ID = "lengyue233/content-vec-best"


class HubertModelWithFinalProj(HubertModel):
    def __init__(self, config):
        super().__init__(config)
        self.final_proj = nn.Linear(config.hidden_size, config.classifier_proj_size)


class ContentVec(nn.Module):
    def __init__(self):
        super().__init__()
        self.hubert = HubertModelWithFinalProj.from_pretrained(MODEL_ID)
        self.final_proj = self.hubert.final_proj

    def extract_features(self, source, padding_mask=None, output_layer=12):
        out = self.hubert(source, output_hidden_states=True)
        # hidden_states[0] son las entradas; [n] es la salida de la capa n, igual que fairseq output_layer=n
        return (out.hidden_states[output_layer], None)


def load_model_ensemble_and_task(paths, suffix="", **kwargs):
    return [ContentVec()], None, None
