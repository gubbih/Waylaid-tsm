#!/usr/bin/env python3
"""
Discord bot for the WoW Forever Waylaid Crate calculator.
Keep this file in the same folder as waylaid_crate_calc.py.

Setup:
    pip install -U discord.py
    export DISCORD_TOKEN="your-bot-token"      # Windows: set DISCORD_TOKEN=...
    python3 waylaid_bot.py

Slash commands:
    /crates  [region] [type] [faction] [rank] [top]
    /mats    [region] [type] [faction] [top]

Pricing data from TradeSkillMaster - https://tradeskillmaster.com
"""

import asyncio
import csv
import io
import os
import time
import urllib.request

import discord
from discord import app_commands

from waylaid_crate_calc import BASE, CRATES, ITEMS, bundle_cost, bundle_label, fmt, parse_prices

CACHE_SECONDS = 30 * 60          # TSM only refreshes every few hours
_cache = {}                      # url+price -> (timestamp, prices, names)


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "waylaid-bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


async def get_prices(region, gtype, faction, price_kind):
    url = f"{BASE}/forever/{region}/realm/{gtype}-{faction}/items.csv"
    key = (url, price_kind)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2]
    text = await asyncio.to_thread(_download, url)
    prices, _listed, names = parse_prices(text, price_kind)
    _cache[key] = (time.time(), prices, names)
    return prices, names


def build_rows(prices, names):
    rows = []
    for name, (favor, expected, bundles) in CRATES.items():
        best = None
        for b in bundles:
            c = bundle_cost(b, prices)
            if c is not None and (best is None or c < best[0]):
                best = (c, b)
        if best is None:
            continue
        cid = names.get(f"waylaid crate: {name}".lower())
        rows.append({"name": name, "favor": favor, "expected": expected,
                     "fill": best[0], "bundle": best[1],
                     "crate": prices.get(cid) if cid else None})
    return rows


# ---------------------------------------------------------------- bot
class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()   # global sync; can take a few minutes to appear


bot = Bot()

REGION = [app_commands.Choice(name="EU", value="eu"), app_commands.Choice(name="US", value="us")]
TYPE = [app_commands.Choice(name=n, value=v) for n, v in
        [("Normal", "normal"), ("PvP", "pvp"), ("Roleplay", "roleplay"),
         ("Roleplay PvP", "roleplay-pvp")]]
FACTION = [app_commands.Choice(name="Horde", value="horde"),
           app_commands.Choice(name="Alliance", value="alliance")]
RANK = [app_commands.Choice(name="Buy + fill per Favor", value="buy"),
        app_commands.Choice(name="Fill cost per Favor (own the crate)", value="fill")]
PRICE = [app_commands.Choice(name="Market value", value="market"),
         app_commands.Choice(name="Min buyout", value="min")]


@bot.tree.command(name="crates", description="Cheapest Merchant's Favor from Waylaid Crates")
@app_commands.choices(region=REGION, game_type=TYPE, faction=FACTION, rank=RANK, price=PRICE)
async def crates(interaction: discord.Interaction,
                 region: app_commands.Choice[str] = None,
                 game_type: app_commands.Choice[str] = None,
                 faction: app_commands.Choice[str] = None,
                 rank: app_commands.Choice[str] = None,
                 price: app_commands.Choice[str] = None,
                 top: app_commands.Range[int, 1, 30] = 10):
    await interaction.response.defer()
    region_v = region.value if region else "eu"
    type_v = game_type.value if game_type else "normal"
    faction_v = faction.value if faction else "horde"
    price_v = price.value if price else "market"
    try:
        prices, names = await get_prices(region_v, type_v, faction_v, price_v)
    except Exception as e:  # noqa: BLE001
        await interaction.followup.send(f"Couldn't fetch TSM data: `{e}`")
        return

    rows = build_rows(prices, names)
    rank_v = rank.value if rank else ("buy" if any(r["crate"] for r in rows) else "fill")
    if rank_v == "buy":
        priced = sorted((r for r in rows if r["crate"] is not None),
                        key=lambda r: (r["fill"] + r["crate"]) / r["favor"])
        unpriced = sorted((r for r in rows if r["crate"] is None),
                          key=lambda r: r["fill"] / r["favor"])
        rows = priced + unpriced
    else:
        rows.sort(key=lambda r: r["fill"] / r["favor"])
    rows = rows[:top]

    lines = []
    for i, r in enumerate(rows, 1):
        favor = f"{r['favor']}{'*' if r['expected'] else ''}"
        if r["crate"] is not None:
            bf = fmt((r["fill"] + r["crate"]) / r["favor"])
            lines.append(f"{i:>2}. {r['name']} ({favor} Favor)\n"
                         f"    buy+fill {bf}/Favor | crate {fmt(r['crate'])} | "
                         f"fill {fmt(r['fill'])} ({bundle_label(r['bundle'])})")
        else:
            lines.append(f"{i:>2}. {r['name']} ({favor} Favor)\n"
                         f"    fill {fmt(r['fill'] / r['favor'])}/Favor | "
                         f"fill {fmt(r['fill'])} ({bundle_label(r['bundle'])}) | crate price n/a")

    title = (f"Waylaid Crates - {region_v.upper()} {type_v} {faction_v.capitalize()} "
             f"({'buy + fill' if rank_v == 'buy' else 'fill only'} per Favor)")
    embed = discord.Embed(title=title, description="```\n" + "\n".join(lines) + "\n```",
                          colour=discord.Colour.gold())
    embed.set_footer(text="* Artisan Favor unconfirmed | AH cut/deposit not included | "
                          "Data: TradeSkillMaster (tradeskillmaster.com)")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="mats", description="Cheapest Waylaid Crate materials (per unit)")
@app_commands.choices(region=REGION, game_type=TYPE, faction=FACTION, price=PRICE)
async def mats(interaction: discord.Interaction,
               region: app_commands.Choice[str] = None,
               game_type: app_commands.Choice[str] = None,
               faction: app_commands.Choice[str] = None,
               price: app_commands.Choice[str] = None,
               top: app_commands.Range[int, 1, 31] = 10):
    await interaction.response.defer()
    region_v = region.value if region else "eu"
    type_v = game_type.value if game_type else "normal"
    faction_v = faction.value if faction else "horde"
    price_v = price.value if price else "market"
    try:
        prices, _ = await get_prices(region_v, type_v, faction_v, price_v)
    except Exception as e:  # noqa: BLE001
        await interaction.followup.send(f"Couldn't fetch TSM data: `{e}`")
        return

    mat_ids = {i for _, _, bs in CRATES.values() for b in bs for i, _ in b}
    ranked = sorted((prices[i], i) for i in mat_ids if i in prices)[:top]
    lines = [f"{ITEMS.get(i, i):<24} {fmt(p):>12}" for p, i in ranked]
    embed = discord.Embed(
        title=f"Cheapest mats - {region_v.upper()} {type_v} {faction_v.capitalize()}",
        description="```\n" + "\n".join(lines) + "\n```", colour=discord.Colour.gold())
    embed.set_footer(text="Data: TradeSkillMaster (tradeskillmaster.com)")
    await interaction.followup.send(embed=embed)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set the DISCORD_TOKEN environment variable first.")
    bot.run(token)