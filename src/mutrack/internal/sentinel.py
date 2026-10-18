"""Distinguish omitted arguments from explicitly supplied None values."""


class _Missing:
    """Represent the absence of an optional argument distinctly from None."""

    __slots__ = ()


MISSING = _Missing()
