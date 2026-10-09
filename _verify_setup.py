import sys, os
sys.path.insert(0, os.getcwd())
from app.db.database import get_db, init_db
from app.db.seed import seed_all

with get_db() as conn:
    init_db(conn)
    seed_all(conn, force=False)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    print(f'Tables initialized: {len(tables)}')
    for t in tables:
        c = conn.execute(f'SELECT COUNT(*) FROM "{t["name"]}"').fetchone()[0]
        print(f'  {t["name"]}: {c} rows')

    users = conn.execute('SELECT username, role FROM users ORDER BY id').fetchall()
    print(f'Demo users: {len(users)}')
    for u in users:
        print(f'  {u["username"]} / role={u["role"]}')
