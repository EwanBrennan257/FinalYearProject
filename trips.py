# trips.py
import datetime as dt#imports all flask tools needed
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError#import this to catch database constraint errors(adding same location twice)


def init_trips(db, Location):#this function sets up the trip feature as a blueprint
    #this is done to avoid circular imports
    trips_bp = Blueprint("trips", __name__)#blueprint mini app within the system

    class Trip(db.Model):#defines what a trip is
        __tablename__ = "trip"#name the table trip

        id = db.Column(db.Integer, primary_key=True)#unique id number
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)#who owns the trip

        name = db.Column(db.String(120), nullable=False, default="My trip")#trips name
        created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)#when was it created 

        stops = db.relationship(#one trip has multiple stops
            "TripStop",#this comes from the tripstop table
            backref="trip",
            cascade="all, delete-orphan",#if we delete trip delete all stops
            order_by="TripStop.position",#load stops in order
            lazy="select",#load stops not neseccary if system is struggling
        )

    class TripStop(db.Model):#define a tripstop
        __tablename__ = "trip_stop"#tell sqlalchemy to name it trip stop

        id = db.Column(db.Integer, primary_key=True)#every stop gets unique id
        trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)#id for which trip its on
        location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)#which location is it

        #what number is it in the trips 
        position = db.Column(db.Integer, nullable=False)
        #when was it created
        created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)

        #connect each stop to location so we can get the data for it
        location = db.relationship(Location, lazy="joined")

        __table_args__ = (
            #prevent the same location being added twice to the same trip
            db.UniqueConstraint("trip_id", "location_id", name="uq_trip_location"),
        )

    def _require_owner(trip: Trip):#ensure current user owns the trip
        if trip.user_id != current_user.id:
            abort(403)#if trip does not belong to them show error

    def _normalize_positions(trip_id: int):#helper function to fix the positions if they get messed up
        #positions are numbered 1,2,3,4
        stops = (#get all stops for trip sorted by position
            TripStop.query.filter_by(trip_id=trip_id)
            .order_by(TripStop.position.asc(), TripStop.id.asc())
            .all()
        )
        changed = False#flag if changes were made
        for idx, s in enumerate(stops, start=1):#assign position to stop
            if s.position != idx:
                s.position = idx
                changed = True#if stop doesn't match position change it and fix it
        if changed:
            db.session.commit()#commit the change 

    def _next_position(trip_id: int) -> int:#function use to find position for new stop
        last = (#find stop with highest number
            TripStop.query.filter_by(trip_id=trip_id)
            .order_by(TripStop.position.desc())
            .first()
        )#last stop return position +1
        return (last.position + 1) if last else 1

    @trips_bp.route("/trips", methods=["GET"])#show all users trips
    @login_required#must be logged in to show trups
    def trips_list():#function with the trip list
        trips = (#get all trips belonging to the user
            Trip.query.filter_by(user_id=current_user.id)
            .order_by(Trip.created_at.desc())
            .all()
        )#show trips list page
        return render_template("trips_list.html", trips=trips)
    #route to create new trip
    @trips_bp.route("/trips/create", methods=["POST"])
    @login_required#must be logged in
    def trips_create():#function creates a trip
        name = (request.form.get("name") or "").strip()
        if not name:#incase they don't give a name
            name = "My trip"

        t = Trip(user_id=current_user.id, name=name)#create the trip
        db.session.add(t)#add it to the database
        db.session.commit()#save it

        flash("Trip created.", "success")#show it worked
        return redirect(url_for("trips.trip_detail", trip_id=t.id))#send them to its page
    #show details of a specfic trip
    @trips_bp.route("/trips/<int:trip_id>", methods=["GET"])
    @login_required#must be logged in
    def trip_detail(trip_id: int):#shows all details of a trip
        trip = Trip.query.get_or_404(trip_id)#find trip or show error
        _require_owner(trip)#make sure trip belongs to user

        _normalize_positions(trip.id)#clean position nymbers

        stops = (#get all stops in the trip
            TripStop.query.filter_by(trip_id=trip.id)
            .order_by(TripStop.position.asc())
            .all()
        )
        #get all the locations available
        locations = Location.query.order_by(Location.name.asc()).all()
        #show the trip detail page with the data
        return render_template(
            "trip_detail.html",
            trip=trip,
            stops=stops,
            locations=locations,
        )
    #add location to the trip
    @trips_bp.route("/trips/<int:trip_id>/add", methods=["POST"])
    @login_required
    def trip_add_location(trip_id: int):#function adds location to a trip
        trip = Trip.query.get_or_404(trip_id)#find trip or show 404
        _require_owner(trip)#make sure logged in user owns the trip
        #get location id from the form
        loc_id_raw = (request.form.get("location_id") or "").strip()
        try:#try to conver it to a number
            loc_id = int(loc_id_raw)
        except ValueError:#if not an accepted number tell them to pock again or send back
            flash("Please select a location.", "warning")
            return redirect(url_for("trips.trip_detail", trip_id=trip.id))
        #look up location in database
        loc = Location.query.get(loc_id)
        if not loc:#if it doesn't exist tell them it wasn't found and return them
            flash("Location not found.", "warning")
            return redirect(url_for("trips.trip_detail", trip_id=trip.id))

        stop = TripStop(#create a new stio for a trip
            trip_id=trip.id,
            location_id=loc.id,
            position=_next_position(trip.id),#figure out the position of this stop
        )

        db.session.add(stop)#adds stop to the database
        try:#try to save it
            db.session.commit()#save it
            flash("Location added to trip.", "success")
        except IntegrityError:#if theirs and error
            db.session.rollback()#undo the add
            flash("That location is already in this trip.", "info")
        #send them back to the trip detail page
        return redirect(url_for("trips.trip_detail", trip_id=trip.id))
    #removing stop from a trip
    @trips_bp.route("/trips/<int:trip_id>/remove/<int:stop_id>", methods=["POST"])
    @login_required
    def trip_remove_stop(trip_id: int, stop_id: int):#function to remove the stop
        trip = Trip.query.get_or_404(trip_id)#find the trip 
        _require_owner(trip)#you must be the owner

        stop = TripStop.query.get_or_404(stop_id)#find trip
        if stop.trip_id != trip.id:#make sure stop belongs to trip
            abort(400)

        db.session.delete(stop)#delete stop from database
        db.session.commit()#commit the change
        _normalize_positions(trip.id)#fix positioning 

        flash("Removed from trip.", "success")#show it worked
        return redirect(url_for("trips.trip_detail", trip_id=trip.id))#return them to the trip
    #how to move a stop up or down
    @trips_bp.route("/trips/<int:trip_id>/move/<int:stop_id>", methods=["POST"])
    @login_required
    def trip_move_stop(trip_id: int, stop_id: int):#function for moving the stop up or down
        direction = (request.form.get("direction") or "").strip().lower()#is it moving up or down get info from the form

        trip = Trip.query.get_or_404(trip_id)#find the trip 
        _require_owner(trip)

        stop = TripStop.query.get_or_404(stop_id)#find the stop to be moved
        if stop.trip_id != trip.id:
            abort(400)

        if direction not in {"up", "down"}:#stop can only be moved up or down
            abort(400)

        _normalize_positions(trip.id)#fix the position numbers

        if direction == "up":#find neighbour to swap move up means one above goes down one and this goes up 1
            neighbor = TripStop.query.filter_by(trip_id=trip.id, position=stop.position - 1).first()
        else:#move down means swapping with one below
            neighbor = TripStop.query.filter_by(trip_id=trip.id, position=stop.position + 1).first()

        if not neighbor:#if theirs no one dont swap
            return redirect(url_for("trips.trip_detail", trip_id=trip.id))
        #this stop goes to neigbours position and neighbours goes to its
        stop.position, neighbor.position = neighbor.position, stop.position
        db.session.commit()#save the change
        #send back to trip detail page
        return redirect(url_for("trips.trip_detail", trip_id=trip.id))
    #attach model classes to blueprint used when im debugging or with errors
    trips_bp.Trip = Trip
    trips_bp.TripStop = TripStop

    # Generate a random trip flask route
    @trips_bp.route("/trips/random", methods=["POST"])#url endpoint
    @login_required
    def trips_create_random():#creates a trip with randomly selected locations
        #uses python random.sample for non replacement random selection
        import random#import random module for random selection algorithim
        
        # Get how many locations the user wants (default 3)
        try:
            num_locations = int(request.form.get("num_locations", 3))#extract num locations from html form
            #convert string to integer
            # Limit between 2 and 8 locations
            num_locations = max(2, min(8, num_locations))
        except ValueError:#handles case where user input isn't a valid number
            num_locations = 3#fallback
        
        # Get all available locations from database
        all_locations = Location.query.all()
        
        # Check if we have enough locations
        if len(all_locations) < 2:
            flash("Not enough locations available for a random trip. Please add more locations first.", "warning")
            return redirect(url_for("trips.trips_list"))
        
        # Randomly select locations 
        num_to_pick = min(num_locations, len(all_locations))
        #ensures no duplicates locations in the same trip
        #returns a list of randoml selected location objects
        selected_locations = random.sample(all_locations, num_to_pick)
        
        # Generate a fun random trip name
        trip_names = [
            "Random Adventure",
            "Mystery Tour",
            "Cork Discovery"
        ]
        trip_name = random.choice(trip_names)#pick one from the list
        
        # Create the trip
        trip = Trip(user_id=current_user.id, name=trip_name)#creates new row trip
        #add trip to database session
        db.session.add(trip)
        #flsuh writes the trip to the database and generates trip.id
        db.session.flush()  # Get the trip ID without committing yet
        
        # Add the random locations as stops, link trips to the location
        for position, location in enumerate(selected_locations, start=1):
            stop = TripStop(
                trip_id=trip.id, #foregin key which trip this stop belongs to
                location_id=location.id, # foreign key which locations to visit
                position=position # sequential order which stop in what order
            )
            db.session.add(stop)
        
        # Commit all changes
        db.session.commit()
        #show success message
        flash(f"Random trip '{trip_name}' created with {num_to_pick} locations!", "success")
        return redirect(url_for("trips.trip_detail", trip_id=trip.id))

    return trips_bp  # This should be at the very end

    return trips_bp
