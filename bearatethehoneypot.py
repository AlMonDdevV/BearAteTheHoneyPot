#!/usr/bin/env python3
"""
BearAteTheHoneyPot - anti-honeypot guider for mass-posting Discord bots.

Before your bot posts in a channel, the guider checks it against a blacklist
and heuristics. If a channel looks like a honeypot (a trap channel that bans
anyone who posts), safe_send() silently skips it and the bot moves on.

Usage:
    await bot.load_extension("bearatethehoneypot")
    pot = bot.get_cog("BearAteTheHoneyPot")
    await pot.safe_send(channel, "your message")   # skips honeypots
"""

import asyncio
import json
import os
import re
import time
from collections import defaultdict
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# ---------------- configuration ----------------
HONEYPOT_DB = "honeypots.json"          # blacklist storage path
RESCAN_INTERVAL = 1800                  # periodic rescan: 30 min
BAN_SPIKE_LIMIT = 5                     # bans that trigger a rescan
BAN_SPIKE_WINDOW = 300                  # ban-spike window: 5 min

HONEYPOT_NAME_PATTERNS = re.compile(
    r"honeypot|honeyp\d|trap|bait|banhammer|clickhere|free.?nitro.?verify",
    re.IGNORECASE,
)

# ---------------- storage ----------------
def load_honeypots() -> set:
    if os.path.exists(HONEYPOT_DB):
        try:
            with open(HONEYPOT_DB) as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def save_honeypots(hp: set) -> None:
    try:
        with open(HONEYPOT_DB, "w") as f:
            json.dump(sorted(hp), f)
    except OSError as e:
        print(f"[BearAteTheHoneyPot] failed to save blacklist: {e}")

# ---------------- the guider ----------------
class BearAteTheHoneyPot(commands.Cog):
    """Guides mass-posting bots around honeypot channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.honeypots = load_honeypots()
        self.ban_timestamps = defaultdict(list)
        self.rescan_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        self.rescan_task = asyncio.create_task(self._rescan_loop())
        print(f"[BearAteTheHoneyPot] loaded - {len(self.honeypots)} channels flagged")

    async def cog_unload(self):
        if self.rescan_task:
            self.rescan_task.cancel()

    # ---------- detection ----------
    def is_honeypot(self, channel) -> bool:
        """True if this channel looks like a honeypot - do NOT post here."""
        if channel is None:
            return False
        if channel.id in self.honeypots:
            return True
        name = getattr(channel, "name", "")
        if HONEYPOT_NAME_PATTERNS.search(name):
            return True
        guild = getattr(channel, "guild", None)
        if guild is None:
            return False
        # classic trap setup: viewable but the default role can't send
        perms = channel.permissions_for(guild.default_role)
        return not perms.send_messages and perms.view_channel

    # ---------- the core guider ----------
    async def safe_send(self, channel, content=None, **kwargs):
        """Drop-in replacement for channel.send() that skips honeypots.

        Returns the sent discord.Message, or None if the channel was skipped.
        """
        if self.is_honeypot(channel):
            guild = getattr(channel, "guild", None)
            guild_name = guild.name if guild else "unknown guild"
            print(f"[BearAteTheHoneyPot] SKIPPED #{getattr(channel, 'name', channel.id)} "
                  f"({channel.id}) in {guild_name} - honeypot detected")
            return None
        return await channel.send(content, **kwargs)

    # ---------- ban reporting ----------
    async def report_ban(self, guild_id: int, last_channel_id: Optional[int] = None):
        """Call this when your bot gets banned/kicked from a guild.
        Blacklists the last channel it posted in."""
        if last_channel_id:
            self.honeypots.add(last_channel_id)
            save_honeypots(self.honeypots)
            print(f"[BearAteTheHoneyPot] guild {guild_id} banned the bot - "
                  f"blacklisted last channel {last_channel_id}")

    # ---------- events ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.is_honeypot(message.channel):
            # warn the user (classic honeypots auto-ban anyone who posts)
            try:
                await message.author.send(
                    "⚠️ Heads up: the channel you just posted in is flagged "
                    "as a honeypot - you may be auto-banned. Be careful."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user):
        # mass instant-bans in a guild = honeypot country; rescan channels
        now = time.time()
        self.ban_timestamps[guild.id].append(now)
        recent = [t for t in self.ban_timestamps[guild.id] if now - t < BAN_SPIKE_WINDOW]
        self.ban_timestamps[guild.id] = recent
        if len(recent) >= BAN_SPIKE_LIMIT:
            print(f"[BearAteTheHoneyPot] ban spike in {guild.name} - rescanning channels")
            for ch in guild.text_channels:
                if self.is_honeypot(ch):
                    self.honeypots.add(ch.id)
            save_honeypots(self.honeypots)

    # ---------- periodic rescan ----------
    async def _rescan_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                for guild in self.bot.guilds:
                    for ch in guild.text_channels:
                        if self.is_honeypot(ch):
                            self.honeypots.add(ch.id)
                save_honeypots(self.honeypots)
            except Exception as e:
                print(f"[BearAteTheHoneyPot] rescan error: {e}")
            await asyncio.sleep(RESCAN_INTERVAL)

    # ---------- slash commands ----------
    @app_commands.command(name="flag_honeypot", description="Flag a channel as a honeypot")
    @app_commands.checks.has_permissions(administrator=True)
    async def flag_honeypot(self, interaction: discord.Interaction,
                            channel: discord.TextChannel):
        self.honeypots.add(channel.id)
        save_honeypots(self.honeypots)
        await interaction.response.send_message(
            f"🐻 {channel.mention} added to the honeypot blacklist.", ephemeral=True
        )

    @app_commands.command(name="unflag", description="Remove a channel from the honeypot blacklist")
    @app_commands.checks.has_permissions(administrator=True)
    async def unflag(self, interaction: discord.Interaction,
                     channel: discord.TextChannel):
        self.honeypots.discard(channel.id)
        save_honeypots(self.honeypots)
        await interaction.response.send_message(
            f"{channel.mention} removed from the honeypot blacklist.", ephemeral=True
        )

    @app_commands.command(name="honeypots", description="List flagged honeypot channels")
    async def list_honeypots(self, interaction: discord.Interaction):
        chans = [f"<#{cid}>" for cid in self.honeypots]
        await interaction.response.send_message(
            "🍯 Honeypot blacklist:\n" + ("\n".join(chans) if chans else "none flagged"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BearAteTheHoneyPot(bot))
