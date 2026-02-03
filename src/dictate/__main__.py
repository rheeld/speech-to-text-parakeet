"""CLI entry point for dictate."""

import argparse
import json
import os
import subprocess
import sys
import threading
import time

from .audio import AudioCapture
from .config import (
    Config,
    create_default_config,
    load_config,
    parse_keybinding,
)
from .hotkey import HotkeyListener
from .output import output_text, play_sound
from .transcribe import Transcriber


class Dictate:
    """Main dictation application."""

    def __init__(self, config: Config):
        self.config = config
        self.audio = AudioCapture(sample_rate=16000)
        self.transcriber = Transcriber(config.transcription.model)
        self._transcription_thread: threading.Thread | None = None
        self._streaming_thread: threading.Thread | None = None
        self._stop_streaming = threading.Event()
        self._last_partial = ""
        self._last_transcribe_time = 0.0
        self._overlay_proc: subprocess.Popen | None = None

    def _start_overlay(self) -> None:
        """Spawn the overlay subprocess (starts hidden)."""
        if self._overlay_proc and self._overlay_proc.poll() is None:
            return
        self._overlay_proc = subprocess.Popen(
            [sys.executable, "-m", "dictate.overlay"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def _send_overlay(self, action: str, **kwargs: str) -> None:
        """Send a command to the overlay subprocess."""
        if self._overlay_proc and self._overlay_proc.poll() is None:
            try:
                msg = json.dumps({"action": action, **kwargs})
                self._overlay_proc.stdin.write(msg + "\n")
                self._overlay_proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def _close_overlay(self) -> None:
        """Shut down the overlay subprocess."""
        if self._overlay_proc:
            try:
                self._send_overlay("quit")
                self._overlay_proc.wait(timeout=2)
            except Exception:
                self._overlay_proc.kill()
            self._overlay_proc = None

    def _on_start(self) -> None:
        """Called when recording starts."""
        self._stop_streaming.clear()
        self._last_partial = ""
        # Start recording BEFORE the sound so no audio is lost
        self.audio.start()
        # Play start sound as confirmation (non-blocking)
        play_sound("Glass", background=True)
        print("\n🎙️  Recording... (release to transcribe)")

        # Show overlay
        self._start_overlay()
        self._send_overlay("show", status="🎙️ Listening...")

        # Start streaming transcription in background
        self._streaming_thread = threading.Thread(target=self._stream_transcription)
        self._streaming_thread.start()

    def _stream_transcription(self) -> None:
        """Periodically transcribe and display partial results.

        When stop is signaled, does one final transcription pass on the
        complete audio so _on_stop can use the result directly without
        re-running the model.
        """
        # Short initial delay to get some audio
        if self._stop_streaming.wait(timeout=0.4):
            self._final_streaming_pass()
            return

        while not self._stop_streaming.is_set():
            # Get current audio
            audio_data = self.audio.get_audio()
            if len(audio_data) < 4800:  # Less than 0.3 seconds
                if self._stop_streaming.wait(timeout=0.2):
                    break
                continue

            try:
                text = self.transcriber.transcribe(audio_data)
                self._last_transcribe_time = time.monotonic()
                if text and text != self._last_partial:
                    # Update overlay
                    self._send_overlay("update", text=text)

                    # Show in terminal — truncate to terminal width
                    try:
                        cols = os.get_terminal_size().columns
                    except OSError:
                        cols = 80
                    line = f"💬 {text}"
                    if len(line) > cols:
                        line = line[: cols - 1] + "…"
                    sys.stdout.write(f"\r\033[2K{line}")
                    sys.stdout.flush()
                    self._last_partial = text
            except Exception:
                pass  # Ignore errors during streaming

            # Wait before next update
            if self._stop_streaming.wait(timeout=0.6):
                break

        # Final pass on complete audio before exiting
        self._final_streaming_pass()

    def _final_streaming_pass(self) -> None:
        """One last transcription of the full audio buffer.

        Skipped if a streaming transcription completed very recently
        (< 0.8s ago), since that result already covers nearly all audio.
        """
        if time.monotonic() - self._last_transcribe_time < 0.8:
            return

        audio_data = self.audio.get_audio()
        if len(audio_data) < 1600:
            return
        try:
            text = self.transcriber.transcribe(audio_data)
            if text:
                self._last_partial = text
        except Exception:
            pass

    def _on_stop(self) -> None:
        """Called when recording stops."""
        # Signal streaming thread — it will do a final transcription pass
        # and then exit. Event.wait() returns immediately once set, so
        # the thread wakes up from any sleep instantly.
        self._stop_streaming.set()

        # Hide overlay immediately
        self._send_overlay("hide")

        # Play stop sound non-blocking (was blocking before)
        play_sound("Pop", background=True)
        print("\r\033[K⏳ Finalizing...")

        # Finalize in background to avoid blocking the hotkey thread
        def finalize():
            # Wait for streaming thread's final transcription pass
            if self._streaming_thread:
                self._streaming_thread.join(timeout=5.0)

            # Clean up audio capture
            self.audio.stop()

            text = self._last_partial
            if text:
                print(f"\n{'─' * 40}")
                print(text)
                print(f"{'─' * 40}\n")

                output_text(
                    text,
                    method=self.config.output.method,
                    sound=self.config.output.sound,
                )
            else:
                print("❌ No speech detected")

        self._transcription_thread = threading.Thread(target=finalize)
        self._transcription_thread.start()

    def run(self) -> None:
        """Run the dictation loop."""
        kb = self.config.keybinding
        modifiers_str = "+".join(m.capitalize() for m in kb.modifiers)
        key_str = kb.key.capitalize()
        hotkey_display = f"{modifiers_str}+{key_str}" if modifiers_str else key_str

        print(f"🎤 Dictate is running!")
        print(f"   Mode: {kb.mode}")
        print(f"   Hotkey: {hotkey_display}")
        print(f"   Output: {self.config.output.method}")
        print(f"   Model: {self.config.transcription.model}")
        print()

        if kb.mode == "push-to-talk":
            print(f"Hold {hotkey_display} to record, release to transcribe.")
        else:
            print(f"Press {hotkey_display} to start/stop recording.")

        print("Press Ctrl+C to exit.\n")

        # Pre-load the model
        print("Loading transcription model (first run may download ~1.2GB)...")
        try:
            self.transcriber._load_model()
        except Exception as e:
            print(f"Failed to load model: {e}")
            sys.exit(1)

        print("Ready!\n")

        listener = HotkeyListener(
            key=kb.key,
            modifiers=kb.modifiers,
            mode=kb.mode,
            on_start=self._on_start,
            on_stop=self._on_stop,
        )

        try:
            with listener:
                # Keep the main thread alive
                while True:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
        finally:
            self._close_overlay()
            self.audio.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Local real-time speech dictation using MLX"
    )
    parser.add_argument(
        "--mode",
        choices=["push-to-talk", "toggle"],
        help="Recording mode (default: from config or push-to-talk)",
    )
    parser.add_argument(
        "--key",
        help="Hotkey combination (e.g., 'cmd+shift+space')",
    )
    parser.add_argument(
        "--model",
        help="Transcription model (e.g., 'mlx-community/parakeet-tdt-0.6b-v3')",
    )
    parser.add_argument(
        "--output",
        choices=["clipboard", "type", "paste"],
        help="Output method (default: from config or paste)",
    )
    parser.add_argument(
        "--no-sound",
        action="store_true",
        help="Disable sound feedback",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Create default config file and exit",
    )

    args = parser.parse_args()

    # Handle --init-config
    if args.init_config:
        create_default_config()
        from .config import CONFIG_FILE
        print(f"Created default config at: {CONFIG_FILE}")
        return

    # Load config
    config = load_config()

    # Override with command line arguments
    if args.mode:
        config.keybinding.mode = args.mode

    if args.key:
        modifiers, key = parse_keybinding(args.key)
        config.keybinding.modifiers = modifiers
        config.keybinding.key = key

    if args.model:
        config.transcription.model = args.model

    if args.output:
        config.output.method = args.output

    if args.no_sound:
        config.output.sound = False

    # Run the app
    app = Dictate(config)
    app.run()


if __name__ == "__main__":
    main()
