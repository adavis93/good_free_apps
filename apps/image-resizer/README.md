# Image Resizer — Good Free Apps

Resize images entirely in your browser. No uploads, no accounts, no tracking. Just drag, resize, and download.

## What It Does

- Accepts images via drag-and-drop or file picker
- Supports JPEG, PNG, GIF, WebP, BMP, and TIFF input
- Displays original file name, dimensions, and file size
- Lets users set custom target dimensions (width × height in pixels)
- Includes 7 preset sizes for common use cases (profile photo, social media headers, etc.)
- Locks aspect ratio by default with a toggle to override
- Shows a live preview of the resized image on a transparency checkerboard
- Displays estimated output file size before downloading
- Outputs as JPEG, PNG, or WebP with adjustable quality slider
- Download to device or copy to clipboard
- Dark mode toggle (defaults to system preference)
- All processing happens client-side via the Canvas API — nothing leaves the device

## How to Run Locally

1. Clone or download this repository
2. Open a terminal in the project root
3. Start any static file server. For example:

   ```bash
   # Python 3
   python3 -m http.server 8000

   # Node.js (if you have npx)
   npx serve .

   # PHP
   php -S localhost:8000
   ```

4. Open your browser to `http://localhost:8000`
5. Click "Image Resizer" from the hub, or go directly to `http://localhost:8000/apps/image-resizer/index.html`

No build step, no npm install, no dependencies.

## File Structure

```
apps/image-resizer/
└── index.html      ← Single self-contained file (HTML + CSS + JS)
```

The app links to `../../shared/design-tokens.css` for the shared design system and loads Google Fonts (Outfit + IBM Plex Mono) from the CDN.

## Hub Registration

Add this entry to the `apps` array in the root `index.html`:

```javascript
{
  id: 'image-resizer',
  name: 'Image Resizer',
  description: 'Resize images in your browser. No uploads, no tracking.',
  icon: '🖼️',
  url: 'apps/image-resizer/index.html'
},
```

---

## QA Testing Checklist

Run through each item before deploying. Test on both desktop and mobile if possible.

### Upload & Format Support

- [ ] **JPEG upload** — Select a .jpg file via the file picker. Image loads and displays.
- [ ] **PNG upload** — Select a .png file (ideally with transparency). Image loads.
- [ ] **GIF upload** — Select a .gif file. Image loads (static frame).
- [ ] **WebP upload** — Select a .webp file. Image loads.
- [ ] **BMP upload** — Select a .bmp file. Image loads.
- [ ] **TIFF upload** — Select a .tiff file. Image loads (browser-dependent; Chrome/Edge support it, Firefox/Safari may not).
- [ ] **Drag-and-drop** — Drag an image onto the dropzone. It loads correctly.
- [ ] **Drag-and-drop onto workspace** — After loading one image, drag a new image anywhere on the page. It replaces the current image.
- [ ] **Non-image rejection** — Drop a .pdf or .txt file. A toast message says "Please drop an image file" or "Unsupported file format". No crash.
- [ ] **Large file** — Upload a 5MB+ JPEG. It loads and resizes without freezing.

### Original Image Info

- [ ] File name displays (truncated if long)
- [ ] File size displays (e.g., "2.4 MB")
- [ ] Original dimensions display (e.g., "4032 × 3024")

### Presets

- [ ] Click each preset button. Width and height fields update to the preset values.
- [ ] The clicked preset button highlights (blue border).
- [ ] After clicking a preset, manually editing width/height clears the preset highlight.
- [ ] Preview updates after selecting a preset.

### Custom Dimensions

- [ ] Type a width. Height auto-adjusts (aspect ratio locked by default).
- [ ] Type a height. Width auto-adjusts.
- [ ] Values are clamped between 1 and 10,000.
- [ ] Empty or zero values revert to original dimensions on blur.

### Aspect Ratio Lock

- [ ] Lock icon (🔗) is active by default.
- [ ] Click the lock button — it switches to unlocked state (↔️, muted style).
- [ ] When unlocked, changing width does NOT change height and vice versa.
- [ ] Click again to re-lock. Height recalculates from current width.
- [ ] Presets work regardless of lock state (they set both dimensions directly).

### Preview

- [ ] Preview image updates after every dimension change (with a short debounce).
- [ ] Preview dimensions label (e.g., "800 × 600") updates in the panel header.
- [ ] Estimated output file size updates in the panel footer.
- [ ] Checkerboard background is visible behind transparent PNGs.

### Output Format

- [ ] JPEG is selected by default.
- [ ] Click PNG — quality slider hides. Output is PNG.
- [ ] Click WebP — quality slider shows. Output is WebP.
- [ ] Click back to JPEG — quality slider shows.
- [ ] Adjusting the quality slider updates the estimated file size.

### Download

- [ ] Click "Download Resized Image". A file downloads.
- [ ] Downloaded file name includes original name + target dimensions (e.g., `photo_800x600.jpg`).
- [ ] Downloaded image is exactly the specified dimensions (verify in any image viewer).
- [ ] Downloaded format matches the selected output format (check file extension and actual format).
- [ ] Keyboard shortcut: Cmd/Ctrl+S triggers download.

### Copy to Clipboard

- [ ] Click "Copy to Clipboard". Toast says "Image copied to clipboard".
- [ ] Button briefly shows "✓ Copied!" in green.
- [ ] Paste into an app (Slack, Google Docs, etc.) — the resized image appears.
- [ ] Test in Chrome, Firefox, and Safari.
- [ ] If clipboard API is unsupported, a toast says "Copy not supported in this browser". No crash.

### Dark Mode

- [ ] If system is set to dark mode, the app loads in dark mode (no flash of light mode).
- [ ] Click the theme toggle (◐). Theme switches cleanly.
- [ ] All UI elements are legible in both modes.
- [ ] Theme preference persists across page reloads.

### Mobile

- [ ] Layout is single-column, no horizontal scrolling.
- [ ] File picker opens when tapping "Choose Image" or the dropzone.
- [ ] Preset grid is single-column on small screens.
- [ ] Download works (triggers the browser's download/save dialog).
- [ ] All tap targets are at least 44px.

### Performance

- [ ] Resizing a 5MB JPEG to 200×200 completes in under 3 seconds.
- [ ] No console errors during normal use.
- [ ] No memory leaks from repeated image loads (check DevTools → Memory if concerned).

### Edge Cases

- [ ] Upload a 1×1 pixel image. It loads and can be resized.
- [ ] Set dimensions to 1×1. Preview renders. Download works.
- [ ] Set dimensions to 10000×10000. Preview renders (may be slow, that's OK).
- [ ] "Change Image" button opens the file picker and loads a new image.
- [ ] Rapidly switching presets doesn't cause errors.

---

## Deployment to Netlify

### Prerequisites

- A GitHub account
- A free Netlify account (sign up at [netlify.com](https://www.netlify.com))
- The project code pushed to a GitHub repository

### Step-by-Step

1. **Push code to GitHub**

   If not already done:
   ```bash
   git init
   git add .
   git commit -m "Add image resizer app"
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```

2. **Log in to Netlify**

   Go to [app.netlify.com](https://app.netlify.com) and log in with your GitHub account.

3. **Create a new site**

   - Click **"Add new site"** → **"Import an existing project"**
   - Select **GitHub** as the Git provider
   - Authorize Netlify to access your repositories if prompted
   - Select your repository from the list

4. **Configure build settings**

   Since this is a static site with no build step:
   - **Branch to deploy**: `main` (or whatever your default branch is)
   - **Build command**: leave blank (or delete any default)
   - **Publish directory**: `.` (just a dot — the project root)

5. **Deploy**

   Click **"Deploy site"**. Netlify will publish the site in about 30 seconds.

6. **Access your site**

   Netlify assigns a random subdomain like `graceful-moonbeam-abc123.netlify.app`. You can:
   - Visit it immediately to verify everything works
   - Go to **Site settings** → **Domain management** → **Custom domains** to add your own domain
   - Go to **Site settings** → **General** → **Site name** to change the subdomain

7. **Automatic deploys**

   Every time you push to the `main` branch on GitHub, Netlify will automatically rebuild and redeploy the site. No manual steps needed after initial setup.

### Post-Deploy Verification

After deploying, run through the key items in the QA checklist above on the live URL. Pay special attention to:
- Font loading (Google Fonts CDN)
- Theme toggle persistence
- Image upload and download on mobile
- Copy to clipboard (requires HTTPS, which Netlify provides by default)
