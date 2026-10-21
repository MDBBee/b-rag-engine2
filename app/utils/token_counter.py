import logging

import tiktoken

logger = logging.getLogger(__name__)


def get_encoder(model_name: str) -> tiktoken.Encoding:
    """Get appropriate tokenizer based on model name from config."""
    model_lower = model_name.lower()
    
    # OpenAI models - use model-specific tokenizer
    if any(m in model_lower for m in ["openai", "gpt-4", "gpt-3.5", "gpt-4o"]):
        try:
            return tiktoken.encoding_for_model("gpt-4")
        except Exception:
            logger.debug("tiktoken encoding_for_model('gpt-4') failed, falling back")
    
    # Text embedding models
    if "text-embedding" in model_lower:
        return tiktoken.get_encoding("cl100k_base")
    
    # Fallback for all other models (Claude, Llama, Mistral, etc.)
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model_name: str) -> int:
    """Count tokens using model-appropriate tokenizer."""
    if not text:
        return 0
    
    try:
        encoder = get_encoder(model_name)
        return len(encoder.encode(text))
    except Exception as e:
        logger.warning(f"Token counting failed for {model_name}: {e}")
        return 0
