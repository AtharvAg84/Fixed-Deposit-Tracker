# FD Tracker Deployment Guide

## 📋 Prerequisites

1. **Render Account**: Sign up at [render.com](https://render.com)
2. **GitHub Repository**: Push your code to GitHub
3. **API Keys**: Have your Gemini and Groq API keys ready

---

## 🚀 Deployment Steps

### Step 1: Update Backend CORS Settings

Before deploying, update the CORS origins in `server/bridge.py` to include your production frontend URL:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://fd-tracker-frontend.onrender.com",  # Add this
        "https://your-custom-domain.com"  # If you have one
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Step 2: Update Frontend API URL

Create a `.env` file in `client/fd-tracker/` (if not exists):

```env
VITE_API_URL=https://fd-tracker-backend.onrender.com
```

Update `App.jsx` to use the environment variable:

```javascript
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
```

### Step 3: Deploy to Render

#### Option A: Using render.yaml (Recommended)

1. Push the `render.yaml` file to your GitHub repository
2. Go to [Render Dashboard](https://dashboard.render.com)
3. Click **"New +"** → **"Blueprint"**
4. Connect your GitHub repository
5. Render will automatically detect `render.yaml` and create both services

#### Option B: Manual Deployment

**Backend:**
1. Go to Render Dashboard → **"New +"** → **"Web Service"**
2. Connect your GitHub repository
3. Configure:
   - **Name**: `fd-tracker-backend`
   - **Runtime**: Python 3
   - **Build Command**: 
     ```bash
     pip install --upgrade pip && pip install -r requirements.txt && pip install uvicorn fastapi && playwright install chromium && playwright install-deps
     ```
   - **Start Command**: `cd server && python bridge.py`
   - **Plan**: Free (or Starter for production)

**Frontend:**
1. Go to Render Dashboard → **"New +"** → **"Static Site"**
2. Connect your GitHub repository
3. Configure:
   - **Name**: `fd-tracker-frontend`
   - **Root Directory**: `client/fd-tracker`
   - **Build Command**: `npm install && npm run build`
   - **Publish Directory**: `dist`

### Step 4: Set Environment Variables

In the Render Dashboard for your **backend service**, add:

- `GEMINI_API_KEY`: Your Gemini API key
- `GROQ_API_KEY`: Your Groq API key
- `PORT`: 8000 (usually auto-set)

For the **frontend service**, add:

- `VITE_API_URL`: `https://fd-tracker-backend.onrender.com`

### Step 5: Deploy

Click **"Manual Deploy"** or wait for auto-deploy to trigger. Render will:
1. Clone your repository
2. Install dependencies
3. Build your application
4. Start the services

---

## 🔧 Post-Deployment Configuration

### Update Frontend API URL

After the backend is deployed, you'll get a URL like:
`https://fd-tracker-backend.onrender.com`

Update the frontend environment variable `VITE_API_URL` to this URL and redeploy the frontend.

### Custom Domain (Optional)

1. Go to your frontend service settings
2. Click **"Custom Domain"**
3. Add your domain and follow DNS configuration instructions

---

## 📊 Monitoring

### Health Checks

- Backend health endpoint: `https://fd-tracker-backend.onrender.com/health`
- Check logs in Render Dashboard → Service → Logs

### Common Issues

**Issue**: Backend fails to start
- **Solution**: Check logs for missing dependencies or environment variables

**Issue**: Frontend can't connect to backend
- **Solution**: Verify CORS settings and API URL environment variable

**Issue**: Database not persisting
- **Solution**: Ensure disk storage is configured (see render.yaml)

**Issue**: Playwright fails to install ("Failed to install browser dependencies")
- **Solution 1**: The build command has been simplified to skip system deps installation
- **Solution 2**: Upgrade to Starter plan ($7/month) which has better system access
- **Solution 3**: Use Docker deployment instead (see below)
- **Note**: Playwright may work without full system deps on Render's base image

---

## 💰 Cost Optimization

### Free Tier Limitations

- **Backend**: Spins down after 15 minutes of inactivity (cold starts)
- **Frontend**: Always available (static sites don't spin down)
- **Storage**: 1GB free disk storage

### Upgrade Recommendations

For production use:
1. Upgrade backend to **Starter plan** ($7/month) to prevent spin-down
2. Use **PostgreSQL** instead of SQLite for better reliability
3. Add **Redis** for caching (optional)

---

## 🔄 CI/CD

### Auto-Deploy

Both services are configured to auto-deploy on push to `main` branch.

To disable:
1. Go to service settings
2. Uncheck **"Auto-Deploy"**

### Manual Deploy

1. Go to service in Render Dashboard
2. Click **"Manual Deploy"** → **"Deploy latest commit"**

---

## 🛠️ Local Development vs Production

### Environment Detection

Update your code to detect environment:

```javascript
// App.jsx
const isDevelopment = import.meta.env.DEV;
const API = isDevelopment 
  ? "http://localhost:8000" 
  : import.meta.env.VITE_API_URL;
```

### Testing Production Build Locally

```bash
# Frontend
cd client/fd-tracker
npm run build
npm run preview

# Backend
cd server
python bridge.py
```

---

## 📝 Checklist

Before deploying:
- [ ] Update CORS origins in `bridge.py`
- [ ] Add `.env` file with `VITE_API_URL`
- [ ] Update `App.jsx` to use environment variable
- [ ] Push `render.yaml` to GitHub
- [ ] Have API keys ready (Gemini, Groq)
- [ ] Test locally with production build

After deploying:
- [ ] Verify backend health endpoint
- [ ] Test frontend → backend connection
- [ ] Check database persistence
- [ ] Monitor logs for errors
- [ ] Test chat interface with AI
- [ ] Verify all tabs work correctly

---

## 🆘 Support

- **Render Docs**: https://render.com/docs
- **Render Community**: https://community.render.com
- **FastAPI Docs**: https://fastapi.tiangolo.com
- **Vite Docs**: https://vitejs.dev

---

## 🎉 Success!

Once deployed, your FD Tracker will be live at:
- **Frontend**: `https://fd-tracker-frontend.onrender.com`
- **Backend**: `https://fd-tracker-backend.onrender.com`

Share the frontend URL with users to access your premium FD Rate Tracker! 🏦✨
