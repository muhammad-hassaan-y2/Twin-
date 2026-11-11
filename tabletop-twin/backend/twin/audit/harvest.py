"""`python -m twin.audit.harvest` - fetch the EU corpus and write the manifest."""

import sys

from twin.audit.corpus import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
