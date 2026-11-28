"""Drive gate.main() through each decision with GitHub calls faked."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

GATE = Path(sys.argv[1])
CFG = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("gate", GATE)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
clock = [0.0]
g.time.time = lambda: clock[0]
g.time.sleep = lambda s: clock.__setitem__(0, clock[0] + s)

SHA = "a" * 40


def run(files, branch, checks, gpt, gem, comments=(), draft=False):
    calls = []
    pr = {"isDraft": draft, "labels": [], "headRefName": branch, "headRefOid": SHA,
          "files": [{"path": f} for f in files], "comments": list(comments), "state": "OPEN"}

    def gh_json(*a):
        if a[0] == "pr":
            return pr
        return [{"name": n, "status": "completed", "conclusion": c, "html_url": "u",
                 "check_suite": {"id": 1}} for n, c in checks]

    g.gh_json = gh_json
    g.gh = lambda *a: calls.append(a) or ""
    d = Path(tempfile.mkdtemp())
    for name, val in (("gpt.json", gpt), ("gemini.json", gem)):
        if val is not None:
            (d / name).write_text(val if isinstance(val, str) else json.dumps(val))
    os.environ.update(REPO="o/r", PR="1", HEAD_SHA=SHA, AI_LOOP_CONFIG=str(CFG),
                      REVIEW_DIR=str(d), ALLOW_FIX="true", OWN_SUITE="99")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        g.main()
    return dict(l.split("=", 1) for l in out.getvalue().split()), calls


cfg = json.loads(CFG.read_text())
req = cfg["required_checks"]
green = [(n, "success") for n in req]
F = ["src/rssfeeds/sources/metr.py", "tests/test_metr.py"]
clean = {"verdict": "approve", "files_reviewed": F, "findings": []}
must = {"verdict": "changes-requested", "files_reviewed": F, "findings": [
    {"severity": "must-fix", "file": F[0], "line": 3, "summary": "s", "failure_scenario": "f"}]}
blind = {"verdict": "approve", "files_reviewed": [], "findings": []}
fixmark = {"body": g.MARK_ROUND, "url": "x#issuecomment-1"}

cases = {
    "clean ai-fix PR -> merge": (dict(files=F, branch="ai-fix/issue-10", checks=green, gpt=clean, gem=clean), "merge"),
    "clean human PR -> needs-yulong": (dict(files=F, branch="yl/x", checks=green, gpt=clean, gem=clean), "needs-yulong"),
    "must-fix -> fix": (dict(files=F, branch="ai-fix/issue-10", checks=green, gpt=must, gem=clean), "fix"),
    "must-fix after 2 rounds -> needs-yulong": (dict(files=F, branch="ai-fix/issue-10", checks=green, gpt=must, gem=clean, comments=[fixmark, fixmark]), "needs-yulong"),
    "red tests -> fix": (dict(files=F, branch="ai-fix/issue-10", checks=[(n, "failure") for n in req], gpt=clean, gem=clean), "fix"),
    "required check missing -> needs-yulong": (dict(files=F, branch="ai-fix/issue-10", checks=[], gpt=clean, gem=clean), "needs-yulong"),
    "gemini missing -> needs-yulong": (dict(files=F, branch="ai-fix/issue-10", checks=green, gpt=clean, gem=None), "needs-yulong"),
    "blind review -> needs-yulong": (dict(files=F, branch="ai-fix/issue-10", checks=green, gpt=blind, gem=clean), "needs-yulong"),
    "wrapped gemini json -> merge": (dict(files=F, branch="ai-fix/issue-10", checks=green, gpt=clean, gem="Sure:\n```json\n" + json.dumps(clean) + "\n```"), "merge"),
}
bad = 0
for name, (kw, want) in cases.items():
    got, calls = run(**kw)
    status = "ok " if got["decision"] == want else "BAD"
    bad += status == "BAD"
    print(f"{status} {name}: {got['decision']}")
sys.exit(1 if bad else 0)
