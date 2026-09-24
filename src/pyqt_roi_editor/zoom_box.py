"""The zoom control of the status bar.

The box names a few ratios together with two modes that follow the
size of the viewport, and takes a percentage typed into it, such as
``149%``.  It only asks for a zoom: which view is zoomed, and how, is
none of its business.
"""

__all__ = ['ZoomBox', 'ZoomFit', 'parse_percent']

import enum
from typing import cast

from PySide6.QtCore import QCoreApplication, QRegularExpression, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QComboBox, QLineEdit, QWidget

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]

# The ratios the box offers; any other one can be typed.
_PERCENTAGES = (25, 50, 100, 200, 400)

# What may be typed: a percentage of up to four digits, sign optional.
_PERCENT_PATTERN = r'\d{1,4}\s*%?'


class ZoomFit(enum.Enum):
    """A zoom that follows the size of the viewport."""

    WIDTH = 'width'
    WINDOW = 'window'


def parse_percent(text: str) -> float | None:
    """Return the ratio `text` names, or ``None`` when it names none.

    The text is a percentage, with or without its sign: ``149`` and
    ``149%`` are the same zoom, and neither zero nor a negative one
    means anything.
    """
    stripped = text.strip().removesuffix('%').strip()
    try:
        percent = float(stripped)
    except ValueError:
        return None
    if percent <= 0.0:
        return None
    return percent / 100.0


class ZoomBox(QComboBox):
    """The status bar combo that asks for a zoom.

    Signals
    -------
    ratio_requested : float
        Emitted with the ratio of the natural size to show, which is
        ``1.49`` for what the user typed as ``149%``.
    fit_requested : ZoomFit
        Emitted when the user picks a zoom that follows the viewport.
    """

    ratio_requested = Signal(float)
    fit_requested = Signal(ZoomFit)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.object_name = 'zoom_box'
        self.editable = True
        self.insert_policy = QComboBox.InsertPolicy.NoInsert
        self.add_item(self.__tr("Fit Width"), ZoomFit.WIDTH)
        self.add_item(self.__tr("Fit Window"), ZoomFit.WINDOW)
        for percent in _PERCENTAGES:
            self.add_item(f'{percent}%', percent / 100.0)
        # An editable combo has a line edit; the stub cannot say so.
        self._edit = cast('QLineEdit', self.line_edit())
        tip = self.__tr(
            "Zoom the view, or type a percentage such as 149%.")
        self.tool_tip = tip
        self._edit.tool_tip = tip
        self._edit.set_validator(QRegularExpressionValidator(
            QRegularExpression(_PERCENT_PATTERN), self))
        self._ratio = 1.0
        self.show_ratio(1.0)
        self.activated.connect(self._on_activated)
        self._edit.returnPressed.connect(self._on_text_entered)

    def show_ratio(self, ratio: float) -> None:
        """Show `ratio` as the current zoom, without asking for one.

        The entry that names the ratio is marked; a ratio no entry
        names leaves the list unmarked, since marking one would point
        at a zoom the view is not at.
        """
        self._ratio = ratio
        self.current_index = self._index_of(ratio)
        self._edit.text = self._text()

    def show_fit(self, fit: ZoomFit, ratio: float) -> None:
        """Show the mode the view follows, in the name of that mode.

        A view that follows the window has no ratio of its own, so the
        ratio it works out to is only kept for the next request.
        """
        self._ratio = ratio
        self.current_index = self._index_of(fit)
        self._edit.text = self._text()

    def _index_of(self, value: object) -> int:
        """Return the index of the entry that names `value`, or -1."""
        for index in range(self.count):
            data = cast('object', self.item_data(index))
            if isinstance(data, float) and isinstance(value, float):
                if abs(data - value) < 0.0005:
                    return index
            elif data == value:
                return index
        return -1

    def _text(self) -> str:
        """Return the text that describes what the view is doing.

        A mode the marked entry names is shown as that name, and
        anything else as the ratio the view is at.
        """
        data = cast('object', self.item_data(self.current_index))
        if isinstance(data, ZoomFit):
            return self.item_text(self.current_index)
        return f'{self._ratio * 100:.0f}%'

    def _on_activated(self, index: int) -> None:
        """Act on the entry the user picked."""
        data = cast('object', self.item_data(index))
        if isinstance(data, ZoomFit):
            self.fit_requested.emit(data)
            return
        self._on_text_entered()

    def _on_text_entered(self) -> None:
        """Ask for the ratio the text names, or put the text back.

        An editable combo reports the text twice when it is entered,
        once as an activation and once as the return of the line edit;
        the second one asks for the ratio the first one just asked
        for, and is the same request.
        """
        ratio = parse_percent(self._edit.text)
        if ratio is None:
            self._edit.text = self._text()
            return
        if ratio == self._ratio:
            return
        self._ratio = ratio
        self.ratio_requested.emit(ratio)

    def __tr(self,
             source_text: str, disambiguation: str | None = None,
             n: int = -1) -> str:
        return QCoreApplication.translate(
            'ZoomBox', source_text, disambiguation, n)
