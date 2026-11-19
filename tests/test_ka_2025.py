"""The 2025 source renamed the payee header; preserve historical IDs and privacy."""
from datetime import datetime
import json
from pathlib import Path
import sys

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import normalize


def test_2025_report_header_income_and_private_recipient(tmp_path, monkeypatch):
    raw = tmp_path / 'ka-money'
    raw.mkdir()
    path = raw / '2025_KAPF_income_expense.xlsx'
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['총연번', '의원번호', '의원명', '당', '지역명', '연월일', '내역',
               '수입금회', '지출금회', '성명법인단체명', '생년월일-사업자번호', '분류'])
    ws.append([1, 279, '정청래', '더불어민주당', '서울 마포구을', datetime(2025, 2, 1),
               '간담회', None, 50000, '식당', None, '간담회_식대'])
    ws.append([2, 279, '정청래', '더불어민주당', '서울 마포구을', datetime(2025, 2, 2),
               '보수', None, 10000, '홍길동', None, '인건비_보수'])
    ws.append([3, 279, '정청래', '더불어민주당', '서울 마포구을', datetime(2025, 2, 3),
               '후원회 기부금', 100000, None, '후원회', None, '수입'])
    ws.append([4, 279, '정청래', '더불어민주당', '서울 마포구을', datetime(2025, 2, 4),
               '간담회 환급', None, -5000, '식당', None, '수입'])
    wb.save(path)
    expense = raw / '2025_KAPF.xlsx'
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['의원번호', '연월일', '지출액', '내역', '분류', '사용처'])
    ws.append([279, datetime(2025, 2, 1), 50000, '간담회', '간담회_식대', '식당'])
    ws.append([279, datetime(2025, 2, 2), 10000, '보수', '인건비_보수', '홍길동'])
    ws.append([279, datetime(2025, 2, 4), -5000, '간담회', '간담회_식대', '식당'])
    wb.save(expense)
    (raw / 'manifest.json').write_text(json.dumps([{
        'filename': '2025_KAPF_수입지출.xlsx', 'local_path': str(path.relative_to(tmp_path)),
        'github_url': 'https://example.com/2025', 'sha256': 'hash', 'fetched_at': '2026-11-15',
    }, {'filename': '2025_KAPF.xlsx', 'local_path': str(expense.relative_to(tmp_path)),
        'github_url': 'https://example.com/expenses', 'sha256': 'expense-hash'}]))
    monkeypatch.setattr(normalize, 'RAW', tmp_path)
    monkeypatch.setattr(normalize, 'ROOT', tmp_path)
    rows, subjects, documents = normalize.load_ka()
    transactions = normalize.normalize_ka(rows)
    assert documents[0]['doc_id'] == 'ka:2025-22'
    assert documents[0]['period'] == '2025-01-01 ~ 2025-12-31'
    assert subjects['na-279']['income']['2025']['후원회 기부금'] == 100000
    assert transactions[0]['id'] == 'ka25-1' and transactions[0]['payee_display'] == '식당'
    assert transactions[0]['date'] == '2025-02-01'
    assert not transactions[0]['quality']['flags']
    assert transactions[1]['payee_display'] == '개인(비공개)'
    assert '홍길동' not in json.dumps(transactions, ensure_ascii=False)

    assert len(transactions) == 3
    assert sum(t['amount'] for t in transactions) == 55000
    assert transactions[2]['amount'] == -5000
    assert transactions[2]['category'] == '간담회_식대'
    assert documents[0]['related_sources'][0]['sha256'] == 'expense-hash'
    expense.unlink()
    with pytest.raises(FileNotFoundError):
        normalize.load_ka()
