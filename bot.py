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

BASE_DIR = Path("data_store_bot")
BASE_DIR.mkdir(exist_ok=True)

VIP_FILE = BASE_DIR / "vip_sessions.json"
PRODUCT_FILE = BASE_DIR / "cashier_products.json"
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


def product_display_name(product: dict) -> str:
    category = product.get("category", "Umum")
    return f"[{category}] {product['name']}"


def build_product_choices(current: str):
    current_key = normalize_key(current)
    result = []
    for product in sorted(PRODUCTS, key=lambda x: (normalize_key(x.get("category", "Umum")), normalize_key(x["name"]))):
        haystack = f"{product.get('category', 'Umum')} {product['name']}"
        if not current_key or current_key in normalize_key(haystack):
            result.append(
                app_commands.Choice(
                    name=product_display_name(product)[:100],
                    value=product["name"][:100]
                )
            )
        if len(result) >= 25:
            break
    return result


async def product_autocomplete(interaction: discord.Interaction, current: str):
    return build_product_choices(current)


# =========================================================
# STORAGE
# =========================================================
PRODUCTS = load_json(PRODUCT_FILE, [])
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


def migrate_products():
    changed = False
    for product in PRODUCTS:
        if "id" not in product or not product["id"]:
            product["id"] = str(uuid.uuid4())
            changed = True
        if "category" not in product or not str(product.get("category", "")).strip():
            product["category"] = "Umum"
            changed = True
        if "active" not in product:
            product["active"] = True
            changed = True
    if changed:
        save_products()


migrate_products()


def get_active_products() -> list[dict]:
    return [p for p in PRODUCTS if p.get("active", True)]


def get_all_categories() -> list[str]:
    categories = {str(p.get("category", "Umum")).strip() or "Umum" for p in get_active_products()}
    return sorted(categories, key=normalize_key)


def get_products_by_category(category: str, keyword: str = "") -> list[dict]:
    category_key = normalize_key(category)
    keyword_key = normalize_key(keyword)
    products = []
    for product in get_active_products():
        if normalize_key(str(product.get("category", "Umum"))) != category_key:
            continue
        if keyword_key and keyword_key not in normalize_key(product["name"]):
            continue
        products.append(product)
    products.sort(key=lambda x: normalize_key(x["name"]))
    return products


def find_product_by_name(name: str):
    key = normalize_key(name)
    for product in PRODUCTS:
        if normalize_key(product["name"]) == key:
            return product
    return None


def add_product_to_cart(session: dict, product: dict) -> bool:
    for item in session["items"]:
        if item.get("product_id") == product["id"]:
            return False

    rate = int(session["rate"])
    robux = int(product["robux"])
    price = calculate_price(robux, rate)
    session["items"].append({
        "product_id": product["id"],
        "name": product["name"],
        "category": product.get("category", "Umum"),
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
        "**Kasir:**\n"
        "`/kasir` - Mulai kasir dengan rate harian\n"
        "`/produk_tambah` - Tambah produk katalog kasir\n"
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

        for item in (
            self.waktu,
            self.durasi_waktu,
            self.harga,
            self.ps,
            self.server
        ):
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

        self.roblox = TextInput(
            label="Username Roblox",
            placeholder="Contoh : KennMyst"
        )
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
                options.append(
                    discord.SelectOption(
                        label=f"{idx}. {data['roblox']}"[:100],
                        value=data["id"]
                    )
                )

        if not options:
            options.append(discord.SelectOption(label="Tidak ada slot", value="none"))

        super().__init__(
            placeholder="Pilih slot kamu",
            options=options
        )

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

    @discord.ui.button(label="- Hapus slot saya", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: Button):
        session = get_session(self.message_id)

        if not any(x["user_id"] == interaction.user.id for x in session["list"]):
            await interaction.response.send_message("Kamu belum punya slot.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Pilih slot kamu:",
            view=DeleteView(self.message_id, interaction.user.id),
            ephemeral=True
        )

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

    vip_list = session["list"]
    index = nomor - 1

    if index < 0 or index >= len(vip_list):
        await interaction.response.send_message("Nomor slot tidak valid.", ephemeral=True)
        return

    vip_list.pop(index)
    save_vip_sessions()

    msg = await interaction.channel.fetch_message(mid)
    await msg.edit(embed=make_vip_embed(mid), view=VipView(mid))

    await interaction.response.send_message("Slot berhasil dihapus.", ephemeral=True)


@bot.tree.command(name="editslot", description="Admin: edit slot VIP")
@app_commands.describe(
    message_id="ID pesan VIP",
    nomor="Nomor slot",
    roblox="Username Roblox",
    member="User Discord"
)
async def slash_edit(
    interaction: discord.Interaction,
    message_id: str,
    nomor: int,
    roblox: str,
    member: discord.Member
):
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

    vip_list = session["list"]

    if nomor < 1 or nomor > MAX_SLOT:
        await interaction.response.send_message("Nomor slot tidak valid.", ephemeral=True)
        return

    index = nomor - 1

    while len(vip_list) <= index:
        vip_list.append({
            "id": str(uuid.uuid4()),
            "user_id": 0,
            "mention": "-",
            "roblox": "-",
            "paid": False
        })

    vip_list[index] = {
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
@app_commands.describe(
    message_id="ID pesan VIP",
    slots="Contoh: 1,2,10 atau 1-5",
    status="Status pembayaran"
)
@app_commands.choices(status=[
    app_commands.Choice(name="paid", value="paid"),
    app_commands.Choice(name="unpaid", value="unpaid")
])
async def slash_paid(
    interaction: discord.Interaction,
    message_id: str,
    slots: str,
    status: app_commands.Choice[str]
):
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

    vip_list = session["list"]
    updated = []
    not_found = []

    for n in numbers:
        idx = n - 1
        if 0 <= idx < len(vip_list):
            vip_list[idx]["paid"] = status.value == "paid"
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
        options = []
        for item_key, item_name in BUYER_DATA[game_key]["items"].items():
            options.append(discord.SelectOption(label=item_name, value=f"{game_key}|{item_key}"))
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

        files = []
        for name in sorted(folder.iterdir()):
            if name.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                files.append(discord.File(str(name)))

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
# KASIR
# =========================================================
def build_kasir_preview_embed(session: dict) -> discord.Embed:
    embed = discord.Embed(title="Preview Kasir", color=COLOR)
    embed.add_field(name="Customer", value=session["customer"], inline=False)
    embed.add_field(name="Rate Hari Ini", value=str(session["rate"]), inline=False)
    embed.add_field(name="Tanggal", value=format_wib(), inline=False)

    mode = session.get("ui_mode", "preview")
    category = session.get("selected_category") or "-"
    keyword = session.get("search_keyword") or "-"

    if session["items"]:
        lines = []
        total = 0
        for i, item in enumerate(session["items"], start=1):
            qty_text = f" x{item['qty']}" if item["qty"] > 1 else ""
            subtotal = item["price"] * item["qty"]
            total += subtotal
            category_text = item.get("category", "Umum")
            lines.append(f"{i}. [{category_text}] {item['name']} ({item['robux']}){qty_text} : {format_rupiah(subtotal)}")
        embed.add_field(name="List Pembelian", value="\n".join(lines), inline=False)
        embed.add_field(name="TOTAL", value=f"**{format_rupiah(total)}**", inline=False)
    else:
        embed.add_field(name="List Pembelian", value="Belum ada item.", inline=False)

    if mode == "category":
        embed.add_field(
            name="Mode Pilih Kategori",
            value="Pilih kategori dulu. Setelah itu kamu bisa pilih banyak produk sekaligus.",
            inline=False
        )
    elif mode == "product":
        extra = [f"Kategori aktif: **{category}**"]
        if session.get("search_keyword"):
            extra.append(f"Filter nama: **{keyword}**")
        filtered = get_products_by_category(session.get("selected_category", ""), session.get("search_keyword", ""))
        if len(filtered) > 25:
            extra.append(f"Hasil cocok: **{len(filtered)}** produk. Yang tampil hanya 25 pertama, gunakan search agar lebih spesifik.")
        elif filtered:
            extra.append(f"Hasil cocok: **{len(filtered)}** produk.")
        else:
            extra.append("Tidak ada produk yang cocok. Coba search lain atau back ke kategori.")
        embed.add_field(name="Mode Pilih Produk", value="\n".join(extra), inline=False)
    elif mode == "edit_qty":
        embed.add_field(name="Mode Edit Qty", value="Pilih item dari daftar di bawah lalu isi jumlah baru. Semua item default qty = 1.", inline=False)
    elif mode == "remove_item":
        embed.add_field(name="Mode Hapus Item", value="Pilih item yang ingin dihapus dari keranjang.", inline=False)

    embed.set_footer(text="Semua proses kasir hanya terlihat admin sampai invoice dikirim")
    return embed


def build_kasir_invoice_embed(session: dict) -> discord.Embed:
    embed = discord.Embed(title="Fraktur Online", color=COLOR)
    embed.add_field(name="Customer", value=session["customer"], inline=False)
    embed.add_field(name="Rate Hari Ini", value=str(session["rate"]), inline=False)
    embed.add_field(name="Tanggal", value=format_wib(), inline=False)

    lines = []
    total = 0
    for i, item in enumerate(session["items"], start=1):
        qty_text = f" x{item['qty']}" if item["qty"] > 1 else ""
        subtotal = item["price"] * item["qty"]
        total += subtotal
        category_text = item.get("category", "Umum")
        lines.append(f"{i}. [{category_text}] {item['name']} ({item['robux']}){qty_text} : {format_rupiah(subtotal)}")

    embed.add_field(name="**List Pembelian**", value="\n".join(lines), inline=False)
    embed.add_field(name="**TOTAL**", value=f"**{format_rupiah(total)}**", inline=False)
    embed.timestamp = now_wib()
    return embed


def build_kasir_view(session_id: str) -> View:
    session = kasir_sessions.get(session_id)
    if not session:
        return View()

    mode = session.get("ui_mode", "preview")
    if mode == "category":
        return KasirCategoryView(session_id)
    if mode == "product":
        return KasirProductView(session_id)
    if mode == "edit_qty":
        return EditQtyView(session_id)
    if mode == "remove_item":
        return RemoveItemView(session_id)
    return KasirView(session_id)


class ProductSearchModal(Modal):
    def __init__(self, session_id: str):
        super().__init__(title="Cari Produk")
        self.session_id = session_id
        session = kasir_sessions.get(session_id, {})
        self.keyword = TextInput(
            label="Nama produk",
            placeholder="Ketik sebagian nama produk",
            default=session.get("search_keyword", ""),
            required=False,
        )
        self.add_item(self.keyword)

    async def on_submit(self, interaction: discord.Interaction):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        session["search_keyword"] = self.keyword.value.strip()
        session["ui_mode"] = "product"
        await interaction.response.edit_message(
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class EditQtyModal(Modal):
    def __init__(self, session_id: str, product_id: str):
        session = kasir_sessions.get(session_id, {})
        item = get_cart_item_by_product_id(session, product_id)
        title = f"Edit Qty {item['name'][:30]}" if item else "Edit Qty"
        super().__init__(title=title)
        self.session_id = session_id
        self.product_id = product_id
        default_qty = str(item.get("qty", 1)) if item else "1"
        self.qty = TextInput(label="Jumlah item", placeholder="Contoh: 2", default=default_qty)
        self.add_item(self.qty)

    async def on_submit(self, interaction: discord.Interaction):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        item = get_cart_item_by_product_id(session, self.product_id)
        if not item:
            await interaction.response.send_message("Item tidak ditemukan di keranjang.", ephemeral=True)
            return

        try:
            qty = int(self.qty.value)
            if qty <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Jumlah harus angka lebih dari 0.", ephemeral=True)
            return

        item["qty"] = qty
        session["ui_mode"] = "preview"
        await interaction.response.edit_message(
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class KasirCategorySelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        categories = get_all_categories()
        options = [
            discord.SelectOption(label=category[:100], value=category[:100])
            for category in categories[:25]
        ]

        if not options:
            options.append(discord.SelectOption(label="Belum ada kategori", value="none"))

        super().__init__(
            placeholder="Pilih kategori",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada kategori produk.", ephemeral=True)
            return

        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        session["selected_category"] = self.values[0]
        session["search_keyword"] = ""
        session["ui_mode"] = "product"
        await interaction.response.edit_message(
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class KasirCategoryView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=600)
        self.session_id = session_id
        self.add_item(KasirCategorySelect(session_id))

    @discord.ui.button(label="Kembali ke Preview", style=discord.ButtonStyle.secondary)
    async def back_preview(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        session["ui_mode"] = "preview"
        await interaction.response.edit_message(
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class KasirProductMultiSelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        session = kasir_sessions.get(session_id) or {}
        category = session.get("selected_category", "")
        keyword = session.get("search_keyword", "")
        rate = int(session.get("rate", 0))
        products = get_products_by_category(category, keyword)

        options = []
        for product in products[:25]:
            preview_price = calculate_price(int(product["robux"]), rate)
            options.append(
                discord.SelectOption(
                    label=product["name"][:100],
                    description=f"{product['robux']} robux | {format_rupiah(preview_price)}"[:100],
                    value=product["id"]
                )
            )

        if not options:
            options.append(discord.SelectOption(label="Tidak ada produk", value="none"))
            min_values = 1
            max_values = 1
        else:
            min_values = 1
            max_values = min(25, len(options))

        super().__init__(
            placeholder="Pilih satu atau lebih produk",
            min_values=min_values,
            max_values=max_values,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        if self.values[0] == "none":
            await interaction.response.send_message("Tidak ada produk yang bisa dipilih.", ephemeral=True)
            return

        added_count = 0
        duplicate_count = 0
        for product_id in self.values:
            product = next((p for p in PRODUCTS if p["id"] == product_id and p.get("active", True)), None)
            if not product:
                continue
            if add_product_to_cart(session, product):
                added_count += 1
            else:
                duplicate_count += 1

        session["ui_mode"] = "product"

        message = []
        if added_count:
            message.append(f"✅ {added_count} produk ditambahkan ke keranjang.")
        if duplicate_count:
            message.append(f"ℹ️ {duplicate_count} produk sudah ada di keranjang, jadi tidak didobel.")
        if not message:
            message.append("Tidak ada produk baru yang ditambahkan.")

        await interaction.response.edit_message(
            content="\n".join(message),
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class KasirProductView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=600)
        self.session_id = session_id
        self.add_item(KasirProductMultiSelect(session_id))

    @discord.ui.button(label="Cari Produk", style=discord.ButtonStyle.success)
    async def search(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return
        if not session.get("selected_category"):
            await interaction.response.send_message("Pilih kategori dulu.", ephemeral=True)
            return

        await interaction.response.send_modal(ProductSearchModal(self.session_id))

    @discord.ui.button(label="Reset Search", style=discord.ButtonStyle.primary)
    async def reset_search(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        session["search_keyword"] = ""
        session["ui_mode"] = "product"
        await interaction.response.edit_message(
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )

    @discord.ui.button(label="Back ke Kategori", style=discord.ButtonStyle.secondary)
    async def back_category(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        session["ui_mode"] = "category"
        session["search_keyword"] = ""
        await interaction.response.edit_message(
            content=None,
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )

    @discord.ui.button(label="Selesai Pilih Produk", style=discord.ButtonStyle.success)
    async def finish_pick(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        session["ui_mode"] = "preview"
        await interaction.response.edit_message(
            content="✅ Pemilihan produk selesai. Semua item default qty = 1, silakan edit jika perlu.",
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class EditQtySelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        session = kasir_sessions.get(session_id) or {}
        options = []
        for item in session.get("items", [])[:25]:
            options.append(
                discord.SelectOption(
                    label=item["name"][:100],
                    description=f"{item.get('category', 'Umum')} | qty saat ini: {item['qty']}"[:100],
                    value=item["product_id"]
                )
            )

        if not options:
            options.append(discord.SelectOption(label="Belum ada item", value="none"))

        super().__init__(placeholder="Pilih item untuk edit qty", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada item di keranjang.", ephemeral=True)
            return

        await interaction.response.send_modal(EditQtyModal(self.session_id, self.values[0]))


class EditQtyView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=600)
        self.session_id = session_id
        self.add_item(EditQtySelect(session_id))

    @discord.ui.button(label="Kembali ke Preview", style=discord.ButtonStyle.secondary)
    async def back_preview(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        session["ui_mode"] = "preview"
        await interaction.response.edit_message(
            content=None,
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class RemoveItemSelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id
        session = kasir_sessions.get(session_id) or {}
        options = []
        for item in session.get("items", [])[:25]:
            options.append(
                discord.SelectOption(
                    label=item["name"][:100],
                    description=f"{item.get('category', 'Umum')} | qty: {item['qty']}"[:100],
                    value=item["product_id"]
                )
            )

        if not options:
            options.append(discord.SelectOption(label="Belum ada item", value="none"))

        super().__init__(placeholder="Pilih item yang ingin dihapus", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada item di keranjang.", ephemeral=True)
            return

        product_id = self.values[0]
        before = len(session["items"])
        session["items"] = [item for item in session["items"] if item.get("product_id") != product_id]
        after = len(session["items"])
        session["ui_mode"] = "preview"

        if before == after:
            await interaction.response.send_message("Item tidak ditemukan.", ephemeral=True)
            return

        await interaction.response.edit_message(
            content="🗑️ Item berhasil dihapus dari keranjang.",
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class RemoveItemView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=600)
        self.session_id = session_id
        self.add_item(RemoveItemSelect(session_id))

    @discord.ui.button(label="Kembali ke Preview", style=discord.ButtonStyle.secondary)
    async def back_preview(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        session["ui_mode"] = "preview"
        await interaction.response.edit_message(
            content=None,
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )


class KasirView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=600)
        self.session_id = session_id

    @discord.ui.button(label="Tambah Produk", style=discord.ButtonStyle.success)
    async def add_product(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        if not get_active_products():
            await interaction.response.send_message("Belum ada katalog produk aktif. Gunakan /produk_tambah dulu.", ephemeral=True)
            return

        session["ui_mode"] = "category"
        await interaction.response.edit_message(
            content=None,
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )

    @discord.ui.button(label="Edit Qty", style=discord.ButtonStyle.primary)
    async def edit_qty(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session or not session["items"]:
            await interaction.response.send_message("Belum ada item untuk diedit.", ephemeral=True)
            return

        session["ui_mode"] = "edit_qty"
        await interaction.response.edit_message(
            content=None,
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )

    @discord.ui.button(label="Hapus Item", style=discord.ButtonStyle.danger)
    async def remove_item(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session or not session["items"]:
            await interaction.response.send_message("Belum ada item untuk dihapus.", ephemeral=True)
            return

        session["ui_mode"] = "remove_item"
        await interaction.response.edit_message(
            content=None,
            embed=build_kasir_preview_embed(session),
            view=build_kasir_view(self.session_id)
        )

    @discord.ui.button(label="Selesai / Kirim Invoice", style=discord.ButtonStyle.success)
    async def finish(self, interaction: discord.Interaction, button: Button):
        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        if not session["items"]:
            await interaction.response.send_message("Belum ada item yang dipilih.", ephemeral=True)
            return

        await interaction.channel.send(embed=build_kasir_invoice_embed(session))
        kasir_sessions.pop(self.session_id, None)
        await interaction.response.edit_message(content="✅ Invoice berhasil dikirim ke chat.", embed=None, view=None)

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        kasir_sessions.pop(self.session_id, None)
        await interaction.response.edit_message(content="❌ Sesi kasir dibatalkan.", embed=None, view=None)


class StartKasirModal(Modal):
    def __init__(self):
        super().__init__(title="Mulai Kasir")
        self.customer = TextInput(label="Nama Customer", placeholder="Contoh: ABC")
        self.rate = TextInput(label="Rate hari ini", placeholder="Contoh: 90")
        self.add_item(self.customer)
        self.add_item(self.rate)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ Hanya admin yang bisa memakai kasir.", ephemeral=True)
            return

        if not get_active_products():
            await interaction.response.send_message("Belum ada katalog produk aktif. Tambahkan dulu dengan /produk_tambah", ephemeral=True)
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
            "customer": self.customer.value.strip() or "Customer",
            "rate": rate,
            "items": [],
            "ui_mode": "preview",
            "selected_category": None,
            "search_keyword": "",
        }

        await interaction.response.send_message(
            embed=build_kasir_preview_embed(kasir_sessions[session_id]),
            view=build_kasir_view(session_id),
            ephemeral=True
        )


@bot.tree.command(name="kasir", description="Mulai sesi kasir dan isi rate harian")
async def kasir(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin yang bisa memakai kasir.", ephemeral=True)
        return

    await interaction.response.send_modal(StartKasirModal())


# =========================================================
# PRODUK KASIR
# =========================================================
@bot.tree.command(name="produk_tambah", description="Tambah produk ke katalog kasir")
@app_commands.describe(nama="Nama produk", kategori="Kategori produk", robux="Jumlah robux")
async def produk_tambah(interaction: discord.Interaction, nama: str, kategori: str, robux: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    nama = nama.strip()
    kategori = kategori.strip() or "Umum"

    if find_product_by_name(nama):
        await interaction.response.send_message("Produk dengan nama itu sudah ada.", ephemeral=True)
        return

    if robux <= 0:
        await interaction.response.send_message("Jumlah robux harus lebih dari 0.", ephemeral=True)
        return

    PRODUCTS.append({
        "id": str(uuid.uuid4()),
        "name": nama,
        "category": kategori,
        "robux": robux,
        "active": True,
    })
    save_products()
    await interaction.response.send_message(
        f"✅ Produk **{nama}** berhasil ditambahkan ke kategori **{kategori}**.",
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
@app_commands.autocomplete(nama=product_autocomplete)
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

    if nama_baru:
        nama_baru = nama_baru.strip()
        existing = find_product_by_name(nama_baru)
        if existing and existing is not product:
            await interaction.response.send_message("Nama produk baru sudah dipakai produk lain.", ephemeral=True)
            return
        product["name"] = nama_baru

    if kategori is not None:
        product["category"] = kategori.strip() or "Umum"

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

    PRODUCTS.remove(product)
    save_products()
    await interaction.response.send_message(
        f"🗑️ Produk **{product['name']}** dihapus dari kategori **{product.get('category', 'Umum')}**.",
        ephemeral=True
    )


@bot.tree.command(name="produk_list", description="Lihat katalog produk kasir")
@app_commands.describe(kategori="Filter kategori (opsional)")
async def produk_list(interaction: discord.Interaction, kategori: Optional[str] = None):
    if not PRODUCTS:
        await interaction.response.send_message("Belum ada katalog produk.", ephemeral=True)
        return

    if kategori:
        filtered = [
            p for p in PRODUCTS
            if normalize_key(str(p.get("category", "Umum"))) == normalize_key(kategori)
        ]
    else:
        filtered = sorted(PRODUCTS, key=lambda x: (normalize_key(x.get("category", "Umum")), normalize_key(x["name"])))

    if not filtered:
        await interaction.response.send_message("Tidak ada produk pada kategori itu.", ephemeral=True)
        return

    lines = []
    for i, product in enumerate(filtered, start=1):
        status = "aktif" if product.get("active", True) else "nonaktif"
        lines.append(
            f"{i}. [{product.get('category', 'Umum')}] {product['name']} ({product['robux']} robux) - {status}"
        )

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

            await message.channel.send(
                content=payload.get("text") or None,
                files=files if files else None
            )
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
