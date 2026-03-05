#datetime used for dates and times
import os, datetime as dt
import uuid
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
import cloudinary.api
#use this to find other files in relation to this locaiton
BASE = os.path.dirname(os.path.abspath(__file__))
#trys to load api keys and password from .env
try:
    from dotenv import load_dotenv#imports function from .env
    load_dotenv(os.path.join(BASE, ".env"))#loads the function from project folder
except Exception:#incase of error ignore and continue
    pass
#import all flask items
from flask import Flask, render_template, request, redirect, url_for, abort, flash, jsonify, session #flask object, render template renders jinja template/ html pages,
#request redirect form handling and redirects
#https://flask-sqlalchemy.readthedocs.io/en/stable/
from flask_sqlalchemy import SQLAlchemy # handles sqlite 

from services.sun import get_sun_times#API calls in service folder 
from services.weather import get_weather_hours
from services.groq_agent import GroqAgent
from services.photo_analysis import PhotoAnalyzer

from flask_login import ( #login manager used for whos logged in
    LoginManager, login_user, login_required,#logout for people who logout 
    logout_user, current_user, UserMixin
)
#has passwords so they can't be read
from werkzeug.security import generate_password_hash, check_password_hash
#used for creating custom decorators
from functools import wraps
#email sending tool
from flask_mail import Mail, Message
#used for creating secure confirmation token makes encrypted tickets that expire
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
#import tide info
from services.tide import get_cork_tides 
#import SQL functions
from sqlalchemy.sql import func


#reads enviroment variables as true or false
def _env_bool(key: str, default: bool) -> bool:
    #get enviroment variable
    v = os.getenv(key)
    #if it doesn't exist use default
    if v is None:
        return default
    #check if the value is something that means yes or similar to yes
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}

#sets up base directory again
BASE = os.path.dirname(os.path.abspath(__file__))
#creates flask app, template and static folder called 
app = Flask(__name__, static_folder="static", template_folder="templates")

# Get database URL from environment variable
database_url = os.getenv("DATABASE_URL", "postgresql://postgres:Teddycork2016%3F@localhost:5432/fyp_database")

#render provides DATABASE_URL starting with postgres://, but SQLAlchemy needs postgresql://
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url

#Cloudinary configuration
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)
#https://flask.palletsprojects.com/en/stable/patterns/fileuploads/
#https://cloudinary.com/documentation/image_upload_api_reference
#https://pypi.org/project/cloudinary/
# file upload configuration
UPLOAD_FOLDER = os.path.join(BASE, "static", "uploads")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER  
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

#create uploads folder if needed
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    #Check if file extension is allowed
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

#stores sqlite folder in instance folder
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
#creates secret key used for encryption
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")

#tells it to use gmail servers
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
#sets the port number for the email server 
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))
#TLS used for encryption in transit
app.config["MAIL_USE_TLS"] = _env_bool("MAIL_USE_TLS", True)
app.config["MAIL_USE_SSL"] = _env_bool("MAIL_USE_SSL", False)
#gmail name or email
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
#app password set up using personal email college one did not work
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
#where the emails come from personal email again
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER") or app.config.get("MAIL_USERNAME")
#secret salt for tokens prevents tampering
app.config["EMAIL_CONFIRM_SALT"] = os.getenv("EMAIL_CONFIRM_SALT", "email-confirm-salt")
#period of time until confirmation link expires
app.config["EMAIL_CONFIRM_MAX_AGE_SECONDS"] = int(os.getenv("EMAIL_CONFIRM_MAX_AGE_SECONDS", "3600"))
#http used for development
app.config["PREFERRED_URL_SCHEME"] = os.getenv("PREFERRED_URL_SCHEME", "http")

#connect database to flask and project
db = SQLAlchemy(app)

# Create tables if they don't exist (temporary - for initial deployment)
with app.app_context():
    db.create_all()

#creates sqlachemy helper in this app.
login_manager = LoginManager(app)#tracks whos logged in
login_manager.login_view = "login"#if user trys to access login only page

mail = Mail(app)#connect email system to the flask app

@app.context_processor
def inject_google_maps_key():
    return dict(
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
        cloudinary_cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME")
    )

class Location(db.Model): #tabke for photography spots
    id = db.Column(db.Integer, primary_key=True) #locations id primary key 
    name = db.Column(db.String(200), nullable=False, unique=True) #the name of the location
    slug = db.Column(db.String(200), nullable=False, unique=True) #Url version of the name
    lat = db.Column(db.Float, nullable=False) #coordinates for location
    lon = db.Column(db.Float, nullable=False) #coordinates for location
    is_coastal = db.Column(db.Boolean, nullable=False, default=True)#is this location near the coast
    notes = db.Column(db.String(400)) #fact or notes while creating location can be included 
    reviews = db.relationship(#connects locations to their reviews
        "Review",#reviews come from review table
        backref="location",
        lazy=True,#don't automatically load reviews actual location detail is important
        cascade="all, delete-orphan"#if we delete location delete reviews too
    )
    photos = db.relationship(
        "Photo",
        backref="location",
        lazy=True,
        cascade="all, delete-orphan"
    )
    visits = db.relationship(
        "Visit",
        backref="location",
        lazy=True,
        cascade="all, delete-orphan"#delete a location delete its visits
    )

class User(UserMixin, db.Model):#creates sqlalchemy model for users, usermixin helps flask manager login users
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False) #where hashed password is stored
    role = db.Column(db.String(20), nullable=False, default="user") # user roles admin or normal users
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)# timestap for row being created

    is_verified = db.Column(db.Boolean, nullable=False, default=False)#have they confirmed their email yet
    verified_at = db.Column(db.DateTime, nullable=True)#when did they confirm it

    def set_password(self, pw: str):#hashes password and stores it in password hash
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:# validates if entered password is correct
        return check_password_hash(self.password_hash, pw)
    
    reviews = db.relationship(#connects user to their review
        "Review",#reviews come from review table
        backref="user",#from a review you can access the user who wrote it
        lazy=True,#don't load reviews automatically
        cascade="all, delete-orphan"#delete a user delete their reviews
    )
    photos = db.relationship(
        "Photo",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )
    visits = db.relationship(
        "Visit",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"#delete a user delete their visits
    )

#https://docs.sqlalchemy.org/en/21/orm/basic_relationships.html
#https://docs.sqlalchemy.org/en/21/core/constraints.html
#https://flask.palletsprojects.com/en/stable/patterns/flashing/
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)#reviews get unique id number

    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)#location id so system knows
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)#who wrote the review

    rating = db.Column(db.Integer, nullable=False)  #1 to 5 rating system
    body = db.Column(db.String(1000), nullable=False)# review text

    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)#when was the review written at

#a personal visit log for users to track locations they've been to
class Visit(db.Model):
    id = db.Column(db.Integer, primary_key=True)#unique id for each visit
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)#who visited
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)#which location

    visited_date = db.Column(db.Date, nullable=False)#when did they visit
    note = db.Column(db.String(1000))#personal note about their visit

    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)#when was this record made

    #each user can only mark a location as visited once
    __table_args__ = (
        db.UniqueConstraint("user_id", "location_id", name="uq_user_location_visit"),
    )

class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    cloudinary_public_id = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    caption = db.Column(db.String(500))
    uploaded_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

class PhotoAnalysis(db.Model):
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    
    #these were meant to be added but i couldn't only here as i don't want to acidentally break system before submission
    labels = db.Column(db.JSON)  # Objects detected
    colors = db.Column(db.JSON)  # Dominant colors
    landmarks = db.Column(db.JSON)  # Famous places detected
    text_found = db.Column(db.JSON)  # Any text in image (OCR)
    properties = db.Column(db.JSON)  # Other properties
    
    analyzed_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref='photo_analyses')

from trips import init_trips
app.register_blueprint(init_trips(db, Location))

# Register the events blueprint
from events import init_events
app.register_blueprint(init_events(db, Location))

# Initialize database tables on startup
with app.app_context():
    db.create_all()
    print(" Database tables created!")

    #auto promote the admin email from environment variable
    admin_email = os.getenv("ADMIN_EMAIL")
    if admin_email:
        admin_email = admin_email.strip().lower()
        admin_user = User.query.filter_by(email=admin_email).first()
        if admin_user and admin_user.role != "admin":
            admin_user.role = "admin"
            db.session.commit()
            print(f" {admin_email} promoted to admin!")
    
@login_manager.user_loader#required by flask login returns corresponding user so that same user works on later requests
def load_user(user_id):#maintains a users session
    return User.query.get(int(user_id))#look up user in database and return them

def admin_required(view_func):#if user who is not admin attempts to access admin function they are not allowed to access it
    @wraps(view_func)
    @login_required#requires user to be logged in
    def wrapper(*args, **kwargs):#checks to see if user is admin
        if current_user.role != "admin":
            abort(403)#returns 403 forbidden if is attempted
        return view_func(*args, **kwargs)#if admin let them go ahead
    return wrapper
#https://pypi.org/project/python-slugify/
def slugify(s: str):
    #makes the link readable, useful for english names
    #lowercase and coverrts and non numeric to hyphens
    s = "".join(ch.lower() if ch.isalnum() else "-" for ch in s).strip("-")
    #collapses duplicate hyphen and reduces length to 200 characters
    return "-".join(filter(None, s.split("-")))[:200]

def _confirm_serializer() -> URLSafeTimedSerializer:#tool used for creating secure tokens
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])#tokens automatically expire

#https://www.freecodecamp.org/news/setup-email-verification-in-flask-app/
#https://mailtrap.io/blog/flask-email-verification/
#https://www.youtube.com/watch?v=uE9ZesslPYU
#https://www.youtube.com/watch?v=vF9n248M1yk


#create confirmation token for users email
def generate_confirmation_token(email: str) -> str:
    #encrypt email into a token to be put it into url
    return _confirm_serializer().dumps(email, salt=app.config["EMAIL_CONFIRM_SALT"])

#checks if confirmation token is valid and extracts it from the email
def confirm_email_token(token: str) -> str | None:
    #try and decrypt the token
    try:
        return _confirm_serializer().loads(
            #token to be decrypted
            token,
            #salt must be same one we created with
            salt=app.config["EMAIL_CONFIRM_SALT"],
            #check to see if its expired
            max_age=app.config["EMAIL_CONFIRM_MAX_AGE_SECONDS"],
        )
    #if token is expired or tampered with return none
    except (SignatureExpired, BadSignature):
        return None

#check to see if email is correctly set up
def _mail_is_configured() -> bool:
    #ensure all email settings are correct and fileld in
    return bool(
        app.config.get("MAIL_SERVER")#yes to mail server?
        and app.config.get("MAIL_PORT")#yes to port number?
        and app.config.get("MAIL_USERNAME")#yes to username
        and app.config.get("MAIL_PASSWORD")#yes to password
        and app.config.get("MAIL_DEFAULT_SENDER")#yes to sender address?
    )

#send the confirmation email
def send_confirmation_email(user: User) -> bool:
    #returns true if sent correctly
    #creates secure token with user's email in it
    token = generate_confirmation_token(user.email)
    #build the url for the confirmation page
    confirm_url = url_for("confirm_email", token=token, _external=True)
    #what the subject line is
    subject = "Confirm your email - Cork Photographers"
    body = (#and whats inside the email
        "Thanks for signing up to Cork Photographers.\n\n"
        "Please confirm your email by clicking the link below:\n"
        f"{confirm_url}\n\n"
        "This link expires in 1 hour."
    )

    # If email is not configured, print the link to the terminal incase of error
    if not _mail_is_configured():
        print("\n[Email not configured] Confirmation link for", user.email)
        print(confirm_url)
        print()
        return False

    try:#try to send the email again
        import socket
        # Save current timeout and set 10 second timeout for SMTP
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(10)
    
        #create the email again
        msg = Message(subject=subject, recipients=[user.email], body=body)
        #send it
        mail.send(msg)
    
        # Restore original timeout
        socket.setdefaulttimeout(old_timeout)
        return True
    except Exception as e:
        # Avoid crashing the registration flow if SMTP fails.
        print("\n[Email error] Could not send confirmation email:", str(e))
        print("Confirmation link (for debugging):", confirm_url)
        print()
    return False

@app.route("/")
def home():
    #home page lists all locations in grid style subject to change in later iterations
    #server rendered list because it works well for my basic knowledge of Java from last year
    #home page lists all locations, supports search
    q = (request.args.get("q") or "").strip()#get search query from URL
#https://www.freecodecamp.org/news/how-to-implement-instant-search-with-flask-and-htmx/
    if q:#if they searched for something filter locations
        locations = (
            Location.query#start a query on the locations table
            .filter(Location.name.ilike(f"%{q}%"))#filter where the name matches the search, ilike makes it case sensitive
            .order_by(Location.name)#sorts results alphabetically
            .all()#run the query to get all matching results
        )
    else:#no search show all locations
        locations = Location.query.order_by(Location.name).all()#all locations osrted a to z

    return render_template("home.html", locations=locations, search_query=q)#render homepage pass locations in what they searched for

#404 Error Handler
@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

#413 Error Handler
@app.errorhandler(413)
def file_too_large(e):
    flash("File is too large. Cloudinary only supports uploads up to 5MB. Please choose a smaller image.", "warning")
    return redirect(request.referrer or url_for("home"))

#About Page
@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/add", methods=["GET","POST"]
)
@login_required
#Adds a new location to the database using get and post method
def add_location():
    if request.method == "POST":
        name = request.form.get("name","" ).strip() #name of location
        lat = float(request.form.get("lat")) #latitude coordinate
        lon = float(request.form.get("lon")) #longitude coordinate
        notes = request.form.get("notes","" ).strip() #notes about location
        is_coastal = request.form.get("is_coastal") == "yes"#check if they selected coastal
        if not name: abort(400) #validates the input, if not validated aborts returning error to user
        slug = slugify(name) #make a slug name and ensure its unique
        if db.session.query(Location.id).filter_by(slug=slug).first():
            import time; slug = f"{slug}-{int(time.time())}" #insures unique slug by appending timestamp
            #creates and saves a location 
        loc = Location(name=name, lat=lat, lon=lon, notes=notes, slug=slug, is_coastal=is_coastal)
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

    #only fetch tide data if the location is coastal
    if loc.is_coastal:
        tide_info = get_cork_tides()
    else:
        tide_info = {"high_tides": [], "low_tides": [], "error": None}

    reviews = (#get all reviews for a location
        Review.query# start a query on the table
        .filter_by(location_id=loc.id)#only reviews for this location
        .order_by(Review.created_at.desc())#sort by newest
        .all()#get them all
    )

    #average rating (None if no reviews)
    avg_rating = (
        db.session.query(func.avg(Review.rating))
        .filter(Review.location_id == loc.id)
        .scalar()
    )#convert to float or leave if 0 reviews
    avg_rating = float(avg_rating) if avg_rating is not None else None
    review_count = len(reviews)#count the number of reviews

    #check if current user has visited this location
    user_visit = None
    if current_user.is_authenticated:
        user_visit = Visit.query.filter_by(user_id=current_user.id, location_id=loc.id).first()    

    return render_template( #renders the template and we give what data it requires
        "location.html",#which template to use
        location=loc,#location object
        sun=sun,#sunset data
        weather=weather,#weather data
        high_tides=tide_info["high_tides"],#high tide time
        low_tides=tide_info["low_tides"],#low tide time
        tide_error=tide_info["error"],#error is scraping does not work
        reviews=reviews,#pass all reviews
        avg_rating=avg_rating,#pass average rating
        review_count=review_count,#pass review count
    )

#https://cloudinary.com/documentation/image_upload_api_reference
@app.route("/l/<slug>/upload", methods=["POST"])
@login_required
def upload_photo(slug):
    #looks up location with slug 
    loc = Location.query.filter_by(slug=slug).first_or_404()
    #checks whether the request uncluded a file named photo
    if 'photo' not in request.files:
        flash("No file selected.", "warning")
        return redirect(url_for("location_detail", slug=slug))
    #gets the uploaded file object
    file = request.files['photo']
    #if browser submits field with no filename no file was chosen
    if file.filename == '':
        flash("No file selected.", "warning")
        return redirect(url_for("location_detail", slug=slug))
    #ensure file is their and its type is allowed
    if file and allowed_file(file.filename):
        try:
            #upload to Cloudinary
            upload_result = cloudinary.uploader.upload(
                file,
                folder="cork_photographers",  #Organize photos in a folder
                resource_type="auto"
            )
            
            #Get the public_id from Cloudinary response
            cloudinary_public_id = upload_result['public_id']
            
            #Get optional caption
            caption = request.form.get("caption", "").strip()
            if len(caption) > 500:
                caption = caption[:500]
            
            #save to database
            photo = Photo(
                location_id=loc.id,
                user_id=current_user.id,
                cloudinary_public_id=cloudinary_public_id,
                original_filename=file.filename,
                caption=caption
            )
            db.session.add(photo)
            db.session.commit()
            
            flash("Photo uploaded successfully!", "success")
        
        except Exception as e:
            print(f"Upload error: {e}")
            flash("Failed to upload photo. Please try again.", "danger")
    else:
        flash("Invalid file type. Please upload a valid image (PNG, JPG, JPEG, GIF, WEBP).", "warning")
    
    return redirect(url_for("location_detail", slug=slug))

#route for deleting phot by id 
@app.route("/photo/<int:photo_id>/delete", methods=["POST"])
@login_required
def delete_photo(photo_id):
    
    photo = Photo.query.get_or_404(photo_id)
    
    #only owner or admin can delete
    if photo.user_id != current_user.id and current_user.role != "admin":
        abort(403)
    #gets the location slug
    slug = photo.location.slug
    
    try:
        # Delete from Cloudinary
        cloudinary.uploader.destroy(photo.cloudinary_public_id)
    except Exception as e:
        print(f"Failed to delete from Cloudinary: {e}")
    
    #delete from database
    db.session.delete(photo)
    db.session.commit()
    
    flash("Photo deleted.", "success")
    return redirect(url_for("location_detail", slug=slug))

#Delete location admin only
@app.route("/l/<slug>/delete", methods=["POST"])
@login_required
def delete_location(slug):
    #only admins can delete locations
    if current_user.role != "admin":
        abort(403)

    loc = Location.query.filter_by(slug=slug).first_or_404()

    #delete all photos from Cloudinary before removing from database
    for photo in loc.photos:
        try:
            cloudinary.uploader.destroy(photo.cloudinary_public_id)
        except Exception as e:
            print(f"Failed to delete photo from Cloudinary: {e}")

    #manually delete trip stops that reference this location
    #these don't have cascade on the Location model so clean them up
    db.session.execute(
        db.text("DELETE FROM trip_stop WHERE location_id = :lid"),
        {"lid": loc.id}
    )

    #manually delete event stops that reference this location
    db.session.execute(
        db.text("DELETE FROM event_stop WHERE location_id = :lid"),
        {"lid": loc.id}
    )

    #delete the location (cascades will remove reviews, photos, visits)
    db.session.delete(loc)
    db.session.commit()

    flash(f"Location '{loc.name}' and all its data has been permanently deleted.", "success")
    return redirect(url_for("home"))

#Edit location notes
@app.route("/l/<slug>/edit-notes", methods=["GET", "POST"])
@login_required
def edit_location_notes(slug):
    #only admins can edit location notes
    if current_user.role != "admin":
        abort(403)

    loc = Location.query.filter_by(slug=slug).first_or_404()

    if request.method == "POST":
        notes = (request.form.get("notes") or "").strip()

        if len(notes) > 400:#match the 400 char limit from the model
            flash("Notes are too long (max 400 characters).", "warning")
            return redirect(url_for("edit_location_notes", slug=slug))

        loc.notes = notes if notes else None#save empty as None
        db.session.commit()

        flash(f"Notes updated for '{loc.name}'.", "success")
        return redirect(url_for("location_detail", slug=slug))

    return render_template("edit_location_notes.html", location=loc)

#Admin Panel https://www.youtube.com/watch?v=NySBh_DIRlg
@app.route("/admin")
@login_required
def admin_dashboard():#admin dashboard with stats and graphs
    if current_user.role != "admin":
        abort(403)

    #count totals for the stats cards
    total_users = User.query.count()
    total_locations = Location.query.count()
    total_reviews = Review.query.count()
    total_photos = Photo.query.count()
    total_visits = Visit.query.count()

    #get user signups per day for the last 30 days
    thirty_days_ago = dt.datetime.utcnow() - dt.timedelta(days=30)

    user_signups = (
        db.session.query(
            db.func.date(User.created_at).label("day"),#group by date
            db.func.count(User.id).label("count")#count users per day
        )
        .filter(User.created_at >= thirty_days_ago)
        .group_by(db.func.date(User.created_at)) #https://stackoverflow.com/questions/1052148/group-by-count-function-in-sqlalchemy
        .order_by(db.func.date(User.created_at).asc())
        .all()
    )

    #get locations created per day for the last 30 days
    #locations don't have created_at so we'll count total locations
    #instead let's get reviews per day as activity metric
    review_activity = (
        db.session.query(
            db.func.date(Review.created_at).label("day"),
            db.func.count(Review.id).label("count")
        )
        .filter(Review.created_at >= thirty_days_ago)
        .group_by(db.func.date(Review.created_at))
        .order_by(db.func.date(Review.created_at).asc())
        .all()
    )

    #get photo uploads per day for the last 30 days
    photo_activity = (
        db.session.query(
            db.func.date(Photo.uploaded_at).label("day"),
            db.func.count(Photo.id).label("count")
        )
        .filter(Photo.uploaded_at >= thirty_days_ago)
        .group_by(db.func.date(Photo.uploaded_at))
        .order_by(db.func.date(Photo.uploaded_at).asc())
        .all()
    )

    #coastal vs inland count
    coastal_count = Location.query.filter_by(is_coastal=True).count()
    inland_count = Location.query.filter_by(is_coastal=False).count()

    #top rated locations (locations with most reviews)
    top_locations = (
        db.session.query(
            Location.name,
            db.func.count(Review.id).label("review_count"),
            db.func.avg(Review.rating).label("avg_rating")
        )
        .join(Review, Review.location_id == Location.id)
        .group_by(Location.id, Location.name)
        .order_by(db.func.count(Review.id).desc())
        .limit(5)
        .all()
    )

    #format chart data as lists for JSON
    signup_labels = [str(row.day) for row in user_signups]
    signup_data = [row.count for row in user_signups]

    review_labels = [str(row.day) for row in review_activity]
    review_data = [row.count for row in review_activity]

    photo_labels = [str(row.day) for row in photo_activity]
    photo_data = [row.count for row in photo_activity]

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_locations=total_locations,
        total_reviews=total_reviews,
        total_photos=total_photos,
        total_visits=total_visits,
        coastal_count=coastal_count,
        inland_count=inland_count,
        top_locations=top_locations,
        signup_labels=signup_labels,
        signup_data=signup_data,
        review_labels=review_labels,
        review_data=review_data,
        photo_labels=photo_labels,
        photo_data=photo_data,
    )

#Admin Panel
@app.route("/admin/users")
@login_required
def admin_users():#admin panel to manage users
    if current_user.role != "admin":
        abort(403)

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<int:user_id>/promote", methods=["POST"])
@login_required
def admin_promote(user_id):#promote a user to admin
    if current_user.role != "admin":
        abort(403)

    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:#can't promote yourself you're already admin
        flash("You're already an admin.", "info")
        return redirect(url_for("admin_users"))

    user.role = "admin"
    db.session.commit()

    flash(f"{user.email} is now an admin.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/demote", methods=["POST"])
@login_required
def admin_demote(user_id):#demote an admin back to a regular user
    if current_user.role != "admin":
        abort(403)

    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:#can't demote yourself prevents locking yourself out
        flash("You can't remove your own admin role.", "warning")
        return redirect(url_for("admin_users"))

    user.role = "user"
    db.session.commit()

    flash(f"{user.email} is no longer an admin.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_delete_user(user_id):#admin can delete a user account
    if current_user.role != "admin":
        abort(403)

    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:#can't delete yourself
        flash("You can't delete your own account.", "warning")
        return redirect(url_for("admin_users"))

    email = user.email#save email for the flash message before deleting

    #delete all their photos from Cloudinary first
    for photo in user.photos:
        try:
            cloudinary.uploader.destroy(photo.cloudinary_public_id)
        except Exception as e:
            print(f"Failed to delete photo from Cloudinary: {e}")

    db.session.delete(user)#cascade will delete reviews, photos, visits
    db.session.commit()

    flash(f"User '{email}' and all their data has been permanently deleted.", "success")
    return redirect(url_for("admin_users"))

#initialize analyzer
photo_analyzer = PhotoAnalyzer()

@app.route("/analyze")
@login_required
def analyze_page():
    
    #get user's previous analyses
    analyses = PhotoAnalysis.query.filter_by(user_id=current_user.id)\
        .order_by(PhotoAnalysis.analyzed_at.desc())\
        .limit(10)\
        .all()
    
    return render_template("analyze.html", analyses=analyses)


@app.route("/analyze/upload", methods=["POST"])
@login_required
def analyze_upload():
    #Handle photo upload for analysis
    if 'photo' not in request.files:
        flash("No file selected.", "warning")
        return redirect(url_for("analyze_page"))
    
    file = request.files['photo']
    
    if file.filename == '':
        flash("No file selected.", "warning")
        return redirect(url_for("analyze_page"))
    
    if file and allowed_file(file.filename):
        #generate unique filename
        original_filename = secure_filename(file.filename)
        extension = original_filename.rsplit('.', 1)[1].lower()
        unique_filename = f"analysis_{current_user.id}_{int(dt.datetime.utcnow().timestamp())}_{uuid.uuid4().hex[:8]}.{extension}"
        
        #save to separate folder
        analysis_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'analyses')
        os.makedirs(analysis_folder, exist_ok=True)
        filepath = os.path.join(analysis_folder, unique_filename)
        file.save(filepath)
        
        #analyze the photo
        analysis_result = photo_analyzer.analyze_photo(filepath)
        
        if analysis_result['success']:
            #save analysis to database
            analysis = PhotoAnalysis(
                user_id=current_user.id,
                filename=unique_filename,
                original_filename=original_filename,
                colors=analysis_result.get('colors'),
                properties={
                    'summary': analysis_result.get('summary')
                }
            )
            db.session.add(analysis)
            db.session.commit()
            
            flash("Photo analyzed successfully!", "success")
            return redirect(url_for("analysis_detail", analysis_id=analysis.id))
        else:
            #analysis failed
            flash(f"Analysis failed: {analysis_result.get('error', 'Unknown error')}", "danger")
            os.remove(filepath)  # Clean up file
            return redirect(url_for("analyze_page"))
    else:
        flash("Invalid file type. Please upload a valid image.", "warning")
        return redirect(url_for("analyze_page"))


@app.route("/analyze/<int:analysis_id>")
@login_required
def analysis_detail(analysis_id):
    #loads analysis row from the db 
    analysis = PhotoAnalysis.query.get_or_404(analysis_id)
    
    #only owner can view
    if analysis.user_id != current_user.id:
        abort(403)
    
    return render_template("analysis_detail.html", analysis=analysis)


@app.route("/analyze/<int:analysis_id>/delete", methods=["POST"])
@login_required
def delete_analysis(analysis_id):
    #gets the analysis
    analysis = PhotoAnalysis.query.get_or_404(analysis_id)
    
    #only owner can delete
    if analysis.user_id != current_user.id:
        abort(403)
    
    #if the file exists try os.remove if not print error
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'analyses', analysis.filename)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            print(f"Failed to delete file: {e}")
    #removes the row from the db
    db.session.delete(analysis)
    db.session.commit()
    
    flash("Analysis deleted.", "success")
    return redirect(url_for("analyze_page"))


@app.route("/auth/register", methods=["GET", "POST"])#route decorator defines endpoint thats acepts get and post requests
def register():
    message = None#intialises message variable to none trailing comma makes this a ruple
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

            sent = send_confirmation_email(user)#send confirmation email
            if sent:
                flash(#tell users to check their email
                    "Account created. Please check your email and confirm your account before logging in.",
                    "success",
                )
            else:
                flash(#tell them email sending didn't work mostly app password issue
                    "Account created, but we could not send a confirmation email. "
                    "Configure SMTP (Gmail app password) and then use 'Resend confirmation'.",
                    "warning",
                )
            
            return redirect(url_for("login"))#send them to login page
    #show registration if their was an error
    return render_template("register.html", message=message)

@app.route("/auth/confirm/<token>")#confirmation page 
def confirm_email(token):#function that handles email confirmation
    email = confirm_email_token(token)#decrypt token and gain email access
    if not email:#if token is invalid or expired
        flash("That confirmation link is invalid or expired. Please request a new one.", "warning")
        return redirect(url_for("resend_confirmation"))#semd them to get a new link

    user = User.query.filter_by(email=email).first()#look up user by email
    if not user:#if their not a user this happens
        flash("Account not found. Please register again.", "warning")
        return redirect(url_for("register"))#tell them to register again and give them link

    if user.is_verified:#if they have confirmed the email address
        flash("Email already confirmed. You can log in.", "info")
        return redirect(url_for("login"))#send them to login

    user.is_verified = True#mark account as verified
    user.verified_at = dt.datetime.utcnow()#record time
    db.session.commit()#save the change
    #tell them to login
    flash("Email confirmed. You can now log in.", "success")
    return redirect(url_for("login"))#redirect to login page

#page for resending confirmation email
@app.route("/auth/resend-confirmation", methods=["GET", "POST"])
def resend_confirmation():#this function handles resending confirmation emails
    message = None#start with no error message

    if request.method == "POST":#if theyre resubmitting the form
        email = (request.form.get("email") or "").strip().lower()#get the email

        if not email:#make sure they enter email
            message = "Please enter your email address."
        else:#once email is in find the email and if they exist but aren't verified send another email
            user = User.query.filter_by(email=email).first()
            if user and not user.is_verified:
                send_confirmation_email(user)

            # standard message incase someone is trying to login to another account
            flash(
                "If an unconfirmed account exists for that email, we've resent the confirmation email.",
                "info",
            )#return them to login
            return redirect(url_for("login"))
    #show resend form
    return render_template("resend_confirmation.html", message=message)

#password reset feature
#https://flask.palletsprojects.com/en/stable/patterns/flashing/
#https://www.freecodecamp.org/news/setup-email-verification-in-flask-app/

#generates a password reset token using the same serializer as email confirmation
def generate_reset_token(email: str) -> str:
    return _confirm_serializer().dumps(email, salt="password-reset-salt")

#validates the password reset token and extracts the email
def confirm_reset_token(token: str) -> str | None:
    try:
        return _confirm_serializer().loads(
            token,
            salt="password-reset-salt",
            max_age=3600,#token expires in 1 hour
        )
    except (SignatureExpired, BadSignature):
        return None

#sends password reset email to user
def send_reset_email(user: User) -> bool:
    token = generate_reset_token(user.email)#create secure token
    reset_url = url_for("reset_password", token=token, _external=True)#build reset link
    subject = "Reset your password - Capture Cork"
    body = (
        f"Hi,\n\n"
        f"You requested a password reset for your Capture Cork account.\n\n"
        f"Click the link below to set a new password:\n"
        f"{reset_url}\n\n"
        f"This link expires in 1 hour.\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )

    if not _mail_is_configured():#fallback if email isn't configured
        print("\n[Email not configured] Password reset link for", user.email)#prints the link to the terminal/ used for local testing
        print(reset_url)
        print()
        return False

    try:#to send email
        import socket#controls timeout
        old_timeout = socket.getdefaulttimeout()#save current timeout
        socket.setdefaulttimeout(10)#sets a ten second timeout so it doesn't hang
        msg = Message(subject=subject, recipients=[user.email], body=body)#create email message object
        mail.send(msg)#send email through flask mail
        socket.setdefaulttimeout(old_timeout)#put the timeout back to what it was before
        return True#email sent succesfully
    except Exception as e:#if anything goes wrong
        print("\n[Email error] Could not send reset email:", str(e))#log error for debugging
        print("Reset link (for debugging):", reset_url)#print link for testing
        print()
    return False

#route for forgot password page where user enters their email
@app.route("/auth/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()

        if not email:
            message = "Please enter your email address."
        else:
            user = User.query.filter_by(email=email).first()
            #only send if user exists and is verified
            if user and user.is_verified:
                send_reset_email(user)

            #always show the same message for security so impersonators don't know if account exists
            flash(
                "If an account exists with that email, we've sent a password reset link.",
                "info",
            )
            return redirect(url_for("login"))

    return render_template("forgot_password.html", message=message)

#route for the actual password reset page where user enters new password
@app.route("/auth/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    email = confirm_reset_token(token)#decrypt token to get email
    if not email:#if token is invalid or expired
        flash("That reset link is invalid or has expired. Please request a new one.", "warning")
        return redirect(url_for("forgot_password"))#send them back to a request fresh link

    user = User.query.filter_by(email=email).first()#look up user by email got from token
    if not user:#if user doesn't exist
        flash("Account not found.", "warning")
        return redirect(url_for("register"))#suggest they register again

    message = None#no error message to start

    if request.method == "POST":#if they submitted the form with their new password
        password = request.form.get("password") or ""#get the new password
        confirm = request.form.get("confirm_password") or ""#get the confirmation password they typed

        if not password:#they left it empty
            message = "Please enter a new password."
        elif len(password) < 6:#password is to short to be secure
            message = "Password must be at least 6 characters."
        elif password != confirm:#th two typed password don't match
            message = "Passwords do not match."
        else:
            user.set_password(password)#hash and save new password
            db.session.commit()#save the change to the database
            flash("Your password has been reset. You can now log in.", "success")
            return redirect(url_for("login"))

    return render_template("reset_password.html", message=message, token=token)

@app.route("/l/<slug>/review", methods=["POST"])#for adding reviews
@login_required#must be logged in
def add_review(slug):#function handles adding reviews
    loc = Location.query.filter_by(slug=slug).first_or_404()#find location or show error
    #get the rating and body
    rating_raw = (request.form.get("rating") or "").strip()
    body = (request.form.get("body") or "").strip()

    # Validate rating ensure its not 6 or 10 somehow or 0
    try:
        rating = int(rating_raw)
    except ValueError:
        rating = 0

    if rating < 1 or rating > 5:#rating must be between be 1 to 5
        flash("Rating must be between 1 and 5 stars.", "warning")
        return redirect(url_for("location_detail", slug=slug))

    if not body:#ensure they write something in review section
        flash("Please write a short review comment.", "warning")
        return redirect(url_for("location_detail", slug=slug))

    if len(body) > 1000:#ensure written review isnt copy paste of something to waste website
        flash("Review is too long (max 1000 characters).", "warning")
        return redirect(url_for("location_detail", slug=slug))
    #create the review
    r = Review(location_id=loc.id, user_id=current_user.id, rating=rating, body=body)
    db.session.add(r)#add it to the database
    db.session.commit()#save it

    flash("Review added.", "success")#tell them it worked
    return redirect(url_for("location_detail", slug=slug))#send back to location page

#Edit review
@app.route("/review/<int:review_id>/edit", methods=["GET", "POST"])
@login_required
def edit_review(review_id):
    review = Review.query.get_or_404(review_id)  # find the review or 404

    # only the person who wrote the review can edit it
    if review.user_id != current_user.id:
        abort(403)  # forbidden if they don't own this review

    if request.method == "POST":
        rating_raw = (request.form.get("rating") or "").strip()
        body = (request.form.get("body") or "").strip()

        # validate rating
        try:
            rating = int(rating_raw)
        except ValueError:
            rating = 0

        if rating < 1 or rating > 5:  # rating must be between 1 and 5
            flash("Rating must be between 1 and 5 stars.", "warning")
            return redirect(url_for("edit_review", review_id=review_id))

        if not body:  #must write something
            flash("Please write a short review comment.", "warning")
            return redirect(url_for("edit_review", review_id=review_id))

        if len(body) > 1000:  #max length check
            flash("Review is too long (max 1000 characters).", "warning")
            return redirect(url_for("edit_review", review_id=review_id))

        #update the review fields
        review.rating = rating
        review.body = body
        db.session.commit()  #save changes

        flash("Review updated.", "success")
        return redirect(url_for("location_detail", slug=review.location.slug))

    #GET request show the edit form
    return render_template("edit_review.html", review=review)


#Delete review admin only
@app.route("/review/<int:review_id>/delete", methods=["POST"])
@login_required
def delete_review(review_id):
    review = Review.query.get_or_404(review_id)  # find the review or 404

    #only admins can delete reviews
    if current_user.role != "admin":
        abort(403)  #forbidden for users

    slug = review.location.slug  #save slug before deleting

    db.session.delete(review)  #remove from database
    db.session.commit()  #save the change

    flash("Review deleted.", "success")
    return redirect(url_for("location_detail", slug=slug))

#Mark location as visited
@app.route("/l/<slug>/visit", methods=["POST"])
@login_required
def add_visit(slug):#handles marking a location as visited
    loc = Location.query.filter_by(slug=slug).first_or_404()

    #check if they've already visited this location
    existing = Visit.query.filter_by(user_id=current_user.id, location_id=loc.id).first()
    if existing:
        flash("You've already marked this location as visited.", "info")
        return redirect(url_for("location_detail", slug=slug))

    #get the date and note from the form
    date_raw = (request.form.get("visited_date") or "").strip()
    note = (request.form.get("note") or "").strip()

    #validate date
    try:
        visited_date = dt.datetime.strptime(date_raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Please enter a valid date.", "warning")
        return redirect(url_for("location_detail", slug=slug))

    #don't allow future dates
    if visited_date > dt.date.today():
        flash("Visit date can't be in the future.", "warning")
        return redirect(url_for("location_detail", slug=slug))

    if len(note) > 1000:#max length check
        flash("Note is too long (max 1000 characters).", "warning")
        return redirect(url_for("location_detail", slug=slug))

    #create the visit
    v = Visit(user_id=current_user.id, location_id=loc.id, visited_date=visited_date, note=note)
    db.session.add(v)
    db.session.commit()

    flash("Location marked as visited!", "success")
    return redirect(url_for("location_detail", slug=slug))


#Edit a visit note
@app.route("/visit/<int:visit_id>/edit", methods=["GET", "POST"])
@login_required
def edit_visit(visit_id):#allows user to update their visit note and date
    visit = Visit.query.get_or_404(visit_id)

    #only the person who made the visit can edit it
    if visit.user_id != current_user.id:
        abort(403)

    if request.method == "POST":#if they submitted the edit form
        date_raw = (request.form.get("visited_date") or "").strip()#get the date they entered and clean it up
        note = (request.form.get("note") or "").strip()#get the note they entered and clean it up

        try:#try to convert the date strign into an actual date object
            visited_date = dt.datetime.strptime(date_raw, "%Y-%m-%d").date()#parse it in year month day
        except ValueError:#if they enter something that isn't a valid date
            flash("Please enter a valid date.", "warning")
            return redirect(url_for("edit_visit", visit_id=visit_id))#send them back to the form

        if visited_date > dt.date.today():#can't say they visited somewhere in the future
            flash("Visit date can't be in the future.", "warning")
            return redirect(url_for("edit_visit", visit_id=visit_id))

        if len(note) > 1000:
            flash("Note is too long (max 1000 characters).", "warning")
            return redirect(url_for("edit_visit", visit_id=visit_id))

        visit.visited_date = visited_date#update the date on the visit record
        visit.note = note#update the note on the visit record
        db.session.commit()#save the changes to the database

        flash("Visit updated.", "success")
        return redirect(url_for("location_detail", slug=visit.location.slug))

    return render_template("edit_visit.html", visit=visit)


#Remove a visit
@app.route("/visit/<int:visit_id>/delete", methods=["POST"])#only accept post since we're deleting something
@login_required
def delete_visit(visit_id):#allows user to unmark a location as visited
    visit = Visit.query.get_or_404(visit_id)#find the visit or show 404 if it doesn't exist

    if visit.user_id != current_user.id:#only person who created it can delete it 
        abort(403)

    slug = visit.location.slug#save the location slug before we delte it so we can redirect back
    db.session.delete(visit)#remove the visit from the database
    db.session.commit()#save the change

    flash("Visit removed.", "success")
    return redirect(url_for("location_detail", slug=slug))


#My Visits page 
@app.route("/my-visits")
@login_required
def my_visits():#shows all locations the current user has marked as visited
    visits = (#query the database for this users visits
        Visit.query.filter_by(user_id=current_user.id)#only get visits belonging to the logged in user
        .order_by(Visit.visited_date.desc())#show most recent visits first
        .all()#get all of them
    )
    return render_template("my_visits.html", visits=visits)

@app.route("/assistant")
@login_required 
def assistant_page():#renders the assistant page
    return render_template("assistant.html")


@app.route("/api/assistant/chat", methods=["POST"])#restful api endpoint only accept posts requests
@login_required  
def assistant_chat():
    #Handle chat message requests from photography assstant
    #user message and convo history to Ollama
    try:
        data = request.get_json()#gets JSON data from POST request body
        user_message = data.get("message", "").strip()#Extract user's message from JSON to empty strin if missing
        chat_history = data.get("history", [])#extract conversation history 
        
        if not user_message:#validate that message is not empty
            return jsonify({"success": False, "error": "Message cannot be empty"}), 400
        
        # Initialize Groq agent
        agent = GroqAgent()
        
        # Build messages list from history + new message
        messages = []
        for msg in chat_history[-10:]:  # Keep last 10 messages for context
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        
        # Add the new user message
        messages.append({"role": "user", "content": user_message})
        
        # Get response from Groq
        result = agent.chat(messages)
        
        if result["success"]:#check if Groq call was succesful
            return jsonify({ #return success response to user
                "success": True, #succesful api call
                "response": result["message"], #the advice it gives
                "model": result.get("model") # which model responded
            })
        else:#call failed
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error occurred")
            }), 500
            
    except Exception as e:#catch any unexpected error messages
        return jsonify({"success": False, "error": str(e)}), 500 #log exception and return to client


@app.route("/api/assistant/status", methods=["GET"]) #get requests only
def assistant_status(): #check if assistant is available and ready, 
    agent = GroqAgent()# initialise agent to check model status
    is_available = agent.is_model_available()# check if agent is installed and return true if it exists
    
    response = {#build response dictionary with status information
        "available": is_available,#boolean is model ready to use
        "model": agent.model,#string of agent
        "api_base": agent.base_url#currently local host
    }
    
    if is_available:#if model is available get details
        info = agent.get_model_info()#return dict with model metadata or none if request fails
        if info:#only add model info to response if data was successfully retrieved
            response["model_info"] = info# add nested dict with model details
    
    return jsonify(response)#return json response if data was succesfully retrieved

#login page
@app.route("/auth/login", methods=["GET", "POST"])
def login():#function that handles users logging in
    message = None#start with no error message

    if request.method == "POST":#if they're submitting login form get email and clean it
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""#get password

        user = User.query.filter_by(email=email).first()#find this user 

        if user and user.check_password(password):#if password and user are correct
            if not user.is_verified:#check to see if their verified
                message = "Please confirm your email before logging in."
            else:#when email is verified and confirmed
                login_user(user)
                nxt = request.args.get("next")#check to see what page they were trying to access
                return redirect(nxt or url_for("home"))
        else:#if password is wrong or user doesn't exist
            message = "Invalid email or password."
    #show login form 
    return render_template("login.html", message=message)


@app.route("/auth/logout")
@login_required#you have to be logged in to logout
def logout():
    logout_user()
    return redirect(url_for("home"))



if __name__ == "__main__":
    # No longer need to create instance folder for PostgreSQL
    # os.makedirs(os.path.join(BASE,"instance"), exist_ok=True)
    
    with app.app_context():
        db.create_all()  # This still works with PostgreSQL
    app.run(debug=os.getenv("FLASK_DEBUG", "False").lower() == "true")