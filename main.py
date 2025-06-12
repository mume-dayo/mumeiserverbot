import discord
from discord.ext import commands
import json
import os
from datetime import datetime
from flask import Flask
from threading import Thread
import time

# Flask app for Render health check
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot is running!"

@app.route('/health')
def health():
    return {"status": "healthy", "bot": "running"}

def run_flask():
    """Run Flask server"""
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True  # Required for anti-spam
bot = commands.Bot(command_prefix='/', intents=intents)

# Allowed server IDs
ALLOWED_SERVERS = [1373116978709139577, 1382415420413313096]

# Anti-spam system
spam_tracker = {}  # {user_id: [{'message': str, 'timestamp': float, 'channel_id': int}]}
bot_spam_tracker = {}  # {user_id: {'count': int, 'last_timestamp': float}}

# Anti-spam tracking
user_message_history = {}  # {user_id: [timestamp1, timestamp2, ...]}
bot_message_count = {}     # {user_id: consecutive_bot_message_count}

# Data storage files
DATA_FILE = 'bot_data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'users': {},
        'tickets': {},
        'polls': {},
        'user_levels': {}
    }

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_allowed_server(guild_id):
    """Check if the server is allowed to use the bot"""
    return guild_id in ALLOWED_SERVERS

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

    # Set bot status/presence
    activity = discord.Game(name="むめー専用botをプレイ中...")
    await bot.change_presence(status=discord.Status.online, activity=activity)

    # Load configurations
    load_translation_config()
    load_server_log_config()
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')

@bot.event
async def on_message(message):
    # Ignore bot's own messages
    if message.author == bot.user:
        return

    # Check if server is allowed
    if not is_allowed_server(message.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    # Handle message copying first
    await on_message_for_copy(message)

    # Handle server-wide translation
    await on_message_for_server_translation(message)

    # Handle server logging
    await on_message_for_server_logging(message)

    # Don't process commands here
    if message.content.startswith('/'):
        await bot.process_commands(message)
        return

    user_id = message.author.id
    current_time = time.time()

    # Check if message author is a bot
    if message.author.bot:
        # Track consecutive bot messages
        if user_id not in bot_message_count:
            bot_message_count[user_id] = 0

        bot_message_count[user_id] += 1

        # If bot posts 2 or more consecutive messages, delete and ban
        if bot_message_count[user_id] >= 2:
            try:
                await message.delete()
                await message.guild.ban(message.author, reason="Bot spam detected - 2+ consecutive messages")

                # Send warning in channel
                warning_embed = discord.Embed(
                    title="🚫 Bot Ban",
                    description=f"Bot {message.author.mention} has been banned for consecutive message spam.",
                    color=0xff0000
                )
                await message.channel.send(embed=warning_embed, delete_after=10)

                # Reset counter
                if user_id in bot_message_count:
                    del bot_message_count[user_id]

            except discord.Forbidden:
                print(f"Failed to ban bot {message.author.name} - insufficient permissions")
            except Exception as e:
                print(f"Error banning bot: {e}")
    else:
        # Reset bot message count for human users
        if user_id in bot_message_count:
            del bot_message_count[user_id]

    # Anti-spam for human users - only target identical consecutive messages
    if not message.author.bot:
        # Initialize user history if not exists
        if user_id not in user_message_history:
            user_message_history[user_id] = []

        # Add current message with content and timestamp
        user_message_history[user_id].append({
            'content': message.content,
            'timestamp': current_time
        })

        # Keep only messages from last 30 seconds
        user_message_history[user_id] = [
            msg for msg in user_message_history[user_id]
            if current_time - msg['timestamp'] <= 30
        ]

        # Check for identical consecutive messages
        if len(user_message_history[user_id]) >= 3:
            # Get the last 3 messages
            recent_messages = user_message_history[user_id][-3:]
            
            # Check if all 3 messages have the same content and are not empty
            if (len(set(msg['content'] for msg in recent_messages)) == 1 and 
                recent_messages[0]['content'].strip() != ""):
                
                try:
                    print(f"Identical message spam detected from {message.author.name} (ID: {user_id})")
                    print(f"Repeated message: {message.content[:50]}...")

                    # Delete only the consecutive identical messages (last 3)
                    messages_to_delete = []
                    async for msg in message.channel.history(limit=10):
                        if (msg.author.id == user_id and 
                            msg.content == message.content and
                            current_time - msg.created_at.timestamp() <= 30):
                            messages_to_delete.append(msg)
                            # Only delete the last 3 identical messages
                            if len(messages_to_delete) >= 3:
                                break
                    
                    # Delete only the 3 most recent identical messages
                    for msg in messages_to_delete[:3]:
                        try:
                            await msg.delete()
                        except:
                            pass

                    print(f"Deleted {min(len(messages_to_delete), 3)} consecutive identical messages")

                    # 3+ identical messages: 1 hour timeout
                    from datetime import timedelta
                    timeout_duration = discord.utils.utcnow() + timedelta(hours=1)
                    await message.author.timeout(timeout_duration, reason="同じメッセージの連投によるスパム")

                    print(f"Successfully timed out {message.author.name}")

                    warning_embed = discord.Embed(
                        title="🚫 タイムアウト適用",
                        description=f"{message.author.mention} は同じメッセージの連投により1時間のタイムアウトが適用されました。",
                        color=0xff0000
                    )
                    sent_warning = await message.channel.send(embed=warning_embed, delete_after=15)

                    # Clear message history after action
                    user_message_history[user_id] = []

                except discord.Forbidden as e:
                    print(f"Failed to moderate {message.author.name} - insufficient permissions: {e}")
                except Exception as e:
                    print(f"Error in anti-spam: {e}")

    # Add experience for messages (exclude bots and commands)
    if not message.author.bot and not message.content.startswith('/'):
        add_experience(message.author.id, message.guild.id, 5)  # 5 XP per message

    # Process commands
    await bot.process_commands(message)

# Role Selection View
class RoleSelectionView(discord.ui.View):
    def __init__(self, available_roles):
        super().__init__(timeout=300)
        self.available_roles = available_roles
        self.setup_buttons()

    def setup_buttons(self):
        # Create buttons for each role (max 25 buttons)
        for i, role in enumerate(self.available_roles[:25]):
            button = discord.ui.Button(
                label=role.name,
                style=discord.ButtonStyle.primary,
                custom_id=f"role_{role.id}",
                emoji="🎭"
            )
            button.callback = self.create_role_callback(role)
            self.add_item(button)

    def create_role_callback(self, role):
        async def role_callback(interaction):
            await self.assign_role(interaction, role)
        return role_callback

    async def assign_role(self, interaction, role):
        try:
            # Check if user already has the role
            if role in interaction.user.roles:
                await interaction.response.send_message(f'❌ あなたは既に {role.name} ロールを持っています。', ephemeral=True)
                return

            # Add the role to the user
            await interaction.user.add_roles(role)

            # Update user data
            data = load_data()
            user_id = str(interaction.user.id)

            if user_id not in data['users']:
                data['users'][user_id] = {
                    'authenticated': True,
                    'join_date': datetime.now().isoformat()
                }
            else:
                data['users'][user_id]['authenticated'] = True

            save_data(data)

            await interaction.response.send_message(f'✅ {role.name} ロールが付与されました！', ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message('❌ ロールを付与する権限がありません。', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ ロールの付与に失敗しました: {str(e)}', ephemeral=True)

# Specific Role View for single role assignment
class SpecificRoleView(discord.ui.View):
    def __init__(self, role):
        super().__init__(timeout=None)
        self.role = role

    @discord.ui.button(label='ろーるをしゅとく！', style=discord.ButtonStyle.primary)
    async def get_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        user_id = str(interaction.user.id)

        # Add user to database if not exists
        if user_id not in data['users']:
            data['users'][user_id] = {
                'authenticated': True,
                'join_date': datetime.now().isoformat()
            }
        else:
            data['users'][user_id]['authenticated'] = True

        save_data(data)

        try:
            # Check if user already has the role
            if self.role in interaction.user.roles:
                await interaction.response.send_message(f'❌ あなたは既に {self.role.name} ロールを持っています。', ephemeral=True)
                return

            # Add the role to the user
            await interaction.user.add_roles(self.role)
            await interaction.response.send_message(f'✅ {self.role.name} ロールが付与されました！', ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message('❌ ロールを付与する権限がありません。', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ ロールの付与に失敗しました: {str(e)}', ephemeral=True)

# Public Auth View
class PublicAuthView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='認証する', style=discord.ButtonStyle.primary)
    async def authenticate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        user_id = str(interaction.user.id)

        # Add user to database if not exists
        if user_id not in data['users']:
            data['users'][user_id] = {
                'authenticated': True,
                'join_date': datetime.now().isoformat()
            }
        else:
            data['users'][user_id]['authenticated'] = True

        save_data(data)

        # Get assignable roles (exclude @everyone, bot roles, and admin roles)
        assignable_roles = []
        for role in interaction.guild.roles:
            if (role.name != '@everyone' and 
                not role.managed and 
                not role.permissions.administrator and
                role < interaction.guild.me.top_role):
                assignable_roles.append(role)

        if not assignable_roles:
            await interaction.response.send_message('❌ 付与可能なロールがありません。', ephemeral=True)
            return

        # Create embed for role selection
        embed = discord.Embed(
            title='🎭 ロール選択',
            description='取得したいロールを下のボタンから選択してください。\n\n**利用可能なロール:**',
            color=0x00ff99
        )

        # Add role information to embed
        role_list = []
        for role in assignable_roles[:10]:  # Show max 10 roles in embed
            role_list.append(f'• {role.name} ({len(role.members)} メンバー)')

        embed.add_field(
            name='📋 ロール一覧',
            value='\n'.join(role_list) + ('...' if len(assignable_roles) > 10 else ''),
            inline=False
        )

        embed.set_footer(text='ボタンをクリックしてロールを取得')

        # Create view with role buttons
        view = RoleSelectionView(assignable_roles)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)









# Nuke channel
@bot.tree.command(name='nuke', description='チャンネルを再生成（設定を引き継ぎ）')
async def nuke_channel(interaction: discord.Interaction):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message('❌ チャンネル管理権限が必要です。', ephemeral=True)
        return

    channel = interaction.channel

    # Store channel settings
    channel_name = channel.name
    channel_topic = channel.topic
    channel_category = channel.category
    channel_position = channel.position
    channel_overwrites = channel.overwrites

    # Send initial response
    await interaction.response.send_message('🔄 チャンネルを再生成しています...', ephemeral=True)

    try:
        # Create new channel with same settings first
        new_channel = await channel.guild.create_text_channel(
            name=f"{channel_name}-new",
            topic=channel_topic,
            category=channel_category,
            overwrites=channel_overwrites
        )

        # Send confirmation in new channel
        embed = discord.Embed(
            title='💥 チャンネルがヌークされました！',
            description='チャンネルが正常に再生成されました。',
            color=0xff0000
        )
        await new_channel.send(embed=embed)

        # Now delete the old channel
        await channel.delete(reason="Nuke command executed")

        # Rename the new channel to the original name
        await new_channel.edit(name=channel_name, position=channel_position)

    except discord.Forbidden:
        await interaction.followup.send('❌ チャンネルの削除・作成権限が不足しています。', ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)

# View user profile
@bot.tree.command(name='profile', description='ユーザープロフィールを表示')
async def view_profile(interaction: discord.Interaction, user: discord.Member = None):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if user is None:
        user = interaction.user

    data = load_data()
    user_id = str(user.id)

    if user_id not in data['users']:
        await interaction.response.send_message('❌ ユーザーが見つかりません。')
        return

    user_data = data['users'][user_id]

    embed = discord.Embed(
        title=f'👤 {user.display_name} のプロフィール',
        color=0x00ff00
    )
    embed.add_field(name='✅ 認証状態', value='認証済み' if user_data.get('authenticated') else '未認証', inline=True)
    embed.add_field(name='📅 参加日', value=user_data.get('join_date', '不明'), inline=True)

    await interaction.response.send_message(embed=embed)







# Setup role panel command
@bot.tree.command(name='setuprole', description='ロール取得パネルを設置')
async def setup_role(interaction: discord.Interaction, role_name: str = None):
    try:
        # Immediately defer the response
        await interaction.response.defer()
        
        if not is_allowed_server(interaction.guild.id):
            await interaction.followup.send('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
            return

        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send('❌ ロール管理権限が必要です。', ephemeral=True)
            return

        # If specific role name is provided, create a panel for that specific role
        if role_name:
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if not role:
                await interaction.followup.send(f'❌ "{role_name}" ロールが見つかりません。', ephemeral=True)
                return

            # Check if the role can be assigned
            if (role.name == '@everyone' or 
                role.managed or 
                role.permissions.administrator or
                role >= interaction.guild.me.top_role):
                await interaction.followup.send(f'❌ "{role_name}" ロールは付与できません。', ephemeral=True)
                return

            embed = discord.Embed(
                title='🎭 ロール取得システム',
                description=f'下のボタンをクリックして **{role_name}** ロールを取得してください。\n\n'
                           '**認証について:**\n'
                           '• 認証により全機能を利用できるようになります\n'
                           '• 誰でも自由に使用できます',
                color=0x00ff99
            )
            embed.add_field(
                name='📋 取得可能なロール',
                value=f'• {role_name} ({len(role.members)} メンバー)',
                inline=False
            )
            embed.set_footer(text='認証は無料です | 24時間利用可能')

            view = SpecificRoleView(role)
            await interaction.followup.send(embed=embed, view=view)
        else:
            # Original behavior - show all available roles
            embed = discord.Embed(
                title='🎭 ロール取得システム',
                description='下のボタンをクリックして認証を行い、ロールを取得してください。\n\n'
                           '**認証について:**\n'
                           '• 認証により全機能を利用できるようになります\n'
                           '• 利用可能なロールから選択できます\n'
                           '• 誰でも自由に使用できます',
                color=0x00ff99
            )
            embed.set_footer(text='認証は無料です | 24時間利用可能')

            view = PublicAuthView()
            await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        print(f"Error in setuprole command: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
            else:
                await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
        except:
            pass

# View user's servers
@bot.tree.command(name='servers', description='ユーザーが参加しているサーバー一覧を表示')
async def view_servers(interaction: discord.Interaction, user: discord.Member = None):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if user is None:
        user = interaction.user

    # Get all mutual guilds between the bot and the user
    mutual_guilds = user.mutual_guilds

    if not mutual_guilds:
        await interaction.response.send_message(f'❌ {user.display_name} との共通サーバーが見つかりません。')
        return

    embed = discord.Embed(
        title=f'🌐 {user.display_name} が参加しているサーバー',
        description=f'Botと共通のサーバー: {len(mutual_guilds)}個',
        color=0x0099ff
    )

    for guild in mutual_guilds:
        # Get member object for this guild
        member = guild.get_member(user.id)
        if member:
            # Get join date
            joined_at = member.joined_at
            join_date = joined_at.strftime('%Y/%m/%d') if joined_at else '不明'

            # Get member count
            member_count = guild.member_count

            # Get user's roles in this guild (excluding @everyone)
            roles = [role.name for role in member.roles if role.name != '@everyone']
            roles_text = ', '.join(roles[:3]) + ('...' if len(roles) > 3 else '') if roles else 'なし'

            embed.add_field(
                name=f'📋 {guild.name}',
                value=f'**メンバー数:** {member_count}\n**参加日:** {join_date}\n**ロール:** {roles_text}',
                inline=True
            )

    embed.set_footer(text=f'総サーバー数: {len(mutual_guilds)}')
    await interaction.response.send_message(embed=embed)

# Anti-spam management commands
@bot.tree.command(name='antispam-config', description='荒らし対策設定を表示・変更')
async def antispam_config(interaction: discord.Interaction, action: str = "show"):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message('❌ メッセージ管理権限が必要です。', ephemeral=True)
        return

    if action == "show":
        embed = discord.Embed(
            title="🛡️ 荒らし対策設定",
            description="現在の荒らし対策設定:",
            color=0x0099ff
        )
        embed.add_field(
            name="同一メッセージ連投検知",
            value="• 30秒以内に同じメッセージを3回以上: 全て削除 + 1時間タイムアウト",
            inline=False
        )
        embed.add_field(
            name="Bot対策",
            value="• 2連続以上のメッセージでBan",
            inline=False
        )
        embed.add_field(
            name="自動削除",
            value="• スパムメッセージは自動削除",
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    elif action == "reset":
        # Reset all spam tracking
        global user_message_history, bot_message_count
        user_message_history.clear()
        bot_message_count.clear()

        await interaction.response.send_message('✅ 荒らし対策データをリセットしました。', ephemeral=True)

@bot.tree.command(name='spam-status', description='現在のスパム検知状況を表示')
async def spam_status(interaction: discord.Interaction):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message('❌ メッセージ管理権限が必要です。', ephemeral=True)
        return

    embed = discord.Embed(
        title="📊 スパム検知状況",
        color=0x00ff00
    )

    # Count active trackers
    active_users = len([uid for uid, history in user_message_history.items() if history])
    tracked_bots = len(bot_message_count)

    embed.add_field(name="監視中ユーザー", value=f"{active_users}人", inline=True)
    embed.add_field(name="追跡中Bot", value=f"{tracked_bots}個", inline=True)
    embed.add_field(name="システム状態", value="🟢 稼働中", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)

# Giveaway system
active_giveaways = {}  # {message_id: {'end_time': datetime, 'prize': str, 'participants': set(), 'creator_id': int, 'channel_id': int}}

# Giveaway View
class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @discord.ui.button(label='🎉 参加する', style=discord.ButtonStyle.primary, emoji='🎉')
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.giveaway_id not in active_giveaways:
            await interaction.response.send_message('❌ このGiveawayは既に終了しています。', ephemeral=True)
            return

        giveaway = active_giveaways[self.giveaway_id]
        user_id = interaction.user.id

        # Check if giveaway has ended
        if datetime.now() > giveaway['end_time']:
            await interaction.response.send_message('❌ このGiveawayは既に終了しています。', ephemeral=True)
            return

        # Check if user is already participating
        if user_id in giveaway['participants']:
            await interaction.response.send_message('❌ 既にこのGiveawayに参加しています！', ephemeral=True)
            return

        # Add user to participants
        giveaway['participants'].add(user_id)
        participant_count = len(giveaway['participants'])

        await interaction.response.send_message(
            f'✅ Giveawayに参加しました！\n現在の参加者数: **{participant_count}人**',
            ephemeral=True
        )

        # Update the embed with new participant count
        embed = discord.Embed(
            title='🎉 Giveaway開催中！',
            description=f'**景品:** {giveaway["prize"]}\n\n'
                       f'**参加者数:** {participant_count}人\n'
                       f'**終了時刻:** <t:{int(giveaway["end_time"].timestamp())}:F>\n'
                       f'**残り時間:** <t:{int(giveaway["end_time"].timestamp())}:R>',
            color=0xff6b6b
        )
        embed.add_field(
            name='参加方法',
            value='🎉 ボタンをクリックして参加！',
            inline=False
        )
        embed.set_footer(text='Good luck! 🍀')

        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except:
            pass

# Giveaway time selection
class GiveawayTimeSelect(discord.ui.Select):
    def __init__(self, prize):
        self.prize = prize
        options = [
            discord.SelectOption(label='1時間', value='1h', emoji='⏰'),
            discord.SelectOption(label='3時間', value='3h', emoji='⏰'),
            discord.SelectOption(label='5時間', value='5h', emoji='⏰'),
            discord.SelectOption(label='24時間', value='24h', emoji='⏰'),
            discord.SelectOption(label='48時間', value='48h', emoji='⏰')
        ]
        super().__init__(placeholder='Giveaway期間を選択してください...', options=options)

    async def callback(self, interaction: discord.Interaction):
        # Parse time selection
        time_mapping = {
            '1h': 1,
            '3h': 3, 
            '5h': 5,
            '24h': 24,
            '48h': 48
        }

        selected_time = self.values[0]
        hours = time_mapping[selected_time]

        from datetime import timedelta
        end_time = datetime.now() + timedelta(hours=hours)

        # Create giveaway embed
        embed = discord.Embed(
            title='🎉 Giveaway開催中！',
            description=f'**景品:** {self.prize}\n\n'
                       f'**参加者数:** 0人\n'
                       f'**終了時刻:** <t:{int(end_time.timestamp())}:F>\n'
                       f'**残り時間:** <t:{int(end_time.timestamp())}:R>',
            color=0xff6b6b
        )
        embed.add_field(
            name='参加方法',
            value='🎉 ボタンをクリックして参加！',
            inline=False
        )
        embed.set_footer(text='Good luck! 🍀')

        # Create giveaway view
        view = GiveawayView("temp")

        # Send the giveaway message
        await interaction.response.edit_message(embed=embed, view=view)

        # Get the message ID and update the giveaway data
        message = await interaction.original_response()
        giveaway_id = str(message.id)

        # Update the view with correct giveaway ID
        view.giveaway_id = giveaway_id
        await message.edit(view=view)

        # Store giveaway data
        active_giveaways[giveaway_id] = {
            'end_time': end_time,
            'prize': self.prize,
            'participants': set(),
            'creator_id': interaction.user.id,
            'channel_id': interaction.channel.id
        }

        print(f"Giveaway created: {giveaway_id} - Prize: {self.prize} - Duration: {selected_time}")

        # Schedule giveaway end (we'll check this manually for now)
        # In a production environment, you'd want to use a proper task scheduler

class GiveawayTimeView(discord.ui.View):
    def __init__(self, prize):
        super().__init__(timeout=300)
        self.add_item(GiveawayTimeSelect(prize))

# Giveaway command
@bot.tree.command(name='giveaway', description='Giveawayを開始')
async def giveaway(interaction: discord.Interaction, prize: str):
    try:
        # Immediately defer the response
        await interaction.response.defer()
        
        if not is_allowed_server(interaction.guild.id):
            await interaction.followup.send('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
            return

        # Check permissions (optional - you can remove this if anyone should be able to create giveaways)
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.followup.send('❌ メッセージ管理権限が必要です。', ephemeral=True)
            return

        # Create time selection embed
        embed = discord.Embed(
            title='🎉 Giveaway設定',
            description=f'**景品:** {prize}\n\n時間を選択してGiveawayを開始してください。',
            color=0x00ff99
        )
        embed.set_footer(text='下のメニューから時間を選択してください')

        view = GiveawayTimeView(prize)
        await interaction.followup.send(embed=embed, view=view)

    except Exception as e:
        print(f"Error in giveaway command: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
            else:
                await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
        except:
            pass

# Level and Experience System
def add_experience(user_id, guild_id, amount):
    """Add experience to user and check for level up"""
    data = load_data()
    if 'user_levels' not in data:
        data['user_levels'] = {}
    
    guild_key = str(guild_id)
    user_key = str(user_id)
    
    if guild_key not in data['user_levels']:
        data['user_levels'][guild_key] = {}
    
    if user_key not in data['user_levels'][guild_key]:
        data['user_levels'][guild_key][user_key] = {'level': 1, 'xp': 0, 'total_xp': 0}
    
    user_data = data['user_levels'][guild_key][user_key]
    user_data['xp'] += amount
    user_data['total_xp'] += amount
    
    # Calculate level (100 XP per level)
    new_level = (user_data['total_xp'] // 100) + 1
    
    if new_level > user_data['level']:
        user_data['level'] = new_level
        user_data['xp'] = user_data['total_xp'] % 100
        save_data(data)
        return new_level  # Return new level for level up message
    
    save_data(data)
    return None

def get_user_level_data(user_id, guild_id):
    """Get user level data"""
    data = load_data()
    if 'user_levels' not in data:
        return {'level': 1, 'xp': 0, 'total_xp': 0}
    
    guild_key = str(guild_id)
    user_key = str(user_id)
    
    if guild_key not in data['user_levels'] or user_key not in data['user_levels'][guild_key]:
        return {'level': 1, 'xp': 0, 'total_xp': 0}
    
    return data['user_levels'][guild_key][user_key]

@bot.tree.command(name='level', description='ユーザーのレベルを表示')
async def level_command(interaction: discord.Interaction, user: discord.Member = None):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    target_user = user or interaction.user
    level_data = get_user_level_data(target_user.id, interaction.guild.id)
    
    # Calculate XP needed for next level
    current_level = level_data['level']
    xp_needed = 100 - level_data['xp']
    
    embed = discord.Embed(
        title=f'📊 {target_user.display_name} のレベル',
        color=0x00ff99
    )
    embed.add_field(name='🎯 レベル', value=f"{current_level}", inline=True)
    embed.add_field(name='⭐ 経験値', value=f"{level_data['xp']}/100 XP", inline=True)
    embed.add_field(name='📈 総経験値', value=f"{level_data['total_xp']} XP", inline=True)
    embed.add_field(name='🚀 次のレベルまで', value=f"{xp_needed} XP", inline=False)
    
    # Progress bar
    progress = level_data['xp'] / 100
    bar_length = 20
    filled_length = int(bar_length * progress)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    embed.add_field(name='📊 進行度', value=f"`{bar}` {level_data['xp']}%", inline=False)
    
    embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else None)
    embed.set_footer(text='メッセージを送信して経験値を獲得しよう！')
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='ranking', description='サーバーのレベルランキングを表示')
async def ranking_command(interaction: discord.Interaction):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    data = load_data()
    if 'user_levels' not in data or str(interaction.guild.id) not in data['user_levels']:
        await interaction.response.send_message('❌ まだレベルデータがありません。', ephemeral=True)
        return
    
    guild_data = data['user_levels'][str(interaction.guild.id)]
    
    # Sort users by total XP
    sorted_users = sorted(guild_data.items(), key=lambda x: x[1]['total_xp'], reverse=True)
    
    embed = discord.Embed(
        title=f'🏆 {interaction.guild.name} レベルランキング',
        description='サーバー内の上位ユーザー',
        color=0xffd700
    )
    
    for i, (user_id, level_data) in enumerate(sorted_users[:10]):  # Top 10
        user = interaction.guild.get_member(int(user_id))
        if user:
            rank_emoji = ['🥇', '🥈', '🥉'][i] if i < 3 else f"{i+1}."
            embed.add_field(
                name=f'{rank_emoji} {user.display_name}',
                value=f'レベル: {level_data["level"]} | 総XP: {level_data["total_xp"]}',
                inline=False
            )
    
    embed.set_footer(text='メッセージを送信してランキングを上げよう！')
    await interaction.response.send_message(embed=embed)

# Voting System
active_polls = {}  # {message_id: poll_data}

class PollView(discord.ui.View):
    def __init__(self, poll_id, options):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        self.options = options
        self.setup_buttons()

    def setup_buttons(self):
        emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
        for i, option in enumerate(self.options[:10]):  # Max 10 options
            button = discord.ui.Button(
                label=f"{option[:80]}",  # Truncate if too long
                style=discord.ButtonStyle.primary,
                emoji=emojis[i],
                custom_id=f"poll_{self.poll_id}_{i}"
            )
            button.callback = self.create_vote_callback(i)
            self.add_item(button)

    def create_vote_callback(self, option_index):
        async def vote_callback(interaction):
            data = load_data()
            if 'polls' not in data:
                data['polls'] = {}
            
            if self.poll_id not in data['polls']:
                await interaction.response.send_message('❌ この投票は見つかりません。', ephemeral=True)
                return
            
            poll_data = data['polls'][self.poll_id]
            user_id = str(interaction.user.id)
            
            # Check if user already voted
            if user_id in poll_data['voters']:
                old_option = poll_data['voters'][user_id]
                poll_data['votes'][old_option] -= 1
            
            # Record new vote
            poll_data['voters'][user_id] = option_index
            poll_data['votes'][option_index] += 1
            
            save_data(data)
            
            # Update embed
            embed = discord.Embed(
                title=f'📊 {poll_data["question"]}',
                description='下のボタンをクリックして投票してください。',
                color=0x0099ff
            )
            
            total_votes = sum(poll_data['votes'])
            for i, option in enumerate(poll_data['options']):
                votes = poll_data['votes'][i]
                percentage = (votes / total_votes * 100) if total_votes > 0 else 0
                bar_length = 20
                filled_length = int(bar_length * percentage / 100)
                bar = '█' * filled_length + '░' * (bar_length - filled_length)
                
                embed.add_field(
                    name=f'{["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][i]} {option}',
                    value=f'`{bar}` {votes} 票 ({percentage:.1f}%)',
                    inline=False
                )
            
            embed.set_footer(text=f'総投票数: {total_votes}票 | 作成者: {poll_data["creator"]}')
            
            try:
                await interaction.response.edit_message(embed=embed, view=self)
                
                # Add XP for voting
                add_experience(interaction.user.id, interaction.guild.id, 10)
                
            except:
                await interaction.response.send_message(f'✅ **{self.options[option_index]}** に投票しました！', ephemeral=True)
        
        return vote_callback

@bot.tree.command(name='poll', description='投票を作成')
async def poll_command(interaction: discord.Interaction, question: str, options: str):
    try:
        await interaction.response.defer()
        
        if not is_allowed_server(interaction.guild.id):
            await interaction.followup.send('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
            return

        # Parse options (comma separated)
        option_list = [opt.strip() for opt in options.split(',')]
        
        if len(option_list) < 2:
            await interaction.followup.send('❌ 最低2つの選択肢が必要です。', ephemeral=True)
            return
        
        if len(option_list) > 10:
            await interaction.followup.send('❌ 選択肢は最大10個までです。', ephemeral=True)
            return

        # Create poll embed
        embed = discord.Embed(
            title=f'📊 {question}',
            description='下のボタンをクリックして投票してください。',
            color=0x0099ff
        )
        
        for i, option in enumerate(option_list):
            embed.add_field(
                name=f'{["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][i]} {option}',
                value='`░░░░░░░░░░░░░░░░░░░░` 0 票 (0.0%)',
                inline=False
            )
        
        embed.set_footer(text=f'総投票数: 0票 | 作成者: {interaction.user.display_name}')
        
        # Create poll view
        view = PollView("temp", option_list)
        
        # Send poll
        await interaction.followup.send(embed=embed, view=view)
        
        # Get message and update poll data
        message = await interaction.original_response()
        poll_id = str(message.id)
        
        # Update view with correct poll ID
        view.poll_id = poll_id
        await message.edit(view=view)
        
        # Save poll data
        data = load_data()
        if 'polls' not in data:
            data['polls'] = {}
            
        data['polls'][poll_id] = {
            'question': question,
            'options': option_list,
            'votes': [0] * len(option_list),
            'voters': {},  # {user_id: option_index}
            'creator': interaction.user.display_name,
            'channel_id': interaction.channel.id,
            'guild_id': interaction.guild.id
        }
        save_data(data)
        
        # Add XP for creating poll
        add_experience(interaction.user.id, interaction.guild.id, 20)

    except Exception as e:
        print(f"Error in poll command: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
            else:
                await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
        except:
            pass

@bot.tree.command(name='poll-results', description='投票結果を表示')
async def poll_results_command(interaction: discord.Interaction, poll_id: str):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    data = load_data()
    if 'polls' not in data or poll_id not in data['polls']:
        await interaction.response.send_message('❌ 指定された投票が見つかりません。', ephemeral=True)
        return
    
    poll_data = data['polls'][poll_id]
    
    embed = discord.Embed(
        title=f'📊 投票結果: {poll_data["question"]}',
        color=0x00ff00
    )
    
    total_votes = sum(poll_data['votes'])
    winner_index = poll_data['votes'].index(max(poll_data['votes'])) if total_votes > 0 else 0
    
    for i, option in enumerate(poll_data['options']):
        votes = poll_data['votes'][i]
        percentage = (votes / total_votes * 100) if total_votes > 0 else 0
        status = '🏆 ' if i == winner_index and total_votes > 0 else ''
        
        embed.add_field(
            name=f'{status}{option}',
            value=f'{votes} 票 ({percentage:.1f}%)',
            inline=True
        )
    
    embed.add_field(
        name='📈 統計',
        value=f'**総投票数:** {total_votes}\n**投票者数:** {len(poll_data["voters"])}\n**作成者:** {poll_data["creator"]}',
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

# Ticket system commands
class TicketCloseView(discord.ui.View):
    def __init__(self, ticket_id):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

    @discord.ui.button(label='🔒 チケットを閉じる', style=discord.ButtonStyle.danger, emoji='🔒')
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        tickets = data.get('tickets', {})
        
        if str(self.ticket_id) not in tickets:
            await interaction.response.send_message('❌ チケットが見つかりません。', ephemeral=True)
            return
        
        ticket_data = tickets[str(self.ticket_id)]
        
        # Check if user is ticket creator or admin
        is_creator = str(interaction.user.id) == ticket_data['user_id']
        is_admin = interaction.user.guild_permissions.administrator
        
        if not is_creator and not is_admin:
            await interaction.response.send_message('❌ チケットを閉じる権限がありません。', ephemeral=True)
            return
        
        if ticket_data['status'] == 'closed':
            await interaction.response.send_message('❌ このチケットは既に閉じられています。', ephemeral=True)
            return
        
        # Update ticket status
        data['tickets'][str(self.ticket_id)]['status'] = 'closed'
        data['tickets'][str(self.ticket_id)]['closed_at'] = datetime.now().isoformat()
        data['tickets'][str(self.ticket_id)]['closed_by'] = str(interaction.user.id)
        save_data(data)
        
        # Send closure message
        embed = discord.Embed(
            title='🔒 チケットクローズ',
            description=f'チケット #{self.ticket_id} が閉じられました。\n\n**閉じたユーザー:** {interaction.user.mention}\n**閉じた時刻:** <t:{int(datetime.now().timestamp())}:F>',
            color=0xff0000
        )
        embed.set_footer(text='このチャンネルは5秒後に削除されます')
        
        await interaction.response.send_message(embed=embed)
        
        # Delete channel after 5 seconds
        import asyncio
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except:
            pass

class TicketPanelView(discord.ui.View):
    def __init__(self, category_name=None):
        super().__init__(timeout=None)
        self.category_name = category_name

    @discord.ui.button(label='🎫 チケット作成', style=discord.ButtonStyle.primary, emoji='🎫')
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket_channel(interaction)
    
    async def create_ticket_channel(self, interaction):
        data = load_data()
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild.id)

        # Create new ticket ID
        ticket_id = 1
        while str(ticket_id) in data.get('tickets', {}):
            ticket_id += 1

        try:
            # Check if category exists, create if necessary
            if self.category_name:
                category = discord.utils.get(interaction.guild.categories, name=self.category_name)
                if not category:
                    category = await interaction.guild.create_category(self.category_name)
            else:
                category = discord.utils.get(interaction.guild.categories, name="🎫 チケット")
                if not category:
                    category = await interaction.guild.create_category("🎫 チケット")

            # Create the channel with format: name-チケット
            channel_name = f"{interaction.user.name}-チケット"
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                topic=f'チケット #{ticket_id} | 作成者: {interaction.user.display_name}',
                category=category
            )

            # Set channel permissions
            await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
            await channel.set_permissions(interaction.guild.default_role, read_messages=False)
            await channel.set_permissions(interaction.guild.me, read_messages=True, send_messages=True)

            # Add permissions for administrators
            for member in interaction.guild.members:
                if member.guild_permissions.administrator:
                    await channel.set_permissions(member, read_messages=True, send_messages=True)

            # Send initial message
            embed = discord.Embed(
                title=f'🎫 チケット #{ticket_id}',
                description=f'チケットが作成されました。\nご用件をお聞かせください。',
                color=0xff9900
            )
            embed.add_field(
                name='作成者',
                value=interaction.user.mention,
                inline=False
            )
            embed.add_field(
                name='📋 利用方法',
                value='• 問題や質問を詳しく説明してください\n• サポートスタッフが対応します\n• 解決したら下のボタンでチケットを閉じてください',
                inline=False
            )
            embed.set_footer(text='サポートスタッフが対応します')

            # Create close button view
            close_view = TicketCloseView(ticket_id)
            message = await channel.send(embed=embed, view=close_view)
            await message.pin()
            await channel.send(f"{interaction.user.mention} へのメンション", delete_after=1)

            # Save ticket data
            if 'tickets' not in data:
                data['tickets'] = {}

            data['tickets'][str(ticket_id)] = {
                'user_id': user_id,
                'guild_id': guild_id,
                'channel_id': str(channel.id),
                'created_at': datetime.now().isoformat(),
                'description': 'チケット作成',
                'status': 'open'
            }
            save_data(data)

            # Send confirmation
            await interaction.response.send_message(f'✅ チケット #{ticket_id} を作成しました！ {channel.mention} で詳細を確認してください。', ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message('❌ チャンネルを作成する権限がありません。', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ チケットの作成に失敗しました: {str(e)}', ephemeral=True)

@bot.tree.command(name='ticket-panel', description='チケット作成パネルを設置')
async def ticket_panel(interaction: discord.Interaction, category_name: str = None):
    try:
        # Immediately defer the response
        await interaction.response.defer()
        
        if not is_allowed_server(interaction.guild.id):
            await interaction.followup.send('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
            return

        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send('❌ チャンネル管理権限が必要です。', ephemeral=True)
            return

        embed = discord.Embed(
            title='🎫 サポートチケット',
            description='サポートが必要な場合は、下のボタンをクリックしてチケットを作成してください。\n\n'
                       '**チケットについて:**\n'
                       '• 質問や問題がある時にご利用ください\n'
                       '• 専用チャンネルが作成されます\n'
                       '• サポートスタッフが対応します\n'
                       '• 問題が解決したらチケットを閉じてください',
            color=0xff9900
        )
        embed.add_field(
            name='📋 利用方法',
            value='1. 「🎫 チケット作成」ボタンをクリック\n2. 内容を入力して送信\n3. 作成されたチャンネルで対応を待つ',
            inline=False
        )
        embed.set_footer(text='24時間サポート | お気軽にお声がけください')

        view = TicketPanelView(category_name)
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        print(f"Error in ticket-panel command: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
            else:
                await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
        except:
            pass

@bot.tree.command(name='ticket-list', description='チケット一覧を表示')
async def ticket_list(interaction: discord.Interaction, status: str = "all"):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message('❌ メッセージ管理権限が必要です。', ephemeral=True)
        return

    data = load_data()
    tickets = data.get('tickets', {})

    # Filter tickets by guild and status
    guild_tickets = []
    for ticket_id, ticket_data in tickets.items():
        if ticket_data['guild_id'] == str(interaction.guild.id):
            if status == "all" or ticket_data['status'] == status:
                guild_tickets.append((ticket_id, ticket_data))

    if not guild_tickets:
        await interaction.response.send_message('❌ 該当するチケットが見つかりません。', ephemeral=True)
        return

    embed = discord.Embed(
        title=f'🎫 チケット一覧 ({status})',
        description=f'サーバー内のチケット: {len(guild_tickets)}件',
        color=0x0099ff
    )

    for ticket_id, ticket_data in guild_tickets[:10]:  # Show max 10 tickets
        user = interaction.guild.get_member(int(ticket_data['user_id']))
        user_name = user.display_name if user else 'ユーザーが見つかりません'

        status_emoji = '🟢' if ticket_data['status'] == 'open' else '🔴'
        embed.add_field(
            name=f'{status_emoji} チケット #{ticket_id}',
            value=f'**作成者:** {user_name}\n**作成日:** {ticket_data["created_at"][:10]}\n**内容:** {ticket_data["description"][:50]}...',
            inline=True
        )

    if len(guild_tickets) > 10:
        embed.set_footer(text=f'表示: 10/{len(guild_tickets)}件')

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='close-ticket', description='チケットを強制的に閉じる')
async def close_ticket_command(interaction: discord.Interaction, ticket_id: int):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者権限が必要です。', ephemeral=True)
        return

    data = load_data()
    tickets = data.get('tickets', {})

    if str(ticket_id) not in tickets:
        await interaction.response.send_message('❌ 指定されたチケットが見つかりません。', ephemeral=True)
        return

    ticket_data = tickets[str(ticket_id)]

    if ticket_data['guild_id'] != str(interaction.guild.id):
        await interaction.response.send_message('❌ このサーバーのチケットではありません。', ephemeral=True)
        return

    if ticket_data['status'] == 'closed':
        await interaction.response.send_message('❌ このチケットは既に閉じられています。', ephemeral=True)
        return

    # Update ticket status
    data['tickets'][str(ticket_id)]['status'] = 'closed'
    data['tickets'][str(ticket_id)]['closed_at'] = datetime.now().isoformat()
    data['tickets'][str(ticket_id)]['closed_by'] = str(interaction.user.id)
    save_data(data)

    # Try to find and delete the channel
    channel_id = ticket_data.get('channel_id')
    if channel_id:
        channel = interaction.guild.get_channel(int(channel_id))
        if channel:
            try:
                await channel.delete()
            except:
                pass

    embed = discord.Embed(
        title='✅ チケット強制クローズ',
        description=f'チケット #{ticket_id} を強制的に閉じました。',
        color=0x00ff00
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Server logging commands
@bot.tree.command(name='setup-server-log', description='サーバー間ログ転送を設定')
async def setup_server_log(interaction: discord.Interaction, target_server_id: str):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message('❌ サーバー管理権限が必要です。', ephemeral=True)
        return

    try:
        target_guild_id = int(target_server_id)
        target_guild = bot.get_guild(target_guild_id)
        
        if not target_guild:
            await interaction.response.send_message('❌ 指定されたサーバーが見つかりません。Botがそのサーバーに参加していることを確認してください。', ephemeral=True)
            return
        
        # Check if bot has permissions in target server
        if not target_guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message('❌ 転送先サーバーでチャンネル管理権限が必要です。', ephemeral=True)
            return

        source_guild_id = str(interaction.guild.id)
        
        # Update configuration
        server_log_configs[source_guild_id] = target_server_id
        save_server_log_config()

        embed = discord.Embed(
            title='✅ サーバーログ設定完了',
            description=f'**送信元:** {interaction.guild.name}\n**転送先:** {target_guild.name}\n\nこのサーバーのすべてのメッセージが転送先サーバーにログとして送信されます。',
            color=0x00ff00
        )
        embed.add_field(
            name='📋 機能詳細',
            value='• ユーザーメッセージを自動転送\n• チャンネルが存在しない場合は自動作成\n• 添付ファイル情報も含む\n• Botメッセージは除外',
            inline=False
        )
        embed.set_footer(text='設定を解除するには管理者にお問い合わせください')

        await interaction.response.send_message(embed=embed)

    except ValueError:
        await interaction.response.send_message('❌ 無効なサーバーIDです。数字のみを入力してください。', ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)

@bot.tree.command(name='server-log-status', description='サーバーログ設定状況を確認')
async def server_log_status(interaction: discord.Interaction):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    source_guild_id = str(interaction.guild.id)
    
    embed = discord.Embed(
        title='📊 サーバーログ設定状況',
        color=0x0099ff
    )

    if source_guild_id in server_log_configs:
        target_server_id = server_log_configs[source_guild_id]
        target_guild = bot.get_guild(int(target_server_id))
        target_name = target_guild.name if target_guild else f"不明なサーバー (ID: {target_server_id})"
        
        embed.add_field(
            name='🟢 ログ転送設定',
            value=f'**状態:** 有効\n**転送先:** {target_name}\n**サーバーID:** {target_server_id}',
            inline=False
        )
        embed.add_field(
            name='📋 転送内容',
            value='• ユーザーメッセージ\n• 添付ファイル情報\n• メッセージ時刻\n• 送信者情報',
            inline=False
        )
    else:
        embed.add_field(
            name='🔴 ログ転送設定',
            value='**状態:** 無効\n設定するには `/setup-server-log <サーバーID>` を使用してください。',
            inline=False
        )

    # Show reverse logging (if this server is a target)
    reverse_configs = []
    for source_id, target_id in server_log_configs.items():
        if target_id == source_guild_id:
            source_guild = bot.get_guild(int(source_id))
            source_name = source_guild.name if source_guild else f"不明なサーバー (ID: {source_id})"
            reverse_configs.append(source_name)

    if reverse_configs:
        embed.add_field(
            name='📥 受信ログ',
            value=f'以下のサーバーからログを受信中:\n• ' + '\n• '.join(reverse_configs),
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)



# Help system
COMMAND_HELP = {
    'nuke': {
        'description': 'チャンネルを再生成（設定を引き継ぎ）',
        'usage': '/nuke',
        'details': '現在のチャンネルを削除し、同じ設定で再作成します。チャンネル管理権限が必要です。'
    },
    'profile': {
        'description': 'ユーザープロフィールを表示',
        'usage': '/profile [ユーザー]',
        'details': '指定したユーザー（省略時は自分）のプロフィール情報を表示します。'
    },
    'help': {
        'description': 'ヘルプを表示',
        'usage': '/help [コマンド名]',
        'details': 'コマンド一覧を表示します。コマンド名を指定すると詳細な説明を表示します。'
    },

    'servers': {
        'description': 'ユーザーが参加しているサーバー一覧を表示',
        'usage': '/servers [ユーザー]',
        'details': '指定したユーザー（省略時は自分）が参加している共通サーバーの一覧を表示します。各サーバーのメンバー数、参加日、ロール情報も含まれます。'
    },
    'setuprole': {
        'description': 'ロール取得パネルを設置',
        'usage': '/setuprole [ロール名]',
        'details': '誰でもボタンをクリックしてロールを取得できるパネルを設置します。ロール名を指定すると特定のロール専用パネルが作成され、省略すると全ロール選択パネルが作成されます。ロール管理権限が必要です。'
    },
    'antispam-config': {
        'description': '荒らし対策設定を表示・変更',
        'usage': '/antispam-config [action]',
        'details': '同じメッセージの連投を検知して対策します。30秒以内に同じメッセージを3回以上送信した場合、すべての重複メッセージを削除し1時間のタイムアウトを適用します。actionに"show"で設定表示、"reset"でデータリセットができます。メッセージ管理権限が必要です。'
    },
    'spam-status': {
        'description': '現在のスパム検知状況を表示',
        'usage': '/spam-status',
        'details': '現在監視中のユーザー数やBotの追跡状況を表示します。メッセージ管理権限が必要です。'
    },
    'giveaway': {
        'description': 'Giveawayを開始',
        'usage': '/giveaway <景品>',
        'details': '指定した景品でGiveawayを開始します。時間は1h, 3h, 5h, 24h, 48hから選択できます。参加者はボタンをクリックして参加できます。メッセージ管理権限が必要です。'
    },

    'set-join-leave-channel': {
        'description': '入退室ログチャンネルを設定',
        'usage': '/set-join-leave-channel [#チャンネル]',
        'details': 'メンバーの参加・退出時にログを送信するチャンネルを設定します。チャンネルを省略すると現在のチャンネルが設定されます。サーバー管理権限が必要です。'
    },

    'join-leave-status': {
        'description': '入退室ログ設定状況を確認',
        'usage': '/join-leave-status',
        'details': '現在の入退室ログ設定状況を確認します。'
    },
    'translate': {
        'description': 'logとります',
        'usage': '/translate <送信先サーバーID>',
        'details': '2つのサーバー間に双方向のメッセージブリッジを設定します。両サーバーの全チャンネルが自動的に同期され、メッセージが双方向で転送されます。存在しないチャンネルは自動作成されます。サーバー管理権限が必要です。'
    },
    'setup-server-log': {
        'description': 'サーバー間ログ転送を設定',
        'usage': '/setup-server-log <転送先サーバーID>',
        'details': '現在のサーバーから指定したサーバーにすべてのメッセージをログとして転送します。対応するチャンネルが存在しない場合は自動作成されます。サーバー管理権限が必要です。'
    },
    'server-log-status': {
        'description': 'サーバーログ設定状況を確認',
        'usage': '/server-log-status',
        'details': '現在のサーバーログ転送設定を確認します。'
    },
    'ticket-panel': {
        'description': 'チケット作成パネルを設置',
        'usage': '/ticket-panel [カテゴリー名]',
        'details': 'チケット作成パネルを設置します。カテゴリー名を指定すると、作成されるチケットチャンネルが特定のカテゴリーに分類されます。チャンネル管理権限が必要です。'
    },
    'ticket-list': {
        'description': 'チケット一覧を表示',
        'usage': '/ticket-list [状態]',
        'details': 'チケットの一覧を表示します。状態を指定すると、特定の状態のチケットのみを表示します（例: open, closed）。メッセージ管理権限が必要です。'
    },
    'close-ticket': {
        'description': 'チケットを強制的に閉じる',
        'usage': '/close-ticket <チケットID>',
        'details': '指定されたチケットを強制的に閉じます。管理者権限が必要です。'
    },
    'poll': {
        'description': '投票を作成',
        'usage': '/poll <質問> <選択肢1,選択肢2,選択肢3...>',
        'details': '投票を作成します。選択肢はカンマで区切って入力してください。最大10個まで設定可能です。投票作成で20XP、投票参加で10XPを獲得できます。'
    },
    'poll-results': {
        'description': '投票結果を表示',
        'usage': '/poll-results <投票ID>',
        'details': '指定された投票の詳細な結果を表示します。投票IDはメッセージIDです。'
    },
    'level': {
        'description': 'ユーザーのレベルを表示',
        'usage': '/level [ユーザー]',
        'details': '指定したユーザー（省略時は自分）のレベル、経験値、進行度を表示します。メッセージ送信で5XP獲得できます。'
    },
    'ranking': {
        'description': 'サーバーのレベルランキングを表示',
        'usage': '/ranking',
        'details': 'サーバー内のユーザーのレベルランキングを表示します。上位10名まで表示されます。'
    }
}

@bot.tree.command(name='help', description='ヘルプを表示')
async def help_command(interaction: discord.Interaction, command: str = None):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if command is None:
        # Show all commands
        embed = discord.Embed(
            title='🤖 ボットコマンド一覧',
            description='使用可能なコマンドの一覧です。詳細は `/help コマンド名` で確認できます。',
            color=0x0099ff
        )

        for cmd_name, cmd_info in COMMAND_HELP.items():
            embed.add_field(
                name=f"/{cmd_name}",
                value=cmd_info['description'],
                inline=False
            )

        embed.set_footer(text="例: /help auth - authコマンドの詳細を表示")
        await interaction.response.send_message(embed=embed)

    else:
        # Show specific command help
        if command in COMMAND_HELP:
            cmd_info = COMMAND_HELP[command]
            embed = discord.Embed(
                title=f'📖 /{command} コマンドヘルプ',
                color=0x00ff00
            )
            embed.add_field(name='説明', value=cmd_info['description'], inline=False)
            embed.add_field(name='使用方法', value=f"`{cmd_info['usage']}`", inline=False)
            embed.add_field(name='詳細', value=cmd_info['details'], inline=False)

            await interaction.response.send_message(embed=embed)
        else:
            available_commands = ', '.join(COMMAND_HELP.keys())
            await interaction.response.send_message(
                f'❌ コマンド "{command}" が見つかりません。\n'
                f'利用可能なコマンド: {available_commands}'
            )

def run_bot():
    """Run Discord bot"""
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print('DISCORD_TOKEN環境変数が設定されていません。')
        return

    print("Starting Discord bot...")
    bot.run(token)

# Server message logging system
server_log_configs = {}  # {source_server_id: target_server_id}

def save_server_log_config():
    """Save server log configuration"""
    try:
        with open('server_log_config.json', 'w', encoding='utf-8') as f:
            json.dump(server_log_configs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving server log config: {e}")

def load_server_log_config():
    """Load server log configuration"""
    global server_log_configs
    try:
        if os.path.exists('server_log_config.json'):
            with open('server_log_config.json', 'r', encoding='utf-8') as f:
                server_log_configs = json.load(f)
    except Exception as e:
        print(f"Error loading server log config: {e}")
        server_log_configs = {}

async def on_message_for_copy(message):
    """Handle message copying functionality"""
    # This function can be implemented later for message copying features
    pass

async def on_message_for_server_translation(message):
    """Handle server translation functionality"""
    # This function can be implemented later for translation features
    pass

async def on_message_for_server_logging(message):
    """Handle server-to-server message logging"""
    if message.author.bot:
        return
    
    source_guild_id = str(message.guild.id)
    
    # Check if this server has logging configured
    if source_guild_id not in server_log_configs:
        return
    
    target_guild_id = server_log_configs[source_guild_id]
    target_guild = bot.get_guild(int(target_guild_id))
    
    if not target_guild:
        print(f"Target guild {target_guild_id} not found")
        return
    
    # Find or create corresponding channel in target server
    source_channel_name = message.channel.name
    target_channel = discord.utils.get(target_guild.text_channels, name=source_channel_name)
    
    if not target_channel:
        try:
            # Create channel if it doesn't exist
            category = None
            if message.channel.category:
                category = discord.utils.get(target_guild.categories, name=message.channel.category.name)
                if not category:
                    category = await target_guild.create_category(message.channel.category.name)
            
            target_channel = await target_guild.create_text_channel(
                name=source_channel_name,
                category=category,
                topic=f"Log from {message.guild.name}#{source_channel_name}"
            )
            print(f"Created channel #{source_channel_name} in {target_guild.name}")
        except Exception as e:
            print(f"Failed to create channel: {e}")
            return
    
    # Prepare log message
    embed = discord.Embed(
        description=message.content,
        color=0x00ff99,
        timestamp=message.created_at
    )
    embed.set_author(
        name=f"{message.author.display_name} ({message.author.name})",
        icon_url=message.author.avatar.url if message.author.avatar else None
    )
    embed.set_footer(text=f"From: {message.guild.name} #{message.channel.name}")
    
    # Handle attachments
    files = []
    if message.attachments:
        attachment_info = []
        for attachment in message.attachments:
            attachment_info.append(f"[{attachment.filename}]({attachment.url})")
        
        if attachment_info:
            embed.add_field(
                name="📎 添付ファイル",
                value="\n".join(attachment_info),
                inline=False
            )
    
    try:
        await target_channel.send(embed=embed)
        print(f"Logged message from {message.guild.name} to {target_guild.name}")
    except Exception as e:
        print(f"Failed to send log message: {e}")

# channel auto creation
channel_configs = {} # {server_id: {channel_name: {"type": "text" or "voice", "category": category_name}}
def save_translation_config():
    """Save channel configuration"""
    try:
        with open('channel_config.json', 'w', encoding='utf-8') as f:
            json.dump(channel_configs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving channel config: {e}")
def load_translation_config():
    """Load channel configuration"""
    global channel_configs
    try:
        if os.path.exists('channel_config.json'):
            with open('channel_config.json', 'r', encoding='utf-8') as f:
                channel_configs = json.load(f)
    except Exception as e:
        print(f"Error loading channel config: {e}")
        channel_configs = {}

async def create_channel_if_not_exists(guild, channel_name, channel_type="text", category_name=None):
    """Create channel if it does not exist."""
    existing_channel = discord.utils.get(guild.channels, name=channel_name)
    if not existing_channel:
        print(f"Channel {channel_name} does not exist. Creating...")
        if category_name:
            category = discord.utils.get(guild.categories, name=category_name)
            if not category:
                category = await guild.create_category(category_name)
        else:
            category = None

        if channel_type == "text":
            await guild.create_text_channel(channel_name, category=category)
        elif channel_type == "voice":
            await guild.create_voice_channel(channel_name, category=category)
        print(f"Channel {channel_name} created successfully.")

# Run the application
if __name__ == '__main__':
    # Start Flask server in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    port = int(os.environ.get('PORT', 5000))
    print(f"Flask server started on port {port}")

    # Start Discord bot
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print('DISCORD_TOKEN環境変数が設定されていません。')
        exit(1)

    bot.run(token)
