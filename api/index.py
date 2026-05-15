from flask import Flask, render_template, request, jsonify, send_file, url_for, session, redirect
import sqlite3
import pandas as pd
import qrcode
import os
import io
import sys
import traceback
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import urllib.parse
import random

# pg8000 Support
HAS_PG_LIB = False
try:
    import pg8000.native
    HAS_PG_LIB = True
except ImportError:
    print("Warning: pg8000 not found.", file=sys.stderr)

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-change-this')
app.config['ADMIN_PHONE'] = '081249132140' 

# Global state to cache DB type
CACHED_DB_TYPE = None

def get_db_url():
    candidates = ['POSTGRES_URL', 'DATABASE_URL', 'STORAGE_POSTGRES_URL', 'PRISMA_DATABASE_URL', 'POSTGRES_URL_NON_POOLING']
    # Check Vercel Postgres specific env vars
    for c in candidates:
        url = os.environ.get(c)
        if url: return url
    return None

def connect_db():
    global CACHED_DB_TYPE
    url = get_db_url()
    is_vercel = os.environ.get('VERCEL')
    
    if is_vercel and url and HAS_PG_LIB:
        try:
            parsed = urllib.parse.urlparse(url)
            conn = pg8000.native.Connection(
                user=parsed.username,
                password=parsed.password,
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=parsed.path.lstrip('/'),
                ssl_context=True if "sslmode=disable" not in url else None,
                timeout=10
            )
            CACHED_DB_TYPE = 'postgres'
            return conn, 'postgres'
        except Exception as e:
            print(f"Postgres Connection Error: {str(e)}", file=sys.stderr)
            # Try psycopg2 style connection string fallback for pg8000 if parsing failed
            try:
                # pg8000 native doesn't accept full URL strings, so we must parse
                pass
            except: pass
    
    # SQLite Fallback
    path = 'database.db' if not is_vercel else '/tmp/database.db'
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    CACHED_DB_TYPE = 'sqlite'
    return conn, 'sqlite'

def query_db(query, args=(), one=False):
    conn, db_type = connect_db()
    try:
        if db_type == 'postgres':
            params = {}
            for i, arg in enumerate(args):
                pname = f"p{i}"
                query = query.replace('?', f":{pname}", 1)
                params[pname] = arg
            
            res = conn.run(query, **params)
            columns = [c['name'] for c in conn.columns]
            rv = [dict(zip(columns, row)) for row in res]
        else:
            cur = conn.cursor()
            cur.execute(query, args)
            rv = cur.fetchall()
            conn.commit()
            rv = [dict(r) for r in rv]
        
        return (rv[0] if rv else None) if one else rv
    finally:
        conn.close()

def execute_db(query, args=()):
    conn, db_type = connect_db()
    try:
        if db_type == 'postgres':
            params = {}
            for i, arg in enumerate(args):
                pname = f"p{i}"
                query = query.replace('?', f":{pname}", 1)
                params[pname] = arg
            
            if "INSERT" in query.upper() and "RETURNING" not in query.upper():
                query += " RETURNING id"
            
            res = conn.run(query, **params)
            return res[0][0] if res else None
        else:
            cur = conn.execute(query, args)
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()

def init_db():
    conn, db_type = connect_db()
    try:
        if db_type == 'postgres':
            conn.run("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, full_name TEXT, address TEXT, phone_number TEXT, is_active INTEGER DEFAULT 0, verification_code TEXT, raw_password TEXT, last_login TEXT, is_banned INTEGER DEFAULT 0)")
            for col, dtype in [('full_name', 'TEXT'), ('address', 'TEXT'), ('phone_number', 'TEXT'), ('is_active', 'INTEGER DEFAULT 0'), ('verification_code', 'TEXT'), ('raw_password', 'TEXT'), ('last_login', 'TEXT'), ('is_banned', 'INTEGER DEFAULT 0')]:
                try: conn.run(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
                except: pass
            
            exists = conn.run("SELECT id FROM users WHERE username = 'admin'")
            if not exists:
                hpw = generate_password_hash('admin123')
                res = conn.run("INSERT INTO users (username, password, full_name, is_active) VALUES (:u, :p, :f, :a) RETURNING id", u='admin', p=hpw, f='Super Admin', a=1)
                admin_id = res[0][0]
            else:
                admin_id = exists[0][0]
                
            has_settings = conn.run("SELECT id FROM settings WHERE user_id = :u", u=admin_id)
            if not has_settings:
                conn.run("INSERT INTO settings (user_id, activity_name, activity_schedule) VALUES (:u, :n, :s)", u=admin_id, n="Nama Kegiatan Baru", s="2024-01-01T08:00")
            
            conn.run("CREATE TABLE IF NOT EXISTS settings (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, activity_name TEXT, activity_schedule TEXT, theme_type TEXT DEFAULT 'gradient_animated', theme_color_1 TEXT DEFAULT '#4f46e5', theme_color_2 TEXT DEFAULT '#06b6d4', theme_preset TEXT DEFAULT 'ocean', theme_animation TEXT DEFAULT 'flow')")
            conn.run("CREATE TABLE IF NOT EXISTS logos (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, filename TEXT NOT NULL)")
            conn.run("CREATE TABLE IF NOT EXISTS participants (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, status TEXT DEFAULT 'Tidak/Belum Hadir', attendance_time TEXT, permission_reason TEXT, delay_time TEXT)")
        else:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, is_active INTEGER DEFAULT 0)")
            for col, dtype in [('full_name', 'TEXT'), ('address', 'TEXT'), ('phone_number', 'TEXT'), ('is_active', 'INTEGER DEFAULT 0'), ('verification_code', 'TEXT'), ('raw_password', 'TEXT'), ('last_login', 'TEXT'), ('is_banned', 'INTEGER DEFAULT 0')]:
                try: cur.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
                except: pass
            
            cur.execute("SELECT id FROM users WHERE username = 'admin'")
            exists = cur.fetchone()
            if not exists:
                hpw = generate_password_hash('admin123')
                cur.execute("INSERT INTO users (username, password, full_name, is_active) VALUES (?, ?, ?, ?)", ('admin', hpw, 'Super Admin', 1))
                admin_id = cur.lastrowid
            else:
                admin_id = exists['id']
                
            cur.execute("SELECT id FROM settings WHERE user_id = ?", (admin_id,))
            if not cur.fetchone():
                cur.execute("INSERT INTO settings (user_id, activity_name, activity_schedule) VALUES (?, ?, ?)", (admin_id, "Nama Kegiatan Baru", "2024-01-01T08:00"))
            
            cur.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, activity_name TEXT, activity_schedule TEXT, theme_type TEXT DEFAULT 'gradient_animated', theme_color_1 TEXT DEFAULT '#4f46e5', theme_color_2 TEXT DEFAULT '#06b6d4', theme_preset TEXT DEFAULT 'ocean', theme_animation TEXT DEFAULT 'flow')")
            cur.execute("CREATE TABLE IF NOT EXISTS logos (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, filename TEXT NOT NULL)")
            cur.execute("CREATE TABLE IF NOT EXISTS participants (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, status TEXT DEFAULT 'Tidak/Belum Hadir', attendance_time TEXT, permission_reason TEXT, delay_time TEXT)")
            conn.commit()
    finally:
        conn.close()

# --- Routes ---
@app.route('/api/debug')
def debug_info():
    url = get_db_url()
    conn, db_type = connect_db()
    conn.close()
    return jsonify({
        "vercel": os.environ.get('VERCEL'),
        "has_pg8000": HAS_PG_LIB,
        "url_found": bool(url),
        "url_prefix": url[:15] if url else None,
        "active_db": db_type,
        "env_keys": list(os.environ.keys())
    })

@app.route('/register', methods=['GET', 'POST'])
def register():
    init_db()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        address = request.form.get('address')
        phone = request.form.get('country_code', '62') + request.form.get('phone_number', '').strip().lstrip('0')
        v_code = str(random.randint(100000000, 999999999))
        hpw = generate_password_hash(password)
        try:
            u_id = execute_db("INSERT INTO users (username, password, full_name, address, phone_number, verification_code, raw_password, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, 0)", (username, hpw, full_name, address, phone, v_code, password))
            execute_db('INSERT INTO settings (user_id, activity_name, activity_schedule) VALUES (?, ?, ?)', (u_id, "Nama Kegiatan Baru", "2024-01-01T08:00"))
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
        u = request.form.get('username')
        c = request.form.get('code')
        user = query_db('SELECT * FROM users WHERE username = ? AND verification_code = ?', (u, c), one=True)
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
        u = request.form.get('username')
        p = request.form.get('password')
        user = query_db('SELECT * FROM users WHERE username=?', (u,), one=True)
        if user and check_password_hash(user['password'], p):
            if user['is_banned'] == 1: return render_template('login.html', error="Akun di-banned.")
            if user['last_login']:
                try:
                    if datetime.now() - datetime.fromisoformat(user['last_login']) > timedelta(days=90):
                        execute_db('UPDATE users SET is_banned = 1 WHERE id = ?', (user['id'],))
                        return render_template('login.html', error="Akun kedaluwarsa.")
                except: pass
            if user['is_active'] == 0: return redirect(url_for('verify', username=u))
            execute_db('UPDATE users SET last_login = ? WHERE id = ?', (datetime.now().isoformat(), user['id']))
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('admin'))
        error = "Login gagal."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def admin():
    init_db()
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('admin.html', username=session['username'])

@app.route('/presensi/<username>')
def index(username):
    init_db()
    user = query_db('SELECT id FROM users WHERE username=?', (username,), one=True)
    if not user: return "Not found", 404
    return render_template('index.html', target_user_id=user['id'], target_username=username)

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    init_db()
    u_id = session.get('user_id') or request.args.get('user_id')
    if not u_id: return jsonify({"status": "error"}), 401
    u_id = int(u_id)
    if request.method == 'POST':
        if 'user_id' not in session: return jsonify({"status": "error"}), 401
        execute_db('UPDATE settings SET activity_name=?, activity_schedule=?, theme_type=?, theme_color_1=?, theme_color_2=?, theme_preset=?, theme_animation=? WHERE user_id=?', (request.form.get('activity_name'), request.form.get('activity_schedule'), request.form.get('theme_type'), request.form.get('theme_color_1'), request.form.get('theme_color_2'), request.form.get('theme_preset'), request.form.get('theme_animation'), u_id))
        logos = request.files.getlist('activity_logos')
        folder = 'static/uploads' if not os.environ.get('VERCEL') else '/tmp/uploads'
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        for logo in logos:
            if logo and logo.filename:
                fn = secure_filename(f"{u_id}_{datetime.now().timestamp()}_{logo.filename}")
                logo.save(os.path.join(folder, fn))
                execute_db('INSERT INTO logos (user_id, filename) VALUES (?, ?)', (u_id, fn))
        return jsonify({"status": "success"})
    s = query_db('SELECT * FROM settings WHERE user_id=?', (u_id,), one=True)
    l = query_db('SELECT filename FROM logos WHERE user_id=?', (u_id,))
    res = dict(s) if s else {}
    res['logos'] = [i['filename'] for i in l]
    return jsonify(res)

@app.route('/api/logos/reset', methods=['POST'])
def reset_logos():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    u_id = session['user_id']
    l = query_db('SELECT filename FROM logos WHERE user_id=?', (u_id,))
    folder = 'static/uploads' if not os.environ.get('VERCEL') else '/tmp/uploads'
    for i in l:
        p = os.path.join(folder, i['filename'])
        if os.path.exists(p): os.remove(p)
    execute_db('DELETE FROM logos WHERE user_id=?', (u_id,))
    return jsonify({"status": "success"})

@app.route('/api/pending-users')
def get_pending_users():
    if 'user_id' not in session or session['username'] != 'admin': return jsonify([]), 403
    return jsonify(query_db("SELECT id, username, full_name, phone_number, verification_code, raw_password FROM users WHERE is_active = 0 AND username != 'admin'"))

@app.route('/api/active-users')
def get_active_users():
    if 'user_id' not in session or session['username'] != 'admin': return jsonify([]), 403
    return jsonify(query_db("SELECT id, username, full_name, phone_number, last_login FROM users WHERE is_active = 1 AND is_banned = 0 AND username != 'admin'"))

@app.route('/api/admin/ban', methods=['POST'])
def ban_user():
    if 'user_id' not in session or session['username'] != 'admin': return jsonify({"status": "error"}), 403
    execute_db('UPDATE users SET is_banned = 1 WHERE id = ?', (request.json.get('id'),))
    return jsonify({"status": "success"})

@app.route('/api/participants', methods=['GET'])
def get_participants():
    u_id = session.get('user_id') or request.args.get('user_id')
    if not u_id: return jsonify([]), 401
    return jsonify(query_db('SELECT * FROM participants WHERE user_id=?', (int(u_id),)))

@app.route('/api/participants/import', methods=['POST'])
def import_participants():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    f = request.files['file']
    if f:
        df = pd.read_excel(f)
        for name in df.iloc[:, 0].tolist():
            if not pd.isna(name): execute_db('INSERT INTO participants (user_id, name) VALUES (?, ?)', (session['user_id'], str(name)))
        return jsonify({"status": "success"})

@app.route('/api/participants/reset', methods=['POST'])
def reset_participants():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    execute_db('DELETE FROM participants WHERE user_id=?', (session['user_id'],))
    return jsonify({"status": "success"})

@app.route('/api/attendance', methods=['POST'])
def mark_attendance():
    data = request.json
    u_id = int(data.get('user_id'))
    s = query_db('SELECT activity_schedule FROM settings WHERE user_id=?', (u_id,), one=True)
    if not s: return jsonify({"status": "error"}), 404
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    dt, status = "", data.get('status')
    if status == 'Hadir':
        try:
            sch = datetime.strptime(s['activity_schedule'], "%Y-%m-%dT%H:%M")
            if now > sch: dt, status = str(now - sch).split('.')[0], 'Terlambat'
            else: status = 'Tepat Waktu'
        except: status = 'Hadir'
    execute_db('UPDATE participants SET status=?, attendance_time=?, permission_reason=?, delay_time=? WHERE name=? AND user_id=? AND (status = "Tidak/Belum Hadir")', (status, now_str, data.get('reason', ''), dt, data.get('name'), u_id))
    return jsonify({"status": "success", "attendance_status": status})

@app.route('/api/export')
def export_participants():
    if 'user_id' not in session: return redirect(url_for('login'))
    u_id = session['user_id']
    conn, db_type = connect_db()
    try:
        p = "%s" if db_type == 'postgres' else "?"
        data = query_db(f'SELECT name, status, attendance_time, delay_time, permission_reason FROM participants WHERE user_id={p}', (u_id,))
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False, sheet_name='Absensi')
        output.seek(0)
        return send_file(output, download_name="data_absensi.xlsx", as_attachment=True)
    finally: conn.close()

@app.route('/api/qrcode')
def get_qrcode():
    if 'username' not in session: return "Unauthorized", 401
    img_io = io.BytesIO()
    qrcode.make(f"{request.host_url}presensi/{session['username']}").save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
