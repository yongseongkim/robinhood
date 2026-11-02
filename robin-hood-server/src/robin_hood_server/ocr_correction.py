"""Bounded, incremental text correction stage between OCR parsing and normalization."""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import sys

from .codex_correction import PROMPT, PROMPT_VERSION, correct_text
from .correction_store import CorrectionStore
from .job_store import atomic_json

MAX_INPUT_CHARACTERS = 20_000
INPUT_FIELDS = (
    "row_no",
    "date",
    "time",
    "amount",
    "attendees",
    "budget_item",
    "user_role",
    "merchant_name",
    "purpose",
    "payment_method",
)


def helpers(root):
    sys.path.insert(0, str(root / "pipeline"))
    import ocr_overlay
    from common import mask_contacts

    return ocr_overlay, mask_contacts


def source_hashes(root, wanted):
    values = {}
    checked = {}
    for path in (root / "data/raw").glob("*/manifest.json"):
        try:
            body = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(body, list):
            continue
        for post in body:
            for item in post.get("attachments", []):
                sha = item.get("sha256") or ""
                doc_id = f"{path.parent.name}:{sha[:12]}"
                if len(sha) != 64 or doc_id not in wanted or not item.get("local_path"):
                    continue
                original = (root / item["local_path"]).resolve()
                if (
                    not original.is_relative_to((root / "data/raw").resolve())
                    or not original.is_file()
                ):
                    continue
                if original not in checked:
                    digest = hashlib.sha256()
                    with original.open("rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                    checked[original] = digest.hexdigest()
                if checked[original] == sha:
                    values[doc_id] = sha
    return values


def candidates(config):
    helper, mask = helpers(config.root)
    grouped = defaultdict(list)
    for path in sorted((config.root / "data/staging").glob("*_ocr.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("ocr") is True:
                grouped[row["doc_id"]].append(row)
    hashes = source_hashes(config.root, grouped)
    result = []
    for doc_id, rows in sorted(grouped.items()):
        rows.sort(key=lambda r: r["row_no"])
        if len({r["row_no"] for r in rows}) != len(rows):
            raise ValueError(f"OCR 행 번호 중복: {doc_id}")
        for offset in range(0, len(rows), config.ocr_batch_rows):
            batch = rows[offset : offset + config.ocr_batch_rows]
            data = [
                {
                    k: mask(r.get(k)) if isinstance(r.get(k), str) else r.get(k)
                    for k in INPUT_FIELDS
                }
                for r in batch
            ]
            # No image, PDF, document URL, filesystem path or street address in model input.
            payload = {"period": batch[0].get("period"), "rows": data}
            sha = hashes.get(doc_id, "")
            extraction = helper.fingerprint({"source_sha256": sha, "rows": batch})
            identity = helper.fingerprint(
                {
                    "extraction": extraction,
                    "prompt": PROMPT,
                    "version": PROMPT_VERSION,
                    "model": config.ocr_model,
                    "effort": config.ocr_effort,
                }
            )
            result.append(
                {
                    "id": identity,
                    "doc_id": doc_id,
                    "source_sha256": sha,
                    "extraction_sha256": extraction,
                    "prompt_version": PROMPT_VERSION,
                    "model": config.ocr_model or "account-default",
                    "input_rows": batch,
                    "payload": payload,
                    "characters": len(helper.canonical(payload)),
                }
            )
    return result


def run_corrections(config, *, runner=correct_text, plan=False):
    helper, _ = helpers(config.root)
    batches = candidates(config)
    summary = {
        "enabled": config.ocr_correction_enabled,
        "documents": len({b["doc_id"] for b in batches}),
        "rows": sum(len(b["input_rows"]) for b in batches),
        "batches": len(batches),
        "processed": 0,
        "cached": 0,
        "deferred": 0,
        "acceptedChanges": 0,
        "pendingChanges": 0,
        "issues": 0,
    }
    if plan:
        return {
            **summary,
            "mode": "plan",
            "maxBatchesPerRun": config.ocr_max_batches,
            "maxInputCharacters": MAX_INPUT_CHARACTERS,
            "maxBatchCharacters": max((b["characters"] for b in batches), default=0),
            "unverifiedDocuments": len(
                {b["doc_id"] for b in batches if not b["source_sha256"]}
            ),
        }
    store = CorrectionStore(config)
    overlay = {"version": 1, "rows": {}}
    for batch in batches:
        record = store.get(batch["id"])
        if record and record["state"] != "failed":
            summary["cached"] += 1
        elif (
            not config.ocr_correction_enabled
            or summary["processed"] >= config.ocr_max_batches
        ):
            summary["deferred"] += 1
            continue
        else:
            record = {k: v for k, v in batch.items() if k != "payload"}
            record["created_at"] = datetime.now(timezone.utc).isoformat()
            if not batch["source_sha256"] or batch["characters"] > MAX_INPUT_CHARACTERS:
                record.update(
                    state="needs_review",
                    accepted=[],
                    pending=[],
                    issues=[
                        {
                            "row_no": 0,
                            "reason": "원본 해시 미확인 또는 입력 크기 초과. 텍스트 정정 자동 실행을 보류했습니다.",
                        }
                    ],
                )
            else:
                try:
                    response = runner(config, batch["payload"])
                    checked = helper.validate_proposals(batch["input_rows"], response)
                    record.update(
                        **checked,
                        state="needs_review"
                        if checked["pending"] or checked["issues"]
                        else "complete",
                    )
                except Exception as error:
                    record.update(state="failed", errorType=type(error).__name__)
                    store.save(record)
                    raise
                summary["processed"] += 1
            store.save(record)
        # Revalidate cached output under the current policy before deriving the export.
        checked = helper.validate_proposals(
            batch["input_rows"], {"patches": record["accepted"], "issues": []}
        )
        if checked["pending"]:
            raise ValueError("저장된 OCR 정정 제안이 현재 검증 기준에 맞지 않습니다.")
        summary["acceptedChanges"] += len(checked["accepted"])
        summary["pendingChanges"] += len(record["pending"])
        summary["issues"] += len(record["issues"])
        for row in batch["input_rows"]:
            patches = [p for p in checked["accepted"] if p["row_no"] == row["row_no"]]
            if patches:
                overlay["rows"][helper.row_key(row)] = {
                    "row_hash": helper.fingerprint(row),
                    "review_id": record["id"],
                    "patches": patches,
                }
    atomic_json(config.var / "ocr-corrections.json", overlay)
    atomic_json(config.var / "ocr-correction-status.json", summary)
    return summary


def main():
    # Called only by the parent collection pipeline, which already owns the shared lock.
    from .config import settings

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    print(json.dumps(run_corrections(settings), ensure_ascii=False))


if __name__ == "__main__":
    main()
