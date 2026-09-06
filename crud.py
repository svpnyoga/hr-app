"""Generic CRUD engine: given a simple entity configuration (table, fields,
permissions), wires up list / create / edit / view / delete routes backed by
real SQL against SQLite, with search, pagination, sorting, audit logging and
RBAC permission checks. Used for simpler master-data entities; workflow-heavy
records (employees, leave requests, payroll runs, applications...) use
bespoke blueprint handlers instead, see blueprints/*.py.
"""
import math
from flask import render_template, request, redirect, url_for, flash

import db
import audit
from auth import permission_required, has_permission
from helpers import paginate_args, csv_response

SOFT_DELETE_TABLES = ()


class Field:
    def __init__(self, name, label=None, type="text", required=False, fk_table=None,
                 fk_label="name", list=True, form=True, searchable=False, help=None,
                 default=None, step="any", options=None):
        self.name = name
        self.label = label or name.replace("_", " ").title()
        self.type = type  # text, textarea, number, date, select, checkbox, email, tel
        self.required = required
        self.fk_table = fk_table
        self.fk_label = fk_label
        self.list = list
        self.form = form
        self.searchable = searchable
        self.help = help
        self.default = default
        self.step = step
        self.options = options  # static list of (value, label) for type="static-select"


class EntityConfig:
    def __init__(self, key, table, module, entity, name_singular, name_plural, fields,
                 order_by=None, code_prefix=None, code_field=None, icon="box",
                 detail_extra=None, subtitle_field=None):
        self.key = key
        self.table = table
        self.module = module
        self.entity = entity
        self.name_singular = name_singular
        self.name_plural = name_plural
        self.fields = fields
        self.order_by = order_by or "id DESC"
        self.code_prefix = code_prefix
        self.code_field = code_field
        self.icon = icon
        self.detail_extra = detail_extra
        self.subtitle_field = subtitle_field

    def perm(self, action):
        return f"{self.module}.{self.entity}.{action}"


def _fk_options(field):
    rows = db.query(f"SELECT id, {field.fk_label} as label FROM {field.fk_table} ORDER BY {field.fk_label}")
    return [(r["id"], r["label"]) for r in rows]


def register_crud(bp, cfg: EntityConfig):
    list_fields = [f for f in cfg.fields if f.list]
    form_fields = [f for f in cfg.fields if f.form]
    search_fields = [f.name for f in cfg.fields if f.searchable]
    has_deleted = cfg.table in SOFT_DELETE_TABLES

    @bp.route(f"/{cfg.key}", endpoint=f"{cfg.key}_list")
    @permission_required(cfg.perm("view"))
    def _list():
        q = request.args.get("q", "").strip()
        page, per_page = paginate_args(request)
        where = []
        args = []
        if has_deleted:
            where.append("deleted_at IS NULL")
        if q and search_fields:
            ors = " OR ".join([f"{f} LIKE ?" for f in search_fields])
            where.append(f"({ors})")
            args.extend([f"%{q}%"] * len(search_fields))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        total = db.query(f"SELECT COUNT(*) c FROM {cfg.table} {where_sql}", args, one=True)["c"]

        if request.args.get("export") == "csv" and has_permission(cfg.perm("export")):
            all_rows = db.query(f"SELECT * FROM {cfg.table} {where_sql} ORDER BY {cfg.order_by}", args)
            header = [f.label for f in list_fields]
            out = [[r[f.name] for f in list_fields] for r in all_rows]
            audit.log(cfg.module, cfg.entity, None, "export", f"Exported {cfg.name_plural} to CSV")
            return csv_response(f"{cfg.key}.csv", header, out)

        offset = (page - 1) * per_page
        rows = db.query(
            f"SELECT * FROM {cfg.table} {where_sql} ORDER BY {cfg.order_by} LIMIT ? OFFSET ?",
            args + [per_page, offset],
        )
        fk_cache = {}
        display_rows = []
        for r in rows:
            d = dict(r)
            for f in list_fields:
                if f.fk_table and d.get(f.name):
                    key = (f.fk_table, f.fk_label, d[f.name])
                    if key not in fk_cache:
                        rr = db.query(f"SELECT {f.fk_label} as label FROM {f.fk_table} WHERE id=?", (d[f.name],), one=True)
                        fk_cache[key] = rr["label"] if rr else "-"
                    d[f.name + "__label"] = fk_cache[key]
            display_rows.append(d)
        pages = max(1, math.ceil(total / per_page))
        return render_template(
            "partials/generic_list.html", cfg=cfg, rows=display_rows, list_fields=list_fields,
            q=q, page=page, pages=pages, total=total, per_page=per_page,
            can_create=has_permission(cfg.perm("create")),
            can_edit=has_permission(cfg.perm("edit")),
            can_delete=has_permission(cfg.perm("delete")),
            can_export=has_permission(cfg.perm("export")),
        )

    @bp.route(f"/{cfg.key}/new", methods=("GET", "POST"), endpoint=f"{cfg.key}_new")
    @permission_required(cfg.perm("create"))
    def _new():
        options = {f.name: _fk_options(f) for f in form_fields if f.fk_table}
        if request.method == "POST":
            data = _collect_form(form_fields)
            cols = list(data.keys())
            if cfg.code_field and cfg.code_prefix and not data.get(cfg.code_field):
                data[cfg.code_field] = db.next_sequence(cfg.code_prefix)
                cols = list(data.keys())
            placeholders = ",".join(["?"] * len(cols))
            new_id = db.execute(
                f"INSERT INTO {cfg.table} ({','.join(cols)}) VALUES ({placeholders})",
                [data[c] for c in cols],
            )
            audit.log(cfg.module, cfg.entity, new_id, "create", f"Created {cfg.name_singular} #{new_id}")
            flash(f"{cfg.name_singular} created successfully.", "success")
            return redirect(url_for(f"{bp.name}.{cfg.key}_view", id=new_id))
        return render_template("partials/generic_form.html", cfg=cfg, fields=form_fields, row=None, options=options)

    @bp.route(f"/{cfg.key}/<int:id>", endpoint=f"{cfg.key}_view")
    @permission_required(cfg.perm("view"))
    def _view(id):
        row = db.query(f"SELECT * FROM {cfg.table} WHERE id=?", (id,), one=True)
        if row is None:
            flash("Record not found.", "error")
            return redirect(url_for(f"{bp.name}.{cfg.key}_list"))
        d = dict(row)
        for f in cfg.fields:
            if f.fk_table and d.get(f.name):
                rr = db.query(f"SELECT {f.fk_label} as label FROM {f.fk_table} WHERE id=?", (d[f.name],), one=True)
                d[f.name + "__label"] = rr["label"] if rr else "-"
        extra = cfg.detail_extra(id) if cfg.detail_extra else {}
        return render_template(
            "partials/generic_detail.html", cfg=cfg, row=d, fields=cfg.fields,
            can_edit=has_permission(cfg.perm("edit")), can_delete=has_permission(cfg.perm("delete")),
            **extra,
        )

    @bp.route(f"/{cfg.key}/<int:id>/edit", methods=("GET", "POST"), endpoint=f"{cfg.key}_edit")
    @permission_required(cfg.perm("edit"))
    def _edit(id):
        row = db.query(f"SELECT * FROM {cfg.table} WHERE id=?", (id,), one=True)
        if row is None:
            flash("Record not found.", "error")
            return redirect(url_for(f"{bp.name}.{cfg.key}_list"))
        options = {f.name: _fk_options(f) for f in form_fields if f.fk_table}
        if request.method == "POST":
            data = _collect_form(form_fields)
            old = dict(row)
            sets = ",".join([f"{c}=?" for c in data.keys()])
            db.execute(f"UPDATE {cfg.table} SET {sets} WHERE id=?", list(data.values()) + [id])
            audit.log(cfg.module, cfg.entity, id, "update", f"Updated {cfg.name_singular} #{id}",
                      old_value=str(old), new_value=str(data))
            flash(f"{cfg.name_singular} updated successfully.", "success")
            return redirect(url_for(f"{bp.name}.{cfg.key}_view", id=id))
        return render_template("partials/generic_form.html", cfg=cfg, fields=form_fields, row=row, options=options)

    @bp.route(f"/{cfg.key}/<int:id>/delete", methods=("POST",), endpoint=f"{cfg.key}_delete")
    @permission_required(cfg.perm("delete"))
    def _delete(id):
        if has_deleted:
            db.execute(f"UPDATE {cfg.table} SET deleted_at=CURRENT_TIMESTAMP WHERE id=?", (id,))
        else:
            db.execute(f"DELETE FROM {cfg.table} WHERE id=?", (id,))
        audit.log(cfg.module, cfg.entity, id, "delete", f"Deleted {cfg.name_singular} #{id}")
        flash(f"{cfg.name_singular} deleted.", "success")
        return redirect(url_for(f"{bp.name}.{cfg.key}_list"))


def _collect_form(form_fields):
    data = {}
    for f in form_fields:
        if f.type == "checkbox":
            data[f.name] = 1 if request.form.get(f.name) else 0
        else:
            val = request.form.get(f.name, "").strip()
            if f.type == "number":
                data[f.name] = float(val) if val else 0
            else:
                data[f.name] = val if val != "" else None
    return data
