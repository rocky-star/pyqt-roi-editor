"""Tests for reading and writing ``.rsroi`` archives."""

import json
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage

from pyqt_roi_editor.document import Basemap, Document, Shape, ShapeKind
from pyqt_roi_editor.storage import StorageError, load_document, save_document


def sample_document() -> Document:
    """Return a document holding one basemap and two shapes."""
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    image.fill(0xff123456)
    return Document(
        basemaps=[Basemap('map', image, 'PNG')],
        shapes=[
            Shape('line', ShapeKind.LINE, [QPointF(1, 2), QPointF(3.5, 4)],
                  allow_vertices_outside_basemap=True),
            Shape('polygon', ShapeKind.POLYGON,
                  [QPointF(0, 0), QPointF(5, 0), QPointF(5, 5)]),
        ],
        active_basemap=0)


def test_save_writes_the_data_entry_and_every_basemap(
        tmp_path: Path) -> None:
    path = tmp_path / 'doc.rsroi'
    save_document(sample_document(), path)
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == ["basemaps/0.png", "data.json"]


def test_round_trip_keeps_the_basemaps(tmp_path: Path) -> None:
    document = sample_document()
    path = tmp_path / 'doc.rsroi'
    save_document(document, path)
    loaded = load_document(path)
    assert loaded.path == path
    assert loaded.active_basemap == 0
    assert [basemap.name for basemap in loaded.basemaps] == ["map"]
    assert loaded.basemaps[0].image_format == "PNG"
    original = document.basemaps[0].image
    assert loaded.basemaps[0].image.size() == original.size()
    assert loaded.basemaps[0].image.pixel(1, 1) == original.pixel(1, 1)


def test_round_trip_keeps_the_shapes(tmp_path: Path) -> None:
    document = sample_document()
    path = tmp_path / 'doc.rsroi'
    save_document(document, path)
    loaded = load_document(path)
    assert [
        (shape.name, shape.kind, shape.allow_vertices_outside_basemap,
         shape.vertices)
        for shape in loaded.shapes
    ] == [
        (shape.name, shape.kind, shape.allow_vertices_outside_basemap,
         shape.vertices)
        for shape in document.shapes
    ]


def test_an_integer_coordinate_stays_an_integer(tmp_path: Path) -> None:
    document = sample_document()
    path = tmp_path / 'doc.rsroi'
    save_document(document, path)
    with zipfile.ZipFile(path) as archive:
        data = archive.read('data.json').decode('utf-8')
    vertices = json.loads(data)['shapes'][0]['vertices']
    assert vertices == [[1, 2], [3.5, 4.0]]
    assert isinstance(vertices[0][0], int)
    assert isinstance(vertices[1][0], float)


def test_a_file_that_is_not_an_archive_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'doc.rsroi'
    path.write_text('not a zip archive', encoding='utf-8')
    with pytest.raises(StorageError):
        load_document(path)


def test_an_archive_without_the_data_entry_is_rejected(
        tmp_path: Path) -> None:
    path = tmp_path / 'doc.rsroi'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('basemaps/0.png', b'')
    with pytest.raises(StorageError):
        load_document(path)


def test_an_unsupported_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'doc.rsroi'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(
            'data.json',
            '{"format": "rsroi", "version": 99, "basemaps": [],'
            ' "shapes": []}')
    with pytest.raises(StorageError):
        load_document(path)
