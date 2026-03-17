import os, uuid, base64, secrets, re
from datetime import datetime, date, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, render_template, session, send_from_directory

from db import get_db, q, q1, ex, PH, init_db, seed_demo
from stripe_routes import stripe_bp

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

PLAN_LIMITS = {
    'starter':    {'max_employees': 10,  'max_admins': 1,  'history_days': 30,  'export': False, 'analytics': False},
    'pro':        {'max_employees': 100, 'max_admins': 5,  'history_days': 365, 'export': True,  'analytics': True},
    'enterprise': {'max_employees': 9999,'max_admins': 999,'history_days': 9999,'export': True,  'analytics': True},
}

init_db()
seed_demo()

# Register Stripe routes
app.register_blueprint(stripe_bp)

# Run Stripe migration (adds columns if not exist)
def run_stripe_migration():
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)")
            cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255)")
            conn.commit()
    except Exception as e:
        print(f"[Stripe migration] {e}")

if os.environ.get('DATABASE_URL'):
    run_stripe_migration()

# ═══════════════════════════════════════════
# AUTH DECORATORS
# ═══════════════════════════════════════════
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
            return jsonify({"error": "Accès refusé — admin requis"}), 403
        return f(*args, **kwargs)
    return decorated

def get_company_plan():
    with get_db() as conn:
        co = q1(f"SELECT plan FROM companies WHERE id={PH}", (session['company_id'],), conn)
        return PLAN_LIMITS.get(co['plan'], PLAN_LIMITS['starter']) if co else PLAN_LIMITS['starter']

# ═══════════════════════════════════════════
# PAGES
# ═══════════════════════════════════════════
@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/app')
def dashboard():
    return render_template('index.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ═══════════════════════════════════════════
# API — REGISTRATION
# ═══════════════════════════════════════════
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json or {}
    company_name = data.get('companyName', '').strip()
    first_name = data.get('firstName', '').strip()
    last_name = data.get('lastName', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    errors = []
    if not company_name: errors.append("Nom d'entreprise requis")
    if not first_name: errors.append("Prénom requis")
    if not last_name: errors.append("Nom requis")
    if not email or '@' not in email: errors.append("Email invalide")
    if len(password) < 6: errors.append("Mot de passe : 6 caractères minimum")
    if errors:
        return jsonify({"error": " · ".join(errors)}), 400

    slug = re.sub(r'[^a-z0-9]+', '-', company_name.lower()).strip('-')
    if not slug:
        slug = uuid.uuid4().hex[:8]

    with get_db() as conn:
        existing = q1(f"SELECT id FROM companies WHERE slug={PH}", (slug,), conn)
        if existing:
            slug = f"{slug}-{uuid.uuid4().hex[:4]}"

        existing_email = q1(f"SELECT id FROM employees WHERE email={PH}", (email,), conn)
        if existing_email:
            return jsonify({"error": "Cet email est déjà utilisé"}), 409

        comp_id = str(uuid.uuid4())
        emp_id = str(uuid.uuid4())
        code = "E001"

        ex(f"INSERT INTO companies (id,name,slug,plan,max_employees) VALUES ({PH},{PH},{PH},{PH},{PH})",
           (comp_id, company_name, slug, 'starter', 10), conn)

        ex(f"INSERT INTO employees (id,company_id,employee_code,first_name,last_name,email,department,position,password_hash,role) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})",
           (emp_id, comp_id, code, first_name, last_name, email, '', 'Directeur', generate_password_hash(password), 'admin'), conn)

        conn.commit()

    session['employee_id'] = emp_id
    session['company_id'] = comp_id
    session['role'] = 'admin'

    return jsonify({
        "message": "Entreprise créée avec succès",
        "company": {"id": comp_id, "name": company_name, "slug": slug},
        "user": {
            "id": emp_id, "code": code, "firstName": first_name, "lastName": last_name,
            "email": email, "role": "admin",
            "avatar": (first_name[0] + last_name[0]).upper()
        }
    }), 201

# ═══════════════════════════════════════════
# API — AUTH
# ═══════════════════════════════════════════
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400

    with get_db() as conn:
        emp = q1(f"SELECT * FROM employees WHERE email={PH} AND is_active={PH}",
                 (email, True if os.environ.get('DATABASE_URL') else 1), conn)

    if not emp or not check_password_hash(emp['password_hash'], password):
        return jsonify({"error": "Email ou mot de passe incorrect"}), 401

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
    with get_db() as conn:
        emp = q1(f"SELECT e.*, c.name as company_name, c.plan, c.slug FROM employees e JOIN companies c ON e.company_id=c.id WHERE e.id={PH}", (session['employee_id'],), conn)
    if not emp:
        return jsonify({"error": "Introuvable"}), 404
    limits = PLAN_LIMITS.get(emp['plan'], PLAN_LIMITS['starter'])
    return jsonify({
        "id": emp['id'], "code": emp['employee_code'],
        "firstName": emp['first_name'], "lastName": emp['last_name'],
        "email": emp['email'], "department": emp['department'],
        "position": emp['position'], "role": emp['role'],
        "avatar": (emp['first_name'][0] + emp['last_name'][0]).upper(),
        "company": {"name": emp['company_name'], "plan": emp['plan'], "slug": emp['slug']},
        "limits": limits
    })

# ═══════════════════════════════════════════
# API — COMPANY
# ═══════════════════════════════════════════
@app.route('/api/company', methods=['GET'])
@admin_required
def api_company():
    with get_db() as conn:
        co = q1(f"SELECT * FROM companies WHERE id={PH}", (session['company_id'],), conn)
        emp_count = q1(f"SELECT COUNT(*) as c FROM employees WHERE company_id={PH} AND is_active={PH}",
                       (session['company_id'], True if os.environ.get('DATABASE_URL') else 1), conn)
    limits = PLAN_LIMITS.get(co['plan'], PLAN_LIMITS['starter'])
    return jsonify({
        "id": co['id'], "name": co['name'], "slug": co['slug'], "plan": co['plan'],
        "maxEmployees": co['max_employees'],
        "employeeCount": emp_count['c'] if emp_count else 0,
        "limits": limits
    })

@app.route('/api/company', methods=['PUT'])
@admin_required
def api_update_company():
    data = request.json or {}
    with get_db() as conn:
        if 'name' in data:
            ex(f"UPDATE companies SET name={PH} WHERE id={PH}", (data['name'], session['company_id']), conn)
    return jsonify({"message": "Entreprise mise à jour"})

# ═══════════════════════════════════════════
# API — EMPLOYEES (Admin CRUD)
# ═══════════════════════════════════════════
@app.route('/api/employees', methods=['GET'])
@login_required
def api_employees():
    with get_db() as conn:
        emps = q(f"SELECT * FROM employees WHERE company_id={PH} ORDER BY last_name, first_name",
                 (session['company_id'],), conn)
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
    data = request.json or {}
    required = ['firstName', 'lastName', 'email', 'password']
    for f in required:
        if not data.get(f):
            return jsonify({"error": f"Le champ {f} est requis"}), 400

    limits = get_company_plan()
    with get_db() as conn:
        count = q1(f"SELECT COUNT(*) as c FROM employees WHERE company_id={PH} AND is_active={PH}",
                   (session['company_id'], True if os.environ.get('DATABASE_URL') else 1), conn)
        if count and count['c'] >= limits['max_employees']:
            return jsonify({"error": f"Limite de {limits['max_employees']} employés atteinte. Changez de plan pour en ajouter plus."}), 403

        existing_email = q1(f"SELECT id FROM employees WHERE email={PH}", (data['email'].lower(),), conn)
        if existing_email:
            return jsonify({"error": "Cet email est déjà utilisé"}), 409

        if data.get('role') == 'admin':
            admin_count = q1(f"SELECT COUNT(*) as c FROM employees WHERE company_id={PH} AND role='admin' AND is_active={PH}",
                             (session['company_id'], True if os.environ.get('DATABASE_URL') else 1), conn)
            if admin_count and admin_count['c'] >= limits['max_admins']:
                return jsonify({"error": f"Limite de {limits['max_admins']} admin(s) atteinte pour votre plan."}), 403

        # Auto-generate employee code
        last = q1(f"SELECT employee_code FROM employees WHERE company_id={PH} ORDER BY employee_code DESC LIMIT 1",
                  (session['company_id'],), conn)
        try:
            next_num = int(last['employee_code'][1:]) + 1 if last else 1
        except:
            next_num = 1
        code = f'E{next_num:03d}'

        emp_id = str(uuid.uuid4())
        ex(f"INSERT INTO employees (id,company_id,employee_code,first_name,last_name,email,department,position,password_hash,role) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})",
           (emp_id, session['company_id'], code, data['firstName'], data['lastName'],
            data['email'].lower(), data.get('department',''), data.get('position',''),
            generate_password_hash(data['password']), data.get('role','employee')), conn)

    return jsonify({"id": emp_id, "code": code, "message": "Employé créé"}), 201

@app.route('/api/employees/<emp_id>', methods=['PUT'])
@admin_required
def api_update_employee(emp_id):
    data = request.json or {}
    with get_db() as conn:
        emp = q1(f"SELECT * FROM employees WHERE id={PH} AND company_id={PH}", (emp_id, session['company_id']), conn)
        if not emp:
            return jsonify({"error": "Employé introuvable"}), 404

        fields, vals = [], []
        for k, col in [('firstName','first_name'),('lastName','last_name'),('email','email'),
                        ('department','department'),('position','position'),('role','role')]:
            if k in data:
                fields.append(f"{col}={PH}"); vals.append(data[k])
        if 'password' in data and data['password']:
            fields.append(f"password_hash={PH}"); vals.append(generate_password_hash(data['password']))
        if 'isActive' in data:
            active_val = True if os.environ.get('DATABASE_URL') else 1
            inactive_val = False if os.environ.get('DATABASE_URL') else 0
            fields.append(f"is_active={PH}"); vals.append(active_val if data['isActive'] else inactive_val)
        if fields:
            vals.append(emp_id)
            ex(f"UPDATE employees SET {', '.join(fields)} WHERE id={PH}", vals, conn)
    return jsonify({"message": "Employé mis à jour"})

@app.route('/api/employees/<emp_id>', methods=['DELETE'])
@admin_required
def api_delete_employee(emp_id):
    inactive = False if os.environ.get('DATABASE_URL') else 0
    with get_db() as conn:
        ex(f"UPDATE employees SET is_active={PH} WHERE id={PH} AND company_id={PH}",
           (inactive, emp_id, session['company_id']), conn)
    return jsonify({"message": "Employé désactivé"})

# ═══════════════════════════════════════════
# API — BADGES
# ═══════════════════════════════════════════
@app.route('/api/badges/today')
@login_required
def api_today_badge():
    with get_db() as conn:
        badge = q1(f"SELECT * FROM badges WHERE employee_id={PH} AND date={PH}",
                   (session['employee_id'], date.today().isoformat()), conn)
    if not badge: return jsonify(None)
    return jsonify({
        "id": badge['id'], "date": badge['date'],
        "arrival": badge['arrival_time'], "departure": badge['departure_time'],
        "breakStart": badge['break_start'], "breakEnd": badge['break_end'],
        "photoArrival": badge['photo_arrival'], "photoDeparture": badge['photo_departure'],
    })

@app.route('/api/badges/punch', methods=['POST'])
@login_required
def api_punch():
    data = request.json or {}
    action = data.get('action')
    photo_data = data.get('photo')
    emp_id = session['employee_id']
    company_id = session['company_id']
    today_str = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")

    photo_path = None
    if photo_data and isinstance(photo_data, str) and photo_data.startswith('data:image'):
        try:
            header, b64 = photo_data.split(',', 1)
            filename = f"{emp_id}_{today_str}_{action}_{uuid.uuid4().hex[:8]}.jpg"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(b64))
            photo_path = f"/static/uploads/{filename}"
        except Exception:
            pass

    with get_db() as conn:
        badge = q1(f"SELECT * FROM badges WHERE employee_id={PH} AND date={PH}", (emp_id, today_str), conn)
        if badge:
            updates = {}
            if action == 'arrival':
                updates['arrival_time'] = now
                if photo_path: updates['photo_arrival'] = photo_path
            elif action == 'departure':
                updates['departure_time'] = now
                if photo_path: updates['photo_departure'] = photo_path
            elif action == 'breakStart':
                updates['break_start'] = now
            elif action == 'breakEnd':
                updates['break_end'] = now
            if updates:
                set_clause = ", ".join(f"{k}={PH}" for k in updates)
                vals = list(updates.values()) + [badge['id']]
                ex(f"UPDATE badges SET {set_clause} WHERE id={PH}", vals, conn)
        else:
            bid = str(uuid.uuid4())
            cols = {"arrival_time":None,"departure_time":None,"break_start":None,"break_end":None,"photo_arrival":None,"photo_departure":None}
            if action=='arrival': cols["arrival_time"]=now; cols["photo_arrival"]=photo_path
            elif action=='departure': cols["departure_time"]=now; cols["photo_departure"]=photo_path
            elif action=='breakStart': cols["break_start"]=now
            elif action=='breakEnd': cols["break_end"]=now
            ex(f"INSERT INTO badges (id,employee_id,company_id,date,arrival_time,departure_time,break_start,break_end,photo_arrival,photo_departure) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})",
               (bid,emp_id,company_id,today_str,cols["arrival_time"],cols["departure_time"],cols["break_start"],cols["break_end"],cols["photo_arrival"],cols["photo_departure"]), conn)

    return jsonify({"message": "Badge enregistré", "time": now})

@app.route('/api/badges/history')
@login_required
def api_badge_history():
    emp_id = request.args.get('employee_id', session['employee_id'])
    if emp_id != session['employee_id'] and session.get('role') != 'admin':
        return jsonify({"error": "Accès refusé"}), 403

    period = request.args.get('period', 'month')
    today = date.today()
    if period == 'day': start = today
    elif period == 'week': start = today - timedelta(days=today.weekday())
    elif period == 'month': start = today.replace(day=1)
    else: start = today - timedelta(days=365)

    with get_db() as conn:
        badges = q(f"SELECT * FROM badges WHERE employee_id={PH} AND company_id={PH} AND date>={PH} ORDER BY date DESC",
                   (emp_id, session['company_id'], start.isoformat()), conn)

    return jsonify([{
        "id":b['id'],"date":b['date'],
        "arrival":b['arrival_time'],"departure":b['departure_time'],
        "breakStart":b['break_start'],"breakEnd":b['break_end'],
        "photoArrival":b['photo_arrival'],"photoDeparture":b['photo_departure'],
    } for b in badges])

# ═══════════════════════════════════════════
# API — STATS
# ═══════════════════════════════════════════
def calc_work_minutes(b):
    if not b['arrival_time'] or not b['departure_time']: return None
    ah,am = map(int, b['arrival_time'].split(':'))
    dh,dm = map(int, b['departure_time'].split(':'))
    mins = (dh*60+dm) - (ah*60+am)
    if b['break_start'] and b['break_end']:
        bsh,bsm = map(int, b['break_start'].split(':'))
        beh,bem = map(int, b['break_end'].split(':'))
        mins -= (beh*60+bem) - (bsh*60+bsm)
    return max(0, mins)

@app.route('/api/stats')
@login_required
def api_stats():
    emp_id = request.args.get('employee_id', session['employee_id'])
    if emp_id != session['employee_id'] and session.get('role') != 'admin':
        return jsonify({"error": "Accès refusé"}), 403

    today = date.today()
    result = {}

    with get_db() as conn:
        for pname, start in [("day",today),("week",today-timedelta(days=today.weekday())),("month",today.replace(day=1))]:
            badges = q(f"SELECT * FROM badges WHERE employee_id={PH} AND company_id={PH} AND date>={PH} AND date<={PH}",
                       (emp_id, session['company_id'], start.isoformat(), today.isoformat()), conn)
            total, days = 0, 0
            for b in badges:
                w = calc_work_minutes(b)
                if w is not None: total += w; days += 1
            result[pname] = {"totalMinutes":total, "daysWorked":days, "avgMinutes":round(total/days) if days else 0}

        wk_fr = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"]
        week_data = []
        for i in range(6,-1,-1):
            d = today - timedelta(days=i)
            b = q1(f"SELECT * FROM badges WHERE employee_id={PH} AND date={PH}", (emp_id, d.isoformat()), conn)
            mins = calc_work_minutes(b) if b else 0
            week_data.append({"label":wk_fr[d.weekday()],"value":mins or 0,"isToday":i==0})

    result["weekChart"] = week_data
    return jsonify(result)

@app.route('/api/dashboard')
@admin_required
def api_dashboard():
    active = True if os.environ.get('DATABASE_URL') else 1
    with get_db() as conn:
        emps = q(f"SELECT * FROM employees WHERE company_id={PH} AND is_active={PH} ORDER BY last_name",
                 (session['company_id'], active), conn)
        today_str = date.today().isoformat()
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()

        team = []
        for e in emps:
            badge = q1(f"SELECT * FROM badges WHERE employee_id={PH} AND date={PH}", (e['id'], today_str), conn)
            status = "absent"
            if badge:
                if badge['arrival_time'] and not badge['departure_time']:
                    status = "pause" if badge['break_start'] and not badge['break_end'] else "présent"
                elif badge['departure_time']:
                    status = "parti"

            wk_badges = q(f"SELECT * FROM badges WHERE employee_id={PH} AND date>={PH}", (e['id'], week_start), conn)
            wk_mins = sum(calc_work_minutes(wb) or 0 for wb in wk_badges)

            team.append({
                "id":e['id'],"code":e['employee_code'],
                "firstName":e['first_name'],"lastName":e['last_name'],
                "department":e['department'],"position":e['position'],"role":e['role'],
                "avatar":(e['first_name'][0]+e['last_name'][0]).upper(),
                "status":status,
                "todayArrival":badge['arrival_time'] if badge else None,
                "todayPhoto":badge['photo_arrival'] if badge else None,
                "weekMinutes":wk_mins,
            })

    present = sum(1 for t in team if t['status'] in ('présent','pause'))
    on_break = sum(1 for t in team if t['status'] == 'pause')
    absent = sum(1 for t in team if t['status'] == 'absent')

    return jsonify({
        "team":team,
        "summary":{"present":present,"onBreak":on_break,"absent":absent,"total":len(team)}
    })

# ═══════════════════════════════════════════
# API — PLAN INFO
# ═══════════════════════════════════════════
@app.route('/api/plan')
@login_required
def api_plan():
    with get_db() as conn:
        co = q1(f"SELECT * FROM companies WHERE id={PH}", (session['company_id'],), conn)
        emp_count = q1(f"SELECT COUNT(*) as c FROM employees WHERE company_id={PH} AND is_active={PH}",
                       (session['company_id'], True if os.environ.get('DATABASE_URL') else 1), conn)
    limits = PLAN_LIMITS.get(co['plan'], PLAN_LIMITS['starter'])
    return jsonify({
        "plan": co['plan'],
        "limits": limits,
        "usage": {"employees": emp_count['c'] if emp_count else 0}
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=port)
