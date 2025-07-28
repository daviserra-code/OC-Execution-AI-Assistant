
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

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', str(uuid.uuid4()))

openai.api_key = os.environ.get('OPENAI_API_KEY', '')

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

def process_uploaded_file(file_path):
    """Process uploaded file and return its content"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Store full content in session for context
            if 'uploaded_files' not in session:
                session['uploaded_files'] = {}
            session['uploaded_files'][os.path.basename(file_path)] = content
            session.modified = True
            return content
    except UnicodeDecodeError:
        try:
            # Try with different encoding
            with open(file_path, 'r', encoding='latin-1') as f:
                return f.read()
        except:
            return f"[Binary file: {os.path.basename(file_path)}]"
    except Exception as e:
        return f"[Error reading file: {str(e)}]"

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
    if 'chat_history' not in session:
        session['chat_history'] = []
    if 'assistant_mode' not in session:
        session['assistant_mode'] = 'general'
    return render_template('index.html', modes=ASSISTANT_MODES)

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
        current_prompt = ASSISTANT_MODES[mode]['prompt']
        
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
        
        # Save to chat history
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
        
        def generate():
            try:
                if 'chat_history' not in session:
                    session['chat_history'] = []
                
                mode = session.get('assistant_mode', 'general')
                current_prompt = ASSISTANT_MODES[mode]['prompt']
                
                # Build messages
                messages = [{"role": "system", "content": current_prompt}]
                
                # Add context
                context_summary = summarize_context(session['chat_history'])
                if context_summary:
                    messages.append({"role": "system", "content": f"Previous conversation context: {context_summary}"})
                
                # Add uploaded files context
                if 'uploaded_files' in session and session['uploaded_files']:
                    files_context = "Uploaded files context:\n"
                    for filename, content in session['uploaded_files'].items():
                        files_context += f"\n--- {filename} ---\n{content[:2000]}{'...' if len(content) > 2000 else ''}\n"
                    messages.append({"role": "system", "content": files_context})
                
                # Add recent history
                for chat in session['chat_history'][-15:]:
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
                
                # Save to history after streaming is complete
                session['chat_history'].append({
                    'user': user_message,
                    'assistant': full_response,
                    'timestamp': datetime.now().isoformat(),
                    'mode': mode
                })
                session.modified = True
                
                yield f"data: {json.dumps({'done': True})}\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return Response(generate(), mimetype='text/plain')
        
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
            filename = f"{timestamp}_{filename}"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            
            # Process the file content
            file_content = process_uploaded_file(file_path)
            
            return jsonify({
                'success': True,
                'filename': filename,
                'original_name': file.filename,
                'content': file_content[:1000] + ('...' if len(file_content) > 1000 else ''),
                'full_content': file_content
            })
        else:
            return jsonify({'error': 'File type not allowed'}), 400
            
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
        chat_history = session.get('chat_history', [])
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
    session['chat_history'] = []
    session['uploaded_files'] = {}
    session.modified = True
    return jsonify({'success': True})

@app.route('/get_prompt', methods=['GET'])
def get_prompt():
    try:
        mode = session.get('assistant_mode', 'general')
        return jsonify({
            'prompt': ASSISTANT_MODES[mode]['prompt'],
            'mode': mode,
            'mode_info': ASSISTANT_MODES[mode]
        })
    except Exception as e:
        return jsonify({'error': f'Error retrieving prompt: {str(e)}'}), 500

@app.route('/get_history', methods=['GET'])
def get_history():
    try:
        chat_history = session.get('chat_history', [])
        return jsonify({'history': chat_history, 'count': len(chat_history)})
    except Exception as e:
        return jsonify({'error': f'Error retrieving chat history: {str(e)}'}), 500

@app.route('/get_modes', methods=['GET'])
def get_modes():
    return jsonify({'modes': ASSISTANT_MODES})

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
