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


def save_sample(tmp_path: Path) -> tuple[Document, Path]:
    """Write a sample document and return it together with its path."""
    document = sample_document()
    path = tmp_path / 'doc.rsroi'
    save_document(document, path)
    return document, path


def manifest_of(path: Path) -> dict[str, object]:
    """Return the manifest held by the archive at `path`."""
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('manifest.json').decode('utf-8'))


def entry_of(path: Path, name: str) -> bytes:
    """Return the bytes of the entry `name` of the archive at `path`."""
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def rewrite_manifest(path: Path, **changes: object) -> None:
    """Replace the named manifest entries of the archive at `path`.

    The entries are read into memory and written out again, which is
    fine for the small documents these tests work with.
    """
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = manifest_of(path)
    manifest.update(changes)
    entries['manifest.json'] = json.dumps(
        manifest, ensure_ascii=False).encode('utf-8')
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_save_writes_the_manifest_and_every_basemap(tmp_path: Path) -> None:
    document, path = save_sample(tmp_path)
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == [
            f'basemaps/{document.basemaps[0].id}.png', 'manifest.json']


def test_the_manifest_matches_the_format_of_the_other_tools(
        tmp_path: Path) -> None:
    document, path = save_sample(tmp_path)
    basemap = document.basemaps[0]
    line, polygon = document.shapes
    assert manifest_of(path) == {
        'format_version': 1,
        'canvas': {'width': 8, 'height': 6},
        'active_basemap_id': basemap.id,
        'basemaps': [{
            'id': basemap.id,
            'name': 'map',
            'file': f'basemaps/{basemap.id}.png',
        }],
        'shapes': [
            {
                'id': line.id,
                'name': 'line',
                'type': 'line',
                'allow_outside_vertices': True,
                'vertices': [{'x': 1, 'y': 2}, {'x': 3.5, 'y': 4}],
            },
            {
                'id': polygon.id,
                'name': 'polygon',
                'type': 'polygon',
                'allow_outside_vertices': False,
                'vertices': [
                    {'x': 0, 'y': 0}, {'x': 5, 'y': 0}, {'x': 5, 'y': 5}],
            },
        ],
    }


def test_round_trip_keeps_the_basemaps(tmp_path: Path) -> None:
    document, path = save_sample(tmp_path)
    loaded = load_document(path)
    assert loaded.path == path
    assert loaded.active_basemap == 0
    assert [basemap.name for basemap in loaded.basemaps] == ["map"]
    assert loaded.basemaps[0].image_format == "PNG"
    assert loaded.basemaps[0].id == document.basemaps[0].id
    original = document.basemaps[0].image
    assert loaded.basemaps[0].image.size() == original.size()
    assert loaded.basemaps[0].image.pixel(1, 1) == original.pixel(1, 1)


def test_round_trip_keeps_the_shapes(tmp_path: Path) -> None:
    document, path = save_sample(tmp_path)
    loaded = load_document(path)
    assert [
        (shape.id, shape.name, shape.kind,
         shape.allow_vertices_outside_basemap, shape.vertices)
        for shape in loaded.shapes
    ] == [
        (shape.id, shape.name, shape.kind,
         shape.allow_vertices_outside_basemap, shape.vertices)
        for shape in document.shapes
    ]


def test_an_integer_coordinate_stays_an_integer(tmp_path: Path) -> None:
    _document, path = save_sample(tmp_path)
    vertices = manifest_of(path)['shapes'][0]['vertices']
    assert vertices == [{'x': 1, 'y': 2}, {'x': 3.5, 'y': 4}]
    assert isinstance(vertices[0]['x'], int)
    assert isinstance(vertices[1]['x'], float)


def test_the_bytes_of_a_basemap_are_read_with_its_image(
        tmp_path: Path) -> None:
    document, path = save_sample(tmp_path)
    entry = f'basemaps/{document.basemaps[0].id}.png'
    loaded = load_document(path)
    assert loaded.basemaps[0].image_data == entry_of(path, entry)


def test_a_basemap_is_written_from_the_bytes_it_carries(
        tmp_path: Path) -> None:
    """An image that came from a file is not encoded a second time.

    A JPEG loses a little every time it is encoded, and the basemaps
    of a document the user brings along are theirs to keep.
    """
    document = sample_document()
    document.basemaps[0].image_data = b'the bytes of the image'
    path = tmp_path / 'doc.rsroi'
    save_document(document, path)
    assert entry_of(path, f'basemaps/{document.basemaps[0].id}.png') == (
        b'the bytes of the image')


def test_a_basemap_without_bytes_is_encoded_from_its_image(
        tmp_path: Path) -> None:
    """A basemap added in the editor has no file to go back to."""
    document, path = save_sample(tmp_path)
    assert not QImage.from_data(
        entry_of(path, f'basemaps/{document.basemaps[0].id}.png')).is_null()


def test_an_empty_document_round_trips(tmp_path: Path) -> None:
    path = tmp_path / 'doc.rsroi'
    save_document(Document(), path)
    loaded = load_document(path)
    assert loaded.basemaps == []
    assert loaded.shapes == []
    assert loaded.active_basemap == -1
    manifest = manifest_of(path)
    assert manifest['canvas'] == {'width': 0, 'height': 0}
    assert manifest['active_basemap_id'] is None


def test_the_shown_basemap_is_read_from_its_identifier(tmp_path: Path) -> None:
    document = sample_document()
    document.basemaps.append(
        Basemap('second', QImage(4, 4, QImage.Format.Format_RGB32), 'PNG'))
    document.active_basemap = 1
    path = tmp_path / 'doc.rsroi'
    save_document(document, path)
    loaded = load_document(path)
    assert loaded.active_basemap == 1
    assert loaded.current_basemap is not None
    assert loaded.current_basemap.id == document.basemaps[1].id


def test_an_unknown_basemap_identifier_shows_the_first_image(
        tmp_path: Path) -> None:
    _document, path = save_sample(tmp_path)
    rewrite_manifest(path, active_basemap_id='no-such-basemap')
    assert load_document(path).active_basemap == 0


def test_a_polyline_is_read_as_a_line(tmp_path: Path) -> None:
    _document, path = save_sample(tmp_path)
    rewrite_manifest(path, shapes=[{
        'id': 'shape-1',
        'name': '折线',
        'type': 'polyline',
        'allow_outside_vertices': False,
        'vertices': [{'x': 1, 'y': 2}, {'x': 3, 'y': 4}],
    }])
    shape = load_document(path).shapes[0]
    assert shape.kind is ShapeKind.LINE
    assert shape.id == 'shape-1'
    assert shape.name == '折线'


def test_an_unknown_shape_type_is_rejected(tmp_path: Path) -> None:
    _document, path = save_sample(tmp_path)
    rewrite_manifest(path, shapes=[{
        'id': 'shape-1', 'name': 'circle', 'type': 'circle',
        'vertices': [],
    }])
    with pytest.raises(StorageError):
        load_document(path)


def test_two_basemaps_with_one_identifier_are_rejected(
        tmp_path: Path) -> None:
    _document, path = save_sample(tmp_path)
    manifest = manifest_of(path)
    basemaps = manifest['basemaps']
    rewrite_manifest(path, basemaps=[basemaps[0], dict(basemaps[0])])
    with pytest.raises(StorageError):
        load_document(path)


def test_shapes_without_a_basemap_are_rejected(tmp_path: Path) -> None:
    _document, path = save_sample(tmp_path)
    rewrite_manifest(path, basemaps=[], active_basemap_id=None)
    with pytest.raises(StorageError):
        load_document(path)


def test_a_file_that_is_not_an_archive_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'doc.rsroi'
    path.write_text('not a zip archive', encoding='utf-8')
    with pytest.raises(StorageError):
        load_document(path)


def test_an_archive_without_a_manifest_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'doc.rsroi'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('basemaps/0.png', b'')
    with pytest.raises(StorageError):
        load_document(path)


def test_the_data_entry_of_the_old_format_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'doc.rsroi'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(
            'data.json',
            '{"format": "rsroi", "version": 1, "basemaps": [],'
            ' "shapes": []}')
    with pytest.raises(StorageError):
        load_document(path)


def test_an_unsupported_version_is_rejected(tmp_path: Path) -> None:
    _document, path = save_sample(tmp_path)
    rewrite_manifest(path, format_version=99)
    with pytest.raises(StorageError):
        load_document(path)


@pytest.mark.parametrize('kind', ['line', 'polyline'])
def test_a_line_of_three_vertices_is_rejected(
        tmp_path: Path, kind: str) -> None:
    _document, path = save_sample(tmp_path)
    rewrite_manifest(path, shapes=[{
        'id': 'shape-1',
        'name': 'line',
        'type': kind,
        'vertices': [{'x': 0, 'y': 0}, {'x': 1, 'y': 1}, {'x': 2, 'y': 2}],
    }])
    with pytest.raises(StorageError):
        load_document(path)
