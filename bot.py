import io
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import aiohttp

try:
    import discord
    from discord import app_commands
    from discord.ext import commands, tasks
except ImportError:
    print()
    print("  discord.py is not installed.")
    print("  Run: pip install discord.py")
    print()
    sys.exit(1)

KEYWORD = "#gaming"
CLAN_FRIEND_ROLE = "Clan Friend"

# Maps raw TempleOSRS skill/boss names to display names
PVM_NAME_MAP = {
    "Clue_beginner": "Beginner Clues",
    "Clue_easy":     "Easy Clues",
    "Clue_medium":   "Medium Clues",
    "Clue_hard":     "Hard Clues",
    "Clue_elite":    "Elite Clues",
    "Clue_master":   "Master Clues",
}


def pvm_display(raw_name: str) -> tuple[str, str]:
    """Return (display_name, verb) for a PVM achievement skill name."""
    display = PVM_NAME_MAP.get(raw_name, raw_name.replace("_", " "))
    verb = "completed" if "clue" in raw_name.lower() else "kills"
    return display, verb


def load_env():
    """Load key=value pairs from .env file next to this script."""
    env = {}
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def require_role(*role_names: str):
    """App command check: user must have at least one of the given role names."""
    async def predicate(interaction: discord.Interaction) -> bool:
        member_roles = {r.name for r in interaction.user.roles}
        if member_roles & set(role_names):
            return True
        embed = discord.Embed(
            title="Access Denied",
            description="You need the **Admin** or **Moderator** role to use this command.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    return app_commands.check(predicate)


async def run_monday_scan(bot: commands.Bot, channel_id: int, after_message_id: int, limit: int) -> dict:
    """
    Scan a channel for #gaming giveaway entries after a given message ID.
    Returns a dict with keys: fetched, entries, unique, regular, clan_friends, error.
    """
    blacklist = set(read_blacklist())

    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    except discord.NotFound:
        return {"error": f"Channel `{channel_id}` not found. Check the channel ID and make sure the bot is in the server."}
    except discord.Forbidden:
        return {"error": "The bot doesn't have permission to view that channel."}

    after_msg = discord.Object(id=after_message_id)
    entries = []
    fetched = 0

    try:
        async for msg in channel.history(after=after_msg, limit=limit, oldest_first=True):
            fetched += 1
            if KEYWORD in msg.content:
                if str(msg.author.id) in blacklist:
                    continue
                is_clan_friend = any(
                    role.name == CLAN_FRIEND_ROLE for role in getattr(msg.author, "roles", [])
                )
                entries.append({
                    "User": msg.author.display_name,
                    "UserId": str(msg.author.id),
                    "ClanFriend": is_clan_friend,
                })
    except discord.Forbidden:
        return {"error": "The bot doesn't have permission to read message history in that channel."}

    # Deduplicate: keep first entry per user
    seen = set()
    unique_entries = []
    for entry in entries:
        if entry["UserId"] not in seen:
            seen.add(entry["UserId"])
            unique_entries.append(entry)

    clan_friends = [e for e in unique_entries if e["ClanFriend"]]
    regular = [e for e in unique_entries if not e["ClanFriend"]]

    return {
        "fetched": fetched,
        "entries": len(entries),
        "unique": len(unique_entries),
        "regular": regular,
        "clan_friends": clan_friends,
        "error": None,
    }


BLACKLIST_PATH = Path(__file__).parent / "blacklist.txt"


def read_blacklist() -> list[str]:
    if not BLACKLIST_PATH.exists():
        return []
    return [line.strip() for line in BLACKLIST_PATH.read_text().splitlines() if line.strip()]


def write_blacklist(names: list[str]):
    BLACKLIST_PATH.write_text("\n".join(names) + ("\n" if names else ""), encoding="utf-8")


LAST_ACHIEVEMENT_PATH = Path(__file__).parent / "last_achievement.txt"
ICONS_DIR = Path(__file__).parent / "icons"


async def cache_image(session: aiohttp.ClientSession, url: str):
    """Download an image if not already cached. Returns (discord.File, attachment_url) or (None, None)."""
    if not url:
        return None, None
    filename = Path(url.split("?")[0]).name
    local_path = ICONS_DIR / filename
    if not local_path.exists():
        ICONS_DIR.mkdir(exist_ok=True)
        try:
            async with session.get(url, headers={"Accept-Encoding": "gzip, deflate"}) as resp:
                if resp.status == 200:
                    local_path.write_bytes(await resp.read())
                else:
                    return None, None
        except Exception:
            return None, None
    return discord.File(local_path, filename=filename), f"attachment://{filename}"


def read_last_achievement_date() -> str:
    if LAST_ACHIEVEMENT_PATH.exists():
        return LAST_ACHIEVEMENT_PATH.read_text().strip()
    return ""


def write_last_achievement_date(date: str):
    LAST_ACHIEVEMENT_PATH.write_text(date, encoding="utf-8")


def format_xp(xp: int) -> str:
    return f"{xp:,} XP"


def main():
    env = load_env()
    token = env.get("DISCORD_BOT_TOKEN")

    if not token:
        print()
        print("  No bot token found.")
        print("  Fix: Open the .env file and set DISCORD_BOT_TOKEN to your bot's token.")
        print()
        sys.exit(1)

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.tree.command(name="monday", description="Collect #gaming giveaway entries from the channel")
    @app_commands.describe(
        after_message_id="Only count entries after this message ID",
        channel="Channel ID override (uses .env default if omitted)",
        limit="Max messages to scan (default 1000)",
    )

    @require_role("Admin", "Moderator")
    async def monday_command(
        interaction: discord.Interaction,
        after_message_id: str,
        channel: Optional[str] = None,
        limit: int = 1000,
    ):
        # Validate after_message_id
        try:
            after_id = int(after_message_id)
        except ValueError:
            embed = discord.Embed(
                title="Invalid Message ID",
                description=f"`{after_message_id}` is not a valid ID.\nRight-click the target message > **Copy Message ID**.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Resolve channel ID
        raw_channel = channel or env.get("DISCORD_CHANNEL_ID")
        try:
            channel_id = int(raw_channel)
        except (TypeError, ValueError):
            embed = discord.Embed(
                title="No Channel Set",
                description="No valid channel ID was provided and none was found in `.env`.\nPass a `channel` argument or set `DISCORD_CHANNEL_ID` in the `.env` file.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Defer while the scan runs (can take several seconds)
        await interaction.response.defer()

        result = await run_monday_scan(interaction.client, channel_id, after_id, limit)

        if result.get("error"):
            embed = discord.Embed(
                title="Scan Failed",
                description=result["error"],
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)
            return

        embed = discord.Embed(title="Monday Giveaway Results", color=discord.Color.blue())
        embed.add_field(name="Messages Scanned", value=str(result["fetched"]), inline=True)
        embed.add_field(name=f"`{KEYWORD}` Matches", value=str(result["entries"]), inline=True)
        embed.add_field(name="Unique Entrants", value=str(result["unique"]), inline=True)
        embed.add_field(name="Regular", value=str(len(result["regular"])), inline=True)
        embed.add_field(name="Clan Friend", value=str(len(result["clan_friends"])), inline=True)

        if not result["unique"]:
            embed.description = "No entries found."
            await interaction.followup.send(embed=embed)
            return

        files = []
        if result["regular"]:
            content = "\n".join(e["User"] for e in result["regular"]).encode("utf-8")
            files.append(discord.File(io.BytesIO(content), filename="monday-entries.txt"))
        if result["clan_friends"]:
            content = "\n".join(e["User"] for e in result["clan_friends"]).encode("utf-8")
            files.append(discord.File(io.BytesIO(content), filename="monday-entries-clan-friend.txt"))

        await interaction.followup.send(embed=embed)
        await interaction.followup.send(files=files)

    @bot.tree.command(name="monday-blacklist-add", description="Add a user to the giveaway blacklist")
    @app_commands.describe(user="The user to blacklist")
    @require_role("Admin", "Moderator")
    async def blacklist_add(interaction: discord.Interaction, user: discord.Member):
        ids = read_blacklist()
        if str(user.id) in ids:
            embed = discord.Embed(description=f"{user.mention} is already in the blacklist.", color=discord.Color.yellow())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        ids.append(str(user.id))
        write_blacklist(ids)
        embed = discord.Embed(description=f"{user.mention} has been added to the blacklist.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="monday-blacklist-remove", description="Remove a user from the giveaway blacklist")
    @app_commands.describe(user="The user to remove")
    @require_role("Admin", "Moderator")
    async def blacklist_remove(interaction: discord.Interaction, user: discord.Member):
        ids = read_blacklist()
        if str(user.id) not in ids:
            embed = discord.Embed(description=f"{user.mention} is not in the blacklist.", color=discord.Color.yellow())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        ids = [i for i in ids if i != str(user.id)]
        write_blacklist(ids)
        embed = discord.Embed(description=f"{user.mention} has been removed from the blacklist.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="monday-blacklist-list", description="Show all users in the giveaway blacklist")
    @require_role("Admin", "Moderator")
    async def blacklist_list(interaction: discord.Interaction):
        ids = read_blacklist()
        if not ids:
            embed = discord.Embed(description="The blacklist is empty.", color=discord.Color.blue())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Blacklist — {len(ids)} user{'s' if len(ids) != 1 else ''}",
            description="\n".join(f"<@{i}>" for i in ids),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="temple", description="Look up a player's EHP gains on TempleOSRS")
    @app_commands.describe(username="OSRS username", period="Time period to check")
    @app_commands.choices(period=[
        app_commands.Choice(name="day",   value="day"),
        app_commands.Choice(name="week",  value="week"),
        app_commands.Choice(name="month", value="month"),
        app_commands.Choice(name="year",  value="year"),
    ])
    async def temple_command(interaction: discord.Interaction, username: str, period: app_commands.Choice[str]):
        await interaction.response.defer()

        try:
            url = f"https://templeosrs.com/api/player_gains.php?player={username}&time={period.value}"
            headers = {"Accept-Encoding": "gzip, deflate"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        embed = discord.Embed(
                            title="Request Failed",
                            description=f"TempleOSRS returned status `{resp.status}`.",
                            color=discord.Color.red(),
                        )
                        await interaction.followup.send(embed=embed)
                        return
                    data = await resp.json(content_type=None)

            if "Error" in data or "error" in data:
                embed = discord.Embed(
                    title="Player Not Found",
                    description=f"`{username}` was not found on TempleOSRS.\nMake sure the username is correct and has been tracked.",
                    color=discord.Color.red(),
                )
                await interaction.followup.send(embed=embed)
                return

            player_data = data.get("data", {})
            primary_key = player_data.get("Primary_ehp", "Ehp")
            ehp = player_data.get(primary_key, 0)

            try:
                ehp_display = f"{float(ehp):,.2f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                ehp_display = str(ehp)

            profile_url = f"https://templeosrs.com/player/overview.php?player={quote_plus(username)}&duration={period.value}"
            embed = discord.Embed(
                description=f"**{username}** is currently on a **{ehp_display} EHP** {period.name.lower()}!\n[View it on TempleOSRS]({profile_url})",
                color=discord.Color.blue(),
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="Something went wrong",
                description=f"```{e}```",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)

    @tasks.loop(minutes=5)
    async def check_achievements():
        group_id = env.get("TEMPLE_GROUP_ID")
        channel_id = env.get("TEMPLE_ACHIEVEMENTS_CHANNEL_ID")
        if not group_id or not channel_id:
            return

        try:
            channel_id_int = int(channel_id)
        except ValueError:
            return

        channel = bot.get_channel(channel_id_int)
        if not channel:
            return

        try:
            url = f"https://templeosrs.com/api/group_achievements.php?id={group_id}"
            headers = {"Accept-Encoding": "gzip, deflate"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json(content_type=None)

                achievements = data if isinstance(data, list) else data.get("data", [])
                if not achievements:
                    return

                last_date = read_last_achievement_date()

                # First run — just save the latest date, don't post anything
                if not last_date:
                    write_last_achievement_date(achievements[0]["Date"])
                    return

                new_entries = [a for a in achievements if a["Date"] > last_date]
                if not new_entries:
                    return

                # Post oldest first
                for achievement in reversed(new_entries):
                    skill_icon_path = achievement.get("Icon", "")
                    skill_url = f"https://templeosrs.com{skill_icon_path}" if skill_icon_path else ""
                    icon_file, icon_attachment = await cache_image(session, skill_url)
                    logo_file, logo_attachment = await cache_image(session, env.get("CLAN_LOGO_URL", ""))
                    skill = achievement["Skill"]
                    xp_raw = achievement.get("Xp", 0)
                    achievement_type = achievement.get("Type", "").lower()
                    if skill.upper() == "EHP":
                        try:
                            ehp_val = float(xp_raw)
                            ehp_display = f"{ehp_val:,.2f}".rstrip("0").rstrip(".")
                        except (TypeError, ValueError):
                            ehp_display = str(xp_raw)
                        description = f"**{achievement['Username']}** reached **{ehp_display} EHP**!"
                    elif achievement_type == "pvm":
                        pvm_name, verb = pvm_display(skill)
                        description = f"**{achievement['Username']}** reached **{int(xp_raw):,} {pvm_name} {verb}**!"
                    else:
                        description = f"**{achievement['Username']}** reached **{format_xp(int(xp_raw))}** in **{skill}**!"
                    embed = discord.Embed(
                        description=description,
                        color=discord.Color.blue(),
                    )
                    embed.set_author(name="New Achievement!", icon_url=logo_attachment or None)
                    if icon_attachment:
                        embed.set_thumbnail(url=icon_attachment)
                    files = [f for f in [logo_file, icon_file] if f]
                    await channel.send(embed=embed, files=files)

                write_last_achievement_date(new_entries[0]["Date"])
        except Exception:
            return

    @bot.event
    async def on_ready():
        guild_id = env.get("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
        if not check_achievements.is_running():
            poll_minutes = max(1, int(env.get("TEMPLE_POLL_MINUTES", 5)))
            check_achievements.change_interval(minutes=poll_minutes)
            check_achievements.start()
        print(f"Logged in as {bot.user}")
        print("Slash commands synced.")

    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        print()
        print("  Login failed — the bot token is invalid or expired.")
        print("  Fix: Go to Discord Developer Portal > Your App > Bot > Reset Token")
        print("  Then paste the new token into your .env file.")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
