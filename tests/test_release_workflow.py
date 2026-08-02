"""Release workflow regression tests."""

from pathlib import Path


def test_publish_job_checks_out_repository_before_verifying_tag():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    publish_job = workflow.split("\n  publish:\n", maxsplit=1)[1]

    checkout = publish_job.index("actions/checkout@")
    release_create = publish_job.index("gh release create")

    assert checkout < release_create
