"""Microphone capture. 16 kHz mono, what ASR models expect.

The stream stays open for the app's lifetime: opening a stream on key-press
costs 70-150ms plus hardware spin-up, which chops the first syllables off the
dictation. Instead we always capture into a small rolling pre-roll buffer and,
when recording starts, seed it with the last ~0.3s — catching speech that
began at (or just before) the key press. Audio outside a recording never
leaves the ring buffer and is discarded within PRE_ROLL_S.
"""

import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
PRE_ROLL_S = 0.3


class Recorder:
    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._ring: deque[tuple[float, np.ndarray]] = deque()
        self._stream: sd.InputStream | None = None
        self._recording = False
        self._lock = threading.Lock()
        # Rolling RMS levels for the waveform overlay (~50ms per chunk)
        self.levels: deque[float] = deque(maxlen=64)

    def open(self):
        """Open the persistent stream. Triggers the mic permission prompt on
        first ever run; the orange mic indicator stays on while wispa runs."""
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._on_audio,
        )
        self._stream.start()

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _on_audio(self, indata, frames, time_info, status):
        chunk = indata.copy()
        now = time.monotonic()
        with self._lock:
            if self._recording:
                self._chunks.append(chunk)
                self.levels.append(float(np.sqrt(np.mean(chunk**2))))
            else:
                self._ring.append((now, chunk))
                while self._ring and now - self._ring[0][0] > PRE_ROLL_S:
                    self._ring.popleft()

    def start(self):
        with self._lock:
            if self._recording:
                return
            # Seed with the pre-roll so speech that started early isn't lost
            self._chunks = [chunk for _, chunk in self._ring]
            self._ring.clear()
            self.levels.clear()
            self._recording = True

    def stop(self) -> np.ndarray:
        """Returns the recording as a 1-D float32 array at 16 kHz."""
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).flatten()
