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
        'tickets': {}
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

    # Load translation configuration
    load_translation_config()
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

    # Anti-spam for human users
    if not message.author.bot:
        # Initialize user history if not exists
        if user_id not in user_message_history:
            user_message_history[user_id] = []

        # Add current message timestamp
        user_message_history[user_id].append(current_time)

        # Keep only messages from last 10 seconds
        user_message_history[user_id] = [
            timestamp for timestamp in user_message_history[user_id] 
            if current_time - timestamp <= 10
        ]

        message_count = len(user_message_history[user_id])

        # Check for spam (3+ messages in 10 seconds)
        if message_count >= 3:
            try:
                print(f"Attempting to timeout user {message.author.name} (ID: {user_id})")
                print(f"Bot permissions: {message.guild.me.guild_permissions}")
                print(f"Bot highest role: {message.guild.me.top_role}")
                print(f"Target user highest role: {message.author.top_role}")

                # Delete the spam message
                await message.delete()

                # 3+ messages: 1 hour timeout immediately
                from datetime import timedelta
                timeout_duration = discord.utils.utcnow() + timedelta(hours=1)
                await message.author.timeout(timeout_duration, reason="Spam detected - 3+ consecutive messages")

                print(f"Successfully timed out {message.author.name}")

                warning_embed = discord.Embed(
                    title="🚫 タイムアウト適用",
                    description=f"{message.author.mention} は連投により1時間のタイムアウトが適用されました。",
                    color=0xff0000
                )
                await message.channel.send(embed=warning_embed, delete_after=10)

                # Clear message history after action
                user_message_history[user_id] = []

            except discord.Forbidden as e:
                print(f"Failed to moderate {message.author.name} - insufficient permissions: {e}")
            except Exception as e:
                print(f"Error in anti-spam: {e}")

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
        await interaction.response.send_message('❌ チャンネル管理権限が必要です。')
        return

    channel = interaction.channel

    # Store channel settings
    channel_name = channel.name
    channel_topic = channel.topic
    channel_category = channel.category
    channel_position = channel.position

    # Create new channel with same settings
    new_channel = await channel.guild.create_text_channel(
        name=channel_name,
        topic=channel_topic,
        category=channel_category,
        position=channel_position
    )

    # Delete old channel
    await channel.delete()

    # Send confirmation in new channel
    embed = discord.Embed(
        title='💥 チャンネルがヌークされました！',
        description='チャンネルが正常に再生成されました。',
        color=0xff0000
    )
    await new_channel.send(embed=embed)

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
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message('❌ ロール管理権限が必要です。', ephemeral=True)
        return

    # If specific role name is provided, create a panel for that specific role
    if role_name:
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            await interaction.response.send_message(f'❌ "{role_name}" ロールが見つかりません。', ephemeral=True)
            return

        # Check if the role can be assigned
        if (role.name == '@everyone' or 
            role.managed or 
            role.permissions.administrator or
            role >= interaction.guild.me.top_role):
            await interaction.response.send_message(f'❌ "{role_name}" ロールは付与できません。', ephemeral=True)
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
        await interaction.response.send_message(embed=embed, view=view)
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
        await interaction.response.send_message(embed=embed, view=view)

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
            name="連投検知",
            value="• 10秒間に3回以上: 1時間タイムアウト",
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
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    try:
        # Check permissions (optional - you can remove this if anyone should be able to create giveaways)
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message('❌ メッセージ管理権限が必要です。', ephemeral=True)
            return

        # Create time selection embed
        embed = discord.Embed(
            title='🎉 Giveaway設定',
            description=f'**景品:** {prize}\n\n時間を選択してGiveawayを開始してください。',
            color=0x00ff99
        )
        embed.set_footer(text='下のメニューから時間を選択してください')

        view = GiveawayTimeView(prize)
        await interaction.response.send_message(embed=embed, view=view)

    except Exception as e:
        print(f"Error in giveaway command: {e}")
        try:
            await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
        except:
            await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)

# Ticket system commands
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
            embed.set_footer(text='サポートスタッフが対応します')

            message = await channel.send(embed=embed)
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
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message('❌ チャンネル管理権限が必要です。', ephemeral=True)
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
    await interaction.response.send_message(embed=embed, view=view)

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
        'details': '荒らし対策の設定を表示または変更します。actionに"show"で設定表示、"reset"でデータリセットができます。メッセージ管理権限が必要です。'
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
