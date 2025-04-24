# URL Shortener Service

Internship Assignment for LOBB

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.8+

### Installation

1. Create a virtual environment:
   ```bash   
   # For Windows
   python -m venv venv
   venv\Scripts\activate
   
   # For macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Create a `.env` file with the following content (I am aware that we should not include the .env files but I have included here for quick setup):
   ```
   BASE_URL=http://localhost:8000
   DATABASE_URL=postgresql://postgres:postgres@postgres:5432/url_shortener
   REDIS_URL=redis://localhost:6379/0
   ```

3. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```

4. Start the database and Redis with Docker Compose (make sure that Docker engine is running in the background):
   ```
   docker-compose up -d
   ```
   You can check if the docker database and redis started or not by running ``` docker ps ```. It should list both the instances.

5. Run the application:
   ```
   fastapi run app.py
   ```

   For development with auto-reload:
   ```
   fastapi dev app.py
   ```

## Usage

### Web Interface

The URL shortener includes a user-friendly web interface. To use it:

1. Open the index.html file in your browser.
2. Enter the URL you want to shorten in the input field
3. Click the "Shorten URL" button
4. The result will show both the JSON response and a clickable short URL link

### API Usage

The URL shortener provides the following REST API endpoints:

| Endpoint | Method | Description | Request Body | Response |
|----------|--------|-------------|--------------|----------|
| `/` | GET | Root endpoint with API information | None | `{"message": "URL Shortener Assignment..."}` |
| `/shorten` | POST | Create a short URL | `{"target_url": "https://example.com/..."}` | JSON with short code and URL |
| `/{short_code}` | GET | Redirect to original URL | None | HTTP redirect to target URL |
| `/database/all` | GET | List all shortened URLs | None | Array of URL objects |

#### Create a Short URL

**Endpoint:** `/shorten`  
**Method:** POST  
**Content-Type:** application/json

Request Body:
```json
{
  "target_url": "https://example.com/very/long/url/that/needs/to/be/shortened"
}
```

Response (200 OK):
```json
{
  "short_code": "AbCdEf12",
  "target_url": "https://example.com/very/long/url/that/needs/to/be/shortened",
  "short_url": "http://localhost:8000/AbCdEf12"
}
```

Example with curl:
```bash
curl -X 'POST' \
  'http://localhost:8000/shorten' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "target_url": "https://example.com/very/long/url/that/needs/to/be/shortened"
}'
```

#### Use a Short URL

**Endpoint:** `/{short_code}`  
**Method:** GET  
**Response:** HTTP 302 redirect to the original URL

Simply visit the short URL in your browser:
```
http://localhost:8000/AbCdEf12
```

Or use curl:
```bash
curl -L 'http://localhost:8000/AbCdEf12'
```

#### List All URLs

**Endpoint:** `/database/all`  
**Method:** GET  
**Response:** JSON array of all URL objects in the database

Example with curl:
```bash
curl -X 'GET' 'http://localhost:8000/database/all'
```

## Architecture

- **FastAPI**: Modern, fast web framework for building APIs
- **PostgreSQL**: Persistent storage for URL mappings
- **Redis**: In-memory caching for URLs which are frequently requested. Cached items expire after 24 hours.
- **Docker**: Running the Postgres and Redis instances in docker containers for easy and quick access.

## Database Schema

The `urls` table stores mappings between short codes and target URLs:

| Column      | Type      | Description                       |
|-------------|-----------|-----------------------------------|
| url_id      | String    | Primary key, unique short code    |
| target_url  | String    | Original URL to redirect to       |
| created_at  | DateTime  | Timestamp when URL was shortened  |
