"""Release workflow regression tests."""

from pathlib import Path


def test_publish_job_checks_out_repository_before_verifying_tag():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    publish_job = workflow.split("\n  publish:\n", maxsplit=1)[1]

    checkout = publish_job.index("actions/checkout@")
    release_create = publish_job.index("gh release create")

    assert checkout < release_create


WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def test_release_publishes_only_what_cosign_writes():
    """Cosign 3 ignores --output-signature, so a .sig would be promised but never published."""
    workflow = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    assert "cosign sign-blob" in workflow
    assert "--output-signature" not in workflow


def test_secret_scan_does_not_skip_tag_pushes():
    """gitleaks-action logs "No commits to scan" and passes on a tag push, which is how releases call it."""
    workflow = (WORKFLOWS / "security.yml").read_text(encoding="utf-8")
    gitleaks_job = workflow.split("\n  gitleaks:\n", maxsplit=1)[1]

    assert "gitleaks/gitleaks-action" not in gitleaks_job
    assert "sha256sum --check" in gitleaks_job
    assert 'gitleaks" git ' in gitleaks_job
    assert "fetch-depth: 0" in gitleaks_job
