"""
Qdrant vector database integration for code storage.

One collection per codebase (e.g., codebase_myproject, codebase_anotherrepo).
Each collection stores code chunks with embeddings and rich metadata.

Features:
- Collection management (create, delete, exists)
- Batch upsert operations
- Semantic search with metadata filters
- Point deletion for incremental updates
- Payload indexing for fast filtering
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from qdrant_client.http.models import (
        Distance,
        VectorParams,
        PointStruct,
        Filter,
        FieldCondition,
        MatchValue,
        MatchAny,
        PayloadSchemaType,
    )
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logger.warning("qdrant-client not available")


@dataclass
class CodePoint:
    """
    Represents a code chunk point for Qdrant storage.
    
    Attributes:
        id: Stable symbol key (used as point ID)
        vector: Embedding vector
        payload: Rich metadata
    """
    id: str
    vector: list[float]
    payload: dict[str, Any]


class QdrantCodeStore:
    """
    Qdrant vector store for code documentation.
    
    Manages one collection per codebase with proper indexing.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        grpc_port: int = 6334,
        vector_size: int = 768,
        distance: str = "COSINE",
    ):
        """
        Initialize Qdrant client.
        
        Args:
            host: Qdrant host.
            port: REST API port.
            grpc_port: gRPC port.
            vector_size: Size of embedding vectors.
            distance: Distance metric (COSINE, DOT, EUCLID).
        """
        if not QDRANT_AVAILABLE:
            raise ImportError("qdrant-client is required. Install with: pip install qdrant-client")
        
        self.host = host
        self.port = port
        self.grpc_port = grpc_port
        self.vector_size = vector_size
        self.distance = self._parse_distance(distance)
        
        # Initialize client (REST for now, can use gRPC for better performance)
        self._client = QdrantClient(host=host, port=port)
        
        logger.info(f"Connected to Qdrant at {host}:{port}")

    def close(self) -> None:
        """Close the Qdrant client."""
        self._client.close()

    def __enter__(self) -> "QdrantCodeStore":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # =========================================================================
    # Collection Management
    # =========================================================================

    def ensure_collection(self, collection_name: str) -> bool:
        """
        Ensure collection exists, create if not.
        
        Args:
            collection_name: Name of the collection.
        
        Returns:
            True if collection exists or was created, False on error.
        """
        try:
            if self._client.collection_exists(collection_name):
                logger.debug(f"Collection {collection_name} already exists")
                return True
            
            # Create collection
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=self.distance,
                ),
            )
            
            logger.info(f"Created collection: {collection_name}")
            
            # Create payload indexes for fast filtering
            self._create_payload_indexes(collection_name)
            
            return True
            
        except Exception as e:
            logger.error(f"Error ensuring collection {collection_name}: {e}")
            return False

    def _create_payload_indexes(self, collection_name: str) -> None:
        """Create payload indexes for efficient filtering."""
        indexed_fields = [
            ("file_path", PayloadSchemaType.KEYWORD),
            ("commit_hash", PayloadSchemaType.KEYWORD),
            ("language", PayloadSchemaType.KEYWORD),
            ("chunk_type", PayloadSchemaType.KEYWORD),
            ("repo_url", PayloadSchemaType.KEYWORD),
            ("fully_qualified_name", PayloadSchemaType.KEYWORD),
        ]
        
        for field_name, field_type in indexed_fields:
            try:
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_type,
                )
            except Exception as e:
                logger.debug(f"Index may already exist for {field_name}: {e}")

    def delete_collection(self, collection_name: str) -> bool:
        """
        Delete a collection.
        
        Args:
            collection_name: Name of the collection.
        
        Returns:
            True if deleted, False on error.
        """
        try:
            self._client.delete_collection(collection_name)
            logger.info(f"Deleted collection: {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Error deleting collection {collection_name}: {e}")
            return False

    def collection_exists(self, collection_name: str) -> bool:
        """Check if collection exists."""
        try:
            return self._client.collection_exists(collection_name)
        except Exception as e:
            logger.error(f"Error checking collection: {e}")
            return False

    def get_collection_info(self, collection_name: str) -> dict[str, Any] | None:
        """Get collection information."""
        try:
            info = self._client.get_collection(collection_name)
            return {
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status,
            }
        except Exception as e:
            logger.error(f"Error getting collection info: {e}")
            return None

    # =========================================================================
    # Point Operations
    # =========================================================================

    def upsert_points(
        self,
        collection_name: str,
        points: list[CodePoint],
        batch_size: int = 100,
    ) -> bool:
        """
        Upsert points to collection in batches.
        
        Args:
            collection_name: Target collection.
            points: List of CodePoint objects.
            batch_size: Number of points per batch.
        
        Returns:
            True if all batches succeeded.
        """
        if not points:
            return True
        
        success = True
        
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            
            try:
                # Convert to PointStruct format
                point_structs = [
                    PointStruct(
                        id=point.id,
                        vector=point.vector,
                        payload=point.payload,
                    )
                    for point in batch
                ]
                
                result = self._client.upsert(
                    collection_name=collection_name,
                    points=point_structs,
                )
                
                if result.status != models.UpdateStatus.COMPLETED:
                    logger.warning(f"Upsert completed with status: {result.status}")
                    
            except Exception as e:
                logger.error(f"Error upserting batch: {e}")
                success = False
        
        return success

    def upsert_single(
        self,
        collection_name: str,
        point: CodePoint,
    ) -> bool:
        """
        Upsert a single point.
        
        Args:
            collection_name: Target collection.
            point: CodePoint to upsert.
        
        Returns:
            True if successful.
        """
        return self.upsert_points(collection_name, [point])

    def delete_points(
        self,
        collection_name: str,
        point_ids: list[str],
    ) -> bool:
        """
        Delete points by ID.
        
        Args:
            collection_name: Target collection.
            point_ids: List of point IDs to delete.
        
        Returns:
            True if successful.
        """
        if not point_ids:
            return True
        
        try:
            result = self._client.delete(
                collection_name=collection_name,
                points_selector=models.PointIdsList(points=point_ids),
            )
            return result.status == models.UpdateStatus.COMPLETED
        except Exception as e:
            logger.error(f"Error deleting points: {e}")
            return False

    def delete_points_by_filter(
        self,
        collection_name: str,
        filter_conditions: dict[str, Any],
    ) -> bool:
        """
        Delete points matching filter conditions.
        
        Args:
            collection_name: Target collection.
            filter_conditions: Dict of field -> value conditions.
        
        Returns:
            True if successful.
        """
        try:
            qdrant_filter = self._build_filter(filter_conditions)
            
            result = self._client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(filter=qdrant_filter),
            )
            return result.status == models.UpdateStatus.COMPLETED
        except Exception as e:
            logger.error(f"Error deleting points by filter: {e}")
            return False

    def get_point(
        self,
        collection_name: str,
        point_id: str,
    ) -> CodePoint | None:
        """
        Get a single point by ID.
        
        Args:
            collection_name: Target collection.
            point_id: Point ID.
        
        Returns:
            CodePoint or None if not found.
        """
        try:
            result = self._client.retrieve(
                collection_name=collection_name,
                ids=[point_id],
                with_vectors=True,
            )
            
            if result and len(result) > 0:
                record = result[0]
                return CodePoint(
                    id=str(record.id),
                    vector=record.vector,
                    payload=record.payload or {},
                )
            return None
        except Exception as e:
            logger.error(f"Error retrieving point: {e}")
            return None

    def get_points_by_filter(
        self,
        collection_name: str,
        filter_conditions: dict[str, Any],
        limit: int = 100,
        with_vectors: bool = False,
    ) -> list[CodePoint]:
        """
        Get points matching filter conditions.
        
        Args:
            collection_name: Target collection.
            filter_conditions: Dict of field -> value conditions.
            limit: Maximum number of points to return.
            with_vectors: Whether to include vectors in response.
        
        Returns:
            List of CodePoint objects.
        """
        try:
            qdrant_filter = self._build_filter(filter_conditions)
            
            result = self._client.scroll(
                collection_name=collection_name,
                scroll_filter=qdrant_filter,
                limit=limit,
                with_vectors=with_vectors,
            )
            
            points = []
            for record in result[0]:  # scroll returns (records, next_offset)
                points.append(CodePoint(
                    id=str(record.id),
                    vector=record.vector if with_vectors else [],
                    payload=record.payload or {},
                ))
            return points
            
        except Exception as e:
            logger.error(f"Error scrolling points: {e}")
            return []

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        filter_conditions: Optional[dict[str, Any]] = None,
        top_k: int = 10,
        score_threshold: Optional[float] = None,
    ) -> list[tuple[CodePoint, float]]:
        """
        Semantic search with optional metadata filters.
        
        Args:
            collection_name: Target collection.
            query_vector: Query embedding vector.
            filter_conditions: Optional metadata filters.
            top_k: Number of results to return.
            score_threshold: Minimum score threshold.
        
        Returns:
            List of (CodePoint, score) tuples.
        """
        try:
            qdrant_filter = None
            if filter_conditions:
                qdrant_filter = self._build_filter(filter_conditions)
            
            results = self._client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=qdrant_filter,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            )
            
            points = []
            for result in results:
                point = CodePoint(
                    id=str(result.id),
                    vector=[],
                    payload=result.payload or {},
                )
                points.append((point, result.score))
            
            return points
            
        except Exception as e:
            logger.error(f"Error searching: {e}")
            return []

    def search_with_multiple_vectors(
        self,
        collection_name: str,
        query_vectors: list[list[float]],
        filter_conditions: Optional[dict[str, Any]] = None,
        top_k: int = 10,
    ) -> list[tuple[CodePoint, float]]:
        """
        Search with multiple query vectors (for multi-query scenarios).
        
        Args:
            collection_name: Target collection.
            query_vectors: List of query embedding vectors.
            filter_conditions: Optional metadata filters.
            top_k: Number of results to return.
        
        Returns:
            List of (CodePoint, score) tuples.
        """
        try:
            qdrant_filter = None
            if filter_conditions:
                qdrant_filter = self._build_filter(filter_conditions)
            
            results = self._client.search_batch(
                collection_name=collection_name,
                requests=[
                    models.SearchRequest(
                        vector=vec,
                        filter=qdrant_filter,
                        limit=top_k,
                        with_payload=True,
                        with_vectors=False,
                    )
                    for vec in query_vectors
                ],
            )
            
            # Combine results (deduplicate by ID, keep highest score)
            seen = {}
            for result_set in results:
                for result in result_set:
                    point_id = str(result.id)
                    if point_id not in seen or seen[point_id][1] < result.score:
                        point = CodePoint(
                            id=point_id,
                            vector=[],
                            payload=result.payload or {},
                        )
                        seen[point_id] = (point, result.score)
            
            # Sort by score and return top_k
            sorted_results = sorted(seen.values(), key=lambda x: x[1], reverse=True)
            return sorted_results[:top_k]
            
        except Exception as e:
            logger.error(f"Error batch searching: {e}")
            return []

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _parse_distance(self, distance_str: str) -> Distance:
        """Parse distance string to Distance enum."""
        distance_map = {
            "COSINE": Distance.COSINE,
            "DOT": Distance.DOT,
            "EUCLID": Distance.EUCLID,
        }
        return distance_map.get(distance_str.upper(), Distance.COSINE)

    def _build_filter(self, conditions: dict[str, Any]) -> Filter:
        """
        Build Qdrant Filter from conditions dict.
        
        Args:
            conditions: Dict of field -> value(s).
        
        Returns:
            Qdrant Filter object.
        """
        must_conditions = []
        
        for field, value in conditions.items():
            if isinstance(value, list):
                # Match any of the values
                must_conditions.append(
                    FieldCondition(
                        key=field,
                        match=MatchAny(any=value),
                    )
                )
            else:
                # Match single value
                must_conditions.append(
                    FieldCondition(
                        key=field,
                        match=MatchValue(value=value),
                    )
                )
        
        return Filter(must=must_conditions) if must_conditions else None

    def count_points(
        self,
        collection_name: str,
        filter_conditions: Optional[dict[str, Any]] = None,
    ) -> int:
        """
        Count points in collection, optionally filtered.
        
        Args:
            collection_name: Target collection.
            filter_conditions: Optional metadata filters.
        
        Returns:
            Count of matching points.
        """
        try:
            qdrant_filter = None
            if filter_conditions:
                qdrant_filter = self._build_filter(filter_conditions)
            
            result = self._client.count(
                collection_name=collection_name,
                count_filter=qdrant_filter,
            )
            return result.count
        except Exception as e:
            logger.error(f"Error counting points: {e}")
            return 0

    def get_all_point_ids(
        self,
        collection_name: str,
        filter_conditions: Optional[dict[str, Any]] = None,
    ) -> list[str]:
        """
        Get all point IDs matching filter conditions.
        
        Useful for detecting deletions.
        
        Args:
            collection_name: Target collection.
            filter_conditions: Optional metadata filters.
        
        Returns:
            List of point IDs.
        """
        points = self.get_points_by_filter(
            collection_name,
            filter_conditions or {},
            limit=10000,  # Large limit to get all
            with_vectors=False,
        )
        return [point.id for point in points]
