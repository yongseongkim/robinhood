import argparse
import json

from .config import settings
from .index import build_index
from .jobs import collect, worker
from .jobs import run_due
from .postgres import JobAlreadyRunning, migrate
from .index import collection_lock
from .ocr_correction import run_corrections


def main():
    parser = argparse.ArgumentParser(prog="robinhood")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("index", help="이미 수집된 자료로 조회 인덱스 생성")
    migration = sub.add_parser(
        "migrate", help="서비스 전용 PostgreSQL 스키마 생성·마이그레이션"
    )
    migration.add_argument(
        "--post-deploy", action="store_true", help="새 API·worker 교체 후 컬럼 정리까지 적용"
    )
    correction = sub.add_parser(
        "ocr-correct", help="추출된 OCR 표 텍스트만 정정 (원본 변경 없음)"
    )
    correction.add_argument(
        "--plan", action="store_true", help="모델 호출·저장 없이 대상과 입력 크기 확인"
    )
    run = sub.add_parser("collect", help="수집·정규화 성공 후 새 인덱스 발행")
    run.add_argument("--no-fetch", action="store_true")
    due = sub.add_parser(
        "run-due", help="저장된 실행 시각이 지났을 때만 수집 (외부 스케줄러용)"
    )
    due.add_argument("--interval-hours", type=float, default=24)
    due.add_argument("--no-fetch", action="store_true")
    loop = sub.add_parser(
        "worker", help="주기적으로 수집; 이 명령을 실행할 때만 활성화"
    )
    loop.add_argument("--interval-hours", type=float, default=24)
    loop.add_argument("--no-fetch", action="store_true")
    api = sub.add_parser("serve", help="API와 빌드된 웹 실행")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "ocr-correct":
        if args.plan:
            result = run_corrections(settings, plan=True)
        else:
            with collection_lock(settings):
                if settings.postgres:
                    migrate(settings)
                result = run_corrections(settings)
        print(json.dumps(result, ensure_ascii=False))
    elif args.command == "migrate":
        if not settings.postgres:
            parser.error("DATABASE_URL 또는 ROBINHOOD_DATABASE_URL을 설정해 주세요.")
        migrate(settings, post_deploy=args.post_deploy)
        print(
            json.dumps(
                {
                    "database": "postgresql",
                    "schema": settings.database_schema,
                    "migration": "complete",
                }
            )
        )
    elif args.command == "index":
        print(json.dumps(build_index(settings), ensure_ascii=False))
    elif args.command == "collect":
        print(json.dumps(collect(settings, no_fetch=args.no_fetch), ensure_ascii=False))
    elif args.command == "worker":
        worker(settings, interval_hours=args.interval_hours, no_fetch=args.no_fetch)
    elif args.command == "run-due":
        try:
            result = run_due(
                settings, interval_hours=args.interval_hours, no_fetch=args.no_fetch
            )
        except JobAlreadyRunning:
            result = {"state": "skipped", "reason": "already_running"}
        print(json.dumps(result, ensure_ascii=False))
    else:
        import uvicorn

        uvicorn.run("robinhood_server.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
