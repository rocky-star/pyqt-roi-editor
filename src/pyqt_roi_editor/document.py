"""The in-memory model of an ROI document.

Nothing in this module touches files: it holds the basemaps and shapes
the editor works on, and the geometry a shape needs to place a new
vertex.
"""

__all__ = ['Basemap', 'Document', 'Shape', 'ShapeKind']

import enum
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]


class ShapeKind(enum.Enum):
    """The geometry a shape traces."""

    LINE = 'line'
    POLYGON = 'polygon'


def _new_id() -> str:
    """Return the identifier a new basemap or shape is given."""
    return str(uuid.uuid4())


def _segment_distance(
        point: QPointF, start: QPointF, end: QPointF) -> float:
    """Return the distance between a point and a line segment.

    The projection of `point` onto the segment is clamped to the
    segment, so a point beyond one of the ends is measured against
    that end.

    Parameters
    ----------
    point : QPointF
        The point to measure.
    start, end : QPointF
        The ends of the segment.

    Returns
    -------
    float
        The distance, in the units the points are given in.
    """
    delta_x = end.x() - start.x()
    delta_y = end.y() - start.y()
    if delta_x == 0.0 and delta_y == 0.0:
        return math.hypot(point.x() - start.x(), point.y() - start.y())
    ratio = (
        (point.x() - start.x()) * delta_x
        + (point.y() - start.y()) * delta_y) / (
            delta_x * delta_x + delta_y * delta_y)
    ratio = min(1.0, max(0.0, ratio))
    return math.hypot(
        point.x() - (start.x() + ratio * delta_x),
        point.y() - (start.y() + ratio * delta_y))


@dataclass(eq=False)
class Basemap:
    """One image the shapes are drawn over.

    Instances compare and hash by identity, so a basemap taken out of
    one document is never mistaken for an equal-looking one.

    Attributes
    ----------
    name : str
        The name shown in the basemap list.
    image : QImage
        The image itself, at its native size.
    image_format : str
        The ``QImage`` format name the image is written back as.
    image_data : bytes or None
        The encoded image as it was read, which is written back
        untouched; ``None`` for an image that has only ever lived in
        memory, which is encoded from `image` instead.  Nothing in the
        editor changes `image`, so the two cannot drift apart.
    id : str
        The identifier the document format knows the basemap by, and
        the one the shown basemap is written as.
    """

    name: str
    image: QImage
    image_format: str = 'PNG'
    image_data: bytes | None = None
    id: str = field(default_factory=_new_id)

    @property
    def rect(self) -> QRectF:
        """Return the area the image covers in scene coordinates."""
        return QRectF(
            0.0, 0.0, float(self.image.width()), float(self.image.height()))

    def contains(self, point: QPointF) -> bool:
        """Return whether `point` lies on a pixel of the image.

        The image spans ``0 <= x < width`` and ``0 <= y < height``, so
        a coordinate on the right or bottom edge is already outside.
        """
        return (
            0.0 <= point.x() < float(self.image.width())
            and 0.0 <= point.y() < float(self.image.height()))


@dataclass(eq=False)
class Shape:
    """One line or polygon being edited.

    A line is a segment and holds exactly its two endpoints, while a
    polygon is closed and grows with every vertex added to it.

    Instances compare and hash by identity, so the shape a view is
    tracking is always the one held by the document.

    Attributes
    ----------
    name : str
        The name shown in the shape tree.
    kind : ShapeKind
        Whether the vertices trace a line or a polygon.
    vertices : list[QPointF]
        The vertices, in the order they are joined, in basemap pixels;
        the two ends of a line, or the corners of a polygon.
    allow_vertices_outside_basemap : bool
        Whether vertices outside the basemap are accepted; typing such
        a coordinate turns this on by itself.
    id : str
        The identifier the document format knows the shape by.
    """

    name: str
    kind: ShapeKind = ShapeKind.LINE
    vertices: list[QPointF] = field(default_factory=list)
    allow_vertices_outside_basemap: bool = False
    id: str = field(default_factory=_new_id)

    @property
    def closed(self) -> bool:
        """Return whether the last vertex is joined back to the first."""
        return self.kind is ShapeKind.POLYGON

    @property
    def accepts_vertices(self) -> bool:
        """Return whether another vertex may be added to the shape.

        A segment has both of its endpoints as soon as it holds two
        vertices, so there is no third one to give it; a polygon takes
        as many as it is offered.
        """
        return self.kind is ShapeKind.POLYGON or len(self.vertices) < 2

    def edges(self) -> list[tuple[int, int]]:
        """Return the index pairs of the vertices the shape joins."""
        if len(self.vertices) < 2:
            return []
        edges = [(index, index + 1) for index in range(len(self.vertices) - 1)]
        if self.closed:
            edges.append((len(self.vertices) - 1, 0))
        return edges

    def insert_vertex(self, point: QPointF) -> int | None:
        """Insert `point` between the nearest pair of joined vertices.

        The edge whose segment lies closest to `point` is found, and
        the new vertex is placed between that edge's two vertices,
        which keeps the existing order of the shape.

        Parameters
        ----------
        point : QPointF
            The position of the new vertex.

        Returns
        -------
        int or None
            The index the new vertex was inserted at, or ``None`` when
            the shape already holds every vertex it can take.
        """
        if not self.accepts_vertices:
            return None
        if len(self.vertices) < 2:
            self.vertices.append(point)
            return len(self.vertices) - 1
        first, _second = min(
            self.edges(),
            key=lambda edge: _segment_distance(
                point, self.vertices[edge[0]], self.vertices[edge[1]]))
        index = first + 1
        self.vertices.insert(index, point)
        return index

    def remove_vertex(self, index: int) -> None:
        """Drop the vertex at `index`."""
        del self.vertices[index]


@dataclass
class Document:
    """Everything one ``.rsroi`` file holds.

    Attributes
    ----------
    basemaps : list[Basemap]
        The images the shapes are drawn over, in list order.
    shapes : list[Shape]
        The shapes, in the order they were created.
    active_basemap : int
        The index of the shown basemap, or ``-1`` when none is shown.
    path : Path or None
        Where the document was last saved, or ``None`` while it has
        never been saved.
    """

    basemaps: list[Basemap] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    active_basemap: int = -1
    path: Path | None = None

    @property
    def current_basemap(self) -> Basemap | None:
        """Return the shown basemap, or ``None`` when there is none."""
        if 0 <= self.active_basemap < len(self.basemaps):
            return self.basemaps[self.active_basemap]
        return None

    @property
    def basename(self) -> str:
        """Return the file name the title is built from, or ``''``."""
        if self.path is None:
            return ''
        return self.path.name

    @property
    def is_empty(self) -> bool:
        """Return whether the document holds nothing worth keeping."""
        return not self.basemaps and not self.shapes
