import os
import re
import sqlite3
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path
import urllib.request
from flask import Flask, render_template_string

# Configuration
MOVIES_DIR = "path/to/your/movies/folder"  # Replace with your actual path
DATABASE_PATH = "movies.db"
OMDB_API_KEY = "your_api_key_here"  # Get from http://www.omdbapi.com/

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
            country TEXT,
            poster_path TEXT,
            plot TEXT,
            genre TEXT,
            imdb_rating TEXT,
            folder_path TEXT NOT NULL,
            last_updated DATETIME
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

def fetch_movie_info(title, year):
    """Fetch movie information from OMDB API"""
    url = f"http://www.omdbapi.com/?t={title}&y={year}&apikey={OMDB_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data.get('Response') == 'True':
            return {
                'title': data.get('Title'),
                'year': data.get('Year'),
                'director': data.get('Director'),
                'country': data.get('Country'),
                'poster_url': data.get('Poster'),
                'plot': data.get('Plot'),
                'genre': data.get('Genre'),
                'imdb_rating': data.get('imdbRating')
            }
    return None

def download_poster(poster_url, movie_title):
    """Download and save movie poster"""
    if poster_url and poster_url != 'N/A':
        posters_dir = Path('posters')
        posters_dir.mkdir(exist_ok=True)
        
        file_extension = poster_url.split('.')[-1]
        poster_path = posters_dir / f"{movie_title.replace(' ', '_')}.{file_extension}"
        
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
                                title, year, director, country, poster_path,
                                plot, genre, imdb_rating, folder_path, last_updated
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            movie_info['title'], movie_info['year'], movie_info['director'],
                            movie_info['country'], poster_path, movie_info['plot'],
                            movie_info['genre'], movie_info['imdb_rating'],
                            folder_path, datetime.now()
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
            c.execute('SELECT id FROM movies WHERE folder_path = ?', (folder_path,))
            result = c.fetchone()
            
            if not result:
                movie_info = fetch_movie_info(title, year)
                if movie_info:
                    poster_path = download_poster(movie_info['poster_url'], movie_info['title'])
                    
                    c.execute('''
                        INSERT INTO movies (
                            title, year, director, country, poster_path,
                            plot, genre, imdb_rating, folder_path, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        movie_info['title'], movie_info['year'], movie_info['director'],
                        movie_info['country'], poster_path, movie_info['plot'],
                        movie_info['genre'], movie_info['imdb_rating'],
                        folder_path, datetime.now()
                    ))
    
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
                h2 { margin: 10px 0; color: #444; }
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
                        <p><strong>Country:</strong> {{ movie['country'] }}</p>
                        <p><strong>Genre:</strong> {{ movie['genre'] }}</p>
                        <p><strong>IMDb Rating:</strong> {{ movie['imdb_rating'] }}</p>
                        <p><strong>Plot:</strong> {{ movie['plot'] }}</p>
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