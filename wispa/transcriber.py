"""On-device ASR with NVIDIA Parakeet running on MLX (Apple Silicon).

We feed the mic buffer straight to the model (log-mel -> generate) instead of
going through model.transcribe(path), which would decode a file with ffmpeg —
no temp files, no ffmpeg dependency, less latency.
"""

import time

import numpy as np


class Transcriber:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self._model = None

    def load(self):
        """Downloads weights on first run (~600MB), then loads from cache."""
        from parakeet_mlx import from_pretrained

        t0 = time.perf_counter()
        self._model = from_pretrained(self.model_id)
        # Warm-up inference so the first real dictation isn't slow
        self.transcribe(np.zeros(8000, dtype=np.float32))
        return time.perf_counter() - t0

    def transcribe(self, audio: np.ndarray) -> str:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        if self._model is None:
            self.load()
        if len(audio) == 0:
            return ""
        # Must be float32: get_logmel bit-views the complex STFT as pairs of the
        # input dtype, which only lines up for float32 (complex64 = 2x float32)
        mel = get_logmel(mx.array(audio, dtype=mx.float32), self._model.preprocessor_config)
        result = self._model.generate(mel)[0]
        return result.text.strip()
