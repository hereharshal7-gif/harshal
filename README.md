# VIKSITBHARAT AI: starter app

Login, Gemini chat, daily plan limits, Dodo Payments checkout, and a private admin view.

## Run on your computer
1. Install Python 3.11+, then in this folder: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in the values (see below).
3. Start it: `uvicorn main:app --reload` and open http://localhost:8000

## Keys you need
- **Gemini key**: create in Google AI Studio (aistudio.google.com). Check the current model name there and set GEMINI_MODEL.
- **Dodo Payments**: in the dashboard create two subscription products (Pro, Business) and copy their product IDs, your API key, and a webhook signing key. Start with `test_mode`.
- **Webhook URL**: `https://YOUR-DOMAIN/api/webhook` (use ngrok while testing locally). Enable payment and subscription events.
- **JWT_SECRET**: any long random string. ADMIN_EMAIL: your email, the only one that sees the Admin button.

## Put it online
Deploy this folder to Render, Railway or a small VPS. Set the same values as environment variables, set `APP_URL` to your site address, and use `live_mode` only after test payments work end to end. Put it on a real domain with HTTPS.

## Before you take real money
- Test the full flow in `test_mode`: signup, chat, upgrade, webhook upgrades the plan, cancel downgrades it.
- The webhook and SDK calls follow Dodo's current Python SDK docs; confirm the field names against docs.dodopayments.com during testing.
- Add real Privacy Policy and Terms pages. Check GST and tax rules with a CA.
- SQLite is fine to start. Move to Postgres when you grow, and back up the database file.
- Add email verification, password reset and login rate limits before a big public launch.
- "Unlimited" plans are capped at a fair-use limit (see LIMITS in main.py) so one user cannot run up your Gemini bill. Check that your prices stay above your cost per user.
