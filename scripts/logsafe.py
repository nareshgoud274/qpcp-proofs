#!/usr/bin/env python3
"""Make contributor-controlled text safe to print in a CI log.

GitHub Actions reads a log line that starts with `::` as a workflow command
(`::error::`, `::add-mask::`, `::stop-commands::` and so on). Text a
contributor controls (file names, Lean error messages that quote the source,
names read from an export, pull request titles) is passed through log_safe()
before it is printed, so it can neither start a new line nor contain `::`.

    log_safe(text)                    one line: no line breaks, no `::`
    python3 -I scripts/logsafe.py     the same for each line of stdin
"""

import re
import sys

# Line breaks and every other control character, including the Unicode line
# and paragraph separators and NEL, become a space.
_BREAKS = re.compile("[\x00-\x1f\x7f\x85  ]")


def log_safe(text):
    text = _BREAKS.sub(" ", str(text))
    # Split every run of colons, so that no `::` survives (`:::` included).
    return re.sub(r":(?=:)", ": ", text)


if __name__ == "__main__":
    for line in sys.stdin:
        print(log_safe(line.rstrip("\n")))
