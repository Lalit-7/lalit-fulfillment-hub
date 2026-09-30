"""
Fulfillment Hub — Flask application
Covers all 4 phases:
  Phase 1: Order pipeline dashboard + priority visibility
  Phase 2: Two-warehouse stock accuracy + transfers
  Phase 3: Pick/pack verification + staging/pickup confirmation
  Phase 4: Issue flagging / accountability
"""

import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify, g

app = Flask(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip() or None

# ---------------------------------------------------------------------------
# Database helpers (Simple per-request connection — Supabase pooler handles
# server-side connection reuse, so app-level pooling is not needed and
# actually breaks on Vercel's serverless environment.)
# ---------------------------------------------------------------------------

def get_db():
    """Get a database connection for the current request."""
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL)
        g.db.autocommit = False
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        try:
            if exception:
                db.rollback()
            db.close()
        except Exception:
            pass


def query_db(query, args=(), one=False):
    """Execute a query and return results as list of dicts."""
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, args)
    rv = [dict(row) for row in cur.fetchall()]
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    """Execute a write query and commit."""
    db = get_db()
    cur = db.cursor()
    cur.execute(query, args)
    db.commit()
    cur.close()


# ---------------------------------------------------------------------------
# Demo data auto-refresh — keeps timestamps perpetually fresh
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Demo data presets and auto-refresh — keeps tags, warnings, & demo state perpetually fresh
# ---------------------------------------------------------------------------

ACTIVE_ORDER_PRESETS = [
    # (order_num, status, is_priority, dl_offset, courier, created_ago, staged_ago)
    # Received (16 core + 6 extra = 22 orders)
    ("ORD-1001", "received", 0, 48, None, 1.0, None),
    ("ORD-1002", "received", 0, 36, None, 2.0, None),
    ("ORD-1003", "received", 1, 2, None, 0.5, None),        # PRIORITY + AT RISK (<3h)
    ("ORD-1004", "received", 1, -1, None, 4.0, None),       # PRIORITY + OVERDUE
    ("ORD-1005", "received", 0, 24, None, 3.0, None),
    ("ORD-1006", "received", 1, -2, None, 5.0, None),       # PRIORITY + OVERDUE
    ("ORD-1007", "received", 0, 30, None, 0.8, None),
    ("ORD-1008", "received", 0, 44, None, 1.5, None),
    ("ORD-1009", "received", 1, 1.5, None, 0.4, None),      # PRIORITY + AT RISK (<3h)
    ("ORD-1010", "received", 0, 18, None, 2.5, None),
    ("ORD-1011", "received", 0, 60, None, 0.2, None),
    ("ORD-1012", "received", 1, 10, None, 1.0, None),
    ("ORD-1013", "received", 0, 28, None, 3.5, None),
    ("ORD-1014", "received", 0, 42, None, 0.7, None),
    ("ORD-1015", "received", 1, 8, None, 0.5, None),
    ("ORD-1016", "received", 0, 20, None, 1.2, None),
    ("ORD-1041", "received", 0, 50, None, 1.5, None),
    ("ORD-1042", "received", 0, 38, None, 2.0, None),
    ("ORD-1043", "received", 0, 26, None, 1.0, None),
    ("ORD-1044", "received", 0, 44, None, 2.5, None),
    ("ORD-1045", "received", 0, 32, None, 0.8, None),
    ("ORD-1046", "received", 0, 22, None, 1.2, None),

    # Processing (5 core + 4 extra = 9 orders)
    ("ORD-1017", "processing", 0, 30, "Delhivery", 5.0, None),
    ("ORD-1018", "processing", 1, 2, "BlueDart", 2.0, None),       # PRIORITY + AT RISK
    ("ORD-1019", "processing", 0, 20, "DTDC", 6.0, None),
    ("ORD-1020", "processing", 1, -0.5, "Delhivery", 8.0, None),   # PRIORITY + OVERDUE
    ("ORD-1021", "processing", 0, 40, None, 4.0, None),
    ("ORD-1047", "processing", 0, 28, "Delhivery", 5.0, None),
    ("ORD-1048", "processing", 0, 35, "BlueDart", 4.0, None),
    ("ORD-1049", "processing", 0, 18, "DTDC", 6.0, None),
    ("ORD-1050", "processing", 0, 42, "Shadowfax", 3.5, None),

    # Picking (5 core + 3 extra = 8 orders)
    ("ORD-1022", "picking", 0, 18, "Ecom Express", 8.0, None),
    ("ORD-1023", "picking", 1, 1.5, "BlueDart", 4.0, None),       # PRIORITY + AT RISK
    ("ORD-1024", "picking", 0, 12, "Delhivery", 10.0, None),
    ("ORD-1025", "picking", 1, -1, "Shadowfax", 6.0, None),       # PRIORITY + OVERDUE
    ("ORD-1026", "picking", 0, 24, "DTDC", 7.0, None),
    ("ORD-1051", "picking", 0, 15, "Ecom Express", 7.0, None),
    ("ORD-1052", "picking", 0, 22, "Delhivery", 9.0, None),
    ("ORD-1053", "picking", 0, 30, "BlueDart", 8.0, None),

    # Packing (5 core + 3 extra = 8 orders)
    ("ORD-1027", "packing", 1, -0.5, "BlueDart", 12.0, None),      # PRIORITY + OVERDUE
    ("ORD-1028", "packing", 1, 2.5, "Delhivery", 6.0, None),       # PRIORITY + AT RISK
    ("ORD-1029", "packing", 0, 10, "DTDC", 14.0, None),
    ("ORD-1030", "packing", 0, 22, "Ecom Express", 9.0, None),
    ("ORD-1031", "packing", 0, 16, "BlueDart", 8.0, None),
    ("ORD-1054", "packing", 0, 12, "DTDC", 11.0, None),
    ("ORD-1055", "packing", 0, 20, "Shadowfax", 13.0, None),
    ("ORD-1056", "packing", 0, 28, "Ecom Express", 10.0, None),

    # Staged (5 core + 2 extra = 7 orders)
    ("ORD-1032", "staged", 1, 8, "Delhivery", 16.0, 1.0),
    ("ORD-1033", "staged", 1, 2, "Shadowfax", 10.0, 3.0),          # PRIORITY + AT RISK + STAGED TOO LONG (3h)
    ("ORD-1034", "staged", 0, 20, "BlueDart", 18.0, 0.5),
    ("ORD-1035", "staged", 0, 6, "DTDC", 20.0, 5.0),              # STAGED TOO LONG (5h)
    ("ORD-1036", "staged", 0, 14, "Ecom Express", 12.0, 1.5),
    ("ORD-1057", "staged", 0, 18, "Delhivery", 14.0, 1.2),
    ("ORD-1058", "staged", 0, 10, "BlueDart", 22.0, 4.0),          # STAGED TOO LONG (4h)

    # Shipped (4 core demo shipped orders)
    ("ORD-1037", "shipped", 1, 48, "BlueDart", 20.0, None),
    ("ORD-1038", "shipped", 0, 36, "DTDC", 30.0, None),
    ("ORD-1039", "shipped", 0, 24, "Ecom Express", 26.0, None),
    ("ORD-1040", "shipped", 0, 48, "Delhivery", 24.0, None),
]


def _refresh_demo_timestamps():
    """Shift timestamps forward and restore all tags/demo states every 30 minutes.

    Restores:
    - All 58 active orders to their designed status columns (Received, Processing, Picking, Packing, Staged).
    - Exact staged_at timestamps so "⚠ Staged too long" tags reliably appear on ORD-1033, ORD-1035, and ORD-1058.
    - Exact deadlines so "Priority At Risk" and "Overdue" badges stay fresh relative to current time.
    - Stock levels & transfer in_transit/requested states.
    - Issue open/resolved statuses and pick verification items.
    """
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cur = conn.cursor()

        # Check demo version
        cur.execute("SELECT value FROM metadata WHERE key = 'demo_version'")
        ver_row = cur.fetchone()
        current_version = ver_row[0] if ver_row else None

        # Lock the row to prevent concurrent refreshes
        cur.execute("SELECT value FROM metadata WHERE key = 'last_refreshed' FOR UPDATE")
        row = cur.fetchone()
        if not row:
            conn.rollback()
            conn.close()
            return

        last_refreshed = datetime.fromisoformat(row[0])
        now = get_now()
        elapsed_secs = (now - last_refreshed).total_seconds()

        # Refresh if >30 minutes have passed OR if demo_version is not v3_tags_refresh
        needs_refresh = (elapsed_secs >= 1800 or current_version != 'v3_tags_refresh')
        if not needs_refresh:
            conn.rollback()
            conn.close()
            return

        # 1. Restore all core active orders to their exact designed status and timestamps
        active_order_numbers = []
        for order_num, status, is_pri, dl_offset, courier, created_ago, staged_ago in ACTIVE_ORDER_PRESETS:
            active_order_numbers.append(order_num)
            created_at = (now - timedelta(hours=created_ago)).isoformat()
            deadline = (now + timedelta(hours=dl_offset)).isoformat() if dl_offset is not None else None
            staged_at = (now - timedelta(hours=staged_ago)).isoformat() if staged_ago is not None else None
            shipped_at = (now - timedelta(hours=2)).isoformat() if status == "shipped" else None

            cur.execute("""
                UPDATE "order" SET
                    status = %s,
                    is_priority = %s,
                    deadline = %s,
                    created_at = %s,
                    staged_at = %s,
                    shipped_at = %s,
                    courier = COALESCE(%s, courier)
                WHERE order_number = %s
            """, (status, is_pri, deadline, created_at, staged_at, shipped_at, courier, order_num))

        # 2. Shift timestamps for bulk shipped orders (ORD-1059+) so they stay realistic
        if elapsed_secs > 0:
            cur.execute("""
                UPDATE "order" SET
                    created_at = (created_at::timestamp + (interval '1 second' * %s))::text,
                    deadline   = CASE WHEN deadline IS NOT NULL
                                 THEN (deadline::timestamp + (interval '1 second' * %s))::text END,
                    shipped_at = CASE WHEN shipped_at IS NOT NULL
                                 THEN (shipped_at::timestamp + (interval '1 second' * %s))::text END
                WHERE order_number != ALL(%s)
            """, (elapsed_secs, elapsed_secs, elapsed_secs, active_order_numbers))

        # 3. Restore stock for secondary-only products (Product 7, 9, 11, 13)
        cur.execute("""
            UPDATE stock SET quantity = 0 WHERE product_id IN (7, 9, 11, 13) AND warehouse_id = 1;
            UPDATE stock SET quantity = 15 WHERE product_id = 7 AND warehouse_id = 2;
            UPDATE stock SET quantity = 18 WHERE product_id = 9 AND warehouse_id = 2;
            UPDATE stock SET quantity = 12 WHERE product_id = 11 AND warehouse_id = 2;
            UPDATE stock SET quantity = 14 WHERE product_id = 13 AND warehouse_id = 2;
        """)

        # 4. Reset transfers table to fresh demo transfers (multiple in_transit, requested, completed)
        cur.execute("DELETE FROM transfer")
        cur.execute("""
            INSERT INTO transfer (product_id, quantity, from_warehouse_id, to_warehouse_id, status, created_at)
            VALUES 
                (7, 6, 2, 1, 'in_transit', %s),
                (9, 5, 2, 1, 'in_transit', %s),
                (11, 4, 2, 1, 'requested', %s),
                (14, 3, 2, 1, 'completed', %s)
        """, (
            (now - timedelta(hours=2)).isoformat(),
            (now - timedelta(hours=3)).isoformat(),
            (now - timedelta(minutes=45)).isoformat(),
            (now - timedelta(days=2)).isoformat()
        ))

        # 5. Reset issue records (3 open, 2 resolved)
        issue_resets = [
            ('ORD-1004', 1, 4.0),
            ('ORD-1031', 0, 2.0),
            ('ORD-1018', 0, 1.0),
            ('ORD-1006', 1, 12.0),
            ('ORD-1011', 0, 0.5),
        ]
        for ord_num, resolved, hours_ago in issue_resets:
            cur.execute("""
                UPDATE issue SET
                    resolved = %s,
                    created_at = %s
                WHERE order_id = (SELECT id FROM "order" WHERE order_number = %s)
            """, (resolved, (now - timedelta(hours=hours_ago)).isoformat(), ord_num))

        # 6. Reset pick verification items on ORD-1022 and ORD-1024
        cur.execute("""
            UPDATE order_item SET picked_ok = 0
            WHERE id IN (
                SELECT oi.id FROM order_item oi
                JOIN "order" o ON o.id = oi.order_id
                WHERE o.order_number IN ('ORD-1022', 'ORD-1024')
            )
        """)

        # 7. Ensure secondary product items are present on test orders
        test_order_items = [
            ('ORD-1002', 7, 1),
            ('ORD-1005', 9, 1),
            ('ORD-1007', 11, 1),
            ('ORD-1009', 13, 1),
            ('ORD-1011', 7, 2),
            ('ORD-1013', 9, 1),
            ('ORD-1015', 11, 2),
            ('ORD-1017', 9, 1),
            ('ORD-1018', 7, 1),
            ('ORD-1019', 11, 2),
            ('ORD-1021', 13, 1),
        ]
        for ord_num, pid, qty in test_order_items:
            cur.execute("""
                INSERT INTO order_item (order_id, product_id, quantity, picked_ok)
                SELECT o.id, %s, %s, 0
                FROM "order" o
                WHERE o.order_number = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM order_item oi WHERE oi.order_id = o.id AND oi.product_id = %s
                  )
            """, (pid, qty, ord_num, pid))

        # 8. Update metadata markers
        cur.execute("UPDATE metadata SET value = %s WHERE key = 'last_refreshed'", (now.isoformat(),))
        cur.execute("""
            INSERT INTO metadata (key, value) VALUES ('demo_version', 'v3_tags_refresh')
            ON CONFLICT (key) DO UPDATE SET value = 'v3_tags_refresh'
        """)

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Demo refresh error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.before_request
def before_request_hook():
    """Auto-refresh demo data on each request if stale."""
    _refresh_demo_timestamps()


# ---------------------------------------------------------------------------
# Status flow
# ---------------------------------------------------------------------------

STATUS_ORDER = ["received", "processing", "picking", "packing", "staged", "shipped"]
STAGED_THRESHOLD_HOURS = 2  # highlight staged orders older than this


def next_status(current):
    idx = STATUS_ORDER.index(current)
    if idx < len(STATUS_ORDER) - 1:
        return STATUS_ORDER[idx + 1]
    return None


IST = timezone(timedelta(hours=5, minutes=30))

def get_now():
    """Return current Indian Standard Time (IST) as naive datetime for consistency."""
    return datetime.now(IST).replace(tzinfo=None)


def compute_risk(is_priority, deadline_str, status):
    """Return 'on_track', 'at_risk', 'overdue', or None."""
    if status == "shipped":
        return "shipped"
    if not deadline_str:
        return None
    try:
        if isinstance(deadline_str, datetime):
            deadline = deadline_str
        else:
            deadline = datetime.fromisoformat(str(deadline_str))
    except (ValueError, TypeError):
        return None
    now = get_now()
    if now > deadline:
        return "overdue"
    remaining = (deadline - now).total_seconds()
    # at_risk if less than 3 hours remain
    if remaining < 3 * 3600:
        return "at_risk"
    return "on_track"


# ---------------------------------------------------------------------------
# Template context helpers
# ---------------------------------------------------------------------------

@app.context_processor
def inject_helpers():
    return {
        "compute_risk": compute_risk,
        "now": get_now,
        "STAGED_THRESHOLD_HOURS": STAGED_THRESHOLD_HOURS,
        "timedelta": timedelta,
    }


# =========================================================================
# PHASE 1 — Dashboard + Order Detail
# =========================================================================

@app.route("/")
def dashboard():
    """Main board: orders grouped by status columns."""
    orders = query_db("""
        SELECT o.*,
               COUNT(oi.id) AS item_count
        FROM "order" o
        LEFT JOIN order_item oi ON oi.order_id = o.id
        GROUP BY o.id
        ORDER BY o.is_priority DESC, o.created_at ASC
    """)

    # Group by status
    columns = {s: [] for s in STATUS_ORDER}
    for o in orders:
        o["risk"] = compute_risk(o["is_priority"], o["deadline"], o["status"])
        # Check staged-too-long
        if o["status"] == "staged" and o.get("staged_at"):
            try:
                staged_val = o["staged_at"]
                if isinstance(staged_val, datetime):
                    staged_time = staged_val
                else:
                    staged_time = datetime.fromisoformat(str(staged_val))
                if (get_now() - staged_time).total_seconds() > STAGED_THRESHOLD_HOURS * 3600:
                    o["staged_too_long"] = True
            except (ValueError, TypeError):
                pass
        columns.get(o["status"], []).append(o)

    # Summary strip counts (combined into 1 query)
    total_open = sum(len(columns[s]) for s in STATUS_ORDER if s != "shipped")
    priority_at_risk = sum(
        1 for o in orders
        if o["is_priority"] and o["risk"] in ("at_risk", "overdue") and o["status"] != "shipped"
    )
    counts = query_db("""
        SELECT 
            (SELECT COUNT(*) FROM issue WHERE resolved = 0) AS open_issues,
            (SELECT COUNT(*) FROM transfer WHERE status IN ('requested', 'in_transit')) AS pending_transfers
    """, one=True)
    open_issues = counts["open_issues"] if counts else 0
    pending_transfers = counts["pending_transfers"] if counts else 0

    return render_template(
        "dashboard.html",
        columns=columns,
        status_order=STATUS_ORDER,
        total_open=total_open,
        priority_at_risk=priority_at_risk,
        open_issues=open_issues,
        pending_transfers=pending_transfers,
    )


@app.route("/order/<int:order_id>")
def order_detail(order_id):
    """Order detail view with items, status, actions."""
    order = query_db('SELECT * FROM "order" WHERE id = %s', [order_id], one=True)
    if not order:
        return "Order not found", 404

    order["risk"] = compute_risk(order["is_priority"], order["deadline"], order["status"])

    # Check staged-too-long
    if order["status"] == "staged" and order.get("staged_at"):
        try:
            staged_val = order["staged_at"]
            if isinstance(staged_val, datetime):
                staged_time = staged_val
            else:
                staged_time = datetime.fromisoformat(str(staged_val))
            if (get_now() - staged_time).total_seconds() > STAGED_THRESHOLD_HOURS * 3600:
                order["staged_too_long"] = True
        except (ValueError, TypeError):
            pass

    # Items with product + stock info + transfer info (Single fast SQL JOIN, zero N+1)
    items = query_db("""
        SELECT oi.*, p.name AS product_name, p.sku, p.variant,
               COALESCE(sm.quantity, 0) AS stock_main,
               COALESCE(ss.quantity, 0) AS stock_secondary,
               t.id AS transfer_id, t.status AS transfer_status
        FROM order_item oi
        JOIN product p ON p.id = oi.product_id
        LEFT JOIN stock sm ON sm.product_id = p.id AND sm.warehouse_id = 1
        LEFT JOIN stock ss ON ss.product_id = p.id AND ss.warehouse_id = 2
        LEFT JOIN (
            SELECT DISTINCT ON (product_id) id, product_id, status
            FROM transfer
            WHERE to_warehouse_id = 1 AND status IN ('requested', 'in_transit')
            ORDER BY product_id, created_at DESC
        ) t ON t.product_id = p.id
        WHERE oi.order_id = %s
    """, [order_id])

    # Determine if any item needs a transfer (only in Secondary, not in Main)
    needs_transfer = False
    for item in items:
        item["only_in_secondary"] = (item["stock_main"] < item["quantity"] and item["stock_secondary"] >= item["quantity"])
        if item["only_in_secondary"]:
            needs_transfer = True
        if item.get("transfer_id"):
            item["transfer_pending"] = {"id": item["transfer_id"], "status": item["transfer_status"]}
        else:
            item["transfer_pending"] = None

    # Issues for this order
    issues = query_db("SELECT * FROM issue WHERE order_id = %s ORDER BY created_at DESC", [order_id])

    # All items picked?
    all_picked = all(item["picked_ok"] for item in items) if items else False

    nxt = next_status(order["status"])

    # Can we advance?
    can_advance = True
    block_reason = None
    if order["status"] == "processing" and needs_transfer:
        # Check if ALL needed transfers are completed
        for item in items:
            if item["only_in_secondary"] and not item["transfer_pending"]:
                can_advance = False
                block_reason = "Some items need a stock transfer from Secondary warehouse before picking can begin."
                break
            if item["only_in_secondary"] and item["transfer_pending"] and item["transfer_pending"]["status"] != "completed":
                can_advance = False
                block_reason = "Stock transfer is still in progress. Wait for completion before advancing."
                break
    if order["status"] == "picking" and not all_picked:
        can_advance = False
        block_reason = "All items must be verified (checked off) before moving to Packing."

    couriers = ["Delhivery", "BlueDart", "DTDC", "Ecom Express", "Shadowfax"]

    return render_template(
        "order_detail.html",
        order=order,
        items=items,
        issues=issues,
        next_status=nxt,
        can_advance=can_advance,
        block_reason=block_reason,
        all_picked=all_picked,
        needs_transfer=needs_transfer,
        couriers=couriers,
        STATUS_ORDER=STATUS_ORDER,
    )


# =========================================================================
# API: Advance order status
# =========================================================================

@app.route("/api/order/<int:order_id>/advance", methods=["POST"])
def api_advance_order(order_id):
    """Advance an order to its next status."""
    order = query_db('SELECT * FROM "order" WHERE id = %s', [order_id], one=True)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    nxt = next_status(order["status"])
    if not nxt:
        return jsonify({"error": "Order is already shipped"}), 400

    # Phase 2: Block advancing to picking if transfer needed
    if order["status"] == "processing":
        items = query_db("""
            SELECT oi.product_id, oi.quantity,
                   COALESCE(sm.quantity, 0) AS stock_main,
                   COALESCE(ss.quantity, 0) AS stock_secondary
            FROM order_item oi
            LEFT JOIN stock sm ON sm.product_id = oi.product_id AND sm.warehouse_id = 1
            LEFT JOIN stock ss ON ss.product_id = oi.product_id AND ss.warehouse_id = 2
            WHERE oi.order_id = %s
        """, [order_id])
        for item in items:
            if item["stock_main"] < item["quantity"] and item["stock_secondary"] >= item["quantity"]:
                # Check transfer
                t = query_db("""
                    SELECT status FROM transfer
                    WHERE product_id = %s AND to_warehouse_id = 1 AND status = 'completed'
                    ORDER BY created_at DESC LIMIT 1
                """, [item["product_id"]], one=True)
                if not t:
                    return jsonify({"error": "Stock transfer required before picking"}), 400

    # Phase 3: Block picking -> packing if not all items checked
    if order["status"] == "picking":
        unchecked = query_db(
            "SELECT COUNT(*) AS cnt FROM order_item WHERE order_id = %s AND picked_ok = 0",
            [order_id], one=True
        )["cnt"]
        if unchecked > 0:
            return jsonify({"error": "All items must be verified before packing"}), 400

    # Record staged_at timestamp when entering staged
    if nxt == "staged":
        execute_db(
            'UPDATE "order" SET status = %s, staged_at = %s WHERE id = %s',
            [nxt, get_now().isoformat(), order_id]
        )
    elif nxt == "shipped":
        execute_db(
            'UPDATE "order" SET status = %s, shipped_at = %s WHERE id = %s',
            [nxt, get_now().isoformat(), order_id]
        )
    else:
        execute_db('UPDATE "order" SET status = %s WHERE id = %s', [nxt, order_id])

    # Phase 2: Deduct stock from Main when entering picking
    if nxt == "picking":
        items = query_db(
            "SELECT product_id, quantity FROM order_item WHERE order_id = %s",
            [order_id]
        )
        for item in items:
            execute_db(
                "UPDATE stock SET quantity = GREATEST(0, quantity - %s) WHERE product_id = %s AND warehouse_id = 1",
                [item["quantity"], item["product_id"]]
            )

    return jsonify({"status": nxt, "order_id": order_id})


# =========================================================================
# API: Update courier
# =========================================================================

@app.route("/api/order/<int:order_id>/courier", methods=["POST"])
def api_update_courier(order_id):
    data = request.get_json()
    courier = data.get("courier", "")
    execute_db('UPDATE "order" SET courier = %s WHERE id = %s', [courier, order_id])
    return jsonify({"ok": True})


# =========================================================================
# PHASE 2 — Inventory + Transfers
# =========================================================================

@app.route("/inventory")
def inventory():
    """Inventory view: products × warehouses."""
    products = query_db("""
        SELECT p.*,
               COALESCE(sm.quantity, 0) AS stock_main,
               COALESCE(ss.quantity, 0) AS stock_secondary
        FROM product p
        LEFT JOIN stock sm ON sm.product_id = p.id AND sm.warehouse_id = 1
        LEFT JOIN stock ss ON ss.product_id = p.id AND ss.warehouse_id = 2
        ORDER BY p.name, p.variant
    """)
    return render_template("inventory.html", products=products)


@app.route("/transfers")
def transfers():
    """Transfers list."""
    transfers_list = query_db("""
        SELECT t.*, p.name AS product_name, p.sku, p.variant,
               wf.name AS from_warehouse, wt.name AS to_warehouse
        FROM transfer t
        JOIN product p ON p.id = t.product_id
        JOIN warehouse wf ON wf.id = t.from_warehouse_id
        JOIN warehouse wt ON wt.id = t.to_warehouse_id
        ORDER BY
            CASE t.status WHEN 'requested' THEN 0 WHEN 'in_transit' THEN 1 ELSE 2 END,
            t.created_at DESC
    """)
    return render_template("transfers.html", transfers=transfers_list)


@app.route("/api/transfer/request", methods=["POST"])
def api_request_transfer():
    """Create a transfer request from Secondary to Main."""
    data = request.get_json()
    product_id = data["product_id"]
    quantity = data.get("quantity", 1)

    # Check if there's already a pending transfer
    existing = query_db("""
        SELECT id FROM transfer
        WHERE product_id = %s AND to_warehouse_id = 1 AND status IN ('requested', 'in_transit')
    """, [product_id], one=True)
    if existing:
        return jsonify({"error": "Transfer already pending", "transfer_id": existing["id"]}), 400

    execute_db("""
        INSERT INTO transfer (product_id, quantity, from_warehouse_id, to_warehouse_id, status, created_at)
        VALUES (%s, %s, 2, 1, 'requested', %s)
    """, [product_id, quantity, get_now().isoformat()])

    return jsonify({"ok": True})


@app.route("/api/transfer/<int:transfer_id>/advance", methods=["POST"])
def api_advance_transfer(transfer_id):
    """Advance a transfer's status."""
    transfer = query_db("SELECT * FROM transfer WHERE id = %s", [transfer_id], one=True)
    if not transfer:
        return jsonify({"error": "Transfer not found"}), 404

    if transfer["status"] == "requested":
        execute_db("UPDATE transfer SET status = 'in_transit' WHERE id = %s", [transfer_id])
        return jsonify({"status": "in_transit"})
    elif transfer["status"] == "in_transit":
        # Complete: move stock from Secondary to Main
        execute_db("UPDATE transfer SET status = 'completed' WHERE id = %s", [transfer_id])
        # Decrease Secondary
        execute_db(
            "UPDATE stock SET quantity = GREATEST(0, quantity - %s) WHERE product_id = %s AND warehouse_id = %s",
            [transfer["quantity"], transfer["product_id"], transfer["from_warehouse_id"]]
        )
        # Increase Main
        existing = query_db(
            "SELECT id FROM stock WHERE product_id = %s AND warehouse_id = %s",
            [transfer["product_id"], transfer["to_warehouse_id"]], one=True
        )
        if existing:
            execute_db(
                "UPDATE stock SET quantity = quantity + %s WHERE product_id = %s AND warehouse_id = %s",
                [transfer["quantity"], transfer["product_id"], transfer["to_warehouse_id"]]
            )
        else:
            execute_db(
                "INSERT INTO stock (product_id, warehouse_id, quantity) VALUES (%s, %s, %s)",
                [transfer["product_id"], transfer["to_warehouse_id"], transfer["quantity"]]
            )
        return jsonify({"status": "completed"})
    else:
        return jsonify({"error": "Transfer already completed"}), 400


# =========================================================================
# PHASE 3 — Pick/pack verification
# =========================================================================

@app.route("/api/order/<int:order_id>/item/<int:item_id>/pick", methods=["POST"])
def api_pick_item(order_id, item_id):
    """Toggle picked_ok for an order item."""
    data = request.get_json()
    picked = 1 if data.get("picked", False) else 0
    execute_db(
        "UPDATE order_item SET picked_ok = %s WHERE id = %s AND order_id = %s",
        [picked, item_id, order_id]
    )
    # Check if all items now picked
    unchecked = query_db(
        "SELECT COUNT(*) AS cnt FROM order_item WHERE order_id = %s AND picked_ok = 0",
        [order_id], one=True
    )["cnt"]
    return jsonify({"picked": bool(picked), "all_picked": unchecked == 0})


# =========================================================================
# PHASE 4 — Issue flagging
# =========================================================================

@app.route("/issues")
def issues_list():
    """All issues across orders."""
    issues = query_db("""
        SELECT i.*, o.order_number
        FROM issue i
        JOIN "order" o ON o.id = i.order_id
        ORDER BY i.resolved ASC, i.created_at DESC
    """)
    return render_template("issues.html", issues=issues)


@app.route("/api/order/<int:order_id>/issue", methods=["POST"])
def api_create_issue(order_id):
    """Flag a problem on an order."""
    data = request.get_json()
    note = data.get("note", "").strip()
    if not note:
        return jsonify({"error": "Note is required"}), 400
    execute_db(
        "INSERT INTO issue (order_id, note, created_at, resolved) VALUES (%s, %s, %s, 0)",
        [order_id, note, get_now().isoformat()]
    )
    return jsonify({"ok": True})


@app.route("/api/issue/<int:issue_id>/resolve", methods=["POST"])
def api_resolve_issue(issue_id):
    """Mark an issue as resolved."""
    data = request.get_json()
    resolved = 1 if data.get("resolved", True) else 0
    execute_db("UPDATE issue SET resolved = %s WHERE id = %s", [resolved, issue_id])
    return jsonify({"ok": True, "resolved": bool(resolved)})


# =========================================================================
# API: Reset / reload demo state
# =========================================================================

@app.route("/api/demo/reset", methods=["POST", "GET"])
def api_demo_reset():
    """Manual trigger to immediately restore demo transfer & order test data."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE metadata SET value = 'reset_needed' WHERE key = 'demo_version'")
        conn.commit()
        cur.close()
        conn.close()
        _refresh_demo_timestamps()
        return jsonify({"ok": True, "message": "Demo transfer & test data refreshed"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# =========================================================================
# Run
# =========================================================================

if __name__ == "__main__":
    if not DATABASE_URL:
        print("ERROR: Set the DATABASE_URL environment variable.")
        print("Example: set DATABASE_URL=postgresql://user:pass@host/dbname")
    else:
        app.run(debug=True, port=5000)

