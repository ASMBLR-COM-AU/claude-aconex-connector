"""Turning Aconex's XML into small, plain results for Claude.

Shapes marked "live" were checked against the live API by the Aconex skill
(Oct 2026). Others follow Oracle's guides only and are confirmed in stage 5.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

MAX_TEXT = 500  # longest single value passed back to Claude

# Invisible or direction-changing characters are removed from everything
# Aconex sends back, before Claude sees it: control characters, Unicode
# "format" characters (right-to-left overrides, zero-width characters and the
# invisible "tag" characters that can hide instructions readable by an AI but
# not by a person), and line/paragraph separators. Ordinary new lines and tabs
# are kept.
_HIDDEN_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")
_ASCII_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(value: str) -> str:
    if value.isascii():
        return _ASCII_CONTROLS.sub("", value)
    return "".join(ch for ch in value
                   if ch in "\n\t" or unicodedata.category(ch) not in _HIDDEN_CATEGORIES)


def clean_tree(root: ET.Element) -> ET.Element:
    """clean_text applied to every text, tail and attribute in an XML reply."""
    for el in root.iter():
        if el.text:
            el.text = clean_text(el.text)
        if el.tail:
            el.tail = clean_text(el.tail)
        for key, value in el.attrib.items():
            el.attrib[key] = clean_text(value)
    return root


def clean_value(value):
    """clean_text applied to every string (keys too) in a JSON reply."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [clean_value(v) for v in value]
    if isinstance(value, dict):
        return {clean_text(str(k)): clean_value(v) for k, v in value.items()}
    return value


def text(el: ET.Element | None, path: str) -> str:
    if el is None:
        return ""
    return (el.findtext(path) or "").strip()


def first(el: ET.Element | None, *paths: str) -> str:
    for path in paths:
        value = text(el, path)
        if value:
            return value
    return ""


def person(el: ET.Element | None) -> str:
    """'Name (Organisation)' from a user-details element (live)."""
    if el is None:
        return ""
    name = first(el, "Name", "FullName", "UserName")
    org = text(el, "OrganizationName")
    return f"{name} ({org})" if name and org else name or org


def _label(tag: str) -> str:
    """CamelCase element name to snake_case: DocumentNumber -> document_number."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", tag).lower()


def flatten(el: ET.Element, limit: int = 80) -> dict:
    """Every leaf value under an element, keyed by a readable path. For
    responses whose exact shape isn't confirmed: Claude still sees every
    field, and nothing depends on guessing element names."""
    out: dict = {}

    def walk(node: ET.Element, prefix: str) -> None:
        for key, value in node.attrib.items():
            if len(out) < limit and value.strip():
                out[f"{prefix}{_label(key)}"] = value.strip()[:MAX_TEXT]
        children = list(node)
        if not children:
            value = (node.text or "").strip()
            if value and len(out) < limit:
                key = prefix.rstrip(".") or _label(node.tag)
                if key in out:
                    out[key] = f"{out[key]}; {value[:MAX_TEXT]}"
                else:
                    out[key] = value[:MAX_TEXT]
            return
        for child in children:
            walk(child, f"{prefix}{_label(child.tag)}.")

    walk(el, "")
    return out


def page_info(root: ET.Element) -> dict:
    """Paging attributes Aconex puts on search results (live)."""
    info = {}
    for attr, key in (("TotalResults", "total"), ("CurrentPage", "page"),
                      ("PageNumber", "page"), ("TotalPages", "pages")):
        value = root.get(attr)
        if value and key not in info:
            info[key] = int(value) if value.isdigit() else value
    return info


def schema_values(schema: ET.Element, identifier: str) -> dict:
    """{name: id} for one field of a register or mail schema (live)."""
    for field in schema.iter():
        if text(field, "Identifier") != identifier:
            continue
        values = {
            text(v, "Value"): text(v, "Id")
            for v in field.iter("SchemaValue")
            if text(v, "Value") and text(v, "Id")
        }
        if values:
            return values
    return {}


def lucene_phrase(value: str) -> str:
    """Escape for a quoted Lucene phrase: only `"` and `\\` (live: escaping
    more breaks matching)."""
    return re.sub(r'(["\\])', r"\\\1", value)


class _HTMLText(HTMLParser):
    _BLOCKS = {"p", "div", "li", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
    _HIDDEN = {"style", "script", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list = []
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._HIDDEN:
            self._hidden += 1
        elif tag in self._BLOCKS or tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._hidden:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Mail bodies are HTML (live); plain text passes through unchanged."""
    parser = _HTMLText()
    parser.feed(markup)
    parser.close()
    # Entities such as &#8238; are only decoded here, so clean again.
    out = clean_text("".join(parser.parts)).replace("\xa0", " ")
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r" *\n *", "\n", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()
