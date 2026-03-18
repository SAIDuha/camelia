"""
Camélia — Super Admin Routes
Secret panel for Sabri to manage all companies and plans.
"""
import os
from functools import wraps
from flask import Blueprint, request, jsonify, session, render_template
from db import get_db, q, q1, ex, PH
from security import rate_limit

superadmin_bp = Blueprint('superadmin', __name__)

# Super admin password — set in Render env vars
SUPERADMIN_EMAIL = os.environ.get('SUPERADMIN_EMAIL', 'sabri@camelia.app')
SUPERADMIN_PASSWORD = os.environ.get('SUPERADMIN_PASSWORD', 'camelia-admin-2026')

PLAN_CONFIG = {
    'starter':    {'max_employees': 10,  'max_admins': 1,  'price': '19€/mois'},
    'pro':        {'max_employees': 100, 'max_admins': 5,  'price': '49€/mois'},
    'enterprise': {'max_employees': 9999,'max_admins': 999,'price': 'Sur mesure'},
}

def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_superadmin'):
            return jsonify({"error": "Accès refusé"}), 403
        return f(*args, **kwargs)
    return decorated

# ── Page ──
@superadmin_bp.route('/superadmin')
def superadmin_page():
    return render_template('superadmin.html')

# ── Login ──
@superadmin_bp.route('/api/superadmin/login', methods=['POST'])
@rate_limit(max_requests=5, window=600, scope='superadmin_login')
def superadmin_login():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if email == SUPERADMIN_EMAIL.lower() and password == SUPERADMIN_PASSWORD:
        session['is_superadmin'] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Identifiants incorrects"}), 401

@superadmin_bp.route('/api/superadmin/logout', methods=['POST'])
def superadmin_logout():
    session.pop('is_superadmin', None)
    return jsonify({"ok": True})

# ── List all companies ──
@superadmin_bp.route('/api/superadmin/companies')
@superadmin_required
def list_companies():
    with get_db() as conn:
        companies = q("SELECT * FROM companies ORDER BY created_at DESC", (), conn)
        result = []
        for c in companies:
            emp_count = q1(f"SELECT COUNT(*) as c FROM employees WHERE company_id={PH} AND is_active=TRUE",
                          (c['id'],), conn)
            admin_info = q1(f"SELECT first_name, last_name, email FROM employees WHERE company_id={PH} AND role='admin' LIMIT 1",
                           (c['id'],), conn)
            result.append({
                "id": c['id'],
                "name": c['name'],
                "slug": c['slug'],
                "plan": c['plan'],
                "maxEmployees": c['max_employees'],
                "employeeCount": emp_count['c'] if emp_count else 0,
                "isActive": c['is_active'] if 'is_active' in c.keys() else True,
                "createdAt": str(c['created_at']) if c.get('created_at') else '',
                "adminName": f"{admin_info['first_name']} {admin_info['last_name']}" if admin_info else '—',
                "adminEmail": admin_info['email'] if admin_info else '—',
            })
    return jsonify(result)

# ── Change plan ──
@superadmin_bp.route('/api/superadmin/companies/<company_id>/plan', methods=['PUT'])
@superadmin_required
def change_plan(company_id):
    data = request.json or {}
    plan = data.get('plan')
    if plan not in PLAN_CONFIG:
        return jsonify({"error": "Plan invalide"}), 400
    config = PLAN_CONFIG[plan]
    with get_db() as conn:
        ex(f"UPDATE companies SET plan={PH}, max_employees={PH} WHERE id={PH}",
           (plan, config['max_employees'], company_id), conn)
    return jsonify({"message": f"Plan changé en {plan}", "maxEmployees": config['max_employees']})

# ── Toggle active ──
@superadmin_bp.route('/api/superadmin/companies/<company_id>/toggle', methods=['PUT'])
@superadmin_required
def toggle_company(company_id):
    with get_db() as conn:
        co = q1(f"SELECT is_active FROM companies WHERE id={PH}", (company_id,), conn)
        if not co:
            return jsonify({"error": "Entreprise introuvable"}), 404
        new_status = not co['is_active']
        ex(f"UPDATE companies SET is_active={PH} WHERE id={PH}", (new_status, company_id), conn)
    return jsonify({"message": "Statut mis à jour", "isActive": new_status})

# ── Stats overview ──
@superadmin_bp.route('/api/superadmin/stats')
@superadmin_required
def superadmin_stats():
    with get_db() as conn:
        total_companies = q1("SELECT COUNT(*) as c FROM companies", (), conn)
        total_employees = q1("SELECT COUNT(*) as c FROM employees WHERE is_active=TRUE", (), conn)
        total_badges = q1("SELECT COUNT(*) as c FROM badges", (), conn)
        plans = q("SELECT plan, COUNT(*) as c FROM companies GROUP BY plan", (), conn)
    plan_counts = {p['plan']: p['c'] for p in plans}
    return jsonify({
        "totalCompanies": total_companies['c'] if total_companies else 0,
        "totalEmployees": total_employees['c'] if total_employees else 0,
        "totalBadges": total_badges['c'] if total_badges else 0,
        "planBreakdown": plan_counts,
    })

# ── Contact requests ──
@superadmin_bp.route('/api/superadmin/contacts')
@superadmin_required
def list_contacts():
    with get_db() as conn:
        try:
            contacts = q("SELECT * FROM contact_requests ORDER BY created_at DESC", (), conn)
        except:
            contacts = []
    return jsonify([{
        "id": c['id'], "name": c['name'], "email": c['email'],
        "company": c.get('company', ''), "size": c.get('size', ''),
        "message": c.get('message', ''), "read": bool(c.get('read', False)),
        "createdAt": str(c.get('created_at', '')),
    } for c in contacts])

@superadmin_bp.route('/api/superadmin/contacts/<contact_id>/read', methods=['PUT'])
@superadmin_required
def mark_contact_read(contact_id):
    with get_db() as conn:
        ex(f"UPDATE contact_requests SET read=TRUE WHERE id={PH}", (contact_id,), conn)
    return jsonify({"message": "Marqué comme lu"})

@superadmin_bp.route('/api/superadmin/contacts/<contact_id>', methods=['DELETE'])
@superadmin_required
def delete_contact(contact_id):
    with get_db() as conn:
        ex(f"DELETE FROM contact_requests WHERE id={PH}", (contact_id,), conn)
    return jsonify({"message": "Supprimé"})
