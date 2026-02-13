#datetime used for dates and times
import os, datetime as dt
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
from flask_sqlalchemy import SQLAlchemy # handles sqlite 

from services.sun import get_sun_times#API calls in service folder 
from services.weather import get_weather_hours
from services.groq_agent import GroqAgent

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

# Render provides DATABASE_URL starting with postgres://, but SQLAlchemy needs postgresql://
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url

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
#creates sqlachemy helper in this app.
login_manager = LoginManager(app)#tracks whos logged in
login_manager.login_view = "login"#if user trys to access login only page

mail = Mail(app)#connect email system to the flask app

@app.context_processor
def inject_google_maps_key():#makes it available to all templates, eliminates need for passing the key in every route
    return dict(google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"))#return dictionary of variables to inject into template context

class Location(db.Model): #tabke for photography spots
    id = db.Column(db.Integer, primary_key=True) #locations id primary key 
    name = db.Column(db.String(200), nullable=False, unique=True) #the name of the location
    slug = db.Column(db.String(200), nullable=False, unique=True) #Url version of the name
    lat = db.Column(db.Float, nullable=False) #coordinates for location
    lon = db.Column(db.Float, nullable=False) #coordinates for location
    notes = db.Column(db.String(400)) #fact or notes while creating location can be included 
    reviews = db.relationship(#connects locations to their reviews
        "Review",#reviews come from review table
        backref="location",
        lazy=True,#don't automatically load reviews actual location detail is important
        cascade="all, delete-orphan"#if we delete location delete reviews too
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
    
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)#reviews get unique id number

    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)#location id so system knows
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)#who wrote the review

    rating = db.Column(db.Integer, nullable=False)  # 1 to 5 rating system
    body = db.Column(db.String(1000), nullable=False)# review text

    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)#when was the review written at

from trips import init_trips
app.register_blueprint(init_trips(db, Location))

# Initialize database tables on startup
with app.app_context():
    db.create_all()
    print("✅ Database tables created!")
    
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

def slugify(s: str):
    #makes the link readable, useful for english names
    #lowercase and coverrts and non numeric to hyphens
    s = "".join(ch.lower() if ch.isalnum() else "-" for ch in s).strip("-")
    #collapses duplicate hyphen and reduces length to 200 characters
    return "-".join(filter(None, s.split("-")))[:200]

def _confirm_serializer() -> URLSafeTimedSerializer:#tool used for creating secure tokens
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])#tokens automatically expire

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
        # ADD THESE THREE LINES AT THE TOP OF TRY BLOCK:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(10)  # 10 second timeout for SMTP
        #create the email again
        msg = Message(subject=subject, recipients=[user.email], body=body)
        #send it
        mail.send(msg)
        socket.setdefaulttimeout(old_timeout)  # Restore original timeout
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
    locations = Location.query.order_by(Location.name).all()
    return render_template("home.html", locations=locations)

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

    reviews = (#get all reviews for a location
        Review.query# start a query on the table
        .filter_by(location_id=loc.id)#only reviews for this location
        .order_by(Review.created_at.desc())#sort by newest
        .all()#get them all
    )

    # average rating (None if no reviews)
    avg_rating = (
        db.session.query(func.avg(Review.rating))
        .filter(Review.location_id == loc.id)
        .scalar()
    )#convert to float or leave if 0 reviews
    avg_rating = float(avg_rating) if avg_rating is not None else None
    review_count = len(reviews)#count the number of reviews

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
        
        # Get response from Ollama
        result = agent.chat(messages)
        
        if result["success"]:#check if ollama call was succesful
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