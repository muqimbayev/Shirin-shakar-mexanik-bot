from odoo_client import OdooClient
import logging

logging.basicConfig(level=logging.INFO)
client = OdooClient()
if client.authenticate():
    fields = client.execute_kw('repair.order', 'fields_get', [], {'attributes': ['string', 'type', 'selection']})
    for field_name in sorted(fields.keys()):
        if any(t in field_name.lower() for t in ['report', 'desc', 'file', 'finish', 'done']):
            print(f"{field_name}: {fields[field_name]}")
else:
    print("Failed to authenticate")
