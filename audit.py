from flask import g, request
import db


def log(module, entity, entity_id, action, description, old_value=None, new_value=None):
    user = g.get("user")
    details = description
    db.execute(
        """INSERT INTO audit_log (user_id, action, entity_type, entity_id, details, ip_address)
           VALUES (?,?,?,?,?,?)""",
        (
            user["id"] if user else None,
            action,
            f"{module}.{entity}",
            entity_id,
            details,
            request.remote_addr if request else None,
        ),
    )
