import os
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from backend.app.config import settings

logger = logging.getLogger(__name__)

class PPTXParser:
    """
    Extracts structured content, text, speaker notes, tables,
    and embedded images from PPTX files.
    """
    def __init__(self, file_path: str, document_id: str):
        self.file_path = file_path
        self.document_id = document_id
        self.output_img_dir = settings.SLIDES_DIR / document_id
        self.output_img_dir.mkdir(parents=True, exist_ok=True)

    def parse(self) -> List[Dict[str, Any]]:
        prs = Presentation(self.file_path)
        slides_data = []

        for slide_idx, slide in enumerate(prs.slides, start=1):
            slide_text_chunks = []
            title = None
            speaker_notes = ""
            image_paths = []

            # Extract title if present
            if slide.shapes.title and slide.shapes.title.has_text_frame:
                title = slide.shapes.title.text_frame.text.strip()

            # Extract speaker notes
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                speaker_notes = slide.notes_slide.notes_text_frame.text.strip()

            # Iterate shapes
            img_counter = 1
            for shape in slide.shapes:
                # Text frames
                if shape.has_text_frame:
                    shape_text = shape.text_frame.text.strip()
                    if shape_text:
                        slide_text_chunks.append(shape_text)

                # Tables
                elif shape.has_table:
                    table_rows = []
                    for row in shape.table.rows:
                        row_cells = [cell.text.strip() for cell in row.cells]
                        table_rows.append(" | ".join(row_cells))
                    if table_rows:
                        slide_text_chunks.append("\n".join(table_rows))

                # Images
                elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    try:
                        image = shape.image
                        ext = image.ext
                        img_filename = f"slide_{slide_idx}_img_{img_counter}.{ext}"
                        img_path = self.output_img_dir / img_filename
                        with open(img_path, "wb") as f:
                            f.write(image.blob)
                        # Relative path for frontend serving
                        rel_path = f"/static/slides/{self.document_id}/{img_filename}"
                        image_paths.append(rel_path)
                        img_counter += 1
                    except Exception as e:
                        logger.warning(f"Could not extract image from slide {slide_idx}: {e}")

            # Deduplicate text chunks while preserving order
            unique_chunks = []
            seen = set()
            for chunk in slide_text_chunks:
                norm = chunk.strip()
                if norm and norm not in seen:
                    unique_chunks.append(norm)
                    seen.add(norm)

            combined_text = "\n\n".join(unique_chunks)

            slides_data.append({
                "slide_number": slide_idx,
                "title": title or (unique_chunks[0] if unique_chunks else f"Slide {slide_idx}"),
                "extracted_text": combined_text,
                "speaker_notes": speaker_notes,
                "image_paths": image_paths,
                "has_images": len(image_paths) > 0,
                "metadata_json": {
                    "shape_count": len(slide.shapes),
                    "has_notes": bool(speaker_notes)
                }
            })

        return slides_data
