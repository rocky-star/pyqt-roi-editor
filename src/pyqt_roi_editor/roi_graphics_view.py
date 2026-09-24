"""The graphics view the ROI editing area is drawn in.

The view only reports what happens to it — a click, a request to
finish the shape being drawn, a new size — and leaves every decision
to the main window.  The keyboard is watched by the window itself,
because a menu holds the focus for long enough that the view cannot
be relied on to receive it.
"""

__all__ = ['ROIGraphicsView']

from typing import override

from PySide6.QtCore import QCoreApplication, QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QGraphicsView

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]


class ROIGraphicsView(QGraphicsView):
    """The view of the scene the basemap and the shapes live in.

    Signals
    -------
    clicked : QPointF
        Emitted with the position in scene coordinates when the left
        mouse button is pressed.
    finish_requested
        Emitted on a double click, asking for the shape being drawn to
        be kept.
    resized
        Emitted once the viewport has taken its new size, so that a
        zoom which follows the window knows what to follow.
    """

    clicked = Signal(QPointF)
    finish_requested = Signal()
    resized = Signal()

    @override
    def mouse_press_event(self, event: QMouseEvent) -> None:
        """Report a left click, then pass the event on."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.map_to_scene(event.position().to_point()))
        super().mouse_press_event(event)

    @override
    def mouse_double_click_event(self, event: QMouseEvent) -> None:
        """Ask for the shape being drawn to be kept."""
        self.finish_requested.emit()
        super().mouse_double_click_event(event)

    @override
    def resize_event(self, event: QResizeEvent) -> None:
        """Report the new size, once the viewport has taken it."""
        super().resize_event(event)
        self.resized.emit()

    def __tr(self,
             source_text: str, disambiguation: str | None = None,
             n: int = -1) -> str:
        """Return the translation of `source_text` for this class.

        The view shows no text of its own yet; the helper is here so
        every class of the editor translates its strings the same way.
        """
        return QCoreApplication.translate(
            'ROIGraphicsView', source_text, disambiguation, n)
