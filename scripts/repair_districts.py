"""Re-derive districts for stored events still marked 待确认.

Dry run by default; pass --apply to write. Only rows whose address now points to
exactly one district are changed; nothing else on the event is touched.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar import core  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with core.db() as c:
        if args.apply:
            c.execute('BEGIN IMMEDIATE')
        rows = c.execute("SELECT id,location FROM events WHERE district='待确认' AND trim(location)<>''").fetchall()
        changes = [(core.infer_district(loc), eid, loc) for eid, loc in rows]
        changes = [x for x in changes if x[0]]
        for district, eid, loc in changes[:20]:
            print(f'{district}\t{loc[:60]}')
        if args.apply:
            c.executemany("UPDATE events SET district=? WHERE id=? AND district='待确认'", [(d, e) for d, e, _ in changes])
    print(f"{'updated' if args.apply else 'would update'} {len(changes)} of {len(rows)} 待确认 events")


if __name__ == '__main__':
    main()
