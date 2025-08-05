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
import requests
from PIL import Image
import io
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    HAS_VECTOR_SUPPORT = True
except ImportError:
    HAS_VECTOR_SUPPORT = False
    print("⚠️  Vector database support not available. Install sentence-transformers and faiss-cpu for enhanced AI capabilities.")

import ast
import re
try:
    import PyPDF2
    import docx
    HAS_DOC_SUPPORT = True
except ImportError:
    HAS_DOC_SUPPORT = False

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', str(uuid.uuid4()))

openai.api_key = os.environ.get('OPENAI_API_KEY', '')

# AI Model Configuration
AVAILABLE_MODELS = {
    'gpt-4': {'name': 'GPT-4', 'provider': 'openai', 'max_tokens': 3000},
    'gpt-4-turbo': {'name': 'GPT-4 Turbo', 'provider': 'openai', 'max_tokens': 4000},
    'gpt-3.5-turbo': {'name': 'GPT-3.5 Turbo', 'provider': 'openai', 'max_tokens': 2000}
}
DEFAULT_MODEL = 'gpt-4'

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
    try:
        if 'user_session_id' not in session:
            new_session_id = str(uuid.uuid4())
            session['user_session_id'] = new_session_id
            session.modified = True

            # Create session in database with better error handling
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        'INSERT OR IGNORE INTO chat_sessions (session_id) VALUES (?)',
                        (new_session_id,)
                    )
                    conn.commit()
                    print(f"✅ Created new session: {new_session_id[:8]}...")
            except Exception as e:
                print(f"❌ Error creating session in database: {e}")
                # Continue with session even if database insert fails
                pass

        return session['user_session_id']
    except RuntimeError as e:
        if "Working outside of request context" in str(e):
            # Return a temporary session ID when outside request context
            return str(uuid.uuid4())
        raise e

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

# Initialize vector database for enhanced AI capabilities
vector_db = None
sentence_model = None

def initialize_vector_db():
    """Initialize vector database for RAG capabilities"""
    global vector_db, sentence_model
    if HAS_VECTOR_SUPPORT:
        try:
            sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
            vector_db = faiss.IndexFlatIP(384)  # 384 is the embedding dimension
            print("✅ Vector database initialized for enhanced AI capabilities")
        except Exception as e:
            print(f"⚠️  Could not initialize vector database: {e}")

# Initialize database and vector database on startup
def initialize_app():
    """Initialize the application with proper context"""
    try:
        init_database()
        print("✅ Database initialized successfully")

        # Test database connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM chat_sessions')
            session_count = cursor.fetchone()['count']
            cursor.execute('SELECT COUNT(*) as count FROM chat_exchanges')
            exchange_count = cursor.fetchone()['count']
            print(f"📊 Database stats: {session_count} sessions, {exchange_count} exchanges")

        # Initialize vector database for enhanced AI capabilities after database setup
        initialize_vector_db()
    except Exception as e:
        print(f"❌ Database initialization error: {e}")

# Initialize with app context
with app.app_context():
    initialize_app()


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

## Enhanced Capabilities

### Image Generation and Visual Communication:
- **Diagram Creation**: When users request visual diagrams, architecture drawings, or illustrations, you can generate them using DALL-E by responding with the special format: `[GENERATE_IMAGE: detailed description of the image to generate]`
- **Image Analysis**: You can analyze uploaded images, screenshots, diagrams, or generated images to provide detailed feedback and suggestions
- **Visual Architecture**: Create visual representations of system architectures, data flows, and technical concepts
- **UI/UX Mockups**: Generate mockups and visual examples for user interfaces and system designs

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
        "name": "Opcenter Expert",
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
    }
}

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'py', 'js', 'html', 'css', 'json', 'xml', 'cs', 'yaml', 'yml', 'md', 'sql'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def analyze_code_structure(code_content, file_extension):
    """Enhanced code analysis with dependency tracking and metrics"""
    analysis = {
        'functions': [],
        'classes': [],
        'imports': [],
        'dependencies': {},
        'complexity_score': 0,
        'line_count': len(code_content.split('\n')),
        'metrics': {
            'comment_ratio': 0,
            'blank_line_ratio': 0,
            'avg_function_length': 0
        }
    }

    try:
        lines = code_content.split('\n')
        comment_lines = sum(1 for line in lines if line.strip().startswith('#'))
        blank_lines = sum(1 for line in lines if not line.strip())

        analysis['metrics']['comment_ratio'] = round(comment_lines / len(lines) * 100, 1)
        analysis['metrics']['blank_line_ratio'] = round(blank_lines / len(lines) * 100, 1)

        if file_extension in ['.py']:
            tree = ast.parse(code_content)
            function_lengths = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_end = getattr(node, 'end_lineno', node.lineno + 10)
                    func_length = func_end - node.lineno
                    function_lengths.append(func_length)

                    analysis['functions'].append({
                        'name': node.name,
                        'line': node.lineno,
                        'length': func_length,
                        'args': [arg.arg for arg in node.args.args],
                        'complexity': len([n for n in ast.walk(node) if isinstance(n, (ast.If, ast.For, ast.While))])
                    })
                elif isinstance(node, ast.ClassDef):
                    methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                    analysis['classes'].append({
                        'name': node.name,
                        'line': node.lineno,
                        'methods': len(methods),
                        'method_names': [m.name for m in methods]
                    })
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        analysis['imports'].append(alias.name)
                        analysis['dependencies'][alias.name] = 'standard'
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        full_import = f"from {node.module}"
                        analysis['imports'].append(full_import)
                        analysis['dependencies'][node.module] = 'external' if '.' not in node.module else 'local'

            if function_lengths:
                analysis['metrics']['avg_function_length'] = round(sum(function_lengths) / len(function_lengths), 1)

        # Enhanced complexity calculation
        analysis['complexity_score'] = (
            len(analysis['functions']) + 
            len(analysis['classes']) * 2 + 
            len(analysis['imports']) * 0.5
        )

        # Code quality score (0-100)
        quality_score = 100
        if analysis['metrics']['comment_ratio'] < 10:
            quality_score -= 20
        if analysis['metrics']['avg_function_length'] > 20:
            quality_score -= 15
        if analysis['complexity_score'] > 50:
            quality_score -= 25

        analysis['quality_score'] = max(0, round(quality_score))

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
        if file_extension == '.pdf' and HAS_DOC_SUPPORT:
            try:
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    content = ""
                    for page in pdf_reader.pages:
                        content += page.extract_text() + "\n"
            except Exception as e:
                content = f"[PDF processing error: {str(e)}]"

        elif file_extension in ['.docx', '.doc'] and HAS_DOC_SUPPORT:
            try:
                doc = docx.Document(file_path)
                content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            except Exception as e:
                content = f"[Document processing error: {str(e)}]"

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
        if file_extension in ['.py', '.js', '.cs', '.java', '.cpp', '.c', '.h']:
            code_analysis = analyze_code_structure(content, file_extension)

            # Add analysis summary to content
            if 'error' not in code_analysis:
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
    session_id = get_session_id()

    # Load persistent chat history and store in session
    try:
        persistent_history = load_chat_history(session_id)
        session['chat_history'] = persistent_history
        print(f"Loaded {len(persistent_history)} chat exchanges for session {session_id[:8]}")
    except Exception as e:
        print(f"Error loading chat history: {e}")
        persistent_history = []
        session['chat_history'] = []

    if 'assistant_mode' not in session:
        session['assistant_mode'] = 'general'
    session.modified = True

    return render_template('index.html', modes=ASSISTANT_MODES, initial_chat_history=persistent_history)

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

        # Add uploaded files context
        if 'uploaded_files' in session and session['uploaded_files']:
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

        # Get selected model from session
        selected_model = session.get('ai_model', DEFAULT_MODEL)
        model_config = AVAILABLE_MODELS.get(selected_model, AVAILABLE_MODELS[DEFAULT_MODEL])

        response = openai.chat.completions.create(
            model=selected_model,
            messages=messages,
            temperature=0.7,
            max_tokens=model_config['max_tokens']
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

                # Add uploaded files context
                if uploaded_files:
                    files_context = "Uploaded files context:\n"
                    for filename, content in uploaded_files.items():
                        files_context += f"\n--- {filename} ---\n{content[:2000]}{'...' if len(content) > 2000 else ''}\n"
                    messages.append({"role": "system", "content": files_context})

                # Add recent history
                for chat in chat_history[-15:]:
                    messages.append({"role": "user", "content": chat['user']})
                    messages.append({"role": "assistant", "content": chat['assistant']})

                messages.append({"role": "user", "content": user_message})

                # Get selected model from session
                selected_model = session.get('ai_model', DEFAULT_MODEL)
                model_config = AVAILABLE_MODELS.get(selected_model, AVAILABLE_MODELS[DEFAULT_MODEL])

                # Stream response
                stream = openai.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=model_config['max_tokens'],
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
            allowed_types = ', '.join(sorted(ALLOWED_EXTENSIONS))
            return jsonify({'error': f'File type not allowed. Supported types: {allowed_types}'}), 400

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

@app.route('/get_modes', methods=['GET'])
def get_modes():
    return jsonify({'modes': ASSISTANT_MODES})

@app.route('/set_model', methods=['POST'])
def set_model():
    """Set the AI model for the session"""
    try:
        data = request.get_json()
        model = data.get('model', DEFAULT_MODEL)

        if model not in AVAILABLE_MODELS:
            return jsonify({'error': 'Invalid model'}), 400

        session['ai_model'] = model
        session.modified = True

        return jsonify({
            'success': True, 
            'model': model,
            'model_info': AVAILABLE_MODELS[model]
        })
    except Exception as e:
        return jsonify({'error': f'Error setting model: {str(e)}'}), 500

@app.route('/get_models', methods=['GET'])
def get_models():
    """Get available AI models"""
    return jsonify({'models': AVAILABLE_MODELS, 'default': DEFAULT_MODEL})

@app.route('/get_analytics', methods=['GET'])
def get_analytics():
    """Get conversation analytics and insights"""
    try:
        session_id = get_session_id()

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Basic conversation stats
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_exchanges,
                    COUNT(DISTINCT mode) as modes_used,
                    AVG(LENGTH(user_message)) as avg_user_length,
                    AVG(LENGTH(assistant_response)) as avg_response_length,
                    MIN(timestamp) as first_exchange,
                    MAX(timestamp) as last_exchange
                FROM chat_exchanges 
                WHERE session_id = ?
            ''', (session_id,))

            stats = dict(cursor.fetchone())

            # Mode usage statistics
            cursor.execute('''
                SELECT mode, COUNT(*) as count
                FROM chat_exchanges 
                WHERE session_id = ?
                GROUP BY mode
                ORDER BY count DESC
            ''', (session_id,))

            mode_stats = [dict(row) for row in cursor.fetchall()]

            # Recent activity pattern
            cursor.execute('''
                SELECT 
                    DATE(timestamp) as date,
                    COUNT(*) as exchanges
                FROM chat_exchanges 
                WHERE session_id = ? AND datetime(timestamp) >= datetime('now', '-30 days')
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
                LIMIT 30
            ''', (session_id,))

            activity_pattern = [dict(row) for row in cursor.fetchall()]

            return jsonify({
                'success': True,
                'stats': stats,
                'mode_usage': mode_stats,
                'activity_pattern': activity_pattern,
                'insights': generate_insights(stats, mode_stats)
            })

    except Exception as e:
        return jsonify({'error': f'Analytics error: {str(e)}'}), 500

def generate_insights(stats, mode_stats):
    """Generate intelligent insights from conversation data"""
    insights = []

    if stats['total_exchanges'] > 0:
        # Usage insights
        if stats['total_exchanges'] > 10:
            insights.append("🎯 You're an active user! Your engagement shows deep architectural thinking.")

        # Mode preferences
        if mode_stats:
            top_mode = mode_stats[0]['mode']
            mode_name = ASSISTANT_MODES.get(top_mode, {}).get('name', top_mode)
            insights.append(f"📊 Your favorite mode is {mode_name}, showing focus on this area.")

        # Communication style
        avg_user_length = stats.get('avg_user_length', 0)
        if avg_user_length > 200:
            insights.append("📝 You provide detailed context, which leads to better AI responses.")
        elif avg_user_length < 50:
            insights.append("💡 Try providing more context in your questions for enhanced responses.")

        # Response complexity
        avg_response_length = stats.get('avg_response_length', 0)
        if avg_response_length > 1000:
            insights.append("🔍 You're getting comprehensive, detailed responses from the AI.")

    return insights

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
        days = request.json.get('days', 30) if request.is_json else 30

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

@app.route('/generate_image', methods=['POST'])
def generate_image():
    """Generate images using DALL-E"""
    try:
        data = request.get_json()
        prompt = data.get('prompt', '').strip()
        size = data.get('size', '1024x1024')  # Default size
        quality = data.get('quality', 'standard')  # standard or hd

        if not prompt:
            return jsonify({'error': 'Image prompt cannot be empty'}), 400

        if not openai.api_key:
            return jsonify({'error': 'OpenAI API key not configured'}), 500

        # Generate image using DALL-E
        response = openai.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )

        image_url = response.data[0].url
        revised_prompt = response.data[0].revised_prompt

        # Save image info to session for context
        session_id = get_session_id()
        if 'generated_images' not in session:
            session['generated_images'] = []

        image_info = {
            'url': image_url,
            'prompt': prompt,
            'revised_prompt': revised_prompt,
            'timestamp': datetime.now().isoformat(),
            'size': size,
            'quality': quality
        }

        session['generated_images'].append(image_info)
        session.modified = True

        return jsonify({
            'success': True,
            'image_url': image_url,
            'revised_prompt': revised_prompt,
            'prompt': prompt,
            'size': size,
            'quality': quality
        })

    except Exception as e:
        return jsonify({'error': f'Image generation error: {str(e)}'}), 500

@app.route('/analyze_image', methods=['POST'])
def analyze_image():
    """Analyze uploaded images using GPT-4 Vision"""
    try:
        data = request.get_json()
        image_url = data.get('image_url', '')
        question = data.get('question', 'Describe this image in detail')

        if not image_url:
            return jsonify({'error': 'Image URL is required'}), 400

        if not openai.api_key:
            return jsonify({'error': 'OpenAI API key not configured'}), 500

        # Use GPT-4 Vision to analyze the image
        response = openai.chat.completions.create(
            model="gpt-4-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url}
                        }
                    ]
                }
            ],
            max_tokens=1000
        )

        analysis = response.choices[0].message.content

        return jsonify({
            'success': True,
            'analysis': analysis,
            'question': question,
            'image_url': image_url
        })

    except Exception as e:
        return jsonify({'error': f'Image analysis error: {str(e)}'}), 500

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
    app.run(host='0.0.0.0', port=5000, debug=True)