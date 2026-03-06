# UptimeGolem - Minecraft Server Status Discord Bot

A Discord bot that monitors Minecraft server status and displays it in real-time across voice and text channels with intelligent rate limiting.

## Features

- ✅ **Real-time Server Monitoring**: Queries Minecraft server every 5 seconds
- 🎤 **Voice Channel Updates**: Displays server status in voice channel name
  - 🟢 online (current/max players)
  - 🔴 offline
- 💬 **Player List Messages**: Shows currently online players in text channel
- 🚦 **Adaptive Rate Limiting**: 
  - Fast updates when under 50% rate limit usage
  - Automatic throttling when approaching Discord API limits
  - Prevents timeouts and rate limit violations
- 🔄 **Synchronized Updates**: Voice and text channels update together within rate limits

## Installation

### Prerequisites
- Python 3.8+
- Minecraft server accessible via LAN
- Discord bot token
- Voice and Text channel IDs
- Guild ID

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create and configure `.env` file:
```bash
cp .env.example .env
```

3. Edit the `.env` file with your settings:
```env
# Discord Bot Configuration
DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE

# Minecraft Server Configuration
MINECRAFT_SERVER_IP=127.0.0.1
MINECRAFT_SERVER_PORT=25565

# Discord Channel Configuration
VOICE_CHANNEL_ID=123456789
TEXT_CHANNEL_ID=987654321
GUILD_ID=111222333

# Polling and Update Configuration
LAN_POLL_INTERVAL=5
INITIAL_DISCORD_UPDATE_INTERVAL=10
RATE_LIMIT_THRESHOLD=0.5
```

4. Run the bot:
```bash
python uptimeGolem.py
```

## Configuration

All settings are loaded from the `.env` file. Copy the `.env.example` as template:

```bash
cp .env.example .env
```

Then edit `.env` with your values:

```env
DISCORD_TOKEN=YOUR_TOKEN              # Discord bot token
MINECRAFT_SERVER_IP=192.168.1.100    # Server LAN IP
MINECRAFT_SERVER_PORT=25565           # Server port
VOICE_CHANNEL_ID=123456789            # Voice channel ID
TEXT_CHANNEL_ID=987654321             # Text channel ID
GUILD_ID=111222333                    # Guild/Server ID

LAN_POLL_INTERVAL=5                   # Query interval (seconds)
INITIAL_DISCORD_UPDATE_INTERVAL=10    # Initial Discord update interval
RATE_LIMIT_THRESHOLD=0.5              # Throttle at 50% rate limit
```

## How It Works

### LAN Polling
The bot queries the Minecraft server every 5 seconds using the `JavaServer` class. This happens independently and doesn't impact Discord API rate limits.

### Discord Updates
Updates to Discord channels (voice name + text messages) are synchronized and controlled by the `DiscordRateLimiter` class:

1. **Fast Mode**: When >50% rate limit actions remain, updates every 10 seconds
2. **Throttled Mode**: When <50% rate limit actions remain, updates every 30 seconds
3. **Player List**: Only updates when player list changes

### Rate Limiting Strategy
- Monitors Discord API rate limit status
- Automatically switches to slower update rate when approaching limits
- Prevents violation of Discord's 10 requests per 10 seconds per channel rule

## Finding Channel and Guild IDs

### Enable Developer Mode in Discord
1. User Settings → Advanced → Developer Mode (ON)

### Get IDs
- Right-click on server name → "Copy Server ID" = `GUILD_ID`
- Right-click on voice channel → "Copy Channel ID" = `VOICE_CHANNEL_ID`
- Right-click on text channel → "Copy Channel ID" = `TEXT_CHANNEL_ID`

## Logs

The bot logs all activities with timestamps:
- Server status queries
- Discord API updates
- Rate limit throttling events
- Errors and exceptions

All logs are printed to console with format: `[HH:MM:SS] - Logger - Level - Message`

## Troubleshooting

### Bot doesn't connect
- Check `DISCORD_TOKEN` is correct
- Verify bot has permission to join your server

### Can't find Minecraft server
- Ensure `MINECRAFT_SERVER_IP` is correct LAN IP (use `ipconfig` or `ifconfig`)
- Check server is running and port is accessible
- Verify firewall allows connections on port 25565

### Voice channel not updating
- Confirm `VOICE_CHANNEL_ID` is correct
- Check bot has permission to edit channel name
- Look at console logs for rate limit errors

### Player list not showing
- Confirm `TEXT_CHANNEL_ID` is correct
- Check bot has permission to send messages
- Ensure "Server List Ping" is enabled on Minecraft server
