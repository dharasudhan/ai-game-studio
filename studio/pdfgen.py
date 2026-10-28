"""Tiny dependency-free PDF writer for audit reports (A4, Helvetica, word-wrapped text).

Enough for a readable report on any Mac without pandoc/LaTeX. Markdown-ish input: '# ' / '## ' headings,
'- ' bullets, '**x**' bold markers are stripped, everything else is a paragraph line.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

W, H, M = 595, 842, 50          # A4 points, margin


def _esc(s: str) -> str:
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _lines(md: str) -> list[tuple[str, int, str]]:
    """-> (font F1 regular/F2 bold, size, text)"""
    out: list[tuple[str, int, str]] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            continue
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", line).replace("`", "")
        if clean.startswith("# "):
            out += [("F2", 16, t) for t in textwrap.wrap(clean[2:], 60)] + [("F1", 6, "")]
        elif clean.startswith("## "):
            out += [("F1", 6, "")] + [("F2", 12.5, t) for t in textwrap.wrap(clean[3:], 75)]
        elif clean.startswith("### "):
            out += [("F2", 11, t) for t in textwrap.wrap(clean[4:], 85)]
        elif clean.startswith(("- ", "* ")):
            w = textwrap.wrap(clean[2:], 92) or [""]
            out += [("F1", 9.5, "- " + w[0])] + [("F1", 9.5, "  " + t) for t in w[1:]]
        elif clean.startswith("|"):
            cells = [c.strip() for c in clean.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            w = textwrap.wrap("  |  ".join(cells), 100) or [""]
            out += [("F1", 8.5, t) for t in w]
        elif not clean.strip():
            out.append(("F1", 5, ""))
        else:
            out += [("F1", 9.5, t) for t in (textwrap.wrap(clean, 95) or [""])]
    return out


def markdown_to_pdf(md: str, path: Path, title: str = "Report") -> Path:
    pages: list[list[str]] = [[]]
    y = H - M
    for font, size, text in _lines(md):
        lh = size * 1.35
        if y - lh < M:
            pages.append([])
            y = H - M
        y -= lh
        if text:
            pages[-1].append(f"BT /{font} {size} Tf {M} {y:.1f} Td ({_esc(text)}) Tj ET")
    objs: list[bytes] = []

    def add(b: str | bytes) -> int:
        objs.append(b.encode("latin-1") if isinstance(b, str) else b)
        return len(objs)

    cat = add("")  # placeholder 1
    pages_id = add("")  # placeholder 2
    f1 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    n = len(pages)
    for i, ops in enumerate(pages, 1):
        ops = ops + [f"BT /F1 8 Tf {M} 25 Td ({_esc(title)}  -  page {i}/{n}) Tj ET"]
        stream = "\n".join(ops).encode("latin-1", "replace")
        c = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {W} {H}] "
                        f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {c} 0 R >>"))
    objs[cat - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objs[pages_id - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {cat} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path
