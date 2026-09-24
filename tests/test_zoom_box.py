"""Tests for the zoom box of the status bar."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox

from pyqt_roi_editor.zoom_box import ZoomBox, ZoomFit, parse_percent

from __feature__ import snake_case, true_property


@pytest.mark.parametrize(('text', 'expected'), [
    ('149%', 1.49),
    ('149', 1.49),
    ('  149 %  ', 1.49),
    ('100%', 1.0),
    ('25%', 0.25),
    ('1000', 10.0),
])
def test_parse_percent_reads_a_percentage(text: str, expected: float) -> None:
    assert parse_percent(text) == pytest.approx(expected)


@pytest.mark.parametrize('text', ['', '%', '0', '0%', '-5%', 'wide', '1,5'])
def test_parse_percent_refuses_what_is_no_percentage(text: str) -> None:
    assert parse_percent(text) is None


def test_the_box_offers_the_modes_and_some_ratios(qapp) -> None:
    box = ZoomBox()
    data = [box.item_data(index) for index in range(box.count)]
    assert data[:2] == [ZoomFit.WIDTH, ZoomFit.WINDOW]
    assert 1.0 in data
    assert box.editable
    assert box.insert_policy is QComboBox.InsertPolicy.NoInsert


def test_the_box_carries_a_tool_tip(qapp) -> None:
    box = ZoomBox()
    assert '%' in box.tool_tip
    assert box.line_edit().tool_tip == box.tool_tip


def test_picking_a_mode_asks_for_it(qapp) -> None:
    box = ZoomBox()
    asked: list[ZoomFit] = []
    box.fit_requested.connect(asked.append)
    box.activated.emit(0)
    box.activated.emit(1)
    assert asked == [ZoomFit.WIDTH, ZoomFit.WINDOW]


def test_typing_a_percentage_asks_for_it(qapp) -> None:
    box = ZoomBox()
    asked: list[float] = []
    box.ratio_requested.connect(asked.append)
    box.line_edit().text = '149%'
    QTest.key_click(box.line_edit(), Qt.Key.Key_Return)
    assert asked == [pytest.approx(1.49)]


def test_typing_the_ratio_already_shown_asks_for_nothing(qapp) -> None:
    box = ZoomBox()
    asked: list[float] = []
    box.ratio_requested.connect(asked.append)
    box.line_edit().text = '100%'
    QTest.key_click(box.line_edit(), Qt.Key.Key_Return)
    assert asked == []


def test_a_percentage_of_zero_is_no_zoom(qapp) -> None:
    """A text the validator lets through but nothing can zoom to."""
    box = ZoomBox()
    box.show_ratio(0.5)
    asked: list[float] = []
    box.ratio_requested.connect(asked.append)
    box.line_edit().text = '0'
    QTest.key_click(box.line_edit(), Qt.Key.Key_Return)
    assert asked == []
    assert box.line_edit().text == '50%'


def test_showing_a_ratio_marks_the_entry_it_matches(qapp) -> None:
    box = ZoomBox()
    box.show_ratio(0.25)
    assert box.item_text(box.current_index) == '25%'
    box.show_ratio(1.49)
    # A ratio the box does not offer leaves the list unmarked.
    assert box.current_index == -1
    assert box.line_edit().text == '149%'


def test_showing_a_mode_names_it(qapp) -> None:
    box = ZoomBox()
    box.show_fit(ZoomFit.WINDOW, 0.73)
    assert box.item_text(box.current_index) == 'Fit Window'
    assert box.line_edit().text == 'Fit Window'


def test_a_refused_percentage_gives_the_mode_back(qapp) -> None:
    box = ZoomBox()
    box.show_fit(ZoomFit.WIDTH, 0.5)
    box.line_edit().text = '0'
    QTest.key_click(box.line_edit(), Qt.Key.Key_Return)
    assert box.line_edit().text == 'Fit Width'
