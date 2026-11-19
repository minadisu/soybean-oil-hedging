"""Reproduce the classroom exercise and the inventory-hedging extension."""
import argparse
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from scipy.stats import genpareto

import soybean_oil_hedging as hedge
from soybean_oil_hedging import plt

ROOT = Path(__file__).resolve().parent
COLORS = ["#335b8e", "#c76835", "#14826a"]
LABELS = ["Inventory only", "Nearby hedge", "Dominant hedge"]


def save_plot(series, title, ylabel, path, percent=False):
    fig, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
    plotted = series * 100 if percent else series
    plotted.plot(ax=ax, color=COLORS[:len(series.columns)], linewidth=1.4)
    ax.set(title=title, ylabel=ylabel, xlabel="")
    ax.grid(axis="y", alpha=0.2)
    ax.legend(title=None, frameon=False, ncol=len(series.columns))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def pot(loss):
    """GPD fit to strict exceedances above the window's 90th percentile."""
    threshold = np.quantile(loss, .90)
    excess = loss[loss > threshold] - threshold
    count = len(excess)
    if count < 10 or np.ptp(excess) == 0:
        return [threshold, count, np.nan, np.nan, np.nan, np.nan]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        shape, _, scale = genpareto.fit(excess, floc=0)
    q = 1 - .05 * len(loss) / count
    var = threshold + genpareto.ppf(q, shape, scale=scale)
    es = (var + scale - shape * threshold) / (1 - shape) if shape < 1 else np.nan
    return [threshold, count, shape, scale, var, es]


def classroom(data, year, out):
    prices = pd.DataFrame({"Spot": data.spot, "Assignment proxy": data.spot - data.nearby.diff()})
    if (prices <= 0).any().any():
        raise ValueError("Log returns require positive proxy and spot prices.")
    returns = np.log(prices).diff().dropna()
    shown = prices.loc[prices.index.year == year]
    shown.to_csv(out / "classroom_prices.csv")
    save_plot(shown, f"Soybean oil | Spot and assignment price proxy, {year}",
              "Price (input units)", out / "classroom_prices.png")
    rows = []
    for i in np.flatnonzero(returns.index.year == year):
        if i < hedge.WINDOW:
            continue
        for name in returns:
            loss = -returns[name].iloc[i-hedge.WINDOW:i].to_numpy()
            var = np.quantile(loss, .95)
            rows.append([returns.index[i], name, var, loss[loss >= var].mean(), *pot(loss)])
    stats = pd.DataFrame(rows, columns=["date", "series", "hs_var", "hs_es", "threshold",
                                        "exceedances", "shape", "scale", "evt_var", "evt_es"])
    stats.to_csv(out / "classroom_risk.csv", index=False)
    for metric in ["var", "es"]:
        fig, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 7), layout="constrained")
        for ax, method, title in zip(axes, ["hs", "evt"], ["Historical simulation", "Peaks over threshold"]):
            values = stats.pivot(index="date", columns="series", values=f"{method}_{metric}")
            (100 * values[list(prices)]).plot(ax=ax, color=COLORS[:2])
            ax.set(title=title, ylabel=f"Daily {metric.upper()} (%)", xlabel="")
            ax.grid(axis="y", alpha=.2)
            ax.legend(title=None, frameon=False)
        fig.suptitle(f"Classroom replication | 95% {metric.upper()} | {year}")
        fig.savefig(out / f"classroom_{metric}.png", dpi=160)
        plt.close(fig)


def extension(data, year, out):
    daily = hedge.daily_positions(data)
    annual = daily.loc[daily.index.year == year]
    sample = annual.loc[annual.common_sample]
    summary, tails = hedge.summarize(sample)
    common = daily.loc[daily.common_sample, list(hedge.STRATEGIES)]
    rolling = hedge.rolling_risk(common, year)
    annual.to_csv(out / "daily_audit.csv")
    summary.to_csv(out / "risk_summary.csv")
    tails.to_csv(out / "tail_days.csv")
    rolling.to_csv(out / "rolling_risk.csv", index=False)
    for metric in ["var", "es"]:
        values = rolling.pivot(index="date", columns="strategy", values=f"{metric}_95")
        values = values[list(hedge.STRATEGIES)].set_axis(LABELS, axis=1)
        save_plot(values, f"Inventory hedging | Rolling 95% historical {metric.upper()}, {year}",
                  f"Daily {metric.upper()} (% of inventory value)", out / f"inventory_{metric}.png", True)
    differences = []
    for date in sample.index:
        losses = -sample.drop(date)[list(hedge.STRATEGIES)]
        es = losses.where(losses >= losses.quantile(.95)).mean()
        differences.append([date, es.spot_return - es.dominant_return, es.nearby_return - es.spot_return])
    pd.DataFrame(differences, columns=["excluded_date", "spot_minus_dominant_es",
                                       "nearby_minus_spot_es"]).to_csv(out / "leave_one_out.csv", index=False)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "豆油.csv")
    parser.add_argument("--year", type=int, default=2024)
    args = parser.parse_args()
    out = ROOT / "results" / str(args.year)
    data = hedge.load_data(args.data)
    out.mkdir(parents=True, exist_ok=True)
    summary = extension(data, args.year, out)
    classroom(data, args.year, out)
    print(summary.to_string())
    print(out)


if __name__ == "__main__":
    main()
