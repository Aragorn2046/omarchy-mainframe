#!/usr/bin/env python3
"""Resolve Mainframe's theme and maintain the Omarchy picker previews."""
import json
import fcntl
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import subprocess
import syslog
import sys
import tempfile
import time

EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')
FOLLOW = 'follow-omarchy'
THEME_NAME = re.compile(r'[A-Za-z0-9._-]{1,64}\Z')


def valid_theme_name(name):
    return bool(THEME_NAME.fullmatch(name)) and name[0] not in '.-'


def preview_name(name):
    theme, ext = os.path.splitext(name)
    return ext in EXTENSIONS and valid_theme_name(theme)


def paths():
    home = Path(os.environ.get('HOME', str(Path.home())))
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    cache = Path(os.environ.get('XDG_CACHE_HOME') or home / '.cache')
    omarchy = Path(os.environ.get('OMARCHY_PATH') or '/usr/share/omarchy')
    return home, config / 'mainframe' / 'settings.json', cache / 'mainframe' / 'theme-previews', [home / '.config/omarchy/themes', omarchy / 'themes']


def preview(folder):
    try:
        files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: str(p))
        for ext in EXTENSIONS:
            for p in files:
                if p.name.lower() == 'preview' + ext:
                    return p
        return next((p for p in sorted((folder / 'backgrounds').iterdir(), key=lambda p: str(p))
                     if p.is_file() and p.suffix.lower() in EXTENSIONS), None)
    except OSError:
        return None


def themes(roots):
    found = {}
    for root in roots:
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if valid_theme_name(entry.name) and entry.is_dir() and entry.name != FOLLOW:
                found.setdefault(entry.name, []).append(entry)
    return found


SIGNATURE_NAME = '.theme-preview-signatures.json'


@contextmanager
def signatures_lock(parent_fd):
    fd = os.open('.theme-preview-state.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError('unsafe preview state lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def read_signatures(parent_fd):
    try:
        fd = os.open(SIGNATURE_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        with os.fdopen(fd, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_signatures(parent_fd, signatures):
    temp_name = f'.theme-preview-signatures-{os.getpid()}-{time.time_ns()}'
    fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(signatures, f, ensure_ascii=False)
            f.write('\n')
        os.replace(temp_name, SIGNATURE_NAME, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        try:
            os.unlink(temp_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def version_signature():
    # Installs are checkout links, with no separate version file. Hash the app
    # sources so a release update invalidates previews even without git metadata.
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for file in sorted(list(root.glob('*.qml')) + list((root / 'lib').glob('*.js')) + [root / 'theme_manager.py', root / 'tests/fake-local.py']):
        digest.update(file.name.encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def color_signature(folder, version):
    try:
        colors = (folder / 'colors.toml').read_bytes()
    except OSError:
        colors = b''
    return hashlib.sha256(version.encode() + b'\0' + colors).hexdigest()


def build_previews(destination, available, current):
    destination.parent.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    # XDG_CACHE_HOME may itself be a configured symlink; pin its target first.
    cache_fd = os.open(destination.parent.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            os.mkdir(destination.parent.name, dir_fd=cache_fd)
        except FileExistsError:
            pass
        parent_fd = os.open(destination.parent.name, flags, dir_fd=cache_fd)
    finally:
        os.close(cache_fd)
    try:
        try:
            info = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if info is not None and not stat.S_ISDIR(info.st_mode):
            # Rename the directory entry itself, never its target.
            bad_name = f'{destination.name}.bad-{time.time_ns()}'
            try:
                os.stat(bad_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(destination.name, bad_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            else:
                raise FileExistsError(bad_name)
            info = None
        if info is None:
            os.mkdir(destination.name, dir_fd=parent_fd)
        preview_fd = os.open(destination.name, flags, dir_fd=parent_fd)
        try:
            if os.fstat(preview_fd).st_uid != os.getuid():
                raise PermissionError('theme preview directory is not owned by the current user')
            with signatures_lock(parent_fd):
                previous = read_signatures(parent_fd)
                renders = previous.get('$renders', {})
                if not isinstance(renders, dict):
                    renders = {}
                active = set(available) | {FOLLOW}
                for name in list(renders):
                    if name in active or not valid_theme_name(name):
                        continue
                    target = name + '.png'
                    try:
                        info = os.stat(target, dir_fd=preview_fd, follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
                            os.unlink(target, dir_fd=preview_fd)
                    except FileNotFoundError:
                        pass
                    del renders[name]
                wanted = {}
                for name, folders in list(available.items()) + [(FOLLOW, [current])]:
                    if not valid_theme_name(name) or (name == FOLLOW and folders != [current]):
                        continue
                    rendered_name = name + '.png'
                    try:
                        info = os.stat(rendered_name, dir_fd=preview_fd, follow_symlinks=False)
                        generated = name in renders and stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    except OSError:
                        generated = False
                    if generated:
                        wanted[rendered_name] = None
                    else:
                        image = next((p for p in (preview(folder) for folder in folders) if p), None)
                        if image:
                            wanted[name + image.suffix.lower()] = image.absolute()
                for name in os.listdir(preview_fd):
                    if not preview_name(name):
                        continue
                    info = os.stat(name, dir_fd=preview_fd, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) and (name not in wanted or
                            os.readlink(name, dir_fd=preview_fd) != str(wanted[name])):
                        os.unlink(name, dir_fd=preview_fd)
                for name, image in wanted.items():
                    if image is None:
                        continue
                    try:
                        os.symlink(image, name, dir_fd=preview_fd)
                    except FileExistsError:
                        pass
                # Invalidate Omarchy's image list when an image changes in place.
                signatures = {}
                for name, image in wanted.items():
                    try:
                        image_stat = image.stat() if image is not None else os.stat(name, dir_fd=preview_fd, follow_symlinks=False)
                        signatures[name] = [str(image), image_stat.st_size, image_stat.st_mtime_ns, image_stat.st_ino]
                    except OSError:
                        pass
                signatures['$renders'] = renders
                if previous != signatures:
                    write_signatures(parent_fd, signatures)
                    os.utime(preview_fd, None)
        finally:
            os.close(preview_fd)
    finally:
        os.close(parent_fd)
    return {name.rsplit('.', 1)[0]: str(destination / name) for name in wanted}


def render_theme(folder, output):
    """Render the real UI with isolated config and the existing local fixture."""
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='mainframe-preview-') as tmp:
        base = Path(tmp)
        for name in ('home', 'config', 'cache', 'state', 'runtime'):
            (base / name).mkdir(mode=0o700)
        clean_env = {key: value for key, value in os.environ.items() if not key.startswith('MAINFRAME_')}
        env = dict(clean_env, HOME=str(base / 'home'), XDG_CONFIG_HOME=str(base / 'config'),
                   XDG_CACHE_HOME=str(base / 'cache'), XDG_STATE_HOME=str(base / 'state'),
                   XDG_RUNTIME_DIR=str(base / 'runtime'), DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(base / 'missing-bus'),
                   QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='', QSG_RENDER_LOOP='basic',
                   MAINFRAME_SMOKE='1', MAINFRAME_SMOKE_NO_REMOTE='1', MAINFRAME_SMOKE_FIXTURE_LOCAL='1',
                   MAINFRAME_SMOKE_W='1600', MAINFRAME_SMOKE_H='1000', MAINFRAME_SMOKE_MS='2500', MAINFRAME_SMOKE_START_LOCAL='1',
                   MAINFRAME_PREVIEW_THEME=str(folder / 'colors.toml'), MAINFRAME_PREVIEW_OUTPUT=str(output))
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'MAINFRAME_SMOKE_PAGE', 'MAINFRAME_SMOKE_LIVE', 'MAINFRAME_SMOKE_TAB', 'MAINFRAME_SMOKE_TAB_NAME'):
            env.pop(key, None)
        proc = subprocess.Popen(['nice', '-n', '19', 'qs', '-p', str(root)], env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            code = proc.wait(timeout=20)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                proc.wait()
            else:
                # The leader may exit before its children. Give the entire group
                # the grace period before killing any remaining processes.
                deadline = time.monotonic() + 2
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
        if code:
            raise subprocess.CalledProcessError(code, proc.args)
    with open(output, 'rb') as f:
        header = f.read(24)
    if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', header[16:24]) != (1600, 1000):
        raise ValueError('invalid preview image')


def render_previews(destination, available, current):
    """Serialize workers and publish only completed images into the pinned cache."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    cache_fd = os.open(destination.parent.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        parent_fd = os.open(destination.parent.name, flags, dir_fd=cache_fd)
    finally:
        os.close(cache_fd)
    try:
        lock_fd = os.open('.theme-preview-render.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent_fd)
        try:
            if not stat.S_ISREG(os.fstat(lock_fd).st_mode) or os.fstat(lock_fd).st_uid != os.getuid():
                raise PermissionError('unsafe preview lock')
            with signatures_lock(parent_fd):
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    marker_fd = os.open('.theme-preview-rerun', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent_fd)
                    try:
                        info = os.fstat(marker_fd)
                        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                            raise PermissionError('unsafe preview rerun marker')
                    finally:
                        os.close(marker_fd)
                    return
            while True:
                preview_fd = os.open(destination.name, flags, dir_fd=parent_fd)
                try:
                    if os.fstat(preview_fd).st_uid != os.getuid():
                        raise PermissionError('theme preview directory is not owned by the current user')
                    try:
                        root = Path(__file__).resolve().parent
                        for required in (root / 'shell.qml', root / 'tests/fake-local.py'):
                            if not required.is_file():
                                raise FileNotFoundError(str(required))
                        version = version_signature()
                    except OSError as exc:
                        syslog.syslog(syslog.LOG_WARNING, f'mainframe preview: missing renderer files: {exc}')
                        return
                    for name, folders in list(available.items()) + [(FOLLOW, [current])]:
                        if not valid_theme_name(name) or not folders or (name == FOLLOW and folders != [current]):
                            continue
                        signatures = read_signatures(parent_fd)
                        renders = signatures.get('$renders', {})
                        if not isinstance(renders, dict):
                            renders = {}
                        signature = color_signature(folders[0], version)
                        target = name + '.png'
                        try:
                            info = os.stat(target, dir_fd=preview_fd, follow_symlinks=False)
                            generated = stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                        except FileNotFoundError:
                            generated = False
                        if generated and renders.get(name) == signature:
                            continue
                        # Do not replace an unrelated regular file or special file.
                        if generated and name not in renders:
                            continue
                        with tempfile.TemporaryDirectory(prefix='mainframe-render-') as tmp:
                            output = Path(tmp) / 'preview.png'
                            try:
                                render_theme(folders[0], output)
                                data = output.read_bytes()
                                temp_name = f'.render-{os.getpid()}-{time.time_ns()}'
                                fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=preview_fd)
                                try:
                                    with os.fdopen(fd, 'wb') as f:
                                        f.write(data)
                                    with signatures_lock(parent_fd):
                                        signatures = read_signatures(parent_fd)
                                        renders = signatures.get('$renders', {})
                                        if not isinstance(renders, dict):
                                            renders = {}
                                        # Replace only a symlink fallback or our own tracked image.
                                        try:
                                            info = os.stat(target, dir_fd=preview_fd, follow_symlinks=False)
                                            if not stat.S_ISLNK(info.st_mode) and not (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and name in renders):
                                                continue
                                        except FileNotFoundError:
                                            pass
                                        os.replace(temp_name, target, src_dir_fd=preview_fd, dst_dir_fd=preview_fd)
                                        for entry in os.listdir(preview_fd):
                                            if entry != target and entry.rsplit('.', 1)[0] == name and preview_name(entry):
                                                info = os.stat(entry, dir_fd=preview_fd, follow_symlinks=False)
                                                if stat.S_ISLNK(info.st_mode):
                                                    os.unlink(entry, dir_fd=preview_fd)
                                        renders[name] = signature
                                        signatures['$renders'] = renders
                                        write_signatures(parent_fd, signatures)
                                        os.utime(preview_fd, None)
                                finally:
                                    try:
                                        os.unlink(temp_name, dir_fd=preview_fd)
                                    except FileNotFoundError:
                                        pass
                            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                                syslog.syslog(syslog.LOG_WARNING, f'mainframe preview {name}: {exc}')
                finally:
                    os.close(preview_fd)
                with signatures_lock(parent_fd):
                    try:
                        marker = os.stat('.theme-preview-rerun', dir_fd=parent_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        # Release under the state lock, so a competing worker
                        # cannot leave a marker after our final check.
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        break
                    if not stat.S_ISREG(marker.st_mode) or marker.st_uid != os.getuid():
                        raise PermissionError('unsafe preview rerun marker')
                    os.unlink('.theme-preview-rerun', dir_fd=parent_fd)
                home, _, _, roots = paths()
                available = themes(roots)
                current = home / '.local/state/omarchy/current/theme'
                build_previews(destination, available, current)

        finally:
            os.close(lock_fd)
    finally:
        os.close(parent_fd)


def schedule_previews():
    subprocess.Popen(['nice', '-n', '19', sys.executable, str(Path(__file__).resolve()), '--render-previews'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def read_settings(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def resolve(selection=None):
    home, settings, dest, roots = paths()
    current = home / '.local/state/omarchy/current/theme'
    available = themes(roots)
    data = read_settings(settings)
    choice = data.get('theme', FOLLOW)
    if not isinstance(choice, str):
        choice = FOLLOW
    if selection:
        if selection != FOLLOW and selection not in available:
            return None
        choice = selection
        data['theme'] = choice
        save_settings(settings, data)
    missing = choice != FOLLOW and choice not in available
    if missing:
        choice = FOLLOW
        data['theme'] = choice
        save_settings(settings, data)
    previews = build_previews(dest, available, current)
    if os.environ.get('MAINFRAME_SMOKE') != '1':
        try:
            schedule_previews()
        except OSError as exc:
            syslog.syslog(syslog.LOG_WARNING, f'mainframe preview worker: {exc}')
    folder = current if choice == FOLLOW else available[choice][0]
    try:
        system_name = (home / '.local/state/omarchy/current/theme.name').read_text(encoding='utf-8').strip()
    except OSError:
        system_name = ''
    return {'theme': choice, 'active': system_name if choice == FOLLOW and system_name else choice,
            'colors': str(folder / 'colors.toml'), 'previewDir': str(dest),
            'selected': previews.get(choice, ''), 'missing': missing,
            'picker': bool(shutil.which('omarchy-menu-images'))}


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--render-previews':
        home, _, dest, roots = paths()
        try:
            render_previews(dest, themes(roots), home / '.local/state/omarchy/current/theme')
        except OSError as exc:
            syslog.syslog(syslog.LOG_WARNING, f'mainframe preview worker: {exc}')
    else:
        result = resolve(sys.argv[1] if len(sys.argv) > 1 else None)
        print(json.dumps(result, ensure_ascii=False))
