
# Cash Command System — Streamlit + QuickBooks Online MVP

This is a working hybrid product demo for:

- QuickBooks Online OAuth connection
- Pulling open AR, open AP, and bank/cash balances
- 13-week rolling cash forecast
- Scenario controls
- AI-assisted risk flags
- Weekly Cash Decision Report

## 1. Local setup

```bash
python -m venv .venv
source .venv/bin/activate   # Mac/Linux
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
streamlit run app.py
```

## 2. Intuit Developer setup

Create an app in Intuit Developer.

Use sandbox first.

Set your redirect URI to your Streamlit app URL.

For local testing, Streamlit commonly runs at:

```text
http://localhost:8501
```

For Streamlit Community Cloud, use:

```text
https://your-app-name.streamlit.app
```

The redirect URI in Intuit must exactly match `QBO_REDIRECT_URI`.

## 3. Required Streamlit secrets

```toml
QBO_CLIENT_ID = "..."
QBO_CLIENT_SECRET = "..."
QBO_REDIRECT_URI = "https://your-app-name.streamlit.app"
QBO_ENVIRONMENT = "sandbox"
```

## 4. Deployment on Streamlit Community Cloud

1. Push this folder to GitHub.
2. Go to Streamlit Community Cloud.
3. Create a new app from your GitHub repo.
4. Set the app file to `app.py`.
5. Add secrets in app settings.
6. Copy the deployed app URL.
7. Add that URL to Intuit Developer redirect URIs.
8. Update `QBO_REDIRECT_URI` to the exact same URL.

## 5. How to link from Netlify

On your Netlify consulting site, add a button:

```html
<a href="https://your-app-name.streamlit.app" target="_blank" class="btn primary">
  View Cash Command Demo →
</a>
```

## 6. MVP limitations

This is intentionally MVP-level:

- Token storage is session-based for demo use.
- It is not multi-client production SaaS yet.
- Scheduled Monday reports require a backend scheduler later.
- Risk flags are rules-based first; the AI learning layer comes from customer/vendor history and forecast-vs-actual variance.

## 7. Production upgrade path

For real client use:

- Store refresh tokens in encrypted database.
- Add user login and company-level permissions.
- Add scheduled weekly sync/reporting.
- Add audit logs.
- Add a paid always-on backend such as Railway, Fly.io, Render paid, or AWS.


## v2 token handling update

This version persists sandbox/demo QBO tokens to:

```text
.qbo_tokens.local.json
```

Why this matters:

- QBO access tokens expire quickly.
- QBO refresh tokens can rotate.
- The app must save the newest refresh token after every refresh response.

This file-based persistence is only for local/sandbox/personal demo use.

For production SaaS, replace `.qbo_tokens.local.json` with encrypted database storage, such as Supabase or Neon Postgres.

Do not commit `.qbo_tokens.local.json` to GitHub.
