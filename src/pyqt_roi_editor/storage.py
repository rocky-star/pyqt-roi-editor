"""Read and write ``.rsroi`` documents.

A document is a ZIP archive holding one JSON entry, `manifest.json`,
and one image entry per basemap under `basemaps/`, named after the
identifier of the basemap it holds.  Nothing is ever extracted to
disk, so a hostile archive cannot write outside itself.

The manifest also frames the shapes: `canvas` is the area they are
placed in and `active_basemap_id` names the image that is shown.  The
editor keeps every image at the origin of the shape coordinates and
has no frame of its own, so it writes both from the image it shows,
and reads a canvas as no more than a note.
"""

__all__ = ['FORMAT_VERSION', 'StorageError', 'load_document', 'save_document']

import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from PySide6.QtCore import QBuffer, QIODevice, QPointF
from PySide6.QtGui import QImage, QImageWriter

from pyqt_roi_editor.document import Basemap, Document, Shape, ShapeKind

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]

FORMAT_VERSION = 1
MANIFEST_ENTRY = 'manifest.json'
BASEMAP_DIRECTORY = 'basemaps'

# The document format names a shape by its type, and knows an older
# name for a line.
_SHAPE_KINDS = {
    'line': ShapeKind.LINE,
    'polyline': ShapeKind.LINE,
    'polygon': ShapeKind.POLYGON,
}

# The format leaves the image format to the extension of the entry.
_IMAGE_FORMATS = {
    'jpg': 'JPEG',
    'jpeg': 'JPEG',
    'png': 'PNG',
    'bmp': 'BMP',
    'tif': 'TIFF',
    'tiff': 'TIFF',
    'webp': 'WEBP',
}

_EXTENSIONS = {
    'JPEG': 'jpg',
    'PNG': 'png',
    'BMP': 'bmp',
    'TIFF': 'tif',
    'WEBP': 'webp',
}


class StorageError(Exception):
    """Raised when a document cannot be read or written."""


def save_document(document: Document, path: Path) -> None:
    """Write `document` to `path` as a ``.rsroi`` archive.

    Parameters
    ----------
    document : Document
        The document to write.
    path : Path
        The file to write to, which is replaced if it exists.

    Raises
    ------
    StorageError
        If the file cannot be written or an image cannot be encoded.
    """
    basemaps: list[Mapping[str, object]] = []
    try:
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for basemap in document.basemaps:
                data = basemap.image_data
                if data is None:
                    data = _image_to_bytes(
                        basemap.image, basemap.image_format)
                if data is None:
                    raise StorageError(
                        f"cannot encode basemap {basemap.name!r}")
                entry = (
                    f'{BASEMAP_DIRECTORY}/{basemap.id}'
                    f'.{_extension(basemap.image_format)}')
                archive.writestr(entry, data)
                basemaps.append({
                    'id': basemap.id,
                    'name': basemap.name,
                    'file': entry,
                })
            manifest: Mapping[str, object] = {
                'format_version': FORMAT_VERSION,
                'canvas': _canvas(document),
                'active_basemap_id': _active_basemap_id(document),
                'basemaps': basemaps,
                'shapes': [
                    _shape_payload(shape) for shape in document.shapes],
            }
            archive.writestr(
                MANIFEST_ENTRY,
                json.dumps(manifest, indent=2, ensure_ascii=False))
    except OSError as error:
        raise StorageError(str(error)) from error


def load_document(path: Path) -> Document:
    """Read the ``.rsroi`` archive at `path`.

    Parameters
    ----------
    path : Path
        The file to read.

    Returns
    -------
    Document
        The document held by the archive.

    Raises
    ------
    StorageError
        If the file is not a readable ``.rsroi`` archive.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _read_manifest(archive)
            basemaps = [
                _read_basemap(archive, entry)
                for entry in _array(manifest, 'basemaps')]
            shapes = [
                _read_shape(entry)
                for entry in _array(manifest, 'shapes')]
    except (
            OSError, zipfile.BadZipFile, KeyError,
            TypeError, ValueError) as error:
        raise StorageError(str(error)) from error
    _check_basemap_ids(basemaps)
    if shapes and not basemaps:
        # The vertices of a shape are pixels of an image, so a
        # document holding shapes holds the image they belong to.
        raise StorageError("shapes without a basemap to place them in")
    return Document(
        basemaps=basemaps,
        shapes=shapes,
        active_basemap=_active_index(manifest, basemaps),
        path=path)


def _canvas(document: Document) -> Mapping[str, object]:
    """Return the area the shapes of `document` are placed in.

    The editor keeps every image at the origin of the shape
    coordinates, so the area is the size of the image that is shown,
    and nothing at all when no image is.
    """
    basemap = document.current_basemap
    if basemap is None:
        return {'width': 0, 'height': 0}
    return {
        'width': basemap.image.width(),
        'height': basemap.image.height(),
    }


def _active_basemap_id(document: Document) -> str | None:
    """Return the identifier of the image `document` shows."""
    basemap = document.current_basemap
    return None if basemap is None else basemap.id


def _read_manifest(archive: zipfile.ZipFile) -> Mapping[str, object]:
    """Return the validated JSON object held by `archive`."""
    try:
        text = archive.read(MANIFEST_ENTRY).decode('utf-8')
    except KeyError as error:
        raise StorageError(
            f"the archive holds no {MANIFEST_ENTRY}") from error
    data = cast('object', json.loads(text))
    manifest = _as_mapping(data, "the manifest")
    version = manifest.get('format_version')
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise StorageError(f"unsupported document version {version!r}")
    return manifest


def _active_index(
        manifest: Mapping[str, object],
        basemaps: Sequence[Basemap]) -> int:
    """Return the index of the image the manifest shows.

    An identifier that names no basemap leaves the first one shown:
    the editor shows an image for as long as it holds one.
    """
    if not basemaps:
        return -1
    active = manifest.get('active_basemap_id')
    for index, basemap in enumerate(basemaps):
        if basemap.id == active:
            return index
    return 0


def _check_basemap_ids(basemaps: Sequence[Basemap]) -> None:
    """Refuse basemaps that would be written over one another."""
    seen: set[str] = set()
    for basemap in basemaps:
        if basemap.id in seen:
            raise StorageError(
                f"two basemaps share the id {basemap.id!r}")
        seen.add(basemap.id)


def _read_basemap(archive: zipfile.ZipFile, entry: object) -> Basemap:
    """Return the basemap described by the JSON object `entry`."""
    mapping = _as_mapping(entry, "a basemap entry")
    identifier = mapping.get('id')
    name = mapping.get('name')
    file_name = mapping.get('file')
    if (
            not _is_id(identifier)
            or not isinstance(name, str)
            or not isinstance(file_name, str)):
        raise StorageError(f"a basemap entry of {name!r} is malformed")
    data = archive.read(file_name)
    image = QImage.from_data(data)
    if image.is_null():
        raise StorageError(f"cannot decode basemap {name!r}")
    return Basemap(
        name=name,
        image=image,
        image_format=_format_of(file_name),
        image_data=data,
        id=cast('str', identifier))


def _read_shape(entry: object) -> Shape:
    """Return the shape described by the JSON object `entry`."""
    mapping = _as_mapping(entry, "a shape entry")
    identifier = mapping.get('id')
    name = mapping.get('name')
    kind = mapping.get('type')
    if (
            not _is_id(identifier)
            or not isinstance(name, str)
            or not isinstance(kind, str)):
        raise StorageError(f"a shape entry of {name!r} is malformed")
    shape_kind = _SHAPE_KINDS.get(kind)
    if shape_kind is None:
        raise StorageError(f"unknown shape type {kind!r}")
    vertices = _read_vertices(mapping.get('vertices', []))
    if shape_kind is ShapeKind.LINE and len(vertices) > 2:
        # A line is a segment: it has the two ends and nothing else.
        raise StorageError(f"the line {name!r} has more than two vertices")
    return Shape(
        name=name,
        kind=shape_kind,
        vertices=vertices,
        allow_vertices_outside_basemap=bool(
            mapping.get('allow_outside_vertices', False)),
        id=cast('str', identifier))


def _read_vertices(raw: object) -> list[QPointF]:
    """Return the vertices held by the JSON array `raw`."""
    vertices: list[QPointF] = []
    for entry in _as_sequence(raw, "the vertices of a shape"):
        point = _as_mapping(entry, "a vertex")
        x = _as_number(point.get('x'))
        y = _as_number(point.get('y'))
        if x is None or y is None:
            raise StorageError(f"invalid vertex {entry!r}")
        vertices.append(QPointF(x, y))
    return vertices


def _shape_payload(shape: Shape) -> Mapping[str, object]:
    """Return the JSON object describing `shape`."""
    return {
        'id': shape.id,
        'name': shape.name,
        'type': shape.kind.value,
        'allow_outside_vertices': shape.allow_vertices_outside_basemap,
        'vertices': [
            {'x': _dump_number(vertex.x()), 'y': _dump_number(vertex.y())}
            for vertex in shape.vertices],
    }


def _as_mapping(value: object, what: str) -> Mapping[str, object]:
    """Return `value` as a JSON object, or complain about it."""
    if not isinstance(value, dict):
        raise StorageError(f"{what} is not a JSON object")
    return cast('Mapping[str, object]', value)


def _array(payload: Mapping[str, object], key: str) -> Sequence[object]:
    """Return the JSON array `key` of `payload`, or an empty one."""
    return _as_sequence(payload.get(key, []), f'"{key}"')


def _as_sequence(value: object, what: str) -> Sequence[object]:
    """Return `value` as a JSON array, or complain about it."""
    if not isinstance(value, list):
        raise StorageError(f"{what} is not a JSON array")
    return cast('Sequence[object]', value)


def _as_number(value: object) -> float | None:
    """Return `value` as a number, or ``None`` when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _is_id(value: object) -> bool:
    """Return whether `value` names a basemap or a shape."""
    return isinstance(value, str) and bool(value)


def _dump_number(value: float) -> int | float:
    """Return `value` as an integer when it has no fractional part."""
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _format_of(file_name: str) -> str:
    """Return the image format the extension of `file_name` names."""
    suffix = Path(file_name).suffix.lstrip('.').lower()
    return _IMAGE_FORMATS.get(suffix, 'PNG')


def _extension(image_format: str) -> str:
    """Return the file extension used for `image_format`."""
    upper = image_format.upper()
    return _EXTENSIONS.get(upper, upper.lower() or 'png')


def _image_to_bytes(image: QImage, image_format: str) -> bytes | None:
    """Return `image` encoded as `image_format`, or ``None``."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter(buffer, image_format.encode('ascii'))
    if not writer.write(image):
        return None
    return bytes(buffer.data().data())
