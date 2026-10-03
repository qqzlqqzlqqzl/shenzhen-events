"""Durable source observations, immutable targets and planning availability.

All write-side authority reads follow BEGIN IMMEDIATE. Network/model work never
runs under this module's writer lock. A read projection is valid only for its
SQLite snapshot; it is not a promise about future publisher state.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

from . import core

SCHEMA = 1
WARNING = '来源显示已取消；当前活动身份待复核'
UNAVAILABLE = '来源安全采集尚未完成；当前安排待重新核实'
MIB = 1024 * 1024
LIMITS = dict(inventory_bytes=1_000_000, cards=256, slice_bytes=65_536,
              slices_bytes=1_000_000, metadata_bytes=4096, target_edges=2048,
              row_bytes=4096, account_bytes=256*MIB, headroom_bytes=16*MIB,
              outstanding=1, anchor_bytes=192*MIB, target_bytes=1_000_000, bindings=24)
# Includes all four edge/guard/membership/adjudication ledgers, two copies for
# SQLite pages/indexes and two for WAL/checkpoint/staging. Measured by the bound
# harness, not merely a blob counter. Physical ENOSPC is still possible.
CAPTURE_RESERVE = 4 * (2_000_000 + 256*4096 + 5*2048*4096) + 2*MIB
UNFINISHED = "('reserved','acquiring','captured','recovery_required')"


class SafetyError(RuntimeError):
    code = 'safety_unavailable'
    status = 503


class Conflict(SafetyError):
    code = 'safety_snapshot_changed'
    status = 409


class Capacity(SafetyError):
    code = 'safety_capacity_paused'


class Integrity(SafetyError):
    code = 'safety_integrity_failure'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def uid(prefix):
    return prefix + '-' + uuid.uuid4().hex


DDL = [
    'CREATE TABLE safety_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_version INTEGER NOT NULL,safety_epoch INTEGER NOT NULL)',
    'CREATE TABLE safety_evidence_blobs(digest TEXT PRIMARY KEY,body BLOB NOT NULL,format TEXT NOT NULL,parser_schema TEXT NOT NULL,original_bytes INTEGER NOT NULL)',
    "CREATE TABLE safety_capture_runs(capture_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,inventory_url TEXT NOT NULL,owner TEXT NOT NULL,started_at TEXT NOT NULL,capture_state TEXT NOT NULL CHECK(capture_state IN ('reserved','acquiring','captured','recovery_required','safety_finalized')),revision INTEGER NOT NULL CHECK(revision>0),completed_at TEXT,failure_code TEXT,reserved_capacity INTEGER NOT NULL,response_digest TEXT REFERENCES safety_evidence_blobs(digest),provenance TEXT,receipt TEXT,recovery_decision_id TEXT)",
    f'CREATE UNIQUE INDEX safety_source_fence ON safety_capture_runs(source_id) WHERE capture_state IN {UNFINISHED}',
    'CREATE TABLE safety_capacity(reservation_id TEXT PRIMARY KEY,bytes INTEGER NOT NULL CHECK(bytes>=0),kind TEXT NOT NULL)',
    'CREATE TABLE safety_diagnostics(id TEXT PRIMARY KEY,code TEXT NOT NULL,source_id TEXT,recorded_at TEXT NOT NULL,details TEXT NOT NULL)',
    'CREATE TABLE eefocus_target_anchors(binding_id TEXT PRIMARY KEY REFERENCES eefocus_identity_bindings(binding_id),event_id TEXT NOT NULL REFERENCES events(id),raw_id INTEGER NOT NULL REFERENCES raw_items(id),occurrence TEXT NOT NULL,evidence TEXT NOT NULL,anchored_at TEXT NOT NULL)',
    'CREATE INDEX safety_anchor_event ON eefocus_target_anchors(event_id)',
    'CREATE TABLE safety_observations(observation_id TEXT PRIMARY KEY,capture_id TEXT NOT NULL REFERENCES safety_capture_runs(capture_id),source_id TEXT NOT NULL,alias_url TEXT NOT NULL,card_key TEXT NOT NULL,kind TEXT NOT NULL,observed_at TEXT NOT NULL,occurrence TEXT NOT NULL,status_text TEXT NOT NULL,status_scope TEXT NOT NULL,evidence_digest TEXT NOT NULL REFERENCES safety_evidence_blobs(digest),metadata TEXT NOT NULL,targeting_state TEXT NOT NULL,targeting_revision INTEGER NOT NULL,UNIQUE(capture_id,card_key,kind))',
    'CREATE INDEX safety_observation_alias ON safety_observations(source_id,alias_url)',
    'CREATE TABLE safety_observation_targets(observation_id TEXT NOT NULL REFERENCES safety_observations(observation_id),event_id TEXT NOT NULL REFERENCES events(id),source_id TEXT NOT NULL,occurrence TEXT NOT NULL,evidence TEXT NOT NULL,guard_id TEXT NOT NULL,PRIMARY KEY(observation_id,event_id))',
    'CREATE TABLE safety_target_evidence(observation_id TEXT NOT NULL,event_id TEXT NOT NULL,evidence_key TEXT NOT NULL,reference TEXT NOT NULL,PRIMARY KEY(observation_id,event_id,evidence_key),FOREIGN KEY(observation_id,event_id) REFERENCES safety_observation_targets(observation_id,event_id))',
    'CREATE TABLE event_safety_guards(guard_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,event_id TEXT NOT NULL REFERENCES events(id),occurrence TEXT NOT NULL,alias_url TEXT NOT NULL,reason TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN (\'active\',\'resolved\')),revision INTEGER NOT NULL,evidence_set_digest TEXT NOT NULL,created_at TEXT NOT NULL,resolved_at TEXT,resolution_id TEXT)',
    "CREATE INDEX safety_active_event ON event_safety_guards(event_id) WHERE state='active'",
    'CREATE TABLE safety_guard_members(guard_id TEXT NOT NULL REFERENCES event_safety_guards(guard_id),observation_id TEXT NOT NULL REFERENCES safety_observations(observation_id),PRIMARY KEY(guard_id,observation_id))',
    'CREATE TABLE safety_target_adjudications(adjudication_id TEXT PRIMARY KEY,observation_id TEXT NOT NULL REFERENCES safety_observations(observation_id),binding_id TEXT NOT NULL REFERENCES eefocus_target_anchors(binding_id),event_id TEXT NOT NULL REFERENCES events(id),prior_revision INTEGER NOT NULL,result TEXT NOT NULL,evidence TEXT NOT NULL,committed_at TEXT NOT NULL,UNIQUE(observation_id,binding_id,event_id))',
    'CREATE TABLE safety_resolutions(resolution_id TEXT PRIMARY KEY,kind TEXT NOT NULL,source_id TEXT NOT NULL,event_id TEXT NOT NULL REFERENCES events(id),expectations TEXT NOT NULL,evidence_digest TEXT NOT NULL REFERENCES safety_evidence_blobs(digest),actor TEXT NOT NULL,resolved_at TEXT NOT NULL,result TEXT NOT NULL)',
    'CREATE TABLE safety_recovery_decisions(decision_id TEXT PRIMARY KEY,capture_id TEXT NOT NULL REFERENCES safety_capture_runs(capture_id),expected_revision INTEGER NOT NULL,mode TEXT NOT NULL,evidence TEXT NOT NULL,actor TEXT NOT NULL,result TEXT NOT NULL,committed_at TEXT NOT NULL)',
]
for table in ('safety_evidence_blobs','eefocus_target_anchors','safety_observation_targets',
              'safety_target_evidence','safety_guard_members','safety_target_adjudications','safety_resolutions','safety_recovery_decisions'):
    DDL.extend([f"CREATE TRIGGER {table}_immutable_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable safety evidence'); END",
                f"CREATE TRIGGER {table}_immutable_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'immutable safety evidence'); END"])
DDL.extend([
    "CREATE TRIGGER binding_immutable_update BEFORE UPDATE ON eefocus_identity_bindings WHEN NEW.binding_id<>OLD.binding_id OR NEW.source_id<>OLD.source_id OR NEW.alias_url<>OLD.alias_url OR NEW.canonical_url<>OLD.canonical_url OR NEW.evidence<>OLD.evidence OR NEW.verified_at<>OLD.verified_at OR (OLD.event_id IS NOT NULL AND NEW.event_id IS NOT OLD.event_id) BEGIN SELECT RAISE(ABORT,'immutable verified binding'); END",
    "CREATE TRIGGER binding_immutable_delete BEFORE DELETE ON eefocus_identity_bindings BEGIN SELECT RAISE(ABORT,'immutable verified binding'); END",
    "CREATE TRIGGER observation_immutable_update BEFORE UPDATE OF observation_id,capture_id,source_id,alias_url,card_key,kind,observed_at,occurrence,status_text,status_scope,evidence_digest,metadata ON safety_observations BEGIN SELECT RAISE(ABORT,'immutable captured observation'); END",
    "CREATE TRIGGER observation_immutable_delete BEFORE DELETE ON safety_observations BEGIN SELECT RAISE(ABORT,'immutable captured observation'); END",
    "CREATE TRIGGER capture_immutable_evidence BEFORE UPDATE ON safety_capture_runs WHEN OLD.response_digest IS NOT NULL AND (NEW.response_digest IS NOT OLD.response_digest OR NEW.provenance IS NOT OLD.provenance) BEGIN SELECT RAISE(ABORT,'immutable capture response'); END",
    "CREATE TRIGGER capture_finalized BEFORE UPDATE ON safety_capture_runs WHEN OLD.capture_state='safety_finalized' BEGIN SELECT RAISE(ABORT,'immutable capture receipt'); END",
    "CREATE TRIGGER capture_no_delete BEFORE DELETE ON safety_capture_runs BEGIN SELECT RAISE(ABORT,'capture replay ledger retained'); END",
])


def migrate(c):
    """Add only audit schema/consistent anchors, in one deliberate transaction."""
    c.commit()
    c.execute('BEGIN IMMEDIATE')
    try:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='safety_meta'").fetchone()
        if exists:
            assert_schema(c)
            if c.execute('PRAGMA foreign_key_check').fetchall():raise Integrity('existing safety references corrupt')
            c.commit()
            return
        for statement in DDL:
            c.execute(statement)
        for row in c.execute('SELECT * FROM eefocus_identity_bindings WHERE event_id IS NOT NULL').fetchall():
            try:evidence = json.loads(row['evidence'])
            except (ValueError,TypeError):continue
            if not isinstance(evidence,dict):continue
            links = c.execute('SELECT es.*,e.start_at FROM event_sources es JOIN events e ON e.id=es.event_id WHERE es.source_id=? AND es.url=? AND es.event_id=?',
                              (row['source_id'], row['canonical_url'], row['event_id'])).fetchall()
            days = evidence.get('occurrence_dates', [])
            raw=c.execute('SELECT source_id,url FROM raw_items WHERE id=?',(links[0]['raw_id'],)).fetchone() if len(links)==1 else None
            if (len(links) == 1 and raw and raw['source_id']==row['source_id'] and raw['url']==row['canonical_url']
                    and evidence.get('canonical_url')==row['canonical_url'] and days == [(links[0]['start_at'] or '')[:10]]):
                c.execute('INSERT INTO eefocus_target_anchors VALUES(?,?,?,?,?,?)',
                          (row['binding_id'], row['event_id'], links[0]['raw_id'], encoded(days), row['evidence'], core.stamp()))
        c.execute('INSERT INTO safety_meta VALUES(1,?,0)', (SCHEMA,))
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise Integrity('migration foreign-key failure')
        c.commit()
    except Exception:
        c.rollback()
        raise


def assert_schema(c):
    try:
        row = c.execute('SELECT schema_version,safety_epoch FROM safety_meta WHERE singleton=1').fetchone()
        if not row or row['schema_version'] != SCHEMA:
            raise SafetyError('unsupported safety schema')
        columns={
            'event_safety_guards':'guard_id,event_id,source_id,state,revision,evidence_set_digest,occurrence',
            'safety_capture_runs':'capture_id,source_id,capture_state,revision,response_digest,receipt',
            'safety_observations':'observation_id,capture_id,source_id,alias_url,occurrence,targeting_state,targeting_revision',
            'safety_guard_members':'guard_id,observation_id',
            'eefocus_target_anchors':'binding_id,event_id,raw_id,occurrence,evidence',
            'safety_observation_targets':'observation_id,event_id,guard_id,evidence',
            'safety_target_evidence':'observation_id,event_id,evidence_key,reference',
            'safety_resolutions':'resolution_id,event_id,expectations,evidence_digest,result',
            'safety_capacity':'reservation_id,bytes,kind',
            'safety_evidence_blobs':'digest,body,format,parser_schema,original_bytes',
            'safety_target_adjudications':'adjudication_id,observation_id,binding_id,event_id,prior_revision,result,evidence',
            'safety_recovery_decisions':'decision_id,capture_id,expected_revision,mode,evidence,actor,result',
            'safety_diagnostics':'id,code,source_id,recorded_at,details',
            'eefocus_identity_bindings':'binding_id,source_id,alias_url,canonical_url,evidence,event_id',
        }
        for table,fields in columns.items():c.execute('SELECT '+fields+' FROM '+table+' LIMIT 0')
        return row['safety_epoch']
    except sqlite3.Error as exc:
        raise SafetyError('safety schema unavailable') from exc


def bump(c):
    c.execute('UPDATE safety_meta SET safety_epoch=safety_epoch+1 WHERE singleton=1')


def diagnostic(c, code, source_id, details):
    """One replaceable bounded operational diagnostic per supported condition."""
    if code not in ('safety_merge_deferred','safety_capacity_paused'):raise ValueError('unknown diagnostic')
    value=encoded(details)
    if len(value.encode())>4096:value=encoded(dict(summary='diagnostic detail exceeded bound'))
    c.execute('INSERT INTO safety_diagnostics VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source_id=excluded.source_id,recorded_at=excluded.recorded_at,details=excluded.details',
              (code,code,source_id,core.stamp(),value))


def limits():
    configured = core.config().get('safety_limits', {})
    result=dict(LIMITS)
    for key,value in configured.items():
        if key not in LIMITS:continue
        value=int(value)
        if value<0:raise Integrity('negative safety limit')
        # The reservation is calibrated to this supported maximum. Configuration
        # can tighten work/account bounds or increase recovery headroom, never
        # silently expand workload beyond the measured reservation.
        result[key]=max(LIMITS[key],value) if key=='headroom_bytes' else min(LIMITS[key],value)
    return result


def reserve_capacity(c, amount, reservation_id, kind):
    cfg = limits()
    # Account for every operational data file, allocated pages, outstanding
    # reservations and an additional WAL/checkpoint peak, not just evidence.
    files = sum(p.stat().st_size for p in (core.ROOT/'data').glob('*') if p.is_file())
    allocated = c.execute('PRAGMA page_count').fetchone()[0]*c.execute('PRAGMA page_size').fetchone()[0]
    wal = core.ROOT/'data/events.sqlite3-wal'
    peak = wal.stat().st_size if wal.exists() else 0
    outstanding = c.execute('SELECT COALESCE(SUM(bytes),0) FROM safety_capacity').fetchone()[0]
    used = max(files, allocated)+peak+outstanding
    free = shutil.disk_usage(core.ROOT/'data').free
    if used+amount+cfg['headroom_bytes'] > cfg['account_bytes'] or free < amount+cfg['headroom_bytes']:
        raise Capacity('insufficient durable capture/recovery headroom')
    c.execute('INSERT INTO safety_capacity VALUES(?,?,?)', (reservation_id, amount, kind))


@dataclass(frozen=True)
class Capture:
    id: str
    owner: str
    revision: int


def begin_capture(source):
    capture_id, owner = uid('capture'), uid('owner')
    try:
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE')
            assert_schema(c)
            if c.execute(f'SELECT 1 FROM safety_capture_runs WHERE capture_state IN {UNFINISHED}').fetchone():
                raise SafetyError('unfinished source capture requires recovery')
            reserve_capacity(c, CAPTURE_RESERVE, capture_id, 'inventory')
            c.execute('INSERT INTO safety_capture_runs(capture_id,source_id,inventory_url,owner,started_at,capture_state,revision,reserved_capacity) VALUES(?,?,?,?,?,\'reserved\',1,?)',
                      (capture_id,source['id'],source['url'],owner,core.stamp(),CAPTURE_RESERVE))
            bump(c)
    except Capacity:
        # A diagnostic cannot replace the original capacity error or consume an
        # unbounded ledger. Physical storage failure may prevent this tiny write.
        try:
            with core.db() as c:
                c.execute('BEGIN IMMEDIATE')
                diagnostic(c,'safety_capacity_paused',source['id'],dict(reserve_bytes=CAPTURE_RESERVE))
        except sqlite3.Error:pass
        raise
    return Capture(capture_id,owner,1)


@contextmanager
def optional_capacity():
    reservation=uid('optional')
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        assert_schema(c)
        reserve_capacity(c,4_000_000+2*MIB,reservation,'optional_detail')
    try:
        yield
    finally:
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM safety_capacity WHERE reservation_id=?',(reservation,))


def transition(c, capture, state, **values):
    cols = ['capture_state=?','revision=revision+1']+[k+'=?' for k in values]
    n = c.execute('UPDATE safety_capture_runs SET '+','.join(cols)+' WHERE capture_id=? AND owner=? AND revision=? AND capture_state<>\'safety_finalized\'',
                  (state,*values.values(),capture.id,capture.owner,capture.revision)).rowcount
    if n != 1:
        raise Conflict('capture ownership/revision changed')
    return Capture(capture.id,capture.owner,capture.revision+1)


def claim(capture):
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT capture_state FROM safety_capture_runs WHERE capture_id=?',(capture.id,)).fetchone()
        if not row or row[0] != 'reserved':
            raise Conflict('capture not reserved')
        return transition(c,capture,'acquiring')


def blob(c, body, fmt='html'):
    raw = body if isinstance(body,bytes) else body.encode()
    key = digest(raw)
    previous = c.execute('SELECT body FROM safety_evidence_blobs WHERE digest=?',(key,)).fetchone()
    if previous and bytes(previous[0]) != raw:
        raise Integrity('evidence digest collision')
    if not previous:
        c.execute('INSERT INTO safety_evidence_blobs VALUES(?,?,?,?,?)',(key,raw,fmt,'eefocus_safety_v1',len(raw)))
    return key


def retain(capture, html, final, trace):
    from .collectors import ResponseText
    captured = isinstance(html, ResponseText)
    raw = html.response_bytes if captured else html.encode()
    provenance = dict(final_url=final, trace=trace)
    if captured:
        if not isinstance(raw, bytes) or raw.decode(html.response_encoding, 'replace') != html:
            raise Integrity('response bytes and decoded evidence disagree')
        provenance['response_entity'] = dict(version=1, encoding=html.response_encoding, errors='replace')
    if len(raw) > limits()['inventory_bytes']:
        raise Capacity('complete capture exceeds retained inventory bound')
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        run=c.execute('SELECT * FROM safety_capture_runs WHERE capture_id=?',(capture.id,)).fetchone()
        if not run or run['capture_state']!='acquiring' or run['owner']!=capture.owner or run['revision']!=capture.revision:
            raise Conflict('only the live acquiring owner may retain its accepted response')
        key = blob(c,raw)
        return transition(c,capture,'captured',response_digest=key,provenance=encoded(provenance))


def known_failure(capture, exc, metrics=None):
    """Only the live acquisition owner can attest caught no-response failure."""
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM safety_capture_runs WHERE capture_id=?',(capture.id,)).fetchone()
        if row['capture_state'] != 'acquiring' or row['response_digest']:
            raise Conflict('accepted response cannot be replaced by a failure')
        receipt = dict(version=1,capture_id=capture.id,outcome='known_acquisition_failure',
                       transport_failure=type(exc).__name__,transport_message=str(exc)[:500],
                       inventory_url=row['inventory_url'],requests_attempted=(metrics or {}).get('http_requests_attempted',0),
                       proof='live_owner_caught_terminal_failure_before_adapter_response',observations_new=0,guards_created=0)
        transition(c,capture,'safety_finalized',failure_code=type(exc).__name__,receipt=encoded(receipt),completed_at=core.stamp())
        c.execute('DELETE FROM safety_capacity WHERE reservation_id=?',(capture.id,))
        bump(c)
        return receipt


def mark_unknown(capture, failure):
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM safety_capture_runs WHERE capture_id=?',(capture.id,)).fetchone()
        if row and row['capture_state'] == 'safety_finalized':
            return json.loads(row['receipt'])
        if row and row['capture_state'] == 'acquiring':
            current=Capture(capture.id,row['owner'],row['revision'])
            transition(c,current,'recovery_required',failure_code=failure)
            bump(c)


def direct_targets(c, observation):
    targets = {}
    for row in c.execute('SELECT a.*,b.alias_url,b.canonical_url FROM eefocus_target_anchors a JOIN eefocus_identity_bindings b USING(binding_id) WHERE b.source_id=? AND b.alias_url=?',
                         (observation['source_id'],observation['alias_url'])):
        targets.setdefault(row['event_id'],[]).append(dict(row))
    # Direct source links are evidence; no title/numeric/chained lookup.
    for row in c.execute('SELECT es.*,e.start_at FROM event_sources es JOIN events e ON e.id=es.event_id WHERE es.source_id=? AND es.url=?',
                         (observation['source_id'],observation['alias_url'])):
        targets.setdefault(row['event_id'],[]).append({**dict(row),'occurrence':encoded([(row['start_at'] or '')[:10]]),'mode':'direct_source_link'})
    return targets


def target(c, observation, event_id, evidence, coalesce=True):
    if c.execute('SELECT 1 FROM safety_observation_targets WHERE observation_id=? AND event_id=?',(observation['observation_id'],event_id)).fetchone():
        return 0,0
    occurrence = encoded(sorted({day for row in evidence for day in json.loads(row['occurrence']) if day}))
    if len(encoded(dict(event_id=event_id,source_id=observation['source_id'],alias_url=observation['alias_url'],occurrence=occurrence)).encode())+1024>limits()['row_bytes']:
        raise Capacity('guard/target row metadata bound exceeded')
    prior_resolution = c.execute("SELECT 1 FROM event_safety_guards WHERE source_id=? AND event_id=? AND alias_url=? AND state='resolved' LIMIT 1",
                                 (observation['source_id'],event_id,observation['alias_url'])).fetchone()
    reason = 'cancellation_generation_ambiguous_after_reinstatement' if prior_resolution else 'unconfirmed_cancellation_for_historical_identity'
    guard = c.execute("SELECT * FROM event_safety_guards WHERE source_id=? AND event_id=? AND alias_url=? AND occurrence=? AND reason=? AND state='active' ORDER BY rowid LIMIT 1",
                      (observation['source_id'],event_id,observation['alias_url'],occurrence,reason)).fetchone() if coalesce else None
    guard_id = guard['guard_id'] if guard else uid('guard')
    if not guard:
        c.execute('INSERT INTO event_safety_guards VALUES(?,?,?,?,?,?,\'active\',1,?,?,NULL,NULL)',
                  (guard_id,observation['source_id'],event_id,occurrence,observation['alias_url'],reason,digest(observation['observation_id']),core.stamp()))
    c.execute('INSERT INTO safety_guard_members VALUES(?,?)',(guard_id,observation['observation_id']))
    if guard:
        members = [r[0] for r in c.execute('SELECT observation_id FROM safety_guard_members WHERE guard_id=? ORDER BY observation_id',(guard_id,))]
        c.execute('UPDATE event_safety_guards SET revision=revision+1,evidence_set_digest=? WHERE guard_id=?',(digest(encoded(members)),guard_id))
    refs=[{key:row[key] for key in ('binding_id','event_id','raw_id','source_id','url','canonical_url','occurrence','mode') if key in row} for row in evidence]
    c.execute('INSERT INTO safety_observation_targets VALUES(?,?,?,?,?,?)',
              (observation['observation_id'],event_id,observation['source_id'],occurrence,encoded(dict(direct_evidence_count=len(refs))),guard_id))
    for ref in refs:
        if len(encoded(ref).encode())>limits()['row_bytes']:raise Capacity('target evidence metadata bound exceeded')
        c.execute('INSERT INTO safety_target_evidence VALUES(?,?,?,?)',(observation['observation_id'],event_id,digest(encoded(ref)),encoded(ref)))
    bump(c)
    return int(not guard),int(bool(guard))


def targeting(c, observation_id):
    count=c.execute('SELECT COUNT(*) FROM safety_observation_targets WHERE observation_id=?',(observation_id,)).fetchone()[0]
    c.execute('UPDATE safety_observations SET targeting_state=?,targeting_revision=targeting_revision+1 WHERE observation_id=?',
              ('unlinked' if not count else 'linked_single' if count==1 else 'linked_ambiguous',observation_id))


def finalize(capture):
    """Replay exact retained bytes; commit all targets and receipt atomically."""
    from bs4 import BeautifulSoup
    from . import eefocus, collectors
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        assert_schema(c)
        run=c.execute('SELECT * FROM safety_capture_runs WHERE capture_id=?',(capture.id,)).fetchone()
        if not run:raise Integrity('missing capture')
        if run['capture_state']=='safety_finalized':return json.loads(run['receipt'])
        if run['capture_state']!='captured':raise SafetyError('exact retained capture required')
        if run['revision']!=capture.revision or run['owner']!=capture.owner:raise Conflict('capture ownership/revision changed')
        stored=c.execute('SELECT * FROM safety_evidence_blobs WHERE digest=?',(run['response_digest'],)).fetchone()
        if not stored or digest(bytes(stored['body']))!=run['response_digest']:raise Integrity('capture bytes corrupt or absent')
        provenance=json.loads(run['provenance'])
        response_entity=provenance.get('response_entity')
        if response_entity is None:
            # Legacy captures and explicit offline fixtures retained UTF-8 text.
            # Preserve their immutable bytes; do not claim original HTTP bytes.
            html=bytes(stored['body']).decode('utf-8')
        else:
            if (not isinstance(response_entity,dict) or response_entity.get('version')!=1
                    or not isinstance(response_entity.get('encoding'),str)
                    or response_entity.get('errors')!='replace'):
                raise Integrity('capture response decoding metadata invalid')
            try:html=bytes(stored['body']).decode(response_entity['encoding'],'replace')
            except (LookupError,TypeError,ValueError) as exc:
                raise Integrity('capture response encoding unavailable') from exc
        receipt=dict(version=1,capture_id=capture.id,observations_new=0,observations_replayed=0,guards_created=0,guards_changed=0,
                     unlinked_observations=0,ambiguous_targets=0,safety_update_failed=False)
        try:
            observations=eefocus.cancellation_observations(BeautifulSoup(html,'html.parser'),provenance['final_url'])
            outcome='observed_and_applied' if observations else 'no_qualifying_observations'
        except collectors.SourceError:
            observations=[];outcome='rejected_inventory'
        cfg=limits()
        if len(observations)>cfg['cards']:raise Capacity('observation bound exceeded; retained capture remains fenced')
        total_edges=0
        for notice in observations:
            if len(encoded(notice).encode())>cfg['metadata_bytes']:raise Capacity('observation metadata bound exceeded')
            observation=dict(observation_id=digest(capture.id+'|'+notice['card_key']+'|cancelled'),capture_id=capture.id,
                             source_id=run['source_id'],observed_at=run['started_at'],evidence_digest=run['response_digest'],**notice)
            immutable=(observation['observation_id'],capture.id,run['source_id'],notice['alias_url'],notice['card_key'],'cancelled',run['started_at'],
                       encoded(notice['occurrence']),notice['status_text'],'current_whole_event',run['response_digest'],encoded(notice))
            prior=c.execute('SELECT * FROM safety_observations WHERE observation_id=?',(observation['observation_id'],)).fetchone()
            if prior:
                if tuple(prior)[:12]!=immutable:raise Integrity('observation ID reused with different evidence')
                receipt['observations_replayed']+=1
            else:
                collision=c.execute('SELECT observation_id FROM safety_observations WHERE capture_id=? AND card_key=? AND kind=?',(capture.id,notice['card_key'],'cancelled')).fetchone()
                if collision:raise Integrity('card observation collision')
                c.execute('INSERT INTO safety_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,\'unlinked\',1)',immutable)
                receipt['observations_new']+=1
            # An unfinished retained capture must complete its original mandatory
            # disposition transaction. Finalized replay returned above and never
            # performs this target discovery or rewrites resolved dispositions.
            targets=direct_targets(c,observation)
            total_edges+=sum(len(edges) for edges in targets.values())
            if total_edges>cfg['target_edges']:raise Capacity('direct-target bound exceeded; no truncated success')
            writes=0
            for event_id,evidence in targets.items():
                new,changed=target(c,observation,event_id,evidence,coalesce=not notice.get('cancelled_again'))
                receipt['guards_created']+=new;receipt['guards_changed']+=changed
                writes+=new+changed
            if not prior or writes:targeting(c,observation['observation_id'])
            receipt['unlinked_observations']+=int(not targets)
            receipt['ambiguous_targets']+=int(len(targets)>1)
        receipt['outcome']=outcome
        receipt['active_guards']=c.execute("SELECT COUNT(*) FROM event_safety_guards WHERE source_id=? AND state='active'",(run['source_id'],)).fetchone()[0]
        transition(c,capture,'safety_finalized',receipt=encoded(receipt),completed_at=core.stamp())
        c.execute('DELETE FROM safety_capacity WHERE reservation_id=?',(capture.id,))
        bump(c)
        return receipt


def replay_capture(capture_id):
    with core.db() as c:
        row=c.execute('SELECT * FROM safety_capture_runs WHERE capture_id=?',(capture_id,)).fetchone()
        if not row:raise LookupError('capture absent')
        capture=Capture(capture_id,row['owner'],row['revision'])
    return finalize(capture)


def anchor(c, source, item, event_id, raw_id):
    """Exact item binding IDs only; atomic with canonical ingest and vetoes."""
    assert_schema(c)
    ids=item.get('_identity_binding_ids',[])
    if not ids:raise Integrity('admission missing exact identity binding IDs')
    cfg=limits()
    if len(ids)>cfg['bindings'] or len(encoded(item).encode())>cfg['target_bytes']:
        raise Capacity('retained target/anchor workload bound exceeded')
    marks=','.join('?' for _ in ids)
    prospective=c.execute(f'SELECT COUNT(*) FROM safety_observations so WHERE so.source_id=? AND so.alias_url IN (SELECT alias_url FROM eefocus_identity_bindings WHERE binding_id IN ({marks})) AND NOT EXISTS(SELECT 1 FROM safety_observation_targets st WHERE st.observation_id=so.observation_id AND st.event_id=?)',
                          (source['id'],*ids,event_id)).fetchone()[0]
    if prospective>cfg['target_edges']:raise Capacity('late-anchor disposition workload bound exceeded')
    amount=4*(cfg['target_bytes']+len(ids)*cfg['row_bytes']+5*prospective*cfg['row_bytes'])+2*MIB
    if amount>cfg['anchor_bytes']:raise Capacity('late-anchor reservation exceeds configured operation ceiling')
    reservation=uid('anchor-reserve')
    reserve_capacity(c,amount,reservation,'late_anchor')
    for binding_id in ids:
        row=c.execute('SELECT * FROM eefocus_identity_bindings WHERE binding_id=?',(binding_id,)).fetchone()
        if not row or row['source_id']!=source['id'] or row['canonical_url']!=item['url']:raise Integrity('exact binding/source/canonical mismatch')
        evidence=json.loads(row['evidence']);days=evidence.get('occurrence_dates',[])
        from . import eefocus
        if (evidence.get('schema')!=eefocus.SCHEMA or not evidence.get('body_digest')
                or eefocus.heading(evidence.get('title'))!=eefocus.heading(item['title'])
                or evidence.get('canonical_url')!=item['url']):
            raise Integrity('exact admitted identity evidence incomplete')
        eefocus.trace_identity(row['alias_url'],item['url'],evidence.get('trace'))
        expected_days=[item['start_at'][:10]] if item.get('start_at') else []
        if days!=expected_days:raise Integrity('exact occurrence binding mismatch')
        link=c.execute('SELECT 1 FROM event_sources WHERE source_id=? AND url=? AND event_id=? AND raw_id=?',(source['id'],item['url'],event_id,raw_id)).fetchone()
        if not link:raise Integrity('exact successful ingest link missing')
        previous=c.execute('SELECT * FROM eefocus_target_anchors WHERE binding_id=?',(binding_id,)).fetchone()
        if previous:
            if previous['event_id']!=event_id or previous['raw_id']!=raw_id or previous['occurrence']!=encoded(days):raise Integrity('immutable anchor retarget forbidden')
            continue
        if row['event_id'] and row['event_id']!=event_id:raise Integrity('legacy binding retarget forbidden')
        c.execute('INSERT INTO eefocus_target_anchors VALUES(?,?,?,?,?,?)',(binding_id,event_id,raw_id,encoded(days),row['evidence'],core.stamp()))
        c.execute('UPDATE eefocus_identity_bindings SET event_id=? WHERE binding_id=? AND event_id IS NULL',(event_id,binding_id))
        observations=c.execute('SELECT * FROM safety_observations WHERE source_id=? AND alias_url=?',(source['id'],row['alias_url'])).fetchall()
        if len(observations)>limits()['target_edges']:raise Capacity('late-anchor adjudication workload bound exceeded')
        for old in observations:
            observation=dict(old)
            if c.execute('SELECT 1 FROM safety_observation_targets WHERE observation_id=? AND event_id=?',(old['observation_id'],event_id)).fetchone():continue
            captured=eefocus.verified_cancellation_occurrence(json.loads(old['metadata']))
            if not captured or not days:raise SafetyError('pending target occurrence unknown; admission rolled back')
            if captured!=json.loads(old['occurrence']):raise Integrity('retained cancellation occurrence contradicts evidence roles')
            result='applicable' if captured==days else 'not_applicable'
            operation=digest(old['observation_id']+'|'+binding_id+'|'+event_id)
            if c.execute('SELECT 1 FROM safety_target_adjudications WHERE adjudication_id=?',(operation,)).fetchone():continue
            c.execute('INSERT INTO safety_target_adjudications VALUES(?,?,?,?,?,?,?,?)',
                      (operation,old['observation_id'],binding_id,event_id,old['targeting_revision'],result,row['evidence'],core.stamp()))
            if result=='applicable':
                target(c,observation,event_id,[dict(c.execute('SELECT * FROM eefocus_target_anchors WHERE binding_id=?',(binding_id,)).fetchone())])
                targeting(c,old['observation_id'])
    c.execute('DELETE FROM safety_capacity WHERE reservation_id=?',(reservation,))


def projection(c, rows):
    epoch=assert_schema(c)
    if not rows:return epoch
    marks=','.join('?' for _ in rows);ids=[r['id'] for r in rows]
    guards={}
    for row in c.execute(f"SELECT event_id,guard_id,reason FROM event_safety_guards WHERE state='active' AND event_id IN ({marks})",ids):
        guards.setdefault(row['event_id'],[]).append(dict(row))
    fenced={r[0] for r in c.execute(f'SELECT DISTINCT es.event_id FROM event_sources es JOIN safety_capture_runs sc ON sc.source_id=es.source_id WHERE sc.capture_state IN {UNFINISHED} AND es.event_id IN ({marks})',ids)}
    for row in rows:
        details=json.loads(row.get('details') or '{}') if isinstance(row.get('details'),str) else row.get('details') or {}
        active=guards.get(row['id'],[]);unavailable=row['id'] in fenced
        held=any(details.get(k) for k in ('review_hold','attendance_conflict','time_conflict'))
        row['stored_status']=row['status']
        row['effective_status']='needs_review' if (active or unavailable or held) and row['status']=='scheduled' else row['status']
        row['status']=row['effective_status']
        row['planning_eligible']=bool(row.get('start_at') and row['status']=='scheduled' and not active and not unavailable and not held)
        row['safety_epoch']=epoch
        row['safety']={'available':not unavailable,'guard_count':len(active),'warning':UNAVAILABLE if unavailable else WARNING if active else '',
                       'guards':active[:16]}
    return epoch


def fenced(c):
    assert_schema(c)
    return bool(c.execute(f'SELECT 1 FROM safety_capture_runs WHERE capture_state IN {UNFINISHED} LIMIT 1').fetchone())


def protected(c, event_id):
    return bool(c.execute('SELECT 1 FROM eefocus_identity_bindings WHERE event_id=? UNION ALL SELECT 1 FROM eefocus_target_anchors WHERE event_id=? UNION ALL SELECT 1 FROM safety_observation_targets WHERE event_id=? UNION ALL SELECT 1 FROM event_safety_guards WHERE event_id=? UNION ALL SELECT 1 FROM event_sources es JOIN eefocus_identity_bindings b ON b.source_id=es.source_id AND b.canonical_url=es.url WHERE es.event_id=? LIMIT 1',(event_id,)*5).fetchone())


def ai_expectation(c, raw_id=None, event_id=None):
    assert_schema(c)
    raw=dict(c.execute('SELECT * FROM raw_items WHERE id=?',(raw_id,)).fetchone()) if raw_id else None
    rows=[dict(r) for r in c.execute('SELECT e.* FROM events e JOIN event_sources es ON es.event_id=e.id WHERE es.raw_id=? ORDER BY e.id',(raw_id,))] if raw_id else [dict(r) for r in c.execute('SELECT * FROM events WHERE id=?',(event_id,))]
    authority=encoded(rows)
    projection(c,rows)
    blocked=any(r['status'] in ('cancelled','not_event') or not r['safety']['available'] or r['safety']['guard_count'] or any(json.loads(r['details'] or '{}').get(k) for k in ('review_hold','time_conflict','attendance_conflict')) for r in rows)
    ids=[r['id'] for r in rows]
    marks=','.join('?' for _ in ids) or 'NULL'
    source_authority=[tuple(r) for r in c.execute(f'SELECT a.binding_id,a.event_id,a.occurrence,b.evidence FROM eefocus_target_anchors a JOIN eefocus_identity_bindings b USING(binding_id) WHERE a.event_id IN ({marks}) ORDER BY a.binding_id',ids)]
    return dict(raw_hash=raw['content_hash'] if raw else None,authority=authority,source_authority=source_authority,
                links=[tuple(r) for r in c.execute('SELECT event_id,source_id,url,raw_id FROM event_sources WHERE raw_id=? ORDER BY source_id,url',(raw_id,))] if raw_id else [],
                epoch=assert_schema(c),blocked=blocked)


def guard_snapshot(guard_ids):
    if not guard_ids or len(guard_ids)>16 or len(set(guard_ids))!=len(guard_ids):
        raise Integrity('resolution requires 1–16 distinct named guards')
    with core.db() as c:
        c.execute('BEGIN')
        assert_schema(c)
        rows=[]
        for guard_id in guard_ids:
            row=c.execute('SELECT * FROM event_safety_guards WHERE guard_id=?',(guard_id,)).fetchone()
            if not row or row['state']!='active':raise Conflict('named guard not active')
            rows.append(dict(row))
        return rows


@dataclass(frozen=True)
class VerifiedResolution:
    """Internal authority token constructed only after parser/transport validation."""
    source_id: str
    event_id: str
    body: str
    evidence: str
    authority: str


def resolution_authority(c,event_id):
    row=c.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
    if not row:raise Integrity('resolution canonical target absent')
    links=[tuple(r) for r in c.execute('SELECT source_id,url,raw_id FROM event_sources WHERE event_id=? ORDER BY source_id,url',(event_id,))]
    anchors=[tuple(r) for r in c.execute('SELECT binding_id,occurrence,evidence FROM eefocus_target_anchors WHERE event_id=? ORDER BY binding_id',(event_id,))]
    return encoded(dict(event=dict(row),links=links,anchors=anchors))


def resolve_verified(resolution_id, expectations, verified):
    if not isinstance(verified,VerifiedResolution):raise Integrity('internally verified source evidence required')
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        assert_schema(c)
        immutable=encoded(expectations)
        prior=c.execute('SELECT * FROM safety_resolutions WHERE resolution_id=?',(resolution_id,)).fetchone()
        proof=encoded(dict(body=verified.body,evidence=json.loads(verified.evidence),authority=verified.authority))
        if prior:
            if prior['expectations']!=immutable or prior['evidence_digest']!=digest(proof):raise Integrity('resolution ID reused')
            return json.loads(prior['result'])
        if len(immutable.encode())>limits()['row_bytes'] or len(proof.encode())>2_000_000:
            raise Capacity('resolution evidence/metadata bound exceeded')
        reservation=uid('resolution');reserve_capacity(c,4*2_000_000+2*MIB,reservation,'resolution')
        key=blob(c,proof,'resolution')
        if resolution_authority(c,verified.event_id)!=verified.authority:
            raise Conflict('source/canonical authority changed during resolution verification')
        for expected in expectations:
            if expected['source_id']!=verified.source_id or expected['event_id']!=verified.event_id:raise Integrity('resolution target/source mismatch')
            current=c.execute('SELECT * FROM event_safety_guards WHERE guard_id=?',(expected['guard_id'],)).fetchone()
            if not current or any(current[key]!=expected[key] for key in ('source_id','event_id','alias_url','occurrence')):
                raise Conflict('named guard applicability changed')
            n=c.execute("UPDATE event_safety_guards SET state='resolved',revision=revision+1,resolution_id=?,resolved_at=? WHERE guard_id=? AND source_id=? AND event_id=? AND state='active' AND revision=? AND evidence_set_digest=?",
                        (resolution_id,core.stamp(),expected['guard_id'],verified.source_id,verified.event_id,expected['revision'],expected['evidence_set_digest'])).rowcount
            if n!=1:raise Conflict('guard changed since resolution snapshot')
        result=dict(resolved_guard_ids=[e['guard_id'] for e in expectations])
        c.execute('INSERT INTO safety_resolutions VALUES(?,?,?,?,?,?,?,?,?)',(resolution_id,'explicit_same_occurrence_reinstatement',verified.source_id,verified.event_id,immutable,key,'internal_source_parser',core.stamp(),encoded(result)))
        c.execute('DELETE FROM safety_capacity WHERE reservation_id=?',(reservation,))
        bump(c)
        return result


def recover_capture(capture_id, expected_revision, mode, decision_id, actor):
    """Maintainer API supplies authenticated actor, never fixture provenance.

    No submitted response/boolean can prove a lost acquisition harmless. Initial
    recovery supports retained exact bytes, reserved-owner revocation and an
    explicit unresolved decision. Lost-response uncertainty has no escape hatch.
    """
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        assert_schema(c)
        row=c.execute('SELECT * FROM safety_capture_runs WHERE capture_id=?',(capture_id,)).fetchone()
        if not row:raise LookupError('capture absent')
        original=c.execute('SELECT * FROM safety_recovery_decisions WHERE decision_id=?',(decision_id,)).fetchone()
        if original:
            if (original['capture_id'],original['expected_revision'],original['mode'],original['actor'])!=(capture_id,expected_revision,mode,actor):raise Integrity('recovery ID reused')
            if mode=='replay_exact_capture' and row['capture_state']=='safety_finalized':return json.loads(row['receipt'])
            return json.loads(original['result'])
        if row['revision']!=expected_revision:raise Conflict('recovery expected revision changed')
        capture=Capture(capture_id,row['owner'],row['revision'])
        if mode=='prove_not_started':
            if row['capture_state']!='reserved':raise Integrity('start permission already issued; not_started cannot be proven')
            receipt=dict(version=1,capture_id=capture_id,outcome='not_started',proof='reserved_owner_revoked_by_CAS',observations_new=0,guards_created=0)
            transition(c,capture,'safety_finalized',receipt=encoded(receipt),completed_at=core.stamp(),recovery_decision_id=decision_id)
            c.execute('DELETE FROM safety_capacity WHERE reservation_id=?',(capture_id,));bump(c)
            result=receipt
        elif mode=='retain_unresolved':
            if row['capture_state']=='safety_finalized':raise Conflict('finalized capture cannot reopen')
            transition(c,capture,'recovery_required',failure_code='trusted_outcome_unavailable',recovery_decision_id=decision_id)
            bump(c);result=dict(capture_id=capture_id,state='recovery_required')
        elif mode=='replay_exact_capture':
            if row['capture_state']=='safety_finalized':return json.loads(row['receipt'])
            if row['capture_state']!='captured' or not row['response_digest']:raise Integrity('no trusted exact retained response')
            # Record decision first; deterministic replay operates on the same
            # immutable capture after this short writer transaction closes.
            result=dict(capture_id=capture_id,state='replay_authorized')
            transition(c,capture,'captured',recovery_decision_id=decision_id)
        elif mode=='prove_no_accepted_inventory':
            raise Integrity('no durable terminal transport proof for this lost capture')
        else:raise ValueError('unsupported recovery mode')
        c.execute('INSERT INTO safety_recovery_decisions VALUES(?,?,?,?,?,?,?,?)',
                  (decision_id,capture_id,expected_revision,mode,encoded(dict(response_digest=row['response_digest'],provenance=row['provenance'])),actor,encoded(result),core.stamp()))
    return replay_capture(capture_id) if mode=='replay_exact_capture' else result


def replay_ready():
    """Recovery stays routable when new acquisitions hit the collection cap."""
    with core.db() as c:
        assert_schema(c)
        ids=[r[0] for r in c.execute("SELECT capture_id FROM safety_capture_runs WHERE capture_state='captured'")]
    results=[]
    for capture_id in ids:
        try:results.append(replay_capture(capture_id))
        except SafetyError as exc:results.append(dict(capture_id=capture_id,error=exc.code))
    return results


def reviewed_disassociation(resolution_id, expectations, current_binding_id, actor, observation_ids, review_reason):
    """Explicit human adjudication, never inference from an alias's newer owner.

    The authenticated maintainer must address the exact retained observations
    and explain the reviewed disposition. Different historical occurrences are
    supporting references, not automatic proof of disassociation.
    """
    if not actor or not expectations or not observation_ids or not 20<=len(review_reason.strip())<=2000:
        raise Integrity('authenticated reviewed reason and exact observation scope required')
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        assert_schema(c)
        anchor=c.execute('SELECT a.*,b.source_id,b.alias_url,b.canonical_url FROM eefocus_target_anchors a JOIN eefocus_identity_bindings b USING(binding_id) WHERE a.binding_id=?',(current_binding_id,)).fetchone()
        if not anchor:raise Integrity('review evidence must name a verified immutable target anchor')
        target_event=expectations[0]['event_id'];source=expectations[0]['source_id']
        members=sorted({r[0] for old in expectations for r in c.execute('SELECT observation_id FROM safety_guard_members WHERE guard_id=?',(old['guard_id'],))})
        if sorted(set(observation_ids))!=members:raise Integrity('review must address exact named guard observations')
        observations=[{k:v for k,v in dict(c.execute('SELECT * FROM safety_observations WHERE observation_id=?',(oid,)).fetchone()).items()
                       if k not in ('targeting_state','targeting_revision')} for oid in members]
        proof=encoded(dict(binding_id=current_binding_id,evidence=anchor['evidence'],occurrence=anchor['occurrence'],
                           observations=observations,review_reason=review_reason.strip()))
        prior=c.execute('SELECT * FROM safety_resolutions WHERE resolution_id=?',(resolution_id,)).fetchone()
        if prior:
            if prior['expectations']!=encoded(expectations) or prior['evidence_digest']!=digest(proof) or prior['actor']!=actor:raise Integrity('reviewed resolution ID reused')
            return json.loads(prior['result'])
        if len(encoded(expectations).encode())>limits()['row_bytes'] or len(proof.encode())>2_000_000:
            raise Capacity('reviewed resolution evidence/metadata bound exceeded')
        reservation=uid('reviewed-resolution');reserve_capacity(c,4*2_000_000+2*MIB,reservation,'reviewed_resolution')
        for old in expectations:
            current=c.execute('SELECT * FROM event_safety_guards WHERE guard_id=?',(old['guard_id'],)).fetchone()
            if not current or any(current[key]!=old[key] for key in ('source_id','event_id','alias_url','occurrence')):
                raise Conflict('reviewed immutable target expectations do not match stored guard')
            if (old['source_id']!=source or old['event_id']!=target_event or anchor['source_id']!=source
                    or anchor['alias_url']!=old['alias_url'] or anchor['event_id']==target_event
                    or not json.loads(anchor['occurrence']) or not json.loads(old['occurrence'])
                    or json.loads(anchor['occurrence'])==json.loads(old['occurrence'])):
                raise Integrity('direct same-alias different-occurrence disassociation evidence missing')
            n=c.execute("UPDATE event_safety_guards SET state='resolved',revision=revision+1,resolution_id=?,resolved_at=? WHERE guard_id=? AND source_id=? AND event_id=? AND state='active' AND revision=? AND evidence_set_digest=?",
                        (resolution_id,core.stamp(),old['guard_id'],source,target_event,old['revision'],old['evidence_set_digest'])).rowcount
            if n!=1:raise Conflict('reviewed target changed since snapshot')
        key=blob(c,proof,'reviewed_disassociation');result=dict(resolved_guard_ids=[r['guard_id'] for r in expectations])
        c.execute('INSERT INTO safety_resolutions VALUES(?,?,?,?,?,?,?,?,?)',(resolution_id,'authorized_reviewed_adjudication',source,target_event,encoded(expectations),key,actor,core.stamp(),encoded(result)))
        c.execute('DELETE FROM safety_capacity WHERE reservation_id=?',(reservation,))
        bump(c);return result
