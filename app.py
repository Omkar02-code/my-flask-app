import json
import datetime as dt
from flask import Flask, request, redirect, url_for, render_template
import sqlite3
import os
import re

conn = sqlite3.connect('pipeline.db')
cursor = conn.cursor()

# Updated ConsumerComplaints table
cursor.execute('''
CREATE TABLE IF NOT EXISTS ConsumerComplaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_date TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    consumer_mobile_number TEXT,
    OHT_name TEXT,
    issue text,
    Address TEXT,
    longitude REAL,
    latitude REAL,
    complaint_details TEXT,
    status TEXT
)
''')

# Updated TeamWork table
cursor.execute('''
CREATE TABLE IF NOT EXISTS TeamWork (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_date TEXT NOT NULL,
    team_member TEXT NOT NULL,
    OHT TEXT,
    area TEXT,
    work_description TEXT,
    complaint_id INTEGER,
    FOREIGN KEY (complaint_id) REFERENCES ConsumerComplaints(id)
)
''')

# Updated Materials table
cursor.execute('''
CREATE TABLE IF NOT EXISTS Materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_name TEXT NOT NULL,
    quantity_used REAL,
    work_id INTEGER,
    FOREIGN KEY (work_id) REFERENCES TeamWork(id)
)
''')

conn.commit()
conn.close()
print("Updated database successfully!")

app = Flask(__name__)
DATABASE = 'pipeline.db'
print("Updated database successfully!")


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # For dict-like access to rows
    return conn

# Home route


@app.route('/')
def index():
    return render_template('index.html')

# Route to display consumer complaints


# @app.route('/complaints')
# def complaints():
#     conn = get_db_connection()
#     complaints = conn.execute('SELECT * FROM ConsumerComplaints').fetchall()
#     conn.close()
#     return render_template('complaints.html', complaints=complaints)

#     if not complaint:
#         conn.close()
#         return "No complaints found", 404

#     if request.method == 'POST':
#         complaint_id = request.form['complaint_id']
#         complaint_date = request.form['complaint_date']
#         customer_name = request.form['customer_name']
#         consumer_mobile_number = request.form['consumer_mobile_number']
#         OHT_name = request.form['OHT_name']
#         issue = request.form['issue']
#         Address = request.form['Address']
#         longitude = request.form['longitude']
#         latitude = request.form['latitude']
#         complaint_details = request.form['complaint_details']
#         status = request.form['status']

#         conn = get_db_connection()

#     conn.execute('''
#         UPDATE ConsumerComplaints
#            SET complaint_date = ?,
#                customer_name = ?,
#                consumer_mobile_number = ?,
#                OHT_name = ?,
#                issue = ?,
#                Address = ?,
#                longitude = ?,
#                latitude = ?,
#                complaint_details = ?,
#                status = ?
#          WHERE id = ?
#     ''', (complaint_date, customer_name, consumer_mobile_number, OHT_name, issue, Address, longitude, latitude, complaint_details, status, complaint_id))
#     conn.commit()
#     conn.close()
#     return redirect(url_for('complaints'))
#     conn.close()
#     return render_template('complaints.html', complaints=complaints)

@app.route('/complaints')
def complaints():
    conn = get_db_connection()
    # DISTINCT values for dropdowns
    # --- 1) Load DISTINCT values for dropdowns ---
    statuses = [row['status'] for row in conn.execute(
        "SELECT DISTINCT status FROM ConsumerComplaints WHERE status IS NOT NULL AND status <> '' ORDER BY status"
    ).fetchall()]
    oht_names = [row['OHT_name'] for row in conn.execute(
        "SELECT DISTINCT OHT_name FROM ConsumerComplaints WHERE OHT_name IS NOT NULL AND OHT_name <> '' ORDER BY OHT_name"
    ).fetchall()]
    issues = [row['issue'] for row in conn.execute(
        "SELECT DISTINCT issue FROM ConsumerComplaints WHERE issue IS NOT NULL AND issue <> '' ORDER BY issue"
    ).fetchall()]

    # Read filter values from the URL query string (?param=value)
    id = request.args.get('id', '').strip()
    complaint_date_from = request.args.get('date_from', '').strip()
    complaint_date_to = request.args.get('date_to', '').strip()
    sel_statuses = request.args.getlist(
        'status')       # e.g. ['Open','Closed']
    sel_oht_names = request.args.getlist(
        'oht_name')    # e.g. ['OHT-12','OHT-15']
    sel_issues = request.args.getlist('issue')          # e.g. ['Leakage']
    q = request.args.get('q', '').strip()
    # Start SQL
    sql = """
        SELECT id, complaint_date, customer_name, consumer_mobile_number, OHT_name, issue, Address, longitude, latitude, complaint_details, status
        FROM ConsumerComplaints
    """
    where = []
    params = []

    if complaint_date_from:
        where.append("complaint_date >= ?")
        params.append(complaint_date_from)
    if complaint_date_to:
        where.append("complaint_date <= ?")
        params.append(complaint_date_to)

    # Filter: exact status
    if sel_statuses:
        where.append(f"status IN ({','.join(['?']*len(sel_statuses))})")
        params.extend(sel_statuses)
    # Filter: OHT_name partial match (case-insensitive)
    if sel_oht_names:
        where.append(f"OHT_name IN ({','.join(['?']*len(sel_oht_names))})")
        params.extend(sel_oht_names)
    # Filter: issue partial match (case-insensitive)
    if sel_issues:
        where.append(f"issue IN ({','.join(['?']*len(sel_issues))})")
        params.extend(sel_issues)

    # Filter: free-text search
    if q:
        where.append("""
            (LOWER(customer_name) LIKE ? 
             OR LOWER(complaint_details) LIKE ? 
             OR consumer_mobile_number LIKE ?)
        """)
        like_val = f"%{q.lower()}%"
        params.extend([like_val, like_val, f"%{q}%"])
        # Combine WHERE clauses if there are any
    if where:
        sql += " WHERE " + " AND ".join(where)
        # Always order newest first by date then id
    sql += " ORDER BY complaint_date DESC, id DESC"
    # Execute the query with parameters
    conn = get_db_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    # --- 5) Render template ---
    return render_template(
        'complaints.html',
        complaints=rows,
        statuses=statuses,
        oht_names=oht_names,
        issues=issues,
        filters={
            'date_from': complaint_date_from,
            'date_to': complaint_date_to,
            'status': sel_statuses,
            'oht_name': sel_oht_names,
            'issue': sel_issues,
            'q': q
        }
    )


# Route to add a complaint (GET shows form, POST handles submission)


@app.route('/complaints/add', methods=('GET', 'POST'))
def add_complaint():
    if request.method == 'POST':
        complaint_date = request.form['complaint_date']
        customer_name = request.form['customer_name']
        consumer_mobile_number = request.form['consumer_mobile_number']
        OHT_name = request.form['OHT_name']
        issue = request.form['issue']
        Address = request.form['Address']
        longitude = request.form['longitude']
        latitude = request.form['latitude']
        complaint_details = request.form['complaint_details']
        status = request.form['status']

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO ConsumerComplaints 
            (complaint_date, customer_name, consumer_mobile_number, OHT_name, issue, Address, longitude, latitude, complaint_details, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,?)
        ''', (complaint_date, customer_name, consumer_mobile_number, OHT_name, issue, Address, longitude, latitude, complaint_details, status))
        conn.commit()
        conn.close()
        return redirect(url_for('complaints'))

    return render_template('add_complaint.html')

# if __name__ == '__main__':
#     app.run(debug=True)

# ------------ TEAMWORK: LIST ------------


# @app.route('/teamwork')
# def teamwork():
#     conn = get_db_connection()
#     # Join with ConsumerComplaints to show customer/complaint context if linked
#     rows = conn.execute('''
#         SELECT
#             t.id, t.work_date, t.team_member, t.OHT, t.area, t.work_description,
#             t.complaint_id,
#             c.customer_name AS consumer_name,
#             c.complaint_details AS complaint_details
#         FROM TeamWork t
#         LEFT JOIN ConsumerComplaints c ON t.complaint_id = c.id
#         ORDER BY t.work_date DESC, t.id DESC
#     ''').fetchall()
#     conn.close()
#     return render_template('teamwork.html', teamwork=rows)


@app.route('/teamwork')
def teamwork():
    conn = get_db_connection()
    # --- Dropdown data ---
    team_members = [row['team_member'] for row in conn.execute(
        "SELECT DISTINCT team_member FROM TeamWork WHERE team_member IS NOT NULL AND team_member<>'' ORDER BY team_member"
    ).fetchall()]
    oht_names = [row['OHT'] for row in conn.execute(
        "SELECT DISTINCT OHT FROM TeamWork WHERE OHT IS NOT NULL AND OHT<>'' ORDER BY OHT"
    ).fetchall()]
    areas = [row['area'] for row in conn.execute(
        "SELECT DISTINCT area FROM TeamWork WHERE area IS NOT NULL AND area<>'' ORDER BY area"
    ).fetchall()]
    work_discriptions = [row['work_description'] for row in conn.execute(
        "SELECT DISTINCT work_description FROM TeamWork WHERE work_description IS NOT NULL AND work_description<>'' ORDER BY work_description"
    ).fetchall()]
    complaint_ids = [row['complaint_id'] for row in conn.execute(
        "SELECT DISTINCT complaint_id FROM TeamWork WHERE complaint_id IS NOT NULL ORDER BY complaint_id"
    ).fetchall()]
    # --- 1) Read filter values from the URL query string ---
    # --- Read filters ---
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    sel_team_members = request.args.getlist('team_member')
    sel_oht_names = request.args.getlist('OHT')
    sel_areas = request.args.getlist('area')
    sel_work_descriptions = request.args.getlist('work_description')
    sel_complaint_ids = request.args.getlist('complaint_id')
    q = request.args.get('q', '').strip()
    # --- Build SQL ---
    sql = """
      SELECT 
        t.id, t.work_date, t.team_member, t.OHT, t.area, t.work_description,
        t.complaint_id,
        c.customer_name AS complaint_customer,
        c.complaint_details AS complaint_summary
      FROM TeamWork t
      LEFT JOIN ConsumerComplaints c ON t.complaint_id = c.id
    """
    where, params = [], []
    if date_from:
        where.append("t.work_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("t.work_date <= ?")
        params.append(date_to)
    if sel_team_members:
        where.append(
            f"t.team_member IN ({','.join(['?']*len(sel_team_members))})")
        params.extend(sel_team_members)
    if sel_oht_names:
        where.append(f"t.OHT IN ({','.join(['?']*len(sel_oht_names))})")
        params.extend(sel_oht_names)
    if sel_areas:
        where.append(f"t.area IN ({','.join(['?']*len(sel_areas))})")
        params.extend(sel_areas)
    if sel_work_descriptions:
        where.append(
            f"t.work_description IN ({','.join(['?']*len(sel_work_descriptions))})")
        params.extend(sel_work_descriptions)
    if sel_complaint_ids:
        where.append(
            f"t.complaint_id IN ({','.join(['?']*len(sel_complaint_ids))})")
        params.extend(sel_complaint_ids)
    if q:
        like_val = f"%{q.lower()}%"
        where.append(
            "(LOWER(t.work_description) LIKE ? OR LOWER(c.customer_name) LIKE ? OR LOWER(c.complaint_details) LIKE ?)")
        params.extend([like_val, like_val, like_val])

    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.work_date DESC, t.id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    # --- 5) Render template ---
    return render_template(
        'teamwork.html',
        teamwork=rows,
        team_members=team_members,
        oht_names=oht_names,
        areas=areas,
        work_descriptions=work_discriptions,
        complaint_ids=complaint_ids,

        filters={
            'date_from': date_from,
            'date_to': date_to,
            'team_member': sel_team_members,
            'OHT': sel_oht_names,
            'area': sel_areas,
            'work_description': sel_work_descriptions,
            'complaint_id': sel_complaint_ids,
            'q': q


        }
    )

# @app.route('/teamwork')
# def teamwork():
#     conn = get_db_connection()

#     # Dropdown data
#     team_members = [row['team_member'] for row in conn.execute(
#         "SELECT DISTINCT team_member FROM TeamWork WHERE team_member IS NOT NULL AND team_member<>'' ORDER BY team_member"
#     ).fetchall()]
#     oht_names = [row['OHT'] for row in conn.execute(
#         "SELECT DISTINCT OHT FROM TeamWork WHERE OHT IS NOT NULL AND OHT<>'' ORDER BY OHT"
#     ).fetchall()]
#     areas = [row['area'] for row in conn.execute(
#         "SELECT DISTINCT area FROM TeamWork WHERE area IS NOT NULL AND area<>'' ORDER BY area"
#     ).fetchall()]
#     work_descriptions = [row['work_description'] for row in conn.execute(
#         "SELECT DISTINCT work_description FROM TeamWork WHERE work_description IS NOT NULL AND work_description<>'' ORDER BY work_description"
#     ).fetchall()]
#     complaint_ids = [row['complaint_id'] for row in conn.execute(
#         "SELECT DISTINCT complaint_id FROM TeamWork WHERE complaint_id IS NOT NULL ORDER BY complaint_id"
#     ).fetchall()]
#     customer_names = [row['customer_name'] for row in conn.execute(
#         "SELECT DISTINCT customer_name FROM ConsumerComplaints WHERE customer_name IS NOT NULL AND customer_name<>'' ORDER BY customer_name"
#     ).fetchall()]
#     complaint_details = [row['complaint_details'] for row in conn.execute(
#         "SELECT DISTINCT complaint_details FROM ConsumerComplaints WHERE complaint_details IS NOT NULL AND complaint_details<>'' ORDER BY complaint_details"
#     ).fetchall()]

#     # Read filters
#     date_from = request.args.get('date_from', '').strip()
#     date_to = request.args.get('date_to', '').strip()
#     sel_team_members = request.args.getlist('team_member')
#     sel_oht_names = request.args.getlist('OHT')
#     sel_areas = request.args.getlist('area')
#     sel_work_descriptions = request.args.getlist('work_description')
#     sel_complaint_ids = request.args.getlist('complaint_id')
#     sel_ustomer_names = request.args.getlist('customer_name')
#     sel_complaint_details = request.args.getlist('complaint_details')
#     q = request.args.get('q', '').strip()

#     # Build SQL
#     sql = """
#       SELECT
#         t.id, t.work_date, t.team_member, t.OHT, t.area, t.work_description,
#         t.complaint_id,
#         c.customer_name AS complaint_customer,
#         c.complaint_details AS complaint_summary
#       FROM TeamWork t
#       LEFT JOIN ConsumerComplaints c ON t.complaint_id = c.id
#     """
#     where, params = [], []

#     if date_from:
#         where.append("t.work_date >= ?"); params.append(date_from)
#     if date_to:
#         where.append("t.work_date <= ?"); params.append(date_to)

#     if sel_team_members:
#         where.append(f"t.team_member IN ({','.join(['?']*len(sel_team_members))})")
#         params.extend(sel_team_members)
#     if sel_oht_names:
#         where.append(f"t.OHT IN ({','.join(['?']*len(sel_oht_names))})")
#         params.extend(sel_oht_names)
#     if sel_areas:
#         where.append(f"t.area IN ({','.join(['?']*len(sel_areas))})")
#         params.extend(sel_areas)
#     if sel_work_descriptions:
#         where.append(f"t.work_description IN ({','.join(['?']*len(sel_work_descriptions))})")
#         params.extend(sel_work_descriptions)
#     if sel_complaint_ids:
#         where.append(f"t.complaint_id IN ({','.join(['?']*len(sel_complaint_ids))})")
#         params.extend(sel_complaint_ids)

#     if q:
#         like_val = f"%{q.lower()}%"
#         where.append(
#             "(LOWER(t.work_description) LIKE ? OR LOWER(c.customer_name) LIKE ? OR LOWER(c.complaint_details) LIKE ?)"
#         )
#         params.extend([like_val, like_val, like_val])

#     # ✅ Always add WHERE here, after all filters processed
#     if where:
#         sql += " WHERE " + " AND ".join(where)

#     sql += " ORDER BY t.work_date DESC, t.id DESC"

#     rows = conn.execute(sql, params).fetchall()
#     conn.close()

#     return render_template(
#         'teamwork.html',
#         teamwork=rows,
#         team_members=team_members,
#         oht_names=oht_names,
#         areas=areas,
#         work_descriptions=work_descriptions,
#         complaint_ids=complaint_ids,
#         customer_names=customer_names,
#         complaint_details=complaint_details,
#         filters={
#             'date_from': date_from,
#             'date_to': date_to,
#             'team_member': sel_team_members,
#             'OHT': sel_oht_names,
#             'area': sel_areas,
#             'work_description': sel_work_descriptions,
#             'complaint_id': sel_complaint_ids,
#             'customer_name': sel_ustomer_names,
#             'complaint_details': sel_complaint_details,
#             'q': q
#         }
#     )
# ------------ TEAMWORK: ADD FORM ------------


@app.route('/teamwork/add', methods=('GET', 'POST'))
def add_teamwork():
    conn = get_db_connection()
    # For dropdown: show existing complaints (id + a short label)
    complaints = conn.execute('''
        SELECT id, customer_name || ' - ' || complaint_details AS label
        FROM ConsumerComplaints
        ORDER BY id DESC
    ''').fetchall()

    if request.method == 'POST':
        work_date = request.form['work_date']
        team_member = request.form['team_member']
        OHT = request.form['OHT']
        area = request.form['area']
        # Convert complaint_id to None if blank
        work_description = request.form['work_description']
        complaint_id_raw = request.form['complaint_id']  # can be empty
        # material_used = request.form['material_used']

        # Convert complaint_id to None if blank
        complaint_id = int(
            complaint_id_raw) if complaint_id_raw.strip() else None

        conn.execute('''
            INSERT INTO TeamWork (work_date, team_member, OHT, area, work_description, complaint_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (work_date, team_member, OHT, area, work_description, complaint_id))
        conn.commit()
        conn.close()
        return redirect(url_for('teamwork'))

    conn.close()
    return render_template('add_teamwork.html', complaints=complaints)
    print("Updated database successfully!")

# ------------ MATERIALS: LIST ------------


# @app.route('/materials')
# def materials():
#     conn = get_db_connection()
#     rows = conn.execute('''
#         SELECT
#             m.id, m.material_name, m.quantity_used, m.work_id,
#             t.work_date, t.team_member, t.work_description
#         FROM Materials m
#         LEFT JOIN TeamWork t ON m.work_id = t.id
#         ORDER BY m.id DESC
#     ''').fetchall()
#     conn.close()
#     return render_template('materials.html', materials=rows)

@app.route('/materials')
def materials():
    conn = get_db_connection()

    # --- Dropdown data for Select2 ---
    material_names = [row['material_name'] for row in conn.execute(
        "SELECT DISTINCT material_name FROM Materials WHERE material_name IS NOT NULL AND material_name<>'' ORDER BY material_name"
    ).fetchall()]

    team_members = [row['team_member'] for row in conn.execute(
        "SELECT DISTINCT team_member FROM TeamWork WHERE team_member IS NOT NULL AND team_member<>'' ORDER BY team_member"
    ).fetchall()]

    work_ids = [row['id'] for row in conn.execute(
        "SELECT DISTINCT id FROM TeamWork ORDER BY id"
    ).fetchall()]

    # --- Read filter values from URL ---
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    sel_material_names = request.args.getlist('material_name')
    sel_team_members = request.args.getlist('team_member')
    sel_work_ids = request.args.getlist('work_id')
    q = request.args.get('q', '').strip()

    # --- Build base SQL ---
    sql = """
      SELECT 
        m.id, m.material_name, m.quantity_used, m.work_id,
        t.work_date, t.team_member, t.work_description
      FROM Materials m
      LEFT JOIN TeamWork t ON m.work_id = t.id
    """
    where, params = [], []

    # --- Apply filters ---
    if date_from:
        where.append("t.work_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("t.work_date <= ?")
        params.append(date_to)

    if sel_material_names:
        where.append(
            f"m.material_name IN ({','.join(['?']*len(sel_material_names))})")
        params.extend(sel_material_names)

    if sel_team_members:
        where.append(
            f"t.team_member IN ({','.join(['?']*len(sel_team_members))})")
        params.extend(sel_team_members)

    if sel_work_ids:
        where.append(f"m.work_id IN ({','.join(['?']*len(sel_work_ids))})")
        params.extend(sel_work_ids)

    if q:
        like_val = f"%{q.lower()}%"
        where.append(
            "(LOWER(m.material_name) LIKE ? OR LOWER(t.work_description) LIKE ?)")
        params.extend([like_val, like_val])

    # --- Final WHERE ---
    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += " ORDER BY t.work_date DESC, m.id DESC"

    # --- Execute ---
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    # --- Render ---
    return render_template(
        'materials.html',
        materials=rows,
        material_names=material_names,
        team_members=team_members,
        work_ids=work_ids,
        filters={
            'date_from': date_from,
            'date_to': date_to,
            'material_name': sel_material_names,
            'team_member': sel_team_members,
            'work_id': sel_work_ids,
            'q': q
        }
    )


# ------------ MATERIALS: ADD FORM ------------


# @app.route('/materials/add', methods=('GET', 'POST'))
# def add_material():
#     conn = get_db_connection()
#     # For dropdown: list works to attach materials to
#     works = conn.execute('''
#         SELECT id, work_date || ' - ' || team_member || ' - ' || COALESCE(work_description, '') AS label
#         FROM TeamWork
#         ORDER BY work_date DESC, id DESC
#     ''').fetchall()

#     if request.method == 'POST':
#         material_name = request.form['material_name']
#         quantity_used_raw = request.form['quantity_used']  # could be empty
#         work_id_raw = request.form['work_id']

#         # Sanitize numeric conversions
#         quantity_used = float(
#             quantity_used_raw) if quantity_used_raw.strip() else None
#         work_id = int(work_id_raw) if work_id_raw.strip() else None

#         conn.execute('''
#             INSERT INTO Materials (material_name, quantity_used, work_id)
#             VALUES (?, ?, ?)
#         ''', (material_name, quantity_used, work_id))
#         conn.commit()
#         conn.close()
#         return redirect(url_for('materials'))

#     conn.close()
#     return render_template('add_material.html', works=works)

@app.route('/materials/add', methods=('GET', 'POST'))
def add_material():
    conn = get_db_connection()

    works = conn.execute('''
        SELECT id, work_date || ' - ' || team_member || ' - ' || 
               COALESCE(work_description, '') AS label
        FROM TeamWork
        ORDER BY work_date DESC, id DESC
    ''').fetchall()

    preselected_work_id = request.args.get('work_id', '').strip()

    if request.method == 'POST':
        material_name = request.form['material_name']
        quantity_used_raw = request.form['quantity_used']
        work_id_raw = request.form['work_id']

        quantity_used = float(
            quantity_used_raw) if quantity_used_raw.strip() else None
        work_id = int(work_id_raw) if work_id_raw.strip() else None

        # Insert into DB
        conn.execute('''
            INSERT INTO Materials (material_name, quantity_used, work_id)
            VALUES (?, ?, ?)
        ''', (material_name, quantity_used, work_id))
        conn.commit()
        conn.close()

        # Check which button was clicked
        if 'save_add_another' in request.form:
            # Redirect back to add page with same work_id
            return redirect(url_for('add_material', work_id=work_id))
        else:
            # Normal save → go to materials list
            return redirect(url_for('materials'))

    conn.close()
    return render_template('add_material.html', works=works, preselected_work_id=preselected_work_id)

    # ------------- EDIT COMPLAINT -----------------


@app.route('/complaints/<int:complaint_id>/edit', methods=('GET', 'POST'))
def edit_complaint(complaint_id):
    conn = get_db_connection()
    complaint = conn.execute('SELECT * FROM ConsumerComplaints WHERE id = ?',
                             (complaint_id,)).fetchone()

    if not complaint:
        conn.close()
        return "Complaint not found", 404

    if request.method == 'POST':
        complaint_date = request.form['complaint_date']
        customer_name = request.form['customer_name']
        consumer_mobile_number = request.form['consumer_mobile_number']
        OHT_name = request.form['OHT_name']
        issue = request.form['issue']
        Address = request.form['Address']
        longitude = request.form['longitude']
        latitude = request.form['latitude']
        complaint_details = request.form['complaint_details']
        status = request.form['status']

        conn.execute('''
            UPDATE ConsumerComplaints
            SET complaint_date = ?, customer_name = ?, consumer_mobile_number = ?,
                OHT_name = ?, issue = ?, Address = ?, longitude = ?, latitude = ?,
                complaint_details = ?, status = ?
            WHERE id = ?
        ''', (complaint_date, customer_name, consumer_mobile_number, OHT_name,
              issue, Address, longitude, latitude, complaint_details, status, complaint_id))
        conn.commit()
        conn.close()
        return redirect(url_for('complaints'))

    conn.close()
    return render_template('edit_complaint.html', c=complaint)

    # ------------- DELETE COMPLAINT -----------------


@app.route('/complaints/<int:complaint_id>/delete', methods=('POST',))
def delete_complaint(complaint_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM ConsumerComplaints WHERE id = ?',
                 (complaint_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('complaints'))

    # ----------- EDIT TEAMWORK -----------


@app.route('/teamwork/<int:work_id>/edit', methods=('GET', 'POST'))
def edit_teamwork(work_id):
    conn = get_db_connection()
    work = conn.execute(
        'SELECT * FROM TeamWork WHERE id = ?', (work_id,)).fetchone()
    if not work:
        conn.close()
        return "Work not found", 404

    # For dropdown: list complaints to link to
    complaints = conn.execute('''
        SELECT id, customer_name || ' - ' || complaint_details AS label
        FROM ConsumerComplaints
        ORDER BY id DESC
    ''').fetchall()

    if request.method == 'POST':
        work_date = request.form['work_date']
        team_member = request.form['team_member']
        OHT = request.form['OHT']
        area = request.form['area']
        work_description = request.form['work_description']
        complaint_id_raw = request.form['complaint_id']
        complaint_id = int(
            complaint_id_raw) if complaint_id_raw.strip() else None
        conn.execute('''
            UPDATE TeamWork
            SET work_date = ?, team_member = ?, OHT = ?, area = ?, work_description = ?, complaint_id = ?
            WHERE id = ?
        ''', (work_date, team_member, OHT, area, work_description, complaint_id, work_id))
        conn.commit()
        conn.close()
        return redirect(url_for('teamwork'))
        conn.close()
    return render_template('edit_teamwork.html', w=work, complaints=complaints)

# ----------- DELETE TEAMWORK -----------


@app.route('/teamwork/<int:work_id>/delete', methods=('POST',))
def delete_teamwork(work_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM TeamWork WHERE id = ?', (work_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('teamwork'))

    # ----------- EDIT MATERIAL -----------


@app.route('/materials/<int:material_id>/edit', methods=('GET', 'POST'))
def edit_material(material_id):
    conn = get_db_connection()

    m = conn.execute('SELECT * FROM Materials WHERE id = ?',
                     (material_id,)).fetchone()
    if not m:
        conn.close()
        return "Material not found", 404

    # For dropdown: list all works to link to
    works = conn.execute('''
        SELECT id, work_date || ' - ' || team_member || ' - ' || COALESCE(work_description, '') AS label
        FROM TeamWork
        ORDER BY work_date DESC, id DESC
    ''').fetchall()

    if request.method == 'POST':
        material_name = request.form['material_name']
        quantity_used_raw = request.form['quantity_used']
        work_id_raw = request.form['work_id']

        quantity_used = float(
            quantity_used_raw) if quantity_used_raw.strip() else None
        work_id = int(work_id_raw) if work_id_raw.strip() else None

        conn.execute('''
            UPDATE Materials
               SET material_name = ?,
                   quantity_used = ?,
                   work_id = ?
             WHERE id = ?
        ''', (material_name, quantity_used, work_id, material_id))
        conn.commit()
        conn.close()
        return redirect(url_for('materials'))

    conn.close()
    return render_template('edit_material.html', m=m, works=works)


# ----------- DELETE MATERIAL -----------
@app.route('/materials/<int:material_id>/delete', methods=('POST',))
def delete_material(material_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM Materials WHERE id = ?', (material_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('materials'))

# ----------- VIEW MATERIAL FROM TEAM WORK-----------


@app.route('/teamwork/<int:work_id>/materials')
def materials_for_work(work_id):
    conn = get_db_connection()

    # Get the work info (optional, to show at top)
    work = conn.execute(
        "SELECT id, work_date, team_member, OHT, area, work_description "
        "FROM TeamWork WHERE id = ?", (work_id,)
    ).fetchone()
    if not work:
        conn.close()
        return "TeamWork record not found", 404

    # Get all materials linked to this work
    mats = conn.execute(
        "SELECT id, material_name, quantity_used "
        "FROM Materials WHERE work_id = ? ORDER BY id", (work_id,)
    ).fetchall()

    conn.close()
    return render_template(
        'materials_for_work.html',
        work=work,
        materials=mats
    )


# ----------- FILE UPLOAD ---------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------------------------------------------
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'.xlsx', '.csv'}


def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/complaints/import', methods=('GET', 'POST'))
def import_complaints():
    if request.method == 'GET':
        return render_template('import_complaints.html')
    # POST: file uploaded
    file = request.files.get('file')
    if not file or file.filename == '':
        return render_template('import_complaints.html', error='Please choose a file (.xlsx or .csv).')

    # if not allowed_file(file.filename):
    #     return render_template('import_complaints.html', error='Unsupported file type. Use .xlsx or .csv.')
    if not allowed_file(file.filename):
        return render_template('import_complaints.html', error='Unsupported file type. Use .xlsx or .csv.')
# Save temporary
    # ext = os.path.splitext(file.filename).lower()[1]
    # tmp_path = os.path.join(UPLOAD_FOLDER, f'complaints_upload{ext}')
    # file.save(tmp_path)
    root, ext = os.path.splitext(file.filename)
    ext = ext.lower()
    tmp_path = os.path.join(UPLOAD_FOLDER, f'complaints_upload{ext}')
    file.save(tmp_path)
# Parse with pandas
    import pandas as pd
    try:
        if ext == '.xlsx':
            df = pd.read_excel(tmp_path)
        else:
            df = pd.read_csv(tmp_path)
    except Exception as e:
        return render_template('import_complaints.html', error=f'Could not read file: {e}')


    # Normalize columns: expected schema
    # Required: complaint_date, customer_name, complaint_details
    # Optional: consumer_mobile_number, OHT_name, longitude, latitude, status
    # Accept case-insensitive headers and common variants
    colmap = {
        'complaint_date': ['complaint_date', 'date', 'complaintdate'],
        'customer_name': ['customer_name', 'name', 'customer'],
        'consumer_mobile_number': ['consumer_mobile_number', 'mobile', 'phone', 'mobile_number'],
        'OHT_name': ['OHT_name', 'oht', 'oht_name'],
        'issue': ['issue', 'problem', 'issue_description'],
        'Address': ['Address', 'address', 'location'],
        'longitude': ['longitude', 'long', 'lng'],
        'latitude': ['latitude', 'lat'],
        'complaint_details': ['complaint_details', 'details', 'description'],
        'status': ['status', 'state']
    }
    # Build a mapping from found df columns to our canonical keys
    found = {}
    lower_cols = {c.lower(): c for c in df.columns}
    for key, aliases in colmap.items():
        for a in aliases:
            if a.lower() in lower_cols:
                found[key] = lower_cols[a.lower()]
                break

    missing_required = [k for k in ['complaint_date',
                                    'customer_name', 'complaint_details'] if k not in found]
    if missing_required:
            return render_template('import_complaints.html',
                               error=f"Missing required columns: {', '.join(missing_required)}")

    # Build cleaned records and validate
    records = []
    errors = []


    def to_date(v):
        if pd.isna(v):
            return None
        # Try pandas date parsing, then format YYYY-MM-DD
        try:
            d = pd.to_datetime(v)
            return d.strftime('%Y-%m-%d')
        except Exception:
            return None


    for idx, row in df.iterrows():
        rec = {
            'complaint_date': to_date(row[found['complaint_date']]),
            'customer_name': str(row[found['customer_name']]).strip() if not pd.isna(row[found['customer_name']]) else '',
            'consumer_mobile_number': str(row[found['consumer_mobile_number']]).strip() if 'consumer_mobile_number' in found and not pd.isna(row[found['consumer_mobile_number']]) else None,
            'OHT_name': str(row[found['OHT_name']]).strip() if 'OHT_name' in found and not pd.isna(row[found['OHT_name']]) else None,
            'issue': str(row[found['issue']]).strip() if 'issue' in found and not pd.isna(row[found['issue']]) else None,
            # 'issue': str(row.get('issue', '')).strip() if 'issue' in row and not pd.isna(row.get('issue')) else '',
            'Address': str(row.get('Address', '')).strip() if 'Address' in row and not pd.isna(row.get('Address')) else '',
            'longitude': float(row[found['longitude']]) if 'longitude' in found and not pd.isna(row[found['longitude']]) else None,
            'latitude': float(row[found['latitude']]) if 'latitude' in found and not pd.isna(row[found['latitude']]) else None,
            'complaint_details': str(row[found['complaint_details']]).strip() if not pd.isna(row[found['complaint_details']]) else '',
            'status': str(row[found['status']]).strip() if 'status' in found and not pd.isna(row[found['status']]) else 'Open'
        }

        row_errors = []
        if not rec['complaint_date']:
            row_errors.append('Invalid complaint_date')
        if not rec['customer_name']:
            row_errors.append('customer_name required')
        if not rec['complaint_details']:
            row_errors.append('complaint_details required')
        if rec['consumer_mobile_number'] and not re.match(r'^\+?\d{10,15}$', rec['consumer_mobile_number']):
            row_errors.append('Invalid consumer_mobile_number format')

        # Basic longitude/latitude sanity range
        if rec['longitude'] is not None and not (-180 <= rec['longitude'] <= 180):
            row_errors.append('longitude out of range')
        if rec['latitude'] is not None and not (-90 <= rec['latitude'] <= 90):
            row_errors.append('latitude out of range')

        if row_errors:
            # +2 because header + 1-based
            errors.append({'row_index': int(idx)+2, 'errors': row_errors})
        else:
            records.append(rec)

    # Store parsed data into session or a temp file for confirmation
    # For simplicity, write a JSON sidecar file
    json_path = os.path.join(UPLOAD_FOLDER, 'complaints_upload.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False)

    summary = {
        'total_rows': len(df),
        'valid_rows': len(records),
        'invalid_rows': len(errors)
    }

    return render_template('import_complaints_preview.html',
                           summary=summary,
                           errors=errors,
                           tmp_ext=ext)
    # Redirect to confirmation page

@app.route('/complaints/import/confirm', methods=['POST'])
def import_complaints_confirm():
    import json
    json_path = os.path.join(UPLOAD_FOLDER, 'complaints_upload.json')
    if not os.path.exists(json_path):
        return redirect(url_for('import_complaints'))

    with open(json_path, 'r', encoding='utf-8') as f:
        records = json.load(f)

    if not records:
        return redirect(url_for('complaints'))

    conn = get_db_connection()
    try:
        conn.execute('BEGIN')
        conn.executemany('''
            INSERT INTO ConsumerComplaints
              (complaint_date, customer_name, consumer_mobile_number,
               OHT_name, issue, address, longitude, latitude, complaint_details, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', [
            (r['complaint_date'], r['customer_name'], r['consumer_mobile_number'],
             r['OHT_name'], r['issue'], r['Address'], r['longitude'], r['latitude'], r['complaint_details'], r['status'])
            for r in records
        ])
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return render_template('import_complaints.html', error='Import failed. Transaction rolled back.')
    conn.close()

    try:
        os.remove(json_path)
    except Exception:
        pass
    return redirect(url_for('complaints'))



    # --------------------
    # START THE SERVER
    # --------------------
print("Updated database successfully!")
if __name__ == '__main__':
        app.run(debug=True)
