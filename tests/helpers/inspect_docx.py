"""Read-only structural evidence for the synthetic document round-trip checks.

This is an acceptance inspector, not a DOCX editor or a fidelity guarantee.
Usage: python3 inspect_docx.py FILE.docx [OTHER.docx ...]
"""

import hashlib
import json
import posixpath
import sys
import zipfile
from pathlib import Path

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "r": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def inspect(path):
    path = Path(path)
    with zipfile.ZipFile(path) as package:
        assert package.testzip() is None
        parts = {name: package.read(name) for name in package.namelist()}
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    xml = {
        name: etree.fromstring(data, parser)
        for name, data in parts.items()
        if name.endswith((".xml", ".rels"))
    }
    body = xml["word/document.xml"]

    def text(node):
        return "".join(node.xpath(".//w:t/text() | .//w:delText/text()", namespaces=NS))

    def fragment(node):
        return {
            "id": node.get("{%s}id" % NS["w"]),
            "author": node.get("{%s}author" % NS["w"]),
            "date": node.get("{%s}date" % NS["w"]),
            "text": text(node),
        }

    missing_targets = []
    for name, root in xml.items():
        if not name.endswith(".rels"):
            continue
        base = "" if name == "_rels/.rels" else posixpath.dirname(posixpath.dirname(name))
        for rel in root:
            if rel.get("TargetMode") == "External":
                continue
            target = rel.get("Target", "").split("#")[0]
            resolved = posixpath.normpath(posixpath.join(base, target)).lstrip("/")
            if target and resolved not in parts:
                missing_targets.append({"part": name, "target": target})

    return {
        "file": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "parts": sorted(parts),
        "text": text(body),
        "paragraphs": [text(p) for p in body.xpath(".//w:body/w:p", namespaces=NS)],
        "table_cells": [text(p) for p in body.xpath(".//w:tc", namespaces=NS)],
        "math": [
            {"text": "".join(m.xpath(".//m:t/text()", namespaces=NS)),
             "elements": [etree.QName(e).localname for e in m.iter() if e.tag.startswith("{%s}" % NS["m"])]}
            for m in body.xpath(".//m:oMath", namespaces=NS)
        ],
        "fields": body.xpath(".//w:fldSimple/@w:instr | .//w:instrText/text()", namespaces=NS),
        "bookmarks": body.xpath(".//w:bookmarkStart/@w:name", namespaces=NS),
        "headers": [text(e) for n, e in xml.items() if n.startswith("word/header") and n.endswith(".xml")],
        "footers": [text(e) for n, e in xml.items() if n.startswith("word/footer") and n.endswith(".xml")],
        "footnotes": [text(e) for n, e in xml.items() if n == "word/footnotes.xml"],
        "footnote_anchors": body.xpath(".//w:footnoteReference/@w:id", namespaces=NS),
        "images": sorted(hashlib.sha256(data).hexdigest() for n, data in parts.items() if n.startswith("word/media/")),
        "custom_xml": {n: data.decode("utf-8", errors="replace") for n, data in parts.items() if n.startswith("customXml/") and n.endswith(".xml")},
        "comments": [fragment(c) for n, e in xml.items() if n == "word/comments.xml" for c in e],
        "comment_starts": body.xpath(".//w:commentRangeStart/@w:id", namespaces=NS),
        "comment_ends": body.xpath(".//w:commentRangeEnd/@w:id", namespaces=NS),
        "comment_refs": body.xpath(".//w:commentReference/@w:id", namespaces=NS),
        "insertions": [fragment(e) for e in body.xpath(".//w:ins", namespaces=NS)],
        "deletions": [fragment(e) for e in body.xpath(".//w:del", namespaces=NS)],
        "missing_relationship_targets": missing_targets,
    }


if __name__ == "__main__":
    print(json.dumps([inspect(p) for p in sys.argv[1:]], ensure_ascii=False, indent=2))
