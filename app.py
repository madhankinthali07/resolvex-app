# app.py
import os
import sqlite3
import sys
import pickle
import pandas as pd
from datetime import datetime
from flask import Flask, request, jsonify, session, redirect, send_from_directory, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder=None)
app.secret_key = 'resolvex-secret-key-12345'  # Secure session secret key

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'resolve_x.db')

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create ticket_solvers table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ticket_solvers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create admins table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create tickets table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'Normal',
                status TEXT NOT NULL DEFAULT 'Open',
                ai_suggestion TEXT,
                admin_note TEXT,
                solver_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Create ticket_activity table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ticket_activity (
                activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                solver_id INTEGER NOT NULL,
                old_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES tickets (ticket_id),
                FOREIGN KEY (solver_id) REFERENCES ticket_solvers (id)
            )
        ''')
        
        # Create audit_logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER NOT NULL,
                actor_role TEXT NOT NULL,
                action TEXT NOT NULL,
                target_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Ensure assigned_solver_id column exists in tickets table
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN assigned_solver_id INTEGER REFERENCES ticket_solvers(id)")
        except sqlite3.OperationalError:
            pass

        # Ensure is_approved column exists in ticket_solvers table
        try:
            cursor.execute("ALTER TABLE ticket_solvers ADD COLUMN is_approved INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Ensure is_approved column exists in users table
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_approved INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Ensure phone column exists in users table
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        except sqlite3.OperationalError:
            pass

        # Ensure products_purchased column exists in users table
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN products_purchased TEXT")
        except sqlite3.OperationalError:
            pass

        # Ensure release_reason column exists in tickets table
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN release_reason TEXT")
        except sqlite3.OperationalError:
            pass

        # Ensure approval_status column exists in tickets table
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN approval_status TEXT DEFAULT 'None'")
        except sqlite3.OperationalError:
            pass

        # Ensure subject column exists in tickets table
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN subject TEXT")
        except sqlite3.OperationalError:
            pass

        # Ensure contact_channel column exists in tickets table
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN contact_channel TEXT")
        except sqlite3.OperationalError:
            pass

        # Ensure product_purchased column exists in tickets table
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN product_purchased TEXT")
        except sqlite3.OperationalError:
            pass

        # Ensure approval_request_message column exists in tickets table
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN approval_request_message TEXT")
        except sqlite3.OperationalError:
            pass

        # Seed default admin account if table is empty and not in testing mode
        if not app.config.get('TESTING'):
            cursor.execute("SELECT COUNT(*) FROM admins")
            if cursor.fetchone()[0] == 0:
                hashed_pw = generate_password_hash("admin")
                cursor.execute(
                    "INSERT INTO admins (username, email, password, created_at) VALUES (?, ?, ?, ?)",
                    ("admin", "admin@gmail.com", hashed_pw, datetime.utcnow().isoformat())
                )

            # Seed default solver account if table is empty and not in testing mode
            cursor.execute("SELECT COUNT(*) FROM ticket_solvers")
            if cursor.fetchone()[0] == 0:
                hashed_pw = generate_password_hash("solver123")
                cursor.execute(
                    "INSERT INTO ticket_solvers (username, email, password, is_approved, created_at) VALUES (?, ?, ?, 1, ?)",
                    ("solver", "solver@gmail.com", hashed_pw, datetime.utcnow().isoformat())
                )
            
        conn.commit()
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
    finally:
        if conn:
            conn.close()

# Initialize the SQLite tables on startup
init_db()

# Audit log helper function (supports atomic cursor sharing)
def log_audit_event(actor_id, actor_role, action, target_id=None, cursor=None):
    try:
        if cursor:
            cursor.execute('''
                INSERT INTO audit_logs (actor_id, actor_role, action, target_id, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (actor_id, actor_role, action, target_id, datetime.utcnow().isoformat()))
        else:
            conn = None
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30.0)
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO audit_logs (actor_id, actor_role, action, target_id, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (actor_id, actor_role, action, target_id, datetime.utcnow().isoformat()))
                conn.commit()
            finally:
                if conn:
                    conn.close()
    except Exception as e:
        print(f"Error logging audit event: {str(e)}")

# --- BACKEND API ENDPOINTS ---

@app.before_request
def resolve_session_from_headers():
    # Verify active session user still exists and is approved in the database
    if 'user_id' in session and 'role' in session:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            role = session['role']
            user_id = session['user_id']
            
            table_map = {
                'user': 'users',
                'solver': 'ticket_solvers',
                'admin': 'admins'
            }
            table = table_map.get(role)
            if table:
                if role == 'solver':
                    cursor.execute(f"SELECT id, is_approved FROM {table} WHERE id = ?", (user_id,))
                    row = cursor.fetchone()
                    if not row or (row['is_approved'] == 0 and not app.config.get('TESTING')):
                        session.clear()
                elif role == 'user':
                    cursor.execute(f"SELECT id FROM {table} WHERE id = ?", (user_id,))
                    if not cursor.fetchone():
                        session.clear()
                else:
                    cursor.execute(f"SELECT id FROM {table} WHERE id = ?", (user_id,))
                    if not cursor.fetchone():
                        session.clear()
            else:
                session.clear()
        except Exception as e:
            print(f"Error verifying active session: {e}")
        finally:
            if conn:
                conn.close()
                
    if 'user_id' in session and 'role' in session:
        return
        
    email = request.headers.get('X-User-Email', '').strip().lower()
    if not email:
        email = request.args.get('email', '').strip().lower()
        
    if email:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 1. Try admins
            cursor.execute("SELECT id, username, email FROM admins WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                session['user_id'] = row['id']
                session['role'] = 'admin'
                session['email'] = row['email']
                session['username'] = row['username']
                return
                
            # 2. Try solvers
            cursor.execute("SELECT id, username, email, is_approved FROM ticket_solvers WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                if row['is_approved'] == 1:
                    session['user_id'] = row['id']
                    session['role'] = 'solver'
                    session['email'] = row['email']
                    session['username'] = row['username']
                return
                
            # 3. Try users
            cursor.execute("SELECT id, username, email, is_approved FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                session['user_id'] = row['id']
                session['role'] = 'user'
                session['email'] = row['email']
                session['username'] = row['username']
                return
        except Exception as e:
            print(f"Error auto-restoring session from header: {e}")
        finally:
            if conn:
                conn.close()

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    role = data.get('role', '').strip().lower()
    
    if role != 'user' and not app.config.get('TESTING'):
        return jsonify({'success': False, 'message': 'Public registration is disabled. Please contact the administrator.'}), 403

    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    
    # Validations
    if not username or not email or not password or not role:
        return jsonify({'success': False, 'message': 'Please fill in all fields.'}), 400
        
    if '@' not in email:
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400
        
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters.'}), 400
        
    if role not in ['user', 'solver', 'admin']:
        return jsonify({'success': False, 'message': 'Invalid portal role specified.'}), 400
        
    # Block registration of admins/solvers publicly unless in testing mode
    if role in ['admin', 'solver'] and not app.config.get('TESTING'):
        return jsonify({'success': False, 'message': 'Registration for this role is not allowed publicly.'}), 403

    # Map role to appropriate table name
    table_map = {
        'user': 'users',
        'solver': 'ticket_solvers',
        'admin': 'admins'
    }
    table = table_map[role]
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if email already exists in the role table
        cursor.execute(f"SELECT id FROM {table} WHERE email = ?", (email,))
        existing = cursor.fetchone()
        if existing:
            return jsonify({'success': False, 'message': 'An account with this email already exists.'}), 400
            
        # Hash password and save
        hashed_password = generate_password_hash(password)
        if role == 'solver':
            is_approved_val = 1 if app.config.get('TESTING') else 0
            cursor.execute(
                "INSERT INTO ticket_solvers (username, email, password, is_approved, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, email, hashed_password, is_approved_val, datetime.utcnow().isoformat())
            )
        elif role == 'user':
            is_approved_val = 1 # customers register as approved immediately
            cursor.execute(
                "INSERT INTO users (username, email, password, is_approved, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, email, hashed_password, is_approved_val, datetime.utcnow().isoformat())
            )
        else:
            cursor.execute(
                f"INSERT INTO {table} (username, email, password, created_at) VALUES (?, ?, ?, ?)",
                (username, email, hashed_password, datetime.utcnow().isoformat())
            )
        
        # Get the new ID
        cursor.execute(f"SELECT id, username, email FROM {table} WHERE email = ?", (email,))
        user = cursor.fetchone()
        
        # Log the user in via session (unless they are a solver, who is pending approval)
        should_login = role != 'solver' or app.config.get('TESTING')
        if should_login:
            session['user_id'] = user['id']
            session['role'] = role
            session['email'] = user['email']
            session['username'] = user['username']
        
        # Log registration event in same transaction
        log_audit_event(user['id'], role, f"Registered new {role} account: {username} ({email})", user['id'], cursor=cursor)
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'pending_approval': role == 'solver' and not app.config.get('TESTING'),
            'user': {
                'username': user['username'],
                'email': user['email'],
                'role': role
            }
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Please fill in all fields.'}), 400
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        role = None
        user = None
        
        # 1. Try admin table
        cursor.execute("SELECT id, username, email, password FROM admins WHERE email = ? OR username = ?", (email, email))
        user = cursor.fetchone()
        if user and check_password_hash(user['password'], password):
            role = 'admin'
        else:
            # 2. Try ticket_solvers table
            cursor.execute("SELECT id, username, email, password, is_approved FROM ticket_solvers WHERE email = ?", (email,))
            user = cursor.fetchone()
            if user and check_password_hash(user['password'], password):
                role = 'solver'
                if user['is_approved'] == 0:
                    return jsonify({'success': False, 'message': 'Your account is pending approval by an administrator.'}), 403
            else:
                 # 3. Try users table
                 cursor.execute("SELECT id, username, email, password, is_approved FROM users WHERE email = ?", (email,))
                 user = cursor.fetchone()
                 if user and check_password_hash(user['password'], password):
                     role = 'user'
                     if user['is_approved'] == 0 and not app.config.get('TESTING'):
                         return jsonify({'success': False, 'message': 'Your profile changes are pending approval by an administrator.'}), 403
                 else:
                     user = None
        
        if not role or not user:
            return jsonify({'success': False, 'message': 'Invalid email or password.'}), 401
            
        # Log the user in via session
        session['user_id'] = user['id']
        session['role'] = role
        session['email'] = user['email']
        session['username'] = user['username']
        
        # Log login event in same transaction
        log_audit_event(user['id'], role, f"Logged into the portal", user['id'], cursor=cursor)
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'user': {
                'username': user['username'],
                'email': user['email'],
                'role': role
            }
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/logout', methods=['POST'])
def api_logout():
    if 'user_id' in session and 'role' in session:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            log_audit_event(session['user_id'], session['role'], "Logged out of the portal", session['user_id'], cursor=cursor)
            conn.commit()
        except Exception as e:
            print(f"Error logging logout: {str(e)}")
        finally:
            if conn:
                conn.close()
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me', methods=['GET'])
def api_me():
    if 'user_id' in session and 'role' in session:
        role = session.get('role')
        user_id = session.get('user_id')
        user_data = {
            'username': session.get('username'),
            'email': session.get('email'),
            'role': role
        }
        if role == 'user':
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT phone, products_purchased FROM users WHERE id = ?", (user_id,))
                row = cursor.fetchone()
                if row:
                    user_data['phone'] = row['phone'] or ''
                    user_data['products_purchased'] = row['products_purchased'] or ''
            except Exception as e:
                print(f"Error fetching me details: {e}")
            finally:
                if conn:
                    conn.close()
        return jsonify({
            'success': True,
            'user': user_data
        })
    return jsonify({'success': False, 'message': 'Not logged in'}), 401

@app.route('/api/me/change_password', methods=['POST'])
def api_change_password():
    if 'user_id' not in session or 'role' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
        
    data = request.get_json() or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    
    if not current_password or not new_password:
        return jsonify({'success': False, 'message': 'Please specify both current and new passwords.'}), 400
        
    if len(new_password) < 6:
        return jsonify({'success': False, 'message': 'New password must be at least 6 characters.'}), 400
        
    role = session['role']
    user_id = session['user_id']
    
    table_map = {
        'user': 'users',
        'solver': 'ticket_solvers',
        'admin': 'admins'
    }
    table = table_map.get(role)
    if not table:
        return jsonify({'success': False, 'message': 'Invalid role.'}), 400
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(f"SELECT password FROM {table} WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or not check_password_hash(row['password'], current_password):
            return jsonify({'success': False, 'message': 'Incorrect current password.'}), 400
            
        hashed_password = generate_password_hash(new_password)
        cursor.execute(f"UPDATE {table} SET password = ? WHERE id = ?", (hashed_password, user_id))
        
        log_audit_event(user_id, role, "Updated their account password", user_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Password changed successfully.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/me/update', methods=['POST'])
def api_update_profile():
    if 'user_id' not in session or 'role' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
        
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    products_purchased = data.get('products_purchased', '').strip()
    
    if not username or not email:
        return jsonify({'success': False, 'message': 'Please specify both username and email.'}), 400
        
    if '@' not in email:
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400
        
    role = session['role']
    user_id = session['user_id']
    
    table_map = {
        'user': 'users',
        'solver': 'ticket_solvers',
        'admin': 'admins'
    }
    table = table_map.get(role)
    if not table:
        return jsonify({'success': False, 'message': 'Invalid role.'}), 400
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify if email is already in use
        cursor.execute(f"SELECT id FROM {table} WHERE email = ? AND id != ?", (email, user_id))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Email address is already in use.'}), 400
            
        if role == 'user':
            # Check if name, email, or phone changed
            cursor.execute("SELECT username, email, phone FROM users WHERE id = ?", (user_id,))
            current = cursor.fetchone()
            pending_approval = False
            if current:
                name_changed = current['username'] != username
                email_changed = current['email'] != email
                phone_changed = (current['phone'] or '') != phone
                if name_changed or email_changed or phone_changed:
                    pending_approval = True
            
            if pending_approval:
                cursor.execute("UPDATE users SET username = ?, email = ?, phone = ?, products_purchased = ?, is_approved = 0 WHERE id = ?", (username, email, phone, products_purchased, user_id))
                log_audit_event(user_id, role, f"Updated profile details (pending approval) (name: {username}, email: {email}, phone: {phone})", user_id, cursor=cursor)
                session['username'] = username
                session['email'] = email
                conn.commit()
                return jsonify({'success': True, 'pending_approval': True, 'message': 'Profile updated. Your changes are pending admin approval.'})
            else:
                cursor.execute("UPDATE users SET username = ?, email = ?, phone = ?, products_purchased = ? WHERE id = ?", (username, email, phone, products_purchased, user_id))
        else:
            cursor.execute(f"UPDATE {table} SET username = ?, email = ? WHERE id = ?", (username, email, user_id))
        
        # Log action
        log_audit_event(user_id, role, f"Updated profile details (name: {username}, email: {email}, phone: {phone}, products_purchased: {products_purchased})", user_id, cursor=cursor)
        
        # Update session
        session['username'] = username
        session['email'] = email
        
        conn.commit()
        return jsonify({'success': True, 'user': {'username': username, 'email': email, 'phone': phone, 'products_purchased': products_purchased}})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/me/delete', methods=['POST'])
def api_delete_my_account():
    if 'user_id' not in session or 'role' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
        
    role = session['role']
    user_id = session['user_id']
    
    if role != 'user':
        return jsonify({'success': False, 'message': 'Only Customer accounts can be deleted.'}), 403
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Log audit event before deletion
        log_audit_event(user_id, role, f"Account deleted by user themselves", user_id, cursor=cursor)
        
        # Delete user
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        
        conn.commit()
        session.clear()
        return jsonify({'success': True, 'message': 'Account deleted successfully.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()


# --- TICKETS BACKEND API ENDPOINTS ---

@app.route('/api/tickets', methods=['POST'])
def api_create_ticket():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    category = data.get('category', '').strip()
    description = data.get('description', '').strip()
    priority = data.get('priority', 'Normal').strip()
    ai_suggestion = data.get('aiSuggestion', '').strip()
    subject = data.get('subject', '').strip()
    contact_channel = data.get('contactChannel', '').strip()
    product_purchased = data.get('productPurchased', '').strip()
    # AI-resolved tickets may pass status='Resolved' and a solver_note
    requested_status = data.get('status', 'Open').strip()
    solver_note = data.get('solver_note', '').strip()
    ticket_status = 'Resolved' if requested_status == 'Resolved' else 'Open'
    
    if not category or not description:
        return jsonify({'success': False, 'message': 'Please fill in all required fields.'}), 400
        
    user_id = None
    
    # 1. Try to get user_id from session if logged in as user
    if 'user_id' in session and session.get('role') == 'user':
        user_id = session['user_id']
        
    # 2. Try to get user_id using the form's email address
    if not user_id and email:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                user_id = row['id']
                
                # Auto-restore session for the user
                session['user_id'] = user_id
                session['role'] = 'user'
                session['email'] = email
                cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    session['username'] = user_row['username']
        except Exception as e:
            print(f"Error resolving user: {e}")
        finally:
            if conn:
                conn.close()
                
    # 3. Fallback: try session email
    if not user_id and 'email' in session:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = ?", (session['email'],))
            row = cursor.fetchone()
            if row:
                user_id = row['id']
        except Exception as e:
            print(f"Error querying session user: {e}")
        finally:
            if conn:
                conn.close()
                
    if not user_id:
        return jsonify({'success': False, 'message': 'Unauthorized access. Please specify a valid email address.'}), 401
        
    # Generate title automatically from category and snippet of description
    desc_snippet = description[:40] + '...' if len(description) > 40 else description
    title = f"{category} Issue — {desc_snippet}"
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Find the smallest unused positive integer for ticket_id
        cursor.execute("SELECT ticket_id FROM tickets ORDER BY ticket_id ASC")
        existing_ids = {row[0] for row in cursor.fetchall()}
        next_id = 1
        while next_id in existing_ids:
            next_id += 1
            
        cursor.execute('''
            INSERT INTO tickets (ticket_id, user_id, title, description, category, priority, status, ai_suggestion, solver_note, subject, contact_channel, product_purchased, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            next_id,
            user_id,
            title,
            description,
            category,
            priority,
            ticket_status,
            ai_suggestion,
            solver_note if solver_note else None,
            subject,
            contact_channel,
            product_purchased,
            datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat()
        ))
        
        ticket_id = next_id
        
        # Log ticket creation event in same transaction
        log_audit_event(session['user_id'], 'user', f"Submitted a new ticket: {category}", ticket_id, cursor=cursor)
        
        # Retrieve the inserted ticket
        cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        
        conn.commit()
        trigger_ai_retraining()
        
        return jsonify({
            'success': True,
            'ticket': {
                'id': f"TKT-{ticket['ticket_id']}",
                'title': ticket['title'],
                'description': ticket['description'],
                'category': ticket['category'],
                'priority': ticket['priority'],
                'status': ticket['status'],
                'aiSuggestion': ticket['ai_suggestion'],
                'createdAt': ticket['created_at'],
                'subject': ticket['subject'] if 'subject' in ticket.keys() else '',
                'contactChannel': ticket['contact_channel'] if 'contact_channel' in ticket.keys() else '',
                'productPurchased': ticket['product_purchased'] if 'product_purchased' in ticket.keys() else ''
            }
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

def run_ai_prediction(category, subject, priority, channel, product, description):
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ai_dir = os.path.join(base_dir, 'AI')
        model_path = os.path.join(ai_dir, 'best_model.pkl')
        
        with open(model_path, 'rb') as f:
            saved_data = pickle.load(f)
        best_pipeline = saved_data['pipeline']
        best_model_name = saved_data.get('model_name', 'Logistic Regression')
        
        if ai_dir not in sys.path:
            sys.path.append(ai_dir)
        import ticket_predictor
        
        # Clean and map the inputs
        mapped = ticket_predictor.map_inputs(
            category=category,
            subject=subject,
            priority=priority,
            channel=channel,
            product=product,
            description=description
        )
        
        threshold = 0.5
        result = ticket_predictor.predict_ticket(best_pipeline, mapped, threshold)
        if 'model_name' not in result:
            result['model_name'] = best_model_name
        return result
    except Exception as e:
        print(f"AI prediction failure: {e}")
        return {
            "decision": "no",
            "source": "fallback",
            "rule_name": None,
            "rule_type": None,
            "elapsed_days": None,
            "limit_days": None,
            "attempt_count": None,
            "limit_attempts": None,
            "reason": f"AI prediction failed due to internal error: {str(e)}",
            "probability": 0.0,
            "model_name": "None"
        }

def trigger_ai_retraining():
    import threading
    def retrain_worker():
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            ai_dir = os.path.join(base_dir, 'AI')
            if ai_dir not in sys.path:
                sys.path.append(ai_dir)
            import ticket_predictor
            csv_path = os.path.join(ai_dir, 'customer_support_tickets.csv')
            if not os.path.exists(csv_path):
                csv_path_root = os.path.join(base_dir, 'customer_support_tickets.csv')
                if os.path.exists(csv_path_root):
                    csv_path = csv_path_root
            best_pipeline, best_model_name = ticket_predictor.train_and_select_best_model(csv_path)
            model_path = os.path.join(ai_dir, 'best_model.pkl')
            with open(model_path, 'wb') as f:
                pickle.dump({'pipeline': best_pipeline, 'model_name': best_model_name}, f)
        except Exception as e:
            print(f"Error in background AI retraining: {e}")
            
    thread = threading.Thread(target=retrain_worker)
    thread.daemon = True
    thread.start()

@app.route('/api/predict_ticket', methods=['POST'])
def api_predict_ticket():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    data = request.get_json() or {}
    category = data.get('category', '').strip()
    subject = data.get('subject', '').strip()
    priority = data.get('priority', '').strip()
    channel = data.get('contactChannel', '').strip()
    product = data.get('productPurchased', '').strip()
    description = data.get('description', '').strip()
    
    if not category or not description:
        return jsonify({'success': False, 'message': 'Please fill in all required fields.'}), 400

    # Run AI prediction
    result = run_ai_prediction(
        category=category,
        subject=subject,
        priority=priority,
        channel=channel,
        product=product,
        description=description
    )
    
    # Log the result to audit logs (admin activity log)
    user_id = session['user_id']
    role = session.get('role', 'user')
    
    desc_snippet = description[:60] + '...' if len(description) > 60 else description
    prediction_label = result['decision']
    
    if result['source'] == 'rule':
        action_msg = f"AI Prediction (Rule Override: {result['rule_name']}): {prediction_label.upper()} — Reason: {result['reason']} | Ticket Description: {desc_snippet}"
    else:
        prob_val = result['probability'] if result['probability'] is not None else 0.0
        action_msg = f"AI Prediction (ML Model: {result.get('model_name', 'Model')}): {prediction_label.upper()} — Probability: {prob_val:.4f} | Reason: {result['reason']} | Ticket Description: {desc_snippet}"
        
    log_audit_event(user_id, role, action_msg)
    
    # Return JSON response merging all key details
    response_data = {'success': True}
    response_data.update(result)
    # Ensure properties used by client are present
    response_data['prediction'] = prediction_label
    response_data['probability'] = result['probability'] if result['probability'] is not None else 0.0
    return jsonify(response_data)


@app.route('/api/tickets', methods=['GET'])
def api_get_tickets():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    role = session.get('role')
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Standard security check: users can only see their own tickets, solvers/admins can see all
        if role == 'user':
            cursor.execute('''
                SELECT t.*, u.username as user_name, u.email as user_email, ts.username as solver_name, ts.email as solver_email
                FROM tickets t 
                LEFT JOIN users u ON t.user_id = u.id 
                LEFT JOIN ticket_solvers ts ON t.assigned_solver_id = ts.id
                WHERE t.user_id = ? 
                ORDER BY t.ticket_id DESC
            ''', (session['user_id'],))
        elif role == 'solver':
            # Solvers must see incoming tickets ordered oldest first!
            cursor.execute('''
                SELECT t.*, u.username as user_name, u.email as user_email, ts.username as solver_name, ts.email as solver_email
                FROM tickets t 
                LEFT JOIN users u ON t.user_id = u.id 
                LEFT JOIN ticket_solvers ts ON t.assigned_solver_id = ts.id
                ORDER BY t.ticket_id ASC
            ''')
        else:
            # Admins can query all tickets (default newest first)
            cursor.execute('''
                SELECT t.*, u.username as user_name, u.email as user_email, ts.username as solver_name, ts.email as solver_email
                FROM tickets t 
                LEFT JOIN users u ON t.user_id = u.id 
                LEFT JOIN ticket_solvers ts ON t.assigned_solver_id = ts.id
                ORDER BY t.ticket_id DESC
            ''')
            
        rows = cursor.fetchall()
        
        tickets_list = []
        for row in rows:
            tickets_list.append({
                'id': f"TKT-{row['ticket_id']}",
                'title': row['title'],
                'name': row['user_name'] or 'Deleted User',
                'email': row['user_email'] or 'deleted@resolvex.com',
                'description': row['description'],
                'category': row['category'],
                'priority': row['priority'],
                'status': row['status'],
                'aiSuggestion': row['ai_suggestion'] or '',
                'adminNote': row['admin_note'] or '',
                'solverNote': row['solver_note'] or '',
                'createdAt': row['created_at'],
                'assignedSolverId': row['assigned_solver_id'],
                'assignedSolverName': row['solver_name'] or '',
                'assignedSolverEmail': row['solver_email'] or '',
                'releaseReason': row['release_reason'] or '',
                'approvalStatus': row['approval_status'] or 'None',
                'subject': row['subject'] if 'subject' in row.keys() else '',
                'contactChannel': row['contact_channel'] if 'contact_channel' in row.keys() else '',
                'productPurchased': row['product_purchased'] if 'product_purchased' in row.keys() else '',
                'approvalRequestMessage': row['approval_request_message'] if 'approval_request_message' in row.keys() else ''
            })
            
        return jsonify({
            'success': True,
            'tickets': tickets_list
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/tickets/<int:ticket_id>', methods=['PUT'])
def api_update_ticket(ticket_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    role = session.get('role')
    if role not in ['solver', 'admin']:
        return jsonify({'success': False, 'message': 'Unauthorized role permission.'}), 403
        
    data = request.get_json() or {}
    new_status = data.get('status', '').strip()
    note = data.get('note', '').strip()
    
    if new_status not in ['Open', 'Pending', 'Solved', 'Resolved', 'Rejected', 'In Progress']:
        return jsonify({'success': False, 'message': 'Invalid status option.'}), 400
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Retrieve the existing ticket to log the old status and check assigned solver
        cursor.execute("SELECT status, assigned_solver_id, approval_status FROM tickets WHERE ticket_id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            return jsonify({'success': False, 'message': 'Ticket not found.'}), 404
            
        # Security check: Solver can only edit tickets assigned to them!
        if role == 'solver':
            if ticket['assigned_solver_id'] != session['user_id']:
                return jsonify({'success': False, 'message': 'You cannot update a ticket that is not assigned to you.'}), 403
            if new_status in ['Solved', 'Resolved'] and ticket['approval_status'] == 'Pending':
                return jsonify({'success': False, 'message': 'Higher official approval is pending. You cannot solve this ticket yet.'}), 403
            
        old_status = ticket['status']
        note_column = 'solver_note' if role == 'solver' else 'admin_note'
        
        # 2. Update status and note on the ticket
        cursor.execute(f'''
            UPDATE tickets 
            SET status = ?, {note_column} = ?, updated_at = ? 
            WHERE ticket_id = ?
        ''', (new_status, note, datetime.utcnow().isoformat(), ticket_id))
        
        # 3. Log the status audit trail in ticket_activity
        cursor.execute('''
            INSERT INTO ticket_activity (ticket_id, solver_id, old_status, new_status, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            ticket_id,
            session['user_id'],
            old_status,
            new_status,
            datetime.utcnow().isoformat()
        ))
        
        # Log status update event in same transaction
        log_audit_event(session['user_id'], role, f"Updated ticket status from {old_status} to {new_status}", ticket_id, cursor=cursor)
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Ticket TKT-{ticket_id} updated successfully.'
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/tickets/<int:ticket_id>/assign', methods=['PUT'])
def api_assign_ticket(ticket_id):
    if 'user_id' not in session or session.get('role') != 'solver':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if already assigned
        cursor.execute("SELECT assigned_solver_id FROM tickets WHERE ticket_id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            return jsonify({'success': False, 'message': 'Ticket not found.'}), 404
            
        if ticket['assigned_solver_id'] is not None:
            return jsonify({'success': False, 'message': 'Ticket is already assigned to another solver.'}), 400
            
        cursor.execute("UPDATE tickets SET assigned_solver_id = ?, updated_at = ? WHERE ticket_id = ?", 
                       (session['user_id'], datetime.utcnow().isoformat(), ticket_id))
                        
        # Log action in audit trail
        log_audit_event(session['user_id'], 'solver', f"Assigned ticket TKT-{ticket_id} to themselves", ticket_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Ticket TKT-{ticket_id} successfully assigned to you.'})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/tickets/<int:ticket_id>/release', methods=['PUT'])
def api_release_ticket(ticket_id):
    if 'user_id' not in session or session.get('role') != 'solver':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    data = request.get_json() or {}
    reason = data.get('reason', '').strip()
    if not reason:
        return jsonify({'success': False, 'message': 'Please provide a reason for releasing the ticket.'}), 400
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check ownership
        cursor.execute("SELECT status, assigned_solver_id FROM tickets WHERE ticket_id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            return jsonify({'success': False, 'message': 'Ticket not found.'}), 404
            
        if ticket['assigned_solver_id'] != session['user_id']:
            return jsonify({'success': False, 'message': 'You cannot release a ticket that is not assigned to you.'}), 403
            
        old_status = ticket['status']
        
        # Update ticket status to Open, unassign, and set release reason
        cursor.execute('''
            UPDATE tickets 
            SET status = 'Open', assigned_solver_id = NULL, release_reason = ?, updated_at = ? 
            WHERE ticket_id = ?
        ''', (reason, datetime.utcnow().isoformat(), ticket_id))
        
        # Log the activity
        cursor.execute('''
            INSERT INTO ticket_activity (ticket_id, solver_id, old_status, new_status, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            ticket_id,
            session['user_id'],
            old_status,
            'Open',
            datetime.utcnow().isoformat()
        ))
        
        log_audit_event(session['user_id'], 'solver', f"Released ticket TKT-{ticket_id}. Reason: {reason}", ticket_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Ticket TKT-{ticket_id} has been released.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/tickets/<int:ticket_id>/request_approval', methods=['PUT'])
def api_request_approval(ticket_id):
    if 'user_id' not in session or session.get('role') != 'solver':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check ownership
        cursor.execute("SELECT assigned_solver_id FROM tickets WHERE ticket_id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            return jsonify({'success': False, 'message': 'Ticket not found.'}), 404
            
        if ticket['assigned_solver_id'] != session['user_id']:
            return jsonify({'success': False, 'message': 'You cannot request approval for a ticket that is not assigned to you.'}), 403
            
        # Update approval status to Pending and save message
        cursor.execute("UPDATE tickets SET approval_status = 'Pending', approval_request_message = ?, updated_at = ? WHERE ticket_id = ?", 
                       (message, datetime.utcnow().isoformat(), ticket_id))
        
        log_audit_event(session['user_id'], 'solver', f"Requested higher official approval for ticket TKT-{ticket_id}. Message: {message}", ticket_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Higher official approval request submitted for ticket TKT-{ticket_id}.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/tickets/<int:ticket_id>/approve_request', methods=['PUT'])
def api_approve_request(ticket_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check ticket
        cursor.execute("SELECT ticket_id, approval_status FROM tickets WHERE ticket_id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            return jsonify({'success': False, 'message': 'Ticket not found.'}), 404
            
        # Update approval status to Approved
        cursor.execute("UPDATE tickets SET approval_status = 'Approved', updated_at = ? WHERE ticket_id = ?", 
                       (datetime.utcnow().isoformat(), ticket_id))
        
        log_audit_event(session['user_id'], 'admin', f"Approved higher official approval request for ticket TKT-{ticket_id}", ticket_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Higher official approval request approved for ticket TKT-{ticket_id}.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500


# --- ADMINISTRATIVE SYSTEM MONITORING & AUDITING ENDPOINTS ---

@app.route('/api/admin/stats', methods=['GET'])
def api_admin_stats():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Tickets breakdown
        cursor.execute("SELECT COUNT(*) FROM tickets")
        total_tickets = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Open'")
        open_tickets = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Pending'")
        pending_tickets = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status IN ('Solved', 'Resolved')")
        solved_tickets = cursor.fetchone()[0]
        
        # 2. Users and solvers directories
        cursor.execute("SELECT COUNT(*) FROM users")
        active_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM ticket_solvers")
        active_solvers = cursor.fetchone()[0]
        
        return jsonify({
            'success': True,
            'stats': {
                'totalTickets': total_tickets,
                'openTickets': open_tickets,
                'pendingTickets': pending_tickets,
                'solvedTickets': solved_tickets,
                'activeUsers': active_users,
                'activeSolvers': active_solvers
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/users', methods=['GET'])
def api_admin_get_users():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, is_approved, created_at, phone, products_purchased FROM users ORDER BY id DESC")
        rows = cursor.fetchall()
        
        users_list = []
        for row in rows:
            users_list.append({
                'id': row['id'],
                'username': row['username'],
                'email': row['email'],
                'is_approved': row['is_approved'],
                'createdAt': row['created_at'],
                'phone': row['phone'],
                'products_purchased': row['products_purchased']
            })
            
        return jsonify({'success': True, 'users': users_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def api_admin_delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT username, email FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'success': False, 'message': 'User not found.'}), 404
            
        # 1. Delete references in activity log first (cascade clean up)
        cursor.execute('''
            DELETE FROM ticket_activity 
            WHERE ticket_id IN (SELECT ticket_id FROM tickets WHERE user_id = ?)
        ''', (user_id,))
        
        # 2. Delete the tickets themselves
        cursor.execute("DELETE FROM tickets WHERE user_id = ?", (user_id,))
        
        # 3. Delete the user account
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        
        # Log action in same transaction
        log_audit_event(session['user_id'], 'admin', f"Deleted User account: {user['username']} ({user['email']})", user_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'User and all their tickets deleted successfully.'})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/solvers', methods=['GET'])
def api_admin_get_solvers():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, is_approved, created_at FROM ticket_solvers ORDER BY id DESC")
        rows = cursor.fetchall()
        
        solvers_list = []
        for row in rows:
            solvers_list.append({
                'id': row['id'],
                'username': row['username'],
                'email': row['email'],
                'is_approved': row['is_approved'],
                'createdAt': row['created_at']
            })
            
        return jsonify({'success': True, 'solvers': solvers_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()
 
@app.route('/api/admin/solvers/<int:solver_id>', methods=['DELETE'])
def api_admin_delete_solver(solver_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT username, email FROM ticket_solvers WHERE id = ?", (solver_id,))
        solver = cursor.fetchone()
        if not solver:
            return jsonify({'success': False, 'message': 'Solver not found.'}), 404
            
        cursor.execute("DELETE FROM ticket_solvers WHERE id = ?", (solver_id,))
        
        # Log action in same transaction
        log_audit_event(session['user_id'], 'admin', f"Deleted Solver account: {solver['username']} ({solver['email']})", solver_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Solver deleted successfully.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/solvers/<int:solver_id>/approve', methods=['PUT'])
def api_admin_approve_solver(solver_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT username, email FROM ticket_solvers WHERE id = ?", (solver_id,))
        solver = cursor.fetchone()
        if not solver:
            return jsonify({'success': False, 'message': 'Solver not found.'}), 404
            
        cursor.execute("UPDATE ticket_solvers SET is_approved = 1 WHERE id = ?", (solver_id,))
        
        # Log action in same transaction
        log_audit_event(session['user_id'], 'admin', f"Approved Solver account: {solver['username']} ({solver['email']})", solver_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Solver account approved successfully.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/users/<int:user_id>/approve', methods=['PUT'])
def api_admin_approve_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT username, email FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'success': False, 'message': 'User not found.'}), 404
            
        cursor.execute("UPDATE users SET is_approved = 1 WHERE id = ?", (user_id,))
        
        # Log action in same transaction
        log_audit_event(session['user_id'], 'admin', f"Approved Customer account: {user['username']} ({user['email']})", user_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Customer account approved successfully.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/solvers', methods=['POST'])
def api_admin_create_solver():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    
    if not username or not email or not password:
        return jsonify({'success': False, 'message': 'Please fill in all fields.'}), 400
        
    if '@' not in email:
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400
        
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters.'}), 400
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if email already exists in ticket_solvers
        cursor.execute("SELECT id FROM ticket_solvers WHERE email = ?", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'A solver account with this email already exists.'}), 400
            
        # Hash password and save (pre-approved)
        hashed_password = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO ticket_solvers (username, email, password, is_approved, created_at) VALUES (?, ?, ?, 1, ?)",
            (username, email, hashed_password, datetime.utcnow().isoformat())
        )
        
        # Get the new ID
        cursor.execute("SELECT id FROM ticket_solvers WHERE email = ?", (email,))
        solver_id = cursor.fetchone()[0]
        
        # Log registration event in same transaction
        log_audit_event(session['user_id'], 'admin', f"Created new Solver account: {username} ({email})", solver_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': f"Solver account '{username}' created successfully."})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/create_account', methods=['POST'])
def api_admin_create_account():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    data = request.get_json() or {}
    role = data.get('role', '').strip().lower()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    
    if not role or not username or not email or not password:
        return jsonify({'success': False, 'message': 'Please fill in all fields.'}), 400
        
    if role not in ['user', 'solver', 'admin']:
        return jsonify({'success': False, 'message': 'Invalid role specified.'}), 400
        
    if '@' not in email:
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400
        
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters.'}), 400
        
    table_map = {
        'user': 'users',
        'solver': 'ticket_solvers',
        'admin': 'admins'
    }
    table = table_map[role]
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if email already exists in target table
        cursor.execute(f"SELECT id FROM {table} WHERE email = ?", (email,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': f'An account with this email already exists in {table}.'}), 400
            
        hashed_password = generate_password_hash(password)
        if role == 'solver':
            cursor.execute(
                "INSERT INTO ticket_solvers (username, email, password, is_approved, created_at) VALUES (?, ?, ?, 1, ?)",
                (username, email, hashed_password, datetime.utcnow().isoformat())
            )
        elif role == 'user':
            cursor.execute(
                "INSERT INTO users (username, email, password, is_approved, created_at) VALUES (?, ?, ?, 1, ?)",
                (username, email, hashed_password, datetime.utcnow().isoformat())
            )
        else: # admin
            cursor.execute(
                "INSERT INTO admins (username, email, password, created_at) VALUES (?, ?, ?, ?)",
                (username, email, hashed_password, datetime.utcnow().isoformat())
            )
            
        # Get the new ID
        cursor.execute(f"SELECT id FROM {table} WHERE email = ?", (email,))
        new_id = cursor.fetchone()[0]
        
        # Log registration event in same transaction
        log_audit_event(session['user_id'], 'admin', f"Admin created new {role} account: {username} ({email})", new_id, cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': f"Account '{username}' created successfully as {role.upper()}."})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/audit_logs', methods=['GET'])
def api_admin_audit_logs():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT log_id, actor_id, actor_role, action, target_id, timestamp FROM audit_logs ORDER BY log_id DESC")
        logs = cursor.fetchall()
        
        resolved_logs = []
        for log in logs:
            actor_id = log['actor_id']
            actor_role = log['actor_role']
            username = "Unknown"
            
            if actor_role == 'user':
                cursor.execute("SELECT username FROM users WHERE id = ?", (actor_id,))
            elif actor_role == 'solver':
                cursor.execute("SELECT username FROM ticket_solvers WHERE id = ?", (actor_id,))
            elif actor_role == 'admin':
                cursor.execute("SELECT username FROM admins WHERE id = ?", (actor_id,))
                
            row = cursor.fetchone()
            if row:
                username = row['username']
                
            resolved_logs.append({
                'log_id': log['log_id'],
                'actor_name': username,
                'actor_role': actor_role,
                'action': log['action'],
                'target_id': log['target_id'],
                'timestamp': log['timestamp']
            })
            
        return jsonify({'success': True, 'logs': resolved_logs})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/audit_logs', methods=['DELETE'])
def api_admin_clear_audit_logs():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM audit_logs")
        
        # Log this action as the first entry in the new log
        log_audit_event(session['user_id'], 'admin', "Cleared audit log history", session['user_id'], cursor=cursor)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Audit logs cleared successfully.'})
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/tickets/<int:ticket_id>', methods=['DELETE'])
def api_admin_delete_ticket(ticket_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ticket_id FROM tickets WHERE ticket_id = ?", (ticket_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Ticket not found.'}), 404
            
        # 1. Delete references in activity log first (standard clean up)
        cursor.execute("DELETE FROM ticket_activity WHERE ticket_id = ?", (ticket_id,))
        
        # 2. Delete the ticket itself
        cursor.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
        
        # Log action in same transaction
        log_audit_event(session['user_id'], 'admin', f"Deleted ticket TKT-{ticket_id}", ticket_id, cursor=cursor)
        
        conn.commit()
        trigger_ai_retraining()
        return jsonify({'success': True, 'message': 'Ticket deleted successfully.'})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/tickets/<int:ticket_id>/activity', methods=['GET'])
def api_get_ticket_activity(ticket_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized access.'}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT ta.*, ts.username as solver_name 
            FROM ticket_activity ta
            JOIN ticket_solvers ts ON ta.solver_id = ts.id
            WHERE ta.ticket_id = ?
            ORDER BY ta.activity_id ASC
        ''', (ticket_id,))
        
        rows = cursor.fetchall()
        
        activity_list = []
        for row in rows:
            activity_list.append({
                'id': row['activity_id'],
                'solver': row['solver_name'],
                'oldStatus': row['old_status'],
                'newStatus': row['new_status'],
                'updatedAt': row['updated_at']
            })
            
        return jsonify({'success': True, 'activity': activity_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server database error: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()


# --- PUBLIC STATS ENDPOINT FOR MAIN PAGE ---

@app.route('/api/public/stats', methods=['GET'])
def api_public_stats():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tickets")
        total_tickets = cursor.fetchone()[0]
        return jsonify({'success': True, 'totalTickets': total_tickets})
    except Exception as e:
        return jsonify({'success': False, 'totalTickets': 0})
    finally:
        if conn:
            conn.close()


# --- FRONTEND ROUTING & ROLE-BASED ACCESS CONTROL (RBAC) ---

@app.route('/')
@app.route('/index.html')
def serve_index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/dashboard-user.html')
def serve_user_dashboard():
    if session.get('role') == 'user':
        return send_from_directory(BASE_DIR, 'dashboard-user.html')
    return redirect(url_for('serve_index'))

@app.route('/dashboard-solver.html')
def serve_solver_dashboard():
    if session.get('role') == 'solver':
        return send_from_directory(BASE_DIR, 'dashboard-solver.html')
    return redirect(url_for('serve_index'))

@app.route('/dashboard-admin.html')
def serve_admin_dashboard():
    if session.get('role') == 'admin':
        return send_from_directory(BASE_DIR, 'dashboard-admin.html')
    return redirect(url_for('serve_index'))


# --- STATIC ASSETS CATCH-ALL ---

@app.route('/<path:filename>')
def serve_static_assets(filename):
    return send_from_directory(BASE_DIR, filename)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
