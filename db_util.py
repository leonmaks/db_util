import logging
import copy

import tittles as t
import db_core as db


if __name__ == "__main__":
    logging.basicConfig(format="%(levelname)s: %(asctime)s %(module)s:%(lineno)d(%(funcName)s) %(message)s", level=logging.DEBUG)

_log = logging.getLogger(__name__)


DB_ERR_TABLE_DOES_NOT_EXIST = "42P01"


__DB_CLASS_KIND_TABLE = "'r', ''"


def db_classes(conn, where_list=None, **kwargs):
    stmt_ = [(
        "SELECT n.nspname, c.relname,"
        " CASE c.relkind"
        " WHEN 'r' THEN 'table'"
        " WHEN 'v' THEN 'view'"
        " WHEN 'm' THEN 'materialized view'"
        " WHEN 'i' THEN 'index'"
        " WHEN 'S' THEN 'sequence'"
        " WHEN 's' THEN 'special'"
        " WHEN 'f' THEN 'foreign table'"
        " END,"
        " u.usename"
        " FROM pg_catalog.pg_user u, pg_catalog.pg_namespace n, pg_catalog.pg_class c"
        " WHERE n.oid = c.relnamespace"
        " AND u.usesysid = c.relowner"
        " AND n.nspname <> 'pg_catalog'"
        " AND n.nspname <> 'information_schema'"
        " AND n.nspname !~ '^pg_toast'"
        " AND pg_catalog.pg_table_is_visible(c.oid)"
    ), ]
    if where_list: stmt_.append("AND %s" % " AND ".join(where_list))
    classes_ = []
    for r_ in conn.select_all(stmt_, **kwargs):
        classes_.append({"schema_name": r_[0], "class_name": r_[1], "class_kind": r_[2], "class_owner": r_[3]})
    return classes_


def db_constraints(conn, where_list=None, **kwargs):
    stmt_ = [(
        # TODO Statement - to collect all db_constraints with their attributes
        #    + order by constraint_type: 1 - pk, 2 - uk, 3 - fk, other
        #    + order by constraint attributes (where attribute order stored?)
        "SELECT x.relname, c.conname, n.nspname, c.contype, pg_catalog.pg_get_constraintdef(c.oid),"
        " CASE"
        " WHEN (c.contype = 'p') THEN 10"
        " WHEN (c.contype = 'u') THEN 20"
        " WHEN (c.contype = 'f') THEN 30"
        " ELSE 00"
        " END AS ord_"
        " FROM pg_catalog.pg_class x, pg_catalog.pg_namespace n, pg_catalog.pg_constraint c"
        " WHERE n.oid = c.connamespace"
        " AND x.oid = c.conrelid"
        " AND c.contype in ('f', 'p','c','u')"
    ), ]
    if where_list: stmt_.append("AND %s" % " AND ".join(where_list))
    stmt_.append(" ORDER BY ord_")
    if kwargs.get("debug"): _log.debug("STMT: %s" % stmt_)
    cons_ = []
    csr_ = None
    try:
        csr_ = conn.select(" ".join(stmt_))
        for t_ in csr_.fetchall():
            cons_.append({"table_name": t_[0], "con_name": t_[1], "schema_name": t_[2], "con_type": t_[3], "con_src": t_[4]})
    finally:
        csr_ and csr_.close()
    return cons_


def db_triggers(conn, where_list=None, **kwargs):
    stmt_ = [(
        "SELECT t.tgname, n.nspname, c.relname"
        " FROM pg_authid a, pg_catalog.pg_namespace n, pg_catalog.pg_class c, pg_catalog.pg_trigger t"
        " WHERE c.oid = t.tgrelid AND n.oid = c.relnamespace AND a.oid = c.relowner"
    ), ]
    if where_list: stmt_.append("AND %s" % " AND ".join(where_list))
    trigs_ = []
    for t_ in conn.select_all(stmt_, **kwargs):
        trigs_.append({"trig_name": t_[0], "schema_name": t_[1], "table_name": t_[2]})
    return trigs_


def db_functions(conn, where_list=None, **kwargs):
    # TODO - add function owner to the query
    stmt_ = [(
        "SELECT p.proname, p.proisagg, pg_catalog.pg_get_function_identity_arguments(p.oid), n.nspname"
        " FROM pg_catalog.pg_namespace n, pg_catalog.pg_authid a, pg_catalog.pg_proc p"
        " WHERE a.oid = p.proowner AND n.oid = p.pronamespace"
    ), ]
    if where_list: stmt_.append("AND %s" % " AND ".join(where_list))
    funcs_ = []
    for f_ in conn.select_all(stmt_, **kwargs):
        funcs_.append({"func_name": f_[0], "is_aggr": f_[1], "args": f_[2], "schema_name": f_[3]})
    return funcs_


def db_sequences(conn, where_list=None, **kwargs):
    stmt_ = [(
        "SELECT t.relname, a.attname, s.relname, n.nspname"
        " FROM pg_namespace n, pg_attribute a, pg_class t, pg_depend d, pg_class s"
        " WHERE s.relkind = 'S'"
        " AND d.objid = s.oid"
        " AND t.oid = d.refobjid"
        " AND (a.attrelid, a.attnum) = (d.refobjid, d.refobjsubid)"
        " AND n.oid = s.relnamespace"
    ), ]
    if where_list: stmt_.append("AND %s" % " AND ".join(where_list))
    seqs_ = []
    csr_ = None
    try:
        csr_ = conn.select(" ".join(stmt_))
        for t_ in csr_.fetchall():
            seqs_.append({"table_name": t_[0], "col_name": t_[1], "seq_name": t_[2], "schema_name": t_[3]})
    finally:
        csr_ and csr_.close()
    return seqs_


def db_tables(conn, where_list=None, **kwargs):
    where_ = ["c.relkind IN (%s)" % __DB_CLASS_KIND_TABLE, ]
    if where_list: where_ = where_ + where_list
    return t.dicarray_dup_key(db_classes(conn, where_, **kwargs), "class_name", "table_name")


def db_owned_tables(conn, where_list=None, **kwargs):
    where_ = ["u.usename=CURRENT_USER", ]
    if where_list: where_ = where_ + where_list
    return db_tables(conn, where_, **kwargs)


def db_table_columns(conn, table_name, **kwargs):
    cols_ = []
    for c_ in conn.select_all((
        "SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnum, a.attnotnull"
        " FROM pg_catalog.pg_attribute a, pg_catalog.pg_namespace n, pg_catalog.pg_class c"
        " WHERE c.relname = %s"
        " AND n.oid = c.relnamespace"
        " AND a.attrelid = c.oid"
        " AND a.attnum > 0"
        " AND NOT a.attisdropped"
        " ORDER BY a.attnum"
    ), (table_name, ), **kwargs):
        cols_.append({"col_name": c_[0], "col_type": c_[1], "col_num": c_[2], "not_null": c_[3]})
    return cols_


def db_table_triggers(conn, table_name, where_list=None, **kwargs):
    return db_triggers(conn, ["c.relname = '%s'" % table_name, ] + (where_list and where_list or []), **kwargs)


def db_table_sequences(conn, table_name, **kwargs):
    return db_sequences(conn, ["t.relname = '%s'" % table_name, ], **kwargs)


# TODO update list_constraints function to get source from pg_get_constraintdef
def db_table_check_constraints(conn, table_name, **kwargs):
    return db_constraints(conn, ["x.relname = '%s'" % table_name, "c.contype = 'c'"], **kwargs)


def db_table_select(conn, table_name, columns, where=None, order_by=None, args=None, **kwargs):
    # _log.debug("table_name=%s, columns=%s, where=%s, order_by=%s, args=%s, kwargs=%s" % (table_name, columns, where, order_by, args, kwargs))

    return conn.select_all((
        "SELECT %s FROM %s WHERE %s ORDER BY %s"
    ) % (
        ", ".join(columns),
        table_name,
        " AND ".join(where),
        ", ".join(order_by),
    ), args, **kwargs)


def db_table_insert_rows(conn, table_name, columns, records, **kwargs):
    vals_ = []
    for c_ in columns:
        vals_.append("%s")
    stmt_ = "INSERT INTO %s (%s) VALUES (%s)" % (table_name, ", ".join(columns), ", ".join(vals_))
    rowcount_ = 0
    for r_ in records:
        rc_ = conn.execute(stmt_, r_[:len(columns)], **kwargs)
        if rc_ < 1: raise t.DbExecuteError("Can't insert into '%s' (rowcount=%s) STMT: %s; ARGS: %s" % (table_name, rc_, stmt_, r_))
        rowcount_ += rc_
    return rowcount_


def db_table_update_rows(conn, table_name, columns, records, ident_columns, **kwargs):
    idents_ = {}
    where_ = []
    for c_ in ident_columns: idents_[c_] = {"i": columns.index(c_)}
    for c_ in idents_.keys():
        where_.append(c_ + " = %s")
        idents_[c_]["v"] = t.tavbi(records, idents_[c_]["i"])
    set_ = []
    for c_ in columns: set_.append(c_ + " = %s")
    stmt_ = "UPDATE %s SET %s WHERE %s" % (table_name, ", ".join(set_), " AND ".join(where_))
    r_i_ = 0
    rowcount_ = 0
    for r_ in records:
        vals_ = ()
        c_i_ = 0
        for c_ in columns:
            vals_ += (r_[c_i_], )
            c_i_ += 1
        args_ = ()
        for c_ in idents_.keys(): args_ += (idents_[c_]["v"][r_i_], )
        rc_ = conn.execute(stmt_, vals_ + args_, **kwargs)
        if rc_ < 1: raise t.DbExecuteError("Can't update '%s' (rowcount=%s) STMT: %s; VALS: %s; ARGS: %s" % (table_name, rc_, stmt_, vals_, args_))
        rowcount_ += rc_
        r_i_ += 1
    return rowcount_


def db_table_delete_rows(conn, table_name, columns, records, ident_columns, **kwargs):
    idents_ = {}
    where_ = []
    for c_ in ident_columns: idents_[c_] = {"i": columns.index(c_)}
    for c_ in idents_.keys():
        where_.append(c_ + " = %s")
        idents_[c_]["v"] = t.tavbi(records, idents_[c_]["i"])
    stmt_ = "DELETE FROM %s WHERE %s" % (table_name, " AND ".join(where_))
    i_ = 0
    rowcount_ = 0
    for r_ in records:
        a_ = ()
        for c_ in idents_.keys():
            a_ += (idents_[c_]["v"][i_], )
        rc_ = conn.execute(stmt_, a_, **kwargs)
        if rc_ < 1: raise t.DbExecuteError("Can't delete from '%s' (rowcount=%s) STMT: %s; ARGS: %s" % (table_name, rc_, stmt_, a_))
        rowcount_ += rc_
        i_ += 1
    return rowcount_


def db_table_ddl(conn, table_name, table_cols, table_seqs, table_cons, **kwargs):

    # Make local copy
    table_cols_ = table_cols

    # Sequences
    if table_seqs:
        for s_ in table_seqs:
            col_ = t.dic_find_in_list(table_cols_, "col_name", s_["col_name"])
            if col_:
                col_["is_seq"] = True
                col_["col_type"] = "serial"
            else:
                raise t.DbIntgrError("Sequence '%s' is not related to any table (%s) column" % (s_["seq_name"], table_name))

    # Columns
    cols_ = []
    for c_ in table_cols_:
        cols_.append("%s %s%s" % (c_["col_name"], c_["col_type"], c_.get("not_null") and " NOT NULL" or ""))

    # Constraints
    cons_ = []
    if table_cons:
        for c_ in table_cons:
            if c_["con_type"] == "c":
                cons_.append("CONSTRAINT %s %s" % (c_["con_name"], c_["con_src"]))

    # Table prefix
    table_pfx_ = kwargs.get("table_prefix", "")

    # Construct DDL statement
    stmt_ = "CREATE TABLE %s%s (%s%s)" % (table_pfx_, table_name, ", ".join(cols_), cons_ and ", %s" % ", ".join(cons_) or "")
    if kwargs.get("apply"): conn.execute(stmt_, **kwargs)
    return [stmt_, ]


def db_table_create(conn, table_name, **kwargs):
    return db_table_ddl(conn, table_name, db_table_columns(conn, table_name), db_table_sequences(conn, table_name), db_table_check_constraints(conn, table_name))


def db_table_drop(conn, table, **kwargs):
    table_name_ = t.DicFld(table, "table_name_field", "class_name", **kwargs)
    schema_name_ = t.DicFld(table, "schema_name_field", "schema_name", **kwargs)
    if not table_name_.v():
        raise t.ConfigError("Table name undefined (no field '%s' in table dict %s)" % (table_name_.n(), table))
    stmt_ = "DROP TABLE %s" % (schema_name_.v() and ("%s.%s" % (schema_name_.v(), table_name_.v())) or table_name_.v())
    if kwargs.get("apply"): conn.execute(stmt_, **kwargs)
    return [stmt_, ]


def db_tables_drop(conn, tables, **kwargs):
    stmt_ = []
    for t_ in tables:
        stmt_ += db_table_drop(conn, t_, **kwargs)
    return stmt_


def __test():

    DB_conf = {
        "USER": "ffba_backup",
        "PASSWORD": "f__",
    }

    table_name_ = "t_records"
    table_name2_ = "t_records_1"

    conn_ = db.Db(DB_conf, database_equals_user=True)
    # conn_.connect(debug="statement")

    coldefs_ = db_table_columns(conn_, table_name_)
    cols_ = t.dalv(coldefs_, "col_name")
    recs_ = db_table_select(conn_, table_name_, cols_)

    rc_ = db_table_delete_rows(conn_, table_name2_, cols_, recs_, ["cash_register_id", "entry_date"])
    _log.debug("%s records deleted" % rc_)

    rc_ = db_table_insert_rows(conn_, table_name2_, cols_, recs_)
    _log.debug("%s records inserted" % rc_)

    conn_.commit()


if __name__ == "__main__":
    __test()
