from unittest.mock import MagicMock, patch


def test_query_does_not_call_ensure_collection():
    from app.infra.vector_store.qdrant_store import QdrantStore

    store = QdrantStore()
    mock_client = MagicMock()
    mock_client.search.return_value = []
    store._client = mock_client

    with patch.object(store, "_ensure_collection") as mock_ensure:
        store.query(query_embedding=[0.1] * 768, top_k=5, collection_name="manual_chunks")

    mock_ensure.assert_not_called()
