"""Fine-tune the approved ModernBERT encoder on provenance-labelled, leakage-separated data."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from datetime import date
from pathlib import Path

from ..provenance import sha256_file, utc_now_iso
from .modernbert import (
    DOMAINS,
    INPUT_CONSTRUCTION,
    MODEL_ID,
    MODEL_REVISION,
    WINDOWING,
    model_input_ids,
    modernbert_config,
    policy_tokens,
)
from .taxonomy import DEFAULT_TOPICS_PATH, load_topics

SPLITS = {"train", "dev", "test", "challenge"}
LABEL_ORIGINS = {"external_coded", "reviewed_target"}


def load_examples(path: Path | str, codes: list[int]) -> list[dict]:
    """Validate the complete split manifest before a model or tokenizer is downloaded."""
    rows = []
    seen_ids = set()
    owners: dict[tuple[str, str], str] = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        required = (
            "record_id", "group_id", "split", "domain", "text", "source_url",
            "label_origin", "label_version", "evidence_tier",
        )
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
            raise ValueError(f"row {number}: missing nonempty evidence/label fields")
        if row["record_id"] in seen_ids:
            raise ValueError(f"row {number}: duplicate record_id")
        seen_ids.add(row["record_id"])
        if row["split"] not in SPLITS or row["domain"] not in DOMAINS:
            raise ValueError(f"row {number}: invalid split/domain")
        if row["label_origin"] not in LABEL_ORIGINS:
            raise ValueError(f"row {number}: model guesses are not independent labels")
        if row["label_origin"] == "reviewed_target":
            review_fields = ("reviewer_id", "reviewer_type", "reviewed_on", "rationale")
            if any(
                not isinstance(row.get(key), str) or not row[key].strip()
                for key in review_fields
            ) or row["reviewer_type"] not in ("human", "assistant", "local_model"):
                raise ValueError(f"row {number}: incomplete target-label review provenance")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["reviewed_on"]) is None:
                raise ValueError(f"row {number}: invalid review date")
            date.fromisoformat(row["reviewed_on"])
        if row["split"] in ("dev", "test", "challenge") and (
            row["label_origin"] != "reviewed_target"
        ):
            raise ValueError(f"row {number}: evaluation requires reviewed target-domain labels")
        if row.get("topic") not in codes and not (
            row.get("topic") is None and row.get("abstention_reason")
            and row["split"] != "train"
        ):
            raise ValueError(f"row {number}: invalid topic or missing abstention rationale")
        normalized = re.sub(r"\W+", " ", row["text"].casefold()).strip()
        if not normalized:
            raise ValueError(f"row {number}: empty substantive input")
        row["text_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
        fingerprint = hashlib.sha256(normalized.encode()).hexdigest()
        for kind, key in (("group", row["group_id"]), ("text", fingerprint)):
            previous = owners.setdefault((kind, key), row["split"])
            if previous != row["split"]:
                raise ValueError(f"row {number}: {kind} leakage across {previous}/{row['split']}")
        rows.append(row)
    if not rows:
        raise ValueError("label manifest is empty")
    return rows


def train(args) -> Path:
    topics = load_topics(args.topics)
    codes = [topic.code for topic in topics]
    rows = load_examples(args.labels, codes)
    train_rows = [row for row in rows if row["split"] == "train"]
    counts = Counter(row["topic"] for row in train_rows)
    missing = set(codes) - counts.keys()
    if missing:
        raise ValueError(f"training labels missing topics: {sorted(missing)}")
    if not any(row["split"] == "dev" for row in rows):
        raise ValueError("reviewed target-domain development labels are required")
    if args.out.exists():
        raise FileExistsError(
            f"{args.out} exists; use a new run directory, never overwrite a model"
        )

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from ..compute import describe_hardware, select_device

    device = select_device()
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION, trust_remote_code=False
    )
    examples = []
    for row in train_rows:
        prefix, tokens = policy_tokens(tokenizer, row["text"], row["domain"])
        encoded = {"input_ids": model_input_ids(tokenizer, prefix + tokens)}
        if len(encoded["input_ids"]) > args.max_tokens:
            raise ValueError(
                f"{row['record_id']}: training unit exceeds token budget; review/segment it "
                "rather than propagating its document label to unrelated chunks"
            )
        examples.append((encoded, codes.index(row["topic"])))
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION,
        config=modernbert_config(
            MODEL_ID, revision=MODEL_REVISION, num_labels=len(codes),
            id2label={i: str(code) for i, code in enumerate(codes)},
            label2id={str(code): i for i, code in enumerate(codes)},
        ),
        trust_remote_code=False, attn_implementation="sdpa",
    ).to(device)
    model.gradient_checkpointing_enable()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)
    weights = torch.tensor(
        [len(train_rows) / (len(codes) * counts[code]) for code in codes], device=device
    )
    criterion = torch.nn.CrossEntropyLoss(weight=weights)
    args.out.mkdir(parents=True)
    manifest = {
        "schema_version": 1, "model_id": MODEL_ID, "base_revision": MODEL_REVISION,
        "status": "provisional", "created_at": utc_now_iso(),
        "topic_codes": codes, "taxonomy_sha256": sha256_file(args.topics),
        "labels_sha256": sha256_file(args.labels),
        "split_counts": dict(Counter(row["split"] for row in rows)),
        "reviewer_types": dict(Counter(
            row["reviewer_type"] for row in rows if row["label_origin"] == "reviewed_target"
        )),
        "training_topic_counts": dict(counts), "hardware": describe_hardware(),
        "torch_version": torch.__version__,
        "input": {
            "max_tokens": args.max_tokens, "overlap": args.overlap,
            "construction": INPUT_CONSTRUCTION,
            "windowing": WINDOWING,
        },
        "decision": {"temperature": 1.0, "min_confidence": 0.8, "min_margin": 0.2},
        "decision_status": "uncalibrated_research_defaults",
        "seed": args.seed, "learning_rate": args.learning_rate,
        "batch_size": args.batch_size, "epochs": args.epochs,
        "limitations": [
            "not independently certified; do not publish",
            "group and normalized-text leakage checked; near-duplicate families need review",
            "development calibration and held-out target-domain evaluation pending",
        ],
    }
    for epoch in range(args.epochs):
        model.train()
        indices = list(range(len(examples)))
        random.Random(args.seed + epoch).shuffle(indices)
        loss_sum = 0.0
        for start in range(0, len(indices), args.batch_size):
            batch = [examples[i] for i in indices[start:start + args.batch_size]]
            inputs = tokenizer.pad(
                [item[0] for item in batch], padding=True, return_tensors="pt"
            ).to(device)
            targets = torch.tensor([item[1] for item in batch], device=device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(**inputs).logits, targets)
            if not torch.isfinite(loss):
                raise RuntimeError("non-finite training loss; checkpoint is not promotable")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            loss_sum += float(loss.detach().cpu()) * len(batch)
        print(json.dumps({"epoch": epoch + 1, "training_loss": loss_sum / len(examples)}),
              flush=True)
    model.save_pretrained(args.out, safe_serialization=True)
    tokenizer.save_pretrained(args.out)
    manifest["checkpoint_files"] = {
        path.name: sha256_file(path) for path in args.out.iterdir() if path.is_file()
    }
    (args.out / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return args.out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True, help="versioned JSONL label manifest")
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--overlap", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    args = parser.parse_args(argv)
    if (
        args.epochs < 1 or args.batch_size < 1 or not 32 <= args.max_tokens <= 8192
        or not 0 <= args.overlap < args.max_tokens - 16
        or not 0 < args.learning_rate < 1
    ):
        parser.error("invalid training dimensions or learning rate")
    print(f"saved provisional checkpoint: {train(args)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
