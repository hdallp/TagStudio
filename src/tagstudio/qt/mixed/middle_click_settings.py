from __future__ import annotations

from PySide6.QtCore import Qt, QSettings, QPoint
from pathlib import Path
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QPushButton,
    QLabel,
    QHBoxLayout,
)

from tagstudio.qt.mixed.middle_click_overlay import MiddleClickOverlay
import structlog

logger = structlog.get_logger(__name__)


class MiddleClickSettingsDialog(QDialog):
    """Settings dialog for the Middle Click plugin.

        Persisted via QSettings keys:
            - middle_click_enabled (bool)
            - middle_click_limit (int)
            - middle_click_apply_to_selected (bool)
            - middle_click_mod_ctrl (bool)
            - middle_click_mod_shift (bool)
            - middle_click_anim_in_enabled (bool)
            - middle_click_anim_in_duration (float, seconds)
            - middle_click_anim_out_enabled (bool)
            - middle_click_anim_out_duration (float, seconds)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Middle Click Settings")
        self.setModal(True)
        self.resize(420, 280)

        self.settings = QSettings()

        self.layout = QVBoxLayout(self)

        form = QFormLayout()

        # Enable
        self.enable_cb = QCheckBox("Enable Middle Click")
        self.enable_cb.setChecked(self.settings.value("middle_click_enabled", True, type=bool))
        form.addRow("Enabled:", self.enable_cb)

        # Apply to selected
        self.apply_cb = QCheckBox("Apply to selected when modifier pressed")
        self.apply_cb.setChecked(self.settings.value("middle_click_apply_to_selected", True, type=bool))
        form.addRow("Apply To Selected:", self.apply_cb)

        # Modifier choices
        self.mod_ctrl_cb = QCheckBox("Use Ctrl")
        self.mod_ctrl_cb.setChecked(self.settings.value("middle_click_mod_ctrl", True, type=bool))
        self.mod_shift_cb = QCheckBox("Use Shift")
        self.mod_shift_cb.setChecked(self.settings.value("middle_click_mod_shift", True, type=bool))
        mods_layout = QHBoxLayout()
        mods_layout.addWidget(self.mod_ctrl_cb)
        mods_layout.addWidget(self.mod_shift_cb)
        form.addRow("Modifiers:", mods_layout)

        # Limit
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 50)
        self.limit_spin.setValue(self.settings.value("middle_click_limit", 6, type=int))
        form.addRow("Options Limit:", self.limit_spin)

        # Animation: separate controls for In / Out
        self.anim_in_cb = QCheckBox("Enable In Animation")
        self.anim_in_cb.setChecked(self.settings.value("middle_click_anim_in_enabled", True, type=bool))
        self.anim_in_dur = QDoubleSpinBox()
        self.anim_in_dur.setRange(0.01, 5.0)
        self.anim_in_dur.setSingleStep(0.05)
        self.anim_in_dur.setValue(self.settings.value("middle_click_anim_in_duration", 0.35, type=float))
        anim_in_layout = QHBoxLayout()
        anim_in_layout.addWidget(self.anim_in_cb)
        anim_in_layout.addWidget(self.anim_in_dur)
        form.addRow("In Animation:", anim_in_layout)

        self.anim_out_cb = QCheckBox("Enable Out Animation")
        self.anim_out_cb.setChecked(self.settings.value("middle_click_anim_out_enabled", True, type=bool))
        self.anim_out_dur = QDoubleSpinBox()
        self.anim_out_dur.setRange(0.01, 5.0)
        self.anim_out_dur.setSingleStep(0.05)
        self.anim_out_dur.setValue(self.settings.value("middle_click_anim_out_duration", 0.12, type=float))
        anim_out_layout = QHBoxLayout()
        anim_out_layout.addWidget(self.anim_out_cb)
        anim_out_layout.addWidget(self.anim_out_dur)
        form.addRow("Out Animation:", anim_out_layout)

        self.layout.addLayout(form)

        # Live preview controls
        self.preview_label = QLabel("Preview:")
        self.layout.addWidget(self.preview_label)

        # Clickable preview image (uses a cached thumbnail if available)
        self.preview_image = QLabel()
        self.preview_image.setFixedSize(256, 256)
        self.preview_image.setStyleSheet("background-color: rgba(40,40,40,255); border: 1px solid #555;")
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.preview_image, alignment=Qt.AlignmentFlag.AlignCenter)

        # Save/close
        buttons = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.close_btn = QPushButton("Close")
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.close_btn)
        self.layout.addLayout(buttons)

        # signals
        self.enable_cb.stateChanged.connect(self._save_settings)
        self.apply_cb.stateChanged.connect(self._save_settings)
        self.mod_ctrl_cb.stateChanged.connect(self._save_settings)
        self.mod_shift_cb.stateChanged.connect(self._save_settings)
        self.limit_spin.valueChanged.connect(self._save_settings)
        self.anim_in_cb.stateChanged.connect(self._save_settings)
        self.anim_in_dur.valueChanged.connect(self._save_settings)
        self.anim_out_cb.stateChanged.connect(self._save_settings)
        self.anim_out_dur.valueChanged.connect(self._save_settings)
        self.save_btn.clicked.connect(self._on_save)
        self.close_btn.clicked.connect(self.accept)

        # clicking the preview image will open the interactive preview overlay
        self.preview_image.mousePressEvent = self._on_preview_image_click  # type: ignore[assignment]

        self._preview_overlay: MiddleClickOverlay | None = None
        # populate preview image initially
        try:
            self._update_preview_image()
        except Exception:
            pass

    def _save_settings(self):
        try:
            self.settings.setValue("middle_click_enabled", bool(self.enable_cb.isChecked()))
            self.settings.setValue("middle_click_apply_to_selected", bool(self.apply_cb.isChecked()))
            self.settings.setValue("middle_click_mod_ctrl", bool(self.mod_ctrl_cb.isChecked()))
            self.settings.setValue("middle_click_mod_shift", bool(self.mod_shift_cb.isChecked()))
            self.settings.setValue("middle_click_limit", int(self.limit_spin.value()))
            self.settings.setValue("middle_click_anim_in_enabled", bool(self.anim_in_cb.isChecked()))
            self.settings.setValue("middle_click_anim_in_duration", float(self.anim_in_dur.value()))
            self.settings.setValue("middle_click_anim_out_enabled", bool(self.anim_out_cb.isChecked()))
            self.settings.setValue("middle_click_anim_out_duration", float(self.anim_out_dur.value()))
            self.settings.sync()
            # Also update driver.cached_values (if available) so changes take effect immediately
            try:
                parent = self.parent()
                if parent is not None and hasattr(parent, "thumb_layout"):
                    tl = parent.thumb_layout
                    driver = getattr(tl, "driver", None)
                    if driver is not None and hasattr(driver, "cached_values"):
                        try:
                            # Write both flat keys (legacy) and a namespaced group for plugins
                            # Flat keys for backwards compatibility
                            driver.cached_values.setValue("middle_click_limit", int(self.limit_spin.value()))
                            driver.cached_values.setValue(
                                "middle_click_apply_to_selected",
                                bool(self.apply_cb.isChecked()),
                            )
                            driver.cached_values.setValue("middle_click_mod_ctrl", bool(self.mod_ctrl_cb.isChecked()))
                            driver.cached_values.setValue(
                                "middle_click_mod_shift", bool(self.mod_shift_cb.isChecked())
                            )
                            driver.cached_values.setValue(
                                "middle_click_anim_in_enabled", bool(self.anim_in_cb.isChecked())
                            )
                            driver.cached_values.setValue(
                                "middle_click_anim_in_duration", float(self.anim_in_dur.value())
                            )
                            driver.cached_values.setValue(
                                "middle_click_anim_out_enabled", bool(self.anim_out_cb.isChecked())
                            )
                            driver.cached_values.setValue(
                                "middle_click_anim_out_duration", float(self.anim_out_dur.value())
                            )
                            driver.cached_values.setValue("middle_click_enabled", bool(self.enable_cb.isChecked()))

                            # Also write into a namespaced group for easier discovery
                            try:
                                driver.cached_values.beginGroup("plugins/middle_click")
                                driver.cached_values.setValue("limit", int(self.limit_spin.value()))
                                driver.cached_values.setValue("apply_to_selected", bool(self.apply_cb.isChecked()))
                                driver.cached_values.setValue("mod_ctrl", bool(self.mod_ctrl_cb.isChecked()))
                                driver.cached_values.setValue("mod_shift", bool(self.mod_shift_cb.isChecked()))
                                driver.cached_values.setValue("anim_in_enabled", bool(self.anim_in_cb.isChecked()))
                                driver.cached_values.setValue("anim_in_duration", float(self.anim_in_dur.value()))
                                driver.cached_values.setValue("anim_out_enabled", bool(self.anim_out_cb.isChecked()))
                                driver.cached_values.setValue("anim_out_duration", float(self.anim_out_dur.value()))
                                driver.cached_values.setValue("enabled", bool(self.enable_cb.isChecked()))
                                driver.cached_values.endGroup()
                            except Exception:
                                # if grouping isn't available, ignore and continue
                                try:
                                    driver.cached_values.endGroup()
                                except Exception:
                                    pass

                            driver.cached_values.sync()
                            logger.info("Middle Click settings written to driver.cached_values", file=driver.cached_values.fileName())
                        except Exception:
                            logger.exception("Failed to set driver.cached_values via setValue")
            except Exception:
                logger.exception("Failed to update driver.cached_values with middle click settings")
        except Exception:
            logger.exception("Failed to save Middle Click settings")

    def _on_save(self):
        self._save_settings()
        self.accept()

    def _on_preview(self):
        try:
            # Close any existing preview overlay
            if self._preview_overlay is not None:
                try:
                    self._preview_overlay.close()
                except Exception:
                    pass
                self._preview_overlay = None
            # Try to pick a random rendered thumbnail from the main window's thumb layout
            parent = self.parent()
            driver = None
            entry_id = None
            tl = None
            try:
                if parent is not None and hasattr(parent, "thumb_layout"):
                    tl = parent.thumb_layout
                    driver = getattr(tl, "driver", None)
                    # collect candidate rendered results (exclude the loading placeholder Path())
                    candidates = [k for k in list(tl._render_results.keys()) if k != Path()]
                    import random

                    if candidates:
                        sample = random.choice(candidates)
                        # map file path to entry id
                        if sample in tl._entry_paths:
                            entry_id = tl._entry_paths[sample]
            except Exception:
                logger.exception("Failed to select a cached thumbnail for preview")

            # Fallback: if we couldn't find a rendered thumbnail, try driver.cache_manager files
            if entry_id is None and driver is not None:
                try:
                    files = []
                    for cache_folder in getattr(driver, "cache_manager", object()).folders or []:
                        for f in cache_folder.path.iterdir():
                            files.append(f)
                    if files:
                        import random

                        chosen = random.choice(files)
                        # try to find a matching entry id by checking thumb_layout._entry_paths keys
                        for p, eid in tl._entry_paths.items():
                            try:
                                if p.name == chosen.name:
                                    entry_id = eid
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass

            # If we still have no entry, show a small sample overlay with placeholder labels
            opts = []
            if entry_id is None or driver is None:
                sample_labels = ["One", "Two", "Three", "Four", "Five", "Extra"]
                for i, lbl in enumerate(sample_labels[: self.limit_spin.value()]):
                    opts.append((lbl, lambda: None))
            else:
                # Build options from recent tags (driver.get_recent_tags) and fallback search
                lim = int(self.limit_spin.value())
                recent_ids = []
                try:
                    if hasattr(driver, "get_recent_tags"):
                        recent_ids = driver.get_recent_tags(lim)
                except Exception:
                    recent_ids = []

                seen = set()
                tag_objs = []
                try:
                    for tid in recent_ids:
                        if tid in seen:
                            continue
                        t = driver.lib.get_tag(tid)
                        if not t:
                            continue
                        tag_objs.append((tid, t))
                        seen.add(tid)
                except Exception:
                    pass

                # fallback
                try:
                    if len(tag_objs) < lim:
                        search_res = driver.lib.search_tags(None, limit=lim * 2)
                        direct = []
                        if isinstance(search_res, list) and len(search_res) > 0:
                            direct = list(search_res[0])
                        for t in direct:
                            if len(tag_objs) >= lim:
                                break
                            if not t:
                                continue
                            if t.id in seen:
                                continue
                            tag_objs.append((t.id, t))
                            seen.add(t.id)
                except Exception:
                    logger.exception("Preview: failed to fetch fallback tags")

                # Build callbacks that will apply the selected tag to the sampled entry
                for tid, tag in tag_objs[:lim]:
                    def make_cb(tag_id, eid):
                        def cb():
                            try:
                                # update UI
                                try:
                                    driver.main_window.thumb_layout.add_tags([eid], [tag_id])
                                except Exception:
                                    pass
                                # persist
                                try:
                                    driver.lib.add_tags_to_entries(eid, tag_id)
                                except Exception:
                                    logger.exception("Preview: failed to add tag to entry")
                                # record MRU
                                try:
                                    if hasattr(driver, "record_tag_usage"):
                                        driver.record_tag_usage(tag_id)
                                except Exception:
                                    logger.exception("Preview: record_tag_usage failed")
                            except Exception:
                                logger.exception("Preview callback failed")

                        return cb

                    opts.append((tag.name, make_cb(tid, entry_id), tag))

            self._preview_overlay = MiddleClickOverlay(parent=self)
            self._preview_overlay.options = opts
            # apply in/out animation settings to overlay
            try:
                s = QSettings()
                in_enabled = bool(s.value("middle_click_anim_in_enabled", True, type=bool))
                in_dur = float(s.value("middle_click_anim_in_duration", 0.35, type=float))
                out_enabled = bool(s.value("middle_click_anim_out_enabled", True, type=bool))
                out_dur = float(s.value("middle_click_anim_out_duration", 0.12, type=float))
            except Exception:
                in_enabled, in_dur, out_enabled, out_dur = True, 0.35, True, 0.12
            self._preview_overlay.anim_in_duration = in_dur
            self._preview_overlay.anim_out_duration = out_dur
            self._preview_overlay.anim_enabled = bool(in_enabled)
            self._preview_overlay.anim_out_enabled = bool(out_enabled)
            center = self.mapToGlobal(self.rect().center())
            self._preview_overlay.show_at(center)
        except Exception:
            logger.exception("Preview failed")

    def _update_preview_image(self):
        """Populate the preview image label with a cached thumbnail if available."""
        try:
            parent = self.parent()
            if parent is None or not hasattr(parent, "thumb_layout"):
                return
            tl = parent.thumb_layout
            # prefer a real rendered result
            candidates = [k for k in list(tl._render_results.keys()) if k != Path()]
            pix = None
            if candidates:
                # take first candidate's pixmap
                sample = candidates[0]
                res = tl._render_results.get(sample)
                if res and len(res) >= 2:
                    _, qpix, _, _ = res
                    pix = qpix
            if pix is not None:
                self.preview_image.setPixmap(pix.scaled(self.preview_image.size(), Qt.AspectRatioMode.KeepAspectRatio))
            else:
                # fallback: clear
                self.preview_image.setPixmap(QPixmap())
        except Exception:
            logger.exception("Failed to update preview image")

    def _on_preview_image_click(self, event):
        # when the image is clicked, open the interactive overlay using the first available entry
        try:
            parent = self.parent()
            if parent is None or not hasattr(parent, "thumb_layout"):
                return
            tl = parent.thumb_layout
            driver = getattr(tl, "driver", None)
            entry_id = None
            candidates = [k for k in list(tl._render_results.keys()) if k != Path()]
            if candidates:
                sample = candidates[0]
                if sample in tl._entry_paths:
                    entry_id = tl._entry_paths[sample]

            if entry_id is None:
                return

            # reuse the preview-building logic but target the entry_id
            lim = int(self.limit_spin.value())
            recent_ids = []
            try:
                if hasattr(driver, "get_recent_tags"):
                    recent_ids = driver.get_recent_tags(lim)
            except Exception:
                recent_ids = []

            seen = set()
            tag_objs = []
            try:
                for tid in recent_ids:
                    if tid in seen:
                        continue
                    t = driver.lib.get_tag(tid)
                    if not t:
                        continue
                    tag_objs.append((tid, t))
                    seen.add(tid)
            except Exception:
                pass

            try:
                if len(tag_objs) < lim:
                    search_res = driver.lib.search_tags(None, limit=lim * 2)
                    direct = []
                    if isinstance(search_res, list) and len(search_res) > 0:
                        direct = list(search_res[0])
                    for t in direct:
                        if len(tag_objs) >= lim:
                            break
                        if not t:
                            continue
                        if t.id in seen:
                            continue
                        tag_objs.append((t.id, t))
                        seen.add(t.id)
            except Exception:
                logger.exception("Preview click: failed to fetch fallback tags")

            opts = []
            for tid, tag in tag_objs[:lim]:
                def make_cb(tag_id, eid):
                    def cb():
                        try:
                            try:
                                driver.main_window.thumb_layout.add_tags([eid], [tag_id])
                            except Exception:
                                pass
                            try:
                                driver.lib.add_tags_to_entries(eid, tag_id)
                            except Exception:
                                logger.exception("Preview click: failed to add tag to entry")
                            try:
                                if hasattr(driver, "record_tag_usage"):
                                    driver.record_tag_usage(tag_id)
                            except Exception:
                                logger.exception("Preview click: record_tag_usage failed")
                        except Exception:
                            logger.exception("Preview click callback failed")

                    return cb

                opts.append((tag.name, make_cb(tid, entry_id), tag))

            overlay = MiddleClickOverlay(parent=parent)
            overlay.options = opts
            # apply current animation settings from the dialog controls
            try:
                overlay.anim_in_duration = float(self.anim_in_dur.value())
                overlay.anim_out_duration = float(self.anim_out_dur.value())
                overlay.anim_enabled = bool(self.anim_in_cb.isChecked())
                overlay.anim_out_enabled = bool(self.anim_out_cb.isChecked())
            except Exception:
                pass
            center = parent.mapToGlobal(parent.rect().center())
            overlay.show_at(center)
        except Exception:
            logger.exception("Preview image click failed")

    def _on_close_preview(self):
        try:
            if self._preview_overlay is not None:
                self._preview_overlay.close()
                self._preview_overlay = None
        except Exception:
            pass
