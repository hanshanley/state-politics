"""Fine-tune the approved ModernBERT encoder on provenance-labelled, leakage-separated data."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import random
import re
from collections import Counter
from datetime import date
from itertools import product
from pathlib import Path

from ..bills.openstates_dump import STATE_CODES
from ..platforms.recovery import load_json, verify_manifest
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
TRAINING_ABSTENTIONS = {"non_policy", "mixed_policy", "insufficient_evidence"}
PLATFORM_STATES = frozenset(state.upper() for state in STATE_CODES)


def validate_split_isolation(rows: list[dict]) -> None:
    """Check validated examples together, including separately loaded evidence sets."""
    owners: dict[tuple[str, str], str] = {}
    for row in rows:
        normalized = re.sub(r"\W+", " ", row["text"].casefold()).strip()
        identities = [
            ("record", row["record_id"]),
            ("group", row["group_id"]),
            ("text", hashlib.sha256(normalized.encode()).hexdigest()),
        ]
        if row["label_origin"] == "reviewed_target" and row["domain"] == "plank":
            identities.append(("platform source", row["source_sha256"]))
            if row.get("document_text_sha256") is not None:
                identities.append(("platform document text", row["document_text_sha256"]))
        for kind, key in identities:
            previous = owners.setdefault((kind, key), row["split"])
            if previous != row["split"]:
                raise ValueError(
                    f"{row['record_id']}: {kind} leakage across {previous}/{row['split']}"
                )


def label_support(rows: list[dict], codes: list[int]) -> list[dict]:
    """Describe observed label support, not sampling representativeness or label validity."""
    support = []
    for split, domain in product(sorted(SPLITS), sorted(DOMAINS)):
        selected = [row for row in rows if (row["split"], row["domain"]) == (split, domain)]
        target = [row for row in selected if row["label_origin"] == "reviewed_target"]
        external = Counter(
            row["topic"] for row in selected if row["label_origin"] == "external_coded"
        )
        reviewed = Counter(row["topic"] for row in target)
        platforms = target if domain == "plank" else []
        sources = []
        for source_hash in sorted({row["source_sha256"] for row in platforms}):
            source_rows = [row for row in platforms if row["source_sha256"] == source_hash]
            sources.append({
                "source_sha256": source_hash, "n_rows": len(source_rows),
                "states_recorded": sorted({row.get("state") for row in source_rows}, key=str),
                "parties_recorded": sorted({row.get("party") for row in source_rows}, key=str),
                "rows_missing_state_or_party": sum(
                    not row.get("state") or not row.get("party") for row in source_rows
                ),
                "rows_missing_document_text_sha256": sum(
                    not row.get("document_text_sha256") for row in source_rows
                ),
            })
        support.append({
            "split": split, "domain": domain, "n_rows": len(selected),
            "label_origins": dict(Counter(row["label_origin"] for row in selected)),
            "topic_support": [
                {"topic": code, "external_coded": external[code],
                 "reviewed_target": reviewed[code]} for code in codes
            ],
            "topics_without_reviewed_target_positives": [
                code for code in codes if not reviewed[code]
            ],
            "reviewed_target_abstentions": dict(Counter(
                row["abstention_reason"] for row in target if row["topic"] is None
            )),
            "reviewed_platform_sources": sources,
        })
    return support


def load_examples(path: Path | str, codes: list[int]) -> list[dict]:
    """Validate split isolation and integer topics/explicit rejections before model loading."""
    rows = []
    seen_ids = set()
    for number, line in enumerate(Path(path).read_text().split("\n"), 1):
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
        if (type(row.get("topic")) is not int or row["topic"] not in codes) and not (
            row.get("topic") is None
            and isinstance(row.get("abstention_reason"), str)
            and row["abstention_reason"].strip()
            and "topic" in row
        ):
            raise ValueError(f"row {number}: invalid topic or missing abstention rationale")
        if row["split"] == "train" and row["topic"] is None and (
            row["label_origin"] != "reviewed_target"
            or row["abstention_reason"] not in TRAINING_ABSTENTIONS
        ):
            raise ValueError(f"row {number}: training rejection needs an explicit reviewed reason")
        normalized = re.sub(r"\W+", " ", row["text"].casefold()).strip()
        if not normalized:
            raise ValueError(f"row {number}: empty substantive input")
        text_hash = hashlib.sha256(row["text"].encode()).hexdigest()
        if row.get("text_sha256", text_hash) != text_hash:
            raise ValueError(f"row {number}: reviewed text hash mismatch")
        row["text_sha256"] = text_hash
        if row["label_origin"] == "reviewed_target" and row["domain"] == "plank":
            source_hash = row.get("source_sha256")
            if (
                not isinstance(source_hash, str)
                or re.fullmatch(r"[a-f0-9]{64}", source_hash) is None
            ):
                raise ValueError(f"row {number}: reviewed platform source body hash required")
            document_hash = row.get("document_text_sha256")
            if document_hash is not None and (
                not isinstance(document_hash, str)
                or re.fullmatch(r"[a-f0-9]{64}", document_hash) is None
            ):
                raise ValueError(f"row {number}: invalid platform document-text hash")
        rows.append(row)
    if not rows:
        raise ValueError("label manifest is empty")
    validate_split_isolation(rows)
    return rows


def validate_source_reservation(rows: list[dict], path: Path) -> dict:
    """Exclude reserved platform organizations and source identities from training."""
    verify_manifest(path.parent, {path.name})
    reservation = load_json(path)
    sources = reservation.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("source reservation requires a nonempty sources list")
    organizations = set()
    hashes = set()
    for source in sources:
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("state"), str)
            or source["state"] not in PLATFORM_STATES
            or source.get("party") not in ("D", "R")
            or source.get("organization") != f"{source['state']}-{source['party']}"
        ):
            raise ValueError("source reservation has an invalid organization")
        if source["organization"] in organizations:
            raise ValueError("source reservation has a duplicate organization")
        organizations.add(source["organization"])
        for key in ("source_sha256", "document_text_sha256"):
            value = source.get(key)
            if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
                raise ValueError(f"source reservation requires a valid {key}")
            hashes.add(value)
    for row in rows:
        if row["split"] != "train" or row["domain"] != "plank":
            continue
        identities = set()
        if row.get("state") is not None or row.get("party") is not None:
            if (
                not isinstance(row.get("state"), str)
                or row["state"] not in PLATFORM_STATES
                or row.get("party") not in ("D", "R")
            ):
                raise ValueError(f"{row['record_id']}: invalid platform state/party")
            identities.add(f"{row['state']}-{row['party']}")
        if row.get("organization") is not None:
            if not isinstance(row["organization"], str):
                raise ValueError(f"{row['record_id']}: invalid platform organization")
            identities.add(row["organization"])
        if row["group_id"].startswith("platform-organization:"):
            identities.add(row["group_id"].removeprefix("platform-organization:"))
        if any(
            not isinstance(value, str)
            or re.fullmatch(r"[A-Z]{2}-[DR]", value) is None
            or value[:2] not in PLATFORM_STATES
            for value in identities
        ) or len(identities) > 1:
            raise ValueError(f"{row['record_id']}: inconsistent platform organization identity")
        if row["label_origin"] == "reviewed_target" and not identities:
            raise ValueError(f"{row['record_id']}: reservation requires platform organization")
        if identities & organizations or any(
            row.get(key) in hashes for key in ("source_sha256", "document_text_sha256")
        ):
            raise ValueError(f"{row['record_id']}: reserved platform source in training")
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "manifest_sha256": sha256_file(path.parent / "manifest.json"),
        "reserved_organizations": sorted(organizations),
    }


def train(args) -> Path:
    topics = load_topics(args.topics)
    codes = [topic.code for topic in topics]
    rows = load_examples(args.labels, codes)
    reservation_path = getattr(args, "source_reservation", None)
    reservation = (
        validate_source_reservation(rows, reservation_path)
        if reservation_path is not None else None
    )
    train_rows = [row for row in rows if row["split"] == "train"]
    counts = Counter(row["topic"] for row in train_rows)
    outputs = [*codes, None] if counts[None] else codes
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
        examples.append((encoded, outputs.index(row["topic"])))
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION,
        config=modernbert_config(
            MODEL_ID, revision=MODEL_REVISION, num_labels=len(outputs),
            id2label={
                i: str(code) if code is not None else "ABSTAIN"
                for i, code in enumerate(outputs)
            },
            label2id={
                str(code) if code is not None else "ABSTAIN": i
                for i, code in enumerate(outputs)
            },
        ),
        trust_remote_code=False, attn_implementation="sdpa",
    ).to(device)
    model.gradient_checkpointing_enable()
    encoder_name, encoder_parameter = next(
        (name, parameter) for name, parameter in model.named_parameters()
        if name.endswith("attn.Wqkv.weight")
    )
    initial_encoder_parameter = encoder_parameter.detach().cpu().clone()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)
    weights = torch.tensor(
        [len(train_rows) / (len(outputs) * counts[code]) for code in outputs], device=device
    )
    criterion = torch.nn.CrossEntropyLoss(weight=weights)
    args.out.mkdir(parents=True)
    manifest = {
        "schema_version": 2 if counts[None] else 1,
        "model_id": MODEL_ID, "base_revision": MODEL_REVISION,
        "status": "provisional", "created_at": utc_now_iso(),
        "topic_codes": codes, "taxonomy_sha256": sha256_file(args.topics),
        "output_codes": outputs, "training_abstention_count": counts[None],
        "labels_sha256": sha256_file(args.labels),
        "source_reservation": reservation,
        "code_sha256": {
            name: sha256_file(Path(__file__).with_name(name))
            for name in ("train_topics.py", "modernbert.py", "taxonomy.py")
        },
        "dependency_versions": {
            package: importlib.metadata.version(package)
            for package in ("torch", "transformers", "tokenizers", "safetensors", "numpy")
        },
        "split_counts": dict(Counter(row["split"] for row in rows)),
        "reviewer_types": dict(Counter(
            row["reviewer_type"] for row in rows if row["label_origin"] == "reviewed_target"
        )),
        "training_topic_counts": {code: counts[code] for code in codes},
        "label_support": label_support(rows, codes),
        "hardware": describe_hardware(),
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
        "optimizer": {"name": "AdamW", "weight_decay": 0.01, "gradient_clip_norm": 1.0},
        "training_history": [],
        "limitations": [
            "not independently certified; do not publish",
            "record/group/text/platform-body and supplied document-text hashes checked",
            "missing document-text hashes and near-duplicate source families need review",
            "development calibration and held-out target-domain evaluation pending",
            "optimizer-state resumption is not implemented; interrupted runs need a new directory",
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
            if (start // args.batch_size + 1) % 100 == 0:
                print(json.dumps({
                    "epoch": epoch + 1, "examples_processed": start + len(batch),
                    "training_loss_so_far": loss_sum / (start + len(batch)),
                }), flush=True)
        epoch_report = {
            "epoch": epoch + 1, "training_loss": loss_sum / len(examples),
            "completed_at": utc_now_iso(),
        }
        manifest["training_history"].append(epoch_report)
        print(json.dumps(epoch_report), flush=True)
    if torch.equal(initial_encoder_parameter, encoder_parameter.detach().cpu()):
        raise RuntimeError("encoder parameters did not update; refusing a head-only checkpoint")
    manifest["encoder_update_verified"] = {"parameter": encoder_name, "changed": True}
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
    parser.add_argument(
        "--source-reservation", type=Path,
        help="manifest-bound reservation JSON excluding whole platform organizations",
    )
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
