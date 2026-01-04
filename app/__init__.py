from flask import Flask
import os
import uuid

def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', str(uuid.uuid4()))
    
    # Configuration
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['DATABASE_PATH'] = 'chat_history.db'
    
    # Ensure upload folder exists
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    # Register Blueprints
    from app.routes.main_routes import main_bp
    app.register_blueprint(main_bp)

    from app.routes.auth_routes import auth_bp
    app.register_blueprint(auth_bp)
    
    # Initialize RAG Service
    from app.services.rag_service import rag_service
    print("[INFO] Initializing RAG service from create_app...")
    rag_service.initialize()
    
    return app
