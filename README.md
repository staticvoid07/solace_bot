# Solace Bot

A Discord bot for managing Monday giveaway entries and TempleOSRS clan stats.

---

## Prerequisites

- [Python 3.10+](https://www.python.org/downloads/)
- [Git](https://git-scm.com/)
- A Discord bot token ([guide below](#1-create-the-discord-bot))

---

## Setup

### 1. Create the Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**
2. Give it a name, then go to the **Bot** tab
3. Click **Reset Token** and copy the token — you'll need it in a later step
4. Under **Privileged Gateway Intents**, enable:
   - **Server Members Intent**
   - **Message Content Intent**
5. Save changes

### 2. Invite the bot to your server

1. Go to **OAuth2 > URL Generator**
2. Under **Scopes**, check: `bot` and `applications.commands`
3. Under **Bot Permissions**, check:
   - Read Messages / View Channels
   - Read Message History
   - Send Messages
   - Attach Files
4. Copy the generated URL, open it in your browser, and invite the bot to your server

### 3. Clone the repo

```bash
git clone https://github.com/staticvoid07/solace_bot.git
cd solace_bot
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure the bot

Create a `.env` file in the project folder:

```
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_CHANNEL_ID=your_giveaway_channel_id
DISCORD_GUILD_ID=your_server_id
TEMPLE_GROUP_ID=your_templeosrs_group_id
TEMPLE_ACHIEVEMENTS_CHANNEL_ID=your_achievements_channel_id
TEMPLE_POLL_MINUTES=5
```

**How to get these values:**

| Key | How to get it |
|-----|--------------|
| `DISCORD_BOT_TOKEN` | Discord Developer Portal > Your App > Bot > Token |
| `DISCORD_CHANNEL_ID` | Right-click the giveaway channel > Copy Channel ID |
| `DISCORD_GUILD_ID` | Right-click your server icon > Copy Server ID |
| `TEMPLE_GROUP_ID` | Your group's ID on [TempleOSRS](https://templeosrs.com) |
| `TEMPLE_ACHIEVEMENTS_CHANNEL_ID` | Right-click the achievements channel > Copy Channel ID |
| `TEMPLE_POLL_MINUTES` | How often (in minutes) to check for new achievements |

> To copy IDs in Discord, enable **Developer Mode** first: Settings > Advanced > Developer Mode

Leave `TEMPLE_ACHIEVEMENTS_CHANNEL_ID` empty to disable achievement posting.

### 6. Run the bot

```bash
python bot.py
```

You should see:
```
Logged in as YourBot#1234
Slash commands synced.
```

---

## Commands

| Command | Description | Who can use it |
|---------|-------------|----------------|
| `/monday` | Scan a channel for `#gaming` giveaway entries | Admin, Moderator |
| `/monday-blacklist-add` | Add a user to the giveaway blacklist | Admin, Moderator |
| `/monday-blacklist-remove` | Remove a user from the blacklist | Admin, Moderator |
| `/monday-blacklist-list` | Show all blacklisted users | Admin, Moderator |
| `/temple` | Look up a player's EHP gains on TempleOSRS | Everyone |

> To restrict `/monday` commands to specific roles in Discord, go to **Server Settings > Integrations > Bots and Apps** and configure permissions there.

---

## Notes

- `blacklist.txt` and `last_achievement.txt` are created automatically on first run
- The bot deduplicates giveaway entries by user ID (one entry per person)
- Achievement polling skips the first run to avoid spamming old entries
