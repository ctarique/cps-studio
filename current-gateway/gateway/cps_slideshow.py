"""Read-only season slideshow data. No experiment, device or ledger access."""
import json
import os
import uuid
import re
import time
from pathlib import Path

SEASON_ROOT = Path('/var/lib/cps-studio-slideshows/seasons')
STATE_DIR = Path('/var/lib/sentinel-cps-final/presentation-slideshow')
STATE_FILE = STATE_DIR / 'slideshow.json'
SEASONS = ('fall', 'spring', 'winter')
_SLIDE_RE = re.compile(r'slide-[0-9]{2}\.jpg\Z', re.ASCII)
SLIDE_MS = 11_200
FADE_MS = 1_200

class SlideshowUnavailable(ValueError):
    pass

def list_slides(season):
    if season not in SEASONS:
        raise SlideshowUnavailable('invalid season')
    directory = SEASON_ROOT / season
    if not directory.is_dir() or directory.is_symlink():
        raise SlideshowUnavailable('slideshow season missing')
    candidates = [p for p in directory.iterdir() if _SLIDE_RE.fullmatch(p.name)]
    if any(p.is_symlink() or not p.is_file() for p in candidates):
        raise SlideshowUnavailable('invalid slideshow image entry')
    slides = sorted(p.name for p in candidates)
    if not 1 <= len(slides) <= 50:
        raise SlideshowUnavailable('invalid slideshow image count')
    if slides != [f'slide-{i:02d}.jpg' for i in range(1, len(slides) + 1)]:
        raise SlideshowUnavailable('nonconsecutive slideshow images')
    return slides

def load_state():
    try:
        obj = json.loads(STATE_FILE.read_text(encoding='ascii'))
        if type(obj) is not dict or set(obj) != {'season', 'started_at_ms', 'revision'}:
            raise SlideshowUnavailable('invalid slideshow state shape')
        if obj['season'] not in SEASONS:
            raise SlideshowUnavailable('invalid slideshow season')
        if type(obj['started_at_ms']) is not int or not 1_600_000_000_000 <= obj['started_at_ms'] <= 4_102_444_800_000:
            raise SlideshowUnavailable('invalid slideshow timestamp')
        if type(obj['revision']) is not str or not re.fullmatch(r'[0-9a-f]{32}', obj['revision']):
            raise SlideshowUnavailable('invalid slideshow revision')
        return obj
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise SlideshowUnavailable('slideshow state unavailable') from exc

def slideshow_snapshot():
    state = load_state()
    slides = list_slides(state['season'])
    return {
        'season': state['season'],
        'revision': state['revision'],
        'started_at_ms': state['started_at_ms'],
        'server_now_ms': int(time.time() * 1000),
        'slide_duration_ms': SLIDE_MS,
        'crossfade_ms': FADE_MS,
        'slides': [f'/display/slides/{state["season"]}/{name}' for name in slides],
    }

def slide_path(season, filename):
    if season not in SEASONS or not _SLIDE_RE.fullmatch(filename):
        return None
    if filename not in list_slides(season):
        return None
    p = SEASON_ROOT / season / filename
    if p.is_symlink() or not p.is_file():
        return None
    return p


def set_slideshow_season(season):
    """Atomically write only the allowlisted presentation state, as sentinel-final."""
    if type(season) is not str or season not in SEASONS:
        raise SlideshowUnavailable('invalid season')
    list_slides(season)
    try:
        if STATE_DIR.is_symlink() or not STATE_DIR.is_dir():
            raise SlideshowUnavailable('state directory unavailable')
        if STATE_FILE.is_symlink():
            raise SlideshowUnavailable('state file invalid')
        st = STATE_DIR.stat()
        if st.st_uid != os.geteuid() or (st.st_mode & 0o077):
            raise SlideshowUnavailable('state directory permission mismatch')
        new = {
            'season': season,
            'started_at_ms': int(time.time() * 1000),
            'revision': uuid.uuid4().hex,
        }
        temp = STATE_DIR / ('.slideshow.' + uuid.uuid4().hex + '.tmp')
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='ascii') as out:
                json.dump(new, out, separators=(',', ':'))
                out.write('\n')
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, STATE_FILE)
            dirfd = os.open(str(STATE_DIR), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if temp.exists():
                temp.unlink()
        return slideshow_snapshot()
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise SlideshowUnavailable('slideshow state write unavailable') from exc
