"""Output handling - clipboard and typing via CGEvent."""

import subprocess
import time
from typing import Literal

import pyperclip
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    CGEventSourceCreate,
    kCGEventFlagMaskCommand,
    kCGEventSourceStateCombinedSessionState,
    kCGSessionEventTap,
)

V_KEY = 0x09


def _cg_keypress(key_code: int, flags: int = 0) -> None:
    """Simulate a keypress via CGEvent with explicit modifier flags.

    Setting flags explicitly strips any physical modifier state (e.g. held
    Cmd+Opt), so the target app only sees the flags we specify.
    """
    source = CGEventSourceCreate(kCGEventSourceStateCombinedSessionState)
    down = CGEventCreateKeyboardEvent(source, key_code, True)
    up = CGEventCreateKeyboardEvent(source, key_code, False)
    CGEventSetFlags(down, flags)
    CGEventSetFlags(up, flags)
    CGEventPost(kCGSessionEventTap, down)
    CGEventPost(kCGSessionEventTap, up)


def cg_paste() -> None:
    """Simulate Cmd+V with only the Command flag set."""
    _cg_keypress(V_KEY, kCGEventFlagMaskCommand)


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard."""
    pyperclip.copy(text)


def paste_text(text: str) -> None:
    """Copy text to clipboard and paste it via CGEvent Cmd+V."""
    if not text:
        return
    copy_to_clipboard(text)
    time.sleep(0.03)
    cg_paste()


def type_text(text: str) -> None:
    """Type text into the active application using AppleScript."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "System Events" to keystroke "{escaped}"'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Failed to type text: {e}")
        copy_to_clipboard(text)
        print("Text copied to clipboard instead.")


def play_sound(sound_name: str = "Pop", background: bool = False) -> None:
    """Play a system sound using afplay.

    Args:
        sound_name: Name of the system sound to play.
        background: If True, play asynchronously (don't block).
    """
    sound_paths = [
        f"/System/Library/Sounds/{sound_name}.aiff",
        f"/System/Library/Sounds/{sound_name}.wav",
    ]

    for path in sound_paths:
        try:
            if background:
                subprocess.Popen(
                    ["afplay", path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.run(
                    ["afplay", path],
                    check=True,
                    capture_output=True,
                )
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    try:
        subprocess.run(
            ["osascript", "-e", "beep"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass


def output_text(
    text: str,
    method: Literal["clipboard", "type", "paste"] = "paste",
    sound: bool = True,
) -> None:
    """Output transcribed text using the specified method."""
    if not text:
        return

    if method == "type":
        type_text(text)
    elif method == "paste":
        paste_text(text)
    else:
        copy_to_clipboard(text)

    if sound:
        play_sound()
