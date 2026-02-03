"""Global hotkey handling using pynput."""

import threading
from typing import Callable, Literal

from pynput import keyboard


# Map modifier names to pynput keys
MODIFIER_MAP = {
    "cmd": keyboard.Key.cmd,
    "command": keyboard.Key.cmd,
    "ctrl": keyboard.Key.ctrl,
    "control": keyboard.Key.ctrl,
    "alt": keyboard.Key.alt,
    "option": keyboard.Key.alt,
    "shift": keyboard.Key.shift,
}

# Map key names to pynput keys
KEY_MAP = {
    "space": keyboard.Key.space,
    "enter": keyboard.Key.enter,
    "return": keyboard.Key.enter,
    "tab": keyboard.Key.tab,
    "escape": keyboard.Key.esc,
    "esc": keyboard.Key.esc,
    "backspace": keyboard.Key.backspace,
    "delete": keyboard.Key.delete,
    "up": keyboard.Key.up,
    "down": keyboard.Key.down,
    "left": keyboard.Key.left,
    "right": keyboard.Key.right,
    "f1": keyboard.Key.f1,
    "f2": keyboard.Key.f2,
    "f3": keyboard.Key.f3,
    "f4": keyboard.Key.f4,
    "f5": keyboard.Key.f5,
    "f6": keyboard.Key.f6,
    "f7": keyboard.Key.f7,
    "f8": keyboard.Key.f8,
    "f9": keyboard.Key.f9,
    "f10": keyboard.Key.f10,
    "f11": keyboard.Key.f11,
    "f12": keyboard.Key.f12,
}


class HotkeyListener:
    """Listens for global hotkeys and triggers callbacks."""

    def __init__(
        self,
        key: str,
        modifiers: list[str],
        mode: Literal["push-to-talk", "toggle"] = "push-to-talk",
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ):
        self.key_str = key.lower()
        # Check if the key itself is a modifier
        self.key_is_modifier = self.key_str in MODIFIER_MAP
        if self.key_is_modifier:
            self.key = MODIFIER_MAP[self.key_str]
        else:
            self.key = self._parse_key(key)
        self.modifiers = {MODIFIER_MAP[m.lower()] for m in modifiers if m.lower() in MODIFIER_MAP}
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop

        self._pressed_modifiers: set = set()
        self._hotkey_active = False
        self._recording = False
        self._listener: keyboard.Listener | None = None
        self._lock = threading.Lock()

    def _parse_key(self, key: str) -> keyboard.Key | keyboard.KeyCode:
        """Parse a key string into a pynput key."""
        key_lower = key.lower()
        if key_lower in KEY_MAP:
            return KEY_MAP[key_lower]
        # Single character keys
        if len(key) == 1:
            return keyboard.KeyCode.from_char(key.lower())
        raise ValueError(f"Unknown key: {key}")

    def _get_key_identity(self, key) -> keyboard.Key | keyboard.KeyCode | None:
        """Get a consistent identity for a key press."""
        if isinstance(key, keyboard.Key):
            return key
        if isinstance(key, keyboard.KeyCode):
            if key.char:
                return keyboard.KeyCode.from_char(key.char.lower())
            return key
        return None

    def _on_press(self, key) -> None:
        """Handle key press events."""
        key_id = self._get_key_identity(key)
        if key_id is None:
            return

        # Track modifier state
        if key_id in MODIFIER_MAP.values():
            self._pressed_modifiers.add(key_id)
            # If using modifier-only combo, check if all required keys are now pressed
            if self.key_is_modifier:
                # All modifiers + the trigger key must be pressed
                all_required = self.modifiers | {self.key}
                if all_required.issubset(self._pressed_modifiers):
                    self._trigger_start()
            return

        # Check if this is our hotkey (non-modifier key)
        if key_id != self.key:
            return

        # Check if all required modifiers are pressed
        if not self.modifiers.issubset(self._pressed_modifiers):
            return

        self._trigger_start()

    def _trigger_start(self) -> None:
        """Trigger recording start based on mode."""
        with self._lock:
            if self.mode == "push-to-talk":
                if not self._recording:
                    self._recording = True
                    if self.on_start:
                        self.on_start()
            else:  # toggle mode
                if not self._recording:
                    self._recording = True
                    if self.on_start:
                        self.on_start()
                else:
                    self._recording = False
                    if self.on_stop:
                        self.on_stop()

    def _on_release(self, key) -> None:
        """Handle key release events."""
        key_id = self._get_key_identity(key)
        if key_id is None:
            return

        # Track modifier state
        if key_id in MODIFIER_MAP.values():
            self._pressed_modifiers.discard(key_id)
            # In push-to-talk mode, stop recording if a required modifier or trigger key is released
            if self.mode == "push-to-talk" and self._recording:
                # Stop if this is the trigger key (when key is a modifier)
                if self.key_is_modifier and key_id == self.key:
                    self._trigger_stop()
                # Stop if any required modifier is released
                elif key_id in self.modifiers:
                    self._trigger_stop()
            return

        # Check if this is our hotkey being released
        if key_id != self.key:
            return

        # In push-to-talk mode, stop recording when key is released
        if self.mode == "push-to-talk":
            self._trigger_stop()

    def _trigger_stop(self) -> None:
        """Trigger recording stop."""
        with self._lock:
            if self._recording:
                self._recording = False
                if self.on_stop:
                    self.on_stop()

    def start(self) -> None:
        """Start listening for hotkeys."""
        if self._listener is not None:
            return

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        """Stop listening for hotkeys."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def is_recording(self) -> bool:
        """Check if currently in recording state."""
        with self._lock:
            return self._recording

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
