import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"

HAVE_JAVA = shutil.which("javac") is not None and shutil.which("java") is not None
requires_java = pytest.mark.skipif(not HAVE_JAVA, reason="JDK not installed")
