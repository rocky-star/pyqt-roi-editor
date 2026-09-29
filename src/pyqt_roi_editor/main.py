"""The main window and the entry point of the ROI editor.

The editing area and both docks are built in `MainWindow` rather than
in the `.ui` file, so the generated form stays as the skeleton it
started as.
"""

__all__ = [
    'APPLICATION_NAME', 'EditMode', 'MainWindow', 'installed_version', 'main',
]

import enum
import importlib.metadata
import math
import sys
from pathlib import Path
from typing import cast, override

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QItemSelectionModel,
    QLibraryInfo,
    QLocale,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QStandardPaths,
    Qt,
    QTimer,
    QTranslator,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
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
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTreeView,
)

from pyqt_roi_editor import rc_roieditor  # pyright: ignore[reportUnusedImport]
from pyqt_roi_editor.coords_input import CoordsInput
from pyqt_roi_editor.document import Basemap, Document, Shape, ShapeKind
from pyqt_roi_editor.dump_shape_dialog import DumpShapeDialog
from pyqt_roi_editor.helpers import format_number, qformat
from pyqt_roi_editor.roi_graphics_view import ROIGraphicsView, Tool
from pyqt_roi_editor.shape_props_editor import ShapePropsEditor
from pyqt_roi_editor.storage import StorageError, load_document, save_document
from pyqt_roi_editor.ui_mainwindow import Ui_MainWindow
from pyqt_roi_editor.zoom_box import ZoomBox, ZoomFit

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]

APPLICATION_NAME = 'ROI Editor'

_ROI_PATTERNS = '*.rsroi'
_IMAGE_PATTERNS = '*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp'
# The drawing keeps the size it has on the screen, so a handle is as
# big and an outline as thick at every zoom; both of these are pixels
# of the view rather than coordinates of the basemap.
_HANDLE_RADIUS = 4.0
_SELECTION_TOLERANCE = 6.0
_THUMBNAIL_SIZE = 48
_HINT_TIMEOUT = 5000
# The colour of a selected shape, and the wash filling the inside of
# a selected polygon, which is what tells the two kinds apart at a
# glance.
_SELECTION_COLOR = QColor(255, 200, 0)
_SELECTION_FILL = QColor(255, 200, 0, 64)
# The keys that start a typed coordinate, and so open the palette.
_COORDINATE_KEYS = '0123456789-'
# The keys that may separate its two numbers.  Both forms are sent to
# an open palette the way the digits are, so that a coordinate may be
# typed either way wherever the focus happens to be.
_SEPARATOR_KEYS = ', '
# The name of the catalogue Qt puts its own wording in, and the name
# and the resource directory of the compiled translation of the
# interface, which `roieditor.qrc` stores in the resources.
_QT_TRANSLATION_NAME = 'qtbase'
_TRANSLATION_NAME = 'roieditor'
_TRANSLATION_DIRECTORY = ':/translations'


class EditMode(enum.Enum):
    """What a click in the editing area currently does."""

    NONE = 'none'
    CREATE_SHAPE = 'create_shape'
    ADD_VERTEX = 'add_vertex'


def _nearest_vertex(
        shape: Shape, point: QPointF, tolerance: float) -> int | None:
    """Return the vertex of `shape` closest to `point`, if near enough.

    Parameters
    ----------
    shape : Shape
        The shape whose vertices are looked at.
    point : QPointF
        The position to measure from, in scene coordinates.
    tolerance : float
        How far `point` may lie from a vertex and still count as
        being on it, in scene coordinates.
    """
    best: int | None = None
    best_distance = tolerance
    for index, vertex in enumerate(shape.vertices):
        distance = math.hypot(vertex.x() - point.x(), vertex.y() - point.y())
        if distance <= best_distance:
            best = index
            best_distance = distance
    return best


def _snapped(point: QPointF) -> QPointF:
    """Return `point` rounded to the pixel a vertex names.

    The coordinates of a document are whole pixels of the basemap.
    The view turns a position into scene coordinates at whatever zoom
    is in force, so one the pointer gives arrives with a fraction of
    its own; rounding it is what keeps the pixels whole, and a drag
    moves on that grid too.  A typed coordinate needs no rounding:
    the palette takes whole numbers only.
    """
    return QPointF(round(point.x()), round(point.y()))


def _step_between(values: list[float], limit: float) -> float:
    """Return the step bringing `values` within ``0 <= value <= limit``.

    The step is one number for the whole set, so that a shape stopped
    at the edge of its basemap keeps its form instead of being
    squashed against the edge.  A set that is already inside is left
    where it is, and one too large for the space sits against the
    lower edge.
    """
    low = min(values)
    if low < 0.0:
        return -low
    high = max(values)
    if high > limit:
        return limit - high
    return 0.0


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
        self._drag_origin: QPointF | None = None
        self._drag_base: list[QPointF] | None = None
        self._tool = Tool.SELECTION
        self._panning = False
        self._in_view = False
        self._mode_hint = ''
        self._basemap_index: int | None = None
        self._basemap_item: QGraphicsPixmapItem | None = None
        self._document_directory: Path | None = None
        self._image_directory: Path | None = None
        self._zoom_ratio = 1.0
        # The view fits the window until it is asked for something
        # else, which is what a document being opened expects.
        self._zoom_fit: ZoomFit | None = ZoomFit.WINDOW
        self._syncing = False
        self._watching = False
        self._build_editor_area()
        self._connect_signals()
        self._fill_action_placeholders()
        self._choose_tool(Tool.SELECTION)
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
        self.roi_view.context_menu_policy = (
            Qt.ContextMenuPolicy.CustomContextMenu)
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
        self.shapes_view.context_menu_policy = (
            Qt.ContextMenuPolicy.CustomContextMenu)
        # The names of a shape and of its vertices are longer than
        # the two numbers beside them, so that column takes what it
        # needs and the numbers share what is left.
        header = self.shapes_view.header()
        header.set_section_resize_mode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        header.set_section_resize_mode(
            1, QHeaderView.ResizeMode.Stretch)
        header.set_section_resize_mode(
            2, QHeaderView.ResizeMode.Stretch)
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
        # The zoom control sits at the right of the status bar, where
        # a status message never reaches it.
        self.zoom_box = ZoomBox(self)
        self.ui.statusbar.add_permanent_widget(self.zoom_box)
        # One tool is in force at a time, and the group is what keeps
        # the three of the toolbox from being chosen together.
        self.tool_group = QActionGroup(self)
        self.tool_group.add_action(self.ui.action_selection_tool)
        self.tool_group.add_action(self.ui.action_hand_tool)
        self.tool_group.add_action(self.ui.action_zoom_tool)
        # The keys that drive drawing are caught for the whole
        # application: after a menu action the focus sits on the menu
        # bar, so the view never sees them.
        application = QApplication.instance()
        if application is not None:
            application.install_event_filter(self)

    def _connect_signals(self) -> None:
        """Connect the views, the palette and every menu action."""
        self.roi_view.clicked.connect(self._on_view_clicked)
        self.roi_view.dragged.connect(self._on_view_dragged)
        self.roi_view.drag_finished.connect(self._on_view_drag_finished)
        self.roi_view.finish_requested.connect(self._finish_shape)
        self.roi_view.zoom_requested.connect(self._zoom_to_ratio)
        self.roi_view.zoom_area_requested.connect(self._zoom_to_area)
        self.roi_view.pan_started.connect(self._on_view_pan_started)
        self.roi_view.pan_finished.connect(self._on_view_pan_finished)
        self.roi_view.pointer_entered.connect(self._on_view_pointer_entered)
        self.roi_view.pointer_left.connect(self._on_view_pointer_left)
        self.tool_group.triggered.connect(self._on_tool_chosen)
        self.coords_input.accepted.connect(self._on_coords_accepted)
        self.coords_input.rejected.connect(self._cancel_mode)
        self.zoom_box.ratio_requested.connect(self._zoom_to_ratio)
        self.zoom_box.fit_requested.connect(self._zoom_to_fit)
        self.roi_view.resized.connect(self._reapply_zoom)
        self.roi_view.customContextMenuRequested.connect(self._show_view_menu)
        self.shapes_view.customContextMenuRequested.connect(
            self._show_shapes_menu)
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

    def _refresh_shapes(self) -> None:
        """Rebuild what only the shapes decide.

        Moving a shape leaves the images and the title as they were,
        which matters because a drag does this on every step of the
        pointer.
        """
        if self._syncing:
            return
        self._syncing = True
        try:
            self._rebuild_shapes_model()
            self.shapes_view.expand_all()
            self._apply_tree_selection()
            self._refresh_scene()
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
            for number, vertex in enumerate(shape.vertices, start=1):
                items = [
                    QStandardItem(qformat(
                        self.__tr("Vertex %1"), [number])),
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
        # The area the view shows may have changed with the scene.
        self._reapply_zoom()

    def _add_shape_item(self, shape: Shape, selected: bool) -> None:
        """Draw `shape`, highlighted when it is the selected one.

        A selected polygon is also filled, so that the area it closes
        over is as visible as its outline.  The outline is drawn at
        its own width: a zoom is there to show more of the image, not
        to draw the shapes any fatter.
        """
        path = QPainterPath()
        if shape.vertices:
            path.move_to(shape.vertices[0])
            for vertex in shape.vertices[1:]:
                path.line_to(vertex)
            if shape.closed:
                path.close_subpath()
        item = self._scene.add_path(path)
        pen = QPen(
            _SELECTION_COLOR if selected else QColor(0, 200, 255),
            3.0 if selected else 2.0)
        pen.set_cosmetic(True)
        item.set_pen(pen)
        if selected and shape.closed:
            item.set_brush(QBrush(_SELECTION_FILL))
        item.set_data(0, shape)

    def _add_handles(self, shape: Shape) -> None:
        """Draw a handle on every vertex of the selected shape.

        A handle is centred on its vertex and drawn with the view's
        transformation left out, so that it stays the size of the
        pointer that grabs it however far the view is zoomed.
        """
        for index, vertex in enumerate(shape.vertices):
            selected = index == self._selected_vertex
            handle = QGraphicsEllipseItem(
                -_HANDLE_RADIUS, -_HANDLE_RADIUS,
                _HANDLE_RADIUS * 2.0, _HANDLE_RADIUS * 2.0)
            handle.set_flag(
                QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            handle.set_pen(QPen(QColor(0, 0, 0), 1.0))
            handle.set_brush(QBrush(
                QColor(255, 64, 64) if selected else QColor(255, 255, 255)))
            handle.set_accepted_mouse_buttons(Qt.MouseButton.NoButton)
            handle.set_pos(vertex)
            handle.set_data(0, index)
            self._scene.add_item(handle)

    def _update_title(self) -> None:
        """Show the document and the application in the title bar."""
        self.window_title = qformat(
            self.__tr("%1 - %2"),
            [self._document_name(), QCoreApplication.application_name])

    def _update_action_states(self) -> None:
        """Enable each action whose target currently exists."""
        shape = self._selected_shape
        has_basemap = self._basemap_index is not None
        has_shape = shape is not None
        has_vertex = has_shape and self._selected_vertex is not None
        can_add_vertex = shape is not None and shape.accepts_vertices
        idle = self._mode is EditMode.NONE
        # A new shape is built from basemap pixels, so there has to be
        # an image to build it on.
        can_start_shape = idle and has_basemap
        self.ui.action_remove_basemap.enabled = (
            has_basemap and not self._last_basemap_carries_shapes())
        self.ui.action_rename_basemap.enabled = has_basemap
        self.ui.action_remove_shape.enabled = has_shape and idle
        self.ui.action_shape_props.enabled = has_shape and idle
        self.ui.action_dump_shape.enabled = has_shape
        self.ui.action_add_vertex.enabled = can_add_vertex and idle
        self.ui.action_remove_vertex.enabled = has_vertex and idle
        self.ui.action_add_line.enabled = can_start_shape
        self.ui.action_add_polygon.enabled = can_start_shape

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

    def _grab_tolerance(self) -> float:
        """Return the scene distance a press may miss a handle by.

        The handle the press aims at keeps its size on the screen, so
        the distance it may be missed by is an on-screen distance as
        well, and the zoom is what turns it into basemap pixels.
        """
        return _SELECTION_TOLERANCE / max(self._zoom_ratio, 0.001)

    def _select_at(self, point: QPointF) -> None:
        """Select the handle, shape or nothing under `point`."""
        shape = self._selected_shape
        if shape is not None:
            index = _nearest_vertex(shape, point, self._grab_tolerance())
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
        """Switch the shown basemap to the selected one.

        Clicking an empty spot in the list clears the selection, which
        is not a request to show nothing: the image that is shown
        stays the one it was, and the list is put back on it.
        """
        if self._syncing:
            return
        indexes = self.basemaps_view.selection_model().selected_indexes
        if not indexes:
            self._apply_basemap_selection()
            return
        self._basemap_index = indexes[0].row()
        self._document.active_basemap = self._basemap_index
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

    # Tools

    def _on_tool_chosen(self, action: QAction) -> None:
        """Make the view act with the tool the chosen action names."""
        if action is self.ui.action_hand_tool:
            tool = Tool.HAND
        elif action is self.ui.action_zoom_tool:
            tool = Tool.ZOOM
        else:
            tool = Tool.SELECTION
        self._choose_tool(tool)

    def _choose_tool(self, tool: Tool) -> None:
        """Make `tool` what the primary button does in the editing area.

        A shape being drawn gives way before it, since the tool takes
        the primary button for itself; the third button and the zoom
        box go on working while a shape is drawn.
        """
        self._cancel_mode()
        self._tool = tool
        self._update_view_tool()
        self._update_cursor()
        self._update_tool_choice()
        self._show_hint()

    def _tool_in_force(self) -> Tool:
        """Return the tool the view is acting with right now.

        The third button borrows the hand tool for as long as it is
        held, wherever the toolbox stands, and the toolbox shows that
        while it lasts.
        """
        return Tool.HAND if self._panning else self._tool

    def _action_of_tool(self, tool: Tool) -> QAction:
        """Return the action of the toolbox that names `tool`."""
        if tool is Tool.HAND:
            return self.ui.action_hand_tool
        if tool is Tool.ZOOM:
            return self.ui.action_zoom_tool
        return self.ui.action_selection_tool

    def _update_tool_choice(self) -> None:
        """Check the toolbox action of the tool in force."""
        self._action_of_tool(self._tool_in_force()).checked = True

    def _update_view_tool(self) -> None:
        """Tell the view which tool the primary button acts with.

        A shape being drawn takes the primary button for itself, so the
        view reports clicks the way the selection tool does until the
        drawing is over, whatever the toolbox is set to.
        """
        if self._mode is EditMode.NONE:
            self.roi_view.tool = self._tool
        else:
            self.roi_view.tool = Tool.SELECTION

    def _update_cursor(self) -> None:
        """Show the pointer as what the primary button will do."""
        if self._mode is not EditMode.NONE:
            cursor = Qt.CursorShape.CrossCursor
        elif self._tool is Tool.HAND:
            cursor = Qt.CursorShape.OpenHandCursor
        elif self._tool is Tool.ZOOM:
            cursor = Qt.CursorShape.SizeHorCursor
        else:
            cursor = Qt.CursorShape.ArrowCursor
        self.roi_view.cursor = cursor

    def _show_hint(self) -> None:
        """Show what the canvas is doing in the status bar.

        A shape being drawn comes first: its hint is the one that says
        what the primary button does while it is drawn.  The tool in
        force is explained while the pointer is over the canvas, and
        the status bar is left to the document while it is not.
        """
        if self._mode is not EditMode.NONE:
            self.ui.statusbar.show_message(self._mode_hint)
            return
        if not self._in_view:
            self.ui.statusbar.clear_message()
            return
        tool = self._tool_in_force()
        if tool is Tool.HAND:
            hint = self.__tr("Drag to move the view.")
        elif tool is Tool.ZOOM:
            hint = self.__tr(
                "Drag left to zoom out and right to zoom in; drag a box"
                + " with the secondary button to fill the view with it.")
        else:
            hint = self.__tr(
                "Click a shape to select it; drag it or a handle to"
                + " move it.")
        self.ui.statusbar.show_message(hint)

    def _show_message(self, message: str) -> None:
        """Show `message` for a while, and then the hint again.

        A message about the document is worth reading and worth
        replacing afterwards with what the canvas is doing, which
        `_show_hint` says and the pointer decides.
        """
        self.ui.statusbar.show_message(message)
        QTimer.single_shot(_HINT_TIMEOUT, self, self._show_hint)

    def _on_view_pointer_entered(self) -> None:
        """Show what the canvas is doing, the pointer having come over."""
        self._in_view = True
        self._show_hint()

    def _on_view_pointer_left(self) -> None:
        """Leave the status bar to the document, the pointer having gone."""
        self._in_view = False
        self._show_hint()

    def _on_view_pan_started(self) -> None:
        """Show the hand tool while the pointer moves the view.

        The third button lends the tool to the view wherever the
        toolbox stands; a shape being drawn keeps the status bar for
        itself, since its hint is the one that counts there.
        """
        if self._mode is not EditMode.NONE:
            return
        self._panning = True
        self._update_tool_choice()
        self._show_hint()

    def _on_view_pan_finished(self) -> None:
        """Give the toolbox its say back, if it lent it away."""
        if not self._panning:
            return
        self._panning = False
        self._update_tool_choice()
        self._show_hint()

    # Zooming

    def _zoom_to_ratio(self, ratio: float) -> None:
        """Show the scene at `ratio` of its natural size."""
        self._zoom_fit = None
        self._apply_zoom(ratio)

    def _zoom_to_fit(self, fit: ZoomFit) -> None:
        """Keep following the viewport with the zoom `fit` names."""
        self._zoom_fit = fit
        self._reapply_zoom()

    def _reapply_zoom(self) -> None:
        """Apply the zoom the viewport size asks for, if it asks."""
        if self._zoom_fit is None:
            self._update_zoom_box()
            return
        ratio = self._fit_ratio(self._zoom_fit)
        if abs(ratio - self._zoom_ratio) < 0.0005:
            # The view is where it should be, but the box may still be
            # showing the name of the mode it was asked for.
            self._update_zoom_box()
            return
        self._apply_zoom(ratio)

    def _fit_ratio(self, fit: ZoomFit) -> float:
        """Return the ratio that fits the scene into the viewport.

        `scene_rect` is a property once true_property is active, even
        though the stub still describes the getter.
        """
        rect = cast('QRectF', self._scene.scene_rect)
        if rect.width() <= 0.0 or rect.height() <= 0.0:
            return 1.0
        viewport = self.roi_view.viewport()
        width = float(viewport.width)
        height = float(viewport.height)
        if fit is ZoomFit.WIDTH:
            return width / rect.width()
        return min(width / rect.width(), height / rect.height())

    def _apply_zoom(self, ratio: float, middle: QPointF | None = None) -> None:
        """Show the scene at `ratio`, with `middle` in the middle.

        `middle` is a point of the scene to put in the middle of the
        viewport; the one already there is kept when none is named,
        which is what a plain change of scale asks for.
        """
        if middle is None:
            middle = self.roi_view.map_to_scene(
                self.roi_view.viewport().rect.center())
        self.roi_view.reset_transform()
        self.roi_view.scale(ratio, ratio)
        self.roi_view.center_on(middle)
        self._zoom_ratio = ratio
        self._update_zoom_box()

    def _zoom_to_area(self, area: QRectF) -> None:
        """Show the scene so that `area` fills the viewport.

        The area is the one the pointer framed with the zoom tool, so
        the view is scaled to fit it and centred on it.
        """
        viewport = self.roi_view.viewport()
        ratio = min(viewport.width / area.width(),
                    viewport.height / area.height())
        self._zoom_fit = None
        self._apply_zoom(ratio, area.center())

    def _update_zoom_box(self) -> None:
        """Show what the view is doing in the zoom box."""
        if self._zoom_fit is None:
            self.zoom_box.show_ratio(self._zoom_ratio)
            return
        self.zoom_box.show_fit(self._zoom_fit, self._zoom_ratio)

    # Context menus

    def _show_shapes_menu(self, position: QPoint) -> None:
        """Offer what can be done to the item under `position`.

        The item the pointer is on becomes the selection, so that the
        menu describes what is about to be acted on rather than what
        happened to be selected before.
        """
        if self._mode is not EditMode.NONE:
            return
        index = self.shapes_view.index_at(position)
        if not index.is_valid():
            return
        self.shapes_view.set_current_index(index)
        self.shapes_view.selection_model().select(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows)
        menu = self._selection_menu(add_vertex=False)
        if menu is not None:
            menu.popup(self.shapes_view.viewport().map_to_global(position))

    def _show_view_menu(self, position: QPoint) -> None:
        """Offer what can be done to what is drawn under `position`.

        Empty canvas has nothing to act on, but it is where a shape is
        drawn, so it offers the shapes that can be started.  A tool
        that takes the primary button leaves the secondary one to
        itself, which the zoom tool spends on framing an area.
        """
        if (self._mode is not EditMode.NONE
                or self._tool is not Tool.SELECTION):
            return
        self._select_at(self.roi_view.map_to_scene(position))
        menu = self._selection_menu(add_vertex=True)
        if menu is None:
            menu = self._add_shape_menu()
        menu.popup(self.roi_view.viewport().map_to_global(position))

    def _add_shape_menu(self) -> QMenu:
        """Return a menu holding the shapes that can be started."""
        menu = QMenu(self)
        menu.add_menu(self.ui.menu_add_shape)
        return menu

    def _selection_menu(self, *, add_vertex: bool) -> QMenu | None:
        """Return the menu of what can be done to the selection.

        Nothing is offered without a selected shape; the vertices of
        one add an action of their own.  Starting a vertex is offered
        on the canvas alone, since that is where the places to put one
        are.
        """
        if self._selected_shape is None:
            return None
        menu = QMenu(self)
        menu.add_actions((
            self.ui.action_remove_shape,
            self.ui.action_shape_props,
            self.ui.action_dump_shape,
        ))
        if add_vertex or self._selected_vertex is not None:
            menu.add_separator()
        if add_vertex:
            menu.add_action(self.ui.action_add_vertex)
        if self._selected_vertex is not None:
            menu.add_action(self.ui.action_remove_vertex)
        return menu

    # Drawing a shape

    def _add_line(self) -> None:
        """Start drawing a line."""
        self._start_shape(ShapeKind.LINE)

    def _add_polygon(self) -> None:
        """Start drawing a polygon."""
        self._start_shape(ShapeKind.POLYGON)

    def _start_shape(self, kind: ShapeKind) -> None:
        """Start a shape of `kind`; the palette waits for a digit.

        Coordinates are basemap pixels, so a shape drawn over no image
        at all would mean nothing, and the action is not offered
        either.
        """
        if self._document.current_basemap is None:
            return
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
        self._mode_hint = hint
        self._watching = True
        self._drag_origin = None
        self._drag_base = None
        self.coords_input.reset()
        self._update_view_tool()
        self._update_cursor()
        self.roi_view.set_focus()
        self._show_hint()
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
        return event.text() in _COORDINATE_KEYS + _SEPARATOR_KEYS

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
        focus = QApplication.focus_widget()
        if focus is not None and self.zoom_box.is_ancestor_of(focus):
            # The zoom box is typing a percentage of its own.
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

        An open palette is given the separators as well as the digits,
        rather than leaving them to the field: the field holds the
        focus only until something else is clicked, and a key left to
        it would then be lost, running the two numbers of a coordinate
        together.
        """
        if self._mode not in (EditMode.CREATE_SHAPE, EditMode.ADD_VERTEX):
            return False
        if not self.coords_input.visible:
            if character not in _COORDINATE_KEYS:
                return False
            self.coords_input.popup_at(self._palette_position(), character)
            return True
        if character not in _COORDINATE_KEYS + _SEPARATOR_KEYS:
            return False
        self.coords_input.insert_text(character)
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
        """Drop the draft, hide the palette and go back to the tool."""
        self._mode = EditMode.NONE
        self._mode_hint = ''
        self._watching = False
        self._draft = None
        self._update_view_tool()
        self._update_cursor()
        self.coords_input.reset()
        self._show_hint()
        self._update_action_states()
        self._refresh_scene()

    def _cancel_mode(self) -> None:
        """Give up the shape being drawn, if any."""
        if self._mode is EditMode.NONE:
            return
        self._leave_mode()

    def _drop_draft_without_basemap(self) -> None:
        """Stop drawing once the image it is drawn on is gone."""
        if self._document.current_basemap is None:
            self._cancel_mode()

    def _finish_shape(self) -> None:
        """Keep the shape being drawn when it has enough vertices."""
        if self._mode is not EditMode.CREATE_SHAPE or self._draft is None:
            return
        draft = self._draft
        minimum = 3 if draft.closed else 2
        self._leave_mode()
        if len(draft.vertices) < minimum:
            self._show_message(
                qformat(
                    self.__tr("%1 needs at least %2 vertices."),
                    [draft.name, minimum]))
            return
        self._document.shapes.append(draft)
        self._selected_shape = draft
        self._selected_vertex = None
        self._refresh_all()

    def _on_view_clicked(self, point: QPointF) -> None:
        """Add a vertex, or select what the press landed on.

        A press that selects is also where a drag begins, so what it
        landed on is kept until the pointer is let go.
        """
        if self._mode is not EditMode.NONE:
            self._add_point(point)
            return
        self._select_at(point)
        self._begin_drag(point)

    def _begin_drag(self, point: QPointF) -> None:
        """Remember the vertices a drag from `point` may move.

        What the press selected decides what moves: a vertex handle
        moves that vertex alone, and anything else moves the shape as
        a whole.  The vertices are kept as they were at the press, so
        that every step of the drag can be measured against them.
        """
        self._drag_origin = None
        self._drag_base = None
        shape = self._selected_shape
        if shape is None:
            return
        index = self._selected_vertex
        if index is not None and 0 <= index < len(shape.vertices):
            self._drag_base = [shape.vertices[index]]
        else:
            self._drag_base = list(shape.vertices)
        self._drag_origin = point

    def _on_view_dragged(self, point: QPointF) -> None:
        """Move what the press selected to where the pointer has got.

        The step is measured from the press rather than added move by
        move, so a drag that comes back to where it started puts the
        shape back exactly, and it is rounded to whole pixels, so
        dragging never leaves a vertex between two of them.
        """
        origin = self._drag_origin
        base = self._drag_base
        if origin is None or base is None or self._mode is not EditMode.NONE:
            return
        self._drag_selection(base, _snapped(point - origin))

    def _drag_selection(
            self, base: list[QPointF], offset: QPointF) -> None:
        """Move the vertices of `base` by `offset`, within the basemap.

        The whole shape takes one step, so that dragging it about
        never changes its form; a single vertex follows the pointer on
        its own.
        """
        shape = self._selected_shape
        if shape is None:
            return
        moved = self._kept_inside(shape, [
            QPointF(vertex.x() + offset.x(), vertex.y() + offset.y())
            for vertex in base])
        index = self._selected_vertex
        if index is not None and 0 <= index < len(shape.vertices):
            shape.vertices[index] = moved[0]
        else:
            shape.vertices = moved
        self._refresh_shapes()

    def _kept_inside(
            self, shape: Shape, vertices: list[QPointF]) -> list[QPointF]:
        """Return `vertices` as far as the basemap lets them go.

        A shape that may hold vertices outside of the basemap keeps
        them wherever the pointer puts them.  One that may not stops
        at the edge: a shape dragged as a whole slides back along the
        edge, and a vertex dragged on its own is held at the edge it
        reaches.
        """
        basemap = self._document.current_basemap
        if basemap is None or shape.allow_vertices_outside_basemap:
            return vertices
        step_x = _step_between(
            [vertex.x() for vertex in vertices],
            float(basemap.image.width() - 1))
        step_y = _step_between(
            [vertex.y() for vertex in vertices],
            float(basemap.image.height() - 1))
        return [
            QPointF(vertex.x() + step_x, vertex.y() + step_y)
            for vertex in vertices]

    def _on_view_drag_finished(self) -> None:
        """Stop moving the selection, the pointer having been let go."""
        self._drag_origin = None
        self._drag_base = None

    def _on_coords_accepted(self, point: QPointF) -> None:
        """Add the typed position while a mode is active."""
        if self._mode is EditMode.NONE:
            return
        self._add_point(point)

    def _add_point(self, point: QPointF) -> None:
        """Append or insert a vertex at `point`, on the pixel grid.

        A coordinate of the document is a whole pixel: one that was
        typed arrives whole already, and one the pointer gives is
        rounded to the nearest.
        """
        point = _snapped(point)
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
            self, self._document_name(),
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
                self, self._document_name(),
                qformat(self.__tr("Cannot load %1"), [Path(path).name]))
            return
        self._image_directory = Path(path).parent
        suffix = Path(path).suffix.lstrip('.').upper()
        image_format = 'JPEG' if suffix == 'JPG' else (suffix or 'PNG')
        self._document.basemaps.append(Basemap(
            name=self._unique_basemap_name(Path(path).name),
            image=image,
            image_format=image_format))
        self._document.active_basemap = len(self._document.basemaps) - 1
        self._refresh_all()

    def _last_basemap_carries_shapes(self) -> bool:
        """Return whether the only image left is drawn on.

        The vertices of a shape are pixels of an image, so a document
        holding shapes keeps the image they are placed in; without one
        the shapes would be coordinates of nothing.
        """
        return len(self._document.basemaps) == 1 and bool(
            self._document.shapes)

    def _remove_basemap(self) -> None:
        """Drop the selected basemap after a confirmation."""
        index = self._basemap_index
        if index is None or not 0 <= index < len(self._document.basemaps):
            return
        if self._last_basemap_carries_shapes():
            return
        basemap = self._document.basemaps[index]
        answer = QMessageBox.question(
            self, self._document_name(),
            qformat(self.__tr("Remove basemap %1?"), [basemap.name]))
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._document.basemaps[index]
        if self._document.active_basemap >= len(self._document.basemaps):
            self._document.active_basemap = len(self._document.basemaps) - 1
        self._drop_draft_without_basemap()
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

    def _unique_basemap_name(self, file_name: str) -> str:
        """Return a basemap name based on `file_name` that is free.

        The name is the name of the image file, as the format keeps
        it; a second image of the same name is counted before its
        extension, which stays last.
        """
        taken = {basemap.name for basemap in self._document.basemaps}
        if file_name not in taken:
            return file_name
        stem = Path(file_name).stem
        suffix = Path(file_name).suffix
        number = 2
        while f'{stem} {number}{suffix}' in taken:
            number += 1
        return f'{stem} {number}{suffix}'

    # Documents

    def _document_name(self) -> str:
        """Return the name the document is shown by.

        It is the name of the file the document is saved in, without
        the extension every document of the format shares, and a
        document that has not been saved yet goes by the name of the
        untitled one.  The title bar and every message box that
        speaks of the document rather than of another file are shown
        under it.
        """
        path = self._document.path
        if path is None:
            return self.__tr("Untitled")
        return path.stem

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
            self, self.__tr("Open"),
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
            # The file that could not be read is not the one being
            # edited, which the document is named by everywhere else,
            # so this message speaks under the application instead.
            QMessageBox.critical(
                self,
                # pyrefly: ignore[bad-argument-type]
                QCoreApplication.application_name,
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
        self._update_view_tool()
        self._update_cursor()
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
        # The file to suggest is the document by the name it is shown
        # under, with the extension the format gives every file.
        suggestion = self._document_name() + '.rsroi'
        path, _selected = QFileDialog.get_save_file_name(
            self, self.__tr("Save As"),
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
                self, self._document_name(),
                qformat(
                    self.__tr("Cannot save %1: %2"),
                    [path.name, str(error)]))
            return False
        self._document_directory = path.parent
        self._document.path = path
        self._update_title()
        self._show_message(qformat(self.__tr("Saved %1"), [path.name]))
        return True

    def _maybe_discard(self) -> bool:
        """Ask whether the current document may be thrown away."""
        if self._document.is_empty:
            return True
        answer = QMessageBox.question(
            self, self._document_name(),
            self.__tr("Discard the current document?"))
        return answer == QMessageBox.StandardButton.Yes

    # Help

    def _show_about(self) -> None:
        """Show the about box, with the application name and version."""
        app_name = QCoreApplication.application_name
        version = (
            QCoreApplication.application_version
            or self.__tr("(unspecified version)"))
        text = self.__tr(
            "<p>%1, version %2</p>"
            + "<p>A simple ROI editor written in PySide6.</p>")
        QMessageBox.about(
            self, qformat(self.__tr("About %1"), [app_name]),
            qformat(text, [app_name, version]))

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


def installed_version() -> str:
    """Return the version of the installed distribution, or ``''``.

    The metadata names the distribution, which carries the package
    with the punctuation the packaging uses.  A source tree that was
    never installed has no metadata to read, and so no version to
    show.
    """
    try:
        return importlib.metadata.version('pyqt-roi-editor')
    except importlib.metadata.PackageNotFoundError:
        return ''


def _install_translator(app: QApplication, name: str, directory: str) -> None:
    """Install the translation of `name` found in `directory`, if any.

    A catalogue that is not there is left out, and the wording it
    would have given stays in the English of the sources.
    """
    translator = QTranslator(app)
    if translator.load(QLocale.system(), name, '_', directory):
        app.install_translator(translator)


def _install_translations(app: QApplication) -> None:
    """Show the interface in the language of the system, if known.

    Qt has a catalogue of its own for the wording it brings, that of
    the buttons of a message box for example, and the editor has one
    for its menus and messages, which `roieditor.qrc` stores in the
    resources that importing `rc_roieditor` registers.  The editor is
    installed last because the translator installed last is the one
    asked first.
    """
    _install_translator(
        app, _QT_TRANSLATION_NAME,
        QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    _install_translator(app, _TRANSLATION_NAME, _TRANSLATION_DIRECTORY)


def main() -> None:
    """Run the editor."""
    app = QApplication(sys.argv)
    # pyrefly: ignore[bad-assignment]
    QCoreApplication.application_name = APPLICATION_NAME
    # pyrefly: ignore[bad-assignment]
    QCoreApplication.application_version = installed_version()
    _install_translations(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
