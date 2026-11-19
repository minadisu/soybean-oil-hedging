"""Compare equal-quantity soybean oil futures hedges on matched observation dates.

Run: python soybean_oil_hedging.py --data 豆油.csv --year 2024
Requires numpy, pandas, matplotlib. CSV returns and risk measures are in decimals.
ES is the mean loss at or above the estimated 95th percentile (ties included).
Returns use prior inventory value. Fees, margin funding and roll-day P&L are excluded.
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLUMNS = {
    "时间": "date", "现货价格": "spot", "近期合约期货代码": "nearby_code",
    "近期合约期货价格": "nearby", "主力合约期货代码": "dominant_code",
    "主力合约期货价格": "dominant",
}
HEDGES = ("nearby", "dominant")
STRATEGIES = ("spot_return", "nearby_return", "dominant_return")
WINDOW = 250
DECAY = 0.995
CONFIDENCE = 0.95


def load_data(path):
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            data = pd.read_csv(path, encoding=encoding, usecols=list(COLUMNS))
            break
        except UnicodeDecodeError:
            if encoding == "gb18030":
                raise
    data = data.rename(columns=COLUMNS)
    if data.isna().any().any():
        raise ValueError("Missing dates, prices or contract identifiers in the input.")
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    data = data.set_index("date").sort_index()
    if not data.index.is_unique:
        raise ValueError("Duplicate observation dates in the input.")
    for name in ("spot", *HEDGES):
        prices = pd.to_numeric(data[name], errors="raise")
        if not (np.isfinite(prices) & (prices > 0)).all():
            raise ValueError(f"Invalid prices in {name}")
        data[name] = prices
    return data


def daily_positions(data):
    """Difference prices before filtering dates, retaining roll flags for audit."""
    daily = data.copy()
    prior_spot = daily["spot"].shift()
    daily["spot_change"] = daily["spot"].diff()
    daily["spot_return"] = daily["spot_change"] / prior_spot
    for name in HEDGES:
        code = daily[f"{name}_code"]
        roll = code.ne(code.shift()) & code.shift().notna()
        daily[f"{name}_roll"] = roll
        change = daily[name].diff().mask(roll)
        daily[f"{name}_change"] = change
        daily[f"{name}_return"] = (daily["spot_change"] - change) / prior_spot
    daily["common_sample"] = daily[list(STRATEGIES)].notna().all(axis=1)
    return daily


def summarize(sample):
    rows, tails = [], []
    for strategy in STRATEGIES:
        returns = sample[strategy]
        losses = -returns
        var = losses.quantile(CONFIDENCE)
        tail = sample.loc[losses >= var].copy()
        tail["strategy"] = strategy
        tail["loss"] = -tail[strategy]
        tails.append(tail.sort_values("loss", ascending=False))
        rows.append(dict(strategy=strategy, observations=len(sample),
                         volatility=returns.std(ddof=1), var_95=var,
                         es_95=tail["loss"].mean(), tail_days=len(tail)))
    return pd.DataFrame(rows).set_index("strategy"), pd.concat(tails)


def rolling_risk(common, year):
    """At each eligible date, use the preceding 250 eligible observations."""
    weights = DECAY ** np.arange(WINDOW - 1, -1, -1)
    weights /= weights.sum()
    records = []
    for i in np.flatnonzero(common.index.year == year):
        if i < WINDOW:
            continue
        history = common.iloc[i - WINDOW:i]
        for strategy in STRATEGIES:
            losses = -history[strategy].to_numpy()
            var = np.quantile(losses, CONFIDENCE)
            order = np.argsort(losses)
            sorted_weights = weights[order].cumsum()
            cutoff = np.searchsorted(sorted_weights, CONFIDENCE)
            weighted_var = losses[order[cutoff]]
            tail = losses >= weighted_var
            records.append(dict(date=common.index[i], strategy=strategy,
                                window_start=history.index[0], window_end=history.index[-1],
                                var_95=var, es_95=losses[losses >= var].mean(),
                                weighted_var_95=weighted_var,
                                weighted_es_95=np.average(losses[tail], weights=weights[tail])))
    if not records:
        raise ValueError("The selected year has no dates with 250 prior eligible observations.")
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).with_name("豆油.csv"))
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "results")
    args = parser.parse_args()

    daily = daily_positions(load_data(args.data))
    annual = daily.loc[daily.index.year == args.year]
    sample = annual.loc[annual["common_sample"]]
    if len(sample) < 2:
        raise ValueError("The selected year has fewer than two matched observations.")
    summary, tails = summarize(sample)
    rolling = rolling_risk(daily.loc[daily["common_sample"], list(STRATEGIES)], args.year)

    out = args.out / str(args.year)
    out.mkdir(parents=True, exist_ok=True)
    annual.to_csv(out / "daily_audit.csv", encoding="utf-8-sig")
    summary.to_csv(out / "risk_summary.csv")
    tails.to_csv(out / "tail_days.csv")
    rolling.to_csv(out / "rolling_risk.csv", index=False)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
    for axis, metric, title in zip(axes, ("es_95", "weighted_es_95"),
                                   ("Historical simulation", "Exponentially weighted simulation")):
        series = rolling.pivot(index="date", columns="strategy", values=metric)
        series = series[list(STRATEGIES)].rename(columns=lambda s: s.replace("_return", "").title())
        (100 * series).plot(ax=axis, linewidth=1.3)
        axis.set(title=title, ylabel="Daily ES (% of inventory value)", xlabel="")
        axis.legend(title=None, ncol=3)
    fig.suptitle(f"Soybean oil hedging | Rolling 95% expected shortfall | {args.year}")
    fig.savefig(out / "rolling_es.png", dpi=160)
    plt.close(fig)

    print(f"{args.year}: {len(sample)} matched observations from {len(annual)} dates")
    percentages = {key: "{:.2%}".format for key in ("volatility", "var_95", "es_95")}
    print(summary.to_string(formatters=percentages))
    print(f"Results: {out.resolve()}")


if __name__ == "__main__":
    main()
