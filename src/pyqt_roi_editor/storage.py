"""Read and write ``.rsroi`` documents.

A document is a ZIP archive holding one JSON entry, `data.json`, and
one image entry per basemap under `basemaps/`.  Nothing is ever
extracted to disk, so a hostile archive cannot write outside itself.
"""

__all__ = ['FORMAT_NAME', 'FORMAT_VERSION', 'StorageError',
           'load_document', 'save_document']

import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from PySide6.QtCore import QBuffer, QIODevice, QPointF
from PySide6.QtGui import QImage, QImageWriter

from pyqt_roi_editor.document import Basemap, Document, Shape, ShapeKind

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]

FORMAT_NAME = 'rsroi'
FORMAT_VERSION = 1
DATA_ENTRY = 'data.json'
BASEMAP_DIRECTORY = 'basemaps'

_EXTENSIONS = {'JPEG': 'jpg', 'JPG': 'jpg', 'TIFF': 'tif'}


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
            for index, basemap in enumerate(document.basemaps):
                data = _image_to_bytes(basemap.image, basemap.image_format)
                if data is None:
                    raise StorageError(
                        f"cannot encode basemap {basemap.name!r}")
                entry = (
                    f'{BASEMAP_DIRECTORY}/{index}'
                    f'.{_extension(basemap.image_format)}')
                archive.writestr(entry, data)
                basemaps.append({
                    'name': basemap.name,
                    'file': entry,
                    'format': basemap.image_format,
                })
            payload: Mapping[str, object] = {
                'format': FORMAT_NAME,
                'version': FORMAT_VERSION,
                'active_basemap': document.active_basemap,
                'basemaps': basemaps,
                'shapes': [
                    _shape_payload(shape) for shape in document.shapes],
            }
            archive.writestr(
                DATA_ENTRY,
                json.dumps(payload, indent=2, ensure_ascii=False))
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
            payload = _read_payload(archive)
            basemaps = [
                _read_basemap(archive, entry)
                for entry in _array(payload, 'basemaps')]
            shapes = [
                _read_shape(entry)
                for entry in _array(payload, 'shapes')]
    except (
            OSError, zipfile.BadZipFile, KeyError,
            TypeError, ValueError) as error:
        raise StorageError(str(error)) from error
    active = _as_number(payload.get('active_basemap', -1))
    active_index = int(active) if active is not None else -1
    if not 0 <= active_index < len(basemaps):
        active_index = -1
    return Document(
        basemaps=basemaps,
        shapes=shapes,
        active_basemap=active_index,
        path=path)


def _read_payload(archive: zipfile.ZipFile) -> Mapping[str, object]:
    """Return the validated JSON object held by `archive`."""
    text = archive.read(DATA_ENTRY).decode('utf-8')
    data = cast('object', json.loads(text))
    payload = _as_mapping(data, "the data entry")
    if payload.get('format') != FORMAT_NAME:
        raise StorageError("the data entry is not an rsroi document")
    version = payload.get('version')
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise StorageError(f"unsupported document version {version!r}")
    return payload


def _read_basemap(archive: zipfile.ZipFile, entry: object) -> Basemap:
    """Return the basemap described by the JSON object `entry`."""
    mapping = _as_mapping(entry, "a basemap entry")
    name = mapping.get('name')
    file_name = mapping.get('file')
    image_format = mapping.get('format', 'PNG')
    if (
            not isinstance(name, str)
            or not isinstance(file_name, str)
            or not isinstance(image_format, str)):
        raise StorageError(f"a basemap entry of {name!r} is malformed")
    image = QImage.from_data(archive.read(file_name))
    if image.is_null():
        raise StorageError(f"cannot decode basemap {name!r}")
    return Basemap(name=name, image=image, image_format=image_format)


def _read_shape(entry: object) -> Shape:
    """Return the shape described by the JSON object `entry`."""
    mapping = _as_mapping(entry, "a shape entry")
    name = mapping.get('name')
    kind = mapping.get('kind')
    if not isinstance(name, str) or not isinstance(kind, str):
        raise StorageError(f"a shape entry of {name!r} is malformed")
    try:
        shape_kind = ShapeKind(kind)
    except ValueError as error:
        raise StorageError(f"unknown shape kind {kind!r}") from error
    vertices = _read_vertices(mapping.get('vertices', []))
    if shape_kind is ShapeKind.LINE and len(vertices) > 2:
        # A line is a segment: it has the two ends and nothing else.
        raise StorageError(f"the line {name!r} has more than two vertices")
    return Shape(
        name=name,
        kind=shape_kind,
        vertices=vertices,
        allow_vertices_outside_basemap=bool(
            mapping.get('allow_vertices_outside_basemap', False)))


def _read_vertices(raw: object) -> list[QPointF]:
    """Return the vertices held by the JSON array `raw`."""
    vertices: list[QPointF] = []
    for pair in _as_sequence(raw, "the vertices of a shape"):
        values = _as_sequence(pair, "a vertex")
        if len(values) != 2:
            raise StorageError(f"invalid vertex {pair!r}")
        x = _as_number(values[0])
        y = _as_number(values[1])
        if x is None or y is None:
            raise StorageError(f"invalid vertex {pair!r}")
        vertices.append(QPointF(x, y))
    return vertices


def _shape_payload(shape: Shape) -> Mapping[str, object]:
    """Return the JSON object describing `shape`."""
    return {
        'name': shape.name,
        'kind': shape.kind.value,
        'allow_vertices_outside_basemap':
            shape.allow_vertices_outside_basemap,
        'vertices': [
            [_dump_number(vertex.x()), _dump_number(vertex.y())]
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


def _dump_number(value: float) -> int | float:
    """Return `value` as an integer when it has no fractional part."""
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


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
