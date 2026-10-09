import sys, os, types, traceback
sys.path.insert(0, os.getcwd())

from unittest.mock import MagicMock

st_mock = MagicMock()

class _ColCtx:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __getattr__(self, name):
        def _f(*a, **k):
            if name == 'selectbox':
                opts = a[1] if len(a) > 1 else k.get('options', [0])
                if isinstance(opts, list) and opts:
                    if any(isinstance(o, int) for o in opts):
                        return opts[0] if isinstance(opts[0], int) else None
                    return opts[0]
                return None
            if name in ('text_input','text_area','password_input'): return ''
            if name in ('date_input','time_input'): return None
            if name == 'multiselect': return []
            if name == 'form_submit_button': return False
            if name == 'button': return False
            if name == 'checkbox': return False
            if name == 'number_input': return a[1] if len(a) > 1 else 0
            if name == 'slider':
                vals = k.get('value', a[1] if len(a) > 1 else 0)
                return vals if not isinstance(vals, (list, tuple)) else vals[0]
            if name == 'radio':
                opts = a[1] if len(a) > 1 else []
                return opts[0] if opts else None
            return None
        return _f

class _TabCtx:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __getattr__(self, name):
        def _f(*a, **k):
            if name in ('dataframe','markdown','write','subheader','header','caption','info','success','error','warning','metric'):
                return None
            if name == 'spinner':
                s = MagicMock()
                s.__enter__ = lambda self: None
                s.__exit__ = lambda *x: False
                return s
            if name == 'expander':
                e = MagicMock()
                e.__enter__ = lambda self: None
                e.__exit__ = lambda *x: False
                return e
            if name == 'form':
                f = MagicMock()
                f.__enter__ = lambda self: f
                f.__exit__ = lambda *x: False
                f.text_input = lambda *a,**k: ''
                f.text_area = lambda *a,**k: ''
                f.selectbox = lambda *a,**k: (a[1][0] if a and isinstance(a[1],list) and a[1] else None)
                f.multiselect = lambda *a,**k: []
                f.date_input = lambda *a,**k: None
                f.time_input = lambda *a,**k: None
                f.radio = lambda *a,**k: (a[1][0] if a and isinstance(a[1],list) and a[1] else None)
                f.slider = lambda *a,**k: (a[1] if len(a)>1 else 0)
                f.checkbox = lambda *a,**k: False
                f.number_input = lambda *a,**k: 0
                f.form_submit_button = lambda *a,**k: False
                return f
            if name == 'container':
                c = MagicMock()
                c.__enter__ = lambda self: c
                c.__exit__ = lambda *x: False
                return c
            if name == 'selectbox':
                opts = a[1] if len(a) > 1 else k.get('options', [0])
                if isinstance(opts, list) and opts:
                    if any(isinstance(o, int) for o in opts):
                        return opts[0] if isinstance(opts[0], int) else None
                    return opts[0]
                return None
            return None
        return _f

st_mock.session_state = {'user': {
    'id': 1, 'username': 'admin', 'role': 'Admin',
    'full_name': 'Dr. Alice Admin', 'email': 'admin@hospital.edu',
    'department_id': None,
}}
st_mock.title = lambda *a, **k: None
st_mock.markdown = lambda *a, **k: None
st_mock.info = lambda *a, **k: None
st_mock.success = lambda *a, **k: None
st_mock.error = lambda *a, **k: None
st_mock.warning = lambda *a, **k: None
st_mock.stop = lambda *a, **k: None
st_mock.rerun = lambda *a, **k: None
st_mock.set_page_config = lambda *a, **k: None
st_mock.switch_page = lambda *a, **k: None
st_mock.dataframe = lambda *a, **k: None
st_mock.caption = lambda *a, **k: None
st_mock.header = lambda *a, **k: None
st_mock.subheader = lambda *a, **k: None
st_mock.write = lambda *a, **k: None
st_mock.metric = lambda *a, **k: None

def _cols(n, *a, **k):
    count = n if isinstance(n, int) else len(n)
    return [_ColCtx() for _ in range(count)]
st_mock.columns = _cols
st_mock.tabs = lambda names, *a, **k: [_TabCtx() for _ in (names if isinstance(names, list) else range(names))]

_sb = MagicMock()
_sb.button = lambda *a, **k: False
_sb.markdown = lambda *a, **k: None
st_mock.sidebar = _sb

def _get_session(require_auth=True):
    return st_mock.session_state.get('user')
st_mock.get_session = _get_session

sys.modules['streamlit'] = st_mock

pages_dir = os.path.join(os.getcwd(), 'app', 'pages')
page_files = sorted(p for p in os.listdir(pages_dir) if p.endswith('.py'))

failed = []
ok = []
import importlib.util
for pf in page_files:
    try:
        role_map = {
            '6_👩‍⚕️_Staff_&_Scheduling.py': ('Admin',),
            '16_📜_Audit_Log.py': ('Admin',),
            '17_👥_Users_&_Settings.py': ('Admin',),
            '2_👥_Patients.py': ('Admin','Doctor','Nurse'),
            '3_📅_Appointments.py': ('Admin','Doctor','Nurse','Patient'),
            '4_🔢_Queue_Management.py': ('Admin','Nurse','Doctor'),
            '5_🛏️_Beds_&_ICU.py': ('Admin','Nurse','Doctor'),
            '7_🏥_Operating_Rooms.py': ('Admin','Doctor'),
            '8_🚨_Emergency.py': ('Admin','Doctor','Nurse'),
            '9_💊_Inventory.py': ('Admin','InventoryManager'),
            '10_🧪_Laboratory.py': ('Admin','Doctor','Nurse'),
            '11_🔄_Admissions_Flow.py': ('Admin','Doctor','Nurse'),
            '12_🤝_Handover_&_Tasks.py': ('Admin','Doctor','Nurse'),
            '13_💬_Feedback.py': ('Admin','Doctor','Nurse','Patient'),
            '14_🦠_Infection_Control.py': ('Admin','Doctor','Nurse'),
            '15_📊_Reports.py': ('Admin','Doctor','Nurse','InventoryManager'),
            '22_🔔_My_Notifications.py': ('Admin','Doctor','Nurse','Patient','InventoryManager'),
            '18_🩺_My_Appointments.py': ('Patient',),
            '19_⏳_My_Queue.py': ('Patient',),
            '20_📋_My_Records.py': ('Patient',),
            '21_📝_Submit_Feedback.py': ('Patient',),
        }
        roles = role_map.get(pf, ('Admin',))
        st_mock.session_state['user']['role'] = roles[0]

        mod_name = 'page_' + pf.replace('.py','').replace(' ','_').replace('&','_').replace('-','_')
        spec = importlib.util.spec_from_file_location(mod_name, os.path.join(pages_dir, pf))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ok.append(pf)
        print(f'  OK  {pf}  [role={roles[0]}]')
    except Exception as e:
        failed.append((pf, e, traceback.format_exc()))
        print(f'  FAIL  {pf}: {e}')

print()
print(f'Total: {len(page_files)} pages -> {len(ok)} OK, {len(failed)} FAILED')
if failed:
    print()
    print('=== Failures detail ===')
    for pf, e, tb in failed:
        print(f'\n--- {pf} ---')
        print(tb)
