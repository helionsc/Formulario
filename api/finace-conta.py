import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototipos" / "contas-finace"))

from online import OnlineHandler


class handler(OnlineHandler):
    pass
