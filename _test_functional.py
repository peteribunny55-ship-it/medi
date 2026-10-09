import sys, os, traceback
sys.path.insert(0, os.getcwd())
from app.db.database import get_db, init_db
from app.db.seed import seed_all
from app.core.auth import authenticate
from app.config import DEMO_USERS
import datetime as dt
import json
import pandas as pd
import uuid as _uu

def main():
    with get_db() as conn:
        init_db(conn)
        seed_all(conn, force=False)

        admin = authenticate(conn, 'admin', 'admin123')
        doctor = authenticate(conn, 'doctor', 'doctor123')
        nurse = authenticate(conn, 'nurse', 'nurse123')
        patient_u = authenticate(conn, 'patient', 'patient123')
        inv = authenticate(conn, 'inventory', 'inventory123')
        print(f'Sessions: admin={bool(admin)} doctor={bool(doctor)} nurse={bool(nurse)} patient={bool(patient_u)} inventory={bool(inv)}')

        suf = _uu.uuid4().hex[:6]
        pat = conn.execute('SELECT id FROM patients ORDER BY id LIMIT 1').fetchone()
        doc = conn.execute('SELECT id FROM doctors ORDER BY id LIMIT 1').fetchone()
        dep = conn.execute('SELECT id FROM departments ORDER BY id LIMIT 1').fetchone()

        sections = []

        def _sec(name, fn):
            try:
                print(f'\n=== {name} ===')
                fn()
                sections.append((name, True, None))
            except Exception as e:
                sections.append((name, False, e))
                print(f'FAIL {name}: {e}')
                print(f'--- tb ---')
                traceback.print_exc(limit=5)

        def _patients():
            from app.core.patients import search_patients, create_patient
            results = search_patients(conn, admin, query='', dept_id=None, date_from=None, date_to=None, limit=5)
            print(f'search_patients -> {len(results)} results; keys={list(results[0].keys()) if results else []}')
            try:
                new_p = create_patient(conn, admin, first_name='__TestFN'+suf, last_name='__TestLN'+suf, dob='1990-01-01', gender='Male', phone='+9'+suf, email='test_'+suf+'@example.com', address='addr', emergency_contact='ec')
                print(f'create_patient -> ID={new_p.get("patient_id")} OK')
            except Exception as ee:
                print(f'create_patient (conflict ok): {type(ee).__name__}')

        _sec('PATIENTS (page 2)', _patients)

        def _appointments():
            from app.core.appointments import book_appointment, appointment_conflict_exists, list_appointments
            t0 = dt.datetime(2030, 6, 1, 8, 0) + dt.timedelta(minutes=int(_uu.uuid4().hex[:4], 16) % 600)
            d_str = t0.strftime('%Y-%m-%d')
            t_str = t0.strftime('%H:%M')
            conflict = appointment_conflict_exists(conn, int(doc['id']), d_str, t_str)
            print(f'conflict_exists({d_str} {t_str}) -> {conflict}')
            bk = book_appointment(conn, patient_u if patient_u else admin, patient_id=int(pat['id']), doctor_id=int(doc['id']),
                                  dept_id=int(dep['id']), appt_date=d_str, appt_time=t_str, reason='checkup')
            print(f'book_appointment -> id={bk.get("id")} status={bk.get("status")} OK')
            l1 = list_appointments(conn, doctor, doctor_id=int(doc['id']), limit=3)
            print(f'list_appointments -> {len(l1)} rows')

        _sec('APPOINTMENTS (page 3)', _appointments)

        def _queue():
            from app.core.queue import generate_token, call_next_patient, compute_wait_estimate, list_department_queue
            gt = generate_token(conn, patient_id=int(pat['id']), dept_id=int(dep['id']), appointment_id=None, prefix='TEST')
            print(f'generate_token -> {gt.get("prefix")}-{gt.get("token_no")} id={gt.get("id")}')
            eta = compute_wait_estimate(conn, int(dep['id']))
            print(f'compute_wait_estimate(dept={dep["id"]}) -> {eta} min')
            tokens = list_department_queue(conn, dept_id=int(dep['id']))
            print(f'list_department_queue -> {len(tokens)} rows')
            try:
                nx = call_next_patient(conn, nurse if nurse else admin, int(dep['id']))
                print(f'call_next_patient -> {nx}')
            except Exception as e:
                print(f'call_next_patient (empty q ok): {type(e).__name__}')

        _sec('QUEUE (page 4)', _queue)

        def _beds():
            from app.core.beds import list_beds, allocate_bed, discharge_bed
            # Pick a bed that is Available and not currently in active admissions
            occ_bed_ids = {r[0] for r in conn.execute("SELECT bed_id FROM admissions WHERE status != 'Discharged' AND bed_id IS NOT NULL").fetchall()}
            beds = [b for b in list_beds(conn, status='Available') if b['id'] not in occ_bed_ids][:3]
            print(f'list_beds(Available) -> {len(beds)} rows; sample id={beds[0]["id"] if beds else None}')
            if beds:
                al = allocate_bed(conn, nurse if nurse else admin, bed_id=int(beds[0]['id']), patient_id=int(pat['id']),
                                  doctor_id=int(doc['id']), diagnosis='Test', admission_type='Elective', triage_level=2)
                print(f'allocate_bed -> adm_id={al.get("id") if al else None} OK')
                if al and al.get('id'):
                    discharge_bed(conn, doctor if doctor else admin, admission_id=int(al['id']))
                    print(f'discharge_bed -> OK')

        _sec('BEDS (page 5)', _beds)

        def _staff():
            from app.core.staff_scheduling import list_staff, generate_weekly_schedule
            staff = list_staff(conn, dept_id=None)[:3]
            print(f'list_staff -> {len(staff)} rows')
            ws = '2030-06-03'
            ins, method = generate_weekly_schedule(conn, admin, ws)
            print(f'generate_weekly_schedule({ws}) -> inserted={ins} method={method}')

        _sec('STAFF (page 6)', _staff)

        def _or():
            from app.core.or_scheduling import list_operating_rooms, book_or_procedure, approve_or_schedule
            ors = list_operating_rooms(conn, dept_id=None)[:3]
            print(f'list_operating_rooms -> {len(ors)} rows')
            if ors:
                t0 = dt.datetime(2035, 7, 10, 9, 0) + dt.timedelta(minutes=int(_uu.uuid4().hex[:4], 16) % 10000)
                start = t0.strftime('%Y-%m-%d %H:%M:%S')
                end = (t0 + dt.timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
                proc = book_or_procedure(conn, doctor if doctor else admin, or_id=int(ors[0]['id']), patient_id=int(pat['id']),
                                         procedure_name='Test OR '+suf, procedure_type='Elective',
                                         planned_start_iso=start, planned_end_iso=end, estimated_min=120,
                                         assigned_doctor_id=int(doc['id']))
                print(f'book_or_procedure -> id={proc.get("id")} status={proc.get("status")} requires_approval={proc.get("requires_approval")}')
                if proc and proc.get('status') == 'Draft':
                    ap = approve_or_schedule(conn, admin, int(proc['id']))
                    print(f'approve_or_schedule -> status={ap.get("status") if ap else None}')

        _sec('OR (page 7)', _or)

        def _emergency():
            from app.core.emergency import create_case, live_capacity, list_cases, set_case_status, surge_alert
            cap = live_capacity(conn)
            print(f'live_capacity -> keys={list(cap.keys()) if isinstance(cap,dict) else type(cap).__name__}')
            surge = surge_alert(conn)
            print(f'surge_alert -> {surge}')
            arr = '2030-06-05T10:00'
            cs = create_case(conn, doctor if doctor else admin, patient_id=int(pat['id']), arrival_iso=arr, triage_level=2,
                             complaint='CP', status='Triage', bed_id=None)
            print(f'create_case -> id={cs.get("id") if cs else None} status={cs.get("status") if cs else None}')
            if cs:
                set_case_status(conn, doctor if doctor else admin, int(cs['id']), 'Discharged', notes='good')
                print(f'set_case_status -> OK')
            lc = list_cases(conn, status=None)[:3]
            print(f'list_cases -> {len(lc)} rows')

        _sec('EMERGENCY (page 8)', _emergency)

        def _inventory():
            from app.core.inventory import list_items, add_stock, consume_stock, scan_low_stock_and_expiry
            items = list_items(conn, category=None, low_stock=False, near_expiry_days=None)[:3]
            print(f'list_items -> {len(items)} rows; id={items[0]["id"] if items else None} name={items[0]["name"] if items else None}')
            if items:
                add_stock(conn, admin if admin else inv, item_id=int(items[0]['id']), qty=10, reason='Test restock', ref='T1'+suf)
                consume_stock(conn, admin if admin else inv, item_id=int(items[0]['id']), qty=2, reason='Test use', ref='T2'+suf)
                print(f'stock movement -> OK')
            res = scan_low_stock_and_expiry(conn)
            print(f'scan_low_stock_and_expiry -> low={len(res.get("low_stock", []))} near_expiry={len(res.get("near_expiry", []))}')

        _sec('INVENTORY (page 9)', _inventory)

        def _lab():
            from app.core.lab import list_requests, create_request, update_status
            lreq = list_requests(conn, status=None, dept_id=None, delayed_only=False)[:3]
            print(f'list_requests -> {len(lreq)} rows')
            nr = create_request(conn, doctor if doctor else admin, patient_id=int(pat['id']),
                                test_type='CBC', test_category='Hematology', priority='Routine')
            print(f'create_request -> id={nr.get("id") if nr else None} status={nr.get("status") if nr else None}')
            if nr:
                upd = update_status(conn, nurse if nurse else admin, request_id=int(nr['id']), new_status='InProgress')
                print(f'update_status -> {upd.get("status") if upd else None}')

        _sec('LAB (page 10)', _lab)

        def _admissions():
            from app.core.admissions import allocate_bed as adm_allocate, discharge as adm_discharge, bottleneck_detection
            from app.core.beds import list_beds as _lb
            occ_bed_ids = {r[0] for r in conn.execute("SELECT bed_id FROM admissions WHERE status != 'Discharged' AND bed_id IS NOT NULL").fetchall()}
            beds2 = [b for b in _lb(conn, status='Available') if b['id'] not in occ_bed_ids][:1]
            if beds2:
                adp = adm_allocate(conn, nurse if nurse else admin, patient_id=int(pat['id']), bed_id=int(beds2[0]['id']),
                                   doctor_id=int(doc['id']), diagnosis='Test diag', admission_type='Elective')
                print(f'admit -> adm_id={adp.get("id") if adp else None}')
                if adp:
                    adm_discharge(conn, nurse if nurse else admin, admission_id=int(adp['id']))
                    print(f'discharge -> OK')
            bn = bottleneck_detection(conn, lookback_days=30)
            print(f'bottleneck_detection -> {len(bn)} records; levels={[b.get("alert_level") for b in bn[:3]]}')

        _sec('ADMISSIONS (page 11)', _admissions)

        def _handover():
            from app.core.handover import create_note, list_notes, list_tasks, create_task, update_task_status
            notes = list_notes(conn, user=admin, dept_id=None)[:3]
            print(f'list_notes -> {len(notes)} rows')
            newn = create_note(conn, user=nurse if nurse else admin, to_staff_id=int(doctor['id']) if doctor else 1, shift_id=1, dept_id=int(dep['id']), note_text='Test handover '+suf)
            print(f'create_note -> id={newn.get("id") if newn else None}')
            tasks = list_tasks(conn, user=admin)[:3]
            print(f'list_tasks -> {len(tasks)} rows')
            nt = create_task(conn, user=admin, assignee_id=int(nurse['id']) if nurse else int(admin['id']),
                             title='Test task '+suf, description='x', priority='Medium',
                             due_at='2030-08-01T10:00', dept_id=int(dep['id']))
            print(f'create_task -> id={nt.get("id") if nt else None}')
            if nt:
                update_task_status(conn, user=admin, task_id=int(nt['id']), new_status='Done')
                print(f'update_task_status -> OK')

        _sec('HANDOVER (page 12)', _handover)

        def _feedback():
            from app.core.feedback import submit_feedback, list_feedback, resolve_feedback
            fb = submit_feedback(conn, user=patient_u if patient_u else admin, patient_id=int(pat['id']),
                                 is_anonymous=False, category='Service',
                                 subject='Test '+suf, description='Good')
            print(f'submit_feedback -> id={fb.get("id") if fb else None} status={fb.get("status") if fb else None}')
            lfb = list_feedback(conn, user=admin, status=None, dept_id=None)[:3]
            print(f'list_feedback -> {len(lfb)} rows')
            if fb:
                rf = resolve_feedback(conn, admin, int(fb['id']), resolution_notes='OK')
                print(f'resolve_feedback -> status={rf.get("status") if rf else None}')

        _sec('FEEDBACK (page 13)', _feedback)

        def _ic():
            from app.core.infection_control import ensure_default_templates, list_templates, submit_record, list_records
            ensure_default_templates(conn)
            tpl = list_templates(conn)
            print(f'list_templates -> {len(tpl)} rows')
            if tpl:
                res = submit_record(conn, admin, template_id=int(tpl[0]['id']), ward='W1',
                                    dept_id=int(dep['id']), results_list_of_dicts=[{'item':'Step1','passed':True,'na':False}], notes='OK')
                print(f'submit_record -> id={res.get("id") if res else None}')
            recs = list_records(conn, dept_id=None)[:3]
            print(f'list_records -> {len(recs)} rows')

        _sec('INFECTION CONTROL (page 14)', _ic)

        def _reports():
            from app.core.reports import (build_patients_registrations_report, build_appointments_report,
                build_waiting_time_trends_report, build_bed_utilization_report, build_staff_workload_report,
                build_or_utilization_report, build_inventory_alerts_report, build_emergency_demand_report,
                build_feedback_report, build_lab_tat_report, build_audit_log_report)
            rb = [
                ('patients_reg', build_patients_registrations_report),
                ('appointments', build_appointments_report),
                ('waiting_times', build_waiting_time_trends_report),
                ('bed_util', build_bed_utilization_report),
                ('staff_workload', build_staff_workload_report),
                ('or_util', build_or_utilization_report),
                ('inv_alerts', build_inventory_alerts_report),
                ('emergency', build_emergency_demand_report),
                ('feedback', build_feedback_report),
                ('lab_tat', build_lab_tat_report),
                ('audit_log', build_audit_log_report),
            ]
            ok = True
            for name, builder in rb:
                try:
                    df = builder(conn, '2020-01-01', '2040-12-31', None)
                    print(f'  build_{name} -> {len(df)} rows cols={list(df.columns)[:3]}')
                except Exception as e:
                    ok = False
                    print(f'  build_{name} -> FAIL: {e}')
                    traceback.print_exc(limit=3)
            print(f'Reports OK: {ok}')

        _sec('REPORTS (page 15)', _reports)

        def _audit():
            from app.core.audit import list_audit_logs
            al = list_audit_logs(conn, actor_id=None, action=None, entity_type=None, date_from=None, date_to=None, limit=3)
            print(f'list_audit_logs -> {len(al)} rows')

        _sec('AUDIT (page 16)', _audit)

        def _users():
            from app.core.auth import list_users, create_user, change_password, get_user_by_id
            lus = list_users(conn)[:3]
            print(f'list_users -> {len(lus)} rows')
            try:
                new_uid = create_user(conn, username='_testusr_'+suf, password='hello1234', role='Nurse',
                                      full_name='Test', email='t_'+suf+'@t.com', department_id=int(dep['id']), actor_id=admin['id'])
                print(f'create_user -> id={new_uid}')
                if new_uid:
                    u_obj = get_user_by_id(conn, new_uid)
                    acp = change_password(conn, u_obj, 'hello1234', 'newpass999')
                    print(f'change_password -> {bool(acp)}')
            except Exception as e:
                print(f'user ops -> {e}')

        _sec('USERS (page 17)', _users)

        def _notifs():
            from app.core.notifications import list_for_user, unread_count, mark_read
            uc = unread_count(conn, int(admin['id']))
            print(f'unread_count(admin) -> {uc}')
            ln = list_for_user(conn, int(admin['id']), unread_only=False, limit=3)
            print(f'list_for_user -> {len(ln)} rows')
            if ln and not int(ln[0].get('is_read') or 0):
                mark_read(conn, int(admin['id']), int(ln[0]['id']))
                print(f'mark_read -> OK')

        _sec('NOTIFICATIONS (page 22)', _notifs)

        def _blood():
            from app.core.blood import (get_blood_bank_summary, get_blood_inventory, update_blood_stock,
                list_donors, create_donor, record_donation, list_blood_requests, create_blood_request, fulfill_blood_request)
            summ = get_blood_bank_summary(conn)
            print(f'get_blood_bank_summary -> total_units={summ["total_units"]}')
            inv = get_blood_inventory(conn)
            print(f'get_blood_inventory -> {len(inv)} blood types')
            upd = update_blood_stock(conn, admin, 'O+', 2, 'Test restock')
            print(f'update_blood_stock -> new O+ total={upd["units_available"]}')
            d = create_donor(conn, admin, full_name='Test Donor '+suf, blood_type='O+', phone='+1 555-0000')
            print(f'create_donor -> code={d["donor_code"]}')
            don_rec = record_donation(conn, admin, donor_id=int(d['id']), units_donated=1)
            print(f'record_donation -> total={don_rec["total_donations"]}')
            req = create_blood_request(conn, doctor if doctor else admin, patient_id=int(pat['id']), department_id=int(dep['id']), blood_type='O+', units_requested=1, urgency='Urgent')
            print(f'create_blood_request -> id={req["id"]}')
            ful = fulfill_blood_request(conn, admin, request_id=int(req['id']))
            print(f'fulfill_blood_request -> status={ful["status"]}')

        _sec('BLOOD BANK (page 23)', _blood)

        def _ambulance():
            from app.core.ambulance import (list_ambulances, create_ambulance, update_ambulance_location,
                generate_route_geometry, dispatch_ambulance, list_dispatches, update_dispatch_status)
            ambs = list_ambulances(conn)
            print(f'list_ambulances -> {len(ambs)} ambulances')
            new_amb = create_ambulance(conn, admin, vehicle_number='AMB-TEST-'+suf, driver_name='Driver '+suf)
            print(f'create_ambulance -> vehicle={new_amb["vehicle_number"]}')
            route = generate_route_geometry(12.9800, 77.6000, 12.9716, 77.5946, route_type='fastest')
            print(f'generate_route_geometry -> dist={route["distance_km"]}km eta={route["eta_minutes"]}min waypoints={len(route["waypoints"])}')
            disp = dispatch_ambulance(conn, doctor if doctor else admin, ambulance_id=int(new_amb['id']), pickup_address='123 Test St', patient_id=int(pat['id']))
            print(f'dispatch_ambulance -> id={disp["id"]} status={disp["status"]}')
            upd_disp = update_dispatch_status(conn, admin, dispatch_id=int(disp['id']), new_status='En Route to Scene')
            print(f'update_dispatch_status -> status={upd_disp["status"]}')



        _sec('AMBULANCE NAVIGATION (page 24)', _ambulance)

        def _exporters():

            from app.utils.exporters import csv_download
            pdf = pd.DataFrame({'a':[1,2], 'b':['x','y']})
            print(f'csv_download import -> OK; type={type(csv_download).__name__}')

        _sec('CSV EXPORTERS', _exporters)

        print()
        print('=== SUMMARY ===')
        for n, ok, err in sections:
            print(f'  {("OK " if ok else "FAIL")}  {n}  {(" -> " + str(err)) if err else ""}')
        tot = len(sections)
        oks = sum(1 for _, ok, _ in sections if ok)
        print(f'\n{oks}/{tot} sections OK')

main()
