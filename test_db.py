import sqlite3

# 1. Connect to the same database file
conn = sqlite3.connect('pipeline.db')
cursor = conn.cursor()

# -------------------------
# Insert sample complaint
# -------------------------
cursor.execute('''
INSERT INTO ConsumerComplaints
(complaint_date, customer_name, consumer_mobile_number, OHT_name, issue_type, longitude, latitude, complaint_details, status)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
''', (
    '2025-08-09',           # complaint_date
    'John Doe',             # customer_name
    '9876543210',           # consumer_mobile_number
    'OHT-101',              # OHT_name
    'Leakage',            # issue_type
    77.5946,                # longitude
    12.9716,                # latitude
    'Low water pressure',   # complaint_details
    'Open'                  # status
))

complaint_id = cursor.lastrowid  # Get the ID of the complaint we just inserted

# -------------------------
# Insert sample team work
# -------------------------
cursor.execute('''
INSERT INTO TeamWork
(work_date, team_member, OHT, area, work_description, complaint_id)
VALUES (?, ?, ?, ?, ?, ?, ?)
''', (
    '2025-08-10',           # work_date
    'Alice',                # team_member
    'OHT-101',              # OHT
    'Sector 5',             # area
    'Replaced pipeline section', # work_description
    complaint_id,           # complaint_id (link to ConsumerComplaints)
))

work_id = cursor.lastrowid  # Get the ID of this work record

# -------------------------
# Insert sample materials
# -------------------------
materials_data = [
    ('PVC Pipe', 10, work_id),  # material_name, quantity_used, work_id
    ('Valve', 2, work_id)
]

cursor.executemany('''
INSERT INTO Materials
(material_name, quantity_used, work_id)
VALUES (?, ?, ?)
''', materials_data)

# Save changes
conn.commit()

# -------------------------
# Retrieve and display data
# -------------------------
print("Consumer Complaints Records:")
for row in cursor.execute("SELECT * FROM ConsumerComplaints"):
    print(row)

print("\nTeam Work Records:")
for row in cursor.execute("SELECT * FROM TeamWork"):
    print(row)

print("\nMaterials Records:")
for row in cursor.execute("SELECT * FROM Materials"):
    print(row)

conn.close()
