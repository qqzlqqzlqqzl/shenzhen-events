"""Serve only deliberately reviewed, packaged poster assets; no remote image proxy."""
import json,re
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=4)
def manifest(root):
    folder=Path(root)/'static'/'posters'
    try:
        data=json.loads((folder/'manifest.json').read_text())
    except (OSError,ValueError):return {}
    if not isinstance(data,dict):return {}
    return {url:'/events/static/posters/'+name for url,name in data.items()
            if isinstance(url,str) and url.startswith('https://')
            and isinstance(name,str) and re.fullmatch(r'[a-f0-9]{64}\.(?:webp|png|jpg)',name)
            and (folder/name).is_file() and not (folder/name).is_symlink()}

def display_details(details,root):
    # Never trust URLs supplied in a database cached_images field.
    result=dict(details) if isinstance(details,dict) else {}
    approved=manifest(str(root));images=result.get('images')
    result['cached_images']={url:approved[url] for url in images if isinstance(url,str) and url in approved} if isinstance(images,list) else {}
    return result
