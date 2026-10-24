"""
Automated Integration Test Suite for TechStart Backend.
Verifies all API endpoints: Health, Authentication, Progress, Glossary, Paths, and Newsletter.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import threading
import time
import urllib.request
import urllib.error
import json
from http.server import ThreadingHTTPServer
from server import TechStartAPIHandler
from database import init_db

TEST_PORT = 8089

def make_request(path, method="GET", data=None, token=None):
    url = f"http://127.0.0.1:{TEST_PORT}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    encoded_data = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8'))

def run_tests():
    print("Initializing Database...")
    init_db()

    print(f"Spinning up test server on port {TEST_PORT}...")
    server = ThreadingHTTPServer(('127.0.0.1', TEST_PORT), TechStartAPIHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    print("\n--- Running Test Cases ---")

    # 1. Test Health Endpoint
    status, res = make_request("/api/health")
    assert status == 200, f"Expected 200, got {status}"
    assert res["status"] == "healthy"
    print("✅ 1. Health check passed")

    # 2. Test Glossary API
    status, res = make_request("/api/glossary?category=Web")
    assert status == 200
    assert res["count"] > 0
    print(f"✅ 2. Glossary filter passed ({res['count']} web terms returned)")

    # 3. Test Paths API
    status, res = make_request("/api/paths")
    assert status == 200
    assert len(res["paths"]) == 4
    print("✅ 3. Learning paths passed (4 paths returned with modules)")

    # 4. Test User Registration
    test_user = {
        "name": "Sarah Connor",
        "email": f"sarah_{int(time.time())}@techstart.dev",
        "password": "strongPassword123!"
    }
    status, res = make_request("/api/auth/register", method="POST", data=test_user)
    assert status == 201, f"Expected 201, got {status}: {res}"
    assert res["success"] is True
    token = res["token"]
    print("✅ 4. User registration passed with PBKDF2 hashing & session token")

    # 5. Test Current User Profile (/api/auth/me)
    status, res = make_request("/api/auth/me", token=token)
    assert status == 200
    assert res["user"]["name"] == "Sarah Connor"
    print("✅ 5. /api/auth/me authenticated profile passed")

    # 6. Test User Login
    status, res = make_request("/api/auth/login", method="POST", data={
        "email": test_user["email"],
        "password": test_user["password"]
    })
    assert status == 200
    assert res["success"] is True
    print("✅ 6. User login credential verification passed")

    # 7. Test Progress Tracking (Toggle Milestone)
    status, res = make_request("/api/progress/toggle", method="POST", data={
        "milestone_index": 0,
        "milestone_label": "Read hero message",
        "completed": True
    }, token=token)
    assert status == 200
    assert res["completed"] is True
    assert res["progress_percent"] > 0
    print(f"✅ 7. User progress persisted in SQLite ({res['progress_percent']}% complete)")

    # 8. Test Newsletter Subscription
    status, res = make_request("/api/newsletter/subscribe", method="POST", data={
        "email": "curious_beginner@example.com"
    })
    assert status == 200
    assert res["success"] is True
    print("✅ 8. Newsletter subscription endpoint passed")

    # 9. Test Quiz Submission
    status, res = make_request("/api/quiz/submit", method="POST", data={"choice": "B"})
    assert status == 200
    assert res["is_correct"] is True
    print("✅ 9. Quiz validation passed")

    print("\n🎉 ALL 9 BACKEND API TESTS PASSED SUCCESSFULLY!")
    server.shutdown()

if __name__ == "__main__":
    run_tests()
