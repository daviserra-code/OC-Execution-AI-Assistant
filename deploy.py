import paramiko
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Server Details
HOST = "46.224.91.14"
USER = "root"
PASSWORD = "Smalldirty!0"
REMOTE_DIR = "/root/Teyra"

def create_ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=PASSWORD)
        return client
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

def run_command(client, command):
    print(f"Running: {command}")
    stdin, stdout, stderr = client.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status == 0:
        print(f"✅ Success")
        return True
    else:
        print(f"❌ Error: {stderr.read().decode()}")
        return False

def upload_files(sftp, local_dir, remote_dir):
    print(f"Uploading files from {local_dir} to {remote_dir}...")
    
    # Create remote directory if it doesn't exist
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass # Directory likely exists

    for root, dirs, files in os.walk(local_dir):
        # Skip hidden folders and venv
        if '.git' in root or '__pycache__' in root or 'venv' in root or '.gemini' in root:
            continue
            
        rel_path = os.path.relpath(root, local_dir)
        remote_path = os.path.join(remote_dir, rel_path).replace("\\", "/")
        
        if rel_path != ".":
            try:
                sftp.mkdir(remote_path)
            except IOError:
                pass

        for file in files:
            if file.endswith('.pyc') or file == 'deploy.py':
                continue
                
            local_file = os.path.join(root, file)
            remote_file = os.path.join(remote_path, file).replace("\\", "/")
            
            print(f"Uploading {file}...")
            sftp.put(local_file, remote_file)

def deploy():
    print("🚀 Starting Deployment to Hetzner...")
    
    client = create_ssh_client()
    sftp = client.open_sftp()
    
    # 1. Upload Files
    upload_files(sftp, os.getcwd(), REMOTE_DIR)
    sftp.close()
    
    # 2. Install System Dependencies
    print("\n📦 Installing system dependencies...")
    run_command(client, "apt-get update && apt-get install -y python3-pip python3-venv")
    
    # 3. Setup Virtual Environment
    print("\n🐍 Setting up Python environment...")
    run_command(client, f"cd {REMOTE_DIR} && python3 -m venv venv")
    
    # 4. Install Python Requirements
    print("\n📚 Installing Python requirements...")
    run_command(client, f"cd {REMOTE_DIR} && ./venv/bin/pip install -r requirements.txt")
    
    # 5. Create Systemd Service
    print("\n⚙️ Creating systemd service...")
    service_content = f"""[Unit]
Description=Teyra AI Assistant
After=network.target

[Service]
User=root
WorkingDirectory={REMOTE_DIR}
ExecStart={REMOTE_DIR}/venv/bin/python {REMOTE_DIR}/main.py
Restart=always
Environment=OPENAI_API_KEY={os.environ.get('OPENAI_API_KEY', '')}

[Install]
WantedBy=multi-user.target
"""
    # Write service file remotely
    sftp = client.open_sftp()
    with sftp.file("/etc/systemd/system/teyra.service", "w") as f:
        f.write(service_content)
    sftp.close()
    
    # 6. Start Service
    print("\n🚀 Starting service...")
    run_command(client, "systemctl daemon-reload")
    run_command(client, "systemctl enable teyra")
    run_command(client, "systemctl restart teyra")

    # 7. Configure Firewall
    print("\n🔥 Configuring Firewall...")
    run_command(client, "ufw allow 8080/tcp")
    run_command(client, "ufw reload")
    
    print("\n✅ Deployment Complete! App should be running.")
    client.close()

if __name__ == "__main__":
    deploy()
