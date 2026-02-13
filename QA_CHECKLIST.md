# QA Checklist - Admin Portal & Analytics
## Good Free Apps

Use this checklist before and after deploying to production.

---

## Pre-Deployment Checklist

### Cloudflare Worker
- [ ] KV namespace created (`wrangler kv:namespace create "ANALYTICS_KV"`)
- [ ] `wrangler.toml` updated with correct KV namespace ID
- [ ] Admin token set (`wrangler secret put ADMIN_TOKEN`)
- [ ] Worker deployed successfully (`wrangler deploy`)
- [ ] Worker URL copied (format: `https://good-free-apps-api.SUBDOMAIN.workers.dev`)

### Website Files Updated
- [ ] `analytics.js`: Worker URL added to `ENDPOINT`
- [ ] `analytics.js`: `ENABLED` changed to `true`
- [ ] `admin.html`: API_ENDPOINT updated with Worker URL
- [ ] `admin.html`: ADMIN_TOKEN updated to match Cloudflare secret
- [ ] `index.html`: Feedback submission URL updated with Worker URL
- [ ] All files committed and pushed to GitHub
- [ ] Netlify deployed the changes (check deploy log)

---

## Post-Deployment Testing

### Test 1: Analytics Tracking
**Goal**: Verify that page views and events are being tracked

1. Open your website: `https://your-site.com`
2. Open browser Developer Console (F12)
3. Refresh the page
4. **Expected**: You should see in console:
   ```
   [Analytics] Object { type: "page_view", app: "hub", ... }
   ```
5. **If you see errors**: Check that `ENDPOINT` URL is correct in `analytics.js`

**Status**: ☐ Pass ☐ Fail

---

### Test 2: Analytics Data Storage
**Goal**: Verify Worker is receiving and storing events

1. In terminal, run: `wrangler tail` (shows live Worker logs)
2. Open your website in a browser
3. Refresh the page
4. **Expected**: You should see in the terminal:
   ```
   POST /api/track 200 OK
   ```
5. **If you see 500 errors**: Check Worker logs for error details

**Status**: ☐ Pass ☐ Fail

---

### Test 3: Feedback Submission
**Goal**: Verify users can submit feedback

1. Go to: `https://your-site.com`
2. Scroll to footer and click "Send Feedback"
3. Fill out the form:
   - Rate 5 stars
   - Category: "General Feedback"
   - Text: "Test feedback submission"
   - Leave "Submit anonymously" checked
4. Click "Submit Feedback"
5. **Expected**: Alert says "Thank you for your feedback!"
6. **If error**: Check browser console for error messages

**Status**: ☐ Pass ☐ Fail

---

### Test 4: Admin Dashboard Access
**Goal**: Verify admin authentication works

1. Go to: `https://your-site.com/admin.html`
2. Enter your admin token
3. Click "Access Dashboard"
4. **Expected**: Dashboard loads showing stats
5. **If "Invalid token"**: Admin token in `admin.html` doesn't match Cloudflare secret

**Status**: ☐ Pass ☐ Fail

---

### Test 5: Admin Dashboard Data
**Goal**: Verify dashboard shows real data

1. Access admin dashboard (see Test 4)
2. Wait 1-2 minutes for data to sync
3. Click the refresh button (↻) in the header
4. **Expected**: 
   - "Total Page Views" shows > 0
   - "Feedback Items" shows > 0 (if you submitted feedback in Test 3)
5. **If all stats show "—" or "0"**:
   - Wait another minute and refresh
   - Check that analytics is enabled (`ENABLED: true` in analytics.js)
   - Check browser console and Worker logs for errors

**Status**: ☐ Pass ☐ Fail

---

### Test 6: Feedback Appears in Admin Dashboard
**Goal**: Verify submitted feedback shows up

1. In admin dashboard, scroll to "Feedback" section
2. **Expected**: Your test feedback from Test 3 should appear
3. Check that it shows:
   - 5-star rating
   - "General Feedback" category
   - Your test message
   - "Anonymous" as the source
   - Today's date

**Status**: ☐ Pass ☐ Fail

---

### Test 7: Dark Mode Works
**Goal**: Verify theme toggle works in admin

1. In admin dashboard, click the theme toggle button (◐)
2. **Expected**: Dashboard switches between light and dark mode
3. Refresh the page
4. **Expected**: Theme preference persists

**Status**: ☐ Pass ☐ Fail

---

### Test 8: Real User Flow
**Goal**: Simulate a real user visiting the site

1. Open site in incognito/private window
2. Browse around, click things, spend 30 seconds
3. Submit feedback with a different message
4. Wait 1 minute
5. Go to admin dashboard
6. **Expected**: 
   - Page views increased
   - New feedback appears
   - Session count increased

**Status**: ☐ Pass ☐ Fail

---

## Edge Cases to Test

### Test 9: Admin Dashboard Without Auth
**Goal**: Verify unauthorized users can't access data

1. Open admin.html
2. Enter wrong password
3. **Expected**: "Invalid token. Try again." appears
4. **If dashboard loads**: Security issue - check admin.html code

**Status**: ☐ Pass ☐ Fail

---

### Test 10: Feedback Without Required Fields
**Goal**: Verify validation works

1. Open feedback modal
2. Leave text field empty
3. Click submit
4. **Expected**: Alert says "Please enter your feedback."
5. **If it submits**: Check validation in index.html

**Status**: ☐ Pass ☐ Fail

---

### Test 11: Worker Performance
**Goal**: Check Worker isn't timing out

1. Generate lots of page views (refresh site 10 times quickly)
2. Check `wrangler tail` for timing info
3. **Expected**: All requests complete in < 500ms
4. **If slow**: Check KV read/write performance in Cloudflare dashboard

**Status**: ☐ Pass ☐ Fail

---

## Production Monitoring

After deployment, monitor these for the first week:

### Daily Checks
- [ ] Check admin dashboard once per day
- [ ] Verify analytics data is being collected
- [ ] Review any feedback submissions
- [ ] Check for errors in Worker logs (`wrangler tail`)

### Weekly Checks
- [ ] Review Cloudflare dashboard → Workers & Pages → Metrics
- [ ] Check KV storage usage (should be well under 1 GB)
- [ ] Verify you're under free tier limits (100k requests/day)

### Red Flags
- [ ] No analytics data for 24+ hours → Check if `ENABLED: false` accidentally
- [ ] Lots of 500 errors in Worker → Check Worker logs for bugs
- [ ] Feedback spam → Consider adding rate limiting
- [ ] Near free tier limits → May need to optimize or upgrade

---

## Rollback Plan

If something breaks after deployment:

1. **Disable analytics temporarily**:
   - Edit `analytics.js`: Set `ENABLED: false`
   - Commit and push
   - Netlify will redeploy

2. **Redeploy previous Worker version**:
   - `wrangler rollback` (reverts to previous deployment)

3. **Check Worker logs**:
   - `wrangler tail` (live logs)
   - Or Cloudflare dashboard → Workers → Logs

4. **Emergency contact**:
   - Cloudflare support (if Worker is completely broken)
   - GitHub Issues (if code issue)

---

## Success Criteria

✅ All tests pass
✅ Analytics data appears in admin dashboard
✅ Feedback submissions work end-to-end  
✅ No errors in browser console
✅ No errors in Worker logs
✅ Theme toggle works
✅ Admin auth works correctly

---

## Notes Section

Use this space to record any issues you encountered and how you fixed them:

```
Date: 
Issue: 
Solution: 




```
