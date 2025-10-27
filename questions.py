"""
Declarative form schema for the Site Survey app.
"""

FORM_DEFINITION = {
    "base_sections": [
        {
            "title": "Contact Information",
            "fields": [
                {"name": "company", "label": "Company Name", "type": "text"},
                {"name": "contact", "label": "Contact Name", "type": "text"},
                {"name": "address", "label": "Address", "type": "text"},
                {"name": "phone", "label": "Contact Phone #", "type": "text"},
                {"name": "email", "label": "Contact Email", "type": "text"},
            ],
        },
        {
            "title": "Delivery Instructions",
            "fields": [
                {"name": "days_prior", "label": "How many days prior to installation can the safe be delivered?", "type": "text"},
                {"name": "storage_space", "label": "Is there space to store the Tidel safe?",
                    "type": "radio", "options": ["Yes", "No"]},
                {"name": "loading_dock", "label": "Is there a loading dock?",
                    "type": "radio", "options": ["Yes", "No"]},
                {"name": "delivery_hours", "label": "Delivery Hours", "type": "text"},
                {"name": "delivery_loc", "label": "Delivery Location",
                    "type": "radio", "options": ["Front of store", "Back of store"]},
                {"name": "path_desc", "label": "Describe the equipment path from the entry point to the final location", "type": "textarea"},
                {"name": "use_dolly", "label": "Can a dolly be used to move the equipment?",
                    "type": "radio", "options": ["Yes", "No"]},
                {"name": "staircase_notes",
                    "label": "Describe door sizes, staircases (steps, turns, landings), etc.", "type": "textarea"},
                {"name": "elevator_notes",
                    "label": "Elevators (capacity, door size, dimensions)", "type": "textarea"},
                {"name": "delivery_notes",
                    "label": "Additional delivery instructions or comments", "type": "textarea"},
            ],
        },
        {
            "title": "Installation Location",
            "fields": [
                {"name": "floor_scan", "label": "Is a Floor Scan required?",
                    "type": "radio", "options": ["Yes", "No"]},
                {"name": "download_speed",
                    "label": "Speedtest Download (turn off 5G, use Bell)", "type": "text"},
                {"name": "upload_speed", "label": "Speedtest Upload", "type": "text"},
                {"name": "door_size", "label": "Door size", "type": "text"},
                {"name": "room_size",
                    "label": "Room size (Length x Width x Height)", "type": "text"},
                {"name": "sufficient_space", "label": "Is there sufficient space for the safe? (Need 30 inches height)", "type": "radio", "options": [
                    "Yes", "No"]},
                {"name": "floor_type", "label": "Floor/Subfloor type", "type": "radio",
                    "options": ["Concrete", "Wood", "Raised floor", "Other"]},
                {"name": "other_floor_type", "label": "Other floor type (if applicable)", "type": "text", "visible_if": {
                    "field": "floor_type", "equals": "Other"}},
                {"name": "other_safe", "label": "Is there another safe in the same room?",
                    "type": "radio", "options": ["Yes", "No"]},
                {"name": "safe_type", "label": "If yes, what kind?", "type": "text",
                    "visible_if": {"field": "other_safe", "equals": "Yes"}},
                {"name": "network", "label": "Is there a network connection available?",
                    "type": "radio", "options": ["Yes", "No"]},
                {"name": "network_distance", "label": "If yes, how far from the install location?",
                    "type": "text", "visible_if": {"field": "network", "equals": "Yes"}},
                {"name": "water_distance", "label": "Is the safe being installed 6 feet away from water?",
                    "type": "radio", "options": ["Yes", "No"]},
                {"name": "power", "label": "Is there a power outlet within 4 feet of the unit?",
                    "type": "radio", "options": ["Yes", "No"]},
                {"name": "install_notes",
                    "label": "Describe the installation and include any notes", "type": "textarea"},
            ],
        },
    ],
    "model_overrides": {
        ("TiDel", "D4"): {
            "hide_fields": ["loading_dock"],
            "insert_after": [
                {
                    "after": "path_desc",
                    "field": {
                        "name": "stairs_required",
                        "label": "Are stairs required on the path?",
                        "type": "radio",
                        "options": ["Yes", "No"],
                        "help": "Answer applies to the equipment path from entry to final location.",
                    },
                }
            ],
        },
        ("TiDel", "D3 w/Storage Vault"): {
            "hide_fields": [],
            "insert_after": [],
        },
    },
}
