from __future__ import annotations
import json, sqlite3, time, uuid
from pathlib import Path
from contextlib import contextmanager

class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'media').mkdir(exist_ok=True)
        self.db = self.root / 'notes.sqlite3'
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS notes (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL,
              text TEXT NOT NULL DEFAULT '', segments TEXT NOT NULL DEFAULT '[]',
              summary TEXT NOT NULL DEFAULT '', chat TEXT NOT NULL DEFAULT '[]',
              media TEXT NOT NULL DEFAULT '', duration REAL NOT NULL DEFAULT 0,
              state TEXT NOT NULL DEFAULT 'ready', error TEXT NOT NULL DEFAULT '',
              mode TEXT NOT NULL DEFAULT 'general', language TEXT NOT NULL DEFAULT 'auto');
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, note_id TEXT NOT NULL, kind TEXT NOT NULL,
              state TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
              message TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
            ''')
            c.execute("UPDATE jobs SET state='interrupted',message='上次关闭时任务未结束，可点击重试' WHERE state IN ('queued','running')")
            c.execute("UPDATE notes SET state='interrupted',error='上次任务未完成，已保留结果，请重试' WHERE state IN ('queued','transcribing','summarizing','answering')")
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=30)
        c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
    @staticmethod
    def decode(row):
        if row is None: return None
        d=dict(row)
        for k in ('segments','chat'):
            if k in d: d[k]=json.loads(d[k])
        return d
    def create(self, title, **kwargs):
        id=uuid.uuid4().hex
        with self.connect() as c:
            c.execute('INSERT INTO notes(id,title,created) VALUES (?,?,?)',(id,title[:160],time.time()))
        self.update(id, **kwargs)
        return self.get(id)
    def get(self,id):
        with self.connect() as c: return self.decode(c.execute('SELECT * FROM notes WHERE id=?',(id,)).fetchone())
    def list(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT id,title,created,state,duration,error,substr(text,1,90) AS preview FROM notes ORDER BY created DESC')]
    def update(self,id,**fields):
        allowed={'title','text','segments','summary','chat','media','duration','state','error','mode','language'}
        if not fields or not set(fields)<=allowed: return
        for k in ('segments','chat'):
            if k in fields: fields[k]=json.dumps(fields[k],ensure_ascii=False)
        with self.connect() as c:
            c.execute('UPDATE notes SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),id))
    def add_job(self,note_id,kind):
        id=uuid.uuid4().hex
        with self.connect() as c:
            c.execute('INSERT INTO jobs(id,note_id,kind,state,created) VALUES (?,?,?,\'queued\',?)',(id,note_id,kind,time.time()))
        return id
    def job(self,id):
        with self.connect() as c:
            r=c.execute('SELECT * FROM jobs WHERE id=?',(id,)).fetchone()
            return dict(r) if r else None
    def job_update(self,id,**fields):
        allowed={'state','progress','message'}
        if not fields or not set(fields)<=allowed: return
        with self.connect() as c:
            c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),id))
    def active_jobs(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM jobs WHERE state IN ('queued','running') ORDER BY created")]
