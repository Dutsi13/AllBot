import logging
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DATA_FILE = "data.json"

# Conversation states
WAITING_LIST_NAME = 1
WAITING_USERNAME = 2
WAITING_EDIT_CHOICE = 3

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"chats": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_chat_data(data, chat_id):
    chat_id = str(chat_id)
    if chat_id not in data["chats"]:
        data["chats"][chat_id] = {
            "members": {},
            "lists": {}
        }
    return data["chats"][chat_id]

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 <b>MentionBot — бот для призыва участников</b>\n\n"
        "📋 <b>Команды:</b>\n"
        "• /all — призвать всех участников чата\n"
        "• /list — вызвать меню списков\n"
        "• /newlist — создать новый список\n"
        "• /lists — показать все списки\n"
        "• /dellist — удалить список\n"
        "• /register — зарегистрироваться в чате\n"
        "• /addme — добавить себя в список вручную\n\n"
        "⚙️ <b>Как начать:</b>\n"
        "1. Каждый участник пишет /register\n"
        "2. Создай списки через /newlist\n"
        "3. Призывай всех через /all или по спискам через /list"
    )
    await update.message.reply_html(text)

# ─────────────────────────────────────────────
# /register — участник регистрирует себя
# ─────────────────────────────────────────────
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    data = load_data()
    chat_data = get_chat_data(data, chat_id)

    user_id = str(user.id)
    username = user.username or user.first_name
    display = f"@{username}" if user.username else user.first_name

    chat_data["members"][user_id] = {
        "username": username,
        "has_username": bool(user.username),
        "first_name": user.first_name,
        "display": display
    }
    save_data(data)

    await update.message.reply_html(
        f"✅ {display} зарегистрирован(а) в чате!\n"
        f"Теперь тебя будут призывать командой /all"
    )

# ─────────────────────────────────────────────
# /all — призвать всех зарегистрированных
# ─────────────────────────────────────────────
async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = load_data()
    chat_data = get_chat_data(data, chat_id)

    members = chat_data.get("members", {})
    if not members:
        await update.message.reply_html(
            "❌ Нет зарегистрированных участников.\n"
            "Попросите всех написать /register"
        )
        return

    mentions = []
    for uid, info in members.items():
        if info.get("has_username"):
            mentions.append(f"@{info['username']}")
        else:
            mentions.append(
                f'<a href="tg://user?id={uid}">{info["first_name"]}</a>'
            )

    caller = update.effective_user
    caller_display = f"@{caller.username}" if caller.username else caller.first_name

    # Split into chunks of 20 to avoid Telegram limits
    chunk_size = 20
    chunks = [mentions[i:i+chunk_size] for i in range(0, len(mentions), chunk_size)]

    for i, chunk in enumerate(chunks):
        if i == 0:
            text = f"📢 <b>{caller_display}</b> призывает всех:\n\n" + " ".join(chunk)
        else:
            text = " ".join(chunk)
        await update.message.reply_html(text)

# ─────────────────────────────────────────────
# /newlist — создать новый список
# ─────────────────────────────────────────────
async def new_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ Команда работает только в групповых чатах.")
        return ConversationHandler.END

    await update.message.reply_text(
        "📝 Введите название нового списка (например: <b>admin</b>, <b>team</b>):",
        parse_mode="HTML"
    )
    return WAITING_LIST_NAME

async def receive_list_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    list_name = update.message.text.strip().lower().replace(" ", "_")
    if not list_name:
        await update.message.reply_text("❌ Название не может быть пустым. Попробуй ещё раз:")
        return WAITING_LIST_NAME

    context.user_data["new_list_name"] = list_name
    context.user_data["new_list_chat_id"] = update.effective_chat.id

    await update.message.reply_html(
        f"✅ Список <b>{list_name}</b> будет создан.\n\n"
        f"Теперь отправляй юзернеймы по одному (с @ или без).\n"
        f"Когда закончишь, напиши <b>готово</b>."
    )
    context.user_data["collecting_usernames"] = True
    context.user_data["new_list_users"] = []
    return WAITING_USERNAME

async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text.lower() in ["готово", "done", "/done"]:
        list_name = context.user_data.get("new_list_name")
        chat_id = context.user_data.get("new_list_chat_id")
        users = context.user_data.get("new_list_users", [])

        data = load_data()
        chat_data = get_chat_data(data, chat_id)

        chat_data["lists"][list_name] = users
        save_data(data)

        if users:
            user_list = "\n".join([f"  • @{u}" for u in users])
            await update.message.reply_html(
                f"✅ Список <b>{list_name}</b> создан!\n\n"
                f"Участники ({len(users)}):\n{user_list}\n\n"
                f"Используй: /list {list_name}"
            )
        else:
            await update.message.reply_html(
                f"✅ Список <b>{list_name}</b> создан (пустой).\n"
                f"Добавь участников позже через /editlist"
            )

        context.user_data.clear()
        return ConversationHandler.END

    username = text.lstrip("@").strip()
    if not username:
        await update.message.reply_text("❌ Некорректный юзернейм. Попробуй ещё раз:")
        return WAITING_USERNAME

    if username not in context.user_data["new_list_users"]:
        context.user_data["new_list_users"].append(username)
        await update.message.reply_html(
            f"➕ <code>@{username}</code> добавлен.\n"
            f"Добавь ещё или напиши <b>готово</b>."
        )
    else:
        await update.message.reply_text(f"⚠️ @{username} уже в списке.")

    return WAITING_USERNAME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END

# ─────────────────────────────────────────────
# /list — меню выбора списка или вызов по имени
# ─────────────────────────────────────────────
async def list_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = load_data()
    chat_data = get_chat_data(data, chat_id)
    lists = chat_data.get("lists", {})

    # If argument provided: /list listname
    if context.args:
        list_name = context.args[0].lower()
        await call_list(update, context, chat_id, list_name, data)
        return

    if not lists:
        await update.message.reply_html(
            "📋 Нет созданных списков.\n"
            "Создай список командой /newlist"
        )
        return

    keyboard = []
    for list_name, users in lists.items():
        keyboard.append([
            InlineKeyboardButton(
                f"📋 {list_name} ({len(users)} чел.)",
                callback_data=f"call_list:{list_name}"
            ),
            InlineKeyboardButton("✏️", callback_data=f"edit_list:{list_name}"),
            InlineKeyboardButton("🗑️", callback_data=f"del_list:{list_name}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_html(
        "📋 <b>Выбери список для призыва:</b>",
        reply_markup=reply_markup
    )

async def call_list(update, context, chat_id, list_name, data):
    chat_data = get_chat_data(data, chat_id)
    lists = chat_data.get("lists", {})

    if list_name not in lists:
        await update.message.reply_html(f"❌ Список <b>{list_name}</b> не найден.")
        return

    users = lists[list_name]
    if not users:
        await update.message.reply_html(
            f"⚠️ Список <b>{list_name}</b> пуст.\n"
            f"Добавь участников через /editlist"
        )
        return

    mentions = [f"@{u}" for u in users]
    caller = update.effective_user
    caller_display = f"@{caller.username}" if caller.username else caller.first_name

    chunk_size = 20
    chunks = [mentions[i:i+chunk_size] for i in range(0, len(mentions), chunk_size)]

    for i, chunk in enumerate(chunks):
        if i == 0:
            text = f"📢 <b>{caller_display}</b> призывает список <b>{list_name}</b>:\n\n" + " ".join(chunk)
        else:
            text = " ".join(chunk)
        await update.message.reply_html(text)

# ─────────────────────────────────────────────
# Callback handlers
# ─────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data_str = query.data
    chat_id = query.message.chat_id
    data = load_data()
    chat_data = get_chat_data(data, chat_id)
    lists = chat_data.get("lists", {})

    # ── Call a list ──
    if data_str.startswith("call_list:"):
        list_name = data_str.split(":", 1)[1]
        users = lists.get(list_name, [])

        if not users:
            await query.edit_message_text(f"⚠️ Список {list_name} пуст.")
            return

        mentions = [f"@{u}" for u in users]
        caller = query.from_user
        caller_display = f"@{caller.username}" if caller.username else caller.first_name

        await query.edit_message_text(
            f"📢 {caller_display} призывает список {list_name}:\n\n" + " ".join(mentions),
            parse_mode="HTML"
        )

    # ── Edit a list ──
    elif data_str.startswith("edit_list:"):
        list_name = data_str.split(":", 1)[1]
        users = lists.get(list_name, [])
        user_list = "\n".join([f"  • @{u}" for u in users]) if users else "  (пусто)"

        keyboard = [
            [InlineKeyboardButton("➕ Добавить пользователя", callback_data=f"add_user:{list_name}")],
            [InlineKeyboardButton("➖ Удалить пользователя", callback_data=f"remove_user_menu:{list_name}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_lists")]
        ]
        await query.edit_message_text(
            f"✏️ Редактирование списка <b>{list_name}</b>\n\n"
            f"Участники:\n{user_list}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # ── Add user to list (prompt) ──
    elif data_str.startswith("add_user:"):
        list_name = data_str.split(":", 1)[1]
        context.user_data["adding_to_list"] = list_name
        context.user_data["adding_chat_id"] = chat_id
        await query.edit_message_text(
            f"➕ Отправь юзернейм для добавления в <b>{list_name}</b>\n"
            f"(с @ или без, одно сообщение = один пользователь)\n\n"
            f"Напиши /cancel для отмены.",
            parse_mode="HTML"
        )

    # ── Remove user menu ──
    elif data_str.startswith("remove_user_menu:"):
        list_name = data_str.split(":", 1)[1]
        users = lists.get(list_name, [])

        if not users:
            await query.answer("Список пуст!", show_alert=True)
            return

        keyboard = []
        for u in users:
            keyboard.append([
                InlineKeyboardButton(f"❌ @{u}", callback_data=f"remove_user:{list_name}:{u}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"edit_list:{list_name}")])

        await query.edit_message_text(
            f"➖ Выбери кого удалить из <b>{list_name}</b>:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # ── Remove specific user ──
    elif data_str.startswith("remove_user:"):
        parts = data_str.split(":", 2)
        list_name, username = parts[1], parts[2]

        if list_name in lists and username in lists[list_name]:
            lists[list_name].remove(username)
            save_data(data)
            await query.answer(f"@{username} удалён из {list_name}")

            # Refresh edit menu
            users = lists.get(list_name, [])
            user_list = "\n".join([f"  • @{u}" for u in users]) if users else "  (пусто)"
            keyboard = [
                [InlineKeyboardButton("➕ Добавить пользователя", callback_data=f"add_user:{list_name}")],
                [InlineKeyboardButton("➖ Удалить пользователя", callback_data=f"remove_user_menu:{list_name}")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_lists")]
            ]
            await query.edit_message_text(
                f"✏️ Редактирование списка <b>{list_name}</b>\n\n"
                f"Участники:\n{user_list}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    # ── Delete list (confirm) ──
    elif data_str.startswith("del_list:"):
        list_name = data_str.split(":", 1)[1]
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_del:{list_name}"),
                InlineKeyboardButton("❌ Отмена", callback_data="back_to_lists")
            ]
        ]
        await query.edit_message_text(
            f"⚠️ Удалить список <b>{list_name}</b>?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # ── Confirm delete ──
    elif data_str.startswith("confirm_del:"):
        list_name = data_str.split(":", 1)[1]
        if list_name in lists:
            del lists[list_name]
            save_data(data)
            await query.answer(f"Список {list_name} удалён")

        await show_lists_keyboard(query, chat_data)

    # ── Back to lists ──
    elif data_str == "back_to_lists":
        await show_lists_keyboard(query, chat_data)

async def show_lists_keyboard(query, chat_data):
    lists = chat_data.get("lists", {})
    if not lists:
        await query.edit_message_text("📋 Нет созданных списков. Создай через /newlist")
        return

    keyboard = []
    for list_name, users in lists.items():
        keyboard.append([
            InlineKeyboardButton(
                f"📋 {list_name} ({len(users)} чел.)",
                callback_data=f"call_list:{list_name}"
            ),
            InlineKeyboardButton("✏️", callback_data=f"edit_list:{list_name}"),
            InlineKeyboardButton("🗑️", callback_data=f"del_list:{list_name}")
        ])

    await query.edit_message_text(
        "📋 <b>Выбери список для призыва:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ─────────────────────────────────────────────
# Message handler for inline add_user flow
# ─────────────────────────────────────────────
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "adding_to_list" not in context.user_data:
        return

    list_name = context.user_data["adding_to_list"]
    chat_id = context.user_data["adding_chat_id"]
    username = update.message.text.strip().lstrip("@")

    if not username:
        await update.message.reply_text("❌ Некорректный юзернейм.")
        return

    data = load_data()
    chat_data = get_chat_data(data, chat_id)

    if list_name not in chat_data["lists"]:
        chat_data["lists"][list_name] = []

    if username not in chat_data["lists"][list_name]:
        chat_data["lists"][list_name].append(username)
        save_data(data)
        await update.message.reply_html(
            f"✅ <code>@{username}</code> добавлен в список <b>{list_name}</b>!\n"
            f"Можешь добавить ещё или написать /list для управления."
        )
    else:
        await update.message.reply_text(f"⚠️ @{username} уже есть в списке {list_name}.")

    context.user_data.clear()

# ─────────────────────────────────────────────
# /lists — показать все списки
# ─────────────────────────────────────────────
async def show_all_lists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = load_data()
    chat_data = get_chat_data(data, chat_id)
    lists = chat_data.get("lists", {})

    if not lists:
        await update.message.reply_html(
            "📋 Нет созданных списков.\n"
            "Создай через /newlist"
        )
        return

    text = "📋 <b>Все списки чата:</b>\n\n"
    for list_name, users in lists.items():
        text += f"<b>{list_name}</b> ({len(users)} чел.):\n"
        if users:
            text += "  " + ", ".join([f"@{u}" for u in users]) + "\n"
        else:
            text += "  (пусто)\n"
        text += "\n"

    await update.message.reply_html(text)

# ─────────────────────────────────────────────
# /dellist — удалить список
# ─────────────────────────────────────────────
async def del_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = load_data()
    chat_data = get_chat_data(data, chat_id)
    lists = chat_data.get("lists", {})

    if not lists:
        await update.message.reply_text("❌ Нет списков для удаления.")
        return

    if context.args:
        list_name = context.args[0].lower()
        if list_name in lists:
            del lists[list_name]
            save_data(data)
            await update.message.reply_html(f"✅ Список <b>{list_name}</b> удалён.")
        else:
            await update.message.reply_html(f"❌ Список <b>{list_name}</b> не найден.")
        return

    keyboard = []
    for list_name in lists:
        keyboard.append([
            InlineKeyboardButton(f"🗑️ {list_name}", callback_data=f"del_list:{list_name}")
        ])
    await update.message.reply_html(
        "🗑️ <b>Выбери список для удаления:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ─────────────────────────────────────────────
# /members — показать зарег. участников
# ─────────────────────────────────────────────
async def show_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = load_data()
    chat_data = get_chat_data(data, chat_id)
    members = chat_data.get("members", {})

    if not members:
        await update.message.reply_html(
            "👥 Нет зарегистрированных участников.\n"
            "Попросите всех написать /register"
        )
        return

    text = f"👥 <b>Зарегистрированные участники ({len(members)}):</b>\n\n"
    for uid, info in members.items():
        text += f"  • {info['display']}\n"

    await update.message.reply_html(text)

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("❌ Укажите BOT_TOKEN в переменных окружения!")
        print("Пример: export BOT_TOKEN='your_token_here'")
        return

    app = Application.builder().token(token).build()

    # Conversation handler for /newlist
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("newlist", new_list)],
        states={
            WAITING_LIST_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_list_name)
            ],
            WAITING_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("all", mention_all))
    app.add_handler(CommandHandler("list", list_menu))
    app.add_handler(CommandHandler("lists", show_all_lists))
    app.add_handler(CommandHandler("dellist", del_list))
    app.add_handler(CommandHandler("members", show_members))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_message
    ))

    print("🤖 MentionBot запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
