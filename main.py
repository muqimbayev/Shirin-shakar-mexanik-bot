
import logging
import asyncio
import base64
import re
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID
from odoo_client import OdooClient

# Enable logging
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

def get_ticket_id(ticket: dict) -> str:
    """Return a clean ticket ID: custom if it looks valid (TS/XXXXX), else DB id."""
    custom = ticket.get('x_studio_ariza_raqami')
    if custom and isinstance(custom, str) and custom.startswith('TS/'):
        return custom
    return str(ticket.get('id', '?'))

# States for Registration
FULL_NAME, DEPARTMENT, PHONE_NUMBER = range(3)
# States for Ticket Creation
TICKET_TITLE, TICKET_TEAM, TICKET_DESCRIPTION, TICKET_PHOTO = range(3, 7)
# States for Usta Workflow
USTA_DEADLINE, USTA_REPORT, USTA_PHOTO, USTA_CANCEL_REASON = range(7, 11)

ITEMS_PER_PAGE = 5

async def send_ticket_notification(context: ContextTypes.DEFAULT_TYPE, chat_id: int, ticket_data: dict, status_msg: str):
    """Helper to send ticket notifications with consistent formatting."""
    logger.info(f"Preparing to send notification to {chat_id} with status {status_msg}")
    try:
        def clean_html(raw_html):
            cleanr = re.compile('<.*?>')
            cleantext = re.sub(cleanr, '', raw_html)
            return cleantext

        description = ticket_data.get('description', 'Izoh yo`q')
        if description:
             description = clean_html(description)

        msg = (
            f"{status_msg}\n\n"
            f"🆔 <b>ID:</b> {ticket_data.get('x_studio_ariza_raqami', ticket_data['id'])}\n"
            f"👤 <b>Yuboruvchi:</b> {ticket_data.get('sender_name', 'Noma`lum')}\n"
            f"🏢 <b>Bo'lim:</b> {ticket_data.get('department_name', 'Noma`lum')}\n"
            f"📝 <b>Mavzu:</b> {ticket_data['name']}\n"
            f"🔧 <b>Usta:</b> {ticket_data.get('usta_name', 'Belgilanmagan')}\n\n"
            f"📄 <b>Batafsil:</b> {description}\n\n"
            f"📅 <b>Sana:</b> {ticket_data.get('x_studio_berilgan_sana', 'Noma`lum')}\n"
        )
        
        # Add extra fields if available (e.g. deadline, report, reason)
        if ticket_data.get('deadline'):
            msg += f"⏳ <b>Muddat:</b> {ticket_data['deadline']}\n"
        if ticket_data.get('report'):
            msg += f"✅ <b>Hisobot:</b> {ticket_data['report']}\n"
        if ticket_data.get('cancel_reason'):
            msg += f"🚫 <b>Sabab:</b> {ticket_data['cancel_reason']}\n"
        if ticket_data.get('cancelled_by'):
            msg += f"👤 <b>Bekor qildi:</b> {ticket_data['cancelled_by']}\n"

        photo_data_b64 = ticket_data.get('photo', None)
        if photo_data_b64:
            try:
                photo_bytes = base64.b64decode(photo_data_b64)
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_bytes,
                    caption=msg[:1024],
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending photo in notification: {e}")
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Error sending notification to {chat_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Check if user is registered. If not, start registration."""
    user = update.effective_user
    context.user_data['user_id'] = user.id
    
    # Check if user already exists
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    
    if employee:
        # Already registered
        context.user_data['is_usta'] = client.is_usta(employee['id'])
        await update.message.reply_html(
            f"Assalomu alaykum, {employee['name']}! Qaytganingizdan xursandmiz.",
            reply_markup=get_main_menu_keyboard(context)
        )
        return ConversationHandler.END
    
    # New user: Ask for Phone Number FIRST
    contact_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)]],
        one_time_keyboard=True,
        resize_keyboard=True
    )
    
    await update.message.reply_html(
        f"Assalomu alaykum, {user.mention_html()}! Shirin shakar kompaniyasi servis botiga xush kelibsiz\n"
        "Iltimos, avval telefon raqamingizni yuboring (pastdagi tugmani bosing):",
        reply_markup=contact_keyboard
    )
    return PHONE_NUMBER

async def phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle phone number, check existance, or ask for name."""
    contact = update.message.contact
    if not contact:
        await update.message.reply_text("Iltimos, tugmani bosib telefon raqamingizni yuboring.")
        return PHONE_NUMBER
        
    phone_number = contact.phone_number
    # Basic cleanup if needed, but usually OK.
    
    telegram_id = update.effective_user.id
    client = OdooClient()
    
    # Check if employee exists with this phone
    existing_employee = client.get_employee_by_phone(phone_number)
    
    if existing_employee:
        # Update
        client.update_employee_telegram_id(existing_employee['id'], telegram_id)
        context.user_data['is_usta'] = client.is_usta(existing_employee['id'])
        
        await update.message.reply_text(
            f"Sizning profilingiz topildi va Telegram hisobingiz ulandi.\nXush kelibsiz, {existing_employee['name']}!",
            reply_markup=get_main_menu_keyboard(context)
        )
        return ConversationHandler.END
    else:
        # Not found: Proceed to Registration
        context.user_data['phone_number'] = phone_number
        await update.message.reply_text(
            "Tizimda ushbu raqamga ega xodim topilmadi.\n"
            "Iltimos, ro'yxatdan o'tish uchun Ism va Familiyangizni kiriting:",
            reply_markup=ReplyKeyboardRemove()
        )
        return FULL_NAME

async def full_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save name and ask for department."""
    user_name = update.message.text
    context.user_data['full_name'] = user_name
    
    client = OdooClient()
    departments = client.get_departments() # Root departments
    
    if not departments:
        # Fallback if no departments found
        await update.message.reply_text("Bo'limlar topilmadi. Iltimos administratorga murojaat qiling.")
        return ConversationHandler.END
        
    keyboard = []
    for dept in departments:
        keyboard.append([InlineKeyboardButton(dept['name'], callback_data=f"dept_{dept['id']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Rahmat, {user_name}. Endi bo'limingizni tanlang:",
        reply_markup=reply_markup
    )
    return DEPARTMENT

async def department_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle department selection (drill down or confirm)."""
    query = update.callback_query
    await query.answer()
    
    dept_id = int(query.data.split('_')[1])
    client = OdooClient()
    
    # Check for sub-departments
    sub_departments = client.get_departments(parent_id=dept_id)
    
    if sub_departments:
        # Show sub-departments
        keyboard = []
        for dept in sub_departments:
            keyboard.append([InlineKeyboardButton(dept['name'], callback_data=f"dept_{dept['id']}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="Iltimos, quyi bo'limni tanlang:",
            reply_markup=reply_markup
        )
        return DEPARTMENT # Stay in this state
    else:
        # No more sub-departments, selection final
        dept_id = int(query.data.split('_')[1])
        # We need to ensure we have phone number and name
        phone_number = context.user_data.get('phone_number')
        name = context.user_data.get('full_name')
        telegram_id = update.effective_user.id
        
        if not phone_number or not name:
            await query.edit_message_text("Xatolik: Ma'lumotlar yetarli emas. Iltimos /start bosib qaytadan urining.")
            return ConversationHandler.END
             
        # Create Employee
        try:
            client.create_employee(name, dept_id, phone_number, telegram_id)
            await query.delete_message()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Muvaffaqiyatli ro'yxatdan o'tdingiz!",
                reply_markup=get_main_menu_keyboard(context)
            )
        except Exception as e:
            logger.error(f"Error creating employee: {e}")
            await query.edit_message_text("Ro'yxatdan o'tishda xatolik yuz berdi.")
            
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    await update.message.reply_text(
        "Ro'yxatdan o'tish bekor qilindi.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user profile."""
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    
    if employee:
        dept_name = employee['department_id'][1] if employee.get('department_id') else "Belgilanmagan"
        phone = employee.get('mobile_phone') or "Yo'q"
        await update.message.reply_html(
            f"👤 <b>Sizning profilingiz:</b>\n\n"
            f"📛 <b>Ism:</b> {employee['name']}\n"
            f"🏢 <b>Bo'lim:</b> {dept_name}\n"
            f"📞 <b>Telefon:</b> {phone}\n"
        )
    else:
        await update.message.reply_text("Siz hali ro'yxatdan o'tmagansiz. /start buyrug'ini bosing.")

def get_main_menu_keyboard(context: ContextTypes.DEFAULT_TYPE):
    """Return main menu keyboard based on user role."""
    keyboard = [
        ["🛠 Ariza qoldirish", "📂 Mening arizalarim"],
        ["👤 Profil"]
    ]
    
    if context.user_data.get('is_usta'):
        keyboard.insert(0, ["🛠 Mening vazifalarim"])
        
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- Ticket Creation Flow ---

async def create_ticket_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start ticket creation."""
    await update.message.reply_text(
        "📝 Ariza sarlavhasini kiriting (qisqacha mazmuni):",
        reply_markup=ReplyKeyboardMarkup([["Bekor qilish"]], resize_keyboard=True, one_time_keyboard=True)
    )
    return TICKET_TITLE

async def ticket_title_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save title and ask for Team."""
    context.user_data['ticket_title'] = update.message.text
    
    client = OdooClient()
    teams = client.get_helpdesk_teams()
    
    if not teams:
        await update.message.reply_text("Xatolik: Bo'limlar topilmadi.")
        return ConversationHandler.END
        
    keyboard = []
    for team in teams:
        keyboard.append([InlineKeyboardButton(team['name'], callback_data=f"team_{team['id']}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Jamoani tanlang:", reply_markup=reply_markup)
    return TICKET_TEAM

async def ticket_team_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save team and ask for Description."""
    query = update.callback_query
    await query.answer()
    
    team_id = int(query.data.split('_')[-1])
    context.user_data['ticket_team_id'] = team_id
    
    await query.edit_message_text(f"Tanlangan jamoa ID: {team_id}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="📄 Ariza matnini batafsil yozing:",
        reply_markup=ReplyKeyboardMarkup([["Bekor qilish"]], resize_keyboard=True, one_time_keyboard=True)
    )
    return TICKET_DESCRIPTION

async def ticket_description_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save description and ask for Photo."""
    context.user_data['ticket_description'] = update.message.text
    
    await update.message.reply_text(
        "📸 Rasm yuborishingiz mumkin (yoki 'O'tkazib yuborish' deb yozing/bosing):",
        reply_markup=ReplyKeyboardMarkup([["O'tkazib yuborish"], ["Bekor qilish"]], resize_keyboard=True, one_time_keyboard=True)
    )
    return TICKET_PHOTO

async def ticket_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save photo (optional) and create ticket."""
    photo_data = None
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        photo_data = base64.b64encode(photo_bytes).decode('utf-8')
    
    # Create Ticket
    title = context.user_data.get('ticket_title')
    team_id = context.user_data.get('ticket_team_id')
    description = context.user_data.get('ticket_description')
    user = update.effective_user
    
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    
    if not employee:
        await update.message.reply_text("Xatolik: Foydalanuvchi topilmadi.")
        return ConversationHandler.END
    
    import datetime
    now = datetime.datetime.now()
    
    ticket_number = client.create_ticket(
        title=title,
        description=description,
        team_id=team_id,
        employee_id=employee['id'],
        department_id=employee.get('department_id')[0] if employee.get('department_id') else False,
        date=now,
        photo_data=photo_data
    )
    
    if ticket_number:
        if isinstance(ticket_number, int):
             msg = f"✅ Ariza qabul qilindi! ID: {ticket_number}"
        else:
             msg = f"✅ Ariza qabul qilindi! ID: {ticket_number}"
             
        await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(context))
        
        # --- Notifications ---
        try:
            # 1. Fetch full ticket details for notification
            ticket_id = ticket_number if isinstance(ticket_number, int) else None
            # If ticket_number is string (custom ID), we need real ID? 
            # create_ticket returns ID (int) usually, but my wrapper returns custom string if found.
            # Let's check create_ticket implementation. 
            # It returns custom ID string if found, else ID int.
            # We need Real ID to fetch details or just use what we have? 
            # We need to fetch details to get department name, usta name etc.
            
            # Simple approach: Search by custom ID or ID
            domain = []
            if isinstance(ticket_number, int):
                domain = [('id', '=', ticket_number)]
            else:
                domain = [('x_studio_ariza_raqami', '=', ticket_number)]
                
            tickets_data = client.execute_kw(
                'helpdesk.ticket', 'search_read',
                [domain],
                {'fields': ['id', 'name', 'x_studio_ariza_raqami', 'description', 'x_studio_berilgan_sana', 'team_id', 'x_studio_ariza_yuboruvchi', 'x_studio_bolim'], 'limit': 1}
            )
            
            if tickets_data:
                t_data = tickets_data[0]
                
                # Fetch Usta name from team
                usta_name = "Belgilanmagan"
                team_data = t_data.get('team_id')
                if team_data:
                    teams = client.execute_kw('helpdesk.team', 'read', [[team_data[0]]], {'fields': ['x_studio_masul_xodim']})
                    if teams and teams[0].get('x_studio_masul_xodim'):
                        masul_id = teams[0]['x_studio_masul_xodim'][0]
                        emp = client.execute_kw('hr.employee', 'read', [[masul_id]], {'fields': ['name']})
                        if emp:
                            usta_name = emp[0]['name']
                
                # Prepare notification data
                notif_data = {
                    'id': t_data['id'],
                    'x_studio_ariza_raqami': t_data.get('x_studio_ariza_raqami', t_data['id']),
                    'name': t_data['name'],
                    'description': context.user_data.get('ticket_description'),
                    'x_studio_berilgan_sana': t_data.get('x_studio_berilgan_sana'),
                    'sender_name': t_data['x_studio_ariza_yuboruvchi'][1] if t_data.get('x_studio_ariza_yuboruvchi') else "Noma'lum",
                    'department_name': t_data['x_studio_bolim'][1] if t_data.get('x_studio_bolim') else "Noma'lum",
                    'usta_name': usta_name,
                    'photo': photo_data
                }
                
                # Notify Group
                if TELEGRAM_GROUP_ID:
                    await send_ticket_notification(context, TELEGRAM_GROUP_ID, notif_data, "🆕 <b>Yangi Ariza!</b>")
                    
                # Notify Usta (Find Team Leader / Masul Xodim)
                team_id = t_data.get('team_id')
                if team_id:
                    # Get Team details to find masul xodim
                    teams = client.execute_kw('helpdesk.team', 'read', [[team_id[0]]], {'fields': ['x_studio_masul_xodim']})
                    if teams and teams[0].get('x_studio_masul_xodim'):
                        masul_id = teams[0]['x_studio_masul_xodim'][0]
                        # Get Employee Telegram ID
                        emp = client.execute_kw('hr.employee', 'read', [[masul_id]], {'fields': ['x_studio_telegram_id', 'name']})
                        if emp and emp[0].get('x_studio_telegram_id'):
                            tg_id = emp[0]['x_studio_telegram_id']
                            try:
                                await send_ticket_notification(context, int(tg_id), notif_data, "🆕 <b>Sizga yangi ariza biriktirildi!</b>")
                            except Exception as e:
                                logger.error(f"Failed to notify Usta {tg_id}: {e}")

        except Exception as e:
            logger.error(f"Error sending notifications: {e}")

    else:
        await update.message.reply_text("❌ Xatolik yuz berdi. Qaytadan urining.", reply_markup=get_main_menu_keyboard(context))
        
    return ConversationHandler.END

async def cancel_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel ticket creation."""
    await update.message.reply_text("Ariza qoldirish bekor qilindi.", reply_markup=get_main_menu_keyboard(context))
    return ConversationHandler.END

# --- My Tickets Listing ---

async def my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of user's tickets."""
    await show_tickets_page(update, context, page=0)

async def show_tickets_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    
    if not employee:
        await update.message.reply_text("Foydalanuvchi topilmadi.")
        return

    tickets = client.get_employee_tickets(employee['id'], offset=page * ITEMS_PER_PAGE, limit=ITEMS_PER_PAGE + 1)
    
    has_next = len(tickets) > ITEMS_PER_PAGE
    tickets = tickets[:ITEMS_PER_PAGE]
    
    if not tickets and page == 0:
        await update.message.reply_text("Sizda arizalar yo'q.")
        return
        
    msg = "📂 <b>Sizning arizalaringiz:</b>\n\n"
    for t in tickets:
        stage = t['stage_id'][1] if t.get('stage_id') else "Yangi"
        date = t.get('x_studio_berilgan_sana', '')
        # Use custom ticket number if available and valid, else database ID
        ticket_display_id = get_ticket_id(t)
        msg += f"🆔 <b>{ticket_display_id}</b> | {date}\n📝 {t['name']}\n📊 Holat: {stage}\n\n"
        
    keyboard = []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"my_tickets_prev_{page}"))
    if has_next:
        nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"my_tickets_next_{page}"))
        
    if nav_row:
        keyboard.append(nav_row)
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_html(msg, reply_markup=reply_markup)

async def my_tickets_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if "prev" in data:
        current_page = int(data.split("_")[-1])
        new_page = max(0, current_page - 1)
    elif "next" in data:
        current_page = int(data.split("_")[-1])
        new_page = current_page + 1
    else:
        return
        
    await show_tickets_page(update, context, page=new_page)

# --- USTA (MASTER) HANDLERS ---

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for 'Mening vazifalarim' button."""
    await show_task_categories(update, context)

async def show_task_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show categories with counts."""
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    
    if not employee:
        await update.message.reply_text("Xodim topilmadi.")
        return
        
    team_ids = client.get_managed_teams(employee['id'])
    if not team_ids:
        await update.message.reply_text("Sizga biriktirilgan jamoalar yo'q.")
        return
        
    counts_data = client.get_task_counts(team_ids)
    # Process counts_data: [{'stage_id': [1, 'New'], 'stage_id_count': 5}, ...]
    counts = {}
    for item in counts_data:
        stage = item.get('stage_id')
        if stage:
            counts[stage[0]] = item.get('stage_id_count', 0)
            
    categories = [
        (1, "🆕 Yangi"),
        (2, "⏳ Jarayonda"),
        (4, "✅ Hal qilingan"),
        (5, "🚫 Bekor qilingan")
    ]
    
    keyboard = []
    for stage_id, name in categories:
        count = counts.get(stage_id, 0)
        text = f"{name} ({count})"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"usta_cat_{stage_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = "📂 Arizalar bo'limini tanlang:"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

async def show_tasks_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0, stage_id: int = None) -> None:
    """Show paginated tasks, optionally filtered by stage."""
    user = update.effective_user
    client = OdooClient()
    employee = client.get_employee_by_telegram_id(user.id)
    
    if not employee: return

    team_ids = client.get_managed_teams(employee['id'])
    # Fetch one extra to check if next page exists
    tickets = client.get_team_tickets(team_ids, stage_id=stage_id, offset=page * ITEMS_PER_PAGE, limit=ITEMS_PER_PAGE + 1)
    
    has_next = len(tickets) > ITEMS_PER_PAGE
    tickets = tickets[:ITEMS_PER_PAGE]
    
    msg = f"🛠 <b>Mening vazifalarim (Page {page + 1}):</b>\n\n"
    if not tickets:
        msg += "Arizalar mavjud emas."
    
    keyboard = []
    for ticket in tickets:
        # Check deadline
        deadline = ticket.get('sla_deadline') or ticket.get('x_studio_muddati') or ""
        icon = "🔴" if deadline else "🟢"
        
        ticket_id_display = get_ticket_id(ticket)
        ticket_db_id = ticket['id']
        
        msg += f"{icon} <b>{ticket_id_display}</b> | {ticket['name']}\n"
        
        # Add button to view details
        keyboard.append([InlineKeyboardButton(
            f"👁 Ko'rish: {ticket_id_display} | {ticket['name'][:20]}",
            callback_data=f"usta_task_{ticket_db_id}"
        )])
    
    # Pagination Keyboard
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"usta_tasks_prev_{page}"))
    if has_next:
        nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"usta_tasks_next_{page}"))
        
    if nav_row:
        keyboard.append(nav_row)
        
    keyboard.append([InlineKeyboardButton("🔙 Ortga", callback_data="usta_back_cats")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    query = update.callback_query
    if query:
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_html(msg, reply_markup=reply_markup)

async def my_tasks_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for pagination buttons."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Check if category selection
    if data.startswith("usta_cat_"):
        stage_id = int(data.split("_")[-1])
        context.user_data['usta_current_stage'] = stage_id
        await show_tasks_page(update, context, page=0, stage_id=stage_id)
        return
        
    if data == "usta_back_cats":
        await show_task_categories(update, context)
        return
    
    current_stage = context.user_data.get('usta_current_stage')
    
    if "usta_tasks_next_" in data:
        current_page = int(data.split("_")[-1])
        new_page = current_page + 1
    elif "usta_tasks_prev_" in data:
        current_page = int(data.split("_")[-1])
        new_page = max(0, current_page - 1)
    else:
        return
        
    await show_tasks_page(update, context, page=new_page, stage_id=current_stage)


async def task_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show details of a specific task."""
    query = update.callback_query
    await query.answer()
    
    try:
        ticket_id = int(query.data.split("_")[-1])
        client = OdooClient()
        
        tickets = client.execute_kw(
            'helpdesk.ticket', 'search_read', 
            [[('id', '=', ticket_id)]],
            {'fields': ['id', 'name', 'stage_id', 'description', 'x_studio_berilgan_sana', 'x_studio_muddati', 'x_studio_ariza_raqami', 'x_studio_ariza_yuboruvchi', 'x_studio_bolim', 'x_studio_related_field_2pj_1jg9o6rpt', 'x_studio_binary_field_9hi_1jg9o8v5j'], 'limit': 1}
        )
        
        if not tickets:
            await query.edit_message_text("Ariza topilmadi.")
            return
            
        ticket = tickets[0]
        stage_id = ticket['stage_id'][0] if ticket.get('stage_id') else 0
        stage_name = ticket['stage_id'][1] if ticket.get('stage_id') else "Noma'lum"
        
        def clean_html(raw_html):
            cleanr = re.compile('<.*?>')
            cleantext = re.sub(cleanr, '', raw_html)
            return cleantext
            
        desc_raw = ticket.get('description') or "Izoh yo'q"
        desc = clean_html(desc_raw)
        
        deadline = ticket.get('x_studio_muddati') or "Belgilanmagan"
        sender_name = ticket['x_studio_ariza_yuboruvchi'][1] if ticket.get('x_studio_ariza_yuboruvchi') else "Noma'lum"
        
        # Safe access to department
        department = "Noma'lum"
        if ticket.get('x_studio_bolim'):
             department = ticket['x_studio_bolim'][1]
        
        phone = ticket.get('x_studio_related_field_2pj_1jg9o6rpt')
        
        # Fallback: Fetch phone from Employee if missing
        if not phone and ticket.get('x_studio_ariza_yuboruvchi'):
            try:
                emp_id = ticket['x_studio_ariza_yuboruvchi'][0]
                emp_data = client.execute_kw('hr.employee', 'read', [[emp_id], ['mobile_phone', 'work_phone']])
                if emp_data:
                    phone = emp_data[0].get('mobile_phone') or emp_data[0].get('work_phone')
            except Exception as e:
                logger.error(f"Error fetching employee phone: {e}")
                
        phone = phone or "Yo'q"
        
        msg = (
            f"🛠 <b>Ariza tafsilotlari:</b>\n\n"
            f"🆔 <b>ID:</b> {ticket.get('x_studio_ariza_raqami', ticket['id'])}\n"
            f"👤 <b>Yuboruvchi:</b> {sender_name}\n"
            f"🏢 <b>Bo'lim:</b> {department}\n"
            f"📞 <b>Tel:</b> {phone}\n"
            f"📝 <b>Mavzu:</b> {ticket['name']}\n\n"
            f"📄 <b>Batafsil:</b> {desc}\n"
            f"📊 <b>Holat:</b> {stage_name}\n\n"
            f"📅 <b>Sana:</b> {ticket.get('x_studio_berilgan_sana') or 'Noma`lum'}\n"
            f"⏳ <b>Muddat:</b> {deadline}\n"
        )
        
        keyboard = []
        # Action Buttons
        if stage_id == 1: # New
            keyboard.append([
                InlineKeyboardButton("▶️ Bajarishga olish", callback_data=f"usta_start_{ticket_id}"),
                InlineKeyboardButton("🚫 Bekor qilish", callback_data=f"usta_cancel_{ticket_id}")
            ])
        elif stage_id == 2: # In Progress
            keyboard.append([
                InlineKeyboardButton("✅ Hal qilish", callback_data=f"usta_solve_{ticket_id}"),
                InlineKeyboardButton("🚫 Bekor qilish", callback_data=f"usta_cancel_{ticket_id}")
            ])
            
        stage_id_param = context.user_data.get('usta_current_stage', 0)
        keyboard.append([InlineKeyboardButton("🔙 Ro'yxatga qaytish", callback_data=f"usta_cat_{stage_id_param}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Check for photo
        photo_data_b64 = ticket.get('x_studio_binary_field_9hi_1jg9o8v5j')
        if photo_data_b64:
            try:
                photo_bytes = base64.b64decode(photo_data_b64)
                await query.delete_message()
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo_bytes,
                    caption=msg[:1024], # Caption limit
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error sending photo: {e}")
                await query.edit_message_text(msg + "\n(Rasm yuklashda xatolik)", parse_mode="HTML", reply_markup=reply_markup)
        else:
             await query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
            
    except Exception as e:
        logger.error(f"Error viewing task details: {e}")
        await query.edit_message_text("Xatolik yuz berdi.")

# --- Usta Workflow Handlers ---

async def start_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Move task to In Progress and ask for deadline."""
    query = update.callback_query
    await query.answer()
    
    ticket_id = int(query.data.split("_")[-1])
    context.user_data['usta_ticket_id'] = ticket_id
    
    client = OdooClient()
    # Update stage to In Progress (2)
    client.update_ticket(ticket_id, {'stage_id': 2})
    
    await query.message.reply_text(
        "Arizani bajarish muddati qachon? (Masalan: 2026-02-15 18:00):",
        reply_markup=ReplyKeyboardMarkup([["Bekor qilish"]], resize_keyboard=True)
    )
    return USTA_DEADLINE

async def usta_deadline_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save deadline."""
    deadline = update.message.text
    if deadline == "Bekor qilish":
        await update.message.reply_text("Jarayon bekor qilindi.", reply_markup=get_main_menu_keyboard(context))
        return ConversationHandler.END
        
    ticket_id = context.user_data.get('usta_ticket_id')
    client = OdooClient()
    
    try:
        # Assuming deadline is text for now, or validate datetime format
        vals = {'x_studio_muddati': deadline}
        client.update_ticket(ticket_id, vals)
        await update.message.reply_text("Muddat belgilandi. Ariza jarayonga o'tkazildi.", reply_markup=get_main_menu_keyboard(context))
        
        # --- Notification: Sender ---
        try:
             # Fetch ticket data
            logger.info(f"Fetching ticket data for notification. ID: {ticket_id}")
            tickets_data = client.execute_kw(
                'helpdesk.ticket', 'search_read',
                [[('id', '=', ticket_id)]],
                {'fields': ['id', 'name', 'x_studio_ariza_raqami', 'description', 'x_studio_berilgan_sana', 'team_id', 'x_studio_ariza_yuboruvchi', 'x_studio_bolim'], 'limit': 1}
            )
            logger.info(f"Fetched ticket data: {tickets_data}")
            
            if tickets_data:
                t_data = tickets_data[0]
                
                # Fetch Usta name from team
                usta_name = update.effective_user.full_name  # Person who clicked = usta
                
                notif_data = {
                    'id': t_data['id'],
                    'x_studio_ariza_raqami': t_data.get('x_studio_ariza_raqami', t_data['id']),
                    'name': t_data['name'],
                    'description': t_data.get('description'),
                    'x_studio_berilgan_sana': t_data.get('x_studio_berilgan_sana'),
                    'deadline': deadline,
                    'usta_name': usta_name,
                    'sender_name': t_data['x_studio_ariza_yuboruvchi'][1] if t_data.get('x_studio_ariza_yuboruvchi') else "Noma'lum",
                    'department_name': t_data['x_studio_bolim'][1] if t_data.get('x_studio_bolim') else "Noma'lum"
                }

                # Notify Sender
                sender_id = t_data.get('x_studio_ariza_yuboruvchi')
                logger.info(f"Sender ID found: {sender_id}")
                
                if sender_id:
                     # Get Employee Telegram ID
                    emp = client.execute_kw('hr.employee', 'read', [[sender_id[0]]], {'fields': ['x_studio_telegram_id', 'name']})
                    logger.info(f"Employee data found: {emp}")
                    
                    if emp and emp[0].get('x_studio_telegram_id'):
                        tg_id = emp[0]['x_studio_telegram_id']
                        logger.info(f"Sending notification to Sender Telegram ID: {tg_id}")
                        await send_ticket_notification(context, int(tg_id), notif_data, "⏳ <b>Arizangiz qabul qilindi va jarayonda!</b>")
                    else:
                        logger.warning(f"Sender {sender_id} has no Telegram ID linked.")
            else:
                logger.warning(f"Ticket data not found for ID {ticket_id}")

        except Exception as e:
            logger.error(f"Error sending start notification: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        logger.error(f"Error setting deadline: {e}")
        await update.message.reply_text("Xatolik yuz berdi.", reply_markup=get_main_menu_keyboard(context))
        
    return ConversationHandler.END

async def solve_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask for report."""
    query = update.callback_query
    await query.answer()
    
    ticket_id = int(query.data.split("_")[-1])
    context.user_data['usta_ticket_id'] = ticket_id
    
    await query.message.reply_text(
        "Bajarilgan ish bo'yicha hisobot yozing:",
        reply_markup=ReplyKeyboardMarkup([["Bekor qilish"]], resize_keyboard=True)
    )
    return USTA_REPORT

async def usta_report_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save report and ask for photo."""
    text = update.message.text
    if text == "Bekor qilish":
        await update.message.reply_text("Jarayon bekor qilindi.", reply_markup=get_main_menu_keyboard(context))
        return ConversationHandler.END
        
    context.user_data['usta_report_text'] = text
    
    await update.message.reply_text(
        "Bajarilgan ish rasmini yuklang:",
        reply_markup=ReplyKeyboardMarkup([["O'tkazib yuborish"], ["Bekor qilish"]], resize_keyboard=True)
    )
    return USTA_PHOTO

async def usta_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save photo and finish."""
    photo_data = None
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        photo_data = base64.b64encode(photo_bytes).decode('utf-8')
    
    return await finish_solve_task(update, context, photo_data)

async def usta_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await finish_solve_task(update, context, None)

async def finish_solve_task(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_data) -> int:
    ticket_id = context.user_data.get('usta_ticket_id')
    report_text = context.user_data.get('usta_report_text')
    
    client = OdooClient()
    # Stage 4 = Solved/Hal qilingan
    vals = {
        'stage_id': 4,
        'x_studio_matn': report_text
    }
    if photo_data:
        vals['x_studio_rasm'] = photo_data
        
    try:
        client.update_ticket(ticket_id, vals)
        await update.message.reply_text(
            "✅ Ariza hal qilindi!",
            reply_markup=get_main_menu_keyboard(context)
        )
        
        # --- Notification: Group & Sender ---
        try:
             # Fetch ticket data
            logger.info(f"Fetching ticket data for solve notification. ID: {ticket_id}")
            tickets_data = client.execute_kw(
                'helpdesk.ticket', 'search_read',
                [[('id', '=', ticket_id)]],
                {'fields': ['id', 'name', 'x_studio_ariza_raqami', 'description', 'x_studio_berilgan_sana', 'team_id', 'x_studio_ariza_yuboruvchi', 'x_studio_bolim'], 'limit': 1}
            )
            logger.info(f"Fetched ticket data: {tickets_data}")

            if tickets_data:
                t_data = tickets_data[0]
                
                # Usta is the person who solved it
                usta_name = update.effective_user.full_name
                
                notif_data = {
                    'id': t_data['id'],
                    'x_studio_ariza_raqami': t_data.get('x_studio_ariza_raqami', t_data['id']),
                    'name': t_data['name'],
                    'description': t_data.get('description'),
                    'x_studio_berilgan_sana': t_data.get('x_studio_berilgan_sana'),
                    'report': report_text,
                    'usta_name': usta_name,
                    'sender_name': t_data['x_studio_ariza_yuboruvchi'][1] if t_data.get('x_studio_ariza_yuboruvchi') else "Noma'lum",
                    'department_name': t_data['x_studio_bolim'][1] if t_data.get('x_studio_bolim') else "Noma'lum",
                    'photo': photo_data
                }

                # Notify Group
                if TELEGRAM_GROUP_ID:
                    logger.info(f"Sending solve notification to Group: {TELEGRAM_GROUP_ID}")
                    await send_ticket_notification(context, TELEGRAM_GROUP_ID, notif_data, "✅ <b>Ariza hal qilindi!</b>")
                else:
                    logger.warning("TELEGRAM_GROUP_ID not set!")

                # Notify Sender
                sender_id = t_data.get('x_studio_ariza_yuboruvchi')
                logger.info(f"Sender ID found: {sender_id}")
                
                if sender_id:
                     # Get Employee Telegram ID
                    emp = client.execute_kw('hr.employee', 'read', [[sender_id[0]]], {'fields': ['x_studio_telegram_id', 'name']})
                    logger.info(f"Employee data found: {emp}")
                    
                    if emp and emp[0].get('x_studio_telegram_id'):
                        tg_id = emp[0]['x_studio_telegram_id']
                        logger.info(f"Sending solve notification to Sender Telegram ID: {tg_id}")
                        await send_ticket_notification(context, int(tg_id), notif_data, "✅ <b>Arizangiz hal qilindi!</b>")
                    else:
                        logger.warning(f"Sender {sender_id} has no Telegram ID linked.")
                        
        except Exception as e:
            logger.error(f"Error sending solve notification: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        logger.error(f"Error solving ticket {ticket_id}: {e}")
        await update.message.reply_text("Xatolik yuz berdi.", reply_markup=get_main_menu_keyboard(context))
        
    return ConversationHandler.END

async def cancel_task_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask for cancellation reason."""
    query = update.callback_query
    await query.answer()
    
    ticket_id = int(query.data.split("_")[-1])
    context.user_data['usta_ticket_id'] = ticket_id
    
    await query.message.reply_text(
        "Bekor qilish sababini yozing:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Bekor qilish")]], resize_keyboard=True)
    )
    return USTA_CANCEL_REASON

async def usta_cancel_reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save reason and set status to Cancelled."""
    text = update.message.text
    if text == "Bekor qilish":
        await update.message.reply_text("Jarayon bekor qilindi.", reply_markup=get_main_menu_keyboard(context))
        return ConversationHandler.END
        
    ticket_id = context.user_data.get('usta_ticket_id')
    
    client = OdooClient()
    # Stage 5 = Cancelled/Bekor qilingan
    vals = {
        'stage_id': 5,
        'x_studio_matn': text
    }
    
    try:
        client.update_ticket(ticket_id, vals)
        await update.message.reply_text(
            "🚫 Ariza bekor qilindi.",
            reply_markup=get_main_menu_keyboard(context)
        )
        
        # --- Notification: Group & Sender ---
        try:
             # Fetch ticket data
            logger.info(f"Fetching ticket data for cancel notification. ID: {ticket_id}")
            tickets_data = client.execute_kw(
                'helpdesk.ticket', 'search_read',
                [[('id', '=', ticket_id)]],
                {'fields': ['id', 'name', 'x_studio_ariza_raqami', 'description', 'x_studio_berilgan_sana', 'team_id', 'x_studio_ariza_yuboruvchi', 'x_studio_bolim'], 'limit': 1}
            )
            logger.info(f"Fetched ticket data: {tickets_data}")
            
            if tickets_data:
                t_data = tickets_data[0]
                notif_data = {
                    'id': t_data['id'],
                    'x_studio_ariza_raqami': t_data.get('x_studio_ariza_raqami', t_data['id']),
                    'name': t_data['name'],
                    'description': t_data.get('description'),
                    'x_studio_berilgan_sana': t_data.get('x_studio_berilgan_sana'),
                    'cancel_reason': text,
                    'cancelled_by': update.effective_user.full_name,
                    'usta_name': update.effective_user.full_name, # User who cancelled is the Usta here
                    'sender_name': t_data['x_studio_ariza_yuboruvchi'][1] if t_data.get('x_studio_ariza_yuboruvchi') else "Noma'lum",
                    'department_name': t_data['x_studio_bolim'][1] if t_data.get('x_studio_bolim') else "Noma'lum"
                }

                # Notify Group
                if TELEGRAM_GROUP_ID:
                    logger.info(f"Sending cancel notification to Group: {TELEGRAM_GROUP_ID}")
                    await send_ticket_notification(context, TELEGRAM_GROUP_ID, notif_data, "🚫 <b>Ariza bekor qilindi!</b>")
                else:
                    logger.warning("TELEGRAM_GROUP_ID not set!")

                # Notify Sender
                sender_id = t_data.get('x_studio_ariza_yuboruvchi')
                logger.info(f"Sender ID found: {sender_id}")
                
                if sender_id:
                     # Get Employee Telegram ID
                    emp = client.execute_kw('hr.employee', 'read', [[sender_id[0]]], {'fields': ['x_studio_telegram_id', 'name']})
                    logger.info(f"Employee data found: {emp}")
                    
                    if emp and emp[0].get('x_studio_telegram_id'):
                        tg_id = emp[0]['x_studio_telegram_id']
                        logger.info(f"Sending cancel notification to Sender Telegram ID: {tg_id}")
                        await send_ticket_notification(context, int(tg_id), notif_data, "🚫 <b>Arizangiz bekor qilindi!</b>")
                    else:
                        logger.warning(f"Sender {sender_id} has no Telegram ID linked.")
                        
        except Exception as e:
            logger.error(f"Error sending cancel notification: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        logger.error(f"Error cancelling ticket {ticket_id}: {e}")
        await update.message.reply_text("Xatolik yuz berdi.", reply_markup=get_main_menu_keyboard(context))
        
    return ConversationHandler.END

async def cancel_usta_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Bekor qilindi.", reply_markup=get_main_menu_keyboard(context))
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set in .env file.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add conversation handler with the states
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, full_name_input)],
            DEPARTMENT: [CallbackQueryHandler(department_choice)],
            PHONE_NUMBER: [MessageHandler(filters.CONTACT, phone_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    
    # Ticket Conversation Handler
    ticket_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛠 Ariza qoldirish$"), create_ticket_start)],
        states={
            TICKET_TITLE: [
                MessageHandler(filters.Regex("^Bekor qilish$"), cancel_ticket),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_title_input)
            ],
            TICKET_TEAM: [CallbackQueryHandler(ticket_team_choice)],
            TICKET_DESCRIPTION: [
                MessageHandler(filters.Regex("^Bekor qilish$"), cancel_ticket),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_description_input)
            ],
            TICKET_PHOTO: [
                MessageHandler(filters.Regex("^Bekor qilish$"), cancel_ticket),
                MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, ticket_photo_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_ticket), MessageHandler(filters.Regex("^Bekor qilish$"), cancel_ticket)],
    )
    application.add_handler(ticket_conv_handler)
    
    # Menu Handlers
    application.add_handler(MessageHandler(filters.Regex("^👤 Profil$"), view_profile))
    application.add_handler(MessageHandler(filters.Regex("^📂 Mening arizalarim$"), my_tickets))
    application.add_handler(CallbackQueryHandler(my_tickets_pagination, pattern="^my_tickets_"))
    
    # Usta Handlers
    application.add_handler(MessageHandler(filters.Regex("^🛠 Mening vazifalarim$"), my_tasks))
    application.add_handler(CallbackQueryHandler(my_tasks_pagination, pattern="^(usta_tasks_|usta_cat_|usta_back_cats)"))
    application.add_handler(CallbackQueryHandler(task_details, pattern="^usta_task_"))

    # Usta Workflow Conversation
    usta_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_task, pattern="^usta_start_"),
            CallbackQueryHandler(solve_task, pattern="^usta_solve_"),
            CallbackQueryHandler(cancel_task_prompt, pattern="^usta_cancel_")
        ],
        states={
            USTA_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, usta_deadline_input)],
            USTA_REPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, usta_report_input)],
            USTA_PHOTO: [
                MessageHandler(filters.Regex("^O'tkazib yuborish$"), usta_skip_photo),
                MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, usta_photo_input)
            ],
            USTA_CANCEL_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, usta_cancel_reason_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel_usta_flow)],
    )
    application.add_handler(usta_conv_handler)
    
    application.run_polling()

if __name__ == "__main__":
    main()
