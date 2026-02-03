# Dictate

Local real-time speech-to-text dictation for macOS using [Parakeet MLX](https://github.com/senstella/parakeet-mlx). Hold a hotkey, speak, release — transcribed text is pasted into whatever app has focus.

Everything runs on-device. No network requests, no cloud APIs.

## Requirements

- macOS (uses AppKit, Quartz)
- Python >= 3.11
- Apple Silicon recommended (MLX acceleration)

## Install

```bash
uv pip install -e .
```

The first run downloads the Parakeet TDT model (~1.2 GB) to `~/.cache/huggingface/`.

## Usage

```bash
dictate
```

Default hotkey is **Cmd+Option** (push-to-talk). Hold it to record, release to transcribe and paste.

### CLI options

```
dictate --mode toggle          # press once to start, again to stop
dictate --key cmd+shift+space  # custom hotkey
dictate --output clipboard     # copy only, don't auto-paste
dictate --output type          # type via AppleScript instead of paste
dictate --model mlx-community/whisper-large-v3-turbo
dictate --no-sound             # disable audio feedback
dictate --init-config          # write default config to ~/.dictate/config.toml
```

## Configuration

Config file: `~/.dictate/config.toml`

```toml
[keybinding]
mode = "push-to-talk"  # or "toggle"
key = "alt"            # alt = option on Mac
modifiers = ["cmd"]

[transcription]
model = "mlx-community/parakeet-tdt-0.6b-v3"

[output]
method = "paste"  # "paste", "clipboard", or "type"
sound = true
```

Run `dictate --init-config` to generate this file. CLI flags override config values.

## Output methods

| Method      | Behaviour                                          |
|-------------|----------------------------------------------------|
| `paste`     | Copies text to clipboard and simulates Cmd+V       |
| `clipboard` | Copies text to clipboard only                      |
| `type`      | Types text via AppleScript keystroke simulation     |

## How it works

1. A global hotkey listener (pynput) triggers audio recording via sounddevice
2. While recording, a background thread transcribes the growing audio buffer every ~600ms and streams partial results to a floating overlay
3. The overlay runs as a separate subprocess (AppKit NSPanel) and receives updates as JSON over stdin
4. On release, the last transcription result is used directly (no redundant re-processing) and pasted into the active app via CGEvent

## Permissions

macOS will prompt for:

- **Microphone access** (audio recording)
- **Accessibility** (simulating keypresses for paste/type and listening for global hotkeys)

Grant these to your terminal emulator (e.g. Terminal, iTerm2, Ghostty).
