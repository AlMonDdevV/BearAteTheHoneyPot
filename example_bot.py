#!/usr/bin/env python3
"""
Example bot showing BearAteTheHoneyPot integration.

Slash commands:
  /post <channel> <message>   post into one channel, guarded by the bear
  /mass_post <message>        post into every channel in every server,
                              skipping honeypots (admin only)

The token is read from the DISCORD_TOKEN environment variable, or from a
.env file next to this script if the env var is not set.
"""

import asyncio
import os
from typing import Optional

import discord
from discord.ext import commands


def load_token() -> Optional[str]:
    """Read the bot token from the environment, or from a local .env file."""
    token = os.getenv("DISCORD_TOKEN")
    if token:
        return token.strip()
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DISCORD_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class ExampleBot(commands.Bot):
    async def setup_hook(self):
        await self.load_extension("bearatethehoneypot")
        await self.tree.sync()


bot = ExampleBot(command_prefix="!", intents=intents)


@bot.tree.command(name="post", description="Post a message (honeypot-guarded)")
async def post(interaction: discord.Interaction, channel: discord.TextChannel,
               message: str):
    pot = bot.get_cog("BearAteTheHoneyPot")
    sent = await pot.safe_send(channel, message)
    if sent:
        await interaction.response.send_message(f"✅ posted in {channel.mention}",
                                                ephemeral=True)
    else:
        await interaction.response.send_message(
            f"🐻 skipped {channel.mention} - honeypot detected!", ephemeral=True
        )


@bot.tree.command(name="mass_post", description="Post everywhere, skipping honeypots")
async def mass_post(interaction: discord.Interaction, message: str):
    if interaction.guild is None or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admins only (in a server).", ephemeral=True)
        return

    await interaction.response.send_message("🐻 leading the way...", ephemeral=True)
    pot = bot.get_cog("BearAteTheHoneyPot")

    sent, skipped = 0, 0
    for guild in bot.guilds:
        for channel in guild.text_channels:
            result = await pot.safe_send(channel, message)
            if result:
                sent += 1
            else:
                skipped += 1
            await asyncio.sleep(1.5)  # respect rate limits!

    print(f"[example] done: {sent} sent, {skipped} honeypots skipped")


if __name__ == "__main__":
    token = load_token()
    if not token:
        raise SystemExit(
            "No token found. Set the DISCORD_TOKEN environment variable "
            "or create a .env file with DISCORD_TOKEN=your-token"
        )
    bot.run(token)
