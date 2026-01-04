import paramiko

HOST = "46.224.91.14"
USERNAME = "root"
PASSWORD = "Smalldirty!0"

def apply_fix():
    print(f"🔌 Connecting to {HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(HOST, username=USERNAME, password=PASSWORD)
        print("✅ Connected!")
        
        print("🔥 Allowing port 8080...")
        stdin, stdout, stderr = client.exec_command("ufw allow 8080/tcp")
        print(stdout.read().decode())
        
        print("🔄 Reloading UFW...")
        stdin, stdout, stderr = client.exec_command("ufw reload")
        print(stdout.read().decode())
        
        print("✅ Fix applied.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    apply_fix()
