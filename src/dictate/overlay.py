"""Floating overlay for dictation feedback. Runs as a subprocess.

Reads JSON-line commands from stdin:
  {"action": "show", "status": "..."}
  {"action": "update", "text": "..."}
  {"action": "hide"}
  {"action": "quit"}
"""

import json
import math
import random
import sys
import threading
import time

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSFont,
    NSLineBreakByWordWrapping,
    NSPanel,
    NSScreen,
    NSTextField,
    NSTimer,
    NSView,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject, NSRect

PANEL_WIDTH = 560
TEXT_WIDTH = PANEL_WIDTH - 32
STATUS_H = 18
WAVEFORM_H = 28
PAD_TOP = 12
PAD_STATUS_WAVE = 4
PAD_WAVE_TEXT = 8
PAD_BOT = 12
MIN_TEXT_H = 0

NUM_BARS = 50
BAR_GAP = 2
BAR_WIDTH = (TEXT_WIDTH - (NUM_BARS - 1) * BAR_GAP) / NUM_BARS
BAR_MIN_H = 2
FPS_INTERVAL = 0.08


def _screen_for_mouse():
    """Return the NSScreen containing the mouse cursor."""
    mouse = NSEvent.mouseLocation()
    for screen in NSScreen.screens():
        frame = screen.frame()
        if (
            frame.origin.x <= mouse.x <= frame.origin.x + frame.size.width
            and frame.origin.y <= mouse.y <= frame.origin.y + frame.size.height
        ):
            return screen
    return NSScreen.mainScreen()


def _bar_color(i, n):
    """Return a gradient color from cyan-blue (left) to purple (right)."""
    t = i / max(n - 1, 1)
    # cyan-blue: (0.3, 0.7, 1.0) → purple: (0.65, 0.3, 0.95)
    r = 0.3 + t * 0.35
    g = 0.7 - t * 0.4
    b = 1.0 - t * 0.05
    return NSColor.colorWithRed_green_blue_alpha_(r, g, b, 0.9)


class WaveformView(NSView):
    def init(self):
        self = objc.super(WaveformView, self).init()
        if self is None:
            return None
        self._heights = [0.0] * NUM_BARS
        self._targets = [0.0] * NUM_BARS
        self._timer = None
        self._phase = 0.0
        self._start_time = time.monotonic()
        # Per-bar random offsets for phase and frequency — breaks uniformity
        self._bar_phase = [random.uniform(0, math.tau) for _ in range(NUM_BARS)]
        self._bar_freq = [random.uniform(0.7, 1.4) for _ in range(NUM_BARS)]
        # Slow-moving per-bar drift targets (updated sporadically)
        self._drift = [random.uniform(-0.15, 0.15) for _ in range(NUM_BARS)]
        self._tick_count = 0
        return self

    def drawRect_(self, rect):
        frame = self.bounds()
        h = frame.size.height

        for i in range(NUM_BARS):
            bar_h = max(self._heights[i] * h, BAR_MIN_H)
            x = i * (BAR_WIDTH + BAR_GAP)
            y = (h - bar_h) / 2

            color = _bar_color(i, NUM_BARS)
            color.setFill()

            rx = BAR_WIDTH / 2
            ry = min(BAR_WIDTH / 2, bar_h / 2)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSRect((x, y), (BAR_WIDTH, bar_h)), rx, ry
            )
            path.fill()

    @objc.python_method
    def _tick(self):
        t = time.monotonic() - self._start_time
        self._phase = t * 3.0
        self._tick_count += 1

        # Every ~6 frames, randomly re-roll drift for a handful of bars
        # so individual bars occasionally spike or dip independently
        if self._tick_count % 6 == 0:
            for _ in range(NUM_BARS // 5):
                idx = random.randint(0, NUM_BARS - 1)
                self._drift[idx] = random.uniform(-0.25, 0.25)

        for i in range(NUM_BARS):
            pos = i / NUM_BARS
            phi = self._bar_phase[i]
            freq = self._bar_freq[i]

            # Base wave with per-bar phase/freq offsets
            val = 0.45 + 0.2 * math.sin(self._phase * freq + pos * 5.0 + phi)
            # Second harmonic at a different speed
            val += 0.12 * math.sin(self._phase * 1.8 * freq + pos * 9.0 + phi * 0.7)
            # Third faster harmonic for texture
            val += 0.08 * math.sin(self._phase * 3.1 + pos * 14.0 + phi * 1.3)
            # Per-bar drift (slow-changing random bias)
            val += self._drift[i]
            # Strong random jitter per frame per bar
            val += random.uniform(-0.15, 0.15)
            # Occasional random spikes on individual bars
            if random.random() < 0.04:
                val += random.choice([-0.3, 0.3])

            self._targets[i] = max(0.06, min(1.0, val))

        # Lighter smoothing so jitter comes through faster
        for i in range(NUM_BARS):
            self._heights[i] += (self._targets[i] - self._heights[i]) * 0.5

        self.setNeedsDisplay_(True)

    def animationTick_(self, timer):
        self._tick()

    @objc.python_method
    def start(self):
        if self._timer is not None:
            return
        self._start_time = time.monotonic()
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            FPS_INTERVAL, self, b"animationTick:", None, True
        )

    @objc.python_method
    def stop(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None


class Overlay(NSObject):
    def init(self):
        self = objc.super(Overlay, self).init()
        if self is None:
            return None

        self._top_y = 0
        self._has_text = False

        compact_h = PAD_TOP + STATUS_H + PAD_STATUS_WAVE + WAVEFORM_H + PAD_BOT
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (PANEL_WIDTH, compact_h)),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setOpaque_(False)
        self.panel.setAlphaValue_(0.95)
        self.panel.setHasShadow_(True)
        # Panel background must be fully clear so the rounded content view
        # is the only thing visible — otherwise macOS draws square corners.
        self.panel.setBackgroundColor_(NSColor.clearColor())

        cv = self.panel.contentView()
        cv.setWantsLayer_(True)
        cv.layer().setCornerRadius_(14)
        cv.layer().setMasksToBounds_(True)
        from Quartz import CGColorCreateGenericRGB
        cv.layer().setBackgroundColor_(
            CGColorCreateGenericRGB(0.11, 0.11, 0.17, 0.95)
        )

        # Status label
        self.status_label = self._make_label(11, NSColor.grayColor())
        cv.addSubview_(self.status_label)

        # Waveform view
        self.waveform = WaveformView.alloc().init()
        self.waveform.setFrame_(((16, 0), (TEXT_WIDTH, WAVEFORM_H)))
        cv.addSubview_(self.waveform)

        # Transcription text label
        self.text_label = self._make_label(15, NSColor.whiteColor())
        self.text_label.cell().setWraps_(True)
        self.text_label.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
        self.text_label.setMaximumNumberOfLines_(0)
        self.text_label.setPreferredMaxLayoutWidth_(TEXT_WIDTH)
        cv.addSubview_(self.text_label)

        return self

    @objc.python_method
    def _make_label(self, size, color):
        tf = NSTextField.alloc().initWithFrame_(((0, 0), (TEXT_WIDTH, 20)))
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        tf.setTextColor_(color)
        tf.setFont_(NSFont.systemFontOfSize_(size))
        tf.setStringValue_("")
        return tf

    @objc.python_method
    def _layout(self):
        """Recalculate panel height and reposition subviews."""
        text_val = self.text_label.stringValue()
        self._has_text = bool(text_val)

        if self._has_text:
            cell = self.text_label.cell()
            text_h = cell.cellSizeForBounds_(((0, 0), (TEXT_WIDTH, 10000))).height
            text_h = max(text_h, 20)
            h = PAD_TOP + STATUS_H + PAD_STATUS_WAVE + WAVEFORM_H + PAD_WAVE_TEXT + text_h + PAD_BOT
        else:
            text_h = 0
            h = PAD_TOP + STATUS_H + PAD_STATUS_WAVE + WAVEFORM_H + PAD_BOT

        # Keep top edge pinned — grow downward
        new_y = self._top_y - h
        self.panel.setFrame_display_(
            ((self.panel.frame().origin.x, new_y), (PANEL_WIDTH, h)), True
        )

        # Position subviews top-down (macOS y=0 is bottom)
        y_cursor = h - PAD_TOP - STATUS_H
        self.status_label.setFrame_(((16, y_cursor), (TEXT_WIDTH, STATUS_H)))

        y_cursor -= PAD_STATUS_WAVE + WAVEFORM_H
        self.waveform.setFrame_(((16, y_cursor), (TEXT_WIDTH, WAVEFORM_H)))

        if self._has_text:
            self.text_label.setFrame_(((16, PAD_BOT), (TEXT_WIDTH, text_h)))
            self.text_label.setHidden_(False)
        else:
            self.text_label.setFrame_(((16, PAD_BOT), (TEXT_WIDTH, 0)))
            self.text_label.setHidden_(True)

    @objc.python_method
    def _position_on_screen(self):
        """Position panel at top-center of the screen containing the mouse."""
        screen = _screen_for_mouse()
        sf = screen.frame()
        vf = screen.visibleFrame()
        x = sf.origin.x + (sf.size.width - PANEL_WIDTH) / 2
        self._top_y = vf.origin.y + vf.size.height - 12
        self._layout()
        frame = self.panel.frame()
        self.panel.setFrame_display_(
            ((x, frame.origin.y), (PANEL_WIDTH, frame.size.height)), True
        )

    def handleCommand_(self, cmd_str):
        try:
            msg = json.loads(cmd_str)
        except (json.JSONDecodeError, TypeError):
            return

        action = msg.get("action")
        if action == "show":
            self.status_label.setStringValue_(msg.get("status", ""))
            self.text_label.setStringValue_("")
            self._position_on_screen()
            self.panel.orderFront_(None)
            self.waveform.start()
        elif action == "update":
            self.text_label.setStringValue_(msg.get("text", ""))
            self._layout()
        elif action == "hide":
            self.waveform.stop()
            self.panel.orderOut_(None)
        elif action == "quit":
            self.waveform.stop()
            NSApplication.sharedApplication().terminate_(None)

    def terminate_(self, sender):
        self.waveform.stop()
        NSApplication.sharedApplication().terminate_(None)


def _stdin_reader(overlay):
    """Read commands from stdin and dispatch to main thread."""
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            overlay.performSelectorOnMainThread_withObject_waitUntilDone_(
                b"handleCommand:", line, False
            )
    except Exception:
        pass
    overlay.performSelectorOnMainThread_withObject_waitUntilDone_(
        b"terminate:", None, False
    )


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    overlay = Overlay.alloc().init()

    reader = threading.Thread(target=_stdin_reader, args=(overlay,), daemon=True)
    reader.start()

    app.run()


if __name__ == "__main__":
    main()
