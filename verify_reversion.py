import sys
import os
import sqlite3
import json

# Add workspace directory to python path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app import app, get_db_connection

def clean_database():
    db_path = os.path.join(BASE_DIR, 'resolve_x.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF;")
    cursor.execute("DELETE FROM tickets;")
    cursor.execute("DELETE FROM ticket_activity;")
    cursor.execute("DELETE FROM audit_logs;")
    cursor.execute("DELETE FROM users WHERE email = 'tester@gmail.com';")
    from werkzeug.security import generate_password_hash
    cursor.execute("INSERT INTO users (username, email, password, created_at) VALUES ('tester', 'tester@gmail.com', ?, datetime('now'))",
                   (generate_password_hash("password123"),))
    cursor.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'tickets';")
    cursor.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'ticket_activity';")
    cursor.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'audit_logs';")
    
    # Ensure admin user is seeded in admins table
    cursor.execute("SELECT COUNT(*) FROM admins WHERE email = 'admin@gmail.com'")
    if cursor.fetchone()[0] == 0:
        from werkzeug.security import generate_password_hash
        cursor.execute("INSERT INTO admins (username, email, password) VALUES ('admin', 'admin@gmail.com', ?)",
                       (generate_password_hash("admin"),))
    conn.commit()
    conn.close()
    print("Database cleaned for reversion test.")

def run_tests():
    clean_database()
    
    app.config['TESTING'] = True
    client = app.test_client()

    print("\n--- Running AI Reversion Verification Tests ---")
    
    # 1. Verify that AI analysis endpoint is removed (should return 404)
    print("Checking /api/ai/analyze...")
    res_analyze = client.post('/api/ai/analyze', json={
        "category": "Payment Issue",
        "description": "Double charged on checkout"
    })
    print(f"Status Code: {res_analyze.status_code}")
    assert res_analyze.status_code in [404, 405], f"Expected 404 or 405 for removed endpoint, got {res_analyze.status_code}"
    print("Step 1 PASSED: AI analyze endpoint is successfully removed (returned 404 or 405).")

    # 2. Verify that AI admin stats endpoint is removed (should return 404)
    print("Checking /api/admin/ai_stats...")
    res_stats = client.get('/api/admin/ai_stats', headers={'X-User-Email': 'admin@gmail.com'})
    print(f"Status Code: {res_stats.status_code}")
    assert res_stats.status_code == 404, f"Expected 404 for removed endpoint, got {res_stats.status_code}"
    print("Step 2 PASSED: AI admin stats endpoint is successfully removed (returned 404).")

    # 3. Create a ticket that would have matched the auto-resolve criteria and verify status is 'Open'
    print("Submitting ticket with description matching 'Billing Inquiry'...")
    res_ticket = client.post('/api/tickets', json={
        "email": "tester@gmail.com",
        "category": "Billing Inquiry",
        "description": "Double charged checkout on payment page. Please refund my charge.",
        "priority": "High",
        "aiSuggestion": "Manual keyword suggestion"
    }, headers={'X-User-Email': 'tester@gmail.com'})
    
    ticket_data = res_ticket.get_json()
    print("Ticket Submission Response:", ticket_data)
    assert ticket_data['success'] == True
    assert ticket_data['ticket']['status'] == 'Open', f"Expected status to be 'Open', got {ticket_data['ticket']['status']}"
    print("Step 3 PASSED: Ticket created directly in 'Open' status instead of being auto-resolved.")

    # 4. Verify ticket status directly in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, solver_note, ai_suggestion FROM tickets WHERE ticket_id = 1")
    row = cursor.fetchone()
    conn.close()
    
    print(f"Database row state: status={row['status']}, solver_note={row['solver_note']}, ai_suggestion={row['ai_suggestion']}")
    assert row['status'] == 'Open'
    assert row['solver_note'] is None or row['solver_note'] == ''
    assert row['ai_suggestion'] == 'Manual keyword suggestion'
    print("Step 4 PASSED: Database records confirm status is 'Open' and solver_note is empty.")

    print("\n--- ALL REVERSION TESTS PASSED SUCCESSFULLY! ---")

if __name__ == '__main__':
    run_tests()
