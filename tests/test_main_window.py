"""Tests for the main window, the editing area and the docks."""

import importlib.metadata
from pathlib import Path

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QPoint,
    QPointF,
    QStandardPaths,
    Qt,
)
from PySide6.QtGui import QCursor, QGuiApplication, QImage, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QListView,
    QMenu,
    QMessageBox,
    QTreeView,
)

from pyqt_roi_editor.document import Basemap, Document, ShapeKind
from pyqt_roi_editor.dump_shape_dialog import DumpShapeDialog
from pyqt_roi_editor.main import (
    APPLICATION_NAME,
    EditMode,
    MainWindow,
    installed_version,
)
from pyqt_roi_editor.roi_graphics_view import ROIGraphicsView
from pyqt_roi_editor.shape_props_editor import ShapePropsEditor
from pyqt_roi_editor.storage import save_document
from pyqt_roi_editor.zoom_box import ZoomBox, ZoomFit

from __feature__ import snake_case, true_property


def sample_image() -> QImage:
    """Return the image the tests draw on."""
    image = QImage(100, 80, QImage.Format.Format_RGB32)
    image.fill(0xff336699)
    return image


def show_basemap(window: MainWindow) -> None:
    """Give `window` a basemap and show it."""
    window.document.basemaps.append(Basemap('map', sample_image(), 'PNG'))
    window.document.active_basemap = len(window.document.basemaps) - 1
    window._refresh_all()


@pytest.fixture
def window(qapp):
    """Return a shown main window with a basemap to draw on.

    The editor draws nothing before an image is shown, and nearly
    every test edits shapes, so the common window starts with one.
    """
    QCoreApplication.application_name = APPLICATION_NAME
    main_window = MainWindow()
    main_window.show()
    show_basemap(main_window)
    return main_window


@pytest.fixture
def blank_window(window):
    """Return a shown main window with no basemap at all."""
    window.document.basemaps.clear()
    window.document.active_basemap = -1
    window._refresh_all()
    return window


@pytest.fixture(autouse=True)
def silent_message_boxes(monkeypatch):
    """Keep a message box from blocking the headless run."""
    for name in ('critical', 'question', 'information'):
        monkeypatch.setattr(
            QMessageBox, name, staticmethod(lambda *args, **kwargs: None))


@pytest.fixture(autouse=True)
def closed_menus():
    """Close a context menu a test left open."""
    yield
    popup = QApplication.active_popup_widget()
    if popup is not None:
        popup.close()


def open_menu(widget, position: QPoint) -> QMenu:
    """Ask `widget` for its context menu at `position`, and return it."""
    widget.customContextMenuRequested.emit(position)
    menu = QApplication.active_popup_widget()
    assert isinstance(menu, QMenu)
    return menu


def menu_entries(menu: QMenu) -> list[str]:
    """Return what `menu` holds, naming the separators it uses."""
    return [
        '---' if action.is_separator() else action.text
        for action in menu.actions()]


def press(window: MainWindow, key: Qt.Key) -> None:
    """Press `key` on the window, as the keyboard would."""
    QTest.key_click(window, key)


def digit_event(key: Qt.Key) -> QKeyEvent:
    """Return the key press event a number key would produce."""
    return QKeyEvent(
        QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier,
        chr(key))


def enter(window: MainWindow) -> None:
    """Press Return in the palette field, as the keyboard would."""
    QTest.key_click(window.coords_input.ui.coords_edit, Qt.Key.Key_Return)


def type_coords(window: MainWindow, text: str) -> None:
    """Press a number key to open the palette, type `text`, accept it."""
    press(window, Qt.Key.Key_1)
    window.coords_input.ui.coords_edit.text = text
    window.coords_input.ui.accept_button.click()


def sample_path(tmp_path: Path) -> Path:
    """Write and return a document holding a 100x80 basemap."""
    path = tmp_path / 'sample.rsroi'
    save_document(
        Document(basemaps=[Basemap('map', sample_image(), 'PNG')],
                 active_basemap=0),
        path)
    return path


def capture_dialogs(monkeypatch, *answers: str) -> list[str]:
    """Record the folder every file dialog is asked to open in.

    Each dialog answers with the next of `answers`, and cancels once
    they run out.
    """
    asked: list[str] = []
    remaining = list(answers)

    def record(parent, caption, directory, filters):
        asked.append(directory)
        return (remaining.pop(0) if remaining else '', '')

    monkeypatch.setattr(
        QFileDialog, 'get_open_file_name', staticmethod(record))
    monkeypatch.setattr(
        QFileDialog, 'get_save_file_name', staticmethod(record))
    return asked


def documents_folder() -> str:
    """Return where a document dialog is expected to start.

    Qt names the Documents folder of the user, and a system that has
    none leaves the home folder.
    """
    documents = QStandardPaths.writable_location(
        QStandardPaths.StandardLocation.DocumentsLocation)
    return documents or str(Path.home())


def capture_about(monkeypatch) -> list[str]:
    """Record the text of every about box that is shown."""
    shown: list[str] = []

    def record(parent, title, text):
        shown.append(text)

    monkeypatch.setattr(QMessageBox, 'about', staticmethod(record))
    return shown


def draw_polygon(window: MainWindow) -> None:
    """Draw the triangle ``(0, 0) (10, 0) (10, 10)``."""
    window.ui.action_add_polygon.trigger()
    for text in ('0, 0', '10, 0', '10, 10'):
        type_coords(window, text)
    window.roi_view.finish_requested.emit()


def test_the_editing_area_is_a_graphics_view(window) -> None:
    assert isinstance(window.central_widget(), ROIGraphicsView)


def test_the_zoom_box_sits_at_the_right_of_the_status_bar(window) -> None:
    assert window.find_child(ZoomBox, 'zoom_box') is window.zoom_box
    assert window.zoom_box.parent() is window.ui.statusbar
    # A permanent widget is the one a status message leaves alone.
    window.ui.statusbar.show_message("drawing")
    assert window.zoom_box.visible


def test_the_zoom_box_carries_a_tool_tip(window) -> None:
    assert '149%' in window.zoom_box.tool_tip


def test_the_view_starts_by_fitting_the_window(window) -> None:
    assert window._zoom_fit is ZoomFit.WINDOW
    viewport = window.roi_view.viewport()
    rect = window._scene.scene_rect
    assert window._zoom_ratio == pytest.approx(
        min(viewport.width / rect.width(), viewport.height / rect.height()))
    assert window.zoom_box.line_edit().text == 'Fit Window'


def test_a_typed_percentage_zooms_the_view(window) -> None:
    window.zoom_box.line_edit().text = '149%'
    QTest.key_click(window.zoom_box.line_edit(), Qt.Key.Key_Return)
    assert window._zoom_ratio == pytest.approx(1.49)
    assert window.roi_view.transform().m11() == pytest.approx(1.49)
    assert window.zoom_box.line_edit().text == '149%'


def test_a_fitting_zoom_fills_the_viewport(window) -> None:
    window.zoom_box.fit_requested.emit(ZoomFit.WIDTH)
    viewport = window.roi_view.viewport()
    assert window._zoom_ratio == pytest.approx(
        viewport.width / window._scene.scene_rect.width())


def test_a_fitting_zoom_follows_the_size_of_the_view(window, qapp) -> None:
    window.zoom_box.fit_requested.emit(ZoomFit.WINDOW)
    before = window._zoom_ratio
    window.resize(window.width + 200, window.height + 100)
    qapp.process_events()
    viewport = window.roi_view.viewport()
    assert window._zoom_ratio > before
    assert window._zoom_ratio == pytest.approx(
        viewport.width / window._scene.scene_rect.width())


def test_a_fitting_zoom_survives_a_scene_refresh(window) -> None:
    window.zoom_box.fit_requested.emit(ZoomFit.WIDTH)
    fitted = window._zoom_ratio
    window._refresh_all()
    assert window._zoom_ratio == pytest.approx(fitted)


def test_the_zoom_box_names_the_mode_the_view_follows(window) -> None:
    window.zoom_box.fit_requested.emit(ZoomFit.WIDTH)
    assert window.zoom_box.line_edit().text == 'Fit Width'
    assert window.zoom_box.item_text(window.zoom_box.current_index) == (
        'Fit Width')
    window.zoom_box.fit_requested.emit(ZoomFit.WINDOW)
    assert window.zoom_box.line_edit().text == 'Fit Window'


def test_both_docks_hold_the_expected_view(window) -> None:
    assert window.find_child(QListView, 'basemaps_view') is (
        window.basemaps_view)
    assert window.find_child(QTreeView, 'shapes_view') is window.shapes_view
    docks = window.find_children(QDockWidget)
    assert [dock.window_title for dock in docks] == ["Basemaps", "Shapes"]


def test_the_zoom_box_keeps_its_own_keys_while_drawing(
        window, monkeypatch) -> None:
    """The drawing modes leave the keys of the zoom box alone.

    Nothing holds the focus in a headless run, so the box is named as
    the widget that has it.
    """
    window.ui.action_add_polygon.trigger()
    edit = window.zoom_box.line_edit()
    monkeypatch.setattr(
        QApplication, 'focus_widget', staticmethod(lambda: edit))
    QTest.key_click(edit, Qt.Key.Key_5)
    assert not window.coords_input.visible
    QTest.key_click(edit, Qt.Key.Key_Return)
    assert window._mode is EditMode.CREATE_SHAPE
    assert window.document.shapes == []


def test_both_views_offer_a_context_menu_of_their_own(window) -> None:
    assert window.roi_view.context_menu_policy is (
        Qt.ContextMenuPolicy.CustomContextMenu)
    assert window.shapes_view.context_menu_policy is (
        Qt.ContextMenuPolicy.CustomContextMenu)


def test_the_canvas_menu_of_a_shape_offers_starting_a_vertex(
        window) -> None:
    draw_polygon(window)
    window._select(None, None)
    spot = window.roi_view.map_from_scene(QPointF(5, 0))
    menu = open_menu(window.roi_view, spot)
    assert menu_entries(menu) == [
        '&Remove Shape', 'Shape &Properties...', '&Dump Shape', '---',
        '&Add Vertex...']
    # The entries are the actions of the window, so they arrive with
    # the state the window keeps for them.
    assert window.ui.action_add_vertex in menu.actions()
    assert window.ui.action_add_vertex.enabled
    assert not window.ui.action_remove_vertex.enabled


def test_the_canvas_menu_of_a_vertex_offers_removing_it(window) -> None:
    draw_polygon(window)
    spot = window.roi_view.map_from_scene(QPointF(10, 10))
    menu = open_menu(window.roi_view, spot)
    assert window._selected_vertex == 2
    assert menu_entries(menu) == [
        '&Remove Shape', 'Shape &Properties...', '&Dump Shape', '---',
        '&Add Vertex...', '&Remove Vertex']
    assert window.ui.action_remove_vertex.enabled


def test_the_canvas_offers_the_shapes_to_add_over_nothing(window) -> None:
    draw_polygon(window)
    window._select(None, None)
    spot = window.roi_view.map_from_scene(QPointF(90, 70))
    menu = open_menu(window.roi_view, spot)
    assert menu_entries(menu) == ['&Add Shape']
    assert menu.actions()[0].menu() is window.ui.menu_add_shape
    assert [action.text for action in window.ui.menu_add_shape.actions()] == [
        '&Line', '&Polygon']


def test_the_tree_menu_of_a_shape_holds_the_shape_actions(window) -> None:
    draw_polygon(window)
    window._select(None, None)
    item = window.shapes_view.model().item(0)
    position = window.shapes_view.visual_rect(item.index()).center()
    menu = open_menu(window.shapes_view, position)
    assert menu_entries(menu) == [
        '&Remove Shape', 'Shape &Properties...', '&Dump Shape']
    assert window._selected_shape is window.document.shapes[0]
    assert window._selected_vertex is None


def test_the_tree_menu_of_a_vertex_offers_removing_it(window) -> None:
    draw_polygon(window)
    item = window.shapes_view.model().item(0).child(1, 0)
    position = window.shapes_view.visual_rect(item.index()).center()
    menu = open_menu(window.shapes_view, position)
    assert menu_entries(menu) == [
        '&Remove Shape', 'Shape &Properties...', '&Dump Shape', '---',
        '&Remove Vertex']
    assert window._selected_shape is window.document.shapes[0]
    assert window._selected_vertex == 1


def test_a_right_click_selects_the_shape_it_lands_on(window) -> None:
    draw_polygon(window)
    window._select(None, None)
    spot = window.roi_view.map_from_scene(QPointF(10, 0))
    open_menu(window.roi_view, spot).close()
    assert window._selected_shape is window.document.shapes[0]
    assert window._selected_vertex is None
    # The vertices of a shape answer once it is the selected one.
    open_menu(window.roi_view, spot)
    assert window._selected_vertex == 1


def test_no_menu_is_offered_while_drawing(window) -> None:
    draw_polygon(window)
    window.ui.action_add_polygon.trigger()
    spot = window.roi_view.map_from_scene(QPointF(10, 10))
    window.roi_view.customContextMenuRequested.emit(spot)
    assert QApplication.active_popup_widget() is None
    assert window._mode is EditMode.CREATE_SHAPE


def test_both_docks_are_stacked_on_one_side(window) -> None:
    basemaps_area = window.dock_widget_area(window.dock_basemaps)
    shapes_area = window.dock_widget_area(window.dock_shapes)
    assert basemaps_area == shapes_area
    assert basemaps_area == Qt.DockWidgetArea.LeftDockWidgetArea


def test_the_palette_opens_on_a_digit_press(window) -> None:
    window.ui.action_add_polygon.trigger()
    assert not window.coords_input.visible
    press(window, Qt.Key.Key_3)
    assert window.coords_input.visible
    assert window.coords_input.ui.coords_edit.text == "3"


def test_a_minus_key_opens_the_palette(window) -> None:
    window.ui.action_add_line.trigger()
    press(window, Qt.Key.Key_Minus)
    assert window.coords_input.visible
    assert window.coords_input.ui.coords_edit.text == "-"
    window.coords_input.ui.coords_edit.insert("5, -5")
    window.coords_input.ui.accept_button.click()
    # Taking a coordinate puts the palette away again.
    assert not window.coords_input.visible
    press(window, Qt.Key.Key_5)
    assert window.coords_input.visible
    window.coords_input.ui.coords_edit.text = "5, -2"
    # The second endpoint completes the segment and ends the mode.
    enter(window)
    assert [(p.x(), p.y()) for p in window.document.shapes[0].vertices] == [
        (-5.0, -5.0), (5.0, -2.0)]
    assert window._mode is EditMode.NONE
    assert not window.coords_input.visible


def test_return_finishes_the_shape_once_nothing_is_typed(window) -> None:
    window.ui.action_add_polygon.trigger()
    for text in ('0, 0', '10, 0', '10, 10'):
        press(window, Qt.Key.Key_1)
        window.coords_input.ui.coords_edit.text = text
        enter(window)
    assert window.document.shapes == []
    enter(window)
    assert len(window.document.shapes) == 1
    assert window._mode is EditMode.NONE


def test_the_palette_opens_even_when_the_menu_holds_the_focus(
        window) -> None:
    window.ui.action_add_polygon.trigger()
    menu_bar = window.menu_bar()
    menu_bar.set_focus()
    QTest.key_click(menu_bar, Qt.Key.Key_5)
    assert window.coords_input.visible
    assert window.coords_input.ui.coords_edit.text == "5"


def test_the_palette_is_drawn_over_the_view(window) -> None:
    viewport = window.roi_view.viewport()
    origin = viewport.map_to(window, QPoint(0, 0))
    spot = QPoint(origin.x() + 150, origin.y() + 100)
    before = window.grab().to_image().pixel_color(spot)
    QCursor.set_pos(viewport.map_to_global(QPoint(150, 100)))
    window.ui.action_add_line.trigger()
    press(window, Qt.Key.Key_1)
    after = window.grab().to_image().pixel_color(spot)
    assert window.coords_input.visible
    assert window.coords_input.pos == QPoint(150, 100)
    assert after != before


def test_the_palette_opens_where_the_pointer_is(window) -> None:
    viewport = window.roi_view.viewport()
    target = QPoint(viewport.width // 3, viewport.height // 3)
    QCursor.set_pos(viewport.map_to_global(target))
    window.ui.action_add_line.trigger()
    press(window, Qt.Key.Key_1)
    palette = window.coords_input
    assert palette.visible
    assert palette.parent() is viewport
    assert viewport.rect.contains(palette.geometry)
    assert palette.pos == target


def test_a_digit_opens_the_palette_while_inserting_a_vertex(window) -> None:
    draw_polygon(window)
    window.ui.action_add_vertex.trigger()
    press(window, Qt.Key.Key_5)
    assert window.coords_input.visible
    assert window.coords_input.ui.coords_edit.text == "5"


def test_a_digit_is_not_taken_without_a_mode(window) -> None:
    event = digit_event(Qt.Key.Key_7)
    assert not window.event_filter(window, event)
    assert not window.coords_input.visible


def test_a_digit_is_taken_while_drawing(window) -> None:
    window.ui.action_add_polygon.trigger()
    assert window.event_filter(window, digit_event(Qt.Key.Key_3))
    assert window.coords_input.visible


def test_escape_cancels_the_mode_even_with_the_focus_elsewhere(
        window) -> None:
    window.ui.action_add_line.trigger()
    press(window, Qt.Key.Key_1)
    window.menu_bar().set_focus()
    QTest.key_click(window.menu_bar(), Qt.Key.Key_Escape)
    assert window._mode is EditMode.NONE
    assert not window.coords_input.visible


def test_the_palette_is_packed_away_when_the_mode_ends(window) -> None:
    window.ui.action_add_line.trigger()
    press(window, Qt.Key.Key_1)
    press(window, Qt.Key.Key_Escape)
    assert not window.coords_input.visible
    assert window.coords_input.ui.coords_edit.text == ""


def test_the_title_names_the_file_and_the_application(window) -> None:
    assert window.window_title == "Untitled - ROI Editor"


def test_the_title_follows_a_saved_file(window, tmp_path) -> None:
    assert window.save_path(tmp_path / 'doc.rsroi')
    assert window.window_title == "doc.rsroi - ROI Editor"


def test_the_about_action_is_named_after_the_application(window) -> None:
    assert window.ui.action_about.text == f"&About {APPLICATION_NAME}"


def test_the_about_box_shows_the_application_version(
        window, monkeypatch) -> None:
    QCoreApplication.application_version = '3.2.1'
    body = (
        "<p>ROI Editor, version 3.2.1</p>"
        "<p>A simple ROI editor written in PySide6.</p>")
    shown = capture_about(monkeypatch)
    window.ui.action_about.trigger()
    assert shown == [body]


def test_the_about_box_names_a_version_it_does_not_have(
        window, monkeypatch) -> None:
    QCoreApplication.application_version = ''
    body = (
        "<p>ROI Editor, version (unspecified version)</p>"
        "<p>A simple ROI editor written in PySide6.</p>")
    shown = capture_about(monkeypatch)
    window.ui.action_about.trigger()
    assert shown == [body]


def test_a_missing_distribution_has_no_version(monkeypatch) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, 'version', missing)
    assert installed_version() == ''


def test_an_invalid_coordinate_is_not_accepted(window) -> None:
    window.ui.action_add_line.trigger()
    type_coords(window, 'not a coordinate')
    assert window.coords_input.ui.coords_edit.text == "not a coordinate"
    window.roi_view.finish_requested.emit()
    assert window.document.shapes == []
    assert window._mode is EditMode.NONE


def test_bracketed_coordinates_are_accepted(window) -> None:
    window.ui.action_add_polygon.trigger()
    type_coords(window, '(0, 0)')
    type_coords(window, '[10, 10]')
    type_coords(window, '0 10')
    window.roi_view.finish_requested.emit()
    assert [(p.x(), p.y()) for p in window.document.shapes[0].vertices] == [
        (0.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert window.coords_input.ui.coords_edit.text == ""


def test_the_dump_dialog_offers_the_compact_format(window) -> None:
    draw_polygon(window)
    dialog = DumpShapeDialog(window.document.shapes[0], window)
    assert dialog.ui.format_box.count == 1
    assert dialog.ui.format_box.current_text == "Compact"


def test_a_basemap_is_what_makes_drawing_available(window) -> None:
    assert window.ui.action_add_line.enabled
    assert window.ui.action_add_polygon.enabled
    assert window.ui.action_remove_basemap.enabled
    assert not window.ui.action_remove_shape.enabled
    assert not window.ui.action_add_vertex.enabled
    assert not window.ui.action_dump_shape.enabled


def test_nothing_is_drawn_before_a_basemap_is_shown(blank_window) -> None:
    assert not blank_window.ui.action_add_line.enabled
    assert not blank_window.ui.action_add_polygon.enabled
    assert not blank_window.ui.action_remove_basemap.enabled


def test_a_polygon_is_drawn_from_typed_coordinates(window) -> None:
    window.ui.action_add_polygon.trigger()
    assert window._mode is EditMode.CREATE_SHAPE
    for text in ('10, 10', '20, 10', '20, 20'):
        type_coords(window, text)
    window.roi_view.finish_requested.emit()
    shape = window.document.shapes[0]
    assert shape.name == "Shape 1"
    assert shape.kind is ShapeKind.POLYGON
    assert [(p.x(), p.y()) for p in shape.vertices] == [
        (10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]


def test_the_shape_tree_lists_the_vertices(window) -> None:
    window.ui.action_add_line.trigger()
    for text in ('10, 10', '20, 20'):
        type_coords(window, text)
    model = window.shapes_view.model()
    assert model.row_count() == 1
    assert model.item(0).text() == "Shape 1"
    assert model.item(0).row_count() == 2
    assert model.item(0).child(0, 1).text() == "10"
    assert model.item(0).child(0, 2).text() == "10"


def test_a_line_is_kept_once_both_of_its_ends_are_given(window) -> None:
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(1, 2))
    assert window.document.shapes == []
    window.roi_view.clicked.emit(QPointF(3, 4))
    assert window._mode is EditMode.NONE
    assert [(p.x(), p.y()) for p in window.document.shapes[0].vertices] == [
        (1.0, 2.0), (3.0, 4.0)]


def test_a_line_keeps_no_third_vertex(window) -> None:
    window.ui.action_add_line.trigger()
    for point in (QPointF(1, 2), QPointF(3, 4), QPointF(5, 6)):
        window.roi_view.clicked.emit(point)
    # The last click belongs to the selection again, now that the
    # segment is complete and the mode has ended.
    assert len(window.document.shapes) == 1
    assert [(p.x(), p.y()) for p in window.document.shapes[0].vertices] == [
        (1.0, 2.0), (3.0, 4.0)]


def test_escape_drops_the_shape_being_drawn(window) -> None:
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(1, 2))
    press(window, Qt.Key.Key_Escape)
    assert window.document.shapes == []
    assert window._mode is EditMode.NONE


def test_a_line_with_one_vertex_is_dropped(window) -> None:
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(1, 2))
    window.roi_view.finish_requested.emit()
    assert window.document.shapes == []


def test_a_shape_is_not_started_without_a_basemap(blank_window) -> None:
    # The actions are disabled, so the slots behind them are the
    # backstop a disabled menu entry never reaches.
    blank_window._add_line()
    blank_window._add_polygon()
    assert blank_window._mode is EditMode.NONE
    assert blank_window._draft is None
    assert blank_window.document.shapes == []


def test_removing_the_basemap_gives_up_the_draft(
        window, monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.ui.action_remove_basemap.trigger()
    assert window._mode is EditMode.NONE
    assert window._draft is None
    assert window.document.shapes == []


def test_clearing_the_basemap_selection_keeps_the_image(window) -> None:
    window.ui.action_add_polygon.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.basemaps_view.selection_model().clear()
    # An empty spot of the list is not a request to show nothing.
    assert window.document.active_basemap == 0
    assert window._basemap_index == 0
    assert window.basemaps_view.selection_model().selected_indexes
    assert window._mode is EditMode.CREATE_SHAPE
    press(window, Qt.Key.Key_Escape)


def test_a_typed_coordinate_outside_the_basemap_sets_the_flag(
        window, tmp_path) -> None:
    assert window.load_path(sample_path(tmp_path))
    window.ui.action_add_line.trigger()
    type_coords(window, '10, 10')
    type_coords(window, '500, 10')
    assert window.document.shapes[0].allow_vertices_outside_basemap


def test_a_clicked_point_inside_the_basemap_leaves_the_flag_alone(
        window, tmp_path) -> None:
    assert window.load_path(sample_path(tmp_path))
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.roi_view.clicked.emit(QPointF(20, 20))
    assert not window.document.shapes[0].allow_vertices_outside_basemap


def test_an_inserted_vertex_lands_between_the_nearest_pair(window) -> None:
    draw_polygon(window)
    window.ui.action_add_vertex.trigger()
    window.roi_view.clicked.emit(QPointF(0, 10))
    press(window, Qt.Key.Key_Escape)
    assert [(p.x(), p.y()) for p in window.document.shapes[0].vertices] == [
        (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_a_typed_vertex_lands_between_the_nearest_pair(window) -> None:
    draw_polygon(window)
    window.ui.action_add_vertex.trigger()
    press(window, Qt.Key.Key_0)
    assert window.coords_input.visible
    window.coords_input.ui.coords_edit.text = "0, 10"
    enter(window)
    press(window, Qt.Key.Key_Escape)
    assert [(p.x(), p.y()) for p in window.document.shapes[0].vertices] == [
        (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_dumping_a_shape_copies_the_compact_text(window) -> None:
    draw_polygon(window)
    dialog = DumpShapeDialog(window.document.shapes[0], window)
    assert dialog.ui.output_edit.plain_text == (
        '[[0, 0], [10, 0], [10, 10]]')
    dialog.copy_button.click()
    assert QGuiApplication.clipboard().text() == (
        '[[0, 0], [10, 0], [10, 10]]')


def test_a_saved_document_round_trips_through_the_window(
        window, tmp_path) -> None:
    window.ui.action_add_line.trigger()
    for text in ('10, 10', '20, 20'):
        type_coords(window, text)
    path = tmp_path / 'doc.rsroi'
    assert window.save_path(path)
    assert window.load_path(path)
    assert [(p.x(), p.y()) for p in window.document.shapes[0].vertices] == [
        (10.0, 10.0), (20.0, 20.0)]
    assert window.shapes_view.model().item(0).row_count() == 2


def test_a_basemap_is_listed_and_shown(window, tmp_path) -> None:
    assert window.load_path(sample_path(tmp_path))
    model = window.basemaps_view.model()
    assert model.row_count() == 1
    assert model.item(0).text() == "map"
    assert window.document.active_basemap == 0
    assert window._scene.scene_rect.width() == 100.0


def test_a_basemap_is_loaded_through_the_file_dialog(
        blank_window, monkeypatch, tmp_path) -> None:
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    image.fill(0xff00ff00)
    path = tmp_path / 'map.png'
    assert image.save(str(path), 'PNG')
    monkeypatch.setattr(
        QFileDialog, 'get_open_file_name',
        staticmethod(lambda *args, **kwargs: (str(path), '')))
    blank_window.ui.action_add_basemap.trigger()
    # A basemap is named after the image file, extension and all.
    assert [basemap.name for basemap in blank_window.document.basemaps] == [
        "map.png"]
    assert blank_window.document.active_basemap == 0
    assert blank_window._scene.scene_rect.width() == 20.0
    assert blank_window.basemaps_view.model().item(0).text() == "map.png"
    assert blank_window.ui.action_add_line.enabled


def test_a_second_basemap_of_one_name_is_counted_before_its_extension(
        blank_window, monkeypatch, tmp_path) -> None:
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    path = tmp_path / 'map.png'
    assert image.save(str(path), 'PNG')
    monkeypatch.setattr(
        QFileDialog, 'get_open_file_name',
        staticmethod(lambda *args, **kwargs: (str(path), '')))
    blank_window.ui.action_add_basemap.trigger()
    blank_window.ui.action_add_basemap.trigger()
    assert [basemap.name for basemap in blank_window.document.basemaps] == [
        "map.png", "map 2.png"]


def test_a_file_dialog_starts_in_the_documents_folder(
        blank_window, monkeypatch) -> None:
    asked = capture_dialogs(monkeypatch)
    blank_window.ui.action_open.trigger()
    blank_window.ui.action_add_basemap.trigger()
    assert asked == [documents_folder()] * 2


def test_a_file_dialog_starts_where_the_last_document_was_saved(
        blank_window, monkeypatch, tmp_path) -> None:
    asked = capture_dialogs(monkeypatch)
    assert blank_window.save_path(tmp_path / 'doc.rsroi')
    blank_window.ui.action_open.trigger()
    assert asked == [str(tmp_path)]


def test_a_basemap_dialog_starts_where_the_last_one_came_from(
        window, monkeypatch, tmp_path) -> None:
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    path = tmp_path / 'map.png'
    assert image.save(str(path), 'PNG')
    asked = capture_dialogs(monkeypatch, str(path))
    window.ui.action_add_basemap.trigger()
    window.ui.action_add_basemap.trigger()
    assert asked == [documents_folder(), str(tmp_path)]


def test_a_basemap_leaves_the_document_dialogs_where_they_were(
        window, monkeypatch, tmp_path) -> None:
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    path = tmp_path / 'map.png'
    assert image.save(str(path), 'PNG')
    asked = capture_dialogs(monkeypatch, str(path))
    window.ui.action_add_basemap.trigger()
    window.ui.action_save_as.trigger()
    assert asked == [
        documents_folder(),
        str(Path(documents_folder()) / 'Untitled.rsroi')]


def test_a_document_leaves_the_basemap_dialog_where_it_was(
        window, monkeypatch, tmp_path) -> None:
    asked = capture_dialogs(monkeypatch)
    assert window.save_path(tmp_path / 'doc.rsroi')
    window.ui.action_add_basemap.trigger()
    assert asked == [documents_folder()]


def test_the_save_dialog_offers_the_name_in_the_start_folder(
        window, monkeypatch) -> None:
    asked = capture_dialogs(monkeypatch)
    window.ui.action_save_as.trigger()
    assert asked == [str(Path(documents_folder()) / 'Untitled.rsroi')]


def test_the_documents_folder_falls_back_to_the_home_folder(
        blank_window, monkeypatch) -> None:
    asked = capture_dialogs(monkeypatch)
    monkeypatch.setattr(
        QStandardPaths, 'writable_location',
        staticmethod(lambda location: ''))
    blank_window.ui.action_open.trigger()
    assert asked == [str(Path.home())]


def test_a_basemap_is_removed_after_a_confirmation(
        window, monkeypatch, tmp_path) -> None:
    assert window.load_path(sample_path(tmp_path))
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    window.ui.action_remove_basemap.trigger()
    assert window.document.basemaps == []
    assert window.document.active_basemap == -1


def test_the_shape_properties_are_applied(window, monkeypatch) -> None:
    draw_polygon(window)
    shape = window.document.shapes[0]
    original_init = ShapePropsEditor.__init__

    def prepare(self, edited, parent=None):
        original_init(self, edited, parent)
        self.ui.name_edit.text = "renamed"
        self.ui.allow_vertices_outside_basemap_check_box.checked = True

    monkeypatch.setattr(ShapePropsEditor, '__init__', prepare)
    monkeypatch.setattr(
        ShapePropsEditor, 'exec',
        lambda self: QDialog.DialogCode.Accepted)
    window.ui.action_shape_props.trigger()
    assert shape.name == "renamed"
    assert shape.allow_vertices_outside_basemap
    assert window.shapes_view.model().item(0).text() == "renamed"


def test_a_new_document_replaces_the_current_one(
        window, monkeypatch) -> None:
    draw_polygon(window)
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    window.ui.action_new.trigger()
    assert window.document.shapes == []
    assert window.window_title == "Untitled - ROI Editor"


def test_an_unreadable_document_leaves_the_current_one_alone(
        window, tmp_path) -> None:
    draw_polygon(window)
    broken = tmp_path / 'broken.rsroi'
    broken.write_text('not an archive', encoding='utf-8')
    assert not window.load_path(broken)
    assert len(window.document.shapes) == 1


def test_a_vertex_is_selected_by_clicking_near_it(window) -> None:
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.roi_view.clicked.emit(QPointF(20, 20))
    window.roi_view.clicked.emit(QPointF(21, 20))
    assert window._selected_vertex == 1
    assert window.ui.action_remove_vertex.enabled


def test_a_vertex_cannot_be_added_to_a_line(window) -> None:
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.roi_view.clicked.emit(QPointF(20, 20))
    assert not window.ui.action_add_vertex.enabled


def test_a_vertex_is_still_added_to_a_polygon(window) -> None:
    draw_polygon(window)
    assert window.ui.action_add_vertex.enabled


def test_the_last_basemap_is_kept_while_shapes_are_drawn(
        window, monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    draw_polygon(window)
    # The shapes live in the pixels of the image, so it stays, and the
    # vertex edit it backs keeps working.
    assert not window.ui.action_remove_basemap.enabled
    window._remove_basemap()
    assert len(window.document.basemaps) == 1
    assert len(window.document.shapes) == 1
    assert window.ui.action_add_vertex.enabled


def test_a_basemap_without_shapes_can_go(window, monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    assert window.ui.action_remove_basemap.enabled
    window.ui.action_remove_basemap.trigger()
    assert window.document.basemaps == []


def test_a_spare_basemap_can_go_while_shapes_stay(window, monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    draw_polygon(window)
    show_basemap(window)
    assert window.ui.action_remove_basemap.enabled
    window.ui.action_remove_basemap.trigger()
    assert len(window.document.basemaps) == 1
    assert len(window.document.shapes) == 1
    assert not window.ui.action_remove_basemap.enabled


def test_removing_a_vertex_leaves_the_rest(window) -> None:
    draw_polygon(window)
    window.roi_view.clicked.emit(QPointF(10, 0))
    window.ui.action_remove_vertex.trigger()
    assert [(p.x(), p.y()) for p in window.document.shapes[0].vertices] == [
        (0.0, 0.0), (10.0, 10.0)]


def test_a_new_shape_gets_a_free_name(window) -> None:
    for _ in range(2):
        window.ui.action_add_line.trigger()
        for text in ('0, 0', '1, 1'):
            type_coords(window, text)
    assert [shape.name for shape in window.document.shapes] == [
        "Shape 1", "Shape 2"]
