"""Tests for the document model and the small helpers around it."""

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage

from pyqt_roi_editor.coords_input import parse_coords
from pyqt_roi_editor.document import Basemap, Document, Shape, ShapeKind
from pyqt_roi_editor.dump_shape_dialog import format_compact
from pyqt_roi_editor.helpers import format_number


@pytest.mark.parametrize(('text', 'expected'), [
    ('10, 20', QPointF(10.0, 20.0)),
    ('10 20', QPointF(10.0, 20.0)),
    ('(10, 20)', QPointF(10.0, 20.0)),
    ('[10, 20]', QPointF(10.0, 20.0)),
    ('-1.5, 2.25', QPointF(-1.5, 2.25)),
    ('  3 , 4  ', QPointF(3.0, 4.0)),
])
def test_parse_coords_accepts(text: str, expected: QPointF) -> None:
    assert parse_coords(text) == expected


@pytest.mark.parametrize('text', ['', '10', '10,', 'a, b', '1, 2, 3', '(1, 2'])
def test_parse_coords_rejects(text: str) -> None:
    assert parse_coords(text) is None


def test_format_number_drops_an_empty_fraction() -> None:
    assert format_number(10.0) == "10"
    assert format_number(-3.0) == "-3"


def test_format_number_keeps_a_fraction() -> None:
    assert format_number(10.5) == "10.5"
    assert format_number(-0.25) == "-0.25"


def test_format_compact_matches_the_documented_shape() -> None:
    shape = Shape('s', ShapeKind.POLYGON, [
        QPointF(10, 10), QPointF(20, 20), QPointF(30, 30)])
    assert format_compact(shape) == "[[10, 10], [20, 20], [30, 30]]"


def test_format_compact_of_a_shape_without_vertices() -> None:
    assert format_compact(Shape("s")) == "[]"


def test_insert_vertex_appends_while_there_is_no_edge() -> None:
    shape = Shape('s')
    assert shape.insert_vertex(QPointF(1, 1)) == 0
    assert shape.insert_vertex(QPointF(2, 2)) == 1
    assert shape.vertices == [QPointF(1, 1), QPointF(2, 2)]


def test_insert_vertex_uses_the_nearest_edge() -> None:
    shape = Shape('s', ShapeKind.LINE, [
        QPointF(0, 0), QPointF(10, 0), QPointF(10, 10)])
    assert shape.insert_vertex(QPointF(5, 1)) == 1


def test_insert_vertex_can_use_the_closing_edge() -> None:
    shape = Shape('s', ShapeKind.POLYGON, [
        QPointF(0, 0), QPointF(10, 0), QPointF(10, 10)])
    assert shape.insert_vertex(QPointF(5, 5)) == 3


def test_remove_vertex_drops_the_one_at_the_index() -> None:
    shape = Shape('s', ShapeKind.LINE, [QPointF(0, 0), QPointF(1, 1)])
    shape.remove_vertex(0)
    assert shape.vertices == [QPointF(1, 1)]


def test_polygon_is_closed_and_line_is_not() -> None:
    assert Shape('s', ShapeKind.POLYGON).closed
    assert not Shape('s', ShapeKind.LINE).closed


def test_basemap_contains_its_own_area() -> None:
    basemap = Basemap('map', QImage(100, 50, QImage.Format.Format_RGB32))
    assert basemap.contains(QPointF(0, 0))
    assert basemap.contains(QPointF(99, 49))
    assert not basemap.contains(QPointF(100, 10))
    assert not basemap.contains(QPointF(-1, 10))


def test_current_basemap_follows_the_active_index() -> None:
    document = Document(basemaps=[
        Basemap('a', QImage()), Basemap('b', QImage())])
    assert document.current_basemap is None
    document.active_basemap = 1
    assert document.current_basemap is document.basemaps[1]
    document.active_basemap = 5
    assert document.current_basemap is None


def test_an_empty_document_has_no_basename() -> None:
    assert Document().basename == ''
    assert Document().is_empty
