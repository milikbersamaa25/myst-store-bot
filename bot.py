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
WIB = ZoneInfo("Asia/Jakarta")
COLOR = 0x00F8FF
MAX_SLOT = 20
UNCATEGORIZED_NAME = "Umum"

BASE_DIR = Path("data_store_bot")
BASE_DIR.mkdir(exist_ok=True)

VIP_FILE = BASE_DIR / "vip_sessions.json"
PRODUCT_FILE = BASE_DIR / "cashier_products.json"
CATEGORY_FILE = BASE_DIR / "cashier_categories.json"
CUSTOM_PRICELIST_FILE = BASE_DIR / "custom_pricelists.json"
CUSTOM_PRICELIST_DIR = BASE_DIR / "pricelist_media"
CUSTOM_PRICELIST_DIR.mkdir(exist_ok=True)
BUYER_PRICELIST_DIR = BASE_DIR / "buyer_pricelists"
BUYER_PRICELIST_DIR.mkdir(exist_ok=True)

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
    return re.sub(r"\s+", " ", str(text).strip().lower())


def normalize_trigger(text: str) -> str:
    return str(text).strip().lower().lstrip("!")


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


# =========================================================
# STORAGE
# =========================================================
PRODUCTS = load_json(PRODUCT_FILE, [])
CATEGORIES = load_json(CATEGORY_FILE, [])
CUSTOM_PRICELISTS = load_json(CUSTOM_PRICELIST_FILE, {})
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


def save_pricelists():
    save_json(CUSTOM_PRICELIST_FILE, CUSTOM_PRICELISTS)


def save_vip_sessions():
    save_json(VIP_FILE, vip_sessions)


def get_session(message_id: int | str):
    key = str(message_id)
    if key not in vip_sessions:
        vip_sessions[key] = {"info": {}, "list": []}
        save_vip_sessions()
    return vip_sessions[key]


def get_category_by_id(category_id: str):
    for category in CATEGORIES:
        if category.get("id") == category_id:
            return category
    return None


def get_category_by_name(name: str):
    key = normalize_key(name)
    for category in CATEGORIES:
        if normalize_key(category.get("name", "")) == key:
            return category
    return None


def get_uncategorized_category():
    category = get_category_by_name(UNCATEGORIZED_NAME)
    if category:
        return category

    category = {
        "id": str(uuid.uuid4()),
        "name": UNCATEGORIZED_NAME,
        "active": True,
        "protected": True,
    }
    CATEGORIES.append(category)
    save_categories()
    return category


def get_category_name_by_id(category_id: Optional[str]) -> str:
    if not category_id:
        return UNCATEGORIZED_NAME
    category = get_category_by_id(category_id)
    return category.get("name", UNCATEGORIZED_NAME) if category else UNCATEGORIZED_NAME


def get_active_categories() -> list[dict]:
    return sorted(
        [c for c in CATEGORIES if c.get("active", True)],
        key=lambda x: normalize_key(x.get("name", ""))
    )


def get_products_by_category_id(category_id: str, keyword: str = "") -> list[dict]:
    keyword_key = normalize_key(keyword)
    items = []
    for product in PRODUCTS:
        if not product.get("active", True):
            continue
        if product.get("category_id") != category_id:
            continue
        if keyword_key and keyword_key not in normalize_key(product.get("name", "")):
            continue
        items.append(product)
    return sorted(items, key=lambda x: normalize_key(x.get("name", "")))


def find_product_by_id(product_id: str):
    for product in PRODUCTS:
        if product.get("id") == product_id:
            return product
    return None


def find_product_by_name(name: str):
    key = normalize_key(name)
    for product in PRODUCTS:
        if normalize_key(product.get("name", "")) == key:
            return product
    return None


def find_product_by_name_and_category(name: str, category_id: str):
    name_key = normalize_key(name)
    for product in PRODUCTS:
        if normalize_key(product.get("name", "")) == name_key and product.get("category_id") == category_id:
            return product
    return None


def product_display_name(product: dict) -> str:
    return f"[{get_category_name_by_id(product.get('category_id'))}] {product['name']}"


def build_product_choices(current: str):
    current_key = normalize_key(current)
    result = []
    for product in sorted(PRODUCTS, key=lambda x: (normalize_key(get_category_name_by_id(x.get("category_id"))), normalize_key(x.get("name", "")))):
        haystack = f"{get_category_name_by_id(product.get('category_id'))} {product.get('name', '')}"
        if not current_key or current_key in normalize_key(haystack):
            result.append(
                app_commands.Choice(
                    name=product_display_name(product)[:100],
                    value=product.get("name", "")[:100]
                )
            )
        if len(result) >= 25:
            break
    return result


async def product_autocomplete(interaction: discord.Interaction, current: str):
    return build_product_choices(current)


def build_category_choices(current: str):
    current_key = normalize_key(current)
    result = []
    for category in get_active_categories():
        if not current_key or current_key in normalize_key(category.get("name", "")):
            result.append(
                app_commands.Choice(
                    name=category.get("name", "")[:100],
                    value=category.get("name", "")[:100]
                )
            )
        if len(result) >= 25:
            break
    return result


async def category_autocomplete(interaction: discord.Interaction, current: str):
    return build_category_choices(current)


def add_product_to_cart(session: dict, product: dict) -> bool:
    for item in session["items"]:
        if item.get("product_id") == product.get("id"):
            return False

    rate = int(session["rate"])
    robux = int(product["robux"])
    price = calculate_price(robux, rate)
    session["items"].append({
        "product_id": product["id"],
        "name": product["name"],
        "category_id": product.get("category_id"),
        "robux": robux,
        "price": price,
        "qty": 1,
    })
    return True


def get_cart_item_by_product_id(session: dict, product_id: str):
    for item in session["items"]:
        if item.get("product_id") == product_id:
            return item
    return None


def migrate_categories_and_products():
    changed_products = False
    changed_categories = False

    if not isinstance(CATEGORIES, list):
        CATEGORIES.clear()
        changed_categories = True

    # normalize categories list
    seen_category_names = set()
    normalized_categories = []
    for category in CATEGORIES:
        if not isinstance(category, dict):
            continue
        name = str(category.get("name", "")).strip() or UNCATEGORIZED_NAME
        name_key = normalize_key(name)
        if name_key in seen_category_names:
            continue
        seen_category_names.add(name_key)
        normalized_categories.append({
            "id": category.get("id") or str(uuid.uuid4()),
            "name": name,
            "active": category.get("active", True),
            "protected": category.get("protected", False) or name_key == normalize_key(UNCATEGORIZED_NAME),
        })

    if len(normalized_categories) != len(CATEGORIES):
        changed_categories = True
    CATEGORIES[:] = normalized_categories

    uncategorized = get_uncategorized_category()
    uncategorized_id = uncategorized["id"]

    def ensure_category(name: str):
        nonlocal changed_categories
        category = get_category_by_name(name)
        if category:
            return category
        category = {
            "id": str(uuid.uuid4()),
            "name": name,
            "active": True,
            "protected": normalize_key(name) == normalize_key(UNCATEGORIZED_NAME),
        }
        CATEGORIES.append(category)
        changed_categories = True
        return category

    for product in PRODUCTS:
        if not isinstance(product, dict):
            continue
        if not product.get("id"):
            product["id"] = str(uuid.uuid4())
            changed_products = True
        if "active" not in product:
            product["active"] = True
            changed_products = True

        category_id = product.get("category_id")
        category_name = str(product.get("category", "")).strip()

        if category_id and not get_category_by_id(category_id):
            category_id = None

        if not category_id:
            if category_name:
                category = ensure_category(category_name)
                product["category_id"] = category["id"]
            else:
                product["category_id"] = uncategorized_id
            changed_products = True

        if "category" in product:
            # preserve compatibility, but align name with master category
            actual_name = get_category_name_by_id(product.get("category_id"))
            if product.get("category") != actual_name:
                product["category"] = actual_name
                changed_products = True
        else:
            product["category"] = get_category_name_by_id(product.get("category_id"))
            changed_products = True

    if changed_categories:
        save_categories()
    if changed_products:
        save_products()


migrate_categories_and_products()


# =========================================================
# HELP COMMANDS
# =========================================================
@bot.tree.command(name="viphelp", description="Panduan command VIP")
async def viphelp(interaction: discord.Interaction):
    embed = discord.Embed(title="Panduan VIP", color=COLOR)
    embed.description = (
        "**Command VIP yang tersedia:**\n\n"
        "`!vip`\n"
        "Membuat list VIP baru.\n\n"
        "`/editslot`\n"
        "Edit slot VIP berdasarkan message ID.\n\n"
        "`/pay`\n"
        "Ubah status paid/unpaid beberapa slot sekaligus.\n\n"
        "`/delete`\n"
        "Hapus slot tertentu berdasarkan message ID.\n\n"
        "**Contoh:**\n"
        "`/editslot message_id:123456789 nomor:1 roblox:ABC member:@User`\n"
        "`/pay message_id:123456789 slots:1,2,3 status:paid`\n"
        "`/delete message_id:123456789 nomor:3`"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="adminhelp", description="Panduan command admin toko")
async def adminhelp(interaction: discord.Interaction):
    embed = discord.Embed(title="Panduan Admin Bot Toko", color=COLOR)
    embed.description = (
        "**VIP:**\n"
        "`!vip` - Buat list VIP\n"
        "`/editslot` - Edit slot VIP\n"
        "`/pay` - Update payment slot VIP\n"
        "`/delete` - Hapus slot VIP\n\n"
        "**Kategori Kasir:**\n"
        "`/kategori_tambah` - Tambah kategori\n"
        "`/kategori_edit` - Edit kategori\n"
        "`/kategori_hapus` - Hapus kategori dan semua produknya\n"
        "`/kategori_list` - Lihat daftar kategori\n\n"
        "**Kasir:**\n"
        "`/kasir` - Mulai kasir dengan rate harian\n"
        "`/produk_tambah` - Tambah produk ke kategori\n"
        "`/produk_edit` - Edit produk katalog kasir\n"
        "`/produk_hapus` - Hapus produk katalog kasir\n"
        "`/produk_list` - Lihat katalog produk kasir\n\n"
        "**Pricelist Customer:**\n"
        "`/cekpricelist` - Customer cek pricelist sendiri\n"
        "`/update_pricelist` - Admin update gambar pricelist\n\n"
        "**Command ! custom:**\n"
        "`/pricelistedit` - Tambah/edit/hapus command ! custom\n\n"
        "**Catatan:**\n"
        "Harga kasir = `robux x rate`, lalu dibulatkan ke atas ke kelipatan 500."
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# VIP SYSTEM
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
        if info.get("server"):
            lines.append(f"SERVER  : {info.get('server')}")
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

    embed = discord.Embed(
        title=title,
        description="\n".join(lines),
        color=COLOR
    )
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
        info["server"] = self.server.value
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
        session = get_session(message_id)
        vip_list = session["list"]

        options = []
        for idx, data in enumerate(vip_list, start=1):
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
        vip_list = session["list"]
        slot_id = self.values[0]

        for i, data in enumerate(vip_list):
            if data["id"] == slot_id:
                if data["user_id"] != interaction.user.id:
                    await interaction.response.send_message("Bukan slot kamu.", ephemeral=True)
                    return

                vip_list.pop(i)
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

    @discord.ui.button(label="- Hapus Slot", style=discord.ButtonStyle.danger)
    async def delete_slot(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            "Pilih slot yang ingin dihapus:",
            view=DeleteView(self.message_id, interaction.user.id),
            ephemeral=True
        )

    @discord.ui.button(label="⚙️ Edit Info", style=discord.ButtonStyle.secondary)
    async def edit_info(self, interaction: discord.Interaction, button: Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("Hanya admin.", ephemeral=True)
            return
        await interaction.response.send_modal(VipSetupModal(self.message_id))


@bot.command(name="vip")
@commands.has_permissions(administrator=True)
async def vip(ctx: commands.Context):
    embed = make_vip_embed("temp")
    sent = await ctx.send(embed=embed)
    vip_sessions[str(sent.id)] = {"info": {}, "list": []}
    save_vip_sessions()
    await sent.edit(embed=make_vip_embed(sent.id), view=VipView(sent.id))


@bot.tree.command(name="editslot", description="Edit slot VIP tertentu")
@app_commands.describe(message_id="ID pesan VIP", nomor="Nomor slot", roblox="Username Roblox baru", member="Member baru")
async def editslot(
    interaction: discord.Interaction,
    message_id: str,
    nomor: int,
    roblox: Optional[str] = None,
    member: Optional[discord.Member] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    session = get_session(message_id)
    vip_list = session["list"]

    if nomor < 1 or nomor > len(vip_list):
        await interaction.response.send_message("Nomor slot tidak valid.", ephemeral=True)
        return

    data = vip_list[nomor - 1]
    if roblox:
        data["roblox"] = roblox.strip()
    if member:
        data["user_id"] = member.id
        data["mention"] = member.mention

    save_vip_sessions()

    msg = await interaction.channel.fetch_message(int(message_id))
    await msg.edit(embed=make_vip_embed(message_id), view=VipView(int(message_id)))
    await interaction.response.send_message("✅ Slot berhasil diperbarui.", ephemeral=True)


@bot.tree.command(name="pay", description="Ubah status pembayaran slot VIP")
@app_commands.describe(message_id="ID pesan VIP", slots="Contoh: 1,2,3 atau 1-5", status="paid / unpaid")
@app_commands.choices(status=[
    app_commands.Choice(name="paid", value="paid"),
    app_commands.Choice(name="unpaid", value="unpaid")
])
async def pay(
    interaction: discord.Interaction,
    message_id: str,
    slots: str,
    status: app_commands.Choice[str]
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    session = get_session(message_id)
    vip_list = session["list"]

    try:
        numbers = parse_slot_numbers(slots)
    except Exception as e:
        await interaction.response.send_message(f"Format slot salah: {e}", ephemeral=True)
        return

    changed = 0
    for num in numbers:
        if 1 <= num <= len(vip_list):
            vip_list[num - 1]["paid"] = status.value == "paid"
            changed += 1

    save_vip_sessions()

    msg = await interaction.channel.fetch_message(int(message_id))
    await msg.edit(embed=make_vip_embed(message_id), view=VipView(int(message_id)))
    await interaction.response.send_message(f"✅ Status payment diperbarui untuk {changed} slot.", ephemeral=True)


@bot.tree.command(name="delete", description="Hapus slot VIP tertentu")
@app_commands.describe(message_id="ID pesan VIP", nomor="Nomor slot yang ingin dihapus")
async def delete(interaction: discord.Interaction, message_id: str, nomor: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    session = get_session(message_id)
    vip_list = session["list"]

    if nomor < 1 or nomor > len(vip_list):
        await interaction.response.send_message("Nomor slot tidak valid.", ephemeral=True)
        return

    vip_list.pop(nomor - 1)
    save_vip_sessions()

    msg = await interaction.channel.fetch_message(int(message_id))
    await msg.edit(embed=make_vip_embed(message_id), view=VipView(int(message_id)))
    await interaction.response.send_message("✅ Slot berhasil dihapus.", ephemeral=True)


# =========================================================
# BUYER PRICELIST
# =========================================================
def get_buyer_file(game_key: str, item_key: str) -> Path:
    return BUYER_PRICELIST_DIR / f"{game_key}_{item_key}.png"


class BuyerGameSelect(Select):
    def __init__(self):
        options = [discord.SelectOption(label=data["name"], value=key) for key, data in BUYER_DATA.items()]
        super().__init__(placeholder="Pilih game", options=options)

    async def callback(self, interaction: discord.Interaction):
        game_key = self.values[0]
        await interaction.response.send_message(
            f"Pilih jenis item untuk **{BUYER_DATA[game_key]['name']}**:",
            view=BuyerItemView(game_key),
            ephemeral=True
        )


class BuyerGameView(View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(BuyerGameSelect())


class BuyerItemSelect(Select):
    def __init__(self, game_key: str):
        self.game_key = game_key
        options = [discord.SelectOption(label=name, value=item_key) for item_key, name in BUYER_DATA[game_key]["items"].items()]
        super().__init__(placeholder="Pilih item", options=options)

    async def callback(self, interaction: discord.Interaction):
        item_key = self.values[0]
        filepath = get_buyer_file(self.game_key, item_key)

        if not filepath.exists():
            await interaction.response.send_message("Pricelist untuk item itu belum diupload admin.", ephemeral=True)
            return

        await interaction.response.send_message(
            content=f"Berikut pricelist **{BUYER_DATA[self.game_key]['name']} - {BUYER_DATA[self.game_key]['items'][item_key]}**",
            file=discord.File(str(filepath)),
            ephemeral=True
        )


class BuyerItemView(View):
    def __init__(self, game_key: str):
        super().__init__(timeout=120)
        self.add_item(BuyerItemSelect(game_key))


@bot.tree.command(name="cekpricelist", description="Cek pricelist game/customer")
async def cekpricelist(interaction: discord.Interaction):
    await interaction.response.send_message("Pilih game untuk melihat pricelist:", view=BuyerGameView(), ephemeral=True)


@bot.tree.command(name="update_pricelist", description="Upload/update gambar pricelist buyer")
@app_commands.describe(game="Game target", item="Jenis item", gambar="File gambar pricelist")
@app_commands.choices(game=[app_commands.Choice(name=data["name"], value=key) for key, data in BUYER_DATA.items()])
async def update_pricelist(
    interaction: discord.Interaction,
    game: app_commands.Choice[str],
    item: str,
    gambar: discord.Attachment
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    game_key = game.value
    item_key = normalize_key(item).replace(" ", "")

    if item_key not in BUYER_DATA[game_key]["items"]:
        valid_items = ", ".join(BUYER_DATA[game_key]["items"].values())
        await interaction.response.send_message(f"Item tidak valid. Gunakan salah satu: {valid_items}", ephemeral=True)
        return

    ext = Path(gambar.filename).suffix.lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

    filepath = BUYER_PRICELIST_DIR / f"{game_key}_{item_key}{ext}"
    for old in BUYER_PRICELIST_DIR.glob(f"{game_key}_{item_key}.*"):
        old.unlink(missing_ok=True)

    await gambar.save(filepath)
    await interaction.response.send_message(
        f"✅ Pricelist **{BUYER_DATA[game_key]['name']} - {BUYER_DATA[game_key]['items'][item_key]}** berhasil diupdate.",
        ephemeral=True
    )


# =========================================================
# KASIR SYSTEM
# =========================================================
def build_kasir_preview_embed(session_id: str) -> discord.Embed:
    session = kasir_sessions[session_id]
    total = 0

    lines = [
        f"**Customer:** {session['customer']}",
        f"**Rate:** {session['rate']}",
        f"**Tanggal:** {format_wib()}",
        "",
        "**Daftar Pembelian:**"
    ]

    if not session["items"]:
        lines.append("_Belum ada item dipilih._")
    else:
        for i, item in enumerate(session["items"], start=1):
            subtotal = item["price"] * item["qty"]
            total += subtotal
            qty_suffix = f" x{item['qty']}" if item["qty"] > 1 else ""
            category_name = get_category_name_by_id(item.get("category_id"))
            lines.append(
                f"{i}. [{category_name}] {item['name']} ({item['robux']} Robux){qty_suffix} = {format_rupiah(subtotal)}"
            )

    lines.append("")
    lines.append(f"**Total:** {format_rupiah(total)}")

    embed = discord.Embed(title="Preview Kasir", description="\n".join(lines), color=COLOR)
    embed.set_footer(text="Pilih produk, ubah qty bila perlu, lalu tekan Selesai")
    return embed


def build_invoice_text(session: dict) -> str:
    lines = [
        "⏤͟͟͞͞★      𝐌𝐘𝐒𝐓 𝐒𝐓𝐎𝐑𝐄      ★⏤͟͟͞͞",
        "",
        f"✦ **Tanggal:** {format_wib()}",
        f"✦ **Customer:** {session['customer']}",
        f"✦ **Rate:** {session['rate']}",
        "",
        "**— Daftar Pembelian —**"
    ]

    total = 0
    for i, item in enumerate(session["items"], start=1):
        subtotal = item["price"] * item["qty"]
        total += subtotal
        qty_suffix = f" x{item['qty']}" if item["qty"] > 1 else ""
        category_name = get_category_name_by_id(item.get("category_id"))
        lines.append(
            f"{i}. [{category_name}] {item['name']} ({item['robux']} Robux){qty_suffix} = {format_rupiah(subtotal)}"
        )

    lines.extend([
        "",
        f"**TOTAL : {format_rupiah(total)}**",
        "",
        "Terima kasih telah berbelanja di **Myst Store** ✨"
    ])
    return "\n".join(lines)


class KasirStartModal(Modal):
    def __init__(self):
        super().__init__(title="Mulai Kasir")
        self.customer = TextInput(label="Nama Customer", placeholder="Contoh: KennMyst")
        self.rate = TextInput(label="Rate hari ini", placeholder="Contoh: 90")
        self.add_item(self.customer)
        self.add_item(self.rate)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
            return

        try:
            rate = int(self.rate.value.strip())
            if rate <= 0:
                raise ValueError
        except Exception:
            await interaction.response.send_message("Rate harus berupa angka lebih dari 0.", ephemeral=True)
            return

        if not get_active_categories():
            await interaction.response.send_message("Belum ada kategori aktif. Buat dulu dengan /kategori_tambah.", ephemeral=True)
            return

        session_id = str(uuid.uuid4())
        kasir_sessions[session_id] = {
            "customer": self.customer.value.strip(),
            "rate": rate,
            "items": [],
            "selected_category_id": None,
            "search_keyword": "",
        }

        await interaction.response.send_message(
            embed=build_kasir_preview_embed(session_id),
            view=KasirView(session_id),
            ephemeral=True
        )


class ProductSearchModal(Modal):
    def __init__(self, session_id: str):
        super().__init__(title="Cari Produk")
        self.session_id = session_id
        session = kasir_sessions[self.session_id]
        self.keyword = TextInput(
            label="Nama produk",
            placeholder="Ketik sebagian nama produk",
            required=False,
            default=session.get("search_keyword", "")
        )
        self.add_item(self.keyword)

    async def on_submit(self, interaction: discord.Interaction):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return

        category_id = session.get("selected_category_id")
        category = get_category_by_id(category_id) if category_id else None
        if not category:
            await interaction.response.send_message("Pilih kategori dulu.", ephemeral=True)
            return

        session["search_keyword"] = self.keyword.value.strip()
        await interaction.response.send_message(
            f"Hasil pencarian kategori **{category['name']}**:",
            view=KasirProductView(self.session_id),
            ephemeral=True
        )


class EditQtyModal(Modal):
    def __init__(self, session_id: str, product_id: str):
        super().__init__(title="Edit Jumlah Item")
        self.session_id = session_id
        self.product_id = product_id
        session = kasir_sessions[self.session_id]
        item = get_cart_item_by_product_id(session, self.product_id)
        current_qty = str(item["qty"]) if item else "1"
        self.qty = TextInput(label="Jumlah item", placeholder="Contoh: 2", default=current_qty)
        self.add_item(self.qty)

    async def on_submit(self, interaction: discord.Interaction):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return

        item = get_cart_item_by_product_id(session, self.product_id)
        if not item:
            await interaction.response.send_message("Item tidak ditemukan.", ephemeral=True)
            return

        try:
            qty = int(self.qty.value.strip())
            if qty <= 0:
                raise ValueError
        except Exception:
            await interaction.response.send_message("Jumlah harus angka lebih dari 0.", ephemeral=True)
            return

        item["qty"] = qty
        await interaction.response.send_message(
            "✅ Qty berhasil diperbarui.",
            embed=build_kasir_preview_embed(self.session_id),
            view=KasirView(self.session_id),
            ephemeral=True
        )


class KasirCategorySelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        categories = get_active_categories()

        if not categories:
            options = [discord.SelectOption(label="Belum ada kategori", value="none")]
        else:
            options = [
                discord.SelectOption(label=category["name"][:100], value=category["id"])
                for category in categories[:25]
            ]

        super().__init__(placeholder="Pilih kategori", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada kategori aktif.", ephemeral=True)
            return

        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return

        category = get_category_by_id(self.values[0])
        if not category or not category.get("active", True):
            await interaction.response.send_message("Kategori tidak ditemukan atau nonaktif.", ephemeral=True)
            return

        session["selected_category_id"] = category["id"]
        session["search_keyword"] = ""

        await interaction.response.send_message(
            f"Pilih produk dari kategori **{category['name']}**:",
            view=KasirProductView(self.session_id),
            ephemeral=True
        )


class KasirCategoryView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=180)
        self.session_id = session_id
        self.add_item(KasirCategorySelect(session_id))

    @discord.ui.button(label="Lihat Keranjang", style=discord.ButtonStyle.secondary)
    async def lihat_keranjang(self, interaction: discord.Interaction, button: Button):
        if self.session_id not in kasir_sessions:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=build_kasir_preview_embed(self.session_id),
            view=KasirView(self.session_id),
            ephemeral=True
        )


class KasirProductMultiSelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        session = kasir_sessions[self.session_id]
        category_id = session.get("selected_category_id")
        keyword = session.get("search_keyword", "")
        products = get_products_by_category_id(category_id, keyword) if category_id else []

        if not products:
            options = [discord.SelectOption(label="Produk tidak ditemukan", value="none")]
            max_values = 1
        else:
            limited = products[:25]
            options = [
                discord.SelectOption(
                    label=product["name"][:100],
                    description=f"{product['robux']} Robux"[:100],
                    value=product["id"]
                )
                for product in limited
            ]
            max_values = len(options)

        category_name = get_category_name_by_id(category_id)
        placeholder = f"Kategori: {category_name}"[:150]
        super().__init__(placeholder=placeholder, min_values=1, max_values=max_values, options=options)

    async def callback(self, interaction: discord.Interaction):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return

        if self.values[0] == "none":
            await interaction.response.send_message("Tidak ada produk yang bisa dipilih.", ephemeral=True)
            return

        added = 0
        for product_id in self.values:
            product = find_product_by_id(product_id)
            if not product or not product.get("active", True):
                continue
            if add_product_to_cart(session, product):
                added += 1

        await interaction.response.send_message(
            f"✅ {added} produk ditambahkan ke keranjang. Qty default semua item adalah 1.",
            embed=build_kasir_preview_embed(self.session_id),
            view=KasirView(self.session_id),
            ephemeral=True
        )


class KasirProductView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=180)
        self.session_id = session_id
        self.add_item(KasirProductMultiSelect(session_id))

    @discord.ui.button(label="Cari Produk", style=discord.ButtonStyle.primary)
    async def cari_produk(self, interaction: discord.Interaction, button: Button):
        if self.session_id not in kasir_sessions:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return
        await interaction.response.send_modal(ProductSearchModal(self.session_id))

    @discord.ui.button(label="Back ke Kategori", style=discord.ButtonStyle.secondary)
    async def back_category(self, interaction: discord.Interaction, button: Button):
        if self.session_id not in kasir_sessions:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return
        await interaction.response.send_message("Pilih kategori lain:", view=KasirCategoryView(self.session_id), ephemeral=True)

    @discord.ui.button(label="Lihat Keranjang", style=discord.ButtonStyle.success)
    async def lihat_keranjang(self, interaction: discord.Interaction, button: Button):
        if self.session_id not in kasir_sessions:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=build_kasir_preview_embed(self.session_id),
            view=KasirView(self.session_id),
            ephemeral=True
        )


class EditQtySelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        session = kasir_sessions[self.session_id]

        options = []
        for item in session["items"][:25]:
            options.append(
                discord.SelectOption(
                    label=f"{item['name']} (qty {item['qty']})"[:100],
                    description=f"{get_category_name_by_id(item.get('category_id'))} - {item['robux']} Robux"[:100],
                    value=item["product_id"]
                )
            )

        if not options:
            options = [discord.SelectOption(label="Belum ada item", value="none")]

        super().__init__(placeholder="Pilih item yang ingin diubah jumlahnya", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada item di keranjang.", ephemeral=True)
            return
        await interaction.response.send_modal(EditQtyModal(self.session_id, self.values[0]))


class EditQtyView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=120)
        self.add_item(EditQtySelect(session_id))


class RemoveItemSelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        session = kasir_sessions[self.session_id]

        options = []
        for item in session["items"][:25]:
            options.append(
                discord.SelectOption(
                    label=item["name"][:100],
                    description=f"{get_category_name_by_id(item.get('category_id'))} - qty {item['qty']}"[:100],
                    value=item["product_id"]
                )
            )

        if not options:
            options = [discord.SelectOption(label="Belum ada item", value="none")]

        super().__init__(placeholder="Pilih item yang ingin dihapus", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada item di keranjang.", ephemeral=True)
            return

        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return

        session["items"] = [item for item in session["items"] if item["product_id"] != self.values[0]]
        await interaction.response.send_message(
            "🗑️ Item dihapus dari keranjang.",
            embed=build_kasir_preview_embed(self.session_id),
            view=KasirView(self.session_id),
            ephemeral=True
        )


class RemoveItemView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=120)
        self.add_item(RemoveItemSelect(session_id))


class KasirView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=300)
        self.session_id = session_id

    @discord.ui.button(label="Tambah Produk", style=discord.ButtonStyle.success)
    async def tambah_produk(self, interaction: discord.Interaction, button: Button):
        if self.session_id not in kasir_sessions:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return

        if not get_active_categories():
            await interaction.response.send_message("Belum ada kategori aktif di katalog.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Pilih kategori produk:",
            view=KasirCategoryView(self.session_id),
            ephemeral=True
        )

    @discord.ui.button(label="Edit Qty", style=discord.ButtonStyle.primary)
    async def edit_qty(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return
        if not session["items"]:
            await interaction.response.send_message("Belum ada item di keranjang.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Pilih item yang ingin diubah qty:",
            view=EditQtyView(self.session_id),
            ephemeral=True
        )

    @discord.ui.button(label="Hapus Item", style=discord.ButtonStyle.danger)
    async def hapus_item(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return
        if not session["items"]:
            await interaction.response.send_message("Belum ada item di keranjang.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Pilih item yang ingin dihapus:",
            view=RemoveItemView(self.session_id),
            ephemeral=True
        )

    @discord.ui.button(label="Selesai", style=discord.ButtonStyle.secondary)
    async def selesai(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Session kasir tidak ditemukan.", ephemeral=True)
            return
        if not session["items"]:
            await interaction.response.send_message("Belum ada item di keranjang.", ephemeral=True)
            return

        invoice = build_invoice_text(session)
        del kasir_sessions[self.session_id]
        await interaction.response.send_message(invoice)

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.danger)
    async def batal(self, interaction: discord.Interaction, button: Button):
        if self.session_id in kasir_sessions:
            del kasir_sessions[self.session_id]
        await interaction.response.send_message("Kasir dibatalkan.", ephemeral=True)


@bot.tree.command(name="kasir", description="Mulai kasir dan hitung invoice dari rate harian")
async def kasir(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return
    await interaction.response.send_modal(KasirStartModal())


# =========================================================
# MASTER KATEGORI
# =========================================================
@bot.tree.command(name="kategori_tambah", description="Tambah kategori master kasir")
@app_commands.describe(nama="Nama kategori")
async def kategori_tambah(interaction: discord.Interaction, nama: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    nama = nama.strip()
    if not nama:
        await interaction.response.send_message("Nama kategori tidak boleh kosong.", ephemeral=True)
        return

    if get_category_by_name(nama):
        await interaction.response.send_message("Kategori dengan nama itu sudah ada.", ephemeral=True)
        return

    CATEGORIES.append({
        "id": str(uuid.uuid4()),
        "name": nama,
        "active": True,
        "protected": normalize_key(nama) == normalize_key(UNCATEGORIZED_NAME),
    })
    save_categories()
    await interaction.response.send_message(f"✅ Kategori **{nama}** berhasil ditambahkan.", ephemeral=True)


@bot.tree.command(name="kategori_edit", description="Edit kategori master kasir")
@app_commands.describe(nama="Nama kategori yang ingin diedit", nama_baru="Nama kategori baru", aktif="Status aktif kategori")
@app_commands.autocomplete(nama=category_autocomplete)
async def kategori_edit(
    interaction: discord.Interaction,
    nama: str,
    nama_baru: Optional[str] = None,
    aktif: Optional[bool] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    category = get_category_by_name(nama)
    if not category:
        await interaction.response.send_message("Kategori tidak ditemukan.", ephemeral=True)
        return

    if nama_baru:
        nama_baru = nama_baru.strip()
        if not nama_baru:
            await interaction.response.send_message("Nama kategori baru tidak boleh kosong.", ephemeral=True)
            return

        existing = get_category_by_name(nama_baru)
        if existing and existing is not category:
            await interaction.response.send_message("Nama kategori baru sudah dipakai kategori lain.", ephemeral=True)
            return

        category["name"] = nama_baru
        for product in PRODUCTS:
            if product.get("category_id") == category.get("id"):
                product["category"] = nama_baru
        save_products()

    if aktif is not None:
        category["active"] = aktif

    save_categories()
    await interaction.response.send_message("✅ Kategori berhasil diperbarui.", ephemeral=True)


@bot.tree.command(name="kategori_hapus", description="Hapus kategori dan semua produk di dalamnya")
@app_commands.describe(nama="Nama kategori yang ingin dihapus")
@app_commands.autocomplete(nama=category_autocomplete)
async def kategori_hapus(interaction: discord.Interaction, nama: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    category = get_category_by_name(nama)
    if not category:
        await interaction.response.send_message("Kategori tidak ditemukan.", ephemeral=True)
        return

    if category.get("protected"):
        await interaction.response.send_message("Kategori default tidak boleh dihapus.", ephemeral=True)
        return

    product_count = sum(1 for product in PRODUCTS if product.get("category_id") == category.get("id"))
    PRODUCTS[:] = [product for product in PRODUCTS if product.get("category_id") != category.get("id")]
    CATEGORIES[:] = [item for item in CATEGORIES if item.get("id") != category.get("id")]

    save_products()
    save_categories()
    await interaction.response.send_message(
        f"🗑️ Kategori **{category['name']}** berhasil dihapus. {product_count} produk ikut terhapus.",
        ephemeral=True
    )


@bot.tree.command(name="kategori_list", description="Lihat daftar kategori master kasir")
async def kategori_list(interaction: discord.Interaction):
    if not CATEGORIES:
        await interaction.response.send_message("Belum ada kategori.", ephemeral=True)
        return

    lines = []
    for idx, category in enumerate(sorted(CATEGORIES, key=lambda x: normalize_key(x.get("name", ""))), start=1):
        total_produk = sum(1 for product in PRODUCTS if product.get("category_id") == category.get("id"))
        status = "aktif" if category.get("active", True) else "nonaktif"
        lines.append(f"{idx}. {category['name']} - {status} - {total_produk} produk")

    embed = discord.Embed(title="Daftar Kategori Kasir", description="\n".join(lines), color=COLOR)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# PRODUK KASIR
# =========================================================
@bot.tree.command(name="produk_tambah", description="Tambah produk ke katalog kasir")
@app_commands.describe(nama="Nama produk", kategori="Nama kategori", robux="Jumlah robux")
@app_commands.autocomplete(kategori=category_autocomplete)
async def produk_tambah(interaction: discord.Interaction, nama: str, kategori: str, robux: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    nama = nama.strip()
    kategori = kategori.strip()

    if not nama:
        await interaction.response.send_message("Nama produk tidak boleh kosong.", ephemeral=True)
        return

    category = get_category_by_name(kategori)
    if not category:
        await interaction.response.send_message("Kategori tidak ditemukan. Buat dulu dengan /kategori_tambah.", ephemeral=True)
        return

    if find_product_by_name_and_category(nama, category["id"]):
        await interaction.response.send_message("Produk dengan nama itu sudah ada di kategori tersebut.", ephemeral=True)
        return

    if robux <= 0:
        await interaction.response.send_message("Jumlah robux harus lebih dari 0.", ephemeral=True)
        return

    PRODUCTS.append({
        "id": str(uuid.uuid4()),
        "name": nama,
        "category_id": category["id"],
        "category": category["name"],
        "robux": robux,
        "active": True,
    })
    save_products()
    await interaction.response.send_message(
        f"✅ Produk **{nama}** berhasil ditambahkan ke kategori **{category['name']}**.",
        ephemeral=True
    )


@bot.tree.command(name="produk_edit", description="Edit produk katalog kasir")
@app_commands.describe(
    nama="Nama produk yang ingin diedit",
    nama_baru="Nama baru",
    kategori="Kategori baru",
    robux="Robux baru",
    aktif="Status aktif produk"
)
@app_commands.autocomplete(nama=product_autocomplete, kategori=category_autocomplete)
async def produk_edit(
    interaction: discord.Interaction,
    nama: str,
    nama_baru: Optional[str] = None,
    kategori: Optional[str] = None,
    robux: Optional[int] = None,
    aktif: Optional[bool] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    product = find_product_by_name(nama)
    if not product:
        await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
        return

    target_category_id = product.get("category_id")
    target_category_name = get_category_name_by_id(target_category_id)

    if kategori is not None:
        category = get_category_by_name(kategori)
        if not category:
            await interaction.response.send_message("Kategori baru tidak ditemukan.", ephemeral=True)
            return
        target_category_id = category["id"]
        target_category_name = category["name"]

    if nama_baru:
        nama_baru = nama_baru.strip()
        if not nama_baru:
            await interaction.response.send_message("Nama baru tidak boleh kosong.", ephemeral=True)
            return
    else:
        nama_baru = product["name"]

    existing = find_product_by_name_and_category(nama_baru, target_category_id)
    if existing and existing is not product:
        await interaction.response.send_message("Produk dengan nama itu sudah ada di kategori tujuan.", ephemeral=True)
        return

    product["name"] = nama_baru
    product["category_id"] = target_category_id
    product["category"] = target_category_name

    if robux is not None:
        if robux <= 0:
            await interaction.response.send_message("Robux harus lebih dari 0.", ephemeral=True)
            return
        product["robux"] = robux

    if aktif is not None:
        product["active"] = aktif

    save_products()
    await interaction.response.send_message("✅ Produk berhasil diperbarui.", ephemeral=True)


@bot.tree.command(name="produk_hapus", description="Hapus produk katalog kasir")
@app_commands.describe(nama="Nama produk yang ingin dihapus")
@app_commands.autocomplete(nama=product_autocomplete)
async def produk_hapus(interaction: discord.Interaction, nama: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    product = find_product_by_name(nama)
    if not product:
        await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
        return

    category_name = get_category_name_by_id(product.get("category_id"))
    PRODUCTS.remove(product)
    save_products()
    await interaction.response.send_message(
        f"🗑️ Produk **{product['name']}** dihapus dari kategori **{category_name}**.",
        ephemeral=True
    )


@bot.tree.command(name="produk_list", description="Lihat katalog produk kasir")
@app_commands.describe(kategori="Filter kategori (opsional)")
@app_commands.autocomplete(kategori=category_autocomplete)
async def produk_list(interaction: discord.Interaction, kategori: Optional[str] = None):
    if not PRODUCTS:
        await interaction.response.send_message("Belum ada katalog produk.", ephemeral=True)
        return

    filtered = []
    if kategori:
        category = get_category_by_name(kategori)
        if not category:
            await interaction.response.send_message("Kategori tidak ditemukan.", ephemeral=True)
            return
        filtered = [p for p in PRODUCTS if p.get("category_id") == category.get("id")]
    else:
        filtered = sorted(PRODUCTS, key=lambda x: (normalize_key(get_category_name_by_id(x.get("category_id"))), normalize_key(x.get("name", ""))))

    if not filtered:
        await interaction.response.send_message("Tidak ada produk pada kategori itu.", ephemeral=True)
        return

    lines = []
    for i, product in enumerate(filtered, start=1):
        status = "aktif" if product.get("active", True) else "nonaktif"
        category_name = get_category_name_by_id(product.get("category_id"))
        lines.append(f"{i}. [{category_name}] {product['name']} ({product['robux']} robux) - {status}")

    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > 3800:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))

    embed = discord.Embed(title="Katalog Produk Kasir", color=COLOR)
    embed.description = chunks[0]
    embed.set_footer(text="Harga final mengikuti rate harian saat /kasir dijalankan")
    await interaction.response.send_message(embed=embed, ephemeral=True)

    for extra in chunks[1:]:
        extra_embed = discord.Embed(title="Katalog Produk Kasir (lanjutan)", description=extra, color=COLOR)
        await interaction.followup.send(embed=extra_embed, ephemeral=True)


# =========================================================
# CUSTOM ! COMMAND PRICELIST
# =========================================================
@bot.tree.command(name="pricelistedit", description="Tambah/edit/hapus command !pricelist custom")
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
async def pricelistedit(
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
        if not CUSTOM_PRICELISTS:
            await interaction.response.send_message("Belum ada command custom.", ephemeral=True)
            return
        lines = [f"!{key}" for key in sorted(CUSTOM_PRICELISTS.keys())]
        await interaction.response.send_message("Command tersedia:\n" + "\n".join(lines), ephemeral=True)
        return

    if not trigger:
        await interaction.response.send_message("Trigger wajib diisi untuk add/edit/delete.", ephemeral=True)
        return

    key = normalize_trigger(trigger)

    if action.value == "delete":
        old_data = CUSTOM_PRICELISTS.pop(key, None)
        if not old_data:
            await interaction.response.send_message("Command tidak ditemukan.", ephemeral=True)
            return

        folder = CUSTOM_PRICELIST_DIR / key
        if folder.exists():
            for f in folder.iterdir():
                f.unlink(missing_ok=True)
            folder.rmdir()

        save_pricelists()
        await interaction.response.send_message(f"🗑️ Command **!{key}** dihapus.", ephemeral=True)
        return

    folder = CUSTOM_PRICELIST_DIR / key
    folder.mkdir(parents=True, exist_ok=True)

    existing = CUSTOM_PRICELISTS.get(key, {"text": "", "images": []})
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

    CUSTOM_PRICELISTS[key] = {
        "text": teks if teks is not None else existing.get("text", ""),
        "images": stored_images
    }
    save_pricelists()
    await interaction.response.send_message(f"✅ Command **!{key}** berhasil disimpan.", ephemeral=True)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()
    if content.startswith("!") and len(content) > 1:
        trigger = normalize_trigger(content.split()[0])

        if trigger in CUSTOM_PRICELISTS:
            payload = CUSTOM_PRICELISTS[trigger]
            files = []
            for image_path in payload.get("images", []):
                path = Path(image_path)
                if path.exists():
                    files.append(discord.File(str(path)))

            await message.channel.send(content=payload.get("text") or None, files=files if files else None)
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
