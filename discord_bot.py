
import discord
from discord.ext import commands, tasks
import os
import aiohttp
import asyncio
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DISCORD_CHANNEL_ID = os.getenv('DISCORD_CHANNEL_ID')
API_URL = "http://localhost:8000"  # Your backend server

# Mapping Discord User ID -> Current Ticket ID (if any)
# This helps us contextually maintain conversation if needed
active_sessions = {}

# 1. Setup Intents
intents = discord.Intents.default()
intents.message_content = True 

# 2. Define the bot
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f'🔌 Connected to Backend: {API_URL}')
    check_resolved_tickets.start() # Start background polling
    print('------')

@bot.event
async def on_message(message):
    # Ignore self
    if message.author == bot.user:
        return

    # Only listen in specific channel (optional, remove check to allow DMs)
    # if str(message.channel.id) != DISCORD_CHANNEL_ID:
    #     return

    user_query = message.content
    user_id = str(message.author.id)
    username = message.author.name
    
    # Simple "Thinking" indicator
    async with message.channel.typing():
        try:
            async with aiohttp.ClientSession() as session:
                
                # 1. Analyze the chat first
                analyze_payload = {
                    "message": user_query,
                    "history": [] # TODO: Add history if needed
                }
                
                async with session.post(f"{API_URL}/chat/analyze", json=analyze_payload) as resp:
                    if resp.status != 200:
                        await message.channel.send("⚠️ Backend Error: Unable to analyze request.")
                        return
                    
                    analysis = await resp.json()
                    
                confidence = analysis.get("confidence")
                solution = analysis.get("response")
                escalate = analysis.get("escalation_required")
                is_related = analysis.get("is_it_related", True)
                summary = analysis.get("summary", "Support Request")

                # Logic: Is it IT related?
                # If NOT related -> Only reply if we were explicitly mentioned
                is_mentioned = bot.user in message.mentions
                if not is_related and not is_mentioned:
                    print(f"Skipping unrelated message: {user_query}")
                    return

                # Create Thread for conversation
                try:
                    thread = await message.create_thread(name=f"🎫 {summary[:50]}", auto_archive_duration=60)
                except Exception as ex:
                    print(f"Failed to create thread: {ex}")
                    thread = message.channel # Fallback
                
                # Logic:
                # If High Confidence & No Escalation -> Respond directly
                # If Low Confidence OR Escalation Required -> Create Ticket
                
                if confidence == "high" and not escalate:
                    # Direct Response (Plain Text)
                    msg = f"**💡 Solution Found**\n\n{solution}\n\n*Is this helpful? If not, reply with 'ticket' to talk to a human.*"
                    await thread.send(msg)
                    
                else:
                    # Create Ticket
                    ticket_payload = {
                        "query": user_query,
                        "history": [{"role": "user", "content": user_query}],
                        "users": [user_id, username], # Track Discord User
                        "force_create": True
                    }
                    
                    async with session.post(f"{API_URL}/tickets", json=ticket_payload) as resp:
                        if resp.status == 200:
                            ticket_data = await resp.json()
                            t_id = ticket_data.get("ticket_id")
                            draft_sol = ticket_data.get("solution", "")
                            
                            # Ticket Confirmation (Plain Text)
                            msg = f"**🎫 Ticket Created: {t_id}**\n\nI've logged this for an admin to review.\n\n**Issue:** {user_query}\n**Status:** Pending"
                            if draft_sol:
                                msg += f"\n\n**Preliminary Suggestion:**\n{draft_sol}"
                            
                            await thread.send(msg)
                        else:
                            await thread.send("❌ Error creating ticket.")

        except Exception as e:
            await message.channel.send(f"⚠️ System Error: {str(e)}")

# --- Background Task: Notify Users of Resolution ---
@tasks.loop(seconds=10)
async def check_resolved_tickets():
    """
    Polls backend for resolved tickets and notifies Discord users.
    NOTE: A real production app would use Webhooks or WebSocket events 
    instead of polling, but this is simple and robust for now.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/tickets") as resp:
                if resp.status == 200:
                    tickets = await resp.json()
                    
                    # Look for tickets that are "Resolved" but maybe we haven't notified them?
                    # Ideally, your backend should have a "notified": false flag.
                    # For this demo, we will just check "Resolved" status.
                    # To avoid spamming, we need a way to track what we've sent. 
                    # We'll use a local set for this session.
                    
                    # See global 'notified_tickets' set below
                    pass 
                    
                
    except Exception as e:
        print(f"Polling Error: {e}")

# Track notified tickets in memory (resets on bot restart)
notified_tickets = set()

@check_resolved_tickets.before_loop
async def before_polling():
    await bot.wait_until_ready()

# Overwrite the actual logic with tracking
@tasks.loop(seconds=15)
async def check_resolved_tickets():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/tickets") as resp:
                if resp.status == 200:
                    tickets = await resp.json()
                    
                    for t in tickets:
                        val_id = t.get("id")
                        status = t.get("status")
                        users = t.get("users", [])
                        
                        # Check conditions: Resolved + Has Discord User + Not Notified
                        if status == "Resolved" and val_id not in notified_tickets and users:
                            
                            discord_user_id = None
                            # Try to find the numeric ID string
                            for u in users:
                                if u.isdigit(): 
                                    discord_user_id = int(u)
                                    break
                            
                            if discord_user_id:
                                user = bot.get_user(discord_user_id)
                                if not user:
                                    try:
                                        user = await bot.fetch_user(discord_user_id)
                                    except: pass
                                
                                if user:
                                    # Send Notification
                                    embed = discord.Embed(title="✅ Ticket Resolved", color=discord.Color.green())
                                    embed.add_field(name="Ticket ID", value=val_id, inline=True)
                                    embed.add_field(name="Issue", value=t.get("query"), inline=False)
                                    embed.add_field(name="Resolution", value=t.get("final_answer"), inline=False)
                                    
                                    try:
                                        await user.send(embed=embed)
                                        print(f"DTO sent to {user.name} for {val_id}")
                                    except:
                                        # Fallback to channel if DM fails
                                        if DISCORD_CHANNEL_ID:
                                            ch = bot.get_channel(int(DISCORD_CHANNEL_ID))
                                            if ch: await ch.send(content=f"<@{discord_user_id}>", embed=embed)
                                
                                # Mark as notified
                                notified_tickets.add(val_id)

    except Exception as e:
        print(f"Polling Error: {e}")

# 3. Run the bot
if DISCORD_BOT_TOKEN:
    bot.run(DISCORD_BOT_TOKEN)
else:
    print("❌ Error: DISCORD_BOT_TOKEN not found in .env")
