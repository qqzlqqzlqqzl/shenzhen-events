"""Opt-in test cleanup retention; never import from a production entry point.

Only controlled Python cleanup is redirected. Native SQLite journals/WAL and
runtime-internal lifecycles retain their normal semantics. Retained test files
are not part of the CI artifact upload and must be handled as private output.
"""
import os
if os.environ.get('RADAR_RETAIN_TEST_FILES') == '1':
    try:
        # Test-only retention adapter. Product behavior/assertions stay unchanged.
        # SQLite's native journal/temp lifecycle is deliberately not intercepted.
        import os, pathlib, shutil, uuid, json, datetime, errno
        _BASE=pathlib.Path(os.environ['RADAR_TEST_RETENTION_ROOT']).resolve()
        _WORKSPACE=pathlib.Path(os.environ['RADAR_TEST_WORKSPACE']).resolve()
        if any(root == pathlib.Path('/') or not root.is_dir() for root in (_BASE, _WORKSPACE)):
            raise ValueError('explicit existing non-root test directories are required')
        _QUARANTINE=_BASE/'retained-test-cleanup'
        _QUARANTINE.mkdir(exist_ok=True)
        _real_rename=os.rename

        def _source_path(path,dir_fd=None):
            value=os.fsdecode(path)
            if dir_fd is not None and not os.path.isabs(value):
                value=os.path.join(os.readlink('/proc/self/fd/'+str(dir_fd)),value)
            value=pathlib.Path(os.path.abspath(value))
            # Follow parent links to prevent modifying a dependency via our venv symlink,
            # but do not follow the final component when preserving a symlink itself.
            actual=value.parent.resolve()/value.name
            if not (actual.is_relative_to(_BASE) or actual.is_relative_to(_WORKSPACE)):
                raise PermissionError('test cleanup outside explicit owned test roots is blocked')
            return value

        def _retain(path,kind,dir_fd=None):
            source=_source_path(path,dir_fd)
            if not os.path.lexists(source):raise FileNotFoundError(errno.ENOENT,os.strerror(errno.ENOENT),str(source))
            if kind=='rmdir' and (source.is_symlink() or not source.is_dir()):raise NotADirectoryError(str(source))
            if kind=='rmdir' and any(source.iterdir()):raise OSError(errno.ENOTEMPTY,os.strerror(errno.ENOTEMPTY),str(source))
            if kind=='unlink' and source.is_dir() and not source.is_symlink():raise IsADirectoryError(str(source))
            if kind=='rmtree' and source.is_symlink():raise OSError('Cannot call rmtree on a symbolic link')
            destination=_QUARANTINE/(uuid.uuid4().hex+'-'+source.name)
            _real_rename(source,destination)
            with (_BASE/'retained-test-cleanup.jsonl').open('a') as stream:
                stream.write(json.dumps({'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'requested':kind,'original':str(source),'retained':str(destination)})+'\n')

        def _unlink(path,*,dir_fd=None):return _retain(path,'unlink',dir_fd)
        def _rmdir(path,*,dir_fd=None):return _retain(path,'rmdir',dir_fd)
        def _rmtree(path,ignore_errors=False,onerror=None,*,onexc=None,dir_fd=None):
            try:return _retain(path,'rmtree',dir_fd)
            except Exception as error:
                if ignore_errors:return
                if onexc:return onexc(_rmtree,path,error)
                if onerror:
                    import sys
                    return onerror(_rmtree,path,sys.exc_info())
                raise
        os.unlink=_unlink
        os.remove=_unlink
        os.rmdir=_rmdir
        shutil.rmtree=_rmtree
    except Exception as error:
        import sys
        print('Test retention initialization failed: '+type(error).__name__, file=sys.stderr)
        os._exit(78)
