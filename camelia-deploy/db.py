import os, uuid, logging
from contextlib import contextmanager
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)
DATABASE_URL = os.environ.get('DATABASE_URL', '')

if DATABASE_URL:
    import psycopg2, psycopg2.extras
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    def _connect():
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    def fetchall(cur):
        if not cur.description: return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    def fetchone(cur):
        if not cur.description: return None
        cols = [d[0] for d in cur.description]
        r = cur.fetchone()
        return dict(zip(cols, r)) if r else None
    PH = '%s'
    TRUE_VAL, FALSE_VAL = 'TRUE', 'FALSE'
    logger.info("Using PostgreSQL")
else:
    import sqlite3
    DB_PATH = os.path.join(os.path.dirname(__file__), 'camelia.db')
    def _connect():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    def fetchall(cur):
        return [dict(r) for r in cur.fetchall()]
    def fetchone(cur):
        r = cur.fetchone()
        return dict(r) if r else None
    PH = '?'
    TRUE_VAL, FALSE_VAL = '1', '0'
    logger.info("Using SQLite (local dev)")

@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def q(sql, params=None, conn=None):
    """Execute query and return all rows as dicts."""
    cur = conn.cursor()
    cur.execute(sql, params or ())
    return fetchall(cur)

def q1(sql, params=None, conn=None):
    """Execute query and return first row as dict or None."""
    cur = conn.cursor()
    cur.execute(sql, params or ())
    return fetchone(cur)

def ex(sql, params=None, conn=None):
    """Execute statement (INSERT/UPDATE/DELETE)."""
    cur = conn.cursor()
    cur.execute(sql, params or ())
    return cur

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        BOOL = 'BOOLEAN' if DATABASE_URL else 'INTEGER'
        DEF_TRUE = 'DEFAULT TRUE' if DATABASE_URL else 'DEFAULT 1'
        DEF_FALSE = 'DEFAULT FALSE' if DATABASE_URL else 'DEFAULT 0'
        TS = 'TIMESTAMP DEFAULT NOW()' if DATABASE_URL else 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'

        cur.execute(f'''CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
            plan TEXT DEFAULT 'starter', max_employees INTEGER DEFAULT 10,
            stripe_customer_id TEXT, stripe_subscription_id TEXT,
            created_at {TS}
        )''')

        cur.execute(f'''CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            employee_code TEXT NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            email TEXT NOT NULL, phone TEXT DEFAULT '', department TEXT DEFAULT '',
            position TEXT DEFAULT '', password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'employee', is_active {BOOL} {DEF_TRUE},
            created_at {TS}, UNIQUE(company_id, employee_code)
        )''')

        cur.execute(f'''CREATE TABLE IF NOT EXISTS badges (
            id TEXT PRIMARY KEY, employee_id TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            date TEXT NOT NULL, arrival_time TEXT, departure_time TEXT,
            break_start TEXT, break_end TEXT, photo_arrival TEXT, photo_departure TEXT,
            note TEXT DEFAULT '', created_at {TS}, UNIQUE(employee_id, date)
        )''')

        cur.execute(f'''CREATE TABLE IF NOT EXISTS invitations (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            email TEXT NOT NULL, token TEXT UNIQUE NOT NULL, role TEXT DEFAULT 'employee',
            used {BOOL} {DEF_FALSE}, created_at {TS}
        )''')

        for idx in [
            "CREATE INDEX IF NOT EXISTS idx_badges_emp ON badges(employee_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_badges_co ON badges(company_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_emp_co ON employees(company_id)",
            "CREATE INDEX IF NOT EXISTS idx_co_slug ON companies(slug)",
            "CREATE INDEX IF NOT EXISTS idx_inv_token ON invitations(token)",
        ]:
            try: cur.execute(idx)
            except: pass

        conn.commit()
        logger.info("Schema OK")

def seed_demo():
    with get_db() as conn:
        row = q1("SELECT COUNT(*) as c FROM companies", conn=conn)
        if row and row['c'] > 0: return

        comp_id = str(uuid.uuid4())
        ex(f"INSERT INTO companies (id,name,slug,plan,max_employees) VALUES ({PH},{PH},{PH},{PH},{PH})",
           (comp_id, "Entreprise Démo", "demo", "pro", 100), conn)

        import random
        from datetime import date, timedelta
        demos = [
            ("E001","Sabri","Benamira","sabri@demo.com","Data & Analytics","Data Analyst","Admin1234!","admin"),
            ("E002","Lynne","Khoury","lynne@demo.com","Marketing","Resp. Marketing","User1234!","employee"),
            ("E003","Jan","Müller","jan@demo.com","Engineering","Dev Senior","User1234!","employee"),
            ("E004","Marie","Dupont","marie@demo.com","RH","Chargée RH","User1234!","employee"),
        ]
        for code,fn,ln,email,dept,pos,pwd,role in demos:
            eid = str(uuid.uuid4())
            ex(f"INSERT INTO employees (id,company_id,employee_code,first_name,last_name,email,department,position,password_hash,role) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})",
               (eid,comp_id,code,fn,ln,email,dept,pos,generate_password_hash(pwd),role), conn)
            today = date.today()
            for d in range(12):
                day = today - timedelta(days=d)
                if day.weekday()>=5: continue
                if d==0 and random.random()>.6: continue
                aH,aM=7+random.randint(0,1),random.randint(0,50)
                dH,dM=16+random.randint(0,2),random.randint(0,55)
                bsM=random.randint(0,25); beH=12 if bsM<15 else 13; beM=(bsM+30+random.randint(5,20))%60
                dep=None if d==0 and random.random()>.4 else f"{dH:02d}:{dM:02d}"
                try:
                    ex(f"INSERT INTO badges (id,employee_id,company_id,date,arrival_time,departure_time,break_start,break_end) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})",
                       (str(uuid.uuid4()),eid,comp_id,day.isoformat(),f"{aH:02d}:{aM:02d}",dep,f"12:{bsM:02d}",f"{beH:02d}:{beM:02d}"), conn)
                except: pass
        conn.commit()
        logger.info("Demo data seeded")
