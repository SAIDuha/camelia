# Camélia - Développé par EL-JAMII SAID, Strasbourg, France
"""
Camélia — Security Module
Rate limiting, input validation, plan quota enforcement.
"""
import re
import time
import html
from functools import wraps
from flask import request, jsonify

class RateLimiter:
    def __init__(self):
        self._store = {}

    def _cleanup(self, key, window):
        now = time.time()
        if key in self._store:
            self._store[key] = [t for t in self._store[key] if now - t < window]

    def is_limited(self, key, max_requests, window_seconds):
        now = time.time()
        self._cleanup(key, window_seconds)
        hits = self._store.get(key, [])
        if len(hits) >= max_requests:
            return True
        hits.append(now)
        self._store[key] = hits
        return False

_limiter = RateLimiter()

def get_client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr or '127.0.0.1').split(',')[0].strip()

def rate_limit(max_requests=10, window=60, scope='default'):
    """Decorator: limits requests per IP."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = get_client_ip()
            key = f"rl:{scope}:{ip}"
            if _limiter.is_limited(key, max_requests, window):
                return jsonify({"error": f"Trop de requêtes. Réessayez dans {window} secondes."}), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

def validate_email(email):
    if not email or not isinstance(email, str):
        return None, "Email requis"
    email = email.strip().lower()
    if len(email) > 254:
        return None, "Email trop long"
    if not EMAIL_REGEX.match(email):
        return None, "Format email invalide"
    return email, None

def validate_password(password):
    if not password or not isinstance(password, str):
        return None, "Mot de passe requis"
    if len(password) < 6:
        return None, "Mot de passe : 6 caractères minimum"
    if len(password) > 128:
        return None, "Mot de passe trop long"
    return password, None

def validate_name(name, field_label="Nom"):
    if not name or not isinstance(name, str):
        return None, f"{field_label} requis"
    name = name.strip()
    if len(name) < 1:
        return None, f"{field_label} requis"
    if len(name) > 100:
        return None, f"{field_label} trop long (100 car. max)"
    if '<' in name or '>' in name or 'script' in name.lower():
        return None, f"{field_label} contient des caractères non autorisés"
    return name, None

def sanitize_string(value, max_length=500):
    if not value or not isinstance(value, str):
        return ''
    return html.escape(value.strip()[:max_length])

PLAN_QUOTAS = {
    'starter':    {'max_employees': 10,  'max_admins': 1,  'max_invitations': 20},
    'pro':        {'max_employees': 100, 'max_admins': 5,  'max_invitations': 200},
    'enterprise': {'max_employees': 9999,'max_admins': 999,'max_invitations': 9999},
}

def check_employee_quota(conn, company_id, plan, q1_func, PH):
    quota = PLAN_QUOTAS.get(plan, PLAN_QUOTAS['starter'])
    count = q1_func(f"SELECT COUNT(*) as c FROM employees WHERE company_id={PH} AND is_active=TRUE", (company_id,), conn)
    current = count['c'] if count else 0
    if current >= quota['max_employees']:
        return False, f"Limite de {quota['max_employees']} employés atteinte pour le plan {plan.title()}. Passez au plan supérieur."
    return True, None

def check_admin_quota(conn, company_id, plan, q1_func, PH):
    quota = PLAN_QUOTAS.get(plan, PLAN_QUOTAS['starter'])
    count = q1_func(f"SELECT COUNT(*) as c FROM employees WHERE company_id={PH} AND role='admin' AND is_active=TRUE", (company_id,), conn)
    current = count['c'] if count else 0
    if current >= quota['max_admins']:
        return False, f"Limite de {quota['max_admins']} admin(s) pour le plan {plan.title()}."
    return True, None

def check_invitation_quota(conn, company_id, plan, q1_func, PH):
    quota = PLAN_QUOTAS.get(plan, PLAN_QUOTAS['starter'])
    count = q1_func(f"SELECT COUNT(*) as c FROM invitations WHERE company_id={PH}", (company_id,), conn)
    current = count['c'] if count else 0
    if current >= quota['max_invitations']:
        return False, f"Limite de {quota['max_invitations']} invitations pour le plan {plan.title()}."
    return True, None

def secure_session_config(app):
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    if 'onrender.com' in (app.config.get('SERVER_NAME') or '') or app.config.get('ENV') == 'production':
        app.config['SESSION_COOKIE_SECURE'] = True
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400
