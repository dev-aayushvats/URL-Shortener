from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
import shortuuid
import os
from dotenv import load_dotenv
import redis

import models
from database import engine, get_db

# Load environment variables from .env file
load_dotenv()
BASE_URL = os.getenv("BASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

# Create database tables
models.Base.metadata.create_all(bind=engine)

# Initialize Redis client from REDIS_URL environment variable
redis_client = redis.Redis.from_url(REDIS_URL)

# Redis cache expiry time in seconds (24 hours)
REDIS_EXPIRY_TIME = 86400

#Initialise FastAPI app
app = FastAPI(title="URL Shortener Assignment")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Defining the Schemas
class URLSchema(BaseModel):
    target_url: HttpUrl

class URLInfo(BaseModel):
    short_code: str
    target_url: str
    short_url: str
    
    class Config:
        orm_mode = True


# /get route returning a simple message and instructions on how to shorten a URL
@app.get("/")
def read_root():
    return {"message": "URL Shortener Assignment. Send a POST request with a JSON body containing the target URL to /shorten to create a short URL."}


# /shorten route returning a shortened URL as required in the assignment
@app.post("/shorten", response_model=URLInfo)
def create_short_url(url: URLSchema, db: Session = Depends(get_db)):

    # Check if the target URL already exists in the database and return the same short URL if it is there.
    while True:
        target = db.query(models.URL).filter(models.URL.target_url == url.target_url).first()
        if target is None:
            break

        else:
            short_code = target.url_id  # Using url_id from database as short_code
            # appending the base URL (localhost:8000) to the short URL.
            short_url = f"{BASE_URL}/{short_code}"

            # returning only the short URL as required in the assignment.
            return URLInfo(
                short_code=short_code,
                target_url=str(url.target_url),
                short_url=short_url
            )
    
    # For a new URL: Generate a short ID
    while True:
        short_code = shortuuid.uuid()[:8]
        
        # Check duplicate short ID.
        existing_url = db.query(models.URL).filter(models.URL.url_id == short_code).first()
        
        if existing_url is None:
            break
    
    # Create URL record in the database for the new URL.
    db_url = models.URL(
        url_id=short_code,  # Using short_code as url_id in database
        target_url=str(url.target_url)
    )
    db.add(db_url)
    db.commit()
    db.refresh(db_url)
    
    # Create response
    short_url = f"{BASE_URL}/{short_code}"

    # returning only the short URL as required in the assignment.
    return URLInfo(
        short_code=short_code,
        target_url=str(url.target_url),
        short_url=short_url
    )

@app.get("/database/all")
def get_all_urls(db: Session = Depends(get_db)):
    all_urls = db.query(models.URL).all()
    return all_urls

#Endpoint to redirect to the initial target URL
@app.get("/{short_code}")
def redirect_to_target_url(short_code: str, db: Session = Depends(get_db)):
    
    # Firstly check if the short code is in the Redis cache. (Fast response)
    try:
        from_cache = redis_client.get(short_code)

        if from_cache:
            target_url = from_cache.decode('utf-8')
            return RedirectResponse(target_url)
    except Exception as e:
        print(f"Error fetching from Redis: {e}")

    # Check for the short_code in the database if its not in the cache.
    db_url = db.query(models.URL).filter(models.URL.url_id == short_code).first()
    
    if db_url is None:
        raise HTTPException(status_code=404, detail="URL not found")
    
    # Redirect to target URL and save to cache with 24-hour expiry.
    redis_client.set(short_code, db_url.target_url, ex=REDIS_EXPIRY_TIME)
    return RedirectResponse(db_url.target_url)
