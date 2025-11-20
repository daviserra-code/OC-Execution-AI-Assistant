from flask import Blueprint, render_template, request, jsonify, session, Response, current_app
from app.services.db_service import DBService
from app.services.rag_service import rag_service
from app.services.openai_service import openai_service
from app.utils.file_processing import process_uploaded_file, allowed_file
from app.config import ASSISTANT_MODES
from werkzeug.utils import secure_filename
import os
import time
import json
import uuid
import hashlib
import threading
from datetime import datetime

main_bp = Blueprint('main', __name__)

# Initialize DB Service
# Note: We initialize it here, but in a real app we might want to use current_app.config
# We'll assume the default path for now or get it from config in the route
db_service = DBService()

# Response cache
response_cache = {}
cache_lock = threading.Lock()

def get_session_id():
    """Get or create a session ID"""
    if 'user_session_id' not in session:
        session['user_session_id'] = str(uuid.uuid4())
        session.modified = True

        # Create session in database
        db_service.create_session(session['user_session_id'])
        print(f"Created new session: {session['user_session_id'][:8]}...")

    return session['user_session_id']

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

@main_bp.route('/')
def index():
    # Fast path for health checks
    accept_header = request.headers.get('Accept', '')
    user_agent = request.headers.get('User-Agent', '').lower()

    if ('health' in user_agent or 'ping' in user_agent or 
        not accept_header.startswith('text/html') or
        'curl' in user_agent or 'wget' in user_agent):
        return {'status': 'ok', 'timestamp': time.time()}, 200

    try:
        if 'chat_history' not in session:
            session['chat_history'] = []
        if 'assistant_mode' not in session:
            session['assistant_mode'] = 'general'

        session_id = get_session_id()
        session.modified = True

        return render_template('index.html', modes=ASSISTANT_MODES, initial_chat_history=[])
    except Exception as e:
        print(f"Error in index route: {e}")
        return render_template('index.html', modes=ASSISTANT_MODES, initial_chat_history=[])

@main_bp.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        regenerate = data.get('regenerate', False)

        if not user_message and not regenerate:
            return jsonify({'error': 'Message cannot be empty'}), 400

        # Initialize chat history if not exists
        if 'chat_history' not in session:
            session['chat_history'] = []

        mode = session.get('assistant_mode', 'general')

        # Get custom prompt from database if available
        with db_service.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT custom_prompt FROM system_prompts WHERE mode = ?', (mode,))
            row = cursor.fetchone()
            current_prompt = row['custom_prompt'] if row else ASSISTANT_MODES[mode]['prompt']

        # Handle regeneration
        if regenerate and session['chat_history']:
            session['chat_history'].pop()
            user_message = session['chat_history'][-1]['user'] if session['chat_history'] else user_message

        # Check cache
        context_summary = summarize_context(session['chat_history'])
        cache_key = get_cache_key(user_message, mode, context_summary)

        with cache_lock:
            if cache_key in response_cache and not regenerate:
                cached_response = response_cache[cache_key]
                if time.time() - cached_response['timestamp'] < 3600:
                    session['chat_history'].append({
                        'user': user_message,
                        'assistant': cached_response['response'],
                        'timestamp': datetime.now().isoformat(),
                        'mode': mode
                    })
                    session.modified = True
                    return jsonify({'response': cached_response['response'], 'cached': True})

        # Build messages
        messages = [{"role": "system", "content": current_prompt}]

        if context_summary:
            messages.append({"role": "system", "content": f"Previous conversation context: {context_summary}"})

        # RAG Context
        rag_context = rag_service.get_context(user_message)
        if rag_context:
            messages.append({"role": "system", "content": rag_context})
        elif 'uploaded_files' in session and session['uploaded_files']:
            files_context = "Uploaded files context:\n"
            for filename, content_data in session['uploaded_files'].items():
                content = content_data['content']
                files_context += f"\n--- {filename} ---\n{content[:2000]}{'...' if len(content) > 2000 else ''}\n"
            messages.append({"role": "system", "content": files_context})

        # History
        for chat in session['chat_history'][-15:]:
            messages.append({"role": "user", "content": chat['user']})
            messages.append({"role": "assistant", "content": chat['assistant']})

        messages.append({"role": "user", "content": user_message})

        # Call OpenAI
        response = openai_service.get_chat_completion(messages)
        assistant_response = response.choices[0].message.content

        # Cache
        with cache_lock:
            response_cache[cache_key] = {
                'response': assistant_response,
                'timestamp': time.time()
            }

        # Save
        session_id = get_session_id()
        db_service.save_exchange(session_id, user_message, assistant_response, mode)

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

@main_bp.route('/chat_stream', methods=['POST'])
def chat_stream():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()

        if not user_message:
            return jsonify({'error': 'Message cannot be empty'}), 400

        if 'chat_history' not in session:
            session['chat_history'] = []

        chat_history = session.get('chat_history', [])
        mode = session.get('assistant_mode', 'general')
        uploaded_files = session.get('uploaded_files', {})

        def generate():
            try:
                with db_service.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT custom_prompt FROM system_prompts WHERE mode = ?', (mode,))
                    row = cursor.fetchone()
                    current_prompt = row['custom_prompt'] if row else ASSISTANT_MODES[mode]['prompt']

                messages = [{"role": "system", "content": current_prompt}]
                
                context_summary = summarize_context(chat_history)
                if context_summary:
                    messages.append({"role": "system", "content": f"Previous conversation context: {context_summary}"})

                rag_context = rag_service.get_context(user_message)
                if rag_context:
                    messages.append({"role": "system", "content": rag_context})
                elif uploaded_files:
                    files_context = "Uploaded files context:\n"
                    for filename, content_data in uploaded_files.items():
                        content = content_data['content']
                        files_context += f"\n--- {filename} ---\n{content[:2000]}{'...' if len(content) > 2000 else ''}\n"
                    messages.append({"role": "system", "content": files_context})

                for chat in chat_history[-15:]:
                    messages.append({"role": "user", "content": chat['user']})
                    messages.append({"role": "assistant", "content": chat['assistant']})

                messages.append({"role": "user", "content": user_message})

                stream = openai_service.get_chat_stream(messages)

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

@main_bp.route('/upload', methods=['POST'])
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
            
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
            file_path = os.path.join(upload_folder, safe_filename)
            file.save(file_path)

            # Enhanced file processing
            file_content, code_analysis = process_uploaded_file(file_path)
            
            # Store in session
            if 'uploaded_files' not in session:
                session['uploaded_files'] = {}
            
            file_extension = os.path.splitext(file.filename)[1].lower()
            
            # Add to RAG
            rag_service.add_document(file_content, filename, file_extension)

            session['uploaded_files'][filename] = {
                'content': file_content,
                'type': file_extension,
                'size': len(file_content),
                'analysis': code_analysis
            }
            session.modified = True

            # Clean up
            try:
                os.remove(file_path)
            except:
                pass
            
            # Prepare response info (simplified for brevity, can add back detailed type info)
            preview_content = file_content[:1000] + ('...' if len(file_content) > 1000 else '')
            
            return jsonify({
                'success': True,
                'filename': safe_filename,
                'original_name': file.filename,
                'content': preview_content,
                'full_content': file_content,
                'size': len(file_content),
                'analysis': code_analysis
            })
        else:
            return jsonify({'error': 'File type not allowed'}), 400

    except Exception as e:
        return jsonify({'error': f'Upload error: {str(e)}'}), 500

@main_bp.route('/set_mode', methods=['POST'])
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

@main_bp.route('/export_conversation', methods=['GET'])
def export_conversation():
    try:
        session_id = get_session_id()
        chat_history = db_service.get_history(session_id, limit=1000)
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

@main_bp.route('/clear_history', methods=['POST'])
def clear_history():
    try:
        session_id = get_session_id()
        db_service.clear_history(session_id)

        session['chat_history'] = []
        session['uploaded_files'] = {}
        session.modified = True

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Error clearing history: {str(e)}'}), 500

@main_bp.route('/get_prompt', methods=['GET'])
def get_prompt():
    try:
        mode = session.get('assistant_mode', 'general')

        with db_service.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT custom_prompt FROM system_prompts WHERE mode = ?', (mode,))
            row = cursor.fetchone()
            prompt = row['custom_prompt'] if row else ASSISTANT_MODES[mode]['prompt']

        return jsonify({
            'prompt': prompt,
            'mode': mode,
            'mode_info': ASSISTANT_MODES[mode]
        })
    except Exception as e:
        return jsonify({'error': f'Error retrieving prompt: {str(e)}'}), 500

@main_bp.route('/get_history', methods=['GET'])
def get_history():
    try:
        session_id = get_session_id()
        chat_history = db_service.get_history(session_id, limit=100)
        session['chat_history'] = chat_history
        session.modified = True
        return jsonify({'history': chat_history, 'count': len(chat_history)})
    except Exception as e:
        return jsonify({'error': f'Error retrieving chat history: {str(e)}', 'history': [], 'count': 0}), 200

@main_bp.route('/health', methods=['GET'])
def health_check():
    return {'status': 'healthy', 'timestamp': time.time()}, 200

@main_bp.route('/get_modes', methods=['GET'])
def get_modes():
    return jsonify({'modes': ASSISTANT_MODES})

@main_bp.route('/get_session_info', methods=['GET'])
def get_session_info():
    try:
        session_id = get_session_id()
        with db_service.get_connection() as conn:
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

@main_bp.route('/test_db', methods=['GET'])
def test_db():
    try:
        stats = db_service.get_stats()
        return jsonify({
            'success': True,
            'session_count': stats['sessions'],
            'exchange_count': stats['exchanges']
        })
    except Exception as e:
        return jsonify({'error': f'Database test error: {str(e)}'}), 500

@main_bp.route('/save_chat', methods=['POST'])
def save_chat():
    try:
        data = request.get_json()
        user_message = data.get('user_message', '')
        assistant_response = data.get('assistant_response', '')
        mode = data.get('mode', 'general')

        if not user_message or not assistant_response:
            return jsonify({'error': 'Missing message data'}), 400

        session_id = get_session_id()
        db_service.save_exchange(session_id, user_message, assistant_response, mode)

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

@main_bp.route('/search_documents', methods=['POST'])
def search_documents():
    try:
        data = request.get_json()
        query = data.get('query', '').strip()

        if not query:
            return jsonify({'error': 'Query cannot be empty'}), 400

        results = rag_service.search(query, top_k=10, similarity_threshold=0.2)

        return jsonify({
            'success': True,
            'query': query,
            'results': results,
            'total_results': len(results)
        })
    except Exception as e:
        return jsonify({'error': f'Search error: {str(e)}'}), 500

@main_bp.route('/vector_db_stats', methods=['GET'])
def vector_db_stats():
    try:
        if not rag_service.initialized:
            return jsonify({'initialized': False, 'error': 'Vector database not initialized'})

        return jsonify({
            'initialized': True,
            'document_count': len(rag_service.document_metadata), # Approximation
            'vector_dimension': 384,
            'model_name': 'all-MiniLM-L6-v2'
        })
    except Exception as e:
        return jsonify({'error': f'Stats error: {str(e)}'}), 500

@main_bp.route('/clear_vector_db', methods=['POST'])
def clear_vector_db():
    try:
        rag_service.clear()
        return jsonify({'success': True, 'message': 'Vector database cleared successfully'})
    except Exception as e:
        return jsonify({'error': f'Clear error: {str(e)}'}), 500

@main_bp.route('/save_system_prompt', methods=['POST'])
def save_system_prompt():
    try:
        data = request.get_json()
        mode = data.get('mode', 'general')
        custom_prompt = data.get('prompt', '').strip()

        if not custom_prompt:
            return jsonify({'error': 'Prompt cannot be empty'}), 400

        if mode not in ASSISTANT_MODES:
            return jsonify({'error': 'Invalid mode'}), 400

        with db_service.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO system_prompts (mode, custom_prompt, modified_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (mode, custom_prompt))
            conn.commit()

        return jsonify({
            'success': True,
            'mode': mode,
            'mode_info': ASSISTANT_MODES[mode],
            'message': f'System prompt for {ASSISTANT_MODES[mode]["name"]} mode saved successfully'
        })
    except Exception as e:
        return jsonify({'error': f'Error saving system prompt: {str(e)}'}), 500

@main_bp.route('/reset_system_prompt', methods=['POST'])
def reset_system_prompt():
    try:
        data = request.get_json()
        mode = data.get('mode', 'general')

        if mode not in ASSISTANT_MODES:
            return jsonify({'error': 'Invalid mode'}), 400

        with db_service.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM system_prompts WHERE mode = ?', (mode,))
            conn.commit()

        default_prompt = ASSISTANT_MODES[mode]['prompt']

        return jsonify({
            'success': True,
            'mode': mode,
            'mode_info': ASSISTANT_MODES[mode],
            'default_prompt': default_prompt,
            'message': f'System prompt for {ASSISTANT_MODES[mode]["name"]} mode reset to default'
        })
    except Exception as e:
        return jsonify({'error': f'Error resetting system prompt: {str(e)}'}), 500

@main_bp.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@main_bp.route('/dashboard/metrics')
def dashboard_metrics():
    try:
        stats = db_service.get_stats()
        return jsonify({
            'sessions': stats['sessions'],
            'exchanges': stats['exchanges'],
            'vector_db_initialized': rag_service.initialized
        })
    except Exception as e:
        return jsonify({'error': f'Metrics error: {str(e)}'}), 500

@main_bp.route('/templates/<template_type>')
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
