#!/usr/bin/env python3
"""Set a sandboxed step's resource limits, then exec it.

    limit_exec.py <fsize-bytes> -- <command> [args...]

Used by scripts/sandbox_verify.py in place of subprocess's preexec_fn, which is
unsafe in threads: this runs as its own process, so nothing runs between the
caller's fork and exec. It sets RLIMIT_FSIZE to exactly <fsize-bytes> bytes
(the same unit setrlimit always uses) and RLIMIT_CORE to 0, restores the
default action of SIGXFSZ and SIGPIPE (Python ignores both, and an ignored
signal stays ignored across exec, which would turn "killed for writing too
much" into a silent write error), and execs the command. Limits are inherited
across exec and fork, so they apply to bubblewrap and to every process inside
it. Exit 125 if the limits cannot be set.
"""

import os
import resource
import signal
import sys


def main(argv):
    if len(argv) < 4 or argv[2] != "--" or not argv[1].isdigit():
        print(__doc__, file=sys.stderr)
        return 125
    fsize = int(argv[1])
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for sig in (signal.SIGXFSZ, signal.SIGPIPE):
            signal.signal(sig, signal.SIG_DFL)
        os.execv(argv[3], argv[3:])
    except (OSError, ValueError) as e:
        print(f"limit_exec: {e}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    sys.exit(main(sys.argv))
