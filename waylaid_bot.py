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

from waylaid_crate_calc import (BASE, CRATES, ITEMS, build_rows, bundle_label, fmt,
                                metric, parse_prices, sort_rows)

CACHE_SECONDS = 30 * 60          # TSM only refreshes every few hours
_cache = {}                      # url -> (timestamp, market, minbuyout, names)


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "waylaid-bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


async def get_prices(region, gtype, faction):
    """Returns (market_prices, minbuyout_prices, names). Cached for CACHE_SECONDS."""
    url = f"{BASE}/forever/{region}/realm/{gtype}-{faction}/items.csv"
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2], hit[3]
    text = await asyncio.to_thread(_download, url)
    pm, _l, names = parse_prices(text, "market", quiet=True)
    pn, _l2, _n = parse_prices(text, "min", quiet=True)
    _cache[url] = (time.time(), pm, pn, names)
    return pm, pn, names


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
    basis = "n" if (price and price.value == "min") else "m"
    try:
        pm, pn, names = await get_prices(region_v, type_v, faction_v)
    except Exception as e:  # noqa: BLE001
        await interaction.followup.send(f"Couldn't fetch TSM data: `{e}`")
        return

    rows = build_rows(pm, pn, names)
    rows = [r for r in rows if r["fill"]["m"] is not None or r["fill"]["n"] is not None]
    if rank:
        rank_v = rank.value
    else:
        rank_v = "buy" if any(r["crate"][basis] is not None for r in rows) else "fill"
    rows = sort_rows(rows, basis, rank_v)[:top]

    lines = []
    for i, r in enumerate(rows, 1):
        favor = f"{r['favor']}{'*' if r['expected'] else ''}"
        lab = "buy+fill" if rank_v == "buy" else "fill"
        lines.append(
            f"{i:>2}. {r['name']} ({favor} Favor)\n"
            f"    {lab}/Favor  MV {fmt(metric(r, 'm', rank_v))} | MB {fmt(metric(r, 'n', rank_v))}\n"
            f"    crate       MV {fmt(r['crate']['m'])} | MB {fmt(r['crate']['n'])}\n"
            f"    fill        MV {fmt(r['fill']['m'])} | MB {fmt(r['fill']['n'])}  "
            f"({bundle_label(r['bundle'][basis])})")

    base_label = "min buyout" if basis == "n" else "market value"
    title = (f"Waylaid Crates - {region_v.upper()} {type_v} {faction_v.capitalize()} "
             f"(by {'buy + fill' if rank_v == 'buy' else 'fill only'}, {base_label})")
    desc = "```\n" + "\n".join(lines) + "\n```"
    if len(desc) > 4000:   # Discord embed description limit is 4096
        desc = desc[:3990] + "\n...```"
    embed = discord.Embed(title=title[:256], description=desc, colour=discord.Colour.gold())
    embed.set_footer(text="MV = market value, MB = min buyout | * Artisan Favor unconfirmed | "
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
    basis = "n" if (price and price.value == "min") else "m"
    try:
        pm, pn, _ = await get_prices(region_v, type_v, faction_v)
    except Exception as e:  # noqa: BLE001
        await interaction.followup.send(f"Couldn't fetch TSM data: `{e}`")
        return

    ref = pn if basis == "n" else pm
    mat_ids = {i for _, _, bs in CRATES.values() for b in bs for i, _ in b}
    ranked = sorted((i for i in mat_ids if i in ref), key=lambda i: ref[i])[:top]
    lines = [f"{'':<24} {'MV':>11} {'MB':>11}"]
    lines += [f"{ITEMS.get(i, i):<24} {fmt(pm.get(i)):>11} {fmt(pn.get(i)):>11}" for i in ranked]
    embed = discord.Embed(
        title=f"Cheapest mats - {region_v.upper()} {type_v} {faction_v.capitalize()} "
              f"(by {'min buyout' if basis == 'n' else 'market value'})",
        description="```\n" + "\n".join(lines) + "\n```", colour=discord.Colour.gold())
    embed.set_footer(text="MV = market value, MB = min buyout | Data: TradeSkillMaster")
    await interaction.followup.send(embed=embed)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set the DISCORD_TOKEN environment variable first.")
    bot.run(token)