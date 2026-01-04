import paramiko
import time

# Server Details
HOST = "46.224.91.14"
USERNAME = "root"
PASSWORD = "Smalldirty!0"

def run_diagnostics():
    print(f"🔌 Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(HOST, username=USERNAME, password=PASSWORD)
        print("✅ Connected!")

        # 1. Check Listening Ports
        print("\n🔍 Checking Listening Ports (netstat -tulnp)...")
        stdin, stdout, stderr = ssh.exec_command("netstat -tulnp")
        print(stdout.read().decode())
        print(stderr.read().decode())

        # 2. Check Firewall Status
        print("\n🔥 Checking Firewall Status (ufw status)...")
        stdin, stdout, stderr = ssh.exec_command("ufw status")
        print(stdout.read().decode())
        print(stderr.read().decode())
        
        # 3. Local Connectivity Test
        print("\n📞 Testing Local Connectivity (curl -v http://127.0.0.1:8080)...")
        stdin, stdout, stderr = ssh.exec_command("curl -v http://127.0.0.1:8080")
        output = stdout.read().decode()
        error = stderr.read().decode()
        print(output[:500]) # First 500 chars
        print(error)

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    run_diagnostics()
