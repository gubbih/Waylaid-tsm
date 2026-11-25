#!/usr/bin/env python3
"""
WoW Forever - Waylaid Crate & Merchant's Favor calculator
Default target: EU / Normal / Horde, prices from TradeSkillMaster public data.

Pricing data from TradeSkillMaster (https://tradeskillmaster.com) - public CSVs,
no API key needed: https://tradeskillmaster.com/public-data

Usage:
    python3 waylaid_crate_calc.py                    # EU Normal Horde, min buyout
    python3 waylaid_crate_calc.py --price market     # use market value instead
    python3 waylaid_crate_calc.py --faction alliance --type pvp
    python3 waylaid_crate_calc.py --file items.csv   # use a downloaded CSV
    python3 waylaid_crate_calc.py --crate-ids crates.json

Needs only Python 3.8+ (standard library).
"""

import argparse
import csv
import io
import json
import sys
import urllib.request

BASE = "https://public-data.tradeskillmaster.com"

# --------------------------------------------------------------------------
# Materials: item id -> name
# --------------------------------------------------------------------------
ITEMS = {
    4231: "Cured Light Hide", 4233: "Cured Medium Hide", 4236: "Cured Heavy Hide",
    8172: "Cured Thick Hide", 2996: "Bolt of Linen Cloth",
    765: "Silverleaf", 2453: "Bruiseweed", 3358: "Khadgar's Whisker",
    8831: "Purple Lotus", 13464: "Golden Sansam", 13467: "Icecap",
    2841: "Bronze Bar", 2842: "Silver Bar", 3577: "Gold Bar", 6037: "Truesilver Bar",
    4363: "Copper Modulator", 4382: "Bronze Framework", 4387: "Iron Strut",
    16000: "Thorium Tube",
    2318: "Light Leather", 2319: "Medium Leather", 4234: "Heavy Leather",
    4304: "Thick Leather",
    2770: "Copper Ore", 2772: "Iron Ore", 2776: "Gold Ore", 7911: "Truesilver Ore",
    10939: "Greater Magic Essence", 11082: "Greater Astral Essence",
    11135: "Greater Mystic Essence", 11176: "Dream Dust",
}

# --------------------------------------------------------------------------
# Crates: name -> (Merchant's Favor, [bundles]); a bundle is [(item_id, qty)].
# Any ONE bundle fills the crate. Favor values are from player reports;
# Artisan values (marked expected=True) are unconfirmed.
# Add more bundles to a crate if you find them - the script takes the cheapest.
# --------------------------------------------------------------------------
CRATES = {
    # name: (favor, expected, [bundles])
    "Apprentice Fabrics":       (10, False, [[(4231, 2)], [(2996, 20)]]),
    "Journeyman Fabrics":       (20, False, [[(4233, 2)]]),
    "Expert Fabrics":           (30, False, [[(4236, 2)]]),
    "Artisan Fabrics":          (40, True,  [[(8172, 2)]]),
    "Apprentice Herbs":         (5,  False, [[(765, 20)]]),
    "Journeyman Herbs":         (10, False, [[(2453, 10)]]),
    "Earthly Expert Herbs":     (15, False, [[(3358, 10)]]),
    "Flowering Expert Herbs":   (15, False, [[(8831, 20)]]),
    "Earthly Artisan Herbs":    (20, True,  [[(13464, 10)]]),
    "Flowering Artisan Herbs":  (20, True,  [[(13467, 20)]]),
    "Apprentice Ingots":        (10, False, [[(2841, 10)]]),
    "Journeyman Ingots":        (20, False, [[(2842, 10)]]),
    "Expert Ingots":            (30, False, [[(3577, 10)]]),
    "Artisan Ingots":           (40, True,  [[(6037, 10)]]),
    "Apprentice Parts":         (10, False, [[(4363, 4)]]),
    "Journeyman Parts":         (20, False, [[(4382, 4)]]),
    "Expert Parts":             (30, False, [[(4387, 8)]]),
    "Artisan Parts":            (40, True,  [[(16000, 2)]]),
    "Apprentice Textiles":      (5,  False, [[(2318, 20)]]),
    "Journeyman Textiles":      (10, False, [[(2319, 20)]]),
    "Expert Textiles":          (15, False, [[(4234, 20)]]),
    "Artisan Textiles":         (20, True,  [[(4304, 20)]]),
    "Apprentice Ore":           (5,  False, [[(2770, 20)]]),
    "Journeyman Ore":           (10, False, [[(2772, 20)]]),
    "Expert Ore":               (15, False, [[(2776, 10)]]),
    "Artisan Ore":              (20, True,  [[(7911, 10)]]),
    "Apprentice Curiosities":   (5,  False, [[(10939, 4)]]),
    "Journeyman Curiosities":   (10, False, [[(11082, 4)]]),
    "Expert Curiosities":       (15, False, [[(11135, 4)]]),
    "Artisan Curiosities":      (20, True,  [[(11176, 20)]]),
}

# Item IDs of the labelled "Waylaid Crate: <name>" items (optional).
# Fill these in to get crate prices + "buy and fill" cost, e.g.
#   CRATE_IDS = {"Apprentice Fabrics": 123456, ...}
# or pass --crate-ids crates.json with the same {name: id} layout.
CRATE_IDS = {}


# --------------------------------------------------------------------------
def fmt(copper):
    """Copper -> '1g 23s 45c'."""
    if copper is None:
        return "n/a"
    copper = int(round(copper))
    g, rest = divmod(copper, 10000)
    s, c = divmod(rest, 100)
    parts = []
    if g:
        parts.append(f"{g}g")
    if s or g:
        parts.append(f"{s}s")
    parts.append(f"{c}c")
    return " ".join(parts)


def load_csv_text(args):
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            return f.read()
    url = f"{BASE}/forever/{args.region}/realm/{args.type}-{args.faction}/items.csv"
    print(f"Fetching {url}", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "waylaid-crate-calc/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not download {url}\n  {e}\n"
                 "Check the URL in a browser, or download the CSV and use --file.")


def find_col(header, names, fallback):
    low = [h.strip().lower() for h in header]
    for n in names:
        if n in low:
            return low.index(n)
    return fallback


def parse_prices(text, which, quiet=False):
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    id_col = find_col(header, ["itemid", "item_id", "id"], 0)
    if which == "min":
        p_col = find_col(header, ["minbuyout", "min_buyout", "minbuy"], 1)
    else:
        # TSM docs: market value is column 3 of the realm file
        p_col = find_col(header, ["marketvalue", "market_value", "market"], 2)
    n_col = find_col(header, ["numauctions", "num_auctions", "quantity"], None)
    name_col = find_col(header, ["name", "itemname"], None)

    if not quiet:
        print(f"CSV columns: {header}  -> using '{header[p_col]}' for {which}",
              file=sys.stderr)

    prices, listed, names = {}, {}, {}
    for row in reader:
        try:
            iid = int(float(row[id_col]))
            price = float(row[p_col])
        except (ValueError, IndexError):
            continue
        if name_col is not None and name_col < len(row):
            names[row[name_col].strip().lower()] = iid
        if price > 0:
            prices[iid] = price
        if n_col is not None:
            try:
                listed[iid] = int(float(row[n_col]))
            except (ValueError, IndexError):
                pass
    return prices, listed, names


def bundle_cost(bundle, prices):
    total = 0
    for iid, qty in bundle:
        if iid not in prices:
            return None
        total += prices[iid] * qty
    return total


def bundle_label(bundle):
    return " + ".join(f"{q}x {ITEMS.get(i, i)}" for i, q in bundle)


def build_rows(pm, pn, names, crate_ids=None):
    """pm = market-value prices, pn = min-buyout prices. Returns one dict per crate
    with market ('m') and min-buyout ('n') figures side by side."""
    crate_ids = crate_ids or {}
    rows = []
    for name, (favor, expected, bundles) in CRATES.items():
        cid = crate_ids.get(name) or names.get(f"waylaid crate: {name}".lower())
        r = {"name": name, "favor": favor, "expected": expected,
             "fill": {}, "bundle": {}, "crate": {}}
        for kind, prices in (("m", pm), ("n", pn)):
            best = None
            for b in bundles:
                c = bundle_cost(b, prices)
                if c is not None and (best is None or c < best[0]):
                    best = (c, b)
            r["fill"][kind] = best[0] if best else None
            r["bundle"][kind] = best[1] if best else bundles[0]
            r["crate"][kind] = prices.get(cid) if cid else None
        rows.append(r)
    return rows


def metric(r, kind, rank):
    """Cost per Favor (copper) for one price kind, or None if data is missing."""
    fill, crate = r["fill"][kind], r["crate"][kind]
    if fill is None:
        return None
    if rank == "buy":
        return None if crate is None else (fill + crate) / r["favor"]
    return fill / r["favor"]


def sort_rows(rows, basis, rank):
    """Cheapest first on the chosen price basis; rows missing data go last."""
    def key(r):
        v = metric(r, basis, rank)
        return (v is None, v if v is not None else 0)
    return sorted(rows, key=key)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="eu", choices=["eu", "us"])
    ap.add_argument("--type", default="normal",
                    choices=["normal", "pvp", "roleplay", "roleplay-pvp"])
    ap.add_argument("--faction", default="horde", choices=["horde", "alliance"])
    ap.add_argument("--price", default="min", choices=["market", "min"],
                    help="which price to RANK by: min buyout (default) or market value; both are shown")
    ap.add_argument("--file", help="use a local items.csv instead of downloading")
    ap.add_argument("--crate-ids", help="JSON file: {\"Apprentice Fabrics\": 12345, ...}")
    ap.add_argument("--rank", default="auto", choices=["auto", "fill", "buy"],
                    help="buy = crate price + fill, per Favor; fill = fill cost "
                         "per Favor only (you own the crate); auto (default) = "
                         "buy when crate prices are available")
    ap.add_argument("--top", type=int, default=0, help="only show the N cheapest crates")
    args = ap.parse_args()

    crate_ids = dict(CRATE_IDS)
    if args.crate_ids:
        with open(args.crate_ids, encoding="utf-8") as f:
            crate_ids.update(json.load(f))

    text = load_csv_text(args)
    pm, listed, names = parse_prices(text, "market")
    pn, _, _ = parse_prices(text, "min", quiet=True)
    basis = "m" if args.price == "market" else "n"
    basis_label = "market value" if basis == "m" else "min buyout"

    rows = build_rows(pm, pn, names, crate_ids)
    rows = [r for r in rows if r["fill"]["m"] is not None or r["fill"]["n"] is not None]

    rank = args.rank
    if rank == "auto":
        rank = "buy" if any(r["crate"][basis] is not None for r in rows) else "fill"
    rows = sort_rows(rows, basis, rank)
    if args.top:
        rows = rows[: args.top]

    what = "BUY + FILL" if rank == "buy" else "FILL"
    print(f"\nWoW Forever | {args.region.upper()} {args.type} {args.faction.capitalize()}")
    print(f"WAYLAID CRATES - ranked by {what} cost per Favor, using {basis_label} "
          f"(MV = market value, MB = min buyout)")
    print("-" * 150)
    lab = "Buy+fill" if rank == "buy" else "Fill"
    print(f"{'#':>2}  {'Crate':<25} {'Favor':>5}  {'Crate MV':>10} {'Crate MB':>10}  "
          f"{'Fill MV':>10} {'Fill MB':>10}  {lab + '/Fv MV':>14} {lab + '/Fv MB':>14}  Bundle")
    for i, r in enumerate(rows, 1):
        favor = f"{r['favor']}{'*' if r['expected'] else ''}"
        print(f"{i:>2}  {r['name']:<25} {favor:>5}  "
              f"{fmt(r['crate']['m']):>10} {fmt(r['crate']['n']):>10}  "
              f"{fmt(r['fill']['m']):>10} {fmt(r['fill']['n']):>10}  "
              f"{fmt(metric(r, 'm', rank)):>14} {fmt(metric(r, 'n', rank)):>14}  "
              f"{bundle_label(r['bundle'][basis])}")
    print("\n* Artisan Favor is expected, not confirmed by players yet.")
    print("n/a = no TSM data (e.g. nothing listed for min buyout).")

    # ---- cheapest individual mats ----
    mat_ids = {i for _, _, bs in CRATES.values() for b in bs for i, _ in b}
    ref = pm if basis == "m" else pn
    mats = sorted(mat_ids, key=lambda i: (i not in ref, ref.get(i, 0)))
    print(f"\nCHEAPEST MATS (per unit, sorted by {basis_label})")
    print("-" * 70)
    print(f"  {'':<26} {'MV':>12} {'MB':>12}")
    for i in mats:
        extra = f"  ({listed[i]} listed)" if i in listed else ""
        print(f"  {ITEMS.get(i, i):<26} {fmt(pm.get(i)):>12} {fmt(pn.get(i)):>12}{extra}")

    print("\nPricing data from TradeSkillMaster - https://tradeskillmaster.com")
    print("Auction house cut and deposit are not included.\n")


if __name__ == "__main__":
    main()
