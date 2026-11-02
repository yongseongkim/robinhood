from datetime import date
import sqlite3
import psycopg
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, settings
from .db import DatasetUnavailable, connect, payload
from .repository import NotFound
from .scopes import FUNDS, period, report_period
from .services import Dashboard
from .job_store import history, latest


def create_app(config: Settings = settings):
    app = FastAPI(
        title="나랏일보고서 API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.exception_handler(NotFound)
    async def not_found(_, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid_value(_, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(DatasetUnavailable)
    async def unavailable(_, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(sqlite3.DatabaseError)
    @app.exception_handler(psycopg.Error)
    async def invalid_database(_, error):
        return JSONResponse(
            {"detail": "조회 데이터를 읽지 못했습니다. 인덱스 상태를 확인해 주세요."},
            status_code=503,
        )

    def repository():
        with connect(config) as db:
            yield Dashboard(db, config)

    Repo = Annotated[Dashboard, Depends(repository)]

    def report_scope(
        report: str = "ka:2024-22", start: date | None = None, end: date | None = None
    ):
        return report_period(
            report,
            start.isoformat() if start else None,
            end.isoformat() if end else None,
        )

    def council_scope(year=2024, funding="COUNCIL_OPERATION", start=None, end=None):
        if funding == "POLITICAL_FUND" or funding not in FUNDS:
            raise ValueError("지방의회 경비 재원을 선택해 주세요.")
        return period(
            start.isoformat() if start else f"{year}-01-01",
            end.isoformat() if end else f"{year}-12-31",
            funding,
        )

    def place_scope(funding, start, end):
        if funding not in ("POLITICAL_FUND", "COUNCIL_OPERATION"):
            raise ValueError(
                "장소 비교는 정치자금 또는 의회운영업무추진비를 각각 선택합니다."
            )
        return period(
            start.isoformat()
            if start
            else ("2023-01-01" if funding == "POLITICAL_FUND" else "2024-01-01"),
            end.isoformat() if end else "2024-12-31",
            funding,
        )

    @app.get("/api/health")
    def health():
        try:
            with connect(config) as db:
                ready = payload(db, "indexed_at") is not None
        except (DatasetUnavailable, sqlite3.DatabaseError):
            ready = False
        return JSONResponse(
            {
                "status": "ok" if ready else "data_unavailable",
                "service": "robin-hood-server",
            },
            status_code=200 if ready else 503,
        )

    @app.get("/api/v1/meta")
    def meta(repo: Repo):
        return repo.meta()

    @app.get("/api/v1/geo")
    def geo(repo: Repo):
        return payload(repo.db, "geo", {})

    @app.get("/api/v1/overview")
    def overview(
        repo: Repo,
        region: str = Query("서울 마포구", max_length=100),
        report: str = "ka:2024-22",
        year: int = Query(2024, ge=2010, le=2100),
    ):
        return repo.overview(region, report_period(report), council_scope(year))

    @app.get("/api/v1/members")
    def members(
        repo: Repo,
        scope: Annotated[dict, Depends(report_scope)],
        party: str = Query("", max_length=100),
        q: str = Query("", max_length=100),
        region: str = Query("", max_length=100),
        page: int = Query(1, ge=1),
        page_size: int = Query(12, alias="pageSize", ge=1, le=100),
        sort: Literal["name", "amount"] = "name",
    ):
        return repo.members(
            scope,
            party=party,
            q=q,
            region=region,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    @app.get("/api/v1/subjects/{sid}")
    def subject(
        sid: str,
        repo: Repo,
        report: str = "ka:2024-22",
        year: int = Query(2024, ge=2010, le=2100),
        funding: str = Query("COUNCIL_OPERATION", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
        page: int = Query(1, ge=1),
    ):
        subject = repo.subject(sid, report)
        scope = (
            report_period(
                report,
                start.isoformat() if start else None,
                end.isoformat() if end else None,
            )
            if subject["type"] == "LEGISLATOR"
            else council_scope(year, funding, start, end)
        )
        return repo.profile(sid, scope, page)

    @app.get("/api/v1/councils")
    def councils(
        repo: Repo,
        year: int = Query(2024, ge=2010, le=2100),
        funding: str = Query("COUNCIL_OPERATION", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
    ):
        return repo.councils(council_scope(year, funding, start, end))

    @app.get("/api/v1/councils/{cid}")
    def council(
        cid: str,
        repo: Repo,
        year: int = Query(2024, ge=2010, le=2100),
        funding: str = Query("COUNCIL_OPERATION", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
    ):
        return repo.council(cid, council_scope(year, funding, start, end))

    @app.get("/api/v1/rankings")
    def rankings(
        repo: Repo,
        target: Literal["members", "councils", "assets"] = "members",
        metric: Literal["amount", "monthly_average", "change"] = "amount",
        report: str = "ka:2024-22",
        year: int = Query(2024, ge=2010, le=2100),
        party: str = Query("", max_length=100),
        category: str = Query("", max_length=100),
        funding: str = Query("COUNCIL_OPERATION", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
    ):
        if (
            target == "members"
            and metric != "amount"
            or target == "councils"
            and metric == "change"
            or target == "assets"
            and metric == "monthly_average"
        ):
            raise ValueError("선택한 대상에서 지원하지 않는 지표입니다.")
        scope = (
            council_scope(year, funding, start, end)
            if target == "councils"
            else report_period(
                report,
                start.isoformat() if start else None,
                end.isoformat() if end else None,
            )
        )
        return repo.rankings(scope, target, metric, party, category)

    @app.get("/api/v1/places")
    def places(
        repo: Repo,
        funding: str = Query("POLITICAL_FUND", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
        region: str = Query("", max_length=100),
        q: str = Query("", max_length=100),
        sort: Literal["payments", "amount", "payers"] = "payments",
        page: int = Query(1, ge=1),
        page_size: int = Query(12, alias="pageSize", ge=1, le=100),
    ):
        return repo.places(
            place_scope(funding, start, end), region, q, sort, page, page_size
        )

    @app.get("/api/v1/places/{mid}")
    def place(
        mid: str,
        repo: Repo,
        funding: str = Query("POLITICAL_FUND", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
        page: int = Query(1, ge=1),
    ):
        return repo.place(mid, place_scope(funding, start, end), page)

    @app.get("/api/v1/transactions")
    def transactions(
        repo: Repo,
        report: str | None = None,
        funding: str = Query("POLITICAL_FUND", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
        subject_id: str = Query("", alias="subjectId"),
        merchant_id: str = Query("", alias="merchantId"),
        category: str = "",
        q: str = Query("", max_length=100),
        page: int = Query(1, ge=1),
        page_size: int = Query(12, alias="pageSize", ge=1, le=100),
    ):
        scope = (
            report_period(
                report,
                start.isoformat() if start else None,
                end.isoformat() if end else None,
            )
            if report
            else period(
                start.isoformat() if start else "2024-01-01",
                end.isoformat() if end else "2024-12-31",
                funding,
            )
        )
        return repo.transactions(
            scope, subject_id, merchant_id, category, q, page, page_size
        )

    @app.get("/api/v1/transactions/{tid}")
    def transaction(tid: str, repo: Repo):
        return repo.transaction(tid)

    @app.get("/api/v1/fiscal")
    def fiscal(
        repo: Repo,
        year: int = Query(2024, ge=2010, le=2100),
        basis: Literal["actual", "budget", "proposal"] = "actual",
    ):
        return repo.fiscal(year, basis)

    @app.get("/api/v1/sources")
    def sources(repo: Repo):
        return repo.sources()

    @app.get("/api/v1/documents/{doc_id}")
    def document(doc_id: str, repo: Repo):
        data = repo.document(doc_id)
        if not data:
            raise NotFound("문서를 찾을 수 없습니다.")
        return data

    @app.get("/api/v1/findings")
    def findings(
        repo: Repo,
        subject_id: str = Query("", alias="subjectId"),
        funding: str = Query("", alias="fundingType"),
        q: str = Query("", max_length=100),
        page: int = Query(1, ge=1),
        page_size: int = Query(30, alias="pageSize", ge=1, le=100),
    ):
        if funding and funding not in FUNDS:
            raise ValueError("지원하지 않는 재원입니다.")
        return repo.findings_page(subject_id, funding, q, page, page_size)

    @app.get("/api/v1/jobs/status")
    def job_status():
        return latest(config)

    @app.get("/api/v1/jobs/history")
    def job_history(limit: int = Query(20, ge=1, le=100)):
        return {"rows": history(config, limit)}

    if (config.web_dist / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=config.web_dist / "assets"),
            name="web-assets",
        )

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "API 경로를 찾을 수 없습니다.")
        target = (config.web_dist / path).resolve()
        if target.is_relative_to(config.web_dist.resolve()) and target.is_file():
            return FileResponse(target)
        index = config.web_dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            {
                "service": "robin-hood-server",
                "docs": "/api/docs",
                "message": "웹은 robin-hood-web에서 실행하거나 빌드해 주세요.",
            }
        )

    return app


app = create_app()
