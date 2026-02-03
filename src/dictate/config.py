"""Configuration loading from ~/.dictate/config.toml."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

try:
    import tomllib
except ImportError:
    import tomli as tomllib


CONFIG_DIR = Path.home() / ".dictate"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_CONFIG = """\
[keybinding]
mode = "push-to-talk"  # or "toggle"
key = "alt"  # alt = option on Mac
modifiers = ["cmd"]

[transcription]
model = "mlx-community/parakeet-tdt-0.6b-v3"
# Alternative: "mlx-community/whisper-large-v3-turbo"

[output]
method = "paste"  # "paste" (auto-paste), "clipboard" (copy only), or "type" (keystroke)
sound = true
"""


@dataclass
class KeybindingConfig:
    mode: Literal["push-to-talk", "toggle"] = "push-to-talk"
    key: str = "alt"  # alt = option on Mac
    modifiers: list[str] = field(default_factory=lambda: ["cmd"])


@dataclass
class TranscriptionConfig:
    model: str = "mlx-community/parakeet-tdt-0.6b-v2"


@dataclass
class OutputConfig:
    method: Literal["clipboard", "type", "paste"] = "paste"
    sound: bool = True


@dataclass
class Config:
    keybinding: KeybindingConfig = field(default_factory=KeybindingConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def ensure_config_dir() -> None:
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def create_default_config() -> None:
    """Create default config file if it doesn't exist."""
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG)


def load_config() -> Config:
    """Load configuration from file or return defaults."""
    config = Config()

    if CONFIG_FILE.exists():
        try:
            data = tomllib.loads(CONFIG_FILE.read_text())

            if "keybinding" in data:
                kb = data["keybinding"]
                config.keybinding = KeybindingConfig(
                    mode=kb.get("mode", "push-to-talk"),
                    key=kb.get("key", "space"),
                    modifiers=kb.get("modifiers", ["cmd", "shift"]),
                )

            if "transcription" in data:
                tr = data["transcription"]
                config.transcription = TranscriptionConfig(
                    model=tr.get("model", "mlx-community/parakeet-tdt-0.6b-v2"),
                )

            if "output" in data:
                out = data["output"]
                config.output = OutputConfig(
                    method=out.get("method", "clipboard"),
                    sound=out.get("sound", True),
                )
        except Exception as e:
            print(f"Warning: Error loading config: {e}. Using defaults.")

    return config


def parse_keybinding(key_str: str) -> tuple[list[str], str]:
    """Parse keybinding string like 'cmd+shift+space' into modifiers and key."""
    parts = key_str.lower().split("+")
    key = parts[-1]
    modifiers = parts[:-1] if len(parts) > 1 else []
    return modifiers, key
