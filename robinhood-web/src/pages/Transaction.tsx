import { query, useMeta, useResource } from "../api";
import { href, Link } from "../router";
import { confidence, count, won } from "../format";
import {
  External,
  KeyValues,
  Notice,
  PageHeader,
  Panel,
  ResourceState,
  ScopeBar,
  Section,
  SourceNote,
  Stat,
} from "../components/ui";
import type { TransactionDetail } from "../types";

export function Transaction({ id }: { id: string }) {
  const resource = useResource<TransactionDetail>(
    "transactions/" + encodeURIComponent(id),
  );
  const data = resource.data;
  const meta = useMeta();
  if (!data) return <ResourceState {...resource} />;
  const political = data.fundingType === "POLITICAL_FUND";
  const holder = data.subject.holders.find(
    (h) => h.start <= data.date && h.end >= data.date,
  );
  return (
    <div className="page stack">
      <Link
        className="back-link"
        href={href(
          "/members/" + data.subjectId,
          political
            ? { report: data.docId, tab: "money" }
            : {
                fundingType: data.fundingType,
                year: data.date.slice(0, 4),
                tab: "money",
              },
        )}
      >
        ← {data.subjectName}의 내역
      </Link>
      <PageHeader
        title="거래 상세"
        context="기록과 출처"
        description={
          data.subjectName +
          " · " +
          (meta.fundingTypes[data.fundingType]?.label || data.fundingType)
        }
      />
      <ScopeBar scope={data.scope} />
      <div className="metrics">
        <Stat
          accent
          label="거래 1건 금액"
          value={won(data.amount)}
          detail={data.amount < 0 ? "취소·반환 금액" : "아래 날짜의 거래 금액"}
        />
        <Stat
          label="거래일·시각"
          value={data.time || "시각 미기재"}
          detail={data.date + " · " + (data.weekday || "")}
        />
        <Stat
          label="기재 인원"
          value={data.attendees ? count(data.attendees) + "명" : "미기재"}
          detail={
            political
              ? "정치자금 자료에는 인원 정보 없음"
              : "공개 집행내역에 적힌 인원"
          }
        />
        <Stat
          label="이 거래의 1인당 금액"
          value={data.perPerson ? won(data.perPerson) : "계산하지 않음"}
          detail={
            data.perPerson
              ? "거래 금액 ÷ 기재 인원 · 원 단위 반올림"
              : "계산 가능한 금액·인원이 필요합니다."
          }
        />
      </div>
      {data.duplicateOf && (
        <Notice>
          다른 공개 문서에 다시 실린 거래로 합계에서 제외합니다.{" "}
          <Link href={"/transactions/" + data.duplicateOf}>
            연결된 거래 보기
          </Link>
        </Notice>
      )}
      <div className="detail-columns">
        <div className="stack">
          <Panel title="집행 목적" description="공개 자료에 기재된 내용">
            <blockquote>{data.description || "미기재"}</blockquote>
            <KeyValues
              rows={[
                [political ? "보고 명의" : "집행 주체", data.subjectName],
                [
                  "거래처",
                  data.merchantId ? (
                    <Link
                      href={href("/places/" + data.merchantId, {
                        fundingType: data.fundingType,
                      })}
                    >
                      {data.payee}
                    </Link>
                  ) : (
                    data.payee
                  ),
                ],
                ["날짜·시각", data.date + " " + (data.time || "(시각 미기재)")],
                ["결제수단", data.payment],
                ["분류", data.category],
                ["분류 근거", data.categorySource],
                ...(political
                  ? ([
                      ["재원 계정", data.account],
                      ["영수증 번호", data.receiptNo],
                    ] as [string, string | undefined][])
                  : ([
                      ["예산 항목", data.budgetItem],
                      ["대수·임기", data.subject.term],
                    ] as [string, string | undefined][])),
              ]}
            />
          </Panel>
          {holder && (
            <Panel
              title="그때 이 직책을 맡은 사람"
              description="의회 공식 연혁에서 별도로 연결했습니다."
            >
              <h3>{holder.name}</h3>
              <KeyValues
                rows={[
                  ["재임 기간", holder.start + "–" + holder.end],
                  ["직책", data.subject.role],
                ]}
              />
              <External url={holder.sourceUrl}>
                {holder.sourceTitle || "의회 공식 연혁"}
              </External>
              <p className="caption">
                직책 보유자와 실제 결제·참석자는 같다고 단정할 수 없습니다.
              </p>
            </Panel>
          )}
          {data.pair && (
            <Panel title="연결된 취소·반환 거래">
              <KeyValues
                rows={[
                  [
                    "연결 내역",
                    <Link href={"/transactions/" + data.pair.id}>
                      {data.pair.description}
                    </Link>,
                  ],
                  ["거래일", data.pair.date],
                  ["건별 금액", won(data.pair.amount)],
                  ["두 거래의 순액", won(data.amount + data.pair.amount)],
                ]}
              />
            </Panel>
          )}
          {data.findings.length > 0 && (
            <Section
              title="추가 확인 표시"
              description="위반이 확정됐다는 뜻이 아닙니다."
            >
              {data.findings.map((f) => (
                <Panel key={f.id} title={"규칙 " + f.code}>
                  <p>{f.explanation}</p>
                  <p className="caption">{f.reference.description}</p>
                  <Link href={href("/sources", { tab: "methods" })}>
                    규칙과 정상적인 설명 확인 →
                  </Link>
                </Panel>
              ))}
            </Section>
          )}
        </div>
        <aside className="stack">
          <Panel title="출처와 확인 위치" description={data.document.publisher}>
            <h3>{data.document.title}</h3>
            <KeyValues
              rows={[
                ["형식", data.document.format],
                ["공개 대상 기간", data.document.period],
                ["원문 행", data.rowRef],
                ["수집일", data.document.fetched_at?.slice(0, 10)],
              ]}
            />
            <External url={data.document.url}>
              {data.document.format.includes("OCR")
                ? "OCR 정제자료 확인"
                : "공식 문서 확인"}
            </External>
            {data.document.origin_note && (
              <p className="caption">{data.document.origin_note}</p>
            )}
          </Panel>
          <Panel title="자료를 읽은 방식">
            <KeyValues
              rows={[
                ["OCR 사용", data.quality.ocr ? "예 · 오인식 가능" : "아니요"],
                [
                  "표 텍스트 정정",
                  data.quality.ocr_correction
                    ? "정정본 적용 · 원문 보존"
                    : "별도 정정본 없음",
                ],
                ["파싱 신뢰도", confidence(data.quality.parse_confidence)],
                [
                  "반환 연결",
                  data.pair ? "연결된 거래 있음" : "현재 연결된 거래 없음",
                ],
              ]}
            />
            {data.quality.ocr_correction && (
              <p className="caption">
                표의 문구·텍스트 열 정정본을 적용했습니다. 금액·날짜·인원·재원은
                추출값을 유지했습니다.
              </p>
            )}
            <p className="caption">
              {political
                ? "영수증 번호는 영수증 이미지 보유를 의미하지 않습니다. 실제 결제자가 의원 본인인지 보좌진인지는 구분되지 않습니다."
                : "기재 인원은 실제 참석자 명단과 다를 수 있습니다. 단순 나눗셈 값을 법령 위반 판단에 사용하지 않습니다."}
            </p>
          </Panel>
        </aside>
      </div>
      <SourceNote>
        {data.scope.note} {data.subject.attribution} 원문에서 금액·날짜·분류를
        확인해 주세요.
      </SourceNote>
    </div>
  );
}
