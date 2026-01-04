import paramiko
import time

# Server Details
HOST = "46.224.91.14"
USERNAME = "root"
PASSWORD = "Smalldirty!0"

def check_logs():
    print(f"🔌 Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(HOST, username=USERNAME, password=PASSWORD)
        print("✅ Connected!")

        # Check Service Status
        print("\n🔍 Checking Service Status...")
        stdin, stdout, stderr = ssh.exec_command("systemctl status teyra")
        print(stdout.read().decode())
        print(stderr.read().decode())

        # Check Logs
        print("\n📜 Fetching Recent Logs...")
        stdin, stdout, stderr = ssh.exec_command("journalctl -u teyra -n 50 --no-pager")
        print(stdout.read().decode())
        print(stderr.read().decode())

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    check_logs()
