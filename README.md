# Fulfillment Hub

This app helps a small e-commerce team track orders from the moment they come in until they're shipped out. It replaces messy spreadsheets with a simple visual board.

## The Problem

A small online store gets 200–300 orders every day. Right now the team uses spreadsheets and shared folders to manage everything. Orders get lost, priority shipments miss their deadlines, and nobody knows where things stand at a glance.

## What This App Does

- **Shows all orders on one screen** — a board with columns: Received → Processing → Picking → Packing → Staged → Shipped. You can see exactly where every order is.
- **Highlights urgent orders** — priority orders that are running late turn yellow (at risk) or red (overdue) so the team knows what to focus on.
- **Manages two warehouses** — some products are stored in a secondary warehouse. If an order needs something from there, the app lets you request a stock transfer before packing.
- **Makes sure the right items get packed** — during picking, each item has a checkbox. The order can't move forward until every item is checked off.
- **Warns about forgotten packages** — if a packed box has been sitting on the staging shelf for too long without being picked up by the courier, it gets flagged.
- **Tracks problems** — anyone can flag an issue on an order (wrong item, damaged box, delay) and it stays visible until someone resolves it.

## Pages in the App

| Page | What's There |
|---|---|
| **Dashboard** | The main board — all orders in columns, with a summary bar at the top |
| **Order Detail** | Click any order to see its items, stock info, and action buttons |
| **Inventory** | Stock counts for every product in both warehouses |
| **Transfers** | List of stock transfer requests between warehouses |
| **Issues** | All flagged problems across all orders |

## Tech Used

- Python (Flask) for the backend
- PostgreSQL (Neon) for the database
- Plain HTML, CSS, and JavaScript for the frontend
- Hosted on Vercel

## How to Run Locally

```bash
# Install what's needed
pip install -r requirements.txt

# Set your database connection (get this from Neon dashboard)
set DATABASE_URL=your-neon-connection-string-here

# Load demo data
python seed.py

# Start the app
python app.py
```

Then open **http://localhost:5000** in your browser.

## How to Reset the Data

Run `python seed.py` again. It wipes everything and loads fresh demo data.

## File Structure

```
app.py              → The main application (routes, logic)
seed.py             → Script to create tables and load demo data
requirements.txt    → Python packages needed
vercel.json         → Deployment settings for Vercel
static/style.css    → All the styling
static/app.js       → Button clicks, checkboxes, and other interactions
templates/          → HTML pages (dashboard, order detail, inventory, etc.)
```
