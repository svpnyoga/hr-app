"""Demo data generator for the Enterprise HR & Workforce Management System.

Populates every module with realistic, richly varied data so the app is
immediately demonstrable after `flask --app app init-db && flask --app app seed`.

Run via `flask --app app seed` (CLI, runs inside an app context already) or
directly with `python3 seed.py` (wraps itself in an app context below).
"""
import random
from datetime import date, datetime, timedelta

import db
import rbac
from werkzeug.security import generate_password_hash

random.seed(42)
PASSWORD_HASH = generate_password_hash("admin123")
TODAY = date.today()


# ----------------------------------------------------------------------------
# Static reference data
# ----------------------------------------------------------------------------

DEPARTMENTS = [
    ("Human Resources", "HR"),
    ("Engineering", "ENG"),
    ("Sales", "SALES"),
    ("Marketing", "MKT"),
    ("Finance & Accounts", "FIN"),
    ("Operations", "OPS"),
    ("Customer Support", "CS"),
    ("Information Technology", "IT"),
]

DESIGNATIONS = {
    "Human Resources": ["HR Executive", "HR Manager", "VP - Human Resources"],
    "Engineering": ["Software Engineer", "Senior Software Engineer", "Engineering Manager"],
    "Sales": ["Sales Executive", "Sales Manager", "VP - Sales"],
    "Marketing": ["Marketing Executive", "Marketing Manager"],
    "Finance & Accounts": ["Accountant", "Finance Manager", "Chief Financial Officer"],
    "Operations": ["Operations Executive", "Operations Manager"],
    "Customer Support": ["Support Executive", "Support Team Lead"],
    "Information Technology": ["IT Support Engineer", "IT Manager"],
}

LOCATIONS = [
    ("Corporate HQ - Austin", "400 Congress Ave", "Austin", "TX", "USA", "78701"),
    ("Chicago Office", "200 W Madison St", "Chicago", "IL", "USA", "60606"),
    ("Denver Office", "1700 Lincoln St", "Denver", "CO", "USA", "80203"),
    ("Remote / Work From Home", "", "", "", "USA", ""),
]

SHIFTS = [
    ("General Shift", "09:00", "18:00", 60, 10),
    ("Morning Shift", "06:00", "14:00", 30, 10),
    ("Night Shift", "22:00", "06:00", 30, 15),
]

LEAVE_TYPES = [
    ("Casual Leave", "CL", 12, 1, 0),
    ("Sick Leave", "SL", 10, 1, 0),
    ("Earned Leave", "EL", 18, 1, 1),
    ("Maternity Leave", "ML", 90, 1, 0),
    ("Paternity Leave", "PL", 10, 1, 0),
]

CLAIM_TYPES = [
    ("Travel", "Reimbursement", 2000),
    ("Food", "Reimbursement", 400),
    ("Accommodation", "Reimbursement", 3000),
    ("Local Conveyance", "Reimbursement", 300),
    ("Fuel", "Reimbursement", 500),
    ("Medical", "Reimbursement", 5000),
    ("Other Expenses", "Reimbursement", 1000),
]

DOCUMENT_TYPES = [
    ("Offer Letter", "Onboarding", 0),
    ("Appointment Letter", "Onboarding", 0),
    ("Experience Certificate", "Exit", 0),
    ("Salary Certificate", "Finance", 1),
    ("ID Proof", "Compliance", 1),
    ("Address Proof", "Compliance", 1),
    ("Educational Certificate", "Onboarding", 0),
    ("Employee Agreement", "Compliance", 0),
    ("Company Policy Handbook", "Policy", 0),
]

COURSES = [
    ("Workplace Health & Safety", "Compliance", 2, "Online"),
    ("Diversity, Equity & Inclusion", "Compliance", 1.5, "Online"),
    ("Effective Communication Skills", "Soft Skills", 4, "Classroom"),
    ("Leadership Fundamentals", "Leadership", 8, "Blended"),
    ("Advanced Excel for Business", "Technical", 6, "Classroom"),
    ("Python for Data Analysis", "Technical", 12, "Online"),
    ("Customer Service Excellence", "Soft Skills", 3, "Classroom"),
    ("Sales Negotiation Mastery", "Sales", 5, "Blended"),
]

HOLIDAYS = [
    ("New Year's Day", "01-01"), ("Martin Luther King Jr. Day", "01-19"),
    ("Presidents' Day", "02-16"), ("Memorial Day", "05-25"),
    ("Juneteenth", "06-19"), ("Independence Day", "07-04"),
    ("Labor Day", "09-07"), ("Thanksgiving Day", "11-27"),
    ("Christmas Day", "12-25"), ("New Year's Eve", "12-31"),
]

FIRST_NAMES = [
    "James","Mary","Robert","Patricia","John","Jennifer","Michael","Linda","David","Elizabeth",
    "William","Barbara","Richard","Susan","Joseph","Jessica","Thomas","Sarah","Charles","Karen",
    "Christopher","Nancy","Daniel","Lisa","Matthew","Betty","Anthony","Margaret","Mark","Sandra",
    "Donald","Ashley","Steven","Kimberly","Paul","Emily","Andrew","Donna","Joshua","Michelle",
    "Kenneth","Carol","Kevin","Amanda","Brian","Melissa","George","Deborah","Edward","Stephanie",
    "Ronald","Rebecca","Priya","Arjun","Sophia","Liam","Olivia","Noah","Ava","Ethan",
]
LAST_NAMES = [
    "Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
    "Hernandez","Lopez","Gonzalez","Wilson","Anderson","Thomas","Taylor","Moore","Jackson","Martin",
    "Lee","Perez","Thompson","White","Harris","Sanchez","Clark","Ramirez","Lewis","Robinson",
    "Walker","Young","Allen","King","Wright","Scott","Torres","Nguyen","Hill","Flores",
    "Green","Adams","Nelson","Baker","Hall","Rivera","Campbell","Mitchell","Carter","Roberts",
]

USER_DEFS = [
    # (username, role_name, full_name, link_to_dept_head)
    ("admin", "Super Admin", "Alex Morgan", None),
    ("hradmin1", "HR Admin", "Taylor Chen", None),
    ("hrmanager1", "HR Manager", None, "Human Resources"),
    ("deptmgr1", "Department Manager", None, "Engineering"),
    ("finance1", "Finance Admin", None, "Finance & Accounts"),
    ("recruiter1", "Recruiter", "Jordan Blake", None),
    ("employee1", "Employee", None, "__random__"),
    ("mgmt1", "Management", "Casey Reynolds", None),
]


def _used_names():
    pairs = set()
    combos = [(f, l) for f in FIRST_NAMES for l in LAST_NAMES]
    random.shuffle(combos)
    return combos


def run():
    print("Seeding: permissions & roles...")
    role_ids = _seed_roles_and_permissions()

    print("Seeding: company settings...")
    _seed_company()

    print("Seeding: master data...")
    dept_ids = _seed_departments()
    designation_ids = _seed_designations(dept_ids)
    location_ids = _seed_locations()
    shift_ids = _seed_shifts()
    leave_type_ids = _seed_leave_types()
    _seed_holidays(location_ids)
    claim_type_ids = _seed_claim_types()
    doc_type_ids = _seed_document_types()
    course_ids = _seed_courses()

    print("Seeding: employees...")
    employees = _seed_employees(dept_ids, designation_ids, location_ids)

    print("Seeding: users & logins...")
    users_by_employee = _seed_users(role_ids, employees, dept_ids)

    print("Seeding: shift assignments...")
    _seed_employee_shifts(employees, shift_ids)

    print("Seeding: salary structures...")
    _seed_salary_structures(employees)

    print("Seeding: attendance history...")
    _seed_attendance(employees)

    print("Seeding: attendance regularization...")
    _seed_regularization(employees, users_by_employee)

    print("Seeding: leave balances & requests...")
    _seed_leave(employees, leave_type_ids, users_by_employee)

    print("Seeding: payroll...")
    _seed_payroll(employees)

    print("Seeding: loans...")
    _seed_loans(employees)

    print("Seeding: recruitment...")
    _seed_recruitment(dept_ids, designation_ids, location_ids)

    print("Seeding: performance...")
    _seed_performance(employees)

    print("Seeding: engagement...")
    _seed_engagement(employees, users_by_employee)

    print("Seeding: learning...")
    _seed_learning(course_ids, location_ids, employees)

    print("Seeding: field visits...")
    _seed_field_visits(employees)

    print("Seeding: claims...")
    _seed_claims(employees, claim_type_ids, users_by_employee)

    print("Seeding: HR documents...")
    _seed_documents(employees, doc_type_ids, users_by_employee)

    print("Seeding: CRM...")
    _seed_crm(users_by_employee)

    print("Seeding: notifications...")
    _seed_notifications(users_by_employee)

    print("Seeding: audit log...")
    _seed_audit_log(users_by_employee)

    print("Done.")


# ----------------------------------------------------------------------------
# Roles & permissions
# ----------------------------------------------------------------------------

def _seed_roles_and_permissions():
    role_ids = {}
    for name in rbac.ROLE_DEFAULTS.keys():
        rid = db.execute("INSERT INTO roles (name, description, is_system) VALUES (?,?,1)", (name, f"{name} role"))
        role_ids[name] = rid

    perm_ids = {}
    for code, module, entity, action, desc in rbac.all_permission_codes():
        pid = db.execute("INSERT INTO permissions (code, module, description) VALUES (?,?,?)", (code, module, desc))
        perm_ids[code] = pid

    for role_name, grants in rbac.ROLE_DEFAULTS.items():
        if grants == "*":
            continue  # Super Admin bypasses the permission table entirely (see auth.py)
        role_id = role_ids[role_name]
        codes = set()
        for module, entity, actions in grants:
            if entity == "*":
                entities = rbac.MODULES.get(module, {}).keys()
            else:
                entities = [entity]
            for ent in entities:
                for action in actions:
                    codes.add(f"{module}.{ent}.{action}")
        for code in codes:
            pid = perm_ids.get(code)
            if pid:
                db.execute("INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?,?)", (role_id, pid))
    return role_ids


def _seed_company():
    db.execute(
        """INSERT INTO company_settings (id, company_name, address, city, state, country, pincode, phone, email,
             website, gstin, pan, currency_symbol, fiscal_year_start_month)
           VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("Meridian Technologies Inc.", "400 Congress Ave, Suite 900", "Austin", "TX", "USA", "78701",
         "+1 (512) 555-0100", "hr@meridiantech.example", "https://meridiantech.example",
         "", "", "$", 1),
    )


# ----------------------------------------------------------------------------
# Master data
# ----------------------------------------------------------------------------

def _seed_departments():
    ids = {}
    for name, code in DEPARTMENTS:
        did = db.execute("INSERT INTO departments (name, code, is_active) VALUES (?,?,1)", (name, code))
        ids[name] = did
    return ids


def _seed_designations(dept_ids):
    ids = {}
    for dept_name, titles in DESIGNATIONS.items():
        ids[dept_name] = []
        for i, title in enumerate(titles):
            level = ["Junior", "Mid", "Senior"][min(i, 2)]
            did = db.execute(
                "INSERT INTO designations (title, department_id, level, is_active) VALUES (?,?,?,1)",
                (title, dept_ids[dept_name], level),
            )
            ids[dept_name].append(did)
    return ids


def _seed_locations():
    ids = []
    for name, address, city, state, country, pincode in LOCATIONS:
        lid = db.execute(
            "INSERT INTO locations (name, address, city, state, country, pincode, is_active) VALUES (?,?,?,?,?,?,1)",
            (name, address, city, state, country, pincode),
        )
        ids.append(lid)
    return ids


def _seed_shifts():
    ids = []
    for name, start, end, brk, grace in SHIFTS:
        sid = db.execute(
            "INSERT INTO shifts (name, start_time, end_time, break_minutes, grace_minutes, is_active) VALUES (?,?,?,?,?,1)",
            (name, start, end, brk, grace),
        )
        ids.append(sid)
    return ids


def _seed_leave_types():
    ids = {}
    for name, code, days, paid, carry in LEAVE_TYPES:
        lid = db.execute(
            "INSERT INTO leave_types (name, code, days_per_year, is_paid, carry_forward, is_active) VALUES (?,?,?,?,?,1)",
            (name, code, days, paid, carry),
        )
        ids[code] = lid
    return ids


def _seed_holidays(location_ids):
    year = TODAY.year
    for name, mmdd in HOLIDAYS:
        db.execute(
            "INSERT INTO holidays (name, holiday_date, location_id, is_optional) VALUES (?,?,NULL,0)",
            (name, f"{year}-{mmdd}"),
        )
    # A couple of holidays coming up soon, for the dashboard "Upcoming Holidays" widget
    db.execute("INSERT INTO holidays (name, holiday_date) VALUES (?,?)",
               ("Company Foundation Day", (TODAY + timedelta(days=6)).isoformat()))
    db.execute("INSERT INTO holidays (name, holiday_date) VALUES (?,?)",
               ("Regional Festival Holiday", (TODAY + timedelta(days=13)).isoformat()))


def _seed_claim_types():
    ids = {}
    for name, category, max_amt in CLAIM_TYPES:
        cid = db.execute("INSERT INTO claim_types (name, category, max_amount, is_active) VALUES (?,?,?,1)", (name, category, max_amt))
        ids[name] = cid
    return ids


def _seed_document_types():
    ids = {}
    for name, category, requires_expiry in DOCUMENT_TYPES:
        did = db.execute("INSERT INTO document_types (name, category, requires_expiry) VALUES (?,?,?)", (name, category, requires_expiry))
        ids[name] = did
    return ids


def _seed_courses():
    ids = []
    for title, category, hours, mode in COURSES:
        code = db.next_sequence("COURSE", "CRS", 4)
        cid = db.execute(
            "INSERT INTO courses (course_code, title, description, category, duration_hours, trainer_name, delivery_mode, is_active) VALUES (?,?,?,?,?,?,?,1)",
            (code, title, f"A comprehensive course on {title.lower()}.", category, hours, "Internal L&D Team", mode),
        )
        ids.append(cid)
    return ids


# ----------------------------------------------------------------------------
# Employees
# ----------------------------------------------------------------------------

def _seed_employees(dept_ids, designation_ids, location_ids):
    names = _used_names()
    employees = []  # list of dicts: id, dept, first, last, ...
    dept_names = list(dept_ids.keys())

    # figure out how many employees per department (weighted so Engineering/Sales are bigger)
    weights = {"Human Resources": 5, "Engineering": 14, "Sales": 10, "Marketing": 5,
               "Finance & Accounts": 6, "Operations": 6, "Customer Support": 8, "Information Technology": 6}
    total_target = sum(weights.values())  # 60

    idx = 0
    dept_heads = {}  # dept_name -> employee_id (most senior designation in that dept)

    for dept_name in dept_names:
        count = weights[dept_name]
        desig_ids = designation_ids[dept_name]
        for i in range(count):
            first, last = names[idx]
            idx += 1
            gender = random.choice(["Male", "Female"])
            # spread joining dates over the last 6 years, weighted toward more recent
            days_ago = int(random.triangular(10, 2200, 400))
            doj = TODAY - timedelta(days=days_ago)
            dob_year = TODAY.year - random.randint(24, 58)
            dob_month = random.randint(1, 12)
            dob_day = random.randint(1, 28)
            dob = date(dob_year, dob_month, dob_day)
            # last person added per department (i == count-1) gets the most senior designation -> dept head
            desig_id = desig_ids[-1] if i == 0 else desig_ids[min(i % len(desig_ids), len(desig_ids) - 1)]
            if i == 0:
                desig_id = desig_ids[-1]  # first hire in our loop = the senior/head role
            employment_status = "Active"
            employee_code = db.next_sequence("EMPLOYEE", "EMP", 4)
            eid = db.execute(
                """INSERT INTO employees (employee_code, first_name, last_name, gender, dob, marital_status, blood_group,
                     personal_email, personal_phone, emergency_contact_name, emergency_contact_phone,
                     department_id, designation_id, location_id, reporting_manager_id, employment_type, employment_status,
                     date_of_joining, work_email, work_phone, current_address, permanent_address, city, state, country, pincode,
                     bank_name, bank_account_no, bank_ifsc, pan_number, aadhaar_number)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (employee_code, first, last, gender, dob.isoformat(), random.choice(["Single", "Married"]),
                 random.choice(["A+", "B+", "O+", "AB+", "O-"]),
                 f"{first.lower()}.{last.lower()}@personalmail.example", f"+1-555-{random.randint(1000,9999)}",
                 f"{random.choice(FIRST_NAMES)} {last}", f"+1-555-{random.randint(1000,9999)}",
                 dept_ids[dept_name], desig_id, random.choice(location_ids), None, "Full-time", employment_status,
                 doj.isoformat(), f"{first.lower()}.{last.lower()}@meridiantech.example", f"+1-512-555-{random.randint(1000,9999)}",
                 f"{random.randint(100,999)} Main St, Apt {random.randint(1,50)}", f"{random.randint(100,999)} Main St",
                 random.choice(["Austin", "Chicago", "Denver"]), random.choice(["TX", "IL", "CO"]), "USA",
                 f"{random.randint(10000,99999)}",
                 random.choice(["Chase Bank", "Bank of America", "Wells Fargo", "Citibank"]),
                 f"{random.randint(10**9,10**10-1)}", f"BANK{random.randint(1000,9999)}",
                 f"PAN{random.randint(100000,999999)}", f"{random.randint(10**11,10**12-1)}"),
            )
            employees.append({"id": eid, "dept": dept_name, "first": first, "last": last, "designation_id": desig_id,
                               "is_head": i == 0, "dob": dob, "doj": doj})
            if i == 0:
                dept_heads[dept_name] = eid

    # Wire up reporting managers: dept head -> reports to the HR dept head (acting as overall CEO stand-in
    # is avoided; instead make an Engineering head the overall lead) ; everyone else -> their dept head
    top_leader = dept_heads.get("Human Resources")
    for dept_name, head_id in dept_heads.items():
        if head_id != top_leader:
            db.execute("UPDATE employees SET reporting_manager_id=? WHERE id=?", (top_leader, head_id))
    for emp in employees:
        if not emp["is_head"]:
            db.execute("UPDATE employees SET reporting_manager_id=? WHERE id=?", (dept_heads[emp["dept"]], emp["id"]))
        db.execute("UPDATE departments SET head_employee_id=? WHERE name=?", (dept_heads[emp["dept"]], emp["dept"])) if emp["is_head"] else None

    # A few upcoming birthdays / work anniversaries within the next 2 weeks, for the dashboard widgets
    soon_targets = random.sample(employees, min(4, len(employees)))
    for i, emp in enumerate(soon_targets[:2]):
        soon = TODAY + timedelta(days=2 + i * 4)
        db.execute("UPDATE employees SET dob=? WHERE id=?",
                   (date(emp["dob"].year, soon.month, soon.day).isoformat(), emp["id"]))
    for i, emp in enumerate(soon_targets[2:4]):
        soon = TODAY + timedelta(days=3 + i * 5)
        years_ago = random.randint(1, 5)
        anniv_date = date(TODAY.year - years_ago, soon.month, soon.day)
        db.execute("UPDATE employees SET date_of_joining=? WHERE id=?", (anniv_date.isoformat(), emp["id"]))

    # A couple of very recent joiners (this month) for "New Joiners" KPI
    for emp in random.sample(employees, 3):
        recent = TODAY - timedelta(days=random.randint(1, 20))
        db.execute("UPDATE employees SET date_of_joining=? WHERE id=?", (recent.isoformat(), emp["id"]))

    # A handful of Resigned/Terminated employees for attrition reporting
    for emp in random.sample(employees, 4):
        status = random.choice(["Resigned", "Terminated"])
        exit_date = TODAY - timedelta(days=random.randint(5, 300))
        db.execute("UPDATE employees SET employment_status=?, date_of_exit=? WHERE id=?", (status, exit_date.isoformat(), emp["id"]))
        emp["employment_status"] = status

    return employees


# ----------------------------------------------------------------------------
# Users
# ----------------------------------------------------------------------------

def _seed_users(role_ids, employees, dept_ids):
    users_by_employee = {}
    active_employees = [e for e in employees if e.get("employment_status", "Active") == "Active"]

    def link_employee_for(dept_name):
        if dept_name == "__random__":
            return random.choice(active_employees)
        candidates = [e for e in active_employees if e["dept"] == dept_name and e["is_head"]]
        return candidates[0] if candidates else random.choice(active_employees)

    for username, role_name, full_name, dept_link in USER_DEFS:
        employee_id = None
        if dept_link:
            emp = link_employee_for(dept_link)
            employee_id = emp["id"]
            if not full_name:
                full_name = f"{emp['first']} {emp['last']}"
        uid = db.execute(
            "INSERT INTO users (username, password_hash, full_name, email, phone, role_id, employee_id, is_active) VALUES (?,?,?,?,?,?,?,1)",
            (username, PASSWORD_HASH, full_name, f"{username}@meridiantech.example", f"+1-555-{random.randint(1000,9999)}",
             role_ids[role_name], employee_id),
        )
        if employee_id:
            users_by_employee[employee_id] = uid

    # Give every department head a login (Department Manager role) so approval/notification chains work end-to-end
    dept_heads = [e for e in employees if e["is_head"]]
    for emp in dept_heads:
        if emp["id"] in users_by_employee:
            continue
        username = f"{emp['first'].lower()}.{emp['last'].lower()}"
        uid = db.execute(
            "INSERT INTO users (username, password_hash, full_name, email, role_id, employee_id, is_active) VALUES (?,?,?,?,?,?,1)",
            (username, PASSWORD_HASH, f"{emp['first']} {emp['last']}", f"{username}@meridiantech.example",
             role_ids["Department Manager"], emp["id"]),
        )
        users_by_employee[emp["id"]] = uid

    # Give ~15 more random active employees a basic Employee-role login for realistic self-service data
    remaining = [e for e in active_employees if e["id"] not in users_by_employee]
    for emp in random.sample(remaining, min(15, len(remaining))):
        username = f"{emp['first'].lower()}.{emp['last'].lower()}{emp['id']}"
        uid = db.execute(
            "INSERT INTO users (username, password_hash, full_name, email, role_id, employee_id, is_active) VALUES (?,?,?,?,?,?,1)",
            (username, PASSWORD_HASH, f"{emp['first']} {emp['last']}", f"{username}@meridiantech.example",
             role_ids["Employee"], emp["id"]),
        )
        users_by_employee[emp["id"]] = uid

    return users_by_employee


def _user_for_employee(users_by_employee, employee_id):
    uid = users_by_employee.get(employee_id)
    if uid:
        return uid
    row = db.query("SELECT id FROM users WHERE employee_id=?", (employee_id,), one=True)
    return row["id"] if row else None


# ----------------------------------------------------------------------------
# Shifts / salary structures
# ----------------------------------------------------------------------------

def _seed_employee_shifts(employees, shift_ids):
    for emp in employees:
        shift_id = shift_ids[0] if random.random() < 0.85 else random.choice(shift_ids[1:])
        db.execute("INSERT INTO employee_shifts (employee_id, shift_id, effective_from) VALUES (?,?,?)",
                   (emp["id"], shift_id, emp["doj"].isoformat()))


def _seed_salary_structures(employees):
    for emp in employees:
        if emp.get("employment_status", "Active") != "Active":
            continue
        basic = random.randint(3000, 9000)
        hra = round(basic * 0.4)
        conveyance = random.randint(150, 300)
        medical = random.randint(100, 250)
        special = random.randint(300, 1200)
        other = random.randint(0, 300)
        db.execute(
            """INSERT INTO salary_structures (employee_id, effective_from, basic, hra, conveyance, medical,
                 special_allowance, other_allowance, pf_employee_pct, esi_employee_pct, professional_tax,
                 income_tax_monthly, is_active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (emp["id"], emp["doj"].isoformat(), basic, hra, conveyance, medical, special, other,
             12, 0.75, 200, round((basic + hra) * 0.04)),
        )


# ----------------------------------------------------------------------------
# Attendance
# ----------------------------------------------------------------------------

def _seed_attendance(employees):
    days_back = 45
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    for emp in active:
        for d in range(days_back, -1, -1):
            day = TODAY - timedelta(days=d)
            if day < emp["doj"]:
                continue
            weekday = day.weekday()
            if weekday >= 5:
                db.execute("INSERT OR IGNORE INTO attendance (employee_id, date, status) VALUES (?,?,'Week Off')",
                           (emp["id"], day.isoformat()))
                continue
            roll = random.random()
            if roll < 0.03:
                status, check_in, check_out, late, work_hours = "Absent", None, None, 0, 0
            elif roll < 0.06:
                status, check_in, check_out, late, work_hours = "On Leave", None, None, 0, 0
            elif roll < 0.14:
                status, check_in, check_out, late, work_hours = "Present", "09:35", "18:10", 35, 8.0
            elif roll < 0.20:
                status, check_in, check_out, late, work_hours = "Half Day", "09:00", "13:30", 0, 4.5
            else:
                status, check_in, check_out, late, work_hours = "Present", "09:02", "18:15", 0, 8.5
            db.execute(
                "INSERT OR IGNORE INTO attendance (employee_id, date, check_in, check_out, status, late_minutes, work_hours, source) VALUES (?,?,?,?,?,?,?,'Manual')",
                (emp["id"], day.isoformat(), check_in, check_out, status, late, work_hours),
            )


def _seed_regularization(employees, users_by_employee):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    sample = random.sample(active, min(6, len(active)))
    statuses = ["Pending", "Pending", "Approved", "Approved", "Rejected", "Approved"]
    for emp, status in zip(sample, statuses):
        req_date = TODAY - timedelta(days=random.randint(1, 20))
        approver = None
        approved_at = None
        if status != "Pending":
            mgr_row = db.query("SELECT reporting_manager_id FROM employees WHERE id=?", (emp["id"],), one=True)
            approver = _user_for_employee(users_by_employee, mgr_row["reporting_manager_id"]) if mgr_row and mgr_row["reporting_manager_id"] else None
            approved_at = datetime.now().isoformat(timespec="seconds")
        db.execute(
            """INSERT INTO attendance_regularization (employee_id, attendance_date, requested_check_in, requested_check_out,
                 reason, status, approver_id, approved_at) VALUES (?,?,?,?,?,?,?,?)""",
            (emp["id"], req_date.isoformat(), "09:05", "18:20", "Forgot to punch in due to a system issue.",
             status, approver, approved_at),
        )


# ----------------------------------------------------------------------------
# Leave
# ----------------------------------------------------------------------------

def _seed_leave(employees, leave_type_ids, users_by_employee):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    year = TODAY.year
    type_rows = {code: lid for code, lid in leave_type_ids.items()}
    days_per_year = {code: dpy for (name, code, dpy, paid, carry) in LEAVE_TYPES}

    for emp in active:
        for code, lid in type_rows.items():
            allocated = days_per_year[code]
            used = round(random.uniform(0, allocated * 0.4), 1)
            db.execute(
                "INSERT INTO leave_balances (employee_id, leave_type_id, year, allocated, used, balance) VALUES (?,?,?,?,?,?)",
                (emp["id"], lid, year, allocated, used, round(allocated - used, 1)),
            )

    statuses_cycle = ["Approved", "Approved", "Pending", "Pending", "Rejected", "Cancelled", "Approved"]
    sample = random.sample(active, min(22, len(active)))
    for i, emp in enumerate(sample):
        code = random.choice(["CL", "SL", "EL"])
        lid = type_rows[code]
        status = statuses_cycle[i % len(statuses_cycle)]
        if status == "Pending":
            start = TODAY + timedelta(days=random.randint(1, 15))
        else:
            start = TODAY - timedelta(days=random.randint(1, 40))
        span = random.randint(1, 4)
        end = start + timedelta(days=span - 1)
        req_number = db.next_sequence("LEAVE", "LV", 5)
        mgr_row = db.query("SELECT reporting_manager_id FROM employees WHERE id=?", (emp["id"],), one=True)
        approver = _user_for_employee(users_by_employee, mgr_row["reporting_manager_id"]) if mgr_row and mgr_row["reporting_manager_id"] else None
        approved_at = datetime.now().isoformat(timespec="seconds") if status in ("Approved", "Rejected") else None
        db.execute(
            """INSERT INTO leave_requests (request_number, employee_id, leave_type_id, from_date, to_date, days,
                 reason, approver_id, status, approved_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (req_number, emp["id"], lid, start.isoformat(), end.isoformat(), span,
             "Personal time off.", approver if status != "Pending" else None, status, approved_at),
        )
        if status == "Approved":
            row = db.query("SELECT allocated, used FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
                            (emp["id"], lid, year), one=True)
            if row:
                new_used = row["used"] + span
                db.execute("UPDATE leave_balances SET used=?, balance=? WHERE employee_id=? AND leave_type_id=? AND year=?",
                           (new_used, row["allocated"] - new_used, emp["id"], lid, year))


# ----------------------------------------------------------------------------
# Payroll
# ----------------------------------------------------------------------------

def _seed_payroll(employees):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    months_back = [2, 1]  # two fully processed past months
    cur = TODAY.replace(day=1)
    for m in months_back:
        period = _shift_month(cur, -m)
        _generate_payroll_run(active, period.month, period.year, process=True)
    # current month draft
    _generate_payroll_run(active, cur.month, cur.year, process=False)


def _shift_month(d, delta):
    month = d.month - 1 + delta
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _generate_payroll_run(active_employees, month, year, process):
    run_number = db.next_sequence("PAYROLL", "PR", 5)
    run_id = db.execute(
        "INSERT INTO payroll_runs (run_number, period_month, period_year, status) VALUES (?,?,?, 'Draft')",
        (run_number, month, year),
    )
    total_gross = total_ded = total_net = 0
    for emp in active_employees:
        structure = db.query("SELECT * FROM salary_structures WHERE employee_id=? AND is_active=1", (emp["id"],), one=True)
        if not structure:
            continue
        gross = sum([structure["basic"], structure["hra"], structure["conveyance"], structure["medical"],
                     structure["special_allowance"], structure["other_allowance"]])
        pf = structure["basic"] * structure["pf_employee_pct"] / 100
        esi = gross * structure["esi_employee_pct"] / 100 if gross <= 21000 else 0
        ded = pf + esi + structure["professional_tax"] + structure["income_tax_monthly"]
        net = gross - ded
        db.execute(
            """INSERT INTO payslips (payroll_run_id, employee_id, basic, hra, conveyance, medical, special_allowance,
                 other_allowance, gross_earnings, pf_deduction, esi_deduction, professional_tax, income_tax,
                 total_deductions, net_pay, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, emp["id"], structure["basic"], structure["hra"], structure["conveyance"], structure["medical"],
             structure["special_allowance"], structure["other_allowance"], gross, pf, esi,
             structure["professional_tax"], structure["income_tax_monthly"], ded, net,
             "Processed" if process else "Generated"),
        )
        total_gross += gross
        total_ded += ded
        total_net += net
    status = "Processed" if process else "Draft"
    processed_at = datetime.now().isoformat(timespec="seconds") if process else None
    db.execute(
        "UPDATE payroll_runs SET total_gross=?, total_deductions=?, total_net=?, status=?, processed_at=? WHERE id=?",
        (total_gross, total_ded, total_net, status, processed_at, run_id),
    )


def _seed_loans(employees):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    for emp in random.sample(active, min(5, len(active))):
        amount = random.choice([1000, 2000, 3000, 5000])
        installment = round(amount / random.choice([6, 10, 12]))
        remaining = amount - installment * random.randint(1, 3)
        db.execute(
            "INSERT INTO loans (employee_id, loan_type, amount, monthly_installment, start_date, remaining_balance, status) VALUES (?,?,?,?,?,?,'Active')",
            (emp["id"], random.choice(["Personal Loan", "Salary Advance", "Emergency Loan"]), amount, installment,
             (TODAY - timedelta(days=90)).isoformat(), max(remaining, 0)),
        )


# ----------------------------------------------------------------------------
# Recruitment
# ----------------------------------------------------------------------------

STAGES = ["Applied", "Screening", "Shortlisted", "Interview", "Technical Interview",
          "HR Interview", "Selected", "Offer", "Joined", "Rejected"]


def _seed_recruitment(dept_ids, designation_ids, location_ids):
    req_statuses = ["Open", "Open", "Open", "On Hold", "Closed", "Closed", "Open", "Cancelled"]
    dept_names = list(dept_ids.keys())
    requisitions = []
    for i in range(8):
        dept_name = dept_names[i % len(dept_names)]
        desig_id = designation_ids[dept_name][0]
        req_number = db.next_sequence("REQUISITION", "REQ", 4)
        rid = db.execute(
            """INSERT INTO job_requisitions (requisition_number, title, department_id, designation_id, location_id,
                 num_openings, employment_type, experience_required, description, status)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (req_number, f"{DESIGNATIONS[dept_name][0]} - {dept_name}", dept_ids[dept_name], desig_id,
             random.choice(location_ids), random.randint(1, 3), "Full-time", f"{random.randint(1,6)}+ years",
             "Great opportunity to join a growing team.", req_statuses[i]),
        )
        requisitions.append(rid)

    candidate_first_last = _used_names()
    for i in range(28):
        first, last = candidate_first_last[i + 200]
        code = db.next_sequence("CANDIDATE", "CAND", 5)
        cid = db.execute(
            """INSERT INTO candidates (candidate_code, full_name, email, phone, total_experience_years, current_company,
                 current_designation, current_salary, expected_salary, notice_period_days, qualification, skills, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (code, f"{first} {last}", f"{first.lower()}.{last.lower()}@candidatemail.example",
             f"+1-555-{random.randint(1000,9999)}", round(random.uniform(0.5, 10), 1),
             random.choice(["Acme Corp", "Globex Inc", "Initech", "Umbrella LLC", "Stark Industries", ""]),
             random.choice(["Software Engineer", "Sales Executive", "Analyst", "Coordinator"]),
             random.randint(3000, 8000), random.randint(3500, 9000), random.choice([0, 15, 30, 60, 90]),
             random.choice(["B.Tech", "MBA", "B.Com", "B.Sc", "M.Tech"]),
             "Communication, Teamwork, " + random.choice(["Python", "Sales", "Excel", "SQL", "Marketing"]),
             random.choice(["Referral", "Job Portal", "LinkedIn", "Campus", "Agency"])),
        )
        req_id = requisitions[i % len(requisitions)]
        stage = STAGES[i % len(STAGES)]
        app_id = db.execute(
            "INSERT INTO applications (requisition_id, candidate_id, stage, applied_date) VALUES (?,?,?,?)",
            (req_id, cid, stage, (TODAY - timedelta(days=random.randint(1, 60))).isoformat()),
        )
        if stage in ("Interview", "Technical Interview", "HR Interview", "Selected", "Offer", "Joined"):
            db.execute(
                """INSERT INTO interviews (application_id, round_name, scheduled_at, interviewer_name, mode, feedback, rating, recommendation)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (app_id, "Round 1 - Technical", (TODAY - timedelta(days=random.randint(1, 30))).isoformat() + " 10:00",
                 random.choice(["Jordan Blake", "Taylor Chen", "Priya Nair"]), "Video",
                 "Solid communication and technical fundamentals.", random.randint(3, 5), "Selected"),
            )
        if stage in ("Offer", "Joined"):
            db.execute(
                "INSERT INTO offers (application_id, offer_date, designation_id, ctc, joining_date, status) VALUES (?,?,?,?,?,?)",
                (app_id, (TODAY - timedelta(days=random.randint(1, 20))).isoformat(),
                 designation_ids[req_dept_lookup(req_id, dept_ids)][0] if False else None,
                 random.randint(4000, 9000) * 12, (TODAY + timedelta(days=random.randint(5, 30))).isoformat(),
                 "Accepted" if stage == "Joined" else "Sent"),
            )


def req_dept_lookup(req_id, dept_ids):
    return list(dept_ids.keys())[0]


# ----------------------------------------------------------------------------
# Performance
# ----------------------------------------------------------------------------

def _seed_performance(employees):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    prev_cycle_id = db.execute(
        "INSERT INTO appraisal_cycles (name, start_date, end_date, status) VALUES (?,?,?, 'Completed')",
        (f"H1 {TODAY.year} Review", date(TODAY.year, 1, 1).isoformat(), date(TODAY.year, 6, 30).isoformat()),
    )
    cur_cycle_id = db.execute(
        "INSERT INTO appraisal_cycles (name, start_date, end_date, status) VALUES (?,?,?, 'In Progress')",
        (f"H2 {TODAY.year} Review", date(TODAY.year, 7, 1).isoformat(), date(TODAY.year, 12, 31).isoformat()),
    )

    appraisal_statuses = ["Pending", "Self Review", "Manager Review", "Completed", "Completed"]
    for i, emp in enumerate(active):
        # previous (completed) cycle: everyone has a completed appraisal
        rating = round(random.uniform(2.5, 5.0), 1)
        db.execute(
            """INSERT INTO appraisals (cycle_id, employee_id, self_review, manager_review, final_rating,
                 promotion_recommended, increment_recommended_pct, status, completed_at)
               VALUES (?,?,?,?,?,?,?, 'Completed', ?)""",
            (prev_cycle_id, emp["id"], "Met most of my goals this half.", "Solid performance, keep it up.",
             rating, 1 if rating > 4.5 else 0, round(random.uniform(0, 10), 1),
             datetime.now().isoformat(timespec="seconds")),
        )
        for g_i in range(random.randint(2, 3)):
            db.execute(
                """INSERT INTO goals (cycle_id, employee_id, title, kra, weight_pct, target, status, self_rating, manager_rating)
                   VALUES (?,?,?,?,?,?, 'Completed', ?, ?)""",
                (prev_cycle_id, emp["id"], f"Goal {g_i+1}: deliver key initiative", "Execution", round(100/3, 1),
                 "Complete on schedule", random.randint(3,5), random.randint(3,5)),
            )

        # current (in-progress) cycle: varied statuses + goals
        status = appraisal_statuses[i % len(appraisal_statuses)]
        self_review = "Making good progress on my goals." if status != "Pending" else None
        manager_review = "On track, good communication." if status == "Completed" else None
        final_rating = round(random.uniform(3.0, 5.0), 1) if status == "Completed" else None
        db.execute(
            """INSERT INTO appraisals (cycle_id, employee_id, self_review, manager_review, final_rating, status)
               VALUES (?,?,?,?,?,?)""",
            (cur_cycle_id, emp["id"], self_review, manager_review, final_rating, status),
        )
        for g_i in range(random.randint(2, 4)):
            g_status = random.choice(["Not Started", "In Progress", "Completed"])
            db.execute(
                """INSERT INTO goals (cycle_id, employee_id, title, kra, weight_pct, target, status)
                   VALUES (?,?,?,?,?,?,?)""",
                (cur_cycle_id, emp["id"], f"H2 Goal {g_i+1}", random.choice(["Execution", "Quality", "Innovation", "Collaboration"]),
                 round(100/3, 1), "Deliver measurable outcome", g_status),
            )


# ----------------------------------------------------------------------------
# Engagement
# ----------------------------------------------------------------------------

def _seed_engagement(employees, users_by_employee):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]

    closed_survey = db.execute(
        "INSERT INTO surveys (title, description, type, start_date, end_date, status, created_by) VALUES (?,?,?,?,?, 'Closed', ?)",
        ("Q2 Employee Pulse Survey", "How are you feeling about work this quarter?", "Pulse",
         (TODAY - timedelta(days=60)).isoformat(), (TODAY - timedelta(days=30)).isoformat(), 1),
    )
    q1 = db.execute("INSERT INTO survey_questions (survey_id, question_text, question_type) VALUES (?,?, 'Rating')",
                    (closed_survey, "How satisfied are you with your work-life balance?"))
    q2 = db.execute("INSERT INTO survey_questions (survey_id, question_text, question_type) VALUES (?,?, 'Rating')",
                    (closed_survey, "How likely are you to recommend this company as a great place to work?"))
    for emp in random.sample(active, min(30, len(active))):
        db.execute("INSERT INTO survey_responses (survey_id, question_id, employee_id, answer_rating) VALUES (?,?,?,?)",
                   (closed_survey, q1, emp["id"], random.randint(3, 5)))
        db.execute("INSERT INTO survey_responses (survey_id, question_id, employee_id, answer_rating) VALUES (?,?,?,?)",
                   (closed_survey, q2, emp["id"], random.randint(2, 5)))

    active_survey = db.execute(
        "INSERT INTO surveys (title, description, type, start_date, end_date, status, created_by) VALUES (?,?,?,?,?, 'Active', ?)",
        ("Q3 Engagement Check-in", "Quick check-in on how things are going.", "Pulse",
         (TODAY - timedelta(days=5)).isoformat(), (TODAY + timedelta(days=25)).isoformat(), 1),
    )
    db.execute("INSERT INTO survey_questions (survey_id, question_text, question_type) VALUES (?,?, 'Rating')",
               (active_survey, "How supported do you feel by your manager?"))
    db.execute("INSERT INTO survey_questions (survey_id, question_text, question_type) VALUES (?,?, 'Text')",
               (active_survey, "What's one thing we could do better?"))

    categories = ["Award", "Kudos", "Milestone"]
    titles = ["Above and Beyond", "Team Player of the Month", "5 Year Work Anniversary", "Great Customer Save",
              "Outstanding Q2 Performance", "Innovation Spotlight"]
    for emp in random.sample(active, min(15, len(active))):
        db.execute(
            "INSERT INTO recognitions (employee_id, given_by, category, title, message) VALUES (?,?,?,?,?)",
            (emp["id"], 1, random.choice(categories), random.choice(titles),
             f"Great work, {emp['first']}! Really appreciate your contribution."),
        )


# ----------------------------------------------------------------------------
# Learning
# ----------------------------------------------------------------------------

def _seed_learning(course_ids, location_ids, employees):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    for i, course_id in enumerate(course_ids):
        for s in range(2):
            session_date = TODAY - timedelta(days=random.randint(-20, 60)) if s == 0 else TODAY + timedelta(days=random.randint(5, 30))
            status = "Completed" if session_date < TODAY else "Scheduled"
            sid = db.execute(
                """INSERT INTO training_sessions (course_id, session_date, start_time, end_time, location_id, trainer_name, capacity, status)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (course_id, session_date.isoformat(), "10:00", "13:00", random.choice(location_ids),
                 "Internal L&D Team", 25, status),
            )
            attendees = random.sample(active, min(random.randint(5, 15), len(active)))
            for emp in attendees:
                if status == "Completed":
                    att_status = random.choice(["Attended", "Completed", "Absent"])
                    score = random.randint(60, 100) if att_status in ("Attended", "Completed") else None
                    cert = 1 if att_status == "Completed" and score and score >= 70 else 0
                else:
                    att_status, score, cert = "Enrolled", None, 0
                db.execute(
                    """INSERT OR IGNORE INTO training_enrollments (session_id, employee_id, attendance_status, assessment_score, certificate_issued, feedback_rating)
                       VALUES (?,?,?,?,?,?)""",
                    (sid, emp["id"], att_status, score, cert, random.randint(3, 5) if status == "Completed" else None),
                )

    skills = ["Python", "Excel", "Public Speaking", "Project Management", "Sales Negotiation", "SQL", "Leadership"]
    for emp in random.sample(active, min(25, len(active))):
        for skill in random.sample(skills, random.randint(1, 3)):
            db.execute(
                "INSERT INTO skill_matrix (employee_id, skill_name, proficiency_level) VALUES (?,?,?)",
                (emp["id"], skill, random.choice(["Beginner", "Intermediate", "Advanced", "Expert"])),
            )


# ----------------------------------------------------------------------------
# Field visits
# ----------------------------------------------------------------------------

def _seed_field_visits(employees):
    field_eligible = [e for e in employees if e["dept"] in ("Sales", "Customer Support", "Operations")
                      and e.get("employment_status", "Active") == "Active"]
    customers = ["Acme Retail Group", "Globex Manufacturing", "Initech Solutions", "Stark Logistics",
                 "Wayne Health Systems", "Umbrella Distribution", "Pinnacle Foods", "Horizon Utilities"]
    for i in range(35):
        emp = random.choice(field_eligible) if field_eligible else random.choice(employees)
        visit_date = TODAY - timedelta(days=random.randint(0, 20))
        purpose = random.choice(["Site inspection", "Customer meeting", "Delivery follow-up", "Installation support", "Account review"])
        if visit_date == TODAY and i % 3 == 0:
            status, check_in, check_out = "In Progress", "09:30", None
        elif visit_date < TODAY:
            status, check_in, check_out = "Completed", "09:30", "12:45"
        else:
            status, check_in, check_out = "Planned", None, None
        db.execute(
            """INSERT INTO field_visits (employee_id, visit_date, customer_name, purpose, check_in_time, check_out_time,
                 check_in_location, check_out_location, travel_distance_km, status)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (emp["id"], visit_date.isoformat(), random.choice(customers), purpose, check_in, check_out,
             "Customer Site - Front Gate" if check_in else None, "Customer Site - Front Gate" if check_out else None,
             round(random.uniform(3, 45), 1) if status != "Planned" else None, status),
        )


# ----------------------------------------------------------------------------
# Claims
# ----------------------------------------------------------------------------

def _seed_claims(employees, claim_type_ids, users_by_employee):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    statuses_cycle = ["Submitted", "Manager Approved", "Finance Verified", "Approved", "Paid", "Paid", "Rejected"]
    type_names = list(claim_type_ids.keys())
    sample = random.sample(active, min(20, len(active)))
    for i, emp in enumerate(sample):
        claim_type = random.choice(type_names)
        status = statuses_cycle[i % len(statuses_cycle)]
        expense_date = TODAY - timedelta(days=random.randint(1, 45))
        claim_number = db.next_sequence("CLAIM", "CLM", 5)
        mgr_row = db.query("SELECT reporting_manager_id FROM employees WHERE id=?", (emp["id"],), one=True)
        manager_id = _user_for_employee(users_by_employee, mgr_row["reporting_manager_id"]) if mgr_row and mgr_row["reporting_manager_id"] else None
        approved_at = datetime.now().isoformat(timespec="seconds") if status not in ("Submitted",) else None
        paid_at = datetime.now().isoformat(timespec="seconds") if status == "Paid" else None
        db.execute(
            """INSERT INTO expense_claims (claim_number, employee_id, claim_type_id, expense_date, amount, description,
                 project_or_department, status, manager_id, approved_at, paid_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (claim_number, emp["id"], claim_type_ids[claim_type], expense_date.isoformat(),
             round(random.uniform(25, 850), 2), f"{claim_type} expense during business travel.",
             emp["dept"], status, manager_id if status != "Submitted" else None, approved_at, paid_at),
        )


# ----------------------------------------------------------------------------
# HR Documents
# ----------------------------------------------------------------------------

def _seed_documents(employees, doc_type_ids, users_by_employee):
    active = [e for e in employees if e.get("employment_status", "Active") == "Active"]
    # company-wide policy docs
    for name in ["Company Policy Handbook", "Employee Agreement"]:
        db.execute(
            "INSERT INTO hr_documents (employee_id, document_type_id, title, uploaded_by, is_verified) VALUES (NULL,?,?,1,1)",
            (doc_type_ids[name], f"{name} - {TODAY.year} Edition"),
        )
    per_employee_docs = ["Offer Letter", "ID Proof", "Educational Certificate"]
    for emp in random.sample(active, min(25, len(active))):
        for name in random.sample(per_employee_docs, random.randint(1, 3)):
            expiry = None
            if name == "ID Proof":
                expiry = (TODAY + timedelta(days=random.choice([15, 25, 200, 400]))).isoformat()
            db.execute(
                """INSERT INTO hr_documents (employee_id, document_type_id, title, uploaded_by, expiry_date, is_verified)
                   VALUES (?,?,?,?,?,?)""",
                (emp["id"], doc_type_ids[name], f"{emp['first']} {emp['last']} - {name}", 1, expiry, random.choice([0, 1])),
            )


# ----------------------------------------------------------------------------
# CRM
# ----------------------------------------------------------------------------

def _seed_crm(users_by_employee):
    owners = list(users_by_employee.values())[:10] or [1]
    industries = ["Retail", "Manufacturing", "Healthcare", "Logistics", "Technology", "Hospitality", "Finance"]
    customer_names = ["Acme Retail Group", "Globex Manufacturing", "Initech Solutions", "Stark Logistics",
                      "Wayne Health Systems", "Umbrella Distribution", "Pinnacle Foods", "Horizon Utilities",
                      "Vertex Technologies", "Sunrise Hospitality", "Blue Ridge Finance", "Cascade Retailers"]
    customer_ids = []
    for name in customer_names:
        code = db.next_sequence("CUSTOMER", "CUST", 4)
        cid = db.execute(
            "INSERT INTO crm_customers (customer_code, name, industry, phone, email, city, owner_user_id) VALUES (?,?,?,?,?,?,?)",
            (code, name, random.choice(industries), f"+1-555-{random.randint(1000,9999)}",
             f"contact@{name.split()[0].lower()}.example", random.choice(["Austin", "Chicago", "Denver", "New York"]),
             random.choice(owners)),
        )
        customer_ids.append(cid)
        db.execute("INSERT INTO crm_contacts (customer_id, name, designation, phone, email) VALUES (?,?,?,?,?)",
                   (cid, f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}", "Procurement Manager",
                    f"+1-555-{random.randint(1000,9999)}", "contact@example.com"))
        db.execute(
            "INSERT INTO crm_activities (customer_id, activity_type, subject, notes, activity_date, owner_user_id) VALUES (?,?,?,?,?,?)",
            (cid, random.choice(["Call", "Email", "Meeting"]), "Quarterly check-in",
             "Discussed renewal and upcoming needs.", (TODAY - timedelta(days=random.randint(1, 30))).isoformat(),
             random.choice(owners)),
        )

    lead_statuses = ["New", "New", "Contacted", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]
    lead_companies = ["Brightline Foods", "Corestone Materials", "NorthPeak Energy", "Silverline Media",
                      "Trailhead Analytics", "Bluebird Airlines", "Redwood Capital", "Ironclad Security",
                      "Lumen Health", "Cobalt Systems", "Amber Logistics", "Falcon Robotics", "Willowbrook Retail",
                      "Granite Financial", "Skyline Software", "Meadowview Hospitality", "Sterling Insurance",
                      "Quantum Analytics", "Palmetto Foods", "Riverside Manufacturing"]
    for i, company in enumerate(lead_companies):
        status = lead_statuses[i % len(lead_statuses)]
        lead_number = db.next_sequence("LEAD", "LD", 5)
        lid = db.execute(
            """INSERT INTO crm_leads (lead_number, company_name, contact_name, phone, email, source, status,
                 estimated_value, owner_user_id) VALUES (?,?,?,?,?,?,?,?,?)""",
            (lead_number, company, f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
             f"+1-555-{random.randint(1000,9999)}", f"contact@{company.split()[0].lower()}.example",
             random.choice(["Referral", "Website", "Trade Show", "Cold Outreach", "Partner"]), status,
             random.randint(5000, 80000), random.choice(owners)),
        )
        db.execute(
            "INSERT INTO crm_activities (lead_id, activity_type, subject, notes, activity_date, owner_user_id) VALUES (?,?,?,?,?,?)",
            (lid, "Call", "Initial outreach", "Introduced our services and gauged interest.",
             (TODAY - timedelta(days=random.randint(1, 25))).isoformat(), random.choice(owners)),
        )


# ----------------------------------------------------------------------------
# Notifications & audit log
# ----------------------------------------------------------------------------

def _seed_notifications(users_by_employee):
    sample_users = list(users_by_employee.values())[:12] or [1]
    messages = [
        ("Leave request approved", "Your recent leave request has been approved.", "success"),
        ("New recognition received", "You've been recognized by your manager!", "success"),
        ("Payslip available", "Your latest payslip is ready to view.", "info"),
        ("Document expiring soon", "One of your uploaded documents is expiring soon.", "warning"),
        ("Training session scheduled", "A new training session you're enrolled in has been scheduled.", "info"),
    ]
    for uid in sample_users:
        for title, msg, ntype in random.sample(messages, random.randint(1, 3)):
            db.execute("INSERT INTO notifications (user_id, title, message, type, is_read) VALUES (?,?,?,?,?)",
                       (uid, title, msg, ntype, random.choice([0, 0, 1])))


def _seed_audit_log(users_by_employee):
    sample_users = list(users_by_employee.values())[:8] or [1]
    actions = [
        ("create", "employees.employees", "Created a new employee record"),
        ("update", "leave.requests", "Approved a leave request"),
        ("create", "claims.claims", "Submitted a new expense claim"),
        ("update", "recruitment.applications", "Moved a candidate to the next stage"),
        ("create", "engagement.recognitions", "Gave a peer recognition"),
        ("update", "payroll.runs", "Processed a payroll run"),
    ]
    for i in range(25):
        uid = random.choice(sample_users)
        action, entity_type, desc = random.choice(actions)
        db.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id, details, created_at) VALUES (?,?,?,?,?,?)",
            (uid, action, entity_type, random.randint(1, 50), desc,
             (datetime.now() - timedelta(hours=random.randint(1, 400))).isoformat(timespec="seconds")),
        )


if __name__ == "__main__":
    from app import app
    with app.app_context():
        run()
