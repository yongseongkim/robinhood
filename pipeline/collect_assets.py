"""국회공보 재산공개 PDF 수집 → data/raw/assets/

국회 홈페이지 '국회공보' 목록에서 제목에 '재산'이 들어간 호를 찾아, 가장 최근 정기재산공개 호를 받는다.
국회공보는 국회공직자윤리위원회가 공직자윤리법 제10조에 따라 공개하는 공고다(국회사무처 저작물, 자유이용).
"""
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone, timedelta

import requests

from common import RAW, ROOT

KST = timezone(timedelta(hours=9))
OUT = RAW / "assets"
BASE = "https://www.assembly.go.kr"
LIST = BASE + "/portal/cnts/cntsNamgzn/gongbo.do"


def list_issues(session):
    r = session.get(LIST, params={"cntsDivCd": "NAMGZN", "pdfClsCd": "CPR", "menuNo": "601019", "pageIndex": 1, "pdfSj": "재산"}, timeout=60)
    r.raise_for_status()
    issues = []
    for row in re.findall(r"<tr>.*?</tr>", r.text, re.S):
        title = re.search(r'class="board_subject100"[^>]*>\s*(.*?)\s*</a>', row, re.S)
        down = re.search(r'href="(/portal/cmmn/file/fileDown\.do\?atchFileId=[0-9a-f]+&amp;fileSn=\d+)"', row)
        date = re.search(r'<td title="(\d{4}-\d{2}-\d{2})"', row)
        if title and down and date:
            issues.append({"title": html.unescape(title.group(1)).strip(), "date": date.group(1), "url": BASE + html.unescape(down.group(1))})
    return issues


def main():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Macintosh) robinhood-collector"
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    have = {m["title"] for m in manifest}
    issues = [i for i in list_issues(s) if "정기재산공개" in i["title"]]
    if not issues:
        print("국회공보 재산공개 목록을 찾지 못함", file=sys.stderr)
        return
    latest = max(issues, key=lambda i: i["date"])
    if latest["title"] in have:
        print(f"이미 받음: {latest['title']}", file=sys.stderr)
        return
    r = s.get(latest["url"], timeout=120)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"PDF가 아님: {latest['url']}")
    no = re.search(r"제(\d{4}-\d+)호", latest["title"]).group(1)
    name = f"gongbo_{no}.pdf"
    (OUT / name).write_bytes(r.content)
    manifest.append({**latest, "file": name, "sha256": hashlib.sha256(r.content).hexdigest(), "bytes": len(r.content),
                     "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
                     "list_page": LIST + "?cntsDivCd=NAMGZN&pdfClsCd=CPR&menuNo=601019"})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"saved {name} ({len(r.content) / 1e6:.1f} MB) to {OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
