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
        version="0.2.0",
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
        repo: Repo,
        report: str | None = None, start: date | None = None, end: date | None = None
    ):
        return repo.report_scope(
            report,
            start.isoformat() if start else None,
            end.isoformat() if end else None,
        )

    def council_scope(repo, year=None, funding="COUNCIL_OPERATION", start=None, end=None):
        if funding == "POLITICAL_FUND" or funding not in FUNDS:
            raise ValueError("지방의회 경비 재원을 선택해 주세요.")
        year = year or repo.latest_council_year()
        return period(
            start.isoformat() if start else f"{year}-01-01",
            end.isoformat() if end else f"{year}-12-31",
            funding,
        )

    def place_scope(repo, funding, start, end, detail=False):
        if funding not in (FUNDS if detail else {"POLITICAL_FUND", "COUNCIL_OPERATION"}):
            raise ValueError(
                "장소 비교는 정치자금 또는 의회운영업무추진비를 각각 선택합니다."
            )
        latest = repo.report_scope() if funding == "POLITICAL_FUND" else council_scope(repo)
        return period(
            start.isoformat() if start else latest["start"],
            end.isoformat() if end else latest["end"],
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
                "service": "robinhood-server",
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
        region: str = Query("", max_length=100),
        report: str | None = None,
        year: int | None = Query(None, ge=2010, le=2100),
    ):
        return repo.overview(region, repo.report_scope(report), council_scope(repo, year))

    @app.get("/api/v1/member-rankings")
    def member_rankings(
        repo: Repo,
        report: str | None = None,
        party: str = Query("", max_length=100),
    ):
        # Asset boards use their own disclosure periods even when a selected accounting period is empty.
        scope = report_period(report) if report else repo.report_scope()
        return repo.member_rankings(scope, party)

    @app.get("/api/v1/roster")
    def roster(repo: Repo, region: str = Query("", max_length=100), q: str = Query("", max_length=100),
               party: str = Query("", max_length=100), district: str = Query("", max_length=30)):
        return repo.directory(region, q, party, district)

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
        report: str | None = None,
        year: int | None = Query(None, ge=2010, le=2100),
        funding: str = Query("COUNCIL_OPERATION", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
        page: int = Query(1, ge=1),
    ):
        sid = repo.resolve_member(sid)
        subject = repo.subject(sid, report)
        scope = (
            repo.report_scope(
                report,
                start.isoformat() if start else None,
                end.isoformat() if end else None,
            )
            if subject["type"] == "LEGISLATOR"
            else council_scope(repo, year, funding, start, end)
        )
        return repo.profile(sid, scope, page)

    @app.get("/api/v1/councils")
    def councils(
        repo: Repo,
        year: int | None = Query(None, ge=2010, le=2100),
        funding: str = Query("COUNCIL_OPERATION", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
    ):
        return repo.councils(council_scope(repo, year, funding, start, end))

    @app.get("/api/v1/councils/{cid}")
    def council(
        cid: str,
        repo: Repo,
        year: int | None = Query(None, ge=2010, le=2100),
        funding: str = Query("COUNCIL_OPERATION", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
    ):
        return repo.council(cid, council_scope(repo, year, funding, start, end))

    @app.get("/api/v1/rankings")
    def rankings(
        repo: Repo,
        target: Literal["members", "councils", "assets"] = "members",
        metric: Literal["amount", "monthly_average", "change"] = "amount",
        report: str | None = None,
        year: int | None = Query(None, ge=2010, le=2100),
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
            council_scope(repo, year, funding, start, end)
            if target == "councils"
            else repo.report_scope(
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
            place_scope(repo, funding, start, end), region, q, sort, page, page_size
        )

    @app.get("/api/v1/places/{mid}")
    def place(
        mid: str,
        repo: Repo,
        funding: str = Query("POLITICAL_FUND", alias="fundingType"),
        start: date | None = None,
        end: date | None = None,
        report: str | None = None,
        meal_only: bool = Query(True, alias="mealOnly"),
        page: int = Query(1, ge=1),
    ):
        if report and funding != "POLITICAL_FUND":
            raise ValueError("정치자금 보고서는 정치자금 재원에서만 선택할 수 있습니다.")
        scope = (repo.report_scope(report, start.isoformat() if start else None, end.isoformat() if end else None)
                 if report else place_scope(repo, funding, start, end, detail=not meal_only))
        return repo.place(mid, scope, page, meal_only)

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
            repo.report_scope(
                report,
                start.isoformat() if start else None,
                end.isoformat() if end else None,
            )
            if report
            else place_scope(repo, funding, start, end, detail=True)
        )
        return repo.transactions(
            scope, repo.resolve_member(subject_id), merchant_id, category, q, page, page_size
        )

    @app.get("/api/v1/transactions/{tid}")
    def transaction(tid: str, repo: Repo):
        return repo.transaction(tid)

    @app.get("/api/v1/fiscal")
    def fiscal(
        repo: Repo,
        year: int | None = Query(None, ge=2010, le=2100),
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
                "service": "robinhood-server",
                "docs": "/api/docs",
                "message": "웹은 robinhood-web에서 실행하거나 빌드해 주세요.",
            }
        )

    return app


app = create_app()
