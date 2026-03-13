import xmlrpc.client
import logging
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
            else:
                logger.error("Authentication failed. Check credentials.")
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
            logger.error(f"Error executing method {method} on model {model}: {e}")
            return None

    def search_read(self, model, domain, fields, limit=10):
        return self.execute_kw(model, 'search_read', [domain], {'fields': fields, 'limit': limit})

    def create_ticket(self, title, description, team_id, employee_id, department_id, date, photo_data=None, file_data=None):
        """Create a ticket in Odoo Helpdesk."""
        vals = {
            'name': title, # Title of ticket
            'team_id': int(team_id),
            'description': description, # Description body
            'x_studio_ariza_yuboruvchi': int(employee_id),
            'x_studio_bolim': int(department_id) if department_id else False,
            'x_studio_berilgan_sana': date.strftime('%Y-%m-%d %H:%M:%S') if hasattr(date, 'strftime') else str(date).split('.')[0],
        }
        if photo_data:
            vals['x_studio_binary_field_9hi_1jg9o8v5j'] = photo_data
        if file_data:
            vals['x_studio_fayl'] = file_data
            
        ticket_id = self.execute_kw('helpdesk.ticket', 'create', [vals])
        
        # Fetch the custom ticket number (x_studio_ariza_raqami)
        if ticket_id:
            try:
                result = self.search_read('helpdesk.ticket', [('id', '=', ticket_id)], ['x_studio_ariza_raqami'], limit=1)
                if result and result[0].get('x_studio_ariza_raqami'):
                    return result[0]['x_studio_ariza_raqami']
            except Exception as e:
                logger.error(f"Error fetching ticket number for ID {ticket_id}: {e}")
                
        return ticket_id

    def create_attachment(self, name, model, res_id, datas):
        """Create an attachment for a record."""
        vals = {
            'name': name,
            'datas': datas, # base64 string
            'res_model': model,
            'res_id': int(res_id),
            'type': 'binary', 
        }
        return self.execute_kw('ir.attachment', 'create', [vals])

    def get_helpdesk_teams(self):
        """Fetch all helpdesk teams."""
        return self.search_read(
            'helpdesk.team',
            [('active', '=', True)],
            ['id', 'name']
        )

    def get_departments(self, parent_id=None):
        """Fetch departments. If parent_id is provided, fetch children. Else fetch root departments."""
        if parent_id:
            domain = [('parent_id', '=', int(parent_id))]
        else:
            domain = [('parent_id', '=', False)]
        return self.search_read('hr.department', domain, ['id', 'name', 'parent_id'], limit=100)

    def get_employee_by_phone(self, phone):
        """Search employee by mobile or work phone."""
        domain = ['|', ('mobile_phone', '=', phone), ('work_phone', '=', phone)]
        result = self.search_read('hr.employee', domain, ['id', 'name', 'department_id', 'x_studio_telegram_id'], limit=1)
        return result[0] if result else None

    def get_employee_by_telegram_id(self, telegram_id):
        """Search employee by Telegram ID."""
        domain = [('x_studio_telegram_id', '=', str(telegram_id))]
        result = self.search_read('hr.employee', domain, ['id', 'name', 'department_id', 'mobile_phone', 'job_title'], limit=1)
        return result[0] if result else None

    def create_employee(self, name, department_id, phone, telegram_id, job_title="Employee"):
        """Create a new employee record."""
        vals = {
            'name': name,
            'department_id': int(department_id),
            'mobile_phone': phone,
            'work_phone': phone,
            'x_studio_telegram_id': str(telegram_id),
            'job_title': job_title 
        }
        return self.execute_kw('hr.employee', 'create', [vals])

    def update_employee_telegram_id(self, employee_id, telegram_id):
        """Update telegram ID for an existing employee."""
        return self.execute_kw('hr.employee', 'write', [[employee_id], {'x_studio_telegram_id': str(telegram_id)}])

    def get_employee_tickets(self, employee_id, offset=0, limit=5):
        """Fetch tickets created by the employee."""
        return self.execute_kw(
            'helpdesk.ticket',
            'search_read',
            [[('x_studio_ariza_yuboruvchi', '=', int(employee_id))]],
            {
                'fields': ['id', 'name', 'stage_id', 'x_studio_berilgan_sana', 'x_studio_ariza_raqami'],
                'offset': offset,
                'limit': limit,
                'order': 'id desc'
            }
        )

    # --- USTA (MASTER) FEATURES ---

    def is_usta(self, employee_id):
        """Check if employee is a Usta."""
        employee = self.execute_kw(
            'hr.employee',
            'read',
            [[int(employee_id)]],
            {'fields': ['x_studio_usta']}
        )
        return employee[0].get('x_studio_usta', False) if employee else False

    def get_managed_teams(self, employee_id):
        """Get IDs of teams where the employee is responsible (masul xodim)."""
        teams = self.search_read(
            'helpdesk.team',
            [('x_studio_masul_xodim', '=', int(employee_id))],
            ['id', 'name']
        )
        return [t['id'] for t in teams]

    def get_team_tickets(self, team_ids, stage_id=None, offset=0, limit=10):
        """Fetch tickets for the teams."""
        if not team_ids:
            return []
            
        domain = [('team_id', 'in', team_ids)]
        if stage_id:
            domain.append(('stage_id', '=', int(stage_id)))
            
        return self.execute_kw(
            'helpdesk.ticket',
            'search_read',
            [domain],
            {
                'fields': ['id', 'name', 'stage_id', 'x_studio_berilgan_sana', 'description', 'close_date', 'sla_deadline', 'write_date', 'x_studio_ariza_raqami', 'x_studio_ariza_yuboruvchi', 'x_studio_binary_field_9hi_1jg9o8v5j', 'x_studio_bolim', 'x_studio_related_field_2pj_1jg9o6rpt'],
                'offset': offset,
                'limit': limit,
                'order': 'id desc'
            }
        )

    def get_task_counts(self, team_ids):
        """Get count of tickets per stage for managed teams."""
        if not team_ids:
            return []
            
        domain = [('team_id', 'in', team_ids)]
        # We need to group by stage_id. read_group is best.
        return self.execute_kw(
            'helpdesk.ticket',
            'read_group',
            [domain, ['stage_id'], ['stage_id']],
        )

    def update_ticket(self, ticket_id, vals):
        """Update ticket fields."""
        return self.execute_kw('helpdesk.ticket', 'write', [[int(ticket_id)], vals])
