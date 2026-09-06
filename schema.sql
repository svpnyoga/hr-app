-- ============================================================================
-- Enterprise HR & Workforce Management System — Database Schema (SQLite)
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- CORE / AUTH / RBAC
-- ----------------------------------------------------------------------------

CREATE TABLE roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    is_system INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    module TEXT NOT NULL,
    description TEXT
);

CREATE TABLE role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    role_id INTEGER NOT NULL REFERENCES roles(id),
    employee_id INTEGER REFERENCES employees(id),
    is_active INTEGER NOT NULL DEFAULT 1,
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE sequences (
    code TEXT PRIMARY KEY,
    prefix TEXT NOT NULL,
    pad INTEGER NOT NULL DEFAULT 4,
    next_val INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    details TEXT,
    ip_address TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT,
    type TEXT NOT NULL DEFAULT 'info',
    link TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE company_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    company_name TEXT NOT NULL DEFAULT 'Your Company',
    logo_path TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    pincode TEXT,
    phone TEXT,
    email TEXT,
    website TEXT,
    gstin TEXT,
    pan TEXT,
    currency_symbol TEXT NOT NULL DEFAULT '$',
    fiscal_year_start_month INTEGER NOT NULL DEFAULT 4,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- MASTER DATA
-- ----------------------------------------------------------------------------

CREATE TABLE locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    pincode TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    code TEXT,
    parent_id INTEGER REFERENCES departments(id),
    head_employee_id INTEGER REFERENCES employees(id),
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE designations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    department_id INTEGER REFERENCES departments(id),
    level TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- ----------------------------------------------------------------------------
-- EMPLOYEES
-- ----------------------------------------------------------------------------

CREATE TABLE employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_code TEXT NOT NULL UNIQUE,
    photo_path TEXT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    gender TEXT,
    dob TEXT,
    marital_status TEXT,
    blood_group TEXT,
    personal_email TEXT,
    personal_phone TEXT,
    emergency_contact_name TEXT,
    emergency_contact_phone TEXT,

    department_id INTEGER REFERENCES departments(id),
    designation_id INTEGER REFERENCES designations(id),
    location_id INTEGER REFERENCES locations(id),
    reporting_manager_id INTEGER REFERENCES employees(id),
    employment_type TEXT NOT NULL DEFAULT 'Full-time',
    employment_status TEXT NOT NULL DEFAULT 'Active',
    date_of_joining TEXT,
    date_of_confirmation TEXT,
    date_of_exit TEXT,
    work_email TEXT,
    work_phone TEXT,

    current_address TEXT,
    permanent_address TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    pincode TEXT,

    bank_name TEXT,
    bank_account_no TEXT,
    bank_ifsc TEXT,
    pan_number TEXT,
    aadhaar_number TEXT,
    uan_number TEXT,
    pf_number TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by INTEGER REFERENCES users(id),
    is_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE employee_education (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    degree TEXT NOT NULL,
    institution TEXT,
    field_of_study TEXT,
    start_year INTEGER,
    end_year INTEGER,
    grade TEXT
);

CREATE TABLE employee_experience (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    designation TEXT,
    start_date TEXT,
    end_date TEXT,
    description TEXT
);

CREATE TABLE employee_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,
    title TEXT NOT NULL,
    file_path TEXT,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    expiry_date TEXT,
    is_verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE employee_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    asset_name TEXT NOT NULL,
    asset_tag TEXT,
    issued_date TEXT,
    return_date TEXT,
    condition TEXT,
    remarks TEXT
);

-- ----------------------------------------------------------------------------
-- ATTENDANCE
-- ----------------------------------------------------------------------------

CREATE TABLE shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    break_minutes INTEGER NOT NULL DEFAULT 60,
    grace_minutes INTEGER NOT NULL DEFAULT 10,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE employee_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    shift_id INTEGER NOT NULL REFERENCES shifts(id),
    effective_from TEXT NOT NULL DEFAULT (date('now'))
);

CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    shift_id INTEGER REFERENCES shifts(id),
    check_in TEXT,
    check_out TEXT,
    status TEXT NOT NULL DEFAULT 'Present',
    late_minutes INTEGER NOT NULL DEFAULT 0,
    early_leave_minutes INTEGER NOT NULL DEFAULT 0,
    overtime_minutes INTEGER NOT NULL DEFAULT 0,
    work_hours REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'Manual',
    remarks TEXT,
    UNIQUE(employee_id, date)
);
CREATE INDEX idx_attendance_date ON attendance(date);
CREATE INDEX idx_attendance_employee ON attendance(employee_id);

CREATE TABLE attendance_regularization (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    attendance_date TEXT NOT NULL,
    requested_check_in TEXT,
    requested_check_out TEXT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    approver_id INTEGER REFERENCES users(id),
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- LEAVE
-- ----------------------------------------------------------------------------

CREATE TABLE leave_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    days_per_year REAL NOT NULL DEFAULT 12,
    is_paid INTEGER NOT NULL DEFAULT 1,
    carry_forward INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE leave_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    leave_type_id INTEGER NOT NULL REFERENCES leave_types(id),
    year INTEGER NOT NULL,
    allocated REAL NOT NULL DEFAULT 0,
    used REAL NOT NULL DEFAULT 0,
    balance REAL NOT NULL DEFAULT 0,
    UNIQUE(employee_id, leave_type_id, year)
);

CREATE TABLE leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_number TEXT NOT NULL UNIQUE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    leave_type_id INTEGER NOT NULL REFERENCES leave_types(id),
    from_date TEXT NOT NULL,
    to_date TEXT NOT NULL,
    days REAL NOT NULL,
    reason TEXT,
    document_path TEXT,
    approver_id INTEGER REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'Pending',
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE holidays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    holiday_date TEXT NOT NULL,
    location_id INTEGER REFERENCES locations(id),
    is_optional INTEGER NOT NULL DEFAULT 0
);

-- ----------------------------------------------------------------------------
-- PAYROLL
-- ----------------------------------------------------------------------------

CREATE TABLE salary_structures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    effective_from TEXT NOT NULL,
    basic REAL NOT NULL DEFAULT 0,
    hra REAL NOT NULL DEFAULT 0,
    conveyance REAL NOT NULL DEFAULT 0,
    medical REAL NOT NULL DEFAULT 0,
    special_allowance REAL NOT NULL DEFAULT 0,
    other_allowance REAL NOT NULL DEFAULT 0,
    pf_employee_pct REAL NOT NULL DEFAULT 12,
    esi_employee_pct REAL NOT NULL DEFAULT 0.75,
    professional_tax REAL NOT NULL DEFAULT 200,
    income_tax_monthly REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE payroll_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_number TEXT NOT NULL UNIQUE,
    period_month INTEGER NOT NULL,
    period_year INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft',
    processed_at TEXT,
    processed_by INTEGER REFERENCES users(id),
    total_gross REAL NOT NULL DEFAULT 0,
    total_deductions REAL NOT NULL DEFAULT 0,
    total_net REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(period_month, period_year)
);

CREATE TABLE payslips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payroll_run_id INTEGER NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    basic REAL NOT NULL DEFAULT 0,
    hra REAL NOT NULL DEFAULT 0,
    conveyance REAL NOT NULL DEFAULT 0,
    medical REAL NOT NULL DEFAULT 0,
    special_allowance REAL NOT NULL DEFAULT 0,
    other_allowance REAL NOT NULL DEFAULT 0,
    overtime_amount REAL NOT NULL DEFAULT 0,
    bonus REAL NOT NULL DEFAULT 0,
    gross_earnings REAL NOT NULL DEFAULT 0,
    pf_deduction REAL NOT NULL DEFAULT 0,
    esi_deduction REAL NOT NULL DEFAULT 0,
    professional_tax REAL NOT NULL DEFAULT 0,
    income_tax REAL NOT NULL DEFAULT 0,
    loan_deduction REAL NOT NULL DEFAULT 0,
    other_deduction REAL NOT NULL DEFAULT 0,
    total_deductions REAL NOT NULL DEFAULT 0,
    net_pay REAL NOT NULL DEFAULT 0,
    lop_days REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Generated'
);

CREATE TABLE loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    loan_type TEXT NOT NULL,
    amount REAL NOT NULL,
    monthly_installment REAL NOT NULL,
    start_date TEXT NOT NULL,
    remaining_balance REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'Active'
);

-- ----------------------------------------------------------------------------
-- RECRUITMENT / ATS
-- ----------------------------------------------------------------------------

CREATE TABLE job_requisitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requisition_number TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    department_id INTEGER REFERENCES departments(id),
    designation_id INTEGER REFERENCES designations(id),
    location_id INTEGER REFERENCES locations(id),
    num_openings INTEGER NOT NULL DEFAULT 1,
    employment_type TEXT NOT NULL DEFAULT 'Full-time',
    experience_required TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    requested_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_code TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    resume_path TEXT,
    total_experience_years REAL,
    current_company TEXT,
    current_designation TEXT,
    current_salary REAL,
    expected_salary REAL,
    notice_period_days INTEGER,
    qualification TEXT,
    skills TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requisition_id INTEGER NOT NULL REFERENCES job_requisitions(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'Applied',
    applied_date TEXT NOT NULL DEFAULT (date('now')),
    remarks TEXT,
    rejection_reason TEXT
);

CREATE TABLE interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    round_name TEXT NOT NULL,
    scheduled_at TEXT,
    interviewer_name TEXT,
    mode TEXT NOT NULL DEFAULT 'In-person',
    feedback TEXT,
    rating INTEGER,
    recommendation TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    offer_date TEXT NOT NULL DEFAULT (date('now')),
    designation_id INTEGER REFERENCES designations(id),
    ctc REAL,
    joining_date TEXT,
    status TEXT NOT NULL DEFAULT 'Draft'
);

-- ----------------------------------------------------------------------------
-- PERFORMANCE
-- ----------------------------------------------------------------------------

CREATE TABLE appraisal_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Planning'
);

CREATE TABLE goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL REFERENCES appraisal_cycles(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    kra TEXT,
    weight_pct REAL NOT NULL DEFAULT 0,
    target TEXT,
    status TEXT NOT NULL DEFAULT 'Not Started',
    self_rating INTEGER,
    manager_rating INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE appraisals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL REFERENCES appraisal_cycles(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    self_review TEXT,
    manager_review TEXT,
    final_rating REAL,
    promotion_recommended INTEGER NOT NULL DEFAULT 0,
    increment_recommended_pct REAL,
    status TEXT NOT NULL DEFAULT 'Pending',
    reviewer_id INTEGER REFERENCES users(id),
    completed_at TEXT,
    UNIQUE(cycle_id, employee_id)
);

-- ----------------------------------------------------------------------------
-- ENGAGEMENT
-- ----------------------------------------------------------------------------

CREATE TABLE surveys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    type TEXT NOT NULL DEFAULT 'Pulse',
    start_date TEXT,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'Draft',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE survey_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT 'Rating',
    options TEXT
);

CREATE TABLE survey_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES survey_questions(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    answer_text TEXT,
    answer_rating INTEGER,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE recognitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    given_by INTEGER REFERENCES users(id),
    category TEXT NOT NULL DEFAULT 'Kudos',
    title TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- LEARNING & DEVELOPMENT (LMS)
-- ----------------------------------------------------------------------------

CREATE TABLE courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    duration_hours REAL NOT NULL DEFAULT 1,
    trainer_name TEXT,
    delivery_mode TEXT NOT NULL DEFAULT 'Online',
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE training_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    session_date TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    location_id INTEGER REFERENCES locations(id),
    trainer_name TEXT,
    capacity INTEGER NOT NULL DEFAULT 20,
    status TEXT NOT NULL DEFAULT 'Scheduled'
);

CREATE TABLE training_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    enrollment_date TEXT NOT NULL DEFAULT (date('now')),
    attendance_status TEXT NOT NULL DEFAULT 'Enrolled',
    assessment_score REAL,
    certificate_issued INTEGER NOT NULL DEFAULT 0,
    feedback_rating INTEGER,
    UNIQUE(session_id, employee_id)
);

CREATE TABLE skill_matrix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    proficiency_level TEXT NOT NULL DEFAULT 'Beginner',
    assessed_date TEXT NOT NULL DEFAULT (date('now'))
);

-- ----------------------------------------------------------------------------
-- FIELD TRACKING
-- ----------------------------------------------------------------------------

CREATE TABLE field_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    visit_date TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    purpose TEXT,
    check_in_time TEXT,
    check_out_time TEXT,
    check_in_location TEXT,
    check_out_location TEXT,
    travel_distance_km REAL,
    remarks TEXT,
    photo_path TEXT,
    status TEXT NOT NULL DEFAULT 'Planned'
);

-- ----------------------------------------------------------------------------
-- CLAIMS & EXPENSES
-- ----------------------------------------------------------------------------

CREATE TABLE claim_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT,
    max_amount REAL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE expense_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_number TEXT NOT NULL UNIQUE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    claim_type_id INTEGER NOT NULL REFERENCES claim_types(id),
    expense_date TEXT NOT NULL,
    amount REAL NOT NULL,
    description TEXT,
    receipt_path TEXT,
    project_or_department TEXT,
    status TEXT NOT NULL DEFAULT 'Submitted',
    manager_id INTEGER REFERENCES users(id),
    approved_at TEXT,
    paid_at TEXT,
    remarks TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- HR DOCUMENTS
-- ----------------------------------------------------------------------------

CREATE TABLE document_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT,
    requires_expiry INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE hr_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
    document_type_id INTEGER NOT NULL REFERENCES document_types(id),
    title TEXT NOT NULL,
    file_path TEXT,
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    expiry_date TEXT,
    is_verified INTEGER NOT NULL DEFAULT 0,
    verified_by INTEGER REFERENCES users(id),
    verified_at TEXT
);

-- ----------------------------------------------------------------------------
-- CRM
-- ----------------------------------------------------------------------------

CREATE TABLE crm_customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    industry TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    city TEXT,
    owner_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE crm_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_number TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    source TEXT,
    status TEXT NOT NULL DEFAULT 'New',
    estimated_value REAL,
    owner_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE crm_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES crm_customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    designation TEXT,
    phone TEXT,
    email TEXT
);

CREATE TABLE crm_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER REFERENCES crm_leads(id) ON DELETE CASCADE,
    customer_id INTEGER REFERENCES crm_customers(id) ON DELETE CASCADE,
    activity_type TEXT NOT NULL DEFAULT 'Note',
    subject TEXT,
    notes TEXT,
    activity_date TEXT NOT NULL DEFAULT (date('now')),
    owner_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- INDEXES (frequently filtered columns)
-- ----------------------------------------------------------------------------

CREATE INDEX idx_employees_department ON employees(department_id);
CREATE INDEX idx_employees_status ON employees(employment_status);
CREATE INDEX idx_leave_requests_employee ON leave_requests(employee_id);
CREATE INDEX idx_leave_requests_status ON leave_requests(status);
CREATE INDEX idx_applications_requisition ON applications(requisition_id);
CREATE INDEX idx_expense_claims_employee ON expense_claims(employee_id);
CREATE INDEX idx_expense_claims_status ON expense_claims(status);
CREATE INDEX idx_payslips_run ON payslips(payroll_run_id);
CREATE INDEX idx_notifications_user ON notifications(user_id, is_read);
CREATE INDEX idx_field_visits_employee ON field_visits(employee_id, visit_date);
CREATE INDEX idx_crm_leads_status ON crm_leads(status);
