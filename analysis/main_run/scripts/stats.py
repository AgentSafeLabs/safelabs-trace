"""Item-level paired sign-flip permutation test, item bootstrap, Holm. Plan section 5: 100,000 permutations, seed 20261007 (numpy default_rng), two-sided, p = (count + 1) / (N + 1);
item bootstrap 10,000 resamples, seed 20261007. AUTHOR CHOICE (the plan is silent): every contrast gets its own fresh default_rng(20261007) for the permutations and another for the bootstrap, so a
contrast's p does not depend on the order of the contrasts."""
from common import *  # noqa
import numpy as np


def item_rates(trials, tier, framework, model, field="risky_excl", drop=None):
    """item -> mean over the item's trials in the cell of the 0/1 field (trials with an unknown action are left out). drop: optional predicate on a trial row that removes the trial."""
    acc: dict[str, list[int]] = {}
    for t in trials:
        if t["tier"] == tier and t["framework"] == framework and t["model"] == model and t["known"] and not (drop and drop(t)):
            acc.setdefault(t["prompt_id"], []).append(t[field])
    return {k: sum(v) / len(v) for k, v in acc.items()}


def paired(a: dict[str, float], b: dict[str, float]):
    items = sorted(set(a) & set(b))
    return items, np.array([a[i] - b[i] for i in items], dtype=float), np.array([a[i] for i in items]), np.array([b[i] for i in items])


def perm_p(d: np.ndarray, n_perm: int = N_PERM, seed: int = SEED, chunk: int = 5000) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    obs = abs(d.mean())
    count, done = 0, 0
    while done < n_perm:
        m = min(chunk, n_perm - done)
        signs = rng.integers(0, 2, size=(m, len(d)), dtype=np.int8) * 2 - 1
        stat = np.abs(signs @ d) / len(d)
        count += int(np.sum(stat >= obs - 1e-12))
        done += m
    return (count + 1) / (n_perm + 1), obs


def boot_ci(d: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    m = d[idx].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def holm(ps: list[float]) -> list[float]:
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj = [0.0] * m
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


def contrast(a: dict[str, float], b: dict[str, float]) -> dict:
    items, d, ra, rb = paired(a, b)
    p, obs = perm_p(d)
    lo, hi = boot_ci(d)
    return {"n_items": len(items), "mean_A_pct": 100 * ra.mean(), "mean_B_pct": 100 * rb.mean(), "diff_points": 100 * d.mean(), "boot_lo": 100 * lo, "boot_hi": 100 * hi, "p_raw": p,
            "n_items_differing": int(np.sum(d != 0))}
