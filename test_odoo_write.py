import logging
from odoo_client import OdooClient
import base64

logging.basicConfig(level=logging.INFO)
client = OdooClient()
if client.authenticate():
    try:
        # Create a small dummy file
        dummy_file = base64.b64encode(b"test data").decode('utf-8')
        
        # Test write without context (should fail)
        # client.execute_kw('repair.order', 'write', [[4], {'report_file': dummy_file}])
        
        # Test write with context
        res = client.execute_kw('repair.order', 'write', [[4], {'report_file': dummy_file}], {'context': {'mail_notrack': True}})
        print(f"Success with mail_notrack: {res}")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("Auth failed")
