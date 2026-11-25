"""Seeded one-page PDFs for the Fixture world: one with a text layer, one without (a scan's)."""


def _pdf(content: bytes) -> bytes:
    """A valid one-page PDF whose page draws `content` (a content stream), Helvetica as its font."""
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length %d>>stream\n" % len(content) + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def text_pdf(lines: list[str]) -> bytes:
    """A PDF with `lines` (ASCII) printed top to bottom in its text layer."""
    shown = b" T* ".join(b"(" + line.encode("ascii").replace(b"(", rb"\(").replace(b")", rb"\)") + b") Tj"
                         for line in lines)
    return _pdf(b"BT /F1 12 Tf 14 TL 72 770 Td " + shown + b" ET")


def no_text_pdf() -> bytes:
    """A PDF whose page only paints (a grey box, as a scan's image would): no text to extract."""
    return _pdf(b"0.5 g 72 400 451 370 re f")
