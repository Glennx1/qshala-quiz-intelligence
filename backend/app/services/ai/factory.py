import logging
from backend.app.config import settings
from backend.app.services.ai.base import LLMProvider, EmbeddingProvider
from backend.app.services.ai.local_provider import LocalLLMProvider, LocalEmbeddingProvider
from backend.app.services.ai.gemini_provider import GeminiLLMProvider, GeminiEmbeddingProvider
from backend.app.services.ai.openai_provider import OpenAILLMProvider, OpenAIEmbeddingProvider

logger = logging.getLogger(__name__)

def get_llm_provider() -> LLMProvider:
    provider = settings.LLM_PROVIDER.lower()
    if provider == "gemini" and settings.GEMINI_API_KEY:
        try:
            return GeminiLLMProvider()
        except Exception as e:
            logger.warning(f"Failed to initialize GeminiLLMProvider ({e}), falling back to LocalLLMProvider")
    elif provider == "openai" and settings.OPENAI_API_KEY:
        try:
            return OpenAILLMProvider()
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAILLMProvider ({e}), falling back to LocalLLMProvider")
            
    return LocalLLMProvider()

def get_embedding_provider() -> EmbeddingProvider:
    provider = settings.EMBEDDING_PROVIDER.lower()
    if provider == "gemini" and settings.GEMINI_API_KEY:
        try:
            return GeminiEmbeddingProvider()
        except Exception as e:
            logger.warning(f"Failed to initialize GeminiEmbeddingProvider ({e}), falling back to LocalEmbeddingProvider")
    elif provider == "openai" and settings.OPENAI_API_KEY:
        try:
            return OpenAIEmbeddingProvider()
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAIEmbeddingProvider ({e}), falling back to LocalEmbeddingProvider")

    return LocalEmbeddingProvider(dim=settings.EMBEDDING_DIM)
