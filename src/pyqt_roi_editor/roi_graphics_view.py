"""The graphics view the ROI editing area is drawn in.

The view only reports what happens to it — a click, a drag, a request
to finish the shape being drawn, a new size — and leaves every decision
to the main window.  The keyboard is watched by the window itself,
because a menu holds the focus for long enough that the view cannot
be relied on to receive it.
"""

__all__ = ['ROIGraphicsView']

from typing import override

from PySide6.QtCore import QCoreApplication, QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QGraphicsView, QWidget

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]


class ROIGraphicsView(QGraphicsView):
    """The view of the scene the basemap and the shapes live in.

    Signals
    -------
    clicked : QPointF
        Emitted with the position in scene coordinates when the left
        mouse button is pressed.
    dragged : QPointF
        Emitted with the position in scene coordinates on every move
        of the pointer made while that button is held, so that the
        press can move what it selected.
    drag_finished
        Emitted when that button is released and the drag is over.
    finish_requested
        Emitted on a double click, asking for the shape being drawn to
        be kept.
    resized
        Emitted once the viewport has taken its new size, so that a
        zoom which follows the window knows what to follow.
    """

    clicked = Signal(QPointF)
    dragged = Signal(QPointF)
    drag_finished = Signal()
    finish_requested = Signal()
    resized = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the view, with no drag under way."""
        super().__init__(parent)
        self._dragging = False

    @override
    def mouse_press_event(self, event: QMouseEvent) -> None:
        """Report a left click, then pass the event on.

        The press is also what starts a drag: whatever it selects is
        what the moves that follow it move.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.clicked.emit(self.map_to_scene(event.position().to_point()))
        super().mouse_press_event(event)

    @override
    def mouse_move_event(self, event: QMouseEvent) -> None:
        """Report where a drag has got to, then pass the event on."""
        if self._dragging:
            self.dragged.emit(self.map_to_scene(event.position().to_point()))
        super().mouse_move_event(event)

    @override
    def mouse_release_event(self, event: QMouseEvent) -> None:
        """Report the end of a drag, then pass the event on."""
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.drag_finished.emit()
        super().mouse_release_event(event)

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
