import db


def notify_user(user_id, title, message, ntype="info", link=None):
    db.execute(
        "INSERT INTO notifications (user_id, title, message, type, link) VALUES (?,?,?,?,?)",
        (user_id, title, message, ntype, link),
    )


def notify_role(role_name, title, message, ntype="info", link=None):
    users = db.query(
        "SELECT u.id FROM users u JOIN roles r ON r.id=u.role_id WHERE r.name=? AND u.is_active=1",
        (role_name,),
    )
    for u in users:
        notify_user(u["id"], title, message, ntype, link)


def notify_roles(role_names, title, message, ntype="info", link=None):
    for r in role_names:
        notify_role(r, title, message, ntype, link)


def notify_manager(employee_id, title, message, ntype="info", link=None):
    row = db.query(
        """SELECT u.id FROM employees e JOIN users u ON u.employee_id = e.reporting_manager_id
           WHERE e.id=?""",
        (employee_id,), one=True,
    )
    if row:
        notify_user(row["id"], title, message, ntype, link)


def unread_count(user_id):
    row = db.query(
        "SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND is_read=0", (user_id,), one=True
    )
    return row["c"] if row else 0
