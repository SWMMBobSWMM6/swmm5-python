# swmm5-python

EPA SWMM 5.2.4 in Python, written by a translator that reads EPA's C, and judged against EPA itself:
the binary `.out` file byte for byte, and the `.rpt` report line for line except the three lines that
print the wall clock.

**Result: 451 of the 451 fast models (EPA within 1.5 s) identical, and 14 of a 14-model sample of the 29 slower ones identical.** Median CPU time 81.63 times EPA's (57.02 to 99.04 over 12 models, 3 interleaved repetitions; EPA against itself spans 0.98 to 1.06).

It is not a new engine. Every number it writes is EPA 5.2.4's, including the results of EPA's own defects
wherever EPA's behaviour is defined (see `lessons/02-epa-defects-found.md`).

## The parity contract

- Reference: EPA SWMM 5.2.4 built from the [USEPA v5.2.4 tag](https://github.com/USEPA/Stormwater-Management-Model/tree/v5.2.4)
  with gcc 13.3 `-O2` and `_FORTIFY_SOURCE` off (`ref/Makefile`), on x86-64 Linux with glibc 2.39.
- Each model runs in its own folder, as EPA's command line runs it.
- Pass = `.out` byte-identical (when EPA writes one) and `.rpt` identical after removing the lines
  `Analysis begun on`, `Analysis ended on` and `Total elapsed time`. When an input error stops EPA before it
  writes results, the engine must not write a results file either. Nothing else is excused.
- Corpus: [SWMMBobSWMM6/1729-SWMM5-Models-2030](https://github.com/SWMMBobSWMM6/1729-SWMM5-Models-2030),
  folders EPA, Hydraulics, Hydrology, LID, OWA_EXTRAN and OWA_ROUTING. The gate set is 480 of the 518 distinct models (distinct by content) in six folders of the corpus, which holds 4,540 .inp files. The other 38 were left out by an early timing survey with a 12-second limit, whose records were not kept. The cut is rough. Re-timed for this essay on a busy machine, 13 of the 38 ran past a 30-second limit and the rest took 5.8 to 29.6 seconds, 4 of them within 12; and 3 gate models took longer than 12 seconds in the reference run (attenuation_KW_High_CE.inp, 13 s, SCANLON.inp, 35 s, 72_H&H_Elements(2).inp, 39 s).
- 49 of the 480 stop on an input error. For 39 of them EPA writes no
  results file and the report is the whole comparison; the other 10 write a short one, which is compared.

| Engine | Gate result on the same 480 models |
|---|---|
| C++ swmm5-cplus | 480 of 480 identical |
| Rust swmm5-rust | 480 of 480 identical |
| Fortran | 480 of 480 identical |
| C# | 480 of 480 identical |
| Python | 465 identical (451 fast models, then a 14-model sample of the 29 slow ones) |

Controls: EPA run twice gives 40 of 40 identical files (null control). The Fortran
engine rebuilt with `-ffp-contract=fast -mfma` in place of `-ffp-contract=off` (`gate/build_fma_control.sh`)
differs from EPA on 87 of 480 models (positive control): the gate catches a
one-rounding-step change, and those 87 models are the ones that noticed it.

## Build and run

Requires Python 3.10 or newer, standard library only.

```sh
(nothing to build)
python3 py/runswmm.py model.inp model.rpt model.out
```

## How it was made

`tools/c2x/front.py` parses EPA's 54 C files with libclang, builds the program's tables and classifies all
2,083 pointer and array declarations by kind (array, single object, string, reference to a number, file,
`void*`, function). `tools/c2x/emit_py.py` writes the Python engine (31,568 lines, generated: `py/swmm5/engine.py`); a
hand-written runtime (1,253 lines) supplies the C library pieces SWMM uses and hand ports of `odesolve.c`,
`mempool.c` and six helper functions. When the port disagreed with EPA, the fix went into the translator or the
runtime, never into the generated file.

- Pure Python, standard library only: `py/swmm5/engine.py` is generated, `crt.py` is the C runtime, `overrides.py` holds the hand ports.
- Scalars whose address C takes are boxed; C's integer division, modulo and 32-bit wraparound are spelled out.
- Floating division by zero returns C's infinities and the x86 NaN (sign bit set, printed `-nan`) instead of raising.

To regenerate: `python3 tools/c2x/emit_py.py py/swmm5` from the repository root (needs `pip install libclang==18.1.1`
and the clang 18 headers at `/usr/lib/llvm-18/lib/clang/18/include`).

## Re-running the gate

```sh
make -C ref                                   # EPA 5.2.4 reference build
SWMM_CORPUS=/path/to/1729-SWMM5-Models-2030 gate/make_ref.sh       # reference outputs (about 1.2 GB)
SWMM_CORPUS=/path/to/1729-SWMM5-Models-2030 python3 gate/gate.py mine "python3 $PWD/py/runswmm.py"
```

`gate/gate.py` prints a summary and writes `gate/results/mine.json`; the stored runs behind the numbers above
are in `results/`.

## The six-engine app and the essay

`app/six-engines.html` compares EPA 5.2.4, swmm5-cplus, swmm5-rust (safe Rust, built from its repository at de9fbf1 and gated here), and the Fortran, C# and
Python ports on the stored corpus runs: gate results per model, report statistics, graphs with each engine's
difference from EPA, the benchmark, the controls and the defect register. Its Doc tab is the essay
*Six Engines, One Answer*, also in `docs/six-engines.docx`. Rebuild both with
`python3 tools/app/build_aux_data.py && python3 tools/app/build_data.py && python3 tools/app/build_app.py` and `node tools/app/doc/build_docx.js docs/six-engines.docx`.

## What this does not show

- That SWMM is right: identical to EPA means EPA's answers, good or bad. No observed data enter anywhere.
- Other platforms: the math library differs on Windows and macOS, and a port matches EPA built there only if its
  math library matches too.
- Paths no gate model exercises (counting only models that ran without an input error):
  Streets and inlets, Climate file, USE HOTSTART, USE INFLOWS (interface), USE RUNOFF. Street and inlet hydraulics appear in one deck, which stops on
  input errors; snowmelt runs in 4.
- Speed ratios come from 12 short models (EPA 0.01 to 0.72 s); long runs were not timed.
- The stepping API (`swmm_open`/`swmm_step`/...) is translated but only the command line was gated.
- No person has reviewed the generated code line by line; the evidence is the gate and the controls.

## Licence and credit

EPA SWMM is a work of the U.S. Environmental Protection Agency and is in the public domain; its engine is Lewis
Rossman's design, and this port keeps every algorithm as he wrote it. No licence has been chosen yet for the
translator and the runtime.

## AI use

See `AI-USE.md`.
