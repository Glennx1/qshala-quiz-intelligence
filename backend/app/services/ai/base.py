from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class LLMProvider(ABC):
    @abstractmethod
    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generate plain text from prompt."""
        pass

    @abstractmethod
    async def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Generate structured JSON response from prompt."""
        pass

    async def generate_multimodal(
        self,
        prompt: str,
        media_parts: List[Dict[str, str]],
        system_instruction: Optional[str] = None
    ) -> str:
        """Generate text from multimodal inputs (inline images/audio base64 parts)."""
        return await self.generate_text(prompt, system_instruction=system_instruction)

    async def describe_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        """Extract visual OCR and content description from image bytes."""
        return ""

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/mp3") -> str:
        """Transcribe spoken words and audio cues from audio bytes."""
        return ""

class EmbeddingProvider(ABC):
    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """Generate vector embedding for single text string."""
        pass

    @abstractmethod
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate vector embeddings for multiple text strings in batch."""
        pass
