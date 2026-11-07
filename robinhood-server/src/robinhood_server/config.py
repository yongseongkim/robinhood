from dataclasses import dataclass, field
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    database: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "ROBINHOOD_DATABASE", ROOT / "robinhood-server/var/dashboard.sqlite3"
            )
        )
    )
    database_url: str = field(
        default_factory=lambda: os.getenv("ROBINHOOD_DATABASE_URL")
        or os.getenv("DATABASE_URL", ""),
        repr=False,
    )
    job_database_url: str = field(
        default_factory=lambda: os.getenv("ROBINHOOD_JOB_DATABASE_URL", ""), repr=False
    )
    database_schema: str = field(
        default_factory=lambda: os.getenv("ROBINHOOD_DATABASE_SCHEMA", "robinhood")
    )
    data: Path = field(
        default_factory=lambda: Path(
            os.getenv("ROBINHOOD_DATA", ROOT / "data/normalized")
        )
    )
    var: Path = field(
        default_factory=lambda: Path(
            os.getenv("ROBINHOOD_VAR", ROOT / "robinhood-server/var")
        )
    )
    naver_client_id: str = field(
        default_factory=lambda: os.getenv("NAVER_MAPS_CLIENT_ID", "")
    )
    web_dist: Path = field(
        default_factory=lambda: Path(
            os.getenv("ROBINHOOD_WEB_DIST", ROOT / "robinhood-web/dist")
        )
    )
    collector_python: str = field(
        default_factory=lambda: os.getenv(
            "ROBINHOOD_COLLECTOR_PYTHON", str(ROOT / ".venv/bin/python")
        )
    )
    ocr_correction_enabled: bool = field(
        default_factory=lambda: os.getenv(
            "ROBINHOOD_OCR_CORRECTION_ENABLED", "false"
        ).lower()
        == "true"
    )
    ocr_model: str = field(
        default_factory=lambda: os.getenv("ROBINHOOD_OCR_MODEL", "")
    )
    ocr_effort: str = field(
        default_factory=lambda: os.getenv("ROBINHOOD_OCR_EFFORT", "")
    )
    ocr_codex_home: str = field(
        default_factory=lambda: os.getenv("ROBINHOOD_OCR_CODEX_HOME", "")
    )
    ocr_max_batches: int = field(
        default_factory=lambda: int(os.getenv("ROBINHOOD_OCR_MAX_BATCHES", "5"))
    )
    ocr_batch_rows: int = field(
        default_factory=lambda: int(os.getenv("ROBINHOOD_OCR_BATCH_ROWS", "40"))
    )
    ocr_timeout: int = field(
        default_factory=lambda: int(os.getenv("ROBINHOOD_OCR_TIMEOUT_SECONDS", "120"))
    )

    def __post_init__(self):
        if (
            not 1 <= self.ocr_max_batches <= 100
            or not 1 <= self.ocr_batch_rows <= 100
            or not 1 <= self.ocr_timeout <= 3600
        ):
            raise ValueError("OCR 정정 실행 한도·시간 설정을 확인해 주세요.")
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.database_schema):
            raise ValueError(
                "PostgreSQL 스키마는 소문자 영문·숫자·밑줄로 지정해 주세요."
            )
        if self.database_schema in {
            "public",
            "information_schema",
        } or self.database_schema.startswith("pg_"):
            raise ValueError("서비스 전용 PostgreSQL 스키마를 지정해 주세요.")

    @property
    def postgres(self):
        return bool(self.database_url)


settings = Settings()
