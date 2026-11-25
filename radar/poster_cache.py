"""Pre-download public images of upcoming events as small local webp files.

Cards and details then read /events/static/posters/<sha256>.webp from this server
instead of waiting on (or being blocked from) the original host. Images are
decoded and re-encoded with Pillow, so only real pictures are stored, without
metadata. Run: python -m radar.poster_cache [--limit N]
"""
import argparse, hashlib, io, json, os, tempfile, time
from datetime import timedelta

import requests

from . import core
from .posters import NAME

PER_EVENT = 4               # the detail view shows a few images; the card uses the first
MAX_BYTES = 8 * 1024 * 1024
MAX_SIZE = (960, 2400)      # width, height in pixels after shrinking
MIN_SIDE = 100              # narrower or shorter than this is an icon, not a poster
QUALITY = 78
KEEP_DAYS = 30              # keep files of events that ended within this window
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36',
           'Accept': 'image/avif,image/webp,image/*,*/*;q=0.8'}


class NotPoster(ValueError):
    """A real picture, but an icon: remembered once and never downloaded again."""


def paths():
    return core.ROOT / 'static' / 'posters', core.ROOT / 'data' / 'poster-cache.json'


def load_state(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    images = data.get('images') if isinstance(data.get('images'), dict) else {}
    failures = data.get('failures') if isinstance(data.get('failures'), dict) else {}
    icons = data.get('icons') if isinstance(data.get('icons'), dict) else {}
    # Earlier runs recorded icons as retryable failures; they are simply not posters.
    for url in [u for u, f in failures.items() if isinstance(f, dict) and str(f.get('why', '')).startswith('too small')]:
        icons[url] = {'why': 'too small'}
        failures.pop(url)
    return {'images': images, 'failures': failures, 'icons': icons}


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def event_images(since):
    """(priority rank, start, page url, image urls) for events still worth showing."""
    rank = {'high': 0, 'medium': 1}
    with core.db() as c:
        rows = c.execute("SELECT url,start_at,end_at,priority,details FROM events WHERE status='scheduled'").fetchall()
    out = []
    for url, start, end, priority, details in rows:
        try:
            last = core._query_datetime(end or start) if (end or start) else None
            images = json.loads(details or '{}').get('images')
        except (ValueError, TypeError, AttributeError):
            continue
        if not last or last < since or not isinstance(images, list):
            continue
        images = [u for u in images if isinstance(u, str) and u.startswith('https://')]
        if images:
            out.append((rank.get(priority, 2), start or '', url or '', images))
    return sorted(out)


def encode(data):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 40_000_000
    with Image.open(io.BytesIO(data)) as im:
        im.draft('RGB', (MAX_SIZE[0] * 2, MAX_SIZE[1] * 2))   # JPEG: decode at a smaller scale
        im = ImageOps.exif_transpose(im)
        if min(im.size) < MIN_SIDE:
            raise NotPoster(f'icon {im.size[0]}x{im.size[1]}')
        im.thumbnail(MAX_SIZE, Image.LANCZOS)
        alpha = im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)
        im = im.convert('RGBA' if alpha else 'RGB')
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=QUALITY, method=4)
    return buf.getvalue()


def fetch(url, referer, session):
    with session.get(url, headers={**HEADERS, 'Referer': referer} if referer else HEADERS,
                     timeout=(5, 15), stream=True, allow_redirects=True) as res:
        if res.status_code != 200:
            raise ValueError(f'HTTP {res.status_code}')
        kind = res.headers.get('content-type', '').split(';')[0].strip().lower()
        if kind and not kind.startswith('image/') and kind != 'application/octet-stream':
            raise ValueError('not an image: ' + kind[:40])
        body = bytearray()
        for chunk in res.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                raise ValueError('too large')
    return bytes(body)


def run(limit=40, deadline=240.0, sleep=0.3, session=None):
    folder, state_path = paths()
    folder.mkdir(parents=True, exist_ok=True)
    state = load_state(state_path)
    images, failures, icons = state['images'], state['failures'], state['icons']
    started, clock = time.monotonic(), time.time()
    since = core._query_datetime(core.now()) - timedelta(days=KEEP_DAYS)
    wanted, session = event_images(since), session or requests.Session()
    current = core._query_datetime(core.now())
    stats = {'events': len(wanted), 'cached': 0, 'fetched': 0, 'icons': 0, 'failed': 0, 'skipped': 0, 'removed': 0}
    for _, _, page, urls in wanted:
        for url in urls[:PER_EVENT]:
            name = images.get(url)
            if isinstance(name, str) and NAME.fullmatch(name) and (folder / name).is_file():
                stats['cached'] += 1
                continue
            if url in icons:
                continue
            failure = failures.get(url) or {}
            if failure.get('next', 0) > clock:
                stats['skipped'] += 1
                continue
            if stats['fetched'] + stats['failed'] >= limit or time.monotonic() - started > deadline:
                stats['stop'] = 'limit'
                break
            try:
                out = encode(fetch(url, page, session))
                name = hashlib.sha256(out).hexdigest() + '.webp'
                if not (folder / name).is_file():
                    atomic_write(folder / name, out)
                images[url] = name
                failures.pop(url, None)
                stats['fetched'] += 1
            except NotPoster as exc:
                icons[url] = {'why': str(exc)}
                failures.pop(url, None)
                stats['icons'] += 1
            except Exception as exc:  # one bad image must not stop the run
                n = int(failure.get('n', 0)) + 1
                failures[url] = {'n': n, 'next': clock + min(7 * 86400, 3600 * 2 ** n), 'why': str(exc)[:80] or type(exc).__name__}
                stats['failed'] += 1
            time.sleep(sleep)
        if stats.get('stop'):
            break
    # Forget images no event needs any more and delete their files (never the reviewed ones).
    referenced = {u for _, _, _, urls in wanted for u in urls[:PER_EVENT]}
    for url in [u for u in images if u not in referenced]:
        images.pop(url)
    for table in (failures, icons):
        for url in [u for u in table if u not in referenced]:
            table.pop(url)
    try:
        reviewed = set(json.loads((folder / 'manifest.json').read_text()).values())
    except (OSError, ValueError, AttributeError):
        reviewed = set()
    keep = set(images.values()) | reviewed
    for path in folder.iterdir():
        if NAME.fullmatch(path.name) and path.name not in keep and path.is_file():
            path.unlink()
            stats['removed'] += 1
    atomic_write(state_path, json.dumps({'images': images, 'failures': failures, 'icons': icons,
                                         'updated': current.isoformat(timespec='seconds')},
                                        ensure_ascii=False, indent=1, sort_keys=True).encode())
    stats['seconds'] = round(time.monotonic() - started, 1)
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=40, help='images to download in this run')
    args = parser.parse_args()
    core.init()
    print(json.dumps(run(limit=args.limit), ensure_ascii=False))


if __name__ == '__main__':
    main()
