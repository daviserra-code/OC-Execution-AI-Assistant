from flask import Flask, render_template, request, jsonify, session, Response, stream_template
import openai
import os
import sys
import base64
from werkzeug.utils import secure_filename
import uuid
import json
import hashlib
import time
from datetime import datetime
import threading
import queue
import sqlite3
from contextlib import contextmanager
import numpy as np
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    HAS_VECTOR_SUPPORT = True
except ImportError:
    HAS_VECTOR_SUPPORT = False
    SentenceTransformer = None
    faiss = None
    print("⚠️  Vector database support not available. Install sentence-transformers and faiss-cpu for enhanced AI capabilities.")

import ast
import re
try:
    import PyPDF2
    import docx
    import zipfile
    import tarfile
    import json
    HAS_DOC_SUPPORT = True
except ImportError:
    HAS_DOC_SUPPORT = False
    PyPDF2 = None
    docx = None
    zipfile = None
    tarfile = None
    json = None

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', str(uuid.uuid4()))

openai.api_key = os.environ.get('OPENAI_API_KEY', '')

# Database configuration
DATABASE_PATH = 'chat_history.db'

def init_database():
    """Initialize the SQLite database with required tables"""
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_message TEXT NOT NULL,
                assistant_response TEXT NOT NULL,
                mode TEXT DEFAULT 'general',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL UNIQUE,
                custom_prompt TEXT NOT NULL,
                modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_session_id ON chat_exchanges (session_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_timestamp ON chat_exchanges (timestamp)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mode ON system_prompts (mode)
        ''')
        conn.commit()

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def get_session_id():
    """Get or create a session ID"""
    if 'user_session_id' not in session:
        session['user_session_id'] = str(uuid.uuid4())
        session.modified = True

        # Create session in database
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT OR IGNORE INTO chat_sessions (session_id) VALUES (?)',
                    (session['user_session_id'],)
                )
                conn.commit()
                print(f"Created new session: {session['user_session_id'][:8]}...")
        except Exception as e:
            print(f"Error creating session in database: {e}")

    return session['user_session_id']

def save_chat_exchange(session_id, user_message, assistant_response, mode='general'):
    """Save a chat exchange to the database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Ensure session exists first
            cursor.execute('''
                INSERT OR IGNORE INTO chat_sessions (session_id) VALUES (?)
            ''', (session_id,))

            # Insert the chat exchange
            cursor.execute('''
                INSERT INTO chat_exchanges (session_id, user_message, assistant_response, mode)
                VALUES (?, ?, ?, ?)
            ''', (session_id, user_message, assistant_response, mode))

            # Update session last activity
            cursor.execute('''
                UPDATE chat_sessions 
                SET last_activity = CURRENT_TIMESTAMP 
                WHERE session_id = ?
            ''', (session_id,))

            conn.commit()
            print(f"✅ Saved chat exchange for session {session_id[:8]} (mode: {mode})")
    except Exception as e:
        print(f"❌ Error saving chat exchange: {e}")
        raise e

def load_chat_history(session_id, limit=50):
    """Load chat history from database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_message, assistant_response, mode, timestamp
                FROM chat_exchanges
                WHERE session_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
            ''', (session_id, limit))

            rows = cursor.fetchall()
            history = [
                {
                    'user': row['user_message'],
                    'assistant': row['assistant_response'],
                    'mode': row['mode'] or 'general',
                    'timestamp': row['timestamp']
                }
                for row in rows
            ]
            print(f"Successfully loaded {len(history)} exchanges from database")
            return history
    except Exception as e:
        print(f"Error loading chat history from database: {e}")
        return []

def clear_session_history(session_id):
    """Clear chat history for a specific session"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM chat_exchanges WHERE session_id = ?', (session_id,))
        conn.commit()

# Initialize database on startup (lightweight)
try:
    init_database()
    print("✅ Database initialized successfully")
except Exception as e:
    print(f"❌ Database initialization error: {e}")

# Defer expensive operations to avoid blocking health checks
def init_app_background():
    """Initialize expensive operations in background"""
    try:
        # Test database connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM chat_sessions')
            session_count = cursor.fetchone()['count']
            cursor.execute('SELECT COUNT(*) as count FROM chat_exchanges')
            exchange_count = cursor.fetchone()['count']
            print(f"📊 Database stats: {session_count} sessions, {exchange_count} exchanges")
    except Exception as e:
        print(f"❌ Database stats error: {e}")
    
    # Initialize vector database in background
    if HAS_VECTOR_SUPPORT:
        try:
            initialize_vector_db()
        except NameError:
            print("⚠️  Vector database initialization deferred - function not yet defined")

if not openai.api_key:
    print("⚠️  Warning: OPENAI_API_KEY not set. Please add it to Secrets.")

# Response cache for similar questions
response_cache = {}
cache_lock = threading.Lock()

# Assistant modes/personas
ASSISTANT_MODES = {
    "general": {
        "name": "General Architecture",
        "icon": "🏗️",
        "prompt": """You are a highly experienced and proactive Software Architecture Assistant specializing in modern software patterns, architectural decision-making, documentation, and stakeholder communication, as well as a coding assistant for Siemens Opcenter Execution Foundation, Process, and Discrete platforms.

# Responsibilities and Areas of Focus

### General Software Architecture:
- **Architecture Recommendations**: Provide modern software architecture patterns such as microservices, event-driven architecture, and domain-driven design.
- **Technology Trade-offs**: Analyze and summarize the pros, cons, and trade-offs for key decisions (e.g., SQL vs. NoSQL, REST vs. gRPC).
- **Technical Documentation**: Draft high-level designs (HLDs), low-level designs (LLDs), and diagrammatic representations (C4, sequence diagrams, flowcharts) in markdown/mermaid syntax.
- **Architecture Decision Records (ADRs)**: Create concise ADRs that document the context, decision, and consequences of architectural choices.
- **Stakeholder Adaptation**: Tailor responses based on the target audience, offering high-level summaries to executives and technical depth to developers.
- **DevOps and Cloud Best Practices**: Recommend DevOps pipelines, cloud-native practices, and tools like Terraform, Kubernetes, and containerization.
- **Code and Design Reviews**: Ensure system designs and code follow principles like SOLID and clean code practices while ensuring scalability, maintainability, and security.
- **Interactive Diagrams and Materials**: Communicate clearly with bullet points, tables, pseudo-code, and annotated diagrams.

### Opcenter Execution Coding Assistance:
- **Customizations for Opcenter Platforms**: Proactively assist in implementing customizations for Siemens Opcenter Execution Foundation, Process, and Discrete (version 2401+).
  - Provide best practices for writing and optimizing code in **C#** or **Mendix**, rooted in modern design patterns.
  - Suggest ways to adhere to platform-specific guidelines while also future-proofing code with extensibility and maintainability.
  - Offer integrated advice on unit testing, debugging tips, and deployment strategies specific to Siemens environments.
- **Detailed Coding Guidance**: Assist with pseudocode, algorithms, or specific implementations aligned with Opcenter capabilities.

# Steps

1. **Clarify Requirements**: If the user's request is under-specified, extract more detail with contextual questions.
2. **Tailor the Response**: Adapt content depth and tone based on the user's intended audience.
3. **Present Recommendations**: Provide structured, well-reasoned responses including trade-offs.
4. **Deliver Outputs**: Offer concise, actionable, and implementation-ready suggestions.
5. **Iterate and Follow Up**: Remain context-aware for ongoing conversations.

# Output Format

1. Structure technical documentation using markdown or mermaid syntax with explanations.
2. For recommendations, provide: brief summary, key considerations, trade-offs, clear conclusion.
3. Use language-specific syntax with clear comments for code examples.
4. Always close with next steps or invitation to clarify further details.

Always adapt based on user context and role, ensuring clarity and relevance of recommendations."""
    },
    "architecture_review": {
        "name": "Architecture Review",
        "icon": "🔍",
        "prompt": """You are an expert Architecture Reviewer focused on analyzing existing systems and providing detailed feedback.

Your primary responsibilities:
- Conduct thorough architectural reviews
- Identify potential issues, bottlenecks, and risks
- Suggest improvements for scalability, maintainability, and performance
- Evaluate security considerations
- Assess compliance with best practices and patterns
- Provide actionable recommendations with priorities

Always structure your reviews with: Current State Analysis, Issues Identified, Recommendations, Risk Assessment, and Next Steps."""
    },
    "code_review": {
        "name": "Code Review",
        "icon": "👨‍💻",
        "prompt": """You are a Senior Code Reviewer specializing in code quality, best practices, and maintainability.

Focus areas:
- Code quality and adherence to SOLID principles
- Security vulnerabilities and potential issues
- Performance optimization opportunities
- Test coverage and testability
- Documentation and readability
- Opcenter-specific coding standards (when applicable)

Provide constructive feedback with specific examples and improvement suggestions."""
    },
    "documentation": {
        "name": "Documentation",
        "icon": "📚",
        "prompt": """You are a Technical Documentation Specialist focused on creating clear, comprehensive documentation.

Specializations:
- Technical specifications and API documentation
- Architecture Decision Records (ADRs)
- System design documents (HLD/LLD)
- User guides and tutorials
- Diagram creation (C4, sequence, flowcharts) using Mermaid syntax
- Documentation templates and standards

Always ensure documentation is clear, well-structured, and appropriate for the target audience."""
    },
    "opcenter": {
        "name": "MES/MOM Expert",
        "icon": "⚙️",
        "prompt": """You are an expert in Siemens Opcenter Execution platforms (Foundation, Process, Discrete) with deep knowledge of version 2401+ features.

Core expertise:
- Opcenter customization best practices in C# and Mendix
- Platform-specific design patterns and architecture
- Integration patterns and data flow optimization
- Performance tuning and scalability considerations
- Deployment strategies and environment management
- Troubleshooting and debugging techniques
- Version upgrade and migration strategies

Provide Opcenter-specific guidance with practical examples and real-world scenarios."""
    },
    "bob_prompt_maker": {
        "name": "Bob The Prompt Maker",
        "icon": "🎯",
        "prompt": """You are Bob, a master-level AI prompt optimization specialist. Your mission is to transform any user input into precision-crafted prompts that unlock AI's full potential across all platforms.

## Methodology

**Deconstruct**: Extract core intent, key entities, and context. Identify output requirements and constraints. Map what's provided vs. missing.
**Diagnose**: Audit for clarity gaps and ambiguity. Check specificity and completeness. Assess structure and complexity needs.
**Develop**: Select techniques based on request type (Creative, Technical, Educational, Complex). Assign appropriate AI role/expertise. Enhance context and implement logical structure.
**Deliver**: Construct optimized prompt. Format based on complexity. Provide implementation guidance.

## Techniques

**Foundational**: Role assignment, context layering, output specs, task decomposition.
**Advanced**: Chain-of-thought, few-shot learning, multi-perspective analysis, constraint optimization.

**Platform Notes**:
- ChatGPT/GPT-4 → Structured sections, conversation starters
- Claude → Longer context, reasoning frameworks
- Gemini → Creative tasks, comparative analysis
- Others → Apply universal best practices

## Modes

**Detail Mode**: Gather context, ask clarifying questions, provide comprehensive optimization.
**Basic Mode**: Quick fixes only, apply core techniques, deliver ready-to-use prompt.

## Response Formats

**Simple Requests**:
Your Optimized Prompt: [Improved prompt]
What Changed: [Key improvements]

**Complex Requests**:
Your Optimized Prompt: [Improved prompt]
Key Improvements: [Changes + benefits]
Techniques Applied: [Brief mention]
Pro Tip: [Usage guidance]

## Welcome Message

When activated, display exactly:

*"Hello! I'm Bob Sacamano, your AI prompt optimizer. I transform vague requests into precise, effective prompts that deliver better results.

What I need to know:

→ Target AI: ChatGPT, Claude, Gemini, or Other

→ Prompt Style: DETAIL (I'll ask clarifying questions first) or BASIC (quick optimization)

Examples:

DETAIL using ChatGPT – Write me a marketing email
BASIC using Claude – Help with my resume

Just share your rough prompt and I'll handle the optimization!"*

## Processing Flow

Auto-detect complexity: simple → BASIC; complex/professional → DETAIL.
Inform user with override option.
Execute chosen protocol.
Deliver optimized prompt.

Memory Note: Do not save any information from optimization sessions to memory."""
    }
}

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'py', 'js', 'html', 'css', 'json', 'xml', 'cs', 'yaml', 'yml', 'md', 'sql', 'ipynb', 'zip', 'tar', 'tar.gz', 'tgz', 'rar', '7z'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Enhanced Vector Database for RAG
vector_db = None
sentence_model = None
vector_db_initialized = False
document_store = {}  # Maps document IDs to metadata
chunk_store = {}     # Maps chunk IDs to content and metadata

def initialize_vector_db():
    """Initialize vector database for RAG capabilities - runs asynchronously"""
    global vector_db, sentence_model, vector_db_initialized
    if HAS_VECTOR_SUPPORT and SentenceTransformer and faiss:
        try:
            sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
            vector_db = faiss.IndexFlatIP(384)  # 384 is the embedding dimension
            vector_db_initialized = True
            print("✅ Vector database initialized for enhanced AI capabilities")
            
            # Load existing documents from database if any
            load_existing_documents()
            return True
        except Exception as e:
            print(f"⚠️  Could not initialize vector database: {e}")
            return False
    else:
        print("⚠️  Vector database support not available. Install sentence-transformers and faiss-cpu for enhanced AI capabilities.")
        return False

def chunk_text(text, chunk_size=500, overlap=50):
    """Split text into overlapping chunks for better semantic search"""
    words = text.split()
    chunks = []
    
    for i in range(0, len(words), chunk_size - overlap):
        chunk = ' '.join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
        
        # Break if we've reached the end
        if i + chunk_size >= len(words):
            break
    
    return chunks

def add_document_to_vector_db(content, filename, file_type='text'):
    """Add a document to the vector database with semantic chunking"""
    if not vector_db_initialized or not sentence_model:
        return False
    
    try:
        # Generate unique document ID
        doc_id = hashlib.md5(f"{filename}_{time.time()}".encode()).hexdigest()
        
        # Chunk the document
        chunks = chunk_text(content)
        
        if not chunks:
            return False
        
        # Generate embeddings for all chunks
        embeddings = sentence_model.encode(chunks)
        
        # Store document metadata
        document_store[doc_id] = {
            'filename': filename,
            'file_type': file_type,
            'total_chunks': len(chunks),
            'created_at': datetime.now().isoformat()
        }
        
        # Add each chunk to the vector database
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_id = f"{doc_id}_chunk_{i}"
            
            # Store chunk metadata
            chunk_store[chunk_id] = {
                'content': chunk,
                'doc_id': doc_id,
                'filename': filename,
                'chunk_index': i,
                'file_type': file_type
            }
            
            # Add to FAISS index
            vector_db.add(embedding.reshape(1, -1))
        
        # Save to database for persistence
        save_document_to_db(doc_id, filename, content, file_type, len(chunks))
        
        print(f"✅ Added document '{filename}' to vector database with {len(chunks)} chunks")
        return True
        
    except Exception as e:
        print(f"❌ Error adding document to vector database: {e}")
        return False

def search_similar_content(query, k=5, similarity_threshold=0.3):
    """Search for similar content using semantic search"""
    if not vector_db_initialized or not sentence_model:
        return []
    
    try:
        # Generate query embedding
        query_embedding = sentence_model.encode([query])
        
        # Search in vector database
        scores, indices = vector_db.search(query_embedding, k)
        
        results = []
        chunk_ids = list(chunk_store.keys())
        
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(chunk_ids) and score > similarity_threshold:
                chunk_id = chunk_ids[idx]
                chunk_data = chunk_store.get(chunk_id, {})
                
                if chunk_data:
                    results.append({
                        'content': chunk_data['content'],
                        'filename': chunk_data['filename'],
                        'similarity_score': float(score),
                        'chunk_index': chunk_data['chunk_index'],
                        'file_type': chunk_data['file_type']
                    })
        
        # Sort by similarity score
        results.sort(key=lambda x: x['similarity_score'], reverse=True)
        return results
        
    except Exception as e:
        print(f"❌ Error searching vector database: {e}")
        return []

def save_document_to_db(doc_id, filename, content, file_type, chunk_count):
    """Save document metadata to SQLite database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Create documents table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    content TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Insert document
            cursor.execute('''
                INSERT OR REPLACE INTO documents (id, filename, content, file_type, chunk_count)
                VALUES (?, ?, ?, ?, ?)
            ''', (doc_id, filename, content, file_type, chunk_count))
            
            conn.commit()
            
    except Exception as e:
        print(f"❌ Error saving document to database: {e}")

def load_existing_documents():
    """Load existing documents from database into vector store"""
    if not vector_db_initialized:
        return
        
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Check if documents table exists
            cursor.execute('''
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='documents'
            ''')
            
            if not cursor.fetchone():
                return  # Table doesn't exist yet
            
            # Load all documents
            cursor.execute('SELECT id, filename, content, file_type FROM documents')
            documents = cursor.fetchall()
            
            for doc in documents:
                doc_id, filename, content, file_type = doc
                
                # Re-chunk and add to vector database
                chunks = chunk_text(content)
                
                if chunks:
                    embeddings = sentence_model.encode(chunks)
                    
                    # Store document metadata
                    document_store[doc_id] = {
                        'filename': filename,
                        'file_type': file_type,
                        'total_chunks': len(chunks),
                        'created_at': datetime.now().isoformat()
                    }
                    
                    # Add chunks to vector database
                    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                        chunk_id = f"{doc_id}_chunk_{i}"
                        
                        chunk_store[chunk_id] = {
                            'content': chunk,
                            'doc_id': doc_id,
                            'filename': filename,
                            'chunk_index': i,
                            'file_type': file_type
                        }
                        
                        vector_db.add(embedding.reshape(1, -1))
            
            print(f"✅ Loaded {len(documents)} existing documents into vector database")
            
    except Exception as e:
        print(f"❌ Error loading existing documents: {e}")

def get_rag_context(user_message, max_context_length=2000):
    """Get relevant context from vector database for RAG"""
    if not vector_db_initialized:
        return ""
    
    try:
        # Search for relevant content
        similar_content = search_similar_content(user_message, k=3, similarity_threshold=0.4)
        
        if not similar_content:
            return ""
        
        # Build context from similar content
        context_parts = []
        current_length = 0
        
        for content in similar_content:
            content_text = f"From {content['filename']} (similarity: {content['similarity_score']:.2f}):\n{content['content']}\n"
            
            if current_length + len(content_text) > max_context_length:
                break
                
            context_parts.append(content_text)
            current_length += len(content_text)
        
        if context_parts:
            rag_context = "=== RELEVANT CONTEXT FROM UPLOADED DOCUMENTS ===\n\n"
            rag_context += "\n---\n\n".join(context_parts)
            rag_context += "\n=== END CONTEXT ===\n"
            return rag_context
        
        return ""
        
    except Exception as e:
        print(f"❌ Error getting RAG context: {e}")
        return ""

# Vector database will be initialized in background thread

# Start background initialization after all functions are defined
if not openai.api_key:
    pass  # Already warned above
threading.Thread(target=init_app_background, daemon=True).start()

def process_jupyter_notebook(notebook_content):
    """Process Jupyter notebook and extract code, markdown, and outputs"""
    try:
        notebook = json.loads(notebook_content)
        
        processed_content = "=== JUPYTER NOTEBOOK ANALYSIS ===\n\n"
        
        # Extract metadata
        if 'metadata' in notebook:
            metadata = notebook['metadata']
            if 'kernelspec' in metadata:
                kernel = metadata['kernelspec']
                processed_content += f"**Kernel:** {kernel.get('display_name', 'Unknown')} ({kernel.get('name', 'unknown')})\n"
            if 'language_info' in metadata:
                lang_info = metadata['language_info']
                processed_content += f"**Language:** {lang_info.get('name', 'Unknown')} v{lang_info.get('version', 'Unknown')}\n"
        
        processed_content += f"**Total Cells:** {len(notebook.get('cells', []))}\n\n"
        
        # Process cells
        code_cells = 0
        markdown_cells = 0
        
        for i, cell in enumerate(notebook.get('cells', []), 1):
            cell_type = cell.get('cell_type', 'unknown')
            source = ''.join(cell.get('source', []))
            
            if cell_type == 'code':
                code_cells += 1
                if source.strip():
                    processed_content += f"### Code Cell {i}\n```python\n{source}\n```\n"
                    
                    # Include outputs if present
                    outputs = cell.get('outputs', [])
                    if outputs:
                        processed_content += "**Output:**\n"
                        for output in outputs:
                            if output.get('output_type') == 'stream':
                                stream_text = ''.join(output.get('text', []))
                                processed_content += f"```\n{stream_text}\n```\n"
                            elif output.get('output_type') == 'execute_result':
                                data = output.get('data', {})
                                if 'text/plain' in data:
                                    result_text = ''.join(data['text/plain'])
                                    processed_content += f"```\n{result_text}\n```\n"
                    processed_content += "\n"
            
            elif cell_type == 'markdown':
                markdown_cells += 1
                if source.strip():
                    processed_content += f"### Markdown Cell {i}\n{source}\n\n"
        
        processed_content += f"\n**Summary:** {code_cells} code cells, {markdown_cells} markdown cells\n"
        
        return processed_content
        
    except Exception as e:
        return f"[Jupyter notebook processing error: {str(e)}]"

def process_archive_file(file_path, filename):
    """Process archive files (zip, tar, etc.) and extract file list with content preview"""
    try:
        file_extension = os.path.splitext(filename)[1].lower()
        second_ext = os.path.splitext(os.path.splitext(filename)[0])[1].lower()
        
        processed_content = f"=== ARCHIVE ANALYSIS: {filename} ===\n\n"
        
        files_list = []
        total_files = 0
        
        if file_extension == '.zip':
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                total_files = len(file_list)
                
                for file_name in file_list[:20]:  # Limit to first 20 files
                    file_info = zip_ref.getinfo(file_name)
                    files_list.append({
                        'name': file_name,
                        'size': file_info.file_size,
                        'is_dir': file_name.endswith('/'),
                        'compressed_size': file_info.compress_size
                    })
                    
                # Try to extract and preview small text files
                for file_name in file_list[:5]:  # Preview first 5 files
                    if (not file_name.endswith('/') and 
                        any(file_name.lower().endswith(ext) for ext in ['.py', '.js', '.txt', '.md', '.json', '.yaml', '.yml']) and
                        zip_ref.getinfo(file_name).file_size < 10000):  # Less than 10KB
                        
                        try:
                            with zip_ref.open(file_name) as f:
                                content = f.read().decode('utf-8')[:500]
                                processed_content += f"\n### Preview: {file_name}\n```\n{content}{'...' if len(content) >= 500 else ''}\n```\n"
                        except:
                            continue
        
        elif file_extension in ['.tar', '.tgz'] or second_ext == '.tar':
            mode = 'r:gz' if file_extension in ['.tgz'] or second_ext == '.tar' else 'r'
            with tarfile.open(file_path, mode) as tar_ref:
                members = tar_ref.getmembers()
                total_files = len(members)
                
                for member in members[:20]:  # Limit to first 20 files
                    files_list.append({
                        'name': member.name,
                        'size': member.size,
                        'is_dir': member.isdir(),
                        'type': 'directory' if member.isdir() else 'file'
                    })
                    
                # Try to extract and preview small text files
                for member in members[:5]:  # Preview first 5 files
                    if (member.isfile() and 
                        any(member.name.lower().endswith(ext) for ext in ['.py', '.js', '.txt', '.md', '.json', '.yaml', '.yml']) and
                        member.size < 10000):  # Less than 10KB
                        
                        try:
                            f = tar_ref.extractfile(member)
                            if f:
                                content = f.read().decode('utf-8')[:500]
                                processed_content += f"\n### Preview: {member.name}\n```\n{content}{'...' if len(content) >= 500 else ''}\n```\n"
                        except:
                            continue
        
        # Build file list summary
        processed_content += f"**Total Files:** {total_files}\n"
        processed_content += f"**Showing:** {min(len(files_list), 20)} files\n\n"
        
        processed_content += "**File Structure:**\n```\n"
        for file_info in files_list:
            size_str = f" ({file_info['size']} bytes)" if not file_info.get('is_dir', False) else " (directory)"
            processed_content += f"{file_info['name']}{size_str}\n"
        
        if total_files > 20:
            processed_content += f"... and {total_files - 20} more files\n"
        
        processed_content += "```\n"
        
        return processed_content
        
    except Exception as e:
        return f"[Archive processing error: {str(e)}]"

def analyze_code_structure(code_content, file_extension):
    """Analyze code structure and extract meaningful information"""
    analysis = {
        'functions': [],
        'classes': [],
        'imports': [],
        'complexity_score': 0,
        'line_count': len(code_content.split('\n'))
    }

    try:
        if file_extension in ['.py']:
            tree = ast.parse(code_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis['functions'].append({
                        'name': node.name,
                        'line': node.lineno,
                        'args': [arg.arg for arg in node.args.args]
                    })
                elif isinstance(node, ast.ClassDef):
                    analysis['classes'].append({
                        'name': node.name,
                        'line': node.lineno
                    })
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        analysis['imports'].append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        analysis['imports'].append(f"from {node.module}")

        # Simple complexity estimation
        analysis['complexity_score'] = len(analysis['functions']) + len(analysis['classes']) * 2

    except Exception as e:
        analysis['error'] = f"Code analysis error: {str(e)}"

    return analysis

def process_uploaded_file(file_path):
    """Enhanced file processing with code analysis and better content extraction"""
    filename = os.path.basename(file_path)
    file_extension = os.path.splitext(filename)[1].lower()

    try:
        content = ""

        # Handle different file types
        if file_extension == '.pdf' and HAS_DOC_SUPPORT and PyPDF2:
            try:
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    content = ""
                    for page in pdf_reader.pages:
                        content += page.extract_text() + "\n"
            except Exception as e:
                content = f"[PDF processing error: {str(e)}]"

        elif file_extension in ['.docx', '.doc'] and HAS_DOC_SUPPORT and docx:
            try:
                doc = docx.Document(file_path)
                content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            except Exception as e:
                content = f"[Document processing error: {str(e)}]"

        elif file_extension == '.ipynb':
            # Jupyter Notebook processing
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    notebook_content = f.read()
                content = process_jupyter_notebook(notebook_content)
            except Exception as e:
                content = f"[Jupyter notebook processing error: {str(e)}]"

        elif file_extension in ['.zip', '.tar', '.tgz'] or filename.lower().endswith('.tar.gz'):
            # Archive file processing
            content = process_archive_file(file_path, filename)

        else:
            # Text-based files
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                try:
                    with open(file_path, 'r', encoding='latin-1') as f:
                        content = f.read()
                except Exception as e:
                    return f"[Binary file - could not read: {str(e)}]"

        # Enhanced processing for code files
        code_analysis = None
        if file_extension in ['.py', '.js', '.cs', '.java', '.cpp', '.c', '.h']:
            code_analysis = analyze_code_structure(content, file_extension)

            # Add analysis summary to content
            if code_analysis and 'error' not in code_analysis:
                analysis_summary = f"\n\n--- CODE ANALYSIS ---\n"
                analysis_summary += f"File: {filename}\n"
                analysis_summary += f"Lines: {code_analysis['line_count']}\n"
                analysis_summary += f"Functions: {len(code_analysis['functions'])}\n"
                analysis_summary += f"Classes: {len(code_analysis['classes'])}\n"
                analysis_summary += f"Imports: {len(code_analysis['imports'])}\n"
                analysis_summary += f"Complexity Score: {code_analysis['complexity_score']}\n"

                if code_analysis['functions']:
                    analysis_summary += f"Function Names: {', '.join([f['name'] for f in code_analysis['functions']])}\n"

                content += analysis_summary

        # Store enhanced content in session
        if 'uploaded_files' not in session:
            session['uploaded_files'] = {}

        session['uploaded_files'][filename] = {
            'content': content,
            'type': file_extension,
            'size': len(content),
            'analysis': code_analysis if file_extension in ['.py', '.js', '.cs', '.java', '.cpp', '.c', '.h'] else None
        }
        session.modified = True

        # Add to vector database for semantic search
        if vector_db_initialized:
            success = add_document_to_vector_db(content, filename, file_extension)
            if success:
                print(f"✅ Document '{filename}' added to vector database for semantic search")

        return content

    except Exception as e:
        return f"[Error processing {filename}: {str(e)}]"

def get_cache_key(message, mode, context_summary):
    """Generate cache key for similar messages"""
    content = f"{message}_{mode}_{context_summary}"
    return hashlib.md5(content.encode()).hexdigest()

def summarize_context(chat_history):
    """Create a summary of chat context for better memory management"""
    if len(chat_history) < 5:
        return ""

    # Create a summary of older conversations
    summary_parts = []
    for chat in chat_history[:-10]:  # Summarize older chats
        if len(chat['user']) > 100:
            summary_parts.append(f"User asked about: {chat['user'][:100]}...")
        else:
            summary_parts.append(f"User asked about: {chat['user']}")

    return " | ".join(summary_parts)

@app.route('/')
def index():
    # Fast path for health checks and deployment probes
    accept_header = request.headers.get('Accept', '')
    user_agent = request.headers.get('User-Agent', '').lower()
    
    # Return JSON for non-browser requests (health checks, deployment probes)
    if ('health' in user_agent or 'ping' in user_agent or 
        not accept_header.startswith('text/html') or
        'curl' in user_agent or 'wget' in user_agent):
        return {'status': 'ok', 'timestamp': time.time()}, 200

    try:
        # Minimal initialization for browser requests
        if 'chat_history' not in session:
            session['chat_history'] = []
        if 'assistant_mode' not in session:
            session['assistant_mode'] = 'general'
        
        # Get session ID but don't block on database operations
        session_id = get_session_id()
        session.modified = True

        return render_template('index.html', modes=ASSISTANT_MODES, initial_chat_history=[])
    except Exception as e:
        print(f"Error in index route: {e}")
        # Return minimal working template
        return render_template('index.html', modes=ASSISTANT_MODES, initial_chat_history=[])

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        regenerate = data.get('regenerate', False)

        if not user_message and not regenerate:
            return jsonify({'error': 'Message cannot be empty'}), 400

        if not openai.api_key:
            return jsonify({'error': 'OpenAI API key not configured. Please add OPENAI_API_KEY to Secrets.'}), 500

        # Initialize chat history if not exists
        if 'chat_history' not in session:
            session['chat_history'] = []

        mode = session.get('assistant_mode', 'general')

        # Get custom prompt from database if available
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT custom_prompt FROM system_prompts WHERE mode = ?', (mode,))
            row = cursor.fetchone()
            current_prompt = row['custom_prompt'] if row else ASSISTANT_MODES[mode]['prompt']

        # Handle regeneration
        if regenerate and session['chat_history']:
            # Remove last assistant response and use the previous user message
            session['chat_history'].pop()
            user_message = session['chat_history'][-1]['user'] if session['chat_history'] else user_message

        # Check cache for similar questions
        context_summary = summarize_context(session['chat_history'])
        cache_key = get_cache_key(user_message, mode, context_summary)

        with cache_lock:
            if cache_key in response_cache and not regenerate:
                cached_response = response_cache[cache_key]
                if time.time() - cached_response['timestamp'] < 3600:  # 1 hour cache
                    session['chat_history'].append({
                        'user': user_message,
                        'assistant': cached_response['response'],
                        'timestamp': datetime.now().isoformat(),
                        'mode': mode
                    })
                    session.modified = True
                    return jsonify({'response': cached_response['response'], 'cached': True})

        # Build messages for OpenAI
        messages = [{"role": "system", "content": current_prompt}]

        # Add context summary if available
        if context_summary:
            messages.append({"role": "system", "content": f"Previous conversation context: {context_summary}"})

        # Add RAG context using semantic search
        rag_context = get_rag_context(user_message)
        if rag_context:
            messages.append({"role": "system", "content": rag_context})
        elif 'uploaded_files' in session and session['uploaded_files']:
            # Fallback to basic file context if RAG is not available
            files_context = "Uploaded files context:\n"
            for filename, content in session['uploaded_files'].items():
                files_context += f"\n--- {filename} ---\n{content[:2000]}{'...' if len(content) > 2000 else ''}\n"
            messages.append({"role": "system", "content": files_context})

        # Add recent chat history (last 15 exchanges for better context)
        for chat in session['chat_history'][-15:]:
            messages.append({"role": "user", "content": chat['user']})
            messages.append({"role": "assistant", "content": chat['assistant']})

        # Add current message
        messages.append({"role": "user", "content": user_message})

        response = openai.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=3000
        )

        assistant_response = response.choices[0].message.content

        # Cache the response
        with cache_lock:
            response_cache[cache_key] = {
                'response': assistant_response,
                'timestamp': time.time()
            }

        # Save to database and session
        session_id = get_session_id()
        save_chat_exchange(session_id, user_message, assistant_response, mode)

        session['chat_history'].append({
            'user': user_message,
            'assistant': assistant_response,
            'timestamp': datetime.now().isoformat(),
            'mode': mode
        })
        session.modified = True

        return jsonify({'response': assistant_response})

    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/chat_stream', methods=['POST'])
def chat_stream():
    """Streaming chat endpoint for better UX"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()

        if not user_message:
            return jsonify({'error': 'Message cannot be empty'}), 400

        if not openai.api_key:
            return jsonify({'error': 'OpenAI API key not configured.'}), 500

        # Get session data before streaming starts
        if 'chat_history' not in session:
            session['chat_history'] = []

        chat_history = session.get('chat_history', [])
        mode = session.get('assistant_mode', 'general')
        uploaded_files = session.get('uploaded_files', {})

        def generate():
            try:
                # Get custom prompt from database if available
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT custom_prompt FROM system_prompts WHERE mode = ?', (mode,))
                    row = cursor.fetchone()
                    current_prompt = row['custom_prompt'] if row else ASSISTANT_MODES[mode]['prompt']

                # Build messages
                messages = [{"role": "system", "content": current_prompt}]

                # Add context
                context_summary = summarize_context(chat_history)
                if context_summary:
                    messages.append({"role": "system", "content": f"Previous conversation context: {context_summary}"})

                # Add RAG context using semantic search
                rag_context = get_rag_context(user_message)
                if rag_context:
                    messages.append({"role": "system", "content": rag_context})
                elif uploaded_files:
                    # Fallback to basic file context if RAG is not available
                    files_context = "Uploaded files context:\n"
                    for filename, content in uploaded_files.items():
                        files_context += f"\n--- {filename} ---\n{content[:2000]}{'...' if len(content) > 2000 else ''}\n"
                    messages.append({"role": "system", "content": files_context})

                # Add recent history
                for chat in chat_history[-15:]:
                    messages.append({"role": "user", "content": chat['user']})
                    messages.append({"role": "assistant", "content": chat['assistant']})

                messages.append({"role": "user", "content": user_message})

                # Stream response
                stream = openai.chat.completions.create(
                    model="gpt-4",
                    messages=messages,
                    temperature=0.7,
                    max_tokens=3000,
                    stream=True
                )

                full_response = ""
                for chunk in stream:
                    if chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        yield f"data: {json.dumps({'content': content})}\n\n"

                yield f"data: {json.dumps({'done': True, 'full_response': full_response})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        response = Response(generate(), mimetype='text/event-stream')
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Connection'] = 'keep-alive'
        return response

    except Exception as e:
        return jsonify({'error': f'Stream error: {str(e)}'}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = str(int(time.time()))
            safe_filename = f"{timestamp}_{filename}"
            file_path = os.path.join(UPLOAD_FOLDER, safe_filename)
            file.save(file_path)

            # Enhanced file processing
            file_content = process_uploaded_file(file_path)

            # Get file info from session
            file_info = session.get('uploaded_files', {}).get(file.filename, {})
            file_extension = os.path.splitext(file.filename)[1].lower()

            # Provide enhanced preview based on file type
            preview_content = file_content[:1000] + ('...' if len(file_content) > 1000 else '')

            # Add file type specific information
            file_type_info = ""
            if file_extension in ['.py', '.js', '.cs', '.java', '.cpp', '.c', '.h']:
                file_type_info = "📄 Code file - Enhanced analysis available"
            elif file_extension == '.pdf':
                file_type_info = "📋 PDF document" + (" - Extracted text" if HAS_DOC_SUPPORT else " - Text extraction not available")
            elif file_extension in ['.docx', '.doc']:
                file_type_info = "📝 Word document" + (" - Extracted content" if HAS_DOC_SUPPORT else " - Content extraction not available")
            elif file_extension == '.ipynb':
                file_type_info = "📓 Jupyter Notebook - Full analysis with code, markdown, and outputs"
            elif file_extension in ['.zip', '.tar', '.tgz'] or filename.lower().endswith('.tar.gz'):
                file_type_info = "📦 Archive file - File structure analysis and content preview"
            elif file_extension in ['.md', '.txt']:
                file_type_info = "📄 Text document"
            elif file_extension in ['.json', '.xml', '.yaml', '.yml']:
                file_type_info = "🔧 Configuration file"
            else:
                file_type_info = f"📎 {file_extension.upper()[1:]} file"

            # Clean up temporary file
            try:
                os.remove(file_path)
            except:
                pass

            return jsonify({
                'success': True,
                'filename': safe_filename,
                'original_name': file.filename,
                'content': preview_content,
                'full_content': file_content,
                'file_type_info': file_type_info,
                'size': len(file_content),
                'analysis': file_info.get('analysis') if isinstance(file_info, dict) else None
            })
        else:
            # Group file types for better error message
            code_files = ['py', 'js', 'html', 'css', 'cs', 'sql']
            document_files = ['txt', 'md', 'pdf', 'doc', 'docx']
            config_files = ['json', 'xml', 'yaml', 'yml']
            notebook_files = ['ipynb']
            archive_files = ['zip', 'tar', 'tar.gz', 'tgz']
            image_files = ['png', 'jpg', 'jpeg', 'gif']
            
            error_msg = 'File type not allowed. Supported types:\n'
            error_msg += f'• Code: {", ".join(code_files)}\n'
            error_msg += f'• Documents: {", ".join(document_files)}\n'
            error_msg += f'• Notebooks: {", ".join(notebook_files)}\n'
            error_msg += f'• Archives: {", ".join(archive_files)}\n'
            error_msg += f'• Config: {", ".join(config_files)}\n'
            error_msg += f'• Images: {", ".join(image_files)}'
            
            return jsonify({'error': error_msg}), 400

    except Exception as e:
        return jsonify({'error': f'Upload error: {str(e)}'}), 500

@app.route('/set_mode', methods=['POST'])
def set_mode():
    try:
        data = request.get_json()
        mode = data.get('mode', 'general')

        if mode not in ASSISTANT_MODES:
            return jsonify({'error': 'Invalid mode'}), 400

        session['assistant_mode'] = mode
        session.modified = True

        return jsonify({'success': True, 'mode': mode, 'mode_info': ASSISTANT_MODES[mode]})
    except Exception as e:
        return jsonify({'error': f'Error setting mode: {str(e)}'}), 500

@app.route('/export_conversation', methods=['GET'])
def export_conversation():
    try:
        session_id = get_session_id()
        chat_history = load_chat_history(session_id, limit=1000)  # Load more for export
        export_format = request.args.get('format', 'json')

        if export_format == 'json':
            return jsonify({
                'conversation': chat_history,
                'exported_at': datetime.now().isoformat(),
                'total_exchanges': len(chat_history)
            })

        elif export_format == 'markdown':
            md_content = f"# Conversation Export\n\n**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n**Total Exchanges:** {len(chat_history)}\n\n---\n\n"

            for i, exchange in enumerate(chat_history, 1):
                timestamp = exchange.get('timestamp', 'Unknown time')
                mode = exchange.get('mode', 'general')
                mode_info = ASSISTANT_MODES.get(mode, {'name': 'General'})

                md_content += f"## Exchange {i}\n\n"
                md_content += f"**Time:** {timestamp}  \n**Mode:** {mode_info['name']}\n\n"
                md_content += f"**👤 User:**\n{exchange['user']}\n\n"
                md_content += f"**🤖 Assistant:**\n{exchange['assistant']}\n\n---\n\n"

            return Response(
                md_content,
                mimetype='text/markdown',
                headers={"Content-disposition": f"attachment; filename=conversation_{int(time.time())}.md"}
            )

        else:
            return jsonify({'error': 'Unsupported format'}), 400

    except Exception as e:
        return jsonify({'error': f'Export error: {str(e)}'}), 500

@app.route('/clear_history', methods=['POST'])
def clear_history():
    try:
        session_id = get_session_id()
        clear_session_history(session_id)

        session['chat_history'] = []
        session['uploaded_files'] = {}
        session.modified = True

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Error clearing history: {str(e)}'}), 500

@app.route('/get_prompt', methods=['GET'])
def get_prompt():
    try:
        mode = session.get('assistant_mode', 'general')

        # Check for custom prompt in database first
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT custom_prompt FROM system_prompts WHERE mode = ?', (mode,))
            row = cursor.fetchone()

            if row:
                prompt = row['custom_prompt']
            else:
                # Use default prompt
                prompt = ASSISTANT_MODES[mode]['prompt']

        return jsonify({
            'prompt': prompt,
            'mode': mode,
            'mode_info': ASSISTANT_MODES[mode]
        })
    except Exception as e:
        return jsonify({'error': f'Error retrieving prompt: {str(e)}'}), 500

@app.route('/get_history', methods=['GET'])
def get_history():
    try:
        session_id = get_session_id()

        # Load fresh history from database
        chat_history = load_chat_history(session_id, limit=100)

        # Update session with latest history
        session['chat_history'] = chat_history
        session.modified = True

        print(f"Returning {len(chat_history)} chat exchanges to frontend")
        return jsonify({'history': chat_history, 'count': len(chat_history)})
    except Exception as e:
        print(f"Error in get_history route: {e}")
        return jsonify({'error': f'Error retrieving chat history: {str(e)}', 'history': [], 'count': 0}), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Dedicated health check endpoint for deployment"""
    return {'status': 'healthy', 'timestamp': time.time()}, 200

@app.route('/get_modes', methods=['GET'])
def get_modes():
    return jsonify({'modes': ASSISTANT_MODES})

@app.route('/get_session_info', methods=['GET'])
def get_session_info():
    """Get information about the current session"""
    try:
        session_id = get_session_id()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT created_at, last_activity,
                       (SELECT COUNT(*) FROM chat_exchanges WHERE session_id = ?) as message_count
                FROM chat_sessions 
                WHERE session_id = ?
            ''', (session_id, session_id))

            row = cursor.fetchone()
            if row:
                return jsonify({
                    'session_id': session_id,
                    'created_at': row['created_at'],
                    'last_activity': row['last_activity'],
                    'message_count': row['message_count']
                })
            else:
                return jsonify({'error': 'Session not found'}), 404

    except Exception as e:
        return jsonify({'error': f'Error retrieving session info: {str(e)}'}), 500

@app.route('/test_db', methods=['GET'])
def test_db():
    """Test database connectivity and show recent entries"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Test basic connectivity
            cursor.execute('SELECT COUNT(*) as session_count FROM chat_sessions')
            session_count = cursor.fetchone()['session_count']

            cursor.execute('SELECT COUNT(*) as exchange_count FROM chat_exchanges')
            exchange_count = cursor.fetchone()['exchange_count']

            # Get recent exchanges
            cursor.execute('''
                SELECT session_id, user_message, assistant_response, timestamp, mode
                FROM chat_exchanges 
                ORDER BY timestamp DESC 
                LIMIT 5
            ''')
            recent_exchanges = [dict(row) for row in cursor.fetchall()]

            return jsonify({
                'success': True,
                'database_path': DATABASE_PATH,
                'session_count': session_count,
                'exchange_count': exchange_count,
                'recent_exchanges': recent_exchanges
            })

    except Exception as e:
        return jsonify({'error': f'Database test error: {str(e)}'}), 500

@app.route('/delete_old_sessions', methods=['POST'])
def delete_old_sessions():
    """Delete sessions older than specified days (default 30 days)"""
    try:
        data = request.get_json() if request.is_json else {}
        days = data.get('days', 30) if data else 30

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Delete old chat exchanges first
            cursor.execute('''
                DELETE FROM chat_exchanges 
                WHERE session_id IN (
                    SELECT session_id FROM chat_sessions 
                    WHERE last_activity < datetime('now', '-{} days')
                )
            '''.format(days))

            # Delete old sessions
            cursor.execute('''
                DELETE FROM chat_sessions 
                WHERE last_activity < datetime('now', '-{} days')
            '''.format(days))

            deleted_count = cursor.rowcount
            conn.commit()

        return jsonify({'success': True, 'deleted_sessions': deleted_count})

    except Exception as e:
        return jsonify({'error': f'Error deleting old sessions: {str(e)}'}), 500

@app.route('/save_chat', methods=['POST'])
def save_chat():
    """Save chat exchange to database and session after streaming"""
    try:
        data = request.get_json()
        user_message = data.get('user_message', '')
        assistant_response = data.get('assistant_response', '')
        mode = data.get('mode', 'general')

        if not user_message or not assistant_response:
            return jsonify({'error': 'Missing message data'}), 400

        # Save to database
        session_id = get_session_id()
        save_chat_exchange(session_id, user_message, assistant_response, mode)

        # Also update session for immediate use
        if 'chat_history' not in session:
            session['chat_history'] = []

        session['chat_history'].append({
            'user': user_message,
            'assistant': assistant_response,
            'timestamp': datetime.now().isoformat(),
            'mode': mode
        })
        session.modified = True

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': f'Error saving chat: {str(e)}'}), 500

@app.route('/search_documents', methods=['POST'])
def search_documents():
    """Search uploaded documents using semantic search"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        
        if not query:
            return jsonify({'error': 'Query cannot be empty'}), 400
        
        if not vector_db_initialized:
            return jsonify({'error': 'Vector database not initialized'}), 500
        
        # Search for similar content
        results = search_similar_content(query, k=10, similarity_threshold=0.2)
        
        return jsonify({
            'success': True,
            'query': query,
            'results': results,
            'total_results': len(results)
        })
        
    except Exception as e:
        return jsonify({'error': f'Search error: {str(e)}'}), 500

@app.route('/vector_db_stats', methods=['GET'])
def vector_db_stats():
    """Get vector database statistics"""
    try:
        if not vector_db_initialized:
            return jsonify({
                'initialized': False,
                'error': 'Vector database not initialized'
            })
        
        # Count documents and chunks
        document_count = len(document_store)
        chunk_count = len(chunk_store)
        
        # Get document details
        document_details = []
        for doc_id, doc_info in document_store.items():
            document_details.append({
                'id': doc_id,
                'filename': doc_info['filename'],
                'file_type': doc_info['file_type'],
                'chunk_count': doc_info['total_chunks'],
                'created_at': doc_info['created_at']
            })
        
        return jsonify({
            'initialized': True,
            'document_count': document_count,
            'chunk_count': chunk_count,
            'vector_dimension': 384,
            'model_name': 'all-MiniLM-L6-v2',
            'documents': document_details
        })
        
    except Exception as e:
        return jsonify({'error': f'Stats error: {str(e)}'}), 500

@app.route('/clear_vector_db', methods=['POST'])
def clear_vector_db():
    """Clear all documents from vector database"""
    try:
        global vector_db, document_store, chunk_store
        
        if not vector_db_initialized:
            return jsonify({'error': 'Vector database not initialized'}), 500
        
        # Clear in-memory stores
        document_store.clear()
        chunk_store.clear()
        
        # Recreate empty FAISS index
        if HAS_VECTOR_SUPPORT and faiss:
            vector_db = faiss.IndexFlatIP(384)
        
        # Clear documents from database
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM documents')
            conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Vector database cleared successfully'
        })
        
    except Exception as e:
        return jsonify({'error': f'Clear error: {str(e)}'}), 500

@app.route('/save_system_prompt', methods=['POST'])
def save_system_prompt():
    """Save custom system prompt to database with full persistence"""
    try:
        data = request.get_json()
        mode = data.get('mode', 'general')
        custom_prompt = data.get('prompt', '').strip()

        if not custom_prompt:
            return jsonify({'error': 'Prompt cannot be empty'}), 400

        if mode not in ASSISTANT_MODES:
            return jsonify({'error': 'Invalid mode'}), 400

        # Save to database with UPSERT
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO system_prompts (mode, custom_prompt, modified_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (mode, custom_prompt))
            conn.commit()

        print(f"✅ System prompt saved for mode: {mode}")

        return jsonify({
            'success': True,
            'mode': mode,
            'mode_info': ASSISTANT_MODES[mode],
            'message': f'System prompt for {ASSISTANT_MODES[mode]["name"]} mode saved successfully'
        })

    except Exception as e:
        print(f"❌ Error saving system prompt: {e}")
        return jsonify({'error': f'Error saving system prompt: {str(e)}'}), 500

@app.route('/reset_system_prompt', methods=['POST'])
def reset_system_prompt():
    """Reset system prompt to default and remove custom version"""
    try:
        data = request.get_json()
        mode = data.get('mode', 'general')

        if mode not in ASSISTANT_MODES:
            return jsonify({'error': 'Invalid mode'}), 400

        # Remove custom prompt from database
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM system_prompts WHERE mode = ?', (mode,))
            conn.commit()

        default_prompt = ASSISTANT_MODES[mode]['prompt']

        print(f"✅ System prompt reset to default for mode: {mode}")

        return jsonify({
            'success': True,
            'mode': mode,
            'mode_info': ASSISTANT_MODES[mode],
            'default_prompt': default_prompt,
            'message': f'System prompt for {ASSISTANT_MODES[mode]["name"]} mode reset to default'
        })

    except Exception as e:
        print(f"❌ Error resetting system prompt: {e}")
        return jsonify({'error': f'Error resetting system prompt: {str(e)}'}), 500

@app.route('/dashboard')
def dashboard():
    """Render the monitoring dashboard"""
    return render_template('dashboard.html')

@app.route('/dashboard/metrics')
def dashboard_metrics():
    """Get real-time dashboard metrics"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Basic metrics
            cursor.execute('SELECT COUNT(*) as count FROM chat_sessions')
            total_sessions = cursor.fetchone()['count']

            cursor.execute('SELECT COUNT(*) as count FROM chat_exchanges')
            total_messages = cursor.fetchone()['count']

            # Active sessions (last 24 hours)
            cursor.execute('''
                SELECT COUNT(DISTINCT session_id) as count 
                FROM chat_exchanges 
                WHERE timestamp > datetime('now', '-1 day')
            ''')
            active_sessions = cursor.fetchone()['count']

            # Mode distribution
            cursor.execute('''
                SELECT mode, COUNT(*) as count
                FROM chat_exchanges
                WHERE mode IS NOT NULL
                GROUP BY mode
                ORDER BY count DESC
            ''')
            mode_rows = cursor.fetchall()
            
            mode_distribution = {}
            total_mode_messages = sum(row['count'] for row in mode_rows)
            most_used_mode = 'General'
            
            if mode_rows:
                most_used_mode = ASSISTANT_MODES.get(mode_rows[0]['mode'], {'name': 'General'})['name']
                for row in mode_rows:
                    mode_name = ASSISTANT_MODES.get(row['mode'], {'name': row['mode']})['name']
                    percentage = round((row['count'] / total_mode_messages) * 100, 1)
                    mode_distribution[mode_name] = percentage

            # Message volume by hour (last 24 hours)
            cursor.execute('''
                SELECT 
                    strftime('%H', timestamp) as hour,
                    COUNT(*) as count
                FROM chat_exchanges 
                WHERE timestamp > datetime('now', '-1 day')
                GROUP BY hour
                ORDER BY hour
            ''')
            volume_rows = cursor.fetchall()
            
            # Create 24-hour timeline
            hours = [f"{i:02d}:00" for i in range(24)]
            volume_data = [0] * 24
            
            for row in volume_rows:
                hour_index = int(row['hour'])
                volume_data[hour_index] = row['count']

            # Files processed count (estimate from session data)
            cursor.execute('''
                SELECT COUNT(*) as count 
                FROM chat_exchanges 
                WHERE user_message LIKE '%uploaded%' OR user_message LIKE '%file%'
            ''')
            files_processed = cursor.fetchone()['count']

            # Recent activity
            cursor.execute('''
                SELECT 
                    'chat' as type,
                    'New message in ' || COALESCE(mode, 'general') || ' mode' as message,
                    timestamp
                FROM chat_exchanges
                WHERE timestamp > datetime('now', '-1 hour')
                ORDER BY timestamp DESC
                LIMIT 10
            ''')
            activity_rows = cursor.fetchall()
            
            activity = []
            for row in activity_rows:
                activity.append({
                    'type': row['type'],
                    'message': row['message'],
                    'timestamp': row['timestamp']
                })

            # Add session creation activity
            cursor.execute('''
                SELECT 
                    'session' as type,
                    'New session created' as message,
                    created_at as timestamp
                FROM chat_sessions
                WHERE created_at > datetime('now', '-1 hour')
                ORDER BY created_at DESC
                LIMIT 5
            ''')
            session_rows = cursor.fetchall()
            
            for row in session_rows:
                activity.append({
                    'type': row['type'],
                    'message': row['message'],
                    'timestamp': row['timestamp']
                })

            # Sort activity by timestamp
            activity.sort(key=lambda x: x['timestamp'], reverse=True)
            activity = activity[:20]  # Keep top 20

            metrics = {
                'total_sessions': total_sessions,
                'total_messages': total_messages,
                'active_sessions': active_sessions,
                'avg_response_time': '1.2s',  # Placeholder - could be calculated from logs
                'most_used_mode': most_used_mode,
                'files_processed': files_processed,
                'mode_distribution': mode_distribution
            }

            charts = {
                'message_volume': {
                    'labels': hours,
                    'data': volume_data
                },
                'mode_usage': {
                    'labels': list(mode_distribution.keys()),
                    'data': list(mode_distribution.values())
                }
            }

            return jsonify({
                'metrics': metrics,
                'charts': charts,
                'activity': activity
            })

    except Exception as e:
        print(f"❌ Error getting dashboard metrics: {e}")
        return jsonify({'error': f'Error getting metrics: {str(e)}'}), 500

@app.route('/dashboard/export')
def dashboard_export():
    """Export dashboard metrics as JSON"""
    try:
        # Get comprehensive metrics
        metrics_response = dashboard_metrics()
        metrics_data = metrics_response.get_json()

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Add detailed session data
            cursor.execute('''
                SELECT 
                    cs.session_id,
                    cs.created_at,
                    cs.last_activity,
                    COUNT(ce.id) as message_count,
                    GROUP_CONCAT(DISTINCT ce.mode) as modes_used
                FROM chat_sessions cs
                LEFT JOIN chat_exchanges ce ON cs.session_id = ce.session_id
                GROUP BY cs.session_id
                ORDER BY cs.created_at DESC
            ''')
            
            sessions = []
            for row in cursor.fetchall():
                sessions.append({
                    'session_id': row['session_id'],
                    'created_at': row['created_at'],
                    'last_activity': row['last_activity'],
                    'message_count': row['message_count'],
                    'modes_used': row['modes_used'].split(',') if row['modes_used'] else []
                })

        export_data = {
            'export_timestamp': datetime.now().isoformat(),
            'summary': metrics_data,
            'detailed_sessions': sessions,
            'metadata': {
                'application': 'Teyra Architecture Assistant',
                'version': '2.0',
                'export_type': 'dashboard_metrics'
            }
        }

        return jsonify(export_data)

    except Exception as e:
        return jsonify({'error': f'Export error: {str(e)}'}), 500

@app.route('/templates/<template_type>')
def get_template(template_type):
    """Provide quick templates for common tasks"""
    templates = {
        'adr': {
            'name': 'Architecture Decision Record',
            'content': '''# ADR-{number}: {Title}

## Status
Proposed | Accepted | Deprecated | Superseded

## Context
What is the issue that we're seeing that is motivating this decision or change?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or more difficult to do because of this change?

## Alternatives Considered
What other options did we consider?

## References
Links to relevant documentation, discussions, or other ADRs.'''
        },
        'hld': {
            'name': 'High-Level Design Template',
            'content': '''# High-Level Design: {System Name}

## Overview
Brief description of the system and its purpose.

## Goals and Requirements
- Functional requirements
- Non-functional requirements
- Constraints

## Architecture Overview

```mermaid
graph TB
    A[Client] --> B[API Gateway]
    B --> C[Service Layer]
    C --> D[Data Layer]
```

## System Components
### Component 1
- Purpose
- Responsibilities
- Interfaces

## Data Flow
Describe how data flows through the system.

## Security Considerations
Authentication, authorization, data protection.

## Scalability and Performance
Expected load, scaling strategies.

## Monitoring and Observability
Logging, metrics, alerting strategies.'''
        },
        'code_review': {
            'name': 'Code Review Checklist',
            'content': '''# Code Review Checklist

## Functionality
- [ ] Code does what it's supposed to do
- [ ] Edge cases are handled
- [ ] Error handling is appropriate

## Code Quality
- [ ] Code follows established conventions
- [ ] Variables and functions are well-named
- [ ] Code is DRY (Don't Repeat Yourself)
- [ ] Functions are small and focused

## Security
- [ ] No hardcoded secrets or credentials
- [ ] Input validation is implemented
- [ ] SQL injection prevention
- [ ] XSS prevention (for web apps)

## Performance
- [ ] No obvious performance bottlenecks
- [ ] Database queries are optimized
- [ ] Appropriate data structures used

## Testing
- [ ] Unit tests cover new functionality
- [ ] Tests are meaningful and not just for coverage
- [ ] Integration tests where appropriate

## Documentation
- [ ] Code is self-documenting
- [ ] Complex logic is commented
- [ ] API documentation updated if needed'''
        }
    }

    template = templates.get(template_type)
    if template:
        return jsonify(template)
    else:
        return jsonify({'error': 'Template not found'}), 404

if __name__ == '__main__':
    # Production configuration for deployment
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    # Try different ports if default is occupied
    import socket
    for attempt_port in [port, 5001, 5002, 5003]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', attempt_port))
                port = attempt_port
                break
        except OSError:
            continue
    
    print(f"🚀 Starting Flask app on port {port} (debug: {debug_mode})")
    app.run(host='0.0.0.0', port=port, debug=debug_mode, threaded=True)