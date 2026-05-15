from flask import Flask, render_template, request, jsonify, send_file, url_for, session, redirect
import sqlite3
import pandas as pd
import qrcode
import os
import io
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import urllib.parse
import random

# Postgres Support
try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

# Adjust folders for Vercel structure
app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-change-this')
app.config['ADMIN_PHONE'] = '081249132140' # Secret Admin Number

# Database Configuration
IS_VERCEL = os.environ.get('VERCEL')
POSTGRES_URL = os.environ.get('POSTGRES_URL')

if IS_VERCEL and POSTGRES_URL:
    DB_TYPE = 'postgres'
    # Vercel Postgres URL usually starts with postgres://, psycopg2 needs it
    DB_PATH = POSTGRES_URL
    app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
else:
    DB_TYPE = 'sqlite'
    app.config['DATABASE'] = 'database.db'
    app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Ensure folders exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def get_db():
    if DB_TYPE == 'postgres':
        conn = psycopg2.connect(DB_PATH)
        return conn
    else:
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        return conn

def query_db(query, args=(), one=False):
    conn = get_db()
    # Convert ? to %s for Postgres
    if DB_TYPE == 'postgres':
        query = query.replace('?', '%s')
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    else:
        cur = conn.execute(query, args)
    
    if DB_TYPE == 'postgres':
        cur.execute(query, args)
        rv = cur.fetchall()
    else:
        rv = cur.fetchall()
    
    conn.commit()
    cur.close()
    conn.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    conn = get_db()
    if DB_TYPE == 'postgres':
        query = query.replace('?', '%s')
        cur = conn.cursor()
        cur.execute(query, args)
        lastrowid = None
        if "INSERT" in query.upper() and "RETURNING" in query.upper():
            lastrowid = cur.fetchone()[0]
    else:
        cur = conn.execute(query, args)
        lastrowid = cur.lastrowid
    
    conn.commit()
    cur.close()
    conn.close()
    return lastrowid

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # Use SERIAL for Postgres, AUTOINCREMENT for SQLite
    pk_type = "SERIAL PRIMARY KEY" if DB_TYPE == 'postgres' else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    cur.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            id {pk_type},
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT,
            address TEXT,
            phone_number TEXT,
            is_active INTEGER DEFAULT 0,
            verification_code TEXT,
            raw_password TEXT,
            last_login TEXT,
            is_banned INTEGER DEFAULT 0
        )
    ''')
    
    # Migration helper for both DB types
    cols = [('full_name', 'TEXT'), ('address', 'TEXT'), 
            ('phone_number', 'TEXT'), ('is_active', 'INTEGER DEFAULT 0'),
            ('verification_code', 'TEXT'), ('raw_password', 'TEXT'),
            ('last_login', 'TEXT'), ('is_banned', 'INTEGER DEFAULT 0')]
    
    for col, dtype in cols:
        try:
            cur.execute(f'ALTER TABLE users ADD COLUMN {col} {dtype}')
        except:
            pass

    # Create default admin
    cur.execute('SELECT * FROM users WHERE username = %s' if DB_TYPE == 'postgres' else 'SELECT * FROM users WHERE username = ?', ('admin',))
    if not cur.fetchone():
        hashed_admin = generate_password_hash('admin123')
        cur.execute('''
            INSERT INTO users (username, password, full_name, is_active) 
            VALUES (%s, %s, %s, %s)
        ''' if DB_TYPE == 'postgres' else '''
            INSERT INTO users (username, password, full_name, is_active) 
            VALUES (?, ?, ?, ?)
        ''', ('admin', hashed_admin, 'Super Admin', 1))

    cur.execute(f'''
        CREATE TABLE IF NOT EXISTS settings (
            id {pk_type},
            user_id INTEGER NOT NULL,
            activity_name TEXT,
            activity_schedule TEXT,
            theme_type TEXT DEFAULT 'gradient_animated',
            theme_color_1 TEXT DEFAULT '#4f46e5',
            theme_color_2 TEXT DEFAULT '#06b6d4',
            theme_preset TEXT DEFAULT 'ocean',
            theme_animation TEXT DEFAULT 'flow'
        )
    ''')

    cur.execute(f'''
        CREATE TABLE IF NOT EXISTS logos (
            id {pk_type},
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL
        )
    ''')

    cur.execute(f'''
        CREATE TABLE IF NOT EXISTS participants (
            id {pk_type},
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'Tidak/Belum Hadir',
            attendance_time TEXT,
            permission_reason TEXT,
            delay_time TEXT
        )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

# --- Auth Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    init_db()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        address = request.form.get('address')
        
        country_code = request.form.get('country_code', '62')
        phone_input = request.form.get('phone_number', '').strip()
        
        if phone_input.startswith('0'):
            phone_input = phone_input[1:]
        phone = country_code + phone_input
        
        v_code = str(random.randint(100000000, 999999999))
        hashed_pw = generate_password_hash(password)
        
        try:
            # Postgres needs RETURNING id to get lastrowid easily in one go
            q = '''INSERT INTO users (username, password, full_name, address, phone_number, verification_code, raw_password, is_active) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)'''
            if DB_TYPE == 'postgres': q += " RETURNING id"
            
            u_id = execute_db(q, (username, hashed_pw, full_name, address, phone, v_code, password))
            
            execute_db('INSERT INTO settings (user_id, activity_name, activity_schedule) VALUES (?, ?, ?)', 
                       (u_id, "Nama Kegiatan Baru", "2024-01-01T08:00"))
            
            msg = f"Halo Admin, saya ingin mendaftar.\n\n*DATA PENDAFTAR*\nNama: {full_name}\nUsername: {username}\nAlamat: {address}\nNo HP: {phone}\n\n*ID VERIFIKASI (Admin Only)*: {v_code}\n\nMohon berikan kode akses untuk akun saya."
            wa_url = f"https://wa.me/{app.config['ADMIN_PHONE']}?text={urllib.parse.quote(msg)}"
            
            return render_template('register_waiting.html', username=username, wa_url=wa_url)
        except Exception as e:
            return f"Error: {str(e)}", 400
    return render_template('register.html')

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    init_db()
    if request.method == 'POST':
        username = request.form.get('username')
        code = request.form.get('code')
        user = query_db('SELECT * FROM users WHERE username = ? AND verification_code = ?', (username, code), one=True)
        if user:
            execute_db('UPDATE users SET is_active = 1 WHERE id = ?', (user['id'],))
            return redirect(url_for('login'))
        return "Kode Verifikasi Salah!", 400
    return render_template('verify.html', username=request.args.get('username', ''))

@app.route('/login', methods=['GET', 'POST'])
def login():
    init_db()
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = query_db('SELECT * FROM users WHERE username=?', (username,), one=True)
        if user and check_password_hash(user['password'], password):
            if user['is_banned'] == 1:
                error = "Akun Anda telah di-banned oleh Admin. Silakan daftar ulang."
                return render_template('login.html', error=error)

            if user['last_login']:
                last_login_dt = datetime.fromisoformat(user['last_login'])
                if datetime.now() - last_login_dt > timedelta(days=90):
                    execute_db('UPDATE users SET is_banned = 1 WHERE id = ?', (user['id'],))
                    error = "Akun Anda telah kedaluwarsa (tidak aktif 3 bulan). Silakan daftar ulang."
                    return render_template('login.html', error=error)

            if user['is_active'] == 0:
                return redirect(url_for('verify', username=username))
            
            execute_db('UPDATE users SET last_login = ? WHERE id = ?', (datetime.now().isoformat(), user['id']))
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('admin'))
        error = "Username atau Password salah!"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Dashboard ---
@app.route('/')
def admin():
    init_db()
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('admin.html', username=session['username'])

@app.route('/presensi/<username>')
def index(username):
    init_db()
    user = query_db('SELECT id FROM users WHERE username=?', (username,), one=True)
    if not user:
        return "User tidak ditemukan!", 404
    return render_template('index.html', target_user_id=user['id'], target_username=username)

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    init_db()
    u_id = session.get('user_id') or request.args.get('user_id')
    if not u_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    if request.method == 'POST':
        if 'user_id' not in session: return jsonify({"status": "error"}), 401
        name = request.form.get('activity_name')
        schedule = request.form.get('activity_schedule')
        theme_type = request.form.get('theme_type')
        color1 = request.form.get('theme_color_1')
        color2 = request.form.get('theme_color_2')
        preset = request.form.get('theme_preset')
        animation = request.form.get('theme_animation')
        logos = request.files.getlist('activity_logos')
        
        execute_db('''
            UPDATE settings 
            SET activity_name=?, activity_schedule=?, theme_type=?, theme_color_1=?, theme_color_2=?, theme_preset=?, theme_animation=? 
            WHERE user_id=?
        ''', (name, schedule, theme_type, color1, color2, preset, animation, u_id))
        
        for logo in logos:
            if logo and logo.filename != '':
                if not logo.filename.lower().endswith('.png'): continue
                filename = secure_filename(f"{u_id}_{datetime.now().timestamp()}_{logo.filename}")
                logo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                execute_db('INSERT INTO logos (user_id, filename) VALUES (?, ?)', (u_id, filename))
        return jsonify({"status": "success"})
    
    settings = query_db('SELECT * FROM settings WHERE user_id=?', (u_id,), one=True)
    logos = query_db('SELECT filename FROM logos WHERE user_id=?', (u_id,))
    result = dict(settings) if settings else {}
    result['logos'] = [l['filename'] for l in logos]
    return jsonify(result)

@app.route('/api/logos/reset', methods=['POST'])
def reset_logos():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    u_id = session['user_id']
    logos = query_db('SELECT filename FROM logos WHERE user_id=?', (u_id,))
    for logo in logos:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], logo['filename'])
        if os.path.exists(file_path): os.remove(file_path)
    execute_db('DELETE FROM logos WHERE user_id=?', (u_id,))
    return jsonify({"status": "success"})

@app.route('/api/pending-users')
def get_pending_users():
    if 'user_id' not in session or session['username'] != 'admin':
        return jsonify([]), 403
    users = query_db('SELECT id, username, full_name, phone_number, verification_code, raw_password FROM users WHERE is_active = 0 AND username != "admin"')
    return jsonify([dict(u) for u in users])

@app.route('/api/active-users')
def get_active_users():
    if 'user_id' not in session or session['username'] != 'admin':
        return jsonify([]), 403
    users = query_db('SELECT id, username, full_name, phone_number, last_login FROM users WHERE is_active = 1 AND is_banned = 0 AND username != "admin"')
    return jsonify([dict(u) for u in users])

@app.route('/api/admin/ban', methods=['POST'])
def ban_user():
    if 'user_id' not in session or session['username'] != 'admin':
        return jsonify({"status": "error"}), 403
    u_id = request.json.get('id')
    execute_db('UPDATE users SET is_banned = 1 WHERE id = ?', (u_id,))
    return jsonify({"status": "success"})

@app.route('/api/participants', methods=['GET'])
def get_participants():
    u_id = session.get('user_id') or request.args.get('user_id')
    if not u_id: return jsonify([]), 401
    participants = query_db('SELECT * FROM participants WHERE user_id=?', (u_id,))
    return jsonify([dict(p) for p in participants])

@app.route('/api/participants/import', methods=['POST'])
def import_participants():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    u_id = session['user_id']
    if 'file' not in request.files: return jsonify({"status": "error"}), 400
    file = request.files['file']
    if file:
        df = pd.read_excel(file)
        names = df.iloc[:, 0].tolist()
        for name in names:
            if pd.isna(name): continue
            execute_db('INSERT INTO participants (user_id, name) VALUES (?, ?)', (u_id, str(name)))
        return jsonify({"status": "success"})

@app.route('/api/participants/reset', methods=['POST'])
def reset_participants():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    u_id = session['user_id']
    execute_db('DELETE FROM participants WHERE user_id=?', (u_id,))
    return jsonify({"status": "success"})

@app.route('/api/attendance', methods=['POST'])
def mark_attendance():
    data = request.json
    name = data.get('name')
    status = data.get('status')
    reason = data.get('reason', '')
    u_id = data.get('user_id')
    
    settings = query_db('SELECT activity_schedule FROM settings WHERE user_id=?', (u_id,), one=True)
    if not settings: return jsonify({"status": "error", "message": "Settings not found"}), 404
    
    schedule_str = settings['activity_schedule']
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    delay_time = ""
    attendance_status = status
    if status == 'Hadir':
        try:
            schedule_dt = datetime.strptime(schedule_str, "%Y-%m-%dT%H:%M")
            if now > schedule_dt:
                diff = now - schedule_dt
                delay_time = str(diff).split('.')[0]
                attendance_status = 'Terlambat'
            else:
                attendance_status = 'Tepat Waktu'
        except Exception as e:
            attendance_status = 'Hadir'

    execute_db('''
        UPDATE participants 
        SET status=?, attendance_time=?, permission_reason=?, delay_time=? 
        WHERE name=? AND user_id=? AND (status = 'Tidak/Belum Hadir')
    ''', (attendance_status, now_str, reason, delay_time, name, u_id))
    return jsonify({"status": "success", "attendance_status": attendance_status})

@app.route('/api/export')
def export_participants():
    if 'user_id' not in session: return redirect(url_for('login'))
    u_id = session['user_id']
    
    # Pandas read_sql works best with the raw connection
    conn = get_db()
    if DB_TYPE == 'postgres':
        df = pd.read_sql_query('SELECT name, status, attendance_time, delay_time, permission_reason FROM participants WHERE user_id=%s', conn, params=(u_id,))
    else:
        df = pd.read_sql_query('SELECT name, status, attendance_time, delay_time, permission_reason FROM participants WHERE user_id=?', conn, params=(u_id,))
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Absensi')
    output.seek(0)
    conn.close()
    return send_file(output, download_name="data_absensi.xlsx", as_attachment=True)

@app.route('/api/qrcode')
def get_qrcode():
    if 'username' not in session: return "Unauthorized", 401
    url = f"{request.host_url}presensi/{session['username']}"
    img = qrcode.make(url)
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
