from flask import Flask, request, redirect, render_template, make_response
from datetime import datetime
import psycopg2
import pandas as pd
import pytz
import requests
from config import DB_CONFIG, WEATHER_CONFIG

now = datetime.now().replace(microsecond=0)
app = Flask(__name__)

def get_current_weather():
    url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "zip": f"{WEATHER_CONFIG['zip_code']},{WEATHER_CONFIG['country_code']}",
        "appid": WEATHER_CONFIG['api_key'],
        "units": "imperial"  # Changed from metric to imperial for Fahrenheit
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        return {
            "temp_f": data["main"]["temp"],  # Now returns Fahrenheit
            "humidity": data["main"]["humidity"],
            "conditions": data["weather"][0]["main"],
            "wind_speed": data["wind"]["speed"]  # Note: This will now be in mph
        }
    except Exception as e:
        print(f"Weather API error: {e}")
        return None

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            ph = float(request.form.get("ph"))
            ec_raw = float(request.form.get("ec_ms_cm"))
            ec = ec_raw / 1000  # convert to mS/cm for DB
            ppm = int(request.form.get("ppm"))
            salt_percent = float(request.form.get("salt_percent"))
            water_temp_c = float(request.form.get("water_temp_c"))
            water_height_in = float(request.form.get("water_height_in", 0))
            water_gallons = height_to_gallons(water_height_in)
            weather = get_current_weather()

            with psycopg2.connect(**DB_CONFIG) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO tower_readings 
                        (date, ph, ec_ms_cm, ppm, salt_percent, water_temp_c, 
                         water_height_in, water_gallons, outside_temp_f,  # Changed from outside_temp_c 
                         humidity, weather_conditions, wind_speed)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        now, ph, ec, ppm, salt_percent, water_temp_c, 
                        water_height_in, water_gallons,
                        weather["temp_f"] if weather else None,  # Changed from temp_c
                        weather["humidity"] if weather else None,
                        weather["conditions"] if weather else None,
                        weather["wind_speed"] if weather else None
                    ))
                conn.commit()

        except (ValueError, TypeError) as e:
            print(f"Error processing form: {e}")  # Debug print
            return "Invalid input, please enter valid numbers", 400

    return render_template("form.html")

@app.route("/export")
def export_data():
    start_date = request.args.get('start_date', default=None)
    end_date = request.args.get('end_date', default=None)
    
    query = """
        SELECT date, ph, ec_ms_cm, ppm, salt_percent, water_temp_c
        FROM tower_readings
        WHERE date BETWEEN %s AND %s
        ORDER BY date DESC
    """
    
    with psycopg2.connect(**DB_CONFIG) as conn:
        df = pd.read_sql(query, conn, params=[start_date, end_date])
        
    resp = make_response(df.to_csv(index=False))
    resp.headers["Content-Disposition"] = "attachment; filename=hydro_data.csv"
    resp.headers["Content-Type"] = "text/csv"
    return resp

@app.route("/history")
def history():
    with psycopg2.connect(**DB_CONFIG) as conn:
        query = """
            SELECT date, ph, ec_ms_cm, ppm, salt_percent, water_temp_c, 
                   water_height_in, water_gallons
            FROM tower_readings 
            ORDER BY date DESC 
            LIMIT 50
        """
        df = pd.read_sql(query, conn)
        
        # Convert timezone-aware timestamps to local time
        eastern = pytz.timezone('America/New_York')
        df['date'] = df['date'].dt.tz_convert(eastern)
        
        # Replace any NaN values with None for Jinja2 template
        df = df.where(pd.notnull(df), None)
        
        readings = df.to_dict('records')
    return render_template("history.html", readings=readings)
def height_to_gallons(height_in):
    # Based on your bucket markings:
    # 5 gal bucket height (inches)
    total_height = 14.5  # adjust this to your bucket’s full height in inches
    total_gallons = 5
    
    gallons = (height_in / total_height) * total_gallons
    return round(gallons, 2)

if __name__ == "__main__":
    # Expose server on all interfaces for LAN access, debug on for dev
    app.run(host="0.0.0.0", port=5000, debug=True)
