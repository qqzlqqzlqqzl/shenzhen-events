"""Serve only local poster files listed in a manifest; no remote image proxy.

Two manifests are merged: the hand-reviewed static/posters/manifest.json packaged
with the code, and data/poster-cache.json written by radar.poster_cache, which
pre-downloads public event images as small webp files. The same file records
cover images discovered on an event's own page (og:image) for events whose
source listed none.
"""
import json,re
from functools import lru_cache
from pathlib import Path

NAME=re.compile(r'[a-f0-9]{64}\.(?:webp|png|jpg)')
# Douban serves one poster in several sizes; treat them as the large one.
DOUBAN_POSTER=re.compile(r'^(https://img\d+\.doubanio\.com/p?view/event_poster/)(?:small|median|raw|large)(/public/[\w.-]+)$')

def canonical_image(url):
    m=DOUBAN_POSTER.match(url)
    return m.group(1)+'large'+m.group(2) if m else url

def image_list(details,discovered=None):
    """The event's pictures, cover first: the listed cover, page images, then a discovered one."""
    images=details.get('images') if isinstance(details.get('images'),list) else []
    cover=details.get('cover') if isinstance(details.get('cover'),str) else ''
    extra=[u for u in (cover,discovered) if isinstance(u,str) and u.startswith('https://')]
    if not extra and not any(isinstance(u,str) and DOUBAN_POSTER.match(u) for u in images):return images
    out=[]
    for url in ([cover] if cover in extra else [])+images+[u for u in extra if u!=cover]:
        if isinstance(url,str) and url.startswith('https://'):
            url=canonical_image(url)
            if url not in out:out.append(url)
    return out[:8]

def _mtime(path):
    try:return path.stat().st_mtime_ns
    except OSError:return None

def _entries(path,key=None):
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):return {}
    if key is not None:data=data.get(key) if isinstance(data,dict) else None
    return data if isinstance(data,dict) else {}

@lru_cache(maxsize=8)
def _discovered(root,cached_mtime):
    pages=_entries(Path(root)/'data'/'poster-cache.json','pages')
    return {page:row['image'] for page,row in pages.items()
            if isinstance(row,dict) and isinstance(row.get('image'),str) and row['image'].startswith('https://')}

def discovered(root):
    root=Path(root)
    return _discovered(str(root),_mtime(root/'data'/'poster-cache.json'))

@lru_cache(maxsize=8)
def _manifest(root,reviewed_mtime,cached_mtime):
    folder=Path(root)/'static'/'posters'
    merged={**_entries(Path(root)/'data'/'poster-cache.json','images'),**_entries(folder/'manifest.json')}
    return {url:'/events/static/posters/'+name for url,name in merged.items()
            if isinstance(url,str) and url.startswith('https://')
            and isinstance(name,str) and NAME.fullmatch(name)
            and (folder/name).is_file() and not (folder/name).is_symlink()}

def manifest(root):
    # Keyed by both files' mtimes so a background cache run shows up without a restart.
    root=Path(root)
    return _manifest(str(root),_mtime(root/'static'/'posters'/'manifest.json'),_mtime(root/'data'/'poster-cache.json'))

def display_details(details,root,page_url=None):
    # Never trust URLs supplied in a database cached_images field.
    result=dict(details) if isinstance(details,dict) else {}
    result['images']=image_list(result,discovered(root).get(page_url) if page_url else None)
    if not result['images'] and 'images' not in (details if isinstance(details,dict) else {}):result.pop('images')
    approved=manifest(str(root));images=result.get('images')
    result['cached_images']={url:approved[url] for url in images if isinstance(url,str) and url in approved} if isinstance(images,list) else {}
    return result
