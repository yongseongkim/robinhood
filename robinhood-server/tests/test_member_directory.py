import json

from fastapi.testclient import TestClient

from robinhood_server.app import create_app
from robinhood_server.index import build_index, public_merchant_id


def test_successor_without_expenses_has_own_profile_and_disclosure(config):
    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False))

    seat = {"MONA_CD": "NEW", "HG_NM": "후임의원", "ORIG_NM": "서울 마포구을", "POLY_NM": "무소속"}
    save(config.data / "assembly.json", {"subjects": {"mona-NEW": {"member": seat}},
         "summary": {"fetched_at": "2026-10-01", "voteDates": {"22": "2026-09-28"}}})
    raw = config.data.parent / "raw"
    save(raw / "peti/filings.json", [{"id": "1", "name": "후임의원", "office": "국회의원", "kind": "수시",
         "published": "2026-09-22", "basis": "2026-06-04", "url": "https://www.peti.go.kr/peOptpListVie.do"}])
    save(raw / "assets/events/gazettes.json", {"issue":{"title":"수시공개", "date":"2026-09-22","url":"https://example.org/gazette",
         "totals":[{"name":"후임의원","amount":120000,"totalPage":2}]}})
    save(raw / "source-status/roster.json", {"state":"partial", "checkedAt":"2026-10-02","lastSuccess":"2026-10-01"})
    build_index(config)
    api = TestClient(create_app(config))
    directory = api.get("/api/v1/roster", params={"region":"서울 마포구"}).json()
    assert [r["id"] for r in directory["rows"]] == ["mona-NEW"]
    assert directory["asOf"] == "2026-10-01" and directory["check"]["state"] == "partial"
    current = api.get("/api/v1/subjects/mona-NEW").json()
    assert current["summary"]["amount"] is None
    assert current["filings"][0]["amount"] == 120000
    assert current["activity"]["voteDates"]["22"] == "2026-09-28"
    former = api.get("/api/v1/subjects/na-279").json()
    assert former["subject"]["currentSeat"] is None and former["summary"]["amount"] == 12000
    assert former["filings"] == []


def test_latest_report_and_all_category_merchant(config):
    docs = json.loads((config.data / "documents.json").read_text())
    docs.append({**docs[0], "doc_id": "ka:2025-22", "period": "2025"})
    (config.data / "documents.json").write_text(json.dumps(docs))
    path = config.data / "expenditures.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    row = next(r for r in rows if r["id"] == "retained")
    sample = {**row, "id":"rail-2025","date":"2025-06-02", "amount":131000,
              "doc_id":"ka:2025-22", "category":"교통", "description":"철도", "payee_region":"대전 동구"}
    with path.open("a") as output:
        output.write("\n" + json.dumps(sample) + "\n")
    build_index(config)
    api = TestClient(create_app(config))
    assert api.get("/api/v1/members").json()["scope"]["reportId"] == "ka:2025-22"
    tx = api.get("/api/v1/transactions/rail-2025").json()
    assert tx["payeeRegion"] == "대전 동구"
    mid = public_merchant_id(row["merchant_id"])
    query = {"start":"2025-06-02","end":"2025-06-02","mealOnly":"false"}
    merchant = api.get("/api/v1/places/" + mid, params=query).json()
    assert merchant["summary"]["amount"] == 131000
    assert [r["id"] for r in merchant["transactions"]["rows"]] == ["rail-2025"]


def test_region_labels_keep_gyeonggi_gwangju_separate():
    from robinhood_server.constituency import region_label, seat_key
    assert region_label("경기도 광주시") == "경기 광주시"
    assert seat_key("광주광역시 북구갑") == seat_key("전남광주통합특별시 북구갑")
    assert seat_key("경기도 광주시갑") != seat_key("광주광역시 북구갑")
