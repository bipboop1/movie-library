import os
import re
import sqlite3
from datetime import datetime
import requests
from pathlib import Path
import urllib.request
from flask import Flask, render_template_string

# Configuration
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

MOVIES_DIR = os.getenv('MOVIES_DIR', 'path/to/your/movies/folder')
DATABASE_PATH = "movies.db"
TMDB_API_KEY = os.getenv('TMDB_API_KEY')
if not TMDB_API_KEY:
    raise ValueError("TMDB_API_KEY environment variable is not set")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"  # w500 is the image width

def setup_database():
    """Create SQLite database and tables if they don't exist"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            year INTEGER,
            director TEXT,
            countries TEXT,
            poster_path TEXT,
            plot TEXT,
            genres TEXT,
            rating FLOAT,
            folder_path TEXT NOT NULL,
            last_updated DATETIME,
            tmdb_id INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def parse_movie_folder(folder_name):
    """Extract title and year from folder name"""
    pattern = r"(.+)\s*\((\d{4})\)"
    match = re.match(pattern, folder_name)
    if match:
        return match.group(1).strip(), int(match.group(2))
    return folder_name, None

def get_director_from_credits(movie_id):
    """Fetch director information from TMDB credits"""
    url = f"{TMDB_BASE_URL}/movie/{movie_id}/credits"
    params = {"api_key": TMDB_API_KEY}
    
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            directors = [crew['name'] for crew in data.get('crew', []) 
                        if crew['job'] == 'Director']
            return ', '.join(directors) if directors else None
    except Exception as e:
        print(f"Error fetching director info: {e}")
    return None

def fetch_movie_info(title, year):
    """Fetch movie information from TMDB API"""
    # First, search for the movie
    search_url = f"{TMDB_BASE_URL}/search/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "year": year
    }
    
    try:
        response = requests.get(search_url, params=params)
        if response.status_code == 200:
            results = response.json().get('results', [])
            if not results:
                return None
            
            # Get the first result's ID
            movie_id = results[0]['id']
            
            # Get detailed movie info
            details_url = f"{TMDB_BASE_URL}/movie/{movie_id}"
            params = {
                "api_key": TMDB_API_KEY,
                "append_to_response": "release_dates"
            }
            
            details_response = requests.get(details_url, params=params)
            if details_response.status_code == 200:
                data = details_response.json()
                
                # Get director
                director = get_director_from_credits(movie_id)
                
                return {
                    'title': data.get('title'),
                    'year': year,  # Use the year from folder name for consistency
                    'director': director,
                    'countries': ', '.join(c['iso_3166_1'] for c in data.get('production_countries', [])),
                    'poster_url': f"{TMDB_IMAGE_BASE_URL}{data.get('poster_path')}" if data.get('poster_path') else None,
                    'plot': data.get('overview'),
                    'genres': ', '.join(g['name'] for g in data.get('genres', [])),
                    'rating': data.get('vote_average'),
                    'tmdb_id': movie_id
                }
    except Exception as e:
        print(f"Error fetching movie info for {title}: {e}")
    return None

def download_poster(poster_url, movie_title):
    """Download and save movie poster"""
    if poster_url:
        posters_dir = Path('posters')
        posters_dir.mkdir(exist_ok=True)
        
        poster_path = posters_dir / f"{movie_title.replace(' ', '_')}.jpg"
        
        try:
            urllib.request.urlretrieve(poster_url, poster_path)
            return str(poster_path)
        except Exception as e:
            print(f"Error downloading poster for {movie_title}: {e}")
    return None

def scan_directory(directory, conn, cursor):
    """Recursively scan directory for movie folders"""
    for folder_name in os.listdir(directory):
        # Skip the posters directory and any hidden folders
        if folder_name == 'posters' or folder_name.startswith('.'):
            continue
            
        folder_path = os.path.join(directory, folder_name)
        if os.path.isdir(folder_path):
            title, year = parse_movie_folder(folder_name)
            
            if year:  # This is a movie folder
                # Check if movie already exists in database
                cursor.execute('SELECT id FROM movies WHERE folder_path = ?', (folder_path,))
                result = cursor.fetchone()
                
                if not result:
                    movie_info = fetch_movie_info(title, year)
                    if movie_info:
                        poster_path = download_poster(movie_info['poster_url'], movie_info['title'])
                        
                        cursor.execute('''
                            INSERT INTO movies (
                                title, year, director, countries, poster_path,
                                plot, genres, rating, folder_path, last_updated,
                                tmdb_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            movie_info['title'], movie_info['year'], movie_info['director'],
                            movie_info['countries'], poster_path, movie_info['plot'],
                            movie_info['genres'], movie_info['rating'],
                            folder_path, datetime.now(), movie_info['tmdb_id']
                        ))
            else:  # This might be a director folder, scan it recursively
                scan_directory(folder_path, conn, cursor)

def scan_and_update_database():
    """Scan movie folders and update database"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    scan_directory(MOVIES_DIR, conn, c)
    conn.commit()
    conn.close()

# Flask web application for displaying the movie library
app = Flask(__name__)

@app.route('/')
def display_library():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM movies ORDER BY title')
    movies = c.fetchall()
    conn.close()
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Movie Library</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; background-color: #f0f0f0; }
                .movie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
                .movie-card {
                    background: white;
                    padding: 15px;
                    border-radius: 10px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }
                .movie-card img { max-width: 100%; height: auto; border-radius: 5px; }
                .movie-info { margin-top: 10px; }
                h1 { color: #333; }
                h2 { margin: 10px 0; color: #444; font-size: 1.2em; }
                .rating { color: #f39c12; font-weight: bold; }
                .genres { color: #666; font-style: italic; }
            </style>
        </head>
        <body>
            <h1>Movie Library</h1>
            <div class="movie-grid">
                {% for movie in movies %}
                <div class="movie-card">
                    {% if movie['poster_path'] %}
                    <img src="{{ movie['poster_path'] }}" alt="{{ movie['title'] }} poster">
                    {% endif %}
                    <div class="movie-info">
                        <h2>{{ movie['title'] }} ({{ movie['year'] }})</h2>
                        <p><strong>Director:</strong> {{ movie['director'] }}</p>
                        <p><strong>Countries:</strong> {{ movie['countries'] }}</p>
                        <p class="genres">{{ movie['genres'] }}</p>
                        <p class="rating">Rating: {{ "%.1f"|format(movie['rating']) }}/10</p>
                        <p>{{ movie['plot'] }}</p>
                    </div>
                </div>
                {% endfor %}
            </div>
        </body>
        </html>
    ''', movies=movies)

if __name__ == '__main__':
    # Setup database and scan for movies
    setup_database()
    scan_and_update_database()
    
    # Start the web application
    app.run(debug=True)