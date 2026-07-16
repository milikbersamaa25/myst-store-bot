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

# Railway Volume.
# Kalau Railway punya /data, semua penyimpanan dibaca dari /data/data_store_bot.
RAILWAY_VOLUME = Path("/data")
if RAILWAY_VOLUME.exists():
    BASE_DIR = RAILWAY_VOLUME / "data_store_bot"
else:
    BASE_DIR = Path(__file__).resolve().parent / "data_store_bot"

BASE_DIR.mkdir(parents=True, exist_ok=True)

VIP_FILE = BASE_DIR / "vip_sessions.json"
PRODUCT_FILE = BASE_DIR / "cashier_products.json"
CATEGORY_FILE = BASE_DIR / "cashier_categories.json"
CUSTOM_PRICELIST_FILE = BASE_DIR / "custom_pricelists.json"
CUSTOM_EMBED_FILE = BASE_DIR / "custom_embeds.json"
GAME_PRICELIST_FILE = BASE_DIR / "game_pricelists.json"

CUSTOM_PRICELIST_DIR = BASE_DIR / "pricelist_media"
CUSTOM_PRICELIST_DIR.mkdir(exist_ok=True)

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


# =========================================================
# STORAGE
# =========================================================
PRODUCTS = load_json(PRODUCT_FILE, [])
CATEGORIES = load_json(CATEGORY_FILE, [])
CUSTOM_PRICELISTS = load_json(CUSTOM_PRICELIST_FILE, {})
CUSTOM_EMBEDS = load_json(CUSTOM_EMBED_FILE, {})
GAME_PRICELISTS = load_json(GAME_PRICELIST_FILE, {})
vip_sessions = load_json(VIP_FILE, {})

# Kategori Lainnya wajib selalu ada.
if not any(normalize_key(cat) == "lainnya" for cat in CATEGORIES):
    CATEGORIES.append("Lainnya")

# Kompatibilitas data lama:
# Produk lama yang belum punya category tetap dibuat bisa muncul di kasir.
for product in PRODUCTS:
    if "category" not in product or not product.get("category"):
        product["category"] = "Robux"

    if not any(normalize_key(cat) == normalize_key(product.get("category", "")) for cat in CATEGORIES):
        CATEGORIES.append(product["category"])


def save_products():
    save_json(PRODUCT_FILE, PRODUCTS)


def save_categories():
    save_json(CATEGORY_FILE, CATEGORIES)


def save_pricelists():
    save_json(CUSTOM_PRICELIST_FILE, CUSTOM_PRICELISTS)


def save_custom_embeds():
    save_json(CUSTOM_EMBED_FILE, CUSTOM_EMBEDS)


def save_game_pricelists():
    save_json(GAME_PRICELIST_FILE, GAME_PRICELISTS)


def save_vip_sessions():
    save_json(VIP_FILE, vip_sessions)


def get_session(message_id: int | str):
    key = str(message_id)
    if key not in vip_sessions:
        vip_sessions[key] = {"info": {}, "list": []}
        save_vip_sessions()
    return vip_sessions[key]


def find_product_by_name(name: str):
    key = normalize_key(name)
    for product in PRODUCTS:
        if normalize_key(product.get("name", "")) == key:
            return product
    return None


def find_product_by_name_and_category(name: str, category: str):
    name_key = normalize_key(name)
    category_key = normalize_key(category)

    for product in PRODUCTS:
        if (
            normalize_key(product.get("name", "")) == name_key
            and normalize_key(product.get("category", "")) == category_key
        ):
            return product

    return None


def category_exists(name: str) -> bool:
    key = normalize_key(name)
    return any(normalize_key(cat) == key for cat in CATEGORIES)


def get_category_name(name: str) -> Optional[str]:
    key = normalize_key(name)
    for cat in CATEGORIES:
        if normalize_key(cat) == key:
            return cat
    return None


def is_lainnya_category(category: str) -> bool:
    return normalize_key(category) == "lainnya"


def is_lainnya_product(product: dict) -> bool:
    return is_lainnya_category(str(product.get("category", "")))


def get_invoice_item_info(item: dict):
    if is_lainnya_product(item):
        return "Lainnya"
    return item.get("robux", "-")


def get_product_preview_description(product: dict, rate: int = 0) -> str:
    category = product.get("category", "-")

    if is_lainnya_product(product):
        return f"{category} | {format_rupiah(int(product.get('price', 0)))}"[:100]

    robux = int(product.get("robux", 0))
    preview_price = calculate_price(robux, rate) if rate else 0
    if rate:
        return f"{category} | {robux} robux | {format_rupiah(preview_price)}"[:100]
    return f"{category} | {robux} robux"[:100]


def build_product_choices(current: str):
    current_key = normalize_key(current)
    result = []

    for product in PRODUCTS:
        label = f"[{product.get('category', '-')}] {product.get('name', '-')}"
        if not current_key or current_key in normalize_key(label):
            result.append(
                app_commands.Choice(
                    name=label[:100],
                    value=product["name"][:100]
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

    for cat in CATEGORIES:
        if not current_key or current_key in normalize_key(cat):
            result.append(app_commands.Choice(name=cat[:100], value=cat[:100]))
        if len(result) >= 25:
            break

    return result


async def category_autocomplete(interaction: discord.Interaction, current: str):
    return build_category_choices(current)


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
        "`/kasir` - Mulai kasir dengan nama customer dan rate harian\n"
        "`/kategori_tambah` - Tambah kategori produk robux\n"
        "`/kategori_hapus` - Hapus kategori produk\n"
        "`/kategori_list` - Lihat daftar kategori\n"
        "`/produk_tambah` - Tambah produk ke katalog kasir\n"
        "`/produk_edit` - Edit produk katalog kasir\n"
        "`/produk_hapus` - Hapus produk katalog kasir\n"
        "`/produk_list` - Lihat katalog produk kasir\n\n"
        "**Command ! custom:**\n"
        "`/pricelistedit` - Tambah/edit/hapus command ! custom\n\n"
        "**Alur Kasir:**\n"
        "`/kasir` → isi customer & rate → Tambah Produk → pilih kategori → pilih produk.\n"
        "Jika produk tidak muncul di dropdown, gunakan tombol **Cari Produk**.\n\n"
        "**Catatan:**\n"
        "Kategori yang dibuat lewat `/kategori_tambah` memakai robux dan dihitung dari `robux x rate`.\n"
        "Kategori default **Lainnya** memakai harga rupiah langsung dan tidak dihitung rate.\n"
        "Rate hanya tampil di preview admin, tidak tampil di Fraktur Online."
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =========================================================
# CUSTOM EMBED MAKER
# =========================================================
def normalize_embed_name(name: str) -> str:
    return re.sub(r"\s+", "_", name.strip().lower())


def parse_embed_color(color_text: str) -> int:
    color_text = color_text.strip()

    if not color_text:
        return COLOR

    if color_text.startswith("#"):
        color_text = color_text[1:]

    return int(color_text, 16)


def build_embed_buttons(interaction: discord.Interaction, buttons_text: str) -> Optional[View]:
    buttons_text = buttons_text.strip()

    if not buttons_text:
        return None

    raw_buttons = [item.strip() for item in buttons_text.split(",") if item.strip()]

    if len(raw_buttons) > 5:
        raise ValueError("Maksimal 5 button dalam 1 embed.")

    view = View(timeout=None)

    for raw_button in raw_buttons:
        if "|" not in raw_button:
            raise ValueError(
                "Format button salah. Gunakan format: Nama Button|ID Channel"
            )

        label, channel_raw = raw_button.split("|", 1)
        label = label.strip()

        channel_id = (
            channel_raw
            .replace("<#", "")
            .replace(">", "")
            .strip()
        )

        if not label:
            raise ValueError("Nama button tidak boleh kosong.")

        if len(label) > 80:
            raise ValueError("Nama button maksimal 80 karakter.")

        if not channel_id.isdigit():
            raise ValueError("Tujuan button harus berupa mention channel atau ID channel.")

        channel_url = f"https://discord.com/channels/{interaction.guild.id}/{channel_id}"

        view.add_item(
            Button(
                label=label,
                style=discord.ButtonStyle.link,
                url=channel_url
            )
        )

    return view


def build_custom_embed(data: dict) -> discord.Embed:
    title = data.get("title", "").strip()
    body = data.get("body", "").strip()
    color = int(data.get("color", COLOR))

    embed = discord.Embed(
        color=color
    )

    image_url = data.get("image_url")
    image_position = data.get("image_position", "bawah")

    parts = body.split("[section]")

    intro = parts[0].strip()

    if intro:
        embed.description = f"# {title}\n\n{intro}"
    else:
        embed.description = f"# {title}"

    for section in parts[1:]:
        section = section.strip()

        if not section:
            continue

        lines = section.splitlines()

        if not lines:
            continue

        field_title = lines[0].strip()

        field_content = "\n".join(lines[1:]).strip()

        if not field_content:
            field_content = "\u200b"

        embed.add_field(
            name=field_title,
            value=field_content,
            inline=False
        )

    if image_url and image_position == "bawah":
        embed.set_image(url=image_url)

    return embed


def build_top_image_embed(data: dict) -> Optional[discord.Embed]:
    image_url = data.get("image_url")
    image_position = data.get("image_position", "bawah")
    color = int(data.get("color", COLOR))

    if image_url and image_position == "atas":
        image_embed = discord.Embed(color=color)
        image_embed.set_image(url=image_url)
        return image_embed

    return None


class CustomEmbedModal(Modal):
    def __init__(
        self,
        mode: str,
        embed_key: str,
        target_channel_id: int,
        image_url: Optional[str] = None,
        image_position: str = "bawah",
        old_data: Optional[dict] = None
    ):
        super().__init__(title="Buat/Edit Embed Custom")

        self.mode = mode
        self.embed_key = embed_key
        self.target_channel_id = target_channel_id
        self.image_url = image_url
        self.image_position = image_position
        self.old_data = old_data or {}

        self.judul = TextInput(
            label="Judul Embed",
            placeholder="Contoh: INFORMASI ORDER",
            default=self.old_data.get("title", ""),
            required=True,
            max_length=256
        )

        self.isi = TextInput(
            label="Isi Embed",
            placeholder="Bisa pakai emoji, enter, markdown, ##, ###, dll.",
            default=self.old_data.get("body", ""),
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000
        )

        self.buttons = TextInput(
            label="Button",
            placeholder="Contoh: Order Ticket|123456789, Vouch|987654321",
            default=self.old_data.get("buttons", ""),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000
        )

        self.warna = TextInput(
            label="Warna Embed",
            placeholder="Default tosca. Samarkan garis kiri: #2B2D31",
            default=self.old_data.get("color_text", ""),
            required=False,
            max_length=7
        )

        self.add_item(self.judul)
        self.add_item(self.isi)
        self.add_item(self.buttons)
        self.add_item(self.warna)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ Hanya admin yang bisa membuat/edit embed.",
                ephemeral=True
            )
            return

        try:
            warna = parse_embed_color(self.warna.value)
        except ValueError:
            await interaction.response.send_message(
                "❌ Format warna salah. Gunakan contoh: `#00F8FF` atau `#2B2D31`.",
                ephemeral=True
            )
            return

        try:
            view = build_embed_buttons(interaction, self.buttons.value)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        final_image_url = self.image_url
        final_image_position = self.image_position

        if self.mode == "edit":
            if final_image_url is None:
                final_image_url = self.old_data.get("image_url")
                final_image_position = self.old_data.get("image_position", "bawah")

        data = {
            "title": self.judul.value.strip(),
            "body": self.isi.value.strip(),
            "buttons": self.buttons.value.strip(),
            "color": warna,
            "color_text": self.warna.value.strip(),
            "image_url": final_image_url,
            "image_position": final_image_position,
            "channel_id": self.target_channel_id
        }

        embed = build_custom_embed(data)
        top_image_embed = build_top_image_embed(data)

        if self.mode == "buat":
            target_channel = interaction.guild.get_channel(self.target_channel_id)

            if not target_channel:
                await interaction.response.send_message(
                    "❌ Channel tujuan tidak ditemukan.",
                    ephemeral=True
                )
                return

            if top_image_embed:
                msg = await target_channel.send(
                    embeds=[top_image_embed, embed],
                    view=view
                )
            else:
                msg = await target_channel.send(
                    embed=embed,
                    view=view
                )

            data["message_id"] = msg.id
            CUSTOM_EMBEDS[self.embed_key] = data
            save_custom_embeds()

            await interaction.response.send_message(
                f"✅ Embed **{self.embed_key}** berhasil dibuat di {target_channel.mention}.",
                ephemeral=True
            )
            return

        if self.mode == "edit":
            old_saved = CUSTOM_EMBEDS.get(self.embed_key)

            if not old_saved:
                await interaction.response.send_message(
                    "❌ Data embed tidak ditemukan.",
                    ephemeral=True
                )
                return

            channel = interaction.guild.get_channel(int(old_saved["channel_id"]))

            if not channel:
                await interaction.response.send_message(
                    "❌ Channel embed lama tidak ditemukan.",
                    ephemeral=True
                )
                return

            try:
                msg = await channel.fetch_message(int(old_saved["message_id"]))
            except discord.NotFound:
                await interaction.response.send_message(
                    "❌ Pesan embed lama tidak ditemukan. Mungkin sudah terhapus.",
                    ephemeral=True
                )
                return

            if top_image_embed:
                await msg.edit(
                    embeds=[top_image_embed, embed],
                    view=view
                )
            else:
                await msg.edit(
                    embeds=[embed],
                    view=view
                )

            data["message_id"] = old_saved["message_id"]
            data["channel_id"] = old_saved["channel_id"]

            CUSTOM_EMBEDS[self.embed_key] = data
            save_custom_embeds()

            await interaction.response.send_message(
                f"✅ Embed **{self.embed_key}** berhasil diedit.",
                ephemeral=True
            )


@bot.tree.command(name="embed_buat", description="Admin: buat embed custom baru")
@app_commands.describe(
    nama_embed="Nama unik embed, contoh: pricelist_robux",
    channel_tujuan="Channel tempat embed dikirim",
    gambar="Opsional: upload JPG/PNG/GIF/WEBP",
    posisi_gambar="Letak gambar"
)
@app_commands.choices(posisi_gambar=[
    app_commands.Choice(name="Atas", value="atas"),
    app_commands.Choice(name="Bawah", value="bawah"),
])
async def embed_buat(
    interaction: discord.Interaction,
    nama_embed: str,
    channel_tujuan: discord.TextChannel,
    gambar: Optional[discord.Attachment] = None,
    posisi_gambar: Optional[app_commands.Choice[str]] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin yang bisa memakai command ini.",
            ephemeral=True
        )
        return

    embed_key = normalize_embed_name(nama_embed)

    if embed_key in CUSTOM_EMBEDS:
        await interaction.response.send_message(
            f"❌ Nama embed **{embed_key}** sudah ada. Gunakan `/embed_edit` untuk mengubahnya.",
            ephemeral=True
        )
        return

    image_url = None
    image_position = posisi_gambar.value if posisi_gambar else "bawah"

    if gambar:
        allowed_ext = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        filename = gambar.filename.lower()

        if not any(filename.endswith(ext) for ext in allowed_ext):
            await interaction.response.send_message(
                "❌ Format gambar harus JPG, PNG, GIF, atau WEBP.",
                ephemeral=True
            )
            return

        image_url = gambar.url

    await interaction.response.send_modal(
        CustomEmbedModal(
            mode="buat",
            embed_key=embed_key,
            target_channel_id=channel_tujuan.id,
            image_url=image_url,
            image_position=image_position
        )
    )


@bot.tree.command(name="embed_edit", description="Admin: edit embed custom yang sudah dibuat")
@app_commands.describe(
    nama_embed="Nama embed yang ingin diedit",
    gambar="Opsional: upload gambar baru. Kosongkan jika tidak ingin mengganti gambar.",
    posisi_gambar="Letak gambar baru"
)
@app_commands.choices(posisi_gambar=[
    app_commands.Choice(name="Atas", value="atas"),
    app_commands.Choice(name="Bawah", value="bawah"),
])
async def embed_edit(
    interaction: discord.Interaction,
    nama_embed: str,
    gambar: Optional[discord.Attachment] = None,
    posisi_gambar: Optional[app_commands.Choice[str]] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin yang bisa memakai command ini.",
            ephemeral=True
        )
        return

    embed_key = normalize_embed_name(nama_embed)

    old_data = CUSTOM_EMBEDS.get(embed_key)

    if not old_data:
        await interaction.response.send_message(
            f"❌ Embed **{embed_key}** tidak ditemukan.",
            ephemeral=True
        )
        return

    image_url = None
    image_position = posisi_gambar.value if posisi_gambar else old_data.get("image_position", "bawah")

    if gambar:
        allowed_ext = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        filename = gambar.filename.lower()

        if not any(filename.endswith(ext) for ext in allowed_ext):
            await interaction.response.send_message(
                "❌ Format gambar harus JPG, PNG, GIF, atau WEBP.",
                ephemeral=True
            )
            return

        image_url = gambar.url

    await interaction.response.send_modal(
        CustomEmbedModal(
            mode="edit",
            embed_key=embed_key,
            target_channel_id=int(old_data["channel_id"]),
            image_url=image_url,
            image_position=image_position,
            old_data=old_data
        )
    )


@bot.tree.command(name="embed_hapus", description="Admin: hapus embed custom")
@app_commands.describe(
    nama_embed="Nama embed yang ingin dihapus"
)
async def embed_hapus(
    interaction: discord.Interaction,
    nama_embed: str
):
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin yang bisa memakai command ini.",
            ephemeral=True
        )
        return

    embed_key = normalize_embed_name(nama_embed)
    data = CUSTOM_EMBEDS.get(embed_key)

    if not data:
        await interaction.response.send_message(
            f"❌ Embed **{embed_key}** tidak ditemukan.",
            ephemeral=True
        )
        return

    channel = interaction.guild.get_channel(int(data["channel_id"]))

    if channel:
        try:
            msg = await channel.fetch_message(int(data["message_id"]))
            await msg.delete()
        except discord.NotFound:
            pass

    CUSTOM_EMBEDS.pop(embed_key, None)
    save_custom_embeds()

    await interaction.response.send_message(
        f"✅ Embed **{embed_key}** berhasil dihapus.",
        ephemeral=True
    )


@bot.tree.command(name="embed_list", description="Admin: lihat daftar embed custom")
async def embed_list(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin yang bisa memakai command ini.",
            ephemeral=True
        )
        return

    if not CUSTOM_EMBEDS:
        await interaction.response.send_message(
            "Belum ada embed custom yang tersimpan.",
            ephemeral=True
        )
        return

    lines = []
    for key, data in CUSTOM_EMBEDS.items():
        channel_id = data.get("channel_id")
        message_id = data.get("message_id")
        lines.append(f"• **{key}** → <#{channel_id}> | `{message_id}`")

    await interaction.response.send_message(
        "\n".join(lines),
        ephemeral=True
    )


@bot.tree.command(
    name="embed_kirim_ulang",
    description="Admin: kirim ulang embed yang sudah tersimpan"
)
@app_commands.describe(
    nama_embed="Nama embed yang ingin dikirim ulang",
    channel_tujuan="Channel tujuan pengiriman"
)
async def embed_kirim_ulang(
    interaction: discord.Interaction,
    nama_embed: str,
    channel_tujuan: discord.TextChannel
):
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin yang bisa memakai command ini.",
            ephemeral=True
        )
        return

    embed_key = normalize_embed_name(nama_embed)

    data = CUSTOM_EMBEDS.get(embed_key)

    if not data:
        await interaction.response.send_message(
            f"❌ Embed **{embed_key}** tidak ditemukan.",
            ephemeral=True
        )
        return

    try:
        embed = build_custom_embed(data)
        top_image_embed = build_top_image_embed(data)
        view = build_embed_buttons(
            interaction,
            data.get("buttons", "")
        )

        if top_image_embed:
            msg = await channel_tujuan.send(
                embeds=[top_image_embed, embed],
                view=view
            )
        else:
            msg = await channel_tujuan.send(
                embed=embed,
                view=view
            )

        await interaction.response.send_message(
            f"✅ Embed **{embed_key}** berhasil dikirim ulang ke {channel_tujuan.mention}.",
            ephemeral=True
        )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ Gagal mengirim ulang embed.\n{e}",
            ephemeral=True
        )


# =========================================================
# GAME PRICELIST SYSTEM BY MYST STORE
# =========================================================

class GamePricelistSelect(Select):

    def __init__(self):

        options = []

        for key, data in GAME_PRICELISTS.items():

            options.append(
                discord.SelectOption(
                    label=data.get("name", key)[:100],
                    emoji=data.get("emoji", "🎮"),
                    value=key
                )
            )


        if not options:

            options.append(
                discord.SelectOption(
                    label="Belum ada pricelist",
                    value="none"
                )
            )


        super().__init__(
            placeholder="🎮 Pilih Game Favoritmu",
            options=options[:25],
            custom_id="game_pricelist_select"
        )


    async def callback(
        self,
        interaction: discord.Interaction
    ):

        key = self.values[0]


        if key == "none":

            await interaction.response.send_message(
                "❌ Belum ada pricelist.",
                ephemeral=True
            )

            return


        data = GAME_PRICELISTS.get(key)


        if not data:

            await interaction.response.send_message(
                "❌ Pricelist tidak ditemukan.",
                ephemeral=True
            )

            return


        try:

            channel = interaction.guild.get_channel(
                int(data["channel_id"])
            )


            if not channel:

                await interaction.response.send_message(
                    "❌ Channel pricelist tidak ditemukan.",
                    ephemeral=True
                )

                return


            embeds = []


            for message_id in data.get("message_ids", []):

                msg = await channel.fetch_message(
                    int(message_id)
                )

                embeds.extend(
                    msg.embeds
                )


            if not embeds:

                await interaction.response.send_message(
                    "❌ Embed pricelist kosong.",
                    ephemeral=True
                )

                return


            await interaction.response.send_message(
                embeds=embeds[:10],
                ephemeral=True
            )


        except Exception as e:

            await interaction.response.send_message(
                f"❌ Error mengambil pricelist:\n{e}",
                ephemeral=True
            )


class GamePricelistView(View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            GamePricelistSelect()
        )


@bot.tree.command(
    name="listpricelist",
    description="Admin membuat panel pricelist"
)
async def listpricelist(
    interaction: discord.Interaction
):

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin.",
            ephemeral=True
        )
        return


    embed = discord.Embed(
        description=(
            "## <:Gifting_Hero:1527270420921716807> "
            "PRICELIST GIFT IN GAME BY MYST STORE "
            "<:PixelSparkle:1511778680874209402>\n"

            "**⠂⠄⠄⠂⠁⠁⠂⠄⠄⠂⠁⠁⠂⠄⠄⠂ ⠂⠄⠄⠂☆**\n\n"

            "🛒 **Pilih Game Favoritmu!**\n"
            "*Gunakan menu di bawah untuk melihat daftar harga gift in game terbaru.*\n\n"

            "<:playing:1511777875143950487> **__Tersedia :__**\n"

            "⚔️\u2003•\u2003Blade Ball\n"
            "🏡\u2003•\u2003Bloxburg\n"
            "🚗\u2003•\u2003CDID\n"
            "🎣\u2003•\u2003Fisch\n"
            "🐟\u2003•\u2003Fish It\n"
            "🌱\u2003•\u2003Grow A Garden\n"
            "🧟\u2003•\u2003Hunty Zombie\n"
            "🏴\u2003•\u2003Sailor Piece\n"
            "🌾\u2003•\u2003Sawah Indo\n"
            "<:sr_tangleslime:1511973089762873377>\u2003•\u2003Slime Rng\n"
            "**⠂⠄⠄⠂⠁⠁⠂⠄⠄⠂⠁⠁⠂⠄⠄⠂ ⠂⠄⠄⠂☆**\n\n"

            "> -# <:foxnote:1511780221030895678> **Notes :**\n"
            "> -# ──.✦ Harga dan item terupdate!\n"
            "> -# ──.✦ Khusus member dengan tag Myst akan mendapatkan diskon pembelian.\n"
            "> -# ──.✦ Feel free untuk request map yang belum tersedia."
        ),
        color=COLOR
    )


    await interaction.channel.send(
        embed=embed,
        view=GamePricelistView()
    )


    await interaction.response.send_message(
        "✅ Panel pricelist berhasil dibuat.",
        ephemeral=True
    )


# =========================================================
# ADD GAME PRICELIST
# =========================================================

@bot.tree.command(
    name="pricelist_add",
    description="Admin menambahkan game pricelist"
)
@app_commands.describe(
    nama_game="Nama game",
    emoji="Emoji game",
    message_ids="ID message embed, pisahkan dengan koma"
)
async def pricelist_add(
    interaction: discord.Interaction,
    nama_game: str,
    emoji: str,
    message_ids: str
):

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin.",
            ephemeral=True
        )
        return


    ids = [
        x.strip()
        for x in message_ids.split(",")
        if x.strip()
    ]


    GAME_PRICELISTS[
        normalize_key(nama_game).replace(" ", "_")
    ] = {

        "name": nama_game,

        "emoji": emoji,

        "message_ids": ids
    }


    save_game_pricelists()


    await interaction.response.send_message(
        f"✅ Pricelist **{nama_game}** disimpan dengan {len(ids)} embed.",
        ephemeral=True
    )

@bot.tree.command(
    name="pricelist_list",
    description="Admin melihat daftar pricelist"
)
async def pricelist_list(
    interaction: discord.Interaction
):

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin.",
            ephemeral=True
        )
        return


    if not GAME_PRICELISTS:

        await interaction.response.send_message(
            "Belum ada pricelist.",
            ephemeral=True
        )
        return


    lines = []

    for key, data in GAME_PRICELISTS.items():

        lines.append(
            f"{data.get('emoji','🎮')} **{data['name']}**\n"
            f"Message ID: `{data['message_id']}`"
        )


    await interaction.response.send_message(
        "\n\n".join(lines),
        ephemeral=True
    )

@bot.tree.command(
    name="pricelist_remove",
    description="Admin menghapus game dari pricelist"
)
@app_commands.describe(
    nama_game="Nama game yang ingin dihapus"
)
async def pricelist_remove(
    interaction: discord.Interaction,
    nama_game: str
):

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya admin.",
            ephemeral=True
        )
        return


    key = normalize_key(nama_game).replace(" ", "_")


    if key not in GAME_PRICELISTS:

        await interaction.response.send_message(
            "❌ Game tidak ditemukan.",
            ephemeral=True
        )
        return


    GAME_PRICELISTS.pop(key)

    save_game_pricelists()


    await interaction.response.send_message(
        f"🗑️ Pricelist **{nama_game}** berhasil dihapus.",
        ephemeral=True
    )


# =========================================================
# VIP SYSTEM
# =========================================================
def make_vip_embed(message_id: int | str):
    session = get_session(message_id)
    info = session["info"]
    vip_list = session["list"]

    lines = []
    title = "💎 **VIP X8 LUCK BY MYST STORE** 💎"

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
# KASIR
# =========================================================
def build_kasir_preview_embed(session: dict) -> discord.Embed:
    embed = discord.Embed(title="Preview Kasir", color=COLOR)
    embed.add_field(name="Customer", value=session["customer"], inline=False)
    embed.add_field(name="Rate Hari Ini", value=str(session["rate"]), inline=False)
    embed.add_field(name="Tanggal", value=format_wib(), inline=False)

    if session["items"]:
        lines = []
        total = 0

        for i, item in enumerate(session["items"], start=1):
            qty_text = f" x{item['qty']}" if item["qty"] > 1 else ""
            subtotal = item["price"] * item["qty"]
            total += subtotal
            item_info = get_invoice_item_info(item)

            lines.append(
                f"{i}. {item['name']} ({item_info}){qty_text} : {format_rupiah(subtotal)}"
            )

        embed.add_field(name="List Pembelian", value="\n".join(lines), inline=False)
        embed.add_field(name="TOTAL", value=f"**{format_rupiah(total)}**", inline=False)
    else:
        embed.add_field(name="List Pembelian", value="Belum ada item.", inline=False)

    embed.set_footer(text="Semua proses kasir hanya terlihat admin sampai invoice dikirim")
    return embed


def build_kasir_invoice_embed(session: dict) -> discord.Embed:
    lines = []

    lines.append(f"* **Customer** : {session['customer']}")
    lines.append(f"* **Tanggal **: {format_wib()}")
    lines.append("")
    lines.append("**━.✦ List Pembelian**")

    total = 0
    for i, item in enumerate(session["items"], start=1):
        qty_text = f" x{item['qty']}" if item["qty"] > 1 else ""
        subtotal = item["price"] * item["qty"]
        total += subtotal
        item_info = get_invoice_item_info(item)

        lines.append(
            f"{i}. {item['name']} ({item_info}){qty_text} : {format_rupiah(subtotal)}"
        )

    lines.append("")
    lines.append("**━.✦ Total Pembayaran**")
    lines.append(format_rupiah(total))

    return discord.Embed(
        description="\n".join(lines),
        color=COLOR
    )


class QuantityModal(Modal):
    def __init__(self, session_id: str, product: dict):
        super().__init__(title=f"Jumlah untuk {product['name'][:30]}")
        self.session_id = session_id
        self.product = product
        self.qty = TextInput(label="Jumlah item", placeholder="Contoh: 1", default="1")
        self.add_item(self.qty)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.qty.value)
            if qty <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Jumlah harus angka lebih dari 0.", ephemeral=True)
            return

        session = kasir_sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("Sesi kasir sudah berakhir.", ephemeral=True)
            return

        if is_lainnya_product(self.product):
            harga = int(self.product.get("price", 0))

            session["items"].append({
                "category": "Lainnya",
                "name": self.product["name"],
                "robux": None,
                "price": harga,
                "qty": qty
            })
        else:
            rate = int(session["rate"])
            robux = int(self.product["robux"])
            harga = calculate_price(robux, rate)

            session["items"].append({
                "category": self.product.get("category", "-"),
                "name": self.product["name"],
                "robux": robux,
                "price": harga,
                "qty": qty
            })

        preview_msg = session.get("preview_message")
        if preview_msg:
            try:
                await preview_msg.edit(
                    embed=build_kasir_preview_embed(session),
                    view=KasirView(self.session_id)
                )
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            "✅ Produk ditambahkan ke preview kasir.",
            ephemeral=True
        )


class KasirCategorySelect(Select):
    def __init__(self, session_id: str):
        self.session_id = session_id

        options = []
        used_categories = []

        for cat in CATEGORIES:
            if any(normalize_key(product.get("category", "")) == normalize_key(cat) for product in PRODUCTS):
                used_categories.append(cat)

        for cat in used_categories[:25]:
            options.append(discord.SelectOption(label=cat[:100], value=cat[:100]))

        if not options:
            options.append(discord.SelectOption(label="Belum ada kategori berisi produk", value="none"))

        super().__init__(
            placeholder="Pilih kategori",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Belum ada kategori yang punya produk.", ephemeral=True)
            return

        category = self.values[0]
        await interaction.response.edit_message(
            content=f"Kategori: **{category}**\nPilih produk:",
            view=KasirProductByCategoryView(self.session_id, category)
        )


class KasirCategoryView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=120)
        self.add_item(KasirCategorySelect(session_id))


class KasirProductByCategorySelect(Select):
    def __init__(self, session_id: str, category: str):
        self.session_id = session_id
        self.category = category

        session = kasir_sessions.get(session_id)
        rate = int(session["rate"]) if session else 0

        options = []
        for product in PRODUCTS:
            if normalize_key(product.get("category", "")) == normalize_key(category):
                options.append(
                    discord.SelectOption(
                        label=product["name"][:100],
                        description=get_product_preview_description(product, rate),
                        value=product["id"]
                    )
                )

        if not options:
            options.append(discord.SelectOption(label="Tidak ada produk", value="none"))

        super().__init__(
            placeholder="Pilih produk",
            min_values=1,
            max_values=1,
            options=options[:25]
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Kategori ini belum punya produk.", ephemeral=True)
            return

        product = next((p for p in PRODUCTS if p["id"] == self.values[0]), None)
        if not product:
            await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
            return

        await interaction.response.send_modal(QuantityModal(self.session_id, product))


class KasirProductByCategoryView(View):
    def __init__(self, session_id: str, category: str):
        super().__init__(timeout=120)
        self.add_item(KasirProductByCategorySelect(session_id, category))


class SearchProductModal(Modal):
    def __init__(self, session_id: str):
        super().__init__(title="Cari Produk")
        self.session_id = session_id

        self.keyword = TextInput(
            label="Nama produk",
            placeholder="Ketik nama produk..."
        )
        self.add_item(self.keyword)

    async def on_submit(self, interaction: discord.Interaction):
        keyword = normalize_key(self.keyword.value)

        if not keyword:
            await interaction.response.send_message("Kata kunci tidak boleh kosong.", ephemeral=True)
            return

        results = []
        for product in PRODUCTS:
            label = f"{product.get('category', '')} {product.get('name', '')}"
            if keyword in normalize_key(label):
                results.append(product)

        if not results:
            await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Hasil pencarian:",
            view=SearchResultView(self.session_id, results),
            ephemeral=True
        )


class SearchResultSelect(Select):
    def __init__(self, session_id: str, products: list):
        self.session_id = session_id

        session = kasir_sessions.get(session_id)
        rate = int(session["rate"]) if session else 0

        options = []
        for product in products[:25]:
            options.append(
                discord.SelectOption(
                    label=f"[{product.get('category', '-')}] {product['name']}"[:100],
                    description=get_product_preview_description(product, rate),
                    value=product["id"]
                )
            )

        super().__init__(
            placeholder="Pilih produk hasil pencarian",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        product = next((p for p in PRODUCTS if p["id"] == self.values[0]), None)
        if not product:
            await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
            return

        await interaction.response.send_modal(QuantityModal(self.session_id, product))


class SearchResultView(View):
    def __init__(self, session_id: str, products: list):
        super().__init__(timeout=120)
        self.add_item(SearchResultSelect(session_id, products))


class KasirView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=600)
        self.session_id = session_id

    @discord.ui.button(label="Tambah Produk", style=discord.ButtonStyle.success)
    async def add_product(self, interaction: discord.Interaction, button: Button):
        if not PRODUCTS:
            await interaction.response.send_message("Belum ada katalog produk. Gunakan /produk_tambah dulu.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Pilih kategori:",
            view=KasirCategoryView(self.session_id),
            ephemeral=True
        )

    @discord.ui.button(label="Cari Produk", style=discord.ButtonStyle.secondary)
    async def search_product(self, interaction: discord.Interaction, button: Button):
        if not PRODUCTS:
            await interaction.response.send_message("Belum ada katalog produk. Gunakan /produk_tambah dulu.", ephemeral=True)
            return

        await interaction.response.send_modal(SearchProductModal(self.session_id))

    @discord.ui.button(label="Kirim Invoice", style=discord.ButtonStyle.primary)
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

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.danger)
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

        preview_msg = await interaction.original_response()
        kasir_sessions[session_id]["preview_message"] = preview_msg


@bot.tree.command(name="kasir", description="Mulai sesi kasir dan isi rate harian")
async def kasir(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin yang bisa memakai kasir.", ephemeral=True)
        return

    await interaction.response.send_modal(StartKasirModal())


# =========================================================
# KATEGORI & PRODUK KASIR
# =========================================================
@bot.tree.command(name="kategori_tambah", description="Tambah kategori produk robux")
@app_commands.describe(nama="Nama kategori, contoh: Gamepass, Limited, Reroll")
async def kategori_tambah(interaction: discord.Interaction, nama: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    nama = nama.strip()
    if not nama:
        await interaction.response.send_message("Nama kategori tidak boleh kosong.", ephemeral=True)
        return

    if is_lainnya_category(nama):
        await interaction.response.send_message("Kategori Lainnya sudah otomatis tersedia.", ephemeral=True)
        return

    if category_exists(nama):
        await interaction.response.send_message("Kategori itu sudah ada.", ephemeral=True)
        return

    CATEGORIES.append(nama)
    save_categories()

    await interaction.response.send_message(f"✅ Kategori robux **{nama}** berhasil ditambahkan.", ephemeral=True)


@bot.tree.command(name="kategori_hapus", description="Hapus kategori produk")
@app_commands.describe(nama="Nama kategori")
@app_commands.autocomplete(nama=category_autocomplete)
async def kategori_hapus(interaction: discord.Interaction, nama: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    if is_lainnya_category(nama):
        await interaction.response.send_message("Kategori default Lainnya tidak bisa dihapus.", ephemeral=True)
        return

    target = get_category_name(nama)
    if not target:
        await interaction.response.send_message("Kategori tidak ditemukan.", ephemeral=True)
        return

    used = any(normalize_key(product.get("category", "")) == normalize_key(target) for product in PRODUCTS)
    if used:
        await interaction.response.send_message("Kategori masih dipakai produk. Hapus produknya dulu.", ephemeral=True)
        return

    CATEGORIES.remove(target)
    save_categories()

    await interaction.response.send_message(f"🗑️ Kategori **{target}** berhasil dihapus.", ephemeral=True)


@bot.tree.command(name="kategori_list", description="Lihat daftar kategori")
async def kategori_list(interaction: discord.Interaction):
    lines = [f"{i}. {cat}" for i, cat in enumerate(CATEGORIES, start=1)]

    await interaction.response.send_message(
        "**Daftar Kategori:**\n" + "\n".join(lines),
        ephemeral=True
    )


@bot.tree.command(name="produk_tambah", description="Tambah produk ke katalog kasir")
@app_commands.describe(
    kategori="Pilih kategori. Selain Lainnya wajib isi robux.",
    nama="Nama produk",
    robux="Jumlah robux untuk kategori biasa",
    harga="Harga rupiah langsung khusus kategori Lainnya"
)
@app_commands.autocomplete(kategori=category_autocomplete)
async def produk_tambah(
    interaction: discord.Interaction,
    kategori: str,
    nama: str,
    robux: Optional[int] = None,
    harga: Optional[int] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    kategori_asli = get_category_name(kategori)
    if not kategori_asli:
        await interaction.response.send_message("Kategori belum ada. Tambahkan dulu dengan `/kategori_tambah`.", ephemeral=True)
        return

    if find_product_by_name_and_category(nama, kategori_asli):
        await interaction.response.send_message(
            "Produk dengan nama itu sudah ada di kategori yang sama.",
            ephemeral=True
        )
        return

    if is_lainnya_category(kategori_asli):
        if harga is None or harga <= 0:
            await interaction.response.send_message("Kategori Lainnya wajib isi harga rupiah lebih dari 0.", ephemeral=True)
            return

        PRODUCTS.append({
            "id": str(uuid.uuid4()),
            "category": "Lainnya",
            "name": nama.strip(),
            "robux": None,
            "price": harga
        })

    else:
        if robux is None or robux <= 0:
            await interaction.response.send_message("Kategori ini wajib isi robux lebih dari 0.", ephemeral=True)
            return

        PRODUCTS.append({
            "id": str(uuid.uuid4()),
            "category": kategori_asli,
            "name": nama.strip(),
            "robux": robux
        })

    save_products()
    await interaction.response.send_message(f"✅ Produk **{nama}** berhasil ditambahkan.", ephemeral=True)


@bot.tree.command(name="produk_edit", description="Edit produk katalog kasir")
@app_commands.describe(
    nama="Nama produk yang ingin diedit",
    kategori="Kategori baru",
    nama_baru="Nama baru",
    robux="Robux baru untuk kategori biasa",
    harga="Harga rupiah baru khusus kategori Lainnya"
)
@app_commands.autocomplete(nama=product_autocomplete, kategori=category_autocomplete)
async def produk_edit(
    interaction: discord.Interaction,
    nama: str,
    kategori: Optional[str] = None,
    nama_baru: Optional[str] = None,
    robux: Optional[int] = None,
    harga: Optional[int] = None
):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ Hanya admin.", ephemeral=True)
        return

    product = find_product_by_name(nama)
    if not product:
        await interaction.response.send_message("Produk tidak ditemukan.", ephemeral=True)
        return

    kategori_asli = None
    if kategori:
        kategori_asli = get_category_name(kategori)
        if not kategori_asli:
            await interaction.response.send_message("Kategori tidak ditemukan.", ephemeral=True)
            return

    target_category = kategori_asli if kategori_asli else product.get("category", "")

    if nama_baru:
        existing = find_product_by_name_and_category(nama_baru, target_category)
        if existing and existing is not product:
            await interaction.response.send_message(
                "Nama produk baru sudah dipakai di kategori yang sama.",
                ephemeral=True
            )
            return

        product["name"] = nama_baru.strip()

    if kategori_asli:
        product["category"] = kategori_asli

    kategori_final = product.get("category", "")

    if is_lainnya_category(kategori_final):
        product["category"] = "Lainnya"
        product["robux"] = None

        if harga is not None:
            if harga <= 0:
                await interaction.response.send_message("Harga harus lebih dari 0.", ephemeral=True)
                return
            product["price"] = harga

        if "price" not in product:
            await interaction.response.send_message("Produk Lainnya wajib punya harga. Isi parameter harga.", ephemeral=True)
            return

    else:
        if robux is not None:
            if robux <= 0:
                await interaction.response.send_message("Robux harus lebih dari 0.", ephemeral=True)
                return
            product["robux"] = robux

        if product.get("robux") is None:
            await interaction.response.send_message("Produk kategori ini wajib punya robux. Isi parameter robux.", ephemeral=True)
            return

        product.pop("price", None)

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
    await interaction.response.send_message(f"🗑️ Produk **{product['name']}** dihapus.", ephemeral=True)


class ProductListCategorySelect(Select):
    def __init__(self):
        options = []

        used_categories = []
        for cat in CATEGORIES:
            if any(normalize_key(product.get("category", "")) == normalize_key(cat) for product in PRODUCTS):
                used_categories.append(cat)

        for cat in used_categories[:25]:
            options.append(
                discord.SelectOption(
                    label=cat[:100],
                    value=cat[:100]
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="Belum ada kategori berisi produk",
                    value="none"
                )
            )

        super().__init__(
            placeholder="Pilih kategori produk",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message(
                "Belum ada produk di katalog.",
                ephemeral=True
            )
            return

        category = self.values[0]

        products = [
            product for product in PRODUCTS
            if normalize_key(product.get("category", "")) == normalize_key(category)
        ]

        if not products:
            await interaction.response.send_message(
                "Kategori ini belum punya produk.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"Katalog Produk - {category}",
            color=COLOR
        )

        lines = []
        for i, product in enumerate(products, start=1):
            if is_lainnya_product(product):
                lines.append(
                    f"{i}. {product['name']} - {format_rupiah(int(product.get('price', 0)))}"
                )
            else:
                lines.append(
                    f"{i}. {product['name']} ({product['robux']} robux)"
                )

        embed.description = "\n".join(lines)

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=None
        )


class ProductListCategoryView(View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ProductListCategorySelect())


@bot.tree.command(name="produk_list", description="Lihat katalog produk kasir berdasarkan kategori")
async def produk_list(interaction: discord.Interaction):
    if not PRODUCTS:
        await interaction.response.send_message(
            "Belum ada katalog produk.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "Pilih kategori produk:",
        view=ProductListCategoryView(),
        ephemeral=True
    )


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
        save_categories()
        save_products()

        bot.add_view(
            GamePricelistView()
        )

        synced = await bot.tree.sync()

        print(
            f"Bot siap sebagai {bot.user}. Slash synced: {len(synced)}"
        )

        print(
            f"Data folder aktif: {BASE_DIR}"
        )

    except Exception as e:
        print(
            f"Gagal sync slash command: {e}"
        )


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
