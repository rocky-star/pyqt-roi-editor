"""The main window and the entry point of the ROI editor.

The editing area and both docks are built in `MainWindow` rather than
in the `.ui` file, so the generated form stays as the skeleton it
started as.
"""

__all__ = ['APPLICATION_NAME', 'EditMode', 'MainWindow', 'main']

import enum
import math
import sys
from pathlib import Path
from typing import cast, override

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QItemSelectionModel,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QStandardPaths,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QCursor,
    QIcon,
    QImage,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QListView,
    QMainWindow,
    QMessageBox,
    QTreeView,
)

from pyqt_roi_editor.coords_input import CoordsInput
from pyqt_roi_editor.document import Basemap, Document, Shape, ShapeKind
from pyqt_roi_editor.dump_shape_dialog import DumpShapeDialog
from pyqt_roi_editor.helpers import format_number, qformat
from pyqt_roi_editor.roi_graphics_view import ROIGraphicsView
from pyqt_roi_editor.shape_props_editor import ShapePropsEditor
from pyqt_roi_editor.storage import StorageError, load_document, save_document
from pyqt_roi_editor.ui_mainwindow import Ui_MainWindow

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]

APPLICATION_NAME = 'ROI Editor'

_ROI_PATTERNS = '*.rsroi'
_IMAGE_PATTERNS = '*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp'
_HANDLE_RADIUS = 4.0
_SELECTION_TOLERANCE = 6.0
_THUMBNAIL_SIZE = 48
_HINT_TIMEOUT = 5000
# The keys that start a typed coordinate, and so open the palette.
_COORDINATE_KEYS = '0123456789-'


class EditMode(enum.Enum):
    """What a click in the editing area currently does."""

    NONE = 'none'
    CREATE_SHAPE = 'create_shape'
    ADD_VERTEX = 'add_vertex'


def _nearest_vertex(shape: Shape, point: QPointF) -> int | None:
    """Return the vertex of `shape` closest to `point`, if near enough."""
    best: int | None = None
    best_distance = _SELECTION_TOLERANCE
    for index, vertex in enumerate(shape.vertices):
        distance = math.hypot(vertex.x() - point.x(), vertex.y() - point.y())
        if distance <= best_distance:
            best = index
            best_distance = distance
    return best


def _thumbnail(image: QImage) -> QPixmap:
    """Return a small pixmap of `image` for the basemap list."""
    if image.width() > _THUMBNAIL_SIZE or image.height() > _THUMBNAIL_SIZE:
        image = image.scaled(
            _THUMBNAIL_SIZE, _THUMBNAIL_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    return QPixmap.from_image(image)


class MainWindow(QMainWindow):
    """The editor: one document, one view scene and two docks."""

    def __init__(self) -> None:
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)  # pyright: ignore[reportUnknownMemberType]
        self._document = Document()
        self._draft: Shape | None = None
        self._mode = EditMode.NONE
        self._selected_shape: Shape | None = None
        self._selected_vertex: int | None = None
        self._basemap_index: int | None = None
        self._basemap_item: QGraphicsPixmapItem | None = None
        self._document_directory: Path | None = None
        self._image_directory: Path | None = None
        self._syncing = False
        self._watching = False
        self._build_editor_area()
        self._connect_signals()
        self._fill_action_placeholders()
        self._refresh_all()

    @property
    def document(self) -> Document:
        """Return the document being edited."""
        return self._document

    # Building

    def _build_editor_area(self) -> None:
        """Install the editing area and both docks."""
        placeholder = self.take_central_widget()
        if placeholder is not None:
            placeholder.delete_later()
        self.roi_view = ROIGraphicsView(self)
        self.roi_view.object_name = 'roi_view'
        self.roi_view.set_render_hint(QPainter.RenderHint.Antialiasing)
        self.roi_view.background_brush = QBrush(QColor(64, 64, 64))
        self.set_central_widget(self.roi_view)
        self._scene = QGraphicsScene(self)
        self.roi_view.set_scene(self._scene)

        self._basemaps_model = QStandardItemModel(0, 1, self)
        self.basemaps_view = QListView(self)
        self.basemaps_view.object_name = 'basemaps_view'
        self.basemaps_view.set_model(self._basemaps_model)
        self.basemaps_view.edit_triggers = (
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dock_basemaps = QDockWidget(self.__tr("Basemaps"), self)
        self.dock_basemaps.object_name = 'dock_basemaps'
        self.dock_basemaps.set_widget(self.basemaps_view)
        self.add_dock_widget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_basemaps)

        self._shapes_model = QStandardItemModel(0, 3, self)
        self.shapes_view = QTreeView(self)
        self.shapes_view.object_name = 'shapes_view'
        self.shapes_view.set_model(self._shapes_model)
        self.shapes_view.edit_triggers = (
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.shapes_view.header().set_section_resize_mode(
            QHeaderView.ResizeMode.Stretch)
        self.dock_shapes = QDockWidget(self.__tr("Shapes"), self)
        self.dock_shapes.object_name = 'dock_shapes'
        self.dock_shapes.set_widget(self.shapes_view)
        # Both docks share the left side, one above the other.
        self.split_dock_widget(
            self.dock_basemaps, self.dock_shapes, Qt.Orientation.Vertical)

        # The palette is an overlay inside the editing area, so it is
        # drawn by this window and no compositor has a say in where it
        # ends up.
        self.coords_input = CoordsInput(self.roi_view.viewport())
        # The keys that drive drawing are caught for the whole
        # application: after a menu action the focus sits on the menu
        # bar, so the view never sees them.
        application = QApplication.instance()
        if application is not None:
            application.install_event_filter(self)

    def _connect_signals(self) -> None:
        """Connect the views, the palette and every menu action."""
        self.roi_view.clicked.connect(self._on_view_clicked)
        self.roi_view.finish_requested.connect(self._finish_shape)
        self.coords_input.accepted.connect(self._on_coords_accepted)
        self.coords_input.rejected.connect(self._cancel_mode)
        self.basemaps_view.selection_model().selectionChanged.connect(
            self._on_basemap_selection_changed)
        self.shapes_view.selection_model().selectionChanged.connect(
            self._on_shape_selection_changed)

        self.ui.action_new.triggered.connect(self._new_document)
        self.ui.action_open.triggered.connect(self._open_document)
        self.ui.action_save.triggered.connect(self._save_document)
        self.ui.action_save_as.triggered.connect(self._save_document_as)
        self.ui.action_exit.triggered.connect(self.close)
        self.ui.action_add_basemap.triggered.connect(self._add_basemap)
        self.ui.action_remove_basemap.triggered.connect(self._remove_basemap)
        self.ui.action_rename_basemap.triggered.connect(self._rename_basemap)
        self.ui.action_add_line.triggered.connect(self._add_line)
        self.ui.action_add_polygon.triggered.connect(self._add_polygon)
        self.ui.action_remove_shape.triggered.connect(self._remove_shape)
        self.ui.action_shape_props.triggered.connect(self._show_shape_props)
        self.ui.action_dump_shape.triggered.connect(self._dump_shape)
        self.ui.action_add_vertex.triggered.connect(self._start_add_vertex)
        self.ui.action_remove_vertex.triggered.connect(self._remove_vertex)
        self.ui.action_about.triggered.connect(self._show_about)
        self.ui.action_about_qt.triggered.connect(self._show_about_qt)

    def _fill_action_placeholders(self) -> None:
        """Put the application name into every ``%1`` action text."""
        app_name = QCoreApplication.application_name
        for action in self.find_children(QAction):
            text = action.text
            if '%1' in text:
                action.text = qformat(text, [app_name])

    # Refreshing

    def _refresh_all(self) -> None:
        """Rebuild both models and the scene from the document."""
        if self._syncing:
            return
        self._prune_selection()
        self._syncing = True
        try:
            self._rebuild_basemaps_model()
            self._rebuild_shapes_model()
            self.shapes_view.expand_all()
            self._apply_basemap_selection()
            self._apply_tree_selection()
            self._refresh_scene()
            self._update_title()
            self._update_action_states()
        finally:
            self._syncing = False

    def _prune_selection(self) -> None:
        """Forget a shape that is no longer in the document."""
        if (self._selected_shape is not None
                and self._selected_shape not in self._document.shapes):
            self._selected_shape = None
            self._selected_vertex = None

    def _rebuild_basemaps_model(self) -> None:
        """List the basemaps, with a thumbnail each."""
        self._basemaps_model.clear()
        for index, basemap in enumerate(self._document.basemaps):
            item = QStandardItem(basemap.name)
            item.set_icon(QIcon(_thumbnail(basemap.image)))
            item.set_data(index, Qt.ItemDataRole.UserRole)
            item.set_editable(False)
            self._basemaps_model.append_row(item)

    def _rebuild_shapes_model(self) -> None:
        """List the shapes, and the vertices of each under it."""
        self._shapes_model.clear()
        self._shapes_model.set_horizontal_header_labels(
            [self.__tr("Name"), self.__tr("X"), self.__tr("Y")])
        for shape in self._document.shapes:
            top = QStandardItem(shape.name)
            top.set_data(shape, Qt.ItemDataRole.UserRole)
            top.set_editable(False)
            for vertex in shape.vertices:
                items = [
                    QStandardItem(''),
                    QStandardItem(format_number(vertex.x())),
                    QStandardItem(format_number(vertex.y())),
                ]
                for item in items:
                    item.set_editable(False)
                top.append_row(items)
            self._shapes_model.append_row(top)

    def _apply_basemap_selection(self) -> None:
        """Select the active basemap in the list."""
        index = self._document.active_basemap
        if not 0 <= index < len(self._document.basemaps):
            self._basemap_index = None
            return
        self._basemap_index = index
        self.basemaps_view.selection_model().select(
            self._basemaps_model.item(index).index(),
            QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def _apply_tree_selection(self) -> None:
        """Select the current shape, and its vertex, in the tree."""
        selection_model = self.shapes_view.selection_model()
        selection_model.clear()
        shape = self._selected_shape
        if shape is None:
            return
        for row in range(self._shapes_model.row_count()):
            item = self._shapes_model.item(row)
            if item.data(Qt.ItemDataRole.UserRole) is not shape:
                continue
            index = item.index()
            if (self._selected_vertex is not None
                    and 0 <= self._selected_vertex < len(shape.vertices)):
                self.shapes_view.expand(index)
                index = self._shapes_model.index(
                    self._selected_vertex, 0, index)
            selection_model.select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows)
            self.shapes_view.set_current_index(index)
            self.shapes_view.scroll_to(index)
            return

    def _refresh_scene(self) -> None:
        """Draw the basemap, the shapes and the vertex handles."""
        self._scene.clear()
        self._basemap_item = None
        basemap = self._document.current_basemap
        if basemap is None:
            # `scene_rect` is a property once true_property is active,
            # even though the stub still describes the setter method.
            self._scene.scene_rect = QRectF()  # type: ignore
        else:
            self._basemap_item = self._scene.add_pixmap(
                QPixmap.from_image(basemap.image))
            self._basemap_item.z_value = -1.0  # type: ignore
            self._scene.scene_rect = basemap.rect  # type: ignore
        for shape in self._document.shapes:
            self._add_shape_item(shape, shape is self._selected_shape)
        if self._draft is not None:
            self._add_shape_item(self._draft, True)
        if self._selected_shape is not None:
            self._add_handles(self._selected_shape)

    def _add_shape_item(self, shape: Shape, selected: bool) -> None:
        """Draw `shape`, highlighted when it is the selected one."""
        path = QPainterPath()
        if shape.vertices:
            path.move_to(shape.vertices[0])
            for vertex in shape.vertices[1:]:
                path.line_to(vertex)
            if shape.closed:
                path.close_subpath()
        item = self._scene.add_path(path)
        item.set_pen(QPen(
            QColor(255, 200, 0) if selected else QColor(0, 200, 255),
            3.0 if selected else 2.0))
        item.set_data(0, shape)

    def _add_handles(self, shape: Shape) -> None:
        """Draw a handle on every vertex of the selected shape."""
        for index, vertex in enumerate(shape.vertices):
            selected = index == self._selected_vertex
            handle = QGraphicsEllipseItem(
                vertex.x() - _HANDLE_RADIUS,
                vertex.y() - _HANDLE_RADIUS,
                _HANDLE_RADIUS * 2.0, _HANDLE_RADIUS * 2.0)
            handle.set_pen(QPen(QColor(0, 0, 0), 1.0))
            handle.set_brush(QBrush(
                QColor(255, 64, 64) if selected else QColor(255, 255, 255)))
            handle.set_accepted_mouse_buttons(Qt.MouseButton.NoButton)
            handle.set_data(0, index)
            self._scene.add_item(handle)

    def _update_title(self) -> None:
        """Show the file name and the application name."""
        basename = self._document.basename or self.__tr("Untitled")
        self.window_title = qformat(
            self.__tr("%1 - %2"),
            [basename, QCoreApplication.application_name])

    def _update_action_states(self) -> None:
        """Enable each action whose target currently exists."""
        shape = self._selected_shape
        has_basemap = self._basemap_index is not None
        has_shape = shape is not None
        has_vertex = has_shape and self._selected_vertex is not None
        can_add_vertex = shape is not None and shape.accepts_vertices
        idle = self._mode is EditMode.NONE
        self.ui.action_remove_basemap.enabled = has_basemap
        self.ui.action_rename_basemap.enabled = has_basemap
        self.ui.action_remove_shape.enabled = has_shape and idle
        self.ui.action_shape_props.enabled = has_shape and idle
        self.ui.action_dump_shape.enabled = has_shape
        self.ui.action_add_vertex.enabled = can_add_vertex and idle
        self.ui.action_remove_vertex.enabled = has_vertex and idle
        self.ui.action_add_line.enabled = idle
        self.ui.action_add_polygon.enabled = idle

    # Selection

    def _select(self, shape: Shape | None, vertex: int | None) -> None:
        """Make `shape` and `vertex` the current selection."""
        if self._syncing:
            return
        self._selected_shape = shape
        self._selected_vertex = vertex if shape is not None else None
        self._syncing = True
        try:
            self._apply_tree_selection()
            self._refresh_scene()
            self._update_action_states()
        finally:
            self._syncing = False

    def _select_at(self, point: QPointF) -> None:
        """Select the handle, shape or nothing under `point`."""
        shape = self._selected_shape
        if shape is not None:
            index = _nearest_vertex(shape, point)
            if index is not None:
                self._select(shape, index)
                return
        item = self._shape_item_at(point)
        if item is None:
            self._select(None, None)
            return
        shape = cast('object', item.data(0))
        if isinstance(shape, Shape):
            self._select(shape, None)

    def _shape_item_at(self, point: QPointF) -> QGraphicsPathItem | None:
        """Return the shape item drawn under `point`, if any."""
        for item in self._scene.items(point):
            if isinstance(item, QGraphicsPathItem):
                return item
        return None

    def _on_basemap_selection_changed(self) -> None:
        """Switch the shown basemap to the selected one."""
        if self._syncing:
            return
        indexes = self.basemaps_view.selection_model().selected_indexes
        if indexes:
            self._basemap_index = indexes[0].row()
            self._document.active_basemap = self._basemap_index
        else:
            self._basemap_index = None
            self._document.active_basemap = -1
        self._update_action_states()
        self._refresh_scene()

    def _on_shape_selection_changed(self) -> None:
        """Follow the tree selection with the scene selection."""
        if self._syncing:
            return
        indexes = self.shapes_view.selection_model().selected_indexes
        if not indexes:
            self._selected_shape = None
            self._selected_vertex = None
        else:
            index = indexes[0]
            parent = index.parent()
            row = parent.row() if parent.is_valid() else index.row()
            item = self._shapes_model.item(row)
            self._selected_shape = (
                item.data(Qt.ItemDataRole.UserRole) if item else None)
            self._selected_vertex = index.row() if parent.is_valid() else None
        self._update_action_states()
        self._refresh_scene()

    # Drawing a shape

    def _add_line(self) -> None:
        """Start drawing a line."""
        self._start_shape(ShapeKind.LINE)

    def _add_polygon(self) -> None:
        """Start drawing a polygon."""
        self._start_shape(ShapeKind.POLYGON)

    def _start_shape(self, kind: ShapeKind) -> None:
        """Start a shape of `kind`; the palette waits for a digit."""
        self._cancel_mode()
        self._draft = Shape(name=self._unique_shape_name(), kind=kind)
        if kind is ShapeKind.LINE:
            # A segment is finished by its second vertex, so there is
            # no point in telling the user about Enter.
            hint = self.__tr("Click or type both endpoints; Esc cancels.")
        else:
            hint = self.__tr(
                "Click or type digits; Enter finishes, Esc cancels.")
        self._enter_mode(EditMode.CREATE_SHAPE, hint)

    def _start_add_vertex(self) -> None:
        """Start inserting vertices into the selected shape."""
        if self._selected_shape is None:
            return
        self._cancel_mode()
        self._enter_mode(
            EditMode.ADD_VERTEX,
            self.__tr("Click or type a coordinate; Esc stops."))

    def _enter_mode(self, mode: EditMode, hint: str) -> None:
        """Switch to `mode` and show `hint`."""
        self._mode = mode
        self._watching = True
        self.coords_input.reset()
        self.roi_view.cursor = Qt.CursorShape.CrossCursor
        self.roi_view.set_focus()
        self.ui.statusbar.show_message(hint)
        self._update_action_states()

    @override
    def event_filter(self, watched: QObject, event: QEvent) -> bool:
        """Take the keys that drive drawing wherever the focus is.

        A menu keeps the focus for itself after an action has been
        picked, so pressing a number key would otherwise reach the
        menu bar instead of the view.

        The filter is installed on the whole application, so it is
        also called for a window Qt has already torn down and wrapped
        again: such a wrapper never ran `__init__`, which is why the
        flag is read straight out of the instance dictionary.
        """
        if not self.__dict__.get('_watching', False):
            return super().event_filter(watched, event)
        if not self._is_mode_key(event):
            return super().event_filter(watched, event)
        return self._handle_mode_key(event)

    def _is_mode_key(self, event: QEvent) -> bool:
        """Return whether `event` is a key the drawing modes act on."""
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not isinstance(event, QKeyEvent):
            return False
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return,
                           Qt.Key.Key_Enter):
            return True
        return event.text() in _COORDINATE_KEYS

    def _handle_mode_key(self, event: QEvent) -> bool:
        """Act on a key of a drawing mode, and only then.

        Return accepts the typed coordinate, or finishes the shape
        when nothing has been typed, so a shape drawn purely by typing
        can be closed without touching the mouse.  A key the mode has
        no use for is left alone, so it still reaches whatever has the
        focus.
        """
        if not isinstance(event, QKeyEvent):
            return False
        active = QApplication.active_window()
        if (active is not None and active is not self
                and active is not self.coords_input):
            return False
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel_mode()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.coords_input.text.strip():
                self.coords_input.accept()
                return True
            if self._mode is EditMode.CREATE_SHAPE:
                self._finish_shape()
                return True
            return False
        return self._type_coordinate(event.text())

    def _type_coordinate(self, character: str) -> bool:
        """Add `character` to the palette, opening it when needed.

        Typing only makes sense while a shape is drawn or a vertex is
        inserted; anywhere else the key is none of the mode's business
        and is reported as unhandled.
        """
        if self._mode not in (EditMode.CREATE_SHAPE, EditMode.ADD_VERTEX):
            return False
        if self.coords_input.visible:
            self.coords_input.insert_text(character)
        else:
            self.coords_input.popup_at(self._palette_position(), character)
        return True

    def _palette_position(self) -> QPoint:
        """Return where the palette goes, near the pointer.

        The position is relative to the viewport the palette lives in,
        and is pulled back inside that viewport when the pointer is
        outside it, so the palette is never cut off or hidden.
        """
        viewport = self.roi_view.viewport()
        pointer = viewport.map_from_global(QCursor.pos())
        size = self.coords_input.size_hint
        area = viewport.rect
        return QPoint(
            min(max(pointer.x(), 0), max(area.width() - size.width(), 0)),
            min(max(pointer.y(), 0), max(area.height() - size.height(), 0)))

    def _leave_mode(self) -> None:
        """Drop the draft, hide the palette and go back to selecting."""
        self._mode = EditMode.NONE
        self._watching = False
        self._draft = None
        self.roi_view.cursor = Qt.CursorShape.ArrowCursor
        self.coords_input.reset()
        self.ui.statusbar.clear_message()
        self._update_action_states()
        self._refresh_scene()

    def _cancel_mode(self) -> None:
        """Give up the shape being drawn, if any."""
        if self._mode is EditMode.NONE:
            return
        self._leave_mode()

    def _finish_shape(self) -> None:
        """Keep the shape being drawn when it has enough vertices."""
        if self._mode is not EditMode.CREATE_SHAPE or self._draft is None:
            return
        draft = self._draft
        minimum = 3 if draft.closed else 2
        self._leave_mode()
        if len(draft.vertices) < minimum:
            self.ui.statusbar.show_message(
                qformat(
                    self.__tr("%1 needs at least %2 vertices."),
                    [draft.name, minimum]),
                _HINT_TIMEOUT)
            return
        self._document.shapes.append(draft)
        self._selected_shape = draft
        self._selected_vertex = None
        self._refresh_all()

    def _on_view_clicked(self, point: QPointF) -> None:
        """Add a vertex, or select, depending on the mode."""
        if self._mode is EditMode.NONE:
            self._select_at(point)
        else:
            self._add_point(point)

    def _on_coords_accepted(self, point: QPointF) -> None:
        """Add the typed position while a mode is active."""
        if self._mode is EditMode.NONE:
            return
        self._add_point(point)

    def _add_point(self, point: QPointF) -> None:
        """Append or insert a vertex at `point`."""
        if self._mode is EditMode.CREATE_SHAPE:
            draft = self._draft
            if draft is None:
                return
            draft.vertices.append(point)
            self._note_outside(draft, point)
            if not draft.accepts_vertices:
                # A segment holds both of its endpoints now, so there
                # is nothing left to draw and the shape is kept.
                self._finish_shape()
                return
            self._refresh_scene()
            return
        shape = self._selected_shape
        if shape is None:
            return
        index = shape.insert_vertex(point)
        if index is None:
            return
        self._note_outside(shape, point)
        self._selected_vertex = index
        self._selected_shape = shape
        self._refresh_all()

    def _note_outside(self, shape: Shape, point: QPointF) -> None:
        """Allow outside vertices once one is given."""
        basemap = self._document.current_basemap
        if basemap is None:
            return
        if not basemap.contains(point):
            shape.allow_vertices_outside_basemap = True

    def _remove_vertex(self) -> None:
        """Drop the selected vertex."""
        shape = self._selected_shape
        index = self._selected_vertex
        if shape is None or index is None:
            return
        if not 0 <= index < len(shape.vertices):
            return
        shape.remove_vertex(index)
        self._selected_vertex = None
        self._refresh_all()

    # Shapes

    def _remove_shape(self) -> None:
        """Drop the selected shape after a confirmation."""
        shape = self._selected_shape
        if shape is None:
            return
        answer = QMessageBox.question(
            self, self.__tr("Remove Shape"),
            qformat(self.__tr("Remove shape %1?"), [shape.name]))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._document.shapes.remove(shape)
        self._selected_shape = None
        self._selected_vertex = None
        self._refresh_all()

    def _show_shape_props(self) -> None:
        """Edit the name and the flag of the selected shape."""
        shape = self._selected_shape
        if shape is None:
            return
        editor = ShapePropsEditor(shape, self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        shape.name = editor.shape_name
        shape.allow_vertices_outside_basemap = (
            editor.allow_vertices_outside_basemap)
        self._refresh_all()

    def _dump_shape(self) -> None:
        """Show the dump of the selected shape."""
        shape = self._selected_shape
        if shape is None:
            return
        DumpShapeDialog(shape, self).exec()

    def _unique_shape_name(self) -> str:
        """Return a shape name no other shape uses."""
        taken = {shape.name for shape in self._document.shapes}
        number = len(self._document.shapes) + 1
        while True:
            name = qformat(self.__tr("Shape %1"), [number])
            if name not in taken:
                return name
            number += 1

    # File dialogs

    def _start_directory(self, remembered: Path | None) -> str:
        """Return the folder a file dialog opens in by default.

        `remembered` is the folder the last file of the dialog's own
        kind was read from or written to; before there is one, the
        Documents folder of the user is the starting point, or their
        home folder where the system has no Documents folder.
        """
        if remembered is not None:
            return str(remembered)
        documents = QStandardPaths.writable_location(
            QStandardPaths.StandardLocation.DocumentsLocation)
        return documents or str(Path.home())

    # Basemaps

    def _add_basemap(self) -> None:
        """Load an image and show it as the active basemap."""
        path, _selected = QFileDialog.get_open_file_name(
            self, self.__tr("Add Basemap"),
            self._start_directory(self._image_directory),
            qformat(self.__tr("Image Files (%1)"), [_IMAGE_PATTERNS]))
        if not path:
            return
        image = QImage(path)
        if image.is_null():
            QMessageBox.critical(
                self, self.__tr("Add Basemap"),
                qformat(self.__tr("Cannot load %1"), [Path(path).name]))
            return
        self._image_directory = Path(path).parent
        suffix = Path(path).suffix.lstrip('.').upper()
        image_format = 'JPEG' if suffix == 'JPG' else (suffix or 'PNG')
        self._document.basemaps.append(Basemap(
            name=self._unique_basemap_name(Path(path).stem),
            image=image,
            image_format=image_format))
        self._document.active_basemap = len(self._document.basemaps) - 1
        self._refresh_all()

    def _remove_basemap(self) -> None:
        """Drop the selected basemap after a confirmation."""
        index = self._basemap_index
        if index is None or not 0 <= index < len(self._document.basemaps):
            return
        basemap = self._document.basemaps[index]
        answer = QMessageBox.question(
            self, self.__tr("Remove Basemap"),
            qformat(self.__tr("Remove basemap %1?"), [basemap.name]))
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._document.basemaps[index]
        if self._document.active_basemap >= len(self._document.basemaps):
            self._document.active_basemap = len(self._document.basemaps) - 1
        self._refresh_all()

    def _rename_basemap(self) -> None:
        """Rename the selected basemap."""
        index = self._basemap_index
        if index is None or not 0 <= index < len(self._document.basemaps):
            return
        basemap = self._document.basemaps[index]
        name, accepted = QInputDialog.get_text(
            self, self.__tr("Rename Basemap"), self.__tr("&Name:"),
            QLineEdit.EchoMode.Normal, basemap.name)
        if not accepted or not name.strip():
            return
        basemap.name = name.strip()
        self._refresh_all()

    def _unique_basemap_name(self, base: str) -> str:
        """Return a basemap name based on `base` that is free."""
        taken = {basemap.name for basemap in self._document.basemaps}
        if base not in taken:
            return base
        number = 2
        while f'{base} {number}' in taken:
            number += 1
        return f'{base} {number}'

    # Documents

    def _new_document(self) -> None:
        """Throw the document away and start over."""
        if not self._maybe_discard():
            return
        self._adopt_document(Document())

    def _open_document(self) -> None:
        """Read a document from a ``.rsroi`` file."""
        if not self._maybe_discard():
            return
        path, _selected = QFileDialog.get_open_file_name(
            self, self.__tr("Open Document"),
            self._start_directory(self._document_directory),
            qformat(self.__tr("ROI Files (%1)"), [_ROI_PATTERNS]))
        if not path:
            return
        self.load_path(Path(path))

    def load_path(self, path: Path) -> bool:
        """Load `path`, reporting a failure in a message box.

        Parameters
        ----------
        path : Path
            The ``.rsroi`` file to read.

        Returns
        -------
        bool
            Whether the file was read; the current document is left
            alone when it was not.
        """
        try:
            document = load_document(path)
        except StorageError as error:
            QMessageBox.critical(
                self, self.__tr("Open Document"),
                qformat(
                    self.__tr("Cannot open %1: %2"),
                    [path.name, str(error)]))
            return False
        self._document_directory = path.parent
        self._adopt_document(document)
        return True

    def _adopt_document(self, document: Document) -> None:
        """Make `document` the one being edited."""
        self._mode = EditMode.NONE
        self._watching = False
        self._draft = None
        self._selected_shape = None
        self._selected_vertex = None
        self.coords_input.reset()
        self.roi_view.cursor = Qt.CursorShape.ArrowCursor
        self._document = document
        self._refresh_all()

    def _save_document(self) -> None:
        """Write the document back to where it came from."""
        if self._document.path is None:
            self._save_document_as()
            return
        self._write_document(self._document.path)

    def _save_document_as(self) -> None:
        """Ask for a file and write the document to it."""
        suggestion = self._document.basename or (
            self.__tr("Untitled") + '.rsroi')
        path, _selected = QFileDialog.get_save_file_name(
            self, self.__tr("Save Document"),
            str(Path(self._start_directory(self._document_directory))
                / suggestion),
            qformat(self.__tr("ROI Files (%1)"), [_ROI_PATTERNS]))
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != '.rsroi':
            target = target.with_suffix('.rsroi')
        self._write_document(target)

    def _write_document(self, path: Path) -> None:
        """Write the document to `path`."""
        self.save_path(path)

    def save_path(self, path: Path) -> bool:
        """Write the document to `path`, reporting a failure.

        Parameters
        ----------
        path : Path
            The ``.rsroi`` file to write.

        Returns
        -------
        bool
            Whether the file was written and remembered.
        """
        try:
            save_document(self._document, path)
        except StorageError as error:
            QMessageBox.critical(
                self, self.__tr("Save Document"),
                qformat(
                    self.__tr("Cannot save %1: %2"),
                    [path.name, str(error)]))
            return False
        self._document_directory = path.parent
        self._document.path = path
        self._update_title()
        self.ui.statusbar.show_message(
            qformat(self.__tr("Saved %1"), [path.name]), _HINT_TIMEOUT)
        return True

    def _maybe_discard(self) -> bool:
        """Ask whether the current document may be thrown away."""
        if self._document.is_empty:
            return True
        answer = QMessageBox.question(
            self, self.__tr("Discard Document"),
            self.__tr("Discard the current document?"))
        return answer == QMessageBox.StandardButton.Yes

    # Help

    def _show_about(self) -> None:
        """Show the about box, named after the application."""
        app_name = QCoreApplication.application_name
        QMessageBox.about(
            self, qformat(self.__tr("About %1"), [app_name]),
            qformat(
                self.__tr(
                    "<p>%1</p><p>A simple ROI editor written in PySide6.</p>"),
                [app_name]))

    def _show_about_qt(self) -> None:
        """Show the Qt about box."""
        QApplication.about_qt()

    # Events

    @override
    def close_event(self, event: QCloseEvent) -> None:
        """Ask before closing a document worth keeping."""
        if self._maybe_discard():
            super().close_event(event)
        else:
            event.ignore()

    def __tr(self,
             source_text: str, disambiguation: str | None = None,
             n: int = -1) -> str:
        return QCoreApplication.translate(
            'MainWindow', source_text, disambiguation, n)


def main() -> None:
    """Run the editor."""
    app = QApplication(sys.argv)
    QCoreApplication.application_name = APPLICATION_NAME  # pyrefly: ignore[bad-assignment]
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
