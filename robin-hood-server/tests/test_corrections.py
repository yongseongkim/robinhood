from dataclasses import replace
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
from concurrent.futures import TimeoutError as FutureTimeout

import pytest

from robin_hood_server.codex_correction import correct_text
from robin_hood_server.correction_store import CorrectionStore
from robin_hood_server.ocr_correction import candidates, helpers, run_corrections


@pytest.fixture
def ocr_config(config, tmp_path):
    root = tmp_path / "source"
    (root / "pipeline").parent.mkdir(parents=True)
    (root / "pipeline").symlink_to(config.root / "pipeline", target_is_directory=True)
    raw = root / "data/raw/mapo"
    raw.mkdir(parents=True)
    pdf = raw / "source.pdf"
    pdf.write_bytes(b"%PDF-1.7\noriginal-immutable-document")
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    (raw / "manifest.json").write_text(
        json.dumps([{"attachments": [{"sha256": sha, "local_path": str(pdf)}]}])
    )
    stage = root / "data/staging"
    stage.mkdir(parents=True)
    rows = []
    for n, merchant in [(1, "한 빛식당"), (2, "한빛식당")]:
        rows.append(
            {
                "source_id": "mapo",
                "doc_id": "mapo:" + sha[:12],
                "doc_title": "source.pdf",
                "doc_url": "https://example.com/source.pdf",
                "post_url": "https://example.com/post",
                "council": "마포구의회",
                "period": "2024-01",
                "row_no": n,
                "date": "2024-01-02",
                "time": "12:30",
                "amount": 130000,
                "attendees": 10,
                "budget_item": "의회운영업무추진비",
                "user_role": "의장",
                "merchant_name": merchant,
                "merchant_address": "서울 마포구 주소",
                "purpose": "지역 주민 간 담회",
                "payment_method": "카드",
                "ocr": True,
                "parse_confidence": "LOW",
            }
        )
    (stage / "mapo_ocr.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    )
    return replace(
        config,
        root=root,
        ocr_correction_enabled=True,
        ocr_model="configured-test-model",
    )


def patch(
    field="purpose", before="지역 주민 간 담회", after="지역 주민 간담회", **extra
):
    return {
        "row_no": 1,
        "field": field,
        "before": before,
        "after": after,
        "reason": "OCR 띄어쓰기 정리",
        "evidence": "지역 주민 간 담회",
        **extra,
    }


def test_correction_preserves_originals_and_is_idempotent(ocr_config):
    paths = list((ocr_config.root / "data").rglob("*"))
    originals = {p: p.read_bytes() for p in paths if p.is_file()}
    calls = []

    def runner(_, payload):
        calls.append(payload)
        assert all(
            set(row)
            <= {
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
            }
            for row in payload["rows"]
        )
        assert ".pdf" not in json.dumps(payload) and "https://" not in json.dumps(
            payload
        )
        return {
            "patches": [patch(), patch("merchant_name", "한 빛식당", "한빛식당")],
            "issues": [],
        }

    first = run_corrections(ocr_config, runner=runner)
    assert first["acceptedChanges"] == 2 and first["processed"] == 1
    second = run_corrections(ocr_config, runner=runner)
    assert second["cached"] == 1 and len(calls) == 1
    assert all(p.read_bytes() == content for p, content in originals.items())
    helper, _ = helpers(ocr_config.root)
    rows = candidates(ocr_config)[0]["input_rows"]
    overlay = json.loads((ocr_config.var / "ocr-corrections.json").read_text())
    corrected = helper.apply_rows(rows, overlay)
    assert corrected[0]["purpose"] == "지역 주민 간담회"
    assert corrected[0]["merchant_name"] == "한빛식당"
    assert sum(r["amount"] for r in corrected) == sum(r["amount"] for r in rows)
    assert len(corrected) == len(rows)
    assert corrected[0]["_ocr_correction"]["review_id"]
    assert rows[0]["purpose"] == "지역 주민 간 담회"


@pytest.mark.parametrize(
    "field,before,after",
    [
        ("amount", 130000, 140000),
        ("date", "2024-01-02", "2024-01-03"),
        ("attendees", 10, 11),
        ("budget_item", "의회운영업무추진비", "의정운영공통경비"),
        ("user_role", "의장", "부의장"),
        ("merchant_address", "서울 마포구 주소", "서울 중구 주소"),
    ],
)
def test_numerical_and_attribution_changes_remain_pending(
    ocr_config, field, before, after
):
    result = run_corrections(
        ocr_config,
        runner=lambda *_: {"patches": [patch(field, before, after)], "issues": []},
    )
    assert result["acceptedChanges"] == 0 and result["pendingChanges"] == 1
    assert (
        json.loads((ocr_config.var / "ocr-corrections.json").read_text())["rows"] == {}
    )
    record = CorrectionStore(ocr_config).get(candidates(ocr_config)[0]["id"])
    assert (
        record["state"] == "needs_review" and record["pending"][0]["before"] == before
    )


def test_cannot_invent_names_numbers_or_unverifiable_evidence(ocr_config):
    helper, _ = helpers(ocr_config.root)
    rows = candidates(ocr_config)[0]["input_rows"]
    result = helper.validate_proposals(
        rows,
        {
            "patches": [patch("merchant_name", "한 빛식당", "전혀새로운식당")],
            "issues": [],
        },
    )
    assert result["pending"] and not result["accepted"]
    changed = deepcopy(rows)
    changed[0]["purpose"] = "직원 10명 간 담회"
    result = helper.validate_proposals(
        changed,
        {
            "patches": [
                patch(
                    before="직원 10명 간 담회",
                    after="직원 11명 간담회",
                    evidence="직원 10명 간 담회",
                )
            ],
            "issues": [],
        },
    )
    assert result["pending"] and not result["accepted"]
    result = helper.validate_proposals(
        rows,
        {"patches": [patch(evidence="원문에서 보았다고 추정한 내용")], "issues": []},
    )
    assert result["pending"] and not result["accepted"]


def test_changed_source_rejects_stale_corrections_and_limits_calls(ocr_config):
    helper, _ = helpers(ocr_config.root)
    cfg = replace(ocr_config, ocr_batch_rows=1, ocr_max_batches=1)
    summary = run_corrections(
        cfg, runner=lambda *_: {"patches": [patch()], "issues": []}
    )
    assert summary["processed"] == 1 and summary["deferred"] == 1
    rows = candidates(ocr_config)[0]["input_rows"]
    overlay = json.loads((ocr_config.var / "ocr-corrections.json").read_text())
    rows[0]["amount"] += 1
    assert "_ocr_correction" not in helper.apply_rows(rows, overlay)[0]
    tampered = deepcopy(overlay)
    entry = next(iter(tampered["rows"].values()))
    entry["row_hash"] = helper.fingerprint(rows[0])
    entry["patches"] = [patch("amount", 130001, 140000)]
    with pytest.raises(ValueError):
        helper.apply_rows(rows, tampered)


def test_disabled_and_plan_modes_never_call_codex(ocr_config):
    runner = lambda *_: pytest.fail("Model must not be called")
    plan = run_corrections(ocr_config, runner=runner, plan=True)
    assert (
        plan["rows"] == 2
        and not ocr_config.var.joinpath("ocr-corrections.sqlite3").exists()
    )
    result = run_corrections(
        replace(ocr_config, ocr_correction_enabled=False), runner=runner
    )
    assert result["deferred"] == 1 and result["processed"] == 0


def test_invalid_response_is_recorded_and_not_applied(ocr_config):
    with pytest.raises(ValueError):
        run_corrections(
            ocr_config, runner=lambda *_: {"patches": [patch(row_no=999)], "issues": []}
        )
    record = CorrectionStore(ocr_config).get(candidates(ocr_config)[0]["id"])
    assert record["state"] == "failed"
    assert not (ocr_config.var / "ocr-corrections.json").exists()


def test_changed_model_is_a_new_review_and_unverified_pdf_is_not_sent(ocr_config):
    calls = []

    def runner(*args):
        calls.append(1)
        return {"patches": [], "issues": []}

    run_corrections(ocr_config, runner=runner)
    run_corrections(
        replace(ocr_config, ocr_model="another-configured-model"), runner=runner
    )
    assert len(calls) == 2
    pdf = ocr_config.root / "data/raw/mapo/source.pdf"
    pdf.write_bytes(pdf.read_bytes() + b"changed-external-source")
    plan = run_corrections(ocr_config, plan=True)
    assert plan["unverifiedDocuments"] == 1
    result = run_corrections(
        ocr_config,
        runner=lambda *_: pytest.fail("Unverified original must not be sent"),
    )
    assert result["processed"] == 0 and result["issues"] == 1


def test_sdk_receives_only_text_in_read_only_ephemeral_workspace(config, monkeypatch):
    codex = MagicMock()
    codex.__enter__.return_value = codex
    codex.account.return_value = SimpleNamespace(
        account=SimpleNamespace(root=SimpleNamespace(type="chatgpt"))
    )
    codex.thread_start.return_value.turn.return_value.run.return_value = (
        SimpleNamespace(final_response='{"patches":[],"issues":[]}')
    )
    ctor = MagicMock(return_value=codex)
    module = SimpleNamespace(
        Codex=ctor,
        CodexConfig=lambda **kw: SimpleNamespace(**kw),
        Sandbox=SimpleNamespace(read_only="read-only"),
        ApprovalMode=SimpleNamespace(deny_all="deny-all"),
    )
    monkeypatch.setitem(sys.modules, "openai_codex", module)
    monkeypatch.setenv("DATABASE_URL", "postgresql://do-not-forward")
    result = correct_text(config, {"rows": [{"purpose": "간 담회"}]})
    assert result == {"patches": [], "issues": []}
    runtime = ctor.call_args.args[0]
    assert runtime.env["DATABASE_URL"] == ""
    options = codex.thread_start.call_args.kwargs
    assert options["sandbox"] == "read-only" and options["ephemeral"]
    assert options["cwd"] != str(config.root) and not Path(options["cwd"]).exists()
    turn = codex.thread_start.return_value.turn.call_args
    assert isinstance(turn.args[0], str) and turn.kwargs["output_schema"]


@pytest.mark.parametrize("kind", ["apiKey", None])
def test_sdk_requires_chatgpt_login_before_starting_model(config, monkeypatch, kind):
    codex = MagicMock()
    codex.__enter__.return_value = codex
    codex.account.return_value = SimpleNamespace(
        account=SimpleNamespace(root=SimpleNamespace(type=kind))
    )
    module = SimpleNamespace(
        Codex=MagicMock(return_value=codex),
        CodexConfig=lambda **kw: SimpleNamespace(**kw),
        Sandbox=SimpleNamespace(read_only="read-only"),
        ApprovalMode=SimpleNamespace(deny_all="deny-all"),
    )
    monkeypatch.setitem(sys.modules, "openai_codex", module)
    with pytest.raises(RuntimeError, match="ChatGPT 로그인"):
        correct_text(config, {"rows": []})
    codex.thread_start.assert_not_called()


def test_sdk_timeout_interrupts_the_turn(config, monkeypatch):
    codex = MagicMock()
    codex.__enter__.return_value = codex
    codex.account.return_value = SimpleNamespace(
        account=SimpleNamespace(root=SimpleNamespace(type="chatgpt"))
    )
    module = SimpleNamespace(
        Codex=MagicMock(return_value=codex),
        CodexConfig=lambda **kw: SimpleNamespace(**kw),
        Sandbox=SimpleNamespace(read_only="read-only"),
        ApprovalMode=SimpleNamespace(deny_all="deny-all"),
    )
    monkeypatch.setitem(sys.modules, "openai_codex", module)
    pool = MagicMock()
    pool.submit.return_value.result.side_effect = FutureTimeout()
    monkeypatch.setattr(
        "robin_hood_server.codex_correction.ThreadPoolExecutor", lambda **kw: pool
    )
    with pytest.raises(TimeoutError):
        correct_text(config, {"rows": []})
    codex.thread_start.return_value.turn.return_value.interrupt.assert_called_once()
