from app.services.embedder import EmbedderService
from app.services.vector_store import VectorStoreService

# Create singletons to reuse client connections and embedding models
_embedder_service = EmbedderService()
_vector_store_service = VectorStoreService()

def get_embedder_service() -> EmbedderService:
    """
    Dependency injection token returning stateless EmbedderService instance.
    """
    return _embedder_service

async def get_vector_store_service() -> VectorStoreService:
    """
    Dependency injection token returning initialized VectorStoreService instance.
    Guarantees target Qdrant collection is created before query routing.
    """
    global _vector_store_service
    # Perform collection verification on-demand if not already done
    if not getattr(_vector_store_service, "_initialized_collection", False):
        await _vector_store_service.init_collection()
    return _vector_store_service
