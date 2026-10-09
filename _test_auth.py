import sys, os
sys.path.insert(0, os.getcwd())
from app.core.auth import authenticate, create_user
from app.db.database import get_db, init_db
from app.db.seed import seed_all
from app.config import DEMO_USERS

with get_db() as conn:
    init_db(conn)
    seed_all(conn, force=False)
    print('auth import ok')
    u = DEMO_USERS[0]
    r = authenticate(conn, u['username'], u['password'])
    print('auth as admin ->', 'OK' if r else 'FAIL', r['username'] if r else None, r['role'] if r else None)
    print('user dict keys:', list(r.keys()) if r else [])
