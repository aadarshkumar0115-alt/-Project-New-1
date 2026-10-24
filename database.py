"""
Database configuration and SQLite schema setup for TechStart Backend.
Zero external dependencies required - runs on standard Python 3.
"""

import sqlite3
import os
import hashlib
import secrets
import hmac
from datetime import datetime, timezone, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "techstart.db")

def get_connection():
    """Returns a SQLite connection with row_factory set to Row dictionary-like objects."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Hashes a password using PBKDF2-HMAC-SHA256 with a unique cryptographic salt."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return hashed, salt

def verify_password(provided_password: str, stored_hash: str, salt: str) -> bool:
    """Verifies a password against the stored PBKDF2 hash using constant-time comparison."""
    hashed, _ = hash_password(provided_password, salt)
    return hmac.compare_digest(hashed, stored_hash)

def init_db():
    """Initializes tables and seeds initial data if not present."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        # 2. Sessions table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
        """)

        # 3. User Progress / Milestones table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            milestone_index INTEGER NOT NULL,
            milestone_label TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, milestone_index),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
        """)

        # 4. User Path Enrollments table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            path_id TEXT NOT NULL,
            enrolled_at TEXT NOT NULL,
            UNIQUE(user_id, path_id),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
        """)

        # 5. Glossary terms table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS glossary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT UNIQUE NOT NULL COLLATE NOCASE,
            category TEXT NOT NULL,
            definition TEXT NOT NULL
        );
        """)

        # 6. Newsletter Subscribers table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            subscribed_at TEXT NOT NULL
        );
        """)

        conn.commit()

        # Seed Demo User
        cursor.execute("SELECT id FROM users WHERE email = 'demo@techstart.dev'")
        demo_user = cursor.fetchone()
        if not demo_user:
            now_iso = datetime.now(timezone.utc).isoformat()
            demo_hash, demo_salt = hash_password("password123")
            cursor.execute("""
            INSERT INTO users (name, email, password_hash, salt, created_at)
            VALUES (?, ?, ?, ?, ?)
            """, ("Alex Learner", "demo@techstart.dev", demo_hash, demo_salt, now_iso))
            demo_id = cursor.lastrowid

            # Pre-seed sample milestone for demo user
            cursor.execute("""
            INSERT INTO user_progress (user_id, milestone_index, milestone_label, completed, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """, (demo_id, 0, "Read the hero confidence message", 1, now_iso))
            conn.commit()

        # Seed Glossary Terms (all 30 terms)
        cursor.execute("SELECT COUNT(*) as count FROM glossary")
        if cursor.fetchone()["count"] == 0:
            sample_glossary = [
                ("API", "Web", "Application Programming Interface. Think of it like a restaurant waiter: it takes your order from the app to the kitchen (server) and brings back your food (data)."),
                ("Browser", "Web", "The software you use to visit the internet (like Chrome, Safari, or Firefox). It reads behind-the-scenes code and translates it into pictures and clickable text."),
                ("Variable", "Basics", "A labeled storage box in computer memory that holds a piece of information, such as a player's score, an email address, or a user's name."),
                ("Server", "Systems", "A dedicated computer that stays powered on 24/7. When you visit a website, its server sends the web page files straight to your device."),
                ("Bug", "Basics", "A tiny mistake or typo in computer code that causes something unexpected to happen. Tracking down and fixing these mistakes is called 'debugging'."),
                ("Frontend", "Web", "The visual part of an app or website that humans interact with—the layout, buttons, colors, fonts, and animations."),
                ("Backend", "Systems", "The engine under the hood. It handles user passwords, database lookups, payment processing, and behind-the-scenes computations."),
                ("Database", "Systems", "A super-organized digital filing cabinet where an app securely stores information long term, like user accounts, photos, and messages."),
                ("Algorithm", "Basics", "A step-by-step recipe to solve a specific problem. If you follow steps to assemble furniture or bake chocolate chip cookies, you are following an algorithm!"),
                ("Cloud", "Systems", "Simply someone else's computer servers connected through the internet. Instead of keeping files on your phone, you access them remotely."),
                ("Responsive Design", "Web", "The art of designing a website so it automatically rearranges itself to look fantastic on small phones, tablets, and large computer monitors."),
                ("Framework", "Basics", "A pre-assembled toolkit of code created by other developers. It gives you a head start so you don't have to reinvent common wheels."),
                ("Git", "Basics", "A time machine for your code projects. It saves snapshots of your work so you can undo mistakes anytime and collaborate safely with teammates."),
                ("Open Source", "Basics", "Software whose original recipe (code) is made public for anyone in the world to inspect, use, learn from, and enhance for free."),
                ("IP Address", "Security", "A unique digital mailing address assigned to your device on a network so other computers know where to deliver web pages and messages."),
                ("Phishing", "Security", "A deceptive trick where scammers send fake emails pretending to be a bank or delivery service to steal private logins. Learning to spot them keeps you safe!"),
                ("HTML & CSS", "Web", "The foundation of every website. HTML builds the brick walls, text, and structure; CSS paints the colors, sets the fonts, and arranges the decor."),
                ("JavaScript", "Web", "The programming language that makes websites alive and interactive—handling popups, theme switches, live calculations, and button animations."),
                ("Machine Learning", "AI", "Teaching computers through examples rather than rigid rules. For instance, feeding an algorithm 5,000 photos of cats until it learns to identify cats on its own."),
                ("LLM", "AI", "Large Language Model. An advanced AI system trained on massive amounts of books, articles, and websites to understand human sentences and predict helpful answers."),
                ("Prompt", "AI", "The natural-language instructions, question, or scenario you give to an AI model (like ChatGPT or Claude) to guide the answer you want."),
                ("Encryption", "Security", "Scrambling readable information into secret gibberish that only someone with the digital key can decipher. It keeps banking and passwords secure."),
                ("2FA", "Security", "Two-Factor Authentication. A security deadbolt: even if someone guesses your password, they can't get in without a temporary code sent to your phone."),
                ("VPN", "Security", "Virtual Private Network. An encrypted digital tunnel between your device and the internet that conceals your real location and shields activity on public Wi-Fi."),
                ("Boolean", "Basics", "A data type with only two possibilities: True or False. Think of it like a light switch that can only ever be turned ON or OFF."),
                ("Loop", "Basics", "A programming instruction that repeats a task automatically until a goal is reached (e.g., emailing 500 customers without doing it one by one)."),
                ("Function", "Basics", "A named, reusable recipe of code. You pass in ingredients (inputs/parameters), the function runs its recipe, and it gives you back a finished dish (output)."),
                ("DNS", "Systems", "Domain Name System. The phonebook of the internet. It translates human names like google.com into numeric IP addresses like 142.250.190.46."),
                ("Cache", "Web", "Pronounced 'cash'. A temporary high-speed digital memory stash where your browser saves logos and images so websites open in a split second next time."),
                ("JSON", "Systems", "JavaScript Object Notation. A universal, human-readable format used by apps and servers to send information back and forth using neat key/value pairs.")
            ]
            cursor.executemany("INSERT INTO glossary (term, category, definition) VALUES (?, ?, ?)", sample_glossary)
            conn.commit()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", DB_PATH)
