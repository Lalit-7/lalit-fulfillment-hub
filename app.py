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
DATABASE_URL = os.environ.get("DATABASE_URL")

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
        LEFT JOIN transfer t ON t.product_id = p.id AND t.to_warehouse_id = 1 AND t.status IN ('requested', 'in_transit')
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
# Run
# =========================================================================

if __name__ == "__main__":
    if not DATABASE_URL:
        print("ERROR: Set the DATABASE_URL environment variable.")
        print("Example: set DATABASE_URL=postgresql://user:pass@host/dbname")
    else:
        app.run(debug=True, port=5000)
