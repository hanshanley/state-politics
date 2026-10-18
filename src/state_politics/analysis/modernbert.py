"""Supervised local topic inference. No checkpoint means no production predictions."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from ..provenance import sha256_file
from .taxonomy import DEFAULT_TOPICS_PATH, load_topics

MODEL_ID = "answerdotai/ModernBERT-base"
MODEL_REVISION = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
DEFAULT_CHECKPOINT = Path("data/models/modernbert-topics")
DOMAINS = {"bill": "Bill policy", "plank": "Platform policy"}
INPUT_CONSTRUCTION = "separate_marker_and_text_tokens_v1"
WINDOWING = "paragraph_boundaries_with_overlap_v1"


def modernbert_config(source, **kwargs):
    """Keep the legacy compile setting out of newer model constructors."""
    from transformers import AutoConfig

    config = AutoConfig.from_pretrained(source, trust_remote_code=False, **kwargs)
    if hasattr(config, "reference_compile"):
        config.reference_compile = False
    return config


def model_input_ids(tokenizer, token_ids: list[int]) -> list[int]:
    """Apply ModernBERT's CLS/SEP wrapper without removed legacy tokenizer APIs."""
    wrapper = tokenizer.encode("", add_special_tokens=True)
    if (
        None in wrapper or len(wrapper) != 2
        or wrapper != [tokenizer.cls_token_id, tokenizer.sep_token_id]
    ):
        raise ValueError("tokenizer does not use the approved ModernBERT CLS/SEP wrapper")
    return [wrapper[0], *token_ids, wrapper[1]]


def policy_units(text: str) -> list[tuple[int, int, str]]:
    """Preserve paragraph text and offsets, attaching short headings to the following unit."""
    units = []
    pending_start = None
    for match in re.finditer(r"\S.*?(?=\n[ \t]*\n|\Z)", text, re.S):
        start = match.start() if pending_start is None else pending_start
        if len(text[start:match.end()].strip()) < 120:
            pending_start = start
            continue
        units.append((start, match.end(), text[start:match.end()]))
        pending_start = None
    if pending_start is not None:
        if units:
            start, _, _ = units.pop()
            units.append((start, len(text), text[start:]))
        else:
            units.append((pending_start, len(text), text[pending_start:]))
    return units


def token_windows(length: int, budget: int, overlap: int) -> list[tuple[int, int]]:
    if length < 0 or budget < 1 or not 0 <= overlap < budget:
        raise ValueError("require length >= 0 and 0 <= overlap < positive token budget")
    windows = []
    start = 0
    while start < length:
        end = min(start + budget, length)
        windows.append((start, end))
        if end == length:
            break
        start = end - overlap
    return windows


def section_windows(
    text: str, offsets: list[tuple[int, int]], budget: int, overlap: int,
) -> list[tuple[int, int]]:
    """Prefer paragraph boundaries while covering every token, including long paragraphs."""
    token_windows(0, budget, overlap)
    starts = [left for left, _ in offsets]
    boundaries = [
        bisect.bisect_left(starts, match.end())
        for match in re.finditer(r"\n[ \t]*\n", text)
    ]
    windows = []
    left = 0
    while left < len(offsets):
        right = min(left + budget, len(offsets))
        if right < len(offsets):
            candidates = [
                boundary for boundary in boundaries
                if left + max(overlap + 1, budget // 2) <= boundary <= right
            ]
            if candidates:
                right = candidates[-1]
        windows.append((left, right))
        if right == len(offsets):
            break
        left = right - overlap
    return windows


def policy_tokens(tokenizer, text: str, domain: str) -> tuple[list[int], list[int]]:
    """Use identical, separately tokenized source markers in training and inference."""
    if domain not in DOMAINS:
        raise ValueError("invalid policy domain")
    prefix = tokenizer.encode(DOMAINS[domain] + ":\n", add_special_tokens=False)
    tokens = tokenizer.encode(text, add_special_tokens=False)
    return prefix, tokens


@dataclass(frozen=True)
class Decision:
    topic: int | None
    candidate_topic: int | None
    runner_up: int | None
    score: float
    margin: float
    abstention_reason: str | None
    n_chunks: int
    scores: tuple[float, ...]


def decide(
    chunk_logits: list[list[float]],
    codes: list[int],
    *,
    temperature: float,
    min_confidence: float,
    min_margin: float,
) -> Decision:
    """Conservative chunk consensus; scores remain diagnostics, not proof of certainty."""
    if (
        len(codes) < 2 or len(set(codes)) != len(codes)
        or not math.isfinite(temperature) or temperature <= 0
        or not 0 <= min_confidence <= 1 or not 0 <= min_margin <= 1
    ):
        raise ValueError("invalid label map or decision thresholds")
    if not chunk_logits:
        return Decision(None, None, None, 0.0, 0.0, "insufficient_evidence", 0, ())
    probabilities = []
    for logits in chunk_logits:
        if len(logits) != len(codes) or not all(math.isfinite(x) for x in logits):
            raise ValueError("invalid or non-finite model logits")
        scaled = [x / temperature for x in logits]
        maximum = max(scaled)
        values = [math.exp(x - maximum) for x in scaled]
        total = sum(values)
        probabilities.append([x / total for x in values])
    means = [sum(row[i] for row in probabilities) / len(probabilities)
             for i in range(len(codes))]
    first, second = sorted(range(len(codes)), key=lambda i: means[i], reverse=True)[:2]
    winners = {max(range(len(codes)), key=lambda i: row[i]) for row in probabilities}
    margin = means[first] - means[second]
    reason = (
        "mixed_chunk_topics" if len(winners) > 1
        else "low_confidence" if means[first] < min_confidence
        else "ambiguous_margin" if margin < min_margin
        else None
    )
    return Decision(
        codes[first] if reason is None else None, codes[first], codes[second],
        means[first], margin, reason, len(chunk_logits), tuple(means),
    )


class ModernBertClassifier:
    """Load only saved fine-tuned local weights; refuse unvalidated runs by default."""

    def __init__(
        self, topics, checkpoint: Path | str = DEFAULT_CHECKPOINT, *,
        allow_provisional: bool = False, device: str | None = None,
        topics_path: Path | str = DEFAULT_TOPICS_PATH,
        calibration: Path | str | None = None,
    ):
        self.checkpoint = Path(checkpoint)
        manifest_path = self.checkpoint / "training_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"{manifest_path} missing. Train and independently evaluate ModernBERT first; "
                "the legacy embedding classifier is not an automatic fallback."
            )
        self.manifest = json.loads(manifest_path.read_text())
        if (
            self.manifest.get("schema_version") != 1
            or self.manifest.get("model_id") != MODEL_ID
            or self.manifest.get("base_revision") != MODEL_REVISION
        ):
            raise ValueError("checkpoint is not the approved ModernBERT-base model")
        if self.manifest["taxonomy_sha256"] != sha256_file(topics_path):
            raise ValueError("checkpoint taxonomy differs from the requested taxonomy")
        self.codes = self.manifest["topic_codes"]
        if self.codes != [topic.code for topic in topics]:
            raise ValueError("checkpoint label order differs from the requested taxonomy")
        if self.manifest["status"] != "certified" and not allow_provisional:
            raise ValueError(
                "ModernBERT checkpoint is provisional. Independent target-domain evaluation "
                "and calibrated abstention gates are required; "
                "--allow-provisional is research-only."
            )
        files = self.manifest.get("checkpoint_files", {})
        required = {"config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"}
        if not isinstance(files, dict) or not required <= files.keys():
            raise ValueError("checkpoint manifest lacks required model/tokenizer file hashes")
        for filename, digest in files.items():
            path = (self.checkpoint / filename).resolve()
            if (
                not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None
                or not path.is_relative_to(self.checkpoint.resolve()) or not path.is_file()
                or sha256_file(path) != digest
            ):
                raise ValueError(f"checkpoint file hash mismatch: {filename}")
        config = json.loads((self.checkpoint / "config.json").read_text())
        if (
            config.get("model_type") != "modernbert"
            or config.get("architectures") != ["ModernBertForSequenceClassification"]
            or config.get("id2label") != {str(i): str(code) for i, code in enumerate(self.codes)}
        ):
            raise ValueError("checkpoint architecture/label mapping differs from its manifest")
        inputs = self.manifest.get("input", {})
        if (
            inputs.get("construction") != INPUT_CONSTRUCTION
            or inputs.get("windowing") != WINDOWING
            or type(inputs.get("max_tokens")) is not int
            or not 32 <= inputs["max_tokens"] <= 8192
            or type(inputs.get("overlap")) is not int
            or not 0 <= inputs["overlap"] < inputs["max_tokens"] - 16
        ):
            raise ValueError("checkpoint input construction/windowing is incompatible")
        if self.manifest["status"] == "certified":
            raise ValueError(
                "certification is not implemented: reviewed labels and predeclared empirical "
                "gates remain unresolved; a status field alone cannot certify a checkpoint"
            )
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        from ..compute import select_device

        self.device = device or select_device()
        if self.device not in ("cpu", "mps"):
            raise ValueError("only local CPU/MPS devices are supported")
        self.model_name = MODEL_ID
        self.run_id = sha256_file(manifest_path)
        self.base_model_run = self.run_id
        self.calibration_sha256 = None
        if calibration is not None:
            calibration = Path(calibration)
            calibrated = json.loads(calibration.read_text())
            if (
                calibrated.get("status") != "development_calibrated"
                or calibrated.get("split") != "dev"
                or calibrated.get("model_run") != self.run_id
                or calibrated.get("taxonomy_sha256") != self.manifest["taxonomy_sha256"]
            ):
                raise ValueError(
                    "calibration is not bound to this model/taxonomy/development split"
                )
            decide([], self.codes, **calibrated["decision"])
            self.manifest["decision"] = calibrated["decision"]
            self.manifest["decision_status"] = "development_calibrated"
            self.calibration_sha256 = sha256_file(calibration)
            self.run_id = hashlib.sha256(
                (self.run_id + self.calibration_sha256).encode()
            ).hexdigest()
        self.topics = topics
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.checkpoint, local_files_only=True, trust_remote_code=False
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(
            self.checkpoint, local_files_only=True, trust_remote_code=False,
            attn_implementation="sdpa",
            config=modernbert_config(self.checkpoint, local_files_only=True),
        ).to(self.device).eval()

    def predict_records(self, texts: list[str], *, domain: str, batch_size: int = 8):
        import torch

        if domain not in DOMAINS or batch_size < 1:
            raise ValueError("invalid domain or batch size")
        config = self.manifest["input"]
        policy = self.manifest["decision"]
        prefix, _ = policy_tokens(self.tokenizer, "", domain)
        budget = config["max_tokens"] - len(prefix) - self.tokenizer.num_special_tokens_to_add()
        records = []
        for text in texts:
            encoded = self.tokenizer(
                text, add_special_tokens=False, return_offsets_mapping=True, truncation=False
            )
            ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
            windows = section_windows(text, offsets, budget, config["overlap"])
            logits = []
            spans = []
            for start in range(0, len(windows), batch_size):
                examples = []
                for left, right in windows[start:start + batch_size]:
                    examples.append({
                        "input_ids": model_input_ids(self.tokenizer, prefix + ids[left:right])
                    })
                    spans.append([offsets[left][0], offsets[right - 1][1]])
                inputs = self.tokenizer.pad(
                    examples, padding=True, return_attention_mask=True, return_tensors="pt"
                ).to(self.device)
                with torch.inference_mode():
                    logits.extend(self.model(**inputs).logits.float().cpu().tolist())
            decision = decide(logits, self.codes, **policy)
            record = asdict(decision)
            record.update(
                input_sha256=hashlib.sha256(text.encode()).hexdigest(),
                model_run=self.run_id, model_status=self.manifest["status"],
                score_type=(
                    "temperature_scaled_softmax"
                    if self.manifest["decision_status"] == "development_calibrated"
                    else "uncalibrated_softmax"
                ),
                n_input_tokens=len(ids), n_discarded_tokens=0,
                chunk_spans=json.dumps(spans), input_domain=domain,
                logits=json.dumps(logits), scores=json.dumps(decision.scores),
                calibration_sha256=self.calibration_sha256,
                base_model_run=self.base_model_run,
                taxonomy_sha256=self.manifest["taxonomy_sha256"],
            )
            records.append(record)
        return records


def add_model_arguments(parser) -> None:
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--allow-provisional", action="store_true",
                        help="explicit research-only use; never certification or publication")
    parser.add_argument(
        "--calibration", type=Path, help="development calibration bound to this run"
    )


def load_classifier(args, topics):
    return ModernBertClassifier(
        topics, args.checkpoint, allow_provisional=args.allow_provisional,
        topics_path=args.topics, calibration=args.calibration,
    )


def prediction_rows(classifier, texts, *, domain, batch_size, min_similarity=0.2):
    if hasattr(classifier, "predict_records"):
        return classifier.predict_records(texts, domain=domain, batch_size=batch_size)
    # Explicitly supplied historical baselines/test doubles; never an automatic CLI fallback.
    predictions = classifier.predict_many(
        texts, batch_size=batch_size, min_similarity=min_similarity
    )
    return [
        {
            "topic": code, "score": score, "margin": margin,
            "abstention_reason": "legacy_below_threshold" if code is None else None,
            "score_type": "legacy_similarity",
            "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "model_run": getattr(classifier, "model_name", type(classifier).__name__),
            "model_status": "legacy_baseline",
        }
        for text, (code, score, margin) in zip(texts, predictions, strict=True)
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True, help="JSONL evidence/label manifest")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--split", choices=("dev", "test", "challenge"), required=True)
    add_model_arguments(parser)
    args = parser.parse_args(argv)
    rows = [
        json.loads(line) for line in args.inputs.read_text().splitlines() if line.strip()
    ]
    rows = [row for row in rows if row.get("split") == args.split]
    if not rows:
        parser.error("selected split has no evidence records")
    ids = [row["record_id"] for row in rows]
    if len(set(ids)) != len(ids):
        parser.error("duplicate record IDs")
    model = load_classifier(args, load_topics(args.topics))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".part")
    with temporary.open("w") as handle:
        for row in rows:
            prediction = model.predict_records([row["text"]], domain=row["domain"])[0]
            handle.write(json.dumps({"record_id": row["record_id"], **prediction}) + "\n")
    temporary.replace(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
