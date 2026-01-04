from flask import Blueprint, request, jsonify, session, current_app
from app.services.db_service import DBService
from functools import wraps

auth_bp = Blueprint('auth', __name__)
db_service = DBService()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        if session.get('role') != 'admin':
            return jsonify({'error': 'Forbidden: Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
            
        user = db_service.verify_user(username, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session.modified = True
            
            return jsonify({
                'success': True,
                'user': {
                    'id': user['id'],
                    'username': user['username'],
                    'role': user['role']
                }
            })
        else:
            return jsonify({'error': 'Invalid credentials'}), 401
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@auth_bp.route('/check_auth', methods=['GET'])
def check_auth():
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'user': {
                'id': session['user_id'],
                'username': session['username'],
                'role': session.get('role', 'user')
            }
        })
    return jsonify({'authenticated': False})

# ========================================
# Admin User Management Routes
# ========================================

@auth_bp.route('/admin/users', methods=['GET'])
@admin_required
def list_users():
    users = db_service.get_all_users()
    return jsonify({'users': users})

@auth_bp.route('/admin/users', methods=['POST'])
@admin_required
def create_user():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'user')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
        
    if db_service.create_user(username, password, role):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to create user (username may already exist)'}), 400

@auth_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    # Prevent deleting self
    if user_id == session.get('user_id'):
        return jsonify({'error': 'Cannot delete your own account'}), 400
        
    if db_service.delete_user(user_id):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to delete user'}), 500

@auth_bp.route('/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    data = request.get_json()
    username = data.get('username')
    role = data.get('role')
    password = data.get('password')
    
    # 1. Update basic details (username, role)
    if username or role:
        if not db_service.update_user_details(user_id, username, role):
            return jsonify({'error': 'Failed to update user details (username might be taken)'}), 400
            
    # 2. Update password if provided
    if password:
        if not db_service.update_user_password(user_id, password):
            return jsonify({'error': 'Failed to update password'}), 500
            
    return jsonify({'success': True})

@auth_bp.route('/admin/users/<int:user_id>/password', methods=['POST'])
@admin_required
def update_password(user_id):
    data = request.get_json()
    new_password = data.get('password')
    
    if not new_password:
        return jsonify({'error': 'New password required'}), 400
        
    if db_service.update_user_password(user_id, new_password):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to update password'}), 500
