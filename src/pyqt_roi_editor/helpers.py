"""Small helpers shared by the rest of the application."""

__all__ = ['qformat']

import re
from collections.abc import Sequence

_PLACEHOLDER = re.compile(r'%(\d+)')


def qformat(
        template: str,
        values: Sequence[object], specs: Sequence[str] = ()) -> str:
    """Format a Qt-style message template with Python's machinery.

    ``%1``, ``%2`` and so on are replaced by the item of `values` at
    the same position: ``%1`` takes the first item, ``%2`` the second,
    and so on.  A placeholder with no matching item is left as it is,
    so ``%3`` in a message given two values stays ``%3``, and so does
    the ``%0`` Qt does not define.  Every other character, including a
    ``%`` not followed by digits, is copied verbatim.

    Parameters
    ----------
    template : str
        The message to format, holding ``%1``, ``%2`` and so on as
        placeholders.
    values : Sequence[object]
        The items the placeholders refer to, by position.
    specs : Sequence[str], optional
        The specifier rendering each value, by position, written as it
        would be inside a ``str.format()`` replacement field: ``''``
        renders the value plainly, ``'!r'`` uses ``repr()``, and
        ``':.2f'`` rounds a float.  A leading colon may be left out,
        and the sequence may be shorter than `values`, the specifiers
        it lacks being taken as ``''``.  Defaults to empty.

    Returns
    -------
    str
        The formatted message.

    Notes
    -----
    The placeholders are replaced one by one, so braces in `template`
    or in a formatted value are copied literally instead of being read
    as further replacement fields.

    Examples
    --------
    >>> qformat("Cannot open %1: %2", ['a.txt', 'bad magic'],
    ...         ['', '!r'])
    "Cannot open a.txt: 'bad magic'"
    """

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if not 1 <= index <= len(values):
            return match.group(0)
        spec = specs[index - 1] if index <= len(specs) else ''
        if spec and spec[0] not in '!:':
            spec = ':' + spec
        field = '{0' + spec + '}'
        return field.format(values[index - 1])

    return _PLACEHOLDER.sub(replace, template)
