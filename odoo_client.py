import xmlrpc.client
import logging
import re
from config import ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD

logger = logging.getLogger(__name__)

class OdooClient:
    def __init__(self):
        self.url = ODOO_URL
        self.db = ODOO_DB
        self.username = ODOO_USER
        self.password = ODOO_PASSWORD
        self.common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(self.url))
        self.models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(self.url))
        self.uid = None

    def authenticate(self):
        try:
            self.uid = self.common.authenticate(self.db, self.username, self.password, {})
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
        return self.execute_kw('repair.order', 'write', [[int(order_id)], vals], {'context': {'mail_notrack': True}})

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

    def get_departments(self, parent_id=None):
        """Fetch departments."""
        domain = [('parent_id', '=', int(parent_id))] if parent_id else [('parent_id', '=', False)]
        return self.search_read('hr.department', domain, ['id', 'name', 'parent_id'], limit=100)
