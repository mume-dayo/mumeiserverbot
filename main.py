import discord
from discord.ext import commands
import json
import os
from datetime import datetime
from flask import Flask
from threading import Thread
import time

app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot is running!"

@app.route('/health')
def health():
    return {"status": "healthy", "bot": "running"}

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

bot_start_time = datetime.now()

ALLOWED_SERVERS = [1373116978709139577, 1383225206797242398]

spam_tracker = {}
bot_spam_tracker = {}

user_message_history = {}
bot_message_count = {}

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
    return guild_id in ALLOWED_SERVERS

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

    server_count = len(bot.guilds)
    activity = discord.Game(name=f"{server_count}サーバをプレイ中...")
    await bot.change_presence(status=discord.Status.online, activity=activity)

    load_translation_config()
    load_server_log_config()
    load_meigen_config()
    
    for guild_id, config in meigen_channels.items():
        if guild_id not in meigen_tasks:
            if isinstance(config, dict):
                channel_id = config["channel_id"]
                interval = config["interval"]
                task = asyncio.create_task(send_interval_meigen(guild_id, channel_id, interval))
            else:
                channel_id = config
                task = asyncio.create_task(send_daily_meigen(guild_id, channel_id))
            meigen_tasks[guild_id] = task
    
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')

@bot.event
async def on_guild_join(guild):
    server_count = len(bot.guilds)
    activity = discord.Game(name=f"{server_count}サーバをプレイ中...")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print(f"Joined guild: {guild.name} (ID: {guild.id}). Now in {server_count} servers.")

@bot.event
async def on_guild_remove(guild):
    server_count = len(bot.guilds)
    activity = discord.Game(name=f"{server_count}サーバをプレイ中...")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print(f"Left guild: {guild.name} (ID: {guild.id}). Now in {server_count} servers.")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if not is_allowed_server(message.guild.id):
        return

    await on_message_for_copy(message)
    await on_message_for_server_translation(message)
    await on_message_for_server_logging(message)

    if message.content.startswith('!'):
        await bot.process_commands(message)
        return

    user_id = message.author.id
    current_time = time.time()

    if message.author.bot:
        if user_id not in bot_message_count:
            bot_message_count[user_id] = 0

        bot_message_count[user_id] += 1

        if bot_message_count[user_id] >= 2:
            try:
                await message.delete()
                await message.guild.ban(message.author, reason="Bot spam detected - 2+ consecutive messages")

                warning_embed = discord.Embed(
                    title="🚫 Bot Ban",
                    description=f"Bot {message.author.mention} has been banned for consecutive message spam.",
                    color=0xff0000
                )
                await message.channel.send(embed=warning_embed, delete_after=10)

                if user_id in bot_message_count:
                    del bot_message_count[user_id]

            except discord.Forbidden:
                print(f"Failed to ban bot {message.author.name} - insufficient permissions")
            except Exception as e:
                print(f"Error banning bot: {e}")
    else:
        if user_id in bot_message_count:
            del bot_message_count[user_id]

    if not message.author.bot:
        if user_id not in user_message_history:
            user_message_history[user_id] = []

        user_message_history[user_id].append({
            'content': message.content,
            'timestamp': current_time
        })

        user_message_history[user_id] = [
            msg for msg in user_message_history[user_id]
            if current_time - msg['timestamp'] <= 30
        ]

        if len(user_message_history[user_id]) >= 3:
            recent_messages = user_message_history[user_id][-3:]
            
            if (len(set(msg['content'] for msg in recent_messages)) == 1 and 
                recent_messages[0]['content'].strip() != ""):
                
                try:
                    print(f"Identical message spam detected from {message.author.name} (ID: {user_id})")
                    print(f"Repeated message: {message.content[:50]}...")

                    messages_to_delete = []
                    async for msg in message.channel.history(limit=10):
                        if (msg.author.id == user_id and 
                            msg.content == message.content and
                            current_time - msg.created_at.timestamp() <= 30):
                            messages_to_delete.append(msg)
                            if len(messages_to_delete) >= 3:
                                break
                    
                    for msg in messages_to_delete[:3]:
                        try:
                            await msg.delete()
                        except:
                            pass

                    print(f"Deleted {min(len(messages_to_delete), 3)} consecutive identical messages")

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

                    user_message_history[user_id] = []

                except discord.Forbidden as e:
                    print(f"Failed to moderate {message.author.name} - insufficient permissions: {e}")
                except Exception as e:
                    print(f"Error in anti-spam: {e}")

    if not message.author.bot and not message.content.startswith('/'):
        add_experience(message.author.id, message.guild.id, 5)

    await bot.process_commands(message)

class RoleSelectionView(discord.ui.View):
    def __init__(self, available_roles):
        super().__init__(timeout=300)
        self.available_roles = available_roles
        self.setup_buttons()

    def setup_buttons(self):
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
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message('❌ ロール取得は管理者のみが利用できます。', ephemeral=True)
                return

            if role in interaction.user.roles:
                await interaction.response.send_message(f'❌ あなたは既に {role.name} ロールを持っています。', ephemeral=True)
                return

            await interaction.user.add_roles(role)

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

class SpecificRoleView(discord.ui.View):
    def __init__(self, role):
        super().__init__(timeout=None)
        self.role = role

    @discord.ui.button(label='ろーるをしゅとく！', style=discord.ButtonStyle.primary)
    async def get_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ ロール取得は管理者のみが利用できます。', ephemeral=True)
            return

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

        try:
            if self.role in interaction.user.roles:
                await interaction.response.send_message(f'❌ あなたは既に {self.role.name} ロールを持っています。', ephemeral=True)
                return

            await interaction.user.add_roles(self.role)
            await interaction.response.send_message(f'✅ {self.role.name} ロールが付与されました！', ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message('❌ ロールを付与する権限がありません。', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ ロールの付与に失敗しました: {str(e)}', ephemeral=True)

class PublicAuthView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='認証する', style=discord.ButtonStyle.primary)
    async def authenticate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ 認証は管理者のみが利用できます。', ephemeral=True)
            return

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

        embed = discord.Embed(
            title='🎭 ロール選択',
            description='取得したいロールを下のボタンから選択してください。\n\n**利用可能なロール:**',
            color=0x00ff99
        )

        role_list = []
        for role in assignable_roles[:10]:
            role_list.append(f'• {role.name} ({len(role.members)} メンバー)')

        embed.add_field(
            name='📋 ロール一覧',
            value='\n'.join(role_list) + ('...' if len(assignable_roles) > 10 else ''),
            inline=False
        )

        embed.set_footer(text='ボタンをクリックしてロールを取得')

        view = RoleSelectionView(assignable_roles)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)









# Nuke channel
@bot.tree.command(name='nuke', description='チャンネルを再生成（設定を引き継ぎ）')
async def nuke_channel(interaction: discord.Interaction):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者権限が必要です。', ephemeral=True)
        return

    channel = interaction.channel

    channel_name = channel.name
    channel_topic = channel.topic
    channel_category = channel.category
    channel_position = channel.position
    channel_overwrites = channel.overwrites

    await interaction.response.send_message('🔄 チャンネルを再生成しています...', ephemeral=True)

    try:
        new_channel = await channel.guild.create_text_channel(
            name=f"{channel_name}-new",
            topic=channel_topic,
            category=channel_category,
            overwrites=channel_overwrites
        )

        embed = discord.Embed(
            title='💥 チャンネルがヌークされました！',
            description='チャンネルが正常に再生成されました。',
            color=0xff0000
        )
        await new_channel.send(embed=embed)

        await channel.delete(reason="Nuke command executed")

        await new_channel.edit(name=channel_name, position=channel_position)

    except discord.Forbidden:
        await interaction.followup.send('❌ チャンネルの削除・作成権限が不足しています。', ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)

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

@bot.tree.command(name='setuprole', description='ロール取得パネルを設置')
async def setup_role(interaction: discord.Interaction, role_name: str = None):
    try:
        await interaction.response.defer()
        
        if not is_allowed_server(interaction.guild.id):
            await interaction.followup.send('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send('❌ 管理者権限が必要です。', ephemeral=True)
            return

        if role_name:
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if not role:
                await interaction.followup.send(f'❌ "{role_name}" ロールが見つかりません。', ephemeral=True)
                return

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

@bot.tree.command(name='servers', description='ユーザーが参加しているサーバー一覧を表示')
async def view_servers(interaction: discord.Interaction, user: discord.Member = None):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if user is None:
        user = interaction.user

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
        member = guild.get_member(user.id)
        if member:
            joined_at = member.joined_at
            join_date = joined_at.strftime('%Y/%m/%d') if joined_at else '不明'

            member_count = guild.member_count

            roles = [role.name for role in member.roles if role.name != '@everyone']
            roles_text = ', '.join(roles[:3]) + ('...' if len(roles) > 3 else '') if roles else 'なし'

            embed.add_field(
                name=f'📋 {guild.name}',
                value=f'**メンバー数:** {member_count}\n**参加日:** {join_date}\n**ロール:** {roles_text}',
                inline=True
            )

    embed.set_footer(text=f'総サーバー数: {len(mutual_guilds)}')
    await interaction.response.send_message(embed=embed)

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

    active_users = len([uid for uid, history in user_message_history.items() if history])
    tracked_bots = len(bot_message_count)

    embed.add_field(name="監視中ユーザー", value=f"{active_users}人", inline=True)
    embed.add_field(name="追跡中Bot", value=f"{tracked_bots}個", inline=True)
    embed.add_field(name="システム状態", value="🟢 稼働中", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)

active_giveaways = {}

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
async def setup_server_log(interaction: discord.Interaction, target_server_id: str, channel_id: str = None):
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
        
        # Determine which channels to log
        if channel_id:
            # Single channel mode
            try:
                source_channel = bot.get_channel(int(channel_id))
                if not source_channel or source_channel.guild.id != interaction.guild.id:
                    await interaction.response.send_message('❌ 指定されたチャンネルが見つからないか、このサーバーのチャンネルではありません。', ephemeral=True)
                    return
                mode_text = f'チャンネル #{source_channel.name}'
                # Store configuration with specific channel
                server_log_configs[source_guild_id] = {"target_server": target_server_id, "channel_id": channel_id}
            except ValueError:
                await interaction.response.send_message('❌ 無効なチャンネルIDです。数字のみを入力してください。', ephemeral=True)
                return
        else:
            # All channels mode
            mode_text = 'サーバーの全チャンネル'
            server_log_configs[source_guild_id] = {"target_server": target_server_id, "channel_id": None}
        
        save_server_log_config()

        embed = discord.Embed(
            title='✅ サーバーログ設定完了',
            description=f'**送信元:** {interaction.guild.name}\n**転送先:** {target_guild.name}\n**対象:** {mode_text}\n\nメッセージが転送先サーバーにログとして送信されます。',
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
        config = server_log_configs[source_guild_id]
        # Handle both old and new format
        if isinstance(config, dict):
            target_server_id = config["target_server"]
            channel_id = config.get("channel_id")
        else:
            # Old format (backward compatibility)
            target_server_id = config
            channel_id = None
            
        target_guild = bot.get_guild(int(target_server_id))
        target_name = target_guild.name if target_guild else f"不明なサーバー (ID: {target_server_id})"
        
        if channel_id:
            source_channel = bot.get_channel(int(channel_id))
            channel_text = f'#{source_channel.name}' if source_channel else f'チャンネルID: {channel_id}'
        else:
            channel_text = '全チャンネル'
        
        embed.add_field(
            name='🟢 ログ転送設定',
            value=f'**状態:** 有効\n**転送先:** {target_name}\n**サーバーID:** {target_server_id}\n**対象:** {channel_text}',
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
    for source_id, config in server_log_configs.items():
        # Handle both old and new format
        if isinstance(config, dict):
            target_id = config["target_server"]
        else:
            target_id = config
            
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



# Random quotes system
import random
import asyncio
from datetime import datetime, timedelta

MEIGEN_QUOTES = [
    "トーマス・エジソン\n「向こうはとても美しいよ。」",
    "アイザック・ニュートン\n「私はただ、海辺で貝殻を拾って遊んでいた子どもにすぎない。」",
    "チャールズ・ダーウィン\n「私は死ぬのを恐れてはいない。」",
    "ハンフリー・ボガート（俳優）\n「俺の人生で唯一の後悔は、スコッチではなくマティーニを飲んでいたことだ。」",
    "ボブ・マーリー\n「金は命を買えない。」",
    "スティーブ・ジョブズ（公式な最期の言葉かは不明）\n「Oh wow. Oh wow. Oh wow.」",
    "フランツ・カフカ\n「殺さないでくれ。僕はまだ生きていたい。」",
    "エドガー・アラン・ポー\n「主よ、私の哀れな魂を救いたまえ！」",
    "ルートヴィヒ・ヴァン・ベートーヴェン\n「諸君、喝采せよ。喜劇は終わった。」"
]

meigen_channels = {}  # {guild_id: channel_id}
meigen_tasks = {}  # {guild_id: task}

def save_meigen_config():
    """Save meigen channel configuration"""
    try:
        with open('meigen_config.json', 'w', encoding='utf-8') as f:
            json.dump(meigen_channels, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving meigen config: {e}")

def load_meigen_config():
    """Load meigen channel configuration"""
    global meigen_channels
    try:
        if os.path.exists('meigen_config.json'):
            with open('meigen_config.json', 'r', encoding='utf-8') as f:
                meigen_channels = json.load(f)
    except Exception as e:
        print(f"Error loading meigen config: {e}")
        meigen_channels = {}

async def send_daily_meigen(guild_id, channel_id):
    """Send random quote at random time daily"""
    while True:
        # Wait for random time between 1-24 hours
        random_hours = random.uniform(1, 24)
        await asyncio.sleep(random_hours * 3600)
        
        try:
            guild = bot.get_guild(int(guild_id))
            if not guild:
                break
                
            channel = guild.get_channel(int(channel_id))
            if not channel:
                break
            
            # Select random quote
            quote = random.choice(MEIGEN_QUOTES)
            
            embed = discord.Embed(
                title="📜 今日の名言",
                description=quote,
                color=0xffd700
            )
            embed.set_footer(text="一日一回、ランダムな時間に配信されます")
            
            await channel.send(embed=embed)
            print(f"Sent daily meigen to {guild.name}#{channel.name}")
            
        except Exception as e:
            print(f"Error sending daily meigen: {e}")
            break

async def send_interval_meigen(guild_id, channel_id, interval_seconds):
    """Send random quote at specified intervals"""
    while True:
        await asyncio.sleep(interval_seconds)
        
        try:
            guild = bot.get_guild(int(guild_id))
            if not guild:
                break
                
            channel = guild.get_channel(int(channel_id))
            if not channel:
                break
            
            # Select random quote
            quote = random.choice(MEIGEN_QUOTES)
            
            # Format interval display
            if interval_seconds >= 3600:
                interval_display = f"{interval_seconds // 3600}時間"
            elif interval_seconds >= 60:
                interval_display = f"{interval_seconds // 60}分"
            else:
                interval_display = f"{interval_seconds}秒"
            
            embed = discord.Embed(
                title="📜 定期名言",
                description=quote,
                color=0xffd700
            )
            embed.set_footer(text=f"{interval_display}間隔で配信されます")
            
            await channel.send(embed=embed)
            print(f"Sent interval meigen to {guild.name}#{channel.name} (interval: {interval_seconds}s)")
            
        except Exception as e:
            print(f"Error sending interval meigen: {e}")
            break

# Delete command
@bot.tree.command(name='delete', description='指定した数のメッセージを削除')
async def delete_messages(interaction: discord.Interaction, count: int, user: discord.Member = None):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者権限が必要です。', ephemeral=True)
        return

    if count <= 0 or count > 100:
        await interaction.response.send_message('❌ 削除するメッセージ数は1-100の間で指定してください。', ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        if user:
            # Delete messages from specific user
            deleted = 0
            async for message in interaction.channel.history(limit=200):
                if message.author == user and deleted < count:
                    await message.delete()
                    deleted += 1
                    await asyncio.sleep(0.5)  # Rate limit protection
            
            await interaction.followup.send(f'✅ {user.display_name}のメッセージを{deleted}件削除しました。', ephemeral=True)
        else:
            # Delete latest messages
            messages = []
            async for message in interaction.channel.history(limit=count):
                messages.append(message)
            
            if messages:
                await interaction.channel.delete_messages(messages)
                await interaction.followup.send(f'✅ {len(messages)}件のメッセージを削除しました。', ephemeral=True)
            else:
                await interaction.followup.send('❌ 削除するメッセージが見つかりません。', ephemeral=True)

    except discord.Forbidden:
        await interaction.followup.send('❌ メッセージを削除する権限がありません。', ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'❌ メッセージの削除中にエラーが発生しました: {str(e)}', ephemeral=True)

# Meigen channel setting command
@bot.tree.command(name='meigen_channel_setting', description='名言を指定間隔で送信するチャンネルを設定')
async def meigen_channel_setting(interaction: discord.Interaction, interval: str = "1h"):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message('❌ サーバー管理権限が必要です。', ephemeral=True)
        return

    # Parse interval
    try:
        if interval.endswith('s'):
            seconds = int(interval[:-1])
            if seconds < 60:
                await interaction.response.send_message('❌ 最小間隔は60秒です。', ephemeral=True)
                return
        elif interval.endswith('m'):
            seconds = int(interval[:-1]) * 60
            if seconds < 60:
                await interaction.response.send_message('❌ 最小間隔は1分です。', ephemeral=True)
                return
        elif interval.endswith('h'):
            seconds = int(interval[:-1]) * 3600
        else:
            await interaction.response.send_message('❌ 時間形式が正しくありません。例: 30s, 5m, 2h', ephemeral=True)
            return
    except ValueError:
        await interaction.response.send_message('❌ 時間形式が正しくありません。例: 30s, 5m, 2h', ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    channel_id = str(interaction.channel.id)

    # Save configuration with interval
    meigen_channels[guild_id] = {"channel_id": channel_id, "interval": seconds}
    save_meigen_config()

    # Stop existing task if any
    if guild_id in meigen_tasks:
        meigen_tasks[guild_id].cancel()

    # Start new task with specified interval
    task = asyncio.create_task(send_interval_meigen(guild_id, channel_id, seconds))
    meigen_tasks[guild_id] = task

    # Format interval display
    if seconds >= 3600:
        interval_display = f"{seconds // 3600}時間"
    elif seconds >= 60:
        interval_display = f"{seconds // 60}分"
    else:
        interval_display = f"{seconds}秒"

    embed = discord.Embed(
        title='✅ 名言チャンネル設定完了',
        description=f'このチャンネル（{interaction.channel.mention}）に{interval_display}間隔で名言を送信します。',
        color=0x00ff00
    )
    embed.add_field(
        name='📜 配信内容',
        value='有名人の名言をランダムに配信します',
        inline=False
    )
    embed.add_field(
        name='⏰ 配信間隔',
        value=f'{interval_display}ごと',
        inline=False
    )
    embed.set_footer(text='設定を変更するには再度このコマンドを実行してください')

    await interaction.response.send_message(embed=embed)

# Help system
COMMAND_HELP = {
    'nuke': {
        'description': 'チャンネルを再生成（設定を引き継ぎ）',
        'usage': '/nuke',
        'details': '現在のチャンネルを削除し、同じ設定で再作成します。管理者権限が必要です。'
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
        'details': '管理者のみがボタンをクリックしてロールを取得できるパネルを設置します。ロール名を指定すると特定のロール専用パネルが作成され、省略すると全ロール選択パネルが作成されます。管理者権限が必要です。'
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
        'usage': '/setup-server-log <転送先サーバーID> [チャンネルID]',
        'details': '現在のサーバーから指定したサーバーにメッセージをログとして転送します。チャンネルIDを指定した場合はそのチャンネルのみをログ転送し、省略した場合は全チャンネルが対象になります。対応するチャンネルが存在しない場合は自動作成されます。サーバー管理権限が必要です。'
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
    },
    'delete': {
        'description': '指定した数のメッセージを削除',
        'usage': '/delete <メッセージ数> [ユーザー]',
        'details': '指定した数のメッセージを削除します。ユーザーを指定すると、そのユーザーのメッセージのみを削除します。1-100件まで指定可能です。管理者権限が必要です。'
    },
    'meigen_channel_setting': {
        'description': '名言を指定間隔で送信するチャンネルを設定',
        'usage': '/meigen_channel_setting [間隔]',
        'details': '実行したチャンネルに指定した間隔で有名人の名言を送信するように設定します。間隔は30s（秒）、5m（分）、2h（時間）の形式で指定できます。省略時は1時間間隔です。最小間隔は60秒です。サーバー管理権限が必要です。'
    },
    'timenuke': {
        'description': '指定した時間間隔でチャンネルを定期的にnuke',
        'usage': '/timenuke <間隔>',
        'details': '実行したチャンネルを指定した間隔で定期的に再生成します。間隔は1m（分）、2h（時間）、1d（日）の形式で指定できます。最小間隔は1分です。チャンネル内のメッセージは全て削除されますが、チャンネル設定は引き継がれます。管理者権限が必要です。'
    },
    'stop-timenuke': {
        'description': '定期nukeを停止',
        'usage': '/stop-timenuke',
        'details': '現在設定されている定期ヌークを停止します。管理者権限が必要です。'
    }
}

@bot.tree.command(name='online_check', description='ボットのオンライン状態を確認')
async def online_check(interaction: discord.Interaction):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    # Get bot uptime
    uptime_seconds = (datetime.now() - bot_start_time).total_seconds()
    uptime_hours = int(uptime_seconds // 3600)
    uptime_minutes = int((uptime_seconds % 3600) // 60)
    uptime_secs = int(uptime_seconds % 60)

    embed = discord.Embed(
        title='🟢 ボットオンライン状態',
        description='ボットは正常に稼働しています！',
        color=0x00ff00
    )
    embed.add_field(
        name='📊 ステータス',
        value='🟢 オンライン',
        inline=True
    )
    embed.add_field(
        name='⏰ 稼働時間',
        value=f'{uptime_hours}時間 {uptime_minutes}分 {uptime_secs}秒',
        inline=True
    )
    embed.add_field(
        name='🌐 接続サーバー数',
        value=f'{len(bot.guilds)}サーバー',
        inline=True
    )
    embed.add_field(
        name='💾 レイテンシ',
        value=f'{round(bot.latency * 1000)}ms',
        inline=True
    )
    embed.set_footer(text=f'Bot ID: {bot.user.id} | 最終チェック: {datetime.now().strftime("%Y/%m/%d %H:%M:%S")}')

    await interaction.response.send_message(embed=embed)

@bot.command(name='link_bot')
async def link_bot_command(ctx):
    """Show invite links for all servers the bot is in"""
    if not is_allowed_server(ctx.guild.id):
        await ctx.send('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq')
        return

    if not ctx.author.guild_permissions.administrator:
        await ctx.send('❌ 管理者権限が必要です。')
        return

    embed = discord.Embed(
        title='🔗 ボット参加サーバーの招待リンク',
        description=f'ボットが参加している{len(bot.guilds)}個のサーバーの招待リンク一覧',
        color=0x0099ff
    )

    invite_count = 0
    for guild in bot.guilds:
        try:
            # Try to get existing invites first
            invites = await guild.invites()
            invite_url = None
            
            if invites:
                # Use the first available invite
                invite_url = invites[0].url
            else:
                # Create a new invite if none exist
                # Find a suitable channel to create invite from
                suitable_channel = None
                
                # Prefer general channels
                for channel in guild.text_channels:
                    if channel.name.lower() in ['general', 'welcome', 'main', 'chat']:
                        if channel.permissions_for(guild.me).create_instant_invite:
                            suitable_channel = channel
                            break
                
                # If no preferred channel found, use first available
                if not suitable_channel:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).create_instant_invite:
                            suitable_channel = channel
                            break
                
                if suitable_channel:
                    invite = await suitable_channel.create_invite(
                        max_age=0,  # Never expires
                        max_uses=0,  # Unlimited uses
                        reason="Bot invite link generation"
                    )
                    invite_url = invite.url

            if invite_url:
                embed.add_field(
                    name=f'🌐 {guild.name}',
                    value=f'[招待リンク]({invite_url})\nメンバー数: {guild.member_count}',
                    inline=True
                )
                invite_count += 1
            else:
                embed.add_field(
                    name=f'❌ {guild.name}',
                    value='招待リンクを作成できません\n(権限不足)',
                    inline=True
                )

        except discord.Forbidden:
            embed.add_field(
                name=f'❌ {guild.name}',
                value='招待リンクを取得できません\n(権限不足)',
                inline=True
            )
        except Exception as e:
            print(f"Error getting invite for {guild.name}: {e}")
            embed.add_field(
                name=f'❌ {guild.name}',
                value='エラーが発生しました',
                inline=True
            )

    embed.set_footer(text=f'招待リンク取得成功: {invite_count}/{len(bot.guilds)}サーバー')
    
    # If embed is too large, split into multiple messages
    if len(embed.fields) > 25:  # Discord embed field limit
        # Send first 25 fields
        first_embed = discord.Embed(
            title='🔗 ボット参加サーバーの招待リンク (1/2)',
            description=f'ボットが参加している{len(bot.guilds)}個のサーバーの招待リンク一覧',
            color=0x0099ff
        )
        
        for field in embed.fields[:25]:
            first_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        
        first_embed.set_footer(text=f'招待リンク取得成功: {invite_count}/{len(bot.guilds)}サーバー (続きあり)')
        await ctx.send(embed=first_embed)
        
        # Send remaining fields
        second_embed = discord.Embed(
            title='🔗 ボット参加サーバーの招待リンク (2/2)',
            color=0x0099ff
        )
        
        for field in embed.fields[25:]:
            second_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        
        second_embed.set_footer(text=f'招待リンク取得成功: {invite_count}/{len(bot.guilds)}サーバー')
        await ctx.send(embed=second_embed)
    else:
        await ctx.send(embed=embed)

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
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print('DISCORD_TOKEN環境変数が設定されていません。')
        return
    print("Starting Discord bot...")
    bot.run(token)

server_log_configs = {}

def save_server_log_config():
    try:
        with open('server_log_config.json', 'w', encoding='utf-8') as f:
            json.dump(server_log_configs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving server log config: {e}")

def load_server_log_config():
    global server_log_configs
    try:
        if os.path.exists('server_log_config.json'):
            with open('server_log_config.json', 'r', encoding='utf-8') as f:
                server_log_configs = json.load(f)
    except Exception as e:
        print(f"Error loading server log config: {e}")
        server_log_configs = {}

async def on_message_for_copy(message):
    pass

async def on_message_for_server_translation(message):
    pass

async def on_message_for_server_logging(message):
    if message.author.bot:
        return
    source_guild_id = str(message.guild.id)
    if source_guild_id not in server_log_configs:
        return
    config = server_log_configs[source_guild_id]
    if isinstance(config, dict):
        target_guild_id = config["target_server"]
        specific_channel_id = config.get("channel_id")
        if specific_channel_id and str(message.channel.id) != specific_channel_id:
            return
    else:
        target_guild_id = config
        specific_channel_id = None
    target_guild = bot.get_guild(int(target_guild_id))
    if not target_guild:
        print(f"Target guild {target_guild_id} not found")
        return
    source_channel_name = message.channel.name
    target_channel = discord.utils.get(target_guild.text_channels, name=source_channel_name)
    if not target_channel:
        try:
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

channel_configs = {}

def save_translation_config():
    try:
        with open('channel_config.json', 'w', encoding='utf-8') as f:
            json.dump(channel_configs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving channel config: {e}")

def load_translation_config():
    global channel_configs
    try:
        if os.path.exists('channel_config.json'):
            with open('channel_config.json', 'r', encoding='utf-8') as f:
                channel_configs = json.load(f)
    except Exception as e:
        print(f"Error loading channel config: {e}")
        channel_configs = {}

async def create_channel_if_not_exists(guild, channel_name, channel_type="text", category_name=None):
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

time_nuke_tasks = {}

async def execute_time_nuke(guild_id, channel_id, interval_seconds):
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            guild = bot.get_guild(int(guild_id))
            if not guild:
                break
            channel = guild.get_channel(int(channel_id))
            if not channel:
                break
            channel_name = channel.name
            channel_topic = channel.topic
            channel_category = channel.category
            channel_position = channel.position
            channel_overwrites = channel.overwrites
            new_channel = await guild.create_text_channel(
                name=f"{channel_name}-new",
                topic=channel_topic,
                category=channel_category,
                overwrites=channel_overwrites
            )
            embed = discord.Embed(
                title='💥 定期ヌーク実行！',
                description='チャンネルが定期的に再生成されました。',
                color=0xff0000
            )
            await new_channel.send(embed=embed)
            await channel.delete(reason="Time nuke executed")
            await new_channel.edit(name=channel_name, position=channel_position)
            print(f"Time nuke executed for {guild.name}#{channel_name}")
        except Exception as e:
            print(f"Error in time nuke: {e}")
            break

@bot.tree.command(name='timenuke', description='指定した時間間隔でチャンネルを定期的にnuke')
async def timenuke_command(interaction: discord.Interaction, interval: str):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者権限が必要です。', ephemeral=True)
        return
    try:
        if interval.endswith('m'):
            minutes = int(interval[:-1])
            if minutes < 1:
                await interaction.response.send_message('❌ 最小間隔は1分です。', ephemeral=True)
                return
            seconds = minutes * 60
        elif interval.endswith('h'):
            hours = int(interval[:-1])
            seconds = hours * 3600
        elif interval.endswith('d'):
            days = int(interval[:-1])
            seconds = days * 86400
        else:
            await interaction.response.send_message('❌ 時間形式が正しくありません。例: 5m, 2h, 1d', ephemeral=True)
            return
    except ValueError:
        await interaction.response.send_message('❌ 時間形式が正しくありません。例: 5m, 2h, 1d', ephemeral=True)
        return
    guild_id = str(interaction.guild.id)
    channel_id = str(interaction.channel.id)
    if guild_id in time_nuke_tasks:
        time_nuke_tasks[guild_id].cancel()
    task = asyncio.create_task(execute_time_nuke(guild_id, channel_id, seconds))
    time_nuke_tasks[guild_id] = task
    if seconds >= 86400:
        interval_display = f"{seconds // 86400}日"
    elif seconds >= 3600:
        interval_display = f"{seconds // 3600}時間"
    else:
        interval_display = f"{seconds // 60}分"
    embed = discord.Embed(
        title='⏰ 定期ヌーク設定完了',
        description=f'このチャンネル（{interaction.channel.mention}）を{interval_display}間隔で定期的にヌークします。',
        color=0xff6b6b
    )
    embed.add_field(
        name='⚠️ 注意事項',
        value='• チャンネル内のメッセージは全て削除されます\n• チャンネル設定は引き継がれます\n• Bot再起動まで有効です',
        inline=False
    )
    embed.add_field(
        name='⏰ 実行間隔',
        value=f'{interval_display}ごと',
        inline=False
    )
    embed.set_footer(text='停止するには /stop-timenuke を使用してください')
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='stop-timenuke', description='定期nukeを停止')
async def stop_timenuke_command(interaction: discord.Interaction):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者権限が必要です。', ephemeral=True)
        return
    guild_id = str(interaction.guild.id)
    if guild_id not in time_nuke_tasks:
        await interaction.response.send_message('❌ このサーバーで定期ヌークは設定されていません。', ephemeral=True)
        return
    time_nuke_tasks[guild_id].cancel()
    del time_nuke_tasks[guild_id]
    embed = discord.Embed(
        title='✅ 定期ヌーク停止',
        description='定期ヌークが停止されました。',
        color=0x00ff00
    )
    await interaction.response.send_message(embed=embed)

def get_user_warnings(user_id, guild_id):
    data = load_data()
    if 'warnings' not in data:
        data['warnings'] = {}
    guild_key = str(guild_id)
    user_key = str(user_id)
    if guild_key not in data['warnings']:
        data['warnings'][guild_key] = {}
    if user_key not in data['warnings'][guild_key]:
        return 0
    return data['warnings'][guild_key][user_key]['count']

def add_user_warning(user_id, guild_id, reason, moderator_id):
    data = load_data()
    if 'warnings' not in data:
        data['warnings'] = {}
    guild_key = str(guild_id)
    user_key = str(user_id)
    if guild_key not in data['warnings']:
        data['warnings'][guild_key] = {}
    if user_key not in data['warnings'][guild_key]:
        data['warnings'][guild_key][user_key] = {'count': 0, 'history': []}
    data['warnings'][guild_key][user_key]['count'] += 1
    data['warnings'][guild_key][user_key]['history'].append({
        'reason': reason,
        'moderator_id': str(moderator_id),
        'timestamp': datetime.now().isoformat()
    })
    save_data(data)
    return data['warnings'][guild_key][user_key]['count']

@bot.tree.command(name='warn', description='ユーザーに警告を与える')
async def warn_user(interaction: discord.Interaction, user: discord.Member, reason: str = "規則違反"):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message('❌ メッセージ管理権限が必要です。', ephemeral=True)
        return
    if user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者に警告を与えることはできません。', ephemeral=True)
        return
    warning_count = add_user_warning(user.id, interaction.guild.id, reason, interaction.user.id)
    embed = discord.Embed(
        title='⚠️ 警告システム',
        color=0xff9900
    )
    embed.add_field(name='対象ユーザー', value=user.mention, inline=True)
    embed.add_field(name='警告回数', value=f'{warning_count}/3', inline=True)
    embed.add_field(name='理由', value=reason, inline=False)
    embed.add_field(name='モデレーター', value=interaction.user.mention, inline=True)
    try:
        if warning_count == 1:
            embed.add_field(name='措置', value='警告のみ', inline=False)
            embed.set_footer(text='次回警告で1時間ミュート、3回目でBanとなります')
        elif warning_count == 2:
            from datetime import timedelta
            timeout_duration = discord.utils.utcnow() + timedelta(hours=1)
            await user.timeout(timeout_duration, reason=f"2回目の警告: {reason}")
            embed.add_field(name='措置', value='1時間タイムアウト', inline=False)
            embed.set_footer(text='次回警告でBanとなります')
        elif warning_count >= 3:
            await user.ban(reason=f"3回目の警告: {reason}")
            embed.add_field(name='措置', value='サーバーからBan', inline=False)
            embed.set_footer(text='規則違反により永久Ban')
        await interaction.response.send_message(embed=embed)
        try:
            dm_embed = discord.Embed(
                title=f'⚠️ {interaction.guild.name}で警告を受けました',
                description=f'**理由:** {reason}\n**警告回数:** {warning_count}/3',
                color=0xff9900
            )
            if warning_count == 1:
                dm_embed.add_field(name='次回について', value='次回警告で1時間ミュート、3回目でBanとなります', inline=False)
            elif warning_count == 2:
                dm_embed.add_field(name='措置', value='1時間のタイムアウトが適用されました', inline=False)
            elif warning_count >= 3:
                dm_embed.add_field(name='措置', value='サーバーからBanされました', inline=False)
            await user.send(embed=dm_embed)
        except:
            pass
    except discord.Forbidden:
        await interaction.response.send_message('❌ ユーザーに措置を適用する権限がありません。', ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)

@bot.tree.command(name='warnings', description='ユーザーの警告履歴を表示')
async def show_warnings(interaction: discord.Interaction, user: discord.Member):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message('❌ メッセージ管理権限が必要です。', ephemeral=True)
        return

    data = load_data()
    guild_key = str(interaction.guild.id)
    user_key = str(user.id)

    if ('warnings' not in data or guild_key not in data['warnings'] or 
        user_key not in data['warnings'][guild_key]):
        await interaction.response.send_message(f'❌ {user.display_name}の警告記録はありません。', ephemeral=True)
        return

    warning_data = data['warnings'][guild_key][user_key]
    embed = discord.Embed(
        title=f'⚠️ {user.display_name}の警告履歴',
        description=f'**警告回数:** {warning_data["count"]}/3',
        color=0xff9900
    )

    for i, warning in enumerate(warning_data['history'][-5:], 1):  # Show last 5 warnings
        moderator = interaction.guild.get_member(int(warning['moderator_id']))
        moderator_name = moderator.display_name if moderator else '不明'
        
        embed.add_field(
            name=f'警告 #{i}',
            value=f'**理由:** {warning["reason"]}\n**モデレーター:** {moderator_name}\n**日時:** {warning["timestamp"][:10]}',
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# Temporary mute command
@bot.tree.command(name='tempmute', description='ユーザーを一時的にミュート')
async def temp_mute(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "規則違反"):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message('❌ メンバータイムアウト権限が必要です。', ephemeral=True)
        return

    if user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者をミュートすることはできません。', ephemeral=True)
        return

    # Parse duration
    try:
        if duration.endswith('m'):
            minutes = int(duration[:-1])
            seconds = minutes * 60
        elif duration.endswith('h'):
            hours = int(duration[:-1])
            seconds = hours * 3600
        elif duration.endswith('d'):
            days = int(duration[:-1])
            seconds = days * 86400
        else:
            await interaction.response.send_message('❌ 時間形式が正しくありません。例: 30m, 2h, 1d', ephemeral=True)
            return
        
        if seconds > 2419200:  # 28 days max
            await interaction.response.send_message('❌ 最大ミュート期間は28日です。', ephemeral=True)
            return
            
    except ValueError:
        await interaction.response.send_message('❌ 時間形式が正しくありません。例: 30m, 2h, 1d', ephemeral=True)
        return

    try:
        from datetime import timedelta
        timeout_duration = discord.utils.utcnow() + timedelta(seconds=seconds)
        await user.timeout(timeout_duration, reason=reason)

        # Format duration display
        if seconds >= 86400:
            duration_display = f"{seconds // 86400}日"
        elif seconds >= 3600:
            duration_display = f"{seconds // 3600}時間"
        else:
            duration_display = f"{seconds // 60}分"

        embed = discord.Embed(
            title='🔇 一時ミュート適用',
            color=0xff0000
        )
        embed.add_field(name='対象ユーザー', value=user.mention, inline=True)
        embed.add_field(name='期間', value=duration_display, inline=True)
        embed.add_field(name='理由', value=reason, inline=False)
        embed.add_field(name='モデレーター', value=interaction.user.mention, inline=True)
        embed.add_field(name='解除時刻', value=f'<t:{int(timeout_duration.timestamp())}:F>', inline=False)

        await interaction.response.send_message(embed=embed)

        # Send DM to user
        try:
            dm_embed = discord.Embed(
                title=f'🔇 {interaction.guild.name}でミュートされました',
                description=f'**期間:** {duration_display}\n**理由:** {reason}\n**解除時刻:** <t:{int(timeout_duration.timestamp())}:F>',
                color=0xff0000
            )
            await user.send(embed=dm_embed)
        except:
            pass

    except discord.Forbidden:
        await interaction.response.send_message('❌ ユーザーをミュートする権限がありません。', ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)



# Support system
class SupportResponseView(discord.ui.View):
    def __init__(self, request_user, request_content):
        super().__init__(timeout=300)
        self.request_user = request_user
        self.request_content = request_content

    @discord.ui.button(label='✅ 対応可能', style=discord.ButtonStyle.success, emoji='✅')
    async def support_available(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message('❌ サポート対応権限がありません。', ephemeral=True)
            return

        # Notify the user
        try:
            dm_embed = discord.Embed(
                title='✅ サポート対応開始',
                description=f'あなたのサポート要請に {interaction.user.display_name} が対応します。\n\n**要請内容:** {self.request_content}',
                color=0x00ff00
            )
            dm_embed.set_footer(text=f'サポーター: {interaction.user.display_name} | {interaction.guild.name}')
            
            await self.request_user.send(embed=dm_embed)
            
            # Update the support message
            embed = discord.Embed(
                title='✅ サポート対応中',
                description=f'**要請者:** {self.request_user.mention}\n**対応者:** {interaction.user.mention}\n**内容:** {self.request_content}',
                color=0x00ff00
            )
            embed.add_field(name='対応開始', value=f'<t:{int(datetime.now().timestamp())}:F>', inline=False)
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except discord.Forbidden:
            await interaction.response.send_message('❌ ユーザーにDMを送信できませんでした。', ephemeral=True)

    @discord.ui.button(label='❌ 対応不可', style=discord.ButtonStyle.danger, emoji='❌')
    async def support_unavailable(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message('❌ サポート対応権限がありません。', ephemeral=True)
            return

        # Update the support message
        embed = discord.Embed(
            title='❌ サポート対応不可',
            description=f'**要請者:** {self.request_user.mention}\n**内容:** {self.request_content}\n\n{interaction.user.mention} は現在対応できません。',
            color=0xff0000
        )
        embed.add_field(name='対応不可通知', value=f'<t:{int(datetime.now().timestamp())}:F>', inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)

@bot.tree.command(name='support-request', description='サポートを要請')
async def support_request(interaction: discord.Interaction, content: str):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    support_channel = discord.utils.get(interaction.guild.text_channels, name="サポート要請")
    if not support_channel:
        try:
            support_channel = await interaction.guild.create_text_channel("サポート要請")
        except:
            await interaction.response.send_message('❌ サポートチャンネルを作成できませんでした。', ephemeral=True)
            return

    embed = discord.Embed(
        title='🆘 サポート要請',
        description=f'**要請者:** {interaction.user.mention}\n**内容:** {content}',
        color=0xff9900
    )
    embed.add_field(name='要請日時', value=f'<t:{int(datetime.now().timestamp())}:F>', inline=False)
    embed.set_footer(text='管理者は対応可能かどうかボタンで応答してください')

    view = SupportResponseView(interaction.user, content)
    await support_channel.send(embed=embed, view=view)
    
    await interaction.response.send_message('✅ サポート要請を送信しました。対応者が決まり次第、DMでご連絡します。', ephemeral=True)

@bot.tree.command(name='allmessage', description='サーバーの全メッセージを指定したサーバーにコピー')
async def allmessage_command(interaction: discord.Interaction, target_server_id: str, channel_id: str = None):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者権限が必要です。', ephemeral=True)
        return

    try:
        target_guild_id = int(target_server_id)
        target_guild = bot.get_guild(target_guild_id)
        
        if not target_guild:
            await interaction.response.send_message('❌ 指定されたサーバーが見つかりません。Botがそのサーバーに参加していることを確認してください。', ephemeral=True)
            return
        
        if not target_guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message('❌ 転送先サーバーでチャンネル管理権限が必要です。', ephemeral=True)
            return

        if channel_id:
            try:
                source_channel = bot.get_channel(int(channel_id))
                if not source_channel or source_channel.guild.id != interaction.guild.id:
                    await interaction.response.send_message('❌ 指定されたチャンネルが見つからないか、このサーバーのチャンネルではありません。', ephemeral=True)
                    return
                channels_to_process = [source_channel]
                mode_text = f'チャンネル #{source_channel.name}'
            except ValueError:
                await interaction.response.send_message('❌ 無効なチャンネルIDです。数字のみを入力してください。', ephemeral=True)
                return
        else:
            channels_to_process = interaction.guild.text_channels
            mode_text = 'サーバーの全チャンネル'

        source_guild_id = str(interaction.guild.id)
        if channel_id:
            server_log_configs[source_guild_id] = {"target_server": target_server_id, "channel_id": channel_id}
        else:
            server_log_configs[source_guild_id] = {"target_server": target_server_id, "channel_id": None}
        save_server_log_config()

        await interaction.response.send_message(
            f'✅ メッセージコピーを開始しました。\n**転送先:** {target_guild.name}\n**対象:** {mode_text}\n\n処理には時間がかかる場合があります。進行状況は別メッセージで更新されます。\n\n🔄 **サーバーログも自動で設定されました。**', 
            ephemeral=True
        )

        status_channel = interaction.channel

        status_embed = discord.Embed(
            title='📋 メッセージコピー進行状況',
            description=f'**送信元:** {interaction.guild.name}\n**転送先:** {target_guild.name}\n**対象:** {mode_text}\n\nメッセージをコピーしています...',
            color=0x0099ff
        )
        status_embed.add_field(
            name='進行状況',
            value='開始中...',
            inline=False
        )
        status_embed.set_footer(text=f'開始者: {interaction.user.display_name}')
        
        try:
            status_message = await status_channel.send(embed=status_embed)
        except:
            status_message = None

        copied_messages = 0
        created_channels = 0

        for channel in channels_to_process:
            try:
                target_channel = discord.utils.get(target_guild.text_channels, name=channel.name)
                
                if not target_channel:
                    category = None
                    if channel.category:
                        category = discord.utils.get(target_guild.categories, name=channel.category.name)
                        if not category:
                            category = await target_guild.create_category(channel.category.name)
                    
                    target_channel = await target_guild.create_text_channel(
                        name=channel.name,
                        category=category,
                        topic=f"Copy from {interaction.guild.name}#{channel.name}"
                    )
                    created_channels += 1

                channel_messages = 0
                async for message in channel.history(limit=None, oldest_first=True):
                    
                    embed = discord.Embed(
                        description=message.content if message.content else "(添付ファイルのみ)",
                        color=0x00ff99,
                        timestamp=message.created_at
                    )
                    embed.set_author(
                        name=f"{message.author.display_name} ({message.author.name})",
                        icon_url=message.author.avatar.url if message.author.avatar else None
                    )
                    embed.set_footer(text=f"Original: {interaction.guild.name} #{channel.name}")
                    
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
                        copied_messages += 1
                        channel_messages += 1
                        
                        if copied_messages % 100 == 0 and status_message:
                            try:
                                status_embed.clear_fields()
                                status_embed.add_field(
                                    name='進行状況',
                                    value=f'コピー済みメッセージ: {copied_messages}\n作成チャンネル: {created_channels}\n現在処理中: #{channel.name}',
                                    inline=False
                                )
                                await status_message.edit(embed=status_embed)
                            except Exception as e:
                                print(f"Status update error: {e}")
                                status_message = None
                        
                    except Exception as e:
                        print(f"Failed to copy message: {e}")
                        continue
                
                print(f"Copied {channel_messages} messages from #{channel.name}")
                
            except Exception as e:
                print(f"Error processing channel #{channel.name}: {e}")
                continue

        final_embed = discord.Embed(
            title='✅ メッセージコピー完了',
            description=f'**送信元:** {interaction.guild.name}\n**転送先:** {target_guild.name}',
            color=0x00ff00
        )
        final_embed.add_field(
            name='📊 統計情報',
            value=f'**コピーしたメッセージ:** {copied_messages}件\n**作成したチャンネル:** {created_channels}個',
            inline=False
        )
        final_embed.set_footer(text=f'完了者: {interaction.user.display_name} | 全てのメッセージが正常にコピーされました')
        
        if status_message:
            try:
                await status_message.edit(embed=final_embed)
            except Exception as e:
                print(f"Final status update error: {e}")
                try:
                    await status_channel.send(embed=final_embed)
                except Exception as e2:
                    print(f"Failed to send completion message: {e2}")
        else:
            try:
                await status_channel.send(embed=final_embed)
            except Exception as e:
                print(f"Failed to send completion message: {e}")

    except ValueError:
        try:
            await interaction.response.send_message('❌ 無効なサーバーIDです。数字のみを入力してください。', ephemeral=True)
        except:
            try:
                await interaction.followup.send('❌ 無効なサーバーIDです。数字のみを入力してください。', ephemeral=True)
            except:
                print("Failed to send error message about invalid server ID")
    except Exception as e:
        print(f"Error in allmessage command: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
            else:
                await interaction.followup.send(f'❌ エラーが発生しました: {str(e)}', ephemeral=True)
        except Exception as e2:
            print(f"Failed to send error message: {e2}")
            try:
                error_embed = discord.Embed(
                    title='❌ allmessageコマンドエラー',
                    description=f'エラーが発生しました: {str(e)}',
                    color=0xff0000
                )
                await interaction.channel.send(embed=error_embed)
            except Exception as e3:
                print(f"Failed to send error message to channel: {e3}")

@bot.tree.command(name='allmember', description='指定したロールをサーバーの全メンバーに付与')
async def allmember_command(interaction: discord.Interaction, role: discord.Role):
    if not is_allowed_server(interaction.guild.id):
        await interaction.response.send_message('❌ m.m.botを購入してください　https://discord.gg/5kwyPgd5fq', ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ 管理者権限が必要です。', ephemeral=True)
        return

    if role.name == '@everyone':
        await interaction.response.send_message('❌ @everyoneロールは付与できません。', ephemeral=True)
        return
    
    if role.managed:
        await interaction.response.send_message('❌ 管理されたロール（Bot用ロールなど）は付与できません。', ephemeral=True)
        return
    
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message('❌ Botの最高ロールより上位のロールは付与できません。', ephemeral=True)
        return
    
    if role.permissions.administrator:
        await interaction.response.send_message('❌ 管理者権限を持つロールは付与できません。', ephemeral=True)
        return

    await interaction.response.send_message(
        f'🔄 **{role.name}** ロールをサーバーの全メンバーに付与しています...\n\nメンバーリストを読み込み中です...',
        ephemeral=True
    )
    
    all_members = interaction.guild.members
    bot_members = [member for member in all_members if member.bot]
    human_members = [member for member in all_members if not member.bot]
    
    members = human_members
    total_members = len(members)
    
    try:
        print("Attempting to fetch all guild members...")
        await interaction.guild.chunk()
        print("Guild chunking completed")
        
        all_members_after_chunk = interaction.guild.members
        human_members_after_chunk = [member for member in all_members_after_chunk if not member.bot]
        
        print(f"After chunking:")
        print(f"- All members: {len(all_members_after_chunk)}")
        print(f"- Human members: {len(human_members_after_chunk)}")
        
        if len(human_members_after_chunk) > total_members:
            members = human_members_after_chunk
            total_members = len(members)
            all_members = all_members_after_chunk
            bot_members = [member for member in all_members_after_chunk if member.bot]
            human_members = human_members_after_chunk
            print(f"Updated target members to: {total_members}")
        
    except Exception as e:
        print(f"Failed to chunk guild members: {e}")
    
    if total_members == 0:
        error_embed = discord.Embed(
            title='❌ メンバーが見つかりません',
            description=f'**サーバー:** {interaction.guild.name}\n**ロール:** {role.name}',
            color=0xff0000
        )
        error_embed.add_field(
            name='詳細情報',
            value=f'**サーバーメンバー数:** {interaction.guild.member_count}\n'
                  f'**読み込み済みメンバー:** {len(interaction.guild.members)}\n'
                  f'**人間のメンバー:** {len([m for m in interaction.guild.members if not m.bot])}\n'
                  f'**Botメンバー:** {len([m for m in interaction.guild.members if m.bot])}',
            inline=False
        )
        error_embed.add_field(
            name='可能な原因',
            value='• サーバーにBot以外のメンバーがいない\n'
                  f'• Botにメンバー一覧の権限がない\n'
                  f'• メンバーリストの読み込みに失敗',
            inline=False
        )
        
        try:
            await interaction.channel.send(embed=error_embed)
        except:
            pass
        return

    status_embed = discord.Embed(
        title='👥 全メンバーロール付与進行状況',
        description=f'**ロール:** {role.name}\n**サーバー:** {interaction.guild.name}\n\nメンバーにロールを付与しています...',
        color=0x0099ff
    )
    status_embed.add_field(
        name='進行状況',
        value='開始中...',
        inline=False
    )
    status_embed.set_footer(text=f'実行者: {interaction.user.display_name}')
    
    try:
        status_message = await interaction.channel.send(embed=status_embed)
    except:
        status_message = None

    members_with_role = 0
    members_without_role = 0
    
    for member in members:
        if role in member.roles:
            members_with_role += 1
        else:
            members_without_role += 1
    
    print(f"Pre-check results:")
    print(f"- Members with role: {members_with_role}")
    print(f"- Members without role: {members_without_role}")
    
    if members_without_role == 0:
        early_embed = discord.Embed(
            title='ℹ️ 全メンバーが既にロールを所持',
            description=f'**ロール:** {role.name}\n**サーバー:** {interaction.guild.name}\n\n全ての対象メンバー（{total_members}人）が既にこのロールを持っています。',
            color=0xffaa00
        )
        early_embed.add_field(
            name='📊 確認結果',
            value=f'**既存所持:** {members_with_role}人\n**付与対象:** {members_without_role}人',
            inline=False
        )
        early_embed.add_field(
            name='💡 提案',
            value='• 別のロールを選択してください\n• 特定のメンバーのロールを一度削除してからお試しください\n• これは正常な状態です（問題ではありません）',
            inline=False
        )
        early_embed.set_footer(text='処理は続行されますが、変更は行われません')
        
        try:
            await interaction.channel.send(embed=early_embed)
        except:
            pass

    processed_members = 0
    success_count = 0
    skip_count = 0
    error_count = 0
    
    print(f"Starting allmember command:")
    print(f"- Role: {role.name} (ID: {role.id})")
    print(f"- Guild: {interaction.guild.name} (ID: {interaction.guild.id})")
    print(f"- Guild member count: {interaction.guild.member_count}")
    print(f"- All members loaded: {len(all_members)}")
    print(f"- Bot members: {len(bot_members)}")
    print(f"- Human members: {len(human_members)}")
    print(f"- Target members: {total_members}")
    print(f"- Bot permissions: {interaction.guild.me.guild_permissions}")
    print(f"- Bot top role: {interaction.guild.me.top_role}")
    print(f"- Target role position: {role.position}")
    print(f"- Bot can manage role: {role < interaction.guild.me.top_role}")
    
    if len(human_members) > 0:
        print(f"- First few human members:")
        for i, member in enumerate(human_members[:5]):
            print(f"  {i+1}. {member.display_name} ({member.name}) - Has role: {role in member.roles}")
    else:
        print("- No human members found in server")
        print(f"- All members list:")
        for i, member in enumerate(all_members[:10]):
            member_type = "Bot" if member.bot else "Human"
            print(f"  {i+1}. {member.display_name} ({member.name}) - {member_type}")
    
    if total_members == 0:
        print("WARNING: No human members found. This could be due to:")
        print("1. Server only has bots")
        print("2. Missing member intents")
        print("3. Bot hasn't loaded all members yet")

    for member in members:
        try:
            if role in member.roles:
                skip_count += 1
                print(f"Skipped {member.display_name}: Already has role")
            else:
                await member.add_roles(role, reason=f"全メンバーロール付与 - 実行者: {interaction.user.display_name}")
                
                await member.reload()
                if role in member.roles:
                    success_count += 1
                    print(f"Successfully added role to {member.display_name}")
                else:
                    error_count += 1
                    print(f"Failed to add role to {member.display_name}: Role not found after assignment")
                
        except discord.Forbidden:
            error_count += 1
            print(f"Failed to assign role to {member.display_name}: Missing permissions")
        except discord.HTTPException as e:
            error_count += 1
            print(f"Failed to assign role to {member.display_name}: HTTP error - {e}")
        except Exception as e:
            error_count += 1
            print(f"Unexpected error with {member.display_name}: {e}")
        
        processed_members += 1
        
        if processed_members % 10 == 0 and status_message:
            try:
                progress_percentage = (processed_members / total_members) * 100
                status_embed.clear_fields()
                status_embed.add_field(
                    name='進行状況',
                    value=f'処理済み: {processed_members}/{total_members} ({progress_percentage:.1f}%)\n'
                          f'✅ 付与成功: {success_count}\n'
                          f'⏭️ スキップ: {skip_count}\n'
                          f'❌ エラー: {error_count}',
                    inline=False
                )
                await status_message.edit(embed=status_embed)
            except Exception as e:
                print(f"Status update error: {e}")
                status_message = None
        
        if processed_members % 5 == 0:
            await asyncio.sleep(1)

    if skip_count == total_members and success_count == 0:
        embed_color = 0xffaa00
        embed_title = '⚠️ 全メンバーロール付与完了（変更なし）'
        status_message_text = '全てのメンバーが既に指定されたロールを持っています。'
    elif success_count > 0:
        embed_color = 0x00ff00
        embed_title = '✅ 全メンバーロール付与完了'
        status_message_text = 'ロール付与処理が完了しました。'
    else:
        embed_color = 0xff6600
        embed_title = '⚠️ 全メンバーロール付与完了（問題あり）'
        status_message_text = 'ロール付与処理が完了しましたが、問題が発生しました。'

    final_embed = discord.Embed(
        title=embed_title,
        description=f'**ロール:** {role.name}\n**サーバー:** {interaction.guild.name}\n\n{status_message_text}',
        color=embed_color
    )
    final_embed.add_field(
        name='📊 結果統計',
        value=f'**対象メンバー:** {total_members}人\n'
              f'**付与成功:** {success_count}人\n'
              f'**スキップ:** {skip_count}人（既に所持）\n'
              f'**エラー:** {error_count}人\n'
              f'**処理済み:** {processed_members}人',
        inline=False
    )
    
    if total_members > 0:
        if success_count > 0:
            success_percentage = (success_count / total_members) * 100
            final_embed.add_field(
                name='📈 新規付与率',
                value=f'{success_percentage:.1f}% ({success_count}/{total_members})',
                inline=True
            )
        
        if skip_count > 0:
            skip_percentage = (skip_count / total_members) * 100
            final_embed.add_field(
                name='⏭️ 既存所持率',
                value=f'{skip_percentage:.1f}% ({skip_count}/{total_members})',
                inline=True
            )
    
    if skip_count == total_members:
        final_embed.add_field(
            name='ℹ️ 詳細',
            value='全てのメンバーが既に指定されたロールを持っているため、変更は行われませんでした。これは正常な状態です。',
            inline=False
        )
    elif success_count > 0:
        final_embed.add_field(
            name='✅ 成功',
            value=f'{success_count}人のメンバーに新しくロールが付与されました。',
            inline=False
        )
    
    if error_count > 0:
        final_embed.add_field(
            name='⚠️ 注意',
            value=f'{error_count}人のメンバーでエラーが発生しました。権限の問題や一時的な接続エラーが原因の可能性があります。',
            inline=False
        )
    
    final_embed.set_footer(text=f'実行者: {interaction.user.display_name} | 処理完了')
    
    if status_message:
        try:
            await status_message.edit(embed=final_embed)
        except Exception as e:
            print(f"Final status update error: {e}")
            try:
                await interaction.channel.send(embed=final_embed)
            except Exception as e2:
                print(f"Failed to send completion message: {e2}")
    else:
        try:
            await interaction.channel.send(embed=final_embed)
        except Exception as e:
            print(f"Failed to send completion message: {e}")

COMMAND_HELP.update({
    'allmember': {
        'description': '指定したロールをサーバーの全メンバーに付与',
        'usage': '/allmember <ロール>',
        'details': 'サーバーの全メンバー（Bot除く）に指定したロールを付与します。既にロールを持っているメンバーはスキップされます。@everyone、管理されたロール、管理者権限を持つロールは付与できません。管理者権限が必要です。'
    },
    'allmessage': {
        'description': 'サーバーの全メッセージを指定したサーバーにコピー',
        'usage': '/allmessage <転送先サーバーID> [チャンネルID]',
        'details': 'サーバーの全チャンネル、または指定したチャンネルのメッセージを転送先サーバーにコピーします。チャンネルIDを指定した場合はそのチャンネルのみをコピーします。チャンネルが存在しない場合は自動作成されます。管理者権限が必要です。'
    },
    'warn': {
        'description': 'ユーザーに警告を与える',
        'usage': '/warn <ユーザー> [理由]',
        'details': '段階的警告システム。1回目は警告のみ、2回目で1時間ミュート、3回目でBanとなります。メッセージ管理権限が必要です。'
    },
    'warnings': {
        'description': 'ユーザーの警告履歴を表示',
        'usage': '/warnings <ユーザー>',
        'details': '指定したユーザーの警告履歴と回数を表示します。メッセージ管理権限が必要です。'
    },
    'tempmute': {
        'description': 'ユーザーを一時的にミュート',
        'usage': '/tempmute <ユーザー> <期間> [理由]',
        'details': '指定した期間ユーザーをミュートします。期間は30m（分）、2h（時間）、1d（日）の形式で指定。最大28日まで。メンバータイムアウト権限が必要です。'
    },
    'support-request': {
        'description': 'サポートを要請',
        'usage': '/support-request <内容>',
        'details': 'サポートを要請します。管理者が対応可能かどうか応答し、対応者が決まったらDMで連絡されます。'
    },
    'online_check': {
        'description': 'ボットのオンライン状態を確認',
        'usage': '/online_check',
        'details': 'ボットの稼働状況、アップタイム、レイテンシ、接続サーバー数などの詳細情報を表示します。'
    },
    'link_bot': {
        'description': 'ボット参加サーバーの招待リンクを表示',
        'usage': '!link_bot',
        'details': 'ボットが参加している全サーバーの招待リンクを一覧表示します。既存の招待リンクがない場合は新規作成します。管理者権限が必要です。'
    }
})
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
