"""
UptimeGolem - Minecraft Server Status Discord Bot
Monitors Minecraft server status and displays it in Discord voice and text channels.
Uses adaptive rate limiting to prevent Discord API rate limit violations.
"""

import discord
from discord.ext import tasks, commands
import asyncio
import time
from datetime import datetime, timedelta
from mcstatus import JavaServer
import logging
import os
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

# Load environment variables from .env file
load_dotenv()

# Configure logging
def setup_logger():
    """
    Configure logging with optional file output.
    By default only logs to console to protect SD card on Raspberry Pi.
    Enable file logging in .env with ENABLE_FILE_LOGGING=true for optional persistent logging.
    
    File logging uses RotatingFileHandler to limit log file size:
    - Max file size: 5 MB
    - Backup count: 3 (keeps max 15 MB of logs)
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # Define log format
    log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Console handler (always enabled)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    
    # File handler (optional, disabled by default to protect SD card)
    enable_file_logging = os.getenv('ENABLE_FILE_LOGGING', 'false').lower() == 'true'
    if enable_file_logging:
        log_file = 'uptimeGolem.log'
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB max file size
            backupCount=3               # Keep 3 backups (max 15 MB total)
        )
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)
        logger.info(f"✅ File logging enabled: {log_file}")
    
    return logger

logger = setup_logger()

# ==================== CONFIGURATION ====================
# Load configuration from environment variables (.env file)
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
MINECRAFT_SERVER_IP = os.getenv('MINECRAFT_SERVER_IP', '192.168.1.100')
MINECRAFT_SERVER_PORT = int(os.getenv('MINECRAFT_SERVER_PORT', 25565))
VOICE_CHANNEL_ID = int(os.getenv('VOICE_CHANNEL_ID', 0))
TEXT_CHANNEL_ID = int(os.getenv('TEXT_CHANNEL_ID', 0))
GUILD_ID = int(os.getenv('GUILD_ID', 0))

# Polling and update settings
LAN_POLL_INTERVAL = int(os.getenv('LAN_POLL_INTERVAL', 5))
INITIAL_DISCORD_UPDATE_INTERVAL = int(os.getenv('INITIAL_DISCORD_UPDATE_INTERVAL', 10))
RATE_LIMIT_THRESHOLD = float(os.getenv('RATE_LIMIT_THRESHOLD', 0.5))
OFFLINE_GRACE_PERIOD = int(os.getenv('OFFLINE_GRACE_PERIOD', 30))

# ==================== RATE LIMITER CLASS ====================
class DiscordRateLimiter:
    """
    Adaptive rate limiter for Discord API calls.
    Monitors API call timing and adjusts frequency to prevent rate limit violations.
    """

    def __init__(self, initial_interval: int, name: str = "RateLimiter"):
        """
        Initialize rate limiter.
        Args:
            initial_interval: Initial update interval in seconds
            name: Descriptive name for logging (e.g., "Voice", "Text")
        """
        self.interval = initial_interval
        self.last_update_time = 0
        self.throttled = False
        self.original_interval = initial_interval
        self.throttled_interval = initial_interval * 2  # 2x slower when throttled
        self.name = name

    async def should_update(self, client: discord.Client = None) -> bool:
        """
        Determine if an update should proceed based on timing.
        
        Args:
            client: Discord client instance (optional, for future rate limit checking)
            
        Returns:
            bool: True if update should proceed, False otherwise
        """
        current_time = time.time()
        
        # Check if enough time has passed since last update
        if current_time - self.last_update_time < self.interval:
            return False

        self.last_update_time = current_time
        return True

    def set_throttled(self, throttled: bool):
        """
        Manually set throttle state.
        
        Args:
            throttled: True to enable throttling, False to disable
        """
        self.throttled = throttled
        if throttled:
            self.interval = self.throttled_interval
            logger.warning(f"⚠️ {self.name} RATE LIMIT THROTTLE ENABLED - Interval: {self.interval}s")
        else:
            self.interval = self.original_interval
            logger.info(f"✅ {self.name} RATE LIMIT THROTTLE DISABLED - Interval: {self.interval}s")
    
    def get_time_until_next_update(self) -> float:
        """
        Get seconds until next update is allowed.
        
        Returns:
            float: Seconds remaining, or 0 if update is allowed now
        """
        current_time = time.time()
        time_since_last = current_time - self.last_update_time
        return max(0, self.interval - time_since_last)


# ==================== MINECRAFT SERVER MONITOR ====================
class MinecraftServerMonitor:
    """
    Handles Minecraft server status polling and player information retrieval.
    """

    def __init__(self, host: str, port: int):
        """
        Initialize Minecraft server monitor.
        
        Args:
            host: Minecraft server IP address
            port: Minecraft server port
        """
        self.host = host
        self.port = port
        self.server = JavaServer.lookup(f"{host}:{port}")
        self.last_status = None
        self.last_players = []
        self.last_query_time = 0

    async def query_status(self) -> dict:
        """
        Query Minecraft server status and player information.
        
        Returns:
            dict: Server status containing:
                - online: bool indicating if server is up
                - current_players: Current number of players
                - max_players: Maximum number of players
                - player_list: List of online player names
        """
        try:
            # Run blocking I/O in executor to prevent blocking async code
            loop = asyncio.get_event_loop()
            status = await loop.run_in_executor(None, self._query_server)
            
            if status:
                self.last_status = status
                logger.info(f"✅ Server online - Players: {status['current_players']}/{status['max_players']}")
            
            return status
        except Exception as e:
            logger.error(f"❌ Failed to query server: {e}")
            return {
                'online': False,
                'current_players': 0,
                'max_players': 0,
                'player_list': []
            }

    def _query_server(self) -> dict:
        """
        Internal blocking method to query Minecraft server.
        Should be run in executor.
        
        Returns:
            dict: Server status information
        """
        try:
            status = self.server.status()
            
            # Extract player information
            player_list = []
            if status.players.sample:
                player_list = [player.name for player in status.players.sample]
            
            return {
                'online': True,
                'current_players': status.players.online,
                'max_players': status.players.max,
                'player_list': player_list,
                'latency': status.latency
            }
        except Exception as e:
            logger.error(f"Server query failed: {e}")
            return {
                'online': False,
                'current_players': 0,
                'max_players': 0,
                'player_list': []
            }


# ==================== DISCORD BOT CLASS ====================
class UptimeGolemBot(commands.Cog):
    """
    Main Discord bot cog for Minecraft server status monitoring.
    """

    def __init__(self, client: commands.Bot):
        """
        Initialize bot cog.
        
        Args:
            client: Discord bot instance
        """
        self.client = client
        self.monitor = MinecraftServerMonitor(MINECRAFT_SERVER_IP, MINECRAFT_SERVER_PORT)
        
        # Separate rate limiters for voice (1 rename per 5 min = 300s) and text (5s per update)
        self.voice_rate_limiter = DiscordRateLimiter(initial_interval=300, name="Voice")
        self.text_rate_limiter = DiscordRateLimiter(initial_interval=5, name="Text")

        # Offline grace handling to avoid marking the server offline during wake-up
        self.offline_grace_period = OFFLINE_GRACE_PERIOD
        self.offline_detected_at = None
        
        # Track last known state to detect changes
        # Initialize with placeholder values to avoid false positives on first query
        self.last_voice_name = "INITIAL"
        self.last_player_list = []
        self.last_online_status = None
        self.current_status = {'online': False, 'current_players': 0, 'max_players': 0}
        self.first_status_update = False  # Flag to ensure LAN poll runs first
        
        # Start background tasks
        self.lan_poll_task.start()
        self.discord_update_task.start()

    @tasks.loop(seconds=LAN_POLL_INTERVAL)
    async def lan_poll_task(self):
        """
        Background task: Query Minecraft server status regularly.
        Runs every LAN_POLL_INTERVAL seconds (default: 5s)
        Marks when first successful status is obtained.
        """
        status = await self.monitor.query_status()
        self.current_status = status
        if not self.first_status_update:
            logger.info("✅ First Minecraft server status obtained — Discord updates enabled")
            self.first_status_update = True

    @lan_poll_task.before_loop
    async def before_lan_poll(self):
        """Wait for bot to be ready before starting LAN polling."""
        await self.client.wait_until_ready()

    @tasks.loop(seconds=1)
    async def discord_update_task(self):
        """
        Background task: Update Discord voice channel name and text message.
        Respects Discord rate limiting for each channel type separately.
        Voice: 1 rename per 5 minutes (300s)
        Text: Updates every 5 seconds
        Only activates after first successful Minecraft server status poll.
        """
        # Wait for first successful LAN poll before attempting Discord updates
        if not self.first_status_update:
            logger.debug("Waiting for first Minecraft server status poll...")
            return
        
        # Apply offline grace period to avoid flipping status during wake-up
        if self.current_status.get('online'):
            self.offline_detected_at = None
        else:
            now = time.time()
            if self.offline_detected_at is None:
                self.offline_detected_at = now
                logger.info(f"Offline detected — waiting {self.offline_grace_period}s before updating Discord status")
                return
            elapsed = now - self.offline_detected_at
            if elapsed < self.offline_grace_period:
                remaining = self.offline_grace_period - elapsed
                logger.debug(f"Offline grace period active — {remaining:.1f}s remaining")
                return

        try:
            # Get current formatted status
            status_text = await self._format_voice_channel_name()
            new_player_list = sorted(self.current_status.get('player_list', []))
            status_changed = self.current_status.get('online') != self.last_online_status
            
            # Detect if status or players changed
            voice_changed = status_text != self.last_voice_name
            players_changed = new_player_list != self.last_player_list
            
            if not (voice_changed or players_changed or status_changed):
                logger.debug("No status or player list change detected — skipping Discord update")
                return

            logger.info(f"Change detected — Voice: {voice_changed}, Players: {players_changed}, Status: {status_changed}")

            # Get Discord guild and channels
            guild = self.client.get_guild(GUILD_ID)
            if not guild:
                logger.error(f"Guild {GUILD_ID} not found or bot not in guild")
                return

            voice_channel = guild.get_channel(VOICE_CHANNEL_ID)
            text_channel = guild.get_channel(TEXT_CHANNEL_ID)

            if not voice_channel or not text_channel:
                logger.error(f"Voice or Text channel not found. voice={voice_channel} text={text_channel}")
                return

            # Check if voice channel rename is needed and allowed
            voice_can_update = voice_changed and await self.voice_rate_limiter.should_update()
            
            # Check if text message update is needed and allowed
            # Text updates when players change, online/offline status changes, or voice status changes (max_players changes)
            text_needs_update = players_changed or status_changed or voice_changed
            text_can_update = text_needs_update and await self.text_rate_limiter.should_update()

            # Update voice channel if allowed
            if voice_can_update:
                try:
                    await voice_channel.edit(name=status_text)
                    logger.info(f"Voice rename: Changed to '{status_text}'")
                    self.last_voice_name = status_text
                except discord.errors.HTTPException as e:
                    if getattr(e, 'status', None) == 429:  # Rate limited
                        logger.warning("Voice rename: Rate limited (429) — activating throttle")
                        self.voice_rate_limiter.set_throttled(True)
                    else:
                        logger.error(f"Voice rename: Failed with error: {e}")
            elif voice_changed:
                wait_time = self.voice_rate_limiter.get_time_until_next_update()
                logger.debug(f"Voice rename: Change detected but rate limited — wait {wait_time:.1f}s")

            # Update text message if allowed
            if text_can_update:
                try:
                    await self._update_player_list_message(text_channel, new_player_list)
                    logger.info(f"Text message update: Updated with {len(new_player_list)} players")
                    self.last_player_list = new_player_list
                    self.last_online_status = self.current_status.get('online')
                except discord.errors.HTTPException as e:
                    if getattr(e, 'status', None) == 429:  # Rate limited
                        logger.warning("Text message update: Rate limited (429) — activating throttle")
                        self.text_rate_limiter.set_throttled(True)
                    else:
                        logger.error(f"Text message update: Failed with error: {e}")
            elif text_needs_update:
                wait_time = self.text_rate_limiter.get_time_until_next_update()
                logger.debug(f"Text message update: Change detected but rate limited — wait {wait_time:.1f}s")

        except Exception as e:
            logger.error(f"Error in discord_update_task: {e}")

    @discord_update_task.before_loop
    async def before_discord_update(self):
        """Wait for bot to be ready before starting Discord updates."""
        await self.client.wait_until_ready()

    async def _format_voice_channel_name(self) -> str:
        """
        Format voice channel name with server status and player count.
        Format: 🟢 online (current/max) [+ state] or 🔴 offline
        
        Returns:
            str: Formatted channel name
        """
        state = self._server_state_label()
        if self.current_status['online']:
            emoji = "🟢"
            status = "online"
            players = f"{self.current_status['current_players']}/{self.current_status['max_players']}"
            if state == "asleep":
                return f"{emoji} {status} ({state})"
            if state:
                return f"{emoji} {status} ({players} {state})"
            return f"{emoji} {status} ({players})"
        else:
            emoji = "🔴"
            status = "offline"
            return f"{emoji} {status}"

    async def _update_player_list_message(self, text_channel: discord.TextChannel, player_list: list):
        """
        Update or create player list message in text channel.
        Displays all currently online players.
        
        Args:
            text_channel: Discord text channel to post message
            player_list: List of online player names
        """
        # Format player list message
        if self.current_status['online']:
            state = self._server_state_label()
            current = self.current_status.get('current_players', 0)
            max_p = self.current_status.get('max_players', 0)
            
            # Hide player count when asleep, similar to voice channel
            if state == "asleep":
                state_suffix = " (asleep)"
                player_count_str = ""
            else:
                state_suffix = f" ({state})" if state else ""
                player_count_str = f" ({current}/{max_p})"
            
            if player_list:
                player_names = "\n".join([f"• {player}" for player in player_list])
                embed = discord.Embed(
                    title=f"🟢 Online Players{state_suffix}{player_count_str}",
                    description=player_names,
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )
                embed.set_footer(text="UptimeGolem | Minecraft Server Monitor")
            else:
                embed = discord.Embed(
                    title=f"🟢 Server Online{state_suffix}{player_count_str}",
                    description="No players online currently",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )
                embed.set_footer(text="UptimeGolem | Minecraft Server Monitor")
        else:
            embed = discord.Embed(
                title="🔴 Server Offline",
                description="The Minecraft server is currently offline",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.set_footer(text="UptimeGolem | Minecraft Server Monitor")

        # Find and update existing message or create new one
        try:
            # Search for existing UptimeGolem message
            async for message in text_channel.history(limit=10):
                if message.author == self.client.user and message.embeds:
                    if "UptimeGolem" in str(message.embeds[0].footer.text):
                        await message.edit(embed=embed)
                        return

            # No existing message found, create new one
            await text_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Text message update: Failed to update/send message: {e}")

    def _server_state_label(self) -> str:
        """Return server state label based on max player count."""
        max_players = self.current_status.get('max_players')
        if max_players == 20:
            return "asleep"
        return ""


# ==================== BOT INITIALIZATION ====================
def create_bot() -> commands.Bot:
    """
    Create and configure Discord bot instance.
    
    Returns:
        commands.Bot: Configured bot instance
    """
    intents = discord.Intents.default()
    intents.guilds = True
    # Note: message_content intent removed - not needed for slash commands
    
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        """Event: Bot has successfully logged in and is ready."""
        logger.info(f"✅ {bot.user} is now running!")
        logger.info(f"🎮 Monitoring server: {MINECRAFT_SERVER_IP}:{MINECRAFT_SERVER_PORT}")
        logger.info(f"📢 Voice channel ID: {VOICE_CHANNEL_ID}")
        logger.info(f"💬 Text channel ID: {TEXT_CHANNEL_ID}")

    return bot


# ==================== MAIN EXECUTION ====================
def main():
    """Initialize and run the Discord bot."""
    if DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        logger.error("❌ Please set your Discord bot token in the configuration section!")
        return

    if not all([VOICE_CHANNEL_ID, TEXT_CHANNEL_ID, GUILD_ID]):
        logger.error("❌ Please set all required channel and guild IDs!")
        return

    # Create bot and add cog
    bot = create_bot()
    
    async def setup_bot():
        """Setup bot cogs and run."""
        await bot.add_cog(UptimeGolemBot(bot))
        await bot.start(DISCORD_TOKEN)

    # Run bot
    asyncio.run(setup_bot())


if __name__ == "__main__":
    main()
