"""
Seed script — creates PostgreSQL tables and populates with demo data.
Run: python seed.py
Requires DATABASE_URL environment variable set to your Neon connection string.
"""

import os
import psycopg2
from datetime import datetime, timedelta
import random

DATABASE_URL = os.environ.get("DATABASE_URL")


def create_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS warehouse (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS product (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            sku TEXT NOT NULL UNIQUE,
            variant TEXT
        );

        CREATE TABLE IF NOT EXISTS stock (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES product(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouse(id),
            quantity INTEGER NOT NULL DEFAULT 0,
            UNIQUE(product_id, warehouse_id)
        );

        CREATE TABLE IF NOT EXISTS "order" (
            id SERIAL PRIMARY KEY,
            order_number TEXT NOT NULL UNIQUE,
            customer_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_priority INTEGER NOT NULL DEFAULT 0,
            deadline TEXT,
            status TEXT NOT NULL DEFAULT 'received',
            courier TEXT,
            staged_at TEXT,
            shipped_at TEXT
        );

        CREATE TABLE IF NOT EXISTS order_item (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES "order"(id),
            product_id INTEGER NOT NULL REFERENCES product(id),
            quantity INTEGER NOT NULL DEFAULT 1,
            picked_ok INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS transfer (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES product(id),
            quantity INTEGER NOT NULL DEFAULT 1,
            from_warehouse_id INTEGER NOT NULL REFERENCES warehouse(id),
            to_warehouse_id INTEGER NOT NULL REFERENCES warehouse(id),
            status TEXT NOT NULL DEFAULT 'requested',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS issue (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES "order"(id),
            note TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)


def seed(cur):
    now = datetime.now()

    # ----- Warehouses -----
    cur.execute("INSERT INTO warehouse (name) VALUES ('Main')")
    cur.execute("INSERT INTO warehouse (name) VALUES ('Secondary')")

    # ----- Products (14 products with SKU and variant) -----
    products = [
        ("Classic Cotton T-Shirt", "TEE-BLK-M", "Black / M"),
        ("Classic Cotton T-Shirt", "TEE-BLK-L", "Black / L"),
        ("Classic Cotton T-Shirt", "TEE-WHT-M", "White / M"),
        ("Slim Fit Jeans", "JNS-BLU-32", "Blue / 32"),
        ("Slim Fit Jeans", "JNS-BLU-34", "Blue / 34"),
        ("Canvas Sneakers", "SNK-WHT-9", "White / 9"),
        ("Canvas Sneakers", "SNK-WHT-10", "White / 10"),
        ("Leather Belt", "BLT-BRN-M", "Brown / M"),
        ("Wool Beanie", "BNI-GRY-OS", "Grey / One Size"),
        ("Zip Hoodie", "HDI-NVY-L", "Navy / L"),
        ("Zip Hoodie", "HDI-NVY-XL", "Navy / XL"),
        ("Running Shorts", "SHR-BLK-M", "Black / M"),
        ("Crossbody Bag", "BAG-TAN-OS", "Tan / One Size"),
        ("Polarized Sunglasses", "SNG-BLK-OS", "Black / One Size"),
    ]
    for name, sku, variant in products:
        cur.execute("INSERT INTO product (name, sku, variant) VALUES (%s, %s, %s)",
                     (name, sku, variant))

    # ----- Stock -----
    # Products 9 (Wool Beanie) and 13 (Crossbody Bag) are ONLY in Secondary → triggers transfer flow.
    stock_data = [
        (1, 45, 10), (2, 30, 5), (3, 25, 0), (4, 18, 8),
        (5, 12, 6), (6, 20, 0), (7, 15, 3), (8, 22, 4),
        (9, 0, 18), (10, 10, 5), (11, 8, 3), (12, 35, 0),
        (13, 0, 12), (14, 16, 7),
    ]
    for pid, main_q, sec_q in stock_data:
        if main_q > 0:
            cur.execute("INSERT INTO stock (product_id, warehouse_id, quantity) VALUES (%s, 1, %s)",
                         (pid, main_q))
        if sec_q > 0:
            cur.execute("INSERT INTO stock (product_id, warehouse_id, quantity) VALUES (%s, 2, %s)",
                         (pid, sec_q))

    # ----- Orders -----
    customers = [
        "Aarav Mehta", "Priya Sharma", "Rohan Gupta", "Sneha Patel",
        "Vikram Singh", "Ananya Reddy", "Karan Joshi", "Meera Nair",
        "Arjun Kapoor", "Divya Iyer", "Raj Malhotra", "Pooja Desai",
        "Amit Kumar", "Neha Bhatia", "Siddharth Rao", "Kavya Menon",
        "Varun Agarwal", "Ishita Banerjee", "Nikhil Chauhan", "Riya Saxena",
        "Manish Tiwari", "Swati Kulkarni", "Deepak Verma", "Tanya Mishra",
        "Gaurav Pandey", "Aditi Sinha", "Harsh Vardhan", "Simran Kaur",
        "Rahul Dubey", "Nisha Jain", "Kunal Thakur", "Megha Chopra",
        "Ankit Rawat", "Pallavi Sen", "Yash Goyal", "Ritika Dutta",
        "Om Prakash", "Shruti Pandey", "Farhan Qureshi", "Diya Nambiar",
        "Mohit Bhatt", "Lavanya Rao", "Suresh Pillai", "Aisha Khan",
        "Tanmay Bose",
    ]

    couriers = ["Delhivery", "BlueDart", "DTDC", "Ecom Express", "Shadowfax"]

    order_templates = [
        # (status, is_priority, deadline_offset_hours, courier, created_ago_hours, staged_ago_hours)
        # deadline_offset: positive = future (ON TRACK/AT RISK), negative = past (OVERDUE)
        # Risk: >3h left = on_track, <3h left = at_risk, negative = overdue

        # --- Received (16 orders) ---
        # Mix: mostly ON TRACK, a few PRIORITY+AT RISK, a couple PRIORITY+OVERDUE
        ("received", False, 48,   None,          1,    None),     # ON TRACK
        ("received", False, 36,   None,          2,    None),     # ON TRACK
        ("received", True,  2,    None,          0.5,  None),     # PRIORITY + AT RISK (<3h)
        ("received", True,  -1,   None,          4,    None),     # PRIORITY + OVERDUE
        ("received", False, 24,   None,          3,    None),     # ON TRACK
        ("received", True,  -2,   None,          5,    None),     # PRIORITY + OVERDUE
        ("received", False, 30,   None,          0.8,  None),     # ON TRACK
        ("received", False, 44,   None,          1.5,  None),     # ON TRACK
        ("received", True,  1.5,  None,          0.4,  None),     # PRIORITY + AT RISK (<3h)
        ("received", False, 18,   None,          2.5,  None),     # ON TRACK
        ("received", False, 60,   None,          0.2,  None),     # ON TRACK
        ("received", True,  10,   None,          1,    None),     # PRIORITY + ON TRACK
        ("received", False, 28,   None,          3.5,  None),     # ON TRACK
        ("received", False, 42,   None,          0.7,  None),     # ON TRACK
        ("received", True,  8,    None,          0.5,  None),     # PRIORITY + ON TRACK
        ("received", False, 20,   None,          1.2,  None),     # ON TRACK

        # --- Processing (5 orders) ---
        ("processing", False, 30,  "Delhivery",  5,    None),     # ON TRACK
        ("processing", True,  2,   "BlueDart",   2,    None),     # PRIORITY + AT RISK
        ("processing", False, 20,  "DTDC",       6,    None),     # ON TRACK
        ("processing", True,  -0.5,"Delhivery",  8,    None),     # PRIORITY + OVERDUE
        ("processing", False, 40,  None,         4,    None),     # ON TRACK

        # --- Picking (5 orders) ---
        ("picking", False, 18,     "Ecom Express", 8,  None),     # ON TRACK
        ("picking", True,  1.5,    "BlueDart",     4,  None),     # PRIORITY + AT RISK
        ("picking", False, 12,     "Delhivery",   10,  None),     # ON TRACK
        ("picking", True,  -1,     "Shadowfax",    6,  None),     # PRIORITY + OVERDUE
        ("picking", False, 24,     "DTDC",         7,  None),     # ON TRACK

        # --- Packing (5 orders) ---
        ("packing", True,  -0.5,   "BlueDart",    12,  None),     # PRIORITY + OVERDUE
        ("packing", True,  2.5,    "Delhivery",    6,  None),     # PRIORITY + AT RISK
        ("packing", False, 10,     "DTDC",        14,  None),     # ON TRACK
        ("packing", False, 22,     "Ecom Express",  9, None),     # ON TRACK
        ("packing", False, 16,     "BlueDart",      8, None),     # ON TRACK

        # --- Staged (5 orders) ---
        # staged_ago: >2h = "staged too long" warning
        ("staged", True,  8,       "Delhivery",   16,  1),        # PRIORITY + ON TRACK (staged 1h ago — fine)
        ("staged", True,  2,       "Shadowfax",   10,  3),        # PRIORITY + AT RISK + STAGED TOO LONG (3h)
        ("staged", False, 20,      "BlueDart",    18,  0.5),      # ON TRACK (staged 30min ago — fine)
        ("staged", False, 6,       "DTDC",        20,  5),        # ON TRACK + STAGED TOO LONG (5h)
        ("staged", False, 14,      "Ecom Express", 12, 1.5),      # ON TRACK (staged 1.5h ago — fine)

        # --- Shipped (4 orders) ---
        ("shipped", True,  48,     "BlueDart",    20,  None),      # PRIORITY + SHIPPED
        ("shipped", False, 36,     "DTDC",        30,  None),      # SHIPPED
        ("shipped", False, 24,     "Ecom Express", 26, None),      # SHIPPED
        ("shipped", False, 48,     "Delhivery",   24,  None),      # SHIPPED
    ]

    order_ids = []
    for i, (status, is_pri, dl_offset, courier, created_ago, staged_ago) in enumerate(order_templates):
        order_num = f"ORD-{1001 + i}"
        customer = customers[i % len(customers)]
        created_at = (now - timedelta(hours=created_ago)).isoformat()
        deadline = (now + timedelta(hours=dl_offset)).isoformat() if dl_offset is not None else None

        staged_at = None
        shipped_at = None
        if status == "staged" and staged_ago is not None:
            staged_at = (now - timedelta(hours=staged_ago)).isoformat()
        if status == "shipped":
            shipped_at = (now - timedelta(hours=random.randint(1, 5))).isoformat()

        cur.execute("""
            INSERT INTO "order" (order_number, customer_name, created_at, is_priority,
                                 deadline, status, courier, staged_at, shipped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (order_num, customer, created_at, int(is_pri), deadline, status, courier, staged_at, shipped_at))
        order_ids.append(cur.fetchone()[0])

    # ----- Order Items -----
    random.seed(42)
    for idx, oid in enumerate(order_ids):
        num_items = random.choice([1, 1, 2, 2, 3])
        chosen_products = random.sample(range(1, 15), num_items)
        for pid in chosen_products:
            qty = random.choice([1, 1, 1, 2])
            status = order_templates[idx][0]
            if status in ("packing", "staged", "shipped"):
                picked = 1
            elif status == "picking":
                picked = 1
            else:
                picked = 0
            cur.execute("""
                INSERT INTO order_item (order_id, product_id, quantity, picked_ok)
                VALUES (%s, %s, %s, %s)
            """, (oid, pid, qty, picked))

    # Override: 2 picking orders with some items NOT picked (to test pick verification)
    picking_order_id_1 = order_ids[21]  # picking order index 21
    picking_order_id_2 = order_ids[23]  # picking order index 23
    cur.execute("""
        UPDATE order_item SET picked_ok = 0
        WHERE id = (
            SELECT id FROM order_item WHERE order_id = %s ORDER BY id LIMIT 1
        )
    """, (picking_order_id_1,))
    cur.execute("""
        UPDATE order_item SET picked_ok = 0
        WHERE id = (
            SELECT id FROM order_item WHERE order_id = %s ORDER BY id LIMIT 1
        )
    """, (picking_order_id_2,))

    # ----- Orders needing transfers (secondary-only products) -----
    processing_order_1 = order_ids[16]
    processing_order_2 = order_ids[18]
    cur.execute("INSERT INTO order_item (order_id, product_id, quantity, picked_ok) VALUES (%s, 9, 1, 0)",
                (processing_order_1,))
    cur.execute("INSERT INTO order_item (order_id, product_id, quantity, picked_ok) VALUES (%s, 13, 2, 0)",
                (processing_order_2,))

    # Add secondary-only products to several received orders (to test transfer requests)
    for recv_idx, pid in [(4, 9), (6, 13), (8, 9), (12, 13)]:
        cur.execute("INSERT INTO order_item (order_id, product_id, quantity, picked_ok) VALUES (%s, %s, 1, 0)",
                    (order_ids[recv_idx], pid))

    # ----- Transfers -----
    cur.execute("""
        INSERT INTO transfer (product_id, quantity, from_warehouse_id, to_warehouse_id, status, created_at)
        VALUES (9, 5, 2, 1, 'in_transit', %s)
    """, ((now - timedelta(hours=3)).isoformat(),))

    cur.execute("""
        INSERT INTO transfer (product_id, quantity, from_warehouse_id, to_warehouse_id, status, created_at)
        VALUES (9, 3, 2, 1, 'requested', %s)
    """, ((now - timedelta(minutes=30)).isoformat(),))

    cur.execute("""
        INSERT INTO transfer (product_id, quantity, from_warehouse_id, to_warehouse_id, status, created_at)
        VALUES (13, 3, 2, 1, 'completed', %s)
    """, ((now - timedelta(days=2)).isoformat(),))

    # ----- Issues (3 open, 2 resolved) -----
    issue_data = [
        (order_ids[3],  'Priority order missed same-day cutoff. Customer notified of 1-day delay.', 4, 1),
        (order_ids[30], 'Box was staged but courier driver could not locate it. Re-staged near loading dock.', 2, 0),
        (order_ids[17], 'Item SKU BNI-GRY-OS not found on shelf despite system stock. Need physical recount.', 1, 0),
        (order_ids[5],  'Customer reported wrong size variant listed. Verified SKU — marketplace listing error. Forwarded to catalog team.', 12, 1),
        (order_ids[10], 'Packing tape seal broken on box during staging. Repacked and re-sealed.', 0.5, 0),
    ]
    for oid, note, hours_ago, resolved in issue_data:
        cur.execute("""
            INSERT INTO issue (order_id, note, created_at, resolved)
            VALUES (%s, %s, %s, %s)
        """, (oid, note, (now - timedelta(hours=hours_ago)).isoformat(), resolved))

    # ----- Metadata (for auto-refresh) -----
    cur.execute("INSERT INTO metadata (key, value) VALUES ('last_refreshed', %s)", (now.isoformat(),))


def main():
    if not DATABASE_URL:
        print("ERROR: Set the DATABASE_URL environment variable.")
        print("Example: set DATABASE_URL=postgresql://user:pass@host/dbname")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Drop existing tables in reverse dependency order
    cur.execute("""
        DROP TABLE IF EXISTS metadata CASCADE;
        DROP TABLE IF EXISTS issue CASCADE;
        DROP TABLE IF EXISTS transfer CASCADE;
        DROP TABLE IF EXISTS order_item CASCADE;
        DROP TABLE IF EXISTS "order" CASCADE;
        DROP TABLE IF EXISTS stock CASCADE;
        DROP TABLE IF EXISTS product CASCADE;
        DROP TABLE IF EXISTS warehouse CASCADE;
    """)
    print("Dropped existing tables.")

    create_tables(cur)
    seed(cur)

    conn.commit()
    cur.close()
    conn.close()
    print("Database seeded successfully on Neon!")
    print("Run 'python app.py' to start the server.")


if __name__ == "__main__":
    main()
