#!/usr/bin/env python3
"""Set a sandboxed step's resource limits, then exec it.

    limit_exec.py <fsize-bytes> <status-file> -- <command> [args...]

Used by scripts/sandbox_verify.py in place of subprocess's preexec_fn, which is
unsafe in threads: this runs as its own process, so nothing runs between the
caller's fork and exec. It sets RLIMIT_FSIZE to exactly <fsize-bytes> bytes
(the same unit setrlimit always uses) and RLIMIT_CORE to 0, restores the
default action of SIGXFSZ and SIGPIPE (Python ignores both, and an ignored
signal stays ignored across exec, which would turn "killed for writing too
much" into a silent write error), and execs the command. Limits are inherited
across exec and fork, so they apply to bubblewrap and to every process inside
it. If the limits cannot be set or the command cannot be started, it writes
the reason to <status-file> and exits 125. The caller decides "the launcher
failed" from that file alone, never from the exit code: the status file is
on the host, outside every mount of the sandbox, so a sandboxed program that
exits 125 itself, or prints anything, cannot pass for a launcher failure.
"""

import os
import resource
import signal
import sys


def main(argv):
    if len(argv) < 5 or argv[3] != "--" or not argv[1].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    fsize, status = int(argv[1]), argv[2]
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for sig in (signal.SIGXFSZ, signal.SIGPIPE):
            signal.signal(sig, signal.SIG_DFL)
        os.execv(argv[4], argv[4:])
    except (OSError, ValueError) as e:
        with open(status, "w") as fh:
            fh.write(f"limit_exec: {type(e).__name__}: {e}\n")
        return 125


if __name__ == "__main__":
    sys.exit(main(sys.argv))
