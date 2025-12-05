from __future__ import annotations

from typing import Callable, List, Optional, Tuple, Any
import math
import time

from PySide6.QtCore import QPoint, Qt, QTimer, QRect
from PySide6.QtGui import QColor, QMouseEvent, QPaintEvent, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget
import structlog

logger = structlog.get_logger(__name__)
from tagstudio.qt.mixed.tag_widget import (
    get_primary_color,
    get_border_color,
    get_highlight_color,
    get_text_color,
)


class MiddleClickOverlay(QWidget):
    """A lightweight transient overlay widget showing options around a click point.

    Usage: instantiate with a parent (usually the main window), pass a list of
    (label, callback) pairs, then call ``show_at(global_point)``. The overlay
    will run an entry animation and call the callback when an option is chosen.
    """

    def __init__(self, parent=None, options: List[Tuple[str, Callable]] | None = None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.options = options or []
        self.center: Optional[QPoint] = None
        self._center_global: Optional[QPoint] = None
        self.effects: list[dict] = []
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_tick)
        self.anim_in_duration = 0.35
        self.anim_out_duration = 0.12
        self.anim_enabled = True
        # allow separately disabling out animation
        self.anim_out_enabled = True
        # closing state used to play out-animation before actually closing
        self._closing = False
        self._closing_start: Optional[float] = None
        self._hit_regions: List[Tuple[QRect, int]] = []
        # timer to check mouse distance and auto-close when pointer moves away
        self._leave_timer = QTimer(self)
        self._leave_timer.setInterval(200)
        self._leave_timer.timeout.connect(self._on_leave_check)
        # pixels from center after which overlay will auto-close
        self._leave_distance = 220
        # Track the currently active overlay so only one can be shown at once
        # Class-level reference is used to ensure global single-instance behavior
        try:
            MiddleClickOverlay._active_instance  # type: ignore[attr-defined]
        except Exception:
            MiddleClickOverlay._active_instance = None  # type: ignore[attr-defined]

    def show_at(self, global_point: QPoint) -> None:
        # Ensure only one overlay is active at a time
        try:
            if MiddleClickOverlay._active_instance is not None and MiddleClickOverlay._active_instance is not self:
                try:
                    MiddleClickOverlay._active_instance.close()
                except Exception:
                    pass
        except Exception:
            pass

        # position the overlay full-screen over the parent window
        parent = self.parent() or self.window()
        geo = parent.geometry()
        self.setGeometry(geo)
        # convert global to overlay-local
        local = self.mapFromGlobal(global_point)
        self.center = QPoint(local.x(), local.y())
        # remember center in global coords for leave checks
        self._center_global = QPoint(global_point.x(), global_point.y())

        # prepare effects
        self.effects.clear()
        count = max(1, len(self.options))
        widget_cx = geo.width() / 2
        widget_cy = geo.height() / 2
        baseline = math.atan2(widget_cy - self.center.y(), widget_cx - self.center.x())
        sector = math.pi
        if count == 1:
            angles = [baseline]
        else:
            angles = [baseline - sector / 2 + (sector * i / (count - 1)) for i in range(count)]

        for opt, angle in zip(self.options, angles):
            # option can be (label, callback) or (label, callback, meta)
            label = opt[0]
            meta: Any = opt[2] if len(opt) > 2 else None
            e = {
                "center": QPoint(self.center.x(), self.center.y()),
                "angle": angle,
                "text": label,
                "meta": meta,
                "start": time.time(),
                "progress": 0.0,
                "radius": 18,
                "target_w": 100,
                "target_h": 36,
            }
            self.effects.append(e)

        if self.anim_enabled:
            self.anim_timer.start()
        else:
            for e in self.effects:
                e["progress"] = 1.0

        logger.info("[Overlay] show_at", global_point=(global_point.x(), global_point.y()), options_len=len(self.options))
        # start leave-check timer so overlay closes when mouse moves away
        self._leave_timer.start()
        # mark as active
        try:
            MiddleClickOverlay._active_instance = self
        except Exception:
            pass
        self.show()
        self.update()

    def _on_anim_tick(self) -> None:
        if not self.effects:
            self.anim_timer.stop()
            return
        self.update()
        # animation tick -- no debug logging to reduce noise

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        pos = event.position()
        p = QPoint(int(pos.x()), int(pos.y()))
        # minimal logging: only log clicks that resulted in an option
        for rect, idx in list(self._hit_regions):
            if rect.contains(p) and 0 <= idx < len(self.options):
                logger.info("[Overlay] option clicked", idx=idx, label=self.options[idx][0])
                opt = self.options[idx]
                # opt can be (label, callback) or (label, callback, meta)
                try:
                    cb = opt[1]
                except Exception:
                    cb = None
                if cb:
                    try:
                        cb()
                    except Exception:
                        logger.exception("[Overlay] option callback failed")
                # close immediately after selecting an option
                self.close()
                return
        # not clicking an option — animate out if possible
        try:
            self._start_close()
        except Exception:
            self.close()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        super().mouseMoveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self.center:
            return
        painter = QPainter(self)
        now = time.time()
        self._hit_regions = []
        still_running = False
        for idx, e in enumerate(list(self.effects)):
            elapsed = now - e.get("start", now)
            if self._closing:
                # play out animation
                if not self.anim_out_enabled:
                    prog = 0.0
                else:
                    closing_elapsed = now - (self._closing_start or now)
                    t_out = min(1.0, closing_elapsed / max(1e-6, self.anim_out_duration))
                    # easing for out: cubic ease-out (reverse of in)
                    prog = pow(max(0.0, 1.0 - t_out), 3)
                    if t_out < 1.0:
                        still_running = True
            else:
                if self.anim_enabled:
                    t = min(1.0, elapsed / max(1e-6, self.anim_in_duration))
                    prog = 1 - pow(1 - t, 3)
                    if prog < 1.0:
                        still_running = True
                else:
                    prog = 1.0
            e["progress"] = prog

            rw = self.width()
            rh = self.height()
            base_dist = min(max(80, min(rw, rh) // 4), 140)
            dist = base_dist * prog
            cx = int(e["center"].x() + math.cos(e["angle"]) * dist)
            cy = int(e["center"].y() + math.sin(e["angle"]) * dist)
            w = int(e["target_w"] * (0.6 + 0.4 * prog))
            h = int(e["target_h"] * (0.6 + 0.4 * prog))
            x = cx - w // 2
            y = cy - h // 2

            alpha = int(220 * (0.6 + 0.4 * prog))
            # If meta is a Tag-like object with color info, use its colors
            meta = e.get("meta")
            if meta is not None:
                try:
                    primary_q = get_primary_color(meta)
                    border_q = get_border_color(primary_q)
                    highlight_q = get_highlight_color(primary_q)
                    text_q = (
                        QColor(meta.color.secondary)
                        if (hasattr(meta, "color") and meta.color and meta.color.secondary)
                        else get_text_color(primary_q, highlight_q)
                    )
                    fill = QColor(primary_q)
                    fill.setAlpha(alpha)
                    border = QColor(border_q)
                    border.setAlpha(220)
                    painter.setBrush(fill)
                    pen = QPen(border, 2)
                    painter.setPen(pen)
                except Exception:
                    fill = QColor(230, 230, 230, alpha)
                    border = QColor(180, 90, 90, 220)
                    painter.setBrush(fill)
                    pen = QPen(border, 2)
                    painter.setPen(pen)
            else:
                fill = QColor(230, 230, 230, alpha)
                border = QColor(180, 90, 90, 220)
                painter.setBrush(fill)
                pen = QPen(border, 2)
                painter.setPen(pen)
            corner_radius = int(min(w, h) * 0.45)
            painter.drawRoundedRect(x, y, w, h, corner_radius, corner_radius)

            self._hit_regions.append((QRect(x, y, w, h), idx))

            # draw text using tag text color when available
            try:
                if e.get("meta") is not None:
                    meta = e.get("meta")
                    primary_q = get_primary_color(meta)
                    highlight_q = get_highlight_color(primary_q)
                    text_q = (
                        QColor(meta.color.secondary)
                        if (hasattr(meta, "color") and meta.color and meta.color.secondary)
                        else get_text_color(primary_q, highlight_q)
                    )
                    painter.setPen(QPen(text_q))
                else:
                    painter.setPen(QPen(QColor(10, 10, 10, 230)))
            except Exception:
                painter.setPen(QPen(QColor(10, 10, 10, 230)))
            font = QFont()
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(x, y, w, h, Qt.AlignmentFlag.AlignCenter, e["text"]) 

        if not still_running and self.anim_timer.isActive():
            self.anim_timer.stop()
            # if we finished closing animation, actually close the widget
            if self._closing:
                try:
                    super().close()
                except Exception:
                    pass

    def closeEvent(self, event) -> None:
        logger.info("[Overlay] close")
        self.effects.clear()
        self._hit_regions.clear()
        try:
            if self.anim_timer.isActive():
                self.anim_timer.stop()
        except Exception:
            pass
        try:
            if self._leave_timer.isActive():
                self._leave_timer.stop()
        except Exception:
            pass
        try:
            if getattr(MiddleClickOverlay, "_active_instance", None) is self:
                MiddleClickOverlay._active_instance = None
        except Exception:
            pass
        super().closeEvent(event)

    def _on_leave_check(self) -> None:
        """Close the overlay if the cursor is too far from the click center."""
        try:
            from PySide6.QtGui import QCursor

            if not self._center_global:
                return
            cur = QCursor.pos()
            dx = cur.x() - int(self._center_global.x())
            dy = cur.y() - int(self._center_global.y())
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > self._leave_distance:
                # start closing animation instead of immediate close
                try:
                    self._start_close()
                except Exception:
                    self.close()
        except Exception:
            # silently ignore leave-check failures
            return

    def _start_close(self) -> None:
        """Begin the out animation and schedule actual close when finished."""
        # If already closing, nothing to do
        if self._closing:
            return
        # If out-animation disabled, close immediately
        if not getattr(self, "anim_out_enabled", True) or not getattr(self, "anim_enabled", True):
            super().close()
            return
        self._closing = True
        self._closing_start = time.time()
        # ensure anim timer is running to drive the out animation
        try:
            if not self.anim_timer.isActive():
                self.anim_timer.start()
        except Exception:
            pass
