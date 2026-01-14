# Rebranding Open WebUI

This document explains how to customize the branding of Open WebUI (name, logo, favicon).

## 1. Change the Application Name

### Option A: Environment Variable
```bash
export WEBUI_NAME="Your App Name"
```

**Note:** By default, Open WebUI appends " (Open WebUI)" to custom names.

### Option B: Edit Source Code

Edit `backend/open_webui/env.py` lines 90-92:

```python
# Original:
WEBUI_NAME = os.environ.get("WEBUI_NAME", "Open WebUI")
if WEBUI_NAME != "Open WebUI":
    WEBUI_NAME += " (Open WebUI)"

# Modified (remove the suffix):
WEBUI_NAME = os.environ.get("WEBUI_NAME", "Your App Name")
# Comment out or delete the lines that append "(Open WebUI)"
```

## 2. Replace Logo Files

Replace these files in `backend/open_webui/static/`:

| File | Purpose | Size | Notes |
|------|---------|------|-------|
| `splash.png` | Main logo in sidebar | ~44x44px | Gets inverted in dark mode via CSS `dark:invert` |
| `favicon.png` | Browser tab icon, small sidebar icon | ~40x40px | Used as-is, no inversion |

### Logo Design Tips

- **splash.png**: Use a simple logo that looks good inverted (for dark mode). Black/dark logos on transparent background work best.
- **favicon.png**: Standard favicon, should be recognizable at small sizes.

## 3. Change Favicon URL (Optional)

If you want to serve the favicon from a different URL, edit `backend/open_webui/env.py` line 94:

```python
WEBUI_FAVICON_URL = "https://yourdomain.com/favicon.png"
```

## 4. Additional Branding Locations

### Browser Title
The `WEBUI_NAME` is used throughout the UI for:
- Browser tab titles
- Welcome messages
- About dialogs

### Sidebar Logo
Located in `src/lib/components/app/AppSidebar.svelte`:
- Line 29: `{WEBUI_BASE_URL}/static/splash.png`
- Line 53: `{WEBUI_BASE_URL}/static/favicon.png`

## 5. After Making Changes

1. Rebuild the frontend (if you changed any `.svelte` files):
   ```bash
   npm run build
   ```

2. Restart the server:
   ```bash
   # Kill existing process
   pkill -f "uvicorn open_webui"

   # Start server
   cd backend
   python -m uvicorn open_webui.main:app --host 127.0.0.1 --port 8080
   ```

3. Clear browser cache or hard refresh (Ctrl+Shift+R) to see logo changes.

## Quick Start Example

To rebrand as "My AI Assistant":

1. Set environment variable:
   ```bash
   export WEBUI_NAME="My AI Assistant"
   ```

2. Replace logo files:
   ```bash
   cp /path/to/your/logo.png backend/open_webui/static/splash.png
   cp /path/to/your/favicon.png backend/open_webui/static/favicon.png
   ```

3. (Optional) Remove "(Open WebUI)" suffix by editing `backend/open_webui/env.py`

4. Restart the server
