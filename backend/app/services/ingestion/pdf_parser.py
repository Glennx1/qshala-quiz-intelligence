import logging
from pathlib import Path
from typing import List, Dict, Any
from backend.app.config import settings

logger = logging.getLogger(__name__)

class PDFParser:
    """
    Extracts structured pages, text, and metadata from PDF quiz decks.
    """
    def __init__(self, file_path: str, document_id: str):
        self.file_path = file_path
        self.document_id = document_id

    def parse(self) -> List[Dict[str, Any]]:
        slides_data = []
        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber is not installed or failed to load")
            return slides_data

        with pdfplumber.open(self.file_path) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                extracted_text = page.extract_text() or ""
                lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
                title = lines[0] if lines else f"Page {page_idx}"

                slides_data.append({
                    "slide_number": page_idx,
                    "title": title,
                    "extracted_text": extracted_text.strip(),
                    "speaker_notes": "",
                    "image_paths": [],
                    "has_images": len(page.images) > 0,
                    "metadata_json": {
                        "width": float(page.width),
                        "height": float(page.height),
                        "image_count": len(page.images)
                    }
                })

        return slides_data
