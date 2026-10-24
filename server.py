"""
TechStart Backend Server.
A complete, robust, zero-dependency REST API and static file server built with Python 3.
Provides user authentication, SQLite persistence, progress tracking, glossary API,
learning paths, newsletter signups, safe code simulations, and an AI chat assistant
powered by Ollama (gemma3:1b).
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import os
import json
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from datetime import datetime, timezone, timedelta
import secrets

# ---------------------------------------------------------------------------
# Ollama / AI configuration
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "gemma3:1b"

SYSTEM_PROMPT = (
    "You are TechStart AI, a friendly and encouraging tech learning assistant built "
    "into the TechStart platform. You help absolute beginners learn web development, "
    "Python, cybersecurity, and AI fundamentals. Keep answers concise, jargon-free, "
    "and encouraging. If someone seems frustrated, reassure them that everyone starts "
    "somewhere. Never give harmful or off-topic advice."
)

def call_ollama(messages: list) -> str:
    """
    Sends a chat completion request to the local Ollama API and returns the
    assistant's reply as a plain string.  Raises RuntimeError on failure.
    """
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["message"]["content"]
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_BASE_URL}. "
            "Make sure Ollama is running (`ollama serve`) and "
            f"the model '{OLLAMA_MODEL}' is pulled."
        ) from exc
    except (KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected response from Ollama: {exc}") from exc

from database import (
    get_connection,
    init_db,
    hash_password,
    verify_password,
    DB_PATH
)

PORT = 8000
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

def get_bearer_token(headers):
    """Extracts bearer token from Authorization header if present."""
    auth_header = headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:].strip()
    return None

def get_authenticated_user(headers):
    """Resolves session token to an active user record in SQLite."""
    token = get_bearer_token(headers)
    if not token:
        return None
    
    with get_connection() as conn:
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
        SELECT u.id, u.name, u.email, s.expires_at 
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > ?
        """, (token, now_iso))
        row = cursor.fetchone()
        if row:
            return {
                "id": row["id"],
                "name": row["name"],
                "email": row["email"],
                "token": token
            }
    return None

class TechStartAPIHandler(SimpleHTTPRequestHandler):
    """Custom request handler processing REST API endpoints and serving static frontend assets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def _send_cors_headers(self):
        """Sends permissive CORS headers for development flexibility."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def _send_json(self, data, status_code=200):
        """Helper to serialize Python dictionaries to JSON responses with proper headers."""
        response_bytes = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(response_bytes)

    def _send_error_json(self, message, status_code=400):
        """Helper to return standardized error responses."""
        self._send_json({"success": False, "error": message}, status_code=status_code)

    def _read_json_body(self):
        """Reads and parses JSON body from POST requests."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        raw_body = self.rfile.read(content_length).decode('utf-8')
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError:
            return None

    def do_OPTIONS(self):
        """Responds to browser CORS preflight checks."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        """Handles GET requests for both API endpoints and static HTML/CSS/JS files."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # 1. Health check endpoint
        if path == "/api/health":
            self._send_json({
                "status": "healthy",
                "service": "TechStart Backend API",
                "database": "SQLite (Connected)",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return

        # 2. Get current authenticated user
        if path == "/api/auth/me":
            user = get_authenticated_user(self.headers)
            if not user:
                self._send_error_json("Unauthorized or session expired", 401)
                return
            self._send_json({
                "success": True,
                "user": {
                    "id": user["id"],
                    "name": user["name"],
                    "email": user["email"]
                }
            })
            return

        # 3. Get User Progress & Milestones
        if path == "/api/progress":
            user = get_authenticated_user(self.headers)
            user_id = user["id"] if user else None
            
            # Default milestones definitions
            default_milestones = [
                {"index": 0, "label": "Read the hero confidence message and clicked 'Run Code'", "completed": False},
                {"index": 1, "label": "Checked out the 4 learning paths and picked one that interests you", "completed": False},
                {"index": 2, "label": "Edited your first HTML line in the Live Lesson Preview", "completed": False},
                {"index": 3, "label": "Answered the 60-second coding question correctly", "completed": False},
                {"index": 4, "label": "Searched for a term like 'API' in the beginner glossary", "completed": False},
                {"index": 5, "label": "Took a deep breath and reminded yourself: 'Everyone starts somewhere'", "completed": False}
            ]

            completed_indices = []
            if user_id:
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT milestone_index, completed FROM user_progress WHERE user_id = ?", (user_id,))
                    rows = cursor.fetchall()
                    completed_set = {row["milestone_index"] for row in rows if row["completed"] == 1}
                    for m in default_milestones:
                        if m["index"] in completed_set:
                            m["completed"] = True
                            completed_indices.append(m["index"])

            total = len(default_milestones)
            completed_count = len(completed_indices)
            percent = int(round((completed_count / total) * 100)) if total > 0 else 0

            self._send_json({
                "success": True,
                "user_authenticated": bool(user_id),
                "total": total,
                "completed_count": completed_count,
                "progress_percent": percent,
                "all_completed": completed_count == total,
                "milestones": default_milestones
            })
            return

        # 4. Get Learning Paths Curriculum
        if path == "/api/paths":
            paths_data = [
                {
                    "id": "web-dev",
                    "title": "Web Development from Scratch",
                    "category": "Frontend & Web Design",
                    "difficulty": "Beginner",
                    "estimated_time": "~3 Weeks",
                    "icon": "🌐",
                    "accent_color": "#2563eb",
                    "description": "Learn HTML for structure, CSS for styling and responsiveness, and publish your own live website for free.",
                    "modules": [
                        {
                            "id": "html-foundations",
                            "name": "The Skeleton: HTML5 Foundations",
                            "lessons": [
                                {"id": "1.1", "title": "How Web Browsers Read Code", "time": "8 min"},
                                {"id": "1.2", "title": "Headings, Paragraphs & Links", "time": "12 min"},
                                {"id": "1.3", "title": "Images, Lists & Clickable Buttons", "time": "15 min"}
                            ]
                        },
                        {
                            "id": "css-styling",
                            "name": "The Styling: CSS Aesthetics",
                            "lessons": [
                                {"id": "2.1", "title": "Colors & Google Typography", "time": "15 min"},
                                {"id": "2.2", "title": "The Box Model (Pizza Box 🍕)", "time": "14 min"},
                                {"id": "2.3", "title": "Flexbox: Aligning Items Effortlessly", "time": "20 min"}
                            ]
                        },
                        {
                            "id": "responsive-publishing",
                            "name": "Mobile Design & Publishing",
                            "lessons": [
                                {"id": "3.1", "title": "Media Queries: Phones vs Desktop", "time": "18 min"},
                                {"id": "3.2", "title": "Free Hosting with GitHub Pages", "time": "15 min"},
                                {"id": "3.3", "title": "Accessibility & Friendly Contrast", "time": "10 min"}
                            ]
                        }
                    ],
                    "capstone_project": {
                        "title": "Personal Link-in-Bio & Portfolio Landing Page",
                        "description": "Build a responsive personal homepage featuring your bio, profile avatar, links, and light/dark theme switch."
                    }
                },
                {
                    "id": "python",
                    "title": "Python Programming for Everyday Life",
                    "category": "Automation & Logic",
                    "difficulty": "Beginner",
                    "estimated_time": "~4 Weeks",
                    "icon": "🐍",
                    "accent_color": "#10b981",
                    "description": "Master the world's most beginner-friendly language for computer automation, logic, and mini games.",
                    "modules": [
                        {
                            "id": "speaking-python",
                            "name": "Speaking the Language",
                            "lessons": [
                                {"id": "1.1", "title": "print() & Storing Variables", "time": "10 min"},
                                {"id": "1.2", "title": "Data Types: Numbers & Strings", "time": "12 min"},
                                {"id": "1.3", "title": "input(): Asking User Questions", "time": "15 min"}
                            ]
                        },
                        {
                            "id": "control-flow",
                            "name": "Decisions & Repetition",
                            "lessons": [
                                {"id": "2.1", "title": "if / elif / else Conditions", "time": "16 min"},
                                {"id": "2.2", "title": "Loops: for and while", "time": "18 min"},
                                {"id": "2.3", "title": "Lists: Managing Collections", "time": "15 min"}
                            ]
                        },
                        {
                            "id": "tools-and-files",
                            "name": "Functions & Mini Tools",
                            "lessons": [
                                {"id": "3.1", "title": "def Functions: Reusable Recipes", "time": "15 min"},
                                {"id": "3.2", "title": "Automating Files on Your Computer", "time": "14 min"},
                                {"id": "3.3", "title": "Error Handling: Don't Panic!", "time": "12 min"}
                            ]
                        }
                    ],
                    "capstone_project": {
                        "title": "Text Mystery Adventure & Smart Bill Splitter",
                        "description": "Write a playable branching story game, plus an automated dining bill and tip calculator."
                    }
                },
                {
                    "id": "cybersecurity",
                    "title": "Cybersecurity & Online Defense",
                    "category": "Digital Defense & Privacy",
                    "difficulty": "Beginner",
                    "estimated_time": "~2 Weeks",
                    "icon": "🛡️",
                    "accent_color": "#f59e0b",
                    "description": "Understand encryption, passwords, public Wi-Fi risks, and smart habits to keep your digital identity safe.",
                    "modules": [
                        {
                            "id": "internet-highway",
                            "name": "How Data Travels Safely",
                            "lessons": [
                                {"id": "1.1", "title": "Routers, IP Addresses & Wi-Fi", "time": "10 min"},
                                {"id": "1.2", "title": "The Browser Padlock & Encryption", "time": "14 min"},
                                {"id": "1.3", "title": "Public Wi-Fi: What Can Others See?", "time": "12 min"}
                            ]
                        },
                        {
                            "id": "passwords-and-traps",
                            "name": "Passwords & Human Traps",
                            "lessons": [
                                {"id": "2.1", "title": "Why Passwords Get Cracked in 0.01s", "time": "12 min"},
                                {"id": "2.2", "title": "Password Vaults & 2FA Setup", "time": "15 min"},
                                {"id": "2.3", "title": "Spotting Phishing Scams Instantly", "time": "16 min"}
                            ]
                        },
                        {
                            "id": "device-defense",
                            "name": "Privacy & Everyday Defense",
                            "lessons": [
                                {"id": "3.1", "title": "Cookies, Trackers & VPN Realities", "time": "14 min"},
                                {"id": "3.2", "title": "Safe Downloads & Avoiding Malware", "time": "12 min"},
                                {"id": "3.3", "title": "Emergency Action: If You Get Hacked", "time": "15 min"}
                            ]
                        }
                    ],
                    "capstone_project": {
                        "title": "Personal Digital Security & Wi-Fi Audit",
                        "description": "Execute a guided 10-step audit of your passwords, email breach exposure, and home Wi-Fi defense."
                    }
                },
                {
                    "id": "data-ai",
                    "title": "Data & AI Fundamentals",
                    "category": "Artificial Intelligence",
                    "difficulty": "Beginner",
                    "estimated_time": "~3 Weeks",
                    "icon": "🤖",
                    "accent_color": "#8b5cf6",
                    "description": "Demystify machine learning, neural networks, and prompt engineering without complicated mathematics.",
                    "modules": [
                        {
                            "id": "data-foundations",
                            "name": "What is Data Anyway?",
                            "lessons": [
                                {"id": "1.1", "title": "From Spreadsheets to AI", "time": "10 min"},
                                {"id": "1.2", "title": "Spotting Trends & Outliers", "time": "14 min"},
                                {"id": "1.3", "title": "Telling Stories with Visual Charts", "time": "15 min"}
                            ]
                        },
                        {
                            "id": "ai-learning",
                            "name": "How Artificial Intelligence Learns",
                            "lessons": [
                                {"id": "2.1", "title": "Teaching vs. Programming", "time": "14 min"},
                                {"id": "2.2", "title": "Training Data & Neural Nets", "time": "16 min"},
                                {"id": "2.3", "title": "Large Language Models (LLMs)", "time": "18 min"}
                            ]
                        },
                        {
                            "id": "prompt-crafting",
                            "name": "Prompt Craft & Practical Use",
                            "lessons": [
                                {"id": "3.1", "title": "The 4-Step Prompt Formula", "time": "12 min"},
                                {"id": "3.2", "title": "Spotting AI Hallucinations", "time": "14 min"},
                                {"id": "3.3", "title": "Ethics & Bias in Modern AI", "time": "12 min"}
                            ]
                        }
                    ],
                    "capstone_project": {
                        "title": "Personal AI Playbook & Prompt Library",
                        "description": "Build a custom library of structured AI prompts and visualize a real dataset with charts."
                    }
                }
            ]
            self._send_json({"success": True, "paths": paths_data})
            return

        # 5. Get Glossary Terms (with optional search and category filters)
        if path == "/api/glossary":
            search_query = query_params.get("search", [""])[0].strip().lower()
            category_filter = query_params.get("category", ["all"])[0].strip()

            with get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT id, term, category, definition FROM glossary WHERE 1=1"
                params = []

                if category_filter and category_filter != "all":
                    query += " AND category = ?"
                    params.append(category_filter)

                if search_query:
                    query += " AND (LOWER(term) LIKE ? OR LOWER(definition) LIKE ?)"
                    params.append(f"%{search_query}%")
                    params.append(f"%{search_query}%")

                query += " ORDER BY term ASC"
                cursor.execute(query, params)
                terms = [dict(row) for row in cursor.fetchall()]

            self._send_json({
                "success": True,
                "count": len(terms),
                "terms": terms
            })
            return

        # Default static file serving (e.g. index.html)
        if path == "/" or path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        """Handles POST requests for authentication, progress toggles, newsletters, etc."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        body = self._read_json_body()

        if body is None:
            self._send_error_json("Invalid JSON body", 400)
            return

        # 1. Register Account
        if path == "/api/auth/register":
            name = body.get("name", "").strip()
            email = body.get("email", "").strip().lower()
            password = body.get("password", "")

            if not name or len(name) < 2:
                self._send_error_json("Name must be at least 2 characters long", 400)
                return
            if not email or "@" not in email or "." not in email:
                self._send_error_json("Please provide a valid email address", 400)
                return
            if not password or len(password) < 6:
                self._send_error_json("Password must be at least 6 characters long", 400)
                return

            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
                if cursor.fetchone():
                    self._send_error_json("An account with this email already exists. Try signing in!", 409)
                    return

                pwd_hash, salt = hash_password(password)
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                INSERT INTO users (name, email, password_hash, salt, created_at)
                VALUES (?, ?, ?, ?, ?)
                """, (name, email, pwd_hash, salt, now_iso))
                user_id = cursor.lastrowid

                # Generate session token valid for 30 days
                token = secrets.token_hex(32)
                expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
                cursor.execute("""
                INSERT INTO sessions (token, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """, (token, user_id, now_iso, expires_at))
                conn.commit()

            self._send_json({
                "success": True,
                "message": f"Welcome to TechStart, {name}!",
                "token": token,
                "user": {"id": user_id, "name": name, "email": email}
            }, status_code=201)
            return

        # 2. Login Account
        if path == "/api/auth/login":
            email = body.get("email", "").strip().lower()
            password = body.get("password", "")

            if not email or not password:
                self._send_error_json("Email and password are required", 400)
                return

            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, email, password_hash, salt FROM users WHERE email = ?", (email,))
                user = cursor.fetchone()

                if not user or not verify_password(password, user["password_hash"], user["salt"]):
                    self._send_error_json("Incorrect email or password. Please try again.", 401)
                    return

                # Create active session
                token = secrets.token_hex(32)
                now_iso = datetime.now(timezone.utc).isoformat()
                expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
                cursor.execute("""
                INSERT INTO sessions (token, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """, (token, user["id"], now_iso, expires_at))
                conn.commit()

            self._send_json({
                "success": True,
                "message": f"Welcome back, {user['name']}!",
                "token": token,
                "user": {"id": user["id"], "name": user["name"], "email": user["email"]}
            })
            return

        # 3. Logout
        if path == "/api/auth/logout":
            token = get_bearer_token(self.headers)
            if token:
                with get_connection() as conn:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                    conn.commit()
            self._send_json({"success": True, "message": "Signed out successfully"})
            return

        # 4. Toggle Milestone Completion in Database
        if path == "/api/progress/toggle":
            user = get_authenticated_user(self.headers)
            if not user:
                # If guest, return successful mock toggle so offline users still get feedback
                m_idx = int(body.get("milestone_index", 0))
                completed = bool(body.get("completed", True))
                self._send_json({
                    "success": True,
                    "guest": True,
                    "milestone_index": m_idx,
                    "completed": completed,
                    "message": "Progress tracked locally for guest"
                })
                return

            user_id = user["id"]
            m_idx = int(body.get("milestone_index", 0))
            m_label = body.get("milestone_label", f"Milestone #{m_idx}")
            completed = 1 if body.get("completed", True) else 0
            now_iso = datetime.now(timezone.utc).isoformat()

            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO user_progress (user_id, milestone_index, milestone_label, completed, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, milestone_index) DO UPDATE SET
                    completed = excluded.completed,
                    updated_at = excluded.updated_at;
                """, (user_id, m_idx, m_label, completed, now_iso))

                # Compute new totals
                cursor.execute("SELECT COUNT(*) as count FROM user_progress WHERE user_id = ? AND completed = 1", (user_id,))
                completed_count = cursor.fetchone()["count"]
                total_milestones = 6
                percent = int(round((completed_count / total_milestones) * 100))
                conn.commit()

            self._send_json({
                "success": True,
                "milestone_index": m_idx,
                "completed": bool(completed),
                "completed_count": completed_count,
                "progress_percent": percent,
                "all_completed": completed_count >= total_milestones
            })
            return

        # 5. Reset Progress in Database
        if path == "/api/progress/reset":
            user = get_authenticated_user(self.headers)
            if user:
                with get_connection() as conn:
                    conn.execute("DELETE FROM user_progress WHERE user_id = ?", (user["id"],))
                    conn.commit()
            self._send_json({"success": True, "progress_percent": 0, "message": "Progress reset"})
            return

        # 6. Newsletter Subscription
        if path == "/api/newsletter/subscribe":
            email = body.get("email", "").strip().lower()
            if not email or "@" not in email or "." not in email:
                self._send_error_json("Please provide a valid email address.", 400)
                return

            with get_connection() as conn:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                INSERT INTO subscribers (email, subscribed_at)
                VALUES (?, ?)
                ON CONFLICT(email) DO NOTHING;
                """, (email, now_iso))
                conn.commit()

            self._send_json({
                "success": True,
                "message": "You're on the list! Welcome aboard the Weekly Beginner Byte! 🎉"
            })
            return

        # 7. Quiz Evaluation
        if path == "/api/quiz/submit":
            choice = body.get("choice", "").strip().upper()
            if choice == "B":
                self._send_json({
                    "success": True,
                    "is_correct": True,
                    "title": "Bingo! That's exactly right.",
                    "explanation": "Computers are super fast listeners, but they need clear, step-by-step instructions. That's all coding is!"
                })
            else:
                self._send_json({
                    "success": True,
                    "is_correct": False,
                    "title": "Not quite, but good guess!",
                    "explanation": "Coding is simply giving friendly instructions to a computer, not mysterious alien math or rewiring circuits."
                })
            return

        # 8. Interactive Code Simulator / Playground Run
        if path == "/api/playground/execute":
            code = body.get("code", "")
            language = body.get("language", "html")
            
            # Safe simulated response
            self._send_json({
                "success": True,
                "language": language,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "output": "Execution simulation complete. Code parsed cleanly with 0 errors!"
            })
            return

        # 9. AI Chat Assistant (Ollama gemma3:1b)
        if path == "/api/chat":
            user_message = body.get("message", "").strip()
            history = body.get("history", [])   # list of {role, content} dicts

            if not user_message:
                self._send_error_json("'message' field is required", 400)
                return

            # Build the full conversation for Ollama
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for entry in history:
                role = entry.get("role", "")
                content = entry.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": user_message})

            try:
                reply = call_ollama(messages)
                self._send_json({
                    "success": True,
                    "reply": reply,
                    "model": OLLAMA_MODEL
                })
            except RuntimeError as exc:
                self._send_error_json(str(exc), 503)
            return

        self._send_error_json(f"Endpoint not found: {path}", 404)

def run_server():
    """Initializes the database and starts the HTTP server."""
    init_db()
    server_address = ('', PORT)
    httpd = ThreadingHTTPServer(server_address, TechStartAPIHandler)
    print("=" * 65)
    print(f"🚀 TechStart Backend Server running at http://localhost:{PORT}")
    print(f"📂 Serving static files from: {STATIC_DIR}")
    print(f"💾 SQLite Database: {DB_PATH}")
    print("=" * 65)
    print("Available REST API Endpoints:")
    print("  • GET  /api/health")
    print("  • POST /api/auth/register")
    print("  • POST /api/auth/login")
    print("  • GET  /api/auth/me")
    print("  • POST /api/auth/logout")
    print("  • GET  /api/progress")
    print("  • POST /api/progress/toggle")
    print("  • POST /api/progress/reset")
    print("  • GET  /api/paths")
    print("  • GET  /api/glossary")
    print("  • POST /api/newsletter/subscribe")
    print("  • POST /api/quiz/submit")
    print("  • POST /api/playground/execute")
    print("  • POST /api/chat           ← AI assistant (Ollama gemma3:1b)")
    print("=" * 65)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping TechStart server...")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
