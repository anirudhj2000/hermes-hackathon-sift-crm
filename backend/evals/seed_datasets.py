"""Upload the golden JSONL sets into Langfuse datasets (idempotent).

    python backend/evals/seed_datasets.py

The JSONL files under evals/golden/ stay the version-controlled source of
truth; this pushes them to Langfuse as datasets `sift-system-prompt` and
`sift-skills` so the runs show up in the experiment-compare UI. Requires
LANGFUSE_* keys; no-ops with a message otherwise.
"""

import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from agentcore import tracing  # noqa: E402

GOLDEN = os.path.join(HERE, "golden")
DATASETS = {
    "sift-system-prompt": "system_prompt.jsonl",
    "sift-skills": "skills.jsonl",
}


def _load_jsonl(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main():
    if not tracing.enabled():
        print("Langfuse keys unset — set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY "
              "in .env to seed datasets. (Evals still run offline via run_evals.py.)")
        return
    client = tracing.get_langfuse()
    if client is None:
        print("Could not initialize Langfuse client.")
        return

    for name, filename in DATASETS.items():
        cases = _load_jsonl(os.path.join(GOLDEN, filename))
        try:
            client.create_dataset(name=name, description=f"Sift golden set ({filename})")
        except Exception:
            pass  # already exists
        for case in cases:
            expected = case.get("expect")
            payload = {k: v for k, v in case.items() if k not in ("expect",)}
            try:
                client.create_dataset_item(
                    dataset_name=name, id=case["id"],
                    input=payload, expected_output=expected,
                )
            except Exception as exc:
                print(f"  ! {name}/{case['id']}: {exc}")
        print(f"seeded {name}: {len(cases)} items")

    client.flush()
    print("done.")


if __name__ == "__main__":
    main()
