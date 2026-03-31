import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


PDF_READ_PREFIX = "pdf:"
MANIFEST_VERSION = 1
OCR_THRESHOLD_NON_WS = 30


@dataclass
class PdfWindow:
    text: str
    first_page: int
    last_page: int
    total_pages: int
    next_page: int | None


def marker_for_path(pdf_path: Path) -> str:
    return f"{PDF_READ_PREFIX}{pdf_path}"


def is_pdf_marker(path: str | None) -> bool:
    return bool(path) and path.startswith(PDF_READ_PREFIX)


def marker_path(path: str) -> Path:
    return Path(path[len(PDF_READ_PREFIX):])


def read_pdf_window(pdf_path: Path, research_root: Path, start_page: int, char_budget: int) -> PdfWindow:
    cache = PdfCache(pdf_path, research_root)
    start_page = max(start_page, 1)
    if start_page > cache.page_count:
        raise ValueError(f"No more PDF pages remain in {pdf_path}.")

    sections: list[str] = []
    total_chars = 0
    current_page = start_page
    last_page = start_page

    while current_page <= cache.page_count:
        page_text = cache.page_text(current_page)
        section = f"--- Page {current_page} of {cache.page_count} ---\n{page_text.rstrip()}"
        section_chars = len(section)
        fits_budget = total_chars + section_chars <= char_budget
        if sections and not fits_budget:
            break
        sections.append(section)
        total_chars += section_chars
        last_page = current_page
        current_page += 1

    next_page = current_page if last_page < cache.page_count else None
    return PdfWindow(
        text="\n\n".join(sections),
        first_page=start_page,
        last_page=last_page,
        total_pages=cache.page_count,
        next_page=next_page,
    )


def window_footer(window: PdfWindow) -> str:
    if window.next_page is not None:
        return (
            f"[Showing PDF pages {window.first_page}-{window.last_page} of "
            f"{window.total_pages}. NEXT: READ_MORE for page {window.next_page}.]"
        )
    return (
        f"[End of PDF (pages {window.first_page}-{window.last_page} of "
        f"{window.total_pages}).]"
    )


class PdfCache:
    def __init__(self, pdf_path: Path, research_root: Path):
        self.pdf_path = pdf_path.resolve()
        self.research_root = research_root.resolve()
        self.cache_root = self.research_root / ".pdf_cache"
        self.cache_root.mkdir(exist_ok=True)
        self.cache_dir = self.cache_root / doc_id(str(self.pdf_path))
        self.cache_dir.mkdir(exist_ok=True)

        stat = self.pdf_path.stat()
        source_mtime_ms = stat.st_mtime_ns // 1_000_000
        manifest = {
            "version": MANIFEST_VERSION,
            "source_path": str(self.pdf_path),
            "source_size": stat.st_size,
            "source_mtime_ms": source_mtime_ms,
            "page_count": 0,
        }

        manifest_path = self.cache_dir / "manifest.json"
        cached = None
        if manifest_path.exists():
            try:
                cached = json.loads(manifest_path.read_text())
            except Exception:
                cached = None

        if (
            cached
            and cached.get("version") == MANIFEST_VERSION
            and cached.get("source_path") == manifest["source_path"]
            and cached.get("source_size") == manifest["source_size"]
            and cached.get("source_mtime_ms") == manifest["source_mtime_ms"]
        ):
            self.manifest = cached
        else:
            purge_cached_pages(self.cache_dir)
            manifest["page_count"] = pdf_page_count(self.pdf_path)
            manifest_path.write_text(json.dumps(manifest, indent=2))
            self.manifest = manifest

        self.page_count = int(self.manifest["page_count"])

    def page_text(self, page: int) -> str:
        page_path = self.cache_dir / f"page-{page:04}.txt"
        extracted = page_path.read_text() if page_path.exists() else ""
        if not extracted:
            extracted = normalize_page_text(
                run_utf8_command(
                    "pdftotext",
                    [
                        "-layout",
                        "-enc",
                        "UTF-8",
                        "-q",
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        str(self.pdf_path),
                        "-",
                    ],
                    "extract PDF text",
                )
            )
            page_path.write_text(extracted)

        if non_whitespace_len(extracted) >= OCR_THRESHOLD_NON_WS:
            return non_empty_page_text(extracted)

        try:
            ocr_text = ocr_page_text(self.pdf_path, page)
        except Exception as exc:
            return annotate_sparse_page(self.pdf_path, page, extracted, str(exc))

        if non_whitespace_len(ocr_text) > non_whitespace_len(extracted):
            page_path.write_text(ocr_text)
            return non_empty_page_text(ocr_text)
        return annotate_sparse_page(self.pdf_path, page, extracted, None)


def purge_cached_pages(cache_dir: Path) -> None:
    for page_path in cache_dir.glob("page-*.txt"):
        page_path.unlink(missing_ok=True)


def pdf_page_count(pdf_path: Path) -> int:
    output = run_utf8_command("pdfinfo", [str(pdf_path)], "inspect PDF metadata")
    for line in output.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise ValueError(f"Could not determine page count for {pdf_path}.")


def ocr_page_text(pdf_path: Path, page: int) -> str:
    with tempfile.TemporaryDirectory(prefix="minime-pdf-ocr-") as temp_dir:
        temp_root = Path(temp_dir)
        image_base = temp_root / "page"
        image_path = temp_root / "page.png"
        run_utf8_command(
            "pdftoppm",
            [
                "-f",
                str(page),
                "-l",
                str(page),
                "-r",
                "200",
                "-png",
                "-singlefile",
                str(pdf_path),
                str(image_base),
            ],
            "render PDF page for OCR",
        )
        return normalize_page_text(
            run_utf8_command(
                "tesseract",
                [str(image_path), "stdout"],
                "OCR PDF page",
            )
        )


def run_utf8_command(command: str, args: list[str], action: str) -> str:
    if shutil.which(command) is None:
        raise RuntimeError(f"{action} requires `{command}`, but it is not installed.")
    result = subprocess.run(
        [command, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"`{command}` exited with code {result.returncode}."
        raise RuntimeError(f"{action} failed: {detail}")
    return result.stdout


def normalize_page_text(text: str) -> str:
    return text.replace("\f", "\n").replace("\r\n", "\n")


def annotate_sparse_page(pdf_path: Path, page: int, extracted: str, reason: str | None) -> str:
    body = extracted.rstrip() if extracted.strip() else "[No extractable text on this page.]"
    if reason:
        note = f"[Page {page} of {pdf_path} may need OCR for a fuller read. {reason}]"
    else:
        note = f"[Page {page} of {pdf_path} appears sparse. OCR did not improve extraction.]"
    return f"{body}\n\n{note}"


def non_empty_page_text(text: str) -> str:
    return text if text.strip() else "[No extractable text on this page.]"


def non_whitespace_len(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def doc_id(source_path: str) -> str:
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()
