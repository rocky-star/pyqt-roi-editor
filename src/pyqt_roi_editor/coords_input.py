"""The floating palette a vertex position can be typed into.

The palette is not modal: it stays open while a shape is being drawn,
so a vertex can be clicked in the view or typed here, whichever the
user prefers.
"""

__all__ = ['CoordsInput', 'parse_coords']

import re

from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt, Signal
from PySide6.QtWidgets import QToolTip, QWidget

from pyqt_roi_editor.ui_coordsinput import Ui_CoordsInput

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]

_SEPARATORS = re.compile(r'[,\s]+')
_BRACKETS = (('(', ')'), ('[', ']'))


def parse_coords(text: str) -> QPointF | None:
    """Parse a typed position, or return ``None`` when it is not one.

    ``x, y`` is the expected form; ``x y``, ``(x, y)`` and ``[x, y]``
    are accepted too, so a position can be pasted straight out of the
    Compact dump format or out of a pair of parentheses.  Either
    number may be negative and may have a fractional part.

    Parameters
    ----------
    text : str
        The text to parse.

    Returns
    -------
    QPointF or None
        The parsed position, or ``None`` when `text` is not exactly
        two numbers.

    Examples
    --------
    >>> parse_coords('10, 20') == QPointF(10.0, 20.0)
    True
    >>> parse_coords('10') is None
    True
    """
    cleaned = text.strip()
    for opening, closing in _BRACKETS:
        if cleaned.startswith(opening) and cleaned.endswith(closing):
            cleaned = cleaned[1:-1]
            break
    tokens = [token for token in _SEPARATORS.split(cleaned) if token]
    if len(tokens) != 2:
        return None
    try:
        x, y = (float(token) for token in tokens)
    except ValueError:
        return None
    return QPointF(x, y)


class CoordsInput(QWidget):
    """A small bar holding a position field and its two buttons.

    Signals
    -------
    accepted : QPointF
        Emitted with the parsed position when the text is accepted.
    rejected
        Emitted when the palette is dismissed.

    Notes
    -----
    The palette is an ordinary child widget of the editing area rather
    than a window of its own.  A window would have to be placed by the
    compositor, which on Wayland means it ends up wherever the
    compositor likes, and a bar that cannot be seen is of no use.

    It also does not read the keyboard itself: the window sends the
    characters of a coordinate to `insert_text()`, so typing works
    whether or not the field has managed to take the focus.
    """

    accepted = Signal(QPointF)
    rejected = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui = Ui_CoordsInput()
        self.ui.setupUi(self)  # pyright: ignore[reportUnknownMemberType]
        # A plain child widget paints nothing of its own, which would
        # leave a bare field and two buttons floating on the dark
        # view; the sheet gives the bar a surface and an edge.
        self.object_name = 'coords_input'
        self.set_attribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.style_sheet = (
            '#coords_input {'
            ' background-color: palette(base);'
            ' border: 1px solid palette(mid);'
            '}')
        self.ui.accept_button.clicked.connect(self.accept)
        self.ui.reject_button.clicked.connect(self._reject)
        # A child widget is shown together with its parent, and this
        # one should only appear when a coordinate is typed.
        self.hide()

    @property
    def text(self) -> str:
        """Return what has been typed into the field."""
        return self.ui.coords_edit.text

    def popup_at(self, position: QPoint, typed_text: str = '') -> None:
        """Show the palette at `position`, in parent coordinates.

        Parameters
        ----------
        position : QPoint
            Where to put the palette, near the pointer but kept
            inside the editing area by the caller.
        typed_text : str, optional
            Text to add to the field, so the key that opened the
            palette is not lost.  Defaults to empty.
        """
        self.adjust_size()
        self.move(position)
        self.show()
        self.raise_()
        self.insert_text(typed_text)

    def insert_text(self, text: str) -> None:
        """Add `text` to the field, and put the focus there."""
        if not text:
            return
        if not self.visible:
            self.ui.coords_edit.clear()
        self.ui.coords_edit.insert(text)
        self.ui.coords_edit.set_focus()

    def reset(self) -> None:
        """Empty the field and hide the palette."""
        self.ui.coords_edit.clear()
        self.hide()

    def accept(self) -> None:
        """Emit the typed position, or complain about the text.

        The palette goes away as soon as the position is taken: a
        popup holds the pointer while it is open, and the view answers
        clicks as usual once it is gone.  The next coordinate opens it
        again with its first key.
        """
        field = self.ui.coords_edit
        point = parse_coords(field.text)
        if point is None:
            QToolTip.show_text(
                field.map_to_global(QPoint(0, 0)),
                self.__tr("Enter coordinates as 'x, y'"),
                field)
            field.select_all()
            return
        self.reset()
        self.accepted.emit(point)

    def _reject(self) -> None:
        """Emit the request to give up."""
        self.rejected.emit()

    def __tr(self,
             source_text: str, disambiguation: str | None = None,
             n: int = -1) -> str:
        return QCoreApplication.translate(
            'CoordsInput', source_text, disambiguation, n)
