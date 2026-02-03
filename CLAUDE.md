# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

```bash
uv pip install -e .          # install in dev mode
dictate                      # run with default config (~/.dictate/config.toml)
dictate --init-config        # generate default config file
dictate --mode toggle --key space --output clipboard  # CLI overrides
```

No test suite exists yet. To manually test the overlay subprocess:
```bash
python -c "
import subprocess, sys, time, json
p = subprocess.Popen([sys.executable, '-m', 'dictate.overlay'], stdin=subprocess.PIPE, text=True)
time.sleep(0.3)
p.stdin.write(json.dumps({'action': 'show', 'status': '🎙️ Listening...'}) + '\n'); p.stdin.flush()
time.sleep(2)
p.stdin.write(json.dumps({'action': 'update', 'text': 'Hello world'}) + '\n'); p.stdin.flush()
time.sleep(2)
p.stdin.write(json.dumps({'action': 'hide'}) + '\n'); p.stdin.flush()
time.sleep(0.5)
p.stdin.write(json.dumps({'action': 'quit'}) + '\n'); p.stdin.flush()
p.wait()
"
```

## Architecture

macOS-only dictation tool. Push-to-talk or toggle hotkey triggers local speech-to-text via Parakeet MLX, with a floating overlay showing real-time transcription and an animated waveform.

### Threading model

- **Main thread:** pynput hotkey listener (blocking)
- **Streaming thread:** polls audio buffer every ~600ms, runs transcriber, sends partial results to overlay
- **Finalize thread:** spawned on stop — joins streaming thread, uses its last result directly (no re-transcription), outputs text
- **Overlay stdin reader:** daemon thread in the overlay subprocess dispatching JSON commands to the main AppKit thread

### Overlay is a subprocess

`overlay.py` runs as a separate process (`python -m dictate.overlay`). The main process sends JSON-line commands to its stdin:
```json
{"action": "show", "status": "🎙️ Listening..."}
{"action": "update", "text": "partial transcription"}
{"action": "hide"}
{"action": "quit"}
```

The overlay uses PyObjC (NSPanel, NSView) directly. The `WaveformView` draws animated bars via NSBezierPath and NSTimer. UI updates from the stdin reader thread are dispatched to the AppKit main thread via `performSelectorOnMainThread:`.

### Transcription pipeline

`Transcriber.transcribe()` writes audio to a temp WAV file because parakeet-mlx expects a file path, not raw arrays. The streaming thread transcribes the full accumulated buffer each poll (not incremental). On stop, if the last streaming transcription was recent (<0.8s), the final pass is skipped entirely — `_last_partial` is used as the final result to minimize paste latency.

### Output methods

`paste` (default): copies to clipboard via pyperclip then simulates Cmd+V via CGEvent with explicit modifier flags (strips any held physical modifiers). `type`: AppleScript keystroke. `clipboard`: copy only.

## Key conventions

- Uses `uv` instead of `pip`, `bun` instead of `npm`
- macOS-native APIs throughout: Quartz CGEvent for key simulation, AppKit for overlay UI
- Pyright warnings on PyObjC imports (e.g. `NSView is unknown import symbol`) are expected and harmless — PyObjC stubs are incomplete
- Config lives at `~/.dictate/config.toml` (TOML format)
