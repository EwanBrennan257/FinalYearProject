import os, datetime as dt
from flask import Flask, render_template, request, redirect, url_for, abort #flask object, render template renders jinja template/ html pages,
#request redirect form handling and redirects
from flask_sqlalchemy import SQLAlchemy # handles sqlite 

from services.sun import get_sun_times#API calls in service folder 
from services.weather import get_weather_hours

from flask_login import ( #login manager
    LoginManager, login_user, login_required,
    logout_user, current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

from services.tide import get_cork_tides 

import datetime as dt

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
login_manager = LoginManager(app)
login_manager.login_view = "login"

class Location(db.Model): #tabke for photography spots
    id = db.Column(db.Integer, primary_key=True) #locations id primary key 
    name = db.Column(db.String(200), nullable=False, unique=True) #the name of the location
    slug = db.Column(db.String(200), nullable=False, unique=True) #Url version of the name
    lat = db.Column(db.Float, nullable=False) #coordinates for location
    lon = db.Column(db.Float, nullable=False) #coordinates for location
    notes = db.Column(db.String(400)) #fact or notes while creating location can be included 

class User(UserMixin, db.Model):#creates sqlalchemy model for users, usermixin helps flask manager login users
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False) #where hashed password is stored
    role = db.Column(db.String(20), nullable=False, default="user") # user roles admin or normal users
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)# timestap for row being created

    def set_password(self, pw: str):#hashes password and stores it in password hash
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:# validates if entered password is correct
        return check_password_hash(self.password_hash, pw)
    
@login_manager.user_loader#required by flask login returns corresponding user so that same user works on later requests
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(view_func):#if user who is not admin attempts to access admin function they are not allowed to access it
    @wraps(view_func)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)#returns 403 forbidden if is attempted
        return view_func(*args, **kwargs)
    return wrapper

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

    today = dt.date.today()

    sun = get_sun_times(lat=loc.lat, lon=loc.lon, date=today)#fetches neseccary data required
    weather = get_weather_hours(lat=loc.lat, lon=loc.lon)#fetches neseccary data required

    tide_info = get_cork_tides()

    return render_template( #renders the template and we give what data it requires
        "location.html",
        location=loc,
        sun=sun,
        weather=weather,
        high_tides=tide_info["high_tides"],
        low_tides=tide_info["low_tides"],
        tide_error=tide_info["error"],
    )

@app.route("/auth/register", methods=["GET", "POST"])#route decorator defines endpoint thats acepts get and post requests
def register():
    message = None,#intialises message variable to none trailing comma makes this a ruple
    if request.method == "POST":#check if the request is a post request
        email = (request.form.get("email") or "").strip().lower()#get email from form data conver to lowercase and strip whitespace
        #uses "" to handle none values 
        password = request.form.get("password") or ""#get password from form data default to empty string if none

        if not email or not password:#validate that both email and password are provided
            message = "Email and password are required."
        elif User.query.filter_by(email=email).first():#check if email already exists in db
            message = "That email is already registered."
        else:#if vlaidation passes create new user
            user = User(email=email, role="user")#create a new user object with email and default role user
            user.set_password(password)#hash and set password 
            db.session.add(user)#add new user to the db
            db.session.commit()#commit transaction to save user in db
            login_user(user)#log the user in after
            return redirect(url_for("home"))#redirect to homepage once succesful
#render registraion template with error message, get requests and post requets will reach here
    return render_template("register.html", message=message)

#route decorator defines endpoint acepts get and post request
@app.route("/auth/login", methods=["GET", "POST"])
def login():
    message = None#intialize message variable to none for error feedback message
    if request.method == "POST":#check if request is post request
        email = (request.form.get("email") or "").strip().lower()#get email from form data strip whitespace adn convert to lowercase
        password = request.form.get("password") or ""#get the password from form data default to empty string if none
        user = User.query.filter_by(email=email).first()#query database to find user with matching email
        if user and user.check_password(password):#verify is user exists and password is correct
            login_user(user)#log the user in creates session
            nxt = request.args.get("next")#get the next paramater from url query strin for redirect after login
            return redirect(nxt or url_for("home"))#redirect to the next url if it exists or go home
        message = "Invalid email or password."#if authentication fails set error message
    return render_template("login.html", message=message)#render login template with any error message get request or failed post will go here


@app.route("/auth/logout")#defines endpoint for logout url 
@login_required#decorator requiring user to be logged in to access this route
def logout():
    logout_user()#log out the current user 
    return redirect(url_for("home"))#redirect to home page


if __name__ == "__main__":
    os.makedirs(os.path.join(BASE,"instance"), exist_ok=True)# ensures instance folders exists so SQLite can create the db
    with app.app_context():#create tabeles if none exist
        db.create_all()
    app.run(debug=True)#runs the dev server on device
