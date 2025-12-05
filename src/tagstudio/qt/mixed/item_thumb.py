# Copyright (C) 2025 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio


from enum import Enum
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, override

import structlog
from PIL import Image, ImageQt
from PySide6.QtCore import QEvent, QMimeData, QSize, Qt, QUrl, QSettings
from PySide6.QtGui import QAction, QDrag, QEnterEvent, QGuiApplication, QMouseEvent, QPixmap
from PySide6.QtWidgets import QBoxLayout, QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tagstudio.qt.models.palette import ColorType, UiColor, get_ui_color
from tagstudio.qt.mixed.middle_click_overlay import MiddleClickOverlay

from tagstudio.core.constants import TAG_ARCHIVED, TAG_FAVORITE
from tagstudio.core.library.alchemy.enums import ItemType
from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.media_types import MediaCategories, MediaType
from tagstudio.core.utils.types import unwrap
from tagstudio.qt.platform_strings import open_file_str, trash_term
from tagstudio.qt.translations import Translations
from tagstudio.qt.utils.file_opener import FileOpenerHelper
from tagstudio.qt.views.layouts.flow_layout import FlowWidget
from tagstudio.qt.views.thumb_button import ThumbButton

if TYPE_CHECKING:
    from tagstudio.core.library.alchemy.models import Entry
    from tagstudio.qt.ts_qt import QtDriver

logger = structlog.get_logger(__name__)


class BadgeType(Enum):
    FAVORITE = "Favorite"
    ARCHIVED = "Archived"


BADGE_TAGS = {
    BadgeType.FAVORITE: TAG_FAVORITE,
    BadgeType.ARCHIVED: TAG_ARCHIVED,
}


def badge_update_lock(func):
    """Prevent recursively triggering badge updates."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.driver.badge_update_lock:
            return

        self.driver.badge_update_lock = True
        try:
            func(self, *args, **kwargs)
        except Exception:
            raise
        finally:
            self.driver.badge_update_lock = False

    return wrapper


class ItemThumb(FlowWidget):
    """The thumbnail widget for a library item (Entry, Collation, Tag Group, etc.)."""

    collation_icon_128: Image.Image = Image.open(
        str(Path(__file__).parents[2] / "resources/qt/images/collation_icon_128.png")
    )
    collation_icon_128.load()

    tag_group_icon_128: Image.Image = Image.open(
        str(Path(__file__).parents[2] / "resources/qt/images/tag_group_icon_128.png")
    )
    tag_group_icon_128.load()

    small_text_style = (
        "background-color:rgba(0, 0, 0, 192);"
        "color:#FFFFFF;"
        "font-family:Oxanium;"
        "font-weight:bold;"
        "font-size:12px;"
        "border-radius:3px;"
        "padding-top: 4px;"
        "padding-right: 1px;"
        "padding-bottom: 1px;"
        "padding-left: 1px;"
    )

    med_text_style = (
        "background-color:rgba(0, 0, 0, 192);"
        "color:#FFFFFF;"
        "font-family:Oxanium;"
        "font-weight:bold;"
        "font-size:18px;"
        "border-radius:3px;"
        "padding-top: 4px;"
        "padding-right: 1px;"
        "padding-bottom: 1px;"
        "padding-left: 1px;"
    )

    filename_style = "font-size:10px;"

    def __init__(
        self,
        mode: ItemType | None,
        library: Library,
        driver: "QtDriver",
        thumb_size: tuple[int, int],
        show_filename_label: bool = False,
    ):
        super().__init__()
        self.lib = library
        self.mode: ItemType | None = mode
        self.driver = driver
        self.item_id: int = -1
        self.item_path: Path | None = None
        self.rendered_path: Path | None = None
        self.thumb_size: tuple[int, int] = thumb_size
        self.show_filename_label: bool = show_filename_label
        self.label_height = 12
        self.label_spacing = 4
        self.setMinimumSize(*thumb_size)
        self.setMaximumSize(*thumb_size)
        self.setMouseTracking(True)
        check_size = 24
        self.setFixedSize(
            thumb_size[0],
            thumb_size[1]
            + ((self.label_height + self.label_spacing) if show_filename_label else 0),
        )

        self.thumb_container = QWidget()
        self.base_layout = QVBoxLayout(self)
        self.base_layout.setContentsMargins(0, 0, 0, 0)
        self.base_layout.setSpacing(0)
        self.setLayout(self.base_layout)

        # +----------+
        # |   ARC FAV| Top Right: Favorite & Archived Badges
        # |          |
        # |          |
        # |EXT      #| Lower Left: File Type, Tag Group Icon, or Collation Icon
        # +----------+ Lower Right: Collation Count, Video Length, or Word Count
        #
        #   Filename   Underneath: (Optional) Filename

        # Thumbnail ============================================================

        # +----------+
        # |*--------*|
        # ||        ||
        # ||        ||
        # |*--------*|
        # +----------+
        self.thumb_layout = QVBoxLayout(self.thumb_container)
        self.thumb_layout.setObjectName("baseLayout")
        self.thumb_layout.setContentsMargins(0, 0, 0, 0)

        # +----------+
        # |[~~~~~~~~]|
        # |          |
        # |          |
        # |          |
        # +----------+
        self.top_layout = QHBoxLayout()
        self.top_layout.setObjectName("topLayout")
        self.top_layout.setContentsMargins(6, 6, 6, 6)
        self.top_container = QWidget()
        self.top_container.setLayout(self.top_layout)
        self.thumb_layout.addWidget(self.top_container)

        # +----------+
        # |[~~~~~~~~]|
        # |     ^    |
        # |     |    |
        # |     v    |
        # +----------+
        self.thumb_layout.addStretch(2)

        # +----------+
        # |[~~~~~~~~]|
        # |     ^    |
        # |     v    |
        # |[~~~~~~~~]|
        # +----------+
        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.setObjectName("bottomLayout")
        self.bottom_layout.setContentsMargins(6, 6, 6, 6)
        self.bottom_container = QWidget()
        self.bottom_container.setLayout(self.bottom_layout)
        self.thumb_layout.addWidget(self.bottom_container)

        self.thumb_button = ThumbButton(self.thumb_container, thumb_size)
        self.thumb_button.setFlat(True)
        self.thumb_button.setLayout(self.thumb_layout)
        self.thumb_button.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

        self.opener = FileOpenerHelper(Path())
        open_file_action = QAction(Translations["file.open_file"], self)
        open_file_action.triggered.connect(self.opener.open_file)
        open_explorer_action = QAction(open_file_str(), self)
        open_explorer_action.triggered.connect(self.opener.open_explorer)

        self.delete_action = QAction(
            Translations.format("trash.context.ambiguous", trash_term=trash_term()),
            self,
        )

        def _on_delete():
            if self.item_id != -1 and self.item_path is not None:
                self.driver.delete_files_callback(self.item_path, self.item_id)

        self.delete_action.triggered.connect(lambda checked=False: _on_delete())

        self.thumb_button.addAction(open_file_action)
        self.thumb_button.addAction(open_explorer_action)
        self.thumb_button.addAction(self.delete_action)
        # Install an event filter so we can handle middle-clicks on the thumb button
        # without interfering with the existing left-click / context menu behavior.
        self.thumb_button.installEventFilter(self)

        # transient overlay reference to keep it alive while shown
        self._middle_click_overlay = None

        # Static Badges ========================================================

        # Item Type Badge ------------------------------------------------------
        # Used for showing the Tag Group / Collation icons.
        # Mutually exclusive with the File Extension Badge.
        self.item_type_badge = QLabel()
        self.item_type_badge.setObjectName("itemBadge")
        self.item_type_badge.setPixmap(
            QPixmap.fromImage(
                ImageQt.ImageQt(
                    ItemThumb.collation_icon_128.resize(
                        (check_size, check_size), Image.Resampling.BILINEAR
                    )
                )
            )
        )
        self.item_type_badge.setMinimumSize(check_size, check_size)
        self.item_type_badge.setMaximumSize(check_size, check_size)
        self.bottom_layout.addWidget(self.item_type_badge)

        # File Extension Badge -------------------------------------------------
        # Mutually exclusive with the File Extension Badge.
        self.ext_badge = QLabel()
        self.ext_badge.setObjectName("extBadge")
        self.ext_badge.setStyleSheet(ItemThumb.small_text_style)
        self.bottom_layout.addWidget(self.ext_badge)
        self.bottom_layout.addStretch(2)

        # Count Badge ----------------------------------------------------------
        # Used for Tag Group + Collation counts, video length, word count, etc.
        self.count_badge = QLabel()
        self.count_badge.setObjectName("countBadge")
        self.count_badge.setText("-:--")
        self.count_badge.setStyleSheet(ItemThumb.small_text_style)
        self.bottom_layout.addWidget(self.count_badge, alignment=Qt.AlignmentFlag.AlignBottom)
        self.top_layout.addStretch(2)

        # Intractable Badges ===================================================
        self.cb_container = QWidget()
        self.cb_layout = QHBoxLayout()
        self.cb_layout.setDirection(QBoxLayout.Direction.RightToLeft)
        self.cb_layout.setContentsMargins(0, 0, 0, 0)
        self.cb_layout.setSpacing(6)
        self.cb_container.setLayout(self.cb_layout)
        self.top_layout.addWidget(self.cb_container)

        self.badge_active: dict[BadgeType, bool] = {
            BadgeType.FAVORITE: False,
            BadgeType.ARCHIVED: False,
        }

        self.badges: dict[BadgeType, QCheckBox] = {}
        badge_icons = {
            BadgeType.FAVORITE: (
                ":/images/star_icon_empty_128.png",
                ":/images/star_icon_filled_128.png",
            ),
            BadgeType.ARCHIVED: (
                ":/images/box_icon_empty_128.png",
                ":/images/box_icon_filled_128.png",
            ),
        }
        for badge_type in BadgeType:
            icon_empty, icon_checked = badge_icons[badge_type]
            badge = QCheckBox()
            badge.setObjectName(badge_type.name)
            badge.setToolTip(badge_type.value)
            badge.setStyleSheet(
                f"QCheckBox::indicator{{width: {check_size}px;height: {check_size}px;}}"
                f"QCheckBox::indicator::unchecked{{image: url({icon_empty})}}"
                f"QCheckBox::indicator::checked{{image: url({icon_checked})}}"
            )
            badge.setMinimumSize(check_size, check_size)
            badge.setMaximumSize(check_size, check_size)
            badge.setHidden(True)

            badge.stateChanged.connect(lambda x, bt=badge_type: self.on_badge_check(bt))

            self.badges[badge_type] = badge
            self.cb_layout.addWidget(badge)

        # Filename Label =======================================================
        self.file_label = QLabel(Translations["generic.filename"])
        self.file_label.setStyleSheet(ItemThumb.filename_style)
        self.file_label.setMaximumHeight(self.label_height)
        if not show_filename_label:
            self.file_label.setHidden(True)

        self.base_layout.addWidget(self.thumb_container)
        self.base_layout.addWidget(self.file_label)
        # NOTE: self.item_id seems to act as a reference here and does not need to be updated inside
        # QtDriver.update_thumbs() while item_thumb.delete_action does.
        # If this behavior ever changes, move this method back to QtDriver.update_thumbs().
        self.thumb_button.clicked.connect(
            lambda: self.driver.toggle_item_selection(
                self.item_id,
                append=(QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier),
                bridge=(QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.ShiftModifier),
            )
        )
        self.set_mode(mode)

    @property
    def is_favorite(self) -> bool:
        return self.badge_active[BadgeType.FAVORITE]

    @property
    def is_archived(self) -> bool:
        return self.badge_active[BadgeType.ARCHIVED]

    def set_mode(self, mode: ItemType | None) -> None:
        if mode is None:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on=True)
            self.thumb_button.unsetCursor()
            self.thumb_button.setHidden(True)
        elif mode == ItemType.ENTRY:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on=False)
            self.thumb_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.thumb_button.setHidden(False)
            self.cb_container.setHidden(False)
            # Count Badge depends on file extension (video length, word count)
            self.item_type_badge.setHidden(True)
            self.count_badge.setStyleSheet(ItemThumb.small_text_style)
            self.count_badge.setHidden(True)
            self.ext_badge.setHidden(True)
        elif mode == ItemType.COLLATION:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on=False)
            self.thumb_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.thumb_button.setHidden(False)
            self.cb_container.setHidden(True)
            self.ext_badge.setHidden(True)
            self.count_badge.setStyleSheet(ItemThumb.med_text_style)
            self.count_badge.setHidden(False)
            self.item_type_badge.setHidden(False)
        elif mode == ItemType.TAG_GROUP:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on=False)
            self.thumb_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.thumb_button.setHidden(False)
            self.ext_badge.setHidden(True)
            self.count_badge.setHidden(False)
            self.item_type_badge.setHidden(False)
        self.mode = mode

    def set_extension(self, filename: Path) -> None:
        show_ext_badge = False
        show_count_badge = False

        ext = filename.suffix.lower()
        if ext and ext.startswith(".") is False:
            ext = "." + ext
        media_types: set[MediaType] = MediaCategories.get_types(ext)
        if (
            not MediaCategories.is_ext_in_category(ext, MediaCategories.IMAGE_TYPES)
            or MediaCategories.is_ext_in_category(ext, MediaCategories.IMAGE_RAW_TYPES)
            or MediaCategories.is_ext_in_category(ext, MediaCategories.IMAGE_VECTOR_TYPES)
            or MediaCategories.is_ext_in_category(ext, MediaCategories.ADOBE_PHOTOSHOP_TYPES)
            or ext
            in [
                ".apng",
                ".avif",
                ".exr",
                ".gif",
                ".jxl",
                ".webp",
            ]
        ):
            if ext or filename.stem:
                self.ext_badge.setText(ext.upper()[1:] or filename.stem.upper())
                show_ext_badge = True
            if MediaType.VIDEO in media_types or MediaType.AUDIO in media_types:
                show_count_badge = True

        self.ext_badge.setHidden(not show_ext_badge)
        self.count_badge.setHidden(not show_count_badge)

    def set_count(self, count: str) -> None:
        if count:
            self.count_badge.setHidden(False)
            self.count_badge.setText(count)
        else:
            if self.mode == ItemType.ENTRY:
                self.ext_badge.setHidden(True)
                self.count_badge.setHidden(True)

    def set_filename_text(self, filename: Path):
        self.file_label.setText(str(filename.name))

    def set_filename_visibility(self, set_visible: bool):
        """Toggle the visibility of the filename label.

        Args:
            set_visible (bool): Show the filename, true or false.
        """
        if set_visible:
            if self.file_label.isHidden():
                self.file_label.setHidden(False)
            self.setFixedHeight(self.thumb_size[1] + self.label_height + self.label_spacing)
        else:
            self.file_label.setHidden(True)
            self.setFixedHeight(self.thumb_size[1])
        self.show_filename_label = set_visible

    def update_thumb(self, image: QPixmap | None = None, file_path: Path | None = None):
        """Update attributes of a thumbnail element."""
        self.thumb_button.setIcon(image if image else QPixmap())
        self.rendered_path = file_path

    def update_size(self, size: QSize):
        """Updates attributes of a thumbnail element.

        Args:
            size (QSize): The new thumbnail size to set.
        """
        self.thumb_size = size.width(), size.height()
        self.thumb_button.setIconSize(size)
        self.thumb_button.setMinimumSize(size)
        self.thumb_button.setMaximumSize(size)

    def set_item(self, entry: "Entry"):
        self.set_item_id(entry.id)
        path = unwrap(self.lib.library_dir) / entry.path
        self.set_item_path(path)

    def set_item_id(self, item_id: int):
        self.item_id = item_id

    def set_item_path(self, path: Path):
        """Set the absolute filepath for the item. Used for locating on disk."""
        self.item_path = path
        self.opener.set_filepath(path)

    def assign_badge(self, badge_type: BadgeType, value: bool) -> None:
        mode = self.mode
        # blank mode to avoid recursive badge updates
        badge = self.badges[badge_type]
        self.badge_active[badge_type] = value
        if badge.isChecked() != value:
            self.mode = None
            badge.setChecked(value)
            badge.setHidden(not value)
            self.mode = mode

    def show_check_badges(self, show: bool):
        if self.mode != ItemType.TAG_GROUP:
            for badge_type, badge in self.badges.items():
                is_hidden = not (show or self.badge_active[badge_type])
                badge.setHidden(is_hidden)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:  # type: ignore[misc]
        self.show_check_badges(show=True)
        return super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:  # type: ignore[misc]
        self.show_check_badges(show=False)
        return super().leaveEvent(event)

    @badge_update_lock
    def on_badge_check(self, badge_type: BadgeType):
        if self.mode is None:
            return

        toggle_value = self.badges[badge_type].isChecked()
        self.badge_active[badge_type] = toggle_value
        badge_values: dict[BadgeType, bool] = {badge_type: toggle_value}
        # TODO: Ensure that self.item_id is always an integer. During tests, it is currently None.
        # This issue should be addressed by either fixing the test setup or modifying the
        # self.driver.update_badges() method.
        self.driver.update_badges(badge_values, self.item_id)

    def toggle_item_tag(
        self,
        entry_id: int,
        toggle_value: bool,
        tag_id: int,
    ):
        if entry_id in self.driver.selected:
            if len(self.driver.selected) == 1:
                self.driver.main_window.preview_panel.field_containers_widget.update_toggled_tag(
                    tag_id, toggle_value
                )
            else:
                pass

    @override
    def eventFilter(self, obj, event):
        """Catch middle mouse button presses on the internal `thumb_button`.

        Returns True if the event was handled (prevents further processing), otherwise
        falls back to the default behavior.
        """
        from PySide6.QtCore import QEvent

        # Only handle events for our thumb button and only mouse press events
        if obj is self.thumb_button and event.type() == QEvent.Type.MouseButtonPress:
            try:
                if event.button() == Qt.MouseButton.MiddleButton:
                    # Call the user-visible handler for middle clicks
                    handled = self.on_middle_click(event)
                    return bool(handled)
            except Exception:
                # If anything goes wrong, don't swallow the event — let Qt handle it
                return False

        return super().eventFilter(obj, event)

    def on_middle_click(self, event):
        """Show a small, native QMenu populated with most-recent tags and a search action.

        Selecting a recent tag will add that tag to the clicked entry and record
        the usage in the driver's MRU.
        """
        try:
            logger.info("[ItemThumb] Middle-click menu", item_id=self.item_id)

            # Check enabled setting (QSettings or driver.cached_values)
            enabled = True
            try:
                s = QSettings()
                enabled = bool(s.value("middle_click_enabled", True, type=bool))
            except Exception:
                enabled = True
            try:
                if hasattr(self.driver, "cached_values"):
                    c = self.driver.cached_values.value("middle_click_enabled", None)
                    if c is not None:
                        enabled = bool(c)
            except Exception:
                pass

            if not enabled:
                # Not handled by plugin, allow default Qt behavior
                return False

            # Also select the item on middle-click, same behaviour as left-click
            try:
                self.driver.toggle_item_selection(
                    self.item_id,
                    append=(QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier),
                    bridge=(QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.ShiftModifier),
                )
            except Exception:
                logger.exception("[ItemThumb] middle-click selection failed")

            # Determine whether to apply to all selected items based on settings + modifiers
            try:
                s = QSettings()
                cfg_apply = bool(s.value("middle_click_apply_to_selected", True, type=bool))
                cfg_ctrl = bool(s.value("middle_click_mod_ctrl", True, type=bool))
                cfg_shift = bool(s.value("middle_click_mod_shift", True, type=bool))
            except Exception:
                cfg_apply = True
                cfg_ctrl = True
                cfg_shift = True

            mods = QGuiApplication.keyboardModifiers()
            have_ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            have_shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            apply_to_selected = False
            if cfg_apply:
                if cfg_ctrl and have_ctrl:
                    apply_to_selected = True
                if cfg_shift and have_shift:
                    apply_to_selected = True

            # Limit is configurable via QSettings key `middle_click_limit` or driver.cached_values
            recent_tag_ids = []
            limit = 6
            try:
                s = QSettings()
                val = s.value("middle_click_limit", None)
                if val is not None:
                    limit = int(val)
            except Exception:
                pass
            try:
                if hasattr(self.driver, "cached_values"):
                    cval = self.driver.cached_values.value("middle_click_limit", None)
                    if cval is not None:
                        limit = int(cval)
            except Exception:
                pass
            if hasattr(self.driver, "get_recent_tags"):
                # request up to `limit` recent tags
                recent_tag_ids = self.driver.get_recent_tags(limit)

            logger.info("[ItemThumb] recent_tag_ids", recent_tag_ids=recent_tag_ids)

            tag_objs: list = []
            # Build initial set from recent_tag_ids
            existing_tag_ids: set[int] = set()
            if not apply_to_selected:
                try:
                    entry_full = None
                    if self.item_id and hasattr(self.lib, "get_entry_full"):
                        entry_full = self.lib.get_entry_full(self.item_id, with_fields=False, with_tags=True)
                    if entry_full and getattr(entry_full, "tags", None):
                        existing_tag_ids = {t.id for t in entry_full.tags}
                except Exception:
                    existing_tag_ids = set()

            seen: set[int] = set()
            # add recent tags first (keep order)
            for tid in recent_tag_ids:
                if tid in seen:
                    continue
                t = self.lib.get_tag(tid)
                if not t:
                    continue
                # If we're applying to all selected entries, don't hide tags already present
                if not apply_to_selected and t.id in existing_tag_ids:
                    continue
                tag_objs.append((tid, t))
                seen.add(tid)

            # If we still need more, fetch additional tags from library search and append
            try:
                if len(tag_objs) < limit:
                    # request a larger result set and fill until we reach `limit`
                    search_res = self.lib.search_tags(None, limit=limit * 2)
                    direct = []
                    if isinstance(search_res, list) and len(search_res) > 0:
                        direct = list(search_res[0])
                    for t in direct:
                        if len(tag_objs) >= limit:
                            break
                        if not t:
                            continue
                        if t.id in seen:
                            continue
                        if not apply_to_selected and t.id in existing_tag_ids:
                            continue
                        tag_objs.append((t.id, t))
                        seen.add(t.id)
            except Exception:
                logger.exception("[ItemThumb] failed to fetch fallback tags via search_tags")

            # Build overlay options from tag_objs (recent or fallback) and always try overlay
            try:
                overlay_opts = []
                # provide up to `limit` recent/fallback tags
                # Snapshot targets now so callbacks apply to the intended set
                if apply_to_selected:
                    targets_snapshot = list(self.driver.selected)
                else:
                    targets_snapshot = [self.item_id]

                for tid, tag in tag_objs[:limit]:
                    if apply_to_selected:
                        targets = list(targets_snapshot)
                        cb = (lambda t=tid, targets=targets: self._add_tag_and_record_multi(t, targets))
                    else:
                        cb = (lambda t=tid: self._add_tag_and_record(t))
                    # pass the Tag object as metadata so overlay can style it
                    overlay_opts.append((tag.name, cb, tag))

                # Only include tag options (no search action). Limit already enforced above.

                overlay = MiddleClickOverlay(parent=self.driver.main_window, options=overlay_opts)
                # apply animation settings from QSettings / driver.cached_values so preview/out works
                try:
                    s = QSettings()
                    in_enabled = bool(s.value("middle_click_anim_in_enabled", True, type=bool))
                    in_dur = float(s.value("middle_click_anim_in_duration", 0.35, type=float))
                    out_enabled = bool(s.value("middle_click_anim_out_enabled", True, type=bool))
                    out_dur = float(s.value("middle_click_anim_out_duration", 0.12, type=float))
                except Exception:
                    in_enabled, in_dur, out_enabled, out_dur = True, 0.35, True, 0.12
                try:
                    if hasattr(self.driver, "cached_values"):
                        cv = self.driver.cached_values
                        c_in_enabled = cv.value("middle_click_anim_in_enabled", None)
                        if c_in_enabled is not None:
                            in_enabled = bool(c_in_enabled)
                        c_in_dur = cv.value("middle_click_anim_in_duration", None)
                        if c_in_dur is not None:
                            in_dur = float(c_in_dur)
                        c_out_enabled = cv.value("middle_click_anim_out_enabled", None)
                        if c_out_enabled is not None:
                            out_enabled = bool(c_out_enabled)
                        c_out_dur = cv.value("middle_click_anim_out_duration", None)
                        if c_out_dur is not None:
                            out_dur = float(c_out_dur)
                except Exception:
                    pass
                try:
                    overlay.anim_in_duration = in_dur
                    overlay.anim_out_duration = out_dur
                    overlay.anim_enabled = bool(in_enabled)
                    overlay.anim_out_enabled = bool(out_enabled)
                except Exception:
                    pass
                # keep reference so it doesn't get GC'd
                self._middle_click_overlay = overlay
                global_pos = self.thumb_button.mapToGlobal(self.thumb_button.rect().center())
                logger.info("[ItemThumb] showing overlay", at=(global_pos.x(), global_pos.y()), options=len(overlay_opts))
                overlay.show_at(global_pos)
                return True
            except Exception:
                logger.exception("Middle-click overlay failed, falling back to native menu")

            # Fallback: native QMenu
            try:
                from PySide6.QtWidgets import QMenu

                menu = QMenu(self.thumb_button)

                # Populate recent tags
                for tag_id in recent_tag_ids:
                    tag = self.lib.get_tag(tag_id)
                    if not tag:
                        continue
                    act = menu.addAction(tag.name)
                    act.triggered.connect(lambda checked=False, t=tag_id: self._add_tag_and_record(t))

                # no extra actions; only recent/fallback tags are shown

                # Style menu using app palette / theme colors
                try:
                    dark = QGuiApplication.styleHints().colorScheme() is Qt.ColorScheme.Dark
                    ui_color = UiColor.THEME_DARK if dark else UiColor.THEME_LIGHT
                    bg = get_ui_color(ColorType.PRIMARY, ui_color)
                    fg = get_ui_color(ColorType.LIGHT_ACCENT, ui_color)
                    sel = get_ui_color(ColorType.DARK_ACCENT, ui_color)
                    menu.setStyleSheet(
                        f"QMenu {{ background-color: {bg}; color: {fg}; }}"
                        f" QMenu::item:selected {{ background-color: {sel}; }}"
                    )
                except Exception:
                    pass

                global_pos = self.thumb_button.mapToGlobal(self.thumb_button.rect().center())
                menu.exec(global_pos)
                return True
            except Exception:
                logger.exception("on_middle_click fallback QMenu failed")
        except Exception:
            logger.exception("on_middle_click failed")
            return False

        return False

    def _add_tag_and_record(self, tag_id: int) -> None:
        """Helper to add a tag to this entry and record it in MRU."""
        try:
            if self.item_id is None or self.item_id == -1:
                return

            # Update UI first so the user sees immediate feedback
            try:
                self.driver.main_window.thumb_layout.add_tags([self.item_id], [tag_id])
            except Exception:
                logger.debug("thumb_layout.add_tags failed; continuing to add in DB")

            # Persist tag addition
            try:
                self.lib.add_tags_to_entries(self.item_id, tag_id)
            except Exception:
                logger.exception("Failed to add tag to entry in library")

            # Record usage in MRU
            if hasattr(self.driver, "record_tag_usage"):
                try:
                    self.driver.record_tag_usage(tag_id)
                except Exception:
                    logger.exception("record_tag_usage failed")

            # Update preview/selection state if needed
            try:
                if self.item_id in self.driver.selected:
                    self.driver.main_window.preview_panel.set_selection(self.driver.selected)
            except Exception:
                pass
            # Emit badge signals and update badge UI when relevant
            try:
                if hasattr(self.driver, "emit_badge_signals"):
                    try:
                        self.driver.emit_badge_signals({tag_id}, emit_on_absent=False)
                    except Exception:
                        logger.exception("emit_badge_signals failed")

                # If this tag is a known badge (favorite/archived), update ItemThumb badges
                if tag_id in (TAG_FAVORITE, TAG_ARCHIVED):
                    try:
                        badge_map = {}
                        if tag_id == TAG_FAVORITE:
                            badge_map[BadgeType.FAVORITE] = True
                        elif tag_id == TAG_ARCHIVED:
                            badge_map[BadgeType.ARCHIVED] = True
                        # update_badges will assign visuals; set add_tags=False to avoid re-adding in DB
                        if hasattr(self.driver, "update_badges"):
                            self.driver.update_badges(badge_map, origin_id=self.item_id, add_tags=False)
                    except Exception:
                        logger.exception("update_badges for badge tag failed")
            except Exception:
                logger.exception("post-tag-add notifications failed")
        except Exception:
            logger.exception("_add_tag_and_record failed")

    def _add_tag_and_record_multi(self, tag_id: int, targets: list[int]) -> None:
        """Add a tag to multiple entries and record it in MRU."""
        try:
            if not targets:
                return

            # Update UI first so the user sees immediate feedback
            try:
                for entry_id in targets:
                    try:
                        self.driver.main_window.thumb_layout.add_tags([entry_id], [tag_id])
                    except Exception:
                        pass
            except Exception:
                logger.debug("thumb_layout.add_tags (multi) failed; continuing to add in DB")

            # Persist tag addition for each target
            try:
                for entry_id in targets:
                    try:
                        self.lib.add_tags_to_entries(entry_id, tag_id)
                    except Exception:
                        logger.exception("Failed to add tag to entry in library (multi)")
            except Exception:
                logger.exception("Failed bulk add_tags_to_entries")

            # Record usage in MRU (once per tag)
            if hasattr(self.driver, "record_tag_usage"):
                try:
                    self.driver.record_tag_usage(tag_id)
                except Exception:
                    logger.exception("record_tag_usage failed")

            # Update preview/selection state if needed
            try:
                if any(entry_id in self.driver.selected for entry_id in targets):
                    self.driver.main_window.preview_panel.set_selection(self.driver.selected)
            except Exception:
                pass

            # Emit badge signals and update badge UI when relevant
            try:
                if hasattr(self.driver, "emit_badge_signals"):
                    try:
                        self.driver.emit_badge_signals({tag_id}, emit_on_absent=False)
                    except Exception:
                        logger.exception("emit_badge_signals failed")

                # If this tag is a known badge (favorite/archived), update ItemThumb badges
                if tag_id in (TAG_FAVORITE, TAG_ARCHIVED):
                    try:
                        badge_map = {}
                        if tag_id == TAG_FAVORITE:
                            badge_map[BadgeType.FAVORITE] = True
                        elif tag_id == TAG_ARCHIVED:
                            badge_map[BadgeType.ARCHIVED] = True
                        if hasattr(self.driver, "update_badges"):
                            # origin_id is None since this is multi-target
                            self.driver.update_badges(badge_map, origin_id=None, add_tags=False)
                    except Exception:
                        logger.exception("update_badges for badge tag failed (multi)")
            except Exception:
                logger.exception("post-tag-add notifications failed (multi)")
        except Exception:
            logger.exception("_add_tag_and_record_multi failed")

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[misc]
        if event.buttons() is not Qt.MouseButton.LeftButton:
            return

        drag = QDrag(self.driver)
        paths: list[QUrl] = []
        mimedata = QMimeData()

        selected_ids = self.driver.selected

        for entry_id in selected_ids:
            entry = self.lib.get_entry(entry_id)
            if not entry:
                continue

            url = QUrl.fromLocalFile(Path(unwrap(self.lib.library_dir)) / entry.path)
            paths.append(url)

        mimedata.setUrls(paths)
        drag.setMimeData(mimedata)
        drag.exec(Qt.DropAction.CopyAction)
        logger.info("[ItemThumb] Dragging Files:", entry_ids=selected_ids)
