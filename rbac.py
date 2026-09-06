"""Central catalog of modules/entities/actions used to generate permission
codes, plus the default permission grants for each of the 8 built-in roles.

Convention used throughout the app: the "view" action means "view records
scoped to yourself" (e.g. your own attendance, your own leave requests, your
own payslips) while "view_all" means "view every employee's records". Every
list/detail view in a self-service-capable module MUST check
`has_permission(f"{module}.{entity}.view_all")` and, when false, filter the
query down to `employee_id = g.user["employee_id"]`. The same pattern
applies to "edit" (own record only, where the workflow allows it, e.g.
editing your own draft goal) vs an implicit "edit" combined with
"view_all" for a manager/admin editing anyone's record.
"""

ACTIONS = [
    "view", "view_all", "create", "edit", "delete", "approve", "export", "process",
]

# module -> { entity_key: label }
MODULES = {
    "employees": {"employees": "Employees", "documents": "Employee Documents", "assets": "Employee Assets"},
    "attendance": {"attendance": "Attendance", "regularization": "Attendance Regularization", "shifts": "Shifts"},
    "leave": {"requests": "Leave Requests", "types": "Leave Types", "holidays": "Holiday Calendar"},
    "payroll": {"structures": "Salary Structures", "runs": "Payroll Runs", "payslips": "Payslips", "loans": "Loans"},
    "recruitment": {
        "requisitions": "Job Requisitions", "candidates": "Candidates",
        "applications": "Applications", "interviews": "Interviews", "offers": "Offers",
    },
    "performance": {"cycles": "Appraisal Cycles", "goals": "Goals", "appraisals": "Appraisals"},
    "engagement": {"surveys": "Surveys", "recognitions": "Recognitions"},
    "learning": {"courses": "Courses", "sessions": "Training Sessions", "enrollments": "Enrollments", "skills": "Skill Matrix"},
    "field": {"visits": "Field Visits"},
    "claims": {"claims": "Expense Claims", "types": "Claim Types"},
    "documents": {"documents": "HR Documents", "types": "Document Types"},
    "crm": {"customers": "CRM Customers", "leads": "CRM Leads", "activities": "CRM Activities"},
    "reports": {"reports": "Reports"},
    "admin": {"users": "Users", "roles": "Roles", "settings": "Settings", "masterdata": "Master Data", "audit": "Audit Log"},
}


def all_permission_codes():
    codes = []
    for module, entities in MODULES.items():
        for entity, label in entities.items():
            for action in ACTIONS:
                codes.append((f"{module}.{entity}.{action}", module, entity, action, f"{action.replace('_', ' ').title()} {label}"))
    return codes


# Default permission sets per role, expressed as list of (module, entity, [actions]) or "*" for everything.
ROLE_DEFAULTS = {
    "Super Admin": "*",

    "HR Admin": [
        ("employees", "*", ["view", "view_all", "create", "edit", "delete", "export"]),
        ("attendance", "*", ["view", "view_all", "create", "edit", "approve", "export"]),
        ("leave", "*", ["view", "view_all", "create", "edit", "delete", "approve", "export"]),
        ("payroll", "*", ["view", "view_all", "create", "edit", "process", "export"]),
        ("recruitment", "*", ["view", "view_all", "create", "edit", "delete", "export"]),
        ("performance", "*", ["view", "view_all", "create", "edit", "delete", "export"]),
        ("engagement", "*", ["view", "view_all", "create", "edit", "delete", "export"]),
        ("learning", "*", ["view", "view_all", "create", "edit", "delete", "export"]),
        ("field", "*", ["view", "view_all", "export"]),
        ("claims", "*", ["view", "view_all", "approve", "export"]),
        ("documents", "*", ["view", "view_all", "create", "edit", "delete", "export"]),
        ("crm", "*", ["view", "view_all"]),
        ("reports", "*", ["view", "export"]),
        ("admin", "*", ["view", "create", "edit", "delete", "export"]),
    ],

    "HR Manager": [
        ("employees", "*", ["view", "view_all", "create", "edit", "export"]),
        ("attendance", "*", ["view", "view_all", "create", "edit", "approve", "export"]),
        ("leave", "*", ["view", "view_all", "create", "edit", "approve", "export"]),
        ("payroll", "structures", ["view", "view_all", "create", "edit"]),
        ("payroll", "runs", ["view", "view_all"]),
        ("payroll", "payslips", ["view", "view_all"]),
        ("recruitment", "*", ["view", "view_all", "create", "edit", "export"]),
        ("performance", "*", ["view", "view_all", "create", "edit", "export"]),
        ("engagement", "*", ["view", "view_all", "create", "edit", "export"]),
        ("learning", "*", ["view", "view_all", "create", "edit", "export"]),
        ("field", "*", ["view", "view_all", "export"]),
        ("claims", "*", ["view", "view_all", "approve", "export"]),
        ("documents", "*", ["view", "view_all", "create", "edit", "export"]),
        ("reports", "*", ["view", "export"]),
    ],

    "Department Manager": [
        ("employees", "employees", ["view", "view_all"]),
        ("attendance", "attendance", ["view", "view_all"]),
        ("attendance", "regularization", ["view", "view_all", "approve"]),
        ("leave", "requests", ["view", "view_all", "create", "approve"]),
        ("recruitment", "requisitions", ["view", "view_all", "create"]),
        ("recruitment", "applications", ["view", "view_all"]),
        ("recruitment", "interviews", ["view", "view_all", "create", "edit"]),
        ("performance", "goals", ["view", "view_all", "create", "edit"]),
        ("performance", "appraisals", ["view", "view_all", "edit", "approve"]),
        ("engagement", "recognitions", ["view", "view_all", "create"]),
        ("learning", "*", ["view", "view_all"]),
        ("field", "visits", ["view", "view_all"]),
        ("claims", "claims", ["view", "view_all", "approve"]),
        ("reports", "reports", ["view"]),
    ],

    "Finance Admin": [
        ("employees", "employees", ["view", "view_all"]),
        ("payroll", "*", ["view", "view_all", "create", "edit", "process", "export"]),
        ("claims", "*", ["view", "view_all", "approve", "process", "export"]),
        ("recruitment", "offers", ["view", "view_all"]),
        ("reports", "reports", ["view", "export"]),
    ],

    "Recruiter": [
        ("employees", "employees", ["view", "view_all"]),
        ("recruitment", "*", ["view", "view_all", "create", "edit", "delete", "export"]),
        ("reports", "reports", ["view"]),
    ],

    "Employee": [
        ("employees", "employees", ["view", "edit"]),
        ("employees", "documents", ["view", "create"]),
        ("attendance", "attendance", ["view", "create"]),
        ("attendance", "regularization", ["view", "create"]),
        ("leave", "requests", ["view", "create"]),
        ("payroll", "payslips", ["view"]),
        ("recruitment", "requisitions", ["view"]),
        ("performance", "goals", ["view", "create", "edit"]),
        ("performance", "appraisals", ["view", "edit"]),
        ("engagement", "surveys", ["view", "create"]),
        ("engagement", "recognitions", ["view"]),
        ("learning", "courses", ["view"]),
        ("learning", "enrollments", ["view", "create"]),
        ("field", "visits", ["view", "create", "edit"]),
        ("claims", "claims", ["view", "create"]),
        ("documents", "documents", ["view"]),
    ],

    "Management": [
        ("employees", "*", ["view", "view_all", "export"]),
        ("attendance", "*", ["view", "view_all", "export"]),
        ("leave", "*", ["view", "view_all", "export"]),
        ("payroll", "*", ["view", "view_all", "export"]),
        ("recruitment", "*", ["view", "view_all", "export"]),
        ("performance", "*", ["view", "view_all", "export"]),
        ("engagement", "*", ["view", "view_all", "export"]),
        ("learning", "*", ["view", "view_all", "export"]),
        ("field", "*", ["view", "view_all", "export"]),
        ("claims", "*", ["view", "view_all", "export"]),
        ("documents", "*", ["view", "view_all", "export"]),
        ("crm", "*", ["view", "view_all", "export"]),
        ("reports", "*", ["view", "export"]),
    ],
}
