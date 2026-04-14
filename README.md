# 🎵 Discord Music Bot — Raspberry Pi Setup Guide

A self-hosted Discord music bot that runs on a Raspberry Pi. Supports YouTube playback, a song queue, loop modes, and both prefix (`!`) and slash (`/`) commands.

---

## Requirements

- Raspberry Pi (any model with network access)
- Raspberry Pi OS (Bookworm or later)
- A Discord account and a server you have admin access to

---

## Step 1 — Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**
2. Give it a name, then go to the **Bot** tab on the left
3. Click **Reset Token** and copy the token somewhere safe — you'll need it later
4. Scroll down and enable all three **Privileged Gateway Intents**:
   - Presence Intent
   - Server Members Intent
   - Message Content Intent
5. Go to **OAuth2 → URL Generator**
6. Under **Scopes**, check `bot` and `applications.commands`
7. Under **Bot Permissions**, check:
   - Send Messages
   - Connect
   - Speak
   - Use Slash Commands
8. Copy the generated URL at the bottom, paste it in your browser, and invite the bot to your server

---

## Step 2 — Set Up the Raspberry Pi

SSH into your Pi or open a terminal and run the following:

### Install system dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-venv python3-pip ffmpeg libopus0 nodejs git -y
```

### Clone the repo

```bash
git clone https://github.com/codemdragon/discord-bot.git
cd discord-bot
```

### Create a virtual environment and install Python packages

```bash
python3 -m venv venv
source venv/bin/activate
pip install "discord.py[voice] @ git+https://github.com/Rapptz/discord.py" yt-dlp PyNaCl
```

> **Why install discord.py from GitHub?** The latest release (2.3.2) has a voice connection bug on Python 3.13 which ships with Raspberry Pi OS Bookworm. The GitHub version has the fix.

---

## Step 3 — Configure Your Token

Open `bot.py` and find the last line:

```python
bot.run("YOUR_BOT_TOKEN_HERE")
```

Replace `YOUR_BOT_TOKEN_HERE` with the token you copied in Step 1. Keep the quotes.

> **Keep your token secret.** Never share it or commit it to a public repo. If it gets leaked, go back to the Developer Portal and regenerate it immediately.

---

## Step 4 — Run the Bot

```bash
source venv/bin/activate  # if not already activated
python bot.py
```

You should see:
```
Logged in as YourBot#1234
```

---

## Step 5 — Register Slash Commands

Once the bot is running and online in your server, type this in any channel:

```
!sync
```

Wait a few seconds, then restart your Discord client. Type `/` and you'll see all the bot's commands appear with descriptions and options.

> You only need to do this once, or again if you add new commands.

---

## Commands

All commands work as both slash commands (`/play`) and prefix commands (`!play`).

| Command | Description |
|---|---|
| `/play <url>` | Play a YouTube URL, or add it to the queue if something's already playing |
| `/queue` | Show the current queue and loop mode |
| `/skip` | Skip the current track |
| `/loop <off/one/all>` | `off` = no loop · `one` = repeat current track · `all` = loop entire queue |
| `/pause` | Pause playback |
| `/resume` | Resume playback |
| `/nowplaying` | Show what's currently playing |
| `/remove <n>` | Remove track at position n from the queue |
| `/clearqueue` | Clear the queue (current track keeps playing) |
| `/stop` | Stop playback, clear queue, and disconnect |

---

## Running the Bot Continuously (Optional)

If you want the bot to keep running after you close your SSH session, use `screen`:

```bash
sudo apt install screen -y
screen -S musicbot
source venv/bin/activate
python bot.py
```

Then press `Ctrl+A` then `D` to detach. The bot keeps running in the background.

To come back to it later:
```bash
screen -r musicbot
```

Alternatively, you can set it up as a `systemd` service so it starts automatically on boot:

```bash
sudo nano /etc/systemd/system/musicbot.service
```

Paste this (replace `codem` with your Pi username if different):

```ini
[Unit]
Description=Discord Music Bot
After=network.target

[Service]
User=codem
WorkingDirectory=/home/codem/discord-bot
ExecStart=/home/codem/discord-bot/venv/bin/python bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable musicbot
sudo systemctl start musicbot
```

Check it's running with:
```bash
sudo systemctl status musicbot
```

---

## Troubleshooting

**Voice connection fails with error 4006**

This is a known Python 3.13 + discord.py issue. Make sure you installed discord.py from GitHub as shown in Step 2, not from pip directly.

**`libopus.so.0` not found**

Run `sudo apt install libopus0 -y`

**YouTube warning about "No supported JavaScript runtime"**

Run `sudo apt install nodejs -y` — this lets yt-dlp extract all YouTube formats correctly.

**Slash commands not showing up**

Make sure you ran `!sync` in your server while the bot was online. It can also take up to an hour for Discord to propagate them globally. Try restarting your Discord client first.

**Bot goes offline when I close SSH**

Use `screen` or set up the `systemd` service as described in the section above.
