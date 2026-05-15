from flask import Flask, render_template, request, jsonify, send_file, url_for
import sqlite3
import pandas as pd
import qrcode
import os
import io
from datetime import datetime
from werkzeug.utils import secure_filename

# Adjust folders for Vercel structure
app = Flask(__name__, template_folder='../templates', static_folder='../static')

# Use /tmp for database on Vercel (read-only filesystem workaround)
if os.environ.get('VERCEL'):
    app.config['DATABASE'] = '/tmp/database.db'
    app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
else:
    app.config['DATABASE'] = 'database.db'
    app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Ensure folders exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                activity_name TEXT,
                activity_schedule TEXT,
                theme_type TEXT DEFAULT 'gradient_animated',
                theme_color_1 TEXT DEFAULT '#4f46e5',
                theme_color_2 TEXT DEFAULT '#06b6d4',
                theme_preset TEXT DEFAULT 'ocean',
                theme_animation TEXT DEFAULT 'flow'
            )
        ''')
        # Migration: Add theme columns if not exists
        for col, dtype in [('theme_type', 'TEXT DEFAULT "gradient_animated"'), 
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
                filename TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'Tidak/Belum Hadir',
                attendance_time TEXT,
                permission_reason TEXT,
                delay_time TEXT
            )
        ''')
        # Insert default settings if not exists
        cursor = conn.execute('SELECT COUNT(*) FROM settings')
        if cursor.fetchone()[0] == 0:
            conn.execute('''
                INSERT INTO settings (id, activity_name, activity_schedule, theme_type, theme_color_1, theme_color_2, theme_preset, theme_animation) 
                VALUES (1, "Nama Kegiatan", "2024-01-01T08:00", "gradient_animated", "#4f46e5", "#06b6d4", "ocean", "flow")
            ''')
        conn.commit()

@app.route('/')
def admin():
    init_db() # Ensure DB is ready on serverless cold start
    return render_template('admin.html')

@app.route('/presensi')
def index():
    init_db()
    return render_template('index.html')

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    conn = get_db()
    if request.method == 'POST':
        name = request.form.get('activity_name')
        schedule = request.form.get('activity_schedule')
        theme_type = request.form.get('theme_type')
        color1 = request.form.get('theme_color_1')
        color2 = request.form.get('theme_color_2')
        preset = request.form.get('theme_preset')
        animation = request.form.get('theme_animation')
        logos = request.files.getlist('activity_logos')
        
        # Update text settings
        conn.execute('''
            UPDATE settings 
            SET activity_name=?, activity_schedule=?, theme_type=?, theme_color_1=?, theme_color_2=?, theme_preset=?, theme_animation=? 
            WHERE id=1
        ''', (name, schedule, theme_type, color1, color2, preset, animation))
        
        # Handle logos
        for logo in logos:
            if logo and logo.filename != '':
                if not logo.filename.lower().endswith('.png'):
                    continue # Only PNG allowed
                
                filename = secure_filename(f"{datetime.now().timestamp()}_{logo.filename}")
                logo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                conn.execute('INSERT INTO logos (filename) VALUES (?)', (filename,))
        
        conn.commit()
        return jsonify({"status": "success"})
    
    settings = conn.execute('SELECT * FROM settings WHERE id=1').fetchone()
    logos = conn.execute('SELECT filename FROM logos').fetchall()
    
    result = dict(settings) if settings else {}
    result['logos'] = [l['filename'] for l in logos]
    return jsonify(result)

@app.route('/api/logos/reset', methods=['POST'])
def reset_logos():
    conn = get_db()
    logos = conn.execute('SELECT filename FROM logos').fetchall()
    
    # Delete physical files
    for logo in logos:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], logo['filename'])
        if os.path.exists(file_path):
            os.remove(file_path)
            
    conn.execute('DELETE FROM logos')
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/api/participants', methods=['GET'])
def get_participants():
    conn = get_db()
    participants = conn.execute('SELECT * FROM participants').fetchall()
    return jsonify([dict(p) for p in participants])

@app.route('/api/participants/import', methods=['POST'])
def import_participants():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400
    
    if file:
        df = pd.read_excel(file)
        names = df.iloc[:, 0].tolist() 
        
        conn = get_db()
        for name in names:
            if pd.isna(name): continue
            conn.execute('INSERT INTO participants (name) VALUES (?)', (str(name),))
        conn.commit()
        return jsonify({"status": "success"})

@app.route('/api/participants/reset', methods=['POST'])
def reset_participants():
    conn = get_db()
    conn.execute('DELETE FROM participants')
    conn.commit()
    return jsonify({"status": "success"})

@app.route('/api/attendance', methods=['POST'])
def mark_attendance():
    data = request.json
    name = data.get('name')
    status = data.get('status')
    reason = data.get('reason', '')
    
    conn = get_db()
    settings = conn.execute('SELECT activity_schedule FROM settings WHERE id=1').fetchone()
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
        WHERE name=? AND (status = 'Tidak/Belum Hadir')
    ''', (attendance_status, now_str, reason, delay_time, name))
    
    conn.commit()
    return jsonify({"status": "success", "attendance_status": attendance_status})

@app.route('/api/export')
def export_participants():
    conn = get_db()
    df = pd.read_sql_query('SELECT name, status, attendance_time, delay_time, permission_reason FROM participants', conn)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Absensi')
    output.seek(0)
    return send_file(output, download_name="data_absensi.xlsx", as_attachment=True)

@app.route('/api/qrcode')
def get_qrcode():
    url = f"{request.host_url}presensi"
    img = qrcode.make(url)
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')

# For local running
if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
