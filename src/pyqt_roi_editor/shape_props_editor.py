"""The dialog editing one shape's properties."""

__all__ = ['ShapePropsEditor']

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHeaderView, QWidget

from pyqt_roi_editor.document import Shape
from pyqt_roi_editor.helpers import format_number, qformat
from pyqt_roi_editor.ui_shapepropseditor import Ui_ShapePropsEditor

from __feature__ import snake_case, true_property  # pyright: ignore[reportUnusedImport]


class ShapePropsEditor(QDialog):
    """The properties of one shape: its name, its flag, its vertices.

    The vertices are shown for reference only; they are edited in the
    view, not here.
    """

    def __init__(self, shape: Shape, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui = Ui_ShapePropsEditor()
        self.ui.setupUi(self)  # pyright: ignore[reportUnknownMemberType]
        self._original_name = shape.name
        self.window_title = qformat(self.__tr("%1 Properties"), [shape.name])
        self.ui.name_edit.text = shape.name
        self.ui.allow_vertices_outside_basemap_check_box.checked = (
            shape.allow_vertices_outside_basemap)
        self.ui.vertices_view.edit_triggers = (
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ui.vertices_view.set_model(self._vertices_model(shape))
        self.ui.vertices_view.horizontal_header().set_section_resize_mode(
            QHeaderView.ResizeMode.Stretch)

    @property
    def shape_name(self) -> str:
        """Return the edited name, or the original one when blank."""
        return self.ui.name_edit.text.strip() or self._original_name

    @property
    def allow_vertices_outside_basemap(self) -> bool:
        """Return whether vertices outside the basemap are allowed."""
        return self.ui.allow_vertices_outside_basemap_check_box.checked

    def _vertices_model(self, shape: Shape) -> QStandardItemModel:
        """Return a model listing the X and Y of every vertex."""
        model = QStandardItemModel(0, 2, self)
        model.set_horizontal_header_labels([self.__tr("X"), self.__tr("Y")])
        for vertex in shape.vertices:
            items = [
                QStandardItem(format_number(vertex.x())),
                QStandardItem(format_number(vertex.y())),
            ]
            for item in items:
                item.set_editable(False)
            model.append_row(items)
        return model

    def __tr(self,
             source_text: str, disambiguation: str | None = None,
             n: int = -1) -> str:
        return QCoreApplication.translate(
            'ShapePropsEditor', source_text, disambiguation, n)
