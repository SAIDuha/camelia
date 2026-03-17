import os, json, uuid, base64, hashlib, secrets
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, send_from_directory

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ═══════════════════════════════════════════
# DATABASE (SQLite)
# ═══════════════════════════════════════════
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), 'camelia.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            employee_code TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT,
            department TEXT DEFAULT '',
            position TEXT DEFAULT '',
            pin_hash TEXT NOT NULL,
            role TEXT DEFAULT 'employee' CHECK(role IN ('admin','employee')),
            is_active INTEGER DEFAULT 1,
            avatar_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id),
            UNIQUE(company_id, employee_code)
        );

        CREATE TABLE IF NOT EXISTS badges (
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            date TEXT NOT NULL,
            arrival_time TEXT,
            departure_time TEXT,
            break_start TEXT,
            break_end TEXT,
            photo_arrival TEXT,
            photo_departure TEXT,
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id),
            UNIQUE(employee_id, date)
        );

        CREATE INDEX IF NOT EXISTS idx_badges_emp_date ON badges(employee_id, date);
        CREATE INDEX IF NOT EXISTS idx_employees_company ON employees(company_id);
    ''')

    # Seed demo data if empty
    if db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
        comp_id = str(uuid.uuid4())
        db.execute("INSERT INTO companies (id, name) VALUES (?, ?)", (comp_id, "Entreprise Démo"))

        demo_employees = [
            ("E001", "Sabri", "Benamira", "sabri@demo.com", "Data & Analytics", "Data Analyst", "1234", "admin"),
            ("E002", "Lynne", "Khoury", "lynne@demo.com", "Marketing", "Responsable Marketing", "5678", "employee"),
            ("E003", "Jan", "Müller", "jan@demo.com", "Engineering", "Développeur Senior", "9012", "employee"),
            ("E004", "Marie", "Dupont", "marie@demo.com", "RH", "Chargée RH", "3456", "employee"),
        ]
        for code, fn, ln, email, dept, pos, pin, role in demo_employees:
            emp_id = str(uuid.uuid4())
            pin_hash = hashlib.sha256(pin.encode()).hexdigest()
            db.execute(
                "INSERT INTO employees (id, company_id, employee_code, first_name, last_name, email, department, position, pin_hash, role) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (emp_id, comp_id, code, fn, ln, email, dept, pos, pin_hash, role)
            )
            # Generate demo badges for last 10 business days
            import random
            today = date.today()
            for d in range(12):
                day = today - timedelta(days=d)
                if day.weekday() >= 5: continue
                if d == 0 and random.random() > 0.6: continue
                aH, aM = 7 + random.randint(0,1), random.randint(0,50)
                dH, dM = 16 + random.randint(0,2), random.randint(0,55)
                bsM = random.randint(0,25)
                beH = 12 if bsM < 15 else 13
                beM = (bsM + 30 + random.randint(5,20)) % 60
                dep = None if d == 0 and random.random() > 0.4 else f"{dH:02d}:{dM:02d}"
                db.execute(
                    "INSERT OR IGNORE INTO badges (id, employee_id, date, arrival_time, departure_time, break_start, break_end) VALUES (?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), emp_id, day.isoformat(), f"{aH:02d}:{aM:02d}", dep, f"12:{bsM:02d}", f"{beH:02d}:{beM:02d}")
                )
        db.commit()
    db.close()

init_db()

# ═══════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════
def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'employee_id' not in session:
            return jsonify({"error": "Non authentifié"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'employee_id' not in session:
            return jsonify({"error": "Non authentifié"}), 401
        if session.get('role') != 'admin':
            return jsonify({"error": "Accès refusé"}), 403
        return f(*args, **kwargs)
    return decorated

# ═══════════════════════════════════════════
# ROUTES - PAGES
# ═══════════════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ═══════════════════════════════════════════
# API - AUTH
# ═══════════════════════════════════════════
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    code = data.get('code', '').upper().strip()
    pin = data.get('pin', '')
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE employee_code = ? AND is_active = 1", (code,)).fetchone()
    db.close()
    if not emp:
        return jsonify({"error": "Identifiant inconnu"}), 401
    if emp['pin_hash'] != hash_pin(pin):
        return jsonify({"error": "Code PIN incorrect"}), 401
    session['employee_id'] = emp['id']
    session['company_id'] = emp['company_id']
    session['role'] = emp['role']
    return jsonify({
        "id": emp['id'], "code": emp['employee_code'],
        "firstName": emp['first_name'], "lastName": emp['last_name'],
        "email": emp['email'], "department": emp['department'],
        "position": emp['position'], "role": emp['role'],
        "avatar": (emp['first_name'][0] + emp['last_name'][0]).upper()
    })

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route('/api/me')
@login_required
def api_me():
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ?", (session['employee_id'],)).fetchone()
    db.close()
    if not emp: return jsonify({"error": "Introuvable"}), 404
    return jsonify({
        "id": emp['id'], "code": emp['employee_code'],
        "firstName": emp['first_name'], "lastName": emp['last_name'],
        "email": emp['email'], "department": emp['department'],
        "position": emp['position'], "role": emp['role'],
        "avatar": (emp['first_name'][0] + emp['last_name'][0]).upper()
    })

# ═══════════════════════════════════════════
# API - EMPLOYEES (Admin CRUD)
# ═══════════════════════════════════════════
@app.route('/api/employees', methods=['GET'])
@login_required
def api_employees():
    db = get_db()
    company_id = session['company_id']
    emps = db.execute("SELECT * FROM employees WHERE company_id = ? ORDER BY last_name, first_name", (company_id,)).fetchall()
    db.close()
    return jsonify([{
        "id": e['id'], "code": e['employee_code'],
        "firstName": e['first_name'], "lastName": e['last_name'],
        "email": e['email'], "department": e['department'],
        "position": e['position'], "role": e['role'],
        "isActive": bool(e['is_active']),
        "avatar": (e['first_name'][0] + e['last_name'][0]).upper()
    } for e in emps])

@app.route('/api/employees', methods=['POST'])
@admin_required
def api_create_employee():
    data = request.json
    required = ['code', 'firstName', 'lastName', 'pin']
    for f in required:
        if not data.get(f):
            return jsonify({"error": f"Le champ {f} est requis"}), 400
    db = get_db()
    company_id = session['company_id']
    existing = db.execute("SELECT id FROM employees WHERE company_id = ? AND employee_code = ?", (company_id, data['code'].upper())).fetchone()
    if existing:
        db.close()
        return jsonify({"error": "Ce code employé existe déjà"}), 409
    emp_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO employees (id, company_id, employee_code, first_name, last_name, email, department, position, pin_hash, role) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (emp_id, company_id, data['code'].upper(), data['firstName'], data['lastName'],
         data.get('email',''), data.get('department',''), data.get('position',''),
         hash_pin(data['pin']), data.get('role','employee'))
    )
    db.commit(); db.close()
    return jsonify({"id": emp_id, "message": "Employé créé"}), 201

@app.route('/api/employees/<emp_id>', methods=['PUT'])
@admin_required
def api_update_employee(emp_id):
    data = request.json
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ? AND company_id = ?", (emp_id, session['company_id'])).fetchone()
    if not emp:
        db.close(); return jsonify({"error": "Employé introuvable"}), 404
    fields = []
    vals = []
    for k, col in [('firstName','first_name'),('lastName','last_name'),('email','email'),
                    ('department','department'),('position','position'),('role','role'),('code','employee_code')]:
        if k in data:
            fields.append(f"{col} = ?"); vals.append(data[k])
    if 'pin' in data and data['pin']:
        fields.append("pin_hash = ?"); vals.append(hash_pin(data['pin']))
    if 'isActive' in data:
        fields.append("is_active = ?"); vals.append(1 if data['isActive'] else 0)
    if fields:
        vals.append(emp_id)
        db.execute(f"UPDATE employees SET {', '.join(fields)} WHERE id = ?", vals)
        db.commit()
    db.close()
    return jsonify({"message": "Employé mis à jour"})

@app.route('/api/employees/<emp_id>', methods=['DELETE'])
@admin_required
def api_delete_employee(emp_id):
    db = get_db()
    db.execute("UPDATE employees SET is_active = 0 WHERE id = ? AND company_id = ?", (emp_id, session['company_id']))
    db.commit(); db.close()
    return jsonify({"message": "Employé désactivé"})

# ═══════════════════════════════════════════
# API - BADGES
# ═══════════════════════════════════════════
@app.route('/api/badges/today')
@login_required
def api_today_badge():
    db = get_db()
    badge = db.execute("SELECT * FROM badges WHERE employee_id = ? AND date = ?",
                       (session['employee_id'], date.today().isoformat())).fetchone()
    db.close()
    if not badge: return jsonify(None)
    return jsonify({
        "id": badge['id'], "date": badge['date'],
        "arrival": badge['arrival_time'], "departure": badge['departure_time'],
        "breakStart": badge['break_start'], "breakEnd": badge['break_end'],
        "photoArrival": badge['photo_arrival'], "photoDeparture": badge['photo_departure'],
        "note": badge['note']
    })

@app.route('/api/badges/punch', methods=['POST'])
@login_required
def api_punch():
    data = request.json
    action = data.get('action')  # arrival, departure, breakStart, breakEnd
    photo_data = data.get('photo')  # base64

    emp_id = session['employee_id']
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")

    photo_path = None
    if photo_data and photo_data.startswith('data:image'):
        header, b64 = photo_data.split(',', 1)
        ext = 'jpg'
        filename = f"{emp_id}_{today}_{action}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(filepath, 'wb') as f:
            f.write(base64.b64decode(b64))
        photo_path = f"/static/uploads/{filename}"

    db = get_db()
    badge = db.execute("SELECT * FROM badges WHERE employee_id = ? AND date = ?", (emp_id, today)).fetchone()

    if badge:
        updates = {}
        if action == 'arrival':
            updates = {"arrival_time": now}
            if photo_path: updates["photo_arrival"] = photo_path
        elif action == 'departure':
            updates = {"departure_time": now}
            if photo_path: updates["photo_departure"] = photo_path
        elif action == 'breakStart':
            updates = {"break_start": now}
        elif action == 'breakEnd':
            updates = {"break_end": now}
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [badge['id']]
        db.execute(f"UPDATE badges SET {set_clause} WHERE id = ?", vals)
    else:
        badge_id = str(uuid.uuid4())
        cols = {"arrival_time": None, "departure_time": None, "break_start": None, "break_end": None,
                "photo_arrival": None, "photo_departure": None}
        if action == 'arrival':
            cols["arrival_time"] = now
            if photo_path: cols["photo_arrival"] = photo_path
        elif action == 'departure':
            cols["departure_time"] = now
            if photo_path: cols["photo_departure"] = photo_path
        elif action == 'breakStart': cols["break_start"] = now
        elif action == 'breakEnd': cols["break_end"] = now
        db.execute(
            "INSERT INTO badges (id, employee_id, date, arrival_time, departure_time, break_start, break_end, photo_arrival, photo_departure) VALUES (?,?,?,?,?,?,?,?,?)",
            (badge_id, emp_id, today, cols["arrival_time"], cols["departure_time"],
             cols["break_start"], cols["break_end"], cols["photo_arrival"], cols["photo_departure"])
        )
    db.commit(); db.close()
    return jsonify({"message": "Badge enregistré", "time": now})

@app.route('/api/badges/history')
@login_required
def api_badge_history():
    emp_id = request.args.get('employee_id', session['employee_id'])
    # Only admin can see other employees
    if emp_id != session['employee_id'] and session.get('role') != 'admin':
        return jsonify({"error": "Accès refusé"}), 403
    period = request.args.get('period', 'month')  # day, week, month, all
    today = date.today()
    if period == 'day':
        start = today
    elif period == 'week':
        start = today - timedelta(days=today.weekday())
    elif period == 'month':
        start = today.replace(day=1)
    else:
        start = today - timedelta(days=365)

    db = get_db()
    badges = db.execute(
        "SELECT * FROM badges WHERE employee_id = ? AND date >= ? ORDER BY date DESC",
        (emp_id, start.isoformat())
    ).fetchall()
    db.close()

    return jsonify([{
        "id": b['id'], "date": b['date'],
        "arrival": b['arrival_time'], "departure": b['departure_time'],
        "breakStart": b['break_start'], "breakEnd": b['break_end'],
        "photoArrival": b['photo_arrival'], "photoDeparture": b['photo_departure'],
        "note": b['note']
    } for b in badges])

# ═══════════════════════════════════════════
# API - STATS
# ═══════════════════════════════════════════
@app.route('/api/stats')
@login_required
def api_stats():
    emp_id = request.args.get('employee_id', session['employee_id'])
    if emp_id != session['employee_id'] and session.get('role') != 'admin':
        return jsonify({"error": "Accès refusé"}), 403

    today = date.today()
    db = get_db()

    result = {}
    for period_name, start in [("day", today), ("week", today - timedelta(days=today.weekday())),
                                ("month", today.replace(day=1))]:
        badges = db.execute(
            "SELECT * FROM badges WHERE employee_id = ? AND date >= ? AND date <= ?",
            (emp_id, start.isoformat(), today.isoformat())
        ).fetchall()
        total_mins = 0
        days_worked = 0
        for b in badges:
            if b['arrival_time'] and b['departure_time']:
                ah, am = map(int, b['arrival_time'].split(':'))
                dh, dm = map(int, b['departure_time'].split(':'))
                work = (dh*60+dm) - (ah*60+am)
                if b['break_start'] and b['break_end']:
                    bsh, bsm = map(int, b['break_start'].split(':'))
                    beh, bem = map(int, b['break_end'].split(':'))
                    work -= (beh*60+bem) - (bsh*60+bsm)
                total_mins += max(0, work)
                days_worked += 1
        result[period_name] = {
            "totalMinutes": total_mins,
            "daysWorked": days_worked,
            "avgMinutes": round(total_mins / days_worked) if days_worked else 0
        }

    # Weekly chart data (last 7 days)
    week_data = []
    weekdays_fr = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"]
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        b = db.execute("SELECT * FROM badges WHERE employee_id = ? AND date = ?", (emp_id, d.isoformat())).fetchone()
        mins = 0
        if b and b['arrival_time'] and b['departure_time']:
            ah, am = map(int, b['arrival_time'].split(':'))
            dh, dm = map(int, b['departure_time'].split(':'))
            mins = (dh*60+dm) - (ah*60+am)
            if b['break_start'] and b['break_end']:
                bsh, bsm = map(int, b['break_start'].split(':'))
                beh, bem = map(int, b['break_end'].split(':'))
                mins -= (beh*60+bem) - (bsh*60+bsm)
        week_data.append({"label": weekdays_fr[d.weekday()], "value": max(0, mins), "isToday": i == 0})

    db.close()
    result["weekChart"] = week_data
    return jsonify(result)

@app.route('/api/dashboard')
@admin_required
def api_dashboard():
    db = get_db()
    company_id = session['company_id']
    emps = db.execute("SELECT * FROM employees WHERE company_id = ? AND is_active = 1 ORDER BY last_name", (company_id,)).fetchall()
    today = date.today().isoformat()

    team = []
    for e in emps:
        badge = db.execute("SELECT * FROM badges WHERE employee_id = ? AND date = ?", (e['id'], today)).fetchone()
        status = "absent"
        if badge:
            if badge['arrival_time'] and not badge['departure_time']:
                status = "pause" if badge['break_start'] and not badge['break_end'] else "présent"
            elif badge['departure_time']:
                status = "parti"

        # Week total
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        week_badges = db.execute(
            "SELECT * FROM badges WHERE employee_id = ? AND date >= ?", (e['id'], week_start)
        ).fetchall()
        week_mins = 0
        for wb in week_badges:
            if wb['arrival_time'] and wb['departure_time']:
                ah, am = map(int, wb['arrival_time'].split(':'))
                dh, dm = map(int, wb['departure_time'].split(':'))
                m = (dh*60+dm) - (ah*60+am)
                if wb['break_start'] and wb['break_end']:
                    bsh, bsm = map(int, wb['break_start'].split(':'))
                    beh, bem = map(int, wb['break_end'].split(':'))
                    m -= (beh*60+bem) - (bsh*60+bsm)
                week_mins += max(0, m)

        team.append({
            "id": e['id'], "code": e['employee_code'],
            "firstName": e['first_name'], "lastName": e['last_name'],
            "department": e['department'], "position": e['position'],
            "role": e['role'],
            "avatar": (e['first_name'][0] + e['last_name'][0]).upper(),
            "status": status,
            "todayArrival": badge['arrival_time'] if badge else None,
            "todayPhoto": badge['photo_arrival'] if badge else None,
            "weekMinutes": week_mins,
        })

    db.close()
    present = sum(1 for t in team if t['status'] in ('présent','pause'))
    on_break = sum(1 for t in team if t['status'] == 'pause')
    absent = sum(1 for t in team if t['status'] == 'absent')

    return jsonify({
        "team": team,
        "summary": {"present": present, "onBreak": on_break, "absent": absent, "total": len(team)}
    })

# ═══════════════════════════════════════════
# API - COMPANY
# ═══════════════════════════════════════════
@app.route('/api/company', methods=['GET'])
@admin_required
def api_company():
    db = get_db()
    comp = db.execute("SELECT * FROM companies WHERE id = ?", (session['company_id'],)).fetchone()
    db.close()
    return jsonify({"id": comp['id'], "name": comp['name']})

@app.route('/api/company', methods=['PUT'])
@admin_required
def api_update_company():
    data = request.json
    db = get_db()
    db.execute("UPDATE companies SET name = ? WHERE id = ?", (data.get('name',''), session['company_id']))
    db.commit(); db.close()
    return jsonify({"message": "Entreprise mise à jour"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=port)
