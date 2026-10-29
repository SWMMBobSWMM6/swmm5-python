"""C runtime layer for the pure-Python port of EPA SWMM 5.2.4.

Reproduces the glibc behaviour SWMM's output depends on: printf formatting (Python's %-operator uses
correctly rounded conversions, like glibc), strtod/sscanf parsing, NUL-terminated byte strings,
stdio files, IEEE division by zero, x86-64 float->int conversion and IEEE single rounding.
Written by Claude (Anthropic); see AI-USE.md.
"""
import math, os, struct, sys, time as _time, random

__all__ = ['CPtr', 'lit', 'Box', 'FieldRef', 'ElemRef', 'GlobalRef', 'CFile', 'D2I', 'D2L', 'F32', '_i32',
           '_idiv', '_imod', '_fdiv', '_seta', '_seti', '_post', '_postp', '_arr1', '_chr1', '_comma',
           '_pow', '_sqrt', '_floor', '_ceil', '_exp', '_log', '_log10', '_acos', '_asin', '_sin', '_cos', '_tan',
           'stdout']

_INF = float('inf')
_NAN = float('-nan')   # x86 SSE default NaN has the sign bit set (glibc prints -nan)


# --------------------------------------------------------------------- pointers and references
class CPtr:
    """C char*: a bytearray plus an offset. Indexing reads/writes signed chars like x86 C."""
    __slots__ = ('b', 'o')

    def __init__(self, b, o=0):
        self.b = b
        self.o = o

    def __getitem__(self, i):
        v = self.b[self.o + i]
        return v - 256 if v > 127 else v

    def __setitem__(self, i, v):
        self.b[self.o + i] = v & 255

    def __add__(self, n):
        return CPtr(self.b, self.o + n)

    def __sub__(self, n):
        if isinstance(n, CPtr):
            return self.o - n.o
        return CPtr(self.b, self.o - n)

    def __eq__(self, other):
        return isinstance(other, CPtr) and other.b is self.b and other.o == self.o

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        return self.o < other.o

    def __gt__(self, other):
        return self.o > other.o

    def __le__(self, other):
        return self.o <= other.o

    def __ge__(self, other):
        return self.o >= other.o

    def __hash__(self):
        return id(self.b) ^ self.o

    def copy(self):
        return CPtr(bytearray(self.b), self.o)

    @staticmethod
    def buf(n):
        return CPtr(bytearray(max(int(n), 1)), 0)

    @staticmethod
    def buf_from(src, n):
        p = CPtr.buf(n)
        s = bytes_of(src)[:n]
        p.b[:len(s)] = s
        return p

    @staticmethod
    def diff(a, b):
        return a.o - b.o

    def __repr__(self):
        return 'CPtr(%r)' % bytes_of(self)


def lit(b):
    return CPtr(bytearray(b + b'\0'), 0)


def bytes_of(p):
    b = p.b
    e = b.find(0, p.o)
    return bytes(b[p.o:e if e >= 0 else len(b)])


def str_of(p):
    return bytes_of(p).decode('latin-1')


class Box:
    __slots__ = ('v',)

    def __init__(self, v):
        self.v = v


class FieldRef:
    __slots__ = ('obj', 'name')

    def __init__(self, obj, name):
        self.obj = obj
        self.name = name

    @property
    def v(self):
        return getattr(self.obj, self.name)

    @v.setter
    def v(self, x):
        setattr(self.obj, self.name, x)


class ElemRef:
    __slots__ = ('arr', 'i')

    def __init__(self, arr, i):
        self.arr = arr
        self.i = i

    @property
    def v(self):
        return self.arr[self.i]

    @v.setter
    def v(self, x):
        self.arr[self.i] = x


class GlobalRef:
    __slots__ = ('g', 'name')

    def __init__(self, g, name):
        self.g = g
        self.name = name

    @property
    def v(self):
        return self.g[self.name]

    @v.setter
    def v(self, x):
        self.g[self.name] = x


# --------------------------------------------------------------------- arithmetic with C semantics
_f32 = struct.Struct('<f')


def D2I(x):
    """C (int)x on x86-64 (cvttsd2si): NaN or out of range gives INT_MIN"""
    if x != x or x >= 2147483648.0 or x <= -2147483649.0:
        return -2147483648
    return int(x)


def D2L(x):
    if x != x or x >= 9223372036854775808.0 or x < -9223372036854775808.0:
        return -9223372036854775808
    return int(x)


def F32(x):
    """round to IEEE single precision, as storing into a C float does"""
    try:
        return _f32.unpack(_f32.pack(x))[0]
    except OverflowError:
        return math.copysign(_INF, x)


def _i32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


def _idiv(a, b):
    return int(a / b) if abs(a) < 9007199254740992 else (abs(a) // abs(b)) * (1 if (a >= 0) == (b > 0) else -1)


def _imod(a, b):
    return a - b * _idiv(a, b)


def _fdiv(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        if a != a:
            return a
        if a == 0:
            return _NAN
        return math.copysign(_INF, a) * math.copysign(1.0, b)


def _seta(obj, name, v):
    setattr(obj, name, v)
    return v


def _seti(arr, i, v):
    arr[i] = v
    return v


def _post(ref, d):
    old = ref.v
    ref.v = old + d
    return old


def _postp(ref, d):
    old = ref.v
    ref.v = old + d
    return old


def _arr1(ref, f):
    a = [ref.v]
    r = f(a)
    ref.v = a[0]
    return r


def _chr1(ref, f):
    p = CPtr.buf(2)
    p[0] = ref.v
    r = f(p)
    ref.v = p[0]
    return r


def _comma(a, b):
    return b


# math functions: C returns inf/nan where Python raises
def _pow(x, y):
    try:
        return math.pow(x, y)
    except (ValueError, ZeroDivisionError):
        if x == 0.0 and y < 0:
            return _INF if (y != int(y) or int(y) % 2 == 0 or math.copysign(1.0, x) > 0) else -_INF
        return _NAN
    except OverflowError:
        if x < 0 and y == int(y) and int(y) % 2 == 1:
            return -_INF
        return _INF


def _sqrt(x):
    try:
        return math.sqrt(x)
    except ValueError:
        return x if x != x else _NAN


def _floor(x):
    try:
        return float(math.floor(x))
    except (ValueError, OverflowError):
        return x


def _ceil(x):
    try:
        return float(math.ceil(x))
    except (ValueError, OverflowError):
        return x


def _exp(x):
    try:
        return math.exp(x)
    except OverflowError:
        return _INF


def _log(x):
    try:
        return math.log(x)
    except ValueError:
        if x == 0:
            return -_INF
        return _NAN


def _log10(x):
    try:
        return math.log10(x)
    except ValueError:
        if x == 0:
            return -_INF
        return _NAN


def _acos(x):
    try:
        return math.acos(x)
    except ValueError:
        return _NAN


def _asin(x):
    try:
        return math.asin(x)
    except ValueError:
        return _NAN


def _sin(x):
    try:
        return math.sin(x)
    except ValueError:
        return _NAN


def _cos(x):
    try:
        return math.cos(x)
    except ValueError:
        return _NAN


def _tan(x):
    try:
        return math.tan(x)
    except ValueError:
        return _NAN


# --------------------------------------------------------------------- memory
def memset(a, v, n):
    if isinstance(a, CPtr):
        for i in range(int(n)):
            a.b[a.o + i] = v & 255
    else:
        cnt = int(n) // 8
        for i in range(min(cnt, len(a))):
            a[i] = 0.0 if isinstance(a[i], float) else 0


def realloc(a, n):
    n = int(n)
    if a is None:
        return [None] * n
    if isinstance(a, CPtr):
        p = CPtr.buf(n)
        m = min(n, len(a.b) - a.o)
        p.b[:m] = a.b[a.o:a.o + m]
        return p
    if n <= len(a):
        return a[:n]
    fill = a[0].__class__() if (a and hasattr(a[0], 'clone')) else (0.0 if (a and isinstance(a[0], float)) else (0 if a and isinstance(a[0], int) else None))
    if a and hasattr(a[0], 'clone'):
        return a + [a[0].__class__() for _ in range(n - len(a))]
    return a + [fill] * (n - len(a))


# --------------------------------------------------------------------- strings
def strlen(p):
    e = p.b.find(0, p.o)
    return e - p.o


def strcpy(d, s):
    src = bytes(s.b[s.o:s.b.find(0, s.o) + 1])
    d.b[d.o:d.o + len(src)] = src
    return d


def strcat(d, s):
    strcpy(d + strlen(d), s)
    return d


def strcmp(a, b):
    x, y = bytes_of(a), bytes_of(b)
    for i in range(min(len(x), len(y))):
        if x[i] != y[i]:
            return x[i] - y[i]
    if len(x) == len(y):
        return 0
    return (x[len(y)] if len(x) > len(y) else -y[len(x)])


def strchr(s, c):
    c &= 255
    b = s.b
    i = s.o
    while True:
        if b[i] == c:
            return CPtr(b, i)
        if b[i] == 0:
            return None
        i += 1


def strrchr(s, c):
    c &= 255
    e = s.b.find(0, s.o)
    if c == 0:
        return CPtr(s.b, e)
    i = s.b.rfind(c, s.o, e)
    return CPtr(s.b, i) if i >= 0 else None


def strstr(h, n):
    hb, nb = bytes_of(h), bytes_of(n)
    i = hb.find(nb)
    return CPtr(h.b, h.o + i) if i >= 0 else None


def strcspn(s, rej):
    sb, rb = bytes_of(s), set(bytes_of(rej))
    for i, ch in enumerate(sb):
        if ch in rb:
            return i
    return len(sb)


_tok_next = [None]


def strtok(s, delim):
    if s is not None:
        _tok_next[0] = s
    p = _tok_next[0]
    if p is None:
        return None
    ds = set(bytes_of(delim))
    b = p.b
    i = p.o
    while b[i] != 0 and b[i] in ds:
        i += 1
    if b[i] == 0:
        _tok_next[0] = None
        return None
    start = i
    while b[i] != 0 and b[i] not in ds:
        i += 1
    if b[i] != 0:
        b[i] = 0
        _tok_next[0] = CPtr(b, i + 1)
    else:
        _tok_next[0] = None
    return CPtr(b, start)


def toupper(c):
    return c - 32 if 97 <= c <= 122 else c


_SPACE = b' \t\n\v\f\r'


def _scan_double(b, i, maxw, skip_space=True):
    """parse a C floating number at b[i:] (at most maxw chars after leading space); returns (value, end) or (0.0, None)"""
    n = len(b)

    def g(k):
        return b[k] if k < lim and k < n else 0
    if skip_space:
        while i < n and b[i] in _SPACE:
            i += 1
    lim = n if maxw is None else i + maxw
    st = i
    neg = False
    if g(i) in (43, 45):
        neg = g(i) == 45
        i += 1
    low = lambda c: c | 0x20 if 65 <= c <= 90 else c
    if low(g(i)) == 105 and low(g(i + 1)) == 110 and low(g(i + 2)) == 102:
        i += 3
        if bytes(low(g(i + k)) for k in range(5)) == b'inity':
            i += 5
        return (-_INF if neg else _INF), i
    if low(g(i)) == 110 and low(g(i + 1)) == 97 and low(g(i + 2)) == 110:
        i += 3
        if g(i) == 40:
            k = i + 1
            while chr(g(k)).isalnum() or g(k) == 95:
                k += 1
            if g(k) == 41:
                i = k + 1
        return (-_NAN if neg else _NAN), i
    ms = i
    nd = 0
    while 48 <= g(i) <= 57:
        i += 1
        nd += 1
    if g(i) == 46:
        i += 1
        while 48 <= g(i) <= 57:
            i += 1
            nd += 1
    if nd == 0:
        return 0.0, None
    if low(g(i)) == 101:
        k = i + 1
        if g(k) in (43, 45):
            k += 1
        if 48 <= g(k) <= 57:
            while 48 <= g(k) <= 57:
                k += 1
            i = k
    v = float(bytes(b[ms:i]))
    return (-v if neg else v), i


def strtod(s, endref):
    v, e = _scan_double(s.b, s.o, None)
    if endref is not None:
        endref.v = s if e is None else CPtr(s.b, e)
    return v if e is not None else 0.0


def atof(s):
    return strtod(s, None)


def atoi(s):
    b = s.b
    i = s.o
    while b[i] in _SPACE and b[i] != 0:
        i += 1
    neg = False
    if b[i] in (43, 45):
        neg = b[i] == 45
        i += 1
    v = 0
    st = i
    while 48 <= b[i] <= 57:
        v = v * 10 + b[i] - 48
        i += 1
    if neg:
        v = -v
    v = max(min(v, 9223372036854775807), -9223372036854775808)
    return _i32(v)


# --------------------------------------------------------------------- sscanf
def sscanf(s, fmt, *args):
    b = s.b
    i = s.o
    f = bytes_of(fmt)
    k = 0
    ai = 0
    count = 0
    any_input = False
    n = len(b)
    nf = len(f)

    def ch(j):
        return b[j] if j < n else 0
    while k < nf:
        fc = f[k]
        if fc in _SPACE:
            while k < nf and f[k] in _SPACE:
                k += 1
            while ch(i) != 0 and ch(i) in _SPACE:
                i += 1
            continue
        if fc != 37:
            if ch(i) == 0:
                return count if (any_input or count > 0) else -1
            if ch(i) != fc:
                return count
            i += 1
            k += 1
            continue
        k += 1
        if f[k] == 37:
            while ch(i) != 0 and ch(i) in _SPACE:
                i += 1
            if ch(i) != 37:
                return count
            i += 1
            k += 1
            continue
        suppress = False
        if f[k] == 42:
            suppress = True
            k += 1
        width = 0
        while 48 <= f[k] <= 57:
            width = width * 10 + f[k] - 48
            k += 1
        lmod = 0
        while f[k] in b'lhL':
            if f[k] == 108:
                lmod += 1
            k += 1
        conv = f[k]
        k += 1
        if conv not in (99, 91, 110):
            while ch(i) != 0 and ch(i) in _SPACE:
                i += 1
        if ch(i) == 0 and conv != 110:
            return -1 if (count == 0 and not any_input) else count
        if conv in (100, 105, 117):           # d i u
            j = i
            lim = i + width if width else n
            neg = False
            if j < lim and ch(j) in (43, 45):
                neg = ch(j) == 45
                j += 1
            ds = j
            v = 0
            while j < lim and 48 <= ch(j) <= 57:
                v = v * 10 + ch(j) - 48
                j += 1
            if j == ds:
                return count
            i = j
            any_input = True
            if neg:
                v = -v
            if not suppress:
                a = args[ai]
                ai += 1
                v = max(min(v, 9223372036854775807), -9223372036854775808)
                a[1].v = v if lmod > 0 else _i32(v)
                count += 1
        elif conv in (102, 101, 103):          # f e g
            v, e = _scan_double(b, i, width if width else None, False)
            if e is None:
                return count
            i = e
            any_input = True
            if not suppress:
                a = args[ai]
                ai += 1
                a[1].v = v if (lmod > 0 or a[0] == 'd') else F32(v)
                count += 1
        elif conv == 115:                      # s
            j = i
            w = width if width else 1 << 30
            out = []
            while ch(j) != 0 and ch(j) not in _SPACE and len(out) < w:
                out.append(ch(j))
                j += 1
            if not suppress:
                d = args[ai]
                ai += 1
                d.b[d.o:d.o + len(out) + 1] = bytes(out) + b'\0'
                count += 1
            i = j
            any_input = True
        elif conv == 99:                       # c
            cnt = width if width else 1
            if ch(i) == 0:
                return -1 if (count == 0 and not any_input) else count
            a = None if suppress else args[ai]
            if not suppress:
                ai += 1
            t = 0
            while t < cnt and ch(i) != 0:
                if not suppress:
                    if isinstance(a, CPtr):
                        a.b[a.o + t] = ch(i)
                    else:
                        c = ch(i)
                        a[1].v = c - 256 if c > 127 else c
                i += 1
                t += 1
            any_input = True
            if not suppress:
                count += 1
        else:
            raise NotImplementedError('sscanf %' + chr(conv))
    return count


# --------------------------------------------------------------------- printf family
_fmt_cache = {}


def _parse_fmt(fb):
    """split a printf format into literal bytes and conversion specs"""
    parts = []
    i = 0
    n = len(fb)
    lit_start = 0
    while i < n:
        if fb[i] != 37:
            i += 1
            continue
        if i + 1 < n and fb[i + 1] == 37:
            parts.append(('lit', fb[lit_start:i] + b'%'))
            i += 2
            lit_start = i
            continue
        if i > lit_start:
            parts.append(('lit', fb[lit_start:i]))
        j = i + 1
        flags = b''
        while j < n and fb[j] in b'-+ #0':
            flags += bytes([fb[j]])
            j += 1
        width = b''
        if j < n and fb[j] == 42:
            width = b'*'
            j += 1
        else:
            while j < n and 48 <= fb[j] <= 57:
                width += bytes([fb[j]])
                j += 1
        prec = None
        if j < n and fb[j] == 46:
            j += 1
            prec = b''
            if fb[j] == 42:
                prec = b'*'
                j += 1
            else:
                while j < n and 48 <= fb[j] <= 57:
                    prec += bytes([fb[j]])
                    j += 1
        while j < n and fb[j] in b'hlLqjzt':
            j += 1
        conv = chr(fb[j])
        parts.append(('spec', flags.decode(), width.decode(), None if prec is None else prec.decode(), conv))
        i = j + 1
        lit_start = i
    if lit_start < n:
        parts.append(('lit', fb[lit_start:]))
    return parts


def format_c(fmt, args):
    key = (id(fmt.b), fmt.o)
    ent = _fmt_cache.get(key)
    fb = bytes_of(fmt)
    if ent is None or ent[0] != fb:
        ent = (fb, _parse_fmt(fb))
        _fmt_cache[key] = ent
    out = []
    ai = 0
    for p in ent[1]:
        if p[0] == 'lit':
            out.append(p[1])
            continue
        _, flags, width, prec, conv = p
        if width == '*':
            w = args[ai]
            ai += 1
            if w < 0:
                flags += '-'
                w = -w
            width = str(w)
        if prec == '*':
            pr = args[ai]
            ai += 1
            prec = str(pr) if pr >= 0 else None
        a = args[ai]
        ai += 1
        if conv == 's':
            sv = '(null)' if a is None else str_of(a)
            if prec is not None and prec != '':
                sv = sv[:int(prec)]
            elif prec == '':
                sv = ''
            spec = '%' + flags.replace('0', '') + width + 's'
            out.append((spec % sv).encode('latin-1'))
            continue
        if conv == 'c':
            spec = '%' + flags.replace('0', '') + width + 'c'
            out.append((spec % chr(a & 255)).encode('latin-1'))
            continue
        if conv in 'fFeEgG':
            a = float(a)
            if a != a or a in (_INF, -_INF):
                body = ('nan' if a != a else 'inf')
                if conv in 'FEG':
                    body = body.upper()
                neg = math.copysign(1.0, a) < 0
                sign = '-' if neg else ('+' if '+' in flags else (' ' if ' ' in flags else ''))
                sv = sign + body
                w = int(width) if width else 0
                sv = sv.ljust(w) if '-' in flags else sv.rjust(w)
                out.append(sv.encode())
                continue
            spec = '%' + flags + width + ('' if prec is None else '.' + (prec or '0')) + conv
            out.append((spec % a).encode())
            continue
        if conv in 'diu':
            spec = '%' + flags + width + ('' if prec is None else '.' + (prec or '0')) + 'd'
            if prec is not None and int(prec or 0) == 0 and int(a) == 0:
                w = int(width) if width else 0
                out.append((' ' * w).encode())
                continue
            out.append((spec % int(a)).encode())
            continue
        if conv in 'xXo':
            spec = '%' + flags + width + ('' if prec is None else '.' + (prec or '0')) + conv
            out.append((spec % (int(a) & 0xFFFFFFFFFFFFFFFF if int(a) < 0 else int(a))).encode())
            continue
        raise NotImplementedError('printf %' + conv)
    return b''.join(out)


def fprintf(f, fmt, *args):
    b = format_c(fmt, args)
    if f is None:
        return -1
    f.write(b)
    return len(b)


def snprintf(buf, n, fmt, *args):
    b = format_c(fmt, args)
    n = int(n)
    if n > 0:
        m = min(len(b), n - 1)
        buf.b[buf.o:buf.o + m] = b[:m]
        buf.b[buf.o + m] = 0
    return len(b)


# --------------------------------------------------------------------- files
class CFile:
    __slots__ = ('f', 'eof', 'std')

    def __init__(self, f, std=False):
        self.f = f
        self.eof = False
        self.std = std

    def write(self, b):
        self.f.write(b)


stdout = CFile(sys.stdout.buffer, True)


def fopen(name, mode):
    fn = str_of(name)
    m = str_of(mode).replace('t', '')
    if 'b' not in m:
        m += 'b'
    try:
        return CFile(open(fn, m, buffering=1 << 16))
    except OSError:
        return None


def fclose(f):
    if f is None:
        return -1
    if f.std:
        f.f.flush()
    else:
        f.f.close()
    return 0


def fflush(f):
    if f is not None:
        f.f.flush()
    return 0


def feof(f):
    return 1 if f.eof else 0


def rewind(f):
    f.f.seek(0)
    f.eof = False


def fseek(f, off, whence):
    try:
        f.f.seek(off, whence)
        f.eof = False
        return 0
    except OSError:
        return -1


def ftell(f):
    return f.f.tell()


def fgets(buf, n, f):
    line = f.f.readline(n - 1)
    if not line:
        f.eof = True
        return None
    if len(line) < n - 1 and not line.endswith(b'\n'):
        f.eof = True
    buf.b[buf.o:buf.o + len(line) + 1] = line + b'\0'
    return buf


def remove(name):
    try:
        os.remove(str_of(name))
        return 0
    except OSError:
        return -1


def mkstemp(template):
    n = strlen(template)
    chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    for _ in range(1000):
        for i in range(n - 6, n):
            template[i] = ord(random.choice(chars))
        try:
            fd = os.open(str_of(template), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
            return 3
        except FileExistsError:
            continue
    return -1


_STRUCT = {'d': (8, struct.Struct('<d')), 'f': (4, struct.Struct('<f')), 'i': (4, struct.Struct('<i')),
           'I': (4, struct.Struct('<I')), 'q': (8, struct.Struct('<q'))}


def fwrite1(code, size, v, f):
    if code == 'c':
        f.f.write(bytes([v & 255]))
        return 1
    nat, st = _STRUCT[code]
    if code == 'f':
        b = _f32.pack(v)
    else:
        b = st.pack(v)
    f.f.write(b[:size] if size != nat else b)
    return 1


def fread1(code, size, ref, f):
    nat, st = _STRUCT[code]
    b = f.f.read(size)
    if len(b) < size:
        f.eof = True
        return 0
    if size != nat:
        old = st.pack(ref.v)
        b = b + old[size:]
    ref.v = st.unpack(b)[0]
    return 1


def fwrite_arr(code, size, arr, off, n, f):
    n = int(n)
    if code == 'c':
        f.f.write(bytes(arr.b[arr.o + off:arr.o + off + n]))
        return n
    nat, st = _STRUCT[code]
    if code == 'f':
        f.f.write(b''.join(_f32.pack(arr[off + i]) for i in range(n)))
    else:
        f.f.write(b''.join(st.pack(arr[off + i]) for i in range(n)))
    return n


def fread_arr(code, size, arr, off, n, f):
    n = int(n)
    if code == 'c':
        b = f.f.read(n)
        arr.b[arr.o + off:arr.o + off + len(b)] = b
        if len(b) < n:
            f.eof = True
        return len(b)
    nat, st = _STRUCT[code]
    for i in range(n):
        b = f.f.read(nat)
        if len(b) < nat:
            f.eof = True
            return i
        arr[off + i] = st.unpack(b)[0]
    return n


# --------------------------------------------------------------------- time
def time_():
    return int(_time.time())


def ctime(t):
    return lit(_time.strftime('%a %b ', _time.localtime(t)).encode() + ('%2d' % _time.localtime(t).tm_mday).encode()
               + _time.strftime(' %H:%M:%S %Y\n', _time.localtime(t)).encode())
