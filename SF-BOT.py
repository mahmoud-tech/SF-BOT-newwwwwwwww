import discord
from discord.ext import tasks, commands
import asyncio
import sqlite3
import datetime
import aiohttp
import io
import os
from dotenv import load_dotenv
load_dotenv()
# Bot setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Database setup with migration
def init_db():
    conn = sqlite3.connect('streaks.db')
    c = conn.cursor()
    
    # Create table if it doesn't exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_streaks (
            user_id INTEGER PRIMARY KEY,
            streak_days INTEGER DEFAULT 0,
            last_post_date TEXT,
            username TEXT,
            score INTEGER DEFAULT 0
        )
    ''')
    
    # Check if score column exists, if not add it
    try:
        c.execute('SELECT score FROM user_streaks LIMIT 1')
    except sqlite3.OperationalError:
        print("Adding score column to database...")
        c.execute('ALTER TABLE user_streaks ADD COLUMN score INTEGER DEFAULT 0')
        print("Score column added successfully!")
    
    conn.commit()
    conn.close()

init_db()

class StreakBot:
    def __init__(self):
        # Set your image channel IDs here
        self.image_channels = [
            1433779537786961982,  # Your image channel ID
        ]
        print(f"Image channels set to: {self.image_channels}")
    
    def is_image_channel(self, channel_id):
        """Check if the channel is an image-only channel"""
        result = channel_id in self.image_channels
        return result

    def get_user_data(self, user_id):
        conn = sqlite3.connect('streaks.db')
        c = conn.cursor()
        c.execute('SELECT streak_days, last_post_date, score FROM user_streaks WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        return result

    def update_user_streak_and_score(self, user_id, username):
        conn = sqlite3.connect('streaks.db')
        c = conn.cursor()
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        
        # Get current streak and score
        c.execute('SELECT streak_days, last_post_date, score FROM user_streaks WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        
        if result:
            streak_days, last_post_date, current_score = result
            if last_post_date:
                last_date = datetime.datetime.strptime(last_post_date, '%Y-%m-%d').date()
                current_date = datetime.datetime.now().date()
                
                # Check if user posted yesterday (maintains streak)
                if (current_date - last_date).days == 1:
                    streak_days += 1
                elif (current_date - last_date).days > 1:
                    streak_days = 1  # Reset streak if missed a day
                # If same day, don't increase streak
            else:
                streak_days = 1
            
            # Update score by +3
            new_score = current_score + 3
        else:
            streak_days = 1
            new_score = 3  # Start with 3 points for first image
        
        # Update or insert user record
        c.execute('''
            INSERT OR REPLACE INTO user_streaks (user_id, streak_days, last_post_date, username, score)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, streak_days, today, username, new_score))
        
        conn.commit()
        conn.close()
        return streak_days, new_score

    async def download_image(self, url):
        """Download image from URL"""
        try:
            print(f"Downloading image from: {url}")
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        print(f"Successfully downloaded image, size: {len(image_data)} bytes")
                        return image_data
                    else:
                        print(f"Failed to download image. Status: {response.status}")
                        return None
        except Exception as e:
            print(f"Error downloading image: {e}")
            return None

streak_bot = StreakBot()

@bot.event
async def on_ready():
    print(f'{bot.user} has logged in!')
    print(f'Bot is in {len(bot.guilds)} guilds')
    
    # Set bot status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="your streaks! Use /help"
        )
    )
    
    # Sync slash commands to specific guild for faster updates
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} commands to {guild.name}")
        except Exception as e:
            print(f"Failed to sync commands to {guild.name}: {e}")
    
    reset_streaks.start()

@bot.event
async def on_message(message):
    # Process commands FIRST (in ALL channels)
    await bot.process_commands(message)
    
    # Then check for image processing (ignore bot messages)
    if message.author.bot:
        return
    
    print(f"Message received in channel {message.channel.id} ({message.channel.name})")
    
    # Check if message is in an image channel
    if not streak_bot.is_image_channel(message.channel.id):
        print(f"Channel {message.channel.id} is NOT an image channel, ignoring images...")
        return
    
    print(f"Message received in channel {message.channel.id} ({message.channel.name})")
    
    # Check if message is in an image channel
    if not streak_bot.is_image_channel(message.channel.id):
        print(f"Channel {message.channel.id} is NOT an image channel, ignoring images...")
        return
    
    print(f"Channel {message.channel.id} IS an image channel, processing images...")
    
    # Check if message has an image attachment
    if message.attachments:
        image_attachments = [att for att in message.attachments 
                           if att.content_type and att.content_type.startswith('image/')]
        
        if image_attachments:
            try:
                print(f"Processing image from {message.author.display_name} in image channel {message.channel.name}...")
                
                # Get user info and image URL
                user_id = message.author.id
                username = message.author.display_name
                image_url = image_attachments[0].url
                
                # DOWNLOAD THE IMAGE FIRST (before deleting the message)
                print("Downloading image before deletion...")
                image_data = await streak_bot.download_image(image_url)
                
                if not image_data:
                    print("Image download failed, aborting...")
                    return
                
                # NOW delete the original message
                await message.delete()
                print("Original message deleted")
                
                # Update streak and score (+3 points)
                streak_days, new_score = streak_bot.update_user_streak_and_score(user_id, username)
                print(f"User streak: {streak_days} days, Score: {new_score} points")
                
                # Create caption with mention, streak, and score
                fire_emoji = "🔥" if streak_days >= 3 else "⭐" if streak_days >= 2 else "📸"
                caption = f"📸 {message.author.mention}'s streak: {streak_days} {fire_emoji} | Score: {new_score} 🏆"
                
                # Create file from image data
                file = discord.File(io.BytesIO(image_data), filename="streak_image.png")
                
                # Send the image with caption
                await message.channel.send(content=caption, file=file)
                print(f"Successfully sent image with caption for {username}")
                
            except Exception as e:
                error_msg = f"❌ Error processing image: {str(e)}"
                await message.channel.send(error_msg)
                print(f"Unexpected error: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("No image attachments found in message")
    else:
        print("No attachments found in message")

# Channel check for slash commands - BLOCK commands in image channels
def not_image_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        return not streak_bot.is_image_channel(interaction.channel.id)
    return discord.app_commands.check(predicate)

# Regular command to sync slash commands
@bot.command()
async def sync(ctx):
    """Sync slash commands (Admin only)"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return
    
    try:
        # Sync to specific guild for immediate effect
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync(guild=ctx.guild)
        
        await ctx.send(f"✅ Synced {len(synced)} slash command(s)! They should be available immediately.")
        print(f"Manually synced {len(synced)} slash commands to {ctx.guild.name}")
        
    except Exception as e:
        await ctx.send(f"❌ Failed to sync slash commands: {e}")

@bot.command()
async def set_image(ctx):
    """Set current channel as image channel (Admin only)"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return
    
    channel_id = ctx.channel.id
    if channel_id not in streak_bot.image_channels:
        streak_bot.image_channels.append(channel_id)
        await ctx.send(f"✅ Set {ctx.channel.mention} as an image channel! Bot will now process images here.")
        print(f"Added channel {channel_id} to image channels. Current image channels: {streak_bot.image_channels}")
    else:
        await ctx.send(f"✅ {ctx.channel.mention} is already an image channel!")


@bot.command()
@not_image_channel()
async def list_image_channels(ctx):
    """List all image channels (Admin only)"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return
    
    if streak_bot.image_channels:
        channel_mentions = []
        for channel_id in streak_bot.image_channels:
            channel = bot.get_channel(channel_id)
            if channel:
                channel_mentions.append(f"{channel.mention} (ID: {channel_id})")
            else:
                channel_mentions.append(f"Unknown Channel (ID: {channel_id})")
        
        embed = discord.Embed(
            title="📸 Image Channels",
            description="\n".join(channel_mentions) if channel_mentions else "No image channels set!",
            color=0x7289DA
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ No image channels set! Use `!set_image_channel` to add one.")

@bot.command()
async def debug_channels(ctx):
    """Debug command to see all channels and their IDs"""

    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return
    
    embed = discord.Embed(title="📊 Channel Debug Info", color=0x7289DA)
    
    # Current channel info
    embed.add_field(
        name="Current Channel",
        value=f"Name: {ctx.channel.name}\nID: {ctx.channel.id}\nType: {type(ctx.channel).__name__}",
        inline=False
    )
    
    # Image channels info
    image_info = []
    for channel_id in streak_bot.image_channels:
        channel = bot.get_channel(channel_id)
        if channel:
            image_info.append(f"✅ {channel.name} (ID: {channel_id})")
        else:
            image_info.append(f"❌ Unknown Channel (ID: {channel_id})")
    
    embed.add_field(
        name="Image Channels",
        value="\n".join(image_info) if image_info else "No image channels set!",
        inline=False
    )
    
    await ctx.send(embed=embed)
@bot.command()
async def debug_image_channels(ctx):
    """Debug the image channels list"""
    embed = discord.Embed(title="🔍 Image Channels Debug", color=0xFF6B6B)
    
    # Show current image channels
    embed.add_field(
        name="Current Image Channels",
        value=str(streak_bot.image_channels) if streak_bot.image_channels else "Empty list!",
        inline=False
    )
    
    # Show current channel info
    embed.add_field(
        name="Your Current Channel",
        value=f"Name: {ctx.channel.name}\nID: {ctx.channel.id}",
        inline=False
    )
    
    # Check if current channel is in list
    is_in_list = ctx.channel.id in streak_bot.image_channels
    embed.add_field(
        name="Is Current Channel in List?",
        value="✅ YES" if is_in_list else "❌ NO",
        inline=False
    )
    
    await ctx.send(embed=embed)
    print(f"Image channels debug: {streak_bot.image_channels}")

@bot.command()
async def remove_image(ctx):  # REMOVED @not_image_channel()
    """Remove current channel from image channels (Admin only)"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return
    
    channel_id = ctx.channel.id
    if channel_id in streak_bot.image_channels:
        streak_bot.image_channels.remove(channel_id)
        await ctx.send(f"✅ Removed {ctx.channel.mention} from image channels! Bot will no longer process images here.")
        print(f"Removed channel {channel_id} from image channels. Current image channels: {streak_bot.image_channels}")
    else:
        await ctx.send(f"❌ {ctx.channel.mention} is not an image channel!")
# Slash Commands - BLOCKED in image channels

@bot.tree.command(name="streak", description="Check your current streak days")
@not_image_channel()
async def streak_slash(interaction: discord.Interaction):
    """Check your current streak days"""
    try:
        user_data = streak_bot.get_user_data(interaction.user.id)
        
        if user_data:
            streak_days, last_post_date, score = user_data
            embed = discord.Embed(
                title="🔥 Your Streak",
                color=0xFF6B6B
            )
            
            # Different emojis based on streak length
            if streak_days >= 7:
                streak_emoji = "🔥🔥🔥"
            elif streak_days >= 3:
                streak_emoji = "🔥🔥"
            else:
                streak_emoji = "🔥"
            
            embed.add_field(name="Current Streak", value=f"{streak_days} days {streak_emoji}", inline=False)
            embed.add_field(name="Last Post", value=last_post_date, inline=True)
            embed.add_field(name="Total Score", value=f"{score} points", inline=True)
            
            last_post_datetime = datetime.datetime.strptime(last_post_date, '%Y-%m-%d').date()
            today = datetime.datetime.now().date()
            
            if streak_days > 0:
                if last_post_datetime == today:
                    embed.add_field(
                        name="Status", 
                        value="✅ You've posted today! Keep the streak alive!", 
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="Status", 
                        value="⏰ Don't forget to post today to maintain your streak!", 
                        inline=False
                    )
            
            # Add motivational message based on streak
            if streak_days >= 7:
                embed.set_footer(text="🔥 Amazing! You're on fire!")
            elif streak_days >= 3:
                embed.set_footer(text="🌟 Great job! Keep it up!")
            else:
                embed.set_footer(text="💪 Start strong! You got this!")
                
        else:
            embed = discord.Embed(
                title="🔥 Your Streak",
                description="You haven't started a streak yet! Post an image to begin your streak journey.",
                color=0xFFA500
            )
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message("Error retrieving your streak information.")

@bot.tree.command(name="score", description="Check your current score and stats")
@not_image_channel()
async def score_slash(interaction: discord.Interaction):
    """Check your current score and stats"""
    try:
        user_data = streak_bot.get_user_data(interaction.user.id)
        
        if user_data:
            streak_days, last_post_date, score = user_data
            embed = discord.Embed(
                title="🏆 Your Stats",
                color=0x7289DA
            )
            embed.add_field(name="Total Score", value=f"{score} points 🏆", inline=True)
            embed.add_field(name="Current Streak", value=f"{streak_days} days 🔥", inline=True)
            embed.add_field(name="Last Post", value=last_post_date, inline=True)
            
            # Calculate average points per day
            if streak_days > 0:
                avg_points = score / streak_days
                embed.add_field(name="Avg Points/Day", value=f"{avg_points:.1f} ⭐", inline=True)
            
            # Calculate next milestone
            next_milestone = ((score // 100) + 1) * 100
            points_needed = next_milestone - score
            embed.add_field(name="Next Milestone", value=f"{next_milestone} points ({points_needed} more)", inline=True)
            
            last_post_datetime = datetime.datetime.strptime(last_post_date, '%Y-%m-%d').date()
            today = datetime.datetime.now().date()
            
            if streak_days > 0:
                if last_post_datetime == today:
                    embed.add_field(
                        name="Daily Status", 
                        value="✅ Daily post completed! +3 points earned!", 
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="Daily Status", 
                        value="📸 Post an image today to earn +3 points!", 
                        inline=False
                    )
        else:
            embed = discord.Embed(
                title="🏆 Your Stats",
                description="You haven't started yet! Post an image to begin earning points and building your streak.",
                color=0xFFA500
            )
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message("Error retrieving your stats.")

@bot.tree.command(name="leaderboard", description="Show the top score leaders")
@not_image_channel()
async def leaderboard_slash(interaction: discord.Interaction):
    """Show the top score leaders"""
    try:
        conn = sqlite3.connect('streaks.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT username, score, streak_days, last_post_date 
            FROM user_streaks 
            WHERE score > 0 
            ORDER BY score DESC 
            LIMIT 10
        ''')
        
        leaders = c.fetchall()
        conn.close()
        
        embed = discord.Embed(
            title="🏆 Score Leaderboard",
            description="Top 10 users by total score",
            color=0xFFD700
        )
        
        if leaders:
            for i, (username, score, streak_days, last_post_date) in enumerate(leaders, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                embed.add_field(
                    name=f"{medal} {username}",
                    value=f"**{score} points** | {streak_days} day streak",
                    inline=False
                )
        else:
            embed.description = "No scores yet! Be the first to post an image!"
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message("Error retrieving leaderboard.")

@bot.tree.command(name="streak_leaderboard", description="Show the top streak leaders")
@not_image_channel()
async def streak_leaderboard_slash(interaction: discord.Interaction):
    """Show the top streak leaders"""
    try:
        conn = sqlite3.connect('streaks.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT username, streak_days, score, last_post_date 
            FROM user_streaks 
            WHERE streak_days > 0 
            ORDER BY streak_days DESC 
            LIMIT 10
        ''')
        
        leaders = c.fetchall()
        conn.close()
        
        embed = discord.Embed(
            title="🔥 Streak Leaderboard",
            description="Top 10 users by current streak",
            color=0xFF6B6B
        )
        
        if leaders:
            for i, (username, streak_days, score, last_post_date) in enumerate(leaders, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                
                # Different fire emojis based on streak length
                if streak_days >= 7:
                    fire = "🔥🔥🔥"
                elif streak_days >= 3:
                    fire = "🔥🔥"
                else:
                    fire = "🔥"
                    
                embed.add_field(
                    name=f"{medal} {username}",
                    value=f"**{streak_days} days** {fire} | {score} points",
                    inline=False
                )
        else:
            embed.description = "No active streaks! Start a streak by posting an image!"
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message("Error retrieving streak leaderboard.")

@bot.tree.command(name="user_stats", description="Check another user's stats")
@discord.app_commands.describe(user="The user to check stats for")
@not_image_channel()
async def user_stats_slash(interaction: discord.Interaction, user: discord.Member):
    """Check another user's stats"""
    try:
        user_data = streak_bot.get_user_data(user.id)
        
        if user_data:
            streak_days, last_post_date, score = user_data
            embed = discord.Embed(
                title=f"📊 {user.display_name}'s Stats",
                color=0x7289DA
            )
            embed.add_field(name="Total Score", value=f"{score} points 🏆", inline=True)
            embed.add_field(name="Current Streak", value=f"{streak_days} days 🔥", inline=True)
            embed.add_field(name="Last Post", value=last_post_date, inline=True)
            
            # Streak status
            if streak_days >= 7:
                streak_status = "🔥 On Fire!"
            elif streak_days >= 3:
                streak_status = "🌟 Strong Streak"
            elif streak_days > 0:
                streak_status = "💪 Getting Started"
            else:
                streak_status = "📸 No active streak"
            
            embed.add_field(name="Streak Status", value=streak_status, inline=True)
            
            embed.set_thumbnail(url=user.display_avatar.url)
        else:
            embed = discord.Embed(
                title=f"📊 {user.display_name}'s Stats",
                description="This user hasn't posted any images yet!",
                color=0xFFA500
            )
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message("Error retrieving user stats.")

# Admin commands - also blocked in image channels
@bot.tree.command(name="add_score", description="Add points to a user (Admin only)")
@discord.app_commands.describe(user="The user to add points to", points="Number of points to add")
@not_image_channel()
async def add_score_slash(interaction: discord.Interaction, user: discord.Member, points: int):
    """Add points to a user (Admin only)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    try:
        conn = sqlite3.connect('streaks.db')
        c = conn.cursor()
        
        # Get current score
        c.execute('SELECT score FROM user_streaks WHERE user_id = ?', (user.id,))
        result = c.fetchone()
        
        if result:
            current_score = result[0]
            new_score = current_score + points
        else:
            new_score = points
        
        # Update score
        c.execute('''
            INSERT OR REPLACE INTO user_streaks (user_id, streak_days, last_post_date, username, score)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, 0, datetime.datetime.now().strftime('%Y-%m-%d'), user.display_name, new_score))
        
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"✅ Added {points} points to {user.mention}! New score: {new_score} 🏆", ephemeral=True)
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Error updating score: {e}", ephemeral=True)

@bot.tree.command(name="set_score", description="Set a user's score to a specific value (Admin only)")
@discord.app_commands.describe(user="The user to set score for", points="New score value")
@not_image_channel()
async def set_score_slash(interaction: discord.Interaction, user: discord.Member, points: int):
    """Set a user's score to a specific value (Admin only)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    try:
        conn = sqlite3.connect('streaks.db')
        c = conn.cursor()
        
        # Set score
        c.execute('''
            INSERT OR REPLACE INTO user_streaks (user_id, streak_days, last_post_date, username, score)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, 0, datetime.datetime.now().strftime('%Y-%m-%d'), user.display_name, points))
        
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"✅ Set {user.mention}'s score to {points} points! 🏆", ephemeral=True)
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Error setting score: {e}", ephemeral=True)

@bot.tree.command(name="reset_streak", description="Reset a user's streak (Admin only)")
@discord.app_commands.describe(user="The user to reset streak for")
@not_image_channel()
async def reset_streak_slash(interaction: discord.Interaction, user: discord.Member):
    """Reset a user's streak (Admin only)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    try:
        conn = sqlite3.connect('streaks.db')
        c = conn.cursor()
        
        # Reset streak (keep score)
        c.execute('UPDATE user_streaks SET streak_days = 0 WHERE user_id = ?', (user.id,))
        
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"✅ Reset {user.mention}'s streak to 0 days!", ephemeral=True)
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Error resetting streak: {e}", ephemeral=True)

@tasks.loop(hours=24)
async def reset_streaks():
    """Reset streaks for users who didn't post in the last 24 hours"""
    try:
        conn = sqlite3.connect('streaks.db')
        c = conn.cursor()
        
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Get users to reset
        c.execute('SELECT user_id, username FROM user_streaks WHERE last_post_date < ? AND streak_days > 0', (yesterday,))
        users_to_reset = c.fetchall()
        
        # Reset streaks (but keep scores!)
        c.execute('UPDATE user_streaks SET streak_days = 0 WHERE last_post_date < ?', (yesterday,))
        
        conn.commit()
        conn.close()
        
        if users_to_reset:
            print(f"Reset streaks for {len(users_to_reset)} users at {datetime.datetime.now()}")
        else:
            print(f"No streaks to reset at {datetime.datetime.now()}")
            
    except Exception as e:
        print(f"Error resetting streaks: {e}")

@reset_streaks.before_loop
async def before_reset_streaks():
    await bot.wait_until_ready()

# Error handler for channel restrictions
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.CheckFailure):
        await interaction.response.send_message(
            "❌ Slash commands are not allowed in image channels! Please use commands in other channels.",
            ephemeral=True
        )
    else:
        print(f"Slash command error: {error}")

# Run the bot
# Run the bot
if __name__ == "__main__":
    # Get token from environment variable
    bot_token = os.getenv('DISCORD_TOKEN')
    if not bot_token:
        print("❌ ERROR: DISCORD_TOKEN environment variable not set!")
        print("Please set the DISCORD_BOT_TOKEN environment variable in Railway.")
        exit(1)
    
    print("✅ Starting bot...")
    try:
        bot.run(bot_token)
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        # Wait and exit (Railway will auto-restart)
        import time
        time.sleep(10)