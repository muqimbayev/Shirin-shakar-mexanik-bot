
import logging
import asyncio
import base64
import re
import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, CallbackQueryHandler, filters,
)
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID
from odoo_client import OdooClient

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_debug.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"Loaded TELEGRAM_GROUP_ID: {TELEGRAM_GROUP_ID}")

# State label mapping for repair.order
STATE_LABELS = {
    'draft': 'Yangi',
    'confirmed': 'Biriktirilgan',
    'under_repair': 'Jarayonda',
    'done': 'Hal qilingan',
    'cancel': 'Bekor qilingan',
}

async def edit_or_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    """Safely edit message text or send a new one if it's a media message."""
    query = update.callback_query
    if not query:
        await update.message.reply_html(text, reply_markup=reply_markup)
        return

    try:
        # Check if current message has media
        if query.message.photo or query.message.video or query.message.video_note or query.message.document:
            await query.delete_message()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in edit_or_reply: {e}")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception:
            pass

async def send_any_media(context, chat_id, b64_data, filename, caption, reply_markup=None):
    """Helper to send photo, video or document based on filename extension."""
    if not b64_data:
        return await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", reply_markup=reply_markup)
    
    try:
        file_bytes = base64.b64decode(b64_data)
        ext = filename.lower().split('.')[-1] if filename and '.' in filename else ''
        
        if ext in ['jpg', 'jpeg', 'png', 'webp']:
            return await context.bot.send_photo(chat_id=chat_id, photo=file_bytes, caption=caption[:1024], parse_mode="HTML", reply_markup=reply_markup)
        elif ext in ['mp4', 'mov', 'avi', 'mkv', '3gp']:
            return await context.bot.send_video(chat_id=chat_id, video=file_bytes, caption=caption[:1024], parse_mode="HTML", reply_markup=reply_markup)
        elif ext == 'tgs':
            # Animated stickers are handled as documents
            return await context.bot.send_document(chat_id=chat_id, document=file_bytes, filename=filename, caption=caption[:1024], parse_mode="HTML", reply_markup=reply_markup)
        else:
            return await context.bot.send_document(chat_id=chat_id, document=file_bytes, filename=filename or "file", caption=caption[:1024], parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in send_any_media: {e}")
        return await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", reply_markup=reply_markup)

def get_order_id(order: dict) -> str:
    """Return repair order number (e.g. RO/00001)."""
    return order.get('name', str(order.get('id', '?')))

# Conversation states
PHONE_NUMBER = 0
TICKET_TITLE, TICKET_PRIORITY, TICKET_TEAM, TICKET_DESCRIPTION, TICKET_PHOTO = range(3, 8)
USTA_DEADLINE, USTA_REPORT, USTA_PHOTO, USTA_CANCEL_REASON = range(8, 12)
TICKET_RATING, TICKET_COMMENT = range(12, 14)

ITEMS_PER_PAGE = 5

async def send_ticket_notification(context: ContextTypes.DEFAULT_TYPE, chat_id: int, ticket_data: dict, status_msg: str, reply_markup=None):
    """Helper to send repair order notifications."""
    logger.info(f"Sending notification to {chat_id}: {status_msg}")
    try:
        def clean_html(raw):
            return re.sub(re.compile('<.*?>'), '', raw) if raw else ''

        description = clean_html(ticket_data.get('application_description', ''))

        priority = ticket_data.get('priority')
        emodji = 'Muhumlik darajasi:'
        if priority == '1':
            priority = 'Taklif'; emodji = '🟢 Muhumlik darajasi:'
        elif priority == '2':
            priority = 'Shoshilinch emas'; emodji = '🟡 Muhumlik darajasi:'
        elif priority == '3':
            priority = 'Zarur'; emodji = '🔴 Muhumlik darajasi:'

        msg = (
            f"{status_msg}\n\n"
            f"🆔 <b>ID:</b> {ticket_data.get('name', ticket_data.get('id', '?'))}\n"
            f"👤 <b>Yuboruvchi:</b> {ticket_data.get('sender_name', 'Noma`lum')}\n"
            f"🏢 <b>Bo'lim:</b> {ticket_data.get('department_name', 'Noma`lum')}\n"
            f"📝 <b>Muammo:</b> {description or ticket_data.get('application_name', '-')}\n"
            f"🔧 <b>Usta:</b> {ticket_data.get('usta_name', 'Belgilanmagan')}\n\n"
            f"<b>{emodji}</b> {priority}\n\n"
            f"📅 <b>Sana:</b> {ticket_data.get('create_date', 'Noma`lum')}\n"
        )
        if ticket_data.get('deadline'):
            msg += f"⏳ <b>Muddat:</b> {ticket_data['deadline']}\n"
        if ticket_data.get('report'):
            msg += f"✅ <b>Hisobot:</b> {ticket_data['report']}\n"
        if ticket_data.get('cancel_reason'):
            msg += f"🚫 <b>Sabab:</b> {ticket_data['cancel_reason']}\n"
        if ticket_data.get('cancelled_by'):
            msg += f"👤 <b>Bekor qildi:</b> {ticket_data['cancelled_by']}\n"
        if ticket_data.get('finished_date'):
            msg += f"🏁 <b>Bajarilgan vaqti:</b> {ticket_data['finished_date']}\n"

        photo_b64 = ticket_data.get('photo')
        file_b64 = ticket_data.get('file')
        file_name = ticket_data.get('file_name') or ("photo.jpg" if photo_b64 else "file.dat")
        
        data_to_send = photo_b64 or file_b64
        await send_any_media(context, chat_id, data_to_send, file_name, msg, reply_markup)
    except Exception as e:
        logger.error(f"Error sending notification to {chat_id}: {e}")

# --- REGISTRATION ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data['user_id'] = user.id
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    if employee:
        context.user_data['is_usta'] = client.is_usta(employee['id'])
        await update.message.reply_html(
            f"Assalomu alaykum, {employee['name']}! Qaytganingizdan xursandmiz.",
            reply_markup=get_main_menu_keyboard(context)
        )
        return ConversationHandler.END
    contact_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)]],
        one_time_keyboard=True, resize_keyboard=True
    )
    await update.message.reply_html(
        f"Assalomu alaykum, {user.mention_html()}! Servis botiga xush kelibsiz.\n"
        "Iltimos, telefon raqamingizni yuboring:",
        reply_markup=contact_keyboard
    )
    return PHONE_NUMBER

async def phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.contact
    if not contact:
        await update.message.reply_text("Iltimos, tugmani bosib telefon raqamingizni yuboring.")
        return PHONE_NUMBER
    telegram_id = update.effective_user.id
    client = OdooClient()
    employee = client.get_employee_by_phone(contact.phone_number)
    if employee:
        client.update_employee_telegram_id(employee['id'], telegram_id)
        context.user_data['is_usta'] = client.is_usta(employee['id'])
        await update.message.reply_text(
            f"Profilingiz topildi. Xush kelibsiz, {employee['name']}!",
            reply_markup=get_main_menu_keyboard(context)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "Kechirasiz, raqamingiz tizimda topilmadi. Administrator bilan bog'laning.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    if employee:
        dept_name = employee['department_id'][1] if employee.get('department_id') else "Belgilanmagan"
        phone = employee.get('mobile_phone') or "Yo'q"
        await update.message.reply_html(
            f"👤 <b>Profilingiz:</b>\n\n📛 <b>Ism:</b> {employee['name']}\n"
            f"🏢 <b>Bo'lim:</b> {dept_name}\n📞 <b>Telefon:</b> {phone}\n"
        )
    else:
        await update.message.reply_text("Siz ro'yxatdan o'tmagansiz. /start bosing.")

def get_main_menu_keyboard(context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🛠 Ariza qoldirish", "📂 Mening arizalarim"], ["👤 Profil"]]
    if context.user_data.get('is_usta'):
        keyboard.insert(0, ["🛠 Mening vazifalarim"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- REPAIR ORDER CREATION ---

async def create_ticket_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📝 Muammoni batafsil tushuntirib yozing:",
        reply_markup=ReplyKeyboardMarkup([["Bekor qilish"]], resize_keyboard=True, one_time_keyboard=True)
    )
    return TICKET_DESCRIPTION

async def ticket_description_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    context.user_data['ticket_description'] = text
    context.user_data['ticket_title'] = text[:50] + ("..." if len(text) > 50 else "")
    await update.message.reply_text(
        "📸 Rasm yoki video yuborishingiz mumkin (yoki 'O'tkazib yuborish'):",
        reply_markup=ReplyKeyboardMarkup([["O'tkazib yuborish"], ["Bekor qilish"]], resize_keyboard=True, one_time_keyboard=True)
    )
    return TICKET_PHOTO

async def ticket_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo_data = file_data = file_type = file_name = None
    if getattr(update.message, 'photo', None) and update.message.photo:
        f = await update.message.photo[-1].get_file()
        photo_data = base64.b64encode(await f.download_as_bytearray()).decode('utf-8'); file_name = "photo.jpg"
    elif getattr(update.message, 'video', None) and update.message.video:
        f = await update.message.video.get_file()
        file_data = base64.b64encode(await f.download_as_bytearray()).decode('utf-8'); file_type = 'video'
        file_name = update.message.video.file_name or "video.mp4"
    elif getattr(update.message, 'video_note', None) and update.message.video_note:
        f = await update.message.video_note.get_file()
        file_data = base64.b64encode(await f.download_as_bytearray()).decode('utf-8'); file_type = 'video_note'
        file_name = "video_note.mp4"
    elif getattr(update.message, 'document', None) and update.message.document:
        f = await update.message.document.get_file()
        file_data = base64.b64encode(await f.download_as_bytearray()).decode('utf-8'); file_type = 'document'
        file_name = update.message.document.file_name or "document"
    context.user_data['ticket_photo'] = photo_data
    context.user_data['ticket_file'] = file_data
    context.user_data['ticket_file_type'] = file_type
    context.user_data['ticket_file_name'] = file_name
    keyboard = [
        [InlineKeyboardButton("🔴 Zarur", callback_data="priority_3"),
         InlineKeyboardButton("🟡 Shoshilinch emas", callback_data="priority_2")],
        [InlineKeyboardButton("🟢 Taklif", callback_data="priority_1")]
    ]
    await update.message.reply_text("Zaruriyat darajasini tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return TICKET_PRIORITY

async def ticket_priority_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    priority = query.data.split('_')[1]
    # Map priority: Taklif (1) -> 0, Shoshilinch (2) -> 1, Zarur (3) -> 2
    odoo_priority = str(int(priority))
    
    title = context.user_data.get('ticket_title')
    description = context.user_data.get('ticket_description')
    photo_data = context.user_data.get('ticket_photo')
    file_data = context.user_data.get('ticket_file')
    file_name = context.user_data.get('ticket_file_name')
    file_type = context.user_data.get('ticket_file_type')
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    if not employee:
        if query: await query.edit_message_text("Xatolik: Foydalanuvchi topilmadi.")
        return ConversationHandler.END

    dept_id = employee.get('department_id')[0] if employee.get('department_id') else False
    order_id = client.create_repair(
        title=title, description=description, employee_id=employee['id'],
        department_id=dept_id, photo_data=photo_data, file_data=file_data, file_name=file_name, priority=odoo_priority
    )

    if order_id:
        orders_data = client.execute_kw(
            'repair.order', 'search_read', [[('id', '=', order_id)]],
            {'fields': ['id', 'name', 'application_name', 'application_description',
                        'create_date', 'applicant', 'department', 'priority_custom', 'designated_employee'], 'limit': 1}
        )
        order_name = orders_data[0]['name'] if orders_data else str(order_id)
        if query: await query.delete_message()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Ariza qabul qilindi! Raqami: {order_name}",
            reply_markup=get_main_menu_keyboard(context)
        )
        try:
            if orders_data:
                t_data = orders_data[0]
                desig = t_data.get('designated_employee')
                usta_name = desig[1] if desig and isinstance(desig, list) else "Belgilanmagan"
                dept = employee['department_id'][1] if employee.get('department_id') else "Noma'lum"
                notif_data = {
                    'id': t_data['id'], 'name': t_data['name'],
                    'application_name': t_data.get('application_name', '-'),
                    'application_description': description or '',
                    'create_date': t_data.get('create_date', ''),
                    'sender_name': employee['name'], 'department_name': dept,
                    'usta_name': usta_name, 'photo': photo_data,
                    'file': file_data, 'file_type': file_type, 'file_name': file_name,
                    'priority': t_data.get('priority_custom')
                }
                if TELEGRAM_GROUP_ID:
                    await send_ticket_notification(context, TELEGRAM_GROUP_ID, notif_data, "🆕 <b>Yangi Ariza!</b>")
        except Exception as e:
            logger.error(f"Error sending notifications: {e}")
            import traceback; traceback.print_exc()
    else:
        if query: await query.edit_message_text("❌ Xatolik yuz berdi. Qaytadan urining.")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="...", reply_markup=get_main_menu_keyboard(context))
    return ConversationHandler.END

async def cancel_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Ariza qoldirish bekor qilindi.", reply_markup=get_main_menu_keyboard(context))
    return ConversationHandler.END

# --- MY REPAIRS ---

async def my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_tickets_page(update, context, page=0)

async def show_tickets_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    if not employee:
        await update.message.reply_text("Foydalanuvchi topilmadi.")
        return
    tickets = client.get_employee_repairs(employee['id'], offset=page * ITEMS_PER_PAGE, limit=ITEMS_PER_PAGE + 1)
    has_next = len(tickets) > ITEMS_PER_PAGE
    tickets = tickets[:ITEMS_PER_PAGE]
    if not tickets and page == 0:
        await update.message.reply_text("Sizda arizalar yo'q.")
        return
    msg = "📂 <b>Sizning arizalaringiz:</b>\n\n"
    for t in tickets:
        state_label = STATE_LABELS.get(t.get('state'), t.get('state', 'Yangi'))
        date = t.get('create_date', '')
        desc_short = t.get('application_description', t.get('application_name', '-'))
        def clean_html(raw): return re.sub(re.compile('<.*?>'), '', raw) if raw else '-'
        desc_short = clean_html(desc_short)
        if len(desc_short) > 50: desc_short = desc_short[:50] + "..."
        msg += f"🆔 <b>{t.get('name', t['id'])}</b> | {date}\n📝 {desc_short}\n📊 Holat: {state_label}\n\n"
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"my_tickets_prev_{page}"))
    if has_next:
        nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"my_tickets_next_{page}"))
    keyboard = [nav_row] if nav_row else []
    reply_markup = InlineKeyboardMarkup(keyboard)
    await edit_or_reply(update, context, msg, reply_markup)

async def my_tickets_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if "prev" in data:
        new_page = max(0, int(data.split("_")[-1]) - 1)
    elif "next" in data:
        new_page = int(data.split("_")[-1]) + 1
    else:
        return
    await show_tickets_page(update, context, page=new_page)

# --- USTA HANDLERS ---

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_task_categories(update, context)

async def show_task_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    if not employee:
        await edit_or_reply(update, context, "Xodim topilmadi.")
        return
    counts_data = client.get_repair_counts(employee['id']) or []
    counts = {}
    for item in counts_data:
        state = item.get('state')
        if state:
            counts[state] = item.get('state_count', 0)
    categories = [
        # ('draft', "🆕 Yangi"),
        ('confirmed', "🆕 Biriktirilgan"),
        ('under_repair', "⏳ Jarayonda"),
        ('done', "✅ Hal qilingan"),
        # ('cancel', "🚫 Bekor qilingan"),
    ]
    keyboard = []
    for state, label in categories:
        count = counts.get(state, 0)
        keyboard.append([InlineKeyboardButton(f"{label} ({count})", callback_data=f"usta_cat_{state}")])
    msg = "📂 Arizalar statusini tanlang:"
    await edit_or_reply(update, context, msg, InlineKeyboardMarkup(keyboard))

async def show_tasks_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0, stage_state: str = None) -> None:
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    if not employee: return
    tickets = client.get_assigned_repairs(employee['id'], state=stage_state, offset=page * ITEMS_PER_PAGE, limit=ITEMS_PER_PAGE + 1)
    has_next = len(tickets) > ITEMS_PER_PAGE
    tickets = tickets[:ITEMS_PER_PAGE]
    msg = f"🛠 <b>Mening vazifalarim (Sahifa {page + 1}):</b>\n\n"
    if not tickets:
        msg += "Arizalar mavjud emas."
    keyboard = []
    for ticket in tickets:
        deadline = ticket.get('schedule_date') or ""
        icon = "🔴" if deadline else "🟢"
        order_num = ticket.get('name', str(ticket['id']))
        dept = ticket.get('department')
        dept_label = dept[1][:20] if dept and isinstance(dept, list) else '-'
        app_desc = ticket.get('application_description', ticket.get('application_name', '-'))
        def clean_html(raw): return re.sub(re.compile('<.*?>'), '', raw) if raw else '-'
        app_desc = clean_html(app_desc)
        if len(app_desc) > 30: app_desc = app_desc[:30] + "..."
        msg += f"{icon} <b>{order_num}</b> | {app_desc}\n"
        keyboard.append([InlineKeyboardButton(f"👁 {order_num} | {dept_label}", callback_data=f"usta_task_{ticket['id']}")])
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"usta_tasks_prev_{page}"))
    if has_next:
        nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"usta_tasks_next_{page}"))
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("🔙 Ortga", callback_data="usta_back_cats")])
    query = update.callback_query
    await edit_or_reply(update, context, msg, InlineKeyboardMarkup(keyboard))

async def my_tasks_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("usta_cat_"):
        state = data[len("usta_cat_"):]
        context.user_data['usta_current_stage'] = state
        await show_tasks_page(update, context, page=0, stage_state=state)
        return
    if data == "usta_back_cats":
        await show_task_categories(update, context)
        return
    current_state = context.user_data.get('usta_current_stage')
    if "usta_tasks_next_" in data:
        new_page = int(data.split("_")[-1]) + 1
    elif "usta_tasks_prev_" in data:
        new_page = max(0, int(data.split("_")[-1]) - 1)
    else:
        return
    await show_tasks_page(update, context, page=new_page, stage_state=current_state)

async def task_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        order_id = int(query.data.split("_")[-1])
        client = OdooClient()
        orders = client.execute_kw(
            'repair.order', 'search_read',
            [[('id', '=', order_id)]],
            {'fields': ['id', 'name', 'application_name', 'application_description', 'state',
                        'create_date', 'schedule_date', 'applicant', 'department',
                        'application_file', 'application_file_name', 'designated_employee'], 'limit': 1}
        )
        if not orders:
            await query.edit_message_text("Ariza topilmadi.")
            return
        order = orders[0]
        state = order.get('state', '')
        state_label = STATE_LABELS.get(state, state)

        def clean_html(raw):
            return re.sub(re.compile('<.*?>'), '', raw) if raw else "Izoh yo'q"

        desc = clean_html(order.get('application_description') or '')
        deadline = order.get('schedule_date') or "Belgilanmagan"
        sender_name = order['applicant'][1] if order.get('applicant') else "Noma'lum"
        department = order['department'][1] if order.get('department') and isinstance(order['department'], list) else "Noma'lum"

        # Get phone from applicant employee
        phone = "Yo'q"
        if order.get('applicant'):
            try:
                emp_id = order['applicant'][0]
                emp_data = client.execute_kw('hr.employee', 'read', [[emp_id]], {'fields': ['mobile_phone', 'work_phone']})
                if emp_data:
                    phone = emp_data[0].get('mobile_phone') or emp_data[0].get('work_phone') or "Yo'q"
            except Exception as e:
                logger.error(f"Error fetching employee phone: {e}")

        msg = (
            f"🛠 <b>Ariza tafsilotlari:</b>\n\n"
            f"🆔 <b>Raqami:</b> {order.get('name', order['id'])}\n"
            f"👤 <b>Yuboruvchi:</b> {sender_name}\n"
            f"🏢 <b>Bo'lim:</b> {department}\n"
            f"📞 <b>Tel:</b> {phone}\n"
            f"📝 <b>Muammo:</b> {desc or order.get('application_name', '-')}\n\n"
            f"📊 <b>Holat:</b> {state_label}\n\n"
            f"📅 <b>Sana:</b> {order.get('create_date') or 'Noma`lum'}\n"
            f"⏳ <b>Muddat:</b> {deadline}\n"
        )
        keyboard = []
        closed_states = ['repaired', 'done', 'cancel']
        if state not in closed_states:
            keyboard.append([
                InlineKeyboardButton("▶️ Bajarish", callback_data=f"usta_solve_{order_id}")
            ])
        stage_state_param = context.user_data.get('usta_current_stage', 'confirmed')
        keyboard.append([InlineKeyboardButton("🔙 Ro'yxatga qaytish", callback_data=f"usta_cat_{stage_state_param}")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        photo_b64 = order.get('application_file')
        file_name = order.get('application_file_name') or "photo.jpg"
        if photo_b64:
            if query: await query.delete_message()
            await send_any_media(context, update.effective_chat.id, photo_b64, file_name, msg, reply_markup)
        else:
            await edit_or_reply(update, context, msg, reply_markup)
    except Exception as e:
        logger.error(f"Error viewing task details: {e}")
        if query: await query.edit_message_text("Xatolik yuz berdi.")

# --- USTA WORKFLOW ---

async def start_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    context.user_data['usta_ticket_id'] = order_id
    client = OdooClient()
    client.update_repair(order_id, {'state': 'under_repair'})
    await query.message.reply_text(
        "Arizani bajarish muddati qachon? (Masalan: 2026-02-15 18:00):",
        reply_markup=ReplyKeyboardMarkup([["Ortga"]], resize_keyboard=True)
    )
    return USTA_DEADLINE

async def usta_deadline_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    deadline = update.message.text
    if deadline == "Ortga":
        await update.message.reply_text("Jarayon to'xtatildi.", reply_markup=get_main_menu_keyboard(context))
        return ConversationHandler.END
    order_id = context.user_data.get('usta_ticket_id')
    client = OdooClient()
    try:
        client.update_repair(order_id, {'schedule_date': deadline})
        await update.message.reply_text("Muddat belgilandi. Ariza jarayonga o'tkazildi.", reply_markup=get_main_menu_keyboard(context))
        # Notify sender
        try:
            orders_data = client.execute_kw(
                'repair.order', 'search_read', [[('id', '=', order_id)]],
                {'fields': ['id', 'name', 'application_name', 'application_description',
                            'create_date', 'applicant', 'department'], 'limit': 1}
            )
            if orders_data:
                t_data = orders_data[0]
                usta_name = update.effective_user.full_name
                dept = t_data['department'][1] if t_data.get('department') and isinstance(t_data['department'], list) else "Noma'lum"
                notif_data = {
                    'id': t_data['id'], 'name': t_data['name'],
                    'application_name': t_data.get('application_name', '-'),
                    'application_description': t_data.get('application_description', ''),
                    'create_date': t_data.get('create_date', ''),
                    'deadline': deadline, 'usta_name': usta_name,
                    'sender_name': t_data['applicant'][1] if t_data.get('applicant') else "Noma'lum",
                    'department_name': dept
                }
                sender_id = t_data.get('applicant')
                if sender_id:
                    emp = client.execute_kw('hr.employee', 'read', [[sender_id[0]]], {'fields': ['telegram_id', 'name']})
                    if emp and emp[0].get('telegram_id'):
                        await send_ticket_notification(context, int(emp[0]['telegram_id']), notif_data, "⏳ <b>Arizangiz qabul qilindi va jarayonda!</b>")
        except Exception as e:
            logger.error(f"Error sending start notification: {e}")
            import traceback; traceback.print_exc()
    except Exception as e:
        logger.error(f"Error setting deadline: {e}")
        await update.message.reply_text("Xatolik yuz berdi.", reply_markup=get_main_menu_keyboard(context))
    return ConversationHandler.END

async def solve_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    context.user_data['usta_ticket_id'] = order_id
    await query.message.reply_text(
        "Bajarilgan ish bo'yicha hisobot yozing:",
        reply_markup=ReplyKeyboardMarkup([["Ortga"]], resize_keyboard=True)
    )
    return USTA_REPORT

async def usta_report_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "Ortga":
        await update.message.reply_text("Jarayon to'xtatildi.", reply_markup=get_main_menu_keyboard(context))
        return ConversationHandler.END
    context.user_data['usta_report_text'] = text
    await update.message.reply_text(
        "Bajarilgan ish rasmini yoki videosini yuklang:",
        reply_markup=ReplyKeyboardMarkup([["O'tkazib yuborish"], ["Ortga"]], resize_keyboard=True)
    )
    return USTA_PHOTO

async def usta_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_data = file_type = file_name = None
    if update.message.photo:
        f = await update.message.photo[-1].get_file()
        file_data = base64.b64encode(await f.download_as_bytearray()).decode('utf-8'); file_type = 'photo'; file_name = "report.jpg"
    elif update.message.video:
        f = await update.message.video.get_file()
        file_data = base64.b64encode(await f.download_as_bytearray()).decode('utf-8'); file_type = 'video'
        file_name = update.message.video.file_name or "report.mp4"
    elif update.message.video_note:
        f = await update.message.video_note.get_file()
        file_data = base64.b64encode(await f.download_as_bytearray()).decode('utf-8'); file_type = 'video_note'
        file_name = "report_note.mp4"
    elif update.message.document:
        f = await update.message.document.get_file()
        file_data = base64.b64encode(await f.download_as_bytearray()).decode('utf-8'); file_type = 'document'
        file_name = update.message.document.file_name or "report"
    return await finish_solve_task(update, context, file_data, file_type, file_name)

async def usta_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await finish_solve_task(update, context, None, None, None)

async def finish_solve_task(update: Update, context: ContextTypes.DEFAULT_TYPE, file_data, file_type, file_name) -> int:
    order_id = context.user_data.get('usta_ticket_id')
    report_text = context.user_data.get('usta_report_text')
    client = OdooClient()
    import datetime
    now_utc = datetime.datetime.utcnow()
    finished_odoo = now_utc.strftime('%Y-%m-%d')
    finished_tg = (now_utc + datetime.timedelta(hours=5)).strftime('%Y-%m-%d %H:%M:%S')
    vals = {'state': 'under_repair', 'report_description': report_text, 'finished_date': finished_odoo}
    if file_data:
        vals['report_file'] = file_data
        if file_name: vals['report_file_name'] = file_name
    
    logger.info(f"Attempting to update repair {order_id} to 'done' with vals: { {k: (v[:20] + '...' if isinstance(v, str) and len(v) > 50 else v) for k, v in vals.items()} }")
    try:
        success = client.update_repair(order_id, vals)
        if not success:
            logger.error(f"Failed to update repair {order_id} in Odoo.")
            await update.message.reply_text("❌ Xatolik: Hisobotni Odoo'ga saqlab bo'lmadi. Administratorga murojaat qiling.")
            return ConversationHandler.END
        
        await update.message.reply_text("✅ Ariza hal qilindi!", reply_markup=get_main_menu_keyboard(context))
        try:
            orders_data = client.execute_kw(
                'repair.order', 'search_read', [[('id', '=', order_id)]],
                {'fields': ['id', 'name', 'application_name', 'application_description',
                            'create_date', 'applicant', 'department', 'priority_custom', 'report_file_name'], 'limit': 1}
            )
            if orders_data:
                t_data = orders_data[0]
                usta_name = update.effective_user.full_name
                dept = t_data['department'][1] if t_data.get('department') and isinstance(t_data['department'], list) else "Noma'lum"
                notif_data = {
                    'id': t_data['id'], 'name': t_data['name'],
                    'application_name': t_data.get('application_name', '-'),
                    'application_description': t_data.get('application_description', ''),
                    'create_date': t_data.get('create_date', ''),
                    'report': report_text, 'usta_name': usta_name,
                    'sender_name': t_data['applicant'][1] if t_data.get('applicant') else "Noma'lum",
                    'department_name': dept,
                    'photo': file_data if file_type == 'photo' else None,
                    'file': file_data if file_type != 'photo' else None,
                    'file_name': file_name or t_data.get('report_file_name'),
                    'file_type': file_type, 'priority': t_data.get('priority_custom'),
                    'finished_date': finished_tg
                }
                if TELEGRAM_GROUP_ID:
                    group_keyboard = [
                        [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"chief_approve_{order_id}"), 
                         InlineKeyboardButton("❌ Rad etish", callback_data=f"chief_reject_{order_id}")]
                    ]
                    await send_ticket_notification(
                        context, TELEGRAM_GROUP_ID, notif_data, 
                        "✅ <b>Ariza hal qilindi!</b>\nTasdiqlanishi kutilmoqda...", 
                        reply_markup=InlineKeyboardMarkup(group_keyboard)
                    )
                sender_id = t_data.get('applicant')
                if sender_id:
                    emp = client.execute_kw('hr.employee', 'read', [[sender_id[0]]], {'fields': ['telegram_id']})
                    if emp and emp[0].get('telegram_id'):
                        rating_keyboard = [
                            [InlineKeyboardButton("1. Muammo hal qilinmadi", callback_data=f"rate_1_{order_id}")],
                            [InlineKeyboardButton("2. Juda sekin yoki sifatsiz", callback_data=f"rate_2_{order_id}")],
                            [InlineKeyboardButton("3. O'rtacha", callback_data=f"rate_3_{order_id}")],
                            [InlineKeyboardButton("4. Muammo tez hal qilindi", callback_data=f"rate_4_{order_id}")],
                            [InlineKeyboardButton("5. Juda tez va professional", callback_data=f"rate_5_{order_id}")],
                        ]
                        await send_ticket_notification(
                            context, int(emp[0]['telegram_id']), notif_data,
                            "✅ <b>Arizangiz hal qilindi!</b>\nIltimos, ishni baholang:",
                            reply_markup=InlineKeyboardMarkup(rating_keyboard)
                        )
        except Exception as e:
            logger.error(f"Error sending solve notification: {e}")
            import traceback; traceback.print_exc()
    except Exception as e:
        logger.error(f"Error solving order {order_id}: {e}")
        await update.message.reply_text("Xatolik yuz berdi.", reply_markup=get_main_menu_keyboard(context))
    return ConversationHandler.END

async def chief_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    
    client = OdooClient()
    chief_name = client.get_chief_mechanic_name(user_id)
    if not chief_name:
        await query.answer("Siz tasdiqlash uchun huquqqa ega emassiz.", show_alert=True)
        return

    data_parts = query.data.split('_')
    action = data_parts[1]
    order_id = data_parts[2]
    
    current_text = query.message.text or query.message.caption or ""
    
    if action == "approve":
        try:
            client.update_repair(int(order_id), {'state': 'done'})
            await query.answer("Tasdiqlandi!")
            new_text = current_text.replace("Tasdiqlanishi kutilmoqda...", f"✅ <b>{chief_name} tomonidan tasdiqlandi.</b>")
            if query.message.text:
                await query.edit_message_text(new_text, parse_mode="HTML")
            else:
                await query.edit_message_caption(caption=new_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Approval error: {e}")
    elif action == "reject":
        try:
            client.update_repair(int(order_id), {'state': 'under_repair'})
            await query.answer("Rad etildi!")
            new_text = current_text.replace("Tasdiqlanishi kutilmoqda...", f"❌ <b>{chief_name} tomonidan rad etildi!</b>")
            if query.message.text:
                await query.edit_message_text(new_text, parse_mode="HTML")
            else:
                await query.edit_message_caption(caption=new_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Rejection error: {e}")

    # Notify the designated Usta
    try:
        order_info = client.execute_kw('repair.order', 'read', [[int(order_id)]], {'fields': ['name', 'designated_employee']})
        if order_info:
            ticket_name = order_info[0].get('name', 'Noma`lum')
            desig_emp = order_info[0].get('designated_employee')
            if desig_emp:
                emp_info = client.execute_kw('hr.employee', 'read', [[desig_emp[0]]], {'fields': ['telegram_id']})
                if emp_info and emp_info[0].get('telegram_id'):
                    usta_tg_id = emp_info[0]['telegram_id']
                    if action == "approve":
                        msg = f"✅ <b>{ticket_name}</b> raqamli ariza bo'yicha bajargan ishingiz bosh mexanik ({chief_name}) tasdiqladi."
                    else:
                        msg = f"❌ <b>{ticket_name}</b> raqamli ariza bo'yicha bajargan ishingiz bosh mexanik ({chief_name}) rad etdi. Iltimos jarayonga qayting."
                    await context.bot.send_message(chat_id=int(usta_tg_id), text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error notifying Usta: {e}")

# --- RATING SYSTEM ---

async def ticket_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data_parts = query.data.split("_")
    rating = data_parts[1]
    order_id = data_parts[2]
    context.user_data['rate_ticket_id'] = order_id
    context.user_data['rate_value'] = rating
    client = OdooClient()
    order_info = client.execute_kw('repair.order', 'read', [[int(order_id)]], {'fields': ['rating']})
    if order_info and order_info[0].get('rating'):
        msg = "Siz ushbu ariza uchun allaqachon baho bergansiz. Rahmat!"
        try:
            if query.message.text:
                await query.edit_message_text(msg)
            else:
                await query.edit_message_caption(caption=msg)
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
        return ConversationHandler.END

    rating_labels = {
        '1': "1. Muammo hal qilinmadi",
        '2': "2. Juda sekin yoki sifatsiz",
        '3': "3. O'rtacha",
        '4': "4. Muammo tez hal qilindi",
        '5': "5. Juda tez va professional"
    }
    label = rating_labels.get(rating, rating)

    # Save rating immediately so it's not lost even if user ignores the comment step
    client_save = OdooClient()
    client_save.update_repair(int(order_id), {'rating': rating})
    logger.info(f"Rating {rating} saved immediately for order {order_id}")

    msg_text = f"✅ Bahoyingiz qabul qilindi: <b>{label}</b>\n\nIstasangiz, izoh ham yozib qoldirishingiz mumkin (ixtiyoriy):"
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Could not remove reply markup: {e}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=msg_text, parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["O'tkazib yuborish"]], resize_keyboard=True)
    )
    return TICKET_COMMENT

async def ticket_comment_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    comment = update.message.text
    order_id = context.user_data.get('rate_ticket_id')
    if comment == "O'tkazib yuborish" or not comment:
        await update.message.reply_text("Rahmat! Bahoyingiz qabul qilindi.", reply_markup=get_main_menu_keyboard(context))
        return ConversationHandler.END
    # Save the optional comment
    if order_id:
        client = OdooClient()
        try:
            client.update_repair(int(order_id), {'rating_description': comment})
            logger.info(f"Comment saved for order {order_id}")
        except Exception as e:
            logger.error(f"Error saving comment for order {order_id}: {e}")
    await update.message.reply_text("Izohingiz uchun rahmat!", reply_markup=get_main_menu_keyboard(context))
    return ConversationHandler.END

async def cancel_usta_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Bekor qilindi.", reply_markup=get_main_menu_keyboard(context))
    return ConversationHandler.END

def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set.")
        return
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(60).write_timeout(60).connect_timeout(60).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={PHONE_NUMBER: [MessageHandler(filters.CONTACT, phone_input)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    ticket_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛠 Ariza qoldirish$"), create_ticket_start)],
        states={

            TICKET_DESCRIPTION: [
                MessageHandler(filters.Regex("^Bekor qilish$"), cancel_ticket),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_description_input)
            ],
            TICKET_PHOTO: [
                MessageHandler(filters.Regex("^Bekor qilish$"), cancel_ticket),
                MessageHandler(
                    (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL) & ~filters.COMMAND,
                    ticket_photo_input
                )
            ],
            TICKET_PRIORITY: [CallbackQueryHandler(ticket_priority_choice, pattern="^priority_")],
        },
        fallbacks=[CommandHandler("cancel", cancel_ticket), MessageHandler(filters.Regex("^Bekor qilish$"), cancel_ticket)],
    )
    application.add_handler(ticket_conv_handler)

    application.add_handler(MessageHandler(filters.Regex("^👤 Profil$"), view_profile))
    application.add_handler(MessageHandler(filters.Regex("^📂 Mening arizalarim$"), my_tickets))
    application.add_handler(CallbackQueryHandler(my_tickets_pagination, pattern="^my_tickets_"))
    application.add_handler(MessageHandler(filters.Regex("^🛠 Mening vazifalarim$"), my_tasks))
    application.add_handler(CallbackQueryHandler(my_tasks_pagination, pattern="^(usta_tasks_|usta_cat_|usta_back_cats)"))
    application.add_handler(CallbackQueryHandler(task_details, pattern="^usta_task_"))
    application.add_handler(CallbackQueryHandler(chief_approval_callback, pattern="^chief_"))

    usta_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_task, pattern="^usta_start_"),
            CallbackQueryHandler(solve_task, pattern="^usta_solve_")
        ],
        states={
            USTA_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, usta_deadline_input)],
            USTA_REPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, usta_report_input)],
            USTA_PHOTO: [
                MessageHandler(filters.Regex("^O'tkazib yuborish$"), usta_skip_photo),
                MessageHandler(filters.Regex("^Ortga$"), usta_skip_photo), # Map Ortga to skip or handle separately
                MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL) & ~filters.COMMAND, usta_photo_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_usta_flow)],
    )
    application.add_handler(usta_conv_handler)

    rating_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(ticket_rating_callback, pattern="^rate_")],
        states={TICKET_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_comment_input)]},
        fallbacks=[CommandHandler("cancel", cancel_usta_flow)],
        allow_reentry=True
    )
    application.add_handler(rating_conv_handler)

    application.run_polling()

if __name__ == "__main__":
    main()
