import os
import random
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///chatrooms.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# ── Models ────────────────────────────────────────────────────────────────────

class Room(db.Model):
    __tablename__ = "rooms"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False, unique=True)
    created_by = db.Column(db.String(80),  nullable=False)
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)
    messages   = db.relationship(
        "Message", backref="room", lazy="dynamic",
        cascade="all, delete-orphan"
    )

    @property
    def message_count(self):
        return self.messages.count()

    @property
    def last_activity(self):
        last = self.messages.order_by(Message.posted_at.desc()).first()
        return last.posted_at if last else self.created_at


class Message(db.Model):
    __tablename__ = "messages"
    id        = db.Column(db.Integer, primary_key=True)
    room_id   = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    author    = db.Column(db.String(80), nullable=False)
    content   = db.Column(db.Text,      nullable=False)
    posted_at = db.Column(db.DateTime,  default=datetime.utcnow)


# ── Nickname helper ───────────────────────────────────────────────────────────

ADJECTIVES = [
    "Blue","Red","Green","Silver","Golden","Swift","Bold","Calm",
    "Dark","Bright","Cool","Wild","Lazy","Happy","Fierce","Gentle",
    "Clever","Brave","Quiet","Loud","Fuzzy","Shiny","Speedy","Tiny",
]
ANIMALS = [
    "Fox","Wolf","Bear","Eagle","Hawk","Lion","Tiger","Panda",
    "Otter","Deer","Owl","Raven","Shark","Whale","Lynx","Moose",
    "Bison","Crane","Cobra","Gecko","Falcon","Badger","Ferret","Marmot",
]

def get_nickname():
    if "nickname" not in session:
        adj    = random.choice(ADJECTIVES)
        animal = random.choice(ANIMALS)
        num    = random.randint(10, 99)
        session["nickname"] = f"{adj}{animal}{num}"
    return session["nickname"]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    nickname = get_nickname()
    error = None
    if request.method == "POST":
        name = request.form.get("room_name", "").strip()
        if name:
            existing = Room.query.filter_by(name=name).first()
            if existing:
                return redirect(url_for("room", room_id=existing.id))
            new_room = Room(name=name, created_by=nickname)
            db.session.add(new_room)
            db.session.commit()
            return redirect(url_for("room", room_id=new_room.id))
        error = "Room name cannot be empty."
    rooms = Room.query.order_by(Room.created_at.desc()).all()
    return render_template("index.html", rooms=rooms, nickname=nickname, error=error)


@app.route("/room/<int:room_id>", methods=["GET", "POST"])
def room(room_id):
    r        = Room.query.get_or_404(room_id)
    nickname = get_nickname()
    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if content:
            msg = Message(room_id=room_id, author=nickname, content=content)
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for("room", room_id=room_id))
    messages = r.messages.order_by(Message.posted_at.asc()).limit(50).all()
    return render_template("room.html", room=r, messages=messages, nickname=nickname)


if __name__ == "__main__":
    app.run(debug=True)
