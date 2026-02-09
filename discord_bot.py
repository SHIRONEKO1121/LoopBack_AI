
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
                    msg = f"**{solution}\n\n*Is this helpful? If not, reply with 'ticket' to talk to a human.*"
                    await thread.send(msg)
                    
                else:
                    # Create Ticket with Context
                    # 1. Fetch History
                    messages = []
                    # Check if we are in a thread (best context) or channel
                    target_ctx = message.channel
                    
                    async for msg in target_ctx.history(limit=50):
                         if msg.content:
                             role = "model" if msg.author == bot.user else "user"
                             messages.append({"role": role, "content": msg.content})
                    
                    # Reverse so it's chronological
                    messages.reverse()
                    
                    # 2. Determine meaningful query
                    # If user just said "ticket", look back for the last user message that wasn't "ticket"
                    final_query = user_query
                    if len(user_query.split()) < 3 and len(messages) > 1:
                        for m in reversed(messages[:-1]): # Skip current "ticket" msg
                            if m["role"] == "user":
                                final_query = m["content"]
                                break

                    ticket_payload = {
                        "query": final_query,
                        "history": messages, # Pass full history
                        "users": [user_id, username], 
                        "force_create": True
                    }
                    
                    async with session.post(f"{API_URL}/tickets", json=ticket_payload) as resp:
                        if resp.status == 200:
                            ticket_data = await resp.json()
                            t_id = ticket_data.get("ticket_id")
                            draft_sol = ticket_data.get("solution", "")
                            
                            # Ticket Confirmation (Plain Text)
                            msg = f"**🎫 Ticket Created: {t_id}**\n\nI've logged this for an admin to review.\n\n**Issue:** {final_query}\n**Status:** Pending"
                            if draft_sol:
                                msg += f"\n\n**Preliminary Suggestion:**\n{draft_sol}"
                            
                            await thread.send(msg)
                        else:
                            await thread.send("❌ Error creating ticket.")

        except Exception as e:
            await message.channel.send(f"⚠️ System Error: {str(e)}")

# --- Background Task: Notify Users of Resolution ---
@tasks.loop(seconds=5)
async def check_resolved_tickets():
    """
    Polls backend for tickets requiring notification (Resolved or Awaiting Info).
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/tickets") as resp:
                if resp.status == 200:
                    tickets = await resp.json()
                    
                    for t in tickets:
                        val_id = t.get("id")
                        status = t.get("status")
                        notified = t.get("notified", True) # Default to True for old tickets/legacy stability
                        users = t.get("users", [])
                        
                        # Only process if NOT notified
                        if not notified and (status == "Resolved" or status == "Awaiting Info"):
                            
                            # Determine Message Content based on Status
                            msg_content = ""
                            if status == "Resolved":
                                msg_content = f"**✅ Ticket Resolved: {val_id}**\n\n**Issue:** {t.get('query')}\n**Resolution:** {t.get('final_answer')}"
                            elif status == "Awaiting Info":
                                # Find the last admin question
                                history = t.get("history", [])
                                last_admin_msg = "Please provide more details."
                                for h in reversed(history):
                                    if h.get("role") == "admin":
                                        last_admin_msg = h.get("message")
                                        break
                                msg_content = f"**❓ Admin Question: {val_id}**\n\n{last_admin_msg}\n\n*Reply here to answer.*"
                            
                            if not msg_content:
                                continue

                            sent = False
                            
                            # 1. Try Thread Notification First
                            thread_id = t.get("thread_id")
                            if thread_id:
                                try:
                                    thread = bot.get_channel(int(thread_id)) or await bot.fetch_channel(int(thread_id))
                                    if thread:
                                        await thread.send(msg_content)
                                        sent = True
                                        print(f"DTO sent to thread {thread_id} for {val_id}")
                                except Exception as e:
                                    print(f"Thread notification failed: {e}")

                            # 2. Fallback to DM if not sent to thread
                            if not sent and users:
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
                                        try:
                                            await user.send(msg_content)
                                            sent = True
                                            print(f"DTO sent to DM {user.name} for {val_id}")
                                        except:
                                            # Fallback to channel if DM fails
                                            if DISCORD_CHANNEL_ID:
                                                ch = bot.get_channel(int(DISCORD_CHANNEL_ID))
                                                if ch: await ch.send(content=f"<@{discord_user_id}> \n{msg_content}")
                                                sent = True
                            
                            # 3. ACK Notification to Backend
                            if sent:
                                try:
                                    async with session.post(f"{API_URL}/tickets/{val_id}/ack_notification") as ack_resp:
                                        if ack_resp.status == 200:
                                            print(f"✅ Acked notification for {val_id}")
                                        else:
                                            print(f"❌ Failed to ack notification for {val_id}: {ack_resp.status}")
                                except Exception as ex:
                                    print(f"Exception acking notification: {ex}")

    except Exception as e:
        print(f"Polling Error: {e}")

@check_resolved_tickets.before_loop
async def before_polling():
    await bot.wait_until_ready()

# 3. Run the bot
if DISCORD_BOT_TOKEN:
    bot.run(DISCORD_BOT_TOKEN)
else:
    print("❌ Error: DISCORD_BOT_TOKEN not found in .env")
