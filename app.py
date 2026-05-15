from flask import Flask, render_template, request, jsonify, send_file, url_for
import sqlite3
import pandas as pd
import qrcode
import os
import io
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session, redirect

app = Flask(__name__)
app.secret_key = 'super-secret-key-change-this'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['DATABASE'] = 'database.db'
app.config['ADMIN_PHONE'] = '081249132140' # Secret Admin Number

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                full_name TEXT,
                address TEXT,
                phone_number TEXT,
                is_active INTEGER DEFAULT 0,
                verification_code TEXT
            )
        ''')
        # Migration for users table
        for col, dtype in [('full_name', 'TEXT'), ('address', 'TEXT'), 
                           ('phone_number', 'TEXT'), ('is_active', 'INTEGER DEFAULT 0'),
                           ('verification_code', 'TEXT'), ('raw_password', 'TEXT'),
                           ('last_login', 'TEXT'), ('is_banned', 'INTEGER DEFAULT 0')]:
            try:
                conn.execute(f'ALTER TABLE users ADD COLUMN {col} {dtype}')
            except sqlite3.OperationalError:
                pass
        # Create default admin
        admin_exists = conn.execute('SELECT * FROM users WHERE username = "admin"').fetchone()
        if not admin_exists:
            hashed_admin = generate_password_hash('admin123')
            conn.execute('''
                INSERT INTO users (username, password, full_name, is_active) 
                VALUES (?, ?, ?, ?)
            ''', ('admin', hashed_admin, 'Super Admin', 1))
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                activity_name TEXT,
                activity_schedule TEXT,
                theme_type TEXT DEFAULT 'gradient_animated',
                theme_color_1 TEXT DEFAULT '#4f46e5',
                theme_color_2 TEXT DEFAULT '#06b6d4',
                theme_preset TEXT DEFAULT 'ocean',
                theme_animation TEXT DEFAULT 'flow',
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        # Migration for settings table
        for col, dtype in [('user_id', 'INTEGER'), ('theme_type', 'TEXT DEFAULT "gradient_animated"'), 
                           ('theme_color_1', 'TEXT DEFAULT "#4f46e5"'), 
                           ('theme_color_2', 'TEXT DEFAULT "#06b6d4"'), 
                           ('theme_preset', 'TEXT DEFAULT "ocean"'),
                           ('theme_animation', 'TEXT DEFAULT "flow"')]:
            try:
                conn.execute(f'ALTER TABLE settings ADD COLUMN {col} {dtype}')
            except sqlite3.OperationalError:
                pass
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS logos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        # Migration for logos table
        try:
            conn.execute('ALTER TABLE logos ADD COLUMN user_id INTEGER')
        except sqlite3.OperationalError:
            pass

        conn.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'Tidak/Belum Hadir',
                attendance_time TEXT,
                permission_reason TEXT,
                delay_time TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        # Migration for participants table
        try:
            conn.execute('ALTER TABLE participants ADD COLUMN user_id INTEGER')
        except sqlite3.OperationalError:
            pass
        conn.commit()

def send_notification(phone, code, name, username, password):
    """
    Fungsi untuk mengirim SMS/WA Otomatis melalui API Gateway.
    Anda bisa menggunakan Twilio, Fonnte, atau layanan lainnya.
    """
    message = f"Halo {name}, Kode Verifikasi Anda: {code}. Simpan Detail Akun - User: {username}, Pass: {password}"
    print(f"\n--- [SYSTEM SMS SENT] ---\nTo: {phone}\nMessage: {message}\n------------------------\n")
    
    # CONTOH INTEGRASI FONNTE (WA GATEWAY):
    # import requests
    # url = "https://api.fonnte.com/send"
    # payload = {'target': phone, 'message': message}
    # headers = {'Authorization': 'YOUR_API_TOKEN'}
    # requests.post(url, data=payload, headers=headers)

# --- Auth Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        address = request.form.get('address')
        
        country_code = request.form.get('country_code', '62')
        phone_input = request.form.get('phone_number', '').strip()
        
        # Clean leading 0 if user still types it
        if phone_input.startswith('0'):
            phone_input = phone_input[1:]
        phone = country_code + phone_input
        
        import random
        v_code = str(random.randint(100000000, 999999999))
        hashed_pw = generate_password_hash(password)
        
        conn = get_db()
        try:
            cursor = conn.execute('''
                INSERT INTO users (username, password, full_name, address, phone_number, verification_code, raw_password, is_active) 
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ''', (username, hashed_pw, full_name, address, phone, v_code, password))
            u_id = cursor.lastrowid
            conn.execute('INSERT INTO settings (user_id, activity_name, activity_schedule) VALUES (?, ?, ?)', 
                         (u_id, "Nama Kegiatan Baru", "2024-01-01T08:00"))
            conn.commit()
            
            # Create WA message for Admin (to be sent by Registrant)
            msg = f"Halo Admin, saya ingin mendaftar.\n\n*DATA PENDAFTAR*\nNama: {full_name}\nUsername: {username}\nAlamat: {address}\nNo HP: {phone}\n\n*ID VERIFIKASI (Admin Only)*: {v_code}\n\nMohon berikan kode akses untuk akun saya."
            import urllib.parse
            wa_url = f"https://wa.me/{app.config['ADMIN_PHONE']}?text={urllib.parse.quote(msg)}"
            
            return render_template('register_waiting.html', username=username, wa_url=wa_url)
        except sqlite3.IntegrityError:
            return "Username sudah ada!", 400
    return render_template('register.html')

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if request.method == 'POST':
        username = request.form.get('username')
        code = request.form.get('code')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND verification_code = ?', (username, code)).fetchone()
        if user:
            conn.execute('UPDATE users SET is_active = 1 WHERE id = ?', (user['id'],))
            conn.commit()
            return redirect(url_for('login'))
        return "Kode Verifikasi Salah!", 400
    return render_template('verify.html', username=request.args.get('username', ''))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            # Check manual ban
            if user['is_banned'] == 1:
                error = "Akun Anda telah di-banned oleh Admin. Silakan daftar ulang."
                return render_template('login.html', error=error)

            # Check 3-month expiration
            if user['last_login']:
                from datetime import datetime, timedelta
                last_login_dt = datetime.fromisoformat(user['last_login'])
                if datetime.now() - last_login_dt > timedelta(days=90):
                    conn.execute('UPDATE users SET is_banned = 1 WHERE id = ?', (user['id'],))
                    conn.commit()
                    error = "Akun Anda telah kedaluwarsa (tidak aktif 3 bulan). Silakan daftar ulang."
                    return render_template('login.html', error=error)

            if user['is_active'] == 0:
                return redirect(url_for('verify', username=username))
            
            # Update last login
            from datetime import datetime
            conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (datetime.now().isoformat(), user['id']))
            conn.commit()
            
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
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('admin.html', username=session['username'])

@app.route('/presensi/<username>')
def index(username):
    conn = get_db()
    user = conn.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
    if not user:
        return "User tidak ditemukan!", 404
    return render_template('index.html', target_user_id=user['id'], target_username=username)

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    u_id = session.get('user_id') or request.args.get('user_id')
    if not u_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    conn = get_db()
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
        
        conn.execute('''
            UPDATE settings 
            SET activity_name=?, activity_schedule=?, theme_type=?, theme_color_1=?, theme_color_2=?, theme_preset=?, theme_animation=? 
            WHERE user_id=?
        ''', (name, schedule, theme_type, color1, color2, preset, animation, u_id))
        
        for logo in logos:
            if logo and logo.filename != '':
                if not logo.filename.lower().endswith('.png'): continue
                filename = secure_filename(f"{u_id}_{datetime.now().timestamp()}_{logo.filename}")
                logo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                conn.execute('INSERT INTO logos (user_id, filename) VALUES (?, ?)', (u_id, filename))
        conn.commit()
        return jsonify({"status": "success"})
    
    settings = conn.execute('SELECT * FROM settings WHERE user_id=?', (u_id,)).fetchone()
    logos = conn.execute('SELECT filename FROM logos WHERE user_id=?', (u_id,)).fetchall()
    result = dict(settings) if settings else {}
    result['logos'] = [l['filename'] for l in logos]
    return jsonify(result)

@app.route('/api/logos/reset', methods=['POST'])
def reset_logos():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    u_id = session['user_id']
    conn = get_db()
    logos = conn.execute('SELECT filename FROM logos WHERE user_id=?', (u_id,)).fetchall()
    for logo in logos:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], logo['filename'])
        if os.path.exists(file_path): os.remove(file_path)
    conn.execute('DELETE FROM logos WHERE user_id=?', (u_id,))
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/api/pending-users')
def get_pending_users():
    if 'user_id' not in session or session['username'] != 'admin':
        return jsonify([]), 403
    conn = get_db()
    users = conn.execute('SELECT id, username, full_name, phone_number, verification_code, raw_password FROM users WHERE is_active = 0 AND username != "admin"').fetchall()
    return jsonify([dict(u) for u in users])

@app.route('/api/active-users')
def get_active_users():
    if 'user_id' not in session or session['username'] != 'admin':
        return jsonify([]), 403
    conn = get_db()
    users = conn.execute('SELECT id, username, full_name, phone_number, last_login FROM users WHERE is_active = 1 AND is_banned = 0 AND username != "admin"').fetchall()
    return jsonify([dict(u) for u in users])

@app.route('/api/admin/ban', methods=['POST'])
def ban_user():
    if 'user_id' not in session or session['username'] != 'admin':
        return jsonify({"status": "error"}), 403
    u_id = request.json.get('id')
    conn = get_db()
    conn.execute('UPDATE users SET is_banned = 1 WHERE id = ?', (u_id,))
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/api/participants', methods=['GET'])
def get_participants():
    u_id = session.get('user_id') or request.args.get('user_id')
    if not u_id: return jsonify([]), 401
    conn = get_db()
    participants = conn.execute('SELECT * FROM participants WHERE user_id=?', (u_id,)).fetchall()
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
        conn = get_db()
        for name in names:
            if pd.isna(name): continue
            conn.execute('INSERT INTO participants (user_id, name) VALUES (?, ?)', (u_id, str(name)))
        conn.commit()
        return jsonify({"status": "success"})

@app.route('/api/participants/reset', methods=['POST'])
def reset_participants():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    u_id = session['user_id']
    conn = get_db()
    conn.execute('DELETE FROM participants WHERE user_id=?', (u_id,))
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/api/attendance', methods=['POST'])
def mark_attendance():
    data = request.json
    name = data.get('name')
    status = data.get('status')
    reason = data.get('reason', '')
    u_id = data.get('user_id')
    
    conn = get_db()
    settings = conn.execute('SELECT activity_schedule FROM settings WHERE user_id=?', (u_id,)).fetchone()
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

    conn.execute('''
        UPDATE participants 
        SET status=?, attendance_time=?, permission_reason=?, delay_time=? 
        WHERE name=? AND user_id=? AND (status = 'Tidak/Belum Hadir')
    ''', (attendance_status, now_str, reason, delay_time, name, u_id))
    conn.commit()
    return jsonify({"status": "success", "attendance_status": attendance_status})

@app.route('/api/export')
def export_participants():
    if 'user_id' not in session: return redirect(url_for('login'))
    u_id = session['user_id']
    conn = get_db()
    df = pd.read_sql_query('SELECT name, status, attendance_time, delay_time, permission_reason FROM participants WHERE user_id=?', conn, params=(u_id,))
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Absensi')
    output.seek(0)
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
