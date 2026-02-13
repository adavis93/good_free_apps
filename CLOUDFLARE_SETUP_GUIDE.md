# Cloudflare Workers Deployment Guide
## Good Free Apps - Admin Portal Backend Setup

This guide will walk you through setting up the Cloudflare Worker that powers your analytics and admin dashboard.

---

## Prerequisites

- Cloudflare account (free tier works fine)
- Node.js installed on your computer (v16 or later)
  - Check: `node --version`
  - Download from: https://nodejs.org/

---

## Step 1: Install Wrangler (Cloudflare's CLI)

Open your terminal and run:

```bash
npm install -g wrangler
```

After installation, verify it worked:

```bash
wrangler --version
```

---

## Step 2: Login to Cloudflare

Run this command and follow the prompts to authenticate:

```bash
wrangler login
```

This will open a browser window asking you to authorize Wrangler.

---

## Step 3: Create a KV Namespace

KV (Key-Value) storage is where your analytics data and feedback will be stored.

Run this command:

```bash
wrangler kv:namespace create "ANALYTICS_KV"
```

You'll see output like this:

```
🌀 Creating namespace with title "good-free-apps-api-ANALYTICS_KV"
✨ Success!
Add the following to your wrangler.toml:
[[kv_namespaces]]
binding = "ANALYTICS_KV"
id = "abc123def456..."
```

**IMPORTANT**: Copy the `id` value (it will be a long string like `abc123def456...`)

---

## Step 4: Update wrangler.toml

Open the `wrangler.toml` file and replace this line:

```toml
id = "YOUR_KV_NAMESPACE_ID"
```

With your actual KV namespace ID:

```toml
id = "abc123def456..."  # Use your actual ID from Step 3
```

Save the file.

---

## Step 5: Set Your Admin Token (Environment Variable)

Choose a secure admin password/token. This will protect your admin dashboard.

Run this command (replace `your-secure-token-here` with your chosen password):

```bash
wrangler secret put ADMIN_TOKEN
```

When prompted, enter your chosen admin token and press Enter.

**IMPORTANT**: Remember this token! You'll need it to:
1. Access the admin dashboard (admin.html)
2. Update the admin.html file (see Step 7)

---

## Step 6: Deploy the Worker

From the directory containing `worker.js` and `wrangler.toml`, run:

```bash
wrangler deploy
```

You'll see output like:

```
✨ Success! Uploaded good-free-apps-api (X.XX sec)
  https://good-free-apps-api.YOUR-SUBDOMAIN.workers.dev
```

**IMPORTANT**: Copy your Worker URL! It will look like:
`https://good-free-apps-api.YOUR-SUBDOMAIN.workers.dev`

---

## Step 7: Update Your Website Files

You need to update 3 files with your Worker URL.

### File 1: analytics.js

Find this line:
```javascript
ENDPOINT: 'https://good-free-apps-api.YOUR-SUBDOMAIN.workers.dev/api/track',
```

Replace `YOUR-SUBDOMAIN` with your actual subdomain from Step 6.

Then change:
```javascript
ENABLED: false,
```

To:
```javascript
ENABLED: true,
```

### File 2: admin.html

Find this line:
```javascript
const API_ENDPOINT = 'https://good-free-apps-api.YOUR-SUBDOMAIN.workers.dev/api';
```

Replace `YOUR-SUBDOMAIN` with your actual subdomain.

Also update the admin token to match what you set in Step 5:
```javascript
const ADMIN_TOKEN = 'your-secure-token-here';  // Change this to your token from Step 5
```

### File 3: index.html

Find this line in the `submitFeedback` function:
```javascript
const response = await fetch('https://good-free-apps-api.YOUR-SUBDOMAIN.workers.dev/api/feedback', {
```

Replace `YOUR-SUBDOMAIN` with your actual subdomain.

---

## Step 8: Deploy Your Website

Push all your updated files to your GitHub repository:

```bash
git add .
git commit -m "Connect analytics and admin portal to Cloudflare Worker"
git push
```

If you have Netlify connected to your GitHub repo, it will automatically deploy the changes.

---

## Step 9: Test Everything

### Test 1: Analytics Tracking

1. Open your website in a browser
2. Open the browser's Developer Console (F12 or right-click → Inspect → Console)
3. Navigate to any page
4. You should see: `[Analytics] Object { type: "page_view", app: "...", ... }`

### Test 2: Feedback Submission

1. On the hub page, click "Send Feedback"
2. Fill out the form and submit
3. You should see an alert: "Thank you for your feedback!"
4. Check the console for errors

### Test 3: Admin Dashboard

1. Go to: `https://your-site.com/admin.html`
2. Enter your admin token from Step 5
3. Click "Access Dashboard"
4. You should see the dashboard with stats

**Note**: Stats may be "0" or "—" initially. After some page views and feedback submissions (wait a minute for data to sync), refresh the admin dashboard and you should see data.

---

## Troubleshooting

### "Unauthorized" error on admin dashboard
- Double-check that the `ADMIN_TOKEN` in admin.html matches what you set with `wrangler secret put`

### Analytics not showing in console
- Verify `ENABLED: true` in analytics.js
- Check that the `ENDPOINT` URL is correct (no typos in subdomain)
- Look for error messages in the browser console

### Worker returns 500 error
- Check Worker logs: `wrangler tail` (shows live logs)
- Or view logs in Cloudflare dashboard: Workers & Pages → your worker → Logs

### Data not showing in admin dashboard
- Wait a minute after generating activity (there's a small delay)
- Check the browser console for errors
- Verify the Worker URL is correct in admin.html

---

## Updating the Worker Later

If you need to make changes to `worker.js`:

1. Edit the file
2. Run: `wrangler deploy`
3. Your changes will go live in seconds

---

## Cost & Limits

**Free tier limits:**
- 100,000 requests per day
- Unlimited KV reads
- 1,000 KV writes per day
- 1 GB KV storage

For a personal project or small site, you'll likely never hit these limits.

If you do, Cloudflare's paid tier is $5/month for 10 million requests.

---

## Security Notes

1. **Never commit your admin token to GitHub**
   - It's stored as a Cloudflare secret, which is good
   - The token in `admin.html` is client-side, but that's okay since the real validation happens in the Worker

2. **CORS is wide open** (`Access-Control-Allow-Origin: *`)
   - This is intentional for a public website
   - If you want to restrict it later, edit the `CORS_HEADERS` in `worker.js`

3. **No rate limiting yet**
   - The current Worker doesn't have rate limiting
   - For a personal project, this is fine
   - If you get spam, we can add rate limiting later

---

## Next Steps

Once everything is working:

1. Monitor your analytics in the admin dashboard
2. Check feedback submissions regularly
3. If you want to export data, you can use `wrangler kv:key list` and `wrangler kv:key get`

---

## Questions?

If you run into issues, check:
1. Browser console for errors
2. Worker logs: `wrangler tail`
3. Cloudflare dashboard → Workers & Pages → Metrics
