from odoo_client import OdooClient
import logging

logging.basicConfig(level=logging.INFO)
client = OdooClient()
if client.authenticate():
    order = client.execute_kw('repair.order', 'search_read', [[('name', '=', 'WH/RO/00003')]], 
                             {'fields': ['id', 'name', 'state', 'report_description', 'report_file_name', 'finished_date']})
    print(order)
else:
    print("Failed to authenticate")
