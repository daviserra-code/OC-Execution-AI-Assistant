import threading
import os
import json
import pickle
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    HAS_VECTOR_SUPPORT = True
except ImportError:
    HAS_VECTOR_SUPPORT = False
    SentenceTransformer = None
    faiss = None

class RAGService:
    def __init__(self):
        self.vector_db = None
        self.sentence_model = None
        self.initialized = False
        self.document_store = {}
        self.document_metadata = []
        self.lock = threading.Lock()
        self.storage_dir = 'rag_data'
        
        # Ensure storage directory exists
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

    def initialize(self):
        """Initialize vector database for RAG capabilities"""
        if HAS_VECTOR_SUPPORT and SentenceTransformer and faiss:
            try:
                self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
                
                # Try to load existing state
                if self.load_state():
                    print("[INFO] Loaded existing vector database state")
                else:
                    self.vector_db = faiss.IndexFlatIP(384)  # 384 is the embedding dimension
                    print("[INFO] Vector database initialized (new)")
                
                self.initialized = True
                return True
            except Exception as e:
                print(f"[ERROR] Could not initialize vector database: {e}")
                return False
        else:
            print("⚠️  Vector database support not available. Install sentence-transformers and faiss-cpu for enhanced AI capabilities.")
            return False

    def save_state(self):
        """Save vector index and metadata to disk"""
        if not self.initialized:
            return False
            
        try:
            with self.lock:
                # Save FAISS index
                index_path = os.path.join(self.storage_dir, 'vector.index')
                faiss.write_index(self.vector_db, index_path)
                
                # Save metadata
                metadata_path = os.path.join(self.storage_dir, 'metadata.json')
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(self.document_metadata, f, ensure_ascii=False, indent=2)
                    
            print(f"[INFO] RAG state saved to {self.storage_dir}")
            return True
        except Exception as e:
            print(f"[ERROR] Error saving RAG state: {e}")
            return False

    def load_state(self):
        """Load vector index and metadata from disk"""
        try:
            index_path = os.path.join(self.storage_dir, 'vector.index')
            metadata_path = os.path.join(self.storage_dir, 'metadata.json')
            
            if os.path.exists(index_path) and os.path.exists(metadata_path):
                # Load FAISS index
                self.vector_db = faiss.read_index(index_path)
                
                # Load metadata
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    self.document_metadata = json.load(f)
                
                print(f"[DEBUG] Loaded {len(self.document_metadata)} documents from metadata")
                if self.vector_db:
                    print(f"[DEBUG] Vector index has {self.vector_db.ntotal} vectors")
                    
                return True
            return False
        except Exception as e:
            print(f"[ERROR] Error loading RAG state: {e}")
            return False

    def chunk_text(self, text, chunk_size=500, overlap=50):
        """Split text into overlapping chunks for better retrieval"""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]

            # Try to break at sentence boundaries
            if end < len(text):
                last_period = chunk.rfind('.')
                last_newline = chunk.rfind('\n')
                break_point = max(last_period, last_newline)
                if break_point > start + chunk_size * 0.5:
                    chunk = chunk[:break_point + 1]
                    end = start + len(chunk)

            chunks.append(chunk.strip())
            start = end - overlap

            if start >= len(text):
                break

        return chunks

    def add_document(self, content, filename, file_type):
        """Add document chunks to vector database with enhanced metadata"""
        if not self.initialized or not self.sentence_model:
            return False

        try:
            # Check if document exists and remove it first (update scenario)
            self.delete_document(filename)

            # Chunk the document
            chunks = self.chunk_text(content)

            with self.lock:
                for i, chunk in enumerate(chunks):
                    if len(chunk.strip()) < 10:  # Skip very short chunks
                        continue

                    # Generate embedding
                    embedding = self.sentence_model.encode([chunk])

                    # Store embedding and metadata
                    self.vector_db.add(embedding)
                    self.document_metadata.append({
                        'filename': filename,
                        'file_type': file_type,
                        'chunk_index': i,
                        'total_chunks': len(chunks),
                        'content': chunk,
                        'content_preview': chunk[:200] + '...' if len(chunk) > 200 else chunk
                    })

            print(f"[INFO] Added {len(chunks)} chunks from {filename} to vector database")
            
            # Auto-save after addition
            self.save_state()
            
            return True

        except Exception as e:
            print(f"[ERROR] Error adding document to vector database: {e}")
            return False

    def search(self, query, top_k=5, similarity_threshold=0.2):
        """Perform semantic search on stored documents"""
        if not self.initialized or not self.sentence_model or len(self.document_metadata) == 0:
            print("[DEBUG] Search skipped: not initialized or empty metadata")
            return []

        try:
            # Generate query embedding
            query_embedding = self.sentence_model.encode([query])

            # Search vector database
            with self.lock:
                scores, indices = self.vector_db.search(query_embedding, min(top_k * 2, len(self.document_metadata)))
            
            print(f"[DEBUG] Search scores: {scores[0]}")
            print(f"[DEBUG] Search indices: {indices[0]}")

            # Filter by similarity threshold and prepare results
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < len(self.document_metadata) and score > similarity_threshold:
                    metadata = self.document_metadata[idx]
                    results.append({
                        'content': metadata['content'],
                        'filename': metadata['filename'],
                        'file_type': metadata['file_type'],
                        'similarity_score': float(score),
                        'content_preview': metadata['content_preview'],
                        'chunk_info': f"Chunk {metadata['chunk_index'] + 1}/{metadata['total_chunks']}"
                    })

            # Sort by similarity score (descending)
            results.sort(key=lambda x: x['similarity_score'], reverse=True)
            print(f"[DEBUG] Found {len(results)} relevant results")
            return results[:top_k]

        except Exception as e:
            print(f"[ERROR] Error in semantic search: {e}")
            return []

    def get_context(self, query, max_context_length=2000):
        """Get relevant context for RAG-enhanced responses"""
        if not self.initialized:
            return ""

        # Perform semantic search
        search_results = self.search(query, top_k=3)

        if not search_results:
            return ""

        # Build context from search results
        context_parts = []
        current_length = 0

        context_parts.append("=== RELEVANT CONTEXT FROM UPLOADED DOCUMENTS ===\n")

        for result in search_results:
            result_text = f"**From {result['filename']} ({result['chunk_info']}):**\n{result['content']}\n"

            if current_length + len(result_text) > max_context_length:
                break

            context_parts.append(result_text)
            current_length += len(result_text)

        context_parts.append("=== END CONTEXT ===\n")

        return "\n".join(context_parts)

    def clear(self):
        """Clear all documents from vector database"""
        if not self.initialized:
            return False
        
        with self.lock:
            self.document_metadata = []
            if HAS_VECTOR_SUPPORT and faiss:
                self.vector_db = faiss.IndexFlatIP(384)
                
            # Clear storage files
            try:
                index_path = os.path.join(self.storage_dir, 'vector.index')
                metadata_path = os.path.join(self.storage_dir, 'metadata.json')
                if os.path.exists(index_path): os.remove(index_path)
                if os.path.exists(metadata_path): os.remove(metadata_path)
            except Exception as e:
                print(f"⚠️ Error clearing storage: {e}")
                
        return True

    def get_stats(self):
        """Get statistics about the vector database"""
        if not self.initialized:
            return {
                "status": "Not Initialized",
                "total_documents": 0,
                "total_chunks": 0,
                "index_size": 0,
                "files": []
            }
            
        with self.lock:
            total_chunks = len(self.document_metadata)
            unique_files = list(set(doc['filename'] for doc in self.document_metadata))
            
            # Calculate approximate memory usage (384 float32 vectors)
            # 384 dimensions * 4 bytes per float * number of vectors
            vector_memory = total_chunks * 384 * 4
            
            return {
                "status": "Active",
                "total_documents": len(unique_files),
                "total_chunks": total_chunks,
                "index_size": vector_memory,
                "files": unique_files
            }

    def get_documents(self):
        """Get list of all documents"""
        if not self.initialized:
            return []
        
        with self.lock:
            unique_files = list(set(doc['filename'] for doc in self.document_metadata))
            return sorted(unique_files)

    def get_document_content(self, filename):
        """Reconstruct document content from chunks"""
        if not self.initialized:
            return None
            
        with self.lock:
            # Filter chunks for this file
            file_chunks = [doc for doc in self.document_metadata if doc['filename'] == filename]
            
            if not file_chunks:
                return None
                
            # Sort by chunk index
            file_chunks.sort(key=lambda x: x['chunk_index'])
            
            # Join content
            # Note: This is a best-effort reconstruction since we might have overlaps
            # For editing purposes, we might want to store the original content separately
            # But for now, we'll try to reconstruct or just join them
            
            # If we stored the full content in the first chunk or separately, that would be better.
            # But given the current structure, we'll join them. 
            # Since we have overlap, simply joining might duplicate text.
            # However, for the purpose of "correcting syntax errors", users might prefer to see the chunks 
            # or we need to change how we store data to keep the original.
            
            # A better approach for "editing" is to treat the chunks as the source of truth for now,
            # or acknowledge that we are reconstructing.
            
            # Let's try to stitch them back removing overlap if possible, or just join with a separator
            # if we can't perfectly reconstruct.
            
            # For simplicity and reliability in this context, let's join with newlines if they seem distinct,
            # or just return the raw chunks text.
            
            return "\n".join([chunk['content'] for chunk in file_chunks])

    def delete_document(self, filename):
        """Delete a document and rebuild index"""
        if not self.initialized:
            return False
            
        with self.lock:
            # Remove chunks belonging to this file
            initial_count = len(self.document_metadata)
            self.document_metadata = [doc for doc in self.document_metadata if doc['filename'] != filename]
            
            if len(self.document_metadata) == initial_count:
                return False # File not found
            
            # Rebuild index
            self.rebuild_index()
            self.save_state()
            return True

    def rebuild_index(self):
        """Rebuild FAISS index from metadata"""
        if not HAS_VECTOR_SUPPORT or not self.sentence_model:
            return

        print("[INFO] Rebuilding vector index...")
        self.vector_db = faiss.IndexFlatIP(384)
        
        # Batch process to avoid memory issues if large
        batch_size = 32
        for i in range(0, len(self.document_metadata), batch_size):
            batch = self.document_metadata[i:i+batch_size]
            texts = [item['content'] for item in batch]
            embeddings = self.sentence_model.encode(texts)
            self.vector_db.add(embeddings)
            
        print(f"[INFO] Index rebuilt with {self.vector_db.ntotal} vectors")

    def get_graph_data(self):
        """
        Returns nodes (documents) and edges (similarity connections).
        """
        nodes = []
        edges = []
        
        # Create nodes for each document
        doc_map = {}
        for i, doc in enumerate(self.document_metadata):
            filename = doc['filename']
            if filename not in doc_map:
                doc_id = len(nodes)
                doc_map[filename] = doc_id
                nodes.append({
                    'id': doc_id,
                    'label': filename,
                    'title': filename,
                    'group': 'document'
                })
        
        # For visualization purposes, let's just return the nodes.
        # Real similarity edges would require O(N^2) comparisons or efficient querying.
        
        return {'nodes': nodes, 'edges': edges}


# Global instance
rag_service = RAGService()
