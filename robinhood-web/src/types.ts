export type Scope = {
  kind: string;
  label: string;
  start: string;
  end: string;
  fundingType?: string;
  reportId?: string;
  unit?: string;
  note: string;
  basis?: string;
};
export type Summary = {
  amount: number | null;
  count: number;
  payments: number;
  months: number;
  monthlyAverage: number | null;
  firstDate?: string;
  lastDate?: string;
};
export type Category = { name: string; amount: number; count?: number };
export type Month = {
  month: string;
  amount: number | null;
  count: number;
  payments: number;
  hasRecords: boolean;
};
export type Holder = {
  name: string;
  party?: string;
  start: string;
  end: string;
  sourceUrl?: string;
  sourceTitle?: string;
  confidence?: string;
};
export type Subject = {
  id: string;
  name: string;
  type: string;
  source: string;
  org: string;
  role?: string;
  term?: string;
  party?: string;
  district?: string;
  attribution?: string;
  holders: Holder[];
  reports?: string[];
};
export type Document = {
  doc_id: string;
  title: string;
  url: string;
  publisher?: string;
  format: string;
  period?: string;
  fetched_at?: string;
  sha256?: string;
  origin_note?: string;
};
export type Transaction = {
  id: string;
  date: string;
  time?: string;
  amount: number;
  description?: string;
  category?: string;
  subjectId: string;
  subjectName: string;
  merchantId?: string;
  payee?: string;
  fundingType: string;
  account?: string;
  attendees?: number;
  payment?: string;
  budgetItem?: string;
  docId: string;
  rowRef?: string;
  flags: string[];
  quality: {
    ocr?: boolean;
    flags?: string[];
    parse_confidence?: string;
    ocr_correction?: { review_id: string; fields: string[] };
  };
  pairId?: string;
  duplicateOf?: string;
  perPerson?: number;
  weekday?: string;
  holiday?: string;
};
export type TransactionPage = {
  scope: Scope;
  rows: Transaction[];
  total: number;
  page: number;
  pageSize: number;
};
export type Member = {
  id: string;
  name: string;
  party?: string;
  district?: string;
  amount: number;
  count: number;
};
export type MemberPage = {
  scope: Scope;
  rows: Member[];
  total: number;
  page: number;
  pageSize: number;
  median: number | null;
  summary: Summary;
  monthly: Month[];
  categories: Category[];
};
export type AssetSource = {
  title: string;
  basis: string;
  published: string;
  url: string;
};
export type Asset = {
  page: number;
  total: { cur: number; prev: number; change: number; valuation: number };
  cats: Record<string, { prev: number; cur: number }>;
  realestate: {
    relation: string;
    kind: string;
    sido: string;
    sgg: string;
    emd: string;
    area: string[];
    lease: boolean;
    prev: number;
    cur: number;
    reason: string;
  }[];
  refused: string[];
  cryptoCount: number;
  source: AssetSource;
};
export type Bill = [string, string, string, string, string | null, string];
export type Activity = {
  committees?: string;
  reelection?: string;
  bills: Record<
    string,
    { lead: number; co: number; results: Record<string, number>; list: Bill[] }
  >;
  votes: Record<
    string,
    {
      total: number;
      participation: number;
      counts: Record<string, number>;
      recent: [string, string, string][];
      dissent: [string, string, string][];
    }
  >;
  fetchedAt?: string;
};
export type Finding = {
  id: string;
  ruleId: string;
  code: string;
  explanation: string;
  observed: Record<string, unknown>;
  evidenceIds: string[];
  reference: { type: string; value: string; description: string };
  reviewStatus: string;
  reviewHistory: unknown[];
};
export type Profile = {
  subject: Subject;
  scope: Scope;
  summary: Summary;
  monthly: Month[];
  categories: Category[];
  income: Category[];
  incomeCarry: Record<string, number>;
  incomeYear: string;
  assets?: Asset;
  activity?: Activity;
  transactions: TransactionPage;
  findings: Finding[];
};
export type CouncilItem = {
  id: string;
  source_id?: string;
  name: string;
  region: string;
  level: string;
  board?: string;
  amount: number;
  count: number;
  months: number;
  monthlyAverage: number;
  firstDate?: string;
  lastDate?: string;
};
export type Council = {
  council: CouncilItem;
  scope: Scope;
  summary: Summary;
  monthly: Month[];
  categories: Category[];
  roles: {
    id: string;
    amount: number;
    count: number;
    months: number;
    subject: Subject;
    firstDate: string;
    lastDate: string;
  }[];
  transactions: Transaction[];
};
export type Overview = {
  region: string;
  scope: Scope;
  members: MemberPage;
  council?: Council;
  cityCouncil?: Council;
  localFiscalAvailable: boolean;
};
export type Place = {
  id: string;
  name: string;
  region?: string;
  confidence?: string;
  amount: number;
  count: number;
  payments: number;
  payerCount: number;
  refunds: number;
};
export type Cluster = {
  region: string;
  venues: number;
  payments: number;
  amount: number;
};
export type Places = {
  scope: Scope;
  rows: Place[];
  total: number;
  page: number;
  pageSize: number;
  summary: { amount: number | null; payments: number };
  clusters: Cluster[];
  locationPrecision: string;
};
export type Merchant = {
  id: string;
  name: string;
  region?: string;
  confidence?: string;
  aliases: string[];
  businessNumber?: string;
  kind?: string;
};
export type PlaceDetail = {
  merchant: Merchant;
  scope: Scope;
  summary: Summary;
  monthly: Month[];
  payerCount: number;
  payers: { id: string; amount: number; payments: number; subject: Subject }[];
  refunds: number;
  transactions: TransactionPage;
  locationPrecision: string;
};
export type Ranking = {
  scope: Scope;
  target: string;
  metric: string;
  n: number;
  median: number | null;
  total: number | null;
  mean: number | null;
  rows: {
    id: string;
    name: string;
    party?: string;
    district?: string;
    amount: number;
    value: number;
    count?: number;
    months?: number;
    rank: number;
    ratioToMedian?: number;
  }[];
  categories: Category[];
  monthly?: Month[];
  note?: string;
};
export type Meta = {
  serviceName: string;
  indexedAt: string;
  counts: Record<string, number>;
  fundingTypes: Record<string, { label: string; description: string }>;
  councils: CouncilItem[];
  parties: string[];
  reports: { id: string; title: string; period: string }[];
  documents: number;
  merchants: number;
  naverMapsClientId: string;
  locationPrecision: string;
};
export type MapFeature = {
  code: string;
  name: string;
  short?: string;
  sgg?: string;
  d: string;
  cx: number;
  cy: number;
  lat?: number;
  lng?: number;
};
export type Geo = {
  projection: {
    national: { viewBox: string };
    seoul: { viewBox: string };
    sources: { url: string; attribution: string }[];
  };
  sido: MapFeature[];
  seoul: MapFeature[];
  districts: MapFeature[];
  seoulDistricts: MapFeature[];
};
export type FiscalRow = {
  name: string;
  code?: string;
  amount: number;
  top_programs?: { name: string; amount: number; sector: string }[];
};
export type FiscalPoint = {
  year: number;
  amount: number | null;
  basis: "actual" | "budget" | "proposal" | null;
  label: string | null;
  share: number | null;
};
export type FiscalTrend = {
  id: string;
  name: string;
  dimension: "total" | "sector" | "ministry";
  points: FiscalPoint[];
  current: FiscalPoint | null;
  previous: FiscalPoint | null;
  denominator: string | null;
  delta: number | null;
  rate: number | null;
  shareDeltaPp: number | null;
};
export type FiscalValues = {
  total_revenue: number;
  total_expenditure: number;
  integrated_balance: number;
  managed_balance: number;
  national_tax: number;
  non_tax: number;
  fund_revenue: number;
  through_month: number;
};
export type Fiscal = {
  scope: Scope;
  selectedYear: number;
  availableYears: Record<"actual" | "budget" | "proposal", number[]>;
  trends: { series: FiscalTrend[]; note: string };
  values?: FiscalValues;
  sectors?: { basis: string; items: FiscalRow[] };
  ministries?: { basis: string; items: FiscalRow[] };
  revenue?: { basis: string; items: FiscalRow[] };
  taxes?: { basis: string; items: FiscalRow[] };
  source: { name: string; url: string; fetched_at?: string };
  debt?: { national_debt: number; gdp_ratio_pct: number };
  history: (FiscalValues & { year: string })[];
  actualYears: number[];
};
export type TransactionDetail = Transaction & {
  receiptNo?: string;
  categorySource?: string;
  scope: Scope;
  subject: Subject;
  document: Document;
  pair?: Transaction;
  findings: Finding[];
};
export type Rule = {
  id: string;
  code: string;
  name: string;
  reference_type: string;
  purpose: string;
  fields: string[];
  method: string;
  thresholds: string;
  missing_data: string;
  normal_cases: string[];
  verification: string[];
};
export type Sources = {
  indexedAt: string;
  counts: Record<string, number>;
  sources: {
    source: string;
    name: string;
    count: number;
    documents: number;
    firstDate: string;
    lastDate: string;
  }[];
  rules: Rule[];
  fields: Record<
    string,
    { count: number; time: number; attendees: number; payment: number }
  >;
  findingCount: number;
  assetSource: AssetSource;
  assembly: { fetched_at: string };
  geoSources: { url: string; attribution: string }[];
};
