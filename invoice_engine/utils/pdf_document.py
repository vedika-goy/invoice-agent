"""PDF text and images via PyMuPDF."""
import pymupdf

# Fewer extractable characters than this means the pages are images, i.e. a scan.
MIN_TEXT_LAYER_CHARS = 40


def open_pdf_document(pdf_bytes: bytes) -> pymupdf.Document:
    """Raises RuntimeError (pymupdf.FileDataError) when the bytes are not a readable PDF."""
    return pymupdf.open(stream=pdf_bytes, filetype="pdf")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    with open_pdf_document(pdf_bytes) as document:
        return "\n".join(page.get_text("text") for page in document)


def has_text_layer(pdf_bytes: bytes) -> bool:
    return len("".join(extract_pdf_text(pdf_bytes).split())) >= MIN_TEXT_LAYER_CHARS


def count_pdf_pages(pdf_bytes: bytes) -> int:
    with open_pdf_document(pdf_bytes) as document:
        return document.page_count


def render_pdf_page_png(pdf_bytes: bytes, page_index: int = 0, zoom: float = 1.5) -> bytes:
    with open_pdf_document(pdf_bytes) as document:
        pixmap = document[page_index].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pixmap.tobytes("png")
