"""Microphone audio capture using sounddevice."""

import threading
from collections import deque
from typing import Callable

import numpy as np
import sounddevice as sd


class AudioCapture:
    """Captures audio from microphone with configurable sample rate."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._buffer: deque[np.ndarray] = deque()
        self._recording = False
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._callback: Callable[[np.ndarray], None] | None = None

    def _audio_callback(
        self, indata: np.ndarray, frames: int, time_info, status
    ) -> None:
        """Called by sounddevice for each audio block."""
        if status:
            print(f"Audio status: {status}")
        if self._recording:
            # Copy the data to avoid issues with buffer reuse
            audio_chunk = indata.copy().flatten()
            with self._lock:
                self._buffer.append(audio_chunk)
            # Call streaming callback if set
            if self._callback:
                self._callback(audio_chunk)

    def start(self, streaming_callback: Callable[[np.ndarray], None] | None = None) -> None:
        """Start recording audio."""
        self._callback = streaming_callback
        self._buffer.clear()
        self._recording = True

        if self._stream is None:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32,
                callback=self._audio_callback,
                blocksize=int(self.sample_rate * 0.1),  # 100ms blocks
            )
            self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return accumulated audio."""
        self._recording = False

        with self._lock:
            if self._buffer:
                audio = np.concatenate(list(self._buffer))
            else:
                audio = np.array([], dtype=np.float32)
            self._buffer.clear()

        return audio

    def close(self) -> None:
        """Close the audio stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def get_audio(self) -> np.ndarray:
        """Get current buffered audio without stopping."""
        with self._lock:
            if self._buffer:
                return np.concatenate(list(self._buffer))
            return np.array([], dtype=np.float32)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
