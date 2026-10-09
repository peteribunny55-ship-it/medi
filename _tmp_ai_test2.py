import sys
sys.path.insert(0, '.')

import sqlite3
from app.db.database import init_db
import datetime as dt, random

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row
init_db(conn)
now = dt.datetime.now()
today = now.date()

for i in range(60):
    created = now - dt.timedelta(days=random.randint(0, 40), hours=random.randint(0,23), minutes=random.randint(0,59))
    svc = created + dt.timedelta(minutes=random.randint(5, 40))
    completed = svc + dt.timedelta(minutes=random.randint(5,30))
    conn.execute(
        "INSERT INTO queue_tokens (token_no, prefix, patient_id, department_id, status, created_at, service_started_at, completed_at) VALUES (?, ?, ?, ?, 'Completed', ?, ?, ?)",
        (i+1, 'Q', (i%20)+1, (i%3)+1, created.strftime('%Y-%m-%d %H:%M:%S'), svc.strftime('%Y-%m-%d %H:%M:%S'), completed.strftime('%Y-%m-%d %H:%M:%S')))

for i in range(60):
    adm = now - dt.timedelta(days=random.randint(1, 70))
    discharged = adm + dt.timedelta(days=random.randint(1, 10))
    conn.execute("INSERT INTO admissions (patient_id, bed_id, doctor_id, admitted_at, discharged_at, status) VALUES (?, ?, ?, ?, ?, 'Discharged')",
        ((i%20)+1, None, None, adm.strftime('%Y-%m-%d %H:%M:%S'), discharged.strftime('%Y-%m-%d %H:%M:%S')))
    ordered = now - dt.timedelta(days=random.randint(1, 70), hours=random.randint(0,12))
    resulted = ordered + dt.timedelta(minutes=random.randint(30, 180))
    conn.execute("INSERT INTO lab_requests (patient_id, test_type, requested_by, ordered_at, resulted_at, status) VALUES (?, 'CBC', 1, ?, ?, 'Resulted')",
        ((i%20)+1, ordered.strftime('%Y-%m-%d %H:%M:%S'), resulted.strftime('%Y-%m-%d %H:%M:%S')))
conn.commit()

from app.ai.bottleneck import compute_bottlenecks, get_recent_bottlenecks
b = compute_bottlenecks(conn, lookback_days=30)
assert isinstance(b, list)
for r in b:
    for k in ('workflow_step','alert_level','sample_count'):
        assert k in r
print('compute_bottlenecks OK, n=%d' % len(b))
r = get_recent_bottlenecks(conn, limit=5)
assert len(r) <= 5
print('get_recent_bottlenecks OK, n=%d' % len(r))

from app.ai.wait_time import documented_estimate, historical_avg_service, build_wait_training
m, e = documented_estimate(5, 12.5)
assert isinstance(m, int)
assert 'Estimate = patients_ahead' in e
assert 'DEMO ESTIMATES' in e
print('documented_estimate OK (%d min)' % m)
avg = historical_avg_service(conn, days=30)
assert 5 <= avg <= 70
print('historical_avg_service OK %.2f' % avg)
wt = build_wait_training(conn, days=60)
assert len(wt) > 0 and {'patients_ahead','avg_service','dow','hour','actual_wait'} <= set(wt.columns)
print('build_wait_training OK (%d rows)' % len(wt))

for i in range(150):
    d = today - dt.timedelta(days=149-i)
    for dept in [1, 2, 3]:
        conn.execute("INSERT OR IGNORE INTO appointment_daily_demand (demand_date, department_id, n_admissions, n_appointments, n_emergency, total_demand) VALUES (?, ?, ?, ?, ?, ?)",
            (d.strftime('%Y-%m-%d'), dept, i % 5 + 1, i % 10 + 5, i % 3, (i % 5 + 1) + (i % 10 + 5) + (i % 3)))
conn.commit()

from app.ai.forecast import build_demand_history, add_features
df = build_demand_history(conn, days=120)
assert len(df) == 120
print('build_demand_history OK (%d rows)' % len(df))
fe = add_features(df, holidays=['01-01'])
assert {'dow','month','is_weekend','dom','week','rolling_mean_7','rolling_mean_14','holiday_flag'} <= set(fe.columns)
print('add_features OK')

print('\nALL AVAILABLE TESTS PASSED (numpy+pd only; sklearn/plotly reqs installed elsewhere via requirements.txt)')
