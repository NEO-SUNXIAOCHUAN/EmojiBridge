"""Stable collection IDs over the existing membership keys, with a backed migration."""
import os
import sqlite3
import uuid
from .materials import now


def migrate(store):
    with store.connect() as conn:
        version=conn.execute('PRAGMA user_version').fetchone()[0]
        if version>=3:return
        backup=store.root/'materials-before-S0176.db'
        if not backup.exists():
            pending=backup.with_name(backup.name+'.'+uuid.uuid4().hex+'.pending');dst=sqlite3.connect(pending)
            try:conn.backup(dst)
            finally:dst.close()
            os.replace(pending,backup)
        conn.executescript('''BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS collection_nodes(id TEXT PRIMARY KEY,parent_id TEXT,name TEXT NOT NULL,legacy_key TEXT UNIQUE NOT NULL);
            CREATE INDEX IF NOT EXISTS collection_parent ON collection_nodes(parent_id);
            CREATE TRIGGER IF NOT EXISTS revision_collection_nodes_insert AFTER INSERT ON collection_nodes BEGIN UPDATE library_revision SET value=value+1; END;
            CREATE TRIGGER IF NOT EXISTS revision_collection_nodes_update AFTER UPDATE ON collection_nodes BEGIN UPDATE library_revision SET value=value+1; END;
            CREATE TRIGGER IF NOT EXISTS revision_collection_nodes_delete AFTER DELETE ON collection_nodes BEGIN UPDATE library_revision SET value=value+1; END;
        ''')
        for row in conn.execute('SELECT name FROM collections').fetchall():
            ident=uuid.uuid5(uuid.NAMESPACE_URL,'emojibridge:collection:'+row[0]).hex
            conn.execute('INSERT OR IGNORE INTO collection_nodes VALUES (?,NULL,?,?)',(ident,row[0],row[0]))
        conn.execute('PRAGMA user_version=3')


def label(value):
    value=str(value).strip()
    if not value or len(value)>100 or '\x1f' in value:raise ValueError('合集名须为1～100个字符')
    return value


def ensure(store,name,parent_id=None):
    """A legacy key remains accepted by all existing organizer entry points."""
    name=label(name)
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM collection_nodes WHERE legacy_key=?',(name,)).fetchone()
        if row and parent_id is None:return dict(row)
        if parent_id and not conn.execute('SELECT 1 FROM collection_nodes WHERE id=?',(parent_id,)).fetchone():raise ValueError('父合集不存在')
        row=conn.execute('SELECT * FROM collection_nodes WHERE name=? AND parent_id IS ?',(name,parent_id)).fetchone()
        if row:return dict(row)
        ident=uuid.uuid4().hex
        key=name if parent_id is None and not conn.execute('SELECT 1 FROM collections WHERE name=?',(name,)).fetchone() else '@'+ident
        conn.execute('INSERT OR IGNORE INTO collections VALUES (?,?)',(key,now()))
        conn.execute('INSERT INTO collection_nodes VALUES (?,?,?,?)',(ident,parent_id,name,key))
        return dict(id=ident,parent_id=parent_id,name=name,legacy_key=key)


def listing(store):
    # Some existing editor importers create a root collection using the legacy
    # SQL shape. Assign it a stable ID before presenting it.
    with store.connect() as conn:
        missing=[r[0] for r in conn.execute('SELECT name FROM collections WHERE name NOT IN (SELECT legacy_key FROM collection_nodes)')]
    for name in missing:ensure(store,name)
    with store.connect() as conn:rows=[dict(r) for r in conn.execute('SELECT * FROM collection_nodes ORDER BY name,id')]
    known={r['id']:r for r in rows}
    for row in rows:
        names=[row['name']];parent=row['parent_id'];seen={row['id']}
        while parent in known and parent not in seen:
            seen.add(parent);names.insert(0,known[parent]['name']);parent=known[parent]['parent_id']
        row['breadcrumb']=' / '.join(names);row['depth']=len(names)-1
    return sorted(rows,key=lambda r:(r['breadcrumb'],r['id']))


def change(store,ident,*,name=None,parent_id='unchanged',delete=False):
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM collection_nodes WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('合集不存在')
        if delete:
            # Only organization is removed; materials, flags, sources and all
            # child collections survive. Children become roots.
            children=conn.execute('SELECT id,name FROM collection_nodes WHERE parent_id=?',(ident,)).fetchall()
            for child in children:
                title=child['name'];suffix=1
                while conn.execute('SELECT 1 FROM collection_nodes WHERE parent_id IS NULL AND name=? AND id!=?',(title,ident)).fetchone():
                    suffix+=1;title=f"{child['name']} ({suffix})"
                conn.execute('UPDATE collection_nodes SET parent_id=NULL,name=? WHERE id=?',(title,child['id']))
            conn.execute('DELETE FROM memberships WHERE name=?',(row['legacy_key'],))
            conn.execute("UPDATE materials SET category='' WHERE category=?",(row['legacy_key'],))
            conn.execute('DELETE FROM collections WHERE name=?',(row['legacy_key'],))
            conn.execute('DELETE FROM collection_nodes WHERE id=?',(ident,))
            return
        parent=row['parent_id'] if parent_id=='unchanged' else parent_id or None
        cursor=parent;seen={ident}
        while cursor:
            if cursor in seen:raise ValueError('不能移动到自身或子合集')
            seen.add(cursor);ancestor=conn.execute('SELECT parent_id FROM collection_nodes WHERE id=?',(cursor,)).fetchone()
            if not ancestor:raise ValueError('父合集不存在')
            cursor=ancestor[0]
        title=label(name) if name is not None else row['name']
        if conn.execute('SELECT 1 FROM collection_nodes WHERE parent_id IS ? AND name=? AND id!=?',(parent,title,ident)).fetchone():raise ValueError('同一父合集下已有这个名称')
        conn.execute('UPDATE collection_nodes SET name=?,parent_id=? WHERE id=?',(title,parent,ident))
