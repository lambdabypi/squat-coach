import sys
from pathlib import Path

p = Path(sys.argv[1])
raw = p.read_bytes()
print("first bytes:", raw[:9])
txt = raw.decode("utf-8-sig").lstrip("﻿​�")
p.write_text(txt, encoding="utf-8", newline="\n")
print("first line now:", repr(txt.splitlines()[0][:60]))
