"""Copy the sample target into ./demo_repo as a fresh git repo on `main`, ready to scan.
Usage: python make_demo_repo.py"""
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
dest = root / "demo_repo"
if dest.exists():
    shutil.rmtree(dest, onerror=lambda f, p, e: (Path(p).chmod(0o700), f(p)))
shutil.copytree(root / "sample_target" / "african-arts-craft-api", dest)
g = lambda *a: subprocess.run(["git", "-C", str(dest), "-c", "user.name=demo", "-c", "user.email=demo@local", *a], check=True)
g("init", "-q", "-b", "main")
g("add", "-A")
g("commit", "-q", "-m", "initial import")
print(dest)
