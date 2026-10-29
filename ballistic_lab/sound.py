"""Original procedural WAV effects with optional, asynchronous Windows playback."""

import math
from pathlib import Path
import tempfile
import time
import wave

import numpy as np


SAMPLE_RATE = 22050
DURATIONS = {"click": 0.045, "load": 0.17, "fire": 0.24,
             "explosion": 0.58, "hit": 0.58, "round_end": 0.36}
PRIORITIES = {"click": 1, "load": 2, "fire": 3, "explosion": 4, "hit": 4, "round_end": 5}
_AUTO = object()


def synthesise(name, volume=0.35):
    """Return mono little-endian 16-bit PCM; use a local RNG, never the game's RNG."""
    t = np.arange(round(DURATIONS[name] * SAMPLE_RATE)) / SAMPLE_RATE
    rng = np.random.default_rng(9801)

    def tone(start, end, duration, offset=0.0):
        local = t - offset
        progress = np.clip(local / duration, 0, 1)
        phase = 2 * np.pi * (start * local + (end - start) * local**2 / (2 * duration))
        square = np.where(np.sin(phase) >= 0, 1.0, -1.0)
        # A sine fundamental softens the sharp edge of the square waveform.
        envelope = np.minimum(np.maximum(local, 0) / 0.003, 1) * (1 - progress)**2
        envelope *= (local >= 0) & (local < duration)
        return (0.65 * np.sin(phase) + 0.35 * square) * envelope

    if name == "click":
        signal = 0.24 * tone(1150, 850, 0.04)
    elif name == "load":
        signal = 0.27 * tone(360, 260, 0.065) + 0.35 * tone(640, 480, 0.075, 0.085)
    elif name == "fire":
        noise = rng.uniform(-1, 1, len(t))
        signal = 0.60 * tone(180, 45, 0.23) + 0.38 * noise * np.exp(-t / 0.025)
    elif name in ("explosion", "hit"):
        noise = rng.uniform(-1, 1, len(t))
        rumble = np.convolve(noise, np.ones(9) / 9, mode="same")
        signal = (0.72 * noise + 0.85 * rumble) * np.exp(-t / 0.12)
        signal += 0.16 * np.sin(2 * np.pi * 48 * t) * np.exp(-t / 0.18)
        if name == "hit":
            signal += 0.33 * tone(880, 880, 0.095, 0.18)
            signal += 0.31 * tone(1320, 1320, 0.11, 0.28)
    else:
        signal = (0.28 * tone(660, 660, 0.09) + 0.28 * tone(440, 440, 0.09, 0.12)
                  + 0.28 * tone(330, 330, 0.11, 0.24))
    # Fade both ends and leave headroom; no hard cut or full-scale noise burst.
    fade = np.minimum(t / 0.003, 1) * np.minimum((t[-1] - t) / 0.01, 1)
    signal = np.clip(signal * fade, -0.95, 0.95)
    volume = float(volume)
    volume = min(1.0, max(0.0, volume)) if math.isfinite(volume) else 0.35
    return np.rint(signal * volume * 32767).astype("<i2")


def write_effect(path, name, volume=0.35):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(synthesise(name, volume).tobytes())


def _windows_backend():
    try:
        import winsound
        return winsound
    except ImportError:
        return None


class SoundPlayer:
    """Prepare short files once; PlaySound returns immediately on every event."""

    def __init__(self, enabled=True, volume=0.35, backend=_AUTO, clock=None):
        self.backend = _windows_backend() if backend is _AUTO else backend
        self.available = self.backend is not None
        self.enabled = bool(enabled)
        self.volume = volume
        self.clock = time.monotonic if clock is None else clock
        self.temporary = None
        self.files = {}
        self.closed = False
        self.busy_until = 0.0
        self.priority = 0
        self.last_click = -math.inf
        if self.enabled:
            self._prepare()

    def _prepare(self):
        if self.files:
            return True
        if not self.available or self.closed:
            return False
        try:
            self.temporary = tempfile.TemporaryDirectory(prefix="ballistic-lab-audio-",
                                                          ignore_cleanup_errors=True)
            for name in DURATIONS:
                path = Path(self.temporary.name) / f"{name}.wav"
                write_effect(path, name, self.volume)
                self.files[name] = path
        except (OSError, ValueError, wave.Error):
            self.available = False
            self.files.clear()
            if self.temporary is not None:
                self.temporary.cleanup()
                self.temporary = None
            return False
        return True

    def play(self, name):
        if not self.enabled or not self.available or self.closed or name not in DURATIONS:
            return False
        now = self.clock()
        if now < self.busy_until and PRIORITIES[name] < self.priority:
            return False
        if name == "click" and now - self.last_click < 0.045:
            return False
        if not self._prepare():
            return False
        flags = self.backend.SND_FILENAME | self.backend.SND_ASYNC | self.backend.SND_NODEFAULT
        try:
            self.backend.PlaySound(str(self.files[name]), flags)
        except (OSError, RuntimeError):
            self.available = False
            return False
        self.busy_until = now + DURATIONS[name]
        self.priority = PRIORITIES[name]
        if name == "click":
            self.last_click = now
        return True

    def stop(self):
        if self.backend is not None and self.files and not self.closed:
            try:
                self.backend.PlaySound(None, 0)
            except (OSError, RuntimeError):
                pass
        self.busy_until = 0.0
        self.priority = 0
        self.last_click = -math.inf

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.stop()
        else:
            self._prepare()

    def close(self):
        if self.closed:
            return
        self.stop()
        self.closed = True
        self.files.clear()
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None
