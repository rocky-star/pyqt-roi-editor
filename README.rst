ReadMe for PyQt ROI Editor
==========================

*In other languages:* `汉语 (简化字) <README.zh-Hans.rst>`__

Introduction
------------

PyQt ROI Editor is a small desktop application for drawing regions of
interest (ROIs) over images.  It is written in Python with PySide6, and
keeps a document in a single ``.rsroi`` file.

A document holds one or more *basemaps*, the images the shapes are drawn
over, and any number of *shapes*, each a line or a polygon marking a region
of the basemap on show.  The interface follows the language of the system,
and a Simplified Chinese translation ships with the application.

Installation & Usage
--------------------

The editor needs Python 3.12 or later, and PySide6 6.11.2 or later is its
only dependency.  Install the distribution from the repository and run the
console script it provides:

.. code-block:: console

   $ pip install git+https://github.com/rocky-star/pyqt-roi-editor.git
   $ pyqt-roi-editor

The editing area sits between two docks, the list of basemaps and the tree
of shapes naming every vertex with its X and Y, and a session goes like
this: **File > New** starts an empty document; **Basemap > Add
Basemap...** brings in an image to draw over, and the basemap list
switches between the images of a document holding several; **Shape > Add
Shape > Line** (or **Polygon**) starts a shape; **Shape > Shape
Properties...** renames the selected shape; **File > Save** writes the
whole document as one ``.rsroi`` file.

Drawing
  A shape is started from the *Shape* menu or the context menu of the
  canvas, and its vertices are clicked in the view or typed into a
  floating palette.  The palette reads ``10, 20``, ``10 20``, ``(10, 20)``
  and ``[10, 20]`` alike, and a digit or a minus sign opens it; Enter
  finishes a polygon, and Esc cancels what is being drawn.

Editing
  A shape, or one handle of it, is dragged to move it, while vertices are
  added and removed from the *Vertex* menu.  A vertex is kept on the
  basemap unless the properties of its shape allow vertices outside it,
  which typing such a coordinate turns on by itself.

Navigating
  The *Toolbox* menu chooses what the primary button does: select and
  move shapes, move the view, or zoom it.  The third button moves the
  view whatever the tool is, the zoom tool fills the view with an area
  framed by the secondary button, and the status bar zoom box takes a
  preset, a typed percentage such as ``149%``, or a fit to the width or
  window.

Dumping
  *Shape > Dump Shape* writes the vertices of a shape as a compact list,
  ``[[10, 10], [20, 20]]``, or as the YAML block sequence of one item per
  line, and copies either of them to the clipboard.

Licensing
---------

PyQt ROI Editor is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option)
any later version.

It is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
details.

The full text of the licence is in ``LICENSE.txt``, and the terms are
also available at https://www.gnu.org/licenses/gpl-3.0.html.

Copyright (C) Rocky☆Star <rocky-star22@outlook.com>
