from odoo_client import OdooClient

client = OdooClient()
if client.authenticate():
    # Search for ticket TS/00004
    print("Searching for ticket TS/00004...")
    tickets = client.execute_kw(
        'helpdesk.ticket', 'search_read',
        [[('x_studio_ariza_raqami', '=', 'TS/00004')]],
        {'fields': ['id', 'name', 'x_studio_bolim', 'x_studio_related_field_2pj_1jg9o6rpt', 'x_studio_ariza_yuboruvchi']}
    )
    
    if tickets:
        t = tickets[0]
        print(f"Ticket found: {t}")
        print(f"Bo'lim (Raw): {t.get('x_studio_bolim')}")
        print(f"Tel (Raw): {t.get('x_studio_related_field_2pj_1jg9o6rpt')}")
        print(f"Yuboruvchi: {t.get('x_studio_ariza_yuboruvchi')}")
    else:
        print("Ticket TS/00004 not found.")
    
    # Original check for x_studio_masul_xodim relation (kept as per instruction interpretation)
    print("\nChecking relation of x_studio_masul_xodim on helpdesk.team:")
    try:
        fields = client.models.execute_kw(
            client.db, client.uid, client.password,
            'helpdesk.team', 'fields_get',
            ['x_studio_masul_xodim'], 
            {'attributes': ['string', 'type', 'relation', 'name']}
        )
        if 'x_studio_masul_xodim' in fields:
            print(f"Relation: {fields['x_studio_masul_xodim'].get('relation')}")
        else:
            print("Field not found.")
    except Exception as e:
        print(f"Error: {e}")
