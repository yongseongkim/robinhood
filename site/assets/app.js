/* Robin Hood — 정적 열람실. 서버 없이 site/data/*.js 조각을 <script>로 불러온다 (file:// 에서도 동작). */
(function () {
  'use strict';

  // ------------------------------------------------------------------ data loading
  const RH = (window.RH = { cache: {}, waiting: {} });
  RH.data = function (key, payload) {
    RH.cache[key] = payload;
    (RH.waiting[key] || []).forEach((fn) => fn(payload));
    delete RH.waiting[key];
  };
  function load(key, src) {
    if (key in RH.cache) return Promise.resolve(RH.cache[key]);
    return new Promise((resolve, reject) => {
      (RH.waiting[key] = RH.waiting[key] || []).push(resolve);
      if (document.querySelector('script[data-key="' + key + '"]')) return;
      const s = document.createElement('script');
      s.src = src;
      s.dataset.key = key;
      s.onerror = () => reject(new Error(src + ' 파일을 불러오지 못했습니다.'));
      document.head.appendChild(s);
    });
  }
  const loadMeta = () => load('meta', 'data/meta.js');
  const loadSubject = (sid) => load('s:' + sid, 'data/s/' + encodeURIComponent(sid) + '.js');
  const loadFindingsIndex = () => load('findings-index', 'data/findings-index.js');
  const loadMerchantIndex = () => load('merchant-index', 'data/merchant-index.js');
  function bucketOf(id) {
    let h = 5381;
    for (let i = 0; i < id.length; i++) h = ((h * 33) ^ id.charCodeAt(i)) >>> 0;
    return h % 256;
  }
  const loadMerchant = (mid) => load('m:' + bucketOf(mid), 'data/m/' + bucketOf(mid) + '.js').then((b) => b[mid]);

  // ------------------------------------------------------------------ formatting
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf = new Intl.NumberFormat('ko-KR');
  const won = (n) => (n == null ? '—' : nf.format(Math.round(n)) + '원');
  function short(n) {
    if (n == null) return '—';
    const a = Math.abs(n), sign = n < 0 ? '-' : '';
    if (a >= 1e12) return sign + (a / 1e12).toFixed(a >= 1e14 ? 0 : 1).replace(/\.0$/, '') + '조원';
    if (a >= 1e8) return sign + (a / 1e8).toFixed(a >= 1e10 ? 0 : 1).replace(/\.0$/, '') + '억원';
    if (a >= 1e4) return sign + nf.format(Math.round(a / 1e4)) + '만원';
    return sign + nf.format(a) + '원';
  }
  function tick(n) {
    if (n >= 1e12) return nf.format(Math.round(n / 1e12)) + '조';
    if (n >= 1e8) return (n / 1e8).toFixed(n % 1e8 ? 1 : 0) + '억';
    if (n >= 1e4) return nf.format(Math.round(n / 1e4)) + '만';
    return nf.format(n);
  }
  const pct = (x) => (x == null ? '—' : Math.round(x * 100) + '%');
  const href = (...parts) => '#/' + parts.map(encodeURIComponent).join('/');

  const SOURCE_NAME = { 'ka-money': '국회의원 정치자금', seoul: '서울특별시의회', gwanak: '관악구의회', mapo: '마포구의회' };  // META.councils로 보강
  const SUBJECT_TYPE = {
    LEGISLATOR: '국회의원', COUNCIL_ROLE: '의회 직책', COUNCIL_MEMBER: '사용자로 기재된 의원', COUNCIL_BODY: '위원회·공동경비',
    NEGOTIATION_GROUP: '교섭단체', SECRETARIAT: '의회사무국(공무원)', ORG: '기관',
  };
  const REF_TYPE = {
    REGULATORY: ['법령 기준 대조', 'reg'], STATISTICAL: ['통계 기준', ''], EXACT_MATCH: ['같은 값 반복', ''],
    KEYWORD: ['단어 일치', ''], DISCLOSURE: ['공개자료 점검', 'dq'],
  };
  const REVIEW = { NEEDS_CONTEXT: '맥락 확인 필요', DATA_QUALITY: '데이터 품질 점검', INFO: '참고 정보' };
  const DQ = { OCR_SECONDARY: '언론사 OCR 정제 자료(2차 자료)', STRUCTURED_SOURCE: '의회 공개 엑셀 원본', PDF_TEXT: '의회 공개 PDF에서 표 추출', MIXED_SOURCE: '의회 공개 PDF·엑셀에서 표 추출',
    OCR_SCAN: '스캔 PDF를 OCR로 읽은 값 (오독 가능, 원본 확인 필요)' };
  const FLAG = {
    DATE_OUTSIDE_REPORT_PERIOD: '공개 기간 밖 날짜', BIZNO_NAME_CONFLICT: '사업자번호·상호 불일치', ATTENDEES_MISSING: '인원 미기재',
    PAYEE_MISSING: '사용처 미기재', BUDGET_ITEM_INFERRED: '비목 추정', DATE_UNPARSEABLE: '날짜 판독 불가', DESCRIPTION_MISSING: '내역 미기재',
    DUPLICATE_ACROSS_DOCUMENTS: '다른 공개 파일에 같은 거래 (합계에서 뺌)',
    OCR_EXTRACTED: '스캔본 OCR로 읽음',
  };
  // 같은 거래가 다른 공개 파일에 다시 실린 행은 목록에는 보여주되 합계·차트에서는 뺀다
  const counted = (t) => !(t.flags || []).includes('DUPLICATE_ACROSS_DOCUMENTS');
  const CONFIDENCE = {
    HIGH: ['높음', '사업자등록번호가 일치하는 거래를 하나의 업체로 묶었습니다.'],
    MEDIUM: ['보통', '사업자번호가 없어 상호명과 소재 지역(시·군·구)이 같은 거래를 묶었습니다.'],
    LOW: ['낮음', '상호명만 같은 거래를 묶었습니다. 다른 업체가 섞였을 수 있습니다.'],
  };
  const OBS_LABEL = {
    transactionCount: '거래 건수', totalAmount: '합계', maxPerPerson: '최대 1인당 금액', maxRatio: '기준 대비 최대 배수', maxAmount: '최대 결제액',
    merchantShare: '해당 거래처 비중', max90DayCount: '90일 내 최대 이용 횟수', merchantName: '거래처', merchantIdConfidence: '거래처 식별 신뢰도',
    top3Share: '상위 3개 거래처 비중', hhi: '집중도 지수(HHI)', merchantCount: '거래처 수', times: '결제 시각', shareOfTransactions: '해당 연도 거래 중 비중',
    byDayType: '요일·공휴일별 건수', weekendHolidayShare: '주말·공휴일 비중', weekendHolidayCount: '주말·공휴일 건수', hospitalityCount: '식사·다과 건수',
    occurrences: '발생 횟수', crosses500kCount: '합계 50만원 이상(각 건 미만)', withoutTimeInfo: '시간 정보 없는 경우', sector: '추정 업종', keyword: '일치한 단어',
    keywords: '일치한 단어', matchedOn: '판단 근거', ratio: '기준 기간 대비 배수', windowAmount: '비교 기간 지출', baselineAmount: '기준 기간 지출',
    reelected22: '제22대 재선', month: '해당 월', monthAmount: '해당 월 지출', ratioToMedian: '월 중앙값 대비 배수', tags: '시기 표시',
    patternCount: '반복 패턴 수', groupCount: '중복 묶음 수', excessAmount: '중복분 합계', byKind: '유형별', refundedAmount: '반환액',
    examples: '내역 예시', amount: '금액', category: '분류', description: '내역', payee: '사용처', categories: '분류', byCategory: '분류별',
    firstMonth: '첫 공개 월', lastMonth: '최근 공개 월', missingMonths: '공개 게시글이 없는 달', topDescription: '가장 많이 쓰인 문구',
    topDescriptionShare: '그 문구의 비중', attendeesMissingShare: '인원 미기재 비중', payeeMissingCount: '사용처 미기재 건수', documentId: '문서', dates: '날짜',
    regions: '결제 지역', merchantId: null,
  };
  const MONEY_KEYS = new Set(['totalAmount', 'maxPerPerson', 'maxAmount', 'windowAmount', 'baselineAmount', 'monthAmount', 'excessAmount', 'refundedAmount', 'amount']);
  const SHARE_KEYS = new Set(['merchantShare', 'top3Share', 'shareOfTransactions', 'weekendHolidayShare', 'topDescriptionShare', 'attendeesMissingShare']);

  let META = null;
  const subjectById = {};
  const main = () => document.getElementById('main');

  function setPage(html, title) {
    main().innerHTML = html;
    document.title = (title ? title + ' — ' : '') + 'Robin Hood 공공 지출 열람실';
    document.querySelectorAll('.nav a').forEach((a) => {
      const cur = location.hash.startsWith(a.getAttribute('href'));
      if (cur) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }
  const tag = (label, cls) => '<span class="tag ' + (cls || '') + '">' + esc(label) + '</span>';
  const refTag = (t) => (REF_TYPE[t] ? tag(REF_TYPE[t][0], REF_TYPE[t][1]) : '');
  const ruleOf = (id) => META.rules.find((r) => r.id === id);
  function subjectLabel(s) {
    if (!s) return '';
    if (s.type === 'LEGISLATOR') return s.name + ' 의원';
    return s.name + (s.term ? ' (' + s.term + ')' : '');
  }
  function dayLabel(t) {
    if (!t.date) return '날짜 없음';
    const off = t.holiday || t.weekday === '토' || t.weekday === '일';
    const d = esc(t.date) + ' <span class="' + (off ? 'day-off' : 'muted') + '">' + esc(t.weekday || '') + '</span>';
    return d + (t.holiday ? '<br><small class="day-off">' + esc(t.holiday) + '</small>' : '');
  }
  function fundingLabel(k) { return (META.fundingTypes[k] || {}).label || k; }
  const personHref = (source, name) => href('p', source + ':' + name);
  function holderAt(s, d) {
    if (!s || !s.holders || !d) return null;
    return s.holders.find((h) => h.period_start <= d && d <= h.period_end) || null;
  }
  const HOLDER_CAVEAT = '의회 공식 홈페이지(의회연혁·역대 의장단 등)의 선출 기록 기준입니다. 직책 업무추진비는 직책 수행을 위한 경비이고 결제는 비서실·사무국 직원이 할 수 있으므로, 이 사람의 개인 지출이라는 뜻이 아닙니다.';
  function holdersBlock(s, all) {
    if (!s.holders) return '';
    const rows = s.holders.map((h) => {
      const tx = all.filter((t) => counted(t) && t.date && t.date >= h.period_start && t.date <= h.period_end);
      const byF = {};
      tx.forEach((t) => (byF[t.fundingType] = (byF[t.fundingType] || 0) + t.amount));
      const totals = Object.entries(byF).map(([k, v]) => esc(fundingLabel(k)) + ' <span class="num">' + short(v) + '</span>').join('<br>');
      const who = h.name ? '<a href="' + personHref(s.org_source, h.name) + '">' + esc(h.name) + '</a>' : '<span class="muted">확인하지 못함</span>';
      const src = h.name
        ? '<small><a href="' + esc(h.source_url) + '" target="_blank" rel="noopener">' + esc(h.source_title || '출처') + '</a>' + (h.confidence === 'MEDIUM' ? ', 날짜 일부 추정' : '') +
          (h.evidence ? '<br><span class="muted">“' + esc(h.evidence) + '”</span>' : '') + '</small>'
        : '<small class="muted">' + esc(h.note || '') + '</small>';
      return '<tr><td class="num"><small>' + esc(h.period_start) + ' ~ ' + esc(h.period_end) + '</small></td><td>' + who + (h.party ? '<br><small class="muted">' + esc(h.party) + '</small>' : '') +
        '</td><td class="r num">' + nf.format(tx.length) + '</td><td><small>' + (totals || '—') + '</small></td><td>' + src + '</td></tr>';
    }).join('');
    const group = s.type === 'NEGOTIATION_GROUP';
    return '<div class="holders"><h3>' + (group ? '이 기간 교섭단체 대표의원' : '이 기간 직책을 맡은 사람') + '</h3><p class="small ink2">' + HOLDER_CAVEAT +
      (group ? ' 교섭단체 의정운영공통경비는 소속 의원 전체의 공동 경비이므로 대표의원 개인의 지출로 보지 않습니다.' : '') + '</p><div class="table-wrap"><table><thead><tr><th>기간</th><th>직책 보유자</th><th class="r">거래</th><th>재원별 지출</th><th>근거</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>';
  }

  // ------------------------------------------------------------------ transactions
  // build_site.py의 encode()를 되돌린다: 사전 열은 index → 값, 잘린 행 끝은 null
  function decodeRows(t) {
    const c = t.cols, d = t.dict;
    return t.rows.map((r) => {
      const o = {};
      for (let i = 0; i < c.length; i++) {
        const v = r[i] === undefined ? null : r[i];
        o[c[i]] = d[c[i]] && v != null ? d[c[i]][v] : v;
      }
      return o;
    });
  }
  function txObjects(shard) {
    if (!shard._tx) shard._tx = decodeRows(shard.tx).map((o) => Object.assign(o, { ocr: shard.ocr }));
    return shard._tx;
  }
  function marksFor(findings) {
    const m = {};
    findings.forEach((f) => {
      (f.evidenceIds || []).forEach((id) => {
        (m[id] = m[id] || []).push(f);
      });
    });
    return m;
  }
  function docLink(docId, label) {
    const d = META.documents[docId];
    if (!d) return esc(docId);
    return '<a href="' + esc(d.url) + '" target="_blank" rel="noopener" title="' + esc(d.title) + '">' + esc(label || '원본') + '</a>';
  }

  function ledgerTable(rows, marks, sid, opts) {
    opts = opts || {};
    if (!rows.length) return '<div class="empty">조건에 맞는 거래가 없습니다.</div>';
    const showSubject = opts.showSubject;
    const holderSubj = opts.subject && opts.subject.holders ? opts.subject : null;
    let h = '<div class="table-wrap"><table><thead><tr>' +
      (showSubject ? '<th>지출 주체</th>' : '') +
      '<th>일자</th>' + (holderSubj ? '<th>직책 보유자</th>' : '') + '<th>시간</th><th class="r">금액</th><th>사용처</th><th>내역·집행목적</th><th>분류</th><th class="r">인원</th><th>결제</th><th>표시</th><th>원본</th></tr></thead><tbody>';
    rows.forEach((t) => {
      const fs = (marks && marks[t.id]) || [];
      const pattern = fs.filter((f) => f.reviewStatus !== 'DATA_QUALITY');
      const cls = [pattern.length ? 'marked' : '', t.amount < 0 ? 'neg' : '', opts.focus === t.id ? 'focus' : ''].join(' ');
      const subj = showSubject ? subjectById[t.subjectId] : null;
      const payee = t.merchantId
        ? '<a href="' + href('m', t.merchantId) + '">' + esc(t.payee) + '</a>'
        : esc(t.payee || '') || '<span class="muted">—</span>';
      const flags = (t.flags || []).map((f) => '<span class="flag">' + esc(FLAG[f] || f) + '</span>').join(' ');
      const pair = t.pair ? '<br><a class="small" href="' + href('s', sid || t.subjectId) + '?tx=' + encodeURIComponent(t.pair) + '">' + (t.amount < 0 ? '원거래' : '취소·반환 내역') + '</a>' : '';
      const per = t.attendees && t.amount > 0 && /식사|카페|간담회/.test(t.category || '') ? '<br><small class="muted">1인 ' + won(t.amount / t.attendees) + '</small>' : '';
      h += '<tr id="tx-' + esc(t.id) + '" class="' + cls + '">' +
        (showSubject ? '<td>' + (subj ? '<a href="' + href('s', subj.id) + '">' + esc(subjectLabel(subj)) + '</a>' : esc(t.subjectId)) + '</td>' : '') +
        '<td class="num">' + dayLabel(t) + '</td>' +
        (holderSubj ? '<td><small>' + ((holderAt(holderSubj, t.date) || {}).name ? '<a href="' + personHref(holderSubj.org_source, holderAt(holderSubj, t.date).name) + '">' + esc(holderAt(holderSubj, t.date).name) + '</a>' : '<span class="muted">미확인</span>') + '</small></td>' : '') +
        '<td class="num">' + esc(t.time || '') + '</td>' +
        '<td class="r num amt"><span>' + won(t.amount) + '</span>' + per + pair + '</td>' +
        '<td class="payee">' + payee + '</td>' +
        '<td class="desc">' + esc(t.description || '') + (flags ? '<br>' + flags : '') + '</td>' +
        '<td><small>' + esc(t.category || '') + '</small>' + (t.account ? '<br><small class="muted">' + esc(t.account) + ' 계정(추정)</small>' : '') + '</td>' +
        '<td class="r num">' + esc(t.attendees || '') + '</td>' +
        '<td><small>' + esc(t.payment || '') + '</small></td>' +
        '<td><span class="marks">' + fs.map((f) => '<a class="' + (f.reviewStatus === 'DATA_QUALITY' ? 'dq' : '') + '" href="' + href('f', f.subjectId, f.id) + '" title="' + esc(ruleOf(f.ruleId).name) + '">' + esc(f.code) + '</a>').join('') + '</span></td>' +
        '<td><small>' + docLink(t.docId) + '<br><span class="muted">' + esc(t.rowRef || '') + '</span></small></td></tr>';
    });
    return h + '</tbody></table></div>';
  }

  // ------------------------------------------------------------------ charts
  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }
  // 좁은 화면에서는 viewBox 폭을 줄여 글자가 실제 크기에 가깝게 보이게 한다 (그릴 때의 화면 폭 기준)
  const chartW = (base) => Math.round(Math.min(base, Math.max(300, (window.innerWidth || base) - 60)));
  function barChart(points, label) {
    // points: [{key, label, value}] — 단일 계열이므로 범례 없이 제목이 계열을 설명한다.
    if (!points.length) return '<div class="empty">표시할 자료가 없습니다.</div>';
    const W = chartW(680), H = 230, L = 54, R = 8, T = 12, B = 30;
    const max = niceMax(Math.max(...points.map((p) => Math.max(0, p.value))));
    const band = (W - L - R) / points.length;
    const bw = Math.max(2, Math.min(24, band * 0.68));
    const y = (v) => T + (H - T - B) * (1 - Math.max(0, v) / max);
    let g = '<g class="grid">';
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
    ticks.forEach((t) => (g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(t) + '" y2="' + y(t) + '"/>'));
    g += '</g><g class="axis">';
    ticks.forEach((t) => (g += '<text x="' + (L - 8) + '" y="' + (y(t) + 4) + '" text-anchor="end">' + tick(t) + '</text>'));
    const every = Math.ceil(points.length / (W >= 600 ? 12 : 6));
    points.forEach((p, i) => {
      if (i % every === 0) g += '<text x="' + (L + band * i + band / 2) + '" y="' + (H - 10) + '" text-anchor="middle">' + esc(p.label) + '</text>';
    });
    g += '</g><g>';
    points.forEach((p, i) => {
      const x = L + band * i + (band - bw) / 2, yy = y(p.value), h = H - B - yy;
      const r = Math.min(4, h / 2, bw / 2);
      const d = h <= 0 ? '' : 'M' + x + ',' + (H - B) + 'V' + (yy + r) + 'Q' + x + ',' + yy + ' ' + (x + r) + ',' + yy + 'H' + (x + bw - r) + 'Q' + (x + bw) + ',' + yy + ' ' + (x + bw) + ',' + (yy + r) + 'V' + (H - B) + 'Z';
      g += '<rect class="hit" x="' + (L + band * i) + '" y="' + T + '" width="' + band + '" height="' + (H - T - B) + '" data-tip="' + esc(p.key + ' ' + (Math.abs(p.value) >= 1e12 ? short(p.value) : won(p.value))) + '" data-cx="' + (x + bw / 2) + '" data-cy="' + yy + '"/>';
      g += '<path class="bar" d="' + d + '"/>';
    });
    g += '</g>';
    let table = '<table><thead><tr><th>기간</th><th class="r">금액</th></tr></thead><tbody>' +
      points.map((p) => '<tr><td>' + esc(p.key) + '</td><td class="r num">' + (Math.abs(p.value) >= 1e12 ? short(p.value) : won(p.value)) + '</td></tr>').join('') + '</tbody></table>';
    return '<div class="chart" data-w="' + W + '" data-h="' + H + '"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(label) + '">' + g +
      '</svg><div class="tooltip" role="status"></div></div><details class="table-view"><summary>표로 보기</summary><div class="table-wrap">' + table + '</div></details>';
  }
  function wireCharts(root) {
    root.querySelectorAll('.chart').forEach((c) => {
      const tip = c.querySelector('.tooltip');
      const svg = c.querySelector('svg');
      const W = +c.dataset.w;
      c.addEventListener('mousemove', (ev) => {
        const t = ev.target.closest('.hit');
        c.querySelectorAll('.bar.active').forEach((b) => b.classList.remove('active'));
        if (!t) { tip.classList.remove('on'); return; }
        t.nextElementSibling && t.nextElementSibling.classList.add('active');
        const scale = svg.getBoundingClientRect().width / W;
        tip.textContent = t.dataset.tip;
        tip.style.left = 14 + +t.dataset.cx * scale + 'px';
        tip.style.top = 14 + +t.dataset.cy * scale + 'px';
        tip.classList.add('on');
      });
      c.addEventListener('mouseleave', () => {
        tip.classList.remove('on');
        c.querySelectorAll('.bar.active').forEach((b) => b.classList.remove('active'));
      });
    });
  }
  function hbars(items, fmt) {
    if (!items.length) return '<div class="empty">자료 없음</div>';
    const max = Math.max(...items.map((i) => Math.abs(i.value))) || 1;
    return '<ul class="hbars">' + items.map((i) =>
      '<li><span class="lbl" title="' + esc(i.label) + '">' + (i.href ? '<a href="' + i.href + '">' + esc(i.label) + '</a>' : esc(i.label)) + '</span>' +
      '<span class="track"><span class="fill" style="width:calc((100% - 7.5em) * ' + (Math.max(0, i.value) / max).toFixed(4) + ')"></span><span class="val">' + (fmt || short)(i.value) + '</span></span></li>').join('') + '</ul>';
  }
  function monthlyPoints(rows) {
    const by = {};
    rows.forEach((t) => { if (t.date) by[t.date.slice(0, 7)] = (by[t.date.slice(0, 7)] || 0) + t.amount; });
    const keys = Object.keys(by).sort();
    if (!keys.length) return [];
    const out = [];
    let [y, m] = keys[0].split('-').map(Number);
    const [ey, em] = keys[keys.length - 1].split('-').map(Number);
    while (y < ey || (y === ey && m <= em)) {
      const k = y + '-' + String(m).padStart(2, '0');
      out.push({ key: k, label: m === 1 || out.length === 0 ? String(y).slice(2) + '.' + m : String(m), value: by[k] || 0 });
      m++; if (m > 12) { m = 1; y++; }
    }
    return out;
  }

  // ------------------------------------------------------------------ home
  function sourceColumns() {
    const st = META.sourceStats;
    const col = (src, link, title, extra) => {
      const s = st[src];
      if (!s) return '';
      const funding = Object.entries(s.byFunding).sort((a, b) => b[1].amount - a[1].amount)
        .map(([k, v]) => '<dt>' + esc(fundingLabel(k)) + '</dt><dd class="num">' + short(v.amount) + ' <small class="muted">' + nf.format(v.count) + '건</small></dd>').join('');
      return '<div class="source-col"><h3><a href="' + link + '">' + esc(title) + '</a></h3><p class="small ink2">' + extra + '</p><dl>' +
        '<dt>기간</dt><dd class="num">' + (src === 'ka-money' ? esc(s.first.slice(0, 4)) + '~' + esc(s.last.slice(0, 4)) + '년 회계보고분' : esc(s.first) + ' ~ ' + esc(s.last)) + '</dd><dt>지출 주체</dt><dd class="num">' + nf.format(s.subjects) + '</dd>' + funding + '</dl></div>';
    };
    return '<div class="sources-grid">' +
      col('ka-money', '#/assembly', '국회의원 정치자금', '중앙선관위 수입·지출보고서를 언론사가 정보공개청구·OCR로 데이터화한 2차 자료입니다. 후원회 기부금·본인 자산 등 세금 이외 재원이 섞여 있습니다.') +
      col('seoul', '#/council/seoul', '서울특별시의회', '광역의회입니다. 의장단·위원장 업무추진비와 위원회·교섭단체 공통경비를 월별 PDF·엑셀로 공개합니다. 2022년 7월(제11대)부터 수집했습니다.') +
      districtColumn() +
      '</div>';
  }

  function districtColumn() {
    // 구의회들은 같은 재원 유형끼리만 더한다 (재원끼리는 더하지 않음)
    const cs = (META.councils || []).filter((c) => c.level !== '광역' && META.sourceStats[c.id]);
    if (!cs.length) return '';
    const byF = {};
    let count = 0, first = '9999', last = '0000';
    cs.forEach((c) => {
      const st = META.sourceStats[c.id];
      count += st.count;
      if (st.first < first) first = st.first;
      if (st.last > last) last = st.last;
      Object.entries(st.byFunding).forEach(([k, v]) => { const b = (byF[k] = byF[k] || { count: 0, amount: 0 }); b.count += v.count; b.amount += v.amount; });
    });
    const funding = Object.entries(byF).sort((a, b) => b[1].amount - a[1].amount).slice(0, 5)
      .map(([k, v]) => '<dt>' + esc(fundingLabel(k)) + '</dt><dd class="num">' + short(v.amount) + ' <small class="muted">' + nf.format(v.count) + '건</small></dd>').join('');
    return '<div class="source-col"><h3><a href="#/councils">서울 구의회 ' + cs.length + '곳</a></h3><p class="small ink2">각 구의회 홈페이지 업무추진비 게시판의 엑셀·PDF입니다. 의회마다 공개 서식과 시작 시점이 다릅니다. <a href="#/region?view=seoul">지도로 보기</a></p><dl>' +
      '<dt>기간</dt><dd class="num">' + esc(first) + ' ~ ' + esc(last) + '</dd><dt>거래</dt><dd class="num">' + nf.format(count) + '건</dd>' + funding + '</dl></div>';
  }

  async function pageHome() {
    const ex = META.example;
    let receipt = '';
    if (ex) {
      const t = ex.tx;
      receipt = '<figure class="receipt" aria-label="표시 예시"><div class="receipt-head"><span>' + esc(ex.subjectName) + '</span><span>' + esc(fundingLabel(t.fundingType)) + '</span></div>' +
        '<div class="receipt-line"><span class="when num">' + esc(t.date) + ' ' + esc(t.weekday || '') + ' ' + esc(t.time || '') + '</span><span>' + esc(t.payee) + '<br><small class="muted">' + esc(t.description || '') + '</small></span>' +
        '<span class="amt num"><mark>' + won(t.amount) + '</mark></span></div>' +
        '<div class="receipt-line"><span class="when">대상 인원</span><span>' + esc(t.attendees) + '명</span><span class="num">1인 <mark>' + won(t.amount / t.attendees) + '</mark></span></div>' +
        '<div class="receipt-note"><b>형광펜은 "한 번 더 볼 이유가 있다"는 표시입니다.</b> 이 결제는 회계관리 훈령의 간담회 식사 기준(1인 ' + won(ex.limit) + ')을 넘었습니다. 훈령은 사유를 적으면 초과를 허용하므로, 잘못이 확인됐다는 뜻은 아닙니다. ' +
        '<a href="' + href('f', ex.subjectId, ex.findingId) + '">이 표시의 근거 보기</a></div></figure>';
    }
    const rules = META.rules.filter((r) => r.count > 0);
    const ruleRows = rules.map((r) => '<li><span class="code">' + esc(r.code) + '</span><div><a href="' + href('rules', r.id) + '">' + esc(r.name) + '</a> ' + refTag(r.reference_type) +
      '<p>' + esc(r.purpose) + '</p></div><span class="count">' + nf.format(r.count) + '건</span></li>').join('');
    setPage(
      '<section class="hero"><div><h1>공개된 지출 기록을 한 줄씩 읽습니다</h1><p class="hero-lede">국회의원 정치자금과 지방의회 업무추진비 공개 자료 ' +
      nf.format(Object.values(META.sourceStats).reduce((a, s) => a + s.count, 0)) + '건을 모아, 다시 볼 만한 거래에 근거와 함께 형광펜을 그었습니다. 모든 표시는 원본 문서까지 따라갈 수 있습니다.</p></div>' +
      receipt +
      '<div class="search"><label class="skip" for="q">검색</label><input id="q" type="search" autocomplete="off" placeholder="의원 이름, 의회 직책, 거래처 상호로 찾기" aria-describedby="q-help"><p id="q-help" class="small muted" style="margin-top:6px">예: 의장, 도시건설위원장, 국회후생복지위원회, 스타벅스</p><ul class="search-results" id="q-results"></ul></div></section>' +
      '<div class="questions">' +
      '<a class="q-card" href="#/budget"><b>나라는 어디서 돈을 얻고 어디에 쓰나</b><span>세금·국채로 들어온 돈과 분야·부처별 예산</span></a>' +
      '<a class="q-card" href="#/money"><b>정치인은 돈을 어디서 받아 어디에 쓰나</b><span>국회의원 정치자금과 지방의회 업무추진비의 항목별 금액</span></a>' +
      '<a class="q-card" href="#/rank"><b>누가 제일 많이 쓰나</b><span>국회의원·지방의회 지출 순위, 함께 쓰는 가게, 평소보다 비싼 결제</span></a>' +
      '<a class="q-card" href="#/outliers"><b>유난히 많이 쓴 곳은</b><span>같은 항목·같은 직책끼리 비교했을 때 튀는 지출</span></a>' +
      '<a class="q-card" href="#/region"><b>우리 동네 대표는</b><span>지도에서 지역구 국회의원과 구의회 고르기</span></a></div>' +
      '<h2>무엇을 모았나</h2><p class="ink2">재원마다 회계 기준과 공개 범위가 달라 금액을 서로 더하지 않습니다.</p>' + sourceColumns() +
      '<h2>어떤 패턴을 표시하나</h2><p class="ink2">규칙마다 법령 기준과의 대조인지, 통계적 비교인지, 단순 일치인지 구분합니다. 지출 주체에 점수를 매기지 않습니다.</p><ul class="rule-list">' + ruleRows + '</ul>' +
      '<p class="small" style="margin-top:12px"><a href="#/rules">규칙 전체와 구현하지 못한 규칙 보기</a></p>' +
      '<h2>이 자료가 말해주지 않는 것</h2><div class="limits">' +
      '<div><b>실제 사용자와 참석자</b>정치자금은 회계책임자가 보고한 기록이라 의원 본인이 썼는지 보좌진이 썼는지 알 수 없습니다. 의회 업무추진비는 성명 없이 직책만 공개됩니다.</div>' +
      '<div><b>증빙서류의 사유</b>훈령은 사유를 적으면 주말·심야 사용이나 기준 초과를 허용합니다. 공개 자료에는 그 사유가 없습니다.</div>' +
      '<div><b>OCR 오류</b>정치자금 자료는 스캔한 종이 보고서를 OCR로 읽은 2차 자료입니다. 보도 전에는 원본 PDF를 확인해야 합니다.</div>' +
      '<div><b>확정된 위반</b>감사·수사·재판으로 확정된 사실은 이 사이트의 표시와 별개입니다. 아직 감사 결과는 연결하지 않았습니다.</div></div>',
      null);
    wireSearch();
  }

  function norm(s) { return String(s || '').toLowerCase().replace(/\s+/g, ''); }
  function wireSearch() {
    const input = document.getElementById('q');
    const out = document.getElementById('q-results');
    let merchants = null;
    let timer = null;
    input.addEventListener('focus', () => { if (!merchants) loadMerchantIndex().then((m) => { merchants = m; if (input.value) run(); }); }, { once: true });
    function run() {
      const q = norm(input.value);
      if (q.length < 1) { out.innerHTML = ''; return; }
      const subs = META.subjects.filter((s) => norm(s.name + (s.role || '') + (s.party || '') + (s.district || '')).includes(q))
        .sort((a, b) => (b.last || '').localeCompare(a.last || '')).slice(0, 8);
      const ms = merchants ? merchants.filter((m) => norm(m[1]).includes(q) || (m[6] || []).some((a) => norm(a).includes(q))).slice(0, 8) : [];
      const ps = (META.people || []).filter((p) => norm(p.name).includes(q)).slice(0, 6);
      out.innerHTML = ps.map((p) => '<li><a href="' + href('p', p.id) + '"><span>' + esc(p.name) + '</span><span class="kind">직책 보유자</span><small class="muted">' + esc(p.council) + ', ' +
        esc([...new Set(p.roles.map((r) => r.role))].join(', ')) + '</small></a></li>').join('') + subs.map((s) => '<li><a href="' + href('s', s.id) + '"><span>' + esc(subjectLabel(s)) + '</span><span class="kind">' + esc(SUBJECT_TYPE[s.type]) + '</span><small class="muted">' +
        esc(s.type === 'LEGISLATOR' ? [s.party, s.district].filter(Boolean).join(', ') : s.org) + '</small></a></li>').join('') +
        ms.map((m) => '<li><a href="' + href('m', m[0]) + '"><span>' + esc(m[1]) + '</span><span class="kind">거래처</span><small class="muted">' + nf.format(m[2]) + '건' + (m[7] ? ', ' + esc(m[7]) : '') + '</small></a></li>').join('') +
        (!subs.length && !ms.length && !ps.length ? '<li><a href="#/" tabindex="-1"><span class="muted">' + (merchants ? '일치하는 결과가 없습니다. 다른 표기로 찾아보세요.' : '거래처 목록을 불러오는 중입니다…') + '</span></a></li>' : '');
    }
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 120); });
  }

  // ------------------------------------------------------------------ assembly list
  function pageAssembly(q) {
    const list = META.subjects.filter((s) => s.type === 'LEGISLATOR');
    const state = { text: q.get('q') || '', sort: q.get('sort') || 'name' };
    setPage('<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>국회의원 정치자금 (2023~2024)</h1>' +
      '<p class="ink2" style="margin-top:10px">대표발의 건수는 열린국회정보 기준이며 정렬 기준으로 쓰지 않습니다. 2023~2024년 정치자금 수입·지출보고서의 지출 내역입니다. 2024년은 제21대 임기 종료(5월 29일)와 제22대 임기 시작으로 회계보고가 두 번으로 나뉘고, 상반기 보고에는 제22대 총선 예비후보자의 회계도 들어 있습니다. 소속 정당은 후원회 신고 당시 기준(오마이뉴스 입력)입니다.</p></div>' +
      '<div class="ledger-tools"><input type="search" id="flt" placeholder="이름, 정당, 지역구" value="' + esc(state.text) + '"><span class="small muted" id="cnt"></span></div><div id="tbl"></div>',
      '국회의원 정치자금');
    const draw = () => {
      const t = norm(state.text);
      let rows = list.filter((s) => !t || norm(s.name + s.party + s.district).includes(t));
      rows.sort(state.sort === 'amount'
        ? (a, b) => (b.totals.POLITICAL_FUND || {}).amount - (a.totals.POLITICAL_FUND || {}).amount
        : (a, b) => a.name.localeCompare(b.name, 'ko'));
      document.getElementById('cnt').textContent = nf.format(rows.length) + '명';
      document.getElementById('tbl').innerHTML = '<div class="table-wrap"><table class="list-table sortable"><thead><tr><th><button data-sort="name"' + (state.sort === 'name' ? ' aria-sort="ascending"' : '') + '>이름</button></th><th>정당</th><th>지역구</th><th>회계보고</th><th class="r">대표발의<br><small>제22대</small></th><th class="r">지출 건수</th><th class="r"><button data-sort="amount"' + (state.sort === 'amount' ? ' aria-sort="descending"' : '') + '>지출 합계</button></th><th class="r">표시</th></tr></thead><tbody>' +
        rows.map((s) => '<tr><td><a href="' + href('s', s.id) + '">' + esc(s.name) + '</a></td><td>' + esc(s.party || '') + '</td><td>' + esc(s.district || '') + '</td><td><small>' + esc((s.assemblies || []).join(', ')) + (s.precandidate ? (s.assemblies && s.assemblies.length ? ', ' : '') + '예비후보 기간' : '') + '</small></td>' +
          '<td class="r num">' + (s.assembly && s.assembly.bills && s.assembly.bills['22'] ? nf.format(s.assembly.bills['22'].lead) : '') + '</td>' +
          '<td class="r num">' + nf.format((s.totals.POLITICAL_FUND || {}).count || 0) + '</td><td class="r num">' + won((s.totals.POLITICAL_FUND || {}).amount) + '</td><td class="r num">' + (s.findings || '') + '</td></tr>').join('') +
        '</tbody></table></div><p class="small muted" style="margin-top:8px">표시 개수는 규칙별 탐지 결과의 수일 뿐, 문제의 크기나 순위를 뜻하지 않습니다. 그래서 표시 개수로는 정렬하지 않습니다.</p>';
    };
    draw();
    document.getElementById('flt').addEventListener('input', (e) => { state.text = e.target.value; draw(); });
    document.getElementById('tbl').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-sort]');
      if (b) { state.sort = b.dataset.sort; draw(); }
    });
  }

  // ------------------------------------------------------------------ council
  const TYPE_ORDER = ['COUNCIL_ROLE', 'COUNCIL_MEMBER', 'COUNCIL_BODY', 'NEGOTIATION_GROUP', 'SECRETARIAT'];
  async function pageCouncil(src) {
    const name = SOURCE_NAME[src];
    const subs = META.subjects.filter((s) => s.source === src);
    const col = META.collection[src] || {};
    const orgShard = await loadSubject('org-' + src).catch(() => null);
    const orgF = orgShard ? orgShard.findings : [];
    const groups = TYPE_ORDER.map((t) => [t, subs.filter((s) => s.type === t)]).filter((g) => g[1].length);
    const termRank = (t) => (t || '').replace(/[^0-9]/g, '') + (t && t.includes('후반') ? '2' : '1');
    let html = '<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>' + esc(name) + ' 업무추진비</h1>' +
      '<div class="facts"><span>게시글 <b class="num">' + nf.format(col.posts || 0) + '</b></span><span>첨부파일 <b class="num">' + nf.format(col.attachments || 0) + '</b></span>' +
      '<span>거래 <b class="num">' + nf.format((META.sourceStats[src] || {}).count || 0) + '건</b></span><span>기간 <b class="num">' + esc((META.sourceStats[src] || {}).first) + ' ~ ' + esc((META.sourceStats[src] || {}).last) + '</b></span></div>' +
      '<div class="attribution"><p>공개 자료의 <b>사용자</b> 칸에는 성명 대신 직책·위원회·부서가 적혀 있습니다. 직책 보유자는 전·후반기마다 바뀔 수 있어 직책과 기수를 함께 묶었습니다. 의정운영공통경비는 위원회·의회 공동 경비이므로 소속 의원 개인의 지출로 보지 않습니다.</p></div></div>';
    if (orgF.length) {
      html += '<div class="callout warn"><h3>공개 자료 점검</h3>' + orgF.map((f) => '<p>' + esc(f.explanation) + ' <a href="' + href('f', f.subjectId, f.id) + '">자세히</a></p>').join('') + '</div>';
    }
    groups.forEach(([t, list]) => {
      list.sort((a, b) => termRank(b.term).localeCompare(termRank(a.term)) || ((Object.values(b.totals)[0] || {}).amount || 0) - ((Object.values(a.totals)[0] || {}).amount || 0));
      const withHolders = t === 'COUNCIL_ROLE';
      html += '<h2>' + esc(SUBJECT_TYPE[t]) + ' <small class="muted">' + list.length + '</small></h2>' + (withHolders ? '<p class="small ink2">직책 보유자: ' + esc(HOLDER_CAVEAT) + '</p>' : '') +
        '<div class="table-wrap"><table class="list-table"><thead><tr><th>지출 주체</th><th>기수</th>' + (withHolders ? '<th>직책 보유자</th>' : '') + '<th>자료 기간</th><th>재원별 지출</th><th class="r">건수</th><th class="r">표시</th></tr></thead><tbody>' +
        list.map((s) => {
          const tot = Object.entries(s.totals);
          return '<tr><td><a href="' + href('s', s.id) + '">' + esc(s.role || s.name) + '</a></td><td><small>' + esc(s.term || '') + '</small></td>' +
            (withHolders ? '<td><small>' + (s.holders ? s.holders.map((n) => '<a href="' + personHref(src, n) + '">' + esc(n) + '</a>').join(', ') : '<span class="muted">미확인</span>') + '</small></td>' : '') + '<td class="num"><small>' + esc(s.first) + ' ~ ' + esc(s.last) + '</small></td>' +
            '<td><small>' + tot.map(([k, v]) => esc(fundingLabel(k)) + ' <span class="num">' + short(v.amount) + '</span>').join('<br>') + '</small></td>' +
            '<td class="r num">' + nf.format(tot.reduce((a, [, v]) => a + v.count, 0)) + '</td><td class="r num">' + (s.findings || '') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    });
    setPage(html, name);
  }

  // ------------------------------------------------------------------ subject detail
  async function pageSubject(sid, q) {
    const shard = await loadSubject(sid);
    const s = shard.subject;
    const idx = subjectById[sid];
    const all = txObjects(shard);
    const marks = marksFor(shard.findings);
    const fundings = [...new Set(all.map((t) => t.fundingType))];
    let fund = q.get('fund') && fundings.includes(q.get('fund')) ? q.get('fund') : fundings[0];
    const focusTx = q.get('tx');
    if (focusTx) {
      const ft = all.find((t) => t.id === focusTx);
      if (ft) fund = ft.fundingType;
    }
    const isLeg = s.type === 'LEGISLATOR';
    const terms = s.terms ? Object.entries(s.terms) : [];
    const facts = isLeg
      ? terms.map(([k, v]) => '<span>' + esc(k) + ' <b>' + esc(v.party || '') + '</b>, ' + esc(v.district || '') + '</span>').join('') +
        (s.precandidate ? '<span>2024년 1~5월 <b>제22대 총선 예비후보 기간 회계</b>, ' + esc(s.precandidate.district || '') + '</span>' : '')
      : '<span>기관 <b>' + esc(s.org) + '</b></span>' + (s.term ? '<span>기수 <b>' + esc(s.term) + '</b> <small class="muted">' + esc(s.term_start) + ' ~ ' + esc(s.term_end) + '</small></span>' : '');
    const head = '<div class="crumbs"><a href="#/">처음</a> / ' + (isLeg ? '<a href="#/assembly">국회의원</a>' : '<a href="#/council/' + esc(s.org_source) + '">' + esc(s.org) + '</a>') + '</div>' +
      '<div class="page-head"><h1>' + esc(isLeg ? s.name + ' 의원' : s.name) + '</h1><div class="facts"><span>' + tag(SUBJECT_TYPE[s.type], 'solid') + '</span>' + facts + '</div>' +
      '<div class="attribution"><p><b>이 지출은 누구의 것인가.</b> ' + esc(s.attribution_note) + '</p></div>' + holdersBlock(s, all) + '</div>';

    setPage(head + (isLeg ? assemblySection(shard.assembly) + '<div id="asset-area"></div>' : '') + '<div id="fund-area"></div>', isLeg ? s.name + ' 의원' : s.name);
    if (isLeg) fillAssetSection(sid, q.get('sec') === 'assets');
    const area = document.getElementById('fund-area');
    const state = { text: '', cat: '', catPrefix: q.get('cat') || '', onlyMarked: false, page: 0, sort: q.get('cat') ? 'amount-desc' : 'date-desc' };

    function drawFund() {
      const listed = all.filter((t) => t.fundingType === fund);
      const rows = listed.filter(counted);
      const fd = META.fundingTypes[fund] || {};
      const gross = rows.filter((t) => t.amount > 0).reduce((a, t) => a + t.amount, 0);
      const net = rows.reduce((a, t) => a + t.amount, 0);
      const negs = rows.filter((t) => t.amount < 0);
      const dates = rows.map((t) => t.date).filter(Boolean).sort();
      const fids = new Set(rows.flatMap((t) => (marks[t.id] || []).map((f) => f.id)));
      const findings = shard.findings.filter((f) => f.fundingType === fund || fids.has(f.id) || (!f.fundingType && fundings.length === 1));

      // categories & merchants
      const cats = {};
      rows.forEach((t) => (cats[t.category || '미분류'] = (cats[t.category || '미분류'] || 0) + t.amount));
      const catItems = Object.entries(cats).sort((a, b) => b[1] - a[1]);
      const topCats = catItems.slice(0, 10).map(([k, v]) => ({ label: k, value: v }));
      if (catItems.length > 10) topCats.push({ label: '그 밖의 분류 ' + (catItems.length - 10) + '개', value: catItems.slice(10).reduce((a, [, v]) => a + v, 0) });
      const ms = {};
      rows.forEach((t) => {
        const k = t.merchantId || '_' + (t.payee || '—');
        const m = (ms[k] = ms[k] || { id: t.merchantId, name: t.payee || '사용처 미기재', n: 0, amt: 0 });
        m.n++; m.amt += t.amount;
      });
      const topM = Object.values(ms).sort((a, b) => b.amt - a.amt).slice(0, 12);

      let h = '';
      if (fundings.length > 1) {
        h += '<div class="tabs" role="group" aria-label="재원 선택">' + fundings.map((f) => '<button type="button" data-fund="' + esc(f) + '" aria-pressed="' + (f === fund) + '">' + esc(fundingLabel(f)) + '</button>').join('') +
          '</div><p class="small muted">재원(회계 유형)이 다르면 금액을 합산하지 않습니다.</p>';
      }
      h += '<p class="ink2">' + esc(fd.label || fund) + ': ' + esc(fd.description || '') + '</p>';
      const dupN = listed.length - rows.length;
      if (dupN) h += '<p class="small muted">다른 공개 파일에 다시 실린 같은 거래 ' + nf.format(dupN) + '건은 합계에서 뺐습니다(목록에는 표시).</p>';
      h += '<div class="figures"><div class="figure"><div class="label">순지출</div><div class="value num">' + short(net) + '</div><div class="sub">' + won(net) + '</div></div>' +
        '<div class="figure"><div class="label">지출 건수</div><div class="value num">' + nf.format(rows.length) + '</div><div class="sub">취소·반환 ' + nf.format(negs.length) + '건 포함</div></div>' +
        '<div class="figure"><div class="label">결제 합계(취소 전)</div><div class="value num">' + short(gross) + '</div><div class="sub">' + esc(dates[0] || '') + ' ~ ' + esc(dates[dates.length - 1] || '') + '</div></div></div>';
      if (isLeg && s.income) {
        const inc = Object.entries(s.income).sort((a, b) => b[1] - a[1]);
        h += '<details class="table-view"><summary>같은 회계의 수입 유형별 합계 보기</summary><p class="small muted">개별 후원인 정보는 정치자금법 제42조에 따라 표시하지 않습니다. OCR 자료라 합계에 오류가 있을 수 있고, 이월·누계 행은 중복 집계될 수 있습니다.</p><div class="table-wrap"><table><tbody>' +
          inc.map(([k, v]) => '<tr><td>' + esc(k) + '</td><td class="r num">' + won(v) + '</td></tr>').join('') + '</tbody></table></div></details>';
      }
      h += '<div class="two-col" style="margin-top:28px"><div><h3>월별 지출</h3>' + barChart(monthlyPoints(rows), '월별 지출 합계') + '</div>' +
        '<div><h3>분류별 지출</h3><p class="small muted" style="margin-bottom:8px">' + (isLeg ? '분류는 오마이뉴스가 취재용으로 정한 것으로, 선관위 회계 기준이 아닙니다.' : '분류는 상호명과 집행목적 문구로 추정한 값입니다.') + '</p>' + hbars(topCats) + '</div></div>';
      h += '<h2>자주 지출한 거래처</h2><div class="table-wrap"><table><thead><tr><th>거래처</th><th class="r">건수</th><th class="r">금액</th><th class="r">비중</th></tr></thead><tbody>' +
        topM.map((m) => '<tr><td>' + (m.id ? '<a href="' + href('m', m.id) + '">' + esc(m.name) + '</a>' : esc(m.name)) + '</td><td class="r num">' + nf.format(m.n) + '</td><td class="r num">' + won(m.amt) + '</td><td class="r num">' + (gross ? pct(m.amt / gross) : '') + '</td></tr>').join('') +
        '</tbody></table></div><p class="small muted" style="margin-top:6px">개인에게 지급한 금액(인건비 등)은 "개인(비공개)"로 묶어 표시합니다.</p>';

      h += '<h2>표시된 패턴 <small class="muted">' + findings.length + '</small></h2>';
      if (!findings.length) h += '<p class="ink2">이 재원에서는 탐지 규칙에 걸린 패턴이 없습니다. 패턴이 없다는 것이 문제없음을 보증하지는 않습니다.</p>';
      const byRule = {};
      findings.forEach((f) => (byRule[f.ruleId] = byRule[f.ruleId] || []).push(f));
      Object.entries(byRule).sort((a, b) => ruleOf(a[0]).code.localeCompare(ruleOf(b[0]).code)).forEach(([rid, fs]) => {
        const r = ruleOf(rid);
        h += '<div class="finding-group"><h3><span class="muted">' + esc(r.code) + '</span> ' + esc(r.name) + ' ' + refTag(r.reference_type) + '</h3>' +
          fs.map((f) => '<div class="finding-item ' + (f.reviewStatus === 'DATA_QUALITY' ? 'dq' : f.reviewStatus === 'INFO' ? 'info' : '') + '"><p>' + esc(f.explanation) + '</p><div class="meta"><span>' + esc(REVIEW[f.reviewStatus]) + '</span>' +
            (f.period && f.period.label ? '<span>' + esc(f.period.label) + '</span>' : '') + '<span>근거 거래 ' + nf.format(f.evidenceCount) + '건</span><a href="' + href('f', f.subjectId, f.id) + '">근거와 계산 보기</a></div></div>').join('') + '</div>';
      });

      const catsOpt = [...new Set(rows.map((t) => t.category || '미분류'))].sort();
      h += '<h2 id="ledger">전체 거래 기록</h2><div class="ledger-tools"><input type="search" id="lq" placeholder="사용처, 내역 검색" value="' + esc(state.text) + '">' +
        '<select id="lc" aria-label="분류"><option value="">모든 분류</option>' + catsOpt.map((c) => '<option' + (c === state.cat ? ' selected' : '') + '>' + esc(c) + '</option>').join('') + '</select>' +
        '<select id="ls" aria-label="정렬"><option value="date-desc">최근 순</option><option value="date-asc"' + (state.sort === 'date-asc' ? ' selected' : '') + '>오래된 순</option><option value="amount-desc"' + (state.sort === 'amount-desc' ? ' selected' : '') + '>금액 큰 순</option></select>' +
        '<label><input type="checkbox" id="lm"' + (state.onlyMarked ? ' checked' : '') + '> 형광펜 표시된 거래만</label>' +
        (state.catPrefix ? ' <button class="plain" type="button" id="lcp">\'' + esc(state.catPrefix) + '\' 항목만 보는 중, 해제</button>' : '') + '</div><div id="ledger-body"></div>';
      area.innerHTML = h;
      wireCharts(area);
      drawLedger(listed);
      area.querySelectorAll('[data-fund]').forEach((b) => b.addEventListener('click', () => { fund = b.dataset.fund; state.page = 0; drawFund(); }));
      const upd = () => { state.page = 0; drawLedger(listed); };
      document.getElementById('lq').addEventListener('input', (e) => { state.text = e.target.value; upd(); });
      document.getElementById('lc').addEventListener('change', (e) => { state.cat = e.target.value; upd(); });
      document.getElementById('ls').addEventListener('change', (e) => { state.sort = e.target.value; upd(); });
      document.getElementById('lm').addEventListener('change', (e) => { state.onlyMarked = e.target.checked; upd(); });
      const lcp = document.getElementById('lcp');
      if (lcp) lcp.addEventListener('click', () => { state.catPrefix = ''; drawFund(); });
    }

    const PER = 100;
    function drawLedger(rows) {
      const t = norm(state.text);
      let list = rows.filter((x) => (!t || norm((x.payee || '') + (x.description || '')).includes(t)) && (!state.cat || (x.category || '미분류') === state.cat) &&
        (!state.catPrefix || (x.category || '').startsWith(state.catPrefix)) &&
        (!state.onlyMarked || (marks[x.id] || []).length));
      const key = state.sort;
      list.sort((a, b) => key === 'amount-desc' ? b.amount - a.amount
        : key === 'date-asc' ? (a.date || '').localeCompare(b.date || '') || (a.time || '').localeCompare(b.time || '')
          : (b.date || '').localeCompare(a.date || '') || (b.time || '').localeCompare(a.time || ''));
      if (focusTx && state.page === 0 && !state._focused) {
        const i = list.findIndex((x) => x.id === focusTx);
        if (i >= 0) state.page = Math.floor(i / PER);
      }
      const pages = Math.max(1, Math.ceil(list.length / PER));
      state.page = Math.min(state.page, pages - 1);
      const slice = list.slice(state.page * PER, state.page * PER + PER);
      const body = document.getElementById('ledger-body');
      body.innerHTML = ledgerTable(slice, marks, sid, { focus: focusTx, subject: s }) +
        '<div class="pager"><span class="muted">' + nf.format(list.length) + '건 중 ' + nf.format(list.length ? state.page * PER + 1 : 0) + '–' + nf.format(Math.min(list.length, state.page * PER + PER)) + '</span>' +
        '<span><button type="button" data-p="-1"' + (state.page === 0 ? ' disabled' : '') + '>이전</button> <button type="button" data-p="1"' + (state.page >= pages - 1 ? ' disabled' : '') + '>다음</button></span></div>';
      body.querySelectorAll('[data-p]').forEach((b) => b.addEventListener('click', () => { state.page += +b.dataset.p; drawLedger(rows); document.getElementById('ledger').scrollIntoView(); }));
      if (focusTx && !state._focused) {
        state._focused = true;
        const el = document.getElementById('tx-' + focusTx);
        if (el) setTimeout(() => el.scrollIntoView({ block: 'center' }), 30);
      }
    }
    drawFund();
  }

  // ------------------------------------------------------------------ finding detail
  function obsValue(k, v) {
    if (v == null) return '—';
    if (MONEY_KEYS.has(k) && typeof v === 'number') return won(v);
    if (SHARE_KEYS.has(k) && typeof v === 'number') return pct(v);
    if (typeof v === 'boolean') return v ? '예' : '아니오';
    if (k === 'merchantIdConfidence') return esc((CONFIDENCE[v] || [v])[0]);
    if (Array.isArray(v)) return v.length ? esc(v.join(', ')) : '없음';
    if (typeof v === 'object') return Object.entries(v).map(([a, b]) => esc(a) + ' ' + (typeof b === 'number' && b > 1000 ? won(b) : esc(b))).join(', ');
    if (typeof v === 'number') return nf.format(v);
    return esc(v);
  }
  function observedBlock(f) {
    const o = f.observed || {};
    const skip = new Set(['groups', 'top3', 'patterns', 'problemFiles', 'topCategories', 'merchantId']);
    let h = '<dl class="kv">' + Object.entries(o).filter(([k]) => !skip.has(k) && OBS_LABEL[k] !== null).map(([k, v]) => {
      let val = obsValue(k, v);
      if (k === 'merchantName' && o.merchantId) val = '<a href="' + href('m', o.merchantId) + '">' + esc(v) + '</a>';
      if (k === 'documentId') val = docLink(v, (META.documents[v] || {}).title || v);
      return '<dt>' + esc(OBS_LABEL[k] || k) + '</dt><dd class="num">' + val + '</dd>';
    }).join('') + '</dl>';
    if (o.top3) h += '<h3 style="margin-top:16px">상위 3개 거래처</h3>' + hbars(o.top3.map((t) => ({ label: t.name, value: t.amount, href: href('m', t.merchantId) })));
    if (o.topCategories) h += '<h3 style="margin-top:16px">해당 기간 분류별 지출</h3>' + hbars(o.topCategories.map((t) => ({ label: t.category, value: t.amount })));
    if (o.patterns) h += '<h3 style="margin-top:16px">반복 패턴</h3><div class="table-wrap"><table><thead><tr><th>거래처</th><th class="r">금액</th><th class="r">개월</th><th class="r">건수</th><th>분류</th></tr></thead><tbody>' +
      o.patterns.map((p) => '<tr><td><a href="' + href('m', p.merchantId) + '">' + esc(p.merchantName) + '</a></td><td class="r num">' + won(p.amount) + '</td><td class="r num">' + p.months + '</td><td class="r num">' + p.count + '</td><td><small>' + esc(p.category) + '</small></td></tr>').join('') + '</tbody></table></div>';
    if (o.groups) h += '<h3 style="margin-top:16px">묶음별 내역</h3><div class="table-wrap"><table><thead><tr><th>일자</th><th>내용</th><th class="r">건수</th><th class="r">합계</th></tr></thead><tbody>' +
      o.groups.map((g) => '<tr><td class="num">' + esc(g.date) + '</td><td>' + esc(g.merchantName || g.category || g.kind || '') + (g.payee ? ' <small class="muted">' + esc(g.payee) + '</small>' : '') + (g.minGapMinutes != null ? ' <small class="muted">간격 ' + g.minGapMinutes + '분</small>' : '') + (g.crosses500k ? ' <span class="tag">합계 50만원 이상</span>' : '') + '</td><td class="r num">' + (g.count || (g.ids || []).length) + '</td><td class="r num">' + won(g.total != null ? g.total : g.amount * (g.ids || []).length) + '</td></tr>').join('') + '</tbody></table></div>';
    if (o.problemFiles && o.problemFiles.length) h += '<h3 style="margin-top:16px">문제가 있는 첨부</h3><div class="table-wrap"><table><thead><tr><th>기간</th><th>파일</th><th>내용</th></tr></thead><tbody>' +
      o.problemFiles.map((p) => '<tr><td class="num">' + esc(p.period || '') + '</td><td><small>' + esc(p.filename || '') + '</small></td><td><small>' + esc(p.issue || '') + (p.rejectedRows ? ' (제외된 행 ' + p.rejectedRows + ')' : '') + '</small></td></tr>').join('') + '</tbody></table></div>';
    return h;
  }
  function referenceBlock(f) {
    const r = f.reference || {};
    let h = '<dl class="kv"><dt>기준 종류</dt><dd>' + refTag(r.type) + '</dd>';
    if (r.description) h += '<dt>설명</dt><dd>' + esc(r.description) + '</dd>';
    if (r.value != null) h += '<dt>기준값</dt><dd class="num">' + (typeof r.value === 'number' ? (r.value > 1000 ? won(r.value) : r.value < 1 ? pct(r.value) : esc(r.value)) : esc(r.value)) + '</dd>';
    if (r.median != null) h += '<dt>중앙값</dt><dd class="num">' + pct(r.median) + '</dd>';
    if (r.thresholds) h += '<dt>분류별 기준값</dt><dd class="num">' + Object.entries(r.thresholds).map(([k, v]) => esc(k) + ' ' + won(v)).join('<br>') + '</dd>';
    if (r.sampleSize != null) h += '<dt>비교 표본</dt><dd class="num">' + (typeof r.sampleSize === 'object' ? Object.entries(r.sampleSize).map(([k, v]) => esc(k) + ' ' + nf.format(v) + '건').join(', ') : nf.format(r.sampleSize)) + '</dd>';
    if (r.window) h += '<dt>비교 기간</dt><dd>' + esc(r.window) + '</dd><dt>기준 기간</dt><dd>' + esc(r.baseline) + '</dd>';
    if (r.subjectHospitalityTotal) h += '<dt>주체의 식사·다과 합계</dt><dd class="num">' + won(r.subjectHospitalityTotal) + '</dd>';
    return h + '</dl>';
  }
  function legalBlock(ids) {
    if (!ids || !ids.length) return '<p class="ink2">이 규칙은 특정 법령 기준이 아니라 통계적 비교·사실 확인에 기반합니다.</p>';
    return ids.map((id) => {
      const l = META.legal.find((x) => x.id === id);
      if (!l) return '';
      return '<div class="callout"><h3>' + esc(l.title) + '</h3><p class="small ink2">' + esc(l.law_name) + (l.article ? ' ' + esc(l.article) : '') + '</p><p>' + esc(l.summary) + '</p>' +
        (l.notes ? '<p class="small ink2">' + esc(l.notes) + '</p>' : '') + '<p class="small"><a href="' + esc(l.url) + '" target="_blank" rel="noopener">원문 보기</a> <span class="muted">' + (l.verified ? '원문 대조 확인' : '미확인') + ', ' + esc(l.checked_at) + '</span></p></div>';
    }).join('');
  }

  async function pageFinding(sid, fid) {
    const shard = await loadSubject(sid);
    const f = shard.findings.find((x) => x.id === fid);
    if (!f) return setPage('<p class="err">이 탐지 결과를 찾을 수 없습니다. 자료가 다시 생성되며 번호가 바뀌었을 수 있습니다. <a href="' + href('s', sid) + '">지출 주체 페이지로 가기</a></p>');
    const r = ruleOf(f.ruleId);
    const s = shard.subject;
    const isOrg = s.type === 'ORG';
    const all = txObjects(shard);
    const byId = Object.fromEntries(all.map((t) => [t.id, t]));
    const ev = (f.evidenceIds || []).map((id) => byId[id]).filter(Boolean);
    const marks = marksFor(shard.findings);
    const docs = [...new Set(ev.map((t) => t.docId))];
    const subjLink = isOrg ? '<a href="#/council/' + esc(f.sourceId) + '">' + esc(SOURCE_NAME[f.sourceId]) + '</a>' : '<a href="' + href('s', sid) + '">' + esc(s.type === 'LEGISLATOR' ? s.name + ' 의원' : s.name) + '</a>';
    const reviews = (META.reviews || {})[fid] || [];
    const unknowns = [...r.verification];
    if (f.sourceId === 'ka-money') unknowns.push('OCR로 읽은 금액·날짜·사용처가 원본 PDF와 같은지');
    let holderLine = '';
    if ((s.type === 'COUNCIL_ROLE' || s.type === 'NEGOTIATION_GROUP') && s.holders) {
      const cnt = {};
      ev.forEach((t) => { const h = holderAt(s, t.date); const k = (h && h.name) || ''; cnt[k] = (cnt[k] || 0) + 1; });
      holderLine = '<div class="attribution"><p><b>해당 거래 시점의 직책 보유자.</b> ' + Object.entries(cnt).map(([n, c]) => (n ? '<a href="' + personHref(s.org_source, n) + '">' + esc(n) + '</a>' : '확인하지 못함') + ' ' + c + '건').join(', ') +
        '. ' + esc(HOLDER_CAVEAT) + '</p></div>';
      unknowns.push('실제로 결제한 사람이 직책 보유자 본인인지, 비서실·사무국 직원의 대리 결제인지');
    } else if (s.type === 'COUNCIL_ROLE') unknowns.push('해당 기간 이 직책을 맡은 사람이 누구인지 (공개 자료에 성명 없음)');
    const correction = ['[Robin Hood 정정 요청]', '탐지 결과: ' + fid + ' (' + r.code + ' ' + r.name + ')', '지출 주체: ' + (isOrg ? SOURCE_NAME[f.sourceId] : s.name),
      '관련 거래: ' + (f.evidenceIds || []).slice(0, 10).join(', ') + ((f.evidenceIds || []).length > 10 ? ' 외' : ''), '원본 문서: ' + docs.map((d) => (META.documents[d] || {}).url || d).slice(0, 5).join(' '),
      '정정 내용: ', '근거 자료(링크·문서): '].join('\n');
    setPage('<div class="crumbs"><a href="#/">처음</a> / ' + subjLink + ' / <a href="' + href('rules', r.id) + '">' + esc(r.name) + '</a></div>' +
      '<div class="page-head"><h1>' + esc(r.name) + '</h1><div class="facts"><span>' + refTag(r.reference_type) + '</span><span>' + tag(REVIEW[f.reviewStatus], f.reviewStatus === 'DATA_QUALITY' ? 'dq' : '') + '</span>' +
      '<span>자료 성격 <b>' + esc(DQ[f.dataQuality] || f.dataQuality) + '</b></span>' + (f.period ? '<span>기간 <b class="num">' + esc(f.period.label || (f.period.start + ' ~ ' + f.period.end)) + '</b></span>' : '') + '</div>' +
      '<p style="margin-top:16px;font-size:18px"><span class="hl">' + esc(f.explanation) + '</span></p>' + holderLine + '</div>' +
      '<div class="two-col"><div><h3>실제 계산값</h3>' + observedBlock(f) + '</div><div><h3>비교 기준과 범위</h3>' + referenceBlock(f) +
      '<h3 style="margin-top:20px">규칙의 계산 방법</h3><p class="small ink2">' + esc(r.method) + '</p><p class="small ink2">자료가 부족할 때: ' + esc(r.missing_data) + '</p></div></div>' +
      '<h2>당시 적용 규정</h2>' + legalBlock(r.legal_refs) +
      '<div class="two-col"><div><h2>가능한 정상적인 설명</h2><ul>' + r.normal_cases.map((x) => '<li>' + esc(x) + '</li>').join('') + '</ul>' +
      '<h3 style="margin-top:12px">데이터 오류로 잘못 표시될 가능성</h3><ul>' + r.false_positive_risks.map((x) => '<li>' + esc(x) + '</li>').join('') + '</ul></div>' +
      '<div><h2>아직 확인되지 않은 정보</h2><ul>' + unknowns.map((x) => '<li>' + esc(x) + '</li>').join('') + '</ul></div></div>' +
      (ev.length ? '<h2>관련 거래 <small class="muted">' + nf.format(f.evidenceCount) + '건' + (f.evidenceCount > ev.length ? ' 중 ' + ev.length + '건 표시' : '') + '</small></h2>' + ledgerTable(ev, marks, sid, { subject: s }) : '') +
      '<h2>원본 문서</h2>' + (docs.length ? '<ul>' + docs.map((d) => {
        const m = META.documents[d] || {};
        return '<li>' + docLink(d, m.title || d) + (m.post_url ? ' <small>(<a href="' + esc(m.post_url) + '" target="_blank" rel="noopener">게시글</a>)</small>' : '') + ' <small class="muted">' + esc(m.publisher || '') + '</small>' + (m.origin_note ? '<br><small class="ink2">' + esc(m.origin_note) + '</small>' : '') + '</li>';
      }).join('') + '</ul>' : '<p class="ink2">게시판 전체를 점검한 결과입니다. <a href="#/sources">수집 현황 보기</a></p>') +
      '<h2>검토·정정 이력</h2>' + (reviews.length ? '<ul>' + reviews.map((x) => '<li><span class="num">' + esc(x.date) + '</span> ' + esc(x.status) + ' — ' + esc(x.note) + '</li>').join('') + '</ul>' : '<p class="ink2">아직 사람이 검토한 기록이 없습니다. 자동 계산 결과 그대로입니다.</p>') +
      '<div class="callout"><h3>정정 요청</h3><p class="small ink2">계산이나 원본 판독이 틀렸다면 아래 내용을 채워 보내 주세요. 탐지 번호와 거래 번호가 있으면 원본까지 바로 추적할 수 있습니다.</p><textarea class="copy-box" readonly>' + esc(correction) + '</textarea><p style="margin-top:8px"><button class="plain" type="button" id="copy">요청 내용 복사</button> <span class="small muted" id="copied" role="status"></span></p></div>',
      r.name);
    document.getElementById('copy').addEventListener('click', () => {
      const ta = document.querySelector('.copy-box');
      ta.select();
      (navigator.clipboard ? navigator.clipboard.writeText(ta.value) : Promise.reject()).then(() => (document.getElementById('copied').textContent = '복사했습니다.'), () => {
        document.execCommand && document.execCommand('copy');
        document.getElementById('copied').textContent = '복사했습니다.';
      });
    });
  }

  // ------------------------------------------------------------------ merchant
  async function pageMerchant(mid, q) {
    const entry = await loadMerchant(mid);
    if (!entry) return setPage('<p class="err">이 거래처를 찾을 수 없습니다.</p>');
    const m = entry.merchant;
    const tx = decodeRows(entry.tx).map((t) => Object.assign(t, { payee: t.payee || entry.merchant.name }));
    const fcount = {};
    tx.forEach((t) => (fcount[t.fundingType] = (fcount[t.fundingType] || 0) + 1));
    const fundings = Object.keys(fcount).sort((a, b) => fcount[b] - fcount[a]);
    let fund = q.get('fund') && fundings.includes(q.get('fund')) ? q.get('fund') : fundings[0];
    const conf = CONFIDENCE[m.id_confidence] || ['', ''];
    let head = '<div class="crumbs"><a href="#/">처음</a> / 거래처</div><div class="page-head"><h1>' + esc(m.name) + '</h1><div class="facts">' +
      '<span>식별 신뢰도 <b>' + esc(conf[0]) + '</b></span>' + (m.bizno ? '<span>사업자등록번호 <b class="num">' + esc(m.bizno) + '</b></span>' : '') + (m.region ? '<span>소재 지역 <b>' + esc(m.region) + '</b></span>' : '') +
      '<span>자료 <b>' + m.sources.map((x) => esc(SOURCE_NAME[x])).join(', ') + '</b></span></div>' +
      '<div class="attribution"><p>' + esc(conf[1]) + (m.alias_count ? ' 이 거래처로 묶인 다른 표기 ' + m.alias_count + '개: ' + esc(m.aliases.slice(0, 8).join(', ')) + (m.alias_count > 8 ? ' 등' : '') + '.' : '') +
      (m.biztypes && m.biztypes.length ? ' 보고서 업종 칸(OCR): ' + esc(m.biztypes.join(', ')) + '.' : '') +
      (m.bizno_ocr_variants ? ' 한 자리만 다르게 읽힌(OCR 오류로 보이는) 사업자번호 ' + m.bizno_ocr_variants + '개를 함께 묶었습니다.' : '') + ' 개인사업자 번호는 뒷자리를 가렸습니다.</p></div></div>';
    setPage(head + '<div id="m-area"></div>', m.name);
    const area = document.getElementById('m-area');
    const state = { page: 0 };
    function draw() {
      const rows = tx.filter((t) => t.fundingType === fund);
      const bySub = {};
      rows.forEach((t) => { const b = (bySub[t.subjectId] = bySub[t.subjectId] || { n: 0, amt: 0, first: t.date, last: t.date }); b.n++; b.amt += t.amount; if (t.date < b.first) b.first = t.date; if (t.date > b.last) b.last = t.date; });
      let h = '';
      if (fundings.length > 1) h += '<div class="tabs" role="group" aria-label="재원 선택">' + fundings.map((f) => '<button type="button" data-fund="' + esc(f) + '" aria-pressed="' + (f === fund) + '">' + esc(fundingLabel(f)) + '</button>').join('') + '</div><p class="small muted">재원이 다르면 금액을 합산하지 않습니다.</p>';
      h += '<div class="figures"><div class="figure"><div class="label">' + esc(fundingLabel(fund)) + ' 지출</div><div class="value num">' + short(rows.reduce((a, t) => a + t.amount, 0)) + '</div></div>' +
        '<div class="figure"><div class="label">거래 건수</div><div class="value num">' + nf.format(rows.length) + '</div></div><div class="figure"><div class="label">지출 주체</div><div class="value num">' + Object.keys(bySub).length + '</div></div></div>';
      h += '<div class="two-col" style="margin-top:20px"><div><h3>기간별 지출액</h3>' + barChart(monthlyPoints(rows), '월별 지출') + '</div><div><h3>지출 주체별</h3><div class="table-wrap"><table><thead><tr><th>지출 주체</th><th class="r">건수</th><th class="r">금액</th><th>기간</th></tr></thead><tbody>' +
        Object.entries(bySub).sort((a, b) => b[1].amt - a[1].amt).map(([sid, b]) => {
          const s = subjectById[sid];
          return '<tr><td><a href="' + href('s', sid) + '">' + esc(s ? subjectLabel(s) : entry.subjects[sid]) + '</a></td><td class="r num">' + b.n + '</td><td class="r num">' + won(b.amt) + '</td><td class="num"><small>' + esc(b.first) + ' ~ ' + esc(b.last) + '</small></td></tr>';
        }).join('') + '</tbody></table></div></div></div>';
      h += '<div class="callout"><h3>공공계약 정보</h3><p class="small ink2">나라장터 계약정보와의 연결은 아직 구현하지 않았습니다. 계약 정보는 기관의 계약이므로, 연결하더라도 특정 의원 개인의 소비로 표시하지 않습니다.</p></div>';
      const sorted = rows.slice().sort((a, b) => (b.date || '').localeCompare(a.date || ''));
      const PER = 100, pages = Math.max(1, Math.ceil(sorted.length / PER));
      const slice = sorted.slice(state.page * PER, state.page * PER + PER).map((t) => Object.assign({}, t, { merchantId: null, payee: t.payee }));
      h += '<h2 id="mtx">거래 내역</h2>' + ledgerTable(slice, null, null, { showSubject: true }).replace(/<td><span class="marks"><\/span><\/td>/g, '<td></td>') +
        '<div class="pager"><span class="muted">' + nf.format(sorted.length) + '건</span><span><button type="button" data-p="-1"' + (state.page === 0 ? ' disabled' : '') + '>이전</button> <button type="button" data-p="1"' + (state.page >= pages - 1 ? ' disabled' : '') + '>다음</button></span></div>' +
        '<p class="small muted">형광펜 표시는 각 지출 주체 페이지에서 볼 수 있습니다.</p>';
      area.innerHTML = h;
      wireCharts(area);
      area.querySelectorAll('[data-fund]').forEach((b) => b.addEventListener('click', () => { fund = b.dataset.fund; state.page = 0; draw(); }));
      area.querySelectorAll('[data-p]').forEach((b) => b.addEventListener('click', () => { state.page += +b.dataset.p; draw(); document.getElementById('mtx').scrollIntoView(); }));
    }
    draw();
  }

  // ------------------------------------------------------------------ person (직책 보유자)
  async function pagePerson(pid) {
    const p = (META.people || []).find((x) => x.id === pid);
    if (!p) return setPage('<p class="err">이 사람의 직책 기록을 찾을 수 없습니다.</p>');
    const shards = await Promise.all(p.roles.map((r) => loadSubject(r.subjectId)));
    let rows = '', findingsHtml = '';
    p.roles.forEach((r, i) => {
      const sh = shards[i];
      const tx = txObjects(sh).filter((t) => counted(t) && t.date && t.date >= r.start && t.date <= r.end);
      const ids = new Set(tx.map((t) => t.id));
      const byF = {};
      tx.forEach((t) => (byF[t.fundingType] = (byF[t.fundingType] || 0) + t.amount));
      const fs = sh.findings.filter((f) => (f.evidenceIds || []).some((id) => ids.has(id)));
      rows += '<tr><td><a href="' + href('s', r.subjectId) + '">' + esc(r.role) + '</a></td><td><small>' + esc(r.term) + '</small></td><td class="num"><small>' + esc(r.start) + ' ~ ' + esc(r.end) + '</small></td>' +
        '<td class="r num">' + nf.format(tx.length) + '</td><td><small>' + (Object.entries(byF).map(([k, v]) => esc(fundingLabel(k)) + ' <span class="num">' + short(v) + '</span>').join('<br>') || '—') + '</small></td>' +
        '<td class="r num">' + (fs.length || '') + '</td><td><small><a href="' + esc(r.sourceUrl) + '" target="_blank" rel="noopener">' + esc(r.sourceTitle || '출처') + '</a>' + (r.confidence === 'MEDIUM' ? ', 날짜 일부 추정' : '') + '</small></td></tr>';
      fs.forEach((f) => {
        const inPeriod = (f.evidenceIds || []).filter((id) => ids.has(id)).length;
        findingsHtml += '<div class="finding-item ' + (f.reviewStatus === 'DATA_QUALITY' ? 'dq' : f.reviewStatus === 'INFO' ? 'info' : '') + '"><p>' + esc(f.explanation) + '</p><div class="meta"><span>' + esc(ruleOf(f.ruleId).code + ' ' + ruleOf(f.ruleId).name) + '</span>' +
          '<span>근거 ' + nf.format(f.evidenceCount) + '건 중 이 기간 ' + inPeriod + '건</span><a href="' + href('f', f.subjectId, f.id) + '">근거와 계산 보기</a></div></div>';
      });
    });
    const named = p.memberSubjects.map((id) => subjectById[id]).filter(Boolean);
    setPage('<div class="crumbs"><a href="#/">처음</a> / <a href="#/council/' + esc(p.source) + '">' + esc(p.council) + '</a></div><div class="page-head"><h1>' + esc(p.name) + '</h1>' +
      '<div class="facts"><span>' + tag('직책 보유자', 'solid') + '</span><span>' + esc(p.council) + '</span>' + (p.party ? '<span>정당 <b>' + esc(p.party) + '</b> <small class="muted">' + esc(p.partyNote || '') + '</small></span>' : '') + '</div>' +
      '<div class="attribution"><p><b>이 페이지가 보여주는 것.</b> 공개 자료에는 성명 없이 직책만 있으므로, 이 사람이 직책을 맡았던 기간의 <b>직책 업무추진비</b>를 모아 보여줍니다. ' + esc(HOLDER_CAVEAT) +
      ' 의원 개인의 월정수당·의정활동비나 위원회 공동경비는 여기에 포함되지 않습니다. 같은 이름의 다른 사람일 가능성은 의회 홈페이지 기록으로만 확인했습니다.</p></div></div>' +
      '<h2>직책 이력과 해당 기간 지출</h2><div class="table-wrap"><table><thead><tr><th>직책</th><th>기수</th><th>보유 기간</th><th class="r">거래</th><th>재원별 지출</th><th class="r">관련 표시</th><th>근거</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      (named.length ? '<h2>사용자 칸에 이름이 직접 적힌 경비</h2><ul>' + named.map((x) => '<li><a href="' + href('s', x.id) + '">' + esc(x.name) + '</a> <small class="muted">' + esc(x.term || '') + '</small></li>').join('') + '</ul>' : '') +
      '<h2>보유 기간에 걸친 표시된 패턴</h2>' + (findingsHtml || '<p class="ink2">보유 기간의 거래가 근거로 쓰인 패턴이 없습니다. 패턴이 없다는 것이 문제없음을 보증하지는 않습니다.</p>'),
      p.name);
  }


  // ------------------------------------------------------------------ 의정활동 (열린국회정보)
  const RESULT_ORDER = ['가결', '대안에 반영', '심사 중', '임기만료 폐기', '철회', '부결·폐기'];
  const ASM_CAVEAT = '법안 수는 일의 양이나 질을 그대로 보여주지 않습니다. 비슷한 법안을 여러 건 내거나, 다른 의원 법안을 묶은 위원회 대안에 내용이 반영되는 경우(대안에 반영)도 많습니다. 의원 사이 순위는 매기지 않습니다.';
  function billResultsText(r) {
    return RESULT_ORDER.filter((k) => r[k]).map((k) => esc(k) + ' ' + nf.format(r[k])).join(', ');
  }
  function assemblySection(a) {
    const sum = META.assemblySummary;
    if (!a || !sum) return '';
    const m = a.member;
    let h = '<section class="assembly"><h2>의정활동 <small class="muted">열린국회정보</small></h2>';
    if (m) {
      h += '<dl class="kv"><dt>소속 위원회</dt><dd>' + esc(m.CMITS || '—') + '</dd><dt>선수</dt><dd>' + esc(m.REELE_GBN_NM || '—') + ' (' + esc(m.UNITS || '') + ')</dd>' +
        '<dt>선출</dt><dd>' + esc(m.ELECT_GBN_NM || '') + (m.ORIG_NM && m.ORIG_NM !== '비례대표' ? ', ' + esc(m.ORIG_NM) : '') + '</dd>' +
        (m.JOB_RES_NM ? '<dt>직책</dt><dd>' + esc(m.JOB_RES_NM) + '</dd>' : '') +
        (m.HOMEPAGE ? '<dt>홈페이지</dt><dd><a href="' + esc(m.HOMEPAGE) + '" target="_blank" rel="noopener">' + esc(m.HOMEPAGE) + '</a></dd>' : '') + '</dl>';
    } else {
      h += '<p class="small ink2">현직 의원 명단(열린국회정보)에 없어 위원회 정보는 없습니다. 법률안은 대표발의자 이름으로 연결했습니다.</p>';
    }
    ['22', '21'].filter((age) => a.bills[age]).forEach((age) => {
      const b = a.bills[age];
      h += '<h3 style="margin-top:20px">제' + age + '대 대표발의 법률안 ' + nf.format(b.lead) + '건' + (b.co != null ? ' <small class="muted">공동발의 ' + nf.format(b.co) + '건</small>' : '') + '</h3>';
      if (b.lead) {
        h += hbars(RESULT_ORDER.filter((k) => b.results[k]).map((k) => ({ label: k, value: b.results[k] })), (v) => nf.format(v) + '건');
        const row = (r) => '<tr><td class="num"><small>' + esc(r[3] || '') + '</small></td><td>' + (r[5] ? '<a href="' + esc(r[5]) + '" target="_blank" rel="noopener">' + esc(r[1]) + '</a>' : esc(r[1])) + '</td><td><small>' + esc(r[2] || '') + '</small></td><td><small>' + esc(r[4] || '심사 중') + '</small></td></tr>';
        const head = '<div class="table-wrap"><table><thead><tr><th>발의일</th><th>법률안</th><th>소관 위원회</th><th>처리 결과</th></tr></thead><tbody>';
        h += '<p class="small muted" style="margin:10px 0 4px">최근 대표발의</p>' + head + b.list.slice(0, 8).map(row).join('') + '</tbody></table></div>';
        if (b.list.length > 8) h += '<details class="table-view"><summary>전체 ' + nf.format(b.list.length) + '건 보기</summary>' + head + b.list.map(row).join('') + '</tbody></table></div></details>';
      }
    });
    ['22', '21'].filter((age) => a.votes && a.votes[age]).forEach((age) => {
      const v = a.votes[age], c = v.counts;
      h += '<h3 style="margin-top:20px">제' + age + '대 본회의 표결 ' + nf.format(v.total) + '건 <small class="muted">참여 ' + pct(v.participation) + '</small></h3>' +
        hbars(['찬성', '반대', '기권', '불참'].filter((k) => c[k]).map((k) => ({ label: k, value: c[k] })), (x) => nf.format(x) + '건');
      const vrow = (r) => '<tr><td class="num"><small>' + esc(r[0]) + '</small></td><td>' + esc(r[1] || '') + '</td><td><small>' + esc(r[2]) + '</small></td></tr>';
      const vhead = '<div class="table-wrap"><table><thead><tr><th>표결일</th><th>안건</th><th>표결</th></tr></thead><tbody>';
      if (v.dissent.length) h += '<details class="table-view"><summary>반대·기권한 안건 ' + nf.format(v.dissent.length) + '건 보기</summary>' + vhead + v.dissent.map(vrow).join('') + '</tbody></table></div></details>';
      h += '<details class="table-view"><summary>최근 표결 20건 보기</summary>' + vhead + v.recent.map(vrow).join('') + '</tbody></table></div></details>';
    });
    if (a.votes) h += '<p class="small muted" style="margin-top:6px">"불참"은 표결 시점에 투표하지 않은 것으로, 출장·청가는 물론 국회의장·부의장(관례상 표결에 잘 참여하지 않음), 장관 겸직, 당직·선거 출마 같은 사유가 있을 수 있습니다. 참여 = 찬성·반대·기권. 참여율만으로 의정활동을 평가하지 마세요.</p>';
    h += '<p class="small muted" style="margin-top:10px">' + esc(ASM_CAVEAT) + ' 출처: 국회사무처 열린국회정보 Open API (' + esc((sum.fetched_at || '').slice(0, 10)) + ' 수집). 법안 링크는 국회 의안정보시스템으로 연결됩니다.</p></section>';
    return h;
  }


  // ------------------------------------------------------------------ 정치인의 돈 · 많이 쓴 곳
  const loadMoney = () => load('money', 'data/money.js');
  const CAT_NOTE = {
    '정치': '당내 경선 기탁금, 선거사무소·예비후보 활동비, 대출 상환(금융비용), 소송비 등. 선거가 있는 해에 크게 늘어납니다.',
    '홍보': '의정보고서 제작·발송, 문자, 현수막, 축·조기 등.',
    '사무실': '지역 사무소 임대료·관리비·소모품·비품.',
    '후원': '정당 당비, 의원 모임 회비, 단체·정치인 후원.',
    '차량': '렌터카·차량 구입, 주유, 정비.',
    '인건비': '지역 사무소 유급 직원 급여·수당 (국회 보좌진 급여는 국회 예산이라 여기 없음).',
    '간담회': '외부 인사와의 식사·다과.',
    '언론': '신문 구독, 언론 광고, 기자 간담회.',
    '정책': '정책 연구 용역, 도서·교육비.',
    '교통': '철도·항공·택시, 해외 출장.',
  };
  const tabLink = (base, key, cur, label) => '<a class="tag' + (key === cur ? ' solid' : '') + '" href="' + base + key + '">' + esc(label) + '</a>';

  function stripPlot(rows, opts) {
    // rows: [{label, sub, dots:[{v, flag, tip, href, name}], median, p95}] — 로그 눈금 점그림(한 점 = 한 주체)
    const all = rows.flatMap((r) => r.dots.map((d) => d.v)).filter((v) => v > 0);
    if (!all.length) return '<div class="empty">자료 없음</div>';
    const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...all)))), hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...all))));
    const W = chartW(760), L = W < 500 ? 108 : 150, R = 20, RH = 46, T = 26, H = T + rows.length * RH + 8;
    const x = (v) => L + (W - L - R) * (Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo));
    let g = '<g class="axis">';
    // 좁은 화면에서는 10배 눈금 사이가 40px보다 좁으면 건너뛴다
    const dec = (W - L - R) / (Math.log10(hi) - Math.log10(lo)), stepT = Math.pow(10, Math.max(1, Math.ceil(40 / dec)));
    for (let t = lo; t <= hi; t *= stepT) g += '<line class="gridv" x1="' + x(t) + '" x2="' + x(t) + '" y1="' + (T - 6) + '" y2="' + (H - 6) + '"/><text x="' + x(t) + '" y="' + (T - 10) + '" text-anchor="middle">' + tick(t) + '</text>';
    g += '</g>';
    rows.forEach((r, i) => {
      const cy = T + i * RH + RH / 2;
      g += '<text class="row-label" x="0" y="' + (cy + 4) + '">' + esc(r.label) + '</text>';
      if (r.sub) g += '<text class="row-sub" x="0" y="' + (cy + 18) + '">' + esc(r.sub) + '</text>';
      g += '<line class="baseline" x1="' + L + '" x2="' + (W - R) + '" y1="' + cy + '" y2="' + cy + '"/>';
      r.dots.forEach((d, j) => {
        const jitter = ((j * 7919) % 13 - 6) * 1.2;
        g += '<circle class="dot' + (d.flag ? ' flag' : '') + '" cx="' + x(d.v).toFixed(1) + '" cy="' + (cy + (d.flag ? 0 : jitter)).toFixed(1) + '" r="' + (d.flag ? 5 : 3.2) + '" data-tip="' + esc(d.tip) + '"' + (d.href ? ' data-href="' + esc(d.href) + '"' : '') + '/>';
      });
      g += '<line class="median" x1="' + x(r.median) + '" x2="' + x(r.median) + '" y1="' + (cy - 13) + '" y2="' + (cy + 13) + '"/>';
      g += '<line class="p95" x1="' + x(r.p95) + '" x2="' + x(r.p95) + '" y1="' + (cy - 10) + '" y2="' + (cy + 10) + '"/>';
      const flags = r.dots.filter((d) => d.flag).slice(W < 500 ? -1 : -2);
      flags.forEach((d, k) => (g += '<text class="flag-label" x="' + Math.min(x(d.v) + 7, W - R) + '" y="' + (cy - 8 - k * 11) + '"' + (x(d.v) > W - 110 ? ' text-anchor="end"' : '') + '>' + esc(d.name) + '</text>'));
    });
    return '<div class="chart strip" data-w="' + W + '"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(opts.label) + '">' + g + '</svg><div class="tooltip" role="status"></div></div>' +
      '<p class="map-legend"><span class="key-dot"></span> ' + esc(opts.unit) + ' <span class="key-line median"></span> 중앙값 <span class="key-line p95"></span> 상위 5% 경계 <span class="key-dot flag"></span> 기준을 넘은 곳 (눌러서 근거 보기)</p>';
  }
  function wireStrip(root) {
    root.querySelectorAll('.chart.strip').forEach((c) => {
      const tip = c.querySelector('.tooltip'), svg = c.querySelector('svg'), W = +c.dataset.w;
      c.addEventListener('mousemove', (ev) => {
        const d = ev.target.closest('.dot');
        if (!d) { tip.classList.remove('on'); return; }
        const sc = svg.getBoundingClientRect().width / W;
        tip.textContent = d.dataset.tip;
        tip.style.left = 14 + +d.getAttribute('cx') * sc + 'px';
        tip.style.top = 14 + +d.getAttribute('cy') * sc + 'px';
        tip.classList.add('on');
      });
      c.addEventListener('mouseleave', () => tip.classList.remove('on'));
      c.addEventListener('click', (ev) => { const d = ev.target.closest('.dot[data-href]'); if (d) location.hash = d.dataset.href; });
    });
  }

  async function pageMoney(q) {
    const M = await loadMoney();
    const view = q.get('view') === 'council' ? 'council' : 'assembly';
    const year = M.legislators[q.get('year')] ? q.get('year') : '2024';
    let h = '<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>정치인의 돈은 어디서 와서 어디로 가나</h1><p class="ink2" style="margin-top:10px">국회의원 정치자금(후원금·본인 자산 등)과 지방의회 업무추진비(세금)는 재원이 달라 서로 더하지 않습니다. 금액은 공개된 회계보고·집행내역을 그대로 더한 것입니다.</p></div>' +
      '<div class="ledger-tools">' + tabLink('#/money?view=', 'assembly', view, '국회의원 정치자금') + ' ' + tabLink('#/money?view=', 'council', view, '지방의회 업무추진비') + '</div>';
    if (view === 'assembly') {
      const L = M.legislators[year];
      h += '<div class="ledger-tools">' + Object.keys(M.legislators).map((y) => tabLink('#/money?view=assembly&year=', y, year, y + '년')).join(' ') + (year === '2024' ? ' <small class="muted">2024년은 제22대 총선이 있던 해입니다.</small>' : '') + '</div>';
      h += '<div class="figures"><div class="figure"><div class="label">' + year + '년 정치자금 지출</div><div class="value num">' + short(L.total) + '</div><div class="sub">의원 ' + L.legislators + '명 (예비후보 기간 포함)</div></div>' +
        '<div class="figure"><div class="label">의원 1명당 중앙값</div><div class="value num">' + short(L.median) + '</div></div></div>';
      const catItems = L.categories.map((c) => ({ label: c.name, value: c.amount }));
      h += '<div class="two-col" style="margin-top:20px"><div><h2 style="margin-top:0">어디에 썼나</h2>' + hbars(catItems) +
        '<p class="small muted" style="margin-top:6px">분류는 오마이뉴스가 정한 취재용 분류입니다. 항목을 펼쳐 세부 분류를 보세요.</p>' +
        L.categories.map((c) => '<details class="table-view"><summary>' + esc(c.name) + ' ' + short(c.amount) + '</summary><p class="small ink2">' + esc(CAT_NOTE[c.name] || '') + '</p>' +
          hbars(c.subs.slice(0, 8).map(([k, v]) => ({ label: k.replace(c.name + '_', ''), value: v }))) + '</details>').join('') + '</div>' +
        '<div><h2 style="margin-top:0">어디서 받았나</h2>' + hbars(L.income.map(([k, v]) => ({ label: k, value: v }))) +
        '<p class="small muted" style="margin-top:6px">같은 회계의 수입 합계입니다(OCR 자료). "선거비용 보전"은 선거에서 일정 득표를 한 후보에게 국가가 돌려준 선거비용으로, 세금에서 나온 돈입니다. 전년도 이월·잔액과 계좌 간 이체로 적힌 ' + short(L.incomeCarry) + '은 같은 돈이 두 번 잡힐 수 있어 뺐습니다. 개별 후원인 정보는 다루지 않습니다.</p></div></div>';
      h += '<h2>정당별</h2><p class="small muted">정당은 후원회 신고 당시 기준입니다. 의원 수가 다르므로 합계보다 1인당 중앙값을 보세요.</p><div class="table-wrap"><table><thead><tr><th>정당</th><th class="r">의원 수</th><th class="r">지출 합계</th><th class="r">1인당 중앙값</th></tr></thead><tbody>' +
        L.parties.map((p) => '<tr><td>' + esc(p[0]) + '</td><td class="r num">' + p[1] + '</td><td class="r num">' + short(p[2]) + '</td><td class="r num">' + short(p[3]) + '</td></tr>').join('') + '</tbody></table></div>' +
        '<p style="margin-top:16px"><a href="#/outliers?view=assembly&year=' + year + '">항목별로 유난히 많이 쓴 의원 보기</a> <a href="#/assembly" style="margin-left:14px">국회의원 전체 목록</a></p>';
    } else {
      const cs = M.councils;
      const fundTot = {}, catTot = {};
      cs.filter((c) => c.level !== '광역').forEach((c) => { c.funding.forEach(([k, v]) => (fundTot[k] = (fundTot[k] || 0) + v)); c.categories.forEach(([k, v]) => (catTot[k] = (catTot[k] || 0) + v)); });
      h += '<div class="two-col"><div><h2 style="margin-top:0">서울 구의회 25곳은 어디에 썼나</h2>' + hbars(Object.entries(catTot).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v }))) +
        '<p class="small muted" style="margin-top:6px">분류는 상호명과 집행목적 문구로 추정했습니다. 의회마다 공개 시작 시점이 달라 합계보다 아래 월평균을 보세요.</p></div>' +
        '<div><h2 style="margin-top:0">재원별</h2>' + hbars(Object.entries(fundTot).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: fundingLabel(k), value: v }))) + '</div></div>';
      h += '<h2>의회별 월평균</h2><div class="table-wrap"><table><thead><tr><th>의회</th><th>자료 기간</th><th class="r">월평균 지출</th><th>가장 큰 항목</th><th class="r">식사·간담회 비중</th></tr></thead><tbody>' +
        cs.map((c) => {
          const meal = c.categories.filter(([k]) => /식사|간담회|카페/.test(k)).reduce((a, [, v]) => a + v, 0);
          return '<tr><td><a href="#/council/' + esc(c.id) + '">' + esc(c.name) + '</a>' + (c.level === '광역' ? ' <small class="muted">광역</small>' : '') + '</td><td class="num"><small>' + esc(c.first) + ' ~ ' + esc(c.last) + ' (' + c.months + '개월)</small></td>' +
            '<td class="r num">' + short(c.monthly) + '</td><td><small>' + esc((c.categories[0] || [''])[0]) + '</small></td><td class="r num">' + pct(meal / (c.total || 1)) + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="small muted" style="margin-top:6px">구의회 규모(의원 수·인구)에 따라 예산 총액이 다릅니다. 같은 직책끼리 비교는 <a href="#/outliers?view=council">많이 쓴 곳</a>에서 볼 수 있습니다.</p>';
    }
    setPage(h, '정치인의 돈');
  }

  async function pageOutliers(q) {
    const M = await loadMoney();
    const view = q.get('view') === 'council' ? 'council' : 'assembly';
    let h = '<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>유난히 많이 쓴 곳</h1><p class="ink2" style="margin-top:10px">같은 항목·같은 직책끼리 비교했을 때 다른 곳보다 유난히 큰 경우를 표시합니다. <b>많이 쓴 것이 곧 잘못 쓴 것은 아닙니다.</b> 지역구가 넓으면 차량비가, 사무소가 많으면 임대료가 클 수밖에 없습니다. 점을 누르면 그 금액을 이루는 거래와 근거를 볼 수 있습니다. 금액·건수를 그대로 줄 세운 표는 <a href="#/rank">순위판</a>에 있습니다.</p></div>' +
      '<div class="ledger-tools">' + tabLink('#/outliers?view=', 'assembly', view, '국회의원: 항목별') + ' ' + tabLink('#/outliers?view=', 'council', view, '구의회: 같은 직책끼리') + '</div>';
    if (view === 'assembly') {
      const year = M.legislators[q.get('year')] ? q.get('year') : '2024';
      const L = M.legislators[year];
      h += '<div class="ledger-tools">' + Object.keys(M.legislators).map((y) => tabLink('#/outliers?view=assembly&year=', y, year, y + '년')).join(' ') + '</div>';
      const rows = L.categories.map((c) => ({
        label: c.name, sub: '중앙값 ' + short(c.median), median: c.median, p95: c.p95,
        dots: c.dots.map(([pi, v, fid]) => {
          const p = M.people[pi];
          return { v, flag: !!fid, name: p[1], tip: p[1] + ' (' + (p[2] || '') + ') ' + won(v), href: fid ? 'f/' + p[0] + '/' + fid : 's/' + p[0] + '?cat=' + c.name };
        }),
      }));
      h += stripPlot(rows, { label: year + '년 항목별 의원 지출 분포', unit: '의원 1명의 그해 항목 지출' });
      const flagged = L.categories.flatMap((c) => c.dots.filter((d) => d[2]).map((d) => [c, d])).sort((a, b) => b[1][1] / b[0].median - a[1][1] / a[0].median);
      h += '<h2>기준을 넘은 경우 <small class="muted">' + flagged.length + '</small></h2><p class="small muted">기준: 그 항목에 지출이 있는 의원 중 상위 5% 이상이면서 중앙값의 3배 이상, 1,000만원 이상.</p><div class="table-wrap"><table><thead><tr><th>항목</th><th>의원</th><th class="r">금액</th><th class="r">중앙값 대비</th><th></th></tr></thead><tbody>' +
        flagged.map(([c, d]) => { const p = M.people[d[0]]; return '<tr><td>' + esc(c.name) + '</td><td><a href="' + href('s', p[0]) + '?cat=' + encodeURIComponent(c.name) + '">' + esc(p[1]) + '</a> <small class="muted nowrap">' + esc(p[2] || '') + '</small></td><td class="r num">' + won(d[1]) + '</td><td class="r num">' + (d[1] / c.median).toFixed(1) + '배</td><td class="nowrap"><a class="small" href="' + href('f', p[0], d[2]) + '">근거</a></td></tr>'; }).join('') + '</tbody></table></div>';
    } else {
      const years = [...new Set(M.roles.map((r) => r.year))].sort();
      const year = years.includes(q.get('year')) ? q.get('year') : years[years.length - 2] || years[0];
      h += '<div class="ledger-tools">' + years.map((y) => tabLink('#/outliers?view=council&year=', y, year, y + '년')).join(' ') + ' <small class="muted">서울시의회(광역)는 예산 규모가 달라 기준 계산에서 빼고 회색 점으로만 보여줍니다.</small></div>';
      const rows = M.roles.filter((r) => r.year === year).map((r) => ({
        label: r.group, sub: '중앙값 월 ' + short(r.median), median: r.median, p95: r.p95,
        dots: r.dots.map((d) => ({ v: d[3], flag: !!d[6], name: d[1].replace('의회', ''), tip: d[1] + ' ' + d[2] + ' 월평균 ' + won(d[3]) + ' (' + d[4] + '개월)' + (d[5] === '광역' ? ', 광역의회' : ''),
          href: d[6] ? 'f/' + d[0] + '/' + d[6] : 's/' + d[0] })),
      }));
      h += stripPlot(rows, { label: year + '년 구의회 직책별 월평균 업무추진비', unit: '한 의회 직책의 월평균 의회운영업무추진비' });
      h += '<p class="small muted">직책·기수 단위입니다. 같은 해에 전·후반기가 바뀌면 한 의회가 두 점으로 나옵니다. 자료가 6개월 이상인 경우만 넣었습니다.</p>';
    }
    h += '<h2>법령 기준과 대조한 표시</h2><p class="ink2">금액의 크기와 별개로, 회계관리 훈령의 기준과 대조한 표시도 함께 보세요.</p><ul class="rule-list">' +
      META.rules.filter((r) => r.reference_type === 'REGULATORY' && r.count).map((r) => '<li><span class="code">' + esc(r.code) + '</span><div><a href="' + href('rules', r.id) + '">' + esc(r.name) + '</a><p>' + esc(r.purpose) + '</p></div><span class="count">' + nf.format(r.count) + '건</span></li>').join('') + '</ul>';
    setPage(h, '유난히 많이 쓴 곳');
    wireStrip(main());
  }

  // ------------------------------------------------------------------ 순위판 (공개 금액·건수를 그대로 줄 세운 것. 판단은 독자 몫)
  const loadRank = () => load('rank', 'data/rank.js');
  const pct1 = (x) => (x == null ? '—' : (x * 100).toFixed(x < 0.1 ? 1 : 0) + '%');
  function rankBoard(title, rows, o) {
    // rows: [{label, href, sub, value, show, extra(HTML)}]
    o = o || {};
    const head = '<section class="board"><h3>' + esc(title) + '</h3>' + (o.note ? '<p class="small muted">' + o.note + '</p>' : '');
    if (!rows.length) return head + '<div class="empty">자료 없음</div></section>';
    const max = Math.max(...rows.map((r) => r.value)) || 1;
    const item = (r, i) => '<li><span class="rk num">' + (i + 1) + '</span><div class="who">' + (r.href ? '<a href="' + r.href + '">' + esc(r.label) + '</a>' : esc(r.label)) +
      (r.sub ? '<small>' + esc(r.sub) + '</small>' : '') + '</div><div class="val"><b class="num">' + r.show + '</b><span class="bar"><i style="width:' +
      (100 * Math.max(0, r.value) / max).toFixed(1) + '%"></i></span>' + (r.extra ? '<small>' + r.extra + '</small>' : '') + '</div></li>';
    const rest = rows.slice(10);
    return head + '<ol class="rank-list">' + rows.slice(0, 10).map(item).join('') + '</ol>' +
      (rest.length ? '<details class="more"><summary>11~' + rows.length + '위 보기</summary><ol class="rank-list">' + rest.map((r, i) => item(r, i + 10)).join('') + '</ol></details>' : '') +
      (o.foot ? '<p class="board-foot small muted">' + o.foot + '</p>' : '') + '</section>';
  }
  const subjName = (sid) => { const s = subjectById[sid]; return s ? (s.type === 'LEGISLATOR' ? s.name + ' 의원' : subjectLabel(s)) : sid; };
  const subjLink = (sid) => '<a href="' + href('s', sid) + '">' + esc(subjName(sid)) + '</a>';
  function legRow(sid, value, show, extra, suffix) {
    const s = subjectById[sid] || { name: sid };
    return { label: s.name, href: href('s', sid) + (suffix || ''), sub: [s.party, s.district].filter(Boolean).join(', '), value, show, extra };
  }
  const footOf = (b, unit, fmt) => '비교 대상 ' + nf.format(b.n) + unit + ', 중앙값 ' + fmt(b.median);
  const countFmt = (unit) => (v) => nf.format(Math.round(v)) + unit;

  async function pageRank(q) {
    const R = await loadRank();
    const tabs = [['assembly', '국회의원'], ['council', '지방의회'], ['places', '함께 쓰는 가게'], ['price', '가격 차이'], ['assets', '재산']];
    const tab = tabs.some(([k]) => k === q.get('tab')) ? q.get('tab') : 'assembly';
    let h = '<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>순위판</h1><p class="ink2" style="margin-top:10px">공개 자료의 금액·건수를 그대로 줄 세웠습니다. ' +
      '판단은 보시는 분의 몫입니다. 많이 쓴 것이 곧 잘못 쓴 것은 아니어서, 지역구 크기·직책·자료 기간·선거 여부에 따라 달라집니다. 이름을 누르면 그 금액을 이루는 실제 거래가 나옵니다. ' +
      '재원이 다른 돈(국회의원 정치자금과 지방의회 업무추진비)은 서로 비교하지 않습니다.</p></div>' +
      '<div class="ledger-tools">' + tabs.map(([k, l]) => tabLink('#/rank?tab=', k, tab, l)).join(' ') + '</div>';
    if (tab === 'assembly') h += rankAssembly(R, q);
    else if (tab === 'council') h += rankCouncil(R, q);
    else if (tab === 'places') h += rankPlaces(R, q);
    else if (tab === 'price') h += rankPrice(R);
    else h += rankAssets(await loadAssets(), q);
    setPage(h, '순위판');
    if (q.get('region')) { const el = document.getElementById('region-list'); if (el) setTimeout(() => el.scrollIntoView(), 50); }
    const sel = document.getElementById('rank-council');
    if (sel) sel.addEventListener('change', () => { location.hash = '#/rank?tab=council&council=' + encodeURIComponent(sel.value); });
  }

  function rankAssembly(R, q) {
    const years = Object.keys(R.assembly);
    const y = years.includes(q.get('year')) ? q.get('year') : years[years.length - 1];
    const A = R.assembly[y], mm = R.params.minMeals;
    const cat = A.catOrder.includes(q.get('cat')) ? q.get('cat') : A.catOrder[0];
    const base = '#/rank?tab=assembly&year=';
    let h = '<div class="ledger-tools">' + years.map((yy) => tabLink(base, yy, y, yy + '년')).join(' ') +
      (y === '2024' ? ' <small class="muted">2024년은 제22대 총선이 있던 해라 예비후보·선거 관련 지출이 섞여 있습니다.</small>' : '') + '</div>' +
      '<p class="small muted">정치자금은 후원금·본인 자산 등으로 이뤄진 돈입니다(세금 아님, 선거비용 제외). 언론사가 선관위 보고서를 OCR로 옮긴 2차 자료라 오류가 있을 수 있습니다. 제21·22대 의원만 넣었습니다.</p>';
    h += '<div class="boards">' +
      rankBoard('정치자금 지출 총액', A.total.rows.map((r) => legRow(r[0], r[1], short(r[1]), nf.format(r[2]) + '건')), { foot: footOf(A.total, '명', short) }) +
      rankBoard('식사·다과 결제 건수', A.mealCount.rows.map((r) => legRow(r[0], r[1], nf.format(r[1]) + '건', short(r[2]), '?cat=간담회')),
        { note: '간담회 식대·다과, 기자 식대, 사무실 식대.', foot: footOf(A.mealCount, '명', countFmt('건')) }) +
      rankBoard('식사 1회 평균 금액', A.mealAvg.rows.map((r) => legRow(r[0], r[1], won(r[1]), r[2] + '건 평균', '?cat=간담회')),
        { note: '식사·다과가 ' + mm + '건 이상인 의원만. 인원 정보가 없어 1인당 금액은 알 수 없습니다.', foot: footOf(A.mealAvg, '명', won) }) +
      rankBoard('식사한 가게 수', A.mealPlaces.rows.map((r) => legRow(r[0], r[1], nf.format(r[1]) + '곳', r[2] + '건')), { foot: footOf(A.mealPlaces, '명', countFmt('곳')) }) +
      rankBoard('한 가게에 몰린 비율', A.mealTopPlace.rows.map((r) => legRow(r[0], r[1], pct(r[1]), '<a href="' + href('m', r[2]) + '">' + esc(r[3]) + '</a> ' + short(r[4]))),
        { note: '식사비 중 가장 많이 쓴 가게 한 곳의 비중(' + mm + '건 이상). 국회 안 식당이나 사무실 근처 단골집이면 높게 나옵니다.', foot: footOf(A.mealTopPlace, '명', pct) }) +
      rankBoard('주말·공휴일 식사 비율', A.weekend.rows.map((r) => legRow(r[0], r[1], pct(r[1]), r[2] + '/' + r[3] + '건')),
        { note: '지역구 행사가 주말에 많으면 높게 나옵니다. 정치자금에는 업무추진비 같은 주말 사용 제한 규정이 없습니다.', foot: footOf(A.weekend, '명', pct) }) +
      '</div>';
    const C = A.categories[cat];
    h += '<h2>항목별 순위</h2><div class="ledger-tools">' + A.catOrder.map((c) => tabLink(base + y + '&cat=', c, cat, c)).join(' ') + '</div>' +
      '<div class="boards one">' + rankBoard(y + '년 ' + cat + ' 지출', C.rows.map((r) => legRow(r[0], r[1], short(r[1]), null, '?cat=' + encodeURIComponent(cat))),
        { note: esc(CAT_NOTE[cat] || '') + ' 분류는 오마이뉴스가 정한 취재용 분류입니다.', foot: footOf(C, '명', short) }) + '</div>';
    return h;
  }

  function rankCouncil(R, q) {
    const C = R.council, minM = R.params.minMonths;
    const seoul = C.councils.find((c) => c[2] === '광역');
    const sel = C.councils.some((c) => c[0] === q.get('council')) ? q.get('council') : 'all';
    const opts = [['all', '서울 구의회 전체']].concat((seoul ? [[seoul[0], seoul[1]]] : []),
      C.councils.filter((c) => c[2] !== '광역').map((c) => [c[0], c[1]]).sort((a, b) => a[1].localeCompare(b[1], 'ko')));
    let h = '<div class="ledger-tools"><label>의회 <select id="rank-council">' + opts.map(([k, l]) => '<option value="' + esc(k) + '"' + (k === sel ? ' selected' : '') + '>' + esc(l) + '</option>').join('') + '</select></label></div>' +
      '<p class="small muted">지방의회 업무추진비는 세금입니다. 공개 자료에는 성명 없이 직책만 있어서, 그 기간에 직책을 맡았던 사람(의회 홈페이지의 선출 기록)의 이름으로 모았습니다. ' +
      '직책 수행 경비이고 결제는 비서실·사무국이 할 수 있으므로 개인 지출이라는 뜻은 아닙니다. 사람별 합계에서는 보유자를 확인하지 못한 기간의 지출이 빠집니다.</p>';
    const people = C.people.filter((p) => (sel === 'all' ? p[9] !== '광역' : p[0] === sel));
    const roles = C.roles.filter((r) => (sel === 'all' ? r[7] !== '광역' : r[1] === sel));
    const holderNames = C.holderCouncils.filter((s) => sel !== 'all' || s !== 'seoul').map((s) => SOURCE_NAME[s] || s).join(', ');
    const pRow = (p, v, show, extra) => ({ label: p[1], href: personHref(p[0], p[1]), value: v, show, extra,
      sub: [sel === 'all' ? SOURCE_NAME[p[0]] || p[0] : null, p[2], p[7].join(', ')].filter(Boolean).join(', ') });
    const monthly = people.filter((p) => p[5] >= minM).sort((a, b) => b[6] - a[6]);
    const total = people.slice().sort((a, b) => b[3] - a[3]);
    h += '<div class="boards">' +
      rankBoard('직책별 업무추진비 월평균', roles.slice(0, 30).map((r) => ({ label: subjName(r[0]), href: href('s', r[0]), value: r[5], show: short(r[5]),
        sub: r[6].length ? '맡은 사람: ' + r[6].join(', ') : '', extra: r[4] + '개월, 총 ' + short(r[2]) })),
        { note: '직책·기수(전·후반기) 단위, 의회운영업무추진비만. 자료가 ' + minM + '개월 이상인 경우. 의장은 부의장·위원장보다 예산이 많이 편성됩니다.', foot: '대상 ' + roles.length + '개 직책' + (sel === 'all' ? ' (서울시의회 제외)' : '') }) +
      (people.length ? rankBoard('직책을 맡은 사람별 월평균', monthly.slice(0, 30).map((p) => pRow(p, p[6], short(p[6]), p[5] + '개월, 총 ' + short(p[3]))),
        { note: '같은 사람이 맡은 직책을 모두 합친 값. 보유자 기록을 모은 의회만 나옵니다: ' + esc(holderNames) + '.', foot: '대상 ' + monthly.length + '명' }) +
      rankBoard('직책을 맡은 사람별 총액', total.slice(0, 30).map((p) => pRow(p, p[3], short(p[3]), p[5] + '개월, ' + nf.format(p[4]) + '건')),
        { note: '직책을 오래 맡을수록 커지므로 월평균과 함께 보세요.', foot: '대상 ' + total.length + '명' }) : '');
    if (sel === 'all') {
      const gu = C.councils.filter((c) => c[2] !== '광역');
      const cRow = (c, v, show, extra) => ({ label: c[1], href: '#/council/' + encodeURIComponent(c[0]), sub: c[4] + ' ~ ' + c[5] + ' (' + c[3] + '개월)', value: v, show, extra });
      const by = (i) => gu.filter((c) => c[i] != null && c[i] > 0).sort((a, b) => b[i] - a[i]);
      h += rankBoard('의원 관련 경비 월평균', by(6).map((c) => cRow(c, c[6], short(c[6]))),
          { note: '의회운영업무추진비, 의정운영공통경비, 교섭단체 경비의 월평균. 의원 수와 인구가 의회마다 다릅니다.' + (seoul ? ' 서울시의회(광역)는 규모가 달라 뺐습니다(월 ' + short(seoul[6]) + ').' : '') }) +
        rankBoard('식사 1인당 평균 금액', by(8).map((c) => cRow(c, c[8], won(c[8]))),
          { note: '인원이 적힌 식사 합계를 인원 합계로 나눈 값. 간담회 기준은 1인 4만원(2024년 9월 22일까지), 5만원(23일부터)입니다.' }) +
        rankBoard('주말·공휴일 식사 비율', by(9).map((c) => cRow(c, c[9], pct1(c[9]))), { note: '업무추진비는 주말·공휴일 사용이 원칙적으로 제한되고, 사유를 적으면 쓸 수 있습니다.' }) +
        rankBoard('한 가게에 몰린 비율', by(12).map((c) => cRow(c, c[12], pct1(c[12]), '<a href="' + href('m', c[10]) + '">' + esc(c[11]) + '</a>')), { note: '식사비 중 가장 많이 쓴 가게 한 곳의 비중.' }) +
        rankBoard('사무국 경비 월평균', by(7).map((c) => cRow(c, c[7], short(c[7]))), { note: '의회사무국(공무원)의 기관·시책·부서 업무추진비. 의원 지출이 아니며, 따로 공개하지 않는 의회는 빠집니다.' });
    } else {
      const c = C.councils.find((x) => x[0] === sel);
      h += rankBoard(c[1] + '가 가장 많이 쓴 식당', (R.places.perCouncil[sel] || []).map((r) => ({ label: r[1], href: href('m', r[0]),
        sub: [r[2], nf.format(r[4]) + '건'].filter(Boolean).join(', '), value: r[5], show: short(r[5]), extra: '최다 ' + subjLink(r[6]) + ' ' + short(r[7]) })), { note: '체인점·결제대행 제외.' });
      h += '</div><div class="figures" style="margin-top:8px">' +
        '<div class="figure"><div class="label">의원 관련 경비 월평균</div><div class="value num">' + short(c[6]) + '</div><div class="sub">' + esc(c[4]) + ' ~ ' + esc(c[5]) + '</div></div>' +
        '<div class="figure"><div class="label">식사 1인당 평균</div><div class="value num">' + (c[8] ? won(c[8]) : '—') + '</div></div>' +
        '<div class="figure"><div class="label">주말·공휴일 식사</div><div class="value num">' + pct1(c[9]) + '</div></div>' +
        '<div class="figure"><div class="label">식사한 가게</div><div class="value num">' + nf.format(c[13]) + '곳</div><div class="sub">식사 ' + nf.format(c[14]) + '건</div></div>' +
        '</div><p><a href="#/council/' + encodeURIComponent(sel) + '">' + esc(c[1]) + ' 전체 지출 보기</a></p>';
      return h;
    }
    return h + '</div>';
  }

  function rankPlaces(R, q) {
    const P = R.places;
    const who = q.get('who') === 'council' ? 'council' : 'assembly';
    let h = '<div class="ledger-tools">' + tabLink('#/rank?tab=places&who=', 'assembly', who, '국회의원') + ' ' + tabLink('#/rank?tab=places&who=', 'council', who, '지방의회') + '</div>' +
      '<p class="small muted">사업자로 확인된 거래처만 셉니다. 스타벅스 같은 전국 체인은 지점이 여러 곳이라 한 장소로 보지 않아 식당 순위에서 뺐고, 결제대행·배달앱도 뺐습니다. ' +
      '지역은 사업자 주소라 본사 주소일 수 있습니다(예: 국회 의원식당 운영사 엘에스씨푸드는 노원구). 가게를 누르면 누가 언제 얼마를 썼는지 나옵니다.</p>';
    const place = (r, value, show, sub, extra) => ({ label: r[1], href: href('m', r[0]), sub, value, show, extra });
    const topBy = (r) => '최다 ' + subjLink(r[6]) + ' ' + short(r[7]);
    if (who === 'assembly') {
      h += '<div class="boards">' +
        rankBoard('국회의원이 가장 많이 찾은 식당', P.kaMealByPeople.rows.map((r) => place(r, r[3], r[3] + '명', [r[2], nf.format(r[4]) + '건', short(r[5])].filter(Boolean).join(', '), topBy(r))),
          { note: '2023~2024년 정치자금 식사·다과 결제. 그 식당에서 결제한 의원 수 순.', foot: '식당 ' + nf.format(P.counts.kaMeal) + '곳' }) +
        rankBoard('식사비가 가장 많이 나간 식당', P.kaMealByAmount.rows.map((r) => place(r, r[5], short(r[5]), [r[2], '의원 ' + r[3] + '명', nf.format(r[4]) + '건'].filter(Boolean).join(', '), topBy(r)))) +
        rankBoard('의원들이 공통으로 쓰는 업체 (식당 외)', P.kaVendorByPeople.rows.map((r) => place(r, r[3], r[3] + '명', [r[2], r[8]].filter(Boolean).join(', '), short(r[5]) + ', ' + topBy(r))),
          { note: '정당 당비, 문자 발송, 렌터카, 통신·전기요금처럼 많은 의원이 같은 곳에 내는 돈.' }) +
        rankBoard('돈이 가장 많이 나간 업체 (식당 외)', P.kaVendorByAmount.rows.map((r) => place(r, r[5], short(r[5]), [r[2], r[8], '의원 ' + r[3] + '명'].filter(Boolean).join(', '), topBy(r)))) +
        '<section class="board"><h3>지역별 식사비</h3><p class="small muted">식당 사업자 주소의 시·군·구 기준.</p>' + hbars(P.kaRegions.map(([k, v]) => ({ label: k, value: v }))) + '</section>' +
        '</div>';
    } else {
      h += '<div class="boards">' +
        rankBoard('여러 의회가 함께 쓰는 식당', P.councilMealByCouncils.rows.map((r) => place(r, r[8], r[8] + '곳', [r[2], nf.format(r[4]) + '건', short(r[5])].filter(Boolean).join(', '), topBy(r))),
          { note: '그 식당에서 결제한 의회 수 순. 국회·시청 근처 식당이 많습니다.', foot: '식당 ' + nf.format(P.counts.councilMeal) + '곳' }) +
        rankBoard('식사비가 가장 많이 나간 식당', P.councilMealByAmount.rows.map((r) => place(r, r[5], short(r[5]), [r[2], nf.format(r[4]) + '건'].filter(Boolean).join(', '), topBy(r)))) +
        rankBoard('국회의원과 지방의회가 함께 쓰는 식당', P.both.map((r) => place(r, r[3], '의원 ' + r[3] + '명', r[2] || '', '의회 ' + r[5] + '곳, 정치자금 ' + short(r[4]) + ', 업무추진비 ' + short(r[6])))) +
        rankBoard('돈이 가장 많이 나간 업체 (식당 외)', P.councilVendorByAmount.rows.map((r) => place(r, r[5], short(r[5]), [r[2], r[9], '의회 ' + r[8] + '곳'].filter(Boolean).join(', '), topBy(r))),
          { note: '물품 구매, 경조사 화환, 성금·회비 등.' }) +
        '<section class="board"><h3>지역별 식사비</h3><p class="small muted">결제 행에 적힌 주소(없으면 사업자 주소)의 시·군·구 기준.</p>' + hbars(P.councilRegions.map(([k, v]) => ({ label: k, value: v }))) + '</section>' +
        '</div>';
    }
    return h;
  }

  function rankPrice(R) {
    const X = R.price, p = X.params;
    let h = '<p class="ink2">같은 식당에서 다른 결제들이 보통 낸 1인당 금액(중앙값)과 비교해 <b>' + p.ratio + '배 이상이면서 1인당 ' + won(p.extra) + ' 이상</b> 비싸게 낸 결제입니다. ' +
      '기준은 시중가가 아니라 <b>그 가게의 평소 가격</b>입니다.</p>' +
      '<div class="figures"><div class="figure"><div class="label">비교한 식사</div><div class="value num">' + nf.format(X.checked) + '건</div><div class="sub">식당 ' + nf.format(X.venues) + '곳</div></div>' +
      '<div class="figure"><div class="label">평소보다 크게 비싼 결제</div><div class="value num">' + nf.format(X.count) + '건</div><div class="sub">' + pct1(X.count / (X.checked || 1)) + '</div></div></div>' +
      '<p class="small muted">비교 대상: 지방의회의 인원이 적힌 식사 결제. 인원이 적힌 결제가 ' + p.minMeals + '건 이상이고 평소 1인당 금액이 ' + won(p.baseMin) + ' 이상인 식당만 썼습니다. ' +
      '구내식당 식권·매점·도시락처럼 여러 명분을 한 번에 사는 곳과 스캔본 OCR로 읽은 행(인원 오독 위험)은 뺐습니다. 국회의원 정치자금은 인원 정보가 없어 1인당 비교를 할 수 없습니다.</p>';
    h += '<div class="boards">' + rankBoard('평소보다 크게 비싼 결제가 많은 지출 주체', X.bySubject.rows.map((r) => ({ label: subjName(r[0]), href: href('s', r[0]),
      value: r[1], show: r[1] + '건', sub: '이 주체가 비교 대상 식당에서 낸 결제 ' + nf.format(r[3]) + '건 중', extra: '평소 가격보다 더 낸 금액 ' + short(r[2]) })),
      { note: '지방의회는 직책·위원회 단위로 공개되어 사람이 아닌 직책·기수 단위입니다.' }) + '</div>';
    h += '<h2>배수가 큰 결제</h2><div class="table-wrap"><table><thead><tr><th>날짜</th><th>지출 주체</th><th>가게</th><th class="r">결제액 (인원)</th><th class="r">1인당</th><th class="r">가게 평소 1인당</th><th class="r">배수</th></tr></thead><tbody>' +
      X.tx.map((r) => '<tr><td class="num nowrap">' + esc(r[2]) + '</td><td><a href="' + href('s', r[1]) + '?tx=' + encodeURIComponent(r[0]) + '">' + esc(subjName(r[1])) + '</a></td>' +
        '<td><a href="' + href('m', r[3]) + '">' + esc(r[4]) + '</a> <small class="muted">결제 ' + r[10] + '건 기준</small></td><td class="r num">' + won(r[5]) + ' <small class="muted">(' + r[6] + '명)</small></td>' +
        '<td class="r num"><mark>' + won(r[7]) + '</mark></td><td class="r num">' + won(r[8]) + '</td><td class="r num">' + r[9].toFixed(1) + '배</td></tr>').join('') + '</tbody></table></div>' +
      '<div class="limits" style="margin-top:16px"><div><b>인원은 스스로 적은 숫자</b>참석 인원이 실제보다 적게 적히면 1인당 금액이 커집니다. 참석자 명단은 공개되지 않습니다.</div>' +
      '<div><b>같은 가게, 다른 주문</b>코스 요리, 포장·선물용 구매, 추가 주문처럼 같은 가게라도 1인당 금액이 크게 다를 수 있습니다.</div>' +
      '<div><b>시중가 비교는 아님</b>지방의회 물품 구매 내역에는 수량이 거의 적혀 있지 않아(' + nf.format(X.goods.count) + '건 중 ' + nf.format(X.goods.withQuantity) + '건) 단가를 시중가와 비교할 수 없습니다.</div></div>';
    return h;
  }

  // ------------------------------------------------------------------ 재산 (국회공보 정기재산공개, 신고가액)
  const loadAssets = () => load('assets', 'data/assets.js');
  const signed = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + short(v));
  const ASSET_CAVEAT = '신고가액 기준입니다. 부동산은 공시가격이나 취득 당시 실거래가로 신고해 시세보다 낮을 수 있고, 비상장주식은 액면가 등으로 평가하기도 합니다. ' +
    '본인·배우자·직계존비속의 재산을 합친 값이며, 허가를 받아 고지를 거부한 부모·자녀의 재산은 빠집니다.';
  function assetSource(A) {
    return '출처: <a href="' + esc(A.source.listPage || A.source.url) + '">' + esc(A.source.title) + '</a>' + (A.source.notice ? ' (' + esc(A.source.notice) + ')' : '') +
      ', ' + esc(A.source.published) + ' 공개, ' + esc(A.source.basis) + ' 기준. 부동산 위치는 읍·면·동까지만 싣고 지번·건물명·동호수는 싣지 않습니다.';
  }
  function assetItems(A) {
    if (!A._re) A._re = A.realestate.rows.map((r) => Object.fromEntries(A.realestate.cols.map((c, i) => [c, r[i]])));
    return A._re;
  }
  const placeOf = (r) => [r.sido, r.sgg, r.emd].filter(Boolean).join(' ');
  const assetGross = (A, p) => p.groups.reduce((a, v, i) => a + (A.groups[i] === '채무' ? 0 : Math.max(0, v)), 0);
  const gi = (A, name) => A.groups.indexOf(name);
  function realestateTable(rows, withPerson, A) {
    if (!rows.length) return '<div class="empty">신고한 부동산이 없습니다.</div>';
    return '<div class="table-wrap"><table class="re-table' + (withPerson ? ' wide' : '') + '"><thead><tr>' + (withPerson ? '<th>의원</th>' : '') + '<th>관계</th><th>종류</th><th>위치</th><th>면적</th><th class="r">신고가액</th><th class="r">1년 전</th><th>변동 사유</th></tr></thead><tbody>' +
      rows.map((r) => {
        const p = withPerson ? A.people[r.person] : null;
        return '<tr>' + (withPerson ? '<td>' + (p.sid ? '<a href="' + href('s', p.sid) + '?sec=assets">' + esc(p.name) + '</a>' : esc(p.name)) + ' <small class="muted nowrap">' + esc(p.party || '') + '</small></td>' : '') +
          '<td class="nowrap">' + esc(r.relation) + '</td><td>' + esc(r.kind) + (r.lease ? ' ' + tag('소유 아님') : '') + '</td><td>' + esc(placeOf(r)) + '</td><td><small>' + esc(r.area) + '</small></td>' +
          '<td class="r num">' + won(r.cur) + '</td><td class="r num"><small>' + won(r.prev) + '</small></td><td><small>' + esc(r.reason || '') + '</small></td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  // 의원 페이지의 재산 섹션
  async function fillAssetSection(sid, scroll) {
    const box = document.getElementById('asset-area');
    if (!box) return;
    let A;
    try { A = await loadAssets(); } catch (e) { return; }
    const pi = A.people.findIndex((p) => p.sid === sid);
    if (pi < 0) return;
    const p = A.people[pi], gross = assetGross(A, p);
    const debt = p.groups[gi(A, '채무')];
    const comp = A.groups.map((g, i) => ({ g, v: p.groups[i] })).filter((x) => x.g !== '채무' && x.v > 0);
    const mine = assetItems(A).filter((r) => r.person === pi);
    const now = mine.filter((r) => r.cur > 0), gone = mine.filter((r) => !r.cur && r.prev > 0);
    box.innerHTML = '<section class="asset-section"><h2>재산 <small class="muted">' + esc(A.source.basis) + ' 기준 신고</small></h2>' +
      '<div class="figures"><div class="figure"><div class="label">순재산 (채무 차감)</div><div class="value num">' + short(p.cur) + '</div><div class="sub">재산 ' + short(gross) + ', 채무 ' + short(debt) + '</div></div>' +
      '<div class="figure"><div class="label">1년 사이 증감</div><div class="value num">' + signed(p.change) + '</div><div class="sub">그중 가액변동 ' + signed(p.valuation) + '</div></div>' +
      '<div class="figure"><div class="label">소유 부동산</div><div class="value num">' + p.owned + '건</div><div class="sub">' + short(p.groups[gi(A, '부동산')]) + '</div></div>' +
      (p.refused.length ? '<div class="figure"><div class="label">고지거부</div><div class="value num">' + p.refused.length + '명</div><div class="sub">' + esc(p.refused.join(', ')) + '</div></div>' : '') + '</div>' +
      '<div class="two-col"><div><h3>무엇으로 가지고 있나</h3>' + hbars(comp.map((x) => ({ label: x.g, value: x.v })), (v) => short(v) + ' (' + pct1(v / (gross || 1)) + ')') +
      '<p class="small muted" style="margin-top:6px">채무 ' + short(debt) + '는 빼기 전 재산 대비 비율입니다. 전세·임차권은 빌려 쓰는 집·사무실의 보증금으로 소유가 아닙니다. 정치자금 계좌는 정치자금 수입·지출용 예금입니다.</p></div>' +
      '<div><h3>가액변동이란</h3><p class="small ink2">1년 사이 증감 중 사고팔지 않고 공시가격·주가 등이 바뀌어 생긴 부분입니다. 나머지는 매매·저축·상속 같은 실제 변동입니다.</p></div></div>' +
      '<h3>부동산 (' + now.length + '건)</h3>' + realestateTable(now, false, A) +
      (gone.length ? '<details class="table-view"><summary>지난 1년 사이 정리한 부동산 ' + gone.length + '건</summary>' + realestateTable(gone, false, A) + '</details>' : '') +
      '<p class="small muted" style="margin-top:8px">' + ASSET_CAVEAT + ' ' + assetSource(A) + ' (공보 ' + p.page + '쪽)</p></section>';
    if (scroll) box.scrollIntoView();
  }

  // 순위판 '재산' 탭
  function rankAssets(A, q) {
    const parties = Object.entries(A.people.reduce((m, p) => ((m[p.party || '미상'] = (m[p.party || '미상'] || 0) + 1), m), {})).sort((a, b) => b[1] - a[1]);
    const party = parties.some(([k]) => k === q.get('party')) ? q.get('party') : '';
    const P = A.people.map((p, i) => ({ ...p, i, gross: assetGross(A, p) })).filter((p) => !party || (p.party || '미상') === party);
    const base = '#/rank?tab=assets' + (party ? '&party=' + encodeURIComponent(party) : '');
    const g = (name) => gi(A, name);
    const pRow = (p, value, show, extra) => ({ label: p.name, href: p.sid ? href('s', p.sid) + '?sec=assets' : null, sub: [p.party, p.district].filter(Boolean).join(', '), value, show, extra });
    const top = (arr, key) => arr.slice().sort((a, b) => key(b) - key(a)).slice(0, 30);
    const med = (arr) => { const s = arr.slice().sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };
    let h = '<div class="ledger-tools"><a class="tag' + (party ? '' : ' solid') + '" href="#/rank?tab=assets">전체</a> ' +
      parties.map(([k, n]) => '<a class="tag' + (k === party ? ' solid' : '') + '" href="#/rank?tab=assets&party=' + encodeURIComponent(k) + '">' + esc(k) + ' ' + n + '</a>').join(' ') + '</div>' +
      '<p class="small muted">' + ASSET_CAVEAT + ' ' + assetSource(A) + '</p>' +
      '<div class="figures"><div class="figure"><div class="label">공개 대상 의원</div><div class="value num">' + P.length + '명</div></div>' +
      '<div class="figure"><div class="label">순재산 중앙값</div><div class="value num">' + short(med(P.map((p) => p.cur))) + '</div></div>' +
      '<div class="figure"><div class="label">1년 사이 재산이 늘어난 의원</div><div class="value num">' + P.filter((p) => p.change > 0).length + '명</div><div class="sub">' + pct(P.filter((p) => p.change > 0).length / (P.length || 1)) + '</div></div>' +
      '<div class="figure"><div class="label">부모·자녀 재산 고지거부</div><div class="value num">' + P.filter((p) => p.refused.length).length + '명</div></div></div>';
    const rich = P.filter((p) => p.gross >= 1e8);
    h += '<div class="boards">' +
      rankBoard('순재산', top(P, (p) => p.cur).map((p) => pRow(p, p.cur, short(p.cur), '1년 ' + signed(p.change))), { foot: '중앙값 ' + short(med(P.map((p) => p.cur))) }) +
      rankBoard('1년 사이 가장 많이 늘어난', top(P.filter((p) => p.change > 0), (p) => p.change).map((p) => pRow(p, p.change, signed(p.change), '그중 가액변동 ' + signed(p.valuation))),
        { note: '가액변동은 사고팔지 않고 공시가격·주가 등이 바뀐 부분입니다.' }) +
      rankBoard('1년 사이 가장 많이 줄어든', top(P.filter((p) => p.change < 0), (p) => -p.change).map((p) => pRow(p, -p.change, signed(p.change), '그중 가액변동 ' + signed(p.valuation)))) +
      rankBoard('소유 부동산 신고가액', top(P, (p) => p.groups[g('부동산')]).map((p) => pRow(p, p.groups[g('부동산')], short(p.groups[g('부동산')]), p.owned + '건')),
        { note: '토지·건물 중 소유한 것. 전세·임차권은 뺐습니다.' }) +
      rankBoard('소유 부동산 건수', top(P, (p) => p.owned).map((p) => pRow(p, p.owned, p.owned + '건', short(p.groups[g('부동산')]))),
        { note: '필지·호실 단위라 땅 한 곳이 여러 건일 수 있습니다.' }) +
      rankBoard('재산 중 부동산 비중', top(rich, (p) => p.groups[g('부동산')] / p.gross).map((p) => pRow(p, p.groups[g('부동산')] / p.gross, pct(p.groups[g('부동산')] / p.gross), short(p.groups[g('부동산')]) + ' / ' + short(p.gross))),
        { note: '채무를 빼기 전 재산 대비. 재산 1억원 이상인 의원만.' }) +
      rankBoard('증권 (주식·채권형 증권)', top(P.filter((p) => p.groups[g('증권')] > 0), (p) => p.groups[g('증권')]).map((p) => pRow(p, p.groups[g('증권')], short(p.groups[g('증권')]))),
        { note: '비상장주식은 액면가 등으로 평가되기도 합니다. 펀드·ETF는 예금에 신고합니다.' }) +
      rankBoard('예금 (보험·펀드 포함)', top(P, (p) => p.groups[g('예금')]).map((p) => pRow(p, p.groups[g('예금')], short(p.groups[g('예금')])))) +
      rankBoard('채무', top(P.filter((p) => p.groups[g('채무')] > 0), (p) => p.groups[g('채무')]).map((p) => pRow(p, p.groups[g('채무')], short(p.groups[g('채무')]))),
        { note: '금융채무와 세입자에게 돌려줄 임대보증금 등.' }) +
      rankBoard('가상자산', top(P.filter((p) => p.groups[g('가상자산')] > 0), (p) => p.groups[g('가상자산')]).map((p) => pRow(p, p.groups[g('가상자산')], short(p.groups[g('가상자산')]), p.crypto + '건'))) +
      rankBoard('고지거부한 가족 수', top(P.filter((p) => p.refused.length), (p) => p.refused.length).map((p) => pRow(p, p.refused.length, p.refused.length + '명', esc(p.refused.join(', ')))),
        { note: '독립생계 등 요건을 갖춰 허가를 받으면 부모·자녀 재산을 공개하지 않을 수 있습니다.' }) +
      '</div>';
    // 부동산이 있는 곳
    const pset = new Set(P.map((p) => p.i));
    const owned = assetItems(A).filter((r) => pset.has(r.person) && !r.lease && r.cur > 0);
    const region = q.get('region');
    const agg = (key) => {
      const m = {};
      owned.forEach((r) => { const k = key(r); if (!k) return; const a = (m[k] = m[k] || { v: 0, n: 0, ps: new Set() }); a.v += r.cur; a.n += 1; a.ps.add(r.person); });
      return Object.entries(m).map(([k, a]) => ({ k, ...a })).sort((a, b) => b.v - a.v);
    };
    const bySgg = agg((r) => (r.sido && r.sido !== '해외·기타' ? r.sido + (r.sgg ? ' ' + r.sgg : '') : r.sido));
    const bySido = agg((r) => r.sido);
    const byKind = agg((r) => r.kind.replace(/\(.*$/, ''));
    h += '<h2>의원 부동산이 있는 곳</h2><p class="ink2">소유한 토지·건물의 신고가액을 위치별로 더했습니다. 지역을 누르면 그 지역의 부동산 목록이 나옵니다.</p><div class="boards">' +
      rankBoard('시·군·구별 신고가액', bySgg.slice(0, 30).map((a) => ({ label: a.k, href: base + '&region=' + encodeURIComponent(a.k), value: a.v, show: short(a.v), sub: '의원 ' + a.ps.size + '명, ' + a.n + '건' }))) +
      '<section class="board"><h3>시·도별</h3>' + hbars(bySido.map((a) => ({ label: a.k, value: a.v }))) + '</section>' +
      '<section class="board"><h3>종류별</h3>' + hbars(byKind.slice(0, 14).map((a) => ({ label: a.k, value: a.v }))) + '</section></div>';
    if (region) {
      const rows = owned.filter((r) => (r.sido && r.sido !== '해외·기타' ? r.sido + (r.sgg ? ' ' + r.sgg : '') : r.sido) === region).sort((a, b) => b.cur - a.cur);
      h += '<h3 id="region-list">' + esc(region) + ' <small class="muted">' + rows.length + '건</small></h3>' + realestateTable(rows, true, A);
    }
    return h;
  }

  // ------------------------------------------------------------------ 나라 살림 (열린재정)
  async function pageBudget(q) {
    let F = null;
    try { F = await load('fiscal', 'data/fiscal.js'); } catch (e) { F = null; }
    if (!F) {
      return setPage('<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>나라는 어디서 돈을 얻고 어디에 쓰나</h1></div><p class="ink2">기획재정부 열린재정 자료를 정리하는 중입니다.</p>', '나라 살림');
    }
    return renderBudget(F, q);
  }
  function renderBudget(F, q) {
    const T = 1e12;
    const jo = (v) => (v == null ? '—' : (v / T).toFixed(v >= 100 * T || v <= -100 * T ? 0 : 1).replace(/\.0$/, '') + '조원');
    const actualYears = Object.keys(F.actuals.years).filter((y) => F.actuals.years[y].through_month === 12).sort();
    const year = actualYears.includes(q.get('year')) ? q.get('year') : actualYears[actualYears.length - 1];
    const A = F.actuals.years[year], D = (F.debt.years[year] || {});
    const yearTabs = actualYears.map((y) => tabLink('#/budget?year=', y, year, y)).join(' ');
    let h = '<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>나라는 어디서 돈을 얻고 어디에 쓰나</h1><p class="ink2" style="margin-top:10px">중앙정부의 한 해 살림입니다(지방자치단체 예산은 별도). 숫자는 기획재정부 열린재정 자료이며, 실제로 들어오고 나간 돈(결산·집행 실적)을 기준으로 합니다.</p></div>' +
      '<div class="ledger-tools">' + yearTabs + '</div>';
    h += '<div class="figures"><div class="figure"><div class="label">' + year + '년 총수입</div><div class="value num">' + jo(A.total_revenue) + '</div><div class="sub">세금·세외수입·기금</div></div>' +
      '<div class="figure"><div class="label">총지출</div><div class="value num">' + jo(A.total_expenditure) + '</div><div class="sub">예산 ' + jo(A.budget_expenditure) + ', 기금 ' + jo(A.fund_expenditure) + '</div></div>' +
      '<div class="figure"><div class="label">관리재정수지</div><div class="value num">' + jo(A.managed_balance) + '</div><div class="sub">사회보장성기금 수지를 뺀 살림 적자·흑자</div></div>' +
      '<div class="figure"><div class="label">연말 국가채무</div><div class="value num">' + jo(D.national_debt) + '</div><div class="sub">GDP 대비 ' + (D.gdp_ratio_pct != null ? D.gdp_ratio_pct + '%' : '—') + '</div></div></div>' +
      '<p class="small muted">모자란 돈은 국채를 발행해 빌려 채웁니다. 빌린 돈은 총수입에 들어가지 않고 국가채무 증가로 나타납니다.</p>';

    // 어디서 얻나
    const tax = (F.national_tax_by_item.years[year] || {});
    h += '<div class="two-col" style="margin-top:24px"><div><h2 style="margin-top:0">어디서 얻나</h2>' +
      hbars([['국세 (세금)', A.national_tax], ['기금수입 (연금 보험료 등)', A.fund_revenue], ['세외수입 (벌금·수수료 등)', A.non_tax]].map(([k, v]) => ({ label: k, value: v })), jo) +
      '<p class="small muted" style="margin-top:6px">' + year + '년 집행 실적. 기금수입에는 국민연금·고용보험 같은 사회보험료가 들어 있습니다.</p></div>' +
      '<div><h2 style="margin-top:0">세금은 어떤 세목에서</h2>' + (tax.items ? hbars(tax.items.slice().sort((a, b) => b.amount - a.amount).slice(0, 10).map((i) => ({ label: i.name, value: i.amount })), jo) +
        '<p class="small muted" style="margin-top:6px">국세 ' + esc(tax.basis || '') + ' 기준, 큰 세목 10개.</p>' : '<p class="ink2">자료 없음</p>') + '</div></div>';

    // 어디에 쓰나
    const sec = F.expenditure_by_sector.years[year] || F.expenditure_by_sector.years[Object.keys(F.expenditure_by_sector.years).sort().pop()];
    h += '<h2>어디에 쓰나</h2><div class="two-col"><div><h3>분야별 (' + esc(year) + '년 ' + esc(sec.basis || '') + ')</h3>' +
      hbars(sec.items.slice().sort((a, b) => b.amount - a.amount).map((i) => ({ label: i.name, value: i.amount })), jo) + '</div>';
    const M = F.expenditure_by_ministry;
    h += '<div><h3>부처별 (' + esc(M.year) + '년 ' + esc(M.basis.split(',')[0]) + ')</h3>' +
      hbars(M.items.slice(0, 12).map((i) => ({ label: i.name, value: i.amount })), jo) +
      '<p class="small muted" style="margin-top:6px">부처를 펼치면 큰 사업 10개가 나옵니다.' + (M.proposal ? ' ' + esc(M.proposal.year) + '년 정부안(' + esc(M.proposal.basis) + ') 총액은 ' + jo(M.proposal.items.reduce((a, i) => a + i.amount, 0)) + '입니다.' : '') + '</p>' +
      M.items.slice(0, 12).map((i) => '<details class="table-view"><summary>' + esc(i.name) + ' ' + jo(i.amount) + '</summary>' +
        hbars((i.top_programs || []).map((p) => ({ label: p.name, value: p.amount })), jo) + '</details>').join('') + '</div></div>';

    // 추이
    const ys = actualYears;
    h += '<h2>해마다 얼마나 들어오고 나갔나</h2>' + lineChart(ys, [
      { name: '총수입', cls: 's1', values: ys.map((y) => F.actuals.years[y].total_revenue) },
      { name: '총지출', cls: 's2', values: ys.map((y) => F.actuals.years[y].total_expenditure) },
    ], jo, '연도별 총수입과 총지출');
    const dys = Object.keys(F.debt.years).filter((y) => y >= ys[0]).sort();
    h += '<h2>나라 빚</h2>' + barChart(dys.map((y) => ({ key: y, label: y.slice(2), value: F.debt.years[y].national_debt })), '연말 국가채무') +
      '<p class="small muted">국가채무(D1) 연말 기준. GDP 대비 비율: ' + dys.slice(-4).map((y) => y + '년 ' + F.debt.years[y].gdp_ratio_pct + '%').join(', ') + '.</p>';
    h += '<div class="callout"><h3>읽을 때 주의할 점</h3><ul>' + F.notes.map((n) => '<li>' + esc(n) + '</li>').join('') + '</ul><p class="small muted">출처: <a href="' + esc(F.source.url) + '" target="_blank" rel="noopener">' + esc(F.source.name) + '</a> Open API, ' + esc((F.source.fetched_at || '').slice(0, 10)) + ' 수집. ' + esc(F.units_note) + '</p></div>';
    setPage(h, '나라 살림');
    wireCharts(main());
    wireLines(main());
  }

  function lineChart(xs, series, fmt, label) {
    const W = chartW(680), H = 240, L = 58, R = 64, T = 14, B = 28;
    const all = series.flatMap((s) => s.values).filter((v) => v != null);
    const max = niceMax(Math.max(...all)), min = 0;
    const x = (i) => L + (W - L - R) * (xs.length === 1 ? 0.5 : i / (xs.length - 1));
    const y = (v) => T + (H - T - B) * (1 - (v - min) / (max - min));
    let g = '<g class="grid">' + [0, 0.25, 0.5, 0.75, 1].map((f) => '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(f * max) + '" y2="' + y(f * max) + '"/>').join('') + '</g><g class="axis">' +
      [0, 0.25, 0.5, 0.75, 1].map((f) => '<text x="' + (L - 8) + '" y="' + (y(f * max) + 4) + '" text-anchor="end">' + esc(fmt(f * max).replace('조원', '조')) + '</text>').join('') +
      xs.map((v, i) => (i % Math.ceil(xs.length / (W >= 600 ? 12 : 6)) === 0 ? '<text x="' + x(i) + '" y="' + (H - 9) + '" text-anchor="middle">' + esc(String(v).slice(2)) + '</text>' : '')).join('') + '</g>';
    const ends = [];
    series.forEach((s) => {
      const pts = s.values.map((v, i) => (v == null ? null : [x(i), y(v)])).filter(Boolean);
      g += '<path class="line ' + s.cls + '" d="M' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('L') + '"/>';
      const last = pts[pts.length - 1];
      g += '<circle class="end ' + s.cls + '" cx="' + last[0] + '" cy="' + last[1] + '" r="4"/>';
      ends.push({ x: last[0], y: last[1] + 4, name: s.name });
    });
    // 끝 라벨이 가까우면 위아래로 벌린다
    ends.sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
    ends.forEach((e) => (g += '<text class="end-label" x="' + (e.x + 8) + '" y="' + e.y + '">' + esc(e.name) + '</text>'));
    xs.forEach((v, i) => (g += '<rect class="hit" x="' + (x(i) - (W - L - R) / xs.length / 2) + '" y="' + T + '" width="' + (W - L - R) / xs.length + '" height="' + (H - T - B) + '" data-tip="' + esc(v + '년 ' + series.map((s) => s.name + ' ' + fmt(s.values[i])).join(', ')) + '" data-cx="' + x(i) + '" data-cy="' + y(Math.max(...series.map((s) => s.values[i] || 0))) + '"/>'));
    return '<div class="chart line-chart" data-w="' + W + '"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(label) + '">' + g + '</svg><div class="tooltip" role="status"></div></div>' +
      '<p class="map-legend">' + series.map((s) => '<span class="key-line ' + s.cls + '"></span> ' + esc(s.name)).join(' ') + '</p>' +
      '<details class="table-view"><summary>표로 보기</summary><div class="table-wrap"><table><thead><tr><th>연도</th>' + series.map((s) => '<th class="r">' + esc(s.name) + '</th>').join('') + '</tr></thead><tbody>' +
      xs.map((v, i) => '<tr><td>' + esc(v) + '</td>' + series.map((s) => '<td class="r num">' + fmt(s.values[i]) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div></details>';
  }
  function wireLines(root) {
    root.querySelectorAll('.chart.line-chart').forEach((c) => {
      const tip = c.querySelector('.tooltip'), svg = c.querySelector('svg'), W = +c.dataset.w;
      c.addEventListener('mousemove', (ev) => {
        const t = ev.target.closest('.hit');
        if (!t) { tip.classList.remove('on'); return; }
        const sc = svg.getBoundingClientRect().width / W;
        tip.textContent = t.dataset.tip;
        tip.style.left = 14 + +t.dataset.cx * sc + 'px';
        tip.style.top = 14 + +t.dataset.cy * sc + 'px';
        tip.classList.add('on');
      });
      c.addEventListener('mouseleave', () => tip.classList.remove('on'));
    });
  }

  // ------------------------------------------------------------------ 우리 동네 (지도)
  const loadGeo = () => load('geo', 'data/geo.js');
  const SEOUL_GU = ['종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구', '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구',
    '강서구', '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구'];
  function guTokens(districtName) {
    // '서울 중구성동구갑' → ['중구', '성동구'] (가장 긴 구 이름부터 맞춘다)
    let rest = districtName.replace(/^서울\s*/, '').replace(/[갑을병정무]$/, '');
    const out = [];
    const names = SEOUL_GU.slice().sort((a, b) => b.length - a.length);
    while (rest) {
      const n = names.find((g) => rest.startsWith(g));
      if (!n) break;
      out.push(n);
      rest = rest.slice(n.length);
    }
    return out;
  }
  function legislatorsFor(district, term) {
    return META.subjects.filter((s) => s.type === 'LEGISLATOR' && s.districts && s.districts[term] === district);
  }
  async function legislatorCard(s) {
    const sh = await loadSubject(s.id);
    const tx = txObjects(sh);
    const cats = {};
    tx.forEach((t) => (cats[t.category] = (cats[t.category] || 0) + t.amount));
    // 날짜가 아니라 회계보고 단위로 묶는다 (예비후보 기간 회계에는 전년도 12월 날짜가 섞여 있다)
    const docLabel = { 'ka:2023': '2023년 회계 (제21대 현직)', 'ka:2024-21': s.precandidate ? '2024년 1~5월 회계 (제22대 총선 예비후보 기간)' : '2024년 1~5월 회계 (제21대)',
      'ka:2024-22': '2024년 6~12월 회계 (제22대)' };
    const top = Object.entries(cats).sort((a, b) => b[1] - a[1]).slice(0, 4);
    const fr = {};
    sh.findings.forEach((f) => (fr[f.ruleId] = (fr[f.ruleId] || 0) + 1));
    const asm = s.assembly;
    const asmLine = asm ? '<p class="small ink2" style="margin-top:6px">' + (asm.committees ? '위원회: ' + esc(asm.committees) + '. ' : '') +
      ['22', '21'].filter((age) => asm.bills && asm.bills[age]).map((age) => '제' + age + '대 대표발의 ' + nf.format(asm.bills[age].lead) + '건 (' + billResultsText(asm.bills[age].results) + ')' +
        (asm.votes && asm.votes[age] ? ', 본회의 표결 참여 ' + pct(asm.votes[age].participation) : '')).join('. ') + '</p>' : '';
    return '<div class="rep-card"><h4><a href="' + href('s', s.id) + '">' + esc(s.name) + ' 의원</a> <small class="muted">' + esc(s.party || '') + (asm && asm.reelection ? ', ' + esc(asm.reelection) : '') + '</small></h4>' + asmLine +
      '<dl class="kv">' + Object.keys(docLabel).filter((k) => (s.docTotals || {})[k]).map((k) => '<dt>' + esc(docLabel[k]) + '</dt><dd class="num">' + won(s.docTotals[k].amount) + '</dd>').join('') + '</dl>' +
      '<p class="small ink2" style="margin-top:8px">많이 쓴 분류: ' + top.map(([c, v]) => esc(c) + ' ' + short(v)).join(', ') + '</p>' +
      '<p class="small">' + (sh.findings.length ? '표시된 패턴 ' + sh.findings.length + '건 (' + Object.entries(fr).map(([r, n]) => esc(ruleOf(r).name) + ' ' + n).slice(0, 4).join(', ') + ') ' : '표시된 패턴 없음. ') +
      '<a href="' + href('s', s.id) + '">지출 기록 전체 보기</a></p></div>';
  }
  function councilCard(c) {
    const st = META.sourceStats[c.id];
    if (!st) return '';
    const subs = META.subjects.filter((x) => x.source === c.id);
    const nf_ = subs.reduce((a, x) => a + (x.findings || 0), 0);
    const chair = subs.filter((x) => x.role === '의장' && x.holders).sort((a, b) => (b.termStart || '').localeCompare(a.termStart || ''))[0];
    return '<div class="rep-card"><h4><a href="#/council/' + esc(c.id) + '">' + esc(c.name) + '</a></h4><dl class="kv"><dt>자료 기간</dt><dd class="num">' + esc(st.first) + ' ~ ' + esc(st.last) + '</dd>' +
      Object.entries(st.byFunding).sort((a, b) => b[1].amount - a[1].amount).slice(0, 3).map(([k, v]) => '<dt>' + esc(fundingLabel(k)) + '</dt><dd class="num">' + short(v.amount) + ' <small class="muted">' + nf.format(v.count) + '건</small></dd>').join('') +
      (chair ? '<dt>의장 (' + esc(chair.term) + ')</dt><dd>' + chair.holders.map((n) => '<a href="' + personHref(c.id, n) + '">' + esc(n) + '</a>').join(', ') + '</dd>' : '') +
      '</dl><p class="small" style="margin-top:8px">표시된 패턴 ' + nf.format(nf_) + '건. 의장·위원장 등 직책과 위원회 단위로만 공개되어 의원 개인별 지출은 알 수 없습니다.</p></div>';
  }
  const RAMP = 5;
  function quantileBins(values) {
    const v = values.filter((x) => x > 0).sort((a, b) => a - b);
    if (!v.length) return [];
    return Array.from({ length: RAMP - 1 }, (_, i) => v[Math.floor((v.length * (i + 1)) / RAMP)]);
  }

  async function pageRegion(q) {
    const geo = await loadGeo();
    const view = q.get('view') === 'seoul' ? 'seoul' : 'assembly';
    const metric = q.get('metric') || '';
    let sel = q.get('sel') || '';
    const councilByGu = {};
    (META.councils || []).forEach((c) => { if (c.region && c.region.startsWith('서울 ')) councilByGu[c.region.split(' ')[1]] = c; });
    const districts = geo.districts.filter((d) => d.matched);
    const allSeoul = SEOUL_GU.every((g) => councilByGu[g]);
    const groupOf = (d) => d.short.split(' ')[0];
    const groups = [...new Set(districts.map(groupOf))];
    const amountOf = (name) => legislatorsFor(name, '제22대').reduce((a, s) => a + (((s.docTotals || {})['ka:2024-22'] || {}).amount || 0), 0);
    const bins = metric ? quantileBins(districts.map((d) => amountOf(d.name))) : [];
    const binOf = (v) => { let i = 0; while (i < bins.length && v >= bins[i]) i++; return i; };

    let svg = '';
    if (view === 'assembly') {
      svg = '<svg class="map" viewBox="' + geo.projection.national.viewBox + '" role="group" aria-label="제22대 국회의원 지역구 지도">' +
        districts.map((d) => '<path class="area' + (metric ? ' q' + binOf(amountOf(d.name)) : '') + '" data-key="' + esc(d.name) + '" data-group="' + esc(groupOf(d)) + '" d="' + d.d + '"><title>' + esc(d.name) + '</title></path>').join('') +
        geo.sido.map((x) => '<path class="sido-line" d="' + x.d + '"/>').join('') + '</svg>';
    } else {
      svg = '<svg class="map" viewBox="' + geo.projection.seoul.viewBox + '" role="group" aria-label="서울 자치구 지도">' +
        geo.seoul.map((g) => '<path class="area' + (councilByGu[g.sgg] && !allSeoul ? ' has' : '') + '" data-key="' + esc(g.sgg) + '" d="' + g.d + '"><title>' + esc(g.sgg) + '</title></path>').join('') +
        geo.seoul.map((g) => '<text class="map-label" x="' + g.cx + '" y="' + g.cy + '">' + esc(g.sgg.replace(/구$/, '')) + '</text>').join('') + '</svg>';
    }
    const legend = view === 'seoul'
      ? (allSeoul ? '<p class="map-legend">서울 25개 구의회 업무추진비를 모두 수집했습니다. 구를 누르세요.</p>' : '<p class="map-legend"><span class="swatch has"></span> 구의회 업무추진비 수집 <span class="swatch"></span> 아직 수집 안 함</p>')
      : metric
        ? '<p class="map-legend">제22대 회계(2024.5.30~12.31) 정치자금 지출, 5등분: ' + ['', ...bins].map((b, i) => '<span class="swatch q' + i + '"></span> ' + (i === 0 ? short(bins[0] || 0) + ' 미만' : short(b) + ' 이상')).join(' ') +
          '<br><small class="muted">지출이 많다고 문제가 있다는 뜻은 아닙니다. 지역구 크기·사무소 수·활동 방식에 따라 다릅니다.</small></p>'
        : '';
    const groupOpts = '<option value="">시·도 선택</option>' + groups.map((g) => '<option>' + esc(g) + '</option>').join('');
    const pickers = view === 'assembly'
      ? '<label class="skip" for="pick-g">시·도</label><select id="pick-g">' + groupOpts + '</select> <label class="skip" for="pick-d">지역구</label><select id="pick-d"><option value="">지역구 선택</option></select>'
      : '<label class="skip" for="pick-d">자치구</label><select id="pick-d"><option value="">자치구 선택</option>' + SEOUL_GU.map((g) => '<option>' + esc(g) + '</option>').join('') + '</select>';
    const tab = (v, label) => '<a class="tag' + (view === v ? ' solid' : '') + '" href="#/region?view=' + v + '">' + label + '</a>';
    setPage('<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>우리 동네 대표들의 지출</h1><p class="ink2" style="margin-top:10px">지도에서 지역을 누르거나 목록에서 고르면, 그 지역을 대표하는 국회의원의 정치자금과 지방의회 업무추진비 기록을 볼 수 있습니다. 지출이 많고 적음만으로 일을 잘하는지 판단할 수는 없습니다. 무엇에 썼는지, 표시된 패턴이 있는지를 함께 보세요.</p></div>' +
      '<div class="ledger-tools">' + tab('assembly', '국회의원 지역구 (제22대)') + ' ' + tab('seoul', '서울 자치구') + (view === 'assembly' ? ' <a class="tag' + (metric ? ' solid' : '') + '" href="#/region?view=assembly&metric=' + (metric ? '' : 'spend') + (sel ? '&sel=' + encodeURIComponent(sel) : '') + '">' + (metric ? '지출액 색칠 끄기' : '지출액으로 색칠') + '</a>' : '') + '</div>' +
      '<div class="region"><div class="map-col"><div class="ledger-tools">' + pickers + ' <button class="plain" type="button" id="map-reset">전체 보기</button></div><div class="map-box">' + svg + '<div class="tooltip" role="status"></div></div>' + legend +
      (view === 'assembly' ? '<p class="small muted">비례대표 의원은 지역구가 없어 지도에 나오지 않습니다. <a href="#/assembly">국회의원 전체 목록</a></p>' : '') +
      '<p class="small muted">지도: 통계청 SGIS 행정동 경계(공공누리 제1유형)를 vuski/admdongkor가 가공한 자료(CC BY 4.0), 선거구: 오마이뉴스(MIT). 행정구역 2026-10-01 기준.</p></div>' +
      '<aside class="panel" id="panel" aria-live="polite"><p class="ink2">' + (view === 'assembly' ? '지역구를 고르세요.' : '자치구를 고르세요.') + '</p></aside></div>', '우리 동네');

    const svgEl = main().querySelector('svg.map');
    const full = svgEl.getAttribute('viewBox');
    const tip = main().querySelector('.map-box .tooltip');
    function zoomTo(paths) {
      if (!paths.length) { svgEl.setAttribute('viewBox', full); return; }
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      paths.forEach((p) => { const b = p.getBBox(); x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.width); y1 = Math.max(y1, b.y + b.height); });
      const pad = Math.max(x1 - x0, y1 - y0) * 0.08;
      svgEl.setAttribute('viewBox', [x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad].map((v) => v.toFixed(1)).join(' '));
    }
    const fillDistricts = (g) => {
      const pd = document.getElementById('pick-d');
      if (view !== 'assembly') return;
      pd.innerHTML = '<option value="">지역구 선택</option>' + districts.filter((d) => groupOf(d) === g).map((d) => '<option' + (d.name === sel ? ' selected' : '') + '>' + esc(d.name) + '</option>').join('');
    };
    async function select(key, zoom) {
      sel = key;
      svgEl.querySelectorAll('.area.sel').forEach((p) => p.classList.remove('sel'));
      const path = [...svgEl.querySelectorAll('.area')].find((p) => p.dataset.key === key);
      if (path) path.classList.add('sel');
      history.replaceState(null, '', '#/region?view=' + view + (metric ? '&metric=' + metric : '') + '&sel=' + encodeURIComponent(key));
      const panel = document.getElementById('panel');
      panel.innerHTML = '<p class="loading">불러오는 중…</p>';
      let h = '';
      if (view === 'assembly') {
        const g = path ? path.dataset.group : '';
        if (zoom && g) zoomTo([...svgEl.querySelectorAll('.area')].filter((p) => p.dataset.group === g));
        document.getElementById('pick-g').value = g;
        fillDistricts(g);
        const now = legislatorsFor(key, '제22대'), before = legislatorsFor(key, '제21대').filter((s) => !now.includes(s));
        h = '<h2 class="panel-title">' + esc(key) + '</h2><h3>제22대 국회의원</h3>' + ((await Promise.all(now.map(legislatorCard))).join('') || '<p class="ink2">자료에 이 지역구 의원이 없습니다.</p>');
        if (before.length) h += '<h3>같은 이름 선거구의 제21대 의원</h3>' + (await Promise.all(before.map(legislatorCard))).join('');
        const gus = g === '서울' ? guTokens(key) : [];
        const cs = gus.map((gu) => councilByGu[gu]).filter(Boolean);
        h += '<h3>지방의회</h3>' + (cs.map(councilCard).join('') || '<p class="ink2">' + (g === '서울' ? '이 지역 구의회 자료는 아직 수집하지 않았습니다.' : '서울 밖 지방의회 자료는 아직 수집하지 않았습니다.') + '</p>') +
          (g === '서울' ? councilCard((META.councils || []).find((c) => c.id === 'seoul') || {}) : '');
      } else {
        document.getElementById('pick-d').value = key;
        const ds = districts.filter((d) => groupOf(d) === '서울' && guTokens(d.name).includes(key));
        const reps = ds.flatMap((d) => legislatorsFor(d.name, '제22대'));
        h = '<h2 class="panel-title">서울 ' + esc(key) + '</h2><h3>구의회</h3>' + (councilByGu[key] ? councilCard(councilByGu[key]) : '<p class="ink2">' + esc(key) + '의회 업무추진비는 아직 수집하지 않았습니다.</p>') +
          '<h3>서울특별시의회</h3>' + councilCard((META.councils || []).find((c) => c.id === 'seoul') || {}) +
          '<h3>국회의원 (제22대, ' + ds.map((d) => esc(d.name.replace(/^서울\s*/, ''))).join(', ') + ')</h3>' + ((await Promise.all(reps.map(legislatorCard))).join('') || '<p class="ink2">해당 지역구 의원 자료가 없습니다.</p>');
      }
      if (sel === key) panel.innerHTML = h;
    }
    svgEl.addEventListener('click', (e) => { const p = e.target.closest('.area'); if (p) select(p.dataset.key, true); });
    svgEl.addEventListener('mousemove', (e) => {
      const p = e.target.closest('.area');
      if (!p) { tip.classList.remove('on'); return; }
      const box = main().querySelector('.map-box').getBoundingClientRect();
      let label = p.dataset.key;
      if (view === 'assembly') { const ls = legislatorsFor(p.dataset.key, '제22대'); if (ls.length) label += ', ' + ls.map((s) => s.name).join(', '); }
      tip.textContent = label;
      tip.style.left = e.clientX - box.left + 'px';
      tip.style.top = e.clientY - box.top - 8 + 'px';
      tip.classList.add('on');
    });
    svgEl.addEventListener('mouseleave', () => tip.classList.remove('on'));
    document.getElementById('map-reset').addEventListener('click', () => { svgEl.setAttribute('viewBox', full); });
    if (view === 'assembly') {
      document.getElementById('pick-g').addEventListener('change', (e) => { fillDistricts(e.target.value); zoomTo([...svgEl.querySelectorAll('.area')].filter((p) => p.dataset.group === e.target.value)); });
    }
    document.getElementById('pick-d').addEventListener('change', (e) => { if (e.target.value) select(e.target.value, true); });
    if (sel) select(sel, true);
  }

  // ------------------------------------------------------------------ 지방의회 목록
  function pageCouncils() {
    const cs = (META.councils || []).slice().sort((a, b) => (a.level === '광역' ? -1 : 0) - (b.level === '광역' ? -1 : 0) || a.name.localeCompare(b.name, 'ko'));
    const rows = cs.map((c) => {
      const st = META.sourceStats[c.id] || {};
      const subs = META.subjects.filter((x) => x.source === c.id);
      return '<tr><td><a href="#/council/' + esc(c.id) + '">' + esc(c.name) + '</a></td><td><small>' + esc(c.level || '') + '</small></td><td class="num"><small>' + esc(st.first || '') + ' ~ ' + esc(st.last || '') + '</small></td>' +
        '<td class="r num">' + nf.format(st.count || 0) + '</td><td class="r num">' + nf.format(subs.reduce((a, x) => a + (x.findings || 0), 0)) + '</td><td><small><a href="' + esc(c.board || '#') + '" target="_blank" rel="noopener">게시판</a></small></td></tr>';
    }).join('');
    const missing = 25 - cs.filter((c) => c.level !== '광역').length;
    setPage('<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>지방의회</h1><p class="ink2" style="margin-top:10px">의회 홈페이지에 공개된 업무추진비·의정운영공통경비입니다. 서울 25개 구의회 중 ' + (25 - missing) + '곳을 수집했습니다. <a href="#/region?view=seoul">지도로 보기</a></p></div>' +
      '<div class="table-wrap"><table class="list-table"><thead><tr><th>의회</th><th>구분</th><th>자료 기간</th><th class="r">거래</th><th class="r">표시</th><th>원본</th></tr></thead><tbody>' + rows + '</tbody></table></div>', '지방의회');
  }

  // ------------------------------------------------------------------ rules
  function pageRules() {
    const groups = { A: '식대와 업무추진비', B: '소비·지출 패턴', C: '정치자금 고유 항목', E: '정보 투명성·데이터 품질' };
    let h = '<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>탐지 규칙</h1><p class="ink2" style="margin-top:10px">규칙은 지출 주체가 아니라 거래 단위의 패턴을 찾습니다. 각 규칙은 기준의 성격을 구분합니다.</p>' +
      '<dl class="kv" style="margin-top:12px"><dt>' + tag('법령 기준 대조', 'reg') + '</dt><dd>훈령·법률에 적힌 기준과 비교합니다. 예외(사유 기재 등)가 허용되는 기준이면 "확인 필요"로만 표시합니다.</dd>' +
      '<dt>' + tag('통계 기준') + '</dt><dd>같은 재원·비교집단의 분포와 비교합니다. 법적 허용 금액이 아닙니다. 표본이 작으면 비교하지 않습니다.</dd>' +
      '<dt>' + tag('같은 값 반복') + '</dt><dd>같은 날짜·금액·거래처가 반복되는 사실 자체를 보여줍니다.</dd><dt>' + tag('단어 일치') + '</dt><dd>상호·내역의 단어가 일치한 것으로, 업종이나 목적을 확정하지 않습니다.</dd>' +
      '<dt>' + tag('공개자료 점검', 'dq') + '</dt><dd>공개 자료 자체의 누락·오기·중복을 보여줍니다.</dd></dl></div>';
    Object.entries(groups).forEach(([g, label]) => {
      const rs = META.rules.filter((r) => r.group === g);
      h += '<h2>' + esc(label) + '</h2><ul class="rule-list">' + rs.map((r) => '<li><span class="code">' + esc(r.code) + '</span><div><a href="' + href('rules', r.id) + '">' + esc(r.name) + '</a> ' + refTag(r.reference_type) +
        '<p>' + esc(r.purpose) + ' <span class="muted">적용: ' + esc(r.applies_to.join(', ')) + '</span></p></div><span class="count">' + nf.format(r.count) + '건</span></li>').join('') + '</ul>';
    });
    h += '<h2>아직 구현하지 못한 규칙</h2><ul class="rule-list">' + META.notImplemented.map((r) => '<li><span class="code">' + esc(r.code) + '</span><div>' + esc(r.name) + '<p>' + esc(r.reason) + '</p></div><span></span></li>').join('') + '</ul>';
    setPage(h, '탐지 규칙');
  }

  async function pageRule(rid, q) {
    const r = ruleOf(rid);
    if (!r) return setPage('<p class="err">없는 규칙입니다.</p>');
    const idx = await loadFindingsIndex();
    const src = q.get('src') || '';
    const list = idx.filter((f) => f.ruleId === rid && (!src || f.sourceId === src));
    const sort = q.get('sort') || 'period';
    list.sort(sort === 'metric' ? (a, b) => (b.metric || 0) - (a.metric || 0) : (a, b) => ((b.period || {}).start || '').localeCompare((a.period || {}).start || ''));
    const srcs = [...new Set(idx.filter((f) => f.ruleId === rid).map((f) => f.sourceId))];
    const li = (label, items) => '<h3 style="margin-top:18px">' + esc(label) + '</h3><ul>' + items.map((x) => '<li>' + esc(x) + '</li>').join('') + '</ul>';
    let h = '<div class="crumbs"><a href="#/">처음</a> / <a href="#/rules">탐지 규칙</a></div><div class="page-head"><h1><span class="muted">' + esc(r.code) + '</span> ' + esc(r.name) + '</h1><div class="facts"><span>' + refTag(r.reference_type) + '</span><span>적용 <b>' + esc(r.applies_to.join(', ')) + '</b></span><span>구현 난이도 <b>' + esc(r.difficulty) + '</b></span><span>현재 공개 데이터로 구현 <b>' + (r.mvp ? '가능' : '불가') + '</b></span></div></div>' +
      '<div class="two-col"><div><h3>탐지 목적</h3><p>' + esc(r.purpose) + '</p><h3 style="margin-top:18px">계산 방법</h3><p>' + esc(r.method) + '</p><h3 style="margin-top:18px">기준값</h3><p>' + esc(r.thresholds) + '</p>' +
      '<h3 style="margin-top:18px">필요한 데이터 필드</h3><p>' + esc(r.fields.join(', ')) + '</p><h3 style="margin-top:18px">자료가 부족할 때</h3><p>' + esc(r.missing_data) + '</p></div>' +
      '<div>' + li('정상적인 사례', r.normal_cases) + li('데이터 오류로 인한 오탐 가능성', r.false_positive_risks) + li('실제 확인에 필요한 자료', r.verification) + '</div></div>' +
      '<h2>적용 규정</h2>' + legalBlock(r.legal_refs);
    h += '<h2>탐지 결과 <small class="muted">' + nf.format(list.length) + '</small></h2><div class="ledger-tools"><span class="small">출처</span>' +
      ['', ...srcs].map((x) => '<a class="tag' + (x === src ? ' solid' : '') + '" href="' + href('rules', rid) + '?src=' + encodeURIComponent(x) + '&sort=' + sort + '">' + esc(x ? SOURCE_NAME[x] : '전체') + '</a>').join(' ') +
      '<span class="small" style="margin-left:12px">정렬</span><a class="tag' + (sort === 'period' ? ' solid' : '') + '" href="' + href('rules', rid) + '?src=' + encodeURIComponent(src) + '&sort=period">기간 최근 순</a> <a class="tag' + (sort === 'metric' ? ' solid' : '') + '" href="' + href('rules', rid) + '?src=' + encodeURIComponent(src) + '&sort=metric">계산값 큰 순</a></div>' +
      (list.length ? list.slice(0, 400).map((f) => '<div class="finding-item ' + (f.reviewStatus === 'DATA_QUALITY' ? 'dq' : f.reviewStatus === 'INFO' ? 'info' : '') + '"><p>' + esc(f.explanation) + '</p><div class="meta"><span>' + esc(SOURCE_NAME[f.sourceId]) + '</span>' +
        (f.period && f.period.label ? '<span>' + esc(f.period.label) + '</span>' : '') + '<span>근거 ' + nf.format(f.evidenceCount) + '건</span><a href="' + href('f', f.subjectId, f.id) + '">근거와 계산 보기</a></div></div>').join('') +
        (list.length > 400 ? '<p class="muted">처음 400건만 표시했습니다. 출처를 골라 좁혀 보세요.</p>' : '') : '<p class="ink2">이 규칙에 걸린 결과가 없습니다.</p>');
    setPage(h, r.name);
  }

  // ------------------------------------------------------------------ sources
  function pageSources() {
    const col = META.collection;
    let h = '<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>데이터 출처와 수집 현황</h1><p class="ink2" style="margin-top:10px">실제로 내려받아 검증한 자료와, 존재를 확인했지만 아직 수집하지 않은 자료를 구분합니다. 자료가 존재한다는 것과 자동 수집이 가능하다는 것은 다른 문제입니다.</p></div>';
    h += '<h2>이 사이트가 쓰는 자료</h2><div class="table-wrap"><table><thead><tr><th>자료</th><th>수집 결과</th><th>수집 시점</th></tr></thead><tbody>' +
      (META.assemblySummary ? '<tr><td><b>열린국회정보 Open API</b><br><small class="muted">국회사무처</small></td><td><small>현직 의원 ' + META.assemblySummary.members_current + '명(정치자금 자료와 ' + META.assemblySummary.members_matched + '명 연결), 대표발의 법률안 제21대 ' + nf.format(META.assemblySummary.bills['21']) + '건·제22대 ' + nf.format(META.assemblySummary.bills['22']) + '건. 생년월일·연락처·보좌진·약력 필드는 수집하지 않습니다. 인증키는 SOPS(GCP KMS)로 암호화해 보관합니다.</small></td><td class="num"><small>' + esc(META.assemblySummary.fetched_at || '') + '</small></td></tr>' : '') +
      '<tr><td><b>KA-money 2024</b><br><small class="muted">오마이뉴스·경향신문·뉴스타파, MIT 라이선스</small></td><td><small>' + col['ka-money'].files.map((f) => '<a href="' + esc(f.url) + '" target="_blank" rel="noopener">' + esc(f.name) + '</a>').join('<br>') + '</small><br><small class="muted">원본 엑셀은 수정하지 않고 보관(sha256 기록). 지출 ' + nf.format(META.sourceStats['ka-money'].count) + '건.</small></td><td class="num"><small>' + esc((col['ka-money'].files[0] || {}).fetched_at || '') + '</small></td></tr>' +
      Object.keys(col).filter((s) => s !== 'ka-money').sort((a, b) => (a === 'seoul' ? -1 : b === 'seoul' ? 1 : (SOURCE_NAME[a] || a).localeCompare(SOURCE_NAME[b] || b, 'ko'))).map((s) => '<tr><td><b>' + esc(SOURCE_NAME[s]) + ' 업무추진비 게시판</b></td><td><small>게시글 ' + col[s].posts + '개, 첨부 ' + col[s].attachments + '개. ' +
        Object.entries(col[s].status).map(([k, v]) => ({ parsed: '파싱 ', skipped: '제외 ', unparsed: '파싱 실패 ' }[k] || k + ' ') + v).join(', ') + '. 거래 ' + nf.format(META.sourceStats[s].count) + '건.</small>' +
        (col[s].issues.length ? '<details class="table-view"><summary>제외·실패한 파일 ' + col[s].issues.length + '개</summary><ul>' + col[s].issues.map((i) => '<li><small>' + esc(i.period || '') + ' ' + esc(i.file || '') + ' — ' + esc(i.reason || i.status) + '</small></li>').join('') + '</ul></details>' : '') +
        (col[s].ocr ? '<br><small>스캔 PDF ' + col[s].ocr.files + '개 중 ' + col[s].ocr.parsed + '개를 OCR로 읽어 ' + nf.format(col[s].ocr.rows) + '행 추가' +
          (col[s].ocr.totalChecked ? ' (인쇄된 합계와 비교한 ' + col[s].ocr.totalChecked + '개 중 ' + col[s].ocr.totalMatched + '개 일치)' : '') + '</small>' : '') +
        '</td><td class="num"><small>' + esc(col[s].fetchedAt || '') + '</small></td></tr>').join('') + '</tbody></table></div>';
    h += '<h2>국회의원과 지방의회 자료의 차이</h2><div class="table-wrap"><table><thead><tr><th></th><th>국회의원 정치자금</th><th>지방의회 업무추진비·공통경비</th></tr></thead><tbody>' +
      [['재원', '후원회 기부금, 본인 자산, 정당 지원금 등 (세금 아닌 재원 포함)', '지방자치단체 예산 (세금)'],
        ['공개 방식', '선관위 열람·사본교부 (온라인 상시 공개 아님). 언론사가 정보공개청구 후 OCR로 데이터화', '의회 홈페이지 게시판에 월별 엑셀·PDF'],
        ['귀속', '의원 개인 명의 정치자금 회계 (실제 사용자는 알 수 없음)', '직책·위원회·부서 단위 (성명 없음)'],
        ['시간·인원', '없음 (날짜만)', '결제 시각·대상 인원 공개 (일부 누락)'],
        ['거래처 식별', '사업자번호·주소·업종 (OCR 정제 수준 낮음)', '상호명 (서울시의회·관악구는 주소 포함, 마포구는 상호만, 일부 ○로 가림)'],
        ['적용 기준', '정치자금법 (사적 경비 금지 등). 1인당 식대 같은 금액 기준 없음', '회계관리 훈령 (1인당 식사비, 사용 제한 시간·요일·업종, 현금 사용 제한)']]
        .map((r) => '<tr><th>' + esc(r[0]) + '</th><td>' + esc(r[1]) + '</td><td>' + esc(r[2]) + '</td></tr>').join('') + '</tbody></table></div>';
    const statusTag = (s) => tag(s, s === '다운로드 검증' ? 'reg' : s === '미확인' ? 'dq' : '');
    h += '<h2>조사한 데이터 소스</h2><p class="small muted">확인일 기준. "다운로드 검증"은 실제 파일을 받아 열어본 것, "접근 확인"은 페이지·명세만 확인한 것입니다.</p><div class="table-wrap"><table><thead><tr><th>데이터</th><th>제공기관</th><th>대상</th><th>수집 방식</th><th>개인별 귀속</th><th>상태</th><th>난이도</th><th>분석 가치</th></tr></thead><tbody>' +
      META.sources.map((d) => '<tr><td><a href="' + esc(d.url) + '" target="_blank" rel="noopener">' + esc(d.name) + '</a><br><small class="muted">' + esc(d.period || '') + ', ' + esc(d.update_cycle || '') + '</small>' +
        '<details class="table-view"><summary>필드·이용 조건</summary><small>' + esc((d.key_fields || []).join(', ')) + '<br>' + esc(d.terms || '') + '<br>' + esc(d.notes || '') + '</small></details></td><td><small>' + esc(d.provider) + '</small></td><td><small>' + esc(d.target) + '</small></td><td><small>' + esc(d.access_method) + '</small></td>' +
        '<td><small>' + esc(d.person_attribution) + '</small></td><td>' + statusTag(d.status) + '<br><small class="muted">' + esc(d.checked_at) + '</small></td><td><small>' + esc(d.difficulty) + '</small></td><td><small>' + esc(d.analysis_value) + '</small></td></tr>').join('') + '</tbody></table></div>';
    if ((META.expansion || []).length) {
      h += '<h2>다음에 수집할 후보</h2><p class="small muted">공개 여부와 접근 방법을 실제로 확인한 결과입니다. 우선순위가 높은 순서입니다.</p><div class="table-wrap"><table><thead><tr><th>자료</th><th>접근</th><th>상태</th><th>노력</th><th>쓸모</th></tr></thead><tbody>' +
        META.expansion.map((d) => '<tr><td><a href="' + esc(d.url) + '" target="_blank" rel="noopener">' + esc(d.name) + '</a><br><small class="muted">' + esc(d.provider || '') + (d.period ? ', ' + esc(d.period) : '') + '</small>' +
          (d.notes ? '<details class="table-view"><summary>메모</summary><small>' + esc(d.notes) + '</small></details>' : '') + '</td><td><small>' + esc(d.access || '') + '<br>' + esc(d.format || '') + '</small></td><td>' + statusTag(d.verified || '미확인') + '</td><td><small>' + esc(d.effort || '') + '</small></td><td><small>' + esc(d.value_for_users || '') + '</small></td></tr>').join('') +
        '</tbody></table></div>';
    }
    setPage(h, '데이터 출처');
  }

  // ------------------------------------------------------------------ guide
  function pageGuide() {
    const h = '<div class="crumbs"><a href="#/">처음</a></div><div class="page-head"><h1>읽는 법</h1></div>' +
      '<h2>형광펜의 뜻</h2><p>형광펜은 <mark>한 번 더 볼 이유가 있다</mark>는 표시입니다. 위법, 부정, 사적 사용이 확인되었다는 뜻이 아닙니다. 표시마다 어떤 규칙이 무엇을 계산했고 어떤 정상적인 설명이 가능한지, 무엇이 아직 확인되지 않았는지 함께 적었습니다.</p>' +
      '<div class="limits" style="margin-top:16px"><div><b>맥락 확인 필요</b>지출 목적·참석자·증빙을 확인해야 판단할 수 있는 패턴.</div><div><b>데이터 품질 점검</b>원본 기재 오류, OCR 오류, 중복 수록 등 자료 자체의 문제일 가능성이 큰 표시.</div><div><b>참고 정보</b>정기 계약·자진 정정처럼 그 자체로는 문제 신호가 아니지만 맥락에 도움이 되는 정보.</div></div>' +
      '<h2>지출은 누구의 것인가</h2><div class="table-wrap"><table><tbody>' +
      Object.entries(SUBJECT_TYPE).filter(([k]) => k !== 'ORG').map(([k, v]) => '<tr><th>' + esc(v) + '</th><td>' + esc({
        LEGISLATOR: '의원 본인 명의 정치자금 회계의 지출입니다. 실제 결제자(의원·보좌진)는 자료로 구분할 수 없습니다.',
        COUNCIL_ROLE: '의장·부의장·위원장 등 직책에 편성된 업무추진비입니다. 성명이 공개되지 않고, 직책 보유자가 전·후반기마다 바뀝니다. 그래서 직책과 기수를 함께 묶었습니다.',
        COUNCIL_MEMBER: '공동경비 사용자 칸에 의원 성명이 직접 적힌 경우입니다. 해당 의원이 집행한 기록일 뿐 개인 용도라는 뜻은 아닙니다.',
        COUNCIL_BODY: '위원회·의회 공동 경비입니다. 소속 의원 모두의 개인 지출로 나누어 귀속하지 않습니다.',
        NEGOTIATION_GROUP: '교섭단체(정당) 단위 경비입니다.',
        SECRETARIAT: '의회사무국 공무원의 기관운영·시책추진 업무추진비입니다. 의원의 지출이 아닙니다.',
      }[k]) + '</td></tr>').join('') + '</tbody></table></div>' +
      '<h2>합산하지 않는 이유</h2><p>정치자금(후원금·본인 자산 등), 의회운영업무추진비, 의정운영공통경비, 사무국 업무추진비는 재원과 회계 기준이 다릅니다. 페이지마다 재원별로 나누어 보여주고 서로 더하지 않습니다. 취소·반환(음수)은 같은 거래처·같은 금액의 원거래와 짝을 지어 순지출을 계산합니다.</p>' +
      '<h2>개인정보 처리</h2><ul><li>정치자금 보고서의 생년월일, 개인 주소, 전화번호, 영수증 일련번호 원문은 게시하지 않습니다.</li><li>개인에게 지급된 금액(인건비, 개인 임대인 등)의 사용처는 "개인(비공개)"로 바꿉니다.</li>' +
      '<li>후원인(기부자) 정보는 정치자금법 제42조에 따라 다루지 않고, 수입은 유형별 합계로만 보여줍니다.</li><li>거래처 주소는 시·군·구까지만, 개인사업자 사업자번호는 뒷자리를 가립니다.</li><li>지방의회 공개 자료의 참석자 명단 파일은 수집하되 파싱·게시하지 않습니다.</li></ul>' +
      '<h2>스캔 PDF와 OCR</h2><p>일부 의회는 업무추진비를 스캔한 이미지 PDF로 공개합니다. 이런 파일은 이 컴퓨터 안에서 macOS Vision OCR로 글자와 위치를 읽고, 표의 머리글 위치로 칸을 다시 맞춰 넣었습니다(외부 전송 없음). OCR로 읽은 거래에는 "스캔본 OCR로 읽음" 표시가 붙고, 문서에 인쇄된 합계와 읽은 합계가 같은 파일만 신뢰도 "보통"으로, 나머지는 "낮음"으로 둡니다. 사용자 칸에 적힌 의원 성명은 저장하지 않고 직책만 남깁니다. 보도·인용 전에는 반드시 원본 PDF를 확인하세요.</p>' +
      '<h2>정정과 재처리</h2><p>원본 자료는 받은 그대로 보관하고(sha256 기록), 정규화·탐지·사이트 생성은 언제든 다시 실행할 수 있습니다. 의회가 자료를 정정하거나 삭제하면 다시 수집해 결과를 새로 만듭니다. 탐지 결과마다 정정 요청 양식이 있습니다. 사람이 검토한 결과는 data/reviews.json에 기록되어 해당 탐지 결과 페이지의 "검토·정정 이력"에 표시됩니다.</p>' +
      '<h2>근거 법령</h2>' + legalBlock(META.legal.map((l) => l.id));
    setPage(h, '읽는 법');
  }

  // ------------------------------------------------------------------ router
  async function router() {
    const raw = location.hash.replace(/^#/, '') || '/';
    const [path, qs] = raw.split('?');
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    const q = new URLSearchParams(qs || '');
    try {
      if (!parts.length) await pageHome();
      else if (parts[0] === 'assembly') pageAssembly(q);
      else if (parts[0] === 'council') await pageCouncil(parts[1]);
      else if (parts[0] === 's') await pageSubject(parts[1], q);
      else if (parts[0] === 'f') await pageFinding(parts[1], parts[2]);
      else if (parts[0] === 'm') await pageMerchant(parts[1], q);
      else if (parts[0] === 'p') await pagePerson(parts[1]);
      else if (parts[0] === 'region') await pageRegion(q);
      else if (parts[0] === 'budget') await pageBudget(q);
      else if (parts[0] === 'money') await pageMoney(q);
      else if (parts[0] === 'outliers') await pageOutliers(q);
      else if (parts[0] === 'rank') await pageRank(q);
      else if (parts[0] === 'councils') pageCouncils();
      else if (parts[0] === 'rules' && parts[1]) await pageRule(parts[1], q);
      else if (parts[0] === 'rules') pageRules();
      else if (parts[0] === 'sources') pageSources();
      else if (parts[0] === 'guide') pageGuide();
      else setPage('<p class="err">없는 페이지입니다. <a href="#/">처음으로</a></p>');
    } catch (e) {
      console.error(e);
      setPage('<p class="err">자료를 불러오지 못했습니다: ' + esc(e.message) + ' — site 폴더 안의 data 폴더가 함께 있는지 확인하세요.</p>');
    }
    if (!(parts[0] === 's' && (q.get('tx') || q.get('cat') || q.get('sec'))) && parts[0] !== 'region' && !q.get('region')) window.scrollTo(0, 0);
    if (parts[0] === 's' && q.get('cat')) { const l = document.getElementById('ledger'); if (l) setTimeout(() => l.scrollIntoView(), 50); }
  }

  function initTheme() {
    const btn = document.getElementById('theme-toggle');
    let saved = null;
    try { saved = localStorage.getItem('rh-theme'); } catch (e) { /* storage unavailable */ }
    if (saved) document.documentElement.dataset.theme = saved;
    btn.addEventListener('click', () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === 'dark'
        : window.matchMedia('(prefers-color-scheme: dark)').matches;
      const next = dark ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('rh-theme', next); } catch (e) { /* ignore */ }
    });
  }

  initTheme();
  loadMeta().then((m) => {
    META = m;
    META.subjects.forEach((s) => (subjectById[s.id] = s));
    (META.councils || []).forEach((c) => (SOURCE_NAME[c.id] = c.name));
    document.getElementById('footer-meta').textContent = '자료 생성 ' + m.generatedAt + ', 지출 기록 ' + nf.format(Object.values(m.sourceStats).reduce((a, s) => a + s.count, 0)) + '건, 탐지 결과 ' + nf.format(m.findingCount) + '건.';
    window.addEventListener('hashchange', router);
    router();
  }).catch((e) => setPage('<p class="err">' + esc(e.message) + ' 먼저 파이프라인(pipeline/run_all.sh)을 실행해 site/data 를 만드세요.</p>'));
})();
