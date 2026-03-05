# events.py
import datetime as dt#imports all flask tools needed
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError#catch database constraint errors

#https://flask-sqlalchemy.readthedocs.io/en/stable/queries/
#https://flask-sqlalchemy.readthedocs.io/en/stable/legacy-query/

def init_events(db, Location):#this function sets up the events feature as a blueprint
    #done to avoid circular imports just like trips
    events_bp = Blueprint("events", __name__)#blueprint mini app within the system

    class Event(db.Model):#defines what an event is
        tablename__ = "event"#name the table event

        id = db.Column(db.Integer, primary_key=True)#unique id number
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)#who created the event

        title = db.Column(db.String(200), nullable=False)#event title
        description = db.Column(db.String(2000))#optional longer description of the event
        event_date = db.Column(db.Date, nullable=False)#when the event takes place
        event_time = db.Column(db.Time, nullable=True)#optional start time for the event

        status = db.Column(db.String(20), nullable=False, default="upcoming")#upcoming or completed

        created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)#when was it created

        creator = db.relationship("User", backref="events", lazy="joined")

        stops = db.relationship(
            "EventStop",
            backref="event",
            cascade="all, delete-orphan",
            order_by="EventStop.position",
            lazy="select",
        )
        #https://docs.python.org/3/library/datetime.html
        #https://www.youtube.com/watch?v=FlaP-j26aX0
        def is_ended(self):#checks if event has ended either manually or by time passing
            if self.status == "completed":#creator marked it as done
                return True
            #auto check: if date has passed its ended
            now = dt.datetime.utcnow()
            if self.event_time:#if they set a specific time check date + time
                event_datetime = dt.datetime.combine(self.event_date, self.event_time)
                return now > event_datetime
            else:#no time set so check if the whole day has passed
                return now.date() > self.event_date

    class EventStop(db.Model):#defines an event location stop
        __tablename__ = "event_stop"#tell sqlalchemy to name it event_stop

        id = db.Column(db.Integer, primary_key=True)#every stop gets unique id
        event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)#which event its part of
        location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)#which location

        position = db.Column(db.Integer, nullable=False)#what order is it in
        created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)

        #connect each stop to location so we can get the data for it
        location = db.relationship(Location, lazy="joined")

        __table_args__ = (
            #prevent the same location being added twice to the same event
            db.UniqueConstraint("event_id", "location_id", name="uq_event_location"),
        )

    #Helper functions

    def _require_creator(event):#ensure current user created the event
        if event.user_id != current_user.id:
            abort(403)#if event does not belong to them show error

    def _normalize_positions(event_id):#helper function to fix the positions if they get messed up
        stops = (
            EventStop.query.filter_by(event_id=event_id)#only stops belonging to this event
            .order_by(EventStop.position.asc(), EventStop.id.asc())#sort by position first then by id as a tiebreaker
            .all()
        )
        changed = False#track whether we actually need to update anything
        for idx, s in enumerate(stops, start=1):#loop through the stops starting from position 1
            if s.position != idx:#if the position number doesn't match where it should be
                s.position = idx#fix it to the correct number
                changed = True#flag that a change was made
        if changed:
            db.session.commit()

    def _next_position(event_id):#find position for new stop
        last = (#find the stop with the highest position number
            EventStop.query.filter_by(event_id=event_id)#only stops in this event
            .order_by(EventStop.position.desc())#sort by position descending so the highest is first
            .first()#just get the one with the highest position
        )
        return (last.position + 1) if last else 1#if there are stops already go one higher, otherwise start at 1

    #Routes

    #List all upcoming events (community page — visible to everyone)
    @events_bp.route("/events", methods=["GET"])
    def events_list():#shows all community events
        today = dt.date.today()
        #upcoming events: date is today or future AND not manually completed
        upcoming = (
            Event.query.filter(Event.event_date >= today, Event.status != "completed")#date is today or later AND not marked complete
            .order_by(Event.event_date.asc())#show the soonest events first
            .all()#get all of them
        )
        #past events: date has passed OR manually completed
        past = (
            Event.query.filter(
                db.or_(Event.event_date < today, Event.status == "completed")#either the date passed or it was completed early
            )
            .order_by(Event.event_date.desc())#show most recent past events first
            .limit(10)#only show the last 10 to keep the page tidy
            .all()#run the query
        )#render the events page with both lists so the template can show them in separate sections
        return render_template("events_list.html", upcoming=upcoming, past=past)

    #Create a new event
    @events_bp.route("/events/create", methods=["GET", "POST"])
    @login_required#must be logged in to create events
    def events_create():#function creates an event
        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            date_raw = (request.form.get("event_date") or "").strip()
            time_raw = (request.form.get("event_time") or "").strip()

            #validate title
            if not title:
                flash("Please give your event a title.", "warning")
                return redirect(url_for("events.events_create"))

            if len(title) > 200:
                flash("Title is too long (max 200 characters).", "warning")
                return redirect(url_for("events.events_create"))

            if len(description) > 2000:
                flash("Description is too long (max 2000 characters).", "warning")
                return redirect(url_for("events.events_create"))

            #validate date
            try:#try to parse the date string into an actual date
                event_date = dt.datetime.strptime(date_raw, "%Y-%m-%d").date()#convert from string to date object
            except ValueError:#if they typed something weird that isn't a date
                flash("Please enter a valid date.", "warning")
                return redirect(url_for("events.events_create"))#back to the form

            #parse optional time
            event_time = None#default to no time
            if time_raw:
                try:
                    event_time = dt.datetime.strptime(time_raw, "%H:%M").time()#convert from string to time object
                except ValueError:#if the time format is wrong
                    flash("Please enter a valid time (HH:MM).", "warning")
                    return redirect(url_for("events.events_create"))

            #create the event
            e = Event(
                user_id=current_user.id,
                title=title,
                description=description,
                event_date=event_date,
                event_time=event_time,
            )
            db.session.add(e)#add it to the database
            db.session.commit()#save it

            flash("Event created! Now add locations.", "success")
            return redirect(url_for("events.event_detail", event_id=e.id))#send them to the event page to add locations

        #GET request shows the create form
        return render_template("event_create.html")

    @events_bp.route("/events/<int:event_id>", methods=["GET"])
    def event_detail(event_id):#shows all details of an event
        event = Event.query.get_or_404(event_id)

        _normalize_positions(event.id)#clean up the stop positions in case any got out of order

        stops = (#get all the location stops for this event in the correct order
            EventStop.query.filter_by(event_id=event.id)#only stops belonging to this event
            .order_by(EventStop.position.asc())#sort them by position so they show up in the right order
            .all()
        )
        locations = Location.query.order_by(Location.name.asc()).all()#get all locations sorted A-Z for the add location dropdown

        return render_template(
            "event_detail.html",
            event=event,
            stops=stops,
            locations=locations,
            today=dt.date.today(),#pass today's date so template can compare
        )

    #Edit event (creator only)
    @events_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
    @login_required
    def event_edit(event_id):#allows creator to edit event details
        event = Event.query.get_or_404(event_id)#find the event or 404 if it doesn't exist
        _require_creator(event)#make sure only the person who created it can edit it

        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            date_raw = (request.form.get("event_date") or "").strip()
            time_raw = (request.form.get("event_time") or "").strip()

            if not title:#they can't leave the title blank
                flash("Please give your event a title.", "warning")
                return redirect(url_for("events.event_edit", event_id=event_id))

            try:#try to parse the new date
                event_date = dt.datetime.strptime(date_raw, "%Y-%m-%d").date()#convert string to date
            except ValueError:#if the date is invalid
                flash("Please enter a valid date.", "warning")#let them know
                return redirect(url_for("events.event_edit", event_id=event_id))#back to the form

            event_time = None#default to no time
            if time_raw:#if they entered a time
                try:#try to parse it
                    event_time = dt.datetime.strptime(time_raw, "%H:%M").time()#convert string to time
                except ValueError:#if the time format is wrong
                    flash("Please enter a valid time.", "warning")
                    return redirect(url_for("events.event_edit", event_id=event_id))

            event.title = title
            event.description = description
            event.event_date = event_date
            event.event_time = event_time
            db.session.commit()

            flash("Event updated.", "success")
            return redirect(url_for("events.event_detail", event_id=event_id))

        return render_template("event_edit.html", event=event)

    #Delete event (creator or admin)
    @events_bp.route("/events/<int:event_id>/delete", methods=["POST"])
    @login_required
    def event_delete(event_id):#deletes an event
        event = Event.query.get_or_404(event_id)

        #only creator or admin can delete
        if event.user_id != current_user.id and current_user.role != "admin":
            abort(403)

        db.session.delete(event)#cascade deletes all stops too
        db.session.commit()

        flash("Event deleted.", "success")
        return redirect(url_for("events.events_list"))
    
        #Mark event as completed
    @events_bp.route("/events/<int:event_id>/complete", methods=["POST"])
    @login_required
    def event_complete(event_id):#allows creator to mark event as completed
        event = Event.query.get_or_404(event_id)
        _require_creator(event)#only the creator can mark it as done

        event.status = "completed"#mark it as completed
        db.session.commit()#save the change

        flash("Event marked as completed.", "success")
        return redirect(url_for("events.event_detail", event_id=event.id))

    #Reopen event (creator only) in case they marked it by accident
    @events_bp.route("/events/<int:event_id>/reopen", methods=["POST"])
    @login_required
    def event_reopen(event_id):#allows creator to reopen a completed event
        event = Event.query.get_or_404(event_id)
        _require_creator(event)#only the creator can reopen it

        event.status = "upcoming"#set it back to upcoming
        db.session.commit()#save the change

        flash("Event reopened.", "success")
        return redirect(url_for("events.event_detail", event_id=event.id))

    #Add a location to an event (creator only)
    @events_bp.route("/events/<int:event_id>/add", methods=["POST"])
    @login_required
    def event_add_location(event_id):#adds a location stop to an event
        event = Event.query.get_or_404(event_id)
        _require_creator(event)

        loc_id_raw = (request.form.get("location_id") or "").strip()#get the location id they selected from the dropdown
        try:
            loc_id = int(loc_id_raw)#parse the string to a number
        except ValueError:#if it's not a valid number they didn't pick a location
            flash("Please select a location.", "warning")#tell them to pick one
            return redirect(url_for("events.event_detail", event_id=event.id))

        loc = Location.query.get(loc_id)#look up the location in the database
        if not loc:#if that location doesn't exist for some reason
            flash("Location not found.", "warning")
            return redirect(url_for("events.event_detail", event_id=event.id))
        #create a new stop linking this event to the chosen location
        stop = EventStop(
            event_id=event.id,#which event this stop belongs to
            location_id=loc.id,#which location it is
            position=_next_position(event.id),#put it at the end of the list using the helper function
        )

        db.session.add(stop)#add the new stop to the database
        try:
            db.session.commit()#write to database
            flash("Location added to event.", "success")#let them know it worked
        except IntegrityError:#if this location is already in the event the unique constraint will catch it
            db.session.rollback()#undo the failed save
            flash("That location is already in this event.", "info")#let them know it's a duplicate

        return redirect(url_for("events.event_detail", event_id=event.id))#back to the event page either way

    # Remove a location from an event (creator only)
    @events_bp.route("/events/<int:event_id>/remove/<int:stop_id>", methods=["POST"])#only POST since we're deleting something
    @login_required
    def event_remove_stop(event_id, stop_id):#removes a location stop
        event = Event.query.get_or_404(event_id)#find the event or show 404
        _require_creator(event)

        stop = EventStop.query.get_or_404(stop_id)#find the stop we want to remove
        if stop.event_id != event.id:#make sure this stop actually belongs to this event
            abort(400)

        db.session.delete(stop)#remove the stop from the database
        db.session.commit()#save the deletion
        _normalize_positions(event.id)#clean up the position numbers so there's no gaps after removing one

        flash("Location removed from event.", "success")
        return redirect(url_for("events.event_detail", event_id=event.id))

    #Move a location up or down (creator only)
    @events_bp.route("/events/<int:event_id>/move/<int:stop_id>", methods=["POST"])
    @login_required
    def event_move_stop(event_id, stop_id):#moves a stop up or down
        direction = (request.form.get("direction") or "").strip().lower()#get whether they clicked up or down

        event = Event.query.get_or_404(event_id)#find the event or 404
        _require_creator(event)

        stop = EventStop.query.get_or_404(stop_id)#find the stop they want to move
        if stop.event_id != event.id:#make sure this stop actually belongs to this event
            abort(400)

        if direction not in {"up", "down"}:#the direction has to be either up or down nothing else
            abort(400)

        _normalize_positions(event.id)#make sure positions are clean before we start swapping

        if direction == "up":#if they want to move it up in the list
            neighbor = EventStop.query.filter_by(event_id=event.id, position=stop.position - 1).first()#find the stop directly above
        else:
            neighbor = EventStop.query.filter_by(event_id=event.id, position=stop.position + 1).first()#find the stop directly below

        if not neighbor:#if there's nothing above or below it's already at the top or bottom
            return redirect(url_for("events.event_detail", event_id=event.id))
        #swap the positions of the two stops,
        stop.position, neighbor.position = neighbor.position, stop.position
        db.session.commit()

        return redirect(url_for("events.event_detail", event_id=event.id))

    #attach model classes to blueprint for debugging
    events_bp.Event = Event
    events_bp.EventStop = EventStop

    return events_bp