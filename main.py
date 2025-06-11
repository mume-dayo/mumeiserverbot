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

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    # Load join/leave configuration
    load_join_leave_config()
    # Load translation configuration
    load_translation_config()
    # Load server translation configuration
    load_server_translation_config()
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

    @discord.ui.button(label='🎭 ロールを取得', style=discord.ButtonStyle.primary, emoji='🎭')
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

    @discord.ui.button(label='🎭 認証する', style=discord.ButtonStyle.primary, emoji='🎭')
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





# Ticket View with close button
class TicketView(discord.ui.View):
    def __init__(self, ticket_id):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

    @discord.ui.button(label='チケットを閉じる', style=discord.ButtonStyle.danger, emoji='🔒')
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()

        if self.ticket_id not in data['tickets']:
            await interaction.response.send_message('❌ チケットが見つかりません。', ephemeral=True)
            return

        ticket = data['tickets'][self.ticket_id]
        user_id = str(interaction.user.id)

        # Check if user can close the ticket (creator or admin)
        if user_id != ticket['user_id'] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ このチケットを閉じる権限がありません。', ephemeral=True)
            return

        # Update ticket status
        data['tickets'][self.ticket_id]['status'] = 'closed'
        data['tickets'][self.ticket_id]['closed_at'] = datetime.now().isoformat()
        data['tickets'][self.ticket_id]['closed_by'] = user_id
        save_data(data)

        # Update embed
        embed = discord.Embed(
            title=f'🎫 チケット #{self.ticket_id} (クローズ済み)',
            description=f'**件名:** {ticket["subject"]}\n**説明:** {ticket.get("description", "なし")}\n**作成者:** <@{ticket["user_id"]}>',
            color=0x808080
        )
        embed.add_field(name='ステータス', value='🔴 クローズ済み', inline=True)
        embed.add_field(name='クローズ日時', value=f'<t:{int(datetime.now().timestamp())}:F>', inline=True)
        embed.add_field(name='クローズ実行者', value=interaction.user.mention, inline=True)

        # Disable button
        button.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

        # Send confirmation message
        await interaction.followup.send('🔒 チケットがクローズされました。')



# Nuke channel
@bot.tree.command(name='nuke', description='チャンネルを再生成（設定を引き継ぎ）')
async def nuke_channel(interaction: discord.Interaction):
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

# Public Ticket Creation View
class PublicTicketView(discord.ui.View):
    def __init__(self, category_name=None):
        super().__init__(timeout=None)
        self.category_name = category_name

    @discord.ui.button(label='🎫 チケットを作成', style=discord.ButtonStyle.primary, emoji='🎫')
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            print(f"Ticket creation button clicked by {interaction.user.name}")
            # Show modal for ticket creation
            modal = TicketModal(self.category_name)
            await interaction.response.send_modal(modal)
            print("Modal sent successfully")
        except Exception as e:
            print(f"Error in create_ticket_button: {e}")
            try:
                await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
            except:
                await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)

# Ticket Creation Modal
class TicketModal(discord.ui.Modal, title='🎫 チケット作成'):
    def __init__(self, category_name=None):
        super().__init__()
        self.category_name = category_name

    subject = discord.ui.TextInput(
        label='件名',
        placeholder='チケットの件名を入力してください...',
        required=True,
        max_length=100
    )

    description = discord.ui.TextInput(
        label='説明',
        placeholder='問題の詳細を入力してください...',
        style=discord.TextStyle.long,
        required=False,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        user_id = str(interaction.user.id)
        ticket_id = str(len(data['tickets']) + 1)

        # Create ticket channel
        guild = interaction.guild

        # Use custom category if specified, otherwise default
        if self.category_name:
            category = discord.utils.get(guild.categories, name=self.category_name)
            if not category:
                category = await guild.create_category(self.category_name)
        else:
            category = discord.utils.get(guild.categories, name="🎫 チケット")
            if not category:
                category = await guild.create_category("🎫 チケット")

        # Set permissions for the ticket channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.owner: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        # Add permissions for users with Administrator permission
        for member in guild.members:
            if member.guild_permissions.administrator:
                overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        # Create the ticket channel
        channel_name = f"ticket-{ticket_id}-{interaction.user.name}"
        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )

            data['tickets'][ticket_id] = {
                'user_id': user_id,
                'subject': str(self.subject.value),
                'description': str(self.description.value) if self.description.value else "",
                'status': 'open',
                'created_at': datetime.now().isoformat(),
                'guild_id': str(interaction.guild.id),
                'channel_id': str(ticket_channel.id)
            }

            save_data(data)

            # Send initial message to ticket channel
            embed = discord.Embed(
                title=f'🎫 チケット #{ticket_id}',
                description=f'**件名:** {self.subject.value}\n**説明:** {self.description.value or "なし"}\n**作成者:** {interaction.user.mention}',
                color=0xff9900
            )
            embed.add_field(name='ステータス', value='🟢 オープン', inline=True)
            embed.add_field(name='作成日時', value=f'<t:{int(datetime.now().timestamp())}:F>', inline=True)

            # Add close button
            view = TicketView(ticket_id)
            await ticket_channel.send(embed=embed, view=view)

            # Response to user
            await interaction.response.send_message(
                f'✅ チケット #{ticket_id} を作成しました！\n'
                f'専用チャンネル: {ticket_channel.mention}',
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message(f'❌ チケットチャンネルの作成に失敗しました: {str(e)}', ephemeral=True)

# Ticket panel command
@bot.tree.command(name='ticket-panel', description='チケット作成パネルを設置')
async def ticket_panel(interaction: discord.Interaction, category_name: str = None):
    try:
        print(f"Ticket panel command called by {interaction.user.name}")

        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message('❌ チャンネル管理権限が必要です。', ephemeral=True)
            return

        # Create category if specified but doesn't exist
        category_status = ""
        if category_name:
            target_category = discord.utils.get(interaction.guild.categories, name=category_name)
            if not target_category:
                try:
                    target_category = await interaction.guild.create_category(category_name)
                    category_status = f"\n✅ カテゴリ `{category_name}` を作成しました。"
                    print(f"Created new category: {category_name}")
                except Exception as e:
                    await interaction.response.send_message(f'❌ カテゴリ "{category_name}" の作成に失敗しました: {str(e)}', ephemeral=True)
                    return

        embed = discord.Embed(
            title='🎫 サポートチケット',
            description='何かお困りのことがありましたら、下のボタンをクリックしてサポートチケットを作成してください。\n\n'
                       '**チケットについて:**\n'
                       '• 専用のプライベートチャンネルが作成されます\n'
                       '• あなたとサーバーの管理者のみがアクセス可能です\n'
                       '• 問題が解決したらチケットをクローズしてください',
            color=0x00ff99
        )

        if category_name:
            embed.add_field(name='📁 作成先カテゴリ', value=f'`{category_name}`', inline=True)

        embed.set_footer(text='24時間365日サポート対応')

        view = PublicTicketView(category_name)

        # Send response with category creation status if applicable
        response_text = f"🎫 チケットパネルを設置しました！{category_status}" if category_status else None

        if response_text:
            await interaction.response.send_message(response_text, embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

        print(f"Ticket panel sent successfully with category: {category_name}")

    except Exception as e:
        print(f"Error in ticket-panel command: {e}")
        try:
            await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
        except:
            await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)

# Setup role panel command
@bot.tree.command(name='setuprole', description='ロール取得パネルを設置')
async def setup_role(interaction: discord.Interaction, role_name: str = None):
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





# Join/Leave logging system
join_leave_channels = {}  # {guild_id: channel_id}

def save_join_leave_config():
    """Save join/leave channel configuration"""
    try:
        with open('join_leave_config.json', 'w', encoding='utf-8') as f:
            json.dump(join_leave_channels, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving join/leave config: {e}")

def load_join_leave_config():
    """Load join/leave channel configuration"""
    global join_leave_channels
    try:
        if os.path.exists('join_leave_config.json'):
            with open('join_leave_config.json', 'r', encoding='utf-8') as f:
                join_leave_channels = json.load(f)
    except Exception as e:
        print(f"Error loading join/leave config: {e}")
        join_leave_channels = {}

@bot.event
async def on_member_join(member):
    """Handle member join events"""
    guild_id = str(member.guild.id)

    if guild_id in join_leave_channels:
        channel_id = join_leave_channels[guild_id]
        channel = bot.get_channel(int(channel_id))

        if channel:
            # Create join embed
            embed = discord.Embed(
                title="JOIN一入室ログ",
                description=f"{member.display_name} がサーバーに参加しました！",
                color=0x00ff00,
                timestamp=datetime.now()
            )

            # Add user information
            embed.add_field(
                name="ユーザー:",
                value=f"{member.mention}\n({member.id})",
                inline=False
            )

            # Add server information
            embed.add_field(
                name="サーバー:",
                value=f"{member.guild.name}\n({member.guild.id})",
                inline=False
            )

            # Add member count
            embed.add_field(
                name="現在の人数:",
                value=f"{member.guild.member_count}人",
                inline=False
            )

            # Set user avatar as thumbnail
            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)

            embed.set_footer(text=datetime.now().strftime('%Y/%m/%d %H:%M'))

            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending join message: {e}")

@bot.event
async def on_member_remove(member):
    """Handle member leave events"""
    guild_id = str(member.guild.id)

    if guild_id in join_leave_channels:
        channel_id = join_leave_channels[guild_id]
        channel = bot.get_channel(int(channel_id))

        if channel:
            # Create leave embed
            embed = discord.Embed(
                title="LEAVE一退室ログ",
                description=f"{member.display_name} がサーバーから退出しました。",
                color=0xff0000,
                timestamp=datetime.now()
            )

            # Add user information
            embed.add_field(
                name="ユーザー:",
                value=f"{member.mention}\n({member.id})",
                inline=False
            )

            # Add server information
            embed.add_field(
                name="サーバー:",
                value=f"{member.guild.name}\n({member.guild.id})",
                inline=False
            )

            # Add member count
            embed.add_field(
                name="現在の人数:",
                value=f"{member.guild.member_count}人",
                inline=False
            )

            # Set user avatar as thumbnail
            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)

            embed.set_footer(text=datetime.now().strftime('%Y/%m/%d %H:%M'))

            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending leave message: {e}")

# Set join/leave log channel command
@bot.tree.command(name='set-join-leave-channel', description='入退室ログチャンネルを設定')
async def set_join_leave_channel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message('❌ サーバー管理権限が必要です。', ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    if channel is None:
        channel = interaction.channel

    # Save channel configuration
    join_leave_channels[guild_id] = str(channel.id)
    save_join_leave_config()

    embed = discord.Embed(
        title='✅ 入退室ログ設定完了',
        description=f'入退室ログを {channel.mention} に送信するように設定しました。',
        color=0x00ff00
    )
    embed.add_field(
        name='設定内容',
        value='• メンバーの参加・退出時に自動でログが送信されます\n• ユーザー情報、サーバー情報、現在の人数が表示されます',
        inline=False
    )

    await interaction.response.send_message(embed=embed)



# Check join/leave log settings
@bot.tree.command(name='join-leave-status', description='入退室ログ設定状況を確認')
async def join_leave_status(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)

    embed = discord.Embed(
        title='📊 入退室ログ設定状況',
        color=0x0099ff
    )

    if guild_id in join_leave_channels:
        channel_id = join_leave_channels[guild_id]
        channel = bot.get_channel(int(channel_id))

        if channel:
            embed.add_field(
                name='✅ 設定済み',
                value=f'ログチャンネル: {channel.mention}',
                inline=False
            )
            embed.color = 0x00ff00
        else:
            embed.add_field(
                name='⚠️ 設定エラー',
                value='設定されたチャンネルが見つかりません',
                inline=False
            )
            embed.color = 0xff9900
    else:
        embed.add_field(
            name='❌ 未設定',
            value='入退室ログチャンネルが設定されていません',
            inline=False
        )
        embed.color = 0xff0000

    embed.add_field(
        name='設定方法',
        value='`/set-join-leave-channel [#チャンネル]` で設定できます',
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# Message copy/translate system
message_copy_config = {}  # {guild_id: {'source_channel': channel_id, 'target_guild': guild_id, 'target_channel': channel_id}}

def save_copy_config():
    """Save message copy configuration"""
    try:
        with open('message_copy_config.json', 'w', encoding='utf-8') as f:
            json.dump(message_copy_config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving copy config: {e}")

def load_copy_config():
    """Load message copy configuration"""
    global message_copy_config
    try:
        if os.path.exists('message_copy_config.json'):
            with open('message_copy_config.json', 'r', encoding='utf-8') as f:
                message_copy_config = json.load(f)
    except Exception as e:
        print(f"Error loading copy config: {e}")
        message_copy_config = {}

@bot.event
async def on_message_for_copy(message):
    """Handle message copying to other servers"""
    if message.author.bot:
        return

    guild_id = str(message.guild.id)
    if guild_id in message_copy_config:
        config = message_copy_config[guild_id]

        # Check if message is from configured source channel
        if str(message.channel.id) == config.get('source_channel'):
            target_guild_id = config.get('target_guild')
            target_channel_id = config.get('target_channel')

            if target_guild_id and target_channel_id:
                target_guild = bot.get_guild(int(target_guild_id))
                if target_guild:
                    target_channel = target_guild.get_channel(int(target_channel_id))
                    if target_channel:
                        try:
                            # Create embed for copied message
                            embed = discord.Embed(
                                description=message.content,
                                color=0x00ff99,
                                timestamp=message.created_at
                            )
                            embed.set_author(
                                name=f"{message.author.display_name} ({message.author.name})",
                                icon_url=message.author.avatar.url if message.author.avatar else None
                            )
                            embed.add_field(
                                name="元サーバー",
                                value=f"{message.guild.name} #{message.channel.name}",
                                inline=False
                            )

                            # Handle attachments
                            if message.attachments:
                                for attachment in message.attachments:
                                    if attachment.content_type and attachment.content_type.startswith('image/'):
                                        embed.set_image(url=attachment.url)
                                        break

                                if len(message.attachments) > 1:
                                    embed.add_field(
                                        name="添付ファイル",
                                        value=f"{len(message.attachments)}個のファイルが添付されています",
                                        inline=False
                                    )

                            await target_channel.send(embed=embed)

                        except Exception as e:
                            print(f"Error copying message: {e}")

# Modify the existing on_message event to include message copying
@bot.event
async def on_message_old(message):
    # This is the old on_message function - we'll rename it and call it from the new one
    pass

# Server-wide translation configuration
server_translation_config = {}  # {source_guild_id: target_guild_id}

def save_server_translation_config():
    """Save server translation configuration"""
    try:
        with open('server_translation_config.json', 'w', encoding='utf-8') as f:
            json.dump(server_translation_config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving server translation config: {e}")

def load_server_translation_config():
    """Load server translation configuration"""
    global server_translation_config
    try:
        if os.path.exists('server_translation_config.json'):
            with open('server_translation_config.json', 'r', encoding='utf-8') as f:
                server_translation_config = json.load(f)
    except Exception as e:
        print(f"Error loading server translation config: {e}")
        server_translation_config = {}

async def create_mirrored_channel(source_channel, target_guild):
    """Create a mirrored channel in target guild"""
    try:
        # Check if channel already exists
        existing_channel = discord.utils.get(target_guild.channels, name=source_channel.name)
        if existing_channel:
            return existing_channel

        # Create category if source channel has one
        target_category = None
        if source_channel.category:
            target_category = discord.utils.get(target_guild.categories, name=source_channel.category.name)
            if not target_category:
                target_category = await target_guild.create_category(source_channel.category.name)

        # Create the channel based on type
        if isinstance(source_channel, discord.TextChannel):
            new_channel = await target_guild.create_text_channel(
                name=source_channel.name,
                topic=source_channel.topic,
                category=target_category
            )
        elif isinstance(source_channel, discord.VoiceChannel):
            new_channel = await target_guild.create_voice_channel(
                name=source_channel.name,
                category=target_category
            )
        else:
            return None

        print(f"Created mirrored channel: {new_channel.name} in {target_guild.name}")
        return new_channel

    except Exception as e:
        print(f"Error creating mirrored channel: {e}")
        return None

@bot.event
async def on_message_for_server_translation(message):
    """Handle server-wide message translation"""
    if message.author.bot:
        return

    source_guild_id = str(message.guild.id)
    if source_guild_id in server_translation_config:
        target_guild_id = server_translation_config[source_guild_id]
        target_guild = bot.get_guild(int(target_guild_id))
        
        if target_guild:
            # Find or create corresponding channel
            target_channel = discord.utils.get(target_guild.channels, name=message.channel.name)
            
            if not target_channel:
                # Auto-create the channel
                target_channel = await create_mirrored_channel(message.channel, target_guild)
            
            if target_channel and isinstance(target_channel, discord.TextChannel):
                try:
                    # Send simple message with just name and content
                    formatted_message = f"**{message.author.display_name}**: {message.content}"
                    
                    # Handle attachments by including URLs
                    if message.attachments:
                        attachment_urls = [attachment.url for attachment in message.attachments]
                        formatted_message += f"\n{' '.join(attachment_urls)}"
                    
                    await target_channel.send(formatted_message)

                except Exception as e:
                    print(f"Error sending translated message: {e}")

@bot.tree.command(name='translate', description='logとります')
async def translate_bridge(interaction: discord.Interaction, target_server_id: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message('❌ サーバー管理権限が必要です。', ephemeral=True)
        return

    try:
        target_guild = bot.get_guild(int(target_server_id))
        if not target_guild:
            await interaction.response.send_message('❌ 指定されたサーバーにBotがアクセスできません。', ephemeral=True)
            return

        # Check if bot has necessary permissions in target guild
        if not target_guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message('❌ 送信先サーバーでチャンネル管理権限がありません。', ephemeral=True)
            return

        # Save server-wide translation configuration (bidirectional bridge)
        source_guild_id = str(interaction.guild.id)
        target_guild_id = str(target_guild.id)
        
        # Set up bidirectional bridge
        server_translation_config[source_guild_id] = target_guild_id
        server_translation_config[target_guild_id] = source_guild_id
        save_server_translation_config()

        # Create initial mirror channels for existing text channels (both ways)
        created_channels_in_target = []
        created_channels_in_source = []
        
        # Mirror channels from source to target
        for channel in interaction.guild.text_channels:
            if not discord.utils.get(target_guild.channels, name=channel.name):
                new_channel = await create_mirrored_channel(channel, target_guild)
                if new_channel:
                    created_channels_in_target.append(new_channel.name)
        
        # Mirror channels from target to source
        for channel in target_guild.text_channels:
            if not discord.utils.get(interaction.guild.channels, name=channel.name):
                new_channel = await create_mirrored_channel(channel, interaction.guild)
                if new_channel:
                    created_channels_in_source.append(new_channel.name)

        embed = discord.Embed(
            title='🌉 bridge',
            description=f'サーバー間ブリッジが設定されました。',
            color=0x00ff00
        )
        embed.add_field(
            name='接続サーバー',
            value=f'**{interaction.guild.name}** ⇄ **{target_guild.name}**',
            inline=False
        )
        
        total_created = len(created_channels_in_target) + len(created_channels_in_source)
        if total_created > 0:
            embed.add_field(
                name='作成されたチャンネル',
                value=f'合計 {total_created}個のチャンネルを作成しました',
                inline=False
            )

        embed.add_field(
            name='📋 動作',
            value='• 両サーバーの全チャンネルが双方向でブリッジされます\n'
                  '• 新しいチャンネルは自動的に作成されます\n'
                  '• メッセージは双方向で同期されます',
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    except ValueError:
        await interaction.response.send_message('❌ 無効なサーバーIDです。', ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f'❌ 設定エラー: {str(e)}', ephemeral=True)

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
    'ticket-panel': {
        'description': 'チケット作成パネルを設置',
        'usage': '/ticket-panel [カテゴリ名]',
        'details': '誰でもボタンをクリックしてチケットを作成できるパネルを設置します。カテゴリ名を指定すると、そのカテゴリ内にチケットが作成されます。チャンネル管理権限が必要です。'
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
    }
}

@bot.tree.command(name='help', description='ヘルプを表示')
async def help_command(interaction: discord.Interaction, command: str = None):
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
