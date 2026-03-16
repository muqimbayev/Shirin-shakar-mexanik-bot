from odoo_client import OdooClient
import logging

logging.basicConfig(level=logging.INFO)
client = OdooClient()
if client.authenticate():
    fields = client.execute_kw('helpdesk.ticket', 'fields_get', [['x_studio_baho']], {'attributes': ['string', 'type', 'selection']})
    print(fields.get('x_studio_baho'))
else:
    print("Failed to authenticate")
