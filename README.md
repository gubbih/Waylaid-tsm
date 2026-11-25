WoW Forever: Waylaid Crate & Merchant's Favor Calculator

Finds the cheapest way to earn Merchant's Favor from Waylaid Crates in WoW Forever, using TradeSkillMaster public auction house prices. Works as a command-line script and as a Discord bot.

Default target: EU / Normal / Horde.

Files
File	What it is
waylaid_crate_calc.py	Command-line calculator. Also holds the crate/mat data shared with the bot.
waylaid_bot.py	Discord bot with /crates and /mats slash commands. Needs waylaid_crate_calc.py in the same folder.
requirements.txt	Python dependency for the bot (discord.py).
What it calculates

For each of the 30 Waylaid Crates it works out:

Fill cost: the cheapest bundle of materials that fills the crate.
Crate price: what the labelled crate costs on the auction house.
Buy + fill per Favor: (crate price + fill cost) / Favor the crate gives.
Fill per Favor: fill cost / Favor, for when you already own the crates.

Both TSM prices are shown side by side:

MV = market value (TSM's typical selling price, steadier).
MB = min buyout (cheapest current listing, closer to what you'd pay right now).

The list is ranked by one of them (market value by default). Items with no listing show n/a. Auction house cut and deposit are not included.

Command-line script

Requires Python 3.8+ and nothing else (standard library only).

python3 waylaid_crate_calc.py                      # EU Normal Horde, ranked by market value
python3 waylaid_crate_calc.py --price min          # rank by min buyout instead
python3 waylaid_crate_calc.py --rank fill          # rank by fill cost only (you own the crates)
python3 waylaid_crate_calc.py --rank buy           # rank by crate price + fill
python3 waylaid_crate_calc.py --top 5              # only the 5 cheapest
python3 waylaid_crate_calc.py --faction alliance --type pvp --region us
python3 waylaid_crate_calc.py --file items.csv     # use a CSV you downloaded yourself
python3 waylaid_crate_calc.py --crate-ids crates.json

Options:

Option	Values	Default
--region	eu, us	eu
--type	normal, pvp, roleplay, roleplay-pvp	normal
--faction	horde, alliance	horde
--price	market, min (which price to rank by)	market
--rank	auto, buy, fill	auto (buy + fill when crate prices exist)
--top N	number of crates to show	all
--file	path to a local items.csv	download from TSM
--crate-ids	JSON {"Crate name": item_id}, only needed if name lookup fails	none

Prices come from https://public-data.tradeskillmaster.com/forever/<region>/realm/<type>-<faction>/items.csv. No API key is needed. Crates are matched by the name Waylaid Crate: <name>.

Discord bot
1. Create the bot
Go to https://discord.com/developers/applications and create a New Application.
Open the Bot tab and click Reset Token. Copy the token and keep it private.
Open OAuth2 > URL Generator. Tick the scopes bot and applications.commands, and the permissions Send Messages and Embed Links.
Open the generated URL to add the bot to your server.

No privileged intents are required.

2. Run it
pip install -r requirements.txt
export DISCORD_TOKEN="your-token"        # Windows (cmd): set DISCORD_TOKEN=your-token
python3 waylaid_bot.py

Slash commands can take a few minutes to appear the first time.

3. Commands
/crates [region] [game_type] [faction] [rank] [price] [top] : cheapest Merchant's Favor from crates. Default: EU, Normal, Horde, top 10.
/mats [region] [game_type] [faction] [price] [top] : cheapest raw materials per unit.

TSM data is cached for 30 minutes (TSM only refreshes every few hours).

Giving the bot its token

Either set an environment variable named DISCORD_TOKEN (preferred), or, if your host has no such option, replace os.environ.get("DISCORD_TOKEN") at the bottom of waylaid_bot.py with your token in quotes. Never share the token or commit it to GitHub. If it leaks, reset it in the Developer Portal.

Hosting

The bot only works while the script is running. Notes:

Free hosts that put idle services to sleep (Render, Replit, Heroku free tiers) will knock a bot offline, because a bot holds an open connection and nothing wakes it.
Bot-specific free hosts (e.g. Wispbyte): upload both .py files and requirements.txt, set the startup file to waylaid_bot.py, and add DISCORD_TOKEN.
Oracle Cloud Always Free, a home PC / Raspberry Pi, or a cheap VPS are more reliable.
Troubleshooting
Error	Cause
ModuleNotFoundError: waylaid_crate_calc	waylaid_crate_calc.py isn't in the same folder as the bot.
ModuleNotFoundError: discord	discord.py isn't installed.
Set the DISCORD_TOKEN environment variable first	The token isn't being passed in.
LoginFailure / Improper token	Wrong or reset token. Reset it and paste the new one.
Commands don't appear	Wait a few minutes; check the bot was invited with applications.commands.
Couldn't fetch TSM data	Host blocks outbound requests, or TSM was briefly down.
Customising the data

Crate and material data lives at the top of waylaid_crate_calc.py:

ITEMS maps item IDs to names.
CRATES maps each crate to (Favor, expected, [bundles]). A bundle is a list of (item_id, quantity). Any one bundle fills the crate, and the script uses the cheapest.

To add an alternative way to fill a crate, add another bundle, for example:

python
"Journeyman Ingots": (20, False, [[(2842, 10)], [(2841, 20)]]),

Crates marked with * (the Artisan ones) use expected Favor values that players haven't confirmed yet.

Credits

Pricing data from TradeSkillMaster. Not affiliated with Blizzard Entertainment or TradeSkillMaster.