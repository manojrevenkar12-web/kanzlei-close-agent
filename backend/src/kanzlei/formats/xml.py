"""Namespace-agnostic helpers over defusedxml (no entity expansion, no external DTDs)."""

from __future__ import annotations

from collections.abc import Iterator
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET


class FormatError(ValueError):
    """The file is not what it claims to be, or is missing what makes it usable."""


def parse_xml(data: bytes) -> Element:
    try:
        root: Element = SafeET.fromstring(data)
    except Exception as e:  # defusedxml raises several types
        raise FormatError(f"not well-formed XML: {e}") from e
    return root


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def kids(el: Element | None, name: str) -> Iterator[Element]:
    if el is None:
        return
    for c in el:
        if local(c.tag) == name:
            yield c


def kid(el: Element | None, path: str) -> Element | None:
    """First element along a '/'-separated path of local names."""
    cur = el
    for part in path.split("/"):
        if cur is None:
            return None
        cur = next(kids(cur, part), None)
    return cur


def text(el: Element | None, path: str = "") -> str | None:
    node = kid(el, path) if path else el
    if node is None or node.text is None:
        return None
    t = node.text.strip()
    return t or None


def every(el: Element | None, path: str) -> list[Element]:
    """All elements matching the last step of a path (earlier steps take the first match)."""
    parts = path.split("/")
    parent = kid(el, "/".join(parts[:-1])) if len(parts) > 1 else el
    return list(kids(parent, parts[-1]))
