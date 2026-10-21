import xmlrpc.client
import logging
import re
from config import ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD

logger = logging.getLogger(__name__)

class OdooClient:
    # Login natijasi barcha OdooClient() lar uchun umumiy — har handler'da qayta login qilinmaydi
    _shared_uid = None

    def __init__(self):
        self.url = ODOO_URL
        self.db = ODOO_DB
        self.username = ODOO_USER
        self.password = ODOO_PASSWORD
        self.common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(self.url), allow_none=True)
        self.models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(self.url), allow_none=True)
        self.uid = OdooClient._shared_uid

    def authenticate(self):
        try:
            self.uid = self.common.authenticate(self.db, self.username, self.password, {})
            OdooClient._shared_uid = self.uid or None
            if self.uid:
                logger.info(f"Successfully authenticated with Odoo. UID: {self.uid}")
                return True
            logger.error("Authentication failed.")
            return False
        except Exception as e:
            logger.error(f"Error connecting to Odoo: {e}")
            return False

    def execute_kw(self, model, method, args, kwargs=None):
        if not self.uid:
            if not self.authenticate():
                return None
        if kwargs is None:
            kwargs = {}
        try:
            return self.models.execute_kw(self.db, self.uid, self.password, model, method, args, kwargs)
        except xmlrpc.client.Fault as e:
            # Odoo qayta ishga tushgan / sessiya eskirgan bo'lsa — bir marta qayta login qilib urinamiz
            if 'AccessDenied' in str(e) and self.authenticate():
                try:
                    return self.models.execute_kw(self.db, self.uid, self.password, model, method, args, kwargs)
                except Exception as e2:
                    logger.error(f"Error executing {method} on {model}: {e2}")
                    return None
            logger.error(f"Error executing {method} on {model}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error executing {method} on {model}: {e}")
            return None

    def search_read(self, model, domain, fields, limit=10):
        return self.execute_kw(model, 'search_read', [domain], {'fields': fields, 'limit': limit})

    # --- REPAIR ORDER ---

    def create_repair(self, title, description, employee_id, department_id, photo_data=None, file_data=None, file_name=None, priority=None):
        """Create a repair order in Odoo."""
        vals = {
            'application_name': title,
            'applicant': int(employee_id),
            'department': int(department_id) if department_id else False,
            'application_description': description or '',
        }
        if priority:
            vals['priority_custom'] = str(priority)
        if photo_data:
            vals['application_file'] = photo_data
            if file_name: vals['application_file_name'] = file_name
        elif file_data:
            vals['application_file'] = file_data
            if file_name: vals['application_file_name'] = file_name
        return self.execute_kw('repair.order', 'create', [vals], {'context': {'mail_notrack': True}})

    def update_repair(self, order_id, vals):
        """Update repair order fields."""
        # from_tg_bot: Odoo modul guruh xabarini qayta tahrirlamasin (bot o'zi tahrirlaydi)
        return self.execute_kw('repair.order', 'write', [[int(order_id)], vals], {'context': {'mail_notrack': True, 'from_tg_bot': True}})

    def get_employee_repairs(self, employee_id, offset=0, limit=5):
        """Fetch repair orders submitted by the employee."""
        return self.execute_kw(
            'repair.order', 'search_read',
            [[('applicant', '=', int(employee_id))]],
            {
                'fields': ['id', 'name', 'application_name', 'state', 'create_date'],
                'offset': offset,
                'limit': limit,
                'order': 'id desc'
            }
        ) or []

    def get_assigned_repairs(self, employee_id, state=None, offset=0, limit=10):
        """Fetch repair orders assigned to the employee (usta)."""
        domain = [('designated_employee', '=', int(employee_id))]
        if state:
            domain.append(('state', '=', state))
        return self.execute_kw(
            'repair.order', 'search_read',
            [domain],
            {
                'fields': ['id', 'name', 'application_name', 'state', 'create_date',
                           'applicant', 'department', 'application_file', 'application_file_name', 'schedule_date'],
                'offset': offset,
                'limit': limit,
                'order': 'id desc'
            }
        ) or []

    def get_repair_counts(self, employee_id):
        """Get count of repair orders per state for the assigned employee."""
        domain = [('designated_employee', '=', int(employee_id))]
        return self.execute_kw('repair.order', 'read_group', [domain, ['state'], ['state']]) or []

    # --- EMPLOYEE ---

    def get_employee_by_phone(self, phone):
        """Search employee by mobile or work phone with normalization."""
        if not phone:
            return None
        
        normalized_input = re.sub(r'\D', '', str(phone))
        # Fetch all employees with phone fields to compare locally due to inconsistent Odoo formatting
        employees = self.search_read('hr.employee', [], ['id', 'name', 'department_id', 'telegram_id', 'mobile_phone', 'work_phone'], limit=None)
        
        if employees:
            for emp in employees:
                m_phone = emp.get('mobile_phone')
                w_phone = emp.get('work_phone')
                
                # Check normalized match on suffix (last 9 digits are usually enough for UZ)
                if m_phone and re.sub(r'\D', '', str(m_phone)).endswith(normalized_input[-9:]):
                    return emp
                if w_phone and re.sub(r'\D', '', str(w_phone)).endswith(normalized_input[-9:]):
                    return emp
                    
        return None

    def get_employee_by_telegram_id(self, telegram_id):
        """Search employee by Telegram ID."""
        domain = [('telegram_id', '=', str(telegram_id))]
        result = self.search_read('hr.employee', domain, ['id', 'name', 'department_id', 'mobile_phone'], limit=1)
        return result[0] if result else None

    def update_employee_telegram_id(self, employee_id, telegram_id):
        """Update telegram ID for an existing employee."""
        return self.execute_kw('hr.employee', 'write', [[employee_id], {'telegram_id': str(telegram_id)}])

    def is_usta(self, employee_id):
        """Check if employee is a Master (Usta)."""
        employee = self.execute_kw('hr.employee', 'read', [[int(employee_id)]], {'fields': ['is_master']})
        return employee[0].get('is_master', False) if employee else False

    def get_chief_mechanic_name(self, telegram_id):
        """Check if employee linked to Telegram ID is Chief Mechanic and return their Odoo name."""
        domain = [('telegram_id', '=', str(telegram_id))]
        emp = self.search_read('hr.employee', domain, ['x_studio_chief_mechanic', 'name'], limit=1)
        if emp and emp[0].get('x_studio_chief_mechanic'):
            return emp[0].get('name')
        return False

    def get_all_usta_telegram_ids(self):
        """Fetch all mechanics (is_master=True) with their telegram IDs and names."""
        domain = [('is_master', '=', True), ('telegram_id', '!=', False)]
        result = self.search_read(
            'hr.employee', domain,
            ['id', 'name', 'telegram_id'],
            limit=100
        )
        return result or []

    def get_departments(self, parent_id=None):
        """Fetch departments."""
        domain = [('parent_id', '=', int(parent_id))] if parent_id else [('parent_id', '=', False)]
        return self.search_read('hr.department', domain, ['id', 'name', 'parent_id'], limit=100)

    def get_monthly_score(self, employee_id):
        """Joriy oy uchun ustaning ballarini qaytaradi (mechanic.score.line)."""
        import datetime
        today = datetime.date.today()
        first_day = today.replace(day=1).strftime('%Y-%m-%d')
        if today.month == 12:
            last_day = today.replace(year=today.year + 1, month=1, day=1) - datetime.timedelta(days=1)
        else:
            last_day = today.replace(month=today.month + 1, day=1) - datetime.timedelta(days=1)
        last_day = last_day.strftime('%Y-%m-%d')
        domain = [
            ('employee_id', '=', int(employee_id)),
            ('date', '>=', first_day),
            ('date', '<=', last_day),
        ]
        return self.execute_kw(
            'mechanic.score.line', 'search_read', [domain],
            {'fields': ['points', 'score_type', 'note', 'bonus_amount', 'date', 'repair_id'], 'order': 'date desc'}
        ) or []

    def get_repair_statistics(self):
        """Har bir usta bo'yicha yopilmagan, bekor qilingan va qabul qilinmagan arizalar sonini qaytaradi."""
        # Barcha yopilmagan arizalar (done va cancel dan tashqari)
        open_orders = self.execute_kw(
            'repair.order', 'search_read',
            [[('state', 'not in', ['done', 'cancel'])]],
            {'fields': ['id', 'name', 'state', 'designated_employee'], 'order': 'id desc'}
        ) or []

        # Bekor qilingan arizalar (oxirgi 30 kun)
        import datetime
        thirty_days_ago = (datetime.date.today() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
        cancelled_orders = self.execute_kw(
            'repair.order', 'search_read',
            [[('state', '=', 'cancel'), ('create_date', '>=', thirty_days_ago)]],
            {'fields': ['id', 'name', 'designated_employee'], 'order': 'id desc'}
        ) or []

        stats = {}  # {employee_id: {'name': ..., 'open': 0, 'unassigned': 0}}

        for order in open_orders:
            desig = order.get('designated_employee')
            if desig and isinstance(desig, list):
                emp_id, emp_name = desig[0], desig[1]
            else:
                emp_id, emp_name = 0, '— Tayinlanmagan —'

            if emp_id not in stats:
                stats[emp_id] = {'name': emp_name, 'open': 0, 'unassigned': 0}
            if emp_id == 0:
                stats[0]['unassigned'] = stats[0].get('unassigned', 0) + 1
            else:
                stats[emp_id]['open'] += 1

        return {
            'per_mechanic': stats,
            'open_total': len(open_orders),
            'unassigned_total': sum(1 for o in open_orders if not o.get('designated_employee')),
            'cancelled_30d': len(cancelled_orders),
        }


