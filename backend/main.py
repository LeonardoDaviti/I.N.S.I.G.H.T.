from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from insight_bridge import InsightBridge
from insight_api_bridge import InsightApiBridge
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="INSIGHT Intelligence Platform API",
    description="Backend API for the INSIGHT Mark I Foundation Engine",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # use * for testing?
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the bridge to Mark I Foundation Engine
bridge = InsightBridge()

# Initialize the bridge to Mark I API Engine
api_bridge = InsightApiBridge()

# Request models
class BriefingRequest(BaseModel):
    date: str  # Format: "YYYY-MM-DD"
    includeTopics: bool | None = None
    includeUnreferenced: bool | None = True

@app.get("/")
async def root():
    return {
        "message": "INSIGHT Intelligence Platform API", 
        "version": "1.0.0",
        "engine": "Mark I Foundation Engine",
        "status": "operational"
    }

@app.get("/hello")
async def hello():
    return {"message": "Hello World"}

# ============= SOURCES ENDPOINTS (DATABASE-BACKED) =============

@app.get("/api/sources")
async def get_sources():
    """Get sources in frontend-compatible format (nested by platform)."""
    try:
        logger.info("📋 Fetching sources from database")
        sources_config = api_bridge.get_sources_config()
        return {"success": True, "data": sources_config}
    except Exception as e:
        logger.exception("Failed to get sources")
        return {"success": False, "error": str(e)}

@app.get("/api/enabled-sources")
async def get_enabled_sources():
    """Get only enabled sources (flat list)."""
    try:
        logger.info("📋 Fetching enabled sources from database")
        enabled = api_bridge.get_enabled_sources()
        return {"success": True, "data": enabled}
    except Exception as e:
        logger.exception("Failed to get enabled sources")
        return {"success": False, "error": str(e)}

@app.post("/api/sources")
async def update_sources(config: dict):
    """Update sources configuration (add/remove/enable/disable)."""
    try:
        logger.info("🔧 Updating sources in database")
        result = api_bridge.update_sources_config(config)
        
        if result["success"]:
            return {
                "success": True,
                "message": result["message"],
                "data": result["stats"]
            }
        else:
            return {
                "success": False,
                "error": "Some operations failed",
                "data": result["stats"]
            }
    except Exception as e:
        logger.exception("Failed to update sources")
        return {"success": False, "error": str(e)}
    

# ============= POSTS ENDPOINTS (DATABASE-BACKED) =============

@app.get("/api/posts/{date}")
async def get_posts(date: str):
    """Get posts for a specific date."""
    try:
        logger.info(f"📋 Fetching posts for date: {date}")

        result = api_bridge.get_posts_by_date(date)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Retrieved {result.get('total', 0)} posts")
        
        return result

    except Exception as e:
        logger.exception("Failed to get posts")
        return {"success": False, "error": str(e)}


# Briefing generation endpoints


@app.post("/api/daily")
async def generate_daily_briefing(request: BriefingRequest):
    try:
        date = request.date
        logger.info(f"🚀 Generating daily briefing for date: {date}")
        
        if not date:
            raise HTTPException(status_code=400, detail="Date parameter required")
        
        # If includeTopics flag is set, use enhanced path
        if request.includeTopics:
            result = await bridge.daily_briefing_with_topics(date)
        else:
            # Call the Mark I Foundation Engine
            result = await bridge.daily_briefing(date)
        
        if isinstance(result, dict) and "error" in result:
            logger.error(f"❌ Engine error: {result['error']}")
            return {"success": False, "error": result["error"]}
        
        logger.info("✅ Briefing generated successfully")
        response_payload = {
            "success": True,
            "briefing": result.get("briefing", result) if isinstance(result, dict) else result,
            "date": result.get("date", date) if isinstance(result, dict) else date,
            "posts_processed": result.get("posts_processed", 0) if isinstance(result, dict) else 0,
            "total_posts_fetched": result.get("total_posts_fetched", 0) if isinstance(result, dict) else 0,
            "posts": result.get("posts", []) if isinstance(result, dict) else []
        }
        # If enhanced data exists, include it without token usage
        if isinstance(result, dict) and result.get("topics") is not None:
            response_payload.update({
                "enhanced": result.get("enhanced", True),
                "topics": result.get("topics", []),
                "unreferenced_posts": result.get("unreferenced_posts", [])
            })

        return response_payload
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate briefing: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/daily/topics")
async def generate_daily_briefing_with_topics(request: BriefingRequest):
    try:
        date = request.date
        logger.info(f"🚀 Generating topic-based daily briefing for date: {date}")
        if not date:
            raise HTTPException(status_code=400, detail="Date parameter required")

        include_unreferenced = True if request.includeUnreferenced is None else request.includeUnreferenced
        result = await bridge.daily_briefing_with_topics(date, include_unreferenced=include_unreferenced)
        if isinstance(result, dict) and "error" in result:
            logger.error(f"❌ Engine error: {result['error']}")
            return {"success": False, "error": result["error"]}

        # Construct payload (no token costs exposed)
        return {
            "success": True,
            "enhanced": result.get("enhanced", True),
            # Topic-based daily briefing string (top-level summary)
            "briefing": result.get("briefing", ""),
            "topics": result.get("topics", []),
            "unreferenced_posts": result.get("unreferenced_posts", []),
            "posts": result.get("posts", {}),
            "date": result.get("date", date),
            "posts_processed": result.get("posts_processed", 0),
            "total_posts_fetched": result.get("total_posts_fetched", 0)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate topic-based briefing: {e}")
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    import time
    return {
        "status": "healthy",
        "engine": "Mark I Foundation Engine",
        "timestamp": str(time.time())
    }