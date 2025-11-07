import os, datetime as dt
from flask import Flask, render_template, request, redirect, url_for, abort #flask object, render template renders jinja template/ html pages,
#request redirect form handling and redirects
from flask_sqlalchemy import SQLAlchemy # handles sqlite 

from services.sun import get_sun_times#API calls in service folder 
from services.weather import get_weather_hours

BASE = os.path.dirname(os.path.abspath(__file__))
#creates flask app, template and static folder called 
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE, "instance", "fyp_database.db")
#stores sqlite folder in instance folder
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "dev"
#secret key is used for session management
db = SQLAlchemy(app)
#creates sqlachemy helper in this app.

class Location(db.Model): #tabke for photography spots
    id = db.Column(db.Integer, primary_key=True) #locations id primary key 
    name = db.Column(db.String(200), nullable=False, unique=True) #the name of the location
    slug = db.Column(db.String(200), nullable=False, unique=True) #Url version of the name
    lat = db.Column(db.Float, nullable=False) #coordinates for location
    lon = db.Column(db.Float, nullable=False) #coordinates for location
    notes = db.Column(db.String(400)) #fact or notes while creating location can be included 

def slugify(s: str):
    #makes the link readable, useful for english names
    #lowercase and coverrts and non numeric to hyphens
    s = "".join(ch.lower() if ch.isalnum() else "-" for ch in s).strip("-")
    #collapses duplicate hyphen and reduces length to 200 characters
    return "-".join(filter(None, s.split("-")))[:200]

@app.route("/")
def home():
    #home page lists all locations in grid style subject to change in later iterations
    #server rendered list because it works well for my basic knowledge of Java from last year
    locations = Location.query.order_by(Location.name).all()
    return render_template("home.html", locations=locations)

@app.route("/add", methods=["GET","POST"]
)
#Adds a new location to the database using get and post method
def add_location():
    if request.method == "POST":
        name = request.form.get("name","" ).strip() #name of location
        lat = float(request.form.get("lat")) #latitude coordinate
        lon = float(request.form.get("lon")) #longitude coordinate
        notes = request.form.get("notes","" ).strip() #notes about location
        if not name: abort(400) #validates the input, if not validated aborts returning error to user
        slug = slugify(name) #make a slug name and ensure its unique
        if db.session.query(Location.id).filter_by(slug=slug).first():
            import time; slug = f"{slug}-{int(time.time())}" #insures unique slug by appending timestamp
            #creates and saves a location 
        loc = Location(name=name, lat=lat, lon=lon, notes=notes, slug=slug)
        db.session.add(loc); db.session.commit()
        #redirects user to detail page to view the created location
        return redirect(url_for("location_detail", slug=slug))
    #Get renders the form
    return render_template("add_location.html")

@app.route("/l/<slug>")
def location_detail(slug):
    #detail page for locations, uses external api calls in service
    loc = Location.query.filter_by(slug=slug).first_or_404()#loads the location or 404 if none
    today = dt.date.today()#uses todays date 

    sun = get_sun_times(lat=loc.lat, lon=loc.lon, date=today)#fetches neseccary data required
    weather = get_weather_hours(lat=loc.lat, lon=loc.lon)#fetches neseccary data required

    return render_template( #renders the template and we give what data it requires
        "location.html",
        location=loc,
        sun=sun,
        weather=weather,
    )

if __name__ == "__main__":
    os.makedirs(os.path.join(BASE,"instance"), exist_ok=True)# ensures instance folders exists so SQLite can create the db
    with app.app_context():#create tabeles if none exist
        db.create_all()
    app.run(debug=True)#runs the dev server on device
