"""Microphone capture while the hotkey is held. 16 kHz mono, what ASR models expect."""

import threading
from collections import deque

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000


class Recorder:
    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        # Rolling RMS levels for the waveform overlay (~50ms per chunk)
        self.levels: deque[float] = deque(maxlen=64)

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self):
        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []
            self.levels.clear()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                callback=self._on_audio,
            )
            self._stream.start()

    def _on_audio(self, indata, frames, time_info, status):
        self._chunks.append(indata.copy())
        self.levels.append(float(np.sqrt(np.mean(indata**2))))

    def stop(self) -> np.ndarray:
        """Returns the recording as a 1-D float32 array at 16 kHz."""
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks).flatten()
