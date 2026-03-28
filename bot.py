import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput, Select

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", "data_store_bot")
WIB = ZoneInfo("Asia/Jakarta")
COLOR = 0x00F8FF
MAX_SLOT = 20

BASE_DIR = Path(DATA_DIR)
BASE_DIR.mkdir(parents=True, exist_ok=True)

VIP_FILE = BASE_DIR / "vip_sessions.json"
PRODUCT_FILE = BASE_DIR / "cashier_products.json"
CATEGORY_FILE = BASE_DIR / "cashier_categories.json"
CUSTOM_COMMAND_FILE = BASE_DIR / "custom_commands.json"
CUSTOM_COMMAND_DIR = BASE_DIR / "custom_command_media"
CUSTOM_COMMAND_DIR.mkdir(parents=True, exist_ok=True)
BUYER_PRICELIST_DIR = BASE_DIR / "buyer_pricelists"
BUYER_PRICELIST_DIR.mkdir(parents=True, exist_ok=True)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

vip_sessions: dict[str, dict] = {}
kasir_sessions: dict[str, dict] = {}


# =========================================================
# UTIL
# =========================================================
def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def now_wib() -> datetime:
    return datetime.now(WIB)


def format_wib(dt: Optional[datetime] = None) -> str:
    dt = dt or now_wib()
    bulan = {
        1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei", 6: "Juni",
        7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober", 11: "November", 12: "Desember"
    }
    return f"{dt.day} {bulan[dt.month]} {dt.year}, {dt.strftime('%H.%M')} WIB"


def format_rupiah(value: int) -> str:
    return f"Rp {value:,}".replace(",", ".")


def is_admin(member) -> bool:
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def normalize_trigger(text: str) -> str:
    return text.strip().lower().lstrip("!")


def calculate_price(robux: int, rate: int) -> int:
    raw_price = robux * rate
    return ((raw_price + 499) // 500) * 500


def parse_slot_numbers(text: str) -> list[int]:
    raw = text.replace(" ", "")
    if not raw:
        raise ValueError("Slot kosong.")

    result = set()
    for part in raw.split(","):
        if not part:
            continue

        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = int(start_str)
            end = int(end_str)
            if start > end:
                start, end = end, start

            for num in range(start, end + 1):
                if num < 1 or num > MAX_SLOT:
                    raise ValueError(f"Slot {num} di luar batas 1-{MAX_SLOT}.")
                result.add(num)
        else:
            num = int(part)
            if num < 1 or num > MAX_SLOT:
                raise ValueError(f"Slot {num} di luar batas 1-{MAX_SLOT}.")
            result.add(num)

    return sorted(result)


def chunk_list(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


# =========================================================
# STORAGE
# =========================================================
PRODUCTS = load_json(PRODUCT_FILE, [])
CATEGORIES = load_json(CATEGORY_FILE, [])
CUSTOM_COMMANDS = load_json(CUSTOM_COMMAND_FILE, {})
vip_sessions = load_json(VIP_FILE, {})

BUYER_DATA = {
    "fishit": {
        "name": "Fish It",
        "items": {
            "gamepass": "Gamepass",
            "boostx8": "Boost X8",
            "skincrates": "Skin Crates",
            "emotecrates": "Emote Crates"
        }
    },
    "fisch": {
        "name": "Fisch",
        "items": {
            "gamepass": "Gamepass",
            "limited": "Limited Item"
        }
    },
    "theforge": {
        "name": "The Forge",
        "items": {
            "gamepass": "Gamepass",
            "reroll": "Reroll"
        }
    },
    "abbys": {
        "name": "Abbys",
        "items": {
            "gamepass": "Gamepass",
            "shard": "Shard"
        }
    }
}


def save_products():
    save_json(PRODUCT_FILE, PRODUCTS)


def save_categories():
    save_json(CATEGORY_FILE, CATEGORIES)


def save_custom_commands():
    save_json(CUSTOM_COMMAND_FILE, CUSTOM_COMMANDS)


def save_vip_sessions():
    save_json(VIP_FILE, vip_sessions)


def get_session(message_id: int | str):
    key = str(message_id)
    if key not in vip_sessions:
        vip_sessions[key] = {"info": {}, "list": []}
        save_vip_sessions()
    return vip_sessions[key]


def category_exists(name: str) -> bool:
    key = normalize_key(name)
    return any(normalize_key(cat) == key for cat in CATEGORIES)


def find_category_name(name: str) -> Optional[str]:
    key = normalize_key(name)
    for cat in CATEGORIES:
        if normalize_key(cat) == key:
            return cat
    return None


def find_product_by_name(name: str):
    key = normalize_key(name)
    for product in PRODUCTS:
        if normalize_key(product["name"]) == key:
            return product
    return None


def find_product_by_name_and_category(name: str, category: str):
    name_key = normalize_key(name)
    category_key = normalize_key(category)
    for product in PRODUCTS:
        if normalize_key(product["name"]) == name_key and normalize_key(product["category"]) == category_key:
            return product
    return None


def find_product_by_id(product_id: str):
    for product in PRODUCTS:
        if product.get("id") == product_id:
            return product
    return None


def search_products(keyword: str, category_name: Optional[str] = None) -> list[dict]:
    key = normalize_key(keyword)
    result = []

    for product in PRODUCTS:
        if category_name and normalize_key(product["category"]) != normalize_key(category_name):
            continue

        haystack = normalize_key(f"{product['category']} {product['name']} {product['robux']}")
        if not key or key in haystack:
            result.append(product)

    return result


async def product_autocomplete(interaction: discord.Interaction, current: str):
    current_key = normalize_key(current)
    result = []
    for product in PRODUCTS:
        display = f"[{product['category']}] {product['name']}"
        search_blob = normalize_key(f"{product['category']} {product['name']}")
        if not current_key or current_key in search_blob:
            result.append(
                app_commands.Choice(
                    name=display[:100],
                    value=product["id"]
                )
            )
        if len(result) >= 25:
            break
    return result


async def category_autocomplete(interaction: discord.Interaction, current: str):
    current_key = normalize_key(current)
    result = []
    for cat in CATEGORIES:
        if not current_key or current_key in normalize_key(cat):
            result.append(app_commands.Choice(name=cat[:100], value=cat[:100]))
        if len(result) >= 25:
            break
    return result


# =========================================================
# HELP COMMANDS
# =========================================================
@bot.tree.command(name="viphelp", description="Panduan command VIP")
async def viphelp(interaction: discord.Interaction):
    embed = discord.Embed(title="Panduan VIP", color=COLOR)
    embed.description = (
        "**`!vip`**\n"
        "Membuat panel list VIP baru di chat.\n\n"
        "**`/editslot`**\n"
        "Mengubah isi slot tertentu pada panel VIP berdasarkan message ID.\n\n"
        "**`/pay`**\n"
        "Mengubah status pembayaran beberapa slot sekaligus menjadi paid atau unpaid.\n\n"
        "**`/delete`**\n"
        "Menghapus slot tertentu dari panel VIP berdasarkan message ID.\n\n"
        "**Contoh:**\n"
        "`/editslot message_id:123456789 nomor:1 roblox:ABC member:@User`\n"
        "`/pay message_id:123456789 slots:1,2,3 status:paid`\n"
        "`/delete message_id:123456789 nomor:3`"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="kasirhelp", description="Panduan penggunaan kasir")
async def kasirhelp(interaction: discord.Interaction):
    embed = discord.Embed(title="Panduan Kasir", color=COLOR)
    embed.description = (
        "**Alur penggunaan kasir:**\n\n"
        "1. Buat kategori dulu dengan **`/kategori_tambah`**\n"
        "2. Tambahkan produk ke kategori dengan **`/produk_tambah`**\n"
        "3. Jalankan **`/kasir`** lalu isi nama customer dan rate.\n"
        "4. Klik **Tambah Produk** → pilih kategori → pilih dari list atau cari produk.\n"
        "5. Pilih satu atau beberapa produk sekaligus.\n"
        "6. Isi qty (default semua 1).\n"
        "7. Klik **Selesai / Kirim Invoice** untuk kirim invoice ke chat.\n\n"
        "**Catatan:**\n"
        "- Rate hanya diketahui admin.\n"
        "- Harga dihitung dari `robux x rate`, lalu dibulatkan ke atas ke kelipatan 500.\n"
        "- Invoice customer tidak menampilkan rate.\n"
        "- Dropdown Discord maksimal 25 produk per tampilan, jadi gunakan fitur cari kalau produk banyak.\n\n"
        "**Command kasir:**\n"
        "`/kategori_tambah`\n"
        "`/kategori_hapus`\n"
        "`/kategori_list`\n"
        "`/produk_tambah`\n"
        "`/produk_edit`\n"
        "`/produk_hapus`\n"
        "`/produk_list`\n"
        "`/kasir`"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="adminhelp", description="Panduan command admin toko")
async def adminhelp(interaction: discord.Interaction):
    embed = discord.Embed(title="Panduan Admin Bot Toko", color=COLOR)
    embed.description = (
        "**Bagian VIP:**\n"
        "**`!vip`** → membuat panel VIP baru di chat.\n"
        "**`/editslot`** → mengubah isi slot tertentu pada panel VIP.\n"
        "**`/pay`** → mengubah status pembayaran slot VIP.\n"
        "**`/delete`** → menghapus slot tertentu dari panel VIP.\n\n"
        "**Bagian Kasir:**\n"
        "**`/kasir`** → memulai sesi kasir dengan input customer dan rate.\n"
        "**`/kategori_tambah`** → membuat kategori produk kasir.\n"
        "**`/kategori_hapus`** → menghapus kategori yang tidak dipakai.\n"
        "**`/kategori_list`** → melihat semua kategori.\n"
        "**`/produk_tambah`** → menambahkan produk ke kategori tertentu.\n"
        "**`/produk_edit`** → mengubah nama, kategori, atau robux produk.\n"
        "**`/produk_hapus`** → menghapus produk.\n"
        "**`/produk_list`** → melihat daftar produk.\n"
        "**`/kasirhelp`** → panduan lengkap penggunaan kasir.\n\n"
        "**Bagian Pricelist Customer:**\n"
        "**`/cekpricelist`** → customer bisa cek pricelist sendiri secara private.\n"
        "**`/update_pricelist`** → admin update gambar pricelist buyer.\n\n"
        "**Bagian Command Custom:**\n"
        "**`/tambahcommand`** → menambah, mengedit, menghapus command `!custom` yang bisa mengirim teks/gambar."
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# VIP
# =========================================================
def make_vip_embed(message_id: int | str):
    session = get_session(message_id)
    info = session["info"]
    vip_list = session["list"]

    lines = []
    title = "💎 VIP X8 LUCK BY MYST STORE 💎"

    if info:
        lines.append("```")
        lines.append(f"TANGGAL : {info.get('waktu', '-')}")
        lines.append(f"DURASI  : {info.get('durasi_waktu', '-')}")
        lines.append(f"HARGA   : {info.get('harga', '-')}")
        lines.append(f"PS      : {info.get('ps', '-')}")

        server_value = str(info.get("server", "")).strip()
        if server_value:
            lines.append(f"SERVER  : {server_value}")

        lines.append("```")
    else:
        lines.append("_Belum diatur oleh admin_")

    lines.append("")
    lines.append("**──.✦ LIST SLOT**")

    index = 1
    for data in vip_list:
        line = f"{index}. {data['roblox']} — {data['mention']}"
        if data.get("paid"):
            line += " | ✅"
        lines.append(line)
        index += 1

    while index <= MAX_SLOT:
        lines.append(f"{index}.")
        index += 1

    lines.append("")
    lines.append("*Payment akan dibuka setelah semua list penuh ya guys!*")
    lines.append("*Terimakasih! —Myst MOD :3*")

    embed = discord.Embed(title=title, description="\n".join(lines), color=COLOR)
    embed.set_footer(text=f"{len(vip_list)}/{MAX_SLOT} slot")
    return embed


class VipSetupModal(Modal):
    def __init__(self, message_id: int):
        super().__init__(title="Atur Info VIP (Admin)")
        self.message_id = message_id
        self.waktu = TextInput(label="Tanggal")
        self.durasi_waktu = TextInput(label="Durasi")
        self.harga = TextInput(label="Harga")
        self.ps = TextInput(label="PS / Host")
        self.server = TextInput(label="Server (opsional)", required=False)

        for item in (self.waktu, self.durasi_waktu, self.harga, self.ps, self.server):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("Hanya admin.", ephemeral=True)
            return

        info = get_session(self.message_id)["info"]
        info["waktu"] = self.waktu.value
        info["durasi_waktu"] = self.durasi_waktu.value
        info["harga"] = self.harga.value
        info["ps"] = self.ps.value
        info["server"] = self.server.value.strip()
        save_vip_sessions()

        msg = await interaction.channel.fetch_message(self.message_id)
        await msg.edit(embed=make_vip_embed(self.message_id), view=VipView(self.message_id))
        await interaction.response.send_message("Info diperbarui.", ephemeral=True)


class JoinModal(Modal):
    def __init__(self, message_id: int):
        super().__init__(title="Ikut VIP")
        self.message_id = message_id
        self.roblox = TextInput(label="Username Roblox", placeholder="Contoh : KennMyst")
        self.add_item(self.roblox)

    async def on_submit(self, interaction: discord.Interaction):
        session = get_session(self.message_id)

        if len(session["list"]) >= MAX_SLOT:
            await interaction.response.send_message("Slot sudah penuh.", ephemeral=True)
            return

        session["list"].append({
            "id": str(uuid.uuid4()),
            "user_id": interaction.user.id,
            "mention": interaction.user.mention,
            "roblox": self.roblox.value.strip(),
            "paid": False
        })
        save_vip_sessions()

        msg = await interaction.channel.fetch_message(self.message_id)
        await msg.edit(embed=make_vip_embed(self.message_id), view=VipView(self.message_id))
        await interaction.response.send_message("Berhasil masuk list VIP.", ephemeral=True)


class DeleteSelect(Select):
    def __init__(self, message_id: int, user_id: int):
        self.message_id = message_id
        options = []

        for idx, data in enumerate(get_session(message_id)["list"], start=1):
            if data["user_id"] == user_id:
                options.append(discord.SelectOption(label=f"{idx}. {data['roblox']}"[:100], value=data["id"]))

        if not options:
            options.append(discord.SelectOption(label="Tidak ada slot", value="none"))

        super().__init__(placeholder="Pilih slot kamu", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Tidak ada slot.", ephemeral=True)
            return

        session = get_session(self.message_id)
        slot_id = self.values[0]

        for i, data in enumerate(session["list"]):
            if data["id"] == slot_id:
                if data["user_id"] != interaction.user.id:
                    await interaction.response.send_message("Bukan slot kamu.", ephemeral=True)
                    return

                session["list"].pop(i)
                save_vip_sessions()

                msg = await interaction.channel.fetch_message(self.message_id)
                await msg.edit(embed=make_vip_embed(self.message_id), view=VipView(self.message_id))
                await interaction.response.send_message("Slot dihapus.", ephemeral=True)
                return

        await interaction.response.send_message("Slot tidak ditemukan.", ephemeral=True)


class DeleteView(View):
    def __init__(self, message_id: int, user_id: int):
        super().__init__(timeout=60)
        self.add_item(DeleteSelect(message_id, user_id))


class VipView(View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="+ Ikut", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: Button):
        if len(get_session(self.message_id)["list"]) >= MAX_SLOT:
            await interaction.response.send_message("Slot sudah penuh.", ephemeral=True)
            return
        await interaction.response.send_modal(JoinModal(self.message_id))

    @discord.ui.button(label="- Hapus slot saya", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: Button):
        session = get_session(self.message_id)
        if not any(x["user_id"] == interaction.user.id for x in session["list"]):
            await interaction.response.send_message("Kamu belum punya slot.", ephemeral=True)
            return
        await interaction.response.send_message("Pilih slot kamu:", view=DeleteView(self.message_id, interaction.user.id), ephemeral=True)

    @discord.ui.button(label="✏️ Atur Info (Admin)", style=discord.ButtonStyle.primary)
    async def setup(self, interaction: discord.Interaction, button: Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("Hanya admin.", ephemeral=True)
            return
        await interaction.response.send_modal(VipSetupModal(self.message_id))

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: Button):
        msg = await interaction.channel.fetch_message(self.message_id)
        await msg.edit(embed=make_vip_embed(self.message_id), view=VipView(self.message_id))
        await interaction.response.send_message("Direfresh.", ephemeral=True)


@bot.command()
async def vip(ctx: commands.Context):
    msg = await ctx.send(embed=discord.Embed(title="Membuat list VIP...", color=COLOR))
    get_session(msg.id)
    save_vip_sessions()
    await msg.edit(embed=make_vip_embed(msg.id), view=VipView(msg.id))
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass


@bot.tree.command(name="delete", description="Admin: hapus slot VIP")
@app_commands.describe(message_id="ID pesan VIP", nomor="Nomor slot")
async def slash_delete(interaction: discord.Interaction, message_id: str, nomor: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("Hanya admin.", ephemeral=True)
        return

    try:
        mid = int(message_id)
    except ValueError:
        await interaction.response.send_message("Message ID tidak valid.", ephemeral=True)
        return

    session = vip_sessions.get(str(mid))
    if not session:
        await interaction.response.send_message("List tidak ditemukan.", ephemeral=True)
        return

    index = nomor - 1
    if index < 0 or index >= len(session["list"]):
        await interaction.response.send_message("Nomor slot tidak valid.", ephemeral=True)
        return

    session["list"].pop(index)
    save_vip_sessions()

    msg = await interaction.channel.fetch_message(mid)
    await msg.edit(embed=make_vip_embed(mid), view=VipView(mid))
    await interaction.response.send_message("Slot berhasil dihapus.", ephemeral=True)


@bot.tree.command(name="editslot", description="Admin: edit slot VIP")
@app_commands.describe(message_id="ID pesan VIP", nomor="Nomor slot", roblox="Username Roblox", member="User Discord")
async def slash_edit(interaction: discord.Interaction, message_id: str, nomor: int, roblox: str, member: discord.Member):
    if not is_admin(interaction.user):
        await interaction.response.send_message("Hanya admin.", ephemeral=True)
        return

    try:
        mid = int(message_id)
    except ValueError:
        await interaction.response.send_message("Message ID tidak valid.", ephemeral=True)
        return

    session = vip_sessions.get(str(mid))
    if not session:
        await interaction.response.send_message("List tidak ditemukan.", ephemeral=True)
        return

    if nomor < 1 or nomor > MAX_SLOT:
        await interaction.response.send_message("Nomor slot tidak valid.", ephemeral=True)
        return

    index = nomor - 1
    while len(session["list"]) <= index:
        session["list"].append({
            "id": str(uuid.uuid4()),
            "user_id": 0,
            "mention": "-",
            "roblox": "-",
            "paid": False
        })

    session["list"][index] = {
        "id": str(uuid.uuid4()),
        "user_id": member.id,
        "mention": member.mention,
        "roblox": roblox.strip(),
        "paid": False
    }
    save_vip_sessions()

    msg = await interaction.channel.fetch_message(mid)
    await msg.edit(embed=make_vip_embed(mid), view=VipView(mid))
    await interaction.response.send_message("Slot berhasil diedit.", ephemeral=True)


@bot.tree.command(name="pay", description="Admin: update payment slot VIP")
@app_commands.describe(message_id="ID pesan VIP", slots="Contoh: 1,2,10 atau 1-5", status="Status pembayaran")
@app_commands.choices(status=[
    app_commands.Choice(name="paid", value="paid"),
    app_commands.Choice(name="unpaid", value="unpaid")
])
async def slash_paid(interaction: discord.Interaction, message_id: str, slots: str, status: app_commands.Choice[str]):
    if not is_admin(interaction.user):
        await interaction.response.send_message("Hanya admin.", ephemeral=True)
        return

    try:
        mid = int(message_id)
    except ValueError:
        await interaction.response.send_message("Message ID tidak valid.", ephemeral=True)
        return

    session = vip_sessions.get(str(mid))
    if not session:
        await interaction.response.send_message("List tidak ditemukan.", ephemeral=True)
        return

    try:
        numbers = parse_slot_numbers(slots)
    except Exception as e:
        await interaction.response.send_message(f"Format slot salah: {e}", ephemeral=True)
        return

    updated = []
    not_found = []

    for n in numbers:
        idx = n - 1
        if 0 <= idx < len(session["list"]):
            session["list"][idx]["paid"] = status.value == "paid"
            updated.append(str(n))
        else:
            not_found.append(str(n))

    save_vip_sessions()

    msg = await interaction.channel.fetch_message(mid)
    await msg.edit(embed=make_vip_embed(mid), view=VipView(mid))

    lines = []
    if updated:
        lines.append(f"✅ Slot diupdate: {', '.join(updated)} → {status.value}")
    if not_found:
        lines.append(f"⚠️ Slot tidak ditemukan: {', '.join(not_found)}")

    await interaction.response.send_message("\n".join(lines) if lines else "Tidak ada slot yang diubah.", ephemeral=True)


# =========================================================
# BUYER PRICELIST
# =========================================================
class GameView(View):
    def __init__(self):
        super().__init__(timeout=60)
        options = [discord.SelectOption(label=data["name"], value=key) for key, data in BUYER_DATA.items()]
        self.add_item(GameSelect(options))


class GameSelect(Select):
    def __init__(self, options):
        super().__init__(placeholder="Pilih game", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        game_key = self.values[0]
        await interaction.response.edit_message(content="Pilih produk:", view=ItemView(game_key))


class ItemView(View):
    def __init__(self, game_key: str):
        super().__init__(timeout=60)
        options = [discord.SelectOption(label=item_name, value=f"{game_key}|{item_key}") for item_key, item_name in BUYER_DATA[game_key]["items"].items()]
        self.add_item(ItemSelect(options))


class ItemSelect(Select):
    def __init__(self, options):
        super().__init__(placeholder="Pilih pricelist", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        game_key, item_key = self.values[0].split("|")
        folder = BUYER_PRICELIST_DIR / "game" / game_key / item_key

        if not folder.exists():
            await interaction.response.send_message("❌ Pricelist belum tersedia.", ephemeral=True)
            return

        files = [discord.File(str(name)) for name in sorted(folder.iterdir()) if name.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]

        if not files:
            await interaction.response.send_message("❌ Pricelist belum tersedia.", ephemeral=True)
            return

        await interaction.response.send_message(files=files, ephemeral=True)


@bot.tree.command(name="cekpricelist", description="Cek pricelist game")
async def cekpricelist(interaction: discord.Interaction):
    await interaction.response.send_message("Pilih game:", view=GameView(), ephemeral=True)


@bot.tree.command(name="update_pricelist", description="Update pricelist buyer (admin)")
@app_commands.describe(
    game="Pilih game",
    produk="Pilih produk",
    image1="Gambar 1",
    image2="Gambar 2 (opsional)",
    image3="Gambar 3 (opsional)",
    image4="Gambar 4 (opsional)"
)
@app_commands.choices(
    game=[
        app_commands.Choice(name="Fish It", value="fishit"),
        app_commands.Choice(name="Fisch", value="fisch"),
        app_commands.Choice(name="The Forge", value="theforge"),
        app_commands.Choice(name="Abbys", value="abbys"),
    ],
    produk=[
        app_commands.Choice(name="Fish It - Gamepass", value="fishit|gamepass"),
        app_commands.Choice(name="Fish It - Boost X8", value="fishit|boostx8"),
        app_commands.Choice(name="Fish It - Skin Crates", value="fishit|skincrates"),
        app_commands.Choice(name="Fish It - Emote Crates", value="fishit|emotecrates"),
        app_commands.Choice(name="Fisch - Gamepass", value="fisch|gamepass"),
        app_commands.Choice(name="Fisch - Limited Item", value="fisch|limited"),
        app_commands.Choice(name="The Forge - Gamepass", value="theforge|gamepass"),
        app_commands.Choice(name="The Forge - Reroll", value="theforge|reroll"),
        app_commands.Choice(name="Abbys - Gamepass", value="abbys|gamepass"),
        app_commands.Choice(name="Abbys - Shard", value="abbys|shard"),
    ]
)
async def update_pricelist(
    interaction: discord.Interaction,
    game: app_commands.Choice[str],
    produk: app_commands.Choice[str],
    image1: discord.Attachment,
    image2: Optional[discord.Attachment] = None,
    image3: Optional[discord.Attachment] = None,
    image4: Optional[discord.Attachment] = None
):
    await interaction.response.defer(ephemeral=True)

    if not is_admin(interaction.user):
        await interaction.followup.send("❌ Hanya admin yang bisa update.", ephemeral=True)
        return

    game_key, item_key = produk.value.split("|")
    folder = BUYER_PRICELIST_DIR / "game" / game_key / item_key
    folder.mkdir(parents=True, exist_ok=True)

    for f in folder.iterdir():
        if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            f.unlink(missing_ok=True)

    images = [image1, image2, image3, image4]
    index = 1
    for img in images:
        if img is not None:
            ext = Path(img.filename).suffix.lower() or ".png"
            if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
                ext = ".png"
            await img.save(folder / f"{index}{ext}")
            index += 1

    await interaction.followup.send("✅ Pricelist buyer berhasil diperbarui.", ephemeral=True)


# =========================================================
# KASIR DENGAN KATEGORI
# =========================================================
def build_invoice_embed(session: dict) -> discord.Embed:
    customer = session["customer"]
    tanggal = format_wib()

    lines = [
        f"● **Customer**    :  {customer}",
        f"● **Tanggal**       :  {tanggal}",
        "",
        "**─ .✦ List Pembelian**"
    ]

    total = 0
    for i, item in enumerate(session["items"], start=1):
        subtotal = item["price"] * item["qty"]
        total += subtotal
        qty_text = f" x{item['qty']}" if item["qty"] > 1 else ""
        lines.append(f"{i}. {item['name']} ({item['robux']}){qty_text} : {format_rupiah(subtotal)}")

    lines.extend([
        "",
        "**─ .✦ Total Pembayaran**",
        format_rupiah(total)
    ])

    embed = discord.Embed(description="\n".join(lines), color=COLOR)
    return embed


def build_kasir_preview_embed(session: dict) -> discord.Embed:
    embed = discord.Embed(title="Preview Kasir", color=COLOR)
    embed.add_field(name="Customer", value=session["customer"], inline=False)
    embed.add_field(name="Rate Admin", value=str(session["rate"]), inline=False)
    embed.add_field(name="Tanggal", value=format_wib(), inline=False)

    if session["items"]:
        lines = []
        total = 0
        for i, item in enumerate(session["items"], start=1):
            subtotal = item["price"] * item["qty"]
            total += subtotal
            qty_text = f" x{item['qty']}" if item["qty"] > 1 else ""
            lines.append(f"{i}. [{item['category']}] {item['name']} ({item['robux']}){qty_text} : {format_rupiah(subtotal)}")
        embed.add_field(name="List Pembelian", value="\n".join(lines), inline=False)
        embed.add_field(name="TOTAL", value=f"**{format_rupiah(total)}**", inline=False)
    else:
        embed.add_field(name="List Pembelian", value="Belum ada item.", inline=False)

    embed.set_footer(text="Rate hanya terlihat admin")
    return embed


def add_products_to_kasir_session(session_id: str, product_ids: list[str], qty_map: dict[str, int]) -> bool:
    session = kasir_sessions.get(session_id)
    if not session:
        return False

    rate = int(session["rate"])

    for product_id in product_ids:
        product = find_product_by_id(product_id)
        if not product:
            continue

        qty = qty_map.get(product_id, 1)
        if qty <= 0:
            continue

        robux = int(product["robux"])
        harga = calculate_price(robux, rate)

        session["items"].append({
            "category": product["category"],
            "name": product["name"],
            "robux": robux,
            "price": harga,
            "qty": qty
        })

    return True


class MultiQtyModal(Modal):
    def __init__(self, session_id: str, product_ids: list[str], page_index: int = 0, all_pages: Optional[list[list[str]]] = None):
        super().__init__(title="Atur Qty Produk")
        self.session_id = session_id
        self.product_ids = product_ids
        self.page_index = page_index
        self.all_pages = all_pages or [product_ids]
        self.inputs: list[tuple[str, TextInput]] = []

        for product_id in product_ids:
            product = find_product_by_id(product_id)
            if not product:
                continue

            field = TextInput(
                label=f"{product['name'][:45]}",
                default="1",
                placeholder="Isi jumlah, default 1",
                required=True
            )
            self.inputs.append((product_id, field))
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        qty_map = {}
        for product_id, field in self.inputs:
            try:
                qty = int(field.value.strip())
                if qty <= 0:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message("Semua qty harus berupa angka lebih dari 0.", ephemeral=True)
                return
            qty_map[product_id] = qty

        add_products_to_kasir_session(self.session_id, list(qty_map.keys()), qty_map)

        next_index = self.page_index + 1
        if next_index < len(self.all_pages):
            await interaction.response.send_message(
                "Lanjut isi qty produk berikutnya:",
                view=NextQtyPageView(self.session_id, self.all_pages, next_index),
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=build_kasir_preview_embed(session),
            view=KasirView(self.session_id),
            ephemeral=True
        )


class NextQtyPageView(View):
    def __init__(self, session_id: str, all_pages: list[list[str]], next_index: int):
        super().__init__(timeout=120)
        self.session_id = session_id
        self.all_pages = all_pages
        self.next_index = next_index

    @discord.ui.button(label="Isi Qty Berikutnya", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(
            MultiQtyModal(
                session_id=self.session_id,
                product_ids=self.all_pages[self.next_index],
                page_index=self.next_index,
                all_pages=self.all_pages
            )
        )


class KasirMultiProductSelect(Select):
    def __init__(self, session_id: str, products: list[dict], placeholder: str = "Pilih satu atau beberapa produk"):
        self.session_id = session_id
        self.products = products[:25]

        options = []
        session = kasir_sessions.get(session_id)
        rate = int(session["rate"]) if session else 0

        for product in self.products:
            preview_price = calculate_price(int(product["robux"]), rate)
            options.append(
                discord.SelectOption(
                    label=product["name"][:100],
                    description=f"{product['robux']} robux | {format_rupiah(preview_price)}"[:100],
                    value=product["id"]
                )
            )

        if not options:
            options.append(discord.SelectOption(label="Belum ada produk", value="none"))

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=len(options) if options and options[0].value != "none" else 1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada produk.", ephemeral=True)
            return

        valid_ids = [pid for pid in self.values if find_product_by_id(pid)]
        if not valid_ids:
            await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
            return

        pages = chunk_list(valid_ids, 5)
        await interaction.response.send_modal(
            MultiQtyModal(
                session_id=self.session_id,
                product_ids=pages[0],
                page_index=0,
                all_pages=pages
            )
        )


class KasirProductListView(View):
    def __init__(self, session_id: str, products: list[dict], title_text: str = "Pilih produk"):
        super().__init__(timeout=120)
        self.add_item(KasirMultiProductSelect(session_id, products, placeholder=title_text))


class KasirSearchModal(Modal):
    def __init__(self, session_id: str, category_name: str):
        super().__init__(title="Cari Produk")
        self.session_id = session_id
        self.category_name = category_name
        self.keyword = TextInput(
            label="Kata kunci produk",
            placeholder="Contoh: gamepass, shard, 100",
            required=True
        )
        self.add_item(self.keyword)

    async def on_submit(self, interaction: discord.Interaction):
        keyword = self.keyword.value.strip()
        products = search_products(keyword, self.category_name)

        if not products:
            await interaction.response.send_message("Produk tidak ditemukan pada kategori ini.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Hasil pencarian **{keyword}** di kategori **{self.category_name}**:",
            view=KasirProductListView(
                self.session_id,
                products[:25],
                title_text="Pilih hasil pencarian"
            ),
            ephemeral=True
        )


class KasirProductActionView(View):
    def __init__(self, session_id: str, category_name: str):
        super().__init__(timeout=120)
        self.session_id = session_id
        self.category_name = category_name

    @discord.ui.button(label="Pilih dari List", style=discord.ButtonStyle.success)
    async def choose_from_list(self, interaction: discord.Interaction, button: Button):
        category_products = [p for p in PRODUCTS if normalize_key(p["category"]) == normalize_key(self.category_name)]
        if not category_products:
            await interaction.response.send_message("Belum ada produk di kategori ini.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Pilih produk dari kategori **{self.category_name}**:",
            view=KasirProductListView(
                self.session_id,
                category_products[:25],
                title_text="Pilih satu atau beberapa produk"
            ),
            ephemeral=True
        )

    @discord.ui.button(label="Cari Produk", style=discord.ButtonStyle.primary)
    async def search_product(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(KasirSearchModal(self.session_id, self.category_name))


class KasirCategorySelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        options = [discord.SelectOption(label=cat[:100], value=cat[:100]) for cat in CATEGORIES[:25]]
        if not options:
            options.append(discord.SelectOption(label="Belum ada kategori", value="none"))
        super().__init__(placeholder="Pilih kategori produk", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada kategori.", ephemeral=True)
            return

        category_name = self.values[0]
        await interaction.response.send_message(
            f"Pilih metode untuk kategori **{category_name}**:",
            view=KasirProductActionView(self.session_id, category_name),
            ephemeral=True
        )


class KasirCategoryView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=120)
        self.add_item(KasirCategorySelect(session_id))


class KasirView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=600)
        self.session_id = session_id

    @discord.ui.button(label="Tambah Produk", style=discord.ButtonStyle.success)
    async def add_product(self, interaction: discord.Interaction, button: Button):
        if not CATEGORIES:
            await interaction.response.send_message("Belum ada kategori. Buat dulu dengan /kategori_tambah", ephemeral=True)
            return
        await interaction.response.send_message("Pilih kategori:", view=KasirCategoryView(self.session_id), ephemeral=True)

    @discord.ui.button(label="Hapus Item Terakhir", style=discord.ButtonStyle.danger)
    async def remove_last(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session or not session["items"]:
            await interaction.response.send_message("Belum ada item untuk dihapus.", ephemeral=True)
            return

        session["items"].pop()
        await interaction.response.edit_message(embed=build_kasir_preview_embed(session), view=KasirView(self.session_id))

    @discord.ui.button(label="Selesai / Kirim Invoice", style=discord.ButtonStyle.primary)
    async def finish(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return
        if not session["items"]:
            await interaction.response.send_message("Belum ada item yang dipilih.", ephemeral=True)
            return

        await interaction.channel.send(embed=build_invoice_embed(session))
        kasir_sessions.pop(self.session_id, None)
        await interaction.response.edit_message(content="✅ Invoice berhasil dikirim ke chat.", embed=None, view=None)

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        kasir_sessions.pop(self.session_id, None)
        await interaction.response.edit_message(content="❌ Sesi kasir dibatalkan.", embed=None, view=None)


class StartKasirModal(Modal):
    def __init__(self):
        super().__init__(title="Mulai Kasir")
        self.customer = TextInput(label="Nama Customer", placeholder="Contoh: Kenn")
        self.rate = TextInput(label="Rate hari ini", placeholder="Contoh: 90")
        self.add_item(self.customer)
        self.add_item(self.rate)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ Hanya admin yang bisa memakai kasir.", ephemeral=True)
            return

        if not PRODUCTS:
            await interaction.response.send_message("Belum ada katalog produk. Tambahkan dulu dengan /produk_tambah", ephemeral=True)
            return

        try:
            rate = int(self.rate.value)
            if rate <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Rate harus berupa angka lebih dari 0.", ephemeral=True)
            return

        session_id = str(uuid.uuid4())
        kasir_sessions[session_id] = {
            "customer": self.customer.value.strip(),
            "rate": rate,
            "items": []
        }

        await interaction.response.send_message(
            embed=build_kasir_preview_embed(kasir_sessions[session_id]),
            view=KasirView(session_id),
            ephemeral=True
        )


@bot.tree.command(name="kasir", description="Mulai sesi kasir dan isi rate harian")
async def kasir(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin yang bisa memakai kasir.", ephemeral=True)
        return
    await interaction.response.send_modal(StartKasirModal())


# =========================================================
# KATEGORI PRODUK
# =========================================================
@bot.tree.command(name="kategori_tambah", description="Tambah kategori produk kasir")
@app_commands.describe(nama="Nama kategori")
async def kategori_tambah(interaction: discord.Interaction, nama: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    if category_exists(nama):
        await interaction.response.send_message("Kategori sudah ada.", ephemeral=True)
        return

    CATEGORIES.append(nama.strip())
    save_categories()
    await interaction.response.send_message(f"✅ Kategori **{nama}** berhasil ditambahkan.", ephemeral=True)


@bot.tree.command(name="kategori_hapus", description="Hapus kategori produk kasir")
@app_commands.describe(nama="Nama kategori")
@app_commands.autocomplete(nama=category_autocomplete)
async def kategori_hapus(interaction: discord.Interaction, nama: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    real_name = find_category_name(nama)
    if not real_name:
        await interaction.response.send_message("Kategori tidak ditemukan.", ephemeral=True)
        return

    used = [p for p in PRODUCTS if normalize_key(p["category"]) == normalize_key(real_name)]
    if used:
        await interaction.response.send_message("Kategori masih dipakai produk. Hapus atau pindahkan produknya dulu.", ephemeral=True)
        return

    CATEGORIES.remove(real_name)
    save_categories()
    await interaction.response.send_message(f"🗑️ Kategori **{real_name}** dihapus.", ephemeral=True)


@bot.tree.command(name="kategori_list", description="Lihat daftar kategori produk")
async def kategori_list(interaction: discord.Interaction):
    if not CATEGORIES:
        await interaction.response.send_message("Belum ada kategori.", ephemeral=True)
        return

    embed = discord.Embed(
        title="Daftar Kategori",
        description="\n".join(f"{i}. {cat}" for i, cat in enumerate(CATEGORIES, start=1)),
        color=COLOR
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# PRODUK KASIR
# =========================================================
@bot.tree.command(name="produk_tambah", description="Tambah produk ke katalog kasir")
@app_commands.describe(kategori="Nama kategori", nama="Nama produk", robux="Jumlah robux")
@app_commands.autocomplete(kategori=category_autocomplete)
async def produk_tambah(interaction: discord.Interaction, kategori: str, nama: str, robux: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    real_category = find_category_name(kategori)
    if not real_category:
        await interaction.response.send_message("Kategori tidak ditemukan. Buat dulu dengan /kategori_tambah", ephemeral=True)
        return

    if find_product_by_name_and_category(nama, real_category):
        await interaction.response.send_message("Produk dengan nama itu sudah ada di kategori ini.", ephemeral=True)
        return

    if robux <= 0:
        await interaction.response.send_message("Jumlah robux harus lebih dari 0.", ephemeral=True)
        return

    PRODUCTS.append({
        "id": str(uuid.uuid4()),
        "category": real_category,
        "name": nama.strip(),
        "robux": robux
    })
    save_products()
    await interaction.response.send_message(
        f"✅ Produk **{nama}** berhasil ditambahkan ke kategori **{real_category}**.",
        ephemeral=True
    )


@bot.tree.command(name="produk_edit", description="Edit produk katalog kasir")
@app_commands.describe(
    nama="Pilih produk yang ingin diedit",
    kategori_baru="Kategori baru",
    nama_baru="Nama baru",
    robux="Robux baru"
)
@app_commands.autocomplete(nama=product_autocomplete, kategori_baru=category_autocomplete)
async def produk_edit(
    interaction: discord.Interaction,
    nama: str,
    kategori_baru: Optional[str] = None,
    nama_baru: Optional[str] = None,
    robux: Optional[int] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    product = find_product_by_id(nama)
    if not product:
        await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
        return

    target_category = product["category"]
    if kategori_baru:
        real_category = find_category_name(kategori_baru)
        if not real_category:
            await interaction.response.send_message("Kategori baru tidak ditemukan.", ephemeral=True)
            return
        target_category = real_category

    target_name = nama_baru.strip() if nama_baru else product["name"]

    duplicate = next(
        (
            p for p in PRODUCTS
            if p["id"] != product["id"]
            and normalize_key(p["name"]) == normalize_key(target_name)
            and normalize_key(p["category"]) == normalize_key(target_category)
        ),
        None
    )
    if duplicate:
        await interaction.response.send_message(
            "Sudah ada produk dengan nama yang sama di kategori tujuan.",
            ephemeral=True
        )
        return

    product["category"] = target_category
    product["name"] = target_name

    if robux is not None:
        if robux <= 0:
            await interaction.response.send_message("Robux harus lebih dari 0.", ephemeral=True)
            return
        product["robux"] = robux

    save_products()
    await interaction.response.send_message("✅ Produk berhasil diperbarui.", ephemeral=True)


@bot.tree.command(name="produk_hapus", description="Hapus produk katalog kasir")
@app_commands.describe(nama="Pilih produk yang ingin dihapus")
@app_commands.autocomplete(nama=product_autocomplete)
async def produk_hapus(interaction: discord.Interaction, nama: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    product = find_product_by_id(nama)
    if not product:
        await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
        return

    PRODUCTS.remove(product)
    save_products()
    await interaction.response.send_message(
        f"🗑️ Produk **[{product['category']}] {product['name']}** dihapus.",
        ephemeral=True
    )


@bot.tree.command(name="produk_list", description="Lihat katalog produk kasir")
@app_commands.describe(kategori="Filter kategori opsional")
@app_commands.autocomplete(kategori=category_autocomplete)
async def produk_list(interaction: discord.Interaction, kategori: Optional[str] = None):
    if not PRODUCTS:
        await interaction.response.send_message("Belum ada katalog produk.", ephemeral=True)
        return

    filtered = PRODUCTS
    title = "Katalog Produk Kasir"

    if kategori:
        real_category = find_category_name(kategori)
        if not real_category:
            await interaction.response.send_message("Kategori tidak ditemukan.", ephemeral=True)
            return
        filtered = [p for p in PRODUCTS if normalize_key(p["category"]) == normalize_key(real_category)]
        title = f"Katalog Produk - {real_category}"

    if not filtered:
        await interaction.response.send_message("Tidak ada produk di kategori ini.", ephemeral=True)
        return

    lines = [f"{i}. [{p['category']}] {p['name']} ({p['robux']} robux)" for i, p in enumerate(filtered, start=1)]
    embed = discord.Embed(title=title, description="\n".join(lines[:50]), color=COLOR)
    embed.set_footer(text="Harga final mengikuti rate harian saat /kasir dijalankan")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# CUSTOM ! COMMAND
# =========================================================
@bot.tree.command(name="tambahcommand", description="Tambah/edit/hapus command !custom")
@app_commands.describe(
    action="Aksi yang ingin dilakukan",
    trigger="Nama command tanpa !, contoh: sawahindo",
    teks="Pesan balasan bot (opsional)",
    image1="Gambar 1 (opsional)",
    image2="Gambar 2 (opsional)",
    image3="Gambar 3 (opsional)",
    image4="Gambar 4 (opsional)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="add", value="add"),
    app_commands.Choice(name="edit", value="edit"),
    app_commands.Choice(name="delete", value="delete"),
    app_commands.Choice(name="list", value="list")
])
async def tambahcommand(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    trigger: Optional[str] = None,
    teks: Optional[str] = None,
    image1: Optional[discord.Attachment] = None,
    image2: Optional[discord.Attachment] = None,
    image3: Optional[discord.Attachment] = None,
    image4: Optional[discord.Attachment] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    if action.value == "list":
        if not CUSTOM_COMMANDS:
            await interaction.response.send_message("Belum ada command custom.", ephemeral=True)
            return
        lines = [f"!{key}" for key in sorted(CUSTOM_COMMANDS.keys())]
        await interaction.response.send_message("Command tersedia:\n" + "\n".join(lines), ephemeral=True)
        return

    if not trigger:
        await interaction.response.send_message("Trigger wajib diisi untuk add/edit/delete.", ephemeral=True)
        return

    key = normalize_trigger(trigger)

    if action.value == "delete":
        old_data = CUSTOM_COMMANDS.pop(key, None)
        if not old_data:
            await interaction.response.send_message("Command tidak ditemukan.", ephemeral=True)
            return

        folder = CUSTOM_COMMAND_DIR / key
        if folder.exists():
            for f in folder.iterdir():
                f.unlink(missing_ok=True)
            folder.rmdir()

        save_custom_commands()
        await interaction.response.send_message(f"🗑️ Command **!{key}** dihapus.", ephemeral=True)
        return

    folder = CUSTOM_COMMAND_DIR / key
    folder.mkdir(parents=True, exist_ok=True)

    existing = CUSTOM_COMMANDS.get(key, {"text": "", "images": []})
    provided_images = [img for img in [image1, image2, image3, image4] if img is not None]
    stored_images = existing.get("images", [])

    if provided_images:
        for f in folder.iterdir():
            f.unlink(missing_ok=True)
        stored_images = []

        for index, img in enumerate(provided_images, start=1):
            ext = Path(img.filename).suffix.lower() or ".png"
            if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                ext = ".png"
            filepath = folder / f"{index}{ext}"
            await img.save(filepath)
            stored_images.append(str(filepath))

    CUSTOM_COMMANDS[key] = {
        "text": teks if teks is not None else existing.get("text", ""),
        "images": stored_images
    }
    save_custom_commands()
    await interaction.response.send_message(f"✅ Command **!{key}** berhasil disimpan.", ephemeral=True)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()
    if content.startswith("!") and len(content) > 1:
        trigger = normalize_trigger(content.split()[0])

        if trigger in CUSTOM_COMMANDS:
            payload = CUSTOM_COMMANDS[trigger]
            files = []

            for image_path in payload.get("images", []):
                path = Path(image_path)
                if path.exists():
                    files.append(discord.File(str(path)))

            await message.channel.send(
                content=payload.get("text") or None,
                files=files if files else None
            )

            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

    await bot.process_commands(message)


# =========================================================
# READY / ERROR
# =========================================================
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Bot siap sebagai {bot.user}. Slash synced: {len(synced)}")
    except Exception as e:
        print(f"Gagal sync slash command: {e}")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Kamu tidak punya izin untuk command ini.", delete_after=5)
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        await ctx.send(f"❌ Terjadi error: {error}", delete_after=10)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN belum di-set di environment.")
    bot.run(DISCORD_TOKEN)
