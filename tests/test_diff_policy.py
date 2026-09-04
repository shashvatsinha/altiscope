from __future__ import annotations

from altiscope.ingest.diff_policy import DiffPolicy, ExclusionReason, apply, classify, manifest
from altiscope.ingest.snapshot import FileStatus, PrFile


def _f(
    path: str,
    patch: str | None = "@@ -1 +1 @@\n-a\n+b\n",
    *,
    is_binary: bool = False,
) -> PrFile:
    return PrFile(
        path=path,
        status=FileStatus.modified,
        additions=1,
        deletions=1,
        patch=patch,
        is_binary=is_binary,
    )


def test_source_file_included():
    d = classify(_f("src/app.py"), DiffPolicy())
    assert d.included and d.reason is None


def test_lockfiles_excluded():
    for name in ("package-lock.json", "uv.lock", "go.sum", "Cargo.lock"):
        assert classify(_f(f"sub/{name}"), DiffPolicy()).reason is ExclusionReason.lockfile


def test_vendored_and_generated_and_minified():
    assert classify(_f("vendor/lib/x.go"), DiffPolicy()).reason is ExclusionReason.vendored
    assert classify(_f("node_modules/a/index.js"), DiffPolicy()).reason is ExclusionReason.vendored
    assert classify(_f("api/v1/thing.pb.go"), DiffPolicy()).reason is ExclusionReason.generated
    assert classify(_f("ui/__snapshots__/a.snap"), DiffPolicy()).reason is ExclusionReason.generated
    assert classify(_f("static/app.min.js"), DiffPolicy()).reason is ExclusionReason.minified


def test_binary_and_missing_patch():
    assert (
        classify(_f("a.png", patch=None, is_binary=True), DiffPolicy()).reason
        is ExclusionReason.binary
    )
    assert classify(_f("big.txt", patch=None), DiffPolicy()).reason is ExclusionReason.no_patch


def test_long_line_is_treated_as_minified():
    d = classify(_f("data/blob.json", patch="@@ -1 +1 @@\n+" + "x" * 6000 + "\n"), DiffPolicy())
    assert d.reason is ExclusionReason.minified


def test_oversize_single_file():
    d = classify(_f("gen.sql", patch="+x\n" * 100_000), DiffPolicy(max_patch_bytes=1000))
    assert d.reason is ExclusionReason.oversize


def test_total_cap_drops_largest_first_and_keeps_order():
    files = [
        _f("a.py", patch="+" + "a" * 100 + "\n"),
        _f("b.py", patch="+" + "b" * 900 + "\n"),
        _f("c.py", patch="+" + "c" * 300 + "\n"),
    ]
    out = apply(files, DiffPolicy(max_total_included_bytes=500))
    assert [d.path for d in out.decisions] == ["a.py", "b.py", "c.py"]
    assert [d.included for d in out.decisions] == [True, False, True]
    assert out.decisions[1].reason is ExclusionReason.oversize


def test_manifest_discloses_exclusions():
    files = [
        _f("src/a.py"),
        PrFile(
            path="yarn.lock", status=FileStatus.modified, additions=500, deletions=400, patch="x"
        ),
    ]
    m = manifest(apply(files))
    assert m.included_paths == ["src/a.py"]
    assert [e.path for e in m.excluded] == ["yarn.lock"]
    assert m.excluded_lines == 900
    assert m.policy["max_patch_bytes"] == DiffPolicy().max_patch_bytes
