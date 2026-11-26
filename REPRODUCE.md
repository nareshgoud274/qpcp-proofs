# Reproducing a verification (Linux)

Each step page on the site has a "Reproduce this check" block: a verified
commit, a command, and the line it must print. This file is the setup that
command needs. It is the same setup `verify-main` uses on GitHub's
`ubuntu-latest` runner (`.github/workflows/verify-main.yml`).

## What you need

- Linux on x86_64. CI uses Ubuntu 24.04; other distributions need their own
  bubblewrap package and may not need the AppArmor profile below.
- `git`, `curl`, `python3` (the system one, in `/usr/bin`), and `sudo` to
  install bubblewrap.
- At least 10 GB of disk. Mathlib's prebuilt cache is downloaded, not built.
- **A disposable machine or VM.** The check builds files written by other
  contributors. It builds them inside bubblewrap sandboxes, but
  `scripts/install_sandbox.sh` also changes the system: it installs a package
  and an AppArmor profile that lets bubblewrap create user namespaces.

## Setup, once

```
git clone https://github.com/nareshgoud274/qpcp-proofs
cd qpcp-proofs
git checkout <the verified commit from the step page>
# Scratch space for the scripts; it must NOT be under /tmp, which the sandbox replaces.
export RUNNER_TEMP="$HOME/qpcp-tmp"
mkdir -p "$RUNNER_TEMP"
scripts/install_elan.sh                  # a pinned elan release, checked against its SHA-256
export PATH="$HOME/.elan/bin:$PATH"
lake exe cache get                       # Mathlib's prebuilt cache, at the committed revision
scripts/install_sandbox.sh               # bubblewrap, and a check that it isolates
```

Check out the verified commit before running anything else, so that the
toolchain (`lean-toolchain`), Mathlib (`lake-manifest.json`) and the checker
are the ones that verified the result.

## The check

Run the command from the step page, for example:

```
python3 -I scripts/sandbox_verify.py record --only QPCP.Proofs.S059
```

The last line must be the one the page gives, here `ACCEPTED: proof S059`.
For a refutation, the module is `QPCP.Refutations.<ID>` and the line is
`ACCEPTED: refutation <ID>`.

What it does:
1. It runs the source scanner on the whole tree.
2. It builds the maintainer-written modules and Mathlib outside the sandbox,
   and replays them with `leanchecker`.
3. It compiles that one result, and every merged result it imports, each in
   its own sandbox.
4. It replays each one with `leanchecker` and exports it to text.
5. It type-checks the export with an independent kernel (`nanoda`), and
   compares it with the statement exported from the maintainer-written
   modules.

It prints `REJECTED: ...` or `FAULT: ...` if any of that fails. Each run works
in a new directory under `$RUNNER_TEMP`.

An `--only` run checks the result, but it is never a published record:
`scripts/verification_record.py` refuses partial runs. The record on the site
comes from `verify-main`, which checks every contribution on the commit.

`tests/test_reproduce_command.py` runs the command the site prints, for a step
picked at random, on every maintainer pull request.
