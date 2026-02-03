"""Speech transcription using Parakeet MLX."""

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf


class Transcriber:
    """Transcribes audio using Parakeet TDT model via parakeet-mlx."""

    def __init__(self, model_name: str = "mlx-community/parakeet-tdt-0.6b-v3"):
        self.model_name = model_name
        self._model = None

    def _load_model(self) -> None:
        """Lazy load the model on first use."""
        if self._model is not None:
            return

        print(f"Loading model {self.model_name}...")
        try:
            from parakeet_mlx import from_pretrained

            self._model = from_pretrained(self.model_name)
            print("Model loaded successfully.")
        except ImportError:
            raise ImportError(
                "parakeet-mlx is required. Install with: uv pip install parakeet-mlx"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load model: {e}")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe audio array to text.

        Args:
            audio: Audio data as float32 numpy array
            sample_rate: Sample rate of the audio (default 16000)

        Returns:
            Transcribed text
        """
        self._load_model()

        if len(audio) == 0:
            return ""

        # Ensure audio is the right format
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Normalize if needed (should be in range [-1, 1])
        max_val = np.abs(audio).max()
        if max_val > 1.0:
            audio = audio / max_val

        try:
            # Write audio to temp file (parakeet-mlx expects a file path)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = Path(f.name)
                sf.write(temp_path, audio, sample_rate)

            try:
                result = self._model.transcribe(temp_path)
                # AlignedResult has .text attribute
                if hasattr(result, 'text'):
                    return result.text.strip()
                else:
                    return str(result).strip()
            finally:
                # Clean up temp file
                temp_path.unlink(missing_ok=True)

        except Exception as e:
            print(f"Transcription error: {e}")
            return ""

    def transcribe_file(self, path: str | Path) -> str:
        """Transcribe audio from a file.

        Args:
            path: Path to audio file

        Returns:
            Transcribed text
        """
        self._load_model()

        try:
            result = self._model.transcribe(path)
            if hasattr(result, 'text'):
                return result.text.strip()
            else:
                return str(result).strip()
        except Exception as e:
            print(f"Transcription error: {e}")
            return ""
