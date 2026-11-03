"""On-demand allocated-space inventory for Mainframe."""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

CATEGORIES = ("Games", "Caches & trash", "Apps", "Downloads & archives", "Images", "Videos", "Music", "Documents", "Other")
EXTENSIONS = {
    "Downloads & archives": set("zip tar gz zst xz 7z iso img appimage bz2 rar tgz tbz2 txz deb rpm".split()),
    "Images": set("jpg jpeg png gif bmp tif tiff webp heic heif avif svg raw dng cr2 cr3 nef nrw arw raf orf rw2 pef srw".split()),
    "Videos": set("mp4 mkv avi mov webm m4v mpg mpeg wmv flv mts m2ts".split()),
    "Music": set("mp3 flac wav ogg opus m4a aac wma aiff alac".split()),
    "Documents": set("pdf doc docx xls xlsx ppt pptx odt ods odp md txt epub rtf csv tex".split()),
}
PREFIXES = {
    "Games": (".local/share/Steam", ".steam", "Games", ".var/app/com.valvesoftware.Steam", ".local/share/lutris", ".local/share/heroic", ".config/heroic", ".var/app/com.heroicgameslauncher.hgl", ".var/app/net.lutris.Lutris"),
    "Caches & trash": (".cache", ".local/share/Trash"),
    "Apps": (".local/share/flatpak", ".var/app", ".local/share/mise", ".npm", ".cargo", ".rustup", ".local/lib"),
    "Downloads & archives": ("Downloads",),
}

def classify(relative, is_dir=False):
    path = relative.replace(os.sep, "/").strip("/")
    low = path.lower()
    for category in ("Games", "Caches & trash", "Apps", "Downloads & archives"):
        if category == "Apps" and "node_modules" in low.split("/"):
            return category
        for prefix in PREFIXES[category]:
            prefix = prefix.lower()
            if low == prefix or low.startswith(prefix + "/"):
                return category
    if not is_dir:
        ext = low.rsplit(".", 1)[-1] if "." in low.rsplit("/", 1)[-1] else ""
        for category, extensions in EXTENSIONS.items():
            if ext in extensions:
                return category
    return "Other"

def mount_info(path):
    """Mount boundaries include same-device bind mounts and btrfs subvolumes."""
    mounts = []
    try:
        with open('/proc/self/mountinfo', encoding='utf-8') as handle:
            for line in handle:
                fields = line.split()
                sep = fields.index('-')
                point = fields[4].replace('\\040', ' ').replace('\\011', '\t').replace('\\134', '\\')
                mounts.append((point, fields[sep + 1]))
    except (OSError, ValueError, IndexError):
        pass
    containing = [item for item in mounts if path == item[0] or path.startswith(item[0].rstrip('/') + '/')]
    fs = max(containing, key=lambda item: len(item[0]))[1] if containing else ''
    return {p for p, _ in mounts if p != path and p.startswith(path.rstrip('/') + '/')}, fs

class ScanTimeout(Exception):
    pass

def scan(home, roots=(), timeout=600, progress=None, clock=time.monotonic, should_cancel=None, stat_fn=None):
    """Return an inventory. Optional hooks make timeout and boundaries testable."""
    home = os.path.abspath(home)
    stat_fn = stat_fn or (lambda entry: entry.stat(follow_symlinks=False))
    totals = {key: 0 for key in CATEGORIES}
    seen = set()
    files = 0
    visited = 0
    started = clock()
    last = started
    partial = False
    cancelled = False
    paths = [(home, None)] + [(os.path.abspath(p), 'Apps') for p in roots]
    previous_handler = None
    previous_timer = None
    try:
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        def deadline(_signum, _frame):
            raise ScanTimeout()
        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, timeout))
    except (AttributeError, ValueError, OSError):
        previous_handler = None
    try:
        for root, forced in paths:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            try:
                root_fd = os.open(root, flags)
            except OSError:
                continue
            try:
                rootstat = os.fstat(root_fd)
                home_dev = rootstat.st_dev
                if forced and home_dev != os.stat('/').st_dev:
                    source = mount_source(root)
                    if source is None or source != mount_source('/'):
                        continue
                boundaries, fs = mount_info(root)
                # Store names and identities, not open descriptors. Reopen from the
                # pinned root for each directory, keeping descriptor use bounded.
                stack = [(root, ())]
                while stack:
                    if should_cancel and should_cancel():
                        cancelled = True
                        break
                    now = clock()
                    if now - started >= timeout:
                        partial = True
                        break
                    folder, components = stack.pop()
                    current_fd = None
                    try:
                        current_fd = os.dup(root_fd)
                        for name, expected in components:
                            child_fd = os.open(name, flags, dir_fd=current_fd)
                            os.close(current_fd)
                            current_fd = child_fd
                            opened = os.fstat(current_fd)
                            if opened.st_dev != home_dev or (opened.st_dev, opened.st_ino) != expected:
                                raise OSError('directory changed during scan')
                        with os.scandir(current_fd) as entries:
                            for entry in entries:
                                if should_cancel and should_cancel():
                                    cancelled = True
                                    break
                                now = clock()
                                if now - started >= timeout:
                                    partial = True
                                    break
                                try:
                                    if entry.is_symlink():
                                        continue
                                    st = stat_fn(entry)
                                    if st.st_dev != home_dev:
                                        continue
                                    is_dir = stat.S_ISDIR(st.st_mode) if hasattr(st, 'st_mode') else entry.is_dir(follow_symlinks=False)
                                    entry_path = os.path.join(folder, entry.name)
                                    if is_dir and (entry_path in boundaries or (fs == 'btrfs' and st.st_ino == 256)):
                                        continue
                                    identity = (st.st_dev, st.st_ino)
                                    if identity in seen:
                                        continue
                                    seen.add(identity)
                                    category = forced or classify(os.path.relpath(entry_path, home), is_dir)
                                    totals[category] += st.st_blocks * 512
                                    visited += 1
                                    if not is_dir:
                                        files += 1
                                    if is_dir:
                                        stack.append((entry_path, components + ((entry.name, identity),)))
                                except OSError:
                                    continue
                                if visited % 512 == 0:
                                    time.sleep(0.002)
                                if progress and now - last >= 0.5:
                                    progress({'type': 'progress', 'files': files, 'bytes': sum(totals.values()), 'elapsed': now - started})
                                    last = now
                    except OSError:
                        continue
                    finally:
                        if current_fd is not None:
                            os.close(current_fd)
                    if partial or cancelled:
                        break
                if partial or cancelled:
                    break
            except OSError:
                continue
            finally:
                os.close(root_fd)
    except ScanTimeout:
        partial = True
    finally:
        if previous_handler is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_timer and previous_timer[0] > 0:
                signal.setitimer(signal.ITIMER_REAL, max(0.000001, previous_timer[0] - (time.monotonic() - started)), previous_timer[1])
    return {'categories': totals, 'files': files, 'elapsed': max(0, clock() - started), 'partial': partial, 'cancelled': cancelled}

def emit(value):
    print(json.dumps(value, separators=(',', ':')), flush=True)

def cache_path():
    return os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'mainframe', 'storage.json')

def mount_source(path):
    choices = []
    try:
        with open('/proc/self/mountinfo', encoding='utf-8') as handle:
            for line in handle:
                fields = line.split()
                sep = fields.index('-')
                point = fields[4].replace('\\040', ' ')
                if path == point or path.startswith(point.rstrip('/') + '/'):
                    choices.append((len(point), fields[sep + 1], fields[sep + 2]))
    except (OSError, ValueError, IndexError):
        pass
    return max(choices)[1:] if choices else None

def cache_fresh(cached, now):
    try:
        age = now - float(cached['timestamp'])
        return 0 <= age < 3600 and not cached.get('partial')
    except (TypeError, ValueError, KeyError):
        return False

def run(force=False):
    try:
        os.setsid()
    except OSError:
        pass
    try:
        os.nice(15)
    except OSError:
        pass
    if shutil.which('ionice'):
        subprocess.run(['ionice', '-c', '3', '-p', str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    path = cache_path()
    if not force:
        try:
            with open(path, encoding='utf-8') as handle:
                cached = json.load(handle)
            if cache_fresh(cached, time.time()):
                emit(dict(cached, type='result', cached=True))
                return 0
        except (OSError, ValueError, TypeError, KeyError):
            pass
    home = os.path.expanduser('~')
    rootstat = os.stat('/')
    homestat = os.stat(home)
    if rootstat.st_dev != homestat.st_dev and (not mount_source(home) or mount_source(home) != mount_source('/')):
        emit({'type': 'error', 'message': 'Home is on a different filesystem; root breakdown is unavailable.'})
        return 1
    emit({'type': 'progress', 'files': 0, 'bytes': 0, 'elapsed': 0})
    result = scan(home, ['/usr/share/flatpak', '/var/lib/flatpak', '/opt'], progress=emit)
    fs = os.statvfs('/')
    total = fs.f_blocks * fs.f_frsize
    free = fs.f_bfree * fs.f_frsize
    result.update({'timestamp': time.time(), 'total': total, 'used': total - free, 'free': free, 'type': 'result'})
    if not result['cancelled']:
        temp = None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=os.path.basename(path) + '.', suffix='.tmp')
            try:
                handle = os.fdopen(fd, 'w', encoding='utf-8')
            except BaseException:
                os.close(fd)
                raise
            with handle:
                json.dump(result, handle)
            os.replace(temp, path)
        except OSError:
            pass
        finally:
            if temp is not None:
                try:
                    os.unlink(temp)
                except OSError:
                    pass
        emit(result)
    return 0

def open_category(category):
    home = os.path.expanduser('~')
    folders = {'Images': 'Pictures', 'Videos': 'Videos', 'Music': 'Music', 'Documents': 'Documents', 'Downloads & archives': 'Downloads', 'Games': '.local/share/Steam', 'Caches & trash': '.cache', 'Apps': '.local/share/flatpak'}
    path = os.path.join(home, folders.get(category, ''))
    if category == 'Games' and not os.path.isdir(path):
        for alternative in ('Games', '.steam', '.local/share/lutris', '.local/share/heroic'):
            candidate = os.path.join(home, alternative)
            if os.path.isdir(candidate):
                path = candidate
                break
    if not os.path.isdir(path):
        path = home
    program = shutil.which('baobab') or shutil.which('xdg-open')
    if not program:
        return 1
    try:
        subprocess.Popen([program, path], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0
    except OSError:
        return 1
