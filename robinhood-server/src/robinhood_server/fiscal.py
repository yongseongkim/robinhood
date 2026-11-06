"""Comparable fiscal time series; missing observations never become zero."""

import math


def basis_of(label):
    label = label or ""
    actual = "결산" in label
    proposal = "예산안" in label or "정부안" in label
    budget = "예산" in label and not proposal
    kinds = [
        kind
        for kind, present in (
            ("actual", actual),
            ("proposal", proposal),
            ("budget", budget),
        )
        if present
    ]
    return kinds[0] if len(kinds) == 1 else None


def sections(fiscal, dimension):
    container = fiscal.get("expenditure_by_" + dimension, {})
    result = {"actual": {}, "budget": {}, "proposal": {}}

    def add(year, value):
        kind = basis_of(value.get("basis"))
        if kind and str(year).isdigit() and isinstance(value.get("items"), list):
            result[kind][int(year)] = value

    for key in ("years", "history", "budget_years", "proposal_years"):
        for year, value in container.get(key, {}).items():
            add(year, value)
    if container.get("year"):
        add(container["year"], container)
    proposal = container.get("proposal", {})
    if proposal.get("year"):
        add(proposal["year"], proposal)
    return result


def available_years(fiscal):
    actual = [
        int(year)
        for year, value in fiscal.get("actuals", {}).get("years", {}).items()
        if value
    ]
    output = {"actual": actual, "budget": [], "proposal": []}
    for dimension in ("sector", "ministry"):
        for kind, years in sections(fiscal, dimension).items():
            if kind != "actual":
                output[kind].extend(years)
    return {kind: sorted(set(years), reverse=True) for kind, years in output.items()}


def number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def total(items):
    return (
        sum(row["amount"] for row in items)
        if items and all(number(row.get("amount")) for row in items)
        else None
    )


def build_trends(fiscal, year, basis):
    annual = fiscal.get("actuals", {}).get("years", {})
    groups = {
        dimension: sections(fiscal, dimension) for dimension in ("sector", "ministry")
    }
    # 정부안은 전년도 확정 본예산과 비교하되 각 점의 기준을 그대로 전달한다.
    selected = {}
    for dimension, kinds in groups.items():
        selected[dimension] = dict(
            kinds["budget"] if basis == "proposal" else kinds[basis]
        )
        if basis == "proposal" and year in kinds["proposal"]:
            selected[dimension][year] = kinds["proposal"][year]
        selected[dimension] = {
            y: value for y, value in selected[dimension].items() if y <= year
        }
    observed = set().union(*(set(values) for values in selected.values()))
    if basis == "actual":
        observed.update(
            int(y)
            for y, value in annual.items()
            if int(y) <= year and value.get("through_month") == 12
        )
    first = max(min(observed, default=year), year - 9)
    years = range(first, year + 1)

    def point(y, amount, label, share=None):
        return {
            "year": y,
            "amount": amount if number(amount) else None,
            "basis": basis_of(label),
            "label": label,
            "share": share,
        }

    def series(key, name, dimension, points, denominator):
        current = next((p for p in points if p["year"] == year), None)
        previous = next((p for p in points if p["year"] == year - 1), None)
        comparable = (
            current
            and previous
            and number(current["amount"])
            and number(previous["amount"])
        )
        delta = current["amount"] - previous["amount"] if comparable else None
        rate = (
            delta / previous["amount"]
            if comparable and previous["amount"] > 0
            else None
        )
        share_delta = (
            (current["share"] - previous["share"]) * 100
            if comparable and number(current["share"]) and number(previous["share"])
            else None
        )
        return {
            "id": key,
            "name": name,
            "dimension": dimension,
            "points": points,
            "denominator": denominator,
            "current": current,
            "previous": previous,
            "delta": delta,
            "rate": rate,
            "shareDeltaPp": share_delta,
        }

    totals = []
    for y in years:
        if basis == "actual":
            value = annual.get(str(y), {})
            amount = (
                value.get("total_expenditure")
                if value.get("through_month") == 12
                else None
            )
            totals.append(point(y, amount, "결산"))
        else:
            value = selected["ministry"].get(y, {})
            totals.append(point(y, total(value.get("items", [])), value.get("basis")))
    rows = [
        series(
            "total",
            "연간 총지출" if basis == "actual" else "수집 부처 예산 합계",
            "total",
            totals,
            None,
        )
    ]
    for dimension, values in selected.items():
        names = {}
        for value in values.values():
            for item in value["items"]:
                names[str(item.get("code") or item["name"])] = item["name"]
        for code, name in names.items():
            points = []
            for y in years:
                value = values.get(y, {})
                items = value.get("items", [])
                item = next(
                    (r for r in items if str(r.get("code") or r["name"]) == code), {}
                )
                amount, denominator = item.get("amount"), total(items)
                share = (
                    amount / denominator
                    if number(amount) and denominator and denominator > 0
                    else None
                )
                points.append(point(y, amount, value.get("basis"), share))
            rows.append(
                series(
                    dimension + ":" + code,
                    name,
                    dimension,
                    points,
                    "같은 통계·연도의 수록 "
                    + ("분야" if dimension == "sector" else "부처")
                    + " 합계",
                )
            )
    return {
        "series": rows,
        "note": "정부 예산안은 전년도 확정 예산과 편성 규모를 비교합니다. 집행 실적의 증가를 뜻하지 않습니다."
        if basis == "proposal"
        else "전년도 같은 기준의 자료와 비교합니다. 결산은 12월 누계가 있는 연도만 연간 비교에 포함합니다.",
    }
