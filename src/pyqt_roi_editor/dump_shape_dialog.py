"""The dialog dumping a shape's vertices in a textual format.

The formats offered are the members of `DumpFormat`: the combo box
lists them in the order they are declared, and `_FORMATTERS` says how
each of them writes a shape.  A new format is a member, a formatter
in that mapping, and a name in `DumpShapeDialog.format_name`.
"""

__all__ = [
    'DumpFormat', 'DumpShapeDialog', 'format_compact', 'format_expanded']

import enum
from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QWidget

from pyqt_roi_editor.document import Shape
from pyqt_roi_editor.helpers import format_number
from pyqt_roi_editor.ui_dumpshapedialog import Ui_DumpShapeDialog

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]


class DumpFormat(enum.Enum):
    """The textual formats a shape can be dumped in."""

    COMPACT = 'compact'
    EXPANDED = 'expanded'


def format_compact(shape: Shape) -> str:
    """Return the vertices as ``[[x, y], [x, y], ...]``.

    A polygon keeps exactly the vertices it holds; the first one is
    not repeated at the end.  A vertex with no fractional part is
    written without one, so the result reads ``[[10, 10], ...]``.

    Parameters
    ----------
    shape : Shape
        The shape to dump.

    Returns
    -------
    str
        The dumped vertices, ``[]`` for a shape with no vertex.

    Examples
    --------
    >>> shape = Shape('s', vertices=[QPointF(10, 10), QPointF(20, 20)])
    >>> format_compact(shape)
    '[[10, 10], [20, 20]]'
    """
    points = ', '.join(
        f'[{format_number(vertex.x())}, {format_number(vertex.y())}]'
        for vertex in shape.vertices)
    return f'[{points}]'


def format_expanded(shape: Shape) -> str:
    """Return the vertices as one ``- [x, y]`` item per line.

    The same vectors the compact format puts on one line, written as
    the YAML block sequence of them, which can be read and edited a
    line at a time.  A polygon keeps exactly the vertices it holds;
    the first one is not repeated at the end.  A vertex with no
    fractional part is written without one, so a line reads
    ``- [10, 10]``.

    Parameters
    ----------
    shape : Shape
        The shape to dump.

    Returns
    -------
    str
        The dumped vertices, one per line and without a line ending
        after the last, and ``[]`` for a shape with no vertex, which
        is how YAML writes an empty sequence.

    Examples
    --------
    >>> shape = Shape('s', vertices=[QPointF(10, 10), QPointF(20, 20)])
    >>> print(format_expanded(shape))
    - [10, 10]
    - [20, 20]
    """
    if not shape.vertices:
        return '[]'
    return '\n'.join(
        f'- [{format_number(vertex.x())}, {format_number(vertex.y())}]'
        for vertex in shape.vertices)


_FORMATTERS: dict[DumpFormat, Callable[[Shape], str]] = {
    DumpFormat.COMPACT: format_compact,
    DumpFormat.EXPANDED: format_expanded,
}


class DumpShapeDialog(QDialog):
    """The dump of one shape, with a button copying it out."""

    def __init__(self, shape: Shape, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shape = shape
        self.ui = Ui_DumpShapeDialog()
        self.ui.setupUi(self)  # pyright: ignore[reportUnknownMemberType]
        self.copy_button = QPushButton(self.__tr("Copy"), self)
        self.ui.button_box.add_button(
            self.copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.clicked.connect(self._copy_to_clipboard)
        for dump_format in DumpFormat:
            self.ui.format_box.add_item(
                self.format_name(dump_format), dump_format)
        self.ui.format_box.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def format_name(self, dump_format: DumpFormat) -> str:
        """Return the shown name of `dump_format`."""
        names = {
            DumpFormat.COMPACT: self.__tr("Compact"),
            DumpFormat.EXPANDED: self.__tr("Expanded (YAML)"),
        }
        return names.get(dump_format, dump_format.value)

    def _refresh(self) -> None:
        """Recompute the output for the chosen format."""
        chosen = cast('object', self.ui.format_box.current_data())
        dump_format = chosen if isinstance(chosen, DumpFormat) else None
        formatter = _FORMATTERS.get(dump_format) if dump_format else None
        self.ui.output_edit.plain_text = (
            formatter(self._shape) if formatter is not None else '')

    def _copy_to_clipboard(self) -> None:
        """Put the output on the clipboard."""
        QGuiApplication.clipboard().set_text(self.ui.output_edit.plain_text)

    def __tr(self,
             source_text: str, disambiguation: str | None = None,
             n: int = -1) -> str:
        return QCoreApplication.translate(
            'DumpShapeDialog', source_text, disambiguation, n)
