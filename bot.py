"""
Timhirt Hub - Ethiopian study library bot
python-telegram-bot v21+

Env vars:
  BOT_TOKEN  token from @BotFather
  ADMIN_IDS  comma-separated Telegram user IDs (get yours from @userinfobot)

Admin commands:
  /tree                      show all folders with their IDs
  /newfolder <parent> <name> add a folder (parent = ID, use "root" for top level)
  /rename <id> <new name>    rename a folder
  /delete <id>               delete a folder (and everything inside it)
  /rmfile <id> <number>      remove file number N from a folder
  Send any document with the folder ID as its caption -> file is added.
"""
import json
import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("timhirt")

TOKEN = os.environ["BOT_TOKEN"]
ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
DB = Path(os.environ.get("DB_PATH", "menu.json"))

WELCOME = (
    "📚 *Timhirt Hub*\n"
    "Free study materials for Ethiopian students.\n\n"
    "Pick a category below 👇"
)

# ---------- storage ----------


def _node(title, parent, children=None):
    return {"title": title, "parent": parent, "children": children or [], "files": []}


def seed():
    """Starter menu. Change it later with the admin commands."""
    d = {"root": _node("Main Menu", None)}

    def add(title, parent):
        nid = f"n{len(d)}"
        d[nid] = _node(title, parent)
        d[parent]["children"].append(nid)
        return nid

    tb = add("📗 Textbooks", "root")
    for t in ("Elementary", "High School", "University"):
        add(t, tb)
    ex = add("📝 Entrance Exams", "root")
    add("Natural Science", ex)
    add("Social Science", ex)
    add("🧪 Model Exams", "root")
    rm = add("🧩 Remedial Modules", "root")
    add("Natural Science", rm)
    add("Social Science", rm)
    add("📖 Reference Books", "root")
    return d


def load():
    if DB.exists():
        return json.loads(DB.read_text(encoding="utf-8"))
    data = seed()
    save(data)
    return data


def save(data):
    DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def new_id(data):
    nums = [int(k[1:]) for k in data if k.startswith("n") and k[1:].isdigit()]
    return f"n{max(nums, default=0) + 1}"


# ---------- UI ----------


def menu_text(data, nid):
    if nid == "root":
        return WELCOME
    n = data[nid]
    extra = "\n\nTap a file to download 👇" if n["files"] else ""
    return f"*{n['title']}*{extra}"


def keyboard(data, nid):
    node = data[nid]
    rows, row = [], []
    for cid in node["children"]:
        row.append(InlineKeyboardButton(data[cid]["title"], callback_data=f"n:{cid}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    for i, f in enumerate(node["files"]):
        rows.append([InlineKeyboardButton(f"📥 {f['name'][:50]}", callback_data=f"d:{nid}:{i}")])
    nav = []
    if node["parent"]:
        nav.append(InlineKeyboardButton("⬅️ Back", callback_data=f"n:{node['parent']}"))
    if nid != "root":
        nav.append(InlineKeyboardButton("🏠 Home", callback_data="n:root"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


# ---------- user handlers ----------


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load()
    await update.message.reply_text(
        menu_text(data, "root"),
        reply_markup=keyboard(data, "root"),
        parse_mode=ParseMode.MARKDOWN,
    )


async def on_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    nid = q.data.split(":", 1)[1]
    data = load()
    if nid not in data:
        return
    await q.edit_message_text(
        menu_text(data, nid),
        reply_markup=keyboard(data, nid),
        parse_mode=ParseMode.MARKDOWN,
    )


async def on_download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, nid, idx = q.data.split(":")
    data = load()
    try:
        f = data[nid]["files"][int(idx)]
    except (KeyError, IndexError):
        await q.answer("File not found.", show_alert=True)
        return
    await q.answer("Sending…")
    await ctx.bot.send_document(q.message.chat_id, f["file_id"], caption=f["name"])


# ---------- admin handlers ----------


def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ADMINS


async def tree(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    data = load()
    lines = []

    def walk(nid, depth):
        n = data[nid]
        lines.append(f"{'  ' * depth}{n['title']}  [{nid}]  ({len(n['files'])} files)")
        for c in n["children"]:
            walk(c, depth + 1)

    walk("root", 0)
    await update.message.reply_text("\n".join(lines))


async def newfolder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: /newfolder <parent_id> <name>")
        return
    data = load()
    parent, title = ctx.args[0], " ".join(ctx.args[1:])
    if parent not in data:
        await update.message.reply_text("Parent ID not found. Use /tree.")
        return
    nid = new_id(data)
    data[nid] = _node(title, parent)
    data[parent]["children"].append(nid)
    save(data)
    await update.message.reply_text(f"✅ Created {title} [{nid}]")


async def rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    data = load()
    if len(ctx.args) < 2 or ctx.args[0] not in data:
        await update.message.reply_text("Usage: /rename <id> <new name>")
        return
    data[ctx.args[0]]["title"] = " ".join(ctx.args[1:])
    save(data)
    await update.message.reply_text("✅ Renamed")


async def delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    data = load()
    if not ctx.args or ctx.args[0] not in data or ctx.args[0] == "root":
        await update.message.reply_text("Usage: /delete <id>")
        return

    def drop(nid):
        for c in data[nid]["children"]:
            drop(c)
        del data[nid]

    nid = ctx.args[0]
    data[data[nid]["parent"]]["children"].remove(nid)
    drop(nid)
    save(data)
    await update.message.reply_text("🗑 Deleted")


async def rmfile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    data = load()
    try:
        nid, num = ctx.args[0], int(ctx.args[1])
        removed = data[nid]["files"].pop(num - 1)
    except (IndexError, KeyError, ValueError):
        await update.message.reply_text("Usage: /rmfile <id> <number>")
        return
    save(data)
    await update.message.reply_text(f"🗑 Removed {removed['name']}")


async def add_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin sends a document with the folder ID as caption."""
    if not is_admin(update):
        return
    msg = update.message
    nid = (msg.caption or "").strip()
    data = load()
    if nid not in data:
        await msg.reply_text("Put the folder ID in the caption (see /tree).")
        return
    doc = msg.document
    data[nid]["files"].append({"file_id": doc.file_id, "name": doc.file_name or "file"})
    save(data)
    await msg.reply_text(f"✅ Added to {data[nid]['title']} ({len(data[nid]['files'])} files)")


async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Error", exc_info=ctx.error)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("tree", tree))
    app.add_handler(CommandHandler("newfolder", newfolder))
    app.add_handler(CommandHandler("rename", rename))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("rmfile", rmfile))
    app.add_handler(CallbackQueryHandler(on_nav, pattern=r"^n:"))
    app.add_handler(CallbackQueryHandler(on_download, pattern=r"^d:"))
    app.add_handler(MessageHandler(filters.Document.ALL, add_file))
    app.add_error_handler(on_error)
    log.info("Bot running…")
    app.run_polling()


if __name__ == "__main__":
    main()
