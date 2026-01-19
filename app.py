import os, datetime as dt

BASE = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except Exception:
    pass

from flask import Flask, render_template, request, redirect, url_for, abort, flash #flask object, render template renders jinja template/ html pages,
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
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from services.tide import get_cork_tides 

from sqlalchemy.sql import func

def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}

BASE = os.path.dirname(os.path.abspath(__file__))
#creates flask app, template and static folder called 
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE, "instance", "fyp_database.db")
#stores sqlite folder in instance folder
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"] = _env_bool("MAIL_USE_TLS", True)
app.config["MAIL_USE_SSL"] = _env_bool("MAIL_USE_SSL", False)
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER") or app.config.get("MAIL_USERNAME")

app.config["EMAIL_CONFIRM_SALT"] = os.getenv("EMAIL_CONFIRM_SALT", "email-confirm-salt")
app.config["EMAIL_CONFIRM_MAX_AGE_SECONDS"] = int(os.getenv("EMAIL_CONFIRM_MAX_AGE_SECONDS", "3600"))

app.config["PREFERRED_URL_SCHEME"] = os.getenv("PREFERRED_URL_SCHEME", "http")

#secret key is used for session management
db = SQLAlchemy(app)
#creates sqlachemy helper in this app.
login_manager = LoginManager(app)
login_manager.login_view = "login"

mail = Mail(app)

class Location(db.Model): #tabke for photography spots
    id = db.Column(db.Integer, primary_key=True) #locations id primary key 
    name = db.Column(db.String(200), nullable=False, unique=True) #the name of the location
    slug = db.Column(db.String(200), nullable=False, unique=True) #Url version of the name
    lat = db.Column(db.Float, nullable=False) #coordinates for location
    lon = db.Column(db.Float, nullable=False) #coordinates for location
    notes = db.Column(db.String(400)) #fact or notes while creating location can be included 
    reviews = db.relationship(
        "Review",
        backref="location",
        lazy=True,
        cascade="all, delete-orphan"
    )

class User(UserMixin, db.Model):#creates sqlalchemy model for users, usermixin helps flask manager login users
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False) #where hashed password is stored
    role = db.Column(db.String(20), nullable=False, default="user") # user roles admin or normal users
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)# timestap for row being created

    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    verified_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, pw: str):#hashes password and stores it in password hash
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:# validates if entered password is correct
        return check_password_hash(self.password_hash, pw)
    
    reviews = db.relationship(
        "Review",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )
    
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    rating = db.Column(db.Integer, nullable=False)  # 1..5
    body = db.Column(db.String(1000), nullable=False)

    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)
    
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

def _confirm_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])


def generate_confirmation_token(email: str) -> str:
    return _confirm_serializer().dumps(email, salt=app.config["EMAIL_CONFIRM_SALT"])


def confirm_email_token(token: str) -> str | None:
    try:
        return _confirm_serializer().loads(
            token,
            salt=app.config["EMAIL_CONFIRM_SALT"],
            max_age=app.config["EMAIL_CONFIRM_MAX_AGE_SECONDS"],
        )
    except (SignatureExpired, BadSignature):
        return None


def _mail_is_configured() -> bool:
    return bool(
        app.config.get("MAIL_SERVER")
        and app.config.get("MAIL_PORT")
        and app.config.get("MAIL_USERNAME")
        and app.config.get("MAIL_PASSWORD")
        and app.config.get("MAIL_DEFAULT_SENDER")
    )


def send_confirmation_email(user: User) -> bool:
    """Send a confirmation email. Returns True if sent successfully."""

    token = generate_confirmation_token(user.email)
    confirm_url = url_for("confirm_email", token=token, _external=True)

    subject = "Confirm your email - Cork Photographers"
    body = (
        "Thanks for signing up to Cork Photographers.\n\n"
        "Please confirm your email by clicking the link below:\n"
        f"{confirm_url}\n\n"
        "This link expires in 1 hour."
    )

    # If email is not configured, print the link to the terminal (useful for development)
    if not _mail_is_configured():
        print("\n[Email not configured] Confirmation link for", user.email)
        print(confirm_url)
        print()
        return False

    try:
        msg = Message(subject=subject, recipients=[user.email], body=body)
        mail.send(msg)
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
@admin_required
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

    reviews = (
        Review.query
        .filter_by(location_id=loc.id)
        .order_by(Review.created_at.desc())
        .all()
    )

    # average rating (None if no reviews)
    avg_rating = (
        db.session.query(func.avg(Review.rating))
        .filter(Review.location_id == loc.id)
        .scalar()
    )
    avg_rating = float(avg_rating) if avg_rating is not None else None
    review_count = len(reviews)

    return render_template( #renders the template and we give what data it requires
        "location.html",
        location=loc,
        sun=sun,
        weather=weather,
        high_tides=tide_info["high_tides"],
        low_tides=tide_info["low_tides"],
        tide_error=tide_info["error"],
        reviews=reviews,
        avg_rating=avg_rating,
        review_count=review_count,
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

            sent = send_confirmation_email(user)
            if sent:
                flash(
                    "Account created. Please check your email and confirm your account before logging in.",
                    "success",
                )
            else:
                flash(
                    "Account created, but we could not send a confirmation email. "
                    "Configure SMTP (Gmail app password) and then use 'Resend confirmation'.",
                    "warning",
                )

            return redirect(url_for("login"))

    return render_template("register.html", message=message)

@app.route("/auth/confirm/<token>")
def confirm_email(token):
    email = confirm_email_token(token)
    if not email:
        flash("That confirmation link is invalid or expired. Please request a new one.", "warning")
        return redirect(url_for("resend_confirmation"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Account not found. Please register again.", "warning")
        return redirect(url_for("register"))

    if user.is_verified:
        flash("Email already confirmed. You can log in.", "info")
        return redirect(url_for("login"))

    user.is_verified = True
    user.verified_at = dt.datetime.utcnow()
    db.session.commit()

    flash("Email confirmed. You can now log in.", "success")
    return redirect(url_for("login"))


@app.route("/auth/resend-confirmation", methods=["GET", "POST"])
def resend_confirmation():
    message = None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()

        if not email:
            message = "Please enter your email address."
        else:
            user = User.query.filter_by(email=email).first()
            if user and not user.is_verified:
                send_confirmation_email(user)

            # Always show a generic message to avoid revealing whether an email exists.
            flash(
                "If an unconfirmed account exists for that email, we've resent the confirmation email.",
                "info",
            )
            return redirect(url_for("login"))

    return render_template("resend_confirmation.html", message=message)

@app.route("/l/<slug>/review", methods=["POST"])
@login_required
def add_review(slug):
    loc = Location.query.filter_by(slug=slug).first_or_404()

    rating_raw = (request.form.get("rating") or "").strip()
    body = (request.form.get("body") or "").strip()

    # Validate rating
    try:
        rating = int(rating_raw)
    except ValueError:
        rating = 0

    if rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5 stars.", "warning")
        return redirect(url_for("location_detail", slug=slug))

    if not body:
        flash("Please write a short review comment.", "warning")
        return redirect(url_for("location_detail", slug=slug))

    if len(body) > 1000:
        flash("Review is too long (max 1000 characters).", "warning")
        return redirect(url_for("location_detail", slug=slug))

    r = Review(location_id=loc.id, user_id=current_user.id, rating=rating, body=body)
    db.session.add(r)
    db.session.commit()

    flash("Review added.", "success")
    return redirect(url_for("location_detail", slug=slug))


@app.route("/auth/login", methods=["GET", "POST"])
def login():
    message = None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.is_verified:
                message = "Please confirm your email before logging in."
            else:
                login_user(user)
                nxt = request.args.get("next")
                return redirect(nxt or url_for("home"))
        else:
            message = "Invalid email or password."

    return render_template("login.html", message=message)


@app.route("/auth/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))



if __name__ == "__main__":
    os.makedirs(os.path.join(BASE,"instance"), exist_ok=True)# ensures instance folders exists so SQLite can create the db
    with app.app_context():#create tabeles if none exist
        db.create_all()
    app.run(debug=True)#runs the dev server on device
