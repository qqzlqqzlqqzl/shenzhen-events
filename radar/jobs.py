"""Persistent, rate-limited single-source retry queue. A oneshot worker consumes it."""
import json, secrets
from datetime import datetime,timedelta
from . import core

class QueueError(Exception):
    def __init__(self,message,status=400):self.status=status;super().__init__(message)

def enqueue(source_id):
    allowed={s['id'] for s in json.loads((core.ROOT/'sources.json').read_text())}
    if source_id not in allowed:raise QueueError('来源不存在',404)
    current=core.now();stamp=core.iso(current)
    with core.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM source_jobs WHERE source_id=? ORDER BY requested_at DESC LIMIT 1",(source_id,)).fetchone()
        if row and row['state'] in ('queued','running'):return dict(row)
        if row and (current-datetime.fromisoformat(row['requested_at'])).total_seconds()<120:
            raise QueueError('此来源刚检查过，请稍后重试（至少间隔2分钟）',429)
        jid=secrets.token_hex(10)
        db.execute('INSERT INTO source_jobs VALUES(?,?,?,?,?,?)',(jid,source_id,'queued',stamp,stamp,'已排队，通常一分钟内开始；不触发其他来源'))
        return dict(db.execute('SELECT * FROM source_jobs WHERE id=?',(jid,)).fetchone())

def recover():
    with core.db() as db:
        db.execute("UPDATE source_jobs SET state='failed',message='上次检查中断，可重新检查',updated_at=? WHERE state='running' AND updated_at<?",(core.stamp(),core.iso(core.now()-timedelta(minutes=12))))

def latest_jobs():
    recover()
    with core.db() as db:
        rows=[dict(x) for x in db.execute('SELECT * FROM source_jobs ORDER BY requested_at')]
    return {r['source_id']:r for r in rows}
