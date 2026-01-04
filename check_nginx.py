import paramiko

HOST = "46.224.91.14"
USERNAME = "root"
PASSWORD = "Smalldirty!0"

def check_nginx():
    print(f"🔌 Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(HOST, username=USERNAME, password=PASSWORD)
        print("✅ Connected!")

        print("\n📂 Listing /etc/nginx/sites-enabled/ ...")
        stdin, stdout, stderr = ssh.exec_command("ls -l /etc/nginx/sites-enabled/")
        print(stdout.read().decode())
        
        print("\n📄 Reading default site config (if exists)...")
        stdin, stdout, stderr = ssh.exec_command("cat /etc/nginx/sites-enabled/default")
        print(stdout.read().decode())

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    check_nginx()
