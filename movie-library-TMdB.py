import os
import re
import sqlite3
from datetime import datetime
import requests
from pathlib import Path
import urllib.request
from flask import Flask, render_template_string
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
MOVIES_DIR = os.getenv('MOVIES_DIR', 'path/to/your/movies/folder')
DATABASE_PATH = "movies.db"
TMDB_API_KEY = os.getenv('TMDB_API_KEY')
if not TMDB_API_KEY:
    raise ValueError("TMDB_API_KEY environment variable is not set")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

def setup_database():
    """Create SQLite database and tables if they don't exist"""
    # Delete existing database if it exists
    if os.path.exists(DATABASE_PATH):
        os.remove(DATABASE_PATH)
        print(f"Deleted existing database: {DATABASE_PATH}")

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
            
            movie_id = results[0]['id']
            
            details_url = f"{TMDB_BASE_URL}/movie/{movie_id}"
            params = {
                "api_key": TMDB_API_KEY,
                "append_to_response": "release_dates"
            }
            
            details_response = requests.get(details_url, params=params)
            if details_response.status_code == 200:
                data = details_response.json()
                
                director = get_director_from_credits(movie_id)
                
                return {
                    'title': data.get('title'),
                    'year': year,
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
        
        safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in movie_title)
        filename = f"{safe_title.replace(' ', '_')}.jpg"
        poster_path = posters_dir / filename
        
        try:
            urllib.request.urlretrieve(poster_url, poster_path)
            return f"/static/{filename}"
        except Exception as e:
            print(f"Error downloading poster for {movie_title}: {e}")
    return None

def scan_directory(directory, conn, cursor):
    """Recursively scan directory for movie folders"""
    for folder_name in os.listdir(directory):
        if folder_name == 'posters' or folder_name.startswith('.'):
            continue
            
        folder_path = os.path.join(directory, folder_name)
        if os.path.isdir(folder_path):
            title, year = parse_movie_folder(folder_name)
            
            if year:
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
            else:
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

# Configure static folder directly to the posters directory
app.static_folder = 'posters'
app.static_url_path = '/static'

@app.route('/')
def display_library():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM movies ORDER BY title')
    movies = c.fetchall()
    conn.close()
    
    template = '''<!DOCTYPE html>
<html data-theme="dark">
<head>
    <title>Movie Library</title>
    <style>
        :root[data-theme="light"] {
            --bg-color: #f0f0f0;
            --card-bg: #ffffff;
            --text-color: #333333;
            --title-color: #222222;
            --secondary-text: #666666;
            --border-color: #dddddd;
        }
        
        :root[data-theme="dark"] {
            --bg-color: #1a1a1a;
            --card-bg: #2d2d2d;
            --text-color: #e0e0e0;
            --title-color: #ffffff;
            --secondary-text: #b0b0b0;
            --border-color: #404040;
        }

        body { 
            font-family: Arial, sans-serif; 
            margin: 20px; 
            background-color: var(--bg-color);
            color: var(--text-color);
            transition: all 0.3s ease;
        }

        .controls {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
            flex-wrap: wrap;
            align-items: center;
        }

        .control-group {
            display: flex;
            gap: 10px;
            align-items: center;
        }

        input, select {
            padding: 8px;
            border-radius: 5px;
            border: 1px solid var(--border-color);
            background: var(--card-bg);
            color: var(--text-color);
        }

        button {
            padding: 8px 16px;
            border-radius: 5px;
            border: 1px solid var(--border-color);
            background: var(--card-bg);
            color: var(--text-color);
            cursor: pointer;
            transition: all 0.2s ease;
        }

        button:hover {
            background: var(--border-color);
        }

        .movie-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); 
            gap: 20px; 
        }

        .movie-card {
            background: var(--card-bg);
            padding: 15px;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.3);
            transition: transform 0.2s ease-in-out;
        }

        .movie-card.hidden {
            display: none;
        }

        .movie-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.4);
        }

        .movie-card img { 
            width: 100%;
            height: auto; 
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }

        .movie-info { 
            margin-top: 10px; 
        }

        h1 { 
            color: var(--title-color);
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 10px;
        }

        h2 { 
            margin: 10px 0; 
            color: var(--title-color);
            font-size: 1.2em;
        }

        .rating { 
            color: #ffd700; 
            font-weight: bold;
            background: var(--border-color);
            padding: 3px 8px;
            border-radius: 5px;
            display: inline-block;
        }

        .genres { 
            color: var(--secondary-text);
            font-style: italic;
        }

        strong {
            color: var(--title-color);
        }

        p {
            margin: 8px 0;
            line-height: 1.4;
        }

        .plot {
            color: var(--text-color);
            font-size: 0.95em;
            margin-top: 12px;
            line-height: 1.5;
        }

        .theme-toggle {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
        }
    </style>
</head>
<body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓 Toggle Theme</button>
    <h1>Movie Library</h1>
    
    <div class="controls">
        <div class="control-group">
            <input type="text" id="searchInput" placeholder="Search movies..." onkeyup="filterMovies()">
        </div>
        
        <div class="control-group">
            <select id="directorFilter" onchange="filterMovies()">
                <option value="">All Directors</option>
                {% for director in directors %}
                    <option value="{{ director }}">{{ director }}</option>
                {% endfor %}
            </select>

            <select id="genreFilter" onchange="filterMovies()">
                <option value="">All Genres</option>
                {% for genre in genres %}
                    <option value="{{ genre }}">{{ genre }}</option>
                {% endfor %}
            </select>
        </div>

        <div class="control-group">
            <select id="sortBy" onchange="sortMovies()">
                <option value="title">Sort by Title</option>
                <option value="year">Sort by Year</option>
                <option value="rating">Sort by Rating</option>
                <option value="director">Sort by Director</option>
            </select>
            <button onclick="toggleSortDirection()">↑↓</button>
        </div>
    </div>

    <div class="movie-grid">
        {% for movie in movies %}
        <div class="movie-card" 
             data-title="{{ movie['title']|lower }}"
             data-year="{{ movie['year'] }}"
             data-rating="{{ movie['rating'] }}"
             data-director="{{ movie['director']|lower }}"
             data-genres="{{ movie['genres']|lower }}">
            {% if movie['poster_path'] %}
            <img src="{{ movie['poster_path'] }}" alt="{{ movie['title'] }} poster">
            {% endif %}
            <div class="movie-info">
                <h2>{{ movie['title'] }} ({{ movie['year'] }})</h2>
                <p><strong>Director:</strong> {{ movie['director'] }}</p>
                <p><strong>Countries:</strong> {{ movie['countries'] }}</p>
                <p class="genres">{{ movie['genres'] }}</p>
                <p class="rating">★ {{ "%.1f"|format(movie['rating']) }}/10</p>
                <p class="plot">{{ movie['plot'] }}</p>
            </div>
        </div>
        {% endfor %}
    </div>

    <script>
        let sortDirection = 1; // 1 for ascending, -1 for descending

        function toggleTheme() {
            const html = document.documentElement;
            const currentTheme = html.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        }

        // Load saved theme preference
        const savedTheme = localStorage.getItem('theme') || 'dark';
        document.documentElement.setAttribute('data-theme', savedTheme);

        function filterMovies() {
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const selectedDirector = document.getElementById('directorFilter').value.toLowerCase();
            const selectedGenre = document.getElementById('genreFilter').value.toLowerCase();
            
            document.querySelectorAll('.movie-card').forEach(card => {
                const title = card.getAttribute('data-title');
                const director = card.getAttribute('data-director');
                const genres = card.getAttribute('data-genres');
                
                const matchesSearch = title.includes(searchTerm);
                const matchesDirector = !selectedDirector || director.includes(selectedDirector);
                const matchesGenre = !selectedGenre || genres.includes(selectedGenre);
                
                card.classList.toggle('hidden', !(matchesSearch && matchesDirector && matchesGenre));
            });
        }

        function toggleSortDirection() {
            sortDirection *= -1;
            sortMovies();
        }

        function sortMovies() {
            const sortBy = document.getElementById('sortBy').value;
            const movieGrid = document.querySelector('.movie-grid');
            const movies = Array.from(document.querySelectorAll('.movie-card'));
            
            movies.sort((a, b) => {
                let valueA = a.getAttribute('data-' + sortBy);
                let valueB = b.getAttribute('data-' + sortBy);
                
                if (sortBy === 'rating' || sortBy === 'year') {
                    valueA = parseFloat(valueA);
                    valueB = parseFloat(valueB);
                }
                
                if (valueA < valueB) return -1 * sortDirection;
                if (valueA > valueB) return 1 * sortDirection;
                return 0;
            });
            
            movies.forEach(movie => movieGrid.appendChild(movie));
        }
    </script>
</body>
</html>'''
    
    return render_template_string(
        template,
        movies=movies,
        directors=sorted(set(m['director'] for m in movies if m['director'])),
        genres=sorted(set(genre.strip() for m in movies if m['genres'] for genre in m['genres'].split(',')))
    )

if __name__ == '__main__':
    # Setup database and scan for movies
    setup_database()
    scan_and_update_database()
    
    # Start the web application
    app.run(debug=True)