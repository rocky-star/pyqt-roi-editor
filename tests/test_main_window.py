"""Tests for the main window, the editing area and the docks.

The tests drive the window through its actions and through real, if
offscreen, Qt events, and they check what a user could see: the
document, the models, the titles, the messages and the enabled
actions.  The window is only reached into where nothing else exposes
what a test needs, such as giving it a basemap to draw on.
"""

import importlib.metadata
from pathlib import Path

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QSize,
    QStandardPaths,
    Qt,
)
from PySide6.QtGui import (
    QCursor,
    QEnterEvent,
    QGuiApplication,
    QImage,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QInputDialog,
    QMenu,
    QMessageBox,
)

from pyqt_roi_editor.document import Basemap, ShapeKind
from pyqt_roi_editor.dump_shape_dialog import (
    DumpFormat,
    DumpShapeDialog,
    format_compact,
)
from pyqt_roi_editor.helpers import format_number
from pyqt_roi_editor.main import (
    APPLICATION_NAME,
    MainWindow,
    installed_version,
)
from pyqt_roi_editor.roi_graphics_view import ROIGraphicsView, Tool
from pyqt_roi_editor.shape_props_editor import ShapePropsEditor
from pyqt_roi_editor.storage import load_document
from pyqt_roi_editor.zoom_box import ZoomFit

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


def press(window: MainWindow, key: Qt.Key) -> None:
    """Press `key` on the window, as the keyboard would."""
    QTest.key_click(window, key)


def enter(window: MainWindow) -> None:
    """Press Return in the palette field, as the keyboard would."""
    QTest.key_click(window.coords_input.ui.coords_edit, Qt.Key.Key_Return)


def type_coords(window: MainWindow, text: str) -> None:
    """Press a digit to open the palette, type `text`, accept it."""
    press(window, Qt.Key.Key_1)
    window.coords_input.ui.coords_edit.text = text
    window.coords_input.ui.accept_button.click()


def set_zoom(window: MainWindow, percent: int) -> None:
    """Ask the zoom box for `percent` of the natural size."""
    window.zoom_box.line_edit().text = f'{percent}%'
    QTest.key_click(window.zoom_box.line_edit(), Qt.Key.Key_Return)


def draw_polygon(window: MainWindow) -> None:
    """Draw the triangle ``(0, 0) (10, 0) (10, 10)``."""
    window.ui.action_add_polygon.trigger()
    for text in ('0, 0', '10, 0', '10, 10'):
        type_coords(window, text)
    window.roi_view.finish_requested.emit()


def draw_square(window: MainWindow) -> None:
    """Draw the square ``(0, 0) (40, 0) (40, 40) (0, 40)``.

    The middle of the square is further from every corner of it than
    a press has to be to grab a vertex, so a press there selects the
    shape itself.
    """
    window.ui.action_add_polygon.trigger()
    for text in ('0, 0', '40, 0', '40, 40', '0, 40'):
        type_coords(window, text)
    window.roi_view.finish_requested.emit()


def vertices(
        window: MainWindow, index: int = 0) -> list[tuple[float, float]]:
    """Return the vertices of the shape at `index`, as number pairs."""
    return [
        (vertex.x(), vertex.y())
        for vertex in window.document.shapes[index].vertices]


def shape_items(window: MainWindow) -> list[QGraphicsPathItem]:
    """Return the items the scene draws the shapes with."""
    return [
        item for item in window.roi_view.scene().items()
        if isinstance(item, QGraphicsPathItem)]


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


def capture_messages(monkeypatch, *answers) -> list[tuple[str, str]]:
    """Record the title and text of every message box, agreeing to it.

    Each box is answered with the next of `answers`, and with Yes once
    they run out.
    """
    shown: list[tuple[str, str]] = []
    remaining = list(answers)

    def record(parent, title, text, *args, **kwargs):
        shown.append((title, text))
        return (remaining.pop(0) if remaining
                else QMessageBox.StandardButton.Yes)

    for name in ('critical', 'information', 'question'):
        monkeypatch.setattr(QMessageBox, name, staticmethod(record))
    return shown


# The window and its tools


def test_the_window_shows_the_editing_area_and_the_docks(window) -> None:
    assert isinstance(window.central_widget(), ROIGraphicsView)
    assert window.dock_basemaps.widget() is window.basemaps_view
    assert window.dock_shapes.widget() is window.shapes_view
    assert len(window.find_children(QDockWidget)) == 2
    areas = {
        window.dock_widget_area(window.dock_basemaps),
        window.dock_widget_area(window.dock_shapes)}
    assert areas == {Qt.DockWidgetArea.LeftDockWidgetArea}
    assert window.zoom_box.parent() is window.ui.statusbar


def test_the_toolbox_chooses_the_tool_and_the_cursor(window) -> None:
    group = window.tool_group
    assert group.is_exclusive()
    assert window.ui.action_selection_tool.checked
    assert group.actions() == [
        window.ui.action_selection_tool,
        window.ui.action_hand_tool,
        window.ui.action_zoom_tool]
    window.ui.action_hand_tool.trigger()
    assert window.ui.action_hand_tool.checked
    assert not window.ui.action_selection_tool.checked
    assert window.roi_view.tool is Tool.HAND
    assert window.roi_view.cursor.shape() is Qt.CursorShape.OpenHandCursor
    window.ui.action_zoom_tool.trigger()
    assert window.roi_view.tool is Tool.ZOOM
    assert window.roi_view.cursor.shape() is Qt.CursorShape.SizeHorCursor
    window.ui.action_selection_tool.trigger()
    assert window.roi_view.tool is Tool.SELECTION
    assert window.roi_view.cursor.shape() is Qt.CursorShape.ArrowCursor


def test_the_status_bar_explains_the_tool_in_force(window) -> None:
    status = window.ui.statusbar
    view = window.roi_view
    spot = QPointF(5, 5)
    assert status.current_message() == ""
    QApplication.send_event(view, QEnterEvent(spot, spot, spot))
    selection = status.current_message()
    assert selection != ""
    window.ui.action_hand_tool.trigger()
    hand = status.current_message()
    assert hand not in ("", selection)
    window.ui.action_zoom_tool.trigger()
    zoom = status.current_message()
    assert zoom not in ("", selection, hand)
    window.ui.action_selection_tool.trigger()
    assert status.current_message() == selection
    # The status bar is left to the document once the pointer leaves.
    QApplication.send_event(view, QEvent(QEvent.Type.Leave))
    assert status.current_message() == ""
    window.ui.action_zoom_tool.trigger()
    assert status.current_message() == ""
    QApplication.send_event(view, QEnterEvent(spot, spot, spot))
    assert status.current_message() == zoom


def test_a_message_gives_way_to_the_hint(
        window, monkeypatch, tmp_path) -> None:
    """A message about the document yields to the canvas hint again."""
    monkeypatch.setattr('pyqt_roi_editor.main._HINT_TIMEOUT', 10)
    window.roi_view.pointer_entered.emit()
    assert window.save_path(tmp_path / 'doc.rsroi')
    assert 'doc.rsroi' in window.ui.statusbar.current_message()
    QTest.q_wait(50)
    hint = window.ui.statusbar.current_message()
    assert hint != "" and 'doc.rsroi' not in hint
    # Off the canvas there is no hint to give way to.
    window.roi_view.pointer_left.emit()
    assert window.save_path(tmp_path / 'other.rsroi')
    assert 'other.rsroi' in window.ui.statusbar.current_message()
    QTest.q_wait(50)
    assert window.ui.statusbar.current_message() == ""


# Moving and zooming the view


def test_the_view_is_moved_by_the_hand_tool_and_the_third_button(
        window) -> None:
    draw_square(window)
    set_zoom(window, 800)
    view = window.roi_view
    bar = view.horizontal_scroll_bar()
    # A left drag of the hand tool moves the view, not the shape.
    window.ui.action_hand_tool.trigger()
    before = bar.value
    start = view.map_from_scene(QPointF(30, 30))
    QTest.mouse_press(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouse_move(view.viewport(), start + QPoint(40, 0))
    QTest.mouse_release(
        view.viewport(), Qt.MouseButton.LeftButton,
        pos=start + QPoint(40, 0))
    assert bar.value == before - 40
    # The third button lends the hand tool wherever the toolbox stands.
    window.ui.action_zoom_tool.trigger()
    before = bar.value
    start = view.viewport().rect.center()
    QTest.mouse_press(view.viewport(), Qt.MouseButton.MiddleButton, pos=start)
    assert window.ui.action_hand_tool.checked
    assert not window.ui.action_zoom_tool.checked
    QTest.mouse_move(view.viewport(), start - QPoint(30, 0))
    QTest.mouse_release(
        view.viewport(), Qt.MouseButton.MiddleButton,
        pos=start - QPoint(30, 0))
    assert bar.value == before + 30
    assert window.ui.action_zoom_tool.checked
    assert not window.ui.action_hand_tool.checked
    assert vertices(window) == [
        (0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]


def test_the_third_button_moves_the_view_while_drawing(window) -> None:
    """A shape is drawn over the part of the image the view shows."""
    set_zoom(window, 800)
    window.ui.action_add_polygon.trigger()
    window.roi_view.clicked.emit(QPointF(20, 20))
    view = window.roi_view
    bar = view.horizontal_scroll_bar()
    before = bar.value
    start = view.viewport().rect.center()
    QTest.mouse_press(view.viewport(), Qt.MouseButton.MiddleButton, pos=start)
    assert not window.ui.action_hand_tool.checked
    QTest.mouse_move(view.viewport(), start + QPoint(25, 0))
    QTest.mouse_release(
        view.viewport(), Qt.MouseButton.MiddleButton,
        pos=start + QPoint(25, 0))
    assert bar.value == before - 25
    window.roi_view.clicked.emit(QPointF(30, 30))
    window.roi_view.clicked.emit(QPointF(40, 10))
    window.roi_view.finish_requested.emit()
    assert vertices(window) == [(20.0, 20.0), (30.0, 30.0), (40.0, 10.0)]


def test_the_zoom_tool_scales_the_view_with_a_drag(window) -> None:
    window.ui.action_zoom_tool.trigger()
    set_zoom(window, 100)
    view = window.roi_view
    start = view.viewport().rect.center()
    QTest.mouse_press(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouse_move(view.viewport(), start + QPoint(120, 0))
    QTest.mouse_release(
        view.viewport(), Qt.MouseButton.LeftButton,
        pos=start + QPoint(120, 0))
    assert view.transform().m11() == pytest.approx(2.0)
    assert window.zoom_box.item_data(window.zoom_box.current_index) == (
        pytest.approx(2.0))
    QTest.mouse_press(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouse_move(view.viewport(), start - QPoint(120, 0))
    QTest.mouse_release(
        view.viewport(), Qt.MouseButton.LeftButton,
        pos=start - QPoint(120, 0))
    assert view.transform().m11() == pytest.approx(1.0)


def test_the_zoom_tool_frames_an_area_with_the_secondary_button(
        window) -> None:
    draw_square(window)
    window.ui.action_zoom_tool.trigger()
    set_zoom(window, 200)
    view = window.roi_view
    area = QRect(
        view.viewport().rect.center() - QPoint(50, 50), QSize(100, 100))
    QTest.mouse_press(
        view.viewport(), Qt.MouseButton.RightButton, pos=area.top_left())
    QTest.mouse_move(view.viewport(), area.bottom_right())
    QTest.mouse_release(
        view.viewport(), Qt.MouseButton.RightButton,
        pos=area.bottom_right())
    # The hundred pixels framed cover fifty of the scene at this zoom.
    viewport = view.viewport()
    expected = min(viewport.width / 50.0, viewport.height / 50.0)
    assert view.transform().m11() == pytest.approx(expected)
    # The box is back at a ratio rather than following a mode.
    shown = window.zoom_box.item_data(window.zoom_box.current_index)
    assert not isinstance(shown, ZoomFit)
    # A frame too small to mean anything leaves the view alone.
    before = view.transform().m11()
    start = viewport.rect.center()
    QTest.mouse_press(
        view.viewport(), Qt.MouseButton.RightButton, pos=start)
    QTest.mouse_release(
        view.viewport(), Qt.MouseButton.RightButton,
        pos=start + QPoint(4, 4))
    assert view.transform().m11() == pytest.approx(before)


def test_a_fitting_zoom_follows_the_view(window, qapp) -> None:
    viewport = window.roi_view.viewport()
    rect = window.roi_view.scene().scene_rect
    assert window.zoom_box.item_data(window.zoom_box.current_index) is (
        ZoomFit.WINDOW)
    assert window.roi_view.transform().m11() == pytest.approx(
        min(viewport.width / rect.width(), viewport.height / rect.height()))
    window.zoom_box.fit_requested.emit(ZoomFit.WIDTH)
    assert window.zoom_box.item_data(window.zoom_box.current_index) is (
        ZoomFit.WIDTH)
    fitted = window.roi_view.transform().m11()
    window.resize(window.width + 200, window.height + 100)
    qapp.process_events()
    viewport = window.roi_view.viewport()
    assert window.roi_view.transform().m11() > fitted
    assert window.roi_view.transform().m11() == pytest.approx(
        viewport.width / rect.width())
    # A redrawn scene keeps the zoom the view was asked for.
    window.ui.action_add_line.trigger()
    for text in ('0, 0', '10, 10'):
        type_coords(window, text)
    assert window.roi_view.transform().m11() == pytest.approx(
        viewport.width / rect.width())


def test_a_typed_percentage_zooms_the_view(window) -> None:
    set_zoom(window, 149)
    assert window.roi_view.transform().m11() == pytest.approx(1.49)


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
    assert window.document.shapes == []
    assert not window.ui.action_add_line.enabled


# Context menus


def test_no_menu_is_offered_without_the_selection_tool(window) -> None:
    draw_polygon(window)
    spot = window.roi_view.map_from_scene(QPointF(5, 0))
    for action in (window.ui.action_hand_tool, window.ui.action_zoom_tool):
        action.trigger()
        window.roi_view.customContextMenuRequested.emit(spot)
        assert QApplication.active_popup_widget() is None
    window.ui.action_selection_tool.trigger()
    menu = open_menu(window.roi_view, spot)
    assert window.ui.action_remove_shape in menu.actions()
    menu.close()
    # A shape being drawn has no menu either.
    window.ui.action_add_polygon.trigger()
    window.roi_view.customContextMenuRequested.emit(spot)
    assert QApplication.active_popup_widget() is None
    press(window, Qt.Key.Key_Escape)


def test_the_canvas_menu_of_a_shape_offers_the_shape_actions(
        window) -> None:
    draw_polygon(window)
    window.roi_view.clicked.emit(QPointF(90, 70))
    spot = window.roi_view.map_from_scene(QPointF(5, 0))
    menu = open_menu(window.roi_view, spot)
    assert window.ui.action_remove_shape in menu.actions()
    assert window.ui.action_shape_props in menu.actions()
    assert window.ui.action_dump_shape in menu.actions()
    assert window.ui.action_add_vertex in menu.actions()
    assert window.ui.action_add_vertex.enabled
    assert not window.ui.action_remove_vertex.enabled
    menu.close()


def test_the_canvas_menu_of_a_vertex_offers_removing_it(window) -> None:
    draw_polygon(window)
    spot = window.roi_view.map_from_scene(QPointF(10, 10))
    menu = open_menu(window.roi_view, spot)
    assert window.ui.action_remove_vertex in menu.actions()
    assert window.ui.action_remove_vertex.enabled
    indexes = window.shapes_view.selection_model().selected_indexes
    assert {index.row() for index in indexes} == {2}
    menu.close()


def test_the_canvas_offers_the_shapes_to_add_over_nothing(window) -> None:
    draw_polygon(window)
    spot = window.roi_view.map_from_scene(QPointF(90, 70))
    window.roi_view.clicked.emit(QPointF(90, 70))
    menu = open_menu(window.roi_view, spot)
    assert len(menu.actions()) == 1
    submenu = menu.actions()[0].menu()
    assert submenu is window.ui.menu_add_shape
    assert window.ui.action_add_line in submenu.actions()
    assert window.ui.action_add_polygon in submenu.actions()
    menu.close()


def test_a_secondary_click_selects_what_is_under_it(window) -> None:
    draw_polygon(window)
    window.roi_view.clicked.emit(QPointF(90, 70))
    spot = window.roi_view.map_from_scene(QPointF(10, 0))
    open_menu(window.roi_view, spot).close()
    assert window.ui.action_remove_shape.enabled
    assert not window.ui.action_remove_vertex.enabled
    # The vertices of a shape answer once it is the selected one.
    open_menu(window.roi_view, spot)
    assert window.ui.action_remove_vertex.enabled


def test_the_tree_menu_offers_what_fits_the_item(window) -> None:
    draw_polygon(window)
    window.roi_view.clicked.emit(QPointF(90, 70))
    item = window.shapes_view.model().item(0)
    position = window.shapes_view.visual_rect(item.index()).center()
    menu = open_menu(window.shapes_view, position)
    assert window.ui.action_remove_shape in menu.actions()
    assert window.ui.action_remove_shape.enabled
    assert window.ui.action_add_vertex not in menu.actions()
    menu.close()
    item = window.shapes_view.model().item(0).child(1, 0)
    position = window.shapes_view.visual_rect(item.index()).center()
    menu = open_menu(window.shapes_view, position)
    assert window.ui.action_remove_vertex in menu.actions()
    assert window.ui.action_remove_vertex.enabled
    menu.close()


# Typing coordinates


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
    assert palette.ui.coords_edit.text == "1"
    press(window, Qt.Key.Key_Escape)


def test_the_palette_opens_even_when_the_menu_holds_the_focus(
        window) -> None:
    window.ui.action_add_polygon.trigger()
    menu_bar = window.menu_bar()
    menu_bar.set_focus()
    QTest.key_click(menu_bar, Qt.Key.Key_5)
    assert window.coords_input.visible
    assert window.coords_input.ui.coords_edit.text == "5"


def test_a_line_is_drawn_from_typed_coordinates(window) -> None:
    window.ui.action_add_line.trigger()
    press(window, Qt.Key.Key_Minus)
    assert window.coords_input.ui.coords_edit.text == "-"
    window.coords_input.ui.coords_edit.insert("5, -5")
    window.coords_input.ui.accept_button.click()
    # Taking a coordinate puts the palette away again.
    assert not window.coords_input.visible
    press(window, Qt.Key.Key_5)
    window.coords_input.ui.coords_edit.text = "5, -2"
    # The second endpoint completes the segment and ends the mode.
    enter(window)
    assert vertices(window) == [(-5.0, -5.0), (5.0, -2.0)]
    assert window.ui.action_add_line.enabled
    assert not window.coords_input.visible


def test_a_coordinate_may_be_typed_with_either_separator(window) -> None:
    window.ui.action_add_polygon.trigger()
    for key in (Qt.Key.Key_1, Qt.Key.Key_0, Qt.Key.Key_Comma,
                Qt.Key.Key_2, Qt.Key.Key_0):
        press(window, key)
    assert window.coords_input.ui.coords_edit.text == "10,20"
    press(window, Qt.Key.Key_Return)
    for key in (Qt.Key.Key_2, Qt.Key.Key_0, Qt.Key.Key_Space,
                Qt.Key.Key_3, Qt.Key.Key_0):
        press(window, key)
    assert window.coords_input.ui.coords_edit.text == "20 30"
    press(window, Qt.Key.Key_Return)
    type_coords(window, '0, 0')
    window.roi_view.finish_requested.emit()
    assert vertices(window) == [(10.0, 20.0), (20.0, 30.0), (0.0, 0.0)]


def test_return_finishes_the_shape_once_nothing_is_typed(window) -> None:
    window.ui.action_add_polygon.trigger()
    for text in ('0, 0', '10, 0', '10, 10'):
        press(window, Qt.Key.Key_1)
        window.coords_input.ui.coords_edit.text = text
        enter(window)
    assert window.document.shapes == []
    enter(window)
    assert len(window.document.shapes) == 1
    assert not window.coords_input.visible


def test_a_typed_coordinate_must_parse_and_be_whole(window) -> None:
    window.ui.action_add_line.trigger()
    type_coords(window, 'not a coordinate')
    assert window.coords_input.text == "not a coordinate"
    assert window.coords_input.visible
    type_coords(window, '10.5, 10')
    assert window.coords_input.text == '10.5, 10'
    # A whole pair is taken, and the segment is kept with it.
    type_coords(window, '10, 10')
    assert not window.coords_input.visible
    window.roi_view.clicked.emit(QPointF(20, 20))
    assert vertices(window) == [(10.0, 10.0), (20.0, 20.0)]


def test_escape_cancels_the_mode_and_drops_the_draft(window) -> None:
    # A digit outside a drawing mode opens nothing.
    press(window, Qt.Key.Key_7)
    assert not window.coords_input.visible
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(1, 2))
    press(window, Qt.Key.Key_1)
    press(window, Qt.Key.Key_Escape)
    assert not window.coords_input.visible
    assert window.document.shapes == []
    assert window.ui.action_add_line.enabled
    # The same key works while something else holds the focus.
    window.ui.action_add_line.trigger()
    press(window, Qt.Key.Key_1)
    window.menu_bar().set_focus()
    QTest.key_click(window.menu_bar(), Qt.Key.Key_Escape)
    assert not window.coords_input.visible
    assert window.ui.action_add_line.enabled


# Drawing shapes


def test_a_polygon_is_drawn_from_typed_coordinates(window) -> None:
    window.ui.action_add_polygon.trigger()
    assert not window.ui.action_add_line.enabled
    for text in ('10, 10', '20, 10', '20, 20'):
        type_coords(window, text)
    window.roi_view.finish_requested.emit()
    shape = window.document.shapes[0]
    assert shape.name == "Shape 1"
    assert shape.kind is ShapeKind.POLYGON
    assert vertices(window) == [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]
    # The tree follows the shape it lists.
    model = window.shapes_view.model()
    top = model.item(0)
    assert top.text() == shape.name
    assert top.row_count() == 3
    names = [top.child(row, 0).text() for row in range(3)]
    assert all(names) and len(set(names)) == 3
    assert [top.child(row, 1).text() for row in range(3)] == [
        format_number(vertex.x())
        for vertex in window.document.shapes[0].vertices]


def test_a_line_lives_by_its_two_ends(window) -> None:
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(1, 2))
    window.roi_view.finish_requested.emit()
    assert window.document.shapes == []
    # A clicked vertex lands on the pixel it is nearest to.
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(10.4, 10.6))
    window.roi_view.clicked.emit(QPointF(20.4, 20.6))
    assert vertices(window) == [(10.0, 11.0), (20.0, 21.0)]
    # A third click selects rather than extends the segment.
    window.roi_view.clicked.emit(QPointF(5, 6))
    assert len(window.document.shapes) == 1
    assert vertices(window) == [(10.0, 11.0), (20.0, 21.0)]


def test_a_new_shape_gets_a_name_no_other_shape_uses(window) -> None:
    draw_polygon(window)
    window.document.shapes[0].name = "Shape 2"
    window.ui.action_add_line.trigger()
    for text in ('0, 0', '1, 1'):
        type_coords(window, text)
    assert [shape.name for shape in window.document.shapes] == [
        "Shape 2", "Shape 3"]


def test_a_typed_vertex_is_inserted_between_its_neighbours(window) -> None:
    draw_polygon(window)
    window.ui.action_add_vertex.trigger()
    press(window, Qt.Key.Key_0)
    assert window.coords_input.visible
    window.coords_input.ui.coords_edit.text = "0, 10"
    enter(window)
    press(window, Qt.Key.Key_Escape)
    assert vertices(window) == [
        (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_a_shape_is_not_started_without_a_basemap(blank_window) -> None:
    # The actions are disabled, so the slots behind them are the
    # backstop a disabled menu entry never reaches.
    blank_window._add_line()
    blank_window._add_polygon()
    assert blank_window.document.shapes == []
    show_basemap(blank_window)
    press(blank_window, Qt.Key.Key_1)
    assert not blank_window.coords_input.visible


def test_nothing_is_drawn_before_a_basemap_is_shown(blank_window) -> None:
    assert not blank_window.ui.action_add_line.enabled
    assert not blank_window.ui.action_add_polygon.enabled
    assert not blank_window.ui.action_remove_basemap.enabled


def test_drawing_is_offered_only_with_a_basemap(window) -> None:
    assert window.ui.action_add_line.enabled
    assert window.ui.action_add_polygon.enabled
    assert window.ui.action_remove_basemap.enabled
    assert not window.ui.action_remove_shape.enabled
    assert not window.ui.action_add_vertex.enabled
    assert not window.ui.action_dump_shape.enabled
    # Only a polygon takes another vertex.
    draw_square(window)
    assert window.ui.action_add_vertex.enabled
    window.ui.action_add_line.trigger()
    for text in ('0, 0', '1, 1'):
        type_coords(window, text)
    assert not window.ui.action_add_vertex.enabled


# How the shapes are drawn


def test_a_selected_polygon_is_filled_and_a_line_is_not(window) -> None:
    draw_square(window)
    item = shape_items(window)[0]
    fill = item.brush().color()
    assert item.brush().style() is not Qt.BrushStyle.NoBrush
    # Translucent, so that the pixels it covers stay readable.
    assert 0 < fill.alpha() < 255
    assert fill.get_rgb()[:3] == item.pen().color().get_rgb()[:3]
    # An unselected polygon is left unfilled.
    window.roi_view.clicked.emit(QPointF(80, 70))
    assert shape_items(window)[0].brush().style() is Qt.BrushStyle.NoBrush
    # So is a selected line, which closes over no area.
    window.ui.action_add_line.trigger()
    for text in ('10, 10', '20, 20'):
        type_coords(window, text)
    assert window.ui.action_remove_shape.enabled
    assert all(
        item.brush().style() is Qt.BrushStyle.NoBrush
        for item in shape_items(window))


def test_shapes_and_handles_keep_their_screen_size(window) -> None:
    """A zoom shows more of the image, not fatter shapes or handles."""
    draw_square(window)
    scene = window.roi_view.scene()
    items = shape_items(window)
    assert items
    assert all(item.pen().is_cosmetic() for item in items)
    handles = [
        item for item in scene.items()
        if isinstance(item, QGraphicsEllipseItem)]
    assert sorted(
        (handle.pos().x(), handle.pos().y()) for handle in handles
    ) == sorted(vertices(window))
    assert all(
        handle.flags()
        & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
        for handle in handles)


# Basemaps and documents


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
    blank_window.ui.action_add_basemap.trigger()
    # A basemap is named after the image file, extension and all, and
    # a second one of the name is counted before its extension.
    assert [basemap.name for basemap in blank_window.document.basemaps] == [
        "map.png", "map 2.png"]
    assert blank_window.document.active_basemap == 1
    assert blank_window.roi_view.scene().scene_rect.width() == 20.0
    assert blank_window.basemaps_view.model().item(0).text() == "map.png"
    assert blank_window.ui.action_add_line.enabled


def test_a_basemap_may_go_unless_it_backs_shapes(window, monkeypatch) -> None:
    capture_messages(monkeypatch)
    # An image with nothing drawn on it may go.
    window.ui.action_remove_basemap.trigger()
    assert window.document.basemaps == []
    assert window.document.active_basemap == -1
    # The one the shapes live in stays.
    show_basemap(window)
    draw_polygon(window)
    assert not window.ui.action_remove_basemap.enabled
    # A spare image may go, and the shapes stay.
    show_basemap(window)
    assert window.ui.action_remove_basemap.enabled
    window.ui.action_remove_basemap.trigger()
    assert len(window.document.basemaps) == 1
    assert len(window.document.shapes) == 1
    assert not window.ui.action_remove_basemap.enabled


def test_removing_the_basemap_gives_up_the_draft(
        window, monkeypatch) -> None:
    capture_messages(monkeypatch)
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.ui.action_remove_basemap.trigger()
    assert window.document.basemaps == []
    assert window.document.shapes == []
    # The window is back at rest, so a digit opens nothing.
    show_basemap(window)
    press(window, Qt.Key.Key_1)
    assert not window.coords_input.visible
    assert window.ui.action_add_line.enabled


def test_clearing_the_basemap_selection_keeps_the_image(window) -> None:
    window.ui.action_add_polygon.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.basemaps_view.selection_model().clear()
    # An empty spot of the list is not a request to show nothing.
    assert window.document.active_basemap == 0
    assert window.basemaps_view.selection_model().selected_indexes
    assert not window.ui.action_add_line.enabled
    press(window, Qt.Key.Key_Escape)


def test_a_typed_coordinate_outside_the_basemap_sets_the_flag(
        window) -> None:
    window.ui.action_add_line.trigger()
    type_coords(window, '10, 10')
    type_coords(window, '500, 10')
    assert window.document.shapes[0].allow_vertices_outside_basemap
    # A point clicked inside leaves the flag alone.
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.roi_view.clicked.emit(QPointF(20, 20))
    assert not window.document.shapes[1].allow_vertices_outside_basemap


def test_a_basemap_is_renamed_through_the_dialog(window, monkeypatch) -> None:
    asked: list[str] = []

    def answer(parent, caption, label, mode, text):
        asked.append(text)
        return ('Renamed', True)

    monkeypatch.setattr(QInputDialog, 'get_text', staticmethod(answer))
    window.ui.action_rename_basemap.trigger()
    assert asked == ["map"]
    assert window.document.basemaps[0].name == "Renamed"
    assert window.basemaps_view.model().item(0).text() == "Renamed"
    # An empty name is refused.
    monkeypatch.setattr(
        QInputDialog, 'get_text', staticmethod(lambda *args: ('', True)))
    window.ui.action_rename_basemap.trigger()
    assert window.document.basemaps[0].name == "Renamed"


def test_a_saved_document_round_trips_through_the_window(
        window, tmp_path) -> None:
    assert APPLICATION_NAME in window.window_title
    window.ui.action_add_line.trigger()
    for text in ('10, 10', '20, 20'):
        type_coords(window, text)
    path = tmp_path / 'doc.rsroi'
    assert window.save_path(path)
    # The title names the file by its stem, without the extension.
    title = window.window_title
    assert title.startswith('doc') and APPLICATION_NAME in title
    assert '.rsroi' not in title
    assert window.load_path(path)
    assert vertices(window) == [(10.0, 10.0), (20.0, 20.0)]
    assert window.shapes_view.model().item(0).row_count() == 2
    assert window.basemaps_view.model().item(0).text() == "map"
    assert window.roi_view.scene().scene_rect.width() == 100.0


def test_a_failed_operation_names_what_failed(
        window, monkeypatch, tmp_path) -> None:
    draw_polygon(window)
    broken = tmp_path / 'broken.rsroi'
    broken.write_text('not an archive', encoding='utf-8')
    shown = capture_messages(monkeypatch)
    # A file that cannot be read leaves the document alone.
    assert not window.load_path(broken)
    assert len(window.document.shapes) == 1
    assert shown[0][0] == APPLICATION_NAME
    assert 'broken.rsroi' in shown[0][1]
    # A save that fails speaks under the document it belongs to.
    assert not window.save_path(tmp_path / 'gone' / 'plot.rsroi')
    assert shown[1][0] == "Untitled"
    assert 'plot.rsroi' in shown[1][1]
    assert window.save_path(tmp_path / 'plot.rsroi')
    assert not window.save_path(tmp_path / 'gone' / 'other.rsroi')
    assert shown[2][0] == "plot"
    assert 'other.rsroi' in shown[2][1]
    # An image that cannot be loaded names its file too.
    image = tmp_path / 'not-an-image.png'
    image.write_text('not an image', encoding='utf-8')
    monkeypatch.setattr(
        QFileDialog, 'get_open_file_name',
        staticmethod(lambda *args, **kwargs: (str(image), '')))
    window.ui.action_add_basemap.trigger()
    assert shown[3][0] == "plot"
    assert 'not-an-image.png' in shown[3][1]


def test_a_new_document_replaces_the_current_one(
        window, monkeypatch, tmp_path) -> None:
    draw_polygon(window)
    window.ui.action_hand_tool.trigger()
    shown = capture_messages(monkeypatch)
    window.ui.action_new.trigger()
    assert window.document.basemaps == []
    assert window.document.shapes == []
    assert APPLICATION_NAME in window.window_title
    assert window.ui.action_hand_tool.checked
    assert window.roi_view.tool is Tool.HAND
    # A confirmation speaks under the document it discards.
    show_basemap(window)
    draw_polygon(window)
    assert window.save_path(tmp_path / 'plot.rsroi')
    window.ui.action_new.trigger()
    assert 'plot' not in window.window_title
    assert [title for title, _text in shown] == ["Untitled", "plot"]


def test_removing_a_shape_asks_first(window, monkeypatch, tmp_path) -> None:
    draw_polygon(window)
    assert window.save_path(tmp_path / 'plot.rsroi')
    shown = capture_messages(monkeypatch, QMessageBox.StandardButton.No)
    window.ui.action_remove_shape.trigger()
    assert len(window.document.shapes) == 1
    assert shown[0][0] == "plot"
    assert window.document.shapes[0].name in shown[0][1]
    capture_messages(monkeypatch)
    window.ui.action_remove_shape.trigger()
    assert window.document.shapes == []


def test_file_dialogs_start_in_the_documents_folder(
        blank_window, monkeypatch) -> None:
    asked = capture_dialogs(monkeypatch)
    blank_window.ui.action_open.trigger()
    blank_window.ui.action_add_basemap.trigger()
    assert asked == [documents_folder()] * 2
    # The save dialog offers the name of the untitled document.
    blank_window.ui.action_save_as.trigger()
    assert asked[2] == str(Path(documents_folder()) / 'Untitled.rsroi')
    # A system without a Documents folder falls back to the home one.
    monkeypatch.setattr(
        QStandardPaths, 'writable_location',
        staticmethod(lambda location: ''))
    blank_window.ui.action_open.trigger()
    assert asked[3] == str(Path.home())


def test_each_kind_of_file_dialog_remembers_its_own_folder(
        window, monkeypatch, tmp_path) -> None:
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    map_path = tmp_path / 'map.png'
    assert image.save(str(map_path), 'PNG')
    capture_messages(monkeypatch)
    asked = capture_dialogs(monkeypatch, str(map_path))
    window.ui.action_add_basemap.trigger()
    assert asked[0] == documents_folder()
    # The image dialog goes back to the image it last read.
    window.ui.action_add_basemap.trigger()
    assert asked[1] == str(tmp_path)
    # Saving a document moves the document dialogs, not the image one.
    window.ui.action_save_as.trigger()
    assert asked[2] == str(Path(documents_folder()) / 'Untitled.rsroi')
    assert window.save_path(tmp_path / 'doc.rsroi')
    window.ui.action_open.trigger()
    assert asked[3] == str(tmp_path)
    window.ui.action_add_basemap.trigger()
    assert asked[4] == str(tmp_path)


def test_the_save_action_writes_back_to_the_current_file(
        window, monkeypatch, tmp_path) -> None:
    path = tmp_path / 'doc.rsroi'
    # A document that has never been saved is asked where to go.
    asked = capture_dialogs(monkeypatch, str(path))
    draw_polygon(window)
    window.ui.action_save.trigger()
    assert asked == [str(Path(documents_folder()) / 'Untitled.rsroi')]
    # From then on the same action writes the file it knows.
    window.ui.action_add_line.trigger()
    for text in ('10, 10', '20, 20'):
        type_coords(window, text)
    window.ui.action_save.trigger()
    loaded = load_document(path)
    assert len(loaded.shapes) == 2
    assert [(p.x(), p.y()) for p in loaded.shapes[1].vertices] == [
        (10.0, 10.0), (20.0, 20.0)]


def test_save_as_appends_the_roi_extension(
        window, monkeypatch, tmp_path) -> None:
    asked = capture_dialogs(monkeypatch, str(tmp_path / 'plot'))
    draw_polygon(window)
    window.ui.action_save_as.trigger()
    assert (tmp_path / 'plot.rsroi').exists()
    title = window.window_title
    assert title.startswith('plot') and APPLICATION_NAME in title
    assert '.rsroi' not in title
    assert asked == [str(Path(documents_folder()) / 'Untitled.rsroi')]


def test_closing_asks_about_an_unsaved_document(
        window, monkeypatch) -> None:
    draw_polygon(window)
    capture_messages(monkeypatch, QMessageBox.StandardButton.No)
    assert not window.close()
    assert window.visible
    capture_messages(monkeypatch, QMessageBox.StandardButton.Yes)
    assert window.close()
    assert not window.visible


def test_the_about_box_shows_the_notice(window, monkeypatch) -> None:
    QCoreApplication.application_version = '3.2.1'
    shown = capture_about(monkeypatch)
    window.ui.action_about.trigger()
    assert APPLICATION_NAME in shown[0]
    assert '3.2.1' in shown[0]
    assert 'GNU General Public License' in shown[0]
    assert 'https://www.gnu.org/licenses/' in shown[0]
    # A source tree with no installed distribution has no version.
    QCoreApplication.application_version = ''
    window.ui.action_about.trigger()
    assert shown[1] != shown[0]
    assert 'version' in shown[1]


def test_a_missing_distribution_has_no_version(monkeypatch) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, 'version', missing)
    assert installed_version() == ''


# Selecting and dragging


def test_a_press_selects_the_handle_it_lands_near(window) -> None:
    draw_square(window)
    set_zoom(window, 400)
    view = window.roi_view
    handle = view.map_from_scene(QPointF(40, 0))
    # A press away from every handle takes the shape itself.
    QTest.mouse_click(
        view.viewport(), Qt.MouseButton.LeftButton,
        pos=handle + QPoint(-12, 0))
    assert window.ui.action_remove_shape.enabled
    assert not window.ui.action_remove_vertex.enabled
    # A few pixels from the handle, and it is the vertex that answers.
    QTest.mouse_click(
        view.viewport(), Qt.MouseButton.LeftButton,
        pos=handle + QPoint(-3, 0))
    assert window.ui.action_remove_vertex.enabled
    window.ui.action_remove_vertex.trigger()
    assert vertices(window) == [
        (0.0, 0.0), (40.0, 40.0), (0.0, 40.0)]


def test_a_press_turns_into_a_drag_of_the_selected_vertex(window) -> None:
    draw_square(window)
    view = window.roi_view
    start = view.map_from_scene(QPointF(40, 0))
    QTest.mouse_press(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    assert window.ui.action_remove_vertex.enabled
    QTest.mouse_move(view.viewport(), start + QPoint(30, 30))
    QTest.mouse_release(
        view.viewport(), Qt.MouseButton.LeftButton,
        pos=start + QPoint(30, 30))
    moved = vertices(window)[1]
    assert moved != (40.0, 0.0)
    assert vertices(window)[0] == (0.0, 0.0)


def test_dragging_a_shape_moves_all_of_its_vertices(window) -> None:
    draw_square(window)
    window.roi_view.clicked.emit(QPointF(20, 20))
    assert window.ui.action_remove_shape.enabled
    assert not window.ui.action_remove_vertex.enabled
    window.roi_view.dragged.emit(QPointF(25, 22))
    window.roi_view.drag_finished.emit()
    assert vertices(window) == [
        (5.0, 2.0), (45.0, 2.0), (45.0, 42.0), (5.0, 42.0)]
    # The tree follows the shape it lists.
    model = window.shapes_view.model()
    first = window.document.shapes[0].vertices[0]
    assert model.item(0).child(0, 1).text() == format_number(first.x())
    assert model.item(0).child(0, 2).text() == format_number(first.y())


def test_a_drag_follows_the_pointer_and_snaps_to_pixels(window) -> None:
    draw_square(window)
    window.roi_view.clicked.emit(QPointF(40, 0))
    # Less than half a pixel is no move at all.
    window.roi_view.dragged.emit(QPointF(40.3, 0.4))
    assert vertices(window)[1] == (40.0, 0.0)
    window.roi_view.dragged.emit(QPointF(43.4, 2.6))
    window.roi_view.drag_finished.emit()
    assert vertices(window)[1] == (43.0, 3.0)
    # Every move is measured from the press, so nothing is left over.
    window.roi_view.clicked.emit(QPointF(43, 3))
    window.roi_view.dragged.emit(QPointF(51, 13))
    window.roi_view.dragged.emit(QPointF(43, 3))
    window.roi_view.drag_finished.emit()
    assert vertices(window)[1] == (43.0, 3.0)
    # A move after the pointer is let go moves nothing.
    window.roi_view.dragged.emit(QPointF(45, 5))
    assert vertices(window)[1] == (43.0, 3.0)


def test_dragging_empty_canvas_or_a_draft_moves_nothing(window) -> None:
    draw_square(window)
    window.roi_view.clicked.emit(QPointF(80, 70))
    window.roi_view.dragged.emit(QPointF(85, 75))
    window.roi_view.drag_finished.emit()
    assert not window.ui.action_remove_shape.enabled
    assert vertices(window) == [
        (0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]
    # A shape being drawn is not moved by a drag either.
    window.ui.action_add_line.trigger()
    window.roi_view.clicked.emit(QPointF(10, 10))
    window.roi_view.dragged.emit(QPointF(30, 30))
    window.roi_view.clicked.emit(QPointF(20, 20))
    assert vertices(window, index=1) == [(10.0, 10.0), (20.0, 20.0)]


def test_a_shape_stops_at_the_edge_of_the_basemap(window) -> None:
    draw_square(window)
    window.roi_view.clicked.emit(QPointF(20, 20))
    window.roi_view.dragged.emit(QPointF(500, 500))
    window.roi_view.drag_finished.emit()
    # The square slides along the edge rather than leaving the image.
    assert vertices(window) == [
        (59.0, 39.0), (99.0, 39.0), (99.0, 79.0), (59.0, 79.0)]
    assert not window.document.shapes[0].allow_vertices_outside_basemap


def test_a_vertex_stops_at_the_edge_unless_it_may_leave(window) -> None:
    draw_square(window)
    window.roi_view.clicked.emit(QPointF(40, 0))
    window.roi_view.dragged.emit(QPointF(-500, -500))
    window.roi_view.drag_finished.emit()
    assert vertices(window)[1] == (0.0, 0.0)
    assert vertices(window)[2] == (40.0, 40.0)
    # A shape that may hold vertices outside keeps them.
    window.document.shapes[0].allow_vertices_outside_basemap = True
    window.roi_view.clicked.emit(QPointF(0, 0))
    window.roi_view.dragged.emit(QPointF(-100, -100))
    window.roi_view.drag_finished.emit()
    assert vertices(window)[1] == (-100.0, -100.0)


# The dialogs of a shape


def test_the_shape_properties_are_applied(window, monkeypatch) -> None:
    draw_polygon(window)
    shape = window.document.shapes[0]
    original_init = ShapePropsEditor.__init__

    def prepare(self, edited, parent=None):
        original_init(self, edited, parent)
        self.ui.name_edit.text = "renamed"
        box = self.ui.allow_vertices_outside_basemap_check_box
        box.checked = True

    monkeypatch.setattr(ShapePropsEditor, '__init__', prepare)
    monkeypatch.setattr(
        ShapePropsEditor, 'exec',
        lambda self: QDialog.DialogCode.Accepted)
    window.ui.action_shape_props.trigger()
    assert shape.name == "renamed"
    assert shape.allow_vertices_outside_basemap
    assert window.shapes_view.model().item(0).text() == "renamed"


def test_a_dump_dialog_shows_and_copies_each_format(window) -> None:
    draw_polygon(window)
    dialog = DumpShapeDialog(window.document.shapes[0], window)
    compact = '[[0, 0], [10, 0], [10, 10]]'
    assert dialog.ui.output_edit.plain_text == compact
    dialog.copy_button.click()
    assert QGuiApplication.clipboard().text() == compact
    box = dialog.ui.format_box
    box.current_index = box.find_data(DumpFormat.EXPANDED)
    expanded = '- [0, 0]\n- [10, 0]\n- [10, 10]'
    assert dialog.ui.output_edit.plain_text == expanded
    dialog.copy_button.click()
    assert QGuiApplication.clipboard().text() == expanded


def test_the_dump_action_opens_the_dialog_of_the_selected_shape(
        window, monkeypatch) -> None:
    draw_polygon(window)
    window.ui.action_add_polygon.trigger()
    for text in ('20, 20', '30, 20', '30, 30'):
        type_coords(window, text)
    window.roi_view.finish_requested.emit()
    shape = window.document.shapes[1]
    shown: list[str] = []

    def record(self) -> QDialog.DialogCode:
        shown.append(self.ui.output_edit.plain_text)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DumpShapeDialog, 'exec', record)
    window.ui.action_dump_shape.trigger()
    assert shown == [format_compact(shape)]
