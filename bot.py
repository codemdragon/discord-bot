import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from collections import deque

logging.basicConfig(level=logging.INFO)

discord.opus.load_opus("libopus.so.0")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
executor = ThreadPoolExecutor(max_workers=2)

# --- Per-guild state ---
queues = {}
loop_mode = {}
now_playing = {}

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = deque()
    return queues[guild_id]

def get_loop(guild_id):
    return loop_mode.get(guild_id, "off")


ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_opts)


# --- Voice connection ---

async def safe_connect(channel, guild, max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        vc = guild.voice_client
        if vc:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
            await asyncio.sleep(2)

        print(f"Voice connect attempt {attempt}...")
        try:
            vc = await channel.connect(timeout=60, reconnect=False, self_deaf=True)
            await asyncio.sleep(2)
            if vc.is_connected():
                print(f"Connected on attempt {attempt}")
                return vc

        except discord.errors.ConnectionClosed as e:
            print(f"Attempt {attempt} failed with code {e.code}: {e}")
            if attempt < max_attempts:
                await asyncio.sleep(3 * attempt)

        except asyncio.TimeoutError:
            print(f"Attempt {attempt} timed out")
            if attempt < max_attempts:
                await asyncio.sleep(3 * attempt)

        except Exception as e:
            print(f"Attempt {attempt} unexpected error: {e}")
            if attempt < max_attempts:
                await asyncio.sleep(3 * attempt)

    return None


# --- Audio fetching ---

async def fetch_info(url):
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(
        executor,
        lambda: ytdl.extract_info(url, download=False)
    )
    if 'entries' in info:
        info = info['entries'][0]
    return info['url'], info.get('title', 'Unknown')


# --- Playback ---

def play_next(guild_id, vc, send_func):
    mode = get_loop(guild_id)
    queue = get_queue(guild_id)
    current = now_playing.get(guild_id)

    if mode == "one" and current:
        queue.appendleft(current)
    elif mode == "all" and current:
        queue.append(current)

    if queue:
        audio_url, title = queue.popleft()
        now_playing[guild_id] = (audio_url, title)
        source = discord.FFmpegPCMAudio(audio_url, **ffmpeg_options)
        vc.play(source, after=lambda e: play_next(guild_id, vc, send_func))
        asyncio.run_coroutine_threadsafe(
            send_func(f"Now playing: **{title}**"),
            bot.loop
        )
    else:
        now_playing[guild_id] = None


# --- Shared logic (used by both prefix and slash commands) ---

async def _play(guild, author_voice, send_func, url):
    if not author_voice:
        await send_func("You need to be in a voice channel!")
        return

    await send_func("Loading audio...")

    try:
        audio_url, title = await fetch_info(url)
    except Exception as e:
        await send_func(f"Error fetching audio: {e}")
        return

    guild_id = guild.id
    vc = guild.voice_client

    if not vc or not vc.is_connected():
        await send_func("Connecting to voice...")
        vc = await safe_connect(author_voice.channel, guild)
        if not vc:
            await send_func("Failed to connect to voice. Try again.")
            return

    queue = get_queue(guild_id)

    if vc.is_playing() or vc.is_paused():
        queue.append((audio_url, title))
        await send_func(f"Added to queue: **{title}** (position {len(queue)})")
    else:
        now_playing[guild_id] = (audio_url, title)
        source = discord.FFmpegPCMAudio(audio_url, **ffmpeg_options)
        vc.play(source, after=lambda e: play_next(guild_id, vc, send_func))
        await send_func(f"Now playing: **{title}**")


async def _queue(guild, send_func):
    guild_id = guild.id
    q = get_queue(guild_id)
    current = now_playing.get(guild_id)
    mode = get_loop(guild_id)

    if not current and not q:
        await send_func("The queue is empty.")
        return

    lines = [f"🔁 Loop mode: **{mode}**\n"]
    if current:
        lines.append(f"▶️ Now playing: **{current[1]}**")
    if q:
        lines.append("\n📋 Up next:")
        for i, (_, title) in enumerate(q, start=1):
            lines.append(f"  {i}. {title}")
    else:
        lines.append("\n📋 Queue is empty after this track.")

    await send_func("\n".join(lines))


async def _loop(guild, send_func, mode):
    guild_id = guild.id
    valid = ("off", "one", "all")

    if mode is None:
        current = get_loop(guild_id)
        await send_func(f"Current loop mode: **{current}**\nUse `off`, `one`, or `all`")
        return

    mode = mode.lower()
    if mode not in valid:
        await send_func("Invalid mode. Use: `off`, `one`, or `all`")
        return

    loop_mode[guild_id] = mode
    labels = {"off": "🔁 Loop off", "one": "🔂 Looping current track", "all": "🔁 Looping entire queue"}
    await send_func(labels[mode])


async def _skip(guild, send_func):
    vc = guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await send_func("⏭️ Skipped.")
    else:
        await send_func("Nothing is playing.")


async def _stop(guild, send_func):
    guild_id = guild.id
    queues[guild_id] = deque()
    now_playing[guild_id] = None
    vc = guild.voice_client
    if vc:
        await vc.disconnect(force=True)
        await send_func("⏹️ Stopped and disconnected.")
    else:
        await send_func("Not in a voice channel.")


async def _pause(guild, send_func):
    vc = guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await send_func("⏸️ Paused.")
    else:
        await send_func("Nothing is playing.")


async def _resume(guild, send_func):
    vc = guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await send_func("▶️ Resumed.")
    else:
        await send_func("Nothing is paused.")


async def _nowplaying(guild, send_func):
    current = now_playing.get(guild.id)
    if current:
        await send_func(f"▶️ Now playing: **{current[1]}**")
    else:
        await send_func("Nothing is playing.")


async def _remove(guild, send_func, index: int):
    guild_id = guild.id
    q = get_queue(guild_id)
    if index < 1 or index > len(q):
        await send_func(f"Invalid index. Queue has {len(q)} track(s).")
        return
    q_list = list(q)
    removed = q_list.pop(index - 1)
    queues[guild_id] = deque(q_list)
    await send_func(f"Removed: **{removed[1]}**")


async def _clearqueue(guild, send_func):
    queues[guild.id] = deque()
    await send_func("🗑️ Queue cleared.")


# =====================
# PREFIX COMMANDS (! )
# =====================

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')


@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Owner only: sync slash commands to this guild."""
    bot.tree.copy_global_to(guild=ctx.guild)
    await bot.tree.sync(guild=ctx.guild)
    await ctx.send("✅ Slash commands synced to this server!")


@bot.command()
async def play(ctx, url):
    await _play(ctx.guild, ctx.author.voice, ctx.send, url)

@bot.command()
async def queue(ctx):
    await _queue(ctx.guild, ctx.send)

@bot.command()
async def loop(ctx, mode: str = None):
    await _loop(ctx.guild, ctx.send, mode)

@bot.command()
async def skip(ctx):
    await _skip(ctx.guild, ctx.send)

@bot.command()
async def stop(ctx):
    await _stop(ctx.guild, ctx.send)

@bot.command()
async def pause(ctx):
    await _pause(ctx.guild, ctx.send)

@bot.command()
async def resume(ctx):
    await _resume(ctx.guild, ctx.send)

@bot.command()
async def nowplaying(ctx):
    await _nowplaying(ctx.guild, ctx.send)

@bot.command()
async def remove(ctx, index: int):
    await _remove(ctx.guild, ctx.send, index)

@bot.command()
async def clearqueue(ctx):
    await _clearqueue(ctx.guild, ctx.send)


# =====================
# SLASH COMMANDS (/ )
# =====================

@bot.tree.command(name="play", description="Play a song from a URL or add it to the queue")
@app_commands.describe(url="YouTube URL to play")
async def slash_play(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    await _play(interaction.guild, interaction.user.voice, interaction.followup.send, url)

@bot.tree.command(name="queue", description="Show the current queue")
async def slash_queue(interaction: discord.Interaction):
    await interaction.response.defer()
    await _queue(interaction.guild, interaction.followup.send)

@bot.tree.command(name="loop", description="Set loop mode: off, one, or all")
@app_commands.describe(mode="Loop mode: off | one | all")
@app_commands.choices(mode=[
    app_commands.Choice(name="Off", value="off"),
    app_commands.Choice(name="Loop current track", value="one"),
    app_commands.Choice(name="Loop entire queue", value="all"),
])
async def slash_loop(interaction: discord.Interaction, mode: str = None):
    await interaction.response.defer()
    await _loop(interaction.guild, interaction.followup.send, mode)

@bot.tree.command(name="skip", description="Skip the current track")
async def slash_skip(interaction: discord.Interaction):
    await interaction.response.defer()
    await _skip(interaction.guild, interaction.followup.send)

@bot.tree.command(name="stop", description="Stop playback and disconnect")
async def slash_stop(interaction: discord.Interaction):
    await interaction.response.defer()
    await _stop(interaction.guild, interaction.followup.send)

@bot.tree.command(name="pause", description="Pause the current track")
async def slash_pause(interaction: discord.Interaction):
    await interaction.response.defer()
    await _pause(interaction.guild, interaction.followup.send)

@bot.tree.command(name="resume", description="Resume the paused track")
async def slash_resume(interaction: discord.Interaction):
    await interaction.response.defer()
    await _resume(interaction.guild, interaction.followup.send)

@bot.tree.command(name="nowplaying", description="Show the currently playing track")
async def slash_nowplaying(interaction: discord.Interaction):
    await interaction.response.defer()
    await _nowplaying(interaction.guild, interaction.followup.send)

@bot.tree.command(name="remove", description="Remove a track from the queue by position")
@app_commands.describe(index="Position in the queue to remove (1-based)")
async def slash_remove(interaction: discord.Interaction, index: int):
    await interaction.response.defer()
    await _remove(interaction.guild, interaction.followup.send, index)

@bot.tree.command(name="clearqueue", description="Clear the entire queue")
async def slash_clearqueue(interaction: discord.Interaction):
    await interaction.response.defer()
    await _clearqueue(interaction.guild, interaction.followup.send)


bot.run("YOUR_BOT_TOKEN_HERE")
