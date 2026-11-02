"""Turning Aconex's XML into small, plain results for Claude.

Shapes marked "live" were checked against the live API by the Aconex skill
(Oct 2026). Others follow Oracle's guides only and are confirmed in stage 5.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

MAX_TEXT = 500  # longest single value passed back to Claude


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
