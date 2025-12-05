"""Small demo widget to test middle-click behavior.

Run as a script to open a window. Middle-click anywhere in the gray area
and the widget will log to the terminal and draw a gray-filled circle with
a red border at the click location.

This file is intended as a local testbed before integrating behavior into
`ItemThumb`.
"""
from __future__ import annotations

from typing import List, Tuple, Optional
import math
import time

from PySide6.QtCore import QPoint, Qt, QTimer, QRect
from PySide6.QtGui import QColor, QMouseEvent, QPaintEvent, QPainter, QPen, QFont
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QMenu,
)


class MiddleClickDemo(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Middle Click Demo")
        self.setMinimumSize(640, 480)
        # Only one central circle at a time
        self.center_circle: Optional[Tuple[QPoint, int]] = None

        # Options shown around the click point.
        self.options: List[str] = [f"Option {i+1}" for i in range(4)]

        # Animation control
        self.anim_enabled = True
        self.effects: List[dict] = []
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)  # ~60 FPS
        self.anim_timer.timeout.connect(self._on_anim_tick)
        self.anim_in_duration = 0.45  # seconds per effect
        self.anim_out_duration = 0.1  # seconds per effect
        # Auto-close settings
        self.auto_close_enabled = True
        self.auto_close_distance = 200

        # Track mouse moves even when no button is pressed
        self.setMouseTracking(True)

        # hit regions used for option clicks
        self._hit_regions: List[Tuple[QRect, int]] = []

        # Simple UI hint
        layout = QVBoxLayout(self)
        label = QLabel("Middle-click anywhere to draw a gray circle with a red border")
        layout.addWidget(label)

        # Controls: toggle animation and auto-close
        controls = QHBoxLayout()
        self.anim_checkbox = QCheckBox("Enable animation")
        self.anim_checkbox.setChecked(True)
        self.anim_checkbox.stateChanged.connect(lambda s: self._set_anim_enabled(s == Qt.CheckState.Checked))
        controls.addWidget(self.anim_checkbox)

        # Option to use native dropdown menu (no animation)
        self.native_menu_checkbox = QCheckBox("Use native menu")
        self.native_menu_checkbox.setChecked(False)
        self.native_menu_checkbox.stateChanged.connect(lambda s: self._set_native_menu(s == Qt.CheckState.Checked))
        controls.addWidget(self.native_menu_checkbox)

        self.auto_close_checkbox = QCheckBox("Auto-close on move")
        self.auto_close_checkbox.setChecked(True)
        self.auto_close_checkbox.stateChanged.connect(lambda s: self._set_auto_close(s == Qt.CheckState.Checked))
        controls.addWidget(self.auto_close_checkbox)

        controls.addStretch(1)

        self.auto_close_spin = QSpinBox()
        self.auto_close_spin.setRange(50, 1000)
        self.auto_close_spin.setValue(self.auto_close_distance)
        self.auto_close_spin.setSuffix(" px")
        self.auto_close_spin.valueChanged.connect(lambda v: self._set_auto_close_distance(v))
        controls.addWidget(self.auto_close_spin)

        layout.addLayout(controls)

        # Whether to use the native QMenu dropdown instead of the animated overlay
        self.use_native_menu = False

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton:
            pf = event.position()
            pos = QPoint(int(pf.x()), int(pf.y()))
            # If using the native dropdown menu, show a QMenu and return
            if self.use_native_menu:
                menu = QMenu(self)
                for idx, label in enumerate(self.options):
                    a = menu.addAction(label)
                    a.triggered.connect(lambda checked=False, i=idx: self._on_native_action(i))
                # Show menu at global position
                global_pos = self.mapToGlobal(pos)
                menu.exec(global_pos)
                return

            radius = 24
            # Replace the central circle (always only one)
            self.center_circle = (QPoint(pos.x(), pos.y()), radius)
            print(f"Middle-click at: ({pos.x()}, {pos.y()})")

            # Create option effects arranged radially from the click point for the
            # currently visible options (page slice). Each effect stores its start time
            # and will be animated by the timer.
            visible = self.options
            count = max(1, len(visible))
            self.effects.clear()
            # Clear hit regions; they will be recomputed during paint
            self._hit_regions: List[Tuple[QRect, int]] = []
            # Distribute options evenly in a semicircle pointing toward the
            # center of the widget so items don't go off-screen.
            rw = self.width()
            rh = self.height()
            # baseline angle points from click toward widget center
            widget_cx = rw / 2
            widget_cy = rh / 2
            baseline = math.atan2(widget_cy - pos.y(), widget_cx - pos.x())

            # sector size (radians) for distribution (semicircle)
            sector = math.pi
            if count == 1:
                angles = [baseline]
            else:
                angles = [baseline - sector / 2 + (sector * i / (count - 1)) for i in range(count)]

            for idx, (text, angle) in enumerate(zip(visible, angles)):
                effect = {
                    "center": QPoint(pos.x(), pos.y()),
                    "angle": angle,
                    "text": text,
                    "start": time.time(),
                    "progress": 0.0,
                    "radius": 18,
                    "target_w": 84,
                    "target_h": 36,
                }
                self.effects.append(effect)

            if self.anim_enabled:
                if not self.anim_timer.isActive():
                    self.anim_timer.start()
            else:
                # Immediately set progress to finished so shapes draw in place
                for e in self.effects:
                    e["progress"] = 1.0
            self.update()
            # Do not call super() — we handled the event here.
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        # Detect left-clicks on option circles and execute their action.
        # If clicking outside any option, just close the options (no selection).
        if event.button() == Qt.MouseButton.LeftButton and self._hit_regions is not None:
            pf = event.position()
            pos = QPoint(int(pf.x()), int(pf.y()))
            for rect, idx in list(self._hit_regions):
                if rect.contains(pos):
                    # idx maps directly to options list (no paging)
                    if 0 <= idx < len(self.options):
                        opt = self.options[idx]
                        print(f"Option selected: {opt}")
                        # Placeholder action: you can replace this with a callback
                        # Clear effects and close the option UI
                        # Close with reverse animation if enabled
                        if self.anim_enabled:
                            self._start_reverse_close()
                        else:
                            self.effects.clear()
                            self._hit_regions.clear()
                            self.center_circle = None
                        self.update()
                        return

            # Clicked left but not on any option: close options without selecting
            if self.anim_enabled:
                self._start_reverse_close()
            else:
                self.effects.clear()
                self._hit_regions.clear()
                self.center_circle = None
            self.update()
            return

        return super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        # Auto-close when moving too far from click origin
        if self.auto_close_enabled and self.center_circle is not None:
            center, _ = self.center_circle
            pf = event.position()
            pos = QPoint(int(pf.x()), int(pf.y()))
            dx = pos.x() - center.x()
            dy = pos.y() - center.y()
            dist = math.hypot(dx, dy)
            if dist > self.auto_close_distance:
                # close options
                if self.effects:
                    if self.anim_enabled:
                        self._start_reverse_close()
                    else:
                        self.effects.clear()
                        self._hit_regions.clear()
                        self.center_circle = None
                    self.update()
                    return

        return super().mouseMoveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        # Draw central circle (only one at a time)
        if self.center_circle is not None:
            center, radius = self.center_circle
            brush_color = QColor(180, 180, 180, 220)
            painter.setBrush(brush_color)
            pen = QPen(QColor(200, 30, 30), 3)
            painter.setPen(pen)
            x = center.x() - radius
            y = center.y() - radius
            diameter = radius * 2
            painter.drawEllipse(x, y, diameter, diameter)

        # Draw animated option rectangles (or static if animation disabled)
        now = time.time()
        still_running = False
        # We'll recompute hit regions for current effects so clicks can be detected.
        self._hit_regions = []
        for idx, e in enumerate(list(self.effects)):
            # Support reverse-close animation: if reverse_start present, decay from
            # reverse_progress_start down to 0. Otherwise progress grows from 0->1.
            elapsed = now - e.get("start", now)
            prog = e.get("progress", 0.0)
            # forward animation
            if "reverse_start" not in e:
                if not self.anim_enabled:
                    prog = 1.0
                else:
                    t = min(1.0, elapsed / max(1e-6, self.anim_in_duration))
                    prog = 1 - pow(1 - t, 3)
                    if prog < 1.0:
                        still_running = True
                e["progress"] = prog
            else:
                # reverse animation: linearly decay from reverse_progress_start to 0
                rev_elapsed = now - e["reverse_start"]
                start_p = e.get("reverse_progress_start", e.get("progress", 1.0))
                if self.anim_enabled:
                    frac = min(1.0, rev_elapsed / max(1e-6, self.anim_out_duration))
                    prog = max(0.0, start_p * (1.0 - frac))
                    if prog > 0.0:
                        still_running = True
                else:
                    prog = 0.0
                e["progress"] = prog

            # Compute a base distance for options that avoids overlap and fits on screen
            rw = self.width()
            rh = self.height()
            margin = 12
            max_radius = max(80, min(rw, rh) // 4)
            base_dist = min(max_radius, 120)

            dist = base_dist * prog
            cx = int(e["center"].x() + math.cos(e["angle"]) * dist)
            cy = int(e["center"].y() + math.sin(e["angle"]) * dist)

            # If the proposed rect would be off-screen, clamp position to keep on-screen
            w = int(e["target_w"] * (0.6 + 0.4 * prog))
            h = int(e["target_h"] * (0.6 + 0.4 * prog))
            w = max(8, w)
            h = max(8, h)
            x_test = cx - w // 2
            y_test = cy - h // 2
            out_of_bounds = x_test < margin or y_test < margin or (x_test + w) > (rw - margin) or (y_test + h) > (rh - margin)
            if out_of_bounds:
                # flip to opposite side relative to center and clamp
                new_angle = e["angle"] + math.pi
                cx = int(e["center"].x() + math.cos(new_angle) * dist)
                cy = int(e["center"].y() + math.sin(new_angle) * dist)
                x_test = cx - w // 2
                y_test = cy - h // 2
                x_test = min(max(margin, x_test), rw - margin - w)
                y_test = min(max(margin, y_test), rh - margin - h)
                cx = x_test + w // 2
                cy = y_test + h // 2

            x = cx - w // 2
            y = cy - h // 2

            # colors fade slightly
            alpha = int(220 * (0.6 + 0.4 * prog))
            fill = QColor(200, 200, 200, alpha)
            border = QColor(200, 30, 30, 220)

            painter.setBrush(fill)
            pen = QPen(border, 2)
            painter.setPen(pen)
            # rounded rectangle to simulate border-radius
            # draw rounded rectangle with a very large corner radius so it looks almost circular
            corner_radius = int(min(w, h) * 0.45)
            painter.drawRoundedRect(x, y, w, h, corner_radius, corner_radius)

            # record hit region for click testing (use QRect)
            self._hit_regions.append((QRect(x, y, w, h), idx))

            # draw option text centered
            painter.setPen(QPen(QColor(10, 10, 10, 230)))
            font = QFont()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(x, y, w, h, Qt.AlignmentFlag.AlignCenter, e["text"]) 

        if not still_running and self.anim_timer.isActive():
            self.anim_timer.stop()

        # If all effects are finished and we are in reverse-close mode, clear state
        # so central circle fully disappears.
        if not still_running and any("reverse_start" in e for e in self.effects):
            # all reversed out
            self.effects.clear()
            self._hit_regions.clear()
            self.center_circle = None
            self.update()

    def _on_anim_tick(self) -> None:
        """Called by the QTimer to advance animation frames."""
        # If no active effects, stop timer
        if not self.effects:
            if self.anim_timer.isActive():
                self.anim_timer.stop()
            return

        # Trigger a repaint; paintEvent will check effect progress and stop timer
        self.update()

    def _set_anim_enabled(self, enabled: bool) -> None:
        """Enable/disable animation. When disabling, advance effects to final state."""
        self.anim_enabled = enabled
        if not enabled:
            # finalize effects so they draw in final position
            for e in self.effects:
                e["progress"] = 1.0
            if self.anim_timer.isActive():
                self.anim_timer.stop()
            self.update()
        else:
            if self.effects and not self.anim_timer.isActive():
                self.anim_timer.start()

    def _set_native_menu(self, enabled: bool) -> None:
        """Enable/disable using the native QMenu instead of the animated overlay."""
        self.use_native_menu = bool(enabled)

    def _on_native_action(self, idx: int) -> None:
        """Handler for native menu actions."""
        if 0 <= idx < len(self.options):
            opt = self.options[idx]
            print(f"Native Option selected: {opt}")
        # Ensure no overlay state remains
        self.effects.clear()
        self._hit_regions.clear()
        self.center_circle = None
        self.update()

    def _set_auto_close(self, enabled: bool) -> None:
        """Enable/disable auto-close on mouse move away."""
        self.auto_close_enabled = enabled

    def _set_auto_close_distance(self, value: int) -> None:
        """Set the auto-close distance in pixels."""
        try:
            self.auto_close_distance = int(value)
        except Exception:
            pass

    def _start_reverse_close(self) -> None:
        """Begin reverse animation for all current effects (close animation).

        If animation is disabled, this immediately clears effects/state.
        """
        if not self.anim_enabled:
            self.effects.clear()
            self._hit_regions.clear()
            self.center_circle = None
            return

        now = time.time()
        for e in self.effects:
            e["reverse_start"] = now
            e["reverse_progress_start"] = e.get("progress", 1.0)
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    # paging removed — no _page method needed


def main() -> None:
    app = QApplication([])
    w = MiddleClickDemo()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
