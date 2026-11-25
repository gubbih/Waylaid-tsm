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


def _result_embeds(title, entries, footer):
    """Build paginated embeds with inline fields arranged as a responsive grid."""
    page_size = 9
    pages = [entries[i:i + page_size] for i in range(0, len(entries), page_size)]
    if not pages:
        pages = [[("Results", "No matching results found.")]]

    embeds = []
    for page_number, page in enumerate(pages, 1):
        page_title = title
        if len(pages) > 1:
            page_title += f" · {page_number}/{len(pages)}"
        embed = discord.Embed(title=page_title, colour=discord.Colour.gold())
        for name, value in page:
            embed.add_field(name=name, value=value, inline=True)
        embed.set_footer(text=footer)
        embeds.append(embed)
    return embeds


def _crate_table_embeds(title, headers, rows, footer):
    page_size = 10
    pages = [rows[i:i + page_size] for i in range(0, len(rows), page_size)]
    if not pages:
        pages = [[["No matching results"] + [""] * (len(headers) - 1)]]

    embeds = []
    for page_number, page in enumerate(pages, 1):
        table_rows = [headers, *page]
        widths = [
            max(len(row[column]) for row in table_rows)
            for column in range(len(headers))
        ]
        lines = [
            " | ".join(
                cell.rjust(widths[column]) if 0 < column < len(headers) - 1
                else cell.ljust(widths[column])
                for column, cell in enumerate(row)
            )
            for row in table_rows
        ]
        lines.insert(1, "-+-".join("-" * width for width in widths))

        page_title = title
        if len(pages) > 1:
            page_title += f" · {page_number}/{len(pages)}"
        embed = discord.Embed(
            title=page_title,
            description="```\n" + "\n".join(lines) + "\n```",
            colour=discord.Colour.gold())
        embed.set_footer(text=footer)
        embeds.append(embed)
    return embeds


def _total_cost(row, kind, rank):
    fill = row["fill"][kind]
    if fill is None:
        return None
    if rank == "fill":
        return fill
    crate = row["crate"][kind]
    return fill + crate if crate is not None else None


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
    basis = "m" if (price and price.value == "market") else "n"
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

    total_header = "Total (buy + fill)" if rank_v == "buy" else "Total (fill)"
    entries = []
    for i, r in enumerate(rows, 1):
        name = f"{i}. {r['name']} · {r['favor']}{'*' if r['expected'] else ''} Favor"
        entries.append([
            name,
            f"MV {fmt(_total_cost(r, 'm', rank_v))} / MB {fmt(_total_cost(r, 'n', rank_v))}",
            f"MV {fmt(metric(r, 'm', rank_v))} / MB {fmt(metric(r, 'n', rank_v))}",
            f"MV {fmt(r['crate']['m'])} / MB {fmt(r['crate']['n'])}",
            f"MV {fmt(r['fill']['m'])} / MB {fmt(r['fill']['n'])}",
            bundle_label(r['bundle'][basis]),
        ])

    base_label = "min buyout" if basis == "n" else "market value"
    title = (f"Waylaid Crates - {region_v.upper()} {type_v} {faction_v.capitalize()} "
             f"(by {'buy + fill' if rank_v == 'buy' else 'fill only'}, {base_label})")
    embeds = _crate_table_embeds(
        title,
        ["Crate", total_header, "Per Favor", "Crate", "Fill", "Materials"],
        entries,
        "MV = market value · MB = min buyout · * Artisan Favor unconfirmed · "
        "Data: TradeSkillMaster")
    await interaction.followup.send(embeds=embeds)


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
    basis = "m" if (price and price.value == "market") else "n"
    try:
        pm, pn, _ = await get_prices(region_v, type_v, faction_v)
    except Exception as e:  # noqa: BLE001
        await interaction.followup.send(f"Couldn't fetch TSM data: `{e}`")
        return

    ref = pn if basis == "n" else pm
    mat_ids = {i for _, _, bs in CRATES.values() for b in bs for i, _ in b}
    ranked = sorted((i for i in mat_ids if i in ref), key=lambda i: ref[i])[:top]
    entries = [
        (f"{i}. {ITEMS.get(item_id, item_id)}",
         f"**Market value**\n{fmt(pm.get(item_id))}\n"
         f"**Min buyout**\n{fmt(pn.get(item_id))}")
        for i, item_id in enumerate(ranked, 1)
    ]
    title = (f"Cheapest Materials - {region_v.upper()} {type_v} {faction_v.capitalize()} "
             f"(by {'min buyout' if basis == 'n' else 'market value'})")
    embeds = _result_embeds(
        title,
        entries,
        "Prices from TradeSkillMaster · Sorted by selected price")
    await interaction.followup.send(embeds=embeds)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set the DISCORD_TOKEN environment variable first.")
    bot.run(token)