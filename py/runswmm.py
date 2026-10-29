#!/usr/bin/env python3
"""runswmm for the Python port: same command line and console messages as EPA's run/main.c.
Written by Claude (Anthropic); see AI-USE.md."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swmm5 import engine
from swmm5.crt import lit, CPtr


def main(argv):
    version = engine.swmm_getVersion()
    vMajor = version // 10000
    vMinor = (version - 10000 * vMajor) // 1000
    vRelease = version - 10000 * vMajor - 1000 * vMinor
    out = sys.stdout
    if len(argv) == 0:
        out.write('\nNot Enough Arguments (See Help --help)\n\n')
    elif len(argv) == 1:
        a = argv[0]
        if a in ('--help', '-h'):
            out.write('\n\nSTORMWATER MANAGEMENT MODEL (SWMM) HELP\n\nCOMMANDS:\n\t--help (-h)       SWMM Help\n'
                      '\t--version (-v)    Build Version\n\nRUNNING A SIMULATION:\n'
                      '\t runswmm <input file> <report file> <optional output file>\n\n')
        elif a in ('--version', '-v'):
            out.write('\n%d.%d.%d\n\n' % (vMajor, vMinor, vRelease))
        else:
            out.write('\nUnknown Argument (See Help --help)\n\n')
    else:
        start = time.time()
        out.write('\n... EPA SWMM %d.%d (Build %d.%d.%d) [Python port]\n' % (vMajor, vMinor, vMajor, vMinor, vRelease))
        out.flush()
        engine.swmm_run(lit(argv[0].encode()), lit(argv[1].encode()), lit((argv[2] if len(argv) > 2 else '').encode()))
        out.write('\n\n... EPA SWMM completed in %.2f seconds.' % (time.time() - start))
        err = CPtr.buf(128)
        if engine.swmm_getError(err, 127) > 0:
            out.write(' There are errors.\n')
        elif engine.swmm_getWarnings() > 0:
            out.write(' There are warnings.\n')
        else:
            out.write('\n')
    out.flush()
    engine.stdout.f.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
