import requests
import json

BASE_URL = "http://localhost:8080"
SESSION = requests.Session()

def print_result(name, success, msg=""):
    icon = "✅" if success else "❌"
    print(f"{icon} {name}: {msg}")

def test_auth_flow():
    print("\n🚀 Starting Auth & Admin Verification Test\n")

    # 1. Login as Default Admin
    print("--- Testing Admin Login ---")
    try:
        resp = SESSION.post(f"{BASE_URL}/login", json={
            "username": "admin",
            "password": "admin123"
        })
        if resp.status_code == 200:
            data = resp.json()
            if data.get('success') and data['user']['role'] == 'admin':
                print_result("Admin Login", True, f"Logged in as {data['user']['username']}")
            else:
                print_result("Admin Login", False, "Invalid response payload")
                return False
        else:
            print_result("Admin Login", False, f"Status {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print_result("Admin Login", False, f"Connection error: {e}")
        return False

    # 2. Test Admin Privileges (List Users)
    print("\n--- Testing Admin Privileges ---")
    try:
        resp = SESSION.get(f"{BASE_URL}/admin/users")
        if resp.status_code == 200:
            users = resp.json().get('users', [])
            print_result("List Users", True, f"Found {len(users)} users")
        else:
            print_result("List Users", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("List Users", False, str(e))

    # 3. Create New User via Admin API
    print("\n--- Testing User Creation ---")
    new_user = "test_user_v1"
    try:
        resp = SESSION.post(f"{BASE_URL}/admin/users", json={
            "username": new_user,
            "password": "password123",
            "role": "user"
        })
        if resp.status_code == 200:
            print_result("Create User", True, f"Created {new_user}")
        else:
            print_result("Create User", False, f"Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("Create User", False, str(e))

    # 4. Logout Admin
    SESSION.post(f"{BASE_URL}/logout")
    print("\n--- Admin Logged Out ---")

    # 5. Login as New User
    print("\n--- Testing Regular User Login ---")
    user_session = requests.Session()
    try:
        resp = user_session.post(f"{BASE_URL}/login", json={
            "username": new_user,
            "password": "password123"
        })
        if resp.status_code == 200:
            print_result("User Login", True, "Success")
        else:
            print_result("User Login", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("User Login", False, str(e))

    # 6. Verify RBAC (User trying to access Admin API)
    print("\n--- Testing RBAC (Forbidden Access) ---")
    try:
        resp = user_session.get(f"{BASE_URL}/admin/users")
        if resp.status_code == 403:
            print_result("RBAC Check", True, "Access Forbidden as expected")
        else:
            print_result("RBAC Check", False, f"Unexpected status {resp.status_code} (Should be 403)")
    except Exception as e:
        print_result("RBAC Check", False, str(e))

    # 7. Cleanup (Login as Admin to delete test user)
    print("\n--- Cleanup ---")
    SESSION.post(f"{BASE_URL}/login", json={"username": "admin", "password": "admin123"})
    
    # Get ID of test user
    resp = SESSION.get(f"{BASE_URL}/admin/users")
    users = resp.json().get('users', [])
    target_id = next((u['id'] for u in users if u['username'] == new_user), None)
    
    if target_id:
        resp = SESSION.delete(f"{BASE_URL}/admin/users/{target_id}")
        if resp.status_code == 200:
            print_result("Delete User", True, "Test user deleted")
        else:
            print_result("Delete User", False, "Failed to delete test user")
    else:
        print_result("Delete User", False, "Test user not found in list")

if __name__ == "__main__":
    test_auth_flow()
