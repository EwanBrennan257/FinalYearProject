# trips.py
import datetime as dt
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError


def init_trips(db, Location):
    """
    Trips feature implemented as a Blueprint.

    Usage in app.py (after Location is defined):
        from trips import init_trips
        app.register_blueprint(init_trips(db, Location))

    This avoids importing app.py inside this module (prevents circular imports).
    """

    trips_bp = Blueprint("trips", __name__)

    class Trip(db.Model):
        __tablename__ = "trip"

        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

        name = db.Column(db.String(120), nullable=False, default="My trip")
        created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)

        stops = db.relationship(
            "TripStop",
            backref="trip",
            cascade="all, delete-orphan",
            order_by="TripStop.position",
            lazy="select",
        )

    class TripStop(db.Model):
        __tablename__ = "trip_stop"

        id = db.Column(db.Integer, primary_key=True)
        trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
        location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)

        # 1..n within a trip
        position = db.Column(db.Integer, nullable=False)

        created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)

        # Relationship to Location so templates can do stop.location.name, stop.location.slug, etc.
        location = db.relationship(Location, lazy="joined")

        __table_args__ = (
            # Prevent the same location being added twice to the same trip
            db.UniqueConstraint("trip_id", "location_id", name="uq_trip_location"),
        )

    def _require_owner(trip: Trip):
        if trip.user_id != current_user.id:
            abort(403)

    def _normalize_positions(trip_id: int):
        """Ensure positions are 1..n with no gaps."""
        stops = (
            TripStop.query.filter_by(trip_id=trip_id)
            .order_by(TripStop.position.asc(), TripStop.id.asc())
            .all()
        )
        changed = False
        for idx, s in enumerate(stops, start=1):
            if s.position != idx:
                s.position = idx
                changed = True
        if changed:
            db.session.commit()

    def _next_position(trip_id: int) -> int:
        last = (
            TripStop.query.filter_by(trip_id=trip_id)
            .order_by(TripStop.position.desc())
            .first()
        )
        return (last.position + 1) if last else 1

    @trips_bp.route("/trips", methods=["GET"])
    @login_required
    def trips_list():
        trips = (
            Trip.query.filter_by(user_id=current_user.id)
            .order_by(Trip.created_at.desc())
            .all()
        )
        return render_template("trips_list.html", trips=trips)

    @trips_bp.route("/trips/create", methods=["POST"])
    @login_required
    def trips_create():
        name = (request.form.get("name") or "").strip()
        if not name:
            name = "My trip"

        t = Trip(user_id=current_user.id, name=name)
        db.session.add(t)
        db.session.commit()

        flash("Trip created.", "success")
        return redirect(url_for("trips.trip_detail", trip_id=t.id))

    @trips_bp.route("/trips/<int:trip_id>", methods=["GET"])
    @login_required
    def trip_detail(trip_id: int):
        trip = Trip.query.get_or_404(trip_id)
        _require_owner(trip)

        _normalize_positions(trip.id)

        stops = (
            TripStop.query.filter_by(trip_id=trip.id)
            .order_by(TripStop.position.asc())
            .all()
        )

        locations = Location.query.order_by(Location.name.asc()).all()

        return render_template(
            "trip_detail.html",
            trip=trip,
            stops=stops,
            locations=locations,
        )

    @trips_bp.route("/trips/<int:trip_id>/add", methods=["POST"])
    @login_required
    def trip_add_location(trip_id: int):
        trip = Trip.query.get_or_404(trip_id)
        _require_owner(trip)

        loc_id_raw = (request.form.get("location_id") or "").strip()
        try:
            loc_id = int(loc_id_raw)
        except ValueError:
            flash("Please select a location.", "warning")
            return redirect(url_for("trips.trip_detail", trip_id=trip.id))

        loc = Location.query.get(loc_id)
        if not loc:
            flash("Location not found.", "warning")
            return redirect(url_for("trips.trip_detail", trip_id=trip.id))

        stop = TripStop(
            trip_id=trip.id,
            location_id=loc.id,
            position=_next_position(trip.id),
        )

        db.session.add(stop)
        try:
            db.session.commit()
            flash("Location added to trip.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("That location is already in this trip.", "info")

        return redirect(url_for("trips.trip_detail", trip_id=trip.id))

    @trips_bp.route("/trips/<int:trip_id>/remove/<int:stop_id>", methods=["POST"])
    @login_required
    def trip_remove_stop(trip_id: int, stop_id: int):
        trip = Trip.query.get_or_404(trip_id)
        _require_owner(trip)

        stop = TripStop.query.get_or_404(stop_id)
        if stop.trip_id != trip.id:
            abort(400)

        db.session.delete(stop)
        db.session.commit()
        _normalize_positions(trip.id)

        flash("Removed from trip.", "success")
        return redirect(url_for("trips.trip_detail", trip_id=trip.id))

    @trips_bp.route("/trips/<int:trip_id>/move/<int:stop_id>", methods=["POST"])
    @login_required
    def trip_move_stop(trip_id: int, stop_id: int):
        direction = (request.form.get("direction") or "").strip().lower()

        trip = Trip.query.get_or_404(trip_id)
        _require_owner(trip)

        stop = TripStop.query.get_or_404(stop_id)
        if stop.trip_id != trip.id:
            abort(400)

        if direction not in {"up", "down"}:
            abort(400)

        _normalize_positions(trip.id)

        if direction == "up":
            neighbor = TripStop.query.filter_by(trip_id=trip.id, position=stop.position - 1).first()
        else:
            neighbor = TripStop.query.filter_by(trip_id=trip.id, position=stop.position + 1).first()

        if not neighbor:
            return redirect(url_for("trips.trip_detail", trip_id=trip.id))

        stop.position, neighbor.position = neighbor.position, stop.position
        db.session.commit()

        return redirect(url_for("trips.trip_detail", trip_id=trip.id))

    # Optional: expose models on the blueprint for debugging (not required)
    trips_bp.Trip = Trip
    trips_bp.TripStop = TripStop

    return trips_bp
