"""`python -m twin.audit.calibrate` - re-derive every audit threshold from the corpus."""

import sys

from twin.audit.priors import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
