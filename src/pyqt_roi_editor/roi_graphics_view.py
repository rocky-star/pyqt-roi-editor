"""The graphics view the ROI editing area is drawn in.

The view only reports what happens to it — a click, a drag, a request
to finish the shape being drawn, a new size — and leaves every decision
to the main window.  The keyboard is watched by the window itself,
because a menu holds the focus for long enough that the view cannot
be relied on to receive it.

What the left mouse button does follows the tool the window has put
the view in; the middle button moves the view whatever the tool is,
and the right button frames an area for the zoom tool to fill the
view with.
"""

__all__ = ['ROIGraphicsView', 'Tool']

import enum
import math
from typing import cast, override

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QEnterEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QGraphicsView, QRubberBand, QWidget

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]

# The pointer travels this many pixels in the zoom tool to double the
# scale of the view, which stops at the two ends below however far it
# is dragged.
_ZOOM_DRAG = 120.0
_ZOOM_STEP = 2.0
_ZOOM_LEAST = 0.01
_ZOOM_MOST = 100.0
# A frame dragged out with the right button is only worth zooming into
# once it is more than a few pixels across.
_FRAME_LEAST = 8


class Tool(enum.Enum):
    """What the left mouse button does in the editing area."""

    SELECTION = 'selection'
    HAND = 'hand'
    ZOOM = 'zoom'


class ROIGraphicsView(QGraphicsView):
    """The view of the scene the basemap and the shapes live in.

    Attributes
    ----------
    tool : Tool
        What the left mouse button does: leave it to the window, to
        select shapes and move them, take it for moving the view, or
        take it for zooming the view.  The middle button moves the
        view whatever this says.

    Signals
    -------
    clicked : QPointF
        Emitted with the position in scene coordinates when the left
        mouse button is pressed in the selection tool.
    dragged : QPointF
        Emitted with the position in scene coordinates on every move
        of the pointer made while that button is held, so that the
        press can move what it selected.
    drag_finished
        Emitted when that button is released and the drag is over.
    finish_requested
        Emitted on a double click, asking for the shape being drawn to
        be kept.
    pan_started
        Emitted when the pointer has begun to move the view, so that
        the window can show the tool that does it.
    pan_finished
        Emitted when the view is no longer being moved.
    pointer_entered
        Emitted when the pointer comes over the editing area, which is
        where the window explains the tool it has put the view in.
    pointer_left
        Emitted when the pointer leaves the editing area again.
    resized
        Emitted once the viewport has taken its new size, so that a
        zoom which follows the window knows what to follow.
    zoom_requested : float
        Emitted with the scale a drag of the zoom tool asks for.
    zoom_area_requested : QRectF
        Emitted with the area of the scene the right button framed,
        which the view is to be filled with.
    """

    clicked = Signal(QPointF)
    dragged = Signal(QPointF)
    drag_finished = Signal()
    finish_requested = Signal()
    pan_started = Signal()
    pan_finished = Signal()
    pointer_entered = Signal()
    pointer_left = Signal()
    resized = Signal()
    zoom_requested = Signal(float)
    zoom_area_requested = Signal(QRectF)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the view, at the selection tool and at rest."""
        super().__init__(parent)
        self.tool = Tool.SELECTION
        self._dragging = False
        self._pan_origin: QPoint | None = None
        self._zoom_origin: QPoint | None = None
        self._zoom_base = 1.0
        self._frame: QRubberBand | None = None
        self._frame_origin: QPoint | None = None

    @override
    def mouse_press_event(self, event: QMouseEvent) -> None:
        """Begin what the button that was pressed asks for.

        A press made while a gesture is under way is left alone, so
        that whatever is following the pointer ends with the button
        that began it.
        """
        if not self._following():
            if event.button() == Qt.MouseButton.MiddleButton:
                # The middle button moves the view whatever the tool
                # is, which is how a shape is drawn over a part of the
                # image that is not on the screen yet.
                self._begin_pan(event.position().to_point())
            elif event.button() == Qt.MouseButton.LeftButton:
                self._begin_left(event)
            elif (event.button() == Qt.MouseButton.RightButton
                    and self.tool is Tool.ZOOM):
                self._begin_frame(event.position().to_point())
        super().mouse_press_event(event)

    @override
    def mouse_move_event(self, event: QMouseEvent) -> None:
        """Follow the pointer, as the press asked, then pass it on."""
        point = event.position().to_point()
        if self._pan_origin is not None:
            self._pan(point)
        elif self._zoom_origin is not None:
            self._zoom(point)
        elif self._frame_origin is not None:
            self._draw_frame(point)
        elif self._dragging:
            self.dragged.emit(self.map_to_scene(point))
        super().mouse_move_event(event)

    @override
    def mouse_release_event(self, event: QMouseEvent) -> None:
        """End the gesture, once the last button has been let go."""
        if not event.buttons():
            self._end_gesture()
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

    @override
    def enter_event(self, event: QEnterEvent) -> None:
        """Report the pointer coming over the editing area."""
        self.pointer_entered.emit()
        super().enter_event(event)

    @override
    def leave_event(self, event: QEvent) -> None:
        """Report the pointer going off to something else."""
        self.pointer_left.emit()
        super().leave_event(event)

    # The pointer

    def _following(self) -> bool:
        """Return whether a gesture is already following the pointer."""
        return (self._pan_origin is not None
                or self._zoom_origin is not None
                or self._frame_origin is not None
                or self._dragging)

    def _begin_left(self, event: QMouseEvent) -> None:
        """Begin what the tool does with the left button."""
        if self.tool is Tool.HAND:
            self._begin_pan(event.position().to_point())
            return
        if self.tool is Tool.ZOOM:
            self._zoom_origin = event.position().to_point()
            self._zoom_base = self.transform().m11()
            return
        self._dragging = True
        self.clicked.emit(self.map_to_scene(event.position().to_point()))

    def _end_gesture(self) -> None:
        """Finish whatever the pointer was asked to do."""
        if self._pan_origin is not None:
            self._pan_origin = None
            self.viewport().unset_cursor()
            self.pan_finished.emit()
            return
        if self._zoom_origin is not None:
            self._zoom_origin = None
            return
        if self._frame_origin is not None:
            self._end_frame()
            return
        if self._dragging:
            self._dragging = False
            self.drag_finished.emit()

    # Moving the view

    def _begin_pan(self, point: QPoint) -> None:
        """Begin moving the view with the pointer."""
        self._pan_origin = point
        self.viewport().cursor = Qt.CursorShape.ClosedHandCursor
        self.pan_started.emit()

    def _pan(self, point: QPoint) -> None:
        """Move the view by the step the pointer has made."""
        origin = self._pan_origin
        if origin is None:
            return
        self._pan_origin = point
        step = point - origin
        horizontal = self.horizontal_scroll_bar()
        vertical = self.vertical_scroll_bar()
        horizontal.value = horizontal.value - step.x()
        vertical.value = vertical.value - step.y()

    # Zooming the view

    def _zoom(self, point: QPoint) -> None:
        """Ask for the scale the drag has worked out.

        Dragging right doubles the scale for every `_ZOOM_DRAG` pixels
        the pointer travels, and dragging left halves it the same way.
        """
        origin = self._zoom_origin
        if origin is None:
            return
        steps = (point.x() - origin.x()) / _ZOOM_DRAG
        ratio = self._zoom_base * math.pow(_ZOOM_STEP, steps)
        self.zoom_requested.emit(min(max(ratio, _ZOOM_LEAST), _ZOOM_MOST))

    def _begin_frame(self, point: QPoint) -> None:
        """Begin the area the right button frames."""
        self._frame_origin = point
        self._show_frame(QRect(point, point))

    def _draw_frame(self, point: QPoint) -> None:
        """Show the area the pointer has framed so far."""
        origin = self._frame_origin
        if origin is not None:
            self._show_frame(QRect(origin, point).normalized())

    def _show_frame(self, area: QRect) -> None:
        """Put `area` on the screen as the frame being dragged."""
        frame = self._frame
        if frame is None:
            frame = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
            self._frame = frame
        # `geometry` is a property once true_property is active, even
        # though the stub still describes the setter method.
        frame.geometry = area  # type: ignore
        frame.show()

    def _end_frame(self) -> None:
        """Ask for the framed area to fill the view, and drop it."""
        frame = self._frame
        self._frame_origin = None
        if frame is None:
            return
        frame.hide()
        # `geometry` reads as a property to true_property as well.
        area = cast('QRect', frame.geometry)
        if area.width() < _FRAME_LEAST or area.height() < _FRAME_LEAST:
            return
        # A rectangle holds the pixel at its bottom right corner, so
        # the far corner of the framed area is the one past it.
        corner = area.top_left()
        opposite = corner + QPoint(area.width(), area.height())
        self.zoom_area_requested.emit(QRectF(
            self.map_to_scene(corner), self.map_to_scene(opposite)))

    def __tr(self,
             source_text: str, disambiguation: str | None = None,
             n: int = -1) -> str:
        """Return the translation of `source_text` for this class.

        The view shows no text of its own yet; the helper is here so
        every class of the editor translates its strings the same way.
        """
        return QCoreApplication.translate(
            'ROIGraphicsView', source_text, disambiguation, n)
