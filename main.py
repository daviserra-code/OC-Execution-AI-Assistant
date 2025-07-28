from flask import Flask, render_template, request, jsonify, session
import openai
import os
import sys
import base64
from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', str(uuid.uuid4()))

openai.api_key = os.environ.get('OPENAI_API_KEY', '')

if not openai.api_key:
    print("⚠️  Warning: OPENAI_API_KEY not set. Please add it to Secrets.")

# Software Architecture Assistant System Prompt
ARCHITECTURE_PROMPT = """You are a highly experienced and proactive Software Architecture Assistant specializing in modern software patterns, architectural decision-making, documentation, and stakeholder communication, as well as a coding assistant for Siemens Opcenter Execution Foundation, Process, and Discrete platforms.

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

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'py', 'js', 'html', 'css', 'json', 'xml'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_uploaded_file(file_path):
    """Process uploaded file and return its content"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # For binary files, return a description
        return f"[Binary file: {os.path.basename(file_path)}]"
    except Exception as e:
        return f"[Error reading file: {str(e)}]"

@app.route('/')
def index():
    if 'chat_history' not in session:
        session['chat_history'] = []
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'Message cannot be empty'}), 400
        
        if not openai.api_key:
            return jsonify({'error': 'OpenAI API key not configured. Please add OPENAI_API_KEY to Secrets.'}), 500
        
        # Initialize chat history if not exists
        if 'chat_history' not in session:
            session['chat_history'] = []
        
        # Build messages for OpenAI
        messages = [{"role": "system", "content": ARCHITECTURE_PROMPT}]
        
        # Add previous chat history
        for chat in session['chat_history'][-10:]:  # Keep last 10 exchanges
            messages.append({"role": "user", "content": chat['user']})
            messages.append({"role": "assistant", "content": chat['assistant']})
        
        # Add current message
        messages.append({"role": "user", "content": user_message})
        
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=2500
        )
        
        assistant_response = response.choices[0].message.content
        
        # Save to chat history
        session['chat_history'].append({
            'user': user_message,
            'assistant': assistant_response
        })
        session.modified = True
        
        return jsonify({'response': assistant_response})
        
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

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
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            
            # Process the file content
            file_content = process_uploaded_file(file_path)
            
            return jsonify({
                'success': True,
                'filename': filename,
                'content': file_content[:1000] + ('...' if len(file_content) > 1000 else '')  # Preview
            })
        else:
            return jsonify({'error': 'File type not allowed'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Upload error: {str(e)}'}), 500

@app.route('/clear_history', methods=['POST'])
def clear_history():
    session['chat_history'] = []
    session.modified = True
    return jsonify({'success': True})

@app.route('/get_prompt', methods=['GET'])
def get_prompt():
    try:
        return jsonify({'prompt': ARCHITECTURE_PROMPT})
    except Exception as e:
        return jsonify({'error': f'Error retrieving prompt: {str(e)}'}), 500

@app.route('/get_history', methods=['GET'])
def get_history():
    try:
        chat_history = session.get('chat_history', [])
        return jsonify({'history': chat_history, 'count': len(chat_history)})
    except Exception as e:
        return jsonify({'error': f'Error retrieving chat history: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
