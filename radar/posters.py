"""Serve only local poster files listed in a manifest; no remote image proxy.

Two manifests are merged: the hand-reviewed static/posters/manifest.json packaged
with the code, and data/poster-cache.json written by radar.poster_cache, which
pre-downloads public event images as small webp files.
"""
import json,re
from functools import lru_cache
from pathlib import Path

NAME=re.compile(r'[a-f0-9]{64}\.(?:webp|png|jpg)')

def _mtime(path):
    try:return path.stat().st_mtime_ns
    except OSError:return None

def _entries(path,key=None):
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):return {}
    if key is not None:data=data.get(key) if isinstance(data,dict) else None
    return data if isinstance(data,dict) else {}

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

def display_details(details,root):
    # Never trust URLs supplied in a database cached_images field.
    result=dict(details) if isinstance(details,dict) else {}
    approved=manifest(str(root));images=result.get('images')
    result['cached_images']={url:approved[url] for url in images if isinstance(url,str) and url in approved} if isinstance(images,list) else {}
    return result
