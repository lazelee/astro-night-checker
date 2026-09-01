import os
import sqlite3
import requests
import smtplib
import warnings
from email.message import EmailMessage
from astropy.time import Time
from astropy.coordinates import get_body, GeocentricTrueEcliptic
from dotenv import load_dotenv

warnings.filterwarnings('ignore', module='astropy')
load_dotenv()

# your location
city = "toronto"
country_input = "canada"

# static bortle map - update when needed
# i use this website: https://lightpollutionmap.app/
bortle_map = {
    "toronto": 9, 
    "vancouver": 9,
    "gravenhurst": 5
}
bortle = bortle_map.get(city.lower(), "Unknown (Add to Dict)")

# local db setup
conn = sqlite3.connect('astro_scheduler.db')
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS forecast_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        city TEXT,
        date TEXT,
        best_window TEXT,
        avg_cloud_cover REAL,
        avg_precip REAL,
        moon_phase TEXT
    )
''')
conn.commit()

# fetch geodata globally
geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=10"
geo_data = requests.get(geo_url).json()

if not geo_data.get('results'):
    print(f"Error: Could not locate city '{city}'.")
    exit()

# filter for country
target_location = None
for res in geo_data['results']:
    if res.get('country', '').lower() == country_input.lower():
        target_location = res
        break

if not target_location:
    print(f"Error: Found '{city}', but not in '{country_input}'.")
    exit()

# lock in correct coordinates
lat = target_location['latitude']
lon = target_location['longitude']
region = target_location.get('admin1', '')
country = target_location.get('country', '')
display_city = f"{target_location['name']}, {region}, {country}".strip(", ")

print(f"Locked onto: {display_city} | Lat: {lat}, Lon: {lon} | Bortle: {bortle}")

# fetch 16-day hourly forecast 
weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=cloudcover,precipitation_probability&daily=sunrise,sunset&timezone=auto&forecast_days=16"
weather = requests.get(weather_url).json()

html_rows = ""
optimal_count = 0

# evaluate next 15 nights
for i in range(15):
    sunset_str = weather['daily']['sunset'][i]
    sunrise_str = weather['daily']['sunrise'][i+1]
    
    date_display = sunset_str.split("T")[0]
    sunset_time = sunset_str.split("T")[1]
    sunrise_time = sunrise_str.split("T")[1]
    
    sunset_hr = int(sunset_time.split(":")[0])
    sunrise_hr = int(sunrise_time.split(":")[0])
    
    start_idx = (i * 24) + sunset_hr
    end_idx = ((i + 1) * 24) + sunrise_hr
    
    good_windows = []
    current_window = []
    
    for hr_idx in range(start_idx, end_idx + 1):
        cc = weather['hourly']['cloudcover'][hr_idx]
        pp = weather['hourly']['precipitation_probability'][hr_idx]
        
        # safeguard missing data at end of 16-day range
        if cc is not None and pp is not None and cc < 25 and pp < 15:
            current_window.append((hr_idx, cc, pp))
        else:
            if current_window:
                good_windows.append(current_window)
                current_window = []
                
    if current_window:
        good_windows.append(current_window)
        
    if not good_windows:
        continue
        
    # isolate longest, clearest window
    best_window = sorted(good_windows, key=lambda w: (len(w), -sum(h[1] for h in w)/len(w)), reverse=True)[0]
    
    start_best = weather['hourly']['time'][best_window[0][0]].split("T")[1]
    end_best = weather['hourly']['time'][best_window[-1][0]].split("T")[1]
    best_time_str = f"{start_best} - {end_best}" if start_best != end_best else start_best
    
    avg_cc = int(sum(h[1] for h in best_window) / len(best_window))
    avg_pp = int(sum(h[2] for h in best_window) / len(best_window))
    
    # exact lunar phase math
    obs_date = weather['hourly']['time'][best_window[0][0]]
    obs_time = Time(f"{obs_date.split('T')[0]} {start_best}:00")
    moon = get_body('moon', obs_time)
    sun = get_body('sun', obs_time)
    
    moon_ecl = moon.transform_to(GeocentricTrueEcliptic(equinox=obs_time))
    sun_ecl = sun.transform_to(GeocentricTrueEcliptic(equinox=obs_time))
    elongation = (moon_ecl.lon.deg - sun_ecl.lon.deg) % 360
    
    if elongation < 10 or elongation > 350: phase = "New Moon"
    elif elongation < 80: phase = "Waxing Crescent"
    elif elongation < 100: phase = "First Quarter"
    elif elongation < 170: phase = "Waxing Gibbous"
    elif elongation < 190: phase = "Full Moon"
    elif elongation < 260: phase = "Waning Gibbous"
    elif elongation < 280: phase = "Last Quarter"
    else: phase = "Waning Crescent"
    
    c.execute('''INSERT INTO forecast_logs (city, date, best_window, avg_cloud_cover, avg_precip, moon_phase)
                 VALUES (?, ?, ?, ?, ?, ?)''', (display_city, date_display, best_time_str, avg_cc, avg_pp, phase))
    
    html_rows += f"<tr><td>{date_display}</td><td>{sunset_time}</td><td>{sunrise_time}</td><td>{best_time_str}</td><td>{avg_cc}%</td><td>{avg_pp}%</td><td>{phase}</td></tr>"
    optimal_count += 1

conn.commit()
conn.close()

# send payload
if optimal_count > 0:
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif;">
        <h3>Optimal Astrophotography Nights: {display_city} (Bortle {bortle})</h3>
        <p><b>Forecast Window:</b> Next 16 Days</p>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
          <tr style="background-color: #f2f2f2;">
            <th>Date</th><th>Sunset</th><th>Sunrise</th><th>Best Time</th><th>Avg Cloud Cover</th><th>Avg Precip Chance</th><th>Moon Phase</th>
          </tr>
          {html_rows}
        </table>
      </body>
    </html>
    """
    
    msg = EmailMessage()
    msg['Subject'] = f"Astro Alert: {optimal_count} Optimal Nights Upcoming"
    msg['From'] = os.getenv("SENDER_EMAIL")
    msg['To'] = os.getenv("SENDER_EMAIL") 
    msg.set_content("Please enable HTML to view this message.")
    msg.add_alternative(html_content, subtype='html')

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(os.getenv("SENDER_EMAIL"), os.getenv("APP_PASSWORD"))
        smtp.send_message(msg)
    print(f"Alert sent via email with {optimal_count} optimal nights.")
else:
    print("No optimal nights found in the next 16 days.")

