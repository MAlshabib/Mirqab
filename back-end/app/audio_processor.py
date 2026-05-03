"""
Shared audio inference pipeline for Mirqab.

Holds a singleton MirqabCNN model loaded from
  model/audio_workspace/models/best_model.pth
Used by the live microphone detector and (optionally) a WebSocket audio feed.

Detects: uav, aircraft  —  background is suppressed (not broadcast).
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ── Paths / thresholds ────────────────────────────────────────────────────────

_MODEL_PATH = os.getenv("AUDIO_MODEL_PATH") or str(
    Path(__file__).parent.parent.parent / "model" / "audio_workspace" / "models" / "best_model.pth"
)
_CONFIDENCE_THRESHOLD = float(os.getenv("AUDIO_CONFIDENCE", "0.70"))
_DETECTION_COOLDOWN   = float(os.getenv("AUDIO_COOLDOWN",    "3.0"))

# ── Audio constants (must match training config) ──────────────────────────────

SR          = 16_000
WINDOW_LEN  = SR          # 1.0 s window
STRIDE_LEN  = SR // 2     # 0.5 s stride (50 % overlap)
CLASS_NAMES = ["uav", "aircraft", "background"]

_SEVERITY_MAP = {
    "uav":      "high",
    "aircraft": "medium",
}


# ── MirqabCNN (must mirror 05_train.py exactly) ───────────────────────────────

class _ConvBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
        )

    def forward(self, x):
        return self.net(x)


class _MirqabCNN(nn.Module):
    def __init__(self, num_classes: int = 3, base_ch: int = 32, dropout: float = 0.0):
        super().__init__()
        self.encoder = nn.Sequential(
            _ConvBlock(1, base_ch),
            _ConvBlock(base_ch, base_ch * 2),
            _ConvBlock(base_ch * 2, base_ch * 4),
            _ConvBlock(base_ch * 4, base_ch * 8),
        )
        self.gap  = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(base_ch * 8, num_classes),
        )

    def forward(self, x):
        return self.head(self.gap(self.encoder(x)).flatten(1))


# ── Mel pipeline ──────────────────────────────────────────────────────────────

def _build_mel_pipe(device: torch.device) -> nn.Module:
    try:
        import torchaudio.transforms as T
    except ImportError:
        raise RuntimeError("torchaudio not installed — pip install torchaudio")
    pipe = nn.Sequential(
        T.MelSpectrogram(
            sample_rate=SR, n_fft=1024, hop_length=512,
            n_mels=128, f_min=20, f_max=8000, power=2.0,
        ),
        T.AmplitudeToDB(top_db=80.0),
    ).to(device)
    for p in pipe.parameters():
        p.requires_grad_(False)
    return pipe


def _apply_mel(x: torch.Tensor, mel_pipe: nn.Module) -> torch.Tensor:
    with torch.no_grad(), torch.amp.autocast(device_type=x.device.type, enabled=False):
        x = mel_pipe(x.float())
    x = x.clamp(min=-80.0)
    mu    = x.mean(dim=(-2, -1), keepdim=True)
    sigma = x.std(dim=(-2, -1), keepdim=True).clamp(min=1e-4)
    return (x - mu) / sigma


# ── Inference engine wrapper ──────────────────────────────────────────────────

class AudioEngine:
    def __init__(self, model: nn.Module, mel_pipe: nn.Module, device: torch.device):
        self.model    = model
        self.mel_pipe = mel_pipe
        self.device   = device

    @torch.no_grad()
    def infer(self, audio: np.ndarray) -> dict:
        """Run inference on a single float32 mono window (length = WINDOW_LEN)."""
        x = torch.from_numpy(audio[:WINDOW_LEN]).unsqueeze(0).unsqueeze(0).to(self.device)
        with torch.amp.autocast(device_type=self.device.type):
            x_mel  = _apply_mel(x, self.mel_pipe)
            logits = self.model(x_mel)
        probs   = F.softmax(logits.float(), dim=1).cpu().numpy()[0]
        cls_idx = int(probs.argmax())
        prob_str = ", ".join(f"{CLASS_NAMES[i]}={probs[i]:.3f}" for i in range(len(CLASS_NAMES)))
        print(f"[AUDIO] inference: {prob_str} → {CLASS_NAMES[cls_idx]} ({probs[cls_idx]:.3f})")
        return {
            "class_name": CLASS_NAMES[cls_idx],
            "confidence": float(probs[cls_idx]),
            "probs":      [round(float(v), 4) for v in probs],
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[AudioEngine] = None
_engine_lock = asyncio.Lock()

# Per-unit, per-label cooldowns
_last_emitted: dict[str, dict[str, float]] = {}


async def get_engine() -> AudioEngine:
    global _engine
    if _engine is not None:
        return _engine
    async with _engine_lock:
        if _engine is None:
            def _load() -> AudioEngine:
                device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
                model  = _MirqabCNN(num_classes=3, base_ch=32, dropout=0.0).to(device)
                ckpt   = torch.load(_MODEL_PATH, map_location=device, weights_only=False)
                model.load_state_dict(ckpt["model_state"])
                model.eval()
                mel_pipe = _build_mel_pipe(device)
                return AudioEngine(model, mel_pipe, device)

            print(f"[AUDIO] loading model from {_MODEL_PATH}")
            _engine = await asyncio.to_thread(_load)
            print(f"[AUDIO] model ready on {_engine.device}")
    return _engine


def infer_window(engine: AudioEngine, audio: np.ndarray) -> dict:
    """Blocking inference — call via asyncio.to_thread."""
    return engine.infer(audio)


# ── Event emission ────────────────────────────────────────────────────────────

async def emit_audio_detection(
    unit_id: str,
    class_name: str,
    confidence: float,
    lat: float,
    lng: float,
) -> None:
    """Hand off to the fusion engine (with per-label cooldown to avoid buffer flooding)."""
    if class_name == "background":
        return

    now_t     = asyncio.get_event_loop().time()
    cooldowns = _last_emitted.setdefault(unit_id, {})
    if now_t - cooldowns.get(class_name, 0.0) < _DETECTION_COOLDOWN:
        return
    cooldowns[class_name] = now_t

    from app import fusion
    await fusion.on_acoustic_detection(
        unit_id=unit_id,
        label=class_name,
        confidence=confidence,
        lat=lat,
        lng=lng,
    )


def get_unit_position(unit_id: str) -> tuple[float, float]:
    from sqlmodel import Session
    from app.database import engine as db_engine
    from app.models import Unit

    with Session(db_engine) as session:
        unit = session.get(Unit, unit_id)
        if unit:
            return unit.lat, unit.lng
    return 24.7136, 46.6753
