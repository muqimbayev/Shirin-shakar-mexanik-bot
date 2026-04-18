import logging
from odoo_client import OdooClient

logging.basicConfig(level=logging.INFO)
client = OdooClient()
if client.authenticate():
    # Check hr.employee fields
    emp_fields = client.execute_kw('hr.employee', 'fields_get', [], {'attributes': ['type', 'string']})
    chief_field = {k: v for k, v in emp_fields.items() if 'chief' in k.lower()}
    print("hr.employee chief fields:", chief_field)
    
    # Check repair.order states
    ro_fields = client.execute_kw('repair.order', 'fields_get', [], {'attributes': ['type', 'string', 'selection']})
    if 'state' in ro_fields:
        print("repair.order states:", ro_fields['state'].get('selection'))
        
else:
    print("Auth failed")
