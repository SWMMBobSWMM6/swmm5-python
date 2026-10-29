"""Hand-ported pieces of EPA SWMM 5.2.4 that use C pointer arithmetic the translator does not map:
odesolve.c (whole file), mempool.c (whole file), and five helpers from swmm5.c / project.c.
Each keeps the C statement order and floating-point expressions exactly.
Written by Claude (Anthropic); see AI-USE.md."""
import math, os
from .crt import CPtr, lit, strlen, strrchr, str_of, mkstemp

__all__ = ['sstrncpy', 'sstrcat', 'getAbsolutePath', 'getTempFileName', 'project_createMatrix', 'project_freeMatrix',
           'AllocInit', 'Alloc', 'AllocSetPool', 'AllocReset', 'AllocFreePool',
           'odesolve_open', 'odesolve_close', 'odesolve_integrate']


def sstrncpy(dest, src, n):
    offset = 0
    if n > 0:
        while src[offset] != 0:
            if offset == n:
                break
            dest[offset] = src[offset]
            offset += 1
    dest[offset] = 0
    return strlen(dest)


def sstrcat(dest, src, size):
    offset = strlen(dest)
    src_index = 0
    while src[src_index] != 0:
        dest[offset] = src[src_index]
        offset += 1
        src_index += 1
        if offset == size - 1:
            break
    dest[offset] = 0
    return strlen(dest)


def getAbsolutePath(fname, absPath, size):
    from . import engine
    if fname is None or strlen(fname) == 0:
        return
    if engine.isRelativePath(fname):
        try:
            full = os.path.realpath(str_of(fname)).encode()
        except OSError:
            return
        m = min(len(full), len(absPath.b) - absPath.o - 1)
        absPath.b[absPath.o:absPath.o + m] = full[:m]
        absPath.b[absPath.o + m] = 0
    else:
        sstrncpy(absPath, fname, strlen(fname))
    endOfDir = strrchr(absPath, ord('/'))
    if endOfDir is not None:
        endOfDir[1] = 0


def getTempFileName(fname):
    from . import engine
    sstrncpy(fname, lit(b'swmmXXXXXX'), engine.MAXFNAME)
    mkstemp(fname)
    return fname


def project_createMatrix(nrows, ncols):
    if nrows <= 0 or ncols <= 0:
        return None
    return [[0.0] * ncols for _ in range(nrows)]


def project_freeMatrix(a):
    return None


def AllocInit():
    return object()


def Alloc(n):
    return CPtr.buf(n)


def AllocSetPool(p):
    return p


def AllocReset():
    return None


def AllocFreePool():
    return None


# ------------------------------------------------------------------ odesolve.c (Cash-Karp Runge-Kutta)
MAXSTP = 10000
TINY = 1.0e-30
SAFETY = 0.9
PGROW = -0.2
PSHRNK = -0.25
ERRCON = 1.89e-4
_s = {'nmax': 0}


def odesolve_open(n):
    _s['nmax'] = 0
    for k in ('y', 'yscal', 'dydx', 'yerr', 'ytemp', 'ak2', 'ak3', 'ak4', 'ak5', 'ak6'):
        _s[k] = [0.0] * n
    _s['nmax'] = n
    return 1


def odesolve_close():
    _s.clear()
    _s['nmax'] = 0


def odesolve_integrate(ystart, n, x1, x2, eps, h1, derivs):
    y, yscal, dydx = _s['y'], _s['yscal'], _s['dydx']
    hdid = [0.0]
    hnext = [0.0]
    x = [x1]
    h = h1
    if _s['nmax'] < n:
        return 1
    for i in range(n):
        y[i] = ystart[i]
    for nstp in range(1, MAXSTP + 1):
        derivs(x[0], y, dydx)
        for i in range(n):
            yscal[i] = math.fabs(y[i]) + math.fabs(dydx[i] * h) + TINY
        if (x[0] + h - x2) * (x[0] + h - x1) > 0.0:
            h = x2 - x[0]
        errcode = _rkqs(x, n, h, eps, hdid, hnext, derivs)
        if errcode:
            break
        if (x[0] - x2) * (x2 - x1) >= 0.0:
            for i in range(n):
                ystart[i] = y[i]
            return 0
        if math.fabs(hnext[0]) <= 0.0:
            return 2
        h = hnext[0]
    return 3


def _rkqs(x, n, htry, eps, hdid, hnext, derivs):
    y, yerr, yscal, ytemp = _s['y'], _s['yerr'], _s['yscal'], _s['ytemp']
    xold = x[0]
    h = htry
    while True:
        _rkck(xold, n, h, derivs)
        errmax = 0.0
        for i in range(n):
            err = math.fabs(yerr[i] / yscal[i])
            if err > errmax:
                errmax = err
        errmax /= eps
        if errmax > 1.0:
            htemp = SAFETY * h * math.pow(errmax, PSHRNK)
            if h >= 0:
                h = htemp if htemp > 0.1 * h else 0.1 * h
            else:
                h = htemp if htemp < 0.1 * h else 0.1 * h
            xnew = xold + h
            if xnew == xold:
                return 2
            continue
        else:
            if errmax > ERRCON:
                hnext[0] = SAFETY * h * math.pow(errmax, PGROW)
            else:
                hnext[0] = 5.0 * h
            hdid[0] = h
            x[0] += h
            for i in range(n):
                y[i] = ytemp[i]
            return 0


def _rkck(x, n, h, derivs):
    y, dydx, ytemp, yerr = _s['y'], _s['dydx'], _s['ytemp'], _s['yerr']
    ak2, ak3, ak4, ak5, ak6 = _s['ak2'], _s['ak3'], _s['ak4'], _s['ak5'], _s['ak6']
    a2, a3, a4, a5, a6 = 0.2, 0.3, 0.6, 1.0, 0.875
    b21, b31, b32, b41, b42, b43 = 0.2, 3.0 / 40.0, 9.0 / 40.0, 0.3, -0.9, 1.2
    b51, b52, b53, b54 = -11.0 / 54.0, 2.5, -70.0 / 27.0, 35.0 / 27.0
    b61, b62, b63 = 1631.0 / 55296.0, 175.0 / 512.0, 575.0 / 13824.0
    b64, b65, c1 = 44275.0 / 110592.0, 253.0 / 4096.0, 37.0 / 378.0
    c3, c4, c6 = 250.0 / 621.0, 125.0 / 594.0, 512.0 / 1771.0
    dc5 = -277.0 / 14336.0
    dc1, dc3 = c1 - 2825.0 / 27648.0, c3 - 18575.0 / 48384.0
    dc4, dc6 = c4 - 13525.0 / 55296.0, c6 - 0.25
    for i in range(n):
        ytemp[i] = y[i] + b21 * h * dydx[i]
    derivs(x + a2 * h, ytemp, ak2)
    for i in range(n):
        ytemp[i] = y[i] + h * (b31 * dydx[i] + b32 * ak2[i])
    derivs(x + a3 * h, ytemp, ak3)
    for i in range(n):
        ytemp[i] = y[i] + h * (b41 * dydx[i] + b42 * ak2[i] + b43 * ak3[i])
    derivs(x + a4 * h, ytemp, ak4)
    for i in range(n):
        ytemp[i] = y[i] + h * (b51 * dydx[i] + b52 * ak2[i] + b53 * ak3[i] + b54 * ak4[i])
    derivs(x + a5 * h, ytemp, ak5)
    for i in range(n):
        ytemp[i] = y[i] + h * (b61 * dydx[i] + b62 * ak2[i] + b63 * ak3[i] + b64 * ak4[i] + b65 * ak5[i])
    derivs(x + a6 * h, ytemp, ak6)
    for i in range(n):
        ytemp[i] = y[i] + h * (c1 * dydx[i] + c3 * ak3[i] + c4 * ak4[i] + c6 * ak6[i])
    for i in range(n):
        yerr[i] = h * (dc1 * dydx[i] + dc3 * ak3[i] + dc4 * ak4[i] + dc5 * ak5[i] + dc6 * ak6[i])
